#!/usr/bin/env bash
# Checks the llama-swap API and benchmarks the models. Output -> docs/bench/<date>.md
. "$(dirname "$0")/lib.sh"
load_env
if command -v python3 >/dev/null; then
  python3 scripts/bench.py
else
  # ZimaOS may lack python: run in a throwaway container (VRAM/RAM then show "n/a")
  docker run --rm --network host --env-file .env -v "$ROOT:/w" -w /w python:3.12-slim python scripts/bench.py
  echo; echo "nvidia-smi after the benchmark:"; nvidia-smi --query-gpu=memory.used,pstate,power.draw,temperature.gpu --format=csv
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep notes
fi
