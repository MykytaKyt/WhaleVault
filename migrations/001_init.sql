-- Full schema from the spec. Tables used by later stages (entities, facts, tasks, media)
-- are created now so stages 3-6 don't need to reshape existing data.

CREATE TABLE topics (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    slug         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    emoji        TEXT NOT NULL DEFAULT '',
    overview     TEXT NOT NULL DEFAULT '',
    notes_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE notes (
    id             INTEGER PRIMARY KEY,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source         TEXT NOT NULL CHECK (source IN ('text', 'voice', 'link', 'photo', 'forward')),
    raw_text       TEXT NOT NULL,          -- never modified after insert
    context        TEXT NOT NULL DEFAULT '', -- e.g. forward author; input for the model, not shown as the note
    clean_text     TEXT,
    title          TEXT,
    summary        TEXT,
    topic_id       INTEGER REFERENCES topics(id),
    -- queued -> processing -> done | failed; question = waiting for "save as note?"; deleted = soft delete
    status         TEXT NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued', 'processing', 'done', 'failed', 'question', 'deleted')),
    attempts       INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    embed_dirty    INTEGER NOT NULL DEFAULT 1, -- 1 = chunks/embeddings must be (re)computed
    deleted_at     TEXT,
    tg_message_id  INTEGER,
    tg_reply_id    INTEGER
);
CREATE INDEX notes_status ON notes(status);
CREATE INDEX notes_topic ON notes(topic_id, created_at);
CREATE INDEX notes_created ON notes(created_at);
CREATE INDEX notes_tg_reply ON notes(tg_reply_id);

-- raw_text is immutable
CREATE TRIGGER notes_raw_text_immutable BEFORE UPDATE OF raw_text ON notes
WHEN NEW.raw_text IS NOT OLD.raw_text
BEGIN
    SELECT RAISE(ABORT, 'raw_text is immutable');
END;

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    tag  TEXT NOT NULL UNIQUE
);
CREATE TABLE note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);

CREATE TABLE entities (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('person', 'car', 'project', 'place', 'other')),
    name        TEXT NOT NULL,
    aliases     TEXT NOT NULL DEFAULT '[]', -- JSON array
    page        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE facts (
    id             INTEGER PRIMARY KEY,
    entity_id      INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    note_id        INTEGER REFERENCES notes(id) ON DELETE SET NULL,
    text           TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    superseded_by  INTEGER REFERENCES facts(id)
);

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY,
    note_id      INTEGER REFERENCES notes(id) ON DELETE SET NULL,
    text         TEXT NOT NULL,
    due_at       TEXT,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
    reminded_at  TEXT
);

CREATE TABLE links (
    note_id          INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    related_note_id  INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    score            REAL NOT NULL,
    PRIMARY KEY (note_id, related_note_id)
);

CREATE TABLE chunks (
    chunk_id  INTEGER PRIMARY KEY,
    note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    text      TEXT NOT NULL
);
CREATE INDEX chunks_note ON chunks(note_id);

CREATE TABLE feedback (
    id             INTEGER PRIMARY KEY,
    note_id        INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    from_topic_id  INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    to_topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE media (
    id         INTEGER PRIMARY KEY,
    note_id    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    file_path  TEXT NOT NULL,
    mime       TEXT NOT NULL
);

-- /ask history (shown in the web "Ask" panel in stage 4)
CREATE TABLE asks (
    id          INTEGER PRIMARY KEY,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL DEFAULT '',
    note_ids    TEXT NOT NULL DEFAULT '[]', -- JSON array of source note ids
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Key/value for runtime state (last cleanup, last GPU alert, ...)
CREATE TABLE kv (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Full-text index; rowid = notes.id. Maintained by the app (bot/db/notes.py), not triggers.
CREATE VIRTUAL TABLE notes_fts USING fts5(
    title, summary, clean_text,
    tokenize = 'unicode61 remove_diacritics 2'
);
