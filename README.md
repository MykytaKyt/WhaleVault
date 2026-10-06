# WhaleVault: a smart-notes bot on a local model

A "second memory" Telegram bot: it takes text, voice messages, links and photos and sorts them into
topics with a local model (llama.cpp + llama-swap on a Tesla P4). A Notion-style web UI is for
reading and search.

Status: **stage 4, web UI** (stages 1–3 run on the server; the web UI is tested against a mock model).

What works: text notes and forwards → cleanup → topic, title, summary, tags → embeddings, similar notes,
duplicate warning; buttons "wrong topic" (with feedback learning) and "delete"; /topics, /find (FTS + vectors,
RRF), /ask with streaming and source buttons, /inbox, /stats; daily backup; GPU log; night unload.
Stage 3: entities (people, cars, projects, places) with atomic facts and explicit contradictions, /entities;
tasks with deadlines, reminders at 09:00 on the due day and the day before, /todo; edits in plain language
by replying to the bot's message about a note (move, rename, merge, tag, delete, set a date, or add details).
Stage 4: a Notion-style web UI on the home network, phone first: topic cards with model-written summaries
(known facts, open questions, what changed this week), notes with properties and in-place edits, topic
merge/split, entities with contradictions to confirm, tasks, inbox, "Ask" with streaming, Ctrl/Cmd+K search,
and a dashboard (GPU, models, pipeline, database quality, energy). One password, light and dark themes.

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
