"""Notes: insert, status changes, markup, tags, FTS, soft delete."""
import sqlite3

from .connection import Tx
from . import topics as topics_db

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def insert_note(conn: sqlite3.Connection, source: str, raw_text: str, context: str = "",
                tg_message_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO notes(source, raw_text, context, tg_message_id) VALUES (?, ?, ?, ?)",
        (source, raw_text, context, tg_message_id),
    )
    return cur.lastrowid


def get_note(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT n.*, t.name AS topic_name, t.emoji AS topic_emoji
           FROM notes n LEFT JOIN topics t ON t.id = n.topic_id WHERE n.id = ?""",
        (note_id,),
    ).fetchone()


def set_reply_id(conn: sqlite3.Connection, note_id: int, reply_id: int) -> None:
    conn.execute("UPDATE notes SET tg_reply_id = ? WHERE id = ?", (reply_id, note_id))


def set_status(conn: sqlite3.Connection, note_id: int, status: str, error: str | None = None) -> None:
    conn.execute(f"UPDATE notes SET status = ?, error = ?, updated_at = {NOW} WHERE id = ?", (status, error, note_id))


def bump_attempts(conn: sqlite3.Connection, note_id: int) -> int:
    conn.execute("UPDATE notes SET attempts = attempts + 1 WHERE id = ?", (note_id,))
    return conn.execute("SELECT attempts FROM notes WHERE id = ?", (note_id,)).fetchone()[0]


def pending_ids(conn: sqlite3.Connection) -> list[int]:
    """Notes that must be (re)processed after a restart."""
    return [r[0] for r in conn.execute(
        "SELECT id FROM notes WHERE status IN ('queued', 'processing') ORDER BY id")]


def set_clean_text(conn: sqlite3.Connection, note_id: int, clean_text: str) -> None:
    conn.execute(
        f"UPDATE notes SET clean_text = ?, embed_dirty = 1, updated_at = {NOW} WHERE id = ?",
        (clean_text, note_id),
    )


def apply_markup(conn: sqlite3.Connection, note_id: int, *, title: str, summary: str, topic_id: int,
                 tags: list[str], status: str = "done") -> None:
    """Write the model's markup in one transaction and keep counters and FTS in sync."""
    with Tx(conn):
        old = conn.execute("SELECT topic_id FROM notes WHERE id = ?", (note_id,)).fetchone()
        conn.execute(
            f"UPDATE notes SET title = ?, summary = ?, topic_id = ?, status = ?, error = NULL,"
            f" updated_at = {NOW} WHERE id = ?",
            (title, summary, topic_id, status, note_id),
        )
        set_tags(conn, note_id, tags)
        topics_db.recount(conn, old["topic_id"] if old else None, topic_id)
        sync_fts(conn, note_id)


def set_tags(conn: sqlite3.Connection, note_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
    for tag in dict.fromkeys(t.strip().lstrip("#").lower() for t in tags if t.strip()):
        conn.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?)", (tag,))
        tag_id = conn.execute("SELECT id FROM tags WHERE tag = ?", (tag,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?, ?)", (note_id, tag_id))


def get_tags(conn: sqlite3.Connection, note_id: int) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT t.tag FROM note_tags nt JOIN tags t ON t.id = nt.tag_id WHERE nt.note_id = ? ORDER BY t.tag",
        (note_id,))]


def sync_fts(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
    row = conn.execute("SELECT title, summary, clean_text, raw_text, status FROM notes WHERE id = ?",
                       (note_id,)).fetchone()
    if row and row["status"] == "done":
        conn.execute(
            "INSERT INTO notes_fts(rowid, title, summary, clean_text) VALUES (?, ?, ?, ?)",
            (note_id, row["title"] or "", row["summary"] or "", row["clean_text"] or row["raw_text"]),
        )


def soft_delete(conn: sqlite3.Connection, note_id: int) -> None:
    with Tx(conn):
        row = conn.execute("SELECT topic_id FROM notes WHERE id = ?", (note_id,)).fetchone()
        conn.execute(f"UPDATE notes SET status = 'deleted', deleted_at = {NOW} WHERE id = ?", (note_id,))
        conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        if row:
            topics_db.recount(conn, row["topic_id"])


def restore(conn: sqlite3.Connection, note_id: int) -> None:
    """Undo a soft delete: back to done if it was processed, otherwise back to the queue."""
    with Tx(conn):
        row = conn.execute("SELECT topic_id, title FROM notes WHERE id = ?", (note_id,)).fetchone()
        status = "done" if row and row["title"] else "queued"
        conn.execute("UPDATE notes SET status = ?, deleted_at = NULL WHERE id = ?", (status, note_id))
        sync_fts(conn, note_id)
        if row:
            topics_db.recount(conn, row["topic_id"])


def purge_deleted(conn: sqlite3.Connection, days: int) -> int:
    """Physically remove notes soft-deleted more than `days` ago."""
    with Tx(conn):
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM notes WHERE status = 'deleted' AND deleted_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)",
            (f"-{int(days)} days",))]
        for nid in ids:
            delete_chunks(conn, nid)
            conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
    return len(ids)


def delete_chunks(conn: sqlite3.Connection, note_id: int) -> None:
    ids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunks WHERE note_id = ?", (note_id,))]
    for cid in ids:
        conn.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (cid,))
    conn.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))


def notes_in_topic(conn: sqlite3.Connection, topic_id: int, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, title, created_at FROM notes WHERE topic_id = ? AND status = 'done' ORDER BY created_at DESC LIMIT ?",
        (topic_id, limit),
    ).fetchall()


def failed_notes(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, raw_text, error, created_at FROM notes WHERE status = 'failed' ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def related(conn: sqlite3.Connection, note_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT l.related_note_id AS id, l.score, n.title FROM links l
           JOIN notes n ON n.id = l.related_note_id
           WHERE l.note_id = ? AND n.status = 'done' ORDER BY l.score DESC""",
        (note_id,),
    ).fetchall()


def stats(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "notes": q("SELECT count(*) FROM notes WHERE status = 'done'"),
        "queued": q("SELECT count(*) FROM notes WHERE status IN ('queued', 'processing')"),
        "failed": q("SELECT count(*) FROM notes WHERE status = 'failed'"),
        "topics": q("SELECT count(*) FROM topics WHERE notes_count > 0"),
        "chunks": q("SELECT count(*) FROM chunks"),
    }
