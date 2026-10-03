from types import SimpleNamespace

from bot.db import notes as notes_db
from bot.handlers import render
from bot.handlers.access import AllowedUserMiddleware
from bot.jobs.backup import backup
from bot.jobs.idle import is_night
from bot.pipeline.worker import Worker
from datetime import time


async def test_other_users_are_ignored():
    mw, seen = AllowedUserMiddleware(42), []

    async def handler(event, data):
        seen.append(data["event_from_user"].id)
        return "ok"
    assert await mw(handler, object(), {"event_from_user": SimpleNamespace(id=7)}) is None
    assert await mw(handler, object(), {"event_from_user": None}) is None
    assert await mw(handler, object(), {"event_from_user": SimpleNamespace(id=42)}) == "ok"
    assert seen == [42]


def test_split_text():
    text = "\n\n".join("абзац " * 100 for _ in range(20))
    parts = render.split_text(text)
    assert len(parts) > 1 and all(len(p) <= render.LIMIT for p in parts)
    assert render.split_text("коротко") == ["коротко"]


async def test_report_and_note_view_escape_html(deps):
    nid = notes_db.insert_note(deps.conn, "text", "катализатор <b>Киа</b> & ремонт")
    r = await Worker(deps).run_one(nid)
    text = render.report_text(deps.conn, r)
    assert "Kia Soul" in text and "<b>Киа</b>" not in text
    kb = render.report_kb(r)
    assert any(b.text == "↪️ Не туда" for row in kb.inline_keyboard for b in row)
    full = "".join(render.note_full(deps.conn, nid))
    assert "&lt;b&gt;" in full
    assert all(len(b.callback_data) <= 64 for row in render.move_kb(deps.conn, nid).inline_keyboard for b in row)


def test_night_window():
    assert is_night(time(23, 30), time(8), time(23))
    assert is_night(time(3, 0), time(8), time(23))
    assert not is_night(time(12, 0), time(8), time(23))


async def test_backup_keeps_n(deps, settings):
    notes_db.insert_note(deps.conn, "text", "x")
    for i in range(3):
        d = settings.backup_dir / f"2026-01-0{i + 1}_0000"
        d.mkdir(parents=True)
        (d / "notes.db").write_text("old")
    out = backup(settings.db_path, settings.data_dir, settings.backup_dir, keep=2)
    import sqlite3
    assert sqlite3.connect(out / "notes.db").execute("SELECT count(*) FROM notes").fetchone()[0] == 1
    assert len(list(settings.backup_dir.iterdir())) == 2
