"""Step 5: chunks -> embeddings -> chunks_vec, similar-note links, duplicate detection."""
import re
import sqlite3
from dataclasses import dataclass

import sqlite_vec

from ..db.connection import Tx
from ..db.notes import delete_chunks
from ..deps import Deps
from ..search.vector import knn_notes

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def chunk_text(text: str, threshold: int = 500, target: int = 1000) -> list[str]:
    """Notes up to `threshold` chars are one chunk; longer ones are packed by paragraph/sentence
    into chunks of about `target` chars, with one sentence of overlap."""
    text = text.strip()
    if len(text) <= threshold:
        return [text] if text else []
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        pieces.extend(s.strip() for s in _SENTENCE.split(para) if s.strip())
    chunks, cur = [], []
    for p in pieces:
        while len(p) > target:  # a single huge "sentence"
            pieces_head, p = p[:target], p[target:]
            if cur:
                chunks.append(" ".join(cur))
                cur = []
            chunks.append(pieces_head)
        if cur and len(" ".join(cur)) + len(p) + 1 > target:
            chunks.append(" ".join(cur))
            cur = [cur[-1]] if len(cur[-1]) < target // 3 else []
        cur.append(p)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


@dataclass
class EmbedResult:
    similar: list[tuple[int, float]]
    duplicates: list[tuple[int, float]]


async def embed_note(deps: Deps, note_id: int) -> EmbedResult:
    s, conn = deps.settings, deps.conn
    note = conn.execute("SELECT title, clean_text, raw_text FROM notes WHERE id = ?", (note_id,)).fetchone()
    body = note["clean_text"] or note["raw_text"]
    chunks = chunk_text(body, s.chunk_chars, s.chunk_chars * 2)
    title = (note["title"] or "").strip()
    inputs = [f"{title}\n{c}" if title else c for c in chunks]
    vectors = await deps.llm.embed(inputs)

    with Tx(conn):
        delete_chunks(conn, note_id)
        for text, vec in zip(chunks, vectors):
            cid = conn.execute("INSERT INTO chunks(note_id, text) VALUES (?, ?)", (note_id, text)).lastrowid
            conn.execute("INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
                         (cid, sqlite_vec.serialize_float32(vec)))
        conn.execute("UPDATE notes SET embed_dirty = 0 WHERE id = ?", (note_id,))

    best: dict[int, float] = {}
    for vec in vectors:
        for nid, sim in knn_notes(conn, vec, s.similar_notes + 2, exclude_note=note_id):
            best[nid] = max(sim, best.get(nid, -1.0))
    similar = sorted(best.items(), key=lambda x: -x[1])[: s.similar_notes]
    save_links(conn, note_id, similar)
    duplicates = [(n, sim) for n, sim in similar if sim > s.duplicate_threshold]
    return EmbedResult(similar=similar, duplicates=duplicates)


def save_links(conn: sqlite3.Connection, note_id: int, similar: list[tuple[int, float]]) -> None:
    with Tx(conn):
        conn.execute("DELETE FROM links WHERE note_id = ?", (note_id,))
        for nid, sim in similar:
            conn.execute("INSERT OR REPLACE INTO links(note_id, related_note_id, score) VALUES (?, ?, ?)",
                         (note_id, nid, sim))
            conn.execute("INSERT OR REPLACE INTO links(note_id, related_note_id, score) VALUES (?, ?, ?)",
                         (nid, note_id, sim))
