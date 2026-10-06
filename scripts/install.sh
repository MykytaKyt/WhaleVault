#!/usr/bin/env bash
# One-command install and update for a home server (ZimaOS, or any Linux with Docker + NVIDIA).
#
#   curl -fsSL https://raw.githubusercontent.com/MykytaKyt/WhaleVault/main/scripts/install.sh | sudo bash
#
# Safe to re-run: the second run updates the code and restarts the containers.
# Settings: NOTES_DIR (install folder), NOTES_REPO (git URL), NOTES_BRANCH.
set -euo pipefail

REPO="${NOTES_REPO:-https://github.com/MykytaKyt/WhaleVault.git}"
BRANCH="${NOTES_BRANCH:-main}"
# On ZimaOS only /DATA survives system updates
if [ -z "${NOTES_DIR:-}" ]; then
  if [ -d /DATA ]; then NOTES_DIR=/DATA/AppData/notes-bot; else NOTES_DIR="$HOME/notes-bot"; fi
fi

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

# Questions go to the terminal even when the script itself is piped from curl
ask() {  # ask "Question" default -> answer on stdout
  local answer=""
  if { : > /dev/tty; } 2>/dev/null; then
    printf '%s ' "$1" > /dev/tty
    read -r answer < /dev/tty || true
  fi
  printf '%s' "${answer:-$2}"
}

# ZimaOS ships without git: fall back to git in a throwaway container
git_() {  # git_ <workdir> <args...>
  local dir="$1"; shift
  if command -v git >/dev/null; then
    git -C "$dir" "$@"
  else
    docker run --rm -v "$dir:/w" -w /w alpine/git -c safe.directory=/w "$@"
  fi
}

set_env() {  # set_env KEY VALUE — replace the line in .env, or append it (value must not contain '|')
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

# Everything runs inside main(): bash reads the whole function before executing it, so the
# `git pull` below can safely replace this very file.
main() {
  step "Docker"
  command -v docker >/dev/null || die "docker not found"
  docker info >/dev/null 2>&1 || die "cannot talk to Docker: run this with sudo"
  docker compose version >/dev/null 2>&1 \
    || die "'docker compose' is not available. On ZimaOS update the system; elsewhere install the Compose plugin"
  ok "$(docker --version)"

  step "Code in $NOTES_DIR"
  if [ -d "$NOTES_DIR/.git" ]; then
    # docs/environment.md is regenerated on every run; don't let it block the update
    git_ "$NOTES_DIR" checkout -- docs/environment.md 2>/dev/null || true
    git_ "$NOTES_DIR" pull --ff-only origin "$BRANCH" || die "git pull failed (local changes in $NOTES_DIR?)"
    ok "updated"
  else
    [ -e "$NOTES_DIR" ] && [ -n "$(ls -A "$NOTES_DIR" 2>/dev/null)" ] && die "$NOTES_DIR exists and is not empty"
    mkdir -p "$(dirname "$NOTES_DIR")"
    git_ "$(dirname "$NOTES_DIR")" clone --branch "$BRANCH" "$REPO" "$(basename "$NOTES_DIR")"
    ok "cloned"
  fi
  cd "$NOTES_DIR"

  step "Settings (.env)"
  if [ ! -f .env ]; then
    cp .env.example .env
    ok "created .env from .env.example"
  fi
  # Containers run as the owner of the project folder, so they can write data/, logs/, backups/
  set_env PUID "$(stat -c %u .)"
  set_env PGID "$(stat -c %g .)"
  if ! grep -qE '^TELEGRAM_TOKEN=.+' .env; then
    token=$(ask "Telegram bot token (from @BotFather):" "")
    [ -n "$token" ] || die "the token is required: put TELEGRAM_TOKEN into $NOTES_DIR/.env and run again"
    set_env TELEGRAM_TOKEN "$token"
  fi
  if ! grep -qE '^ALLOWED_USER_ID=[0-9]+' .env; then
    uid=$(ask "Your numeric Telegram id (e.g. from @userinfobot):" "")
    [[ "$uid" =~ ^[0-9]+$ ]] || die "the id must be a number: put ALLOWED_USER_ID into $NOTES_DIR/.env and run again"
    set_env ALLOWED_USER_ID "$uid"
  fi
  if ! grep -qE '^WEB_PASSWORD=.+' .env; then
    set_env WEB_PASSWORD "$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)"
    ok "generated a password for the web UI (WEB_PASSWORD in .env)"
  fi
  tz=$(grep -E '^TZ=' .env | cut -d= -f2)
  ok "time zone $tz (change TZ in .env if needed)"
  mkdir -p data logs backups data/cache/cuda
  chown "$(stat -c %u .):$(stat -c %g .)" data logs backups data/cache data/cache/cuda

  step "Server snapshot"
  ./scripts/snapshot-env.sh >/dev/null && ok "docs/environment.md"

  step "GPU check"
  set +e
  ./scripts/check-gpu.sh
  gpu_rc=$?
  set -e
  if [ "$gpu_rc" -eq 2 ] && ! grep -q '^LLM_IMAGE=notes-llm:pascal' .env; then
    reply=$(ask "The prebuilt llama.cpp image doesn't see the GPU. Build one for the Tesla P4 (20-40 min)? [Y/n]" "y")
    case "$reply" in
      [Nn]*) die "stopped: the model engine can't use the GPU" ;;
    esac
    set_env LLM_IMAGE notes-llm:pascal
    set +e; ./scripts/check-gpu.sh; gpu_rc=$?; set -e
  fi
  [ "$gpu_rc" -eq 0 ] || die "GPU check failed: send the output above (and docs/environment.md) to the developer"

  step "Models (about 10 GB on the first run)"
  ./scripts/download-models.sh || die "model download failed: re-run the script to resume"

  step "Start"
  docker compose up -d --build
  # Always restart the bot, so "bot started" below comes from this run and not an older one
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker compose up -d --no-deps --force-recreate bot
  started=0
  for _ in $(seq 1 60); do
    if docker compose logs --since "$since" bot 2>/dev/null | grep -q "bot started"; then
      started=1
      break
    fi
    sleep 2
  done
  [ "$started" -eq 1 ] \
    || die "the bot did not start in 2 minutes: cd $NOTES_DIR && docker compose logs bot"
  ok "the bot is running"

  # These lookups must never abort the script (set -e + pipefail): busybox may lack `hostname -I`,
  # and an .env from before stage 4 has no WEB_PORT line
  ip=$( (hostname -I 2>/dev/null || true) | awk '{print $1}')
  [ -n "$ip" ] || ip=$( (ip -4 route get 1.1.1.1 2>/dev/null || true) \
    | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')
  port=$( (grep -E '^WEB_PORT=' .env || true) | cut -d= -f2)
  password=$( (grep -E '^WEB_PASSWORD=' .env || true) | cut -d= -f2)
  cat <<EOF

Done. Send your bot any text in Telegram: it answers "Принял" at once, the topic arrives within a minute.

  Web UI:     http://${ip:-<server-ip>}:${port:-8090}   password: $password

  Logs:       cd $NOTES_DIR && docker compose logs -f bot
  Benchmark:  cd $NOTES_DIR && ./scripts/bench.sh
  Update:     run the same install command again
EOF
}

main "$@"
