# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Integração ELOCA ↔ CRM Lovable
# Sem Playwright — só Python + httpx + 2captcha
# Imagem muito menor (~150MB vs ~1.5GB antes)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema para pymssql (FreeTDS + compilador C)
RUN apt-get update && apt-get install -y --no-install-recommends \
        freetds-dev \
        freetds-bin \
        gcc \
        g++ \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    SYNC_CRON="*/30 * * * *" \
    RUN_ON_START=true \
    SESSION_FILE=/data/eloca_session.json \
    TOKEN_FILE=/data/eloca_token.json

RUN useradd -m appuser && chown -R appuser /app
USER appuser

CMD ["python", "src/scheduler.py"]
