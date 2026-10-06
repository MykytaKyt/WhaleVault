"""Night mode: llama-swap's ttl is the daytime value; at night the bot unloads models after a short idle."""
import logging
import time
from datetime import datetime, time as dtime

from ..llm.client import LLMClient

log = logging.getLogger(__name__)


def is_night(now: dtime, day_start: dtime, day_end: dtime) -> bool:
    return not (day_start <= now < day_end)


async def night_unload_job(llm: LLMClient, day_start: dtime, day_end: dtime, idle_seconds: int, gpu_lock,
                           conn=None) -> None:
    if not is_night(datetime.now().time(), day_start, day_end) or gpu_lock.locked():
        return
    if time.monotonic() - llm.last_activity < idle_seconds:
        return
    running = await llm.running()
    loaded = [m for m in (running or []) if m != llm.embed_model]
    if loaded:
        log.info("night idle: unloading %s", loaded)
        if await llm.unload() and conn is not None:
            from .. import metrics
            metrics.event(conn, "model", f"Ночью выгружена модель: {', '.join(loaded)} (простой {idle_seconds} с)")
