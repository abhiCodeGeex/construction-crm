"""Projects (requirements §4): Project -> Stages -> Tasks -> Milestones, team, Gantt dependencies, dashboard,
per-project permissions (§1) and the portal's read-only project view (§13)."""
import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal, can
from ..services.defaults import (SERVICES, PROJECT_ROLES, PROJECT_STATUSES, PROJECT_TYPES, TASK_STATUSES,
                                 DESIGN_SERVICES, DEFAULT_STAGE_DAYS, TASK_PRIORITIES, gate_defaults, LINK_TYPES,
                                 DELAY_REASONS, WAITING_PARTIES)
from ..services import workdays
from ..services import project_events, budget
from ..services.subscription import check_project_limit

bp = Blueprint("projects", __name__)

OPEN_STATUSES = ("planning", "active")  # counted against the plan's active-project limit
ISSUE_SEVERITIES = ("low", "medium", "high")


# ---------------- helpers ----------------
def d(v, field, required=False):
    if v in (None, ""):
        if required:
            abort(400, f"{field} is required")
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        abort(400, f"{field} must be a date (YYYY-MM-DD)")


def money(v, field):
    if v in (None, ""):
        return 0.0
    if not isinstance(v, (int, float)) or v < 0:
        abort(400, f"{field} must be a positive number")
    return round(float(v), 2)


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days + 1


def add_days(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def member(p):
    return next((m for m in p.get("team", []) if m.get("user_id") == g.uid), None)


def can_view(p):
    return g.role == "owner" or member(p) is not None


def can_edit(p):
    """Per-project permission: role must allow project edits AND the user's access on this project must be edit."""
    if not can("projects", True):
        return False
    if g.role == "owner":
        return True
    m = member(p)
    return bool(m and m.get("access") == "edit")


def can_edit_stage(p, stage):
    """Architect / Designer edit design stages (Architecture, Interior) on projects where they have edit access."""
    if can_edit(p):
        return True
    m = member(p)
    return g.role == "designer" and bool(m and m.get("access") == "edit") and stage.get("service") in DESIGN_SERVICES


def load(_id):
    p = t.get("projects", _id)
    if not can_view(p):
        abort(404, "project not found")
    return p


def require_edit(p, stage=None):
    ok = can_edit_stage(p, stage) if stage else can_edit(p)
    if not ok:
        abort(403, "You do not have edit access on this project")


def find_stage(p, sid):
    s = next((x for x in p.get("stages", []) if x["id"] == sid), None)
    if not s:
        abort(404, "stage not found")
    return s


def all_tasks(p):
    return {tk["id"]: (s, tk) for s in p.get("stages", []) for tk in s.get("tasks", [])}


def find_task(p, tid):
    pair = all_tasks(p).get(tid)
    if not pair:
        abort(404, "task not found")
    return pair


def _check_cycle(p):
    graph = {tid: list(tk.get("depends_on") or []) for tid, (_, tk) in all_tasks(p).items()}
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(m) for m in graph.get(n, [])):
            return True
        state[n] = 2
        return False

    if any(visit(n) for n in graph):
        abort(400, "This dependency would create a loop (a task cannot depend on itself through other tasks)")


def normalize(p):
    """Derived values, recomputed on every write so they never drift:
    stage window grows to contain its tasks; stage progress = done tasks / tasks; stage status follows progress."""
    tasks = all_tasks(p)
    cal = workdays.calendar()
    for s in p.get("stages", []):
        ts = s.get("tasks", [])
        for tk in ts:
            tk["links"] = links_of(tk, tasks)
            tk["depends_on"] = [ln["task_id"] for ln in tk["links"]]
            tk["conflict"] = any(link_conflict(tk, tasks[ln["task_id"]][1], ln, cal) for ln in tk["links"])
            tk["progress"] = 100 if tk["status"] == "done" else tk.get("progress", 0)
        starts = [x for x in [s.get("start")] + [tk.get("start") for tk in ts] if x]
        ends = [x for x in [s.get("end")] + [tk.get("end") for tk in ts] if x]
        s["start"] = min(starts) if starts else None
        s["end"] = max(ends) if ends else None
        if ts:
            s["progress"] = round(sum(1 for tk in ts if tk["status"] == "done") / len(ts) * 100)
        if s.get("status") != "on_hold":
            s["status"] = "done" if s.get("progress") == 100 else "in_progress" if s.get("progress", 0) > 0 or \
                any(tk["status"] in ("in_progress", "done") for tk in ts) else "not_started"
    return p


def links_of(tk, tasks):
    """Task links {task_id, type FS|SS|FF, lag working days}. Tasks saved before B+3 only had depends_on (FS)."""
    raw = tk.get("links")
    if raw is None:
        raw = [{"task_id": x, "type": "FS", "lag": 0} for x in (tk.get("depends_on") or [])]
    out, seen = [], set()
    for ln in raw:
        if ln.get("task_id") in tasks and ln["task_id"] != tk["id"] and ln["task_id"] not in seen:
            seen.add(ln["task_id"])
            out.append({"task_id": ln["task_id"], "type": ln.get("type") or "FS", "lag": int(ln.get("lag") or 0)})
    return out


def link_conflict(tk, pred, ln, cal):
    """True when the dates break the link: FS start must be after pred end (+lag), SS start on/after pred start
    (+lag), FF end on/after pred end (+lag). Lags are working days."""
    if ln["type"] == "SS":
        return bool(tk.get("start") and pred.get("start") and tk["start"] < workdays.add_working(pred["start"], ln["lag"], cal))
    if ln["type"] == "FF":
        return bool(tk.get("end") and pred.get("end") and tk["end"] < workdays.add_working(pred["end"], ln["lag"], cal))
    return bool(tk.get("start") and pred.get("end") and tk["start"] <= workdays.add_working(pred["end"], ln["lag"], cal))


def project_progress(p):
    """Duration-weighted average of stage progress (a 60-day stage counts more than a 5-day one)."""
    total = weight = 0
    for s in p.get("stages", []):
        w = days_between(s["start"], s["end"]) if s.get("start") and s.get("end") else 1
        total += s.get("progress", 0) * w
        weight += w
    return round(total / weight) if weight else 0


def save_stages(_id, p):
    """Every stage / task / milestone write ends here, so the notifications follow every change (B+1)."""
    normalize(p)
    old = db.projects.find_one({"_id": oid(_id), "company_id": g.cid}) or {}
    old_ends = {s["id"]: s.get("end") for s in old.get("stages", [])}
    for s in p["stages"]:
        for m in s.get("milestones", []):
            # an open gate that was due on its stage end moves with it; a date set by hand stays
            if m.get("gate") and m["status"] != "achieved" and s.get("end") and m.get("due") == old_ends.get(s["id"]):
                m["due"] = s["end"]
    ends = [s["end"] for s in p["stages"] if s.get("end")]
    saved = t.update("projects", _id, {"stages": p["stages"], "planned_end": max(ends) if ends else None})
    project_events.stage_changes(old, saved)
    return saved


def present(p, full=True):
    data = t.out(p)
    data.pop("lead_handover", None)  # served by /projects/<id>/handover, which hides its money from restricted roles
    data["progress"] = project_progress(p)
    data["budget_total"] = round(sum(s.get("budget", 0) or 0 for s in p.get("stages", [])), 2)
    m = member(p)
    data["my_access"] = "edit" if can_edit(p) else "view"
    data["my_project_role"] = m.get("project_role") if m else None
    data["can_edit_design"] = any(can_edit_stage(p, s) for s in p.get("stages", []))
    if full:
        counts = {r["_id"]: r["n"] for r in db.project_comments.aggregate([
            {"$match": {"company_id": g.cid, "project_id": str(p["_id"])}}, {"$group": {"_id": "$task_id", "n": {"$sum": 1}}}])}
        bl = baseline(p)
        data["baseline"] = {k: bl[k] for k in ("id", "at", "by", "note", "project_end")} if bl else None
        if bl:
            data["baseline"]["slip_days"] = workdays.shift(bl.get("project_end"), p.get("planned_end"))
        for s in data.get("stages", []):
            if bl and s["id"] in bl["stages"]:
                b = bl["stages"][s["id"]]
                s["baseline"] = {**b, "slip_days": workdays.shift(b["end"], s.get("end"))}
            for tk in s.get("tasks", []):
                if bl and tk["id"] in bl["tasks"]:
                    b = bl["tasks"][tk["id"]]
                    tk["baseline"] = {**b, "slip_days": workdays.shift(b["end"], tk.get("end"))}
            gm = next((m for m in s.get("milestones", []) if m.get("gate")), None)
            s.setdefault("checklist", [])
            s["gate"] = {"milestone_id": gm and gm["id"], "closed": bool(gm and gm["status"] == "achieved"),
                         "missing": gate_missing(p, s) if gm and gm["status"] != "achieved" else []}
            for tk in s.get("tasks", []):
                tk["comment_count"] = counts.get(tk["id"], 0)
                tk.setdefault("priority", "normal")
                tk.setdefault("checklist", [])
                tk.setdefault("files", [])
    if g.hide_costs:
        data.pop("budget_total", None)
        data.pop("value", None)
    if not full:
        if p.get("status") in ("planning", "active", "on_hold"):
            from ..services.project_health import health
            h = health(p)
            data["health"] = {"score": h["score"], "grade": h["grade"], "label": h["label"],
                              "late_days": h["forecast"]["late_days"]}
        data.pop("stages", None)
        data["stage_count"] = len(p.get("stages", []))
        data["late"] = any(s.get("status") != "done" and s.get("end") and s["end"] < date.today().isoformat()
                           for s in p.get("stages", []))
    return data


def build_stages(services, start):
    stages = []
    for service in services:
        tpl = db.stage_templates.find_one({"company_id": g.cid, "service": service, "is_default": True}) or \
            db.stage_templates.find_one({"company_id": g.cid, "service": service})
        cursor = start
        for st in (tpl or {}).get("stages", []):
            dur = int(st.get("duration_days") or DEFAULT_STAGE_DAYS)
            end = add_days(cursor, dur - 1)
            gate = gate_defaults(service)
            stages.append({"id": t.sid(), "name": st["name"], "service": service, "start": cursor, "end": end,
                           "status": "not_started", "progress": 0, "budget": 0, "tasks": [],
                           "checklist": checklist_items(st.get("checklist", gate["checklist"])),
                           "client_signoff_required": bool(st.get("client_signoff", gate["client_signoff"])), "signoff": None,
                           "milestones": [gate_milestone(st["name"], end)]})
            cursor = add_days(end, 1)
    return stages


def checklist_items(texts):
    return [{"id": t.sid(), "text": x, "done": False, "done_by": None, "done_at": None} for x in texts]


def gate_milestone(stage_name, due):
    """Each stage's '<stage> complete' milestone is its gate: achieving it closes the stage (B+2 rules)."""
    return {"id": t.sid(), "name": f"{stage_name} complete", "due": due, "status": "pending", "achieved_at": None,
            "gate": True}


def gate_missing(p, s):
    """What is still open before this stage can be closed. Empty list = ready."""
    out = []
    open_tasks = [tk["title"] for tk in s.get("tasks", []) if tk["status"] != "done"]
    if open_tasks:
        out.append(f"{len(open_tasks)} task(s) not done: {', '.join(open_tasks[:3])}{'…' if len(open_tasks) > 3 else ''}")
    if not s.get("tasks") and s.get("progress", 0) < 100:
        out.append(f"Progress is {s.get('progress', 0)}% (no tasks: set it to 100%)")
    items = [c["text"] for c in s.get("checklist", []) if not c["done"]]
    if items:
        out.append("Checklist not ticked: " + ", ".join(items))
    if s.get("client_signoff_required") and not s.get("signoff"):
        out.append("Client sign-off not recorded")
    high = db.project_issues.count_documents({"company_id": g.cid, "project_id": str(p["_id"]), "stage_id": s["id"],
                                             "status": "open", "severity": "high"})
    if high:
        out.append(f"{high} high-severity issue(s) open on this stage")
    return out


def staff_name(uid):
    u = db.users.find_one({"_id": oid(uid), "company_id": g.cid, "kind": "staff"})
    if not u:
        abort(400, "Staff user not found")
    return u


def contact_doc(cid):
    c = t.get("contacts", cid, required=False)
    if not c:
        abort(400, "Contact not found")
    return c


def clean_project(dat, existing=None):
    out = {}
    if "name" in dat or not existing:
        name = (dat.get("name") or "").strip()
        if not name:
            abort(400, "Project name is required")
        out["name"] = name
    if "services" in dat or not existing:
        services = dat.get("services") or []
        if not services:
            abort(400, "Choose at least one service")
        bad = [s for s in services if s not in SERVICES]
        if bad:
            abort(400, f"Unknown service: {', '.join(bad)}")
        disabled = [s for s in services if s not in g.company.get("modules", [])]
        if disabled:
            abort(400, f"The {', '.join(disabled)} module is not enabled for your company")
        out["services"] = list(dict.fromkeys(services))
        if existing and set(existing.get("services", [])) - set(out["services"]):
            abort(409, "Services cannot be removed from a project once added; delete their stages instead")
    if "status" in dat:
        if dat["status"] not in PROJECT_STATUSES:
            abort(400, "Project status must be planning, active, on hold, completed or cancelled")
        out["status"] = dat["status"]
    if "project_type" in dat:
        if dat["project_type"] and dat["project_type"] not in PROJECT_TYPES:
            abort(400, f"Project type must be one of: {', '.join(PROJECT_TYPES)}")
        out["project_type"] = dat["project_type"] or None
    if "start" in dat or not existing:
        out["start"] = d(dat.get("start"), "Start date") or date.today().isoformat()
    if "target_end" in dat:
        out["target_end"] = d(dat.get("target_end"), "Target end")
    start = out.get("start") or (existing or {}).get("start")
    if out.get("target_end") and start and out["target_end"] < start:
        abort(400, "Target end is before the start date")
    if "area" in dat:
        out["area"] = money(dat.get("area"), "Area")
    if "area_unit" in dat:
        if dat["area_unit"] not in ("sqft", "sqm"):
            abort(400, "Area unit must be sq ft or m²")
        out["area_unit"] = dat["area_unit"]
    if "value" in dat:
        out["value"] = money(dat.get("value"), "Project value")
    if "branch" in dat:
        names = [b.get("name") for b in g.company.get("branches", [])]
        if dat["branch"] and dat["branch"] not in names:
            abort(400, "Unknown branch")
        out["branch"] = dat["branch"] or None
    if "site" in dat:
        site = dat.get("site") or {}
        lat, lng = site.get("lat"), site.get("lng")
        if (lat is None) != (lng is None):
            abort(400, "Map pin needs both latitude and longitude")
        if lat is not None and not (isinstance(lat, (int, float)) and isinstance(lng, (int, float))
                                    and -90 <= lat <= 90 and -180 <= lng <= 180):
            abort(400, "Map pin is outside valid latitude / longitude")
        out["site"] = {k: site.get(k) for k in ("line1", "line2", "city", "state", "pincode", "country", "lat", "lng")}
    if "description" in dat:
        out["description"] = dat.get("description")
    if "referred_by" in dat:
        out["referred_by"] = contact_doc(dat["referred_by"]) and dat["referred_by"] if dat["referred_by"] else None
    if "client_id" in dat:
        if dat["client_id"]:
            c = contact_doc(dat["client_id"])
            out["client_id"], out["client_name"] = dat["client_id"], c["name"]
        else:
            out["client_id"], out["client_name"] = None, None
    return out


def sync_client(team, old_client, new_client, name):
    """The project's client is always on the team with the Client role (portal access follows it)."""
    team = [m for m in team if not (m.get("contact_id") == old_client and m.get("project_role") == "Client")]
    if new_client and not any(m.get("contact_id") == new_client and m.get("project_role") == "Client" for m in team):
        team.append({"id": t.sid(), "contact_id": new_client, "name": name, "project_role": "Client",
                     "access": "view", "kind": "external"})
    if new_client:  # a contact that becomes a project's client is listed under Clients from then on
        db.contacts.update_one({"_id": oid(new_client), "company_id": g.cid}, {"$addToSet": {"types": "client"}})
    return team


# ---------------- projects ----------------
@bp.get("/projects/meta")
@api("projects", write=False)
def meta():
    return jsonify({"statuses": PROJECT_STATUSES, "types": PROJECT_TYPES, "project_roles": PROJECT_ROLES,
                    "task_statuses": TASK_STATUSES, "services": [s for s in SERVICES if s in g.company.get("modules", [])],
                    "branches": [b.get("name") for b in g.company.get("branches", [])],
                    "issue_severities": ISSUE_SEVERITIES})


@bp.get("/projects")
@api("projects")
def list_projects():
    q = {}
    if g.role != "owner":
        q["team.user_id"] = g.uid
    for k in ("status", "branch"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("service"):
        q["services"] = request.args["service"]
    if request.args.get("q"):
        rx = {"$regex": re.escape(request.args["q"]), "$options": "i"}
        q["$or"] = [{"name": rx}, {"code": rx}, {"client_name": rx}, {"site.city": rx}]
    return jsonify([present(p, full=False) for p in t.find("projects", q, sort=[("created_at", -1)])])


def new_project(dat, pm_uid, extra_team=(), extra_fields=None):
    """Create a project with `pm_uid` as Project Manager (edit). Used by the projects API and lead conversion."""
    doc = clean_project(dat)
    doc.setdefault("status", "active")
    if doc["status"] in OPEN_STATUSES:
        check_project_limit()
    pm = staff_name(pm_uid)
    doc["code"] = t.next_number("PRJ", "PRJ")
    doc["stages"] = build_stages(doc["services"], doc["start"])
    doc["team"] = [{"id": t.sid(), "user_id": pm_uid, "name": pm["name"], "project_role": "Project Manager",
                    "access": "edit", "kind": "staff"}]
    for m in extra_team:
        if not any(x.get("user_id") == m["user_id"] for x in doc["team"]):
            doc["team"].append({"id": t.sid(), "kind": "staff", **m})
    doc["team"] = sync_client(doc["team"], None, doc.get("client_id"), doc.get("client_name"))
    doc.setdefault("area_unit", "sqft")
    doc.update(extra_fields or {})
    normalize(doc)
    ends = [s["end"] for s in doc["stages"] if s.get("end")]
    doc["planned_end"] = max(ends) if ends else None
    return t.insert("projects", doc)


@bp.post("/projects")
@api("projects")
def create_project():
    return jsonify(present(new_project(request.get_json(force=True) or {}, g.uid))), 201


@bp.get("/projects/<_id>")
@api("projects")
def get_project(_id):
    return jsonify(present(load(_id)))


@bp.put("/projects/<_id>")
@api("projects")
def update_project(_id):
    p = load(_id)
    require_edit(p)
    dat = request.get_json(force=True) or {}
    changes = clean_project(dat, p)
    if changes.get("status") in OPEN_STATUSES and p.get("status") not in OPEN_STATUSES:
        check_project_limit()
    if "client_id" in changes and changes["client_id"] != p.get("client_id"):
        changes["team"] = sync_client(p.get("team", []), p.get("client_id"), changes["client_id"],
                                      changes.get("client_name"))
    added = [s for s in changes.get("services", []) if s not in p.get("services", [])]
    if added:
        p["stages"] = p.get("stages", []) + build_stages(added, p.get("start") or date.today().isoformat())
        normalize(p)
        changes["stages"] = p["stages"]
    saved = t.update("projects", _id, changes)
    labels = {"name": "name", "status": "status", "client_id": "client", "start": "start date", "target_end": "target end",
              "value": "value", "site": "site address", "services": "services", "branch": "branch", "area": "area",
              "description": "description", "project_type": "type", "referred_by": "referred by"}
    diff = [labels[k] for k in changes if k in labels and changes[k] != p.get(k)]
    if diff:
        extra = f" ({p.get('status')} → {changes['status']})" if "status" in changes and changes["status"] != p.get("status") else ""
        project_events.log(_id, "edit", "Project details changed: " + ", ".join(diff) + extra)
    return jsonify(present(saved))


@bp.delete("/projects/<_id>")
@api("projects")
def delete_project(_id):
    if g.role != "owner":
        abort(403, "Only the owner can delete a project")
    p = t.get("projects", _id)
    if db.costs.count_documents({"company_id": g.cid, "project_id": _id, "status": "approved"}):
        abort(409, "This project has approved costs; void them first so the money trail is kept")
    if db.purchase_orders.count_documents({"company_id": g.cid, "project_id": _id, "status": {"$nin": ["draft", "rejected", "cancelled"]}}):
        abort(409, "This project has purchase orders; cancel them first so the money trail is kept")
    if db.invoices.count_documents({"company_id": g.cid, "project_id": _id, "status": {"$nin": ["draft", "void"]}}):
        abort(409, "This project has invoices; void them first so the money trail is kept")
    t.delete("projects", _id)
    db.project_issues.delete_many({"company_id": g.cid, "project_id": _id})
    db.costs.delete_many({"company_id": g.cid, "project_id": _id})  # drafts, submitted, rejected and void only
    db.invoices.delete_many({"company_id": g.cid, "project_id": _id})  # drafts and void only
    db.change_orders.delete_many({"company_id": g.cid, "project_id": _id})
    from .lead_steps import delete_stored
    for doc in db.documents.find({"company_id": g.cid, "project_id": _id}):
        for v in doc.get("versions", []):
            delete_stored(v["file_key"])
    db.documents.delete_many({"company_id": g.cid, "project_id": _id})
    db.transmittals.delete_many({"company_id": g.cid, "project_id": _id})
    db.selections.delete_many({"company_id": g.cid, "project_id": _id})
    db.site_reports.delete_many({"company_id": g.cid, "project_id": _id})
    db.document_comments.delete_many({"company_id": g.cid, "project_id": _id})
    db.messages.delete_many({"company_id": g.cid, "project_id": _id, "channel": "portal"})
    for coll in ("purchase_requests", "rfqs", "purchase_orders"):  # drafts, rejected and cancelled only by now
        db[coll].delete_many({"company_id": g.cid, "project_id": _id})
    db.notifications.delete_many({"company_id": g.cid, "project_id": _id})  # no bell entry may point at it
    for coll in ("project_comments", "project_activity", "project_meetings", "project_delays"):
        db[coll].delete_many({"company_id": g.cid, "project_id": _id})
    # nothing may keep pointing at the deleted project: follow-ups close, the won lead and bid keep their result
    db.followups.update_many({"company_id": g.cid, "related.type": "project", "related.id": _id, "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Project deleted"}})
    note = {"id": t.sid(), "type": "note", "text": f"Project {p.get('code')} was deleted", "at": t.now(),
            "by": g.user.get("name"), "by_id": g.uid}
    db.leads.update_many({"company_id": g.cid, "project_id": _id},
                         {"$set": {"project_id": None}, "$push": {"activities": note}})
    db.bids.update_many({"company_id": g.cid, "project_id": _id}, {"$set": {"project_id": None}})
    # lead files and receipts stay with their lead
    db.lead_files.update_many({"company_id": g.cid, "project_id": _id}, {"$set": {"project_id": None}})
    db.lead_receipts.update_many({"company_id": g.cid, "project_id": _id}, {"$set": {"project_id": None}})
    # a signed contract stays with its lead; its milestone links went with the project
    for c in db.contracts.find({"company_id": g.cid, "project_id": _id}):
        db.contracts.update_one({"_id": c["_id"]}, {"$set": {"project_id": None, "payment_schedule": [
            {**r, "milestone_id": None} for r in c["payment_schedule"]]}})
    return jsonify({"ok": True})


# ---------------- team ----------------
@bp.post("/projects/<_id>/team")
@api("projects")
def add_member(_id):
    p = load(_id)
    require_edit(p)
    dat = request.get_json(force=True) or {}
    role = dat.get("project_role")
    if role not in PROJECT_ROLES:
        abort(400, "Choose a valid project role")
    access = dat.get("access", "view")
    if access not in ("edit", "view"):
        abort(400, "Access must be edit or view")
    if bool(dat.get("user_id")) == bool(dat.get("contact_id")):
        abort(400, "Add either a staff user or an external contact")
    if role == "Client":
        abort(400, "Set the client on the project details; it is added to the team automatically")
    if dat.get("user_id"):
        u = staff_name(dat["user_id"])
        entry = {"user_id": dat["user_id"], "name": u["name"], "kind": "staff", "access": access}
        dup = any(m.get("user_id") == dat["user_id"] for m in p.get("team", []))
    else:
        c = contact_doc(dat["contact_id"])
        entry = {"contact_id": dat["contact_id"], "name": c["name"], "kind": "external", "access": "view"}
        dup = any(m.get("contact_id") == dat["contact_id"] and m.get("project_role") == role for m in p.get("team", []))
    if dup:
        abort(409, f"{entry['name']} is already on this project" + ("" if dat.get("user_id") else f" as {role}"))
    entry.update(id=t.sid(), project_role=role)
    saved = t.update("projects", _id, {}, raw={"$push": {"team": entry}})
    project_events.added_to_team(saved, entry)
    return jsonify(present(saved)), 201


@bp.put("/projects/<_id>/team/<mid>")
@api("projects")
def update_member(_id, mid):
    p = load(_id)
    require_edit(p)
    dat = request.get_json(force=True) or {}
    m = next((x for x in p.get("team", []) if x["id"] == mid), None) or abort(404, "team member not found")
    if m.get("project_role") == "Client":
        abort(400, "Change the client on the project details")
    if "project_role" in dat:
        if dat["project_role"] not in PROJECT_ROLES or dat["project_role"] == "Client":
            abort(400, "Choose a valid project role")
        m["project_role"] = dat["project_role"]
    if "access" in dat:
        if dat["access"] not in ("edit", "view"):
            abort(400, "Access must be edit or view")
        if m.get("kind") == "external" and dat["access"] == "edit":
            abort(400, "External parties have view access only")
        if m.get("user_id") == g.uid and dat["access"] == "view" and g.role != "owner":
            abort(409, "You cannot remove your own edit access")
        m["access"] = dat["access"]
    project_events.log(_id, "team", f"{m['name']}: now {m['project_role']} ({m['access']} access)")
    return jsonify(present(t.update("projects", _id, {"team": p["team"]})))


@bp.delete("/projects/<_id>/team/<mid>")
@api("projects")
def remove_member(_id, mid):
    p = load(_id)
    require_edit(p)
    m = next((x for x in p.get("team", []) if x["id"] == mid), None) or abort(404, "team member not found")
    if m.get("project_role") == "Client":
        abort(400, "Change the client on the project details")
    if m.get("user_id") == g.uid and g.role != "owner":
        abort(409, "You cannot remove yourself from the project")
    team = [x for x in p["team"] if x["id"] != mid]
    if m.get("user_id"):  # unassign their open tasks so nothing points at someone off the project
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                if tk.get("assignee_id") == m["user_id"]:
                    tk["assignee_id"], tk["assignee_name"] = None, None
    project_events.log(_id, "team", f"{m['name']} removed from the team ({m['project_role']})")
    return jsonify(present(t.update("projects", _id, {"team": team, "stages": p.get("stages", [])})))


# ---------------- stages ----------------
def clean_stage(dat, p, stage=None):
    out = {}
    if "name" in dat or stage is None:
        if not (dat.get("name") or "").strip():
            abort(400, "Stage name is required")
        out["name"] = dat["name"].strip()
    if "service" in dat or stage is None:
        if dat.get("service") not in p.get("services", []):
            abort(400, "Stage service must be one of the project's services")
        out["service"] = dat["service"]
    for k in ("start", "end"):
        if k in dat or stage is None:
            out[k] = d(dat.get(k), f"Stage {k}", required=stage is None)
    s, e = out.get("start", (stage or {}).get("start")), out.get("end", (stage or {}).get("end"))
    if s and e and e < s:
        abort(400, "Stage end is before its start")
    if "budget" in dat:
        if not (g.role == "owner" or can("projects", True)) or g.hide_costs:
            abort(403, "Your role cannot set budgets")
        out["budget"] = money(dat["budget"], "Budget")
    if "status" in dat:
        if dat["status"] not in ("on_hold", "active"):
            abort(400, "Stage status is calculated from tasks; you can only put it on hold or resume it")
        out["status"] = "on_hold" if dat["status"] == "on_hold" else "not_started"
    if "client_signoff_required" in dat:
        out["client_signoff_required"] = bool(dat["client_signoff_required"])
    if "progress" in dat:
        if stage and stage.get("tasks"):
            abort(400, "Progress is calculated from this stage's tasks")
        v = dat["progress"]
        if not isinstance(v, (int, float)) or not 0 <= v <= 100:
            abort(400, "Progress must be 0-100")
        out["progress"] = int(v)
    return out


@bp.post("/projects/<_id>/stages")
@api("projects", write=False)
def add_stage(_id):
    p = load(_id)
    dat = request.get_json(force=True) or {}
    stage = {"id": t.sid(), "status": "not_started", "progress": 0, "budget": 0, "tasks": [], "milestones": [],
             "signoff": None, **clean_stage(dat, p)}
    require_edit(p, stage)
    gate = gate_defaults(stage["service"])
    checklist = dat.get("checklist", gate["checklist"]) or []
    if not isinstance(checklist, list):
        abort(400, "The closing checklist is a list of items")
    stage["checklist"] = checklist_items([str(x).strip()[:200] for x in checklist if str(x).strip()])
    stage.setdefault("client_signoff_required", gate["client_signoff"])
    if dat.get("milestone", True):
        stage["milestones"].append(gate_milestone(stage["name"], stage["end"]))
    p["stages"].append(stage)
    return jsonify(present(save_stages(_id, p))), 201


@bp.put("/projects/<_id>/stages/<sid>")
@api("projects", write=False)
def update_stage(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    dat = request.get_json(force=True) or {}
    if "service" in dat and dat["service"] != stage["service"]:
        abort(400, "A stage cannot move to another service")
    old_end = stage.get("end")
    stage.update(clean_stage(dat, p, stage))
    delay = require_delay_reason(p, "stage", stage, old_end, stage.get("end"), dat)
    record_delay(delay)
    return jsonify(present(save_stages(_id, p)))


@bp.delete("/projects/<_id>/stages/<sid>")
@api("projects", write=False)
def delete_stage(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    ids = {tk["id"] for tk in stage.get("tasks", [])}
    blockers = [tk["title"] for s in p["stages"] if s["id"] != sid for tk in s.get("tasks", [])
                if set(tk.get("depends_on") or []) & ids]
    if blockers:
        abort(409, f"Tasks in other stages depend on this stage: {', '.join(blockers[:3])}")
    p["stages"] = [s for s in p["stages"] if s["id"] != sid]
    return jsonify(present(save_stages(_id, p)))


@bp.post("/projects/<_id>/stages/reorder")
@api("projects")
def reorder_stages(_id):
    p = load(_id)
    require_edit(p)
    order = (request.get_json(force=True) or {}).get("order") or []
    if sorted(order) != sorted(s["id"] for s in p["stages"]):
        abort(400, "Order must list every stage exactly once")
    pos = {sid: i for i, sid in enumerate(order)}
    p["stages"].sort(key=lambda s: pos[s["id"]])
    return jsonify(present(save_stages(_id, p)))


# ---------------- tasks ----------------
def clean_task(dat, p, task=None):
    out = {}
    if "title" in dat or task is None:
        if not (dat.get("title") or "").strip():
            abort(400, "Task title is required")
        out["title"] = dat["title"].strip()
    for k in ("start", "end"):
        if k in dat or task is None:
            out[k] = d(dat.get(k), f"Task {k}", required=task is None)
    s, e = out.get("start", (task or {}).get("start")), out.get("end", (task or {}).get("end"))
    if s and e and e < s:
        abort(400, "Task end is before its start")
    if "assignee_id" in dat:
        if dat["assignee_id"]:
            if not any(m.get("user_id") == dat["assignee_id"] for m in p.get("team", [])):
                abort(400, "Assignee must be on the project team")
            out["assignee_id"] = dat["assignee_id"]
            out["assignee_name"] = staff_name(dat["assignee_id"])["name"]
        else:
            out["assignee_id"], out["assignee_name"] = None, None
    if "links" in dat or "depends_on" in dat:
        raw = dat.get("links")
        if raw is None:
            raw = [{"task_id": x, "type": "FS", "lag": 0} for x in (dat.get("depends_on") or [])]
        known = all_tasks(p)
        links, seen = [], set()
        for ln in raw:
            tid = ln.get("task_id")
            if tid not in known:
                abort(400, "Dependency refers to a task that does not exist on this project")
            if task and tid == task["id"]:
                abort(400, "A task cannot depend on itself")
            if (ln.get("type") or "FS") not in LINK_TYPES:
                abort(400, "Link type must be FS (finish → start), SS (start → start) or FF (finish → finish)")
            lag = ln.get("lag") or 0
            if not isinstance(lag, int) or not -60 <= lag <= 365:
                abort(400, "Lag is a whole number of working days (-60 to 365)")
            if tid not in seen:
                seen.add(tid)
                links.append({"task_id": tid, "type": ln.get("type") or "FS", "lag": lag})
        out["links"] = links
        out["depends_on"] = [ln["task_id"] for ln in links]
    if "status" in dat:
        if dat["status"] not in TASK_STATUSES:
            abort(400, "Task status must be to do, in progress, blocked or done")
        out["status"] = dat["status"]
    if "progress" in dat:
        v = dat["progress"]
        if not isinstance(v, (int, float)) or not 0 <= v <= 100:
            abort(400, "Progress must be 0-100")
        out["progress"] = int(v)
    if "notes" in dat:
        out["notes"] = dat["notes"]
    if "waiting_on" in dat:
        w = dat.get("waiting_on") or None
        if w:
            if w.get("party") not in WAITING_PARTIES:
                abort(400, f"Waiting on must be one of: {', '.join(WAITING_PARTIES.values())}")
            out["waiting_on"] = {"party": w["party"], "contact_id": w.get("contact_id") or None,
                                 "note": (w.get("note") or "").strip()[:300] or None,
                                 "since": ((task or {}).get("waiting_on") or {}).get("since") or date.today().isoformat()}
            if w.get("contact_id"):
                out["waiting_on"]["contact_name"] = contact_doc(w["contact_id"])["name"]
        else:
            out["waiting_on"] = None
    if "priority" in dat:
        if dat["priority"] not in TASK_PRIORITIES:
            abort(400, "Priority must be low, normal, high or urgent")
        out["priority"] = dat["priority"]
    return out


def check_checklist(task):
    """A task with a checklist is done only when every item is ticked."""
    if task["status"] == "done":
        left = [c["text"] for c in task.get("checklist", []) if not c["done"]]
        if left:
            abort(409, f"Tick the checklist first ({len(left)} open: {', '.join(left[:3])})")


def check_predecessors(p, task):
    """FS: cannot start until the other task is done. SS: cannot start until the other task has started.
    FF: cannot be done until the other task is done."""
    if task["status"] not in ("in_progress", "done"):
        return
    tasks = all_tasks(p)
    waiting = []
    for ln in links_of(task, tasks):
        other = tasks[ln["task_id"]][1]
        if ln["type"] == "FS" and other["status"] != "done":
            waiting.append(f"{other['title']} to finish")
        elif ln["type"] == "SS" and other["status"] not in ("in_progress", "done"):
            waiting.append(f"{other['title']} to start")
        elif ln["type"] == "FF" and task["status"] == "done" and other["status"] != "done":
            waiting.append(f"{other['title']} to finish first")
    if waiting:
        abort(409, f"Waiting on: {', '.join(waiting)}")


def baseline(p):
    return (p.get("baselines") or [None])[-1]


def require_delay_reason(p, kind, item, old_end, new_end, dat):
    """Once a baseline is set, a date moved later needs a reason; it is kept as a delay (who caused it)."""
    if not (baseline(p) and old_end and new_end and new_end > old_end):
        return None
    reason = dat.get("delay_reason")
    if reason not in DELAY_REASONS:
        abort(409, f"{item.get('title') or item.get('name')} moves {old_end} → {new_end}: choose why "
                   f"(delay reason), because the plan has a baseline")
    return {"project_id": str(p["_id"]), "kind": kind, "item_id": item["id"], "title": item.get("title") or item.get("name"),
            "from": old_end, "to": new_end, "days": workdays.shift(old_end, new_end), "reason": reason,
            "reason_label": DELAY_REASONS[reason][0], "party": DELAY_REASONS[reason][1],
            "note": (dat.get("delay_note") or "").strip()[:300] or None}


def record_delay(row):
    if row:
        doc = {**row, "company_id": g.cid, "by": g.user.get("name"), "by_id": g.uid, "at": t.now()}
        db.project_delays.insert_one(doc)
        project_events.log(row["project_id"], "delay", f"Delay: {row['title']} {row['from']} → {row['to']} "
                           f"(+{row['days']} working days) — {row['reason_label']}" + (f": {row['note']}" if row["note"] else ""),
                           item_id=row["item_id"])


def shift_dependents(p, task, delta):
    """Move every task that depends on this one (and theirs, and so on) by the same number of working days."""
    if not delta:
        return []
    cal = workdays.calendar()
    tasks = all_tasks(p)
    moved, queue = [], [task["id"]]
    while queue:
        cur = queue.pop(0)
        for tid, (_, tk) in tasks.items():
            if tid in moved or tid == task["id"] or cur not in (tk.get("depends_on") or []):
                continue
            tk["start"] = workdays.add_working(tk["start"], delta, cal) if tk.get("start") else tk.get("start")
            tk["end"] = workdays.add_working(tk["end"], delta, cal) if tk.get("end") else tk.get("end")
            moved.append(tid)
            queue.append(tid)
    return [tasks[x][1]["title"] for x in moved]


@bp.post("/projects/<_id>/stages/<sid>/tasks")
@api("projects", write=False)
def add_task(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    from .project_work import _open_stage
    _open_stage(p, stage)
    task = {"id": t.sid(), "status": "todo", "progress": 0, "depends_on": [], "assignee_id": None,
            "assignee_name": None, "priority": "normal", "checklist": [], "files": []}
    task.update(clean_task(request.get_json(force=True) or {}, p))
    check_predecessors(p, task)
    stage.setdefault("tasks", []).append(task)
    _check_cycle(p)
    return jsonify(present(save_stages(_id, p))), 201


@bp.put("/projects/<_id>/tasks/<tid>")
@api("projects", write=False)
def update_task(_id, tid):
    p = load(_id)
    stage, task = find_task(p, tid)
    dat = request.get_json(force=True) or {}
    if not can_edit_stage(p, stage):
        # assignees may update the status / progress / notes of their own task
        if task.get("assignee_id") != g.uid or set(dat) - {"status", "progress", "notes", "waiting_on"}:
            abort(403, "You can only update the status of tasks assigned to you")
    old_start, old_end = task.get("start"), task.get("end")
    task.update(clean_task(dat, p, task))
    if dat.get("status") == "done":
        task["progress"] = 100
    if task["status"] == "blocked" and not task.get("waiting_on"):
        task["waiting_on"] = {"party": "us", "contact_id": None, "note": task.get("notes"), "since": date.today().isoformat()}
    if task["status"] != "blocked" and "status" in dat:
        task["waiting_on"] = None  # unblocked: no longer waiting
    delay = require_delay_reason(p, "task", task, old_end, task.get("end"), dat)
    check_checklist(task)
    check_predecessors(p, task)
    _check_cycle(p)
    moved = []
    if dat.get("shift_dependents") and (task.get("start"), task.get("end")) != (old_start, old_end):
        base = (old_start, task.get("start")) if task.get("start") != old_start else (old_end, task.get("end"))
        moved = shift_dependents(p, task, workdays.shift(*base))
    record_delay(delay)
    saved = save_stages(_id, p)
    if moved:
        project_events.log(_id, "schedule", f"Moved with {task['title']}: {', '.join(moved)}", task_id=tid)
    return jsonify(present(saved))


@bp.delete("/projects/<_id>/tasks/<tid>")
@api("projects", write=False)
def delete_task(_id, tid):
    p = load(_id)
    stage, task = find_task(p, tid)
    require_edit(p, stage)
    stage["tasks"] = [x for x in stage["tasks"] if x["id"] != tid]
    db.project_comments.delete_many({"company_id": g.cid, "project_id": _id, "task_id": tid})
    for s in p["stages"]:  # drop the deleted task from other tasks' dependencies
        for tk in s.get("tasks", []):
            tk["depends_on"] = [x for x in tk.get("depends_on", []) if x != tid]
    return jsonify(present(save_stages(_id, p)))


# ---------------- milestones ----------------
def clean_milestone(dat, ms=None):
    out = {}
    if "name" in dat or ms is None:
        if not (dat.get("name") or "").strip():
            abort(400, "Milestone name is required")
        out["name"] = dat["name"].strip()
    if "due" in dat or ms is None:
        out["due"] = d(dat.get("due"), "Milestone date", required=True)
    if "status" in dat:
        if dat["status"] not in ("pending", "achieved"):
            abort(400, "Milestone status must be pending or achieved")
        out["status"] = dat["status"]
        out["achieved_at"] = date.today().isoformat() if dat["status"] == "achieved" else None
    return out


def find_ms(p, mid):
    for s in p.get("stages", []):
        for ms in s.get("milestones", []):
            if ms["id"] == mid:
                return s, ms
    abort(404, "milestone not found")


@bp.post("/projects/<_id>/stages/<sid>/milestones")
@api("projects", write=False)
def add_milestone(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    ms = {"id": t.sid(), "status": "pending", "achieved_at": None, **clean_milestone(request.get_json(force=True) or {})}
    stage.setdefault("milestones", []).append(ms)
    return jsonify(present(save_stages(_id, p))), 201


@bp.put("/projects/<_id>/milestones/<mid>")
@api("projects", write=False)
def update_milestone(_id, mid):
    p = load(_id)
    stage, ms = find_ms(p, mid)
    require_edit(p, stage)
    dat = request.get_json(force=True) or {}
    closing = ms.get("gate") and dat.get("status") == "achieved" and ms["status"] != "achieved"
    old_due = ms.get("due")
    ms.update(clean_milestone(dat, ms))
    record_delay(require_delay_reason(p, "milestone", ms, old_due, ms.get("due"), dat))
    if closing:
        missing = gate_missing(p, stage)
        reason = (dat.get("override_reason") or "").strip()
        if missing and not reason:
            abort(409, f"{stage['name']} cannot be closed yet: " + "; ".join(missing))
        if missing and g.role != "owner":
            abort(403, "Only the Owner can close a stage that is not ready (with a reason)")
        ms["override_reason"] = reason if missing else None
        ms["closed_by"] = g.user.get("name")
    elif dat.get("status") == "pending":
        ms["override_reason"], ms["closed_by"] = None, None
    return jsonify(present(save_stages(_id, p)))


@bp.delete("/projects/<_id>/milestones/<mid>")
@api("projects", write=False)
def delete_milestone(_id, mid):
    p = load(_id)
    stage, ms = find_ms(p, mid)
    require_edit(p, stage)
    if ms.get("gate"):
        abort(409, f"“{ms['name']}” closes the stage {stage['name']} and cannot be deleted")
    stage["milestones"] = [m for m in stage["milestones"] if m["id"] != mid]
    return jsonify(present(save_stages(_id, p)))


# ---------------- dashboard, issues, history ----------------
def next_milestones(projects, limit=5):
    today = date.today().isoformat()
    rows = []
    for p in projects:
        for s in p.get("stages", []):
            for ms in s.get("milestones", []):
                if ms["status"] == "pending":
                    rows.append({"project_id": str(p["_id"]), "project": p["name"], "stage": s["name"], "id": ms["id"],
                                 "name": ms["name"], "due": ms["due"], "late": ms["due"] < today})
    return sorted(rows, key=lambda r: r["due"])[:limit]


@bp.get("/projects/<_id>/dashboard")
@api("projects")
def dashboard(_id):
    p = load(_id)
    today = date.today().isoformat()
    tasks = [tk for _, tk in all_tasks(p).values()]
    actual = sum(c.get("amount", 0) for c in db.costs.find({"company_id": g.cid, "project_id": _id,
                                                           "status": "approved"}))
    issues = list(db.project_issues.find({"company_id": g.cid, "project_id": _id, "status": "open"})
                  .sort("created_at", -1))
    data = {
        "progress": project_progress(p),
        "next_milestones": next_milestones([p]),
        "open_issues": len(issues),
        "issues": serialize(issues[:5]),
        "tasks": {"total": len(tasks), "done": sum(1 for x in tasks if x["status"] == "done"),
                  "blocked": sum(1 for x in tasks if x["status"] == "blocked"),
                  "late": sum(1 for x in tasks if x["status"] != "done" and x.get("end") and x["end"] < today),
                  "conflicts": sum(1 for x in tasks if x.get("conflict"))},
        "stages": [{"id": s["id"], "name": s["name"], "service": s["service"], "status": s["status"],
                    "progress": s.get("progress", 0), **{k: r[k] for k in ("budget", "spent", "committed", "pct", "level")}}
                   for s, r in zip(p.get("stages", []), budget.budget_rows(p))],
        "budget": {"budget": round(sum(s.get("budget", 0) or 0 for s in p.get("stages", [])), 2),
                   "actual": round(actual, 2), "value": p.get("value", 0)},
    }
    data["budget"]["committed"] = round(sum(s["committed"] for s in data["stages"]), 2)
    if g.hide_costs:
        data.pop("budget")
        for s in data["stages"]:
            for k in ("budget", "spent", "committed", "pct", "level"):
                s.pop(k)
    return jsonify(data)


@bp.get("/projects/<_id>/issues")
@api("projects")
def list_issues(_id):
    load(_id)
    q = {"company_id": g.cid, "project_id": _id}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify(serialize(list(db.project_issues.find(q).sort("created_at", -1))))


@bp.post("/projects/<_id>/issues")
@api("projects", write=False)
def add_issue(_id):
    p = load(_id)  # any project member can raise an issue
    dat = request.get_json(force=True) or {}
    if not (dat.get("title") or "").strip():
        abort(400, "Issue title is required")
    if dat.get("severity", "medium") not in ISSUE_SEVERITIES:
        abort(400, "Severity must be low, medium or high")
    owner = None
    if dat.get("owner_id"):
        if not any(m.get("user_id") == dat["owner_id"] for m in p.get("team", [])):
            abort(400, "Issue owner must be on the project team")
        owner = staff_name(dat["owner_id"])["name"]
    if dat.get("stage_id"):
        find_stage(p, dat["stage_id"])
    doc = t.insert("project_issues", {
        "project_id": _id, "stage_id": dat.get("stage_id") or None, "title": dat["title"].strip(), "description": dat.get("description"),
        "severity": dat.get("severity", "medium"), "status": "open", "owner_id": dat.get("owner_id"),
        "owner_name": owner, "due": d(dat.get("due"), "Due date"), "raised_by": g.user.get("name")})
    project_events.issue_raised(p, doc)
    return jsonify(serialize(doc)), 201


@bp.put("/projects/<_id>/issues/<iid>")
@api("projects", write=False)
def update_issue(_id, iid):
    p = load(_id)
    issue = t.get("project_issues", iid)
    if issue["project_id"] != _id:
        abort(404)
    if not can_edit(p) and issue.get("created_by") != g.uid:
        abort(403, "Only project editors or the person who raised it can change this issue")
    dat = request.get_json(force=True) or {}
    changes = {}
    if "status" in dat:
        if dat["status"] not in ("open", "closed"):
            abort(400, "Status must be open or closed")
        changes["status"] = dat["status"]
        changes["closed_at"] = t.now() if dat["status"] == "closed" else None
    for k in ("title", "description"):
        if k in dat:
            changes[k] = dat[k]
    if "severity" in dat:
        if dat["severity"] not in ISSUE_SEVERITIES:
            abort(400, "Severity must be low, medium or high")
        changes["severity"] = dat["severity"]
    if "waiting_on" in dat:
        w = dat.get("waiting_on") or None
        if w and w.get("party") not in WAITING_PARTIES:
            abort(400, f"Waiting on must be one of: {', '.join(WAITING_PARTIES.values())}")
        changes["waiting_on"] = {"party": w["party"], "note": (w.get("note") or "").strip()[:300] or None,
                                 "since": (issue.get("waiting_on") or {}).get("since") or date.today().isoformat()} if w else None
    if changes.get("status") and changes["status"] != issue["status"]:
        project_events.log(_id, "issue", f"Issue {'closed' if changes['status'] == 'closed' else 'reopened'}: {issue['title']}",
                           issue_id=iid)
    return jsonify(serialize(t.update("project_issues", iid, changes)))


@bp.get("/projects/<_id>/history")
@api("projects")
def project_history(_id):
    load(_id)
    rows = db.audit_logs.find({"company_id": g.cid, "doc_id": _id}).sort("at", -1).limit(100)
    out = []
    for a in rows:
        keys = [k for k in (a.get("changes") or {}) if k not in ("planned_end",)]
        out.append({"at": a["at"], "by": a.get("user_name"), "action": a["action"], "fields": keys})
    return jsonify(serialize(out))


# ---------------- staff directory, home ----------------
@bp.get("/directory/staff")
@api("projects", write=False)
def staff_directory():
    """Active staff for team / assignee pickers (no emails or other private details)."""
    rows = db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}}, {"name": 1, "role": 1})
    return jsonify([{"id": str(u["_id"]), "name": u["name"], "role": u["role"]} for u in rows])


@bp.get("/home")
@api(None)
def home():
    today = date.today().isoformat()
    data = {"today": today}
    if can("projects"):
        q = {} if g.role == "owner" else {"team.user_id": g.uid}
        projects = t.find("projects", q)
        counts = {s: 0 for s in PROJECT_STATUSES}
        for p in projects:
            counts[p.get("status", "active")] = counts.get(p.get("status", "active"), 0) + 1
        my_tasks = []
        for p in projects:
            for s in p.get("stages", []):
                for tk in s.get("tasks", []):
                    if tk.get("assignee_id") == g.uid and tk["status"] != "done":
                        my_tasks.append({"project_id": str(p["_id"]), "project": p["name"], "stage": s["name"],
                                         "id": tk["id"], "title": tk["title"], "status": tk["status"],
                                         "end": tk.get("end"), "late": bool(tk.get("end") and tk["end"] < today)})
        data.update(projects=counts, my_tasks=sorted(my_tasks, key=lambda r: r["end"] or "9999")[:10],
                    milestones=next_milestones([p for p in projects if p.get("status") in OPEN_STATUSES], 8))
        from ..services.project_health import health
        risk = []
        for p in projects:
            if p.get("status") in ("planning", "active"):
                h = health(p)
                if h["grade"] != "green":
                    risk.append({"id": str(p["_id"]), "name": p["name"], "score": h["score"], "grade": h["grade"],
                                 "label": h["label"], "why": next((x["why"] for x in sorted(h["parts"], key=lambda x: x["points"] - x["max"])), "")})
        data["projects_at_risk"] = sorted(risk, key=lambda r: r["score"])[:8]
    if can("followups"):
        mine = {"company_id": g.cid, "owner_id": g.uid, "status": "open"}
        data["followups"] = {"overdue": db.followups.count_documents({**mine, "due": {"$lt": today}}),
                             "today": db.followups.count_documents({**mine, "due": today})}
    if can("leads"):
        data["leads"] = {"open": db.leads.count_documents({"company_id": g.cid, "status": "open"}),
                         "mine": db.leads.count_documents({"company_id": g.cid, "status": "open", "owner_id": g.uid}),
                         "unassigned": db.leads.count_documents({"company_id": g.cid, "status": "open", "owner_id": None})}
    if can("contacts"):
        from .contacts import compliance_status
        alerts = 0
        for c in t.find("contacts", {"compliance": {"$elemMatch": {"expiry": {"$type": "string"}}}}):
            alerts += sum(1 for doc in c.get("compliance", []) if compliance_status(doc) in ("expired", "expiring"))
        data["compliance_alerts"] = alerts
    return jsonify(data)


# ---------------- portal (§13: portal users see only their projects) ----------------
def portal_query():
    q = {"company_id": g.cid, "team.contact_id": g.contact_id}
    return q


@bp.get("/portal/projects")
@portal
def portal_projects():
    out = []
    for p in db.projects.find(portal_query()).sort("created_at", -1):
        roles = [m["project_role"] for m in p.get("team", []) if m.get("contact_id") == g.contact_id]
        out.append({"id": str(p["_id"]), "code": p.get("code"), "name": p["name"], "status": p.get("status"),
                    "services": p.get("services"), "city": (p.get("site") or {}).get("city"),
                    "progress": project_progress(p), "my_roles": roles, "planned_end": p.get("planned_end")})
    return jsonify(out)


@bp.get("/portal/projects/<_id>")
@portal
def portal_project(_id):
    p = db.projects.find_one({**portal_query(), "_id": oid(_id)})
    if not p:
        abort(404, "project not found")
    team = [{"name": m["name"], "project_role": m["project_role"]} for m in p.get("team", [])]
    stages = [{"name": s["name"], "service": s["service"], "start": s.get("start"), "end": s.get("end"),
               "status": s["status"], "progress": s.get("progress", 0),
               "milestones": [{"name": m["name"], "due": m["due"], "status": m["status"]} for m in s.get("milestones", [])]}
              for s in p.get("stages", [])]
    # Phase G: each row is something this person can act on — sent to them by name, or (for the client) to the client
    from ..services.project_health import waiting
    client = any(m.get("contact_id") == g.contact_id and m.get("project_role") == "Client" for m in p.get("team", []))
    waiting_on_you = [{"title": r["title"], "since": r["since"], "days": r["days"], "note": r["note"], "kind": r["kind"], "ref": r["ref"]}
                      for r in waiting(p)["rows"]
                      if ((g.contact_id in r["contact_ids"]) if "contact_ids" in r else (client and r["party"] == "client"))]
    return jsonify({"id": _id, "code": p.get("code"), "name": p["name"], "status": p.get("status"),
                    "services": p.get("services"), "site": p.get("site"), "progress": project_progress(p),
                    "planned_end": p.get("planned_end"), "team": team, "stages": stages, "waiting_on_you": waiting_on_you,
                    "my_role": next((m.get("project_role") for m in p.get("team", []) if m.get("contact_id") == g.contact_id), None)})
