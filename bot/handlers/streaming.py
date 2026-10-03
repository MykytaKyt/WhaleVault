"""Edit a Telegram message as text streams in: at most once per interval, continuing in a new
message past the length limit, tolerant to flood control and "message is not modified"."""
import asyncio
import logging
import time
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message

from .render import LIMIT

log = logging.getLogger(__name__)


class StreamEditor:
    def __init__(self, bot: Bot, message: Message, interval: float = 1.5, limit: int = LIMIT):
        self.bot, self.chat_id = bot, message.chat.id
        self.messages = [message]
        self.interval, self.limit = interval, limit
        self.done_text = ""     # text of finished (full) messages
        self.text = ""          # text of the current message
        self._shown = None
        self._last = 0.0

    async def _edit(self, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
        for _ in range(3):
            try:
                await self.bot.edit_message_text(text, chat_id=self.chat_id, message_id=self.messages[-1].message_id,
                                                 reply_markup=kb)
                self._shown = text
                return
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                raise

    async def status(self, text: str) -> None:
        await self._edit(text)

    async def push(self, piece: str) -> None:
        self.text += piece
        if len(escape(self.text)) > self.limit:
            cut = self.text.rfind("\n", 0, self.limit - 200)
            cut = cut if cut > self.limit // 2 else self.text.rfind(" ", 0, self.limit - 200)
            cut = cut if cut > 0 else self.limit - 200
            head, self.text = self.text[:cut], self.text[cut:].lstrip()
            await self._edit(escape(head))
            self.done_text += head
            self.messages.append(await self.bot.send_message(self.chat_id, "…"))
            self._last = time.monotonic()
        if time.monotonic() - self._last >= self.interval and self.text.strip():
            self._last = time.monotonic()
            await self._edit(escape(self.text) + " ▍")

    async def finish(self, kb: InlineKeyboardMarkup | None = None, footer: str = "") -> str:
        if not (self.done_text + self.text).strip():
            self.text = "Модель вернула пустой ответ. Попробуй переформулировать вопрос."
        await self._edit(escape(self.text) + footer, kb)
        return self.done_text + self.text
