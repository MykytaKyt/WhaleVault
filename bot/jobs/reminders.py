"""Task reminders: at REMIND_CRON (09:00) on the due day and the day before."""
import logging
from html import escape

from ..clock import today
from ..db import tasks as tasks_db
from ..deps import Deps
from ..pipeline.edits import fmt_due

log = logging.getLogger(__name__)


async def remind_job(deps: Deps, send) -> int:
    """send(text, reply_markup) delivers one message. Returns the number of reminders sent."""
    from ..handlers.render_more import task_kb
    d = today(deps.settings.tz)
    sent = 0
    for t in tasks_db.due_for_reminder(deps.conn, d):
        when = "сегодня" if t["due_at"][:10] == d.isoformat() else "завтра"
        time_part = f" в {t['due_at'][11:16]}" if len(t["due_at"]) > 10 else ""
        src = f"\n<i>из заметки #{t['note_id']}</i>" if t["note_id"] else ""
        await send(f"⏰ <b>{when}{time_part}</b>: {escape(t['text'])}{src}", task_kb(t["id"]))
        tasks_db.mark_reminded(deps.conn, t["id"], d)
        sent += 1
    if sent:
        log.info("sent %d task reminders (%s)", sent, fmt_due(d.isoformat()))
    return sent
