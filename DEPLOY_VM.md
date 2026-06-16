# Развертывание на Linux ВМ

Ниже пример для Ubuntu 24.04/22.04.

## Вариант 1: Docker

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2
sudo systemctl enable --now docker

git clone https://github.com/USER/digital-signage-app.git
cd digital-signage-app
cp .env.example .env
nano .env

sudo docker compose up -d --build
```

После запуска:

- Админка: `http://IP_ВМ:8000/`
- Плеер: `http://IP_ВМ:8000/player/main`

## Вариант 2: Python + systemd + Nginx

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip nginx

sudo mkdir -p /opt/digital-signage-app
sudo chown -R $USER:$USER /opt/digital-signage-app
git clone https://github.com/USER/digital-signage-app.git /opt/digital-signage-app

cd /opt/digital-signage-app
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Установить сервис:

```bash
sudo chown -R www-data:www-data /opt/digital-signage-app
sudo cp deploy/signage.service /etc/systemd/system/signage.service
sudo systemctl daemon-reload
sudo systemctl enable --now signage
```

Подключить Nginx:

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/digital-signage
sudo ln -s /etc/nginx/sites-available/digital-signage /etc/nginx/sites-enabled/digital-signage
sudo nginx -t
sudo systemctl reload nginx
```

В файле `deploy/nginx.conf` замените `example.com` на домен или IP.

## Проверка

```bash
sudo systemctl status signage
sudo journalctl -u signage -f
```

## Для телевизора

На Smart TV, Android TV box, Raspberry Pi или мини-ПК откройте:

```text
http://IP_ВМ/player/main
```

Для каждого нового телевизора создайте отдельный экран в админке и откройте его ссылку плеера.
