# One image for the Telegram bot and the web UI (two compose services with different commands).

# Web UI: SvelteKit built into static files, no Node at runtime
FROM node:22-alpine AS web
WORKDIR /app/web/app
COPY web/app/package.json web/app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/app/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY migrations ./migrations
COPY bot ./bot
COPY web/__init__.py ./web/__init__.py
COPY web/api ./web/api
COPY --from=web /app/web/static ./web/static
CMD ["python", "-m", "bot.main"]
