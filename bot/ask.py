"""RAG for /ask. Shared by Telegram and the web API (SSE)."""
import json
import re
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .deps import Deps
from .llm.prompts import render
from .search.hybrid import Hit, search

NOT_FOUND = "В заметках этого нет."
_CITE = re.compile(r"\[#(\d+)\]")


def estimate_tokens(text: str) -> int:
    # Cyrillic with Qwen's tokenizer is roughly 3 characters per token; err on the safe side
    return len(text) // 3 + 1


def note_block(h: Hit, full: bool) -> str:
    body = h.clean_text if full else (h.summary or h.clean_text[:300])
    return f"[#{h.id}] {h.created_at[:10]} · тема: {h.topic or '—'} · {h.title}\n{body}"


def build_context(hits: list[Hit], budget_tokens: int) -> str:
    """Full text for every note; if over budget, shrink to summaries starting from the least relevant."""
    full = [True] * len(hits)
    blocks = lambda: [note_block(h, f) for h, f in zip(hits, full)]
    i = len(hits) - 1
    while estimate_tokens("\n\n".join(blocks())) > budget_tokens and i >= 0:
        full[i] = False
        i -= 1
    out = blocks()
    while out and estimate_tokens("\n\n".join(out)) > budget_tokens:
        out.pop()  # even summaries don't fit: drop the least relevant
    return "\n\n".join(out)


def cited_ids(answer: str, hits: list[Hit]) -> list[int]:
    allowed = {h.id for h in hits}
    return [n for n in dict.fromkeys(int(m) for m in _CITE.findall(answer)) if n in allowed]


@dataclass
class AskPlan:
    question: str
    hits: list[Hit]
    messages: list[dict]


async def plan(deps: Deps, question: str) -> AskPlan:
    s = deps.settings
    hits = await search(deps.conn, deps.llm, question, limit=s.ask_top_notes, candidates=s.ask_candidates)
    if not hits:
        return AskPlan(question, [], [])
    entity = ""  # entity pages are added in stage 3
    messages = render(s.prompts_dir, "ask", question=question, entity=entity,
                      notes=build_context(hits, s.ask_context_tokens))
    return AskPlan(question, hits, messages)


async def stream_answer(deps: Deps, p: AskPlan) -> AsyncIterator[str]:
    """Yield answer deltas. The caller must hold deps.gpu_lock."""
    if not p.hits:
        yield NOT_FOUND
        return
    async for piece in deps.llm.stream(deps.llm.answer, p.messages, thinking=deps.settings.ask_thinking,
                                       temperature=0.3, max_tokens=1200):
        yield piece


def save_ask(conn: sqlite3.Connection, question: str, answer: str, note_ids: list[int]) -> int:
    return conn.execute("INSERT INTO asks(question, answer, note_ids) VALUES (?, ?, ?)",
                        (question, answer, json.dumps(note_ids))).lastrowid
