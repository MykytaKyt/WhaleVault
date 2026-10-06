"""Step 4: title, summary, topic, tags, is_question (routine model, JSON schema)."""
import sqlite3
from dataclasses import dataclass

from ..clock import today_label
from ..db import entities as entities_db
from ..db import topics as topics_db
from ..deps import Deps
from ..llm.prompts import render
from ..llm.schemas import NoteMarkup

FALLBACK_TOPIC = "Разное"


@dataclass
class Classification:
    markup: NoteMarkup
    topic_id: int
    new_topic: bool


def topics_block(conn: sqlite3.Connection) -> str:
    rows = topics_db.list_topics(conn)
    if not rows:
        return "(no topics yet)"
    return "\n".join(
        f"- id={t['id']}: {t['emoji']} {t['name']} — {t['description'] or 'no description'} ({t['notes_count']} notes)"
        for t in rows)


def feedback_block(conn: sqlite3.Connection, limit: int) -> str:
    rows = topics_db.recent_feedback(conn, limit)
    if not rows:
        return "(none)"
    lines = []
    for r in rows:
        what = r["title"] or (r["clean_text"] or "")[:80]
        lines.append(f"- \"{what}\" → {r['from_name'] or '?'} → {r['to_name']}")
    return "\n".join(lines)


async def classify(deps: Deps, text: str) -> NoteMarkup:
    s = deps.settings
    messages = render(s.prompts_dir, "classify", text=text, topics=topics_block(deps.conn),
                      feedback=feedback_block(deps.conn, s.feedback_examples), today=today_label(s.tz),
                      entities=entities_db.known_block(deps.conn, text))
    return await deps.llm.chat_json(deps.llm.routine, messages, NoteMarkup, max_tokens=1200, task="classify")


def resolve_topic(conn: sqlite3.Connection, markup: NoteMarkup) -> tuple[int | None, bool]:
    """Map the model's choice to a topic id. At most one new topic per note.
    A question never creates a topic: it gets an existing one or none until the user keeps it."""
    t = markup.topic
    if t.existing_topic_id is not None and topics_db.get_topic(conn, t.existing_topic_id):
        return t.existing_topic_id, False
    name = (t.new_topic_name or "").strip()
    if name:
        existing = topics_db.find_by_name(conn, name)
        if existing:
            return existing["id"], False
        if markup.is_question:
            return None, False
        return topics_db.create_topic(conn, name, t.new_topic_description or "", t.new_topic_emoji or ""), True
    if markup.is_question:
        return None, False
    return fallback_topic(conn)


def fallback_topic(conn: sqlite3.Connection) -> tuple[int, bool]:
    existing = topics_db.find_by_name(conn, FALLBACK_TOPIC)
    if existing:
        return existing["id"], False
    return topics_db.create_topic(conn, FALLBACK_TOPIC, "Заметки, которым не нашлось темы", "🗂"), True
