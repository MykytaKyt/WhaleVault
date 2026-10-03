# WhaleVault: a smart-notes bot on a local model

A "second memory" Telegram bot: it takes text, voice messages, links and photos and sorts them into
topics with a local model (llama.cpp + llama-swap on a Tesla P4). A Notion-style web UI is for
reading and search.

Status: **stage 2, bot MVP** (code done and tested against a mock model; stages 1–2 still need to be
verified on the server).

What works: text notes and forwards → cleanup → topic, title, summary, tags → embeddings, similar notes,
duplicate warning; buttons "wrong topic" (with feedback learning) and "delete"; /topics, /find (FTS + vectors,
RRF), /ask with streaming and source buttons, /inbox, /stats; daily backup; GPU log; night unload.

```bash
pip install -r requirements-dev.txt && python -m pytest -q   # tests with a mock model, no GPU needed
```

- Setup and operations: [docs/runbook.md](docs/runbook.md)
- Model choices and benchmarks: [docs/models.md](docs/models.md)
- Server environment: [docs/environment.md](docs/environment.md)
- Stage 2 acceptance notes: [docs/test-notes.md](docs/test-notes.md)
