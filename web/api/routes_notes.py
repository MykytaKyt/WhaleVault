"""Notes: feed with filters, note page, edits, delete/restore, reprocess, media."""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bot.db import entities as entities_db
from bot.db import notes as notes_db
from bot.db import tasks as tasks_db
from bot.db import topics as topics_db
from bot.deps import Deps
from bot.pipeline.embed import embed_note
from bot.pipeline.extract import reextract_note

from .common import NOTE_CARD_SQL, deps_of, note_card, row

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
SOURCES = ("text", "voice", "link", "photo", "forward")


def note_or_404(deps: Deps, note_id: int):
    note = notes_db.get_note(deps.conn, note_id)
    if note is None:
        raise HTTPException(404, "Заметка не найдена")
    return note


@router.get("/notes")
async def list_notes(request: Request, topic: str | None = None, tag: str | None = None, source: str | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     cursor: str | None = None, limit: int = 30) -> dict:
    """Feed by date; `from`/`to` are YYYY-MM-DD (aliases date_from/date_to)."""
    q = request.query_params
    date_from, date_to = q.get("from", date_from), q.get("to", date_to)
    conn = deps_of(request).conn
    limit = min(max(limit, 1), 100)
    where, args = ["n.status = 'done'"], []
    if topic:
        t = topics_db.get_by_slug(conn, topic)
        if t is None:
            raise HTTPException(404, "Тема не найдена")
        where.append("n.topic_id = ?")
        args.append(topics_db.resolve(conn, t)["id"])
    if tag:
        where.append("EXISTS (SELECT 1 FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id "
                     "WHERE nt.note_id = n.id AND tg.tag = ?)")
        args.append(tag)
    if source:
        if source not in SOURCES:
            raise HTTPException(400, f"source: один из {', '.join(SOURCES)}")
        where.append("n.source = ?")
        args.append(source)
    if date_from:
        where.append("n.created_at >= ?")
        args.append(date_from)
    if date_to:
        where.append("n.created_at < date(?, '+1 day')")
        args.append(date_to)
    if cursor:
        created, _, nid = cursor.rpartition("|")
        where.append("(n.created_at < ? OR (n.created_at = ? AND n.id < ?))")
        args += [created, created, int(nid)]
    rows = conn.execute(f"{NOTE_CARD_SQL} WHERE {' AND '.join(where)} ORDER BY n.created_at DESC, n.id DESC LIMIT ?",
                        (*args, limit + 1)).fetchall()
    nxt = f"{rows[limit - 1]['created_at']}|{rows[limit - 1]['id']}" if len(rows) > limit else None
    return {"items": [note_card(r) for r in rows[:limit]], "next": nxt}


@router.get("/tags")
async def list_tags(request: Request) -> list[dict]:
    rows = deps_of(request).conn.execute(
        """SELECT tg.tag, count(*) AS n FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id
           JOIN notes n ON n.id = nt.note_id WHERE n.status = 'done' GROUP BY tg.id ORDER BY n DESC LIMIT 200""")
    return [dict(r) for r in rows]


@router.get("/notes/{note_id}")
async def get_note(request: Request, note_id: int) -> dict:
    deps = deps_of(request)
    n = note_or_404(deps, note_id)
    topic = topics_db.get_topic(deps.conn, n["topic_id"]) if n["topic_id"] else None
    media = deps.conn.execute("SELECT id, mime FROM media WHERE note_id = ? ORDER BY id", (note_id,)).fetchall()
    return {
        "id": n["id"], "created_at": n["created_at"], "updated_at": n["updated_at"], "source": n["source"],
        "status": n["status"], "error": n["error"], "title": n["title"], "summary": n["summary"],
        "clean_text": n["clean_text"], "raw_text": n["raw_text"], "context": n["context"],
        "topic": {"id": topic["id"], "slug": topic["slug"], "name": topic["name"], "emoji": topic["emoji"]} if topic else None,
        "tags": notes_db.get_tags(deps.conn, note_id),
        "related": [row(r) for r in notes_db.related(deps.conn, note_id)][:5],
        "facts": [row(r) for r in entities_db.facts_of_note(deps.conn, note_id)],
        "tasks": [row(r) for r in tasks_db.tasks_of_note(deps.conn, note_id)],
        "media": [{"id": m["id"], "mime": m["mime"], "url": f"/api/media/{m['id']}"} for m in media],
    }


class NotePatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    clean_text: str | None = Field(None, max_length=100_000)
    topic_id: int | None = None
    tags: list[str] | None = Field(None, max_length=10)


async def _after_text_edit(deps: Deps, note_id: int) -> None:
    """New embeddings and facts for an edited note (the bot's periodic job retries embeddings if this fails)."""
    try:
        await embed_note(deps, note_id)
    except Exception as e:  # noqa: BLE001
        log.warning("re-embed of #%s postponed: %s", note_id, e)
    try:
        await reextract_note(deps, note_id)
    except Exception as e:  # noqa: BLE001
        log.warning("re-extract of #%s failed: %s", note_id, e)


@router.patch("/notes/{note_id}")
async def patch_note(request: Request, note_id: int, body: NotePatch, background: BackgroundTasks) -> dict:
    deps = deps_of(request)
    note = note_or_404(deps, note_id)
    if body.title is not None or body.clean_text is not None:
        text_changed = body.clean_text is not None and body.clean_text != note["clean_text"]
        notes_db.update_note(deps.conn, note_id, title=body.title, clean_text=body.clean_text)
        background.add_task(_after_text_edit if text_changed else embed_note, deps, note_id)
    if body.topic_id is not None and body.topic_id != note["topic_id"]:
        t = topics_db.get_topic(deps.conn, body.topic_id)
        if t is None or t["merged_into"]:
            raise HTTPException(400, "Нет такой темы")
        topics_db.move_note(deps.conn, note_id, body.topic_id)  # feedback + both summaries become stale
    if body.tags is not None:
        notes_db.set_tags(deps.conn, note_id, body.tags)
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
    """Back to the queue; the bot's worker picks it up within 30 seconds."""
    deps = deps_of(request)
    note_or_404(deps, note_id)
    notes_db.requeue(deps.conn, note_id)
    return {"ok": True}


@router.get("/media/{media_id}")
async def media(request: Request, media_id: int):
    deps = deps_of(request)
    m = deps.conn.execute("SELECT file_path, mime FROM media WHERE id = ?", (media_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Файл не найден")
    root = (deps.settings.data_dir / "media").resolve()
    path = (deps.settings.data_dir / m["file_path"]).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, media_type=m["mime"])
