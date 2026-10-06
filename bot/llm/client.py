"""Client for any OpenAI-compatible server (llama-swap/llama.cpp; Ollama also works).

The bot talks to models only through /v1/chat/completions and /v1/embeddings,
plus optional llama-swap extras (/running, /api/models/unload) that degrade gracefully.
"""
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .schemas import json_schema

log = logging.getLogger(__name__)
err_log = logging.getLogger("llm.errors")

T = TypeVar("T", bound=BaseModel)
_THINK = re.compile(r"<think>.*?</think>", re.S)


class LLMError(Exception):
    pass


def _strip(text: str) -> str:
    text = _THINK.sub("", text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?|\n?```$", "", text).strip()
    return text


class LLMClient:
    def __init__(self, base_url: str, *, routine: str, answer: str, embed: str, timeout: float = 600.0,
                 json_schema_enabled: bool = True, http: httpx.AsyncClient | None = None):
        self.routine, self.answer, self.embed_model = routine, answer, embed
        self.json_schema_enabled = json_schema_enabled
        self.http = http or httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout, connect=10))
        self.last_activity = 0.0  # monotonic time of the last chat request (for night unload)
        # Called after every model call with a dict (model, task, ok, cold, tokens, tps, ttft, seconds); see bot/metrics.py
        self.on_call: Callable[[dict[str, Any]], None] | None = None

    async def _cold(self, model: str) -> bool | None:
        """Will this call have to load the model first? Only checked when metrics are collected."""
        if self.on_call is None:
            return None
        running = await self.running()
        return None if running is None else model not in running

    def _report(self, **info: Any) -> None:
        if self.on_call is not None:
            try:
                self.on_call(info)
            except Exception:  # noqa: BLE001 — metrics must never break a model call
                log.exception("metrics hook failed")

    async def close(self) -> None:
        await self.http.aclose()

    def _body(self, model: str, messages: list[dict], thinking: bool, **params) -> dict:
        return {"model": model, "messages": messages,
                "chat_template_kwargs": {"enable_thinking": thinking}, **params}

    async def chat(self, model: str, messages: list[dict], *, thinking: bool = False, task: str = "other",
                   **params) -> str:
        self.last_activity = time.monotonic()
        cold = await self._cold(model)
        t0 = time.monotonic()
        try:
            r = await self.http.post("/v1/chat/completions", json=self._body(model, messages, thinking, **params))
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
        except (httpx.HTTPError, KeyError, ValueError) as e:
            err_log.error("chat %s failed: %r\nPROMPT:\n%s", model, e, json.dumps(messages, ensure_ascii=False, indent=1))
            self._report(model=model, task=task, ok=False, cold=cold, seconds=time.monotonic() - t0, error=str(e))
            raise LLMError(f"{model}: {e}") from e
        finally:
            self.last_activity = time.monotonic()
        usage, timings = data.get("usage") or {}, data.get("timings") or {}
        self._report(model=model, task=task, ok=True, cold=cold, seconds=time.monotonic() - t0,
                     prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                     tps=timings.get("predicted_per_second"),
                     # Without streaming, time to first token ~ prompt processing time
                     ttft=(timings["prompt_ms"] / 1000) if "prompt_ms" in timings else None)
        return _strip(content)

    async def chat_json(self, model: str, messages: list[dict], schema: type[T], *, retries: int = 1,
                        task: str = "other", **params) -> T:
        """Structured output: grammar-constrained by JSON schema, validated by pydantic, one retry on failure."""
        params.setdefault("temperature", 0.1)
        if self.json_schema_enabled:
            params["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": json_schema(schema)}}
        msgs = list(messages)
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            raw = await self.chat(model, msgs, task=task, **params)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_err = e
                self._report(model=model, task=task, ok=False, invalid_json=True)
                err_log.error("invalid %s from %s (attempt %d): %s\nPROMPT:\n%s\nRESPONSE:\n%s", schema.__name__,
                              model, attempt + 1, e, json.dumps(msgs, ensure_ascii=False, indent=1), raw)
                msgs = [*messages, {"role": "assistant", "content": raw},
                        {"role": "user", "content": f"The JSON is invalid: {e.errors(include_url=False)}. "
                                                    "Return corrected JSON only."}]
        raise LLMError(f"invalid {schema.__name__}: {last_err}")

    async def stream(self, model: str, messages: list[dict], *, thinking: bool = False, task: str = "other",
                     **params) -> AsyncIterator[str]:
        """Yield content deltas. Reasoning deltas (thinking mode) are skipped."""
        self.last_activity = time.monotonic()
        body = self._body(model, messages, thinking, stream=True, **params)
        in_think = False
        cold = await self._cold(model)
        t0, first, pieces, timings, ok = time.monotonic(), None, 0, {}, False
        try:
            async with self.http.stream("POST", "/v1/chat/completions", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    self.last_activity = time.monotonic()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    timings = chunk.get("timings") or timings
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if first is None and (delta.get("content") or delta.get("reasoning_content")):
                        first = time.monotonic() - t0
                    pieces += 1
                    piece = delta.get("content") or ""
                    # Servers without a reasoning parser send <think> inline
                    if "<think>" in piece:
                        in_think, piece = True, piece.split("<think>")[0]
                    if in_think:
                        if "</think>" in piece:
                            in_think, piece = False, piece.split("</think>", 1)[1]
                        else:
                            continue
                    if piece:
                        yield piece
            ok = True
        except (httpx.HTTPError, ValueError) as e:
            err_log.error("stream %s failed: %r\nPROMPT:\n%s", model, e, json.dumps(messages, ensure_ascii=False, indent=1))
            raise LLMError(f"{model}: {e}") from e
        finally:
            self.last_activity = time.monotonic()
            seconds = time.monotonic() - t0
            gen = seconds - (first or 0)
            self._report(model=model, task=task, ok=ok, cold=cold, seconds=seconds, ttft=first,
                         prompt_tokens=timings.get("prompt_n"), completion_tokens=timings.get("predicted_n") or pieces,
                         tps=timings.get("predicted_per_second") or (pieces / gen if ok and gen >= 0.5 else None))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        t0 = time.monotonic()
        try:
            r = await self.http.post("/v1/embeddings", json={"model": self.embed_model, "input": texts})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            err_log.error("embed failed: %r (%d texts)", e, len(texts))
            self._report(model=self.embed_model, task="embed", ok=False, seconds=time.monotonic() - t0)
            raise LLMError(f"embed: {e}") from e
        self._report(model=self.embed_model, task="embed", ok=True, seconds=time.monotonic() - t0, items=len(texts))
        return [d["embedding"] for d in data]

    async def running(self) -> list[str] | None:
        """Models currently loaded (llama-swap /running). None if the server doesn't support it."""
        try:
            r = await self.http.get("/running", timeout=5)
            r.raise_for_status()
            return [m.get("model", "") for m in r.json().get("running", []) if m.get("state", "ready") != "stopped"]
        except (httpx.HTTPError, ValueError):
            return None

    async def unload(self) -> bool:
        for method, path in (("POST", "/api/models/unload"), ("GET", "/unload")):
            try:
                r = await self.http.request(method, path, timeout=30)
                if r.status_code < 400:
                    return True
            except httpx.HTTPError:
                continue
        return False
