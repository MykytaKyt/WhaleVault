#!/usr/bin/env bash
# Проверка API llama-swap и замер скорости моделей. Результат → docs/bench/<дата>.md
. "$(dirname "$0")/lib.sh"
load_env
if command -v python3 >/dev/null; then
  python3 scripts/bench.py
else
  # На ZimaOS python может не быть — запускаем в одноразовом контейнере (VRAM/ОЗУ тогда «н/д»)
  docker run --rm --network host --env-file .env -v "$ROOT:/w" -w /w python:3.12-slim python scripts/bench.py
  echo; echo "nvidia-smi после замера:"; nvidia-smi --query-gpu=memory.used,pstate,power.draw,temperature.gpu --format=csv
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep notes
fi
