from bot import ask
from bot.db import notes as notes_db
from bot.pipeline.worker import Worker
from bot.search.hybrid import Hit, rrf, search


async def seed(deps, *texts):
    for t in texts:
        await Worker(deps).run_one(notes_db.insert_note(deps.conn, "text", t))


def test_rrf_prefers_items_in_both_lists():
    assert [n for n, _ in rrf([1, 2, 3], [3, 4])][0] == 3


async def test_hybrid_search(deps):
    await seed(deps, "катализатор на Киа Соул забит", "научрук попросил правки к статье", "записаться к врачу")
    hits = await search(deps.conn, deps.llm, "катализатор", limit=10)
    assert hits[0].id == 1 and hits[0].topic == "Kia Soul"


async def test_search_survives_embedding_failure(deps):
    await seed(deps, "катализатор на Киа Соул забит")

    from bot.llm.client import LLMError

    async def down(texts):
        raise LLMError("embed down")
    deps.llm.embed = down
    hits = await search(deps.conn, deps.llm, "катализатор")
    assert [h.id for h in hits] == [1]


async def test_ask_not_found_without_model_call(deps):
    p = await ask.plan(deps, "что с катализатором?")
    assert p.hits == []
    assert [x async for x in ask.stream_answer(deps, p)] == [ask.NOT_FOUND]
    assert not any(m == "answer" for m, _ in deps.llm.calls)


async def test_ask_uses_notes_and_cites(deps):
    await seed(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    p = await ask.plan(deps, "сколько стоит ремонт катализатора?")
    assert "[#1]" in p.messages[1]["content"]
    answer = "".join([x async for x in ask.stream_answer(deps, p)])
    assert ask.cited_ids(answer, p.hits) == [1]
    assert ask.cited_ids("см. [#1] и [#99]", p.hits) == [1]   # never link notes that weren't in context


def test_context_trimmed_from_least_relevant():
    hits = [Hit(id=i, title=f"t{i}", summary=f"кратко {i}", clean_text="х" * 3000, topic="T",
                created_at="2026-10-01T00:00:00Z", score=1 / (i + 1)) for i in range(8)]
    ctx = ask.build_context(hits, budget_tokens=4000)
    assert ask.estimate_tokens(ctx) <= 4000
    assert "х" * 3000 in ctx.split("[#1]")[0]            # most relevant keeps full text
    assert "кратко 7" in ctx                              # least relevant shrunk to summary
