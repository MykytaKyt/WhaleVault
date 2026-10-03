"""Only ALLOWED_USER_ID is served; every other update is dropped silently."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

log = logging.getLogger(__name__)


class AllowedUserMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_id: int):
        self.allowed = allowed_user_id

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.id != self.allowed:
            log.info("ignored update from user %s", user.id if user else None)
            return None
        return await handler(event, data)
