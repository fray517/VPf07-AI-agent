# Telegram-бот (run_bot.py). Сборка из корня репозитория.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run_bot.py run.py ./
COPY agent/ ./agent/

RUN mkdir -p /app/agent/data && chown -R appuser:appuser /app

USER appuser

CMD ["python", "run_bot.py"]
