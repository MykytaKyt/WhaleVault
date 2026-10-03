# Runbook

The project lives in one folder (on ZimaOS `/DATA/AppData/notes-bot` is convenient). All state is in `data/`.

## First launch (stage 1)

```bash
git clone <repo> /DATA/AppData/notes-bot && cd /DATA/AppData/notes-bot
cp .env.example .env            # fill in PUID/PGID (id -u; id -g), TZ
./scripts/snapshot-env.sh       # -> docs/environment.md
./scripts/check-gpu.sh          # must end with "check-gpu passed"
./scripts/download-models.sh    # ~10 GB into data/models/
docker compose up -d llm
docker compose logs -f llm      # wait until llama-swap listens on :8080
./scripts/bench.sh              # API check and benchmark -> docs/bench/<date>.md
```

If `check-gpu.sh` reports that llama.cpp can't see the GPU:

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

## Updates, rollback, backup

To be written in stage 2 (cron backup of `data/`, restore procedure).
