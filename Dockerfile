FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p instance uploads

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "4", "--timeout", "0", "-b", "0.0.0.0:8000", "app:app"]
