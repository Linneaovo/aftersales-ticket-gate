# Standalone 演示镜像：Fixture + file_outbox，不含 enterprise-rag
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY pytest.ini .
COPY .env.standalone .env

RUN mkdir -p data/traces data/outbox

EXPOSE 8002 8502

# 默认 API；UI 由 docker-compose 覆盖 command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
