import asyncio
import json
import zipfile
import io

import httpx
import pytest

from bot import metrics
from bot.db import notes as notes_db
from bot.pipeline.worker import Worker
from bot.pipeline.overview import preview, refresh_stale
from web.api.main import create_app


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "_app" / "immutable").mkdir(parents=True)
    (d / "index.html").write_text('<html><script>boot()</script>spa</html>')
    (d / "_app" / "immutable" / "app.js").write_text("js")
    return d


@pytest.fixture
async def client(deps, dist):
    deps.settings.web_password = "secret-pass"
    app = create_app(deps, dist=dist)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://web") as c:
        c.app = app
        yield c


async def login(client, password="secret-pass"):
    return await client.post("/api/auth/login", json={"password": password})


async def add(deps, text):
    nid = notes_db.insert_note(deps.conn, "text", text)
    await Worker(deps).run_one(nid)
    return nid


async def wait_job(client, job):
    for _ in range(100):
        job = (await client.get(f"/api/jobs/{job['id']}")).json()
        if job["status"] in ("done", "failed"):
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(job)


def kia_slug(deps):
    return deps.conn.execute("SELECT slug FROM topics WHERE name = 'Kia Soul'").fetchone()[0]


# ---------- access ----------

async def test_auth_health_errors_headers(client):
    r = await client.get("/api/notes")
    assert r.status_code == 401 and r.json() == {"error": {"code": 401, "message": "Нужно войти"}}
    assert (await client.get("/api/health")).json()["status"] == "ok"           # no session needed
    assert (await login(client, "wrong")).status_code == 401
    assert (await login(client)).status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.get("/api/nope")).json()["error"]["code"] == 404
    bad = await client.get("/api/notes?limit=abc")
    assert bad.status_code == 400 and "limit" in bad.json()["error"]["message"]
    page = await client.get("/n/5")
    assert "spa" in page.text and page.headers["x-frame-options"] == "DENY"
    csp = page.headers["content-security-policy"]
    assert "'sha256-" in csp and "frame-ancestors 'none'" in csp and "http" not in csp


async def test_password_hash_lockout_and_change(client, deps):
    stored = json.loads((deps.settings.data_dir / "web_password.json").read_text())
    assert stored["hash"].startswith("$argon2") and "secret-pass" not in stored["hash"]
    for _ in range(5):
        await login(client, "wrong")
    r = await login(client)                                                       # even the right one waits
    assert r.status_code == 429 and "Подождите" in r.json()["error"]["message"]
    client.app.state.auth.failures.clear()
    await login(client)
    assert (await client.post("/api/settings/password", json={"current": "x", "new": "new-pass-123"})).status_code == 400
    assert (await client.post("/api/settings/password", json={"current": "secret-pass", "new": "new-pass-123"})).json()["ok"]
    assert (await client.get("/api/auth/me")).status_code == 401                  # all sessions logged out
    assert (await login(client)).status_code == 401
    assert (await login(client, "new-pass-123")).status_code == 200


# ---------- topics ----------

async def test_topics_list_detail_refresh(client, deps):
    for t in ("катализатор на Киа Соул забит", "теперь по Киа Соул ремонт 12 тысяч", "научрук попросил правки к статье"):
        await add(deps, t)
    await login(client)
    topics = (await client.get("/api/topics")).json()
    assert {t["name"] for t in topics} == {"Kia Soul", "Наука"} and all(t["new_today"] for t in topics)
    assert not topics[0]["has_overview"] and topics[0]["overview_stale"]
    slug = kia_slug(deps)
    t = (await client.get(f"/api/topics/{slug}")).json()
    assert t["notes_count"] == 2 and t["entities"][0]["name"] == "Kia Soul" and t["tags"]
    async with deps.gpu_lock:                          # the bot is busy with a note: the refresh has to wait
        job = (await client.post(f"/api/topics/{slug}/refresh")).json()
        await asyncio.sleep(0.05)
        again = (await client.post(f"/api/topics/{slug}/refresh")).json()
        assert again["id"] == job["id"]                                           # one refresh at a time
        assert (await client.get(f"/api/topics/{slug}")).json()["job"]["id"] == job["id"]
    job = await wait_job(client, job)
    assert job["status"] == "done"
    t = (await client.get(f"/api/topics/{slug}")).json()
    assert t["overview"].startswith("## Что известно") and "[#" in t["overview"] and not t["overview_stale"]
    card = next(x for x in (await client.get("/api/topics")).json() if x["slug"] == slug)
    assert card["preview"].startswith("Катализатор забит") and "[#" not in card["preview"]
    # A new note makes the summary stale again
    await add(deps, "купить масло для Киа Соул")
    assert (await client.get(f"/api/topics/{slug}")).json()["overview_stale"]


async def test_refresh_fails_clearly_when_llm_down(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await login(client)
    deps.llm.fail_chat = True
    job = await wait_job(client, (await client.post(f"/api/topics/{kia_slug(deps)}/refresh")).json())
    assert job["status"] == "failed" and "Модель недоступна" in job["message"]
    assert (await client.get("/api/notes")).status_code == 200                    # the rest keeps working


async def test_topic_notes_filter_rename_merge_redirect(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "купить масло для Киа Соул")
    await add(deps, "научрук попросил правки к статье")
    await login(client)
    kia = kia_slug(deps)
    sci = deps.conn.execute("SELECT slug FROM topics WHERE name = 'Наука'").fetchone()[0]
    assert len((await client.get(f"/api/topics/{kia}/notes")).json()["items"]) == 2
    assert [n["id"] for n in (await client.get(f"/api/topics/{kia}/notes?tag=купить")).json()["items"]] == [2]
    assert [n["id"] for n in (await client.get(f"/api/topics/{kia}/notes?sort=old")).json()["items"]] == [1, 2]
    r = await client.patch(f"/api/topics/{kia}", json={"name": "Наука"})
    assert r.status_code == 409 and "объедините" in r.json()["error"]["message"]
    assert (await client.patch(f"/api/topics/{kia}", json={"emoji": "🚙"})).json()["emoji"] == "🚙"
    r = (await client.post("/api/topics/merge", json={"source": sci, "target": kia})).json()
    assert r["moved"] == 1 and r["target"] == kia
    assert (await wait_job(client, r["job"]))["status"] == "done"                # target summary rewritten
    assert "Что известно" in (await client.get(f"/api/topics/{kia}")).json()["overview"]
    assert (await client.get(f"/api/topics/{sci}")).json() == {"redirect": kia}  # old links keep working
    assert [t["slug"] for t in (await client.get("/api/topics")).json()] == [kia]


async def test_split_proposal_and_apply(client, deps):
    for t in ("катализатор на Киа Соул забит", "купить масло для Киа Соул", "заменил свечи на Киа Соул"):
        await add(deps, t)
    await login(client)
    slug = kia_slug(deps)
    job = await wait_job(client, (await client.post(f"/api/topics/{slug}/split")).json())
    groups = job["result"]["groups"]
    assert len(groups) == 2 and sum(len(g["note_ids"]) for g in groups) == 3
    r = (await client.post(f"/api/topics/{slug}/split/apply", json={"groups": groups})).json()
    assert len(r["created"]) == 2
    names = {t["name"] for t in (await client.get("/api/topics")).json()}
    assert {"Ремонт", "Обслуживание"} <= names


# ---------- notes ----------

async def test_notes_feed_filters_and_detail(client, deps):
    for i in range(5):
        await add(deps, f"катализатор на Киа Соул, заметка {i}")
    await add(deps, "научрук попросил правки к статье")
    deps.conn.execute("UPDATE notes SET source = 'voice' WHERE id = 6")
    await login(client)
    r = (await client.get("/api/notes?limit=2")).json()
    seen = [n["id"] for n in r["items"]]
    while r["next"]:
        r = (await client.get("/api/notes", params={"limit": 2, "cursor": r["next"]})).json()
        seen += [n["id"] for n in r["items"]]
    assert seen == [6, 5, 4, 3, 2, 1]
    assert [n["id"] for n in (await client.get("/api/notes?source=voice")).json()["items"]] == [6]
    assert len((await client.get(f"/api/notes?topic={kia_slug(deps)}")).json()["items"]) == 5
    assert (await client.get("/api/notes?from=2999-01-01")).json()["items"] == []
    assert (await client.get("/api/notes?source=fax")).status_code == 400
    d = (await client.get("/api/notes/1")).json()
    assert d["topic"]["slug"] == kia_slug(deps) and d["facts"] and d["media"] == []
    assert (await client.get("/api/tags")).json()


async def test_edit_note_reembeds_and_reextracts(client, deps):
    nid = await add(deps, "катализатор на Киа Соул забит")
    other = await add(deps, "научрук попросил правки к статье")
    await login(client)
    target = notes_db.get_note(deps.conn, other)["topic_id"]
    d = (await client.patch(f"/api/notes/{nid}", json={
        "title": "Катализатор", "clean_text": "Надо позвонить Сергею про глушитель на Киа Соул",
        "tags": ["авто"], "topic_id": target})).json()
    assert d["title"] == "Катализатор" and d["tags"] == ["авто"] and d["topic"]["id"] == target
    assert deps.conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1
    assert (await client.get("/api/search", params={"q": "глушитель"})).json()[0]["id"] == nid
    note = (await client.get(f"/api/notes/{nid}")).json()
    assert note["tasks"] and "позвонить" in note["tasks"][0]["text"].lower()        # facts/tasks re-extracted
    assert note["raw_text"] == "катализатор на Киа Соул забит"                       # raw never changes


async def test_delete_restore_reprocess_media(client, deps, tmp_path):
    nid = await add(deps, "катализатор на Киа Соул")
    media = deps.settings.data_dir / "media"
    media.mkdir(parents=True)
    (media / "a.ogg").write_bytes(b"OggS")
    mid = deps.conn.execute("INSERT INTO media(note_id, file_path, mime) VALUES (?, 'media/a.ogg', 'audio/ogg')",
                            (nid,)).lastrowid
    evil = deps.conn.execute("INSERT INTO media(note_id, file_path, mime) VALUES (?, '../web_secret', 'text/plain')",
                             (nid,)).lastrowid
    await login(client)
    assert (await client.get(f"/api/media/{mid}")).content == b"OggS"
    assert (await client.get(f"/api/media/{evil}")).status_code == 404               # stays inside data/media
    assert (await client.get(f"/api/notes/{nid}")).json()["media"][0]["mime"] == "audio/ogg"
    await client.delete(f"/api/notes/{nid}")
    assert (await client.post(f"/api/notes/{nid}/restore")).json()["status"] == "done"
    await client.post(f"/api/notes/{nid}/reprocess")
    assert notes_db.get_note(deps.conn, nid)["status"] == "queued"


# ---------- entities, tasks, inbox ----------

async def test_entities_contradiction_resolve(client, deps):
    await add(deps, "катализатор на Киа Соул: ремонт 9 тысяч")
    await add(deps, "теперь по Киа Соул ремонт 12 тысяч")
    await login(client)
    kia = next(e for e in (await client.get("/api/entities")).json() if e["name"] == "Kia Soul")
    assert kia["to_check"] == 1
    e = (await client.get(f"/api/entities/{kia['id']}")).json()
    [pair] = e["contradictions"]
    assert "9 тысяч" in pair["old"]["text"] and "12 тысяч" in pair["new"]["text"]
    # The user says the old value is right after all
    await client.post(f"/api/facts/{pair['old']['id']}/resolve")
    e = (await client.get(f"/api/entities/{kia['id']}")).json()
    assert e["contradictions"] == []
    by_id = {f["id"]: f for f in e["facts"]}
    assert by_id[pair["old"]["id"]]["superseded_by"] is None
    assert by_id[pair["new"]["id"]]["superseded_by"] == pair["old"]["id"]
    r = (await client.patch(f"/api/entities/{kia['id']}", json={"name": "Kia Soul 2016", "aliases": ["Киа", "Киа"]})).json()
    assert r["name"] == "Kia Soul 2016" and r["aliases"] == ["Киа"]


async def test_tasks_and_inbox(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "спросить у Сергея контакты мастера завтра")
    queued = notes_db.insert_note(deps.conn, "text", "ещё в очереди")
    await login(client)
    tasks = (await client.get("/api/tasks")).json()
    [t] = [t for g in tasks["groups"] for t in g["items"]]
    assert t["note_title"] and {g["label"] for g in tasks["groups"]} >= {"Просрочено", "Без срока"}
    assert (await client.patch(f"/api/tasks/{t['id']}", json={"due_at": "пятница"})).status_code == 400
    assert (await client.patch(f"/api/tasks/{t['id']}", json={"status": "done"})).json()["status"] == "done"
    inbox = (await client.get("/api/inbox")).json()
    assert [n["id"] for n in inbox["processing"]] == [queued]
    d = inbox["duplicates"][0]
    assert (await client.post(f"/api/duplicates/{d['a']}/{d['b']}", json={"action": "distinct"})).json()["ok"]
    assert (await client.get("/api/inbox")).json()["duplicates"] == []
    assert (await client.post("/api/duplicates/1/2", json={"action": "merge"})).json()["ok"]
    assert notes_db.get_note(deps.conn, 2)["status"] == "deleted"


# ---------- search, ask ----------

async def test_search_highlights(client, deps):
    await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    await add(deps, "научрук попросил правки к статье")
    await login(client)
    [hit] = [h for h in (await client.get("/api/search", params={"q": "катализатора"})).json() if h["id"] == 1]
    assert any(s["hit"] and s["t"].lower().startswith("катализатор") for s in hit["snippet"])
    assert hit["topic_slug"] and not hit["by_meaning"]


async def read_sse(client, url):
    events = []
    async with client.stream("GET", url) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in r.headers                                 # gzip would buffer the stream
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                events.append([line[7:], None])
            elif line.startswith("data:"):
                events[-1][1] = json.loads(line[5:])
    return events


async def test_ask_post_then_stream_then_history(client, deps):
    await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    await login(client)
    ask_id = (await client.post("/api/ask", json={"question": "сколько стоит ремонт катализатора?", "thinking": True})).json()["id"]
    events = await read_sse(client, f"/api/ask/{ask_id}/stream")
    kinds = [e for e, _ in events]
    assert kinds[0] == "status" and "sources" in kinds and kinds[-1] == "done"
    assert "".join(d["t"] for e, d in events if e == "token") == deps.llm.answer_text
    again = await read_sse(client, f"/api/ask/{ask_id}/stream")                 # replay, no second generation
    assert [e for e, _ in again] == ["sources", "token", "done"]
    assert sum(1 for m, _ in deps.llm.calls if m == "answer") == 1
    h = (await client.get("/api/ask/history")).json()
    assert h[0]["note_ids"] == [1]
    assert (await client.get(f"/api/ask/{ask_id}")).json()["sources"][0]["id"] == 1


async def test_ask_llm_down_is_explained(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await login(client)

    async def down(*a, **k):
        raise __import__("bot.llm.client", fromlist=["LLMError"]).LLMError("answer: ConnectError")
        yield  # pragma: no cover
    deps.llm.stream = down
    ask_id = (await client.post("/api/ask", json={"question": "что с катализатором?"})).json()["id"]
    events = await read_sse(client, f"/api/ask/{ask_id}/stream")
    assert events[-1][0] == "error" and "Модель недоступна" in events[-1][1]["text"]


# ---------- dashboard, settings ----------

async def test_dashboard(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    hook = metrics.llm_hook(deps.conn)
    hook({"model": "routine", "task": "classify", "ok": True, "cold": True, "seconds": 3, "tps": 35, "ttft": 0.2})
    hook({"model": "routine", "task": "classify", "invalid_json": True})
    for i, (p, v) in enumerate([(30, 3000), (30, 3000), (7, 0)]):
        metrics.record(deps.conn, "gpu_power", p, ts=1_900_000_000 - 120 + i * 30)
        metrics.record(deps.conn, "gpu_vram", v, ts=1_900_000_000 - 120 + i * 30)
    metrics.record(deps.conn, "gpu_temp", 82)
    metrics.record(deps.conn, "disk_used", 90)
    metrics.record(deps.conn, "disk_total", 100)
    await login(client)
    live = (await client.get("/api/metrics/live")).json()
    assert live["levels"] == {"gpu_temp": "warn", "disk": "warn"} and live["models_loaded"] == []
    r = await client.get("/api/metrics/summary?period=month")
    assert r.headers["content-encoding"] == "gzip"                               # big JSON is compressed
    s = r.json()
    assert s["models"]["total_calls"] == 1 and s["models"]["cold_share"] == 1
    assert s["models"]["invalid_json_share"] == 1 and s["models"]["per_model"][0]["tps_avg"] == 35
    assert s["models"]["calls"]["tasks"][0]["label"] == "разметка"
    assert s["pipeline"]["latency_median_all"] is not None and s["pipeline"]["sources"]["text"][-1] == 1
    assert s["quality"]["notes"][-1] == 1 and len(s["quality"]["corrections_by_week"]) == 12
    events = (await client.get("/api/metrics/events")).json()
    assert any("загружена" in e["message"] for e in events)
    assert (await client.get("/api/metrics/summary?period=year")).status_code == 400


async def test_reindex_and_export(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await login(client)
    job = await wait_job(client, (await client.post("/api/settings/reindex")).json())
    assert job["status"] == "done" and job["result"] == {"notes": 1, "failed": 0}
    r = await client.get("/api/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "notes.db" in z.namelist() and r.headers["content-type"] == "application/zip"


def test_preview_strips_citations_cleanly():
    md = "## Что известно\n**Ремонт** оценили в 12 000 грн [#3] [#7].\n- масло [#4], фильтр\n\n## Открытые вопросы и задачи\n- x"
    assert preview(md) == "Ремонт оценили в 12 000 грн. масло, фильтр"


async def test_nightly_refresh_only_stale_topics(deps):
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "научрук попросил правки к статье")
    assert await refresh_stale(deps) == 2
    assert await refresh_stale(deps) == 0                                         # nothing changed since
    await add(deps, "купить масло для Киа Соул")
    assert await refresh_stale(deps) == 1
