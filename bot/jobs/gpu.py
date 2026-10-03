"""GPU log every N minutes into logs/gpu.csv, with a Telegram warning above the temperature limit."""
import asyncio
import csv
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
FIELDS = ["pstate", "power.draw", "temperature.gpu", "memory.used"]


def read_gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    r = subprocess.run(["nvidia-smi", f"--query-gpu={','.join(FIELDS)}", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        log.warning("nvidia-smi failed: %s", r.stderr.strip())
        return None
    return dict(zip(FIELDS, (x.strip() for x in r.stdout.strip().splitlines()[0].split(","))))


def append_csv(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", *FIELDS])
        w.writerow([datetime.now().isoformat(timespec="seconds"), *(row[k] for k in FIELDS)])


async def gpu_job(logs_dir: Path, temp_limit: int, alert) -> None:
    row = await asyncio.to_thread(read_gpu)
    if row is None:
        return
    append_csv(logs_dir / "gpu.csv", row)
    try:
        temp = float(row["temperature.gpu"])
    except ValueError:
        return
    if temp > temp_limit:
        await alert(f"🌡 GPU нагрелся до {temp:.0f} °C (порог {temp_limit} °C).")
