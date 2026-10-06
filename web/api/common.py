"""Helpers shared by the API modules."""
import sqlite3

from fastapi import HTTPException, Request

from bot.deps import Deps


def deps_of(request: Request) -> Deps:
    return request.app.state.deps


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} не найдена" if what in ("Заметка", "Тема", "Задача", "Сущность") else f"{what}: не найдено")


def topic_ref(r) -> dict | None:
    """{id, slug, name, emoji} from a row with topic_* columns, or None."""
    if r["topic_id"] is None:
        return None
    return {"id": r["topic_id"], "slug": r["topic_slug"], "name": r["topic_name"], "emoji": r["topic_emoji"]}


NOTE_CARD_SQL = """
    SELECT n.id, n.created_at, n.title, n.summary, n.source, n.status, n.topic_id,
           substr(coalesce(n.clean_text, n.raw_text), 1, 300) AS preview,
           t.slug AS topic_slug, t.name AS topic_name, t.emoji AS topic_emoji,
           (SELECT group_concat(tg.tag, ',') FROM note_tags nt JOIN tags tg ON tg.id = nt.tag_id
            WHERE nt.note_id = n.id) AS tags
    FROM notes n LEFT JOIN topics t ON t.id = n.topic_id
"""


def note_card(r) -> dict:
    return {"id": r["id"], "created_at": r["created_at"], "title": r["title"], "summary": r["summary"],
            "source": r["source"], "status": r["status"],
            "first_line": (r["preview"] or "").strip().split("\n")[0][:200],
            "topic": topic_ref(r), "tags": r["tags"].split(",") if r["tags"] else []}
