"""Local date/time in the user's time zone (TZ in .env)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def today(tz: str) -> date:
    return now(tz).date()


def today_label(tz: str, d: date | None = None) -> str:
    d = d or today(tz)
    return f"{d.isoformat()} ({WEEKDAYS[d.weekday()]})"
