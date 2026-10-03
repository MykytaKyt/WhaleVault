#!/usr/bin/env bash
# Checks the driver, NVIDIA Container Toolkit and the llama.cpp CUDA backend in the LLM image.
# Exit code 0 = OK to bring up docker compose. No bot code is written until this passes.
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"
load_env
rc=0

echo "== 1. Host driver"
if ! command -v nvidia-smi >/dev/null; then fail "nvidia-smi not found"; exit 1; fi
info=$(nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv,noheader 2>&1) \
  || { fail "nvidia-smi: $info"; exit 1; }
echo "   $info"
drv=$(echo "$info" | awk -F', ' '{print $2}'); drv_major=${drv%%.*}
cap=$(echo "$info" | awk -F', ' '{print $3}')
[ "$cap" = "6.1" ] && ok "compute capability 6.1 (Pascal)" || warn "compute capability $cap (expected 6.1)"
if [ "$drv_major" -ge 570 ] 2>/dev/null; then
  ok "driver $drv supports CUDA 12.8 (prebuilt llama-swap:cuda image)"
elif [ "$drv_major" -ge 550 ] 2>/dev/null; then
  warn "driver $drv < 570: the CUDA 12.8 prebuilt image may not run -> LLM_IMAGE=notes-llm:pascal (llm/Dockerfile, CUDA 12.4)"
else
  fail "driver $drv is too old for CUDA 12.x"; rc=1
fi
[ "$drv_major" -ge 590 ] 2>/dev/null && warn "driver branches newer than 580 may drop Pascal - make sure the P4 is visible"

echo "== 2. GPU usage (Ollama and others)"
apps=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
if [ -n "$apps" ]; then warn "GPU is in use (agree with the user before stopping anything; do not touch it ourselves):"; echo "$apps" | sed 's/^/   /'
else ok "no processes on the GPU"; fi

echo "== 3. GPU inside Docker (NVIDIA Container Toolkit)"
if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L; then
  ok "container sees the GPU"
else
  fail "docker --gpus all does not work: NVIDIA Container Toolkit required (nvidia-ctk runtime configure --runtime=docker && restart docker)"; exit 1
fi

echo "== 4. llama.cpp CUDA backend in image $LLM_IMAGE"
if ! docker image inspect "$LLM_IMAGE" >/dev/null 2>&1; then
  if [ "$LLM_IMAGE" = "notes-llm:pascal" ]; then
    echo "   image not built, building (slow)..."; docker compose build llm || { fail "build failed"; exit 1; }
  else
    docker pull "$LLM_IMAGE" || { fail "failed to pull $LLM_IMAGE"; exit 1; }
  fi
fi
mkdir -p data/cache/cuda
devs=$(docker run --rm --gpus all --entrypoint /app/llama-server \
  -e CUDA_CACHE_PATH=/cache/cuda -v "$ROOT/data/cache/cuda:/cache/cuda" \
  "$LLM_IMAGE" --list-devices 2>&1)
echo "$devs" | sed 's/^/   /' | tail -n 15
if echo "$devs" | grep -qiE 'CUDA0.*(P4|Tesla)'; then
  ok "llama.cpp sees the Tesla P4 via CUDA"
else
  fail "llama.cpp in $LLM_IMAGE does not see the GPU. Try LLM_IMAGE=notes-llm:pascal in .env and rerun this script"; rc=1
fi

echo
[ $rc -eq 0 ] && ok "check-gpu passed" || fail "check-gpu FAILED"
exit $rc
