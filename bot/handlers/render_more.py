"""Rendering for stage 3: entities, facts, tasks, edit outcomes."""
import sqlite3
from datetime import date, timedelta
from html import escape

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import entities as entities_db
from ..db import tasks as tasks_db
from ..pipeline.edits import fmt_due
from ..pipeline.extract import Extracted
from .cb import EntityCB, MergeCB, NoteCB, TaskCB
from .render import date as fmt_date, pack_lines

KIND_LABELS = {"person": "👤 Люди", "car": "🚗 Машины", "project": "📌 Проекты", "place": "📍 Места", "other": "🔹 Другое"}
KIND_ICON = {"person": "👤", "car": "🚗", "project": "📌", "place": "📍", "other": "🔹"}


def extracted_lines(x: Extracted) -> list[str]:
    lines = []
    if x.entities:
        lines.append("👤 " + ", ".join(escape(n) for _, n in x.entities)
                     + (f" · фактов: {x.facts}" if x.facts else ""))
    for _, text, due in x.tasks:
        lines.append(f"✅ {escape(text)}" + (f" — <b>{fmt_due(due)}</b>" if due else ""))
    return lines


def entities_kb(conn: sqlite3.Connection) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = entities_db.list_entities(conn)
    if not rows:
        return "Сущностей пока нет: они появятся, когда в заметках будут люди, машины, проекты.", None
    kb = InlineKeyboardBuilder()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        kb.button(text=f"{KIND_ICON.get(r['kind'], '🔹')} {r['name']} ({r['facts_count']})"[:60],
                  callback_data=EntityCB(id=r["id"]))
    kb.adjust(2)
    summary = " · ".join(f"{KIND_LABELS[k]}: {n}" for k, n in counts.items())
    return f"<b>Сущности</b>\n{summary}", kb.as_markup()


def entity_page(conn: sqlite3.Connection, entity_id: int) -> tuple[list[str], InlineKeyboardMarkup]:
    """Facts grouped by date; superseded facts are struck through with what replaced them."""
    e = entities_db.get_entity(conn, entity_id)
    back = InlineKeyboardBuilder()
    if e is None:
        back.button(text="⬅️ Все сущности", callback_data=EntityCB(id=0))
        return ["Сущность не найдена."], back.as_markup()
    aliases = entities_db.names_of(e)[1:]
    head = f"<b>{KIND_ICON.get(e['kind'], '🔹')} {escape(e['name'])}</b>"
    if aliases:
        head += f"\n<i>также: {escape(', '.join(aliases))}</i>"
    body = []
    if e["page"]:
        body.append(escape(e["page"]))
    facts = entities_db.facts_for_page(conn, entity_id)
    day, note_ids = None, []
    for f in facts:
        d = fmt_date(f["created_at"])
        if d != day:
            body.append(f"\n<b>{d}</b>")
            day = d
        src = f" <i>#{f['note_id']}</i>" if f["note_id"] else ""
        if f["superseded_by"]:
            body.append(f"• <s>{escape(f['text'])}</s>{src}\n   ↳ {fmt_date(f['superseded_at'])}: {escape(f['superseded_text'])}")
        else:
            body.append(f"• {escape(f['text'])}{src}")
        if f["note_id"] and f["note_id"] not in note_ids:
            note_ids.append(f["note_id"])
    if not facts and not e["page"]:
        body.append("Фактов пока нет.")
    kb = InlineKeyboardBuilder()
    for nid in note_ids[-10:]:
        kb.button(text=f"#{nid}", callback_data=NoteCB(action="view", id=nid))
    kb.button(text="⬅️ Все сущности", callback_data=EntityCB(id=0))
    kb.adjust(5)
    return pack_lines([head, *body]), kb.as_markup()


def todo(conn: sqlite3.Connection, today: date) -> tuple[str, InlineKeyboardMarkup | None]:
    groups = tasks_db.group(tasks_db.open_tasks(conn), today)
    if not any(groups.values()):
        return "🎉 Открытых задач нет.", None
    lines, kb, n = ["<b>Задачи</b>"], InlineKeyboardBuilder(), 0
    for key, label in tasks_db.GROUPS:
        if not groups[key]:
            continue
        lines.append(f"\n{label}")
        for t in groups[key]:
            n += 1
            due = f" — {fmt_due(t['due_at'])}" if t["due_at"] else ""
            src = f" <i>#{t['note_id']}</i>" if t["note_id"] else ""
            lines.append(f"{n}. {escape(t['text'])}{due}{src}")
            if n <= 30:  # Telegram allows 100 buttons per message
                kb.button(text=f"✅ {n}", callback_data=TaskCB(action="done", id=t["id"]))
                kb.button(text=f"⏭ {n}", callback_data=TaskCB(action="postpone", id=t["id"]))
    kb.adjust(4)
    return "\n".join(lines)[:4000], kb.as_markup()


def postpone_kb(task_id: int, today: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, days in (("Завтра", 1), ("Через 3 дня", 3), ("Через неделю", 7)):
        kb.button(text=label, callback_data=TaskCB(action="due", id=task_id, date=(today + timedelta(days=days)).isoformat()))
    kb.button(text="Без срока", callback_data=TaskCB(action="due", id=task_id, date=""))
    kb.button(text="⬅️ Задачи", callback_data=TaskCB(action="list", id=0))
    kb.adjust(3, 2)
    return kb.as_markup()


def task_kb(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сделано", callback_data=TaskCB(action="done", id=task_id))
    kb.button(text="⏭ Перенести", callback_data=TaskCB(action="postpone", id=task_id))
    return kb.as_markup()


def merge_kb(pending_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Объединить", callback_data=MergeCB(id=pending_id, yes=1))
    kb.button(text="✖️ Оставить", callback_data=MergeCB(id=pending_id, yes=0))
    return kb.as_markup()


def task_choice_kb(choices: list[tuple[int, str]], due: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for tid, text in choices:
        kb.button(text=text[:50], callback_data=TaskCB(action="due", id=tid, date=due))
    kb.adjust(1)
    return kb.as_markup()


def note_facts_tasks(conn: sqlite3.Connection, note_id: int) -> str:
    """Block for the full note view: facts and tasks extracted from this note."""
    lines = []
    facts = entities_db.facts_of_note(conn, note_id)
    if facts:
        lines.append("\n<b>Факты</b>")
        lines += [f"• {escape(f['entity'])}: {escape(f['text'])}" for f in facts]
    tasks = tasks_db.tasks_of_note(conn, note_id)
    if tasks:
        lines.append("\n<b>Задачи</b>")
        mark = {"open": "◻️", "done": "✅", "cancelled": "✖️"}
        lines += [f"{mark[t['status']]} {escape(t['text'])}" + (f" — {fmt_due(t['due_at'])}" if t["due_at"] else "")
                  for t in tasks]
    return "\n".join(lines)
