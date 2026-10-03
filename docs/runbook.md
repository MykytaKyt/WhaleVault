# Runbook

Проект живёт в одной папке (на ZimaOS удобно `/DATA/AppData/notes-bot`). Всё состояние лежит в `data/`.

## Первый запуск (этап 1)

```bash
git clone <repo> /DATA/AppData/notes-bot && cd /DATA/AppData/notes-bot
cp .env.example .env            # заполнить PUID/PGID (id -u; id -g), TZ
./scripts/snapshot-env.sh       # → docs/environment.md
./scripts/check-gpu.sh          # должен закончиться «check-gpu пройден»
./scripts/download-models.sh    # ~10 ГБ в data/models/
docker compose up -d llm
docker compose logs -f llm      # дождаться, что llama-swap слушает :8080
./scripts/bench.sh              # проверка API и замер → docs/bench/<дата>.md
```

Если `check-gpu.sh` пишет, что llama.cpp не видит GPU:

```bash
sed -i 's|^LLM_IMAGE=.*|LLM_IMAGE=notes-llm:pascal|' .env
./scripts/check-gpu.sh          # сам соберёт llm/Dockerfile (20–40 минут)
```

Если GPU занят Ollama: ничего не останавливаем сами, сначала договориться с пользователем.

## Ручная проверка API

```bash
curl -s localhost:9292/v1/models
curl -s localhost:9292/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"routine","messages":[{"role":"user","content":"Привіт! Як справи?"}],"max_tokens":50}'
curl -s localhost:9292/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"embed","input":"тест"}' | head -c 300
curl -s localhost:9292/running                 # что сейчас загружено
curl -s -X POST localhost:9292/api/models/unload   # выгрузить всё
```

## Проверка простоя GPU

После любого запроса к LLM подождать `LLM_TTL_DAY` (10 минут) и выполнить
`nvidia-smi --query-gpu=memory.used,pstate,power.draw --format=csv` — ожидается 0 МБ.

## Обновление, откат, бэкап

Будет дописано на этапе 2 (бэкап `data/` по cron, восстановление).
