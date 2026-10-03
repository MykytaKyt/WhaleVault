#!/usr/bin/env python3
"""Manual llama-swap check: /v1/chat/completions, JSON schema, /v1/embeddings, tokens/s benchmark.

Standard library only. Run via scripts/bench.sh (it finds a python for you).
Output: markdown to stdout and docs/bench/<date>.md, to be copied into docs/models.md.

The sample texts are deliberately Russian/Ukrainian: that is the language mix of real notes.
"""
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("LLM_URL", f"http://127.0.0.1:{os.environ.get('LLM_PORT', '9292')}")
ROUTINE = os.environ.get("ROUTINE_MODEL_NAME", "routine")
ANSWER = os.environ.get("ANSWER_MODEL_NAME", "answer")
EMBED = os.environ.get("EMBED_MODEL_NAME", "embed")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))

NOTE = (
    "ну короче, в субботу заехал на сто по кіа соул, сказали що каталізатор забитий, "
    "ремонт десь 9 тисяч гривень, треба до кінця місяця вирішити. ещё спросить у Сергея контакты мастера"
)
LONG_PROMPT = (
    "Напиши подробный план на 10 пунктов, как вести личную базу заметок: "
    "сбор, сортировка по темам, регулярный обзор, поиск. Каждый пункт 2–3 предложения."
)

lines: list[str] = []


def out(s: str = "") -> None:
    print(s, flush=True)
    lines.append(s)


def post(path: str, body: dict, timeout: float = 600) -> tuple[dict, float]:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data, time.monotonic() - t0


def unload() -> None:
    for method, path in (("POST", "/api/models/unload"), ("GET", "/unload")):
        try:
            urllib.request.urlopen(urllib.request.Request(BASE + path, method=method), timeout=60)
            return
        except urllib.error.HTTPError:
            continue


def vram() -> str:
    if not shutil.which("nvidia-smi"):
        return "n/a"
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,pstate,power.draw,temperature.gpu", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() or r.stderr.strip()


def ram() -> str:
    if not shutil.which("docker"):
        return "n/a"
    r = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
        capture_output=True, text=True,
    )
    return "; ".join(x for x in r.stdout.splitlines() if "notes" in x) or "n/a"


def chat(model: str, content: str, max_tokens: int, **extra) -> tuple[dict, float]:
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "temperature": 0.3, **extra}
    return post("/v1/chat/completions", body)


def speed(data: dict) -> tuple[str, str, int]:
    t = data.get("timings") or {}
    pp = t.get("prompt_per_second")
    tg = t.get("predicted_per_second")
    n = (data.get("usage") or {}).get("completion_tokens", 0)
    f = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"
    return f(pp), f(tg), n


def ttft_stream(model: str, content: str) -> float:
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": 64, "stream": True}
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("data:") and '"content"' in line and line != "data: [DONE]":
                return time.monotonic() - t0
    return float("nan")


def bench_chat(model: str) -> None:
    out(f"### {model}")
    out()
    unload()
    time.sleep(3)
    data, cold = chat(model, "Ответь одним словом: столица Украины?", 16)
    out(f"- Cold start (load into VRAM + short answer): **{cold:.1f} s**")
    out(f"- VRAM after load: `{vram()}`")
    out(f"- Container RAM: `{ram()}`")
    data, wall = chat(model, LONG_PROMPT, 400)
    pp, tg, n = speed(data)
    text = data["choices"][0]["message"].get("content") or ""
    out(f"- Warm model: prompt **{pp} tok/s**, generation **{tg} tok/s** ({n} tokens in {wall:.1f} s)")
    out(f"- Time to first token (streaming, warm): **{ttft_stream(model, 'Привет! Как дела?'):.2f} s**")
    think = "<think>" in text or bool(data["choices"][0]["message"].get("reasoning_content"))
    out(f"- Thinking in the answer: {'**PRESENT** - check --chat-template-kwargs' if think else 'none'}")
    out()


def bench_schema() -> None:
    out(f"### JSON schema ({ROUTINE})")
    out()
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "tasks": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "due": {"type": ["string", "null"]}},
                "required": ["text", "due"]}},
        },
        "required": ["title", "summary", "tags", "tasks"],
    }
    prompt = ("Tag the user's note. Write the title and summary in the note's language.\n\nNote:\n" + NOTE)
    data, wall = chat(ROUTINE, prompt, 400, temperature=0.1, response_format={
        "type": "json_schema", "json_schema": {"name": "note", "strict": True, "schema": schema}})
    raw = data["choices"][0]["message"].get("content") or ""
    try:
        obj = json.loads(raw)
        valid = all(k in obj for k in schema["required"])
    except json.JSONDecodeError:
        obj, valid = None, False
    pp, tg, n = speed(data)
    out(f"- Valid JSON per schema: **{'yes' if valid else 'NO'}**, {wall:.1f} s, generation {tg} tok/s")
    out("```json")
    out(json.dumps(obj, ensure_ascii=False, indent=2) if obj else raw[:1000])
    out("```")
    out()


def bench_embed() -> None:
    out(f"### Embeddings ({EMBED})")
    out()
    texts = [
        "Каталізатор на Кіа Соул забитий, ремонт коштує 9 тисяч",       # Ukrainian
        "У Kia Soul забит катализатор, ремонт стоит девять тысяч",     # Russian, same meaning
        "Научрук попросил переписать введение к статье до пятницы",    # Russian, unrelated
    ]
    _, cold = post("/v1/embeddings", {"model": EMBED, "input": texts[:1]})
    t0 = time.monotonic()
    data, _ = post("/v1/embeddings", {"model": EMBED, "input": texts})
    warm = time.monotonic() - t0
    vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    dim = len(vecs[0])
    out(f"- Dimension: **{dim}** ({'ok' if dim == EMBED_DIM else 'does NOT match EMBED_DIM'})")
    out(f"- First request (incl. load): {cold:.1f} s; 3 texts on the warm model: {warm * 1000:.0f} ms")
    out(f"- cos(uk, ru - same meaning) = **{cos(vecs[0], vecs[1]):.3f}**, cos(uk, unrelated) = **{cos(vecs[0], vecs[2]):.3f}**")
    out(f"- VRAM with embeddings running: `{vram()}` (with EMBED_CUDA_VISIBLE=-1 embeddings use no VRAM)")
    out()


def main() -> int:
    try:
        urllib.request.urlopen(BASE + "/v1/models", timeout=10).read()
    except Exception as e:  # noqa: BLE001
        print(f"llama-swap is not reachable at {BASE}: {e}", file=sys.stderr)
        return 1
    out(f"## Benchmark {dt.datetime.now():%Y-%m-%d %H:%M}")
    out()
    out(f"- VRAM before start: `{vram()}`")
    out()
    bench_chat(ROUTINE)
    bench_schema()
    bench_chat(ANSWER)
    bench_embed()
    unload()
    time.sleep(5)
    out(f"- After /api/models/unload: VRAM `{vram()}`, RAM `{ram()}`")
    os.makedirs("docs/bench", exist_ok=True)
    path = f"docs/bench/{dt.date.today():%Y-%m-%d}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nWritten to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
