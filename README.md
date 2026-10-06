# WhaleVault: a smart-notes bot on a local model

A "second memory" Telegram bot: it takes text, voice messages, links and photos and sorts them into
topics with a local model (llama.cpp + llama-swap on a Tesla P4). A Notion-style web UI is for
reading and search.

Status: **stage 3, entities and tasks** (code done and tested against a mock model; stages 1–3 still need
to be verified on the server).

What works: text notes and forwards → cleanup → topic, title, summary, tags → embeddings, similar notes,
duplicate warning; buttons "wrong topic" (with feedback learning) and "delete"; /topics, /find (FTS + vectors,
RRF), /ask with streaming and source buttons, /inbox, /stats; daily backup; GPU log; night unload.
Stage 3: entities (people, cars, projects, places) with atomic facts and explicit contradictions, /entities;
tasks with deadlines, reminders at 09:00 on the due day and the day before, /todo; edits in plain language
by replying to the bot's message about a note (move, rename, merge, tag, delete, set a date, or add details).

```bash
pip install -r requirements-dev.txt && python -m pytest -q   # tests with a mock model, no GPU needed
```

## Install on the server (ZimaOS or any Linux with Docker + NVIDIA)

Over SSH, one command (re-run it later to update):

```bash
curl -fsSL https://raw.githubusercontent.com/MykytaKyt/WhaleVault/main/scripts/install.sh | sudo bash
```

It asks for the bot token and your Telegram id, checks the GPU, downloads the models (~10 GB) and starts
the containers. On ZimaOS everything goes to `/DATA/AppData/notes-bot`.

- Setup and operations: [docs/runbook.md](docs/runbook.md)
- Model choices and benchmarks: [docs/models.md](docs/models.md)
- Server environment: [docs/environment.md](docs/environment.md)
- Stage 2 acceptance notes: [docs/test-notes.md](docs/test-notes.md)
