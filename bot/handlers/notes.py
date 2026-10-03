"""Any message without a command is a note. Report buttons: wrong topic, delete, keep question, etc."""
import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message

from ..db import notes as notes_db
from ..db import topics as topics_db
from ..deps import Deps
from ..llm.client import LLMError
from ..pipeline import edits
from ..pipeline.worker import NoteResult, Worker, finish_question_as_note
from . import render, render_more
from .ask import answer_question
from .cb import MergeCB, MoveCB, NoteCB

log = logging.getLogger(__name__)
router = Router(name="notes")


class NewTopic(StatesGroup):
    name = State()


def forward_context(message: Message) -> str:
    o = message.forward_origin
    if o is None:
        return ""
    name = (getattr(o, "sender_user", None) and o.sender_user.full_name) \
        or getattr(o, "sender_user_name", None) \
        or (getattr(o, "chat", None) and o.chat.title) \
        or (getattr(o, "sender_chat", None) and o.sender_chat.title) or "неизвестно"
    return f"Пересланное сообщение, автор: {name}"


# ---------- capture ----------

@router.message(NewTopic.name, F.text)
async def new_topic_name(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    await state.clear()
    note_id = data["note_id"]
    name = message.text.strip()[:60]
    topic_id = topics_db.create_topic(deps.conn, name)
    topics_db.move_note(deps.conn, note_id, topic_id)
    await message.answer(f"✅ #{note_id} → <b>{escape(name)}</b>. Запомнил исправление.")


class ReplyToNote(Filter):
    """Passes a reply to a bot message that shows a note; injects note_id."""

    async def __call__(self, message: Message, deps: Deps) -> bool | dict:
        r = message.reply_to_message
        if r is None or not message.text or message.text.startswith("/"):
            return False
        note_id = notes_db.note_for_message(deps.conn, r.message_id)
        if note_id is None:
            return False
        note = notes_db.get_note(deps.conn, note_id)
        return {"note_id": note_id} if note and note["status"] in ("done", "question") else False


@router.message(ReplyToNote())
async def reply_edit(message: Message, note_id: int, deps: Deps) -> None:
    status = await message.reply("✍️ Понял, разбираю…")
    try:
        async with deps.gpu_lock:
            intent = await edits.classify_edit(deps, note_id, message.text)
        out = await edits.apply_edit(deps, note_id, intent, message.text)
    except LLMError as e:
        log.error("edit of #%s failed: %s", note_id, e)
        await status.edit_text("⚠️ Не получилось разобрать правку. Попробуй кнопками под заметкой.")
        return
    lines = [escape(out.message)]
    if out.extracted:
        lines += render_more.extracted_lines(out.extracted)
    kb = None
    if out.merge_id:
        kb = render_more.merge_kb(out.merge_id)
    elif out.task_choices:
        kb = render_more.task_choice_kb(out.task_choices, out.date)
    elif out.intent == "delete":
        kb = render.InlineKeyboardMarkup(inline_keyboard=[[render.InlineKeyboardButton(
            text="↩️ Вернуть", callback_data=NoteCB(action="restore", id=note_id).pack())]])
    await status.edit_text("\n".join(lines), reply_markup=kb)
    notes_db.link_message(deps.conn, status.message_id, note_id)


@router.message(F.text)
async def capture_text(message: Message, deps: Deps, worker: Worker) -> None:
    if message.text.startswith("/"):
        await message.reply("Не знаю такой команды. Список: /help")
        return
    ctx = forward_context(message)
    source = "forward" if ctx else "text"
    note_id = notes_db.insert_note(deps.conn, source, message.text, ctx, message.message_id)
    reply = await message.reply(render.accepted_text(note_id), reply_markup=render.accepted_kb(note_id))
    notes_db.set_reply_id(deps.conn, note_id, reply.message_id)
    worker.enqueue(note_id)


@router.message()
async def capture_other(message: Message) -> None:
    # Voice, photos, documents: stage 5 (faster-whisper, tesseract)
    await message.reply("Пока принимаю только текст. Голосовые, фото и файлы появятся на этапе 5.")


# ---------- worker callbacks ----------

def make_worker_callbacks(bot: Bot, deps: Deps):
    chat_id = deps.settings.allowed_user_id

    async def on_done(r: NoteResult) -> None:
        note = notes_db.get_note(deps.conn, r.note_id)
        text, kb = render.report_text(deps.conn, r), render.report_kb(r)
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=note["tg_reply_id"], reply_markup=kb)
        except TelegramBadRequest:
            await bot.send_message(chat_id, text, reply_markup=kb)
        if r.is_question:
            asyncio.create_task(answer_question(bot, deps, chat_id, note["clean_text"] or note["raw_text"]))

    async def on_failed(note_id: int, error: str) -> None:
        note = notes_db.get_note(deps.conn, note_id)
        text = f"⚠️ Не смог разобрать #{note_id}, заметка лежит во входящих: /inbox"
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=note["tg_reply_id"],
                                        reply_markup=render.accepted_kb(note_id))
        except TelegramBadRequest:
            await bot.send_message(chat_id, text)

    return on_done, on_failed


# ---------- buttons ----------

async def _safe_edit(cq: CallbackQuery, text: str, kb=None) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cq.message.answer(text, reply_markup=kb)


@router.callback_query(NoteCB.filter(F.action == "view"))
async def cb_view(cq: CallbackQuery, callback_data: NoteCB, deps: Deps) -> None:
    parts = render.note_full(deps.conn, callback_data.id)
    for i, part in enumerate(parts):
        sent = await cq.message.answer(part, reply_markup=render.note_kb(callback_data.id) if i == len(parts) - 1 else None)
        notes_db.link_message(deps.conn, sent.message_id, callback_data.id)
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "raw"))
async def cb_raw(cq: CallbackQuery, callback_data: NoteCB, deps: Deps) -> None:
    for part in render.note_full(deps.conn, callback_data.id, raw=True):
        await cq.message.answer(part)
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "wrong"))
async def cb_wrong(cq: CallbackQuery, callback_data: NoteCB, deps: Deps) -> None:
    await cq.message.edit_reply_markup(reply_markup=render.move_kb(deps.conn, callback_data.id))
    await cq.answer("Выбери правильную тему")


@router.callback_query(NoteCB.filter(F.action == "back"))
async def cb_back(cq: CallbackQuery, callback_data: NoteCB) -> None:
    await cq.message.edit_reply_markup(reply_markup=render.note_kb(callback_data.id))
    await cq.answer()


@router.callback_query(MoveCB.filter(F.topic_id == 0))
async def cb_move_new(cq: CallbackQuery, callback_data: MoveCB, state: FSMContext) -> None:
    await state.set_state(NewTopic.name)
    await state.update_data(note_id=callback_data.note_id)
    await cq.message.answer(f"Как назвать новую тему для #{callback_data.note_id}?",
                            reply_markup=ForceReply(input_field_placeholder="Название темы"))
    await cq.answer()


@router.callback_query(MoveCB.filter())
async def cb_move(cq: CallbackQuery, callback_data: MoveCB, deps: Deps) -> None:
    topics_db.move_note(deps.conn, callback_data.note_id, callback_data.topic_id)
    t = topics_db.get_topic(deps.conn, callback_data.topic_id)
    await cq.message.edit_reply_markup(reply_markup=render.note_kb(callback_data.note_id))
    await cq.message.answer(f"✅ #{callback_data.note_id} → <b>{escape(render.topic_label(t['name'], t['emoji']))}</b>. "
                            "Запомнил исправление.")
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "delete"))
async def cb_delete(cq: CallbackQuery, callback_data: NoteCB, deps: Deps) -> None:
    notes_db.soft_delete(deps.conn, callback_data.id)
    kb = render.InlineKeyboardMarkup(inline_keyboard=[[render.InlineKeyboardButton(
        text="↩️ Вернуть", callback_data=NoteCB(action="restore", id=callback_data.id).pack())]])
    await _safe_edit(cq, f"🗑 Заметка #{callback_data.id} удалена.", kb)
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "restore"))
async def cb_restore(cq: CallbackQuery, callback_data: NoteCB, deps: Deps, worker: Worker) -> None:
    notes_db.restore(deps.conn, callback_data.id)
    note = notes_db.get_note(deps.conn, callback_data.id)
    if note["status"] == "queued":
        worker.enqueue(note["id"])
        await _safe_edit(cq, render.accepted_text(note["id"]), render.accepted_kb(note["id"]))
    else:
        await _safe_edit(cq, f"↩️ Заметка #{note['id']} возвращена.", render.note_kb(note["id"]))
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "keep"))
async def cb_keep(cq: CallbackQuery, callback_data: NoteCB, deps: Deps) -> None:
    await finish_question_as_note(deps, callback_data.id)
    await cq.message.edit_reply_markup(reply_markup=render.note_kb(callback_data.id))
    await cq.message.answer(f"💾 Сохранил #{callback_data.id} как заметку.")
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "question"))
async def cb_question(cq: CallbackQuery, callback_data: NoteCB, bot: Bot, deps: Deps) -> None:
    notes_db.mark_question(deps.conn, callback_data.id)
    note = notes_db.get_note(deps.conn, callback_data.id)
    kb = render.InlineKeyboardMarkup(inline_keyboard=[[
        render.InlineKeyboardButton(text="💾 Сохранить", callback_data=NoteCB(action="keep", id=note["id"]).pack()),
        render.InlineKeyboardButton(text="🗑 Удалить", callback_data=NoteCB(action="delete", id=note["id"]).pack())]])
    await cq.message.edit_reply_markup(reply_markup=kb)
    await cq.answer("Отвечаю как на вопрос")
    asyncio.create_task(answer_question(bot, deps, cq.message.chat.id, note["clean_text"] or note["raw_text"]))


@router.callback_query(MergeCB.filter())
async def cb_merge(cq: CallbackQuery, callback_data: MergeCB, deps: Deps) -> None:
    if callback_data.yes:
        out = await edits.merge(deps, callback_data.id)
    else:
        deps.conn.execute("DELETE FROM pending_merges WHERE id = ?", (callback_data.id,))
        out = edits.EditOutcome("merge_with", "Оставил заметки раздельно.")
    await _safe_edit(cq, escape(out.message))
    await cq.answer()


@router.callback_query(NoteCB.filter(F.action == "retry"))
async def cb_retry(cq: CallbackQuery, callback_data: NoteCB, deps: Deps, worker: Worker) -> None:
    deps.conn.execute("UPDATE notes SET status = 'queued', attempts = 0 WHERE id = ?", (callback_data.id,))
    msg = await cq.message.answer(render.accepted_text(callback_data.id), reply_markup=render.accepted_kb(callback_data.id))
    notes_db.set_reply_id(deps.conn, callback_data.id, msg.message_id)
    worker.enqueue(callback_data.id)
    await cq.answer()
