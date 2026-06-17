# Digital Signage App

Приложение для показа рекламы на телевизорах: видео, картинки, плейлист и расписание по датам, времени и дням недели.

## Возможности

- Загрузка изображений и видео.
- Видео до 20 ГБ с фоновой обработкой и статусами готовности.
- Расписание показа по датам, времени и дням недели.
- Отдельная ссылка-плеер для каждого телевизора.
- Автоматическое обновление плейлиста после каждого круга показа.
- SQLite база без отдельного сервера БД.
- Запуск локально, через Docker или как сервис на Linux ВМ.

## Быстрый запуск через Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Откройте:

- Админка: `http://SERVER_IP:8000/`
- Вход на телевизоре: `http://SERVER_IP:8000/player`

Пароль по умолчанию задается в `.env` через `ADMIN_PASSWORD`.
Лимит загрузки задается через `MAX_UPLOAD_MB`, по умолчанию в примере стоит 20 ГБ.

## Локальный запуск без Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export $(cat .env | xargs)
python app.py
```

## Как пользоваться

1. Войдите в админку.
2. Загрузите картинку или видео.
3. Добавьте файл в расписание.
4. Откройте `/player` на телевизоре.
5. Введите 4-значный код экрана из админки.
6. Переведите браузер на ТВ в полноэкранный режим.

## Git

```bash
git init
git add .
git commit -m "Initial digital signage app"
git branch -M main
git remote add origin git@github.com:USER/digital-signage-app.git
git push -u origin main
```
