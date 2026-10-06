"""JSON API for the web UI. Same functions as the Telegram bot (bot/db, bot/search, bot/pipeline)."""
import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bot import ask as ask_core
from bot.clock import today
from bot.db import entities as entities_db
from bot.db import notes as notes_db
from bot.db import tasks as tasks_db
from bot.db import topics as topics_db
from bot.deps import Deps
from bot.llm.client import LLMError
from bot.llm.schemas import check_due
from bot.pipeline import edits
from bot.pipeline.embed import embed_note
from bot.search.hybrid import search

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def deps_of(request: Request) -> Deps:
    return request.app.state.deps


def note_or_404(deps: Deps, note_id: int):
    note = notes_db.get_note(deps.conn, note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    return note


def row(r) -> dict:
    return dict(r) if r is not None else None


def note_card(r) -> dict:
    return {"id": r["id"], "created_at": r["created_at"], "title": r["title"], "summary": r["summary"],
            "source": r["source"], "preview": r["preview"],
            "topic": {"id": r["topic_id"], "name": r["topic_name"], "emoji": r["topic_emoji"]} if r["topic_id"] else None,
            "tags": r["tags"].split(",") if r["tags"] else []}


# ---------- sidebar ----------

@router.get("/sidebar")
async def sidebar(request: Request) -> dict:
    deps = deps_of(request)
    q = lambda sql: deps.conn.execute(sql).fetchone()[0]
    return {
        "topics": [{"id": t["id"], "name": t["name"], "emoji": t["emoji"], "notes_count": t["notes_count"]}
                   for t in topics_db.list_topics(deps.conn) if t["notes_count"] > 0],
        "inbox": q("SELECT count(*) FROM notes WHERE status = 'failed'")
                 + len(notes_db.duplicate_pairs(deps.conn, deps.settings.duplicate_threshold)),
        "open_tasks": len(tasks_db.open_tasks(deps.conn)),
        "notes": q("SELECT count(*) FROM notes WHERE status = 'done'"),
    }


# ---------- notes ----------

@router.get("/notes")
async def list_notes(request: Request, cursor: str | None = None, limit: int = 50, topic_id: int | None = None) -> dict:
    rows, nxt = notes_db.list_notes(deps_of(request).conn, cursor=cursor, limit=min(max(limit, 1), 200),
                                    topic_id=topic_id)
    return {"items": [note_card(r) for r in rows], "next": nxt}


@router.get("/notes/{note_id}")
async def get_note(request: Request, note_id: int) -> dict:
    deps = deps_of(request)
    n = note_or_404(deps, note_id)
    return {
        "id": n["id"], "created_at": n["created_at"], "updated_at": n["updated_at"], "source": n["source"],
        "status": n["status"], "title": n["title"], "summary": n["summary"],
        "clean_text": n["clean_text"], "raw_text": n["raw_text"], "context": n["context"],
        "topic": {"id": n["topic_id"], "name": n["topic_name"], "emoji": n["topic_emoji"]} if n["topic_id"] else None,
        "tags": notes_db.get_tags(deps.conn, note_id),
        "related": [row(r) for r in notes_db.related(deps.conn, note_id)],
        "facts": [row(r) for r in entities_db.facts_of_note(deps.conn, note_id)],
        "tasks": [row(r) for r in tasks_db.tasks_of_note(deps.conn, note_id)],
    }


class NotePatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    clean_text: str | None = None
    topic_id: int | None = None
    tags: list[str] | None = None


async def _reembed(deps: Deps, note_id: int) -> None:
    try:
        await embed_note(deps, note_id)
    except Exception as e:  # noqa: BLE001 — the bot's periodic job re-embeds dirty notes later
        log.warning("re-embed of #%s postponed: %s", note_id, e)


@router.patch("/notes/{note_id}")
async def patch_note(request: Request, note_id: int, body: NotePatch, background: BackgroundTasks) -> dict:
    deps = deps_of(request)
    note_or_404(deps, note_id)
    if body.title is not None or body.clean_text is not None:
        notes_db.update_note(deps.conn, note_id, title=body.title, clean_text=body.clean_text)
        background.add_task(_reembed, deps, note_id)
    if body.topic_id is not None:
        if topics_db.get_topic(deps.conn, body.topic_id) is None:
            raise HTTPException(400, "unknown topic")
        topics_db.move_note(deps.conn, note_id, body.topic_id)  # recorded as feedback, like "Не туда"
    if body.tags is not None:
        notes_db.set_tags(deps.conn, note_id, body.tags[:10])
    return await get_note(request, note_id)


@router.delete("/notes/{note_id}")
async def delete_note(request: Request, note_id: int) -> dict:
    deps = deps_of(request)
    note_or_404(deps, note_id)
    notes_db.soft_delete(deps.conn, note_id)
    return {"ok": True}


@router.post("/notes/{note_id}/restore")
async def restore_note(request: Request, note_id: int) -> dict:
    deps = deps_of(request)
    note_or_404(deps, note_id)
    notes_db.restore(deps.conn, note_id)
    return {"ok": True, "status": notes_db.get_note(deps.conn, note_id)["status"]}


@router.post("/notes/{note_id}/reprocess")
async def reprocess_note(request: Request, note_id: int) -> dict:
    """The bot's worker picks queued notes up within 30 seconds."""
    deps = deps_of(request)
    note_or_404(deps, note_id)
    notes_db.requeue(deps.conn, note_id)
    return {"ok": True}


class MergeBody(BaseModel):
    target_id: int


@router.post("/notes/{note_id}/merge")
async def merge_note(request: Request, note_id: int, body: MergeBody) -> dict:
    deps = deps_of(request)
    note_or_404(deps, note_id)
    note_or_404(deps, body.target_id)
    pid = deps.conn.execute("INSERT INTO pending_merges(source_id, target_id) VALUES (?, ?)",
                            (note_id, body.target_id)).lastrowid
    out = await edits.merge(deps, pid)
    if not out.ok:
        raise HTTPException(409, out.message)
    return {"ok": True}


# ---------- topics ----------

@router.get("/topics")
async def list_topics(request: Request) -> list[dict]:
    return [row(t) for t in topics_db.list_topics(deps_of(request).conn)]


@router.get("/topics/{topic_id}")
async def get_topic(request: Request, topic_id: int) -> dict:
    t = topics_db.get_topic(deps_of(request).conn, topic_id)
    if t is None:
        raise HTTPException(404, "topic not found")
    return row(t)


class TopicPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, max_length=500)
    emoji: str | None = Field(None, max_length=8)


@router.patch("/topics/{topic_id}")
async def patch_topic(request: Request, topic_id: int, body: TopicPatch) -> dict:
    deps = deps_of(request)
    await get_topic(request, topic_id)
    if body.name is not None:
        other = topics_db.find_by_name(deps.conn, body.name)
        if other and other["id"] != topic_id:
            raise HTTPException(409, "a topic with this name exists: merge instead")
    topics_db.update_topic(deps.conn, topic_id, name=body.name, description=body.description, emoji=body.emoji)
    return await get_topic(request, topic_id)


class TopicMerge(BaseModel):
    into_id: int


@router.post("/topics/{topic_id}/merge")
async def merge_topic(request: Request, topic_id: int, body: TopicMerge) -> dict:
    deps = deps_of(request)
    await get_topic(request, topic_id)
    await get_topic(request, body.into_id)
    return {"moved": topics_db.merge_topics(deps.conn, topic_id, body.into_id)}


# ---------- entities ----------

@router.get("/entities")
async def list_entities(request: Request) -> list[dict]:
    out = []
    for e in entities_db.list_entities(deps_of(request).conn):
        d = row(e)
        d["aliases"] = entities_db.names_of(e)[1:]
        out.append(d)
    return out


@router.get("/entities/{entity_id}")
async def get_entity(request: Request, entity_id: int) -> dict:
    deps = deps_of(request)
    e = entities_db.get_entity(deps.conn, entity_id)
    if e is None:
        raise HTTPException(404, "entity not found")
    d = row(e)
    d["aliases"] = entities_db.names_of(e)[1:]
    d["facts"] = [row(f) for f in entities_db.facts_for_page(deps.conn, entity_id)]
    return d


# ---------- tasks ----------

@router.get("/tasks")
async def list_tasks(request: Request) -> dict:
    deps = deps_of(request)
    groups = tasks_db.group(tasks_db.open_tasks(deps.conn), today(deps.settings.tz))
    done = deps.conn.execute(
        """SELECT t.*, n.title AS note_title FROM tasks t LEFT JOIN notes n ON n.id = t.note_id
           WHERE t.status = 'done' ORDER BY t.id DESC LIMIT 20""").fetchall()
    return {"groups": [{"key": k, "label": label, "items": [row(t) for t in groups[k]]}
                       for k, label in tasks_db.GROUPS],
            "done": [row(t) for t in done]}


class TaskPatch(BaseModel):
    status: Literal["open", "done", "cancelled"] | None = None
    due_at: str | None = None
    clear_due: bool = False


@router.patch("/tasks/{task_id}")
async def patch_task(request: Request, task_id: int, body: TaskPatch) -> dict:
    deps = deps_of(request)
    if tasks_db.get_task(deps.conn, task_id) is None:
        raise HTTPException(404, "task not found")
    if body.status:
        tasks_db.set_status(deps.conn, task_id, body.status)
    if body.clear_due:
        tasks_db.set_due(deps.conn, task_id, None)
    elif body.due_at is not None:
        due = check_due(body.due_at)
        if due is None:
            raise HTTPException(400, "due_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM")
        tasks_db.set_due(deps.conn, task_id, due)
    return row(tasks_db.get_task(deps.conn, task_id))


# ---------- inbox ----------

@router.get("/inbox")
async def inbox(request: Request) -> dict:
    deps = deps_of(request)
    return {"failed": [row(r) for r in notes_db.failed_notes(deps.conn, 100)],
            "duplicates": [row(r) for r in notes_db.duplicate_pairs(deps.conn, deps.settings.duplicate_threshold)]}


class DuplicatePair(BaseModel):
    a: int
    b: int


@router.post("/duplicates/dismiss")
async def dismiss_duplicate(request: Request, body: DuplicatePair) -> dict:
    """"These are different notes": drop the link so the pair leaves the inbox."""
    deps_of(request).conn.execute(
        "DELETE FROM links WHERE (note_id = ? AND related_note_id = ?) OR (note_id = ? AND related_note_id = ?)",
        (body.a, body.b, body.b, body.a))
    return {"ok": True}


# ---------- search and ask ----------

@router.get("/search")
async def search_notes(request: Request, q: str, limit: int = 10, fast: bool = False) -> list[dict]:
    """fast=1 (command palette, < 200 ms): wait for the embedding server only briefly; when it is cold
    (unloaded after EMBED_TTL), full-text results come back alone."""
    deps = deps_of(request)
    if not q.strip():
        return []
    hits = await search(deps.conn, deps.llm, q, limit=min(limit, 30), embed_timeout=0.15 if fast else 3.0)
    return [{"id": h.id, "title": h.title, "topic": h.topic, "created_at": h.created_at,
             "first_line": h.first_line, "score": h.score} for h in hits]


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(request: Request, body: AskBody) -> StreamingResponse:
    deps = deps_of(request)

    async def events():
        answer = ""
        try:
            yield sse("status", {"text": "Ищу в заметках…"})
            plan = await ask_core.plan(deps, body.question)
            yield sse("sources", [{"id": h.id, "title": h.title, "topic": h.topic, "created_at": h.created_at}
                                  for h in plan.hits])
            if not plan.hits:
                answer = ask_core.NOT_FOUND
                yield sse("token", {"t": answer})
            else:
                if deps.gpu_lock.locked():
                    yield sse("status", {"text": "Жду, пока освободится модель…"})
                async with deps.gpu_lock:
                    running = await deps.llm.running()
                    if running is not None and deps.llm.answer not in running:
                        yield sse("status", {"text": "Загружаю модель…"})
                    async for piece in ask_core.stream_answer(deps, plan):
                        answer += piece
                        yield sse("token", {"t": piece})
            cited = ask_core.cited_ids(answer, plan.hits)
            ask_id = ask_core.save_ask(deps.conn, body.question, answer, cited)
            yield sse("done", {"ask_id": ask_id, "cited": cited})
        except LLMError as e:
            log.error("web ask failed: %s", e)
            yield sse("error", {"text": "Модель не ответила. Попробуй ещё раз чуть позже."})
        except asyncio.CancelledError:  # the browser went away
            raise

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/asks")
async def asks(request: Request, limit: int = 30) -> list[dict]:
    rows = deps_of(request).conn.execute("SELECT * FROM asks ORDER BY id DESC LIMIT ?", (min(limit, 100),)).fetchall()
    return [{**row(r), "note_ids": json.loads(r["note_ids"])} for r in rows]
