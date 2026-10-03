# Bot image (Telegram bot now; the FastAPI web UI joins it in stage 4)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY migrations ./migrations
COPY bot ./bot
CMD ["python", "-m", "bot.main"]
