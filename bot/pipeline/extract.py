"""Entities, facts and tasks from the model's output -> database."""
import logging
import sqlite3
from dataclasses import dataclass, field

from ..db import entities as entities_db
from ..db import tasks as tasks_db
from ..db.connection import Tx
from ..deps import Deps
from ..llm.prompts import render
from ..llm.schemas import EntityRef, Extraction, FactItem, TaskItem
from ..clock import today_label

log = logging.getLogger(__name__)


@dataclass
class Extracted:
    entities: list[tuple[int, str]] = field(default_factory=list)   # (entity_id, name)
    facts: int = 0
    tasks: list[tuple[int, str, str | None]] = field(default_factory=list)  # (task_id, text, due)


def clear_note(conn: sqlite3.Connection, note_id: int) -> None:
    """Drop what an earlier run extracted from this note, so re-processing never duplicates."""
    conn.execute("""UPDATE facts SET superseded_by = NULL
                    WHERE superseded_by IN (SELECT id FROM facts WHERE note_id = ?)""", (note_id,))
    conn.execute("DELETE FROM facts WHERE note_id = ?", (note_id,))
    conn.execute("DELETE FROM tasks WHERE note_id = ?", (note_id,))


def apply(conn: sqlite3.Connection, note_id: int, entities: list[EntityRef], facts: list[FactItem],
          tasks: list[TaskItem], *, replace: bool) -> Extracted:
    out = Extracted()
    with Tx(conn):
        if replace:
            clear_note(conn, note_id)
        ids: dict[str, int] = {}
        for e in entities:
            if not e.name.strip():
                continue
            ids[entities_db.norm(e.name)] = entities_db.upsert_entity(conn, e.name, e.kind, e.aliases)
        valid_fact_ids = {r[0] for r in conn.execute("SELECT id FROM facts")}
        for f in facts:
            if not f.text.strip() or not f.entity.strip():
                continue
            eid = ids.get(entities_db.norm(f.entity))
            if eid is None:
                row = entities_db.find_entity(conn, f.entity)
                eid = row["id"] if row else entities_db.upsert_entity(conn, f.entity, "other")
                ids[entities_db.norm(f.entity)] = eid
            replaces = f.replaces_fact_id if f.replaces_fact_id in valid_fact_ids else None
            entities_db.add_fact(conn, eid, note_id, f.text, replaces)
            out.facts += 1
        for eid in dict.fromkeys(ids.values()):
            out.entities.append((eid, entities_db.get_entity(conn, eid)["name"]))
        for t in tasks:
            if t.text.strip():
                out.tasks.append((tasks_db.add_task(conn, note_id, t.text, t.due), t.text.strip(), t.due))
    return out


async def extract_addendum(deps: Deps, note_id: int, note_text: str, addition: str) -> Extracted:
    """Run extraction on a clarification appended to a note (facts/tasks only, topic untouched)."""
    s = deps.settings
    messages = render(s.prompts_dir, "extract", today=today_label(s.tz), note=note_text[:1500], text=addition,
                      entities=entities_db.known_block(deps.conn, addition))
    x = await deps.llm.chat_json(deps.llm.routine, messages, Extraction, max_tokens=600, task="extract")
    return apply(deps.conn, note_id, x.entities, x.facts, x.tasks, replace=False)


async def reextract_note(deps: Deps, note_id: int) -> Extracted:
    """After the user edits clean_text: extract entities, facts and tasks again from the whole note."""
    note = deps.conn.execute("SELECT title, clean_text, raw_text FROM notes WHERE id = ?", (note_id,)).fetchone()
    text = note["clean_text"] or note["raw_text"]
    s = deps.settings
    messages = render(s.prompts_dir, "extract", today=today_label(s.tz), note=note["title"] or "", text=text,
                      entities=entities_db.known_block(deps.conn, text))
    async with deps.gpu_lock:
        x = await deps.llm.chat_json(deps.llm.routine, messages, Extraction, max_tokens=800, task="extract")
    return apply(deps.conn, note_id, x.entities, x.facts, x.tasks, replace=True)
