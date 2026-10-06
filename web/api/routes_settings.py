"""Settings: password change, reindex, export of the database and media."""
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bot.pipeline.embed import embed_note

from . import jobs
from .common import deps_of

router = APIRouter(prefix="/api")


class PasswordBody(BaseModel):
    current: str
    new: str = Field(..., min_length=8, max_length=200)


@router.post("/settings/password")
async def change_password(request: Request, body: PasswordBody) -> dict:
    if not request.app.state.auth.change_password(body.current, body.new):
        raise HTTPException(400, "Текущий пароль неверный")
    return {"ok": True}  # every session, including this one, is now logged out


@router.post("/settings/reindex")
async def reindex(request: Request) -> dict:
    """Recompute embeddings of every note (after changing the embedding model). CPU only, no GPU lock."""
    deps = deps_of(request)

    async def work(job_id: int) -> dict:
        ids = [r[0] for r in deps.conn.execute("SELECT id FROM notes WHERE status = 'done' ORDER BY id")]
        deps.conn.execute("UPDATE notes SET embed_dirty = 1 WHERE status = 'done'")
        failed = 0
        for i, nid in enumerate(ids, 1):
            try:
                await embed_note(deps, nid)
            except Exception:  # noqa: BLE001 — left dirty, the bot retries later
                failed += 1
            if i % 10 == 0 or i == len(ids):
                jobs.update(deps, job_id, progress=i / len(ids), message=f"{i} из {len(ids)} заметок")
        return {"notes": len(ids), "failed": failed}

    return jobs.start(deps, "reindex", None, work)


@router.get("/export")
async def export(request: Request, background: BackgroundTasks) -> FileResponse:
    """One zip: a consistent copy of notes.db (SQLite backup API) and data/media/."""
    deps = deps_of(request)
    tmp = Path(tempfile.mkdtemp(prefix="export-"))
    db_copy = tmp / "notes.db"
    dst = sqlite3.connect(db_copy)
    try:
        deps.conn.backup(dst)
    finally:
        dst.close()
    name = f"whalevault-{datetime.now():%Y-%m-%d_%H%M}.zip"
    archive = tmp / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(db_copy, "notes.db")
        media = deps.settings.data_dir / "media"
        if media.is_dir():
            for f in media.rglob("*"):
                if f.is_file():
                    z.write(f, f"media/{f.relative_to(media)}")
    background.add_task(_cleanup, tmp)
    return FileResponse(archive, media_type="application/zip", filename=name)


def _cleanup(tmp: Path) -> None:
    for f in tmp.iterdir():
        f.unlink()
    os.rmdir(tmp)
