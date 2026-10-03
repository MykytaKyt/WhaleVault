#!/usr/bin/env python3
"""Ручная проверка llama-swap: /v1/chat/completions, JSON-схема, /v1/embeddings, замер токенов/с.

Только стандартная библиотека. Запускать через scripts/bench.sh (он сам найдёт python).
Результат: markdown в stdout и в docs/bench/<дата>.md — переносится в docs/models.md.
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
        return "н/д"
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,pstate,power.draw,temperature.gpu", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() or r.stderr.strip()


def ram() -> str:
    if not shutil.which("docker"):
        return "н/д"
    r = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
        capture_output=True, text=True,
    )
    return "; ".join(x for x in r.stdout.splitlines() if "notes" in x) or "н/д"


def chat(model: str, content: str, max_tokens: int, **extra) -> tuple[dict, float]:
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "temperature": 0.3, **extra}
    return post("/v1/chat/completions", body)


def speed(data: dict) -> tuple[str, str, int]:
    t = data.get("timings") or {}
    pp = t.get("prompt_per_second")
    tg = t.get("predicted_per_second")
    n = (data.get("usage") or {}).get("completion_tokens", 0)
    f = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else "н/д"
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
    out(f"- Холодный старт (загрузка в VRAM + короткий ответ): **{cold:.1f} с**")
    out(f"- VRAM после загрузки: `{vram()}`")
    out(f"- ОЗУ контейнеров: `{ram()}`")
    data, wall = chat(model, LONG_PROMPT, 400)
    pp, tg, n = speed(data)
    text = data["choices"][0]["message"].get("content") or ""
    out(f"- Прогретая модель: промпт **{pp} ток/с**, генерация **{tg} ток/с** ({n} токенов за {wall:.1f} с)")
    out(f"- Время до первого токена (стрим, прогретая): **{ttft_stream(model, 'Привет! Как дела?'):.2f} с**")
    think = "<think>" in text or bool(data["choices"][0]["message"].get("reasoning_content"))
    out(f"- Thinking в ответе: {'**ЕСТЬ** — проверить --chat-template-kwargs' if think else 'нет'}")
    out()


def bench_schema() -> None:
    out(f"### JSON-схема ({ROUTINE})")
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
    prompt = ("Разметь заметку пользователя. Заголовок и резюме — на языке заметки.\n\nЗаметка:\n" + NOTE)
    data, wall = chat(ROUTINE, prompt, 400, temperature=0.1, response_format={
        "type": "json_schema", "json_schema": {"name": "note", "strict": True, "schema": schema}})
    raw = data["choices"][0]["message"].get("content") or ""
    try:
        obj = json.loads(raw)
        valid = all(k in obj for k in schema["required"])
    except json.JSONDecodeError:
        obj, valid = None, False
    pp, tg, n = speed(data)
    out(f"- Валидный JSON по схеме: **{'да' if valid else 'НЕТ'}**, {wall:.1f} с, генерация {tg} ток/с")
    out("```json")
    out(json.dumps(obj, ensure_ascii=False, indent=2) if obj else raw[:1000])
    out("```")
    out()


def bench_embed() -> None:
    out(f"### Эмбеддинги ({EMBED})")
    out()
    texts = [
        "Каталізатор на Кіа Соул забитий, ремонт коштує 9 тисяч",       # укр
        "У Kia Soul забит катализатор, ремонт стоит девять тысяч",     # рус, тот же смысл
        "Научрук попросил переписать введение к статье до пятницы",    # рус, другое
    ]
    _, cold = post("/v1/embeddings", {"model": EMBED, "input": texts[:1]})
    t0 = time.monotonic()
    data, _ = post("/v1/embeddings", {"model": EMBED, "input": texts})
    warm = time.monotonic() - t0
    vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    dim = len(vecs[0])
    out(f"- Размерность: **{dim}** ({'ok' if dim == EMBED_DIM else 'НЕ совпадает с EMBED_DIM'})")
    out(f"- Первый запрос (с загрузкой): {cold:.1f} с; 3 текста прогретой моделью: {warm * 1000:.0f} мс")
    out(f"- cos(укр, рус — один смысл) = **{cos(vecs[0], vecs[1]):.3f}**, cos(укр, другое) = **{cos(vecs[0], vecs[2]):.3f}**")
    out(f"- VRAM при работающих эмбеддингах: `{vram()}` (при EMBED_CUDA_VISIBLE=-1 эмбеддинги VRAM не занимают)")
    out()


def main() -> int:
    try:
        urllib.request.urlopen(BASE + "/v1/models", timeout=10).read()
    except Exception as e:  # noqa: BLE001
        print(f"llama-swap недоступен на {BASE}: {e}", file=sys.stderr)
        return 1
    out(f"## Замер {dt.datetime.now():%Y-%m-%d %H:%M}")
    out()
    out(f"- VRAM до начала: `{vram()}`")
    out()
    bench_chat(ROUTINE)
    bench_schema()
    bench_chat(ANSWER)
    bench_embed()
    unload()
    time.sleep(5)
    out(f"- После /api/models/unload: VRAM `{vram()}`, ОЗУ `{ram()}`")
    os.makedirs("docs/bench", exist_ok=True)
    path = f"docs/bench/{dt.date.today():%Y-%m-%d}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nЗаписано в {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
