"""Vector search over chunks_vec (sqlite-vec, cosine distance)."""
import sqlite3

import sqlite_vec


def knn_notes(conn: sqlite3.Connection, embedding: list[float], k: int = 20,
              exclude_note: int | None = None) -> list[tuple[int, float]]:
    """Nearest notes as (note_id, cosine similarity), best chunk per note, only processed notes."""
    rows = conn.execute(
        """SELECT c.note_id, v.distance FROM chunks_vec v
           JOIN chunks c ON c.chunk_id = v.chunk_id
           WHERE v.embedding MATCH ? AND k = ?
           ORDER BY v.distance""",
        (sqlite_vec.serialize_float32(embedding), k * 3),
    ).fetchall()
    best: dict[int, float] = {}
    for note_id, dist in rows:
        if note_id == exclude_note:
            continue
        sim = 1.0 - dist
        if sim > best.get(note_id, -2.0):
            best[note_id] = sim
    if not best:
        return []
    ok = {r[0] for r in conn.execute(
        f"SELECT id FROM notes WHERE status = 'done' AND id IN ({','.join('?' * len(best))})", list(best))}
    ranked = sorted(((n, s) for n, s in best.items() if n in ok), key=lambda x: -x[1])
    return ranked[:k]
