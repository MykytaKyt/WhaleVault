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


START, END = "\x02", "\x03"


def segments(marked: str) -> list[dict]:
    """"a \x02b\x03 c" -> [{t: "a ", hit: False}, {t: "b", hit: True}, {t: " c", hit: False}]"""
    out, hit = [], False
    for part in re.split(f"([{START}{END}])", marked):
        if part == START:
            hit = True
        elif part == END:
            hit = False
        elif part:
            out.append({"t": part, "hit": hit})
    return out


def snippets(conn: sqlite3.Connection, query: str, ids: list[int], tokens: int = 14) -> dict[int, dict]:
    """Highlighted title and text fragment for the given notes, where the query matches them."""
    terms = _terms(query)
    if not terms or not ids:
        return {}
    rows = conn.execute(
        f"""SELECT rowid, highlight(notes_fts, 0, ?, ?) AS title,
                   snippet(notes_fts, 2, ?, ?, '…', ?) AS text
            FROM notes_fts WHERE notes_fts MATCH ? AND rowid IN ({','.join('?' * len(ids))})""",
        (START, END, START, END, tokens, " OR ".join(terms), *ids)).fetchall()
    return {r[0]: {"title": segments(r[1]), "text": segments(r[2])} for r in rows}
