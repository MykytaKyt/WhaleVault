"""/start /help /topics /find /inbox /stats."""
import asyncio
import shutil
import subprocess
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import notes as notes_db
from ..deps import Deps
from ..search.hybrid import search
from . import render
from .cb import NoteCB, TopicCB

router = Router(name="commands")

HELP = """<b>Вторая память</b>
Просто присылай текст — я сохраню и разложу по темам. Вопрос с «?» тоже пойму.
Ответь (reply) на моё сообщение о заметке, чтобы её поправить: «перенеси в Киа», «это на пятницу»,
«объедини с заметкой про катализатор», «тег ремонт», «удали» — или просто допиши, что забыл.

/ask вопрос — ответ по заметкам
/find слово — поиск
/topics — темы
/entities — люди, машины, проекты
/todo — задачи
/inbox — что не удалось разобрать
/stats — статистика и GPU"""


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("topics"))
async def cmd_topics(message: Message, deps: Deps) -> None:
    kb = render.topics_kb(deps.conn)
    if not kb.inline_keyboard:
        await message.answer("Тем пока нет — пришли первую заметку.")
        return
    await message.answer("<b>Темы</b>", reply_markup=kb)


@router.callback_query(TopicCB.filter(F.id == 0))
async def cb_topics(cq: CallbackQuery, deps: Deps) -> None:
    await cq.message.edit_text("<b>Темы</b>", reply_markup=render.topics_kb(deps.conn))
    await cq.answer()


@router.callback_query(TopicCB.filter())
async def cb_topic(cq: CallbackQuery, callback_data: TopicCB, deps: Deps) -> None:
    text, kb = render.topic_page(deps.conn, callback_data.id)
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject, deps: Deps) -> None:
    q = (command.args or "").strip()
    if not q:
        await message.answer("Что искать? <code>/find катализатор</code>")
        return
    hits = await search(deps.conn, deps.llm, q, limit=10, embed_timeout=3.0)
    await message.answer(render.hits_text(hits, q), reply_markup=render.ids_kb([h.id for h in hits]))


@router.message(Command("inbox"))
async def cmd_inbox(message: Message, deps: Deps) -> None:
    rows = notes_db.failed_notes(deps.conn)
    if not rows:
        await message.answer("📭 Входящие пусты: все заметки разобраны.")
        return
    lines, kb = ["<b>Не удалось разобрать</b>"], InlineKeyboardBuilder()
    for r in rows:
        lines.append(f"\n#{r['id']} · {render.date(r['created_at'])}\n{escape(r['raw_text'][:200])}")
        kb.button(text=f"🔁 #{r['id']}", callback_data=NoteCB(action="retry", id=r["id"]))
        kb.button(text=f"🗑 #{r['id']}", callback_data=NoteCB(action="delete", id=r["id"]))
    kb.adjust(2)
    await message.answer("\n".join(lines)[:4000], reply_markup=kb.as_markup())


def gpu_status() -> str:
    if not shutil.which("nvidia-smi"):
        return "нет доступа к nvidia-smi"
    r = subprocess.run(["nvidia-smi", "--query-gpu=pstate,power.draw,temperature.gpu,memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return "ошибка nvidia-smi"
    p, power, temp, mem, util = [x.strip() for x in r.stdout.strip().split(",")]
    return f"{p}, {power} Вт, {temp} °C, {mem} МБ, загрузка {util}%"


@router.message(Command("stats"))
async def cmd_stats(message: Message, deps: Deps) -> None:
    s = notes_db.stats(deps.conn)
    db = deps.settings.db_path
    size = sum(p.stat().st_size for p in db.parent.glob(db.name + "*") if p.is_file()) / 1024 / 1024
    kv = dict(deps.conn.execute("SELECT key, value FROM kv").fetchall())
    running = await deps.llm.running()
    loaded = ", ".join(running) if running else ("ничего" if running is not None else "н/д")
    await message.answer(
        f"<b>Статистика</b>\n"
        f"📝 Заметок: {s['notes']} (в очереди {s['queued']}, не разобрано {s['failed']})\n"
        f"📁 Тем: {s['topics']}\n"
        f"🧩 Чанков: {s['chunks']}\n"
        f"💾 База: {size:.1f} МБ\n"
        f"🎛 GPU: {escape(await asyncio.to_thread(gpu_status))}\n"
        f"🧠 В памяти: {escape(loaded)}\n"
        f"🧹 Последняя уборка: {escape(kv.get('last_cleanup', 'ещё не было'))}\n"
        f"🗄 Последний бэкап: {escape(kv.get('last_backup', 'ещё не было'))}"
    )
