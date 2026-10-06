"""Metrics and events for the web dashboard, stored in the same SQLite (tables metrics, metric_events).

The bot samples the server every 30 s and records every model call; the web only reads.
No psutil: /proc and /sys are enough on Linux (inside a container they show the host's memory and disk).
"""
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
RETENTION_DAYS = 90

GPU_FIELDS = {"temperature.gpu": "gpu_temp", "power.draw": "gpu_power", "memory.used": "gpu_vram",
              "utilization.gpu": "gpu_util", "pstate": "gpu_pstate"}


def _labels(labels: dict | None) -> str:
    return json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if labels else ""


def record(conn: sqlite3.Connection, name: str, value: float, labels: dict | None = None,
           ts: int | None = None) -> None:
    conn.execute("INSERT INTO metrics(ts, name, value, labels) VALUES (?, ?, ?, ?)",
                 (int(ts or time.time()), name, float(value), _labels(labels)))


def event(conn: sqlite3.Connection, kind: str, message: str, labels: dict | None = None) -> None:
    conn.execute("INSERT INTO metric_events(ts, kind, message, labels) VALUES (?, ?, ?, ?)",
                 (int(time.time()), kind, message, _labels(labels)))


# ---------- model calls ----------

TASK_NAMES = {"clean": "очистка", "classify": "разметка", "extract": "факты", "intent": "правка", "ask": "вопрос",
              "overview": "сводка", "split": "разделение", "embed": "эмбеддинги"}


def llm_hook(conn: sqlite3.Connection):
    """LLMClient.on_call -> rows in metrics (+ an event for cold loads and failures)."""

    def on_call(info: dict[str, Any]) -> None:
        model, task = info.get("model", "?"), info.get("task", "other")
        if info.get("invalid_json"):
            record(conn, "llm_invalid_json", 1, {"model": model, "task": task})
            return
        ok = bool(info.get("ok"))
        record(conn, "llm_call", 1, {"model": model, "task": task, "ok": int(ok), "cold": int(bool(info.get("cold")))})
        for key, name in (("tps", "llm_tps"), ("ttft", "llm_ttft"), ("seconds", "llm_seconds"),
                          ("prompt_tokens", "llm_prompt_tokens"), ("completion_tokens", "llm_completion_tokens")):
            if info.get(key) is not None and (task != "embed" or key == "seconds"):
                record(conn, name, info[key], {"model": model})
        if info.get("cold") and ok:
            event(conn, "model", f"Модель {model} загружена в память ({TASK_NAMES.get(task, task)}), "
                                 f"{info.get('seconds', 0):.0f} с", {"model": model})
        if not ok:
            event(conn, "error", f"Ошибка модели {model} ({TASK_NAMES.get(task, task)}): {info.get('error', '')}"[:300],
                  {"model": model})

    return on_call


# ---------- system sampling ----------

_cpu_prev: tuple[int, int] | None = None


def _cpu_percent() -> float | None:
    global _cpu_prev
    try:
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
    except OSError:
        return None
    idle, total = parts[3] + (parts[4] if len(parts) > 4 else 0), sum(parts)
    prev, _cpu_prev = _cpu_prev, (idle, total)
    if prev is None or total == prev[1]:
        return None
    return 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))


def _meminfo() -> tuple[float, float] | None:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"] - info["MemAvailable"], info["MemTotal"]
    except (OSError, KeyError, ValueError):
        return None


def _cpu_temp() -> float | None:
    best = None
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            kind = (zone / "type").read_text().strip()
            temp = int((zone / "temp").read_text()) / 1000
        except (OSError, ValueError):
            continue
        if kind in ("x86_pkg_temp", "coretemp", "cpu-thermal", "k10temp"):
            return temp
        best = temp if best is None else max(best, temp)
    return best


def read_gpu() -> dict[str, float] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    out = {}
    for (field, name), raw in zip(GPU_FIELDS.items(), r.stdout.strip().splitlines()[0].split(",")):
        raw = raw.strip().lstrip("P")  # pstate "P8" -> 8
        try:
            out[name] = float(raw)
        except ValueError:
            pass
    return out


def sample_system(conn: sqlite3.Connection, data_dir: Path) -> dict[str, float]:
    """One sample of everything the dashboard plots. Returns what was recorded."""
    now = int(time.time())
    values: dict[str, float] = {}
    gpu = read_gpu()
    if gpu:
        values.update(gpu)
    cpu = _cpu_percent()
    if cpu is not None:
        values["cpu_load"] = cpu
    mem = _meminfo()
    if mem:
        values["ram_used"], values["ram_total"] = mem
    try:
        du = shutil.disk_usage(data_dir)
        values["disk_used"], values["disk_total"] = du.used, du.total
    except OSError:
        pass
    temp = _cpu_temp()
    if temp is not None:
        values["cpu_temp"] = temp
    values["queue_length"] = conn.execute(
        "SELECT count(*) FROM notes WHERE status IN ('queued', 'processing')").fetchone()[0]
    for name, value in values.items():
        record(conn, name, value, ts=now)
    return values


# ---------- retention ----------

def compact(conn: sqlite3.Connection, days: int = RETENTION_DAYS) -> int:
    """Samples older than `days` become hourly averages (idempotent). Old events are dropped."""
    cutoff = int(time.time()) - days * 86400
    rows = conn.execute(
        """SELECT (ts / 3600) * 3600 AS hour, name, labels, avg(value) AS value, count(*) AS n FROM metrics
           WHERE ts < ? GROUP BY hour, name, labels""", (cutoff,)).fetchall()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        conn.executemany("INSERT INTO metrics(ts, name, value, labels) VALUES (?, ?, ?, ?)",
                         [(r["hour"], r["name"], r["value"], r["labels"]) for r in rows])
        conn.execute("DELETE FROM metric_events WHERE ts < ?", (cutoff,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return sum(r["n"] for r in rows)


def system_status(conn: sqlite3.Connection) -> dict:
    """Latest value of each system metric (within the last 5 minutes)."""
    since = int(time.time()) - 300
    rows = conn.execute(
        """SELECT name, value, ts FROM metrics m WHERE ts >= ? AND labels = '' AND ts = (
               SELECT max(ts) FROM metrics WHERE name = m.name AND labels = '' AND ts >= ?)""",
        (since, since)).fetchall()
    return {r["name"]: r["value"] for r in rows} | ({"sampled_at": max(r["ts"] for r in rows)} if rows else {})


def env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default
