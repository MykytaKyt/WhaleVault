from datetime import date, timedelta

from bot.clock import today
from bot.db import entities as entities_db
from bot.db import notes as notes_db
from bot.db import tasks as tasks_db
from bot.handlers import render_more
from bot.jobs.reminders import remind_job
from bot.pipeline import edits
from bot.pipeline.worker import Worker, process_note
from bot.search import fts


async def add(deps, text):
    nid = notes_db.insert_note(deps.conn, "text", text)
    return await Worker(deps).run_one(nid), nid


def facts(deps, name):
    e = entities_db.find_entity(deps.conn, name)
    return entities_db.facts_for_page(deps.conn, e["id"]) if e else []


async def test_entity_and_fact_extracted(deps):
    r, nid = await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    assert [n for _, n in r.extracted.entities] == ["Kia Soul"]
    e = entities_db.find_entity(deps.conn, "kia soul")
    assert e["kind"] == "car"
    [f] = facts(deps, "Kia Soul")
    assert f["note_id"] == nid and "9 тысяч" in f["text"]


async def test_contradiction_supersedes_old_fact(deps):
    await add(deps, "катализатор на Киа Соул: ремонт 9 тысяч")
    # The known fact (with its id) must reach the prompt so the model can point at it
    await add(deps, "теперь по Киа Соул ремонт 12 тысяч")
    assert "fact_id=1 [Kia Soul]" in deps.llm.calls[-1][1][-1]["content"]
    old, new = facts(deps, "Kia Soul")
    assert old["superseded_by"] == new["id"] and new["superseded_by"] is None
    parts, _ = render_more.entity_page(deps.conn, entities_db.find_entity(deps.conn, "Kia Soul")["id"])
    page = "\n".join(parts)
    assert "<s>" in page and "12 тысяч" in page.split("↳")[1]


def test_aliases_merge(deps):
    a = entities_db.upsert_entity(deps.conn, "Kia Soul", "car")
    assert entities_db.upsert_entity(deps.conn, "Кіа Соул", "car", ["Kia Soul"]) == a
    assert entities_db.find_entity(deps.conn, "кіа соул")["id"] == a
    assert [r["id"] for r in entities_db.mentioned(deps.conn, "заехал на кіа соулі в сервис")] == [a]


async def test_task_with_relative_date(deps):
    r, nid = await add(deps, "спросить у Сергея контакты мастера в пятницу")
    [(tid, text, due)] = r.extracted.tasks
    d = today(deps.settings.tz)
    friday = d + timedelta(days=(4 - d.weekday()) % 7 or 7)
    assert due == friday.isoformat()
    assert r.extracted.facts == 0          # a plan is a task, not a fact
    text, kb = render_more.todo(deps.conn, d)
    assert "Сергея" in text and kb is not None


async def test_reprocessing_does_not_duplicate(deps):
    _, nid = await add(deps, "купить масло для Киа Соул завтра")
    deps.conn.execute("UPDATE notes SET status = 'queued' WHERE id = ?", (nid,))
    await process_note(deps, nid)
    assert len(tasks_db.tasks_of_note(deps.conn, nid)) == 1


def test_task_groups():
    d = date(2026, 10, 3)
    rows = [{"due_at": x} for x in ("2026-10-01", "2026-10-03T10:00", "2026-10-06", "2026-11-01", None)]
    g = tasks_db.group(rows, d)
    assert [len(g[k]) for k, _ in tasks_db.GROUPS] == [1, 1, 1, 1, 1]


async def test_reminders_today_and_day_before(deps):
    d = today(deps.settings.tz)
    tasks_db.add_task(deps.conn, None, "сегодня", d.isoformat())
    tasks_db.add_task(deps.conn, None, "завтра", (d + timedelta(days=1)).isoformat())
    tasks_db.add_task(deps.conn, None, "потом", (d + timedelta(days=5)).isoformat())
    sent = []

    async def send(text, kb):
        sent.append(text)
    assert await remind_job(deps, send) == 2
    assert await remind_job(deps, send) == 0        # once per day
    assert any("сегодня" in t for t in sent) and any("завтра" in t for t in sent)


async def test_deleted_note_hides_facts_and_tasks_then_purge(deps):
    _, nid = await add(deps, "катализатор на Киа Соул забит")
    _, tid_note = await add(deps, "купить коврики в Киа Соул")
    notes_db.soft_delete(deps.conn, nid)
    notes_db.soft_delete(deps.conn, tid_note)
    assert facts(deps, "Kia Soul") == []
    assert tasks_db.open_tasks(deps.conn) == []
    deps.conn.execute("UPDATE notes SET deleted_at = '2000-01-01T00:00:00Z'")
    notes_db.purge_deleted(deps.conn, 30)
    assert deps.conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 0
    assert deps.conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


# ---------- edits by reply ----------

async def edit(deps, note_id, text):
    intent = await edits.classify_edit(deps, note_id, text)
    return await edits.apply_edit(deps, note_id, intent, text)


async def test_edit_move_rename_tag_delete(deps):
    _, nid = await add(deps, "катализатор на Киа Соул забит")
    _, other = await add(deps, "научрук попросил правки к статье")
    out = await edit(deps, other, "перенеси в Kia")
    assert notes_db.get_note(deps.conn, other)["topic_name"] == "Kia Soul"
    assert deps.conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1 and out.ok
    await edit(deps, nid, "назови «Ремонт катализатора»")
    assert notes_db.get_note(deps.conn, nid)["title"] == "Ремонт катализатора"
    assert fts.search(deps.conn, "ремонт") == [nid]
    await edit(deps, nid, "тег ремонт")
    assert "ремонт" in notes_db.get_tags(deps.conn, nid)
    out = await edit(deps, nid, "удали")
    assert notes_db.get_note(deps.conn, nid)["status"] == "deleted" and out.intent == "delete"


async def test_edit_set_task_date(deps):
    _, nid = await add(deps, "катализатор на Киа Соул забит")
    out = await edit(deps, nid, "это на пятницу")           # no task yet: one is created from the title
    [t] = tasks_db.tasks_of_note(deps.conn, nid)
    assert t["due_at"] and out.ok
    tasks_db.add_task(deps.conn, nid, "вторая", None)
    out = await edit(deps, nid, "это на пятницу")           # several tasks: ask which one
    assert len(out.task_choices) == 2 and out.date


async def test_edit_merge_needs_confirmation(deps):
    _, a = await add(deps, "катализатор на Киа Соул забит")
    _, b = await add(deps, "купить коврики в Киа Соул")
    out = await edit(deps, b, "объедини с заметкой про катализатор")
    assert out.merge_id and notes_db.get_note(deps.conn, b)["status"] == "done"   # nothing happens yet
    res = await edits.merge(deps, out.merge_id)
    assert res.ok
    assert notes_db.get_note(deps.conn, b)["status"] == "deleted"
    assert "коврики" in notes_db.get_note(deps.conn, a)["clean_text"]
    assert [t["note_id"] for t in tasks_db.open_tasks(deps.conn)] == [a]
    assert not (await edits.merge(deps, out.merge_id)).ok                         # used once


async def test_edit_none_appends_clarification(deps):
    _, nid = await add(deps, "катализатор на Киа Соул забит")
    raw = notes_db.get_note(deps.conn, nid)["raw_text"]
    out = await edit(deps, nid, "и ещё надо позвонить Сергею насчёт гарантии")
    note = notes_db.get_note(deps.conn, nid)
    assert out.intent == "none" and note["raw_text"] == raw
    assert note["clean_text"].endswith("и ещё надо позвонить Сергею насчёт гарантии")
    assert fts.search(deps.conn, "гарантии") == [nid]
    assert out.extracted.tasks and note["embed_dirty"] == 0


async def test_question_note_hides_its_facts(deps):
    _, nid = await add(deps, "катализатор на Киа Соул забит")
    notes_db.mark_question(deps.conn, nid)
    assert facts(deps, "Kia Soul") == []
