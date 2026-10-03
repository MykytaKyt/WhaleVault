"""Hybrid search: FTS5 + vectors merged with Reciprocal Rank Fusion. Shared by Telegram and the web API."""
import asyncio
import logging
import sqlite3
from dataclasses import dataclass

from ..llm.client import LLMClient, LLMError
from . import fts, vector

log = logging.getLogger(__name__)
RRF_K = 60


def rrf(*rankings: list[int], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, note_id in enumerate(ranking):
            scores[note_id] = scores.get(note_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


@dataclass
class Hit:
    id: int
    title: str
    summary: str
    clean_text: str
    topic: str
    created_at: str
    score: float

    @property
    def first_line(self) -> str:
        text = (self.clean_text or "").strip()
        return text.splitlines()[0][:140] if text else ""


async def search(conn: sqlite3.Connection, llm: LLMClient, query: str, *, limit: int = 10,
                 candidates: int = 20, embed_timeout: float = 5.0) -> list[Hit]:
    text_ids = fts.search(conn, query, candidates)
    vec_ids: list[int] = []
    try:
        [emb] = await asyncio.wait_for(llm.embed([query]), embed_timeout)
        vec_ids = [n for n, _ in vector.knn_notes(conn, emb, candidates)]
    except (LLMError, asyncio.TimeoutError) as e:
        # Embedding server cold or down: full-text results are still useful
        log.warning("vector search skipped: %r", e)
    ranked = rrf(vec_ids, text_ids)[:limit]
    return load_hits(conn, ranked)


def load_hits(conn: sqlite3.Connection, ranked: list[tuple[int, float]]) -> list[Hit]:
    if not ranked:
        return []
    ids = [n for n, _ in ranked]
    rows = {r["id"]: r for r in conn.execute(
        f"""SELECT n.id, n.title, n.summary, coalesce(n.clean_text, n.raw_text) AS clean_text,
                   n.created_at, coalesce(t.name, '') AS topic
            FROM notes n LEFT JOIN topics t ON t.id = n.topic_id
            WHERE n.id IN ({','.join('?' * len(ids))})""", ids)}
    return [Hit(id=n, title=rows[n]["title"] or "", summary=rows[n]["summary"] or "",
                clean_text=rows[n]["clean_text"], topic=rows[n]["topic"], created_at=rows[n]["created_at"],
                score=s) for n, s in ranked if n in rows]
