"""/entities: list of people, cars, projects, places → entity page with facts."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..deps import Deps
from . import render_more
from .cb import EntityCB

router = Router(name="entities")


@router.message(Command("entities"))
async def cmd_entities(message: Message, deps: Deps) -> None:
    text, kb = render_more.entities_kb(deps.conn)
    await message.answer(text, reply_markup=kb)


@router.callback_query(EntityCB.filter(F.id == 0))
async def cb_entities(cq: CallbackQuery, deps: Deps) -> None:
    text, kb = render_more.entities_kb(deps.conn)
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()


@router.callback_query(EntityCB.filter())
async def cb_entity(cq: CallbackQuery, callback_data: EntityCB, deps: Deps) -> None:
    parts, kb = render_more.entity_page(deps.conn, callback_data.id)
    for i, part in enumerate(parts):
        await cq.message.answer(part, reply_markup=kb if i == len(parts) - 1 else None)
    await cq.answer()
