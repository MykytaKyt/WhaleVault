"""Note queue: strictly one note at a time; two attempts, then status=failed (shown in /inbox)."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..db import notes as notes_db
from ..db import topics as topics_db
from ..deps import Deps
from ..llm.client import LLMError
from ..llm.schemas import NoteMarkup
from .classify import classify, fallback_topic, resolve_topic
from .clean import clean
from .embed import EmbedResult, embed_note
from .extract import Extracted, apply as apply_extraction
from .prepare import prepare

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


@dataclass
class NoteResult:
    note_id: int
    markup: NoteMarkup
    topic_id: int | None
    new_topic: bool
    is_question: bool
    embed: EmbedResult = field(default_factory=lambda: EmbedResult([], []))
    extracted: Extracted = field(default_factory=Extracted)


async def process_note(deps: Deps, note_id: int) -> NoteResult | None:
    """Run steps 2-6 for one note. Returns None if the note was deleted meanwhile."""
    conn = deps.conn
    note = notes_db.get_note(conn, note_id)
    if note is None or note["status"] == "deleted":
        return None
    notes_db.set_status(conn, note_id, "processing")
    text, context = prepare(note)

    async with deps.gpu_lock:
        clean_text = await clean(deps, text, context, note["source"])
        notes_db.set_clean_text(conn, note_id, clean_text)
        model_input = f"[{context}]\n{clean_text}" if context else clean_text
        markup = await classify(deps, model_input)

    if notes_db.get_note(conn, note_id)["status"] == "deleted":
        return None
    topic_id, new_topic = resolve_topic(conn, markup)
    status = "question" if markup.is_question else "done"
    notes_db.apply_markup(conn, note_id, title=markup.title, summary=markup.summary, topic_id=topic_id,
                          tags=markup.tags, status=status)
    result = NoteResult(note_id, markup, topic_id, new_topic, markup.is_question)
    if status == "done":
        result.extracted = apply_extraction(conn, note_id, markup.entities, markup.facts, markup.tasks, replace=True)
        try:
            result.embed = await embed_note(deps, note_id)
        except LLMError as e:
            # The note is filed; embed_dirty stays 1 and reembed_dirty() picks it up later
            log.warning("note %s: embedding postponed: %s", note_id, e)
    return result


async def reembed_dirty(deps: Deps, limit: int = 20) -> int:
    """Embed processed notes whose chunks are missing or stale (CPU only, no GPU lock)."""
    ids = [r[0] for r in deps.conn.execute(
        "SELECT id FROM notes WHERE status = 'done' AND embed_dirty = 1 ORDER BY id LIMIT ?", (limit,))]
    done = 0
    for nid in ids:
        try:
            await embed_note(deps, nid)
            done += 1
        except LLMError as e:
            log.warning("re-embed %s failed: %s", nid, e)
            break
    return done


async def finish_question_as_note(deps: Deps, note_id: int) -> EmbedResult:
    """The user chose to keep a question as a note. Facts/tasks of a question are not extracted.
    A question has no topic of its own (questions never create topics): it goes to the fallback topic."""
    if notes_db.get_note(deps.conn, note_id)["topic_id"] is None:
        topic_id, _ = fallback_topic(deps.conn)
        deps.conn.execute("UPDATE notes SET topic_id = ? WHERE id = ?", (topic_id, note_id))
    notes_db.set_status(deps.conn, note_id, "done")
    note = notes_db.get_note(deps.conn, note_id)
    notes_db.sync_fts(deps.conn, note_id)
    topics_db.recount(deps.conn, note["topic_id"])
    return await embed_note(deps, note_id)


class Worker:
    def __init__(self, deps: Deps,
                 on_done: Callable[[NoteResult], Awaitable[None]] | None = None,
                 on_failed: Callable[[int, str], Awaitable[None]] | None = None):
        self.deps = deps
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.on_done, self.on_failed = on_done, on_failed
        self._task: asyncio.Task | None = None
        self._queued: set[int] = set()

    def start(self) -> None:
        for nid in notes_db.pending_ids(self.deps.conn):
            self.enqueue(nid)
        self._task = asyncio.create_task(self._run(), name="note-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def enqueue(self, note_id: int) -> None:
        if note_id not in self._queued:
            self._queued.add(note_id)
            self.queue.put_nowait(note_id)

    async def run_one(self, note_id: int) -> NoteResult | None:
        """Process with retry policy. Public for tests and /inbox "retry"."""
        conn = self.deps.conn
        attempts = notes_db.bump_attempts(conn, note_id)
        try:
            result = await process_note(self.deps, note_id)
        except Exception as e:  # noqa: BLE001 — any failure keeps the note, never loses it
            log.exception("note %s failed (attempt %s)", note_id, attempts)
            if attempts < MAX_ATTEMPTS:
                notes_db.set_status(conn, note_id, "queued", str(e)[:500])
                self.enqueue(note_id)
            else:
                notes_db.set_status(conn, note_id, "failed", str(e)[:500])
                if self.on_failed:
                    await self.on_failed(note_id, str(e))
            return None
        if result and self.on_done:
            await self.on_done(result)
        return result

    async def _run(self) -> None:
        while True:
            note_id = await self.queue.get()
            self._queued.discard(note_id)
            try:
                await self.run_one(note_id)
            except Exception:  # noqa: BLE001 — callbacks must not kill the worker
                log.exception("worker callback failed for note %s", note_id)
            finally:
                self.queue.task_done()
