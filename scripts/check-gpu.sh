#!/usr/bin/env bash
# Проверка драйвера, NVIDIA Container Toolkit и CUDA-бэкенда llama.cpp в образе LLM.
# Код возврата 0 — можно поднимать docker compose. Пока не проходит, код бота не пишется.
. "$(dirname "$0")/lib.sh"
load_env
rc=0

echo "== 1. Драйвер на хосте"
if ! command -v nvidia-smi >/dev/null; then fail "nvidia-smi не найден"; exit 1; fi
info=$(nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv,noheader 2>&1) \
  || { fail "nvidia-smi: $info"; exit 1; }
echo "   $info"
drv=$(echo "$info" | awk -F', ' '{print $2}'); drv_major=${drv%%.*}
cap=$(echo "$info" | awk -F', ' '{print $3}')
[ "$cap" = "6.1" ] && ok "compute capability 6.1 (Pascal)" || warn "compute capability $cap (ожидалась 6.1)"
if [ "$drv_major" -ge 570 ] 2>/dev/null; then
  ok "драйвер $drv тянет CUDA 12.8 (готовый образ llama-swap:cuda)"
elif [ "$drv_major" -ge 550 ] 2>/dev/null; then
  warn "драйвер $drv < 570: готовый образ на CUDA 12.8 может не запуститься → LLM_IMAGE=notes-llm:pascal (llm/Dockerfile, CUDA 12.4)"
else
  fail "драйвер $drv слишком старый для CUDA 12.x"; rc=1
fi
[ "$drv_major" -ge 590 ] 2>/dev/null && warn "ветки драйвера новее 580 могут не поддерживать Pascal — проверить, что P4 видна"

echo "== 2. Занятость GPU (Ollama и прочие)"
apps=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
if [ -n "$apps" ]; then warn "GPU занят процессами (согласовать остановку с пользователем, сами не трогаем):"; echo "$apps" | sed 's/^/   /'
else ok "на GPU нет процессов"; fi

echo "== 3. GPU внутри Docker (NVIDIA Container Toolkit)"
if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L; then
  ok "контейнер видит GPU"
else
  fail "docker --gpus all не работает: нужен NVIDIA Container Toolkit (nvidia-ctk runtime configure --runtime=docker && перезапуск docker)"; exit 1
fi

echo "== 4. CUDA-бэкенд llama.cpp в образе $LLM_IMAGE"
if ! docker image inspect "$LLM_IMAGE" >/dev/null 2>&1; then
  if [ "$LLM_IMAGE" = "notes-llm:pascal" ]; then
    echo "   образ не собран, собираю (долго)…"; docker compose build llm || { fail "сборка не удалась"; exit 1; }
  else
    docker pull "$LLM_IMAGE" || { fail "не удалось скачать $LLM_IMAGE"; exit 1; }
  fi
fi
mkdir -p data/cache/cuda
devs=$(docker run --rm --gpus all --entrypoint /app/llama-server \
  -e CUDA_CACHE_PATH=/cache/cuda -v "$ROOT/data/cache/cuda:/cache/cuda" \
  "$LLM_IMAGE" --list-devices 2>&1)
echo "$devs" | sed 's/^/   /' | tail -n 15
if echo "$devs" | grep -qiE 'CUDA0.*(P4|Tesla)'; then
  ok "llama.cpp видит Tesla P4 через CUDA"
else
  fail "llama.cpp в $LLM_IMAGE не видит GPU. Попробовать LLM_IMAGE=notes-llm:pascal в .env и запустить скрипт снова"; rc=1
fi

echo
[ $rc -eq 0 ] && ok "check-gpu пройден" || fail "check-gpu НЕ пройден"
exit $rc
