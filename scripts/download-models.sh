#!/usr/bin/env bash
# Скачать GGUF по списку из .env в $MODELS_DIR. Повторный запуск докачивает/пропускает готовые.
. "$(dirname "$0")/lib.sh"
load_env
dir="${MODELS_DIR:-./data/models}"; mkdir -p "$dir"
HF="${HF_ENDPOINT:-https://huggingface.co}"
auth=(); [ -n "${HF_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $HF_TOKEN")

get() {  # repo file
  local repo="$1" file="$2" url="$HF/$1/resolve/main/$2"
  if [ -s "$dir/$file" ] && [ ! -f "$dir/$file.part" ]; then ok "$file уже есть ($(du -h "$dir/$file" | cut -f1))"; return; fi
  code=$(curl -sIL -o /dev/null -w '%{http_code}' "${auth[@]}" "$url")
  if [ "$code" != "200" ]; then
    fail "$repo/$file: HTTP $code. Файлы в репозитории:"
    curl -s "${auth[@]}" "$HF/api/models/$repo" | grep -o '"rfilename":"[^"]*\.gguf"' | cut -d'"' -f4 | sed 's/^/   /'
    echo "   → поправить *_MODEL_FILE / *_MODEL_REPO в .env и записать замену в docs/models.md"
    return 1
  fi
  echo "↓ $repo/$file"
  touch "$dir/$file.part"
  curl -fL -C - --retry 5 --retry-delay 5 "${auth[@]}" -o "$dir/$file" "$url" && rm -f "$dir/$file.part" && ok "$file"
}

rc=0
get "$ROUTINE_MODEL_REPO" "$ROUTINE_MODEL_FILE" || rc=1
get "$ANSWER_MODEL_REPO"  "$ANSWER_MODEL_FILE"  || rc=1
get "$EMBED_MODEL_REPO"   "$EMBED_MODEL_FILE"   || rc=1
[ "${DOWNLOAD_DRAFT:-0}" = "1" ] && { get "$DRAFT_MODEL_REPO" "$DRAFT_MODEL_FILE" || rc=1; }
chmod -R a+rX "$dir"
echo; du -ch "$dir"/*.gguf 2>/dev/null | tail -n1 | sed 's/^/Всего моделей: /'
exit $rc
