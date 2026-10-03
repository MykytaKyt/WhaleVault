"""Callback-data factories for inline buttons (each fits Telegram's 64-byte limit)."""
from aiogram.filters.callback_data import CallbackData


class NoteCB(CallbackData, prefix="n"):
    # view | wrong | delete | restore | keep (save a question as a note) | retry | raw | back
    action: str
    id: int


class MoveCB(CallbackData, prefix="mv"):
    note_id: int
    topic_id: int  # 0 = create a new topic


class TopicCB(CallbackData, prefix="t"):
    id: int  # 0 = list of topics


class EntityCB(CallbackData, prefix="e"):
    id: int  # 0 = list of entities


class TaskCB(CallbackData, prefix="tk"):
    # done | postpone (show options) | due (set `date`; "" = no date) | list
    action: str
    id: int
    date: str = ""


class MergeCB(CallbackData, prefix="mg"):
    id: int      # pending_merges.id
    yes: int     # 1 = merge, 0 = keep apart
