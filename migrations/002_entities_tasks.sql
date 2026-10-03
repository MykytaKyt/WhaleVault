-- Stage 3: entities, facts, tasks, edits by reply.

-- Which bot message shows which note: a reply to any of them is an edit command for that note
CREATE TABLE tg_messages (
    message_id  INTEGER PRIMARY KEY,
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE
);

CREATE INDEX entities_kind ON entities(kind, name);
CREATE INDEX facts_entity ON facts(entity_id, created_at);
CREATE INDEX facts_note ON facts(note_id);
CREATE INDEX tasks_open ON tasks(status, due_at);
CREATE INDEX tasks_note ON tasks(note_id);

-- Pending merge proposals ("merge with the note about X" asks for confirmation first)
CREATE TABLE pending_merges (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
