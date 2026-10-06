"""Dashboard: server and model health, pipeline, database quality, energy, event log. No model needed."""
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from bot import metrics
from bot.metrics import TASK_NAMES

from .common import deps_of

router = APIRouter(prefix="/api/metrics")
PERIODS = {"day": (86400, 600), "week": (7 * 86400, 3600), "month": (30 * 86400, 4 * 3600)}
HARDWARE = ("gpu_temp", "gpu_power", "gpu_vram", "gpu_util", "cpu_load", "cpu_temp", "ram_used", "disk_used",
            "queue_length")


def level(value, warn, error=None, below=False) -> str:
    if value is None:
        return "unknown"
    bad = (lambda v, t: v < t) if below else (lambda v, t: v > t)
    if error is not None and bad(value, error):
        return "error"
    return "warn" if bad(value, warn) else "ok"


@router.get("/live")
async def live(request: Request) -> dict:
    deps = deps_of(request)
    s = metrics.system_status(deps.conn)
    running = await deps.llm.running()
    disk_free = (1 - s["disk_used"] / s["disk_total"]) if s.get("disk_total") else None
    kv = dict(deps.conn.execute("SELECT key, value FROM kv").fetchall())
    queue = deps.conn.execute("SELECT count(*) FROM notes WHERE status IN ('queued', 'processing')").fetchone()[0]
    return {
        "online": True,
        "sampled_at": s.get("sampled_at"),
        "stale": s.get("sampled_at") is None,  # the bot isn't sampling (stopped?)
        "llm_reachable": running is not None,
        "models_loaded": [m for m in (running or []) if m != deps.llm.embed_model],
        "embed_loaded": deps.llm.embed_model in (running or []),
        "gpu": {k: s.get(f"gpu_{k}") for k in ("temp", "power", "vram", "util", "pstate")},
        "cpu_load": s.get("cpu_load"), "cpu_temp": s.get("cpu_temp"),
        "ram_used": s.get("ram_used"), "ram_total": s.get("ram_total"),
        "disk_used": s.get("disk_used"), "disk_total": s.get("disk_total"), "disk_free_share": disk_free,
        "queue": queue,
        "last_cleanup": kv.get("last_cleanup"), "last_backup": kv.get("last_backup"),
        "levels": {"gpu_temp": level(s.get("gpu_temp"), 80, 85), "disk": level(disk_free, 0.15, below=True)},
    }


@router.get("/series")
async def series(request: Request, name: str, step: int = 600) -> dict:
    q = request.query_params
    now = int(time.time())
    start, end = int(q.get("from", now - 86400)), int(q.get("to", now))
    step = max(60, min(step, 86400))
    rows = deps_of(request).conn.execute(
        "SELECT (ts / ?) * ? AS b, avg(value) AS v FROM metrics WHERE name = ? AND labels = '' AND ts BETWEEN ? AND ? "
        "GROUP BY b ORDER BY b", (step, step, name, start, end)).fetchall()
    return {"name": name, "t": [r["b"] for r in rows], "v": [r["v"] for r in rows]}


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def _day(ts: int, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


@router.get("/summary")
async def summary(request: Request, period: str = "day") -> dict:
    if period not in PERIODS:
        raise HTTPException(400, "period: day, week или month")
    deps = deps_of(request)
    conn, s = deps.conn, deps.settings
    tz = ZoneInfo(s.tz)
    span, step = PERIODS[period]
    now = int(time.time())
    start = now - span

    # --- hardware: one line per metric
    hardware = {}
    for name in HARDWARE:
        rows = conn.execute(
            "SELECT (ts / ?) * ? AS b, avg(value) AS v FROM metrics WHERE name = ? AND labels = '' AND ts >= ? "
            "GROUP BY b ORDER BY b", (step, step, name, start)).fetchall()
        hardware[name] = {"t": [r["b"] for r in rows], "v": [r["v"] for r in rows]}

    # --- models
    calls_by_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total = cold = failed = 0
    for r in conn.execute("SELECT ts, labels FROM metrics WHERE name = 'llm_call' AND ts >= ?", (start,)):
        lab = json.loads(r["labels"] or "{}")
        calls_by_day[_day(r["ts"], tz)][lab.get("task", "other")] += 1
        if lab.get("task") != "embed":
            total += 1
            cold += lab.get("cold", 0)
            failed += 1 - lab.get("ok", 1)
    per_model = defaultdict(lambda: {"tps": [], "ttft": []})
    for name, key in (("llm_tps", "tps"), ("llm_ttft", "ttft")):
        for r in conn.execute("SELECT value, labels FROM metrics WHERE name = ? AND ts >= ?", (name, start)):
            per_model[json.loads(r["labels"] or "{}").get("model", "?")][key].append(r["value"])
    structured = conn.execute(
        "SELECT count(*) FROM metrics WHERE name = 'llm_call' AND ts >= ? AND "
        "(labels LIKE '%\"task\":\"classify\"%' OR labels LIKE '%\"task\":\"extract\"%' OR "
        "labels LIKE '%\"task\":\"intent\"%' OR labels LIKE '%\"task\":\"split\"%')", (start,)).fetchone()[0]
    invalid = conn.execute("SELECT count(*) FROM metrics WHERE name = 'llm_invalid_json' AND ts >= ?",
                           (start,)).fetchone()[0]
    days = sorted(calls_by_day)
    tasks_seen = sorted({t for d in calls_by_day.values() for t in d})
    models = {
        "calls": {"days": days, "tasks": [{"task": t, "label": TASK_NAMES.get(t, t),
                                           "values": [calls_by_day[d].get(t, 0) for d in days]} for t in tasks_seen]},
        "per_model": [{"model": m, "tps_avg": statistics.fmean(v["tps"]) if v["tps"] else None,
                       "tps_p95": _pct(v["tps"], 0.95), "ttft_avg": statistics.fmean(v["ttft"]) if v["ttft"] else None,
                       "ttft_p95": _pct(v["ttft"], 0.95), "calls": len(v["tps"]) or len(v["ttft"])}
                      for m, v in sorted(per_model.items())],
        "total_calls": total, "cold_share": cold / total if total else None,
        "error_share": failed / total if total else None,
        "invalid_json_share": invalid / structured if structured else None,
    }

    # --- pipeline
    lat = defaultdict(list)
    for r in conn.execute("SELECT ts, value FROM metrics WHERE name = 'note_latency' AND ts >= ?", (start,)):
        lat[_day(r["ts"], tz)].append(r["value"])
    since_iso = datetime.fromtimestamp(start).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failed_by_day: dict[str, int] = defaultdict(int)
    for r in conn.execute("SELECT created_at, source, status FROM notes WHERE created_at >= ? AND status != 'deleted'",
                          (since_iso,)):
        d = _day(int(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).timestamp()), tz)
        by_source[d][r["source"]] += 1
        if r["status"] == "failed":
            failed_by_day[d] += 1
    pdays = sorted(set(lat) | set(by_source))
    all_lat = [v for vs in lat.values() for v in vs]
    pipeline = {
        "days": pdays,
        "latency_median": [statistics.median(lat[d]) if lat.get(d) else None for d in pdays],
        "latency_p95": [_pct(lat.get(d, []), 0.95) for d in pdays],
        "latency_median_all": statistics.median(all_lat) if all_lat else None,
        "latency_p95_all": _pct(all_lat, 0.95),
        "sources": {src: [by_source[d].get(src, 0) for d in pdays] for src in ("text", "voice", "link", "photo", "forward")},
        "failed": [failed_by_day.get(d, 0) for d in pdays],
    }

    # --- quality (at least the last 4 weeks, so trends are visible)
    qdays = max(span // 86400, 28)
    today = datetime.now(tz).date()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(qdays - 1, -1, -1)]
    note_days = [r[0] for r in conn.execute("SELECT substr(created_at, 1, 10) FROM notes WHERE status = 'done'")]
    topic_days = [r[0] for r in conn.execute(
        "SELECT substr(created_at, 1, 10) FROM topics WHERE merged_into IS NULL AND notes_count > 0")]
    weeks = []
    for w in range(11, -1, -1):
        w_end = today - timedelta(days=7 * w)
        w_start = w_end - timedelta(days=6)
        processed = conn.execute("SELECT count(*) FROM notes WHERE status IN ('done', 'deleted') AND "
                                 "substr(created_at, 1, 10) BETWEEN ? AND ?", (w_start.isoformat(), w_end.isoformat())).fetchone()[0]
        fixed = conn.execute("SELECT count(*) FROM feedback WHERE substr(created_at, 1, 10) BETWEEN ? AND ?",
                             (w_start.isoformat(), w_end.isoformat())).fetchone()[0]
        weeks.append({"week": w_start.isoformat(), "notes": processed, "corrections": fixed,
                      "share": fixed / processed if processed else None})
    month_ago = (datetime.now(tz) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    stale = conn.execute("SELECT slug, name, emoji, overview_updated_at FROM topics WHERE merged_into IS NULL AND "
                         "notes_count > 0 AND (overview_updated_at IS NULL OR overview_updated_at < ?) ORDER BY name",
                         (month_ago,)).fetchall()
    quality = {
        "days": day_list,
        "notes": [sum(1 for d in note_days if d <= day) for day in day_list],
        "topics": [sum(1 for d in topic_days if d <= day) for day in day_list],
        "corrections_by_week": weeks,
        "stale_topics": [dict(r) for r in stale],
        "contradictions_to_check": conn.execute(
            "SELECT count(*) FROM facts WHERE superseded_by IS NOT NULL AND checked = 0").fetchone()[0],
    }

    # --- energy: integral of GPU power, split by tariff
    wh: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # day -> [day Wh, night Wh]
    samples = conn.execute("SELECT ts, value FROM metrics WHERE name = 'gpu_power' AND labels = '' AND ts >= ? "
                           "ORDER BY ts", (start,)).fetchall()
    for a, b in zip(samples, samples[1:]):
        dt = min(b["ts"] - a["ts"], 120)  # a gap (bot stopped) doesn't count as power drawn
        moment = datetime.fromtimestamp(a["ts"], tz)
        night = _is_night(moment.time(), s.energy_night_start, s.energy_night_end)
        wh[moment.strftime("%Y-%m-%d")][1 if night else 0] += a["value"] * dt / 3600
    vram = [r[0] for r in conn.execute("SELECT value FROM metrics WHERE name = 'gpu_vram' AND labels = '' AND ts >= ?",
                                       (start,))]
    edays = sorted(wh)
    energy = {
        "days": edays, "wh": [sum(wh[d]) for d in edays],
        "cost": [(wh[d][0] * s.energy_price_day + wh[d][1] * s.energy_price_night) / 1000 for d in edays],
        "currency": s.energy_currency, "priced": bool(s.energy_price_day or s.energy_price_night),
        "gpu_empty_share": sum(1 for v in vram if v < 100) / len(vram) if vram else None,
    }
    return {"period": period, "hardware": hardware, "models": models, "pipeline": pipeline,
            "quality": quality, "energy": energy}


def _is_night(t: dtime, start: dtime, end: dtime) -> bool:
    return (t >= start or t < end) if start > end else (start <= t < end)


@router.get("/events")
async def events(request: Request, kind: str | None = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM metric_events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC LIMIT ?"
    args = (kind, min(limit, 500)) if kind else (min(limit, 500),)
    return [dict(r) for r in deps_of(request).conn.execute(q, args)]
