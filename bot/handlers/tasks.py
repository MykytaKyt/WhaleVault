"""/todo: open tasks grouped by deadline, buttons to finish or postpone."""
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..clock import today
from ..db import tasks as tasks_db
from ..deps import Deps
from ..pipeline.edits import fmt_due
from . import render_more
from .cb import TaskCB

router = Router(name="tasks")


@router.message(Command("todo"))
async def cmd_todo(message: Message, deps: Deps) -> None:
    text, kb = render_more.todo(deps.conn, today(deps.settings.tz))
    await message.answer(text, reply_markup=kb)


async def _show_list(cq: CallbackQuery, deps: Deps, prefix: str = "") -> None:
    text, kb = render_more.todo(deps.conn, today(deps.settings.tz))
    try:
        await cq.message.edit_text((prefix + "\n\n" if prefix else "") + text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


@router.callback_query(TaskCB.filter(F.action == "list"))
async def cb_list(cq: CallbackQuery, deps: Deps) -> None:
    await _show_list(cq, deps)
    await cq.answer()


@router.callback_query(TaskCB.filter(F.action == "done"))
async def cb_done(cq: CallbackQuery, callback_data: TaskCB, deps: Deps) -> None:
    t = tasks_db.get_task(deps.conn, callback_data.id)
    if t is None:
        await cq.answer("Задача не найдена")
        return
    tasks_db.set_status(deps.conn, t["id"], "done")
    await _show_list(cq, deps, f"✅ Сделано: {escape(t['text'])}")
    await cq.answer("Сделано")


@router.callback_query(TaskCB.filter(F.action == "postpone"))
async def cb_postpone(cq: CallbackQuery, callback_data: TaskCB, deps: Deps) -> None:
    t = tasks_db.get_task(deps.conn, callback_data.id)
    if t is None:
        await cq.answer("Задача не найдена")
        return
    await cq.message.edit_text(f"⏭ На когда перенести «{escape(t['text'])}»?",
                               reply_markup=render_more.postpone_kb(t["id"], today(deps.settings.tz)))
    await cq.answer()


@router.callback_query(TaskCB.filter(F.action == "due"))
async def cb_due(cq: CallbackQuery, callback_data: TaskCB, deps: Deps) -> None:
    t = tasks_db.get_task(deps.conn, callback_data.id)
    if t is None:
        await cq.answer("Задача не найдена")
        return
    due = callback_data.date or None
    tasks_db.set_due(deps.conn, t["id"], due)
    await _show_list(cq, deps, f"📅 «{escape(t['text'])}» — {fmt_due(due)}")
    await cq.answer()
