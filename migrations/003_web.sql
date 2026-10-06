-- Web UI (docs: web spec): topic summaries, merged-topic redirects, contradiction review, jobs, metrics.

-- A merged topic keeps its row so old /t/<slug> links redirect to the target
ALTER TABLE topics ADD COLUMN merged_into INTEGER REFERENCES topics(id);
-- When the summary (topics.overview, markdown) was written, and whether notes changed since
ALTER TABLE topics ADD COLUMN overview_updated_at TEXT;
ALTER TABLE topics ADD COLUMN overview_stale INTEGER NOT NULL DEFAULT 1;

-- A contradiction (old.superseded_by = new) stays "to check" until the user picks the current fact
ALTER TABLE facts ADD COLUMN checked INTEGER NOT NULL DEFAULT 0;

-- Background operations started from the web (summary refresh, reindex, ...)
CREATE TABLE jobs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,             -- refresh_topic | split_topic | reindex
    target       TEXT,                      -- e.g. topic id
    status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    progress     REAL NOT NULL DEFAULT 0,   -- 0..1
    message      TEXT NOT NULL DEFAULT '',
    result       TEXT,                      -- JSON
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at  TEXT
);

-- Time series for the dashboard: raw samples for 90 days, then hourly averages
CREATE TABLE metrics (
    ts      INTEGER NOT NULL,               -- unix seconds
    name    TEXT NOT NULL,
    value   REAL NOT NULL,
    labels  TEXT NOT NULL DEFAULT ''        -- compact JSON, '' when none
);
CREATE INDEX metrics_name_ts ON metrics(name, ts);

-- Event log for the dashboard: model loads/unloads, cleanup runs, errors
CREATE TABLE metric_events (
    id       INTEGER PRIMARY KEY,
    ts       INTEGER NOT NULL,
    kind     TEXT NOT NULL,                 -- model | job | error | note | system
    message  TEXT NOT NULL,
    labels   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX metric_events_ts ON metric_events(ts);
