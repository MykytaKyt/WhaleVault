"""SQLite connection: WAL, foreign keys, sqlite-vec, numbered SQL migrations applied at startup."""
import logging
import sqlite3
from pathlib import Path

import sqlite_vec

log = logging.getLogger(__name__)


def connect(path: Path | str, migrations_dir: Path, embed_dim: int) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn, migrations_dir)
    ensure_vec_table(conn, embed_dim)
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    for f in sorted(migrations_dir.glob("*.sql")):
        if f.name in done:
            continue
        log.info("applying migration %s", f.name)
        conn.execute("BEGIN")
        try:
            # executescript would COMMIT on its own; run statements one by one inside our transaction
            for stmt in _split_sql(f.read_text(encoding="utf-8")):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (f.name,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _split_sql(script: str) -> list[str]:
    """Split a script into complete statements (handles triggers via sqlite3.complete_statement)."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf)
            buf = ""
    if buf.strip() and not all(l.strip().startswith("--") or not l.strip() for l in buf.splitlines()):
        out.append(buf)
    return out


def ensure_vec_table(conn: sqlite3.Connection, dim: int) -> None:
    """chunks_vec depends on the embedding dimension from .env, so it's created here, not in a migration."""
    row = conn.execute("SELECT value FROM kv WHERE key = 'embed_dim'").fetchone()
    if row and int(row[0]) != dim:
        log.warning("EMBED_DIM changed %s -> %s: recreating chunks_vec, run /reindex", row[0], dim)
        conn.execute("DROP TABLE IF EXISTS chunks_vec")
        conn.execute("UPDATE notes SET embed_dirty = 1")
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding float[{int(dim)}] distance_metric=cosine)"
    )
    conn.execute("INSERT OR REPLACE INTO kv(key, value) VALUES ('embed_dim', ?)", (str(dim),))


class Tx:
    """`with Tx(conn):` — BEGIN IMMEDIATE / COMMIT / ROLLBACK (connection is in autocommit mode)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
