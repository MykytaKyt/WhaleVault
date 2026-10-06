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
    link_message(conn, reply_id, note_id)


def set_status(conn: sqlite3.Connection, note_id: int, status: str, error: str | None = None) -> None:
    conn.execute(f"UPDATE notes SET status = ?, error = ?, updated_at = {NOW} WHERE id = ?", (status, error, note_id))


def bump_attempts(conn: sqlite3.Connection, note_id: int) -> int:
    conn.execute("UPDATE notes SET attempts = attempts + 1 WHERE id = ?", (note_id,))
    return conn.execute("SELECT attempts FROM notes WHERE id = ?", (note_id,)).fetchone()[0]


def pending_ids(conn: sqlite3.Connection, include_processing: bool = True) -> list[int]:
    """Notes waiting for the worker. After a restart 'processing' ones are pending too;
    while running, only 'queued' ones are (a 'processing' note is in the worker's hands)."""
    statuses = "('queued', 'processing')" if include_processing else "('queued')"
    return [r[0] for r in conn.execute(f"SELECT id FROM notes WHERE status IN {statuses} ORDER BY id")]


def set_clean_text(conn: sqlite3.Connection, note_id: int, clean_text: str) -> None:
    conn.execute(
        f"UPDATE notes SET clean_text = ?, embed_dirty = 1, updated_at = {NOW} WHERE id = ?",
        (clean_text, note_id),
    )


def apply_markup(conn: sqlite3.Connection, note_id: int, *, title: str, summary: str, topic_id: int | None,
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
            # facts/tasks reference notes with ON DELETE SET NULL; a purged note takes them along
            conn.execute("UPDATE facts SET superseded_by = NULL WHERE superseded_by IN "
                         "(SELECT id FROM facts WHERE note_id = ?)", (nid,))
            conn.execute("DELETE FROM facts WHERE note_id = ?", (nid,))
            conn.execute("DELETE FROM tasks WHERE note_id = ?", (nid,))
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


def link_message(conn: sqlite3.Connection, message_id: int, note_id: int) -> None:
    """Remember that a bot message shows this note (replies to it are edit commands)."""
    conn.execute("INSERT OR REPLACE INTO tg_messages(message_id, note_id) VALUES (?, ?)", (message_id, note_id))


def note_for_message(conn: sqlite3.Connection, message_id: int) -> int | None:
    row = conn.execute("SELECT note_id FROM tg_messages WHERE message_id = ?", (message_id,)).fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT id FROM notes WHERE tg_reply_id = ?", (message_id,)).fetchone()
    return row[0] if row else None


def mark_question(conn: sqlite3.Connection, note_id: int) -> None:
    """The user says a saved note is really a question: hide it from search until kept."""
    with Tx(conn):
        row = conn.execute("SELECT topic_id FROM notes WHERE id = ?", (note_id,)).fetchone()
        conn.execute(f"UPDATE notes SET status = 'question', updated_at = {NOW} WHERE id = ?", (note_id,))
        conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        if row:
            topics_db.recount(conn, row["topic_id"])


def list_notes(conn: sqlite3.Connection, *, cursor: str | None = None, limit: int = 50,
               topic_id: int | None = None) -> tuple[list[sqlite3.Row], str | None]:
    """Processed notes, newest first. cursor = "<created_at>|<id>" of the last row of the previous page."""
    where, args = ["n.status = 'done'"], []
    if topic_id is not None:
        where.append("n.topic_id = ?")
        args.append(topic_id)
    if cursor:
        created, _, nid = cursor.rpartition("|")
        where.append("(n.created_at < ? OR (n.created_at = ? AND n.id < ?))")
        args += [created, created, int(nid)]
    rows = conn.execute(
        f"""SELECT n.id, n.created_at, n.title, n.summary, n.source, n.topic_id,
                   substr(coalesce(n.clean_text, n.raw_text), 1, 300) AS preview,
                   t.name AS topic_name, t.emoji AS topic_emoji,
                   (SELECT group_concat(tg.tag, ',') FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id
                    WHERE nt.note_id = n.id) AS tags
            FROM notes n LEFT JOIN topics t ON t.id = n.topic_id
            WHERE {' AND '.join(where)}
            ORDER BY n.created_at DESC, n.id DESC LIMIT ?""", (*args, limit + 1)).fetchall()
    nxt = f"{rows[limit - 1]['created_at']}|{rows[limit - 1]['id']}" if len(rows) > limit else None
    return rows[:limit], nxt


def update_note(conn: sqlite3.Connection, note_id: int, *, title: str | None = None,
                clean_text: str | None = None) -> None:
    """Edits from the web UI. A changed clean_text needs new embeddings (embed_dirty)."""
    with Tx(conn):
        if title is not None:
            conn.execute(f"UPDATE notes SET title = ?, embed_dirty = 1, updated_at = {NOW} WHERE id = ?",
                         (title.strip(), note_id))
        if clean_text is not None:
            conn.execute(f"UPDATE notes SET clean_text = ?, embed_dirty = 1, updated_at = {NOW} WHERE id = ?",
                         (clean_text, note_id))
        sync_fts(conn, note_id)


def requeue(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute(f"UPDATE notes SET status = 'queued', attempts = 0, error = NULL, updated_at = {NOW} WHERE id = ?",
                 (note_id,))


def duplicate_pairs(conn: sqlite3.Connection, threshold: float, limit: int = 30) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT l.note_id AS a, l.related_note_id AS b, l.score, na.title AS a_title, nb.title AS b_title,
                  na.created_at AS a_created, nb.created_at AS b_created
           FROM links l JOIN notes na ON na.id = l.note_id JOIN notes nb ON nb.id = l.related_note_id
           WHERE l.note_id < l.related_note_id AND l.score > ? AND na.status = 'done' AND nb.status = 'done'
           ORDER BY l.score DESC LIMIT ?""", (threshold, limit)).fetchall()
