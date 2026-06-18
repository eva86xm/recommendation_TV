import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime, time
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "signage.db"
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "webm", "mov"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}
MAX_VIDEO_WIDTH = int(os.getenv("MAX_VIDEO_WIDTH", "2560"))
MAX_VIDEO_HEIGHT = int(os.getenv("MAX_VIDEO_HEIGHT", "1440"))
READY_STATUS = "ready"
PROCESSING_STATUS = "processing"
ERROR_STATUS = "error"


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "20480")) * 1024 * 1024
    app.jinja_env.filters["datetime_ru"] = format_datetime_ru
    app.jinja_env.filters["filesize"] = format_file_size
    app.jinja_env.filters["kind_label"] = media_kind_label
    app.jinja_env.filters["status_label"] = media_status_label

    BASE_DIR.joinpath("instance").mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    init_db()

    @app.get("/")
    def index():
        if not is_logged_in():
            return redirect(url_for("login"))
        with db() as conn:
            media = conn.execute("SELECT * FROM media ORDER BY created_at DESC").fetchall()
            schedule = conn.execute(
                """
                SELECT s.*, m.original_name, m.kind, sc.name AS screen_name
                FROM schedule_items s
                JOIN media m ON m.id = s.media_id
                LEFT JOIN screens sc ON sc.id = s.screen_id
                ORDER BY s.sort_order ASC, s.id DESC
                """
            ).fetchall()
            screens = conn.execute("SELECT * FROM screens ORDER BY name").fetchall()
        return render_template("index.html", media=media, schedule=schedule, screens=screens)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            expected = os.getenv("ADMIN_PASSWORD", "admin123")
            if request.form.get("password") == expected:
                session["admin"] = True
                return redirect(url_for("index"))
            flash("Неверный пароль")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.post("/media")
    def upload_media():
        require_login()
        next_url = request.form.get("next") or url_for("index")
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Выберите файл")
            return redirect(next_url)

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash("Поддерживаются картинки и видео: jpg, png, webp, gif, mp4, webm, mov")
            return redirect(next_url)

        original_name = display_filename(file.filename)
        kind = media_kind(ext)
        stored_name = make_stored_name("mp4" if kind == "video" else ext)
        stored_path = UPLOAD_DIR / stored_name
        source_name = None
        status = READY_STATUS
        file_size = 0

        if kind == "image":
            file.save(stored_path)
            file_size = stored_path.stat().st_size
        else:
            source_name = f"{stored_path.stem}_source.{ext}"
            source_path = UPLOAD_DIR / source_name
            file.save(source_path)
            file_size = source_path.stat().st_size
            status = PROCESSING_STATUS

        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO media
                    (original_name, stored_name, source_name, kind, status, file_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (original_name, stored_name, source_name, kind, status, file_size, utc_now_iso()),
            )
            media_id = cursor.lastrowid

        if kind == "video":
            start_video_processing(media_id, source_name, stored_name)
            flash("Видео загружено и обрабатывается")
        else:
            flash("Файл загружен")
        return redirect(next_url)

    @app.post("/media/scan")
    def scan_media_folder():
        require_login()
        next_url = request.form.get("next") or url_for("index")
        result = import_media_from_uploads()

        if result["added"] == 0:
            flash("Новых файлов для загрузки из папки uploads не найдено")
        else:
            flash(
                f"Загружено из папки uploads: {result['added']}. "
                f"Видео в обработке: {result['processing']}. "
                f"Пропущено: {result['skipped']}."
            )
        return redirect(next_url)

    @app.get("/media/<int:media_id>")
    def media_detail(media_id):
        require_login()
        item = find_media(media_id)
        if not item:
            abort(404)
        return render_template("media.html", item=item)

    @app.post("/media/<int:media_id>/delete")
    def delete_media(media_id):
        require_login()
        next_url = request.form.get("next") or url_for("index")
        item = find_media(media_id)
        if not item:
            abort(404)

        with db() as conn:
            conn.execute("DELETE FROM schedule_items WHERE media_id = ?", (media_id,))
            conn.execute("DELETE FROM media WHERE id = ?", (media_id,))

        delete_media_files(item)

        flash("Файл удален")
        return redirect(next_url)

    @app.post("/schedule")
    def add_schedule_item():
        require_login()
        form = request.form
        media_id = int(form["media_id"])
        screen_id = int(form["screen_id"])
        screen = find_screen_by_id(screen_id)
        media_item = find_media(media_id)
        if not screen or not media_item:
            abort(404)
        if media_item["status"] != READY_STATUS:
            flash("Этот файл еще обрабатывается")
            return redirect(url_for("screen_detail", screen_key=screen["screen_key"]))

        duration_seconds = schedule_duration(form, media_item)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO schedule_items
                    (screen_id, media_id, title, duration_seconds, start_date, end_date, start_time, end_time, weekdays, sort_order, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    screen_id,
                    media_id,
                    form.get("title", "").strip(),
                    duration_seconds,
                    form.get("start_date") or None,
                    form.get("end_date") or None,
                    form.get("start_time") or None,
                    form.get("end_time") or None,
                    ",".join(form.getlist("weekdays")) or None,
                    int(form.get("sort_order") or 100),
                    1 if form.get("active") == "on" else 0,
                ),
            )
        flash("Показ добавлен в расписание")
        if screen:
            return redirect(url_for("screen_detail", screen_key=screen["screen_key"]))
        return redirect(url_for("index"))

    @app.post("/schedule/<int:item_id>/delete")
    def delete_schedule_item(item_id):
        require_login()
        screen_key = None
        with db() as conn:
            row = conn.execute(
                """
                SELECT sc.screen_key
                FROM schedule_items s
                LEFT JOIN screens sc ON sc.id = s.screen_id
                WHERE s.id = ?
                """,
                (item_id,),
            ).fetchone()
            if row:
                screen_key = row["screen_key"]
            conn.execute("DELETE FROM schedule_items WHERE id = ?", (item_id,))
        flash("Пункт расписания удален")
        if screen_key:
            return redirect(url_for("screen_detail", screen_key=screen_key))
        return redirect(url_for("index"))

    @app.post("/screens")
    def add_screen():
        require_login()
        name = request.form.get("name", "").strip()
        if not name:
            flash("Укажите название экрана")
            return redirect(url_for("index"))
        with db() as conn:
            key = generate_screen_key(conn)
            conn.execute("INSERT INTO screens (name, screen_key, created_at) VALUES (?, ?, ?)", (name, key, utc_now_iso()))
        flash("Экран добавлен")
        return redirect(url_for("index"))

    @app.post("/screens/<screen_key>/delete")
    def delete_screen(screen_key):
        require_login()
        screen = find_screen(screen_key)
        if not screen:
            abort(404)

        with db() as conn:
            screen_count = conn.execute("SELECT COUNT(*) AS count FROM screens").fetchone()["count"]
            if screen_count <= 1:
                flash("Нельзя удалить последний экран")
                return redirect(url_for("index"))

            conn.execute("DELETE FROM schedule_items WHERE screen_id = ?", (screen["id"],))
            conn.execute("DELETE FROM screens WHERE id = ?", (screen["id"],))

        flash("Экран удален")
        return redirect(url_for("index"))

    @app.get("/screens/<screen_key>")
    def screen_detail(screen_key):
        require_login()
        screen = find_screen(screen_key)
        if not screen:
            abort(404)
        with db() as conn:
            media = conn.execute("SELECT * FROM media ORDER BY created_at DESC").fetchall()
            ready_media = conn.execute(
                "SELECT * FROM media WHERE status = ? ORDER BY created_at DESC",
                (READY_STATUS,),
            ).fetchall()
            schedule = conn.execute(
                """
                SELECT s.*, m.original_name, m.kind, m.status
                FROM schedule_items s
                JOIN media m ON m.id = s.media_id
                WHERE s.screen_id = ?
                ORDER BY s.sort_order ASC, s.id DESC
                """,
                (screen["id"],),
            ).fetchall()
        return render_template("screen.html", screen=screen, media=media, ready_media=ready_media, schedule=schedule)

    @app.route("/player", methods=["GET", "POST"])
    def player_lookup():
        if request.method == "POST":
            screen_key = request.form.get("screen_key", "").strip()
            if is_four_digit_code(screen_key) and find_screen(screen_key):
                return redirect(url_for("player", screen_key=screen_key))
            flash("Введите 4 цифры из админки")
        return render_template("player_lookup.html")

    @app.get("/player/<screen_key>")
    def player(screen_key):
        screen = find_screen(screen_key)
        if not screen:
            abort(404)
        return render_template("player.html", screen=screen)

    @app.get("/api/player/<screen_key>/playlist")
    def playlist(screen_key):
        screen = find_screen(screen_key)
        if not screen:
            abort(404)

        now = datetime.now()
        with db() as conn:
            rows = conn.execute(
                """
                SELECT s.*, m.stored_name, m.original_name, m.kind, m.status
                FROM schedule_items s
                JOIN media m ON m.id = s.media_id
                WHERE s.active = 1 AND s.screen_id = ? AND m.status = ?
                ORDER BY s.sort_order ASC, s.id ASC
                """,
                (screen["id"], READY_STATUS),
            ).fetchall()

        items = [row_to_playlist_item(row) for row in rows if is_active_now(row, now)]
        return jsonify({"screen": dict(screen), "items": items, "serverTime": now.isoformat()})

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(UPLOAD_DIR, filename)

    @app.get("/api/media/status")
    def media_status():
        require_login()
        with db() as conn:
            rows = conn.execute(
                """
                SELECT id, status, error_message, processed_at
                FROM media
                ORDER BY created_at DESC
                """
            ).fetchall()
        return jsonify({"items": [dict(row) for row in rows]})

    return app


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                source_name TEXT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                file_size INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                processed_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screen_id INTEGER,
                media_id INTEGER NOT NULL,
                title TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 10,
                start_date TEXT,
                end_date TEXT,
                start_time TEXT,
                end_time TEXT,
                weekdays TEXT,
                sort_order INTEGER NOT NULL DEFAULT 100,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(screen_id) REFERENCES screens(id),
                FOREIGN KEY(media_id) REFERENCES media(id)
            );

            CREATE TABLE IF NOT EXISTS screens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                screen_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            """
        )

        exists = conn.execute("SELECT COUNT(*) AS count FROM screens").fetchone()["count"]
        if exists == 0:
            conn.execute(
                "INSERT INTO screens (name, screen_key, created_at) VALUES (?, ?, ?)",
                ("Главный экран", generate_screen_key(conn), utc_now_iso()),
            )

        media_columns = {row["name"] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
        if "source_name" not in media_columns:
            conn.execute("ALTER TABLE media ADD COLUMN source_name TEXT")
        if "status" not in media_columns:
            conn.execute("ALTER TABLE media ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'")
        if "file_size" not in media_columns:
            conn.execute("ALTER TABLE media ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
        if "error_message" not in media_columns:
            conn.execute("ALTER TABLE media ADD COLUMN error_message TEXT")
        if "processed_at" not in media_columns:
            conn.execute("ALTER TABLE media ADD COLUMN processed_at TEXT")
        conn.execute("UPDATE media SET status = 'ready' WHERE status IS NULL OR status = ''")
        for row in conn.execute("SELECT id, stored_name FROM media WHERE file_size = 0 OR file_size IS NULL").fetchall():
            file_path = UPLOAD_DIR / row["stored_name"]
            if file_path.exists():
                conn.execute("UPDATE media SET file_size = ? WHERE id = ?", (file_path.stat().st_size, row["id"]))

        schedule_columns = {row["name"] for row in conn.execute("PRAGMA table_info(schedule_items)").fetchall()}
        if "screen_id" not in schedule_columns:
            conn.execute("ALTER TABLE schedule_items ADD COLUMN screen_id INTEGER")
            main_screen = conn.execute("SELECT id FROM screens WHERE screen_key = ?", ("main",)).fetchone()
            if main_screen:
                conn.execute("UPDATE schedule_items SET screen_id = ? WHERE screen_id IS NULL", (main_screen["id"],))

        migrate_screen_keys(conn)


def is_logged_in():
    return session.get("admin") is True


def require_login():
    if not is_logged_in():
        abort(403)


def find_screen(screen_key):
    with db() as conn:
        return conn.execute("SELECT * FROM screens WHERE screen_key = ?", (screen_key,)).fetchone()


def find_screen_by_id(screen_id):
    with db() as conn:
        return conn.execute("SELECT * FROM screens WHERE id = ?", (screen_id,)).fetchone()


def find_media(media_id):
    with db() as conn:
        return conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()


def import_media_from_uploads():
    added = 0
    processing = 0
    skipped = 0
    videos_to_process = []

    with db() as conn:
        registered_names = set()
        for row in conn.execute("SELECT stored_name, source_name FROM media").fetchall():
            if row["stored_name"]:
                registered_names.add(row["stored_name"])
            if row["source_name"]:
                registered_names.add(row["source_name"])

        for file_path in sorted(UPLOAD_DIR.iterdir(), key=lambda item: item.name.lower()):
            if not file_path.is_file() or file_path.name.startswith("."):
                continue

            ext = file_path.suffix.lower().lstrip(".")
            if ext not in ALLOWED_EXTENSIONS:
                skipped += 1
                continue

            if file_path.name in registered_names or file_path.stem.endswith("_source"):
                skipped += 1
                continue

            kind = media_kind(ext)
            original_name = display_filename(file_path.name)
            file_size = file_path.stat().st_size

            if kind == "image":
                cursor = conn.execute(
                    """
                    INSERT INTO media
                        (original_name, stored_name, source_name, kind, status, file_size, created_at)
                    VALUES (?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (original_name, file_path.name, kind, READY_STATUS, file_size, utc_now_iso()),
                )
                registered_names.add(file_path.name)
                added += 1
                continue

            stored_name = make_stored_name("mp4")
            cursor = conn.execute(
                """
                INSERT INTO media
                    (original_name, stored_name, source_name, kind, status, file_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (original_name, stored_name, file_path.name, kind, PROCESSING_STATUS, file_size, utc_now_iso()),
            )
            registered_names.add(file_path.name)
            registered_names.add(stored_name)
            videos_to_process.append((cursor.lastrowid, file_path.name, stored_name))
            added += 1
            processing += 1

    for media_id, source_name, stored_name in videos_to_process:
        start_video_processing(media_id, source_name, stored_name)

    return {"added": added, "processing": processing, "skipped": skipped}


def format_datetime_ru(value):
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%d.%m.%Y %H:%M")


def format_file_size(value):
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        size = 0

    if size >= 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024 / 1024:.1f} ГБ"
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size} Б"


def media_kind_label(value):
    return "видео" if value == "video" else "фото"


def media_status_label(value):
    labels = {
        READY_STATUS: "готово",
        PROCESSING_STATUS: "обрабатывается",
        ERROR_STATUS: "ошибка",
    }
    return labels.get(value or READY_STATUS, "готово")


def utc_now_iso():
    return datetime.utcnow().isoformat()


def display_filename(filename):
    name = Path(filename.replace("\\", "/")).name.strip()
    return name or secure_filename(filename) or "media"


def media_kind(ext):
    return "video" if ext in VIDEO_EXTENSIONS else "image"


def make_stored_name(ext):
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{timestamp}_{secrets.token_hex(6)}.{ext}"


def delete_media_files(item):
    names = {item["stored_name"]}
    if "source_name" in item.keys() and item["source_name"]:
        names.add(item["source_name"])

    for name in names:
        file_path = UPLOAD_DIR / name
        if file_path.exists():
            file_path.unlink()


def start_video_processing(media_id, source_name, stored_name):
    thread = threading.Thread(
        target=process_video_for_tv,
        args=(media_id, source_name, stored_name),
        daemon=True,
    )
    thread.start()


def process_video_for_tv(media_id, source_name, stored_name):
    source_path = UPLOAD_DIR / source_name
    output_path = UPLOAD_DIR / stored_name

    if not source_path.exists():
        mark_media_error(media_id, "Исходный файл не найден")
        return

    converted, error = convert_video_for_tv(source_path, output_path)
    if converted:
        if not find_media(media_id):
            source_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            return

        source_path.unlink(missing_ok=True)
        with db() as conn:
            conn.execute(
                """
                UPDATE media
                SET status = ?, source_name = NULL, file_size = ?, error_message = NULL, processed_at = ?
                WHERE id = ?
                """,
                (READY_STATUS, output_path.stat().st_size, utc_now_iso(), media_id),
            )
        return

    output_path.unlink(missing_ok=True)
    mark_media_error(media_id, error or "Не удалось подготовить видео")


def mark_media_error(media_id, message):
    with db() as conn:
        conn.execute(
            "UPDATE media SET status = ?, error_message = ?, processed_at = ? WHERE id = ?",
            (ERROR_STATUS, message, utc_now_iso(), media_id),
        )


def schedule_duration(form, media_item):
    if media_item["kind"] == "video":
        return 0
    return max(1, int(form.get("duration_seconds") or 10))


def convert_video_for_tv(source_path, output_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg не установлен"

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        f"scale={MAX_VIDEO_WIDTH}:{MAX_VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=None)
    except OSError as exc:
        return False, str(exc)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return True, None

    error = (result.stderr or "").strip().splitlines()
    return False, error[-1] if error else "ffmpeg завершился с ошибкой"


def is_four_digit_code(value):
    return len(value) == 4 and value.isdigit()


def generate_screen_key(conn, used_codes=None):
    used = set(used_codes or [])
    if not used_codes:
        used.update(
            row["screen_key"]
            for row in conn.execute("SELECT screen_key FROM screens").fetchall()
            if is_four_digit_code(row["screen_key"])
        )

    for _ in range(9000):
        code = str(secrets.randbelow(9000) + 1000)
        if code not in used:
            return code

    raise RuntimeError("Не осталось свободных кодов экранов")


def migrate_screen_keys(conn):
    screens = conn.execute("SELECT id, screen_key FROM screens ORDER BY id").fetchall()
    used_codes = {screen["screen_key"] for screen in screens if is_four_digit_code(screen["screen_key"])}

    for screen in screens:
        if is_four_digit_code(screen["screen_key"]):
            continue

        new_code = generate_screen_key(conn, used_codes)
        used_codes.add(new_code)
        conn.execute("UPDATE screens SET screen_key = ? WHERE id = ?", (new_code, screen["id"]))


def row_to_playlist_item(row):
    return {
        "id": row["id"],
        "title": row["title"] or row["original_name"],
        "kind": row["kind"],
        "durationSeconds": row["duration_seconds"],
        "url": url_for("uploaded_file", filename=row["stored_name"], _external=True),
    }


def is_active_now(row, now):
    today = now.date().isoformat()
    if row["start_date"] and today < row["start_date"]:
        return False
    if row["end_date"] and today > row["end_date"]:
        return False

    if row["weekdays"]:
        allowed_days = {int(day) for day in row["weekdays"].split(",") if day}
        if now.weekday() not in allowed_days:
            return False

    if row["start_time"] and now.time() < parse_time(row["start_time"]):
        return False
    if row["end_time"] and now.time() > parse_time(row["end_time"]):
        return False
    return True


def parse_time(value):
    hours, minutes = value.split(":")[:2]
    return time(int(hours), int(minutes))


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
