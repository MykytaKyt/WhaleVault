# Runbook

The project lives in one folder (on ZimaOS `/DATA/AppData/notes-bot` is convenient). All state is in `data/`.

## Install with one command (recommended)

On the server over SSH (ZimaOS: enable SSH in the ZimaOS settings, log in with the user created at setup):

```bash
curl -fsSL https://raw.githubusercontent.com/MykytaKyt/WhaleVault/main/scripts/install.sh | sudo bash
```

`scripts/install.sh`:

1. checks Docker and `docker compose`;
2. clones the repo into `/DATA/AppData/notes-bot` (only `/DATA` survives ZimaOS updates; elsewhere
   `~/notes-bot`, or set `NOTES_DIR`). ZimaOS has no git, so git runs in a throwaway `alpine/git` container;
3. creates `.env`, asks for `TELEGRAM_TOKEN` and `ALLOWED_USER_ID`, sets `PUID`/`PGID` to the folder owner;
4. writes `docs/environment.md` and runs `check-gpu.sh`; if only the prebuilt llama.cpp image can't see
   the P4, offers to build `llm/Dockerfile` (20–40 min);
5. downloads the models and runs `docker compose up -d --build`, then waits for "bot started".

Re-running it updates the code and restarts the bot; `.env`, `data/` and `backups/` stay as they are.

On ZimaOS, manage the `notes-bot` and `notes-llm` containers over SSH with `docker compose`, not from
the ZimaOS dashboard: editing them there can recreate them without the GPU, memory limits or volumes.

## First launch by hand (stage 1)

```bash
git clone <repo> /DATA/AppData/notes-bot && cd /DATA/AppData/notes-bot
cp .env.example .env            # fill in PUID/PGID (id -u; id -g), TZ, Telegram settings
./scripts/snapshot-env.sh       # -> docs/environment.md
./scripts/check-gpu.sh          # must end with "check-gpu passed"
./scripts/download-models.sh    # ~10 GB into data/models/
docker compose up -d llm
docker compose logs -f llm      # wait until llama-swap listens on :8080
./scripts/bench.sh              # API check and benchmark -> docs/bench/<date>.md
```

If `check-gpu.sh` exits with code 2 (llama.cpp in the prebuilt image can't see the GPU):

```bash
sed -i 's|^LLM_IMAGE=.*|LLM_IMAGE=notes-llm:pascal|' .env
./scripts/check-gpu.sh          # builds llm/Dockerfile itself (20–40 minutes)
```

If Ollama occupies the GPU: don't stop anything yourself, agree with the user first.

## Manual API check

```bash
curl -s localhost:9292/v1/models
curl -s localhost:9292/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"routine","messages":[{"role":"user","content":"Привіт! Як справи?"}],"max_tokens":50}'
curl -s localhost:9292/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"embed","input":"test"}' | head -c 300
curl -s localhost:9292/running                     # what is loaded right now
curl -s -X POST localhost:9292/api/models/unload   # unload everything
```

## GPU idle check

After any LLM request, wait `LLM_TTL_DAY` (10 minutes) and run
`nvidia-smi --query-gpu=memory.used,pstate,power.draw --format=csv`; expect 0 MB.

## Bot (stage 2)

1. Create a bot with @BotFather, put the token into `TELEGRAM_TOKEN`.
2. Get your numeric Telegram id (e.g. from @userinfobot), put it into `ALLOWED_USER_ID`.
3. Start:

```bash
mkdir -p data logs backups      # must exist before compose, or Docker creates them owned by root
docker compose up -d --build
docker compose logs -f bot      # "bot started"
```

Send the bot any text. Logs: `logs/bot.log`; model failures with full prompt and response:
`logs/llm-errors.log`; GPU every 5 minutes: `logs/gpu.csv`.

Prompts live in `bot/prompts/*.md` and are mounted into the container: edits apply on the next
model call, no restart needed.

## Update

Re-run the install command, or by hand:

```bash
git pull                        # ZimaOS without git: docker run --rm -v "$PWD":/w -w /w alpine/git pull
docker compose up -d --build    # migrations in migrations/ are applied on bot start
```

## Rollback

```bash
git checkout <previous commit>
docker compose up -d --build
```

Migrations only add things; if a rollback crosses a migration, restore the backup taken before the update.

## Backup and restore

The bot backs up daily at `BACKUP_CRON` (default 04:30) into `backups/<date>_<time>/`:
`notes.db` (consistent copy via the SQLite backup API) and `media.tar` once media exist.
The newest `BACKUP_KEEP` (14) are kept. Manual backup: `./scripts/backup.sh`.
Models are not backed up: `./scripts/download-models.sh` fetches them again.

Restore:

```bash
docker compose stop bot
mv data/notes.db data/notes.db.broken; rm -f data/notes.db-wal data/notes.db-shm
cp backups/<date>_<time>/notes.db data/notes.db
[ -f backups/<date>_<time>/media.tar ] && tar -xf backups/<date>_<time>/media.tar -C data
docker compose start bot
```

Moving to another server: copy the whole project folder (`data/` included) and run `docker compose up -d`.

## Stage 2 acceptance on the server

| Check | How |
|---|---|
| Ack < 1 s, report ≤ 60 s with a cold model | Send a note after `curl -X POST localhost:9292/api/models/unload` |
| 20 notes → ≤ 7 topics, ≥ 15 where expected | Send the notes from [test-notes.md](test-notes.md) one by one, then `/topics` |
| "Wrong topic" sticks | Move a note with ↪️, send a similar note, check its topic |
| /find < 1 s; /ask streams within 15 s warm | `/find катализатор`; `/ask` twice in a row |
| Honest "not in notes" | `/ask какой у меня размер обуви?` |
| Strangers ignored | Message the bot from another account: no reply, `ignored update` in `logs/bot.log` |
| 0 MB VRAM after 10 min idle | `nvidia-smi --query-gpu=memory.used --format=csv` |
| RAM ≤ 1.5 GB idle, ≤ 4 GB with 9B | `docker stats --no-stream` |
| Restart keeps notes; restore works | `docker compose down && docker compose up -d`; restore once as above |
| **Stage 3:** facts and contradictions | Send «катализатор на Kia Soul: ремонт 9 тысяч», later «теперь ремонт 12 тысяч по Kia Soul»; `/entities` → Kia Soul shows the old fact struck through |
| Tasks and reminders | «спросить у Сергея контакты мастера в пятницу» → task with Friday's date in the report and in `/todo`; a reminder arrives at 09:00 on Thursday and Friday |
| Edits by reply | Reply to a note report: «перенеси в …», «назови …», «тег …», «это на пятницу», «объедини с заметкой про …» (asks to confirm), «удали», or any extra detail (appended to the note) |
| Tests green | `docker compose run --rm --no-deps --user 0 -v ./tests:/app/tests -v ./pytest.ini:/app/pytest.ini bot sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q -p no:cacheprovider tests"` |
