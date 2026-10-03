#!/usr/bin/env bash
# Server environment snapshot -> docs/environment.md. Run on the server from the repo root.
. "$(dirname "$0")/lib.sh"
out="docs/environment.md"

section() {
  local title="$1"; shift
  printf '\n## %s\n\n```\n$ %s\n' "$title" "$*"
  bash -c "$*" 2>&1 || printf '(command exited with code %s)\n' "$?"
  printf '```\n'
}

{
  echo "# Server environment"
  echo
  echo "Captured: $(date '+%Y-%m-%d %H:%M %Z') by scripts/snapshot-env.sh on $(hostname)."
  section "Kernel and OS" "uname -a; cat /etc/os-release 2>/dev/null | head -5"
  section "Docker" "docker --version"
  section "Docker Compose" "docker compose version"
  section "Docker runtimes" "docker info --format '{{json .Runtimes}} default={{.DefaultRuntime}}'"
  section "GPU" "nvidia-smi"
  section "GPU summary" "nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,pstate,power.draw,temperature.gpu --format=csv"
  section "GPU processes" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv"
  section "NVIDIA Container Toolkit" "nvidia-ctk --version 2>/dev/null || which nvidia-container-runtime || echo 'nvidia-ctk not found in PATH'"
  section "Disks" "df -h"
  section "Memory" "free -h"
  section "CPU" "nproc; grep -m1 'model name' /proc/cpuinfo"
  section "Containers" "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
  section "Ollama" "docker ps -a --filter name=ollama --format '{{.Names}} {{.Status}}'; pgrep -a ollama || echo 'no ollama process on the host'"
  section "Tools" "for c in curl python3 jq git crontab; do printf '%-10s %s\n' \$c \"\$(command -v \$c || echo missing)\"; done"
} > "$out"

ok "Snapshot written to $out"
