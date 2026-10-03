#!/usr/bin/env bash
# Manual backup (the bot also runs one daily at BACKUP_CRON): backups/<date>/notes.db (+ media.tar).
. "$(dirname "$0")/lib.sh"
docker compose exec -T bot python -m bot.jobs.backup
