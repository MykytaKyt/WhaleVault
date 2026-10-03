"""Feed real aiogram Updates through the dispatcher with a fake Telegram session."""
import itertools
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, SendMessage,
                             TelegramMethod)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.db import notes as notes_db
from bot.handlers import ask as ask_h, commands, notes
from bot.handlers.access import AllowedUserMiddleware
from bot.handlers.cb import MoveCB, NoteCB
from bot.pipeline.worker import Worker

ME = User(id=42, is_bot=False, first_name="Me")
STRANGER = User(id=7, is_bot=False, first_name="X")
CHAT = Chat(id=42, type="private")
ids = itertools.count(1000)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, EditMessageText, EditMessageReplyMarkup)):
            return Message(message_id=getattr(method, "message_id", None) or next(ids), date=datetime.now(),
                           chat=CHAT, text=getattr(method, "text", "") or "")
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield b""

    def texts(self):
        return [m.text for m in self.sent if isinstance(m, (SendMessage, EditMessageText))]


@pytest.fixture
def env(deps):
    session = FakeSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(AllowedUserMiddleware(42))
    dp.include_routers(commands.router, ask_h.router, notes.router)
    on_done, on_failed = notes.make_worker_callbacks(bot, deps)
    worker = Worker(deps, on_done=on_done, on_failed=on_failed)
    dp["deps"], dp["worker"] = deps, worker
    yield bot, dp, session, worker
    # routers are module-level singletons: detach so the next test can include them again
    for r in (commands.router, ask_h.router, notes.router):
        r._parent_router = None


def msg(text, user=ME):
    return Update(update_id=next(ids), message=Message(message_id=next(ids), date=datetime.now(), chat=CHAT,
                                                       from_user=user, text=text))


def cb(data, user=ME):
    m = Message(message_id=next(ids), date=datetime.now(), chat=CHAT, from_user=ME, text="x")
    return Update(update_id=next(ids), callback_query=CallbackQuery(id=str(next(ids)), from_user=user,
                                                                   chat_instance="c", message=m, data=data))


async def test_text_becomes_note_and_report_is_edited_in(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("катализатор на Киа Соул забит"))
    assert "Принял" in session.texts()[0]
    assert worker.queue.qsize() == 1
    await worker.run_one(worker.queue.get_nowait())
    report = session.sent[-1]
    assert isinstance(report, EditMessageText) and "Kia Soul" in report.text
    assert notes_db.get_note(deps.conn, 1)["tg_reply_id"] == report.message_id


async def test_stranger_is_ignored(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("привет", user=STRANGER))
    await dp.feed_update(bot, cb(NoteCB(action="delete", id=1).pack(), user=STRANGER))
    assert session.sent == [] and worker.queue.qsize() == 0


async def test_wrong_topic_flow_with_new_topic(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("научрук попросил правки к статье"))
    await worker.run_one(worker.queue.get_nowait())
    await dp.feed_update(bot, cb(NoteCB(action="wrong", id=1).pack()))
    assert isinstance(session.sent[-2], EditMessageReplyMarkup)
    await dp.feed_update(bot, cb(MoveCB(note_id=1, topic_id=0).pack()))
    assert "Как назвать" in session.texts()[-1]
    await dp.feed_update(bot, msg("Диссертация"))
    assert notes_db.get_note(deps.conn, 1)["topic_name"] == "Диссертация"
    assert deps.conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1


async def test_find_topics_stats_inbox(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("катализатор на Киа Соул забит"))
    await worker.run_one(worker.queue.get_nowait())
    for command in ("/find катализатор", "/topics", "/stats", "/inbox", "/help", "/nonsense"):
        await dp.feed_update(bot, msg(command))
    out = "\n".join(session.texts())
    assert "#1" in out and "Темы" in out and "Заметок: 1" in out and "Входящие пусты" in out
    assert "Не знаю такой команды" in out
    assert worker.queue.qsize() == 0   # commands are never saved as notes


async def test_ask_streams_answer_with_sources(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("катализатор на Киа Соул забит, ремонт 9 тысяч"))
    await worker.run_one(worker.queue.get_nowait())
    deps.settings.ask_edit_interval = 0
    await dp.feed_update(bot, msg("/ask сколько стоит ремонт катализатора?"))
    final = session.sent[-1]
    assert isinstance(final, EditMessageText) and "[#1]" in final.text and "Источники" in final.text
    assert final.reply_markup.inline_keyboard[0][0].text == "#1"
    assert deps.conn.execute("SELECT note_ids FROM asks").fetchone()[0] == "[1]"


async def test_delete_and_restore(env, deps):
    bot, dp, session, worker = env
    await dp.feed_update(bot, msg("катализатор"))
    await worker.run_one(worker.queue.get_nowait())
    await dp.feed_update(bot, cb(NoteCB(action="delete", id=1).pack()))
    assert notes_db.get_note(deps.conn, 1)["status"] == "deleted"
    await dp.feed_update(bot, cb(NoteCB(action="restore", id=1).pack()))
    assert notes_db.get_note(deps.conn, 1)["status"] == "done"
