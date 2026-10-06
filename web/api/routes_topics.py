"""Topics: list with summary previews, topic page, notes, edits, summary refresh, merge, split."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from bot.db import topics as topics_db
from bot.pipeline import overview as overview_mod

from . import jobs
from .common import NOTE_CARD_SQL, deps_of, note_card

router = APIRouter(prefix="/api")


def _day_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")


def topic_or_404(request: Request, slug: str, follow: bool = True):
    t = topics_db.get_by_slug(deps_of(request).conn, slug)
    if t is None:
        raise HTTPException(404, "Тема не найдена")
    return topics_db.resolve(deps_of(request).conn, t) if follow else t


def topic_summary(t, new_today: int = 0, last_note: str | None = None) -> dict:
    return {"id": t["id"], "slug": t["slug"], "name": t["name"], "emoji": t["emoji"], "description": t["description"],
            "notes_count": t["notes_count"], "preview": overview_mod.preview(t["overview"] or ""),
            "has_overview": bool(t["overview"]), "overview_updated_at": t["overview_updated_at"],
            "overview_stale": bool(t["overview_stale"]), "new_today": new_today, "last_note_at": last_note}


@router.get("/topics")
async def list_topics(request: Request) -> list[dict]:
    """Topics with notes from the last day first ("новое"), then by summary update."""
    conn = deps_of(request).conn
    since = _day_ago()
    stats = {r["topic_id"]: r for r in conn.execute(
        """SELECT topic_id, sum(created_at >= ?) AS new_today, max(created_at) AS last_note FROM notes
           WHERE status = 'done' AND topic_id IS NOT NULL GROUP BY topic_id""", (since,))}
    out = []
    for t in topics_db.list_topics(conn):
        if t["notes_count"] == 0:
            continue
        s = stats.get(t["id"])
        out.append(topic_summary(t, s["new_today"] if s else 0, s["last_note"] if s else None))
    fresh = sorted((t for t in out if t["new_today"]), key=lambda t: t["last_note_at"], reverse=True)
    rest = sorted((t for t in out if not t["new_today"]),
                  key=lambda t: (t["overview_updated_at"] or "", t["notes_count"]), reverse=True)
    return fresh + rest


@router.get("/topics/{slug}")
async def get_topic(request: Request, slug: str) -> dict:
    deps = deps_of(request)
    conn = deps.conn
    original = topic_or_404(request, slug, follow=False)
    t = topics_db.resolve(conn, original)
    if t["id"] != original["id"]:
        return {"redirect": t["slug"]}
    new_today = conn.execute("SELECT count(*) FROM notes WHERE topic_id = ? AND status = 'done' AND created_at >= ?",
                             (t["id"], _day_ago())).fetchone()[0]
    entities = conn.execute(
        """SELECT e.id, e.name, e.kind, count(*) AS n FROM facts f JOIN notes n ON n.id = f.note_id
           JOIN entities e ON e.id = f.entity_id WHERE n.topic_id = ? AND n.status = 'done'
           GROUP BY e.id ORDER BY n DESC LIMIT 8""", (t["id"],)).fetchall()
    neighbors = conn.execute(
        """SELECT t2.slug, t2.name, t2.emoji, count(*) AS n FROM links l
           JOIN notes a ON a.id = l.note_id JOIN notes b ON b.id = l.related_note_id
           JOIN topics t2 ON t2.id = b.topic_id
           WHERE a.topic_id = ? AND b.topic_id != ? AND a.status = 'done' AND b.status = 'done'
             AND t2.merged_into IS NULL
           GROUP BY t2.id ORDER BY n DESC LIMIT 5""", (t["id"], t["id"])).fetchall()
    tags = conn.execute(
        """SELECT tg.tag, count(*) AS n FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id
           JOIN notes n ON n.id = nt.note_id WHERE n.topic_id = ? AND n.status = 'done'
           GROUP BY tg.id ORDER BY n DESC, tg.tag LIMIT 30""", (t["id"],)).fetchall()
    return {**topic_summary(t, new_today), "overview": t["overview"] or "", "updated_at": t["updated_at"],
            "entities": [dict(e) for e in entities], "neighbors": [dict(n) for n in neighbors],
            "tags": [dict(x) for x in tags],
            "job": jobs.active(deps, "refresh_topic", str(t["id"])) or jobs.active(deps, "split_topic", str(t["id"]))}


@router.get("/topics/{slug}/notes")
async def topic_notes(request: Request, slug: str, tag: str | None = None, sort: str = "new",
                      cursor: str | None = None, limit: int = 30) -> dict:
    t = topic_or_404(request, slug)
    limit = min(max(limit, 1), 100)
    where, args = ["n.topic_id = ?", "n.status = 'done'"], [t["id"]]
    if tag:
        where.append("EXISTS (SELECT 1 FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id "
                     "WHERE nt.note_id = n.id AND tg.tag = ?)")
        args.append(tag)
    desc = sort != "old"
    if cursor:
        created, _, nid = cursor.rpartition("|")
        op = "<" if desc else ">"
        where.append(f"(n.created_at {op} ? OR (n.created_at = ? AND n.id {op} ?))")
        args += [created, created, int(nid)]
    order = "DESC" if desc else "ASC"
    rows = deps_of(request).conn.execute(
        f"{NOTE_CARD_SQL} WHERE {' AND '.join(where)} ORDER BY n.created_at {order}, n.id {order} LIMIT ?",
        (*args, limit + 1)).fetchall()
    nxt = f"{rows[limit - 1]['created_at']}|{rows[limit - 1]['id']}" if len(rows) > limit else None
    return {"items": [note_card(r) for r in rows[:limit]], "next": nxt}


class TopicPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, max_length=500)
    emoji: str | None = Field(None, max_length=8)


@router.patch("/topics/{slug}")
async def patch_topic(request: Request, slug: str, body: TopicPatch) -> dict:
    conn = deps_of(request).conn
    t = topic_or_404(request, slug)
    if body.name is not None:
        other = topics_db.find_by_name(conn, body.name)
        if other and other["id"] != t["id"]:
            raise HTTPException(409, "Тема с таким названием уже есть — объедините их")
    topics_db.update_topic(conn, t["id"], name=body.name, description=body.description, emoji=body.emoji)
    return await get_topic(request, t["slug"])


def start_refresh(deps, topic_id: int) -> dict:
    async def work(job_id: int) -> dict:
        jobs.update(deps, job_id, progress=0.1, message="Модель пишет сводку…")
        text = await overview_mod.refresh_topic(deps, topic_id)
        return {"chars": len(text)}

    return jobs.start(deps, "refresh_topic", str(topic_id), work)


@router.post("/topics/{slug}/refresh")
async def refresh_topic(request: Request, slug: str) -> dict:
    return start_refresh(deps_of(request), topic_or_404(request, slug)["id"])


class MergeBody(BaseModel):
    source: str
    target: str


@router.post("/topics/merge")
async def merge_topics(request: Request, body: MergeBody) -> dict:
    conn = deps_of(request).conn
    src, dst = topic_or_404(request, body.source), topic_or_404(request, body.target)
    if src["id"] == dst["id"]:
        raise HTTPException(400, "Нельзя объединить тему саму с собой")
    moved = topics_db.merge_topics(conn, src["id"], dst["id"])
    job = start_refresh(deps_of(request), dst["id"])                    # the target's summary now covers both
    return {"moved": moved, "target": dst["slug"], "job": job}


@router.post("/topics/{slug}/split")
async def propose_split(request: Request, slug: str) -> dict:
    deps = deps_of(request)
    t = topic_or_404(request, slug)

    async def work(job_id: int) -> dict:
        jobs.update(deps, job_id, progress=0.1, message="Модель предлагает, как разделить…")
        return await overview_mod.propose_split(deps, t["id"])

    return jobs.start(deps, "split_topic", str(t["id"]), work)


class SplitGroup(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    emoji: str = ""
    description: str = ""
    note_ids: list[int]


class SplitApply(BaseModel):
    groups: list[SplitGroup] = Field(..., min_length=1, max_length=6)


@router.post("/topics/{slug}/split/apply")
async def apply_split(request: Request, slug: str, body: SplitApply) -> dict:
    t = topic_or_404(request, slug)
    created = overview_mod.apply_split(deps_of(request).conn, t["id"], [g.model_dump() for g in body.groups])
    conn = deps_of(request).conn
    return {"created": [conn.execute("SELECT slug FROM topics WHERE id = ?", (i,)).fetchone()[0] for i in created]}
