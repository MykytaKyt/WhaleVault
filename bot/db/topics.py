"""Topics and topic-correction feedback."""
import re
import sqlite3
import unicodedata

from .connection import Tx

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ё": "e", "ж": "zh",
    "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
})


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKC", name).lower().translate(_TRANSLIT)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "topic"


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def list_topics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM topics ORDER BY notes_count DESC, name").fetchall()


def get_topic(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()


def find_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    key = normalize_name(name)
    for t in conn.execute("SELECT * FROM topics"):
        if normalize_name(t["name"]) == key:
            return t
    return None


def create_topic(conn: sqlite3.Connection, name: str, description: str = "", emoji: str = "") -> int:
    """Create a topic or return the existing one with the same (normalized) name."""
    existing = find_by_name(conn, name)
    if existing:
        return existing["id"]
    base = slugify(name)
    slug, i = base, 2
    while conn.execute("SELECT 1 FROM topics WHERE slug = ?", (slug,)).fetchone():
        slug, i = f"{base}-{i}", i + 1
    cur = conn.execute(
        "INSERT INTO topics(name, slug, description, emoji) VALUES (?, ?, ?, ?)",
        (name.strip(), slug, description.strip(), emoji.strip()),
    )
    return cur.lastrowid


def recount(conn: sqlite3.Connection, *topic_ids: int | None) -> None:
    for tid in {t for t in topic_ids if t}:
        conn.execute(
            "UPDATE topics SET notes_count = (SELECT count(*) FROM notes WHERE topic_id = ? AND status = 'done'),"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (tid, tid),
        )


def move_note(conn: sqlite3.Connection, note_id: int, to_topic_id: int, record_feedback: bool = True) -> None:
    with Tx(conn):
        row = conn.execute("SELECT topic_id FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise KeyError(note_id)
        from_id = row["topic_id"]
        if from_id == to_topic_id:
            return
        conn.execute(
            "UPDATE notes SET topic_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (to_topic_id, note_id),
        )
        if record_feedback:
            conn.execute(
                "INSERT INTO feedback(note_id, from_topic_id, to_topic_id) VALUES (?, ?, ?)",
                (note_id, from_id, to_topic_id),
            )
        recount(conn, from_id, to_topic_id)


def recent_feedback(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Last corrections, as examples for the classification prompt."""
    return conn.execute(
        """SELECT n.title, n.summary, n.clean_text, ft.name AS from_name, tt.name AS to_name
           FROM feedback f
           JOIN notes n ON n.id = f.note_id
           LEFT JOIN topics ft ON ft.id = f.from_topic_id
           JOIN topics tt ON tt.id = f.to_topic_id
           ORDER BY f.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def update_topic(conn: sqlite3.Connection, topic_id: int, *, name: str | None = None,
                 description: str | None = None, emoji: str | None = None) -> None:
    fields, values = [], []
    for col, val in (("name", name), ("description", description), ("emoji", emoji)):
        if val is not None:
            fields.append(f"{col} = ?")
            values.append(val.strip())
    if fields:
        conn.execute(f"UPDATE topics SET {', '.join(fields)}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                     f"WHERE id = ?", (*values, topic_id))


def merge_topics(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    """Move every note of source into target and delete source. Returns the number of notes moved.
    Not recorded as feedback: it's a reorganisation, not a classification mistake."""
    if source_id == target_id:
        return 0
    with Tx(conn):
        moved = conn.execute("UPDATE notes SET topic_id = ? WHERE topic_id = ?", (target_id, source_id)).rowcount
        conn.execute("UPDATE feedback SET from_topic_id = ? WHERE from_topic_id = ?", (target_id, source_id))
        conn.execute("UPDATE feedback SET to_topic_id = ? WHERE to_topic_id = ?", (target_id, source_id))
        conn.execute("DELETE FROM topics WHERE id = ?", (source_id,))
        recount(conn, target_id)
    return moved
