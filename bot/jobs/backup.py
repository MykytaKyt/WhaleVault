"""Daily backup: a consistent copy of notes.db (SQLite backup API) + media, keep the newest N.

Also runnable by hand: python -m bot.jobs.backup  (scripts/backup.sh does it inside the container).
"""
import logging
import sqlite3
import tarfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def backup(db_path: Path, data_dir: Path, backup_dir: Path, keep: int) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    target = backup_dir / stamp
    target.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target / "notes.db"))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    media = data_dir / "media"
    if media.is_dir() and any(media.iterdir()):
        with tarfile.open(target / "media.tar", "w") as tar:
            tar.add(media, arcname="media")
    for old in sorted((p for p in backup_dir.iterdir() if p.is_dir()), reverse=True)[keep:]:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    log.info("backup written to %s", target)
    return target


if __name__ == "__main__":
    from ..config import get_settings
    s = get_settings()
    print(backup(s.db_path, s.data_dir, s.backup_dir, s.backup_keep))
