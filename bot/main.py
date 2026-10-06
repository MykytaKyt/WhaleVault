"""Entry point: python -m bot.main"""
import asyncio
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings, get_settings
from .db import notes as notes_db
from .db.connection import connect
from .deps import Deps
from .gpulock import GpuLock
from . import metrics
from .handlers import ask, commands, entities, notes, tasks
from .handlers.access import AllowedUserMiddleware
from .jobs.backup import backup
from .jobs.gpu import gpu_job
from .jobs.idle import night_unload_job
from .jobs.reminders import remind_job
from .llm.client import LLMClient
from .pipeline.overview import refresh_stale
from .pipeline.worker import Worker, reembed_dirty

log = logging.getLogger("bot")


def setup_logging(s: Settings) -> None:
    s.logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())
    for h in (RotatingFileHandler(s.logs_dir / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        root.addHandler(h)
    # Model failures with full prompt and response, for prompt debugging
    errors = RotatingFileHandler(s.logs_dir / "llm-errors.log", maxBytes=10_000_000, backupCount=3, encoding="utf-8")
    errors.setFormatter(fmt)
    logging.getLogger("llm.errors").addHandler(errors)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_deps(s: Settings) -> Deps:
    conn = connect(s.db_path, s.migrations_dir, s.embed_dim)
    llm = LLMClient(s.llm_url, routine=s.routine_model_name, answer=s.answer_model_name, embed=s.embed_model_name,
                    timeout=s.llm_timeout, json_schema_enabled=s.llm_json_schema)
    llm.on_call = metrics.llm_hook(conn)
    return Deps(settings=s, conn=conn, llm=llm, gpu_lock=GpuLock(s.data_dir / "gpu.lock"))


def schedule_jobs(s: Settings, deps: Deps, bot: Bot, worker: Worker) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=s.tz)

    async def alert(text: str) -> None:
        await bot.send_message(s.allowed_user_id, text)

    def do_backup() -> None:
        backup(s.db_path, s.data_dir, s.backup_dir, s.backup_keep)
        deps.conn.execute("INSERT OR REPLACE INTO kv(key, value) VALUES ('last_backup', ?)",
                          (datetime.now().strftime("%d.%m.%Y %H:%M"),))

    async def backup_job() -> None:
        await asyncio.to_thread(do_backup)

    async def purge_job() -> None:
        n = notes_db.purge_deleted(deps.conn, s.purge_deleted_days)
        if n:
            log.info("purged %d deleted notes", n)

    sched.add_job(gpu_job, "interval", minutes=s.gpu_log_minutes, args=[s.logs_dir, s.gpu_temp_alert, alert],
                  next_run_time=datetime.now())
    async def sample_job() -> None:
        await asyncio.to_thread(metrics.sample_system, deps.conn, s.data_dir)

    sched.add_job(sample_job, "interval", seconds=30, next_run_time=datetime.now())
    sched.add_job(metrics.compact, CronTrigger(hour=4, minute=40, timezone=s.tz), args=[deps.conn])
    sched.add_job(night_unload_job, "interval", seconds=30,
                  args=[deps.llm, s.llm_day_start, s.llm_day_end, s.llm_ttl_night, deps.gpu_lock, deps.conn])
    sched.add_job(reembed_dirty, "interval", minutes=10, args=[deps])

    async def pick_up_queued() -> None:
        # Notes re-queued from the web UI ("reprocess") live only in the database
        for nid in notes_db.pending_ids(deps.conn, include_processing=False):
            worker.enqueue(nid)

    sched.add_job(pick_up_queued, "interval", seconds=30)

    async def send(text, kb=None):
        await bot.send_message(s.allowed_user_id, text, reply_markup=kb)

    sched.add_job(remind_job, CronTrigger.from_crontab(s.remind_cron, timezone=s.tz), args=[deps, send])
    sched.add_job(backup_job, CronTrigger.from_crontab(s.backup_cron, timezone=s.tz))
    sched.add_job(purge_job, CronTrigger(hour=4, minute=50, timezone=s.tz))

    async def overview_job() -> None:
        n = await refresh_stale(deps)
        if n:
            metrics.event(deps.conn, "job", f"Ночью обновлены сводки тем: {n}")

    sched.add_job(overview_job, CronTrigger(hour=3, minute=30, timezone=s.tz))
    return sched


async def main() -> None:
    s = get_settings()
    setup_logging(s)
    if not s.telegram_token or not s.allowed_user_id:
        log.error("TELEGRAM_TOKEN and ALLOWED_USER_ID must be set in .env")
        sys.exit(1)
    deps = build_deps(s)
    bot = Bot(s.telegram_token, default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(AllowedUserMiddleware(s.allowed_user_id))
    dp.include_routers(commands.router, ask.router, entities.router, tasks.router, notes.router)

    on_done, on_failed = notes.make_worker_callbacks(bot, deps)
    worker = Worker(deps, on_done=on_done, on_failed=on_failed)
    dp["deps"], dp["worker"] = deps, worker

    await bot.set_my_commands([
        BotCommand(command="ask", description="Спросить по заметкам"),
        BotCommand(command="find", description="Поиск"),
        BotCommand(command="topics", description="Темы"),
        BotCommand(command="entities", description="Люди, машины, проекты"),
        BotCommand(command="todo", description="Задачи"),
        BotCommand(command="inbox", description="Не удалось разобрать"),
        BotCommand(command="stats", description="Статистика"),
    ])
    sched = schedule_jobs(s, deps, bot, worker)
    sched.start()
    worker.start()
    log.info("bot started, %d notes pending", worker.queue.qsize())
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.shutdown(wait=False)
        await worker.stop()
        await deps.llm.close()
        await bot.session.close()
        deps.conn.close()


if __name__ == "__main__":
    asyncio.run(main())
