"""Edits in plain language: a reply to a bot message about a note becomes a command for that note."""
import logging
import sqlite3
from dataclasses import dataclass, field

from ..clock import today_label
from ..db import notes as notes_db
from ..db import tasks as tasks_db
from ..db import topics as topics_db
from ..db.connection import Tx
from ..deps import Deps
from ..llm.prompts import render
from ..llm.schemas import EditIntent
from ..search.hybrid import search
from .classify import topics_block
from .clean import clean
from .embed import embed_note
from .extract import Extracted, extract_addendum

log = logging.getLogger(__name__)


@dataclass
class EditOutcome:
    intent: str
    message: str
    ok: bool = True
    merge_id: int | None = None                 # pending merge waiting for confirmation
    task_choices: list[tuple[int, str]] = field(default_factory=list)  # several tasks: let the user pick
    date: str | None = None
    extracted: Extracted | None = None


async def classify_edit(deps: Deps, note_id: int, text: str) -> EditIntent:
    s, note = deps.settings, notes_db.get_note(deps.conn, note_id)
    messages = render(s.prompts_dir, "edit", today=today_label(s.tz), topics=topics_block(deps.conn),
                      note_id=note_id, title=note["title"] or "", topic=note["topic_name"] or "—",
                      summary=note["summary"] or (note["clean_text"] or note["raw_text"])[:300], text=text)
    return await deps.llm.chat_json(deps.llm.routine, messages, EditIntent, max_tokens=200, task="intent")


async def apply_edit(deps: Deps, note_id: int, intent: EditIntent, text: str) -> EditOutcome:
    conn = deps.conn
    i = intent.intent
    if i == "move_topic":
        topic = topics_db.get_topic(conn, intent.topic_id) if intent.topic_id else None
        if topic is None and intent.new_topic_name:
            topic = topics_db.get_topic(conn, topics_db.create_topic(conn, intent.new_topic_name.strip()[:60]))
        if topic is None:
            return EditOutcome(i, "Не понял, в какую тему перенести. Нажми «↪️ Не туда» и выбери.", ok=False)
        topics_db.move_note(conn, note_id, topic["id"])
        label = f"{topic['emoji']} {topic['name']}".strip()
        return EditOutcome(i, f"✅ #{note_id} → {label}. Запомнил исправление.")
    if i == "rename" and intent.title and intent.title.strip():
        rename(conn, note_id, intent.title.strip()[:120])
        return EditOutcome(i, f"✏️ #{note_id} теперь называется «{intent.title.strip()[:120]}».")
    if i == "add_tag" and intent.tag and intent.tag.strip():
        tag = intent.tag.strip().lstrip("#").lower()
        notes_db.set_tags(conn, note_id, [*notes_db.get_tags(conn, note_id), tag])
        return EditOutcome(i, f"🏷 Добавил тег #{tag.replace(' ', '_')} к #{note_id}.")
    if i == "delete":
        notes_db.soft_delete(conn, note_id)
        return EditOutcome(i, f"🗑 Заметка #{note_id} удалена.")
    if i == "set_task_date" and intent.date:
        return set_task_date(conn, note_id, intent.date)
    if i == "merge_with" and intent.merge_query:
        hits = [h for h in await search(conn, deps.llm, intent.merge_query, limit=3) if h.id != note_id]
        if not hits:
            return EditOutcome(i, f"Не нашёл заметку «{intent.merge_query}».", ok=False)
        target = hits[0]
        pid = conn.execute("INSERT INTO pending_merges(source_id, target_id) VALUES (?, ?)",
                           (note_id, target.id)).lastrowid
        return EditOutcome(i, f"Объединить #{note_id} с #{target.id} «{target.title}»? "
                              f"Текст #{note_id} допишется в #{target.id}, а #{note_id} удалится.", merge_id=pid)
    return await add_clarification(deps, note_id, text)


def rename(conn: sqlite3.Connection, note_id: int, title: str) -> None:
    with Tx(conn):
        conn.execute("UPDATE notes SET title = ?, embed_dirty = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                     "WHERE id = ?", (title, note_id))
        notes_db.sync_fts(conn, note_id)


def set_task_date(conn: sqlite3.Connection, note_id: int, due: str) -> EditOutcome:
    open_tasks = tasks_db.tasks_of_note(conn, note_id, only_open=True)
    if len(open_tasks) > 1:
        return EditOutcome("set_task_date", f"У #{note_id} несколько задач. Какой поставить {fmt_due(due)}?",
                           task_choices=[(t["id"], t["text"]) for t in open_tasks], date=due)
    if open_tasks:
        tasks_db.set_due(conn, open_tasks[0]["id"], due)
        text = open_tasks[0]["text"]
    else:
        note = notes_db.get_note(conn, note_id)
        text = note["title"] or (note["clean_text"] or note["raw_text"])[:100]
        tasks_db.add_task(conn, note_id, text, due)
    return EditOutcome("set_task_date", f"📅 «{text}» — {fmt_due(due)}.")


def fmt_due(due: str | None) -> str:
    if not due:
        return "без срока"
    d = f"{due[8:10]}.{due[5:7]}.{due[:4]}"
    return f"{d} {due[11:16]}" if len(due) > 10 else d


async def add_clarification(deps: Deps, note_id: int, text: str) -> EditOutcome:
    """intent=none: the reply adds information. It is appended to clean_text (raw_text stays as sent)
    and facts/tasks are extracted from the addition."""
    conn = deps.conn
    note = notes_db.get_note(conn, note_id)
    async with deps.gpu_lock:
        addition = await clean(deps, text)
        base = note["clean_text"] or note["raw_text"]
        with Tx(conn):
            conn.execute("UPDATE notes SET clean_text = ?, embed_dirty = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                         "WHERE id = ?", (f"{base}\n\n{addition}", note_id))
            notes_db.sync_fts(conn, note_id)
        extracted = await extract_addendum(deps, note_id, base, addition)
    try:
        await embed_note(deps, note_id)
    except Exception as e:  # noqa: BLE001 — re-embedded later by the periodic job
        log.warning("re-embed after clarification failed: %s", e)
    return EditOutcome("none", f"📎 Добавил к #{note_id}.", extracted=extracted)


async def merge(deps: Deps, pending_id: int) -> EditOutcome:
    """Merge source into target: text appended, tags, facts and tasks move over, source soft-deleted."""
    conn = deps.conn
    p = conn.execute("SELECT * FROM pending_merges WHERE id = ?", (pending_id,)).fetchone()
    if p is None:
        return EditOutcome("merge_with", "Это предложение уже неактуально.", ok=False)
    src, dst = notes_db.get_note(conn, p["source_id"]), notes_db.get_note(conn, p["target_id"])
    if src["status"] == "deleted" or dst["status"] == "deleted":
        conn.execute("DELETE FROM pending_merges WHERE id = ?", (pending_id,))
        return EditOutcome("merge_with", "Одна из заметок уже удалена.", ok=False)
    with Tx(conn):
        text = f"{dst['clean_text'] or dst['raw_text']}\n\n{src['clean_text'] or src['raw_text']}"
        conn.execute("UPDATE notes SET clean_text = ?, embed_dirty = 1 WHERE id = ?", (text, dst["id"]))
        tags = [*notes_db.get_tags(conn, dst["id"]), *notes_db.get_tags(conn, src["id"])]
        notes_db.set_tags(conn, dst["id"], tags)
        conn.execute("UPDATE facts SET note_id = ? WHERE note_id = ?", (dst["id"], src["id"]))
        conn.execute("UPDATE tasks SET note_id = ? WHERE note_id = ?", (dst["id"], src["id"]))
        conn.execute("DELETE FROM pending_merges WHERE source_id = ? OR target_id = ?", (src["id"], src["id"]))
        notes_db.sync_fts(conn, dst["id"])
    notes_db.soft_delete(conn, src["id"])
    try:
        await embed_note(deps, dst["id"])
    except Exception as e:  # noqa: BLE001
        log.warning("re-embed after merge failed: %s", e)
    return EditOutcome("merge_with", f"🔗 #{src['id']} объединена с #{dst['id']} «{dst['title']}».")
