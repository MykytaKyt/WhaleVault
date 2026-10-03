#!/usr/bin/env bash
# Снимок окружения сервера → docs/environment.md. Запускать на сервере из корня репозитория.
. "$(dirname "$0")/lib.sh"
out="docs/environment.md"

section() {
  local title="$1"; shift
  printf '\n## %s\n\n```\n$ %s\n' "$title" "$*"
  bash -c "$*" 2>&1 || printf '(команда завершилась с кодом %s)\n' "$?"
  printf '```\n'
}

{
  echo "# Окружение сервера"
  echo
  echo "Снято: $(date '+%Y-%m-%d %H:%M %Z') скриптом scripts/snapshot-env.sh на $(hostname)."
  section "Ядро и ОС" "uname -a; cat /etc/os-release 2>/dev/null | head -5"
  section "Docker" "docker --version"
  section "Docker Compose" "docker compose version"
  section "Docker runtimes" "docker info --format '{{json .Runtimes}} default={{.DefaultRuntime}}'"
  section "GPU" "nvidia-smi"
  section "GPU кратко" "nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,pstate,power.draw,temperature.gpu --format=csv"
  section "Процессы на GPU" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv"
  section "NVIDIA Container Toolkit" "nvidia-ctk --version 2>/dev/null || which nvidia-container-runtime || echo 'nvidia-ctk не найден в PATH'"
  section "Диски" "df -h"
  section "Память" "free -h"
  section "CPU" "nproc; grep -m1 'model name' /proc/cpuinfo"
  section "Контейнеры" "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
  section "Ollama" "docker ps -a --filter name=ollama --format '{{.Names}} {{.Status}}'; pgrep -a ollama || echo 'процесс ollama на хосте не найден'"
  section "Утилиты" "for c in curl python3 jq git crontab; do printf '%-10s %s\n' \$c \"\$(command -v \$c || echo нет)\"; done"
} > "$out"

ok "Снимок записан в $out"
