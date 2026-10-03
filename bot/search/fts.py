"""Full-text search over notes_fts (FTS5, unicode61)."""
import re
import sqlite3

_WORD = re.compile(r"\w+", re.U)


def _terms(query: str) -> list[str]:
    """Prefix terms with crude stemming: long words lose their last two letters so that
    inflected forms match ("катализатора" -> "катализато*" matches "катализатор")."""
    out = []
    for w in _WORD.findall(query.lower()):
        if len(w) < 2:
            continue
        stem = w[:-2] if len(w) >= 6 else w
        out.append('"' + stem.replace('"', "") + '"*')
    return list(dict.fromkeys(out))


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[int]:
    terms = _terms(query)
    if not terms:
        return []
    sql = ("SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? "
           "ORDER BY bm25(notes_fts, 3.0, 2.0, 1.0) LIMIT ?")
    ids = [r[0] for r in conn.execute(sql, (" AND ".join(terms), limit))]
    if len(ids) < limit and len(terms) > 1:
        # Not enough documents contain every word: fill up with any-word matches
        for r in conn.execute(sql, (" OR ".join(terms), limit)):
            if r[0] not in ids:
                ids.append(r[0])
    return ids[:limit]
