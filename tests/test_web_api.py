import json

import httpx
import pytest

from bot.db import notes as notes_db
from bot.db import tasks as tasks_db
from bot.pipeline.worker import Worker
from web.api.main import create_app


@pytest.fixture
def static(tmp_path):
    d = tmp_path / "static"
    (d / "_app" / "immutable").mkdir(parents=True)
    (d / "index.html").write_text("<html>spa</html>")
    (d / "_app" / "immutable" / "app.js").write_text("js")
    return d


@pytest.fixture
async def client(deps, static):
    deps.settings.web_password = "secret"
    app = create_app(deps, static_dir=static)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://web") as c:
        yield c


async def login(client):
    r = await client.post("/api/login", json={"password": "secret"})
    assert r.status_code == 200


async def add(deps, text):
    nid = notes_db.insert_note(deps.conn, "text", text)
    await Worker(deps).run_one(nid)
    return nid


async def test_auth_required_and_wrong_password(client):
    assert (await client.get("/api/notes")).status_code == 401
    assert (await client.post("/api/login", json={"password": "nope"})).status_code == 401
    await login(client)
    assert (await client.get("/api/me")).status_code == 200
    await client.post("/api/logout")
    client.cookies.clear()
    assert (await client.get("/api/notes")).status_code == 401


async def test_forged_cookie_rejected(client):
    client.cookies.set("nb_session", "9999999999.deadbeef")
    assert (await client.get("/api/notes")).status_code == 401


async def test_spa_fallback_and_static(client):
    assert (await client.get("/topics/3")).text == "<html>spa</html>"
    r = await client.get("/_app/immutable/app.js")
    assert r.text == "js" and "immutable" in r.headers["cache-control"]
    assert (await client.get("/../../etc/passwd")).text == "<html>spa</html>"   # no path traversal


async def test_notes_list_pagination_and_detail(client, deps):
    for i in range(5):
        await add(deps, f"катализатор на Киа Соул, заметка {i}")
    await login(client)
    r = (await client.get("/api/notes?limit=2")).json()
    assert len(r["items"]) == 2 and r["next"]
    seen = [n["id"] for n in r["items"]]
    while r["next"]:
        r = (await client.get("/api/notes", params={"limit": 2, "cursor": r["next"]})).json()
        seen += [n["id"] for n in r["items"]]
    assert seen == [5, 4, 3, 2, 1]
    card = (await client.get("/api/notes?limit=1")).json()["items"][0]
    assert card["topic"]["name"] == "Kia Soul" and card["tags"]
    d = (await client.get("/api/notes/1")).json()
    assert d["raw_text"].startswith("катализатор") and d["facts"] and d["topic"]["name"] == "Kia Soul"
    assert (await client.get("/api/notes/999")).status_code == 404


async def test_edit_note_fields(client, deps):
    nid = await add(deps, "катализатор на Киа Соул забит")
    other = await add(deps, "научрук попросил правки к статье")
    await login(client)
    other_topic = notes_db.get_note(deps.conn, other)["topic_id"]
    r = await client.patch(f"/api/notes/{nid}", json={"title": "Катализатор", "clean_text": "Новый текст про глушитель",
                                                      "tags": ["авто", "ремонт"], "topic_id": other_topic})
    d = r.json()
    assert d["title"] == "Катализатор" and d["clean_text"].startswith("Новый") and set(d["tags"]) == {"авто", "ремонт"}
    assert d["topic"]["id"] == other_topic
    assert deps.conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1   # like "Не туда"
    hits = (await client.get("/api/search", params={"q": "глушитель"})).json()
    assert hits[0]["id"] == nid
    assert notes_db.get_note(deps.conn, nid)["embed_dirty"] == 0                     # re-embedded in background


async def test_delete_undo_reprocess(client, deps):
    nid = await add(deps, "катализатор на Киа Соул")
    await login(client)
    await client.delete(f"/api/notes/{nid}")
    assert notes_db.get_note(deps.conn, nid)["status"] == "deleted"
    assert (await client.post(f"/api/notes/{nid}/restore")).json()["status"] == "done"
    await client.post(f"/api/notes/{nid}/reprocess")
    assert notes_db.get_note(deps.conn, nid)["status"] == "queued"


async def test_topics_rename_and_merge(client, deps):
    a = await add(deps, "катализатор на Киа Соул")
    b = await add(deps, "научрук попросил правки к статье")
    await login(client)
    ta, tb = (notes_db.get_note(deps.conn, x)["topic_id"] for x in (a, b))
    r = await client.patch(f"/api/topics/{ta}", json={"name": "Машина", "emoji": "🚙"})
    assert r.json()["name"] == "Машина"
    tname = notes_db.get_note(deps.conn, b)["topic_name"]
    assert (await client.patch(f"/api/topics/{ta}", json={"name": tname})).status_code == 409
    assert (await client.post(f"/api/topics/{tb}/merge", json={"into_id": ta})).json() == {"moved": 1}
    assert notes_db.get_note(deps.conn, b)["topic_id"] == ta
    assert (await client.get(f"/api/topics/{tb}")).status_code == 404
    side = (await client.get("/api/sidebar")).json()
    assert [t["name"] for t in side["topics"]] == ["Машина"] and side["notes"] == 2


async def test_entities_tasks_inbox(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "катализатор на Киа Соул забит")                  # duplicate
    nid = await add(deps, "спросить у Сергея контакты мастера завтра")
    await login(client)
    ents = (await client.get("/api/entities")).json()
    kia = next(e for e in ents if e["name"] == "Kia Soul")
    assert (await client.get(f"/api/entities/{kia['id']}")).json()["facts"]
    tasks = (await client.get("/api/tasks")).json()
    today_like = [t for g in tasks["groups"] for t in g["items"]]
    assert today_like[0]["note_title"]
    tid = today_like[0]["id"]
    assert (await client.patch(f"/api/tasks/{tid}", json={"due_at": "пятница"})).status_code == 400
    assert (await client.patch(f"/api/tasks/{tid}", json={"due_at": "2030-01-02"})).json()["due_at"] == "2030-01-02"
    assert (await client.patch(f"/api/tasks/{tid}", json={"status": "done"})).json()["status"] == "done"
    inbox = (await client.get("/api/inbox")).json()
    assert inbox["duplicates"] and inbox["duplicates"][0]["a"] == 1
    r = await client.post("/api/notes/2/merge", json={"target_id": 1})
    assert r.status_code == 200 and notes_db.get_note(deps.conn, 2)["status"] == "deleted"


async def test_ask_streams_sse(client, deps):
    await add(deps, "катализатор на Киа Соул забит, ремонт 9 тысяч")
    await login(client)
    events = []
    async with client.stream("POST", "/api/ask", json={"question": "сколько стоит ремонт катализатора?"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                events.append([line[7:], None])
            elif line.startswith("data:"):
                events[-1][1] = json.loads(line[5:])
    kinds = [e for e, _ in events]
    assert kinds[0] == "status" and "sources" in kinds and kinds[-1] == "done"
    text = "".join(d["t"] for e, d in events if e == "token")
    assert "[#1]" in text and events[-1][1]["cited"] == [1]
    history = (await client.get("/api/asks")).json()
    assert history[0]["note_ids"] == [1]


async def test_ask_not_found(client, deps):
    await login(client)
    async with client.stream("POST", "/api/ask", json={"question": "размер обуви?"}) as r:
        body = "".join([line async for line in r.aiter_lines()])
    assert "В заметках этого нет" in body


async def test_dismiss_duplicate(client, deps):
    await add(deps, "катализатор на Киа Соул забит")
    await add(deps, "катализатор на Киа Соул забит")
    await login(client)
    assert (await client.get("/api/inbox")).json()["duplicates"]
    await client.post("/api/duplicates/dismiss", json={"a": 1, "b": 2})
    assert (await client.get("/api/inbox")).json()["duplicates"] == []
