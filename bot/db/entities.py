"""Entities (people, cars, projects, places) and their atomic facts."""
import json
import re
import sqlite3

from .topics import _TRANSLIT

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
KINDS = ("person", "car", "project", "place", "other")
_WORD = re.compile(r"\w+", re.U)


def norm(name: str) -> str:
    return " ".join(_WORD.findall(name.casefold()))


# Looser than the slug table: Russian и and Ukrainian і both become i, г/ґ become g
_MATCH = {**_TRANSLIT, **str.maketrans({"и": "i", "і": "i", "ї": "i", "ы": "i", "й": "i", "г": "g", "ґ": "g",
                                         "є": "e", "э": "e", "ё": "e", "ю": "yu", "я": "ya"})}


def latin(text: str) -> str:
    """Cyrillic -> Latin, so «Киа Соул», «Кіа Соул» and «Kia Soul» compare equal."""
    return norm(text).translate(_MATCH)


def _aliases(row: sqlite3.Row) -> list[str]:
    try:
        return [a for a in json.loads(row["aliases"] or "[]") if isinstance(a, str)]
    except ValueError:
        return []


def names_of(row: sqlite3.Row) -> list[str]:
    return [row["name"], *_aliases(row)]


def get_entity(conn: sqlite3.Connection, entity_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()


def find_entity(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    key = norm(name)
    if not key:
        return None
    rows = conn.execute("SELECT * FROM entities").fetchall()
    for row in rows:
        if any(norm(n) == key for n in names_of(row)):
            return row
    key = latin(name)
    for row in rows:
        if any(latin(n) == key for n in names_of(row)):
            return row
    return None


def upsert_entity(conn: sqlite3.Connection, name: str, kind: str, aliases: list[str] = ()) -> int:
    """Find by name or any alias (case-insensitive), else create. New aliases are merged in."""
    kind = kind if kind in KINDS else "other"
    row = find_entity(conn, name) or next((r for a in aliases if (r := find_entity(conn, a))), None)
    if row is None:
        extra = [a.strip() for a in dict.fromkeys(aliases) if a.strip() and norm(a) != norm(name)]
        return conn.execute("INSERT INTO entities(name, kind, aliases) VALUES (?, ?, ?)",
                            (name.strip(), kind, json.dumps(extra, ensure_ascii=False))).lastrowid
    known = {norm(n) for n in names_of(row)}
    new = [a.strip() for a in (name, *aliases) if a.strip() and norm(a) not in known]
    if new:
        merged = _aliases(row) + list(dict.fromkeys(new))
        conn.execute(f"UPDATE entities SET aliases = ?, updated_at = {NOW} WHERE id = ?",
                     (json.dumps(merged, ensure_ascii=False), row["id"]))
    return row["id"]


def add_fact(conn: sqlite3.Connection, entity_id: int, note_id: int | None, text: str,
             replaces_fact_id: int | None = None) -> int:
    """Add a fact. A contradiction is a new fact; the old one gets superseded_by = new id."""
    fid = conn.execute("INSERT INTO facts(entity_id, note_id, text) VALUES (?, ?, ?)",
                       (entity_id, note_id, text.strip())).lastrowid
    if replaces_fact_id:
        conn.execute("UPDATE facts SET superseded_by = ? WHERE id = ? AND id != ? AND superseded_by IS NULL",
                     (fid, replaces_fact_id, fid))
    conn.execute(f"UPDATE entities SET updated_at = {NOW} WHERE id = ?", (entity_id,))
    return fid


def _stem(word: str) -> str:
    return word[: max(3, len(word) - 2)] if len(word) > 4 else word


def mentioned(conn: sqlite3.Connection, text: str) -> list[sqlite3.Row]:
    """Entities whose name or alias occurs in the text (all words, inflection-tolerant)."""
    words = _WORD.findall(text.casefold())
    words_lat = latin(text).split()
    out = []
    for row in conn.execute("SELECT * FROM entities ORDER BY updated_at DESC"):
        for n in names_of(row):
            for parts, ws in ((_WORD.findall(n.casefold()), words), (latin(n).split(), words_lat)):
                parts = [p for p in parts if len(p) >= 2]
                if parts and all(any(w.startswith(_stem(p)) for w in ws) for p in parts):
                    out.append(row)
                    break
            else:
                continue
            break
    return out


def current_facts(conn: sqlite3.Connection, entity_id: int, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM facts WHERE entity_id = ? AND superseded_by IS NULL ORDER BY id DESC LIMIT ?",
        (entity_id, limit)).fetchall()


def known_block(conn: sqlite3.Connection, text: str, limit: int = 40) -> str:
    """Prompt block: known entities, plus current facts (with ids) of those mentioned in the text."""
    rows = conn.execute("SELECT * FROM entities ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return "(none yet)"
    lines = []
    for r in rows:
        aliases = _aliases(r)
        lines.append(f"- {r['name']} ({r['kind']})" + (f", also: {', '.join(aliases)}" if aliases else ""))
    hit = mentioned(conn, text)
    if hit:
        lines.append("\nKnown facts about entities mentioned in this note:")
        for r in hit:
            for f in current_facts(conn, r["id"]):
                lines.append(f"- fact_id={f['id']} [{r['name']}] {f['created_at'][:10]}: {f['text']}")
    return "\n".join(lines)


def list_entities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.*, (SELECT count(*) FROM facts f WHERE f.entity_id = e.id AND f.superseded_by IS NULL) AS facts_count
           FROM entities e ORDER BY e.kind, e.name""").fetchall()


def facts_for_page(conn: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
    """All facts, oldest first, with the replacing fact's text for explicit contradictions."""
    return conn.execute(
        """SELECT f.*, n.title AS note_title, s.text AS superseded_text, s.created_at AS superseded_at
           FROM facts f
           LEFT JOIN notes n ON n.id = f.note_id
           LEFT JOIN facts s ON s.id = f.superseded_by
           WHERE f.entity_id = ? AND (n.status IS NULL OR n.status NOT IN ('deleted', 'question'))
           ORDER BY f.created_at, f.id""", (entity_id,)).fetchall()


def facts_of_note(conn: sqlite3.Connection, note_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.text, e.name AS entity FROM facts f JOIN entities e ON e.id = f.entity_id
           WHERE f.note_id = ? ORDER BY f.id""", (note_id,)).fetchall()
