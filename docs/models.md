# Models

All names, files, context sizes and ports live in `.env`; launch flags live in `llama-swap.yaml`.
Switching a model = edit `.env` + `./scripts/download-models.sh` + `docker compose up -d llm`.

## Choices

| Role | Spec | Chosen | Source | Size (est.) |
|---|---|---|---|---|
| Routine: cleanup, tagging, facts | Qwen 3.5 3.8B Q4_K_M | **Qwen3.5-4B** Q4_K_M | `unsloth/Qwen3.5-4B-GGUF` | ~2.7 GB |
| Answers: /ask, cleanup, overviews | Qwen 3.5 9B Q4_K_M | **Qwen3.5-9B** Q4_K_M | `unsloth/Qwen3.5-9B-GGUF` | ~5.7 GB |
| Draft for speculative decoding | Qwen 3.5 0.8B | **Qwen3.5-0.8B** Q4_K_M (stage 7) | `unsloth/Qwen3.5-0.8B-GGUF` | ~0.6 GB |
| Embeddings | bge-m3 | **bge-m3** Q8_0, 1024 dims | `ggml-org/bge-m3-Q8_0-GGUF` | ~0.6 GB |

About 9.6 GB on disk in total (spec limit: 15 GB).

Rationale:

- **3.8B → 4B.** The Qwen3.5 series has no 3.8B model; its small models are 0.8B, 2B, 4B and 9B.
  4B is the closest. If the file names on Hugging Face differ, `download-models.sh` lists the
  repo's files; fix `.env` and this table.
- **Qwen3.5 is multimodal**, but the vision projector (`mmproj`) is not loaded, so the model runs
  text-only and takes no extra VRAM. Per the spec, photos go through tesseract.
- **Thinking.** Qwen3.5 thinks by default. `llama-swap.yaml` sets
  `--chat-template-kwargs '{"enable_thinking":false}'` for both models; for /ask the bot enables it
  in the request itself when `ASK_THINKING=1`.
- **Embeddings on CPU.** The process starts with `CUDA_VISIBLE_DEVICES=-1`, so even the CUDA build of
  llama.cpp creates no context on the GPU: embeddings hold no VRAM and don't keep the P4 out of idle.
- **VRAM.** 9B Q4_K_M ≈ 5.7 GB of weights + KV cache. Qwen3.5 is a hybrid architecture: only the
  full-attention layers need KV, so 12k context in q8_0 is a few hundred MB. 8 GB is enough.

## Engine and Pascal

- The prebuilt `ghcr.io/mostlygeek/llama-swap:cuda` image is based on `ggml-org/llama.cpp:server-cuda`
  (CUDA 12.8). For CUDA below 13, llama.cpp builds `61-virtual`, i.e. PTX that the driver compiles
  for the P4 on first load. Therefore:
  - the driver must be **≥ 570** (CUDA 12.8);
  - the first model load may take minutes. The result is cached in `data/cache/cuda`
    (`CUDA_CACHE_PATH`), later loads are fast.
- `unified-cuda13` images **won't work**: CUDA 13 dropped Pascal.
- Fallback: `llm/Dockerfile` builds llama.cpp for `sm_61` on CUDA 12.4 (driver ≥ 550) plus the
  llama-swap binary. Enable with `LLM_IMAGE=notes-llm:pascal`.

## Risks to verify on the hardware

- **Speculative decoding (stage 7).** Qwen3.5 is a hybrid model with recurrent layers (Gated DeltaNet).
  llama.cpp got draft-model support for such models later than for plain transformers, and it may
  bring no speedup. Measure in stage 7; if there is no gain, report it and leave it off.
- **Speed.** The spec's figures (~35 tok/s for 4B, ~20 tok/s for 9B) are estimates. Real numbers go below.

## Measurements

2026-10-05, ZimaOS, Tesla P4, driver 580.105.08, prebuilt `ghcr.io/mostlygeek/llama-swap:cuda`
(full output: [bench/2026-10-05.md](bench/2026-10-05.md)).

| Model | Cold start, s | Prompt, tok/s | Generation, tok/s | Time to first token, s | VRAM, MB |
|---|---|---|---|---|---|
| routine (Qwen3.5-4B Q4_K_M) | 40.2* | 359 | 35.7 | 0.18 | 3107 |
| answer (Qwen3.5-9B Q4_K_M, 12k, KV q8_0) | 15.5 | 206 | 19.7 | 0.24 | 5357 |
| embed (bge-m3 Q8_0, CPU) | 3.4 | — | — | — | 0 |

\* The very first model load ever: includes JIT compilation of PTX for sm_61, cached in `data/cache/cuda`.
The 9B, loaded second, took 15.5 s.

Findings:

- **Pascal works with the prebuilt image.** Driver 580 runs the CUDA 12.8 image; the fallback build is not needed.
- **Speed matches the spec** (~35 tok/s for routine, ~20 tok/s for answer). JSON-schema output is valid at 34 tok/s.
- **Idle power.** After unload the card returns to P8 at 7–8 W with 0 MiB used, so `nvidia-pstated` is not needed.
- **Embeddings** separate meaning across Russian and Ukrainian well: 0.85 for the same sentence in both
  languages vs 0.35 for an unrelated one; the 0.92 duplicate threshold is safely above cross-topic noise.
- **RAM.** `notes-llm` reports 2.5–2.7 GiB of its 3 GiB limit with a model loaded and 0.9 GiB after unload.
  Most of it is page cache of the GGUF files (reclaimable, not process memory), but it sits close to the
  limit. To check on the server: `--no-mmap` on the GPU models in `llama-swap.yaml` should cut it, since
  the weights live in VRAM anyway.
