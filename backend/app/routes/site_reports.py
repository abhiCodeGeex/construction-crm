"""Phase F block 4 — daily site reports, and the client portal's read-only documents, selections and photos.

* One report per project per day: weather, manpower per trade, equipment, work done per stage / task, materials
  received, visitors, photos, safety. It can be edited until the end of the next day, then only by an Owner.
* An issue in the report becomes a project issue (same notifications, and a high one blocks its stage's gate).
* A delay in the report goes to the delay log with the report as source; it never moves the plan (the PM is told).
* A report with photos of a construction stage offers that stage's "Site photos uploaded" check.
* No report by the company's cut-off on a working day -> the site supervisor; the next day -> the project's managers.
Who: site rw (Owner, PM, Site Supervisor) on projects they are on.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, portal
from ..services import notify, project_events as ev, sales, workdays
from ..services.defaults import DELAY_REASONS
from .lead_money import a_date
from .lead_steps import num
from .projects import load, member, project_progress, ISSUE_SEVERITIES

bp = Blueprint("site_reports", __name__)

WEATHER = ["Clear", "Cloudy", "Rain", "Heavy rain", "Extreme heat"]
TRADES = ["Mason", "Carpenter", "Electrician", "Plumber", "Painter", "Fabricator", "Tiler", "Helper", "Supervisor", "Other"]
SITE_DEFAULTS = {"cutoff": "19:00", "tz_offset_min": 330}
SUPERVISOR = "Site Supervisor"


def site_settings(company=None):
    return {**SITE_DEFAULTS, **((company or g.company).get("site_settings") or {})}


def access(pid, write=False):
    if not can("site"):
        abort(403, "Your role cannot view site reports")
    p = load(pid)
    if write and not (can("site", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot write site reports on this project")
    return p


def editable(r):
    """Until the end of the day after the report's date; then only an Owner."""
    return g.role == "owner" or r["date"] >= (date.fromisoformat(sales.today()) - timedelta(days=1)).isoformat()


def present(r):
    data = serialize(r)
    data["editable"] = editable(r)
    for ph in data.get("photos", []):
        ph["url"] = f"/api/files/{ph['key']}"
    return data


def clean(d, p, r=None):
    ch = {}
    stages = {s["id"]: s for s in p.get("stages", [])}
    tasks = {tk["id"]: tk for s in p.get("stages", []) for tk in s.get("tasks", [])}
    if "weather" in d:
        w = d.get("weather") or {}
        if w.get("kind") and w["kind"] not in WEATHER:
            abort(400, f"Weather: {', '.join(WEATHER)}")
        ch["weather"] = {"kind": w.get("kind") or None, "note": (w.get("note") or "").strip()[:200] or None}
    if "manpower" in d:
        rows = []
        for m in (d.get("manpower") or [])[:30]:
            trade = (m.get("trade") or "").strip()[:40] or abort(400, "Each manpower row needs a trade")
            count = int(num(m.get("count"), f"Count for {trade}", required=True))
            row = {"trade": trade, "count": count, "contact_id": None, "party": "Own"}
            if m.get("contact_id"):
                c = db.contacts.find_one({"_id": oid(m["contact_id"]), "company_id": g.cid}) or abort(400, "Subcontractor not found")
                row.update(contact_id=m["contact_id"], party=c["name"])
            rows.append(row)
        ch["manpower"] = rows
        ch["headcount"] = sum(x["count"] for x in rows)
    if "work" in d:
        rows = []
        for w in (d.get("work") or [])[:40]:
            s = stages.get(w.get("stage_id")) or abort(400, "Each work line needs a stage of this project")
            tk = tasks.get(w.get("task_id")) if w.get("task_id") else None
            if w.get("task_id") and not tk:
                abort(400, "Task not found")
            note = (w.get("note") or "").strip()[:500] or abort(400, "Say what was done")
            rows.append({"stage_id": s["id"], "stage_name": s["name"], "service": s.get("service"), "task_id": tk and tk["id"],
                         "task_title": tk and tk["title"], "note": note})
        ch["work"] = rows
    for k in ("equipment", "materials", "visitors", "safety"):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:1000] or None
    if "photos" in d:
        photos, keep = [], {ph["key"]: ph for ph in (r or {}).get("photos", [])}
        for ph in (d.get("photos") or [])[:40]:
            key = ph.get("key")
            f = db.files.find_one({"company_id": g.cid, "key": key}) if key else None
            if not f:
                abort(400, "Upload the photo first")
            photos.append({"key": key, "name": f["name"], "caption": (ph.get("caption") or "").strip()[:200] or None,
                           "shareable": bool(ph.get("shareable")), "at": keep.get(key, {}).get("at") or t.now()})
        ch["photos"] = photos
    return ch


@bp.get("/projects/<pid>/site-reports")
@api(None)
def list_reports(pid):
    p = access(pid)
    rows = [present(r) for r in t.find("site_reports", {"project_id": pid}, sort=[("date", -1)], limit=120)]
    grns = {}
    for gr in t.find("goods_receipts", {"project_id": pid}):  # Phase H: deliveries of the day, read only
        grns.setdefault(gr["date"], []).append({"number": gr["number"], "po_number": gr["po_number"], "vendor": gr["vendor_name"],
                                                "lines": [f"{x['accepted']:g} {x.get('unit') or ''} {x['description']}" for x in gr["lines"]]})
    for r in rows:
        r["deliveries"] = grns.get(r["date"], [])
    return jsonify({"reports": rows, "weather": WEATHER, "trades": TRADES, "severities": ISSUE_SEVERITIES,
                    "delay_reasons": [{"value": k, "label": v[0]} for k, v in DELAY_REASONS.items()],
                    "stages": [{"id": s["id"], "name": s["name"], "service": s.get("service"),
                                "tasks": [{"id": tk["id"], "title": tk["title"]} for tk in s.get("tasks", [])]} for s in p.get("stages", [])],
                    "today": sales.today(), "has_today": any(r["date"] == sales.today() for r in rows),
                    "can_write": can("site", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/site-reports")
@api(None)
def add_report(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "A report cannot be for a future day")
    if day < (date.fromisoformat(sales.today()) - timedelta(days=1)).isoformat() and g.role != "owner":
        abort(409, "Reports are written on the day (or the next day); ask an Owner for an older one")
    if db.site_reports.find_one({"company_id": g.cid, "project_id": pid, "date": day}, {"_id": 1}):
        abort(409, f"There is already a report for {day}; edit it")
    r = t.insert("site_reports", {"project_id": pid, "project_name": p["name"], "date": day, "weather": {"kind": None, "note": None},
                                  "manpower": [], "headcount": 0, "work": [], "equipment": None, "materials": None, "visitors": None,
                                  "safety": None, "photos": [], "issues": [], "delays": [], "author_id": g.uid,
                                  "author_name": g.user.get("name"), **clean(d, p)})
    after_save(p, r)
    ev.log(pid, "file", f"Site report for {day} by {r['author_name']}: {r['headcount']} on site")
    return jsonify(present(r)), 201


@bp.get("/site-reports/<rid>")
@api(None)
def get_report(rid):
    r = t.get("site_reports", rid)
    access(r["project_id"])
    return jsonify(present(r))


@bp.put("/site-reports/<rid>")
@api(None)
def edit_report(rid):
    r = t.get("site_reports", rid)
    p = access(r["project_id"], write=True)
    if not editable(r):
        abort(409, "This report is locked (it can be changed until the end of the next day); ask an Owner")
    upd = t.update("site_reports", rid, clean(request.get_json(force=True) or {}, p, r))
    after_save(p, upd)
    return jsonify(present(upd))


def after_save(p, r):
    """Photos of a construction stage offer that stage's "Site photos uploaded" check (an editor still ticks it)."""
    if not r.get("photos"):
        return
    stage_ids = {w["stage_id"] for w in r.get("work", []) if w.get("service") == "construction"}
    if not stage_ids:
        return
    fresh = db.projects.find_one({"_id": p["_id"]})
    changed = False
    for s in fresh.get("stages", []):
        if s["id"] in stage_ids:
            for c in s.get("checklist", []):
                if "photo" in c["text"].lower() and not c.get("done") and not c.get("suggested"):
                    c["suggested"] = {"by": "site report", "number": f"site report {r['date']}", "at": t.now().isoformat()}
                    changed = True
    if changed:
        db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": fresh["stages"]}})


@bp.post("/site-reports/<rid>/issues")
@api(None)
def report_issue(rid):
    """An issue seen on site becomes a project issue, with the usual notifications (a high one blocks its stage)."""
    r = t.get("site_reports", rid)
    p = access(r["project_id"], write=True)
    d = request.get_json(force=True) or {}
    title = (d.get("title") or "").strip()[:200] or abort(400, "What is the issue?")
    if d.get("severity", "medium") not in ISSUE_SEVERITIES:
        abort(400, "Severity must be low, medium or high")
    stage = next((s for s in p.get("stages", []) if s["id"] == d.get("stage_id")), None) if d.get("stage_id") else None
    if d.get("stage_id") and not stage:
        abort(400, "Stage not found")
    issue = t.insert("project_issues", {"project_id": r["project_id"], "stage_id": stage and stage["id"], "title": title,
                                        "description": f"From the site report of {r['date']}" + (f": {d['note']}" if d.get("note") else ""),
                                        "severity": d.get("severity", "medium"), "status": "open", "owner_id": None, "owner_name": None,
                                        "due": None, "raised_by": g.user.get("name"), "site_report_id": rid})
    ev.issue_raised(p, issue)
    upd = t.update("site_reports", rid, {"issues": r.get("issues", []) + [{"id": t.sid(), "title": title, "severity": issue["severity"],
                                                                            "issue_id": str(issue["_id"])}]})
    return jsonify(present(upd)), 201


@bp.post("/site-reports/<rid>/delays")
@api(None)
def report_delay(rid):
    """Recorded in the delay log with the report as its source. The plan is not moved: the PM is told to review it."""
    r = t.get("site_reports", rid)
    p = access(r["project_id"], write=True)
    d = request.get_json(force=True) or {}
    if d.get("reason") not in DELAY_REASONS:
        abort(400, "Choose why work was held up")
    stage = next((s for s in p.get("stages", []) if s["id"] == d.get("stage_id")), None) or abort(400, "Choose the stage held up")
    days = num(d.get("days"), "Working days lost", required=True, positive=True)
    reason = DELAY_REASONS[d["reason"]]
    row = {"company_id": g.cid, "project_id": r["project_id"], "kind": "site", "item_id": stage["id"], "title": stage["name"],
           "from": r["date"], "to": r["date"], "days": days, "reason": d["reason"], "reason_label": reason[0], "party": reason[1],
           "note": (d.get("note") or "").strip()[:300] or None, "source": "site_report", "site_report_id": rid,
           "by": g.user.get("name"), "by_id": g.uid, "at": t.now()}
    db.project_delays.insert_one(row)
    ev.log(r["project_id"], "delay", f"Delay reported on site ({r['date']}): {stage['name']} lost {days:g} working day(s) — {reason[0]}")
    notify.send("site_delay", ev.managers(p), f"{p['name']}: {stage['name']} lost {days:g} working day(s) on {r['date']} ({reason[0]}). "
                "Review the plan.", f"/app/projects/{p['_id']}?tab=site", project_id=r["project_id"], level="warn")
    upd = t.update("site_reports", rid, {"delays": r.get("delays", []) + [{"id": t.sid(), "stage_name": stage["name"], "days": days,
                                                                            "reason": d["reason"], "reason_label": reason[0], "note": row["note"]}]})
    return jsonify(present(upd)), 201


@bp.get("/site-reports")
@api("site", write=False)
def day_reports():
    """Site reports for one day across your projects, and the active projects still missing one."""
    day = a_date(request.args.get("date") or sales.today(), "Date")
    q = {"company_id": g.cid, "status": "active"}
    if g.role != "owner":
        q["team.user_id"] = g.uid
    projects = list(db.projects.find(q, {"name": 1, "code": 1, "team": 1}))
    reports = {r["project_id"]: r for r in t.find("site_reports", {"date": day, "project_id": {"$in": [str(p["_id"]) for p in projects]}})}
    rows = []
    for p in projects:
        r = reports.get(str(p["_id"]))
        sup = [m["name"] for m in p.get("team", []) if m.get("project_role") == SUPERVISOR and m.get("user_id")]
        rows.append({"project_id": str(p["_id"]), "code": p.get("code"), "name": p["name"], "supervisors": sup,
                     "report": present(r) if r else None})
    return jsonify({"date": day, "rows": sorted(rows, key=lambda x: (x["report"] is not None, x["name"]))})


@bp.get("/settings/site")
@api(None)
def get_site_settings():
    return jsonify(site_settings())


@bp.put("/settings/site")
@api("settings")
def put_site_settings():
    d = request.get_json(force=True) or {}
    s = site_settings()
    if "cutoff" in d:
        v = str(d["cutoff"] or "")
        try:
            hh, mm = (int(x) for x in v.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            abort(400, "Cut-off is a time like 19:00")
        s["cutoff"] = f"{hh:02d}:{mm:02d}"
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"site_settings": s}})
    return jsonify(s)


# ---------------- the client portal (read only in Phase F) ----------------
def portal_project(pid):
    from .projects import portal_query
    p = db.projects.find_one({**portal_query(), "_id": oid(pid)})
    if not p:
        abort(404, "project not found")
    return p


def is_client(p):
    return any(m.get("contact_id") == g.contact_id and m.get("project_role") == "Client" for m in p.get("team", []))


@bp.get("/portal/projects/<pid>/documents")
@portal
def portal_documents(pid):
    """Documents marked shared, and every revision issued to this person by transmittal."""
    portal_project(pid)
    out = []
    for doc in db.documents.find({"company_id": g.cid, "project_id": pid}):
        issued = [v for v in doc["versions"] if v.get("sent") and db.transmittals.find_one(
            {"_id": {"$in": [oid(s["transmittal_id"]) for s in v["sent"]]}, "to.contact_id": g.contact_id}, {"_id": 1})]
        show = [doc["versions"][-1]] if doc.get("shared") else issued  # shared: always the current revision
        if show:
            v = show[-1]
            out.append({"name": doc["name"], "number": doc.get("number"), "kind": doc["kind"], "rev": v["rev"],
                        "url": f"/api/files/{v['file_key']}", "date": v["at"]})
    return jsonify(serialize(sorted(out, key=lambda x: x["name"])))


@bp.get("/portal/projects/<pid>/selections")
@portal
def portal_selections(pid):
    p = portal_project(pid)
    if not is_client(p):
        return jsonify([])
    rows = []
    for s in db.selections.find({"company_id": g.cid, "project_id": pid}).sort("due_date", 1):
        ch = next((o for o in s.get("options", []) if o["id"] == s.get("chosen_option_id")), None)
        rows.append({"item": s["item"], "room": s.get("room"), "status": s["status"], "due_date": s.get("due_date"),
                     "allowance": s.get("allowance"), "chosen": ch and ch["name"],
                     "options": [{"name": o["name"], "brand": o.get("brand"), "price": o["price"], "lead_days": o.get("lead_days"),
                                  "photo": f"/api/files/{o['file_key']}" if o.get("file_key") else None} for o in s.get("options", [])]})
    return jsonify(rows)


@bp.get("/portal/projects/<pid>/photos")
@portal
def portal_photos(pid):
    """Site photos the team marked as shareable."""
    p = portal_project(pid)
    rows = []
    for r in db.site_reports.find({"company_id": g.cid, "project_id": pid, "photos.shareable": True}).sort("date", -1).limit(60):
        for ph in r["photos"]:
            if ph.get("shareable"):
                rows.append({"date": r["date"], "caption": ph.get("caption"), "url": f"/api/files/{ph['key']}"})
    return jsonify({"project": p["name"], "progress": project_progress(p), "photos": rows})
