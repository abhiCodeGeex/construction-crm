"""Working days (B+3): the company's working week and holidays (Settings -> Projects calendar).

Lags between linked tasks, moving the tasks that depend on a moved task, delay days and the finish forecast are
all counted in working days, so a Sunday or a festival holiday never counts as a day of work."""
from datetime import date, timedelta

from flask import g

from .defaults import DEFAULT_WORKING_DAYS


def calendar(company=None):
    c = (company or g.company).get("calendar") or {}
    days = c.get("working_days")
    return {"working_days": sorted(set(days)) if days else list(DEFAULT_WORKING_DAYS),
            "holidays": sorted(c.get("holidays") or [], key=lambda h: h["date"])}


def _cal(cal):
    cal = cal or calendar()
    return set(cal["working_days"]), {h["date"] for h in cal["holidays"]}


def is_working(day, cal=None):
    week, hols = _cal(cal)
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return d.weekday() in week and d.isoformat() not in hols


def add_working(day, n, cal=None):
    """The working day n working days after `day` (n < 0 goes back). n = 0 returns `day` itself."""
    week, hols = _cal(cal)
    if not week:
        return day
    d = date.fromisoformat(day)
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if d.weekday() in week and d.isoformat() not in hols:
            left -= 1
    return d.isoformat()


def between(a, b, cal=None):
    """Working days from a to b, counting both ends; negative when b is before a."""
    if not a or not b:
        return 0
    if b < a:
        return -between(b, a, cal)
    week, hols = _cal(cal)
    d, end, n = date.fromisoformat(a), date.fromisoformat(b), 0
    while d <= end:
        if d.weekday() in week and d.isoformat() not in hols:
            n += 1
        d += timedelta(days=1)
    return n


def shift(a, b, cal=None):
    """How many working days later b is than a (0 when the same day; negative when earlier)."""
    if not a or not b or a == b:
        return 0
    return between(a, b, cal) - (1 if is_working(a, cal) else 0) if b > a else -(between(b, a, cal) - (1 if is_working(b, cal) else 0))
