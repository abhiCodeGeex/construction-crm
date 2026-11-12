"""Phase K block 3 — timesheets and resource planning (v4 §12, §14).

* Each staff member logs hours per day against a project (and stage / task): billable or not, with a note.
  A week is submitted; the PM of the project (or an Owner) approves or returns each entry with a reason.
* Rates: per person an hourly cost (for job costing, hidden from roles that do not see costs) and an hourly bill rate
  (architects and designers bill hours). Approved billable hours not yet invoiced become a draft invoice
  (one line per person: hours × bill rate).
* Reports: hours per project and stage, per person (billable share and utilisation = logged ÷ capacity).
* Resource calendar: per person and day — the tasks assigned (demand) and the hours logged; a day with more than one
  task is flagged as overbooked.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev
from .lead_money import a_date
from .lead_steps import num
from .projects import load, member

bp = Blueprint("timesheets", __name__)


def r2(v):
    return round((v or 0) + 1e-9, 2)


def tsettings():
    return {"capacity_hours": 8, "rates": {}, **(g.company.get("timesheets") or {})}


def monday(d):
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d - timedelta(days=d.weekday())


def staff_only():
    if g.user.get("kind") != "staff" and getattr(g, "role", None) not in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator"):
        abort(403, "Timesheets are for staff")


def approver_of(p):
    return g.role == "owner" or g.uid in ev.managers(p)


def entry_out(e):
    d = serialize(e)
    if g.hide_costs:
        d.pop("cost", None)
    return d


def clean_entry(d, e=None):
    ch = {}
    if "project_id" in d or e is None:
        p = load(d.get("project_id") or abort(400, "Choose the project"))
        if g.role != "owner" and not member(p):
            abort(403, "Log hours only on projects you are on")
        ch.update(project_id=str(p["_id"]), project_name=p["name"])
    else:
        p = load(e["project_id"])
    if "stage_id" in d or "task_id" in d:
        st = next((s for s in p.get("stages", []) if s["id"] == d.get("stage_id")), None) if d.get("stage_id") else None
        tk = None
        if d.get("task_id"):
            for s in p.get("stages", []):
                tk = next((x for x in s.get("tasks", []) if x["id"] == d["task_id"]), None)
                if tk:
                    st = st or s
                    break
            tk or abort(400, "Task not found on this project")
        if d.get("stage_id") and not st:
            abort(400, "Stage not found on this project")
        ch.update(stage_id=st and st["id"], stage_name=st and st["name"], task_id=tk and tk["id"], task_title=tk and tk["title"])
    if "date" in d or e is None:
        day = a_date(d.get("date") or date.today().isoformat(), "Date")
        if day > date.today().isoformat():
            abort(400, "Hours cannot be logged for a future day")
        ch["date"] = day
    if "hours" in d or e is None:
        h = num(d.get("hours"), "Hours", required=True, positive=True)
        if h > 24 or round(h * 4) != h * 4:
            abort(400, "Hours: up to 24, in quarters of an hour")
        ch["hours"] = h
    if "billable" in d:
        ch["billable"] = bool(d["billable"])
    if "note" in d:
        ch["note"] = (d.get("note") or "").strip()[:500] or None
    return ch


def day_total(uid, day, exclude=None):
    q = {"company_id": g.cid, "user_id": uid, "date": day, "status": {"$ne": "rejected"}}
    if exclude:
        q["_id"] = {"$ne": exclude}
    return sum(x["hours"] for x in db.timesheets.find(q, {"hours": 1}))


def priced(uid, hours):
    r = tsettings()["rates"].get(uid) or {}
    return {"cost": r2(hours * (r.get("cost") or 0)), "bill_rate": r.get("bill") or 0}


# ---------------- my entries ----------------
@bp.get("/timesheets")
@api(None)
def my_week():
    staff_only()
    start = monday(request.args.get("week") or date.today())
    end = start + timedelta(days=6)
    uid = request.args.get("user_id") if request.args.get("user_id") and g.role in ("owner", "pm") else g.uid
    rows = t.find("timesheets", {"user_id": uid, "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}, sort=[("date", 1), ("created_at", 1)])
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    return jsonify({"week": start.isoformat(), "days": days, "entries": [entry_out(e) for e in rows],
                    "totals": {dd: sum(e["hours"] for e in rows if e["date"] == dd and e["status"] != "rejected") for dd in days},
                    "capacity": tsettings()["capacity_hours"],
                    "projects": [{"id": str(p["_id"]), "name": p["name"], "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])]}
                                 for p in db.projects.find({"company_id": g.cid, "status": {"$in": ["planning", "active", "on_hold"]},
                                                            **({} if g.role == "owner" else {"team.user_id": g.uid})})]})


@bp.post("/timesheets")
@api(None)
def add_entry():
    staff_only()
    d = request.get_json(force=True) or {}
    ch = clean_entry(d)
    if day_total(g.uid, ch["date"]) + ch["hours"] > 24:
        abort(400, "More than 24 hours on one day")
    e = t.insert("timesheets", {"user_id": g.uid, "user_name": g.user["name"], "stage_id": None, "stage_name": None, "task_id": None, "task_title": None,
                                "billable": True, "note": None, "status": "draft", "invoice_id": None, **ch, **priced(g.uid, ch["hours"])})
    return jsonify(entry_out(e)), 201


def own(eid):
    e = t.get("timesheets", eid)
    if e["user_id"] != g.uid:
        abort(403, "Not your entry")
    if e["status"] not in ("draft", "rejected"):
        abort(409, "Submitted hours are changed by the approver returning them")
    return e


@bp.put("/timesheets/<eid>")
@api(None)
def edit_entry(eid):
    e = own(eid)
    ch = clean_entry(request.get_json(force=True) or {}, e)
    if day_total(g.uid, ch.get("date", e["date"]), e["_id"]) + ch.get("hours", e["hours"]) > 24:
        abort(400, "More than 24 hours on one day")
    ch.update(status="draft", reason=None, **priced(g.uid, ch.get("hours", e["hours"])))
    return jsonify(entry_out(t.update("timesheets", eid, ch)))


@bp.delete("/timesheets/<eid>")
@api(None)
def delete_entry(eid):
    e = own(eid)
    db.timesheets.delete_one({"_id": e["_id"]})
    return jsonify({"ok": True})


@bp.post("/timesheets/submit")
@api(None)
def submit_week():
    staff_only()
    start = monday((request.get_json(force=True) or {}).get("week") or date.today())
    q = {"company_id": g.cid, "user_id": g.uid, "status": {"$in": ["draft", "rejected"]},
         "date": {"$gte": start.isoformat(), "$lte": (start + timedelta(days=6)).isoformat()}}
    rows = list(db.timesheets.find(q))
    if not rows:
        abort(409, "Nothing to submit this week")
    db.timesheets.update_many({"_id": {"$in": [r["_id"] for r in rows]}}, {"$set": {"status": "submitted", "submitted_at": t.now(), "reason": None}})
    for pid in {r["project_id"] for r in rows}:
        p = t.get("projects", pid)
        hrs = sum(r["hours"] for r in rows if r["project_id"] == pid)
        notify.send("timesheet", ev.managers(p), f"{g.user['name']} submitted {hrs:g} h on {p['name']} (week of {start.isoformat()})",
                    "/app/timesheets?tab=approve", project_id=pid)
    return jsonify({"submitted": len(rows)})


# ---------------- approval ----------------
@bp.get("/timesheets/approvals")
@api(None)
def approvals():
    if g.role not in ("owner", "pm"):
        abort(403, "Only Owners and Project Managers approve hours")
    q = {"status": "submitted"}
    if g.role != "owner":
        q["project_id"] = {"$in": [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}) if g.uid in ev.managers(p)]}
    return jsonify([entry_out(e) for e in t.find("timesheets", q, sort=[("user_name", 1), ("date", 1)], limit=1000)])


@bp.post("/timesheets/decide")
@api(None)
def decide():
    d = request.get_json(force=True) or {}
    ids = d.get("ids") or abort(400, "Choose the entries")
    approve = d.get("decision") == "approve"
    if not approve and d.get("decision") != "reject":
        abort(400, "Decision: approve or reject")
    reason = (d.get("reason") or "").strip()[:500]
    if not approve and not reason:
        abort(400, "Say why the hours are returned")
    done, people = 0, {}
    for eid in ids:
        e = t.get("timesheets", eid)
        if e["status"] != "submitted":
            continue
        if not approver_of(t.get("projects", e["project_id"])):
            abort(403, f"You do not approve hours on {e['project_name']}")
        if e["user_id"] == g.uid and g.role != "owner":
            abort(403, "Someone else approves your own hours")
        t.update("timesheets", eid, {"status": "approved" if approve else "rejected", "decided_by": g.user["name"], "decided_at": t.now(),
                                     "reason": None if approve else reason})
        people.setdefault(e["user_id"], 0)
        people[e["user_id"]] += e["hours"]
        done += 1
    for uid, hrs in people.items():
        notify.send("timesheet_decided", [uid], f"{hrs:g} h {'approved' if approve else 'returned'} by {g.user['name']}" + ("" if approve else f": {reason}"),
                    "/app/timesheets", skip_self=False)
    return jsonify({"decided": done})


# ---------------- rates and settings ----------------
@bp.get("/settings/timesheets")
@api("settings", write=False)
def get_ts_settings():
    s = tsettings()
    users = [{"id": str(u["_id"]), "name": u["name"], "role": u["role"], **(s["rates"].get(str(u["_id"])) or {"cost": 0, "bill": 0})}
             for u in db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}}).sort("name", 1)]
    return jsonify({"capacity_hours": s["capacity_hours"], "people": users})


@bp.put("/settings/timesheets")
@api("settings")
def put_ts_settings():
    d = request.get_json(force=True) or {}
    s = tsettings()
    if "capacity_hours" in d:
        c = num(d["capacity_hours"], "Hours per day", required=True, positive=True)
        s["capacity_hours"] = c if c <= 16 else abort(400, "Hours per day: up to 16")
    if "rates" in d:
        rates = {}
        for uid, r in (d["rates"] or {}).items():
            if not db.users.find_one({"_id": oid(uid), "company_id": g.cid}):
                abort(400, "Unknown person in the rates")
            rates[uid] = {"cost": r2(num(r.get("cost"), "Hourly cost") or 0), "bill": r2(num(r.get("bill"), "Bill rate") or 0)}
        s["rates"] = rates
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"timesheets": s}})
    g.company["timesheets"] = s
    return get_ts_settings()


# ---------------- hourly-fee invoicing ----------------
def unbilled(pid):
    return list(db.timesheets.find({"company_id": g.cid, "project_id": pid, "status": "approved", "billable": True, "invoice_id": None}).sort("date", 1))


@bp.get("/projects/<pid>/billable-hours")
@api("finance", write=False)
def billable(pid):
    load(pid) if g.role not in ("owner", "accounts") else t.get("projects", pid)
    rows = unbilled(pid)
    rates = tsettings()["rates"]
    people = {}
    for e in rows:
        x = people.setdefault(e["user_id"], {"user_id": e["user_id"], "name": e["user_name"], "hours": 0, "rate": (rates.get(e["user_id"]) or {}).get("bill", 0), "ids": []})
        x["hours"] += e["hours"]
        x["ids"].append(str(e["_id"]))
    out = [{**x, "amount": r2(x["hours"] * x["rate"])} for x in people.values()]
    return jsonify({"people": out, "total": r2(sum(x["amount"] for x in out)), "from": rows[0]["date"] if rows else None, "to": rows[-1]["date"] if rows else None})


@bp.post("/projects/<pid>/invoice-hours")
@api("finance")
def invoice_hours(pid):
    from .invoices import base_doc, totals, present, require_write
    p = t.get("projects", pid) if g.role in ("owner", "accounts") else load(pid)
    require_write(p)
    rows = unbilled(pid)
    want = set((request.get_json(force=True) or {}).get("ids") or [str(r["_id"]) for r in rows])
    rows = [r for r in rows if str(r["_id"]) in want]
    if not rows:
        abort(409, "No approved billable hours to invoice")
    rates = tsettings()["rates"]
    tax = float(g.company.get("tax_rate") or 0)
    lines, people = [], {}
    for e in rows:
        people.setdefault((e["user_id"], e["user_name"]), []).append(e)
    for (uid, name), es in people.items():
        rate = (rates.get(uid) or {}).get("bill") or abort(409, f"Set {name}'s bill rate in Settings → Timesheets first")
        hrs = sum(x["hours"] for x in es)
        amount = r2(hrs * rate)
        lines.append({"id": t.sid(), "description": f"Professional fees — {name}, {es[0]['date']} to {es[-1]['date']}", "qty": hrs, "rate": rate,
                      "amount": amount, "tax_pct": tax, "tax": r2(amount * tax / 100), "hsn": None, "hours": True})
    c = db.contracts.find_one({"company_id": g.cid, "project_id": pid})
    inv = t.insert("invoices", {**base_doc("hours", p, c), "lines": lines, **totals(lines), "timesheet_ids": [str(r["_id"]) for r in rows]})
    db.timesheets.update_many({"_id": {"$in": [r["_id"] for r in rows]}}, {"$set": {"invoice_id": str(inv["_id"])}})
    ev.log(pid, "cost", f"Draft invoice for {sum(r['hours'] for r in rows):g} billable hours")
    return jsonify(present(inv)), 201


def release_hours(invoice_id):
    """A voided / deleted hours invoice frees its hours to be invoiced again."""
    db.timesheets.update_many({"company_id": g.cid, "invoice_id": invoice_id}, {"$set": {"invoice_id": None}})


# ---------------- reports and the resource calendar ----------------
def workdays_between(a, b):
    n, d = 0, a
    while d <= b:
        n += 1 if d.weekday() < 6 else 0  # Monday-Saturday, the usual Indian site week
        d += timedelta(days=1)
    return n


@bp.get("/reports/timesheets")
@api(None)
def ts_report():
    if not (can("reports") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view this report")
    a = date.fromisoformat(a_date(request.args.get("from") or (date.today() - timedelta(days=30)).isoformat(), "From"))
    b = date.fromisoformat(a_date(request.args.get("to") or date.today().isoformat(), "To"))
    rows = list(db.timesheets.find({"company_id": g.cid, "status": {"$in": ["submitted", "approved"]}, "date": {"$gte": a.isoformat(), "$lte": b.isoformat()}}))
    cap = tsettings()["capacity_hours"] * workdays_between(a, b)
    projects, people = {}, {}
    for e in rows:
        pj = projects.setdefault(e["project_id"], {"project": e["project_name"], "hours": 0, "billable": 0, "cost": 0, "stages": {}})
        pj["hours"] += e["hours"]
        pj["billable"] += e["hours"] if e.get("billable") else 0
        pj["cost"] += e.get("cost") or 0
        sk = e.get("stage_name") or "—"
        pj["stages"][sk] = pj["stages"].get(sk, 0) + e["hours"]
        pp = people.setdefault(e["user_id"], {"name": e["user_name"], "hours": 0, "billable": 0})
        pp["hours"] += e["hours"]
        pp["billable"] += e["hours"] if e.get("billable") else 0
    for pp in people.values():
        pp["utilisation"] = round(pp["hours"] / cap * 100, 1) if cap else None
        pp["billable_pct"] = round(pp["billable"] / pp["hours"] * 100, 1) if pp["hours"] else None
    out_p = [{"project_id": k, **v, "cost": None if g.hide_costs else r2(v["cost"])} for k, v in projects.items()]
    return jsonify({"from": a.isoformat(), "to": b.isoformat(), "capacity_hours": cap,
                    "projects": sorted(out_p, key=lambda x: -x["hours"]), "people": sorted(people.values(), key=lambda x: -x["hours"])})


@bp.get("/resources")
@api(None)
def resource_calendar():
    if not (can("projects") and g.role in ("owner", "pm")):
        abort(403, "Only Owners and Project Managers plan people")
    a = date.fromisoformat(a_date(request.args.get("from") or monday(date.today()).isoformat(), "From"))
    b = date.fromisoformat(a_date(request.args.get("to") or (a + timedelta(days=13)).isoformat(), "To"))
    if (b - a).days > 62:
        abort(400, "Up to two months at a time")
    days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    users = {str(u["_id"]): {"user_id": str(u["_id"]), "name": u["name"], "role": u["role"], "days": {dd: {"tasks": [], "hours": 0} for dd in days}}
             for u in db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}}).sort("name", 1)}
    for p in db.projects.find({"company_id": g.cid, "status": {"$in": ["planning", "active", "on_hold"]}, "deleted_at": None}):
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                u = users.get(tk.get("assignee_id"))
                if not u or tk.get("status") == "done" or not tk.get("start") or not tk.get("end"):
                    continue
                for dd in days:
                    if tk["start"] <= dd <= tk["end"]:
                        u["days"][dd]["tasks"].append({"project": p["name"], "task": tk["title"]})
    for e in db.timesheets.find({"company_id": g.cid, "date": {"$gte": days[0], "$lte": days[-1]}, "status": {"$ne": "rejected"}}):
        if e["user_id"] in users:
            users[e["user_id"]]["days"][e["date"]]["hours"] += e["hours"]
    rows = []
    for u in users.values():
        u["overbooked"] = [dd for dd, x in u["days"].items() if len(x["tasks"]) > 1 and date.fromisoformat(dd).weekday() < 6]
        rows.append(u)
    return jsonify({"days": days, "capacity": tsettings()["capacity_hours"], "people": rows})
