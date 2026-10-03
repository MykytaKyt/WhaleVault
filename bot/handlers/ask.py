"""/ask: retrieve notes, stream the answer from the answer model, source buttons at the end."""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import ask as ask_core
from ..deps import Deps
from ..llm.client import LLMError
from .render import ids_kb
from .streaming import StreamEditor

log = logging.getLogger(__name__)
router = Router(name="ask")


async def answer_question(bot: Bot, deps: Deps, chat_id: int, question: str) -> None:
    msg = await bot.send_message(chat_id, "🔎 Ищу в заметках…")
    ed = StreamEditor(bot, msg, deps.settings.ask_edit_interval)
    try:
        plan = await ask_core.plan(deps, question)
        if not plan.hits:
            await ed.status(ask_core.NOT_FOUND)
            ask_core.save_ask(deps.conn, question, ask_core.NOT_FOUND, [])
            return
        if deps.gpu_lock.locked():
            await ed.status("⏳ Дожидаюсь, пока разберётся заметка…")
        async with deps.gpu_lock:
            running = await deps.llm.running()
            if running is not None and deps.llm.answer not in running:
                await ed.status("⏳ Загружаю модель, первый ответ может занять до минуты…")
            async for piece in ask_core.stream_answer(deps, plan):
                await ed.push(piece)
        answer = ed.done_text + ed.text
        sources = ask_core.cited_ids(answer, plan.hits)
        full = await ed.finish(ids_kb(sources), "\n\n📎 Источники:" if sources else "")
        ask_core.save_ask(deps.conn, question, full, sources)
    except LLMError as e:
        log.error("ask failed: %s", e)
        await ed.status("⚠️ Модель не ответила. Попробуй ещё раз чуть позже.")


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, bot: Bot, deps: Deps) -> None:
    question = (command.args or "").strip()
    if not question:
        await message.answer("Напиши вопрос после команды: <code>/ask что я записывал про катализатор?</code>")
        return
    await answer_question(bot, deps, message.chat.id, question)
