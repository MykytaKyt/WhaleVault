# Shared helpers for scripts. Source with: . "$(dirname "$0")/lib.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; }

# Load .env if present, otherwise .env.example (defaults only)
load_env() {
  local f=".env"
  [ -f "$f" ] || { warn ".env not found, using values from .env.example"; f=".env.example"; }
  set -a; . "./$f"; set +a
}
