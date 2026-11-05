"""Project health, finish forecast and "waiting on whom" (Phase B+ block 4).

Health is a score out of 100 made of six plain parts, each with the reason it lost points, so anyone can see
why a project is red. Green >= 75 ("On track"), amber 50-74 ("At risk"), red < 50 ("Off track").

Forecast: at the pace a stage has kept so far (progress per working day since it started), when will it finish?
A stage that should have started but has 0% progress needs its whole duration from today."""
import math
from datetime import date, datetime

from flask import g

from ..db import db
from . import workdays
from .defaults import WAITING_PARTIES

GRADES = ((75, "green", "On track"), (50, "amber", "At risk"), (0, "red", "Off track"))


def stage_forecast(s, today, cal):
    """Forecast finish of one stage and how many working days late that is against its planned end."""
    start, end = s.get("start"), s.get("end")
    if not start or not end or s.get("status") == "done":
        return {"forecast": end, "late_days": 0, "basis": "done" if s.get("status") == "done" else "no dates"}
    if today < start:
        return {"forecast": end, "late_days": 0, "basis": "not started yet"}
    planned = max(1, workdays.between(start, end, cal))
    progress = s.get("progress", 0)
    if progress <= 0:
        fc = workdays.add_working(today, planned - 1, cal) if workdays.is_working(today, cal) else workdays.add_working(today, planned, cal)
        basis = "should have started; no progress yet"
    else:
        elapsed = max(1, workdays.between(start, today, cal))  # working days since the stage started
        needed = math.ceil(elapsed / (progress / 100))
        fc = workdays.add_working(start, needed - 1, cal) if workdays.is_working(start, cal) else workdays.add_working(start, needed, cal)
        if fc < today:
            fc = today  # not done yet, so it cannot finish in the past
        basis = f"{progress}% done in {elapsed} working day(s)"
    late = workdays.shift(end, fc, cal) if fc > end else 0
    return {"forecast": fc, "late_days": late, "basis": basis}


def forecast(p, today=None):
    today = today or date.today().isoformat()
    cal = workdays.calendar()
    stages = []
    for s in p.get("stages", []):
        f = stage_forecast(s, today, cal)
        stages.append({"id": s["id"], "name": s["name"], "planned_end": s.get("end"), **f})
    ends = [x["forecast"] for x in stages if x["forecast"]]
    fc = max(ends) if ends else p.get("planned_end")
    planned = p.get("planned_end")
    late = workdays.shift(planned, fc, cal) if fc and planned and fc > planned else 0
    worst = max(stages, key=lambda x: x["late_days"], default=None)
    return {"project_forecast": fc, "planned_end": planned, "late_days": late, "stages": stages,
            "message": (f"At the current pace {worst['name']} finishes {worst['late_days']} working day(s) late "
                        f"({worst['forecast']} instead of {worst['planned_end']})") if worst and worst["late_days"] else
                       "At the current pace every stage finishes on time"}


def waiting(p, today=None):
    """Open items held up by someone: blocked tasks, open issues waiting on a party, stages ready but missing the
    client's sign-off. Each has the party, since when and how many days."""
    today = today or date.today().isoformat()
    pid = str(p["_id"])
    rows = []

    def add(kind, title, party, since, note=None, ref=None, contact=None):
        days = (date.fromisoformat(today) - date.fromisoformat(since)).days if since else 0
        rows.append({"kind": kind, "title": title, "party": party, "party_label": WAITING_PARTIES.get(party, party),
                     "since": since, "days": max(0, days), "note": note, "ref": ref, "contact": contact})

    for s in p.get("stages", []):
        for tk in s.get("tasks", []):
            if tk["status"] == "blocked":
                w = tk.get("waiting_on") or {"party": "us", "since": None}
                add("task", f"{tk['title']} ({s['name']})", w["party"], w.get("since"), w.get("note") or tk.get("notes"),
                    tk["id"], w.get("contact_name"))
        gm = next((m for m in s.get("milestones", []) if m.get("gate")), None)
        ready = s.get("tasks") and all(tk["status"] == "done" for tk in s["tasks"]) and \
            all(c["done"] for c in s.get("checklist", []))
        if s.get("client_signoff_required") and not s.get("signoff") and ready and gm and gm["status"] != "achieved":
            done_at = db.project_activity.find_one({"company_id": g.cid, "project_id": pid, "stage_id": s["id"], "kind": "stage",
                                                    "text": {"$regex": "→ done$"}}, sort=[("at", -1)])
            since = done_at["at"].date().isoformat() if done_at else max(tk.get("end") or today for tk in s["tasks"])
            add("signoff", f"Client sign-off for {s['name']}", "client", min(since, today), "Stage work is done", s["id"])
    for i in db.project_issues.find({"company_id": g.cid, "project_id": pid, "status": "open", "waiting_on": {"$ne": None}}):
        w = i["waiting_on"]
        add("issue", i["title"], w["party"], w.get("since"), w.get("note"), str(i["_id"]))
    rows.sort(key=lambda r: -r["days"])
    summary = {}
    for r in rows:
        x = summary.setdefault(r["party"], {"party": r["party"], "label": r["party_label"], "items": 0, "days": 0})
        x["items"] += 1
        x["days"] += r["days"]
    return {"rows": rows, "by_party": sorted(summary.values(), key=lambda x: -x["days"])}


def health(p, today=None):
    today = today or date.today().isoformat()
    pid = str(p["_id"])
    tasks = [tk for s in p.get("stages", []) for tk in s.get("tasks", [])]
    parts = []

    # 1. late work (25): tasks past their end date and not done
    due = [tk for tk in tasks if tk.get("end") and tk["end"] < today]
    late = [tk for tk in due if tk["status"] != "done"]
    pts = 25 if not due else round(25 * (1 - len(late) / len(due)))
    parts.append({"key": "late", "label": "Work on time", "points": pts, "max": 25,
                  "why": f"{len(late)} of {len(due)} task(s) due so far are late" if due else "No task due yet"})

    # 2. forecast (15): one point off per working day the forecast finish is late
    fc = forecast(p, today)
    pts = max(0, 15 - fc["late_days"])
    parts.append({"key": "forecast", "label": "Forecast finish", "points": pts, "max": 15, "why": fc["message"]})

    # 3. issues (15): -5 per open high, -2 per open medium
    hi = db.project_issues.count_documents({"company_id": g.cid, "project_id": pid, "status": "open", "severity": "high"})
    md = db.project_issues.count_documents({"company_id": g.cid, "project_id": pid, "status": "open", "severity": "medium"})
    parts.append({"key": "issues", "label": "Open issues", "points": max(0, 15 - 5 * hi - 2 * md), "max": 15,
                  "why": f"{hi} high, {md} medium open" if hi or md else "No high or medium issues open"})

    # 4. blocked and waiting (15): -3 per blocked task, -1 per item waiting more than 7 days
    blocked = sum(1 for tk in tasks if tk["status"] == "blocked")
    w = waiting(p, today)
    old = sum(1 for r in w["rows"] if r["days"] > 7)
    parts.append({"key": "blocked", "label": "Blocked / waiting", "points": max(0, 15 - 3 * blocked - old), "max": 15,
                  "why": f"{blocked} blocked task(s), {old} item(s) waiting over 7 days" if blocked or old else "Nothing blocked"})

    # 5. fresh updates (15): when the project was last worked on
    last = db.project_activity.find_one({"company_id": g.cid, "project_id": pid}, sort=[("at", -1)])
    age = (datetime.utcnow() - last["at"]).days if last else None
    pts = 15 if age is not None and age <= 3 else 10 if age is not None and age <= 7 else 5 if age is not None and age <= 14 else 0
    parts.append({"key": "fresh", "label": "Kept up to date", "points": pts, "max": 15,
                  "why": "No updates recorded yet" if age is None else f"Last update {age} day(s) ago"})

    # 6. budget (15): spent against the stage budgets (costs are recorded from Phase E)
    budget = sum(s.get("budget", 0) or 0 for s in p.get("stages", []))
    spent = sum(c.get("amount", 0) for c in db.costs.find({"company_id": g.cid, "project_id": pid, "status": "approved"}))
    prog = 0
    if p.get("stages"):
        from ..routes.projects import project_progress
        prog = project_progress(p)
    if not spent:
        pts, why = 15, "No costs recorded yet (recorded from the Finance phase)"
    elif budget and spent > budget:
        pts, why = 0, "Spent more than the budget"
    elif budget and spent / budget >= 0.8 and prog < 80:
        pts, why = 7, f"{round(spent / budget * 100)}% of the budget spent at {prog}% progress"
    else:
        pts, why = 15, "Spending within the budget"
    parts.append({"key": "budget", "label": "Budget", "points": pts, "max": 15, "why": why})

    score = sum(x["points"] for x in parts)
    grade = next(gr for gr in GRADES if score >= gr[0])
    return {"score": score, "grade": grade[1], "label": grade[2], "parts": parts, "forecast": fc,
            "waiting": w["by_party"]}
