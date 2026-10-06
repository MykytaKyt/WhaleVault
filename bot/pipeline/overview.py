"""Topic summaries (topics.overview, markdown) and split proposals. Model: answer (9B).

Used by the web UI ("Обновить сводку сейчас", "Разделить") and later by the nightly cleanup.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from ..ask import estimate_tokens
from ..clock import today_label
from ..db import topics as topics_db
from ..db.connection import Tx
from ..deps import Deps
from ..llm.prompts import render

log = logging.getLogger(__name__)
SECTIONS = ("Что известно", "Открытые вопросы и задачи", "Что изменилось за неделю")


def _topic_notes(conn: sqlite3.Connection, topic_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT id, created_at, title, summary, coalesce(clean_text, raw_text) AS text FROM notes
           WHERE topic_id = ? AND status = 'done' ORDER BY created_at DESC, id DESC""", (topic_id,)).fetchall()


def notes_block(notes: list[sqlite3.Row], budget_tokens: int) -> str:
    """Newest notes in full; when the budget runs out, older ones shrink to their summary, then drop."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    blocks, used = [], 0
    for n in notes:
        mark = " · new this week" if n["created_at"] >= week_ago else ""
        head = f"[#{n['id']}] {n['created_at'][:10]}{mark} · {n['title'] or ''}"
        full = f"{head}\n{n['text']}"
        short = f"{head}\n{n['summary'] or n['text'][:200]}"
        for block in (full, short):
            cost = estimate_tokens(block)
            if used + cost <= budget_tokens:
                blocks.append(block)
                used += cost
                break
    return "\n\n".join(blocks)


def _tasks_block(conn: sqlite3.Connection, topic_id: int) -> str:
    rows = conn.execute(
        """SELECT t.text, t.due_at, t.note_id FROM tasks t JOIN notes n ON n.id = t.note_id
           WHERE n.topic_id = ? AND n.status = 'done' AND t.status = 'open' ORDER BY t.due_at IS NULL, t.due_at""",
        (topic_id,)).fetchall()
    return "\n".join(f"- {r['text']}" + (f" (до {r['due_at']})" if r["due_at"] else "") + f" [#{r['note_id']}]"
                     for r in rows) or "(none)"


def clean_markdown(text: str) -> str:
    """Drop anything before the first expected heading (models sometimes add a preamble)."""
    m = re.search(r"^##\s", text, re.M)
    return text[m.start():].strip() if m else text.strip()


async def refresh_topic(deps: Deps, topic_id: int) -> str:
    conn, s = deps.conn, deps.settings
    t = topics_db.get_topic(conn, topic_id)
    notes = _topic_notes(conn, topic_id)
    if not notes:
        overview = ""
    else:
        messages = render(s.prompts_dir, "overview", today=today_label(s.tz), topic=f"{t['emoji']} {t['name']}".strip(),
                          description=t["description"] or "", tasks=_tasks_block(conn, topic_id),
                          notes=notes_block(notes, s.ask_context_tokens - 1500))
        async with deps.gpu_lock:
            overview = clean_markdown(await deps.llm.chat(deps.llm.answer, messages, temperature=0.3, max_tokens=1500,
                                                          task="overview"))
    topics_db.set_overview(conn, topic_id, overview)
    return overview


async def refresh_stale(deps: Deps, limit: int = 20) -> int:
    """Nightly: rewrite summaries of topics whose notes changed since the last summary, busiest first."""
    rows = deps.conn.execute(
        "SELECT id FROM topics WHERE merged_into IS NULL AND overview_stale = 1 AND notes_count > 0 "
        "ORDER BY notes_count DESC LIMIT ?", (limit,)).fetchall()
    done = 0
    for r in rows:
        try:
            await refresh_topic(deps, r["id"])
            done += 1
        except Exception:  # noqa: BLE001 - one bad topic must not stop the rest
            log.exception("overview refresh failed for topic %s", r["id"])
    return done


def preview(overview: str, chars: int = 220) -> str:
    """2–3 lines for a topic card: the start of «Что известно» without markdown and citations."""
    body = overview.split("## " + SECTIONS[1])[0]
    body = re.sub(r"^##.*$", "", body, flags=re.M)
    body = re.sub(r"\[#\d+\]", "", body)
    body = re.sub(r"[*_`>#]|^\s*[-•]\s*", "", body, flags=re.M)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"\s+([.,;:!?)])", r"\1", body)  # "12 000 грн [#3]." -> "12 000 грн."
    return body if len(body) <= chars else body[:chars].rsplit(" ", 1)[0] + "…"


# ---------- split ----------

class SplitGroup(BaseModel):
    name: str = Field(..., max_length=60)
    emoji: str = Field("", max_length=8)
    description: str = Field("", max_length=300)
    note_ids: list[int]


class SplitProposal(BaseModel):
    groups: list[SplitGroup] = Field(..., min_length=1, max_length=4)
    reason: str = ""


async def propose_split(deps: Deps, topic_id: int) -> dict:
    conn, s = deps.conn, deps.settings
    t = topics_db.get_topic(conn, topic_id)
    notes = _topic_notes(conn, topic_id)
    lines = "\n".join(f"[#{n['id']}] {n['title'] or ''} — {n['summary'] or n['text'][:150]}" for n in notes[:150])
    messages = render(s.prompts_dir, "split", topic=f"{t['emoji']} {t['name']}".strip(),
                      description=t["description"] or "", notes=lines)
    async with deps.gpu_lock:
        p = await deps.llm.chat_json(deps.llm.answer, messages, SplitProposal, max_tokens=1500, task="split")
    valid = {n["id"] for n in notes}
    groups, seen = [], set()
    for g in p.groups:
        ids = [i for i in dict.fromkeys(g.note_ids) if i in valid and i not in seen]
        seen.update(ids)
        if ids:
            groups.append({**g.model_dump(), "note_ids": ids})
    return {"groups": groups, "reason": p.reason, "unassigned": sorted(valid - seen)}


def apply_split(conn: sqlite3.Connection, topic_id: int, groups: list[dict]) -> list[int]:
    """Create the proposed topics and move notes. A group named like the current topic keeps it."""
    current = topics_db.get_topic(conn, topic_id)
    created = []
    for g in groups:
        if topics_db.normalize_name(g["name"]) == topics_db.normalize_name(current["name"]):
            target = topic_id
        else:
            target = topics_db.create_topic(conn, g["name"], g.get("description", ""), g.get("emoji", ""))
            created.append(target)
        with Tx(conn):
            for nid in g["note_ids"]:
                conn.execute("UPDATE notes SET topic_id = ? WHERE id = ? AND topic_id = ?", (target, nid, topic_id))
            topics_db.recount(conn, target, topic_id)
    return created


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
