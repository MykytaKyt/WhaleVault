"""Tasks extracted from notes. due_at is local time: YYYY-MM-DD or YYYY-MM-DDTHH:MM."""
import sqlite3
from datetime import date, timedelta


def add_task(conn: sqlite3.Connection, note_id: int | None, text: str, due_at: str | None) -> int:
    return conn.execute("INSERT INTO tasks(note_id, text, due_at) VALUES (?, ?, ?)",
                        (note_id, text.strip(), due_at)).lastrowid


def get_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def open_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.* FROM tasks t LEFT JOIN notes n ON n.id = t.note_id
           WHERE t.status = 'open' AND (n.status IS NULL OR n.status NOT IN ('deleted', 'question'))
           ORDER BY t.due_at IS NULL, t.due_at, t.id""").fetchall()


def tasks_of_note(conn: sqlite3.Connection, note_id: int, only_open: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM tasks WHERE note_id = ?" + (" AND status = 'open'" if only_open else "") + " ORDER BY id"
    return conn.execute(sql, (note_id,)).fetchall()


def set_status(conn: sqlite3.Connection, task_id: int, status: str) -> None:
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))


def set_due(conn: sqlite3.Connection, task_id: int, due_at: str | None) -> None:
    conn.execute("UPDATE tasks SET due_at = ?, reminded_at = NULL WHERE id = ?", (due_at, task_id))


GROUPS = (("overdue", "🔴 Просрочено"), ("today", "🟠 Сегодня"), ("week", "🟡 На неделе"),
          ("later", "🟢 Позже"), ("nodate", "⚪ Без срока"))


def group(rows: list[sqlite3.Row], today: date) -> dict[str, list[sqlite3.Row]]:
    out: dict[str, list[sqlite3.Row]] = {k: [] for k, _ in GROUPS}
    for t in rows:
        if not t["due_at"]:
            out["nodate"].append(t)
            continue
        d = date.fromisoformat(t["due_at"][:10])
        key = ("overdue" if d < today else "today" if d == today
               else "week" if d <= today + timedelta(days=7) else "later")
        out[key].append(t)
    return out


def due_for_reminder(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    """Open tasks due today or tomorrow that haven't been reminded about today."""
    days = (today.isoformat(), (today + timedelta(days=1)).isoformat())
    return [t for t in open_tasks(conn)
            if t["due_at"] and t["due_at"][:10] in days and (t["reminded_at"] or "")[:10] != today.isoformat()]


def mark_reminded(conn: sqlite3.Connection, task_id: int, today: date) -> None:
    conn.execute("UPDATE tasks SET reminded_at = ? WHERE id = ?", (today.isoformat(), task_id))
