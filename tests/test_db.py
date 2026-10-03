import sqlite3

import pytest

from bot.db import notes as notes_db
from bot.db import topics as topics_db
from bot.db.connection import connect, migrate


def test_migrations_idempotent(deps, settings):
    migrate(deps.conn, settings.migrations_dir)
    names = {r[0] for r in deps.conn.execute("SELECT name FROM sqlite_master")}
    for t in ("notes", "topics", "tags", "note_tags", "entities", "facts", "tasks", "links", "chunks",
              "chunks_vec", "notes_fts", "feedback", "media", "asks"):
        assert t in names


def test_raw_text_is_immutable(deps):
    nid = notes_db.insert_note(deps.conn, "text", "оригинал")
    with pytest.raises(sqlite3.IntegrityError):
        deps.conn.execute("UPDATE notes SET raw_text = 'другое' WHERE id = ?", (nid,))
    deps.conn.execute("UPDATE notes SET clean_text = 'чисто' WHERE id = ?", (nid,))


def test_topic_create_reuses_same_name(deps):
    a = topics_db.create_topic(deps.conn, "Kia Soul", "машина")
    assert topics_db.create_topic(deps.conn, "  kia   soul ") == a
    b = topics_db.create_topic(deps.conn, "Кіа Соул")
    assert deps.conn.execute("SELECT slug FROM topics WHERE id = ?", (b,)).fetchone()[0] == "kia-soul-2"


def test_embed_dim_change_recreates_vec_table(settings):
    conn = connect(settings.db_path, settings.migrations_dir, 64)
    conn.close()
    conn = connect(settings.db_path, settings.migrations_dir, 128)
    assert conn.execute("SELECT value FROM kv WHERE key='embed_dim'").fetchone()[0] == "128"
    conn.close()
