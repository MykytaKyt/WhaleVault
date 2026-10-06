"""Background jobs started from the web (summary refresh, split proposal, reindex), tracked in the jobs table."""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from bot import metrics
from bot.deps import Deps

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()  # keep references so tasks aren't garbage-collected

JOB_NAMES = {"refresh_topic": "Обновление сводки", "split_topic": "Предложение разделить тему", "reindex": "Переиндексация"}


def get(deps: Deps, job_id: int) -> dict | None:
    r = deps.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def active(deps: Deps, kind: str, target: str | None = None) -> dict | None:
    r = deps.conn.execute("SELECT id FROM jobs WHERE kind = ? AND target IS ? AND status IN ('queued', 'running') "
                          "ORDER BY id DESC LIMIT 1", (kind, target)).fetchone()
    return get(deps, r["id"]) if r else None


def update(deps: Deps, job_id: int, *, progress: float | None = None, message: str | None = None) -> None:
    if progress is not None:
        deps.conn.execute("UPDATE jobs SET progress = ? WHERE id = ?", (max(0.0, min(progress, 1.0)), job_id))
    if message is not None:
        deps.conn.execute("UPDATE jobs SET message = ? WHERE id = ?", (message, job_id))


def start(deps: Deps, kind: str, target: str | None,
          work: Callable[[int], Awaitable[dict | None]]) -> dict:
    """Create the job (or return the running one for the same target) and run `work(job_id)` in the background."""
    running = active(deps, kind, target)
    if running:
        return running
    job_id = deps.conn.execute("INSERT INTO jobs(kind, target, status, message) VALUES (?, ?, 'queued', ?)",
                               (kind, target, "В очереди: жду, пока освободится модель")).lastrowid

    async def run() -> None:
        deps.conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
        try:
            result = await work(job_id)
            deps.conn.execute("UPDATE jobs SET status = 'done', progress = 1, message = '', result = ?, "
                              "finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                              (json.dumps(result, ensure_ascii=False) if result is not None else None, job_id))
            metrics.event(deps.conn, "job", f"{JOB_NAMES.get(kind, kind)}: готово", {"job": job_id})
        except Exception as e:  # noqa: BLE001 — the job row carries the error to the UI
            log.exception("job %s (%s) failed", job_id, kind)
            deps.conn.execute("UPDATE jobs SET status = 'failed', message = ?, "
                              "finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                              (friendly_error(e), job_id))
            metrics.event(deps.conn, "error", f"{JOB_NAMES.get(kind, kind)}: {friendly_error(e)}", {"job": job_id})

    task = asyncio.create_task(run(), name=f"job-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return get(deps, job_id)


def friendly_error(e: Exception) -> str:
    text = str(e)
    if any(s in text for s in ("ConnectError", "connection", "Connection", "Name or service not known")):
        return "Модель недоступна: контейнер llm не отвечает"
    return text[:300] or e.__class__.__name__
