"""Entities, tasks, inbox, search, ask, jobs."""
import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bot import ask as ask_core
from bot.clock import today
from bot.db import entities as entities_db
from bot.db import notes as notes_db
from bot.db import tasks as tasks_db
from bot.db.connection import Tx
from bot.llm.client import LLMError
from bot.llm.schemas import check_due
from bot.pipeline import edits
from bot.search import fts
from bot.search.hybrid import search

from . import jobs
from .common import deps_of, row

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ---------- entities ----------

@router.get("/entities")
async def list_entities(request: Request) -> list[dict]:
    conn = deps_of(request).conn
    open_pairs = {r[0]: r[1] for r in conn.execute(
        "SELECT entity_id, count(*) FROM facts WHERE superseded_by IS NOT NULL AND checked = 0 GROUP BY entity_id")}
    return [{**row(e), "aliases": entities_db.names_of(e)[1:], "to_check": open_pairs.get(e["id"], 0)}
            for e in entities_db.list_entities(conn)]


@router.get("/entities/{entity_id}")
async def get_entity(request: Request, entity_id: int) -> dict:
    conn = deps_of(request).conn
    e = entities_db.get_entity(conn, entity_id)
    if e is None:
        raise HTTPException(404, "Сущность не найдена")
    facts = [row(f) for f in entities_db.facts_for_page(conn, entity_id)]
    by_id = {f["id"]: f for f in facts}
    # A contradiction: an old fact superseded by a newer one that the user hasn't confirmed yet
    pairs = [{"old": f, "new": by_id.get(f["superseded_by"])} for f in facts
             if f["superseded_by"] and not f["checked"] and by_id.get(f["superseded_by"])]
    return {**row(e), "aliases": entities_db.names_of(e)[1:], "facts": facts, "contradictions": pairs}


class EntityPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    aliases: list[str] | None = Field(None, max_length=20)


@router.patch("/entities/{entity_id}")
async def patch_entity(request: Request, entity_id: int, body: EntityPatch) -> dict:
    conn = deps_of(request).conn
    if entities_db.get_entity(conn, entity_id) is None:
        raise HTTPException(404, "Сущность не найдена")
    if body.name is not None:
        conn.execute("UPDATE entities SET name = ? WHERE id = ?", (body.name.strip(), entity_id))
    if body.aliases is not None:
        aliases = [a.strip() for a in dict.fromkeys(body.aliases) if a.strip()]
        conn.execute("UPDATE entities SET aliases = ? WHERE id = ?", (json.dumps(aliases, ensure_ascii=False), entity_id))
    return await get_entity(request, entity_id)


@router.post("/facts/{fact_id}/resolve")
async def resolve_fact(request: Request, fact_id: int) -> dict:
    """The chosen fact becomes current; the other side of its contradiction is superseded by it."""
    conn = deps_of(request).conn
    f = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
    if f is None:
        raise HTTPException(404, "Факт не найден")
    with Tx(conn):
        if f["superseded_by"]:  # the user picked the older fact: it wins over the one that replaced it
            other = f["superseded_by"]
            conn.execute("UPDATE facts SET superseded_by = NULL, checked = 1 WHERE id = ?", (fact_id,))
            conn.execute("UPDATE facts SET superseded_by = ?, checked = 1 WHERE id = ?", (fact_id, other))
        else:  # the newer fact is right: confirm every pair it is part of
            conn.execute("UPDATE facts SET checked = 1 WHERE superseded_by = ? OR id = ?", (fact_id, fact_id))
    return {"ok": True}


# ---------- tasks ----------

@router.get("/tasks")
async def list_tasks(request: Request) -> dict:
    deps = deps_of(request)
    groups = tasks_db.group(tasks_db.open_tasks(deps.conn), today(deps.settings.tz))
    done = deps.conn.execute(
        """SELECT t.*, n.title AS note_title FROM tasks t LEFT JOIN notes n ON n.id = t.note_id
           WHERE t.status = 'done' ORDER BY t.id DESC LIMIT 20""").fetchall()
    return {"today": today(deps.settings.tz).isoformat(),
            "groups": [{"key": k, "label": label.split(" ", 1)[1], "items": [row(t) for t in groups[k]]}
                       for k, label in tasks_db.GROUPS],
            "done": [row(t) for t in done]}


class TaskPatch(BaseModel):
    status: Literal["open", "done", "cancelled"] | None = None
    due_at: str | None = None
    clear_due: bool = False


@router.patch("/tasks/{task_id}")
async def patch_task(request: Request, task_id: int, body: TaskPatch) -> dict:
    conn = deps_of(request).conn
    if tasks_db.get_task(conn, task_id) is None:
        raise HTTPException(404, "Задача не найдена")
    if body.status:
        tasks_db.set_status(conn, task_id, body.status)
    if body.clear_due:
        tasks_db.set_due(conn, task_id, None)
    elif body.due_at is not None:
        due = check_due(body.due_at)
        if due is None:
            raise HTTPException(400, "Дата: ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ")
        tasks_db.set_due(conn, task_id, due)
    return row(tasks_db.get_task(conn, task_id))


# ---------- inbox ----------

@router.get("/inbox")
async def inbox(request: Request) -> dict:
    deps = deps_of(request)
    processing = deps.conn.execute(
        "SELECT id, raw_text, status, attempts, created_at FROM notes WHERE status IN ('queued', 'processing') "
        "ORDER BY id").fetchall()
    return {"processing": [row(r) for r in processing],
            "failed": [row(r) for r in notes_db.failed_notes(deps.conn, 100)],
            "duplicates": [row(r) for r in notes_db.duplicate_pairs(deps.conn, deps.settings.duplicate_threshold)]}


class DuplicateAction(BaseModel):
    action: Literal["merge", "distinct"]


@router.post("/duplicates/{a}/{b}")
async def duplicate_action(request: Request, a: int, b: int, body: DuplicateAction) -> dict:
    """merge: note b is appended to note a and deleted; distinct: the pair leaves the inbox."""
    deps = deps_of(request)
    if body.action == "distinct":
        deps.conn.execute("DELETE FROM links WHERE (note_id = ? AND related_note_id = ?) OR "
                          "(note_id = ? AND related_note_id = ?)", (a, b, b, a))
        return {"ok": True}
    for nid in (a, b):
        if notes_db.get_note(deps.conn, nid) is None:
            raise HTTPException(404, "Заметка не найдена")
    pid = deps.conn.execute("INSERT INTO pending_merges(source_id, target_id) VALUES (?, ?)", (b, a)).lastrowid
    out = await edits.merge(deps, pid)
    if not out.ok:
        raise HTTPException(409, out.message)
    return {"ok": True}


# ---------- search ----------

@router.get("/search")
async def search_notes(request: Request, q: str, limit: int = 12) -> list[dict]:
    """Hybrid search for the palette: full-text + meaning, under 200 ms (embeddings wait at most 150 ms)."""
    deps = deps_of(request)
    if not q.strip():
        return []
    hits = await search(deps.conn, deps.llm, q, limit=min(limit, 30), embed_timeout=0.15)
    marks = fts.snippets(deps.conn, q, [h.id for h in hits])
    slugs = dict(deps.conn.execute(
        f"SELECT n.id, t.slug FROM notes n JOIN topics t ON t.id = n.topic_id WHERE n.id IN "
        f"({','.join('?' * len(hits))})", [h.id for h in hits]).fetchall()) if hits else {}
    return [{"id": h.id, "title": h.title, "topic": h.topic, "topic_slug": slugs.get(h.id), "created_at": h.created_at,
             "title_marked": marks.get(h.id, {}).get("title") or [{"t": h.title or f"#{h.id}", "hit": False}],
             "snippet": marks.get(h.id, {}).get("text") or [{"t": h.first_line, "hit": False}],
             "by_meaning": h.id not in marks} for h in hits]


# ---------- ask ----------

class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    thinking: bool = False


_running: dict[int, bool] = {}  # ask id -> thinking, until its stream starts


@router.post("/ask")
async def ask_start(request: Request, body: AskBody) -> dict:
    ask_id = deps_of(request).conn.execute("INSERT INTO asks(question) VALUES (?)", (body.question.strip(),)).lastrowid
    _running[ask_id] = body.thinking
    return {"id": ask_id}


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sources(hits) -> list[dict]:
    return [{"id": h.id, "title": h.title, "topic": h.topic, "created_at": h.created_at, "first_line": h.first_line}
            for h in hits]


@router.get("/ask/{ask_id}/stream")
async def ask_stream(request: Request, ask_id: int) -> StreamingResponse:
    """SSE: status, sources, token, done, error. A finished answer is replayed in one token."""
    deps = deps_of(request)
    a = deps.conn.execute("SELECT * FROM asks WHERE id = ?", (ask_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Вопрос не найден")
    thinking = _running.pop(ask_id, None)

    async def replay():
        ids = json.loads(a["note_ids"])
        yield sse("sources", _sources(_hits(deps, ids)))
        yield sse("token", {"t": a["answer"]})
        yield sse("done", {"cited": ids})

    async def generate():
        answer = ""
        try:
            yield sse("status", {"text": "Ищу в заметках…"})
            plan = await ask_core.plan(deps, a["question"])
            yield sse("sources", _sources(plan.hits))
            if not plan.hits:
                answer = ask_core.NOT_FOUND
                yield sse("token", {"t": answer})
            else:
                if deps.gpu_lock.locked():
                    yield sse("status", {"text": "Модель занята разбором заметки, жду…"})
                async with deps.gpu_lock:
                    running = await deps.llm.running()
                    if running is not None and deps.llm.answer not in running:
                        yield sse("status", {"text": "Загружаю модель, это до минуты…"})
                    elif thinking:
                        yield sse("status", {"text": "Думаю…"})
                    async for piece in ask_core.stream_answer(deps, plan, thinking=thinking):
                        answer += piece
                        yield sse("token", {"t": piece})
            cited = ask_core.cited_ids(answer, plan.hits)
            deps.conn.execute("UPDATE asks SET answer = ?, note_ids = ? WHERE id = ?",
                              (answer, json.dumps(cited), ask_id))
            yield sse("done", {"cited": cited})
        except LLMError as e:
            log.error("web ask failed: %s", e)
            yield sse("error", {"text": jobs.friendly_error(e) if "Connect" in str(e) or "connect" in str(e)
                                else "Модель не ответила. Попробуйте ещё раз чуть позже."})
        except asyncio.CancelledError:  # the browser went away
            raise

    body = generate() if thinking is not None or not a["answer"] else replay()
    return StreamingResponse(body, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _hits(deps, ids: list[int]):
    from bot.search.hybrid import load_hits
    return load_hits(deps.conn, [(i, 0.0) for i in ids])


@router.get("/ask/history")
async def ask_history(request: Request, limit: int = 50) -> list[dict]:
    deps = deps_of(request)
    rows = deps.conn.execute("SELECT * FROM asks WHERE answer != '' ORDER BY id DESC LIMIT ?",
                             (min(limit, 200),)).fetchall()
    return [{**row(r), "note_ids": json.loads(r["note_ids"])} for r in rows]


@router.get("/ask/{ask_id}")
async def ask_get(request: Request, ask_id: int) -> dict:
    deps = deps_of(request)
    a = deps.conn.execute("SELECT * FROM asks WHERE id = ?", (ask_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Вопрос не найден")
    ids = json.loads(a["note_ids"])
    return {**row(a), "note_ids": ids, "sources": _sources(_hits(deps, ids))}


# ---------- jobs ----------

@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: int) -> dict:
    job = jobs.get(deps_of(request), job_id)
    if job is None:
        raise HTTPException(404, "Задание не найдено")
    return job
