import pytest

from bot.db import notes as notes_db
from bot.db import topics as topics_db
from bot.pipeline.embed import chunk_text
from bot.pipeline.worker import Worker, finish_question_as_note
from bot.search import fts

async def add(deps, text, source="text", context=""):
    nid = notes_db.insert_note(deps.conn, source, text, context)
    return await Worker(deps).run_one(nid), nid


async def test_note_end_to_end(deps):
    r, nid = await add(deps, "ну короче, на СТО сказали что катализатор на Киа Соул забит, ремонт 9 тысяч")
    note = notes_db.get_note(deps.conn, nid)
    assert note["status"] == "done"
    assert note["raw_text"].startswith("ну короче")          # raw never changes
    assert not note["clean_text"].startswith("ну")
    assert note["topic_name"] == "Kia Soul" and r.new_topic
    assert notes_db.get_tags(deps.conn, nid)
    assert deps.conn.execute("SELECT notes_count FROM topics WHERE id=?", (note["topic_id"],)).fetchone()[0] == 1
    assert deps.conn.execute("SELECT count(*) FROM chunks_vec").fetchone()[0] == 1
    assert note["embed_dirty"] == 0
    assert fts.search(deps.conn, "катализатора") == [nid]    # stemming: inflected form matches


async def test_existing_topic_is_reused_and_links_found(deps):
    await add(deps, "катализатор на Киа Соул забит")
    r, nid = await add(deps, "заменил масло на Киа Соул, следующий раз через 10 тысяч")
    assert not r.new_topic
    assert deps.conn.execute("SELECT count(*) FROM topics").fetchone()[0] == 1
    assert r.embed.similar and r.embed.similar[0][0] == 1


async def test_duplicate_detected(deps):
    await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    r, _ = await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    assert r.embed.duplicates and r.embed.duplicates[0][0] == 1


async def test_failed_twice_goes_to_inbox(deps):
    failed = []

    async def on_failed(nid, err):
        failed.append(nid)

    w = Worker(deps, on_failed=on_failed)
    deps.llm.fail_json = 2
    nid = notes_db.insert_note(deps.conn, "text", "что-то")
    await w.run_one(nid)
    assert notes_db.get_note(deps.conn, nid)["status"] == "queued"   # first failure: back to queue
    assert w.queue.qsize() == 1
    await w.run_one(nid)
    assert notes_db.get_note(deps.conn, nid)["status"] == "failed"
    assert failed == [nid] and [r["id"] for r in notes_db.failed_notes(deps.conn)] == [nid]


async def test_wrong_topic_feedback_steers_next_note(deps):
    # The fake model files "научрук ... статья" under "Наука"; the user moves it to "Диссертация"
    _, nid = await add(deps, "научрук попросил переписать введение статьи")
    thesis = topics_db.create_topic(deps.conn, "Диссертация", "всё по диссертации", "📚")
    old = notes_db.get_note(deps.conn, nid)["topic_id"]
    topics_db.move_note(deps.conn, nid, thesis)
    assert tuple(deps.conn.execute("SELECT from_topic_id, to_topic_id FROM feedback").fetchone()) == (old, thesis)
    assert deps.conn.execute("SELECT notes_count FROM topics WHERE id=?", (thesis,)).fetchone()[0] == 1
    assert deps.conn.execute("SELECT notes_count FROM topics WHERE id=?", (old,)).fetchone()[0] == 0
    # The correction is in the next classify prompt and the similar note follows it
    _, nid2 = await add(deps, "научрук прислал правки к введению статьи")
    prompt = deps.llm.calls[-1][1][-1]["content"]
    assert "Диссертация" in prompt.split("Past corrections")[1]
    assert notes_db.get_note(deps.conn, nid2)["topic_id"] == thesis


async def test_question_is_not_saved_until_kept(deps):
    r, nid = await add(deps, "что я записывал про катализатор?")
    assert r.is_question
    assert notes_db.get_note(deps.conn, nid)["status"] == "question"
    assert fts.search(deps.conn, "катализатор") == []
    await finish_question_as_note(deps, nid)
    assert fts.search(deps.conn, "катализатор") == [nid]


async def test_forward_context_reaches_model(deps):
    await add(deps, "встреча в пятницу", source="forward", context="Пересланное сообщение, автор: Сергей")
    clean_prompt = deps.llm.calls[0][1][-1]["content"]
    assert "Сергей" in clean_prompt


async def test_soft_delete_restore_and_purge(deps):
    _, nid = await add(deps, "катализатор на Киа Соул")
    tid = notes_db.get_note(deps.conn, nid)["topic_id"]
    notes_db.soft_delete(deps.conn, nid)
    assert fts.search(deps.conn, "катализатор") == []
    assert deps.conn.execute("SELECT notes_count FROM topics WHERE id=?", (tid,)).fetchone()[0] == 0
    notes_db.restore(deps.conn, nid)
    assert fts.search(deps.conn, "катализатор") == [nid]
    notes_db.soft_delete(deps.conn, nid)
    deps.conn.execute("UPDATE notes SET deleted_at = '2000-01-01T00:00:00Z' WHERE id = ?", (nid,))
    assert notes_db.purge_deleted(deps.conn, 30) == 1
    assert deps.conn.execute("SELECT count(*) FROM chunks_vec").fetchone()[0] == 0


async def test_deleted_while_queued_is_skipped(deps):
    nid = notes_db.insert_note(deps.conn, "text", "катализатор")
    notes_db.soft_delete(deps.conn, nid)
    assert await Worker(deps).run_one(nid) is None
    assert notes_db.get_note(deps.conn, nid)["status"] == "deleted"


def test_chunking():
    assert chunk_text("короткая заметка") == ["короткая заметка"]
    long = " ".join(f"Предложение номер {i} про что-то важное." for i in range(100))
    chunks = chunk_text(long, 500, 1000)
    assert len(chunks) > 3 and all(len(c) <= 1000 for c in chunks)
    assert chunk_text("x" * 2500, 500, 1000) == ["x" * 1000, "x" * 1000, "x" * 500]


async def test_embedding_outage_keeps_note_filed(deps):
    from bot.llm.client import LLMError
    from bot.pipeline.worker import reembed_dirty
    real = deps.llm.embed

    async def down(texts):
        raise LLMError("embed down")
    deps.llm.embed = down
    r, nid = await add(deps, "катализатор на Киа Соул забит")
    note = notes_db.get_note(deps.conn, nid)
    assert r is not None and note["status"] == "done" and note["embed_dirty"] == 1
    assert fts.search(deps.conn, "катализатор") == [nid]
    deps.llm.embed = real
    assert await reembed_dirty(deps) == 1
    assert notes_db.get_note(deps.conn, nid)["embed_dirty"] == 0
