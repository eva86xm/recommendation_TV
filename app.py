import os
import secrets
import sqlite3
from datetime import datetime, time
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "signage.db"
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "webm", "mov"}


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "300")) * 1024 * 1024

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

        original_name = secure_filename(file.filename)
        stored_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}.{ext}"
        file.save(UPLOAD_DIR / stored_name)
        kind = "video" if ext in {"mp4", "webm", "mov"} else "image"

        with db() as conn:
            conn.execute(
                "INSERT INTO media (original_name, stored_name, kind, created_at) VALUES (?, ?, ?, ?)",
                (original_name, stored_name, kind, datetime.utcnow().isoformat()),
            )
        flash("Файл загружен")
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

        file_path = UPLOAD_DIR / item["stored_name"]
        if file_path.exists():
            file_path.unlink()

        flash("Файл удален")
        return redirect(next_url)

    @app.post("/schedule")
    def add_schedule_item():
        require_login()
        form = request.form
        screen = find_screen_by_id(int(form["screen_id"]))
        with db() as conn:
            conn.execute(
                """
                INSERT INTO schedule_items
                    (screen_id, media_id, title, duration_seconds, start_date, end_date, start_time, end_time, weekdays, sort_order, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(form["screen_id"]),
                    int(form["media_id"]),
                    form.get("title", "").strip(),
                    int(form.get("duration_seconds") or 10),
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
        key = secrets.token_urlsafe(12)
        with db() as conn:
            conn.execute("INSERT INTO screens (name, screen_key, created_at) VALUES (?, ?, ?)", (name, key, datetime.utcnow().isoformat()))
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
            schedule = conn.execute(
                """
                SELECT s.*, m.original_name, m.kind
                FROM schedule_items s
                JOIN media m ON m.id = s.media_id
                WHERE s.screen_id = ?
                ORDER BY s.sort_order ASC, s.id DESC
                """,
                (screen["id"],),
            ).fetchall()
        return render_template("screen.html", screen=screen, media=media, schedule=schedule)

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
                SELECT s.*, m.stored_name, m.original_name, m.kind
                FROM schedule_items s
                JOIN media m ON m.id = s.media_id
                WHERE s.active = 1 AND s.screen_id = ?
                ORDER BY s.sort_order ASC, s.id ASC
                """,
                (screen["id"],),
            ).fetchall()

        items = [row_to_playlist_item(row) for row in rows if is_active_now(row, now)]
        return jsonify({"screen": dict(screen), "items": items, "serverTime": now.isoformat()})

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(UPLOAD_DIR, filename)

    return app


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                kind TEXT NOT NULL,
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
                ("Главный экран", "main", datetime.utcnow().isoformat()),
            )

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(schedule_items)").fetchall()}
        if "screen_id" not in columns:
            conn.execute("ALTER TABLE schedule_items ADD COLUMN screen_id INTEGER")
            main_screen = conn.execute("SELECT id FROM screens WHERE screen_key = ?", ("main",)).fetchone()
            if main_screen:
                conn.execute("UPDATE schedule_items SET screen_id = ? WHERE screen_id IS NULL", (main_screen["id"],))


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
