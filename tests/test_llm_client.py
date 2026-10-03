import json

import httpx
import pytest

from bot.llm.client import LLMClient, LLMError
from bot.llm.prompts import render
from bot.llm.schemas import NoteMarkup, json_schema

VALID = {"title": "Катализатор", "summary": "Забит.", "tags": ["авто"], "is_question": False,
         "topic": {"existing_topic_id": None, "new_topic_name": "Kia Soul", "new_topic_description": "машина",
                   "new_topic_emoji": "🚗", "reason": "нет подходящей"}}


def client(handler) -> LLMClient:
    http = httpx.AsyncClient(base_url="http://llm", transport=httpx.MockTransport(handler))
    return LLMClient("http://llm", routine="routine", answer="answer", embed="embed", http=http)


def completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_chat_json_sends_schema_and_retries_once():
    bodies = []

    def handler(req: httpx.Request):
        bodies.append(json.loads(req.content))
        return completion("{not json" if len(bodies) == 1 else json.dumps(VALID, ensure_ascii=False))

    m = await client(handler).chat_json("routine", [{"role": "user", "content": "x"}], NoteMarkup)
    assert m.topic.new_topic_name == "Kia Soul"
    assert len(bodies) == 2
    rf = bodies[0]["response_format"]
    assert rf["type"] == "json_schema" and "$ref" not in json.dumps(rf)
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert bodies[1]["messages"][-1]["role"] == "user"  # the retry explains the error


async def test_chat_json_gives_up_after_retry():
    with pytest.raises(LLMError):
        await client(lambda r: completion('{"title": ""}')).chat_json("routine", [], NoteMarkup)


async def test_chat_strips_think_and_fences():
    c = client(lambda r: completion("<think>hmm</think>\n```\nчистый текст\n```"))
    assert await c.chat("routine", []) == "чистый текст"


async def test_http_error_becomes_llm_error():
    with pytest.raises(LLMError):
        await client(lambda r: httpx.Response(503)).chat("routine", [])


async def test_stream_skips_inline_thinking():
    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n"
                  for p in ["<think>сек", "рет</think>Отв", "ет [#1]"]) + "data: [DONE]\n\n"
    c = client(lambda r: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
    assert "".join([p async for p in c.stream("answer", [])]) == "Ответ [#1]"


async def test_embed_and_llama_swap_extras():
    def handler(req: httpx.Request):
        if req.url.path == "/v1/embeddings":
            return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})
        if req.url.path == "/running":
            return httpx.Response(200, json={"running": [{"model": "answer", "state": "ready"}]})
        return httpx.Response(200)
    c = client(handler)
    assert await c.embed(["a", "b"]) == [[1, 0], [0, 1]]
    assert await c.running() == ["answer"]
    assert await c.unload()


async def test_running_unsupported_returns_none():
    assert await client(lambda r: httpx.Response(404)).running() is None


def test_schema_has_no_refs():
    s = json.dumps(json_schema(NoteMarkup))
    assert "$ref" not in s and "existing_topic_id" in s


def test_prompts_are_reread_on_every_call(tmp_path):
    (tmp_path / "p.md").write_text("system v1\n=== USER ===\nhi {{name}}", encoding="utf-8")
    assert render(tmp_path, "p", name="A")[1]["content"] == "hi A"
    (tmp_path / "p.md").write_text("system v2\n=== USER ===\nbye {{name}}", encoding="utf-8")
    msgs = render(tmp_path, "p", name="A")
    assert msgs[0]["content"] == "system v2" and msgs[1]["content"] == "bye A"
    with pytest.raises(KeyError):
        render(tmp_path, "p")


def test_repo_prompts_render(settings):
    for name, kw in [("clean", dict(text="t", context="")), ("clean_link", dict(text="t", context="")),
                     ("classify", dict(text="t", topics="-", feedback="-")),
                     ("ask", dict(text="t", question="q", notes="n", entity=""))]:
        assert len(render(settings.prompts_dir, name, **kw)) == 2
