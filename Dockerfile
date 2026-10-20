FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Istanbul \
    PORT=10000

WORKDIR /app

# Türkçe karakterli PDF üretimi için DejaVu Sans fontu ve saat dilimi
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.yaml .
COPY app ./app
RUN mkdir -p /app/data /app/output
COPY data/profile.json ./data/profile.json

EXPOSE 10000

CMD ["python", "-m", "app.main"]
