"""Telegram message texts and keyboards. HTML parse mode, no tables, long texts split at 3,500 chars."""
import sqlite3
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import notes as notes_db
from ..pipeline.worker import NoteResult
from ..search.hybrid import Hit
from .cb import MoveCB, NoteCB, TopicCB

LIMIT = 3500


def split_text(text: str, limit: int = LIMIT) -> list[str]:
    """Split on paragraph, then line, then space boundaries. Never cuts inside an HTML tag we produce,
    because we only split plain-text bodies that were escaped as a whole."""
    parts, rest = [], text
    while len(rest) > limit:
        cut = max(rest.rfind("\n\n", 0, limit), rest.rfind("\n", 0, limit))
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest or not parts:
        parts.append(rest)
    return parts


def pack_lines(lines: list[str], limit: int = LIMIT) -> list[str]:
    """Join HTML lines into messages without cutting inside a line (each line is balanced HTML)."""
    parts, cur = [], ""
    for line in lines:
        for piece in ([line] if len(line) <= limit else split_text(line, limit)):
            if cur and len(cur) + len(piece) + 1 > limit:
                parts.append(cur)
                cur = ""
            cur = f"{cur}\n{piece}" if cur else piece
    return parts + [cur] if cur or not parts else parts


def date(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else ""


def topic_label(name: str | None, emoji: str | None) -> str:
    return f"{emoji} {name}".strip() if name else "—"


def accepted_text(note_id: int) -> str:
    return f"📥 Принял <b>#{note_id}</b>, разбираю…"


def accepted_kb(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Удалить", callback_data=NoteCB(action="delete", id=note_id).pack())]])


def report_text(conn: sqlite3.Connection, r: NoteResult, extra: str = "") -> str:
    note = notes_db.get_note(conn, r.note_id)
    lines = [f"<b>{escape(note['title'] or '')}</b>  #{r.note_id}"]
    topic = escape(topic_label(note["topic_name"], note["topic_emoji"]))
    lines.append(f"📁 {topic}" + (" <i>(новая тема)</i>" if r.new_topic else ""))
    if note["summary"]:
        lines.append(f"<i>{escape(note['summary'])}</i>")
    tags = notes_db.get_tags(conn, r.note_id)
    if tags:
        lines.append("🏷 " + " ".join("#" + escape(t.replace(" ", "_")) for t in tags))
    if r.embed.similar:
        titles = {row["id"]: row["title"] for row in notes_db.related(conn, r.note_id)}
        sim = ", ".join(f"#{n} {escape(titles.get(n) or '')}" for n, _ in r.embed.similar)
        lines.append(f"🔗 Похожие: {sim}")
    for n, score in r.embed.duplicates:
        lines.append(f"⚠️ Возможный дубль #{n} (сходство {score:.2f})")
    from .render_more import extracted_lines  # avoid a circular import
    lines += extracted_lines(r.extracted)
    if r.is_question:
        lines.append("❓ Похоже на вопрос — отвечаю ниже. Сохранить его как заметку?")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def report_kb(r: NoteResult) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if r.is_question:
        kb.button(text="💾 Сохранить", callback_data=NoteCB(action="keep", id=r.note_id))
    else:
        kb.button(text="↪️ Не туда", callback_data=NoteCB(action="wrong", id=r.note_id))
        kb.button(text="❓ Это вопрос", callback_data=NoteCB(action="question", id=r.note_id))
    kb.button(text="🗑 Удалить", callback_data=NoteCB(action="delete", id=r.note_id))
    for n, _ in r.embed.similar:
        kb.button(text=f"#{n}", callback_data=NoteCB(action="view", id=n))
    kb.adjust(2 if r.is_question else 3, max(1, len(r.embed.similar)))
    return kb.as_markup()


def note_kb(note_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↪️ Не туда", callback_data=NoteCB(action="wrong", id=note_id))
    kb.button(text="🗑 Удалить", callback_data=NoteCB(action="delete", id=note_id))
    kb.button(text="📄 Оригинал", callback_data=NoteCB(action="raw", id=note_id))
    kb.adjust(3)
    return kb.as_markup()


def note_full(conn: sqlite3.Connection, note_id: int, raw: bool = False) -> list[str]:
    n = notes_db.get_note(conn, note_id)
    if n is None:
        return ["Заметка не найдена."]
    head = [f"<b>{escape(n['title'] or 'Без заголовка')}</b>  #{n['id']}",
            f"📅 {date(n['created_at'])} · 📁 {escape(topic_label(n['topic_name'], n['topic_emoji']))}"]
    tags = notes_db.get_tags(conn, note_id)
    if tags:
        head.append("🏷 " + " ".join("#" + escape(t.replace(" ", "_")) for t in tags))
    if n["status"] == "deleted":
        head.append("🗑 <i>удалена</i>")
    body = n["raw_text"] if raw or not n["clean_text"] else n["clean_text"]
    if raw:
        head.append("<i>оригинал:</i>")
    related = notes_db.related(conn, note_id)
    tail = ("\n\n🔗 " + ", ".join(f"#{r['id']} {escape(r['title'] or '')}" for r in related)) if related else ""
    from .render_more import note_facts_tasks
    extra = note_facts_tasks(conn, note_id)
    if extra:
        tail += "\n" + extra
    parts = split_text(escape(body))
    parts[0] = "\n".join(head) + "\n\n" + parts[0]
    if len(parts[-1]) + len(tail) <= 4000:
        parts[-1] += tail
    else:
        parts += pack_lines(tail.strip().split("\n"))
    return parts


def move_kb(conn: sqlite3.Connection, note_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    current = notes_db.get_note(conn, note_id)["topic_id"]
    for t in conn.execute("SELECT id, name, emoji FROM topics ORDER BY name").fetchall():
        if t["id"] != current:
            kb.button(text=topic_label(t["name"], t["emoji"])[:40], callback_data=MoveCB(note_id=note_id, topic_id=t["id"]))
    kb.button(text="➕ Новая тема", callback_data=MoveCB(note_id=note_id, topic_id=0))
    kb.button(text="✖️ Отмена", callback_data=NoteCB(action="back", id=note_id))
    kb.adjust(2)
    return kb.as_markup()


def topics_kb(conn: sqlite3.Connection) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in conn.execute("SELECT id, name, emoji, notes_count FROM topics WHERE notes_count > 0 "
                          "ORDER BY notes_count DESC, name").fetchall():
        kb.button(text=f"{topic_label(t['name'], t['emoji'])} ({t['notes_count']})"[:60], callback_data=TopicCB(id=t["id"]))
    kb.adjust(2)
    return kb.as_markup()


def topic_page(conn: sqlite3.Connection, topic_id: int) -> tuple[str, InlineKeyboardMarkup]:
    t = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if t is None:
        return "Тема не найдена.", topics_kb(conn)
    lines = [f"<b>{escape(topic_label(t['name'], t['emoji']))}</b> · {t['notes_count']} заметок"]
    if t["description"]:
        lines.append(f"<i>{escape(t['description'])}</i>")
    if t["overview"]:
        lines.append("\n" + escape(t["overview"][:2500]))
    kb = InlineKeyboardBuilder()
    recent = notes_db.notes_in_topic(conn, topic_id, 10)
    if recent:
        lines.append("\nПоследние заметки:")
    for n in recent:
        kb.button(text=f"{date(n['created_at'])} · {n['title'] or '#' + str(n['id'])}"[:60],
                  callback_data=NoteCB(action="view", id=n["id"]))
    kb.button(text="⬅️ Все темы", callback_data=TopicCB(id=0))
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


def hits_text(hits: list[Hit], query: str) -> str:
    if not hits:
        return f"По запросу «{escape(query)}» ничего не нашлось."
    lines = [f"🔎 <b>{escape(query)}</b>"]
    for h in hits:
        lines.append(f"\n<b>#{h.id} {escape(h.title)}</b> · {escape(h.topic)} · {date(h.created_at)}\n"
                     f"{escape(h.first_line)}")
    return "\n".join(lines)


def ids_kb(ids: list[int], per_row: int = 5) -> InlineKeyboardMarkup | None:
    if not ids:
        return None
    kb = InlineKeyboardBuilder()
    for n in ids:
        kb.button(text=f"#{n}", callback_data=NoteCB(action="view", id=n))
    kb.adjust(per_row)
    return kb.as_markup()
