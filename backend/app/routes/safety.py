"""Phase L block 2 — safety: incidents, inspections and checklists, toolbox talks (v4 §10).

* Incident: near miss, first aid, injury, lost time, property damage, environmental, fire. Reported on site (or from
  the offline app) with the people involved, what was done at once and photos. A serious one (an injury, lost time,
  fire, or severity high / critical) tells the project's managers and the Owners at once. Then: investigation (root
  cause and what contributed) and corrective actions, each with an owner and a due date; closed by a manager once every
  action is done. Lost-time days are kept for the safety report.
* Inspection: a checklist from a template (company settings; three ready-made ones). Each item passes, fails or does not
  apply. The score is passed / (passed + failed). A failed item becomes a snag on the project (high priority when the
  item is critical) so it is tracked until it is fixed and closed; a failed critical item tells the managers.
* Toolbox talk: the topic, who attended (from the attendance list) and notes.
* Safety report: incidents by kind and month, days since the last lost-time incident per project, open and overdue
  actions, inspection scores and the items that fail most.
The worker reminds the owner of a corrective action once it is past due.
Who: read — anyone who sees site records on the project; report, inspect, talks — site writers on the project;
investigate, add actions, close — the Owner and the project's managers.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales
from .lead_money import a_date
from .projects import member
from .site_plus import site_access, files_of, people

bp = Blueprint("safety", __name__)
INCIDENT_KINDS = {"near_miss": "Near miss", "first_aid": "First aid", "injury": "Injury", "lost_time": "Lost-time injury",
                  "property_damage": "Property damage", "environmental": "Environmental", "fire": "Fire", "other": "Other"}
SEVERITIES = ["low", "medium", "high", "critical"]
SERIOUS_KINDS = {"injury", "lost_time", "fire"}
ROOT_CAUSES = ["No or wrong PPE", "Unsafe act", "Unsafe condition", "No training", "No method statement / permit", "Housekeeping",
               "Equipment fault", "Supervision", "Weather", "Other"]
STATUSES = ["reported", "investigating", "closed"]
RESULTS = ("pass", "fail", "na")

DEFAULT_TEMPLATES = [
    {"id": "weekly", "name": "Weekly site safety", "kind": "safety", "items": [
        {"id": "ppe", "text": "Everyone on site wears helmet, shoes and the PPE for their work", "critical": True},
        {"id": "scaffold", "text": "Scaffolding and ladders are sound, tagged and tied", "critical": True},
        {"id": "edges", "text": "Open edges, shafts and openings are guarded or covered", "critical": True},
        {"id": "elec", "text": "Temporary electrics: covered DBs, no bare joints, ELCB working", "critical": True},
        {"id": "fire", "text": "Fire extinguishers in place and in date", "critical": False},
        {"id": "firstaid", "text": "First-aid kit stocked; first-aider on site", "critical": False},
        {"id": "house", "text": "Walkways clear, debris removed, materials stacked safely", "critical": False},
        {"id": "signs", "text": "Safety signs and emergency numbers displayed", "critical": False}]},
    {"id": "height", "name": "Working at height", "kind": "safety", "items": [
        {"id": "harness", "text": "Full-body harness worn and anchored above 2 m", "critical": True},
        {"id": "platform", "text": "Working platform has guard rails and toe boards", "critical": True},
        {"id": "ladder", "text": "Ladders at the right angle, footed or tied", "critical": False},
        {"id": "below", "text": "Area below is barricaded", "critical": False}]},
    {"id": "electrical", "name": "Electrical safety", "kind": "safety", "items": [
        {"id": "loto", "text": "Isolation and lock-out before work on circuits", "critical": True},
        {"id": "tools", "text": "Power tools have sound cables and plugs", "critical": False},
        {"id": "wet", "text": "No cables through water or wet areas", "critical": True},
        {"id": "earth", "text": "Earthing in place for the temporary supply", "critical": False}]},
]


def templates(company=None):
    s = (company or g.company).get("safety") or {}
    return s.get("templates") or DEFAULT_TEMPLATES


def r1(v):
    return round(v + 1e-9, 1)


def is_manager(p):
    m = member(p)
    return g.role == "owner" or (g.role == "pm" and m is not None) or (m is not None and m.get("project_role") == ev.PM_ROLE)


def team_user(p, uid, label="Owner of the action"):
    m = next((x for x in p.get("team", []) if x.get("user_id") == uid), None) if uid else None
    return m or abort(400, f"{label} must be someone on the project team")


def serious(i):
    return i["kind"] in SERIOUS_KINDS or i["severity"] in ("high", "critical")


def inc_out(i):
    d = serialize(i)
    today = sales.today()
    for a in d.get("actions", []):
        a["overdue"] = not a.get("done_at") and bool(a.get("due")) and a["due"] < today
    d["kind_label"] = INCIDENT_KINDS.get(i["kind"], i["kind"])
    d["serious"] = serious(i)
    for ph in d.get("photos", []):
        ph["url"] = f"/api/files/{ph['key']}"
    return d


def a_time(v):
    if not v:
        return None
    try:
        hh, mm = (int(x) for x in str(v).split(":")[:2])
        assert 0 <= hh < 24 and 0 <= mm < 60
    except (ValueError, AssertionError):
        abort(400, "Time is like 14:30")
    return f"{hh:02d}:{mm:02d}"


# ============================== incidents ==============================
@bp.get("/projects/<pid>/incidents")
@api(None)
def list_incidents(pid):
    p = site_access(pid)
    rows = [inc_out(i) for i in t.find("incidents", {"project_id": pid}, sort=[("date", -1), ("created_at", -1)])]
    return jsonify({"incidents": rows, "kinds": [{"value": k, "label": v} for k, v in INCIDENT_KINDS.items()], "severities": SEVERITIES,
                    "root_causes": ROOT_CAUSES, "people": people(p), "team": [{"id": m["user_id"], "name": m["name"]} for m in p.get("team", []) if m.get("user_id")],
                    "can_write": can("site", True) and (g.role == "owner" or member(p) is not None), "can_manage": is_manager(p)})


@bp.post("/projects/<pid>/incidents")
@api(None)
def add_incident(pid):
    p = site_access(pid, write=True)
    d = request.get_json(force=True) or {}
    kind = d.get("kind") if d.get("kind") in INCIDENT_KINDS else abort(400, f"Kind: {', '.join(INCIDENT_KINDS)}")
    sev = d.get("severity") or ("high" if kind in SERIOUS_KINDS else "low")
    if sev not in SEVERITIES:
        abort(400, "Severity: low, medium, high or critical")
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "An incident cannot be in the future")
    what = (d.get("description") or "").strip()[:3000] or abort(400, "Say what happened")
    involved = []
    for x in (d.get("people") or [])[:20]:
        name = (x.get("name") or "").strip()[:80] or abort(400, "Each person involved needs a name")
        involved.append({"name": name, "person": x.get("person"), "injury": (x.get("injury") or "").strip()[:300] or None,
                         "treated": (x.get("treated") or "").strip()[:200] or None})
    if kind in ("injury", "lost_time", "first_aid") and not involved:
        abort(400, "Add the person who was hurt")
    lost = d.get("lost_days")
    try:
        lost = max(0, min(365, int(lost or 0)))
    except (TypeError, ValueError):
        abort(400, "Lost days is a number")
    i = t.insert("incidents", {"number": t.next_number("INC", "INC"), "project_id": pid, "project_name": p["name"], "kind": kind, "severity": sev,
                               "date": day, "time": a_time(d.get("time")), "location": (d.get("location") or "").strip()[:200] or None,
                               "description": what, "people": involved, "witnesses": (d.get("witnesses") or "").strip()[:500] or None,
                               "immediate_action": (d.get("immediate_action") or "").strip()[:1000] or None, "photos": files_of(d.get("photos")),
                               "lost_days": lost if kind == "lost_time" else 0, "status": "reported", "root_cause": None, "factors": None,
                               "investigation": None, "actions": [], "reported_by": g.user.get("name"), "reported_by_id": g.uid,
                               "history": [{"status": "reported", "by": g.user.get("name"), "at": t.now()}]})
    ev.log(pid, "issue", f"Safety: {i['number']} {INCIDENT_KINDS[kind].lower()} — {what[:80]}")
    if serious(i):
        who = list(dict.fromkeys(ev.managers(p) + ev.owners()))
        notify.send("safety_incident", who, f"{p['name']}: {INCIDENT_KINDS[kind]} ({sev}) — {what[:120]}", f"/app/projects/{pid}?tab=safety",
                    project_id=pid, level="urgent" if sev == "critical" or kind in SERIOUS_KINDS else "warn", skip_self=False)
    return jsonify(inc_out(i)), 201


def load_incident(iid, manage=False):
    i = t.get("incidents", iid)
    p = site_access(i["project_id"])
    if manage and not is_manager(p):
        abort(403, "Only the Owner or the project's managers investigate and close incidents")
    return i, p


@bp.get("/incidents/<iid>")
@api(None)
def get_incident(iid):
    return jsonify(inc_out(load_incident(iid)[0]))


@bp.post("/incidents/<iid>/investigate")
@api(None)
def investigate(iid):
    i, p = load_incident(iid, manage=True)
    if i["status"] == "closed":
        abort(409, "This incident is closed; reopen it first")
    d = request.get_json(force=True) or {}
    rc = d.get("root_cause")
    if rc not in ROOT_CAUSES:
        abort(400, "Choose the root cause")
    text = (d.get("findings") or "").strip()[:3000] or abort(400, "Write what the investigation found")
    upd = t.update("incidents", iid, {"status": "investigating", "root_cause": rc, "factors": (d.get("factors") or "").strip()[:1000] or None,
                                      "investigation": {"findings": text, "by": g.user.get("name"), "at": t.now()},
                                      "history": i.get("history", []) + [{"status": "investigating", "by": g.user.get("name"), "at": t.now()}]})
    return jsonify(inc_out(upd))


@bp.post("/incidents/<iid>/actions")
@api(None)
def add_action(iid):
    i, p = load_incident(iid, manage=True)
    if i["status"] == "closed":
        abort(409, "This incident is closed")
    d = request.get_json(force=True) or {}
    text = (d.get("text") or "").strip()[:500] or abort(400, "What must be done?")
    m = team_user(p, d.get("owner_id"))
    due = a_date(d.get("due"), "Due date") if d.get("due") else (date.fromisoformat(sales.today()) + timedelta(days=7)).isoformat()
    a = {"id": t.sid(), "text": text, "owner_id": m["user_id"], "owner_name": m["name"], "due": due, "done_at": None, "done_note": None, "done_by": None}
    upd = t.update("incidents", iid, {"actions": i.get("actions", []) + [a]})
    notify.send("safety_action", [m["user_id"]], f"{p['name']}: safety action from {i['number']} — {text} (by {due})", f"/app/projects/{p['_id']}?tab=safety",
                project_id=str(p["_id"]))
    return jsonify(inc_out(upd)), 201


@bp.post("/incidents/<iid>/actions/<aid>/done")
@api(None)
def action_done(iid, aid):
    i, p = load_incident(iid)
    a = next((x for x in i.get("actions", []) if x["id"] == aid), None) or abort(404, "Action not found")
    if a["owner_id"] != g.uid and not is_manager(p):
        abort(403, "Only the action's owner or a manager marks it done")
    if a.get("done_at"):
        abort(409, "Already done")
    d = request.get_json(force=True) or {}
    a.update(done_at=t.now(), done_note=(d.get("note") or "").strip()[:500] or None, done_by=g.user.get("name"), photos=files_of(d.get("photos")))
    return jsonify(inc_out(t.update("incidents", iid, {"actions": i["actions"]})))


@bp.post("/incidents/<iid>/close")
@api(None)
def close_incident(iid):
    i, p = load_incident(iid, manage=True)
    if i["status"] == "closed":
        abort(409, "Already closed")
    if not i.get("investigation") and i["kind"] != "near_miss" and serious(i):
        abort(409, "A serious incident is investigated before it is closed")
    open_ = [a["text"] for a in i.get("actions", []) if not a.get("done_at")]
    if open_:
        abort(409, f"{len(open_)} corrective action(s) are not done yet")
    d = request.get_json(force=True) or {}
    upd = t.update("incidents", iid, {"status": "closed", "closed_at": t.now(), "closed_by": g.user.get("name"),
                                      "close_note": (d.get("note") or "").strip()[:500] or None,
                                      "history": i.get("history", []) + [{"status": "closed", "by": g.user.get("name"), "at": t.now()}]})
    ev.log(str(p["_id"]), "issue", f"Safety: {i['number']} closed by {g.user.get('name')}")
    return jsonify(inc_out(upd))


@bp.post("/incidents/<iid>/reopen")
@api(None)
def reopen_incident(iid):
    i, p = load_incident(iid, manage=True)
    if i["status"] != "closed":
        abort(409, "Only a closed incident is reopened")
    why = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:300] or abort(400, "Say why it is reopened")
    upd = t.update("incidents", iid, {"status": "investigating", "closed_at": None,
                                      "history": i.get("history", []) + [{"status": "reopened", "by": g.user.get("name"), "at": t.now(), "note": why}]})
    return jsonify(inc_out(upd))


# ============================== inspections ==============================
@bp.get("/settings/safety")
@api(None)
def get_safety_settings():
    if not (can("site") or can("settings")):
        abort(403, "Your role cannot view safety settings")
    return jsonify({"templates": templates(), "is_default": not ((g.company.get("safety") or {}).get("templates"))})


@bp.put("/settings/safety")
@api(None)
def put_safety_settings():
    if not (can("settings", True) or g.role in ("owner", "pm")):
        abort(403, "Only the Owner or a PM changes inspection checklists")
    d = request.get_json(force=True) or {}
    out, ids = [], set()
    for tp in (d.get("templates") or [])[:30]:
        name = (tp.get("name") or "").strip()[:100] or abort(400, "Each checklist needs a name")
        tid = (tp.get("id") or "").strip()[:30] or t.sid()
        if tid in ids:
            abort(400, "Two checklists have the same id")
        ids.add(tid)
        items, iids = [], set()
        for it in (tp.get("items") or [])[:60]:
            text = (it.get("text") or "").strip()[:300]
            if not text:
                continue
            iid = (it.get("id") or "").strip()[:30] or t.sid()
            if iid in iids:
                iid = t.sid()
            iids.add(iid)
            items.append({"id": iid, "text": text, "critical": bool(it.get("critical"))})
        if not items:
            abort(400, f"{name}: add at least one item")
        out.append({"id": tid, "name": name, "kind": tp.get("kind") if tp.get("kind") in ("safety", "quality", "handover") else "safety", "items": items})
    if not out:
        abort(400, "Keep at least one checklist")
    s = {**(g.company.get("safety") or {}), "templates": out}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"safety": s}})
    g.company["safety"] = s
    t.audit("update", "companies", g.company["_id"], note=f"Inspection checklists: {len(out)}")
    return get_safety_settings()


def insp_out(x):
    d = serialize(x)
    for r in d.get("results", []):
        for ph in r.get("photos", []):
            ph["url"] = f"/api/files/{ph['key']}"
    return d


@bp.get("/projects/<pid>/inspections")
@api(None)
def list_inspections(pid):
    p = site_access(pid)
    rows = [insp_out(x) for x in t.find("inspections", {"project_id": pid}, sort=[("date", -1), ("created_at", -1)], limit=200)]
    return jsonify({"inspections": rows, "templates": templates(), "can_write": can("site", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/inspections")
@api(None)
def add_inspection(pid):
    p = site_access(pid, write=True)
    d = request.get_json(force=True) or {}
    tp = next((x for x in templates() if x["id"] == d.get("template_id")), None) or abort(400, "Choose the checklist")
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "An inspection cannot be in the future")
    given = {r.get("item_id"): r for r in d.get("results") or []}
    results = []
    for it in tp["items"]:
        r = given.get(it["id"]) or abort(400, f"Answer every item: {it['text']}")
        if r.get("result") not in RESULTS:
            abort(400, "Each item passes, fails or does not apply (pass, fail, na)")
        note = (r.get("note") or "").strip()[:500] or None
        if r["result"] == "fail" and not note:
            abort(400, f"Say what is wrong: {it['text']}")
        results.append({"item_id": it["id"], "text": it["text"], "critical": it["critical"], "result": r["result"], "note": note,
                        "photos": files_of(r.get("photos"), 5), "snag_id": None, "snag_number": None})
    passed, failed = sum(r["result"] == "pass" for r in results), sum(r["result"] == "fail" for r in results)
    score = r1(100 * passed / (passed + failed)) if passed + failed else 100.0
    x = t.insert("inspections", {"number": t.next_number("INS", "INS"), "project_id": pid, "project_name": p["name"], "template_id": tp["id"],
                                 "template_name": tp["name"], "kind": tp.get("kind", "safety"), "date": day, "results": results, "passed": passed,
                                 "failed": failed, "score": score, "critical_failed": sum(r["result"] == "fail" and r["critical"] for r in results),
                                 "notes": (d.get("notes") or "").strip()[:1000] or None, "by": g.user.get("name"), "by_id": g.uid})
    # every failed item is tracked to close as a snag on the project
    changed = False
    for r in results:
        if r["result"] != "fail":
            continue
        s = t.insert("snags", {"project_id": pid, "project_name": p["name"], "number": t.next_number("SNG", "SNG"), "status": "open",
                               "title": f"{tp['name']}: {r['text']}"[:200], "location": None, "room": None,
                               "description": f"Failed in inspection {x['number']} on {day}: {r['note']}", "stage_id": None, "stage_name": None,
                               "priority": "high" if r["critical"] else "normal", "due": (date.fromisoformat(day) + timedelta(days=1 if r["critical"] else 3)).isoformat(),
                               "assignee_id": None, "assignee_name": None, "party_id": None, "party_name": None, "photos": r["photos"],
                               "fix_photos": [], "raised_by": g.user.get("name"), "raised_by_id": g.uid, "source": {"inspection_id": str(x["_id"]), "item_id": r["item_id"]},
                               "history": [{"status": "open", "by": g.user.get("name"), "at": t.now()}]})
        r.update(snag_id=str(s["_id"]), snag_number=s["number"])
        changed = True
    if changed:
        x = t.update("inspections", str(x["_id"]), {"results": results}, audit_it=False)
    ev.log(pid, "file", f"Inspection {x['number']} ({tp['name']}): {score:g}%" + (f", {failed} failed" if failed else ""))
    if x["critical_failed"]:
        notify.send("inspection_failed", ev.managers(p), f"{p['name']}: {x['critical_failed']} critical item(s) failed in {tp['name']} ({x['number']})",
                    f"/app/projects/{pid}?tab=safety", project_id=pid, level="warn")
    return jsonify(insp_out(x)), 201


# ============================== toolbox talks ==============================
@bp.get("/projects/<pid>/toolbox-talks")
@api(None)
def list_talks(pid):
    site_access(pid)
    return jsonify([serialize(x) for x in t.find("toolbox_talks", {"project_id": pid}, sort=[("date", -1)], limit=200)])


@bp.post("/projects/<pid>/toolbox-talks")
@api(None)
def add_talk(pid):
    p = site_access(pid, write=True)
    d = request.get_json(force=True) or {}
    topic = (d.get("topic") or "").strip()[:200] or abort(400, "Topic is required")
    known = {x["person"]: x for x in people(p)}
    att = []
    for per in dict.fromkeys(d.get("attendees") or []):
        x = known.get(per) or abort(400, "Attendees come from the project's attendance list")
        att.append({"person": per, "name": x["name"], "trade": x.get("trade")})
    if not att:
        abort(400, "Who attended?")
    x = t.insert("toolbox_talks", {"project_id": pid, "project_name": p["name"], "date": a_date(d.get("date") or sales.today(), "Date"),
                                   "topic": topic, "attendees": att, "count": len(att), "notes": (d.get("notes") or "").strip()[:1000] or None,
                                   "by": g.user.get("name"), "by_id": g.uid})
    return jsonify(serialize(x)), 201


# ============================== report ==============================
@bp.get("/reports/safety")
@api(None)
def safety_report():
    if not (can("reports") or can("site")):
        abort(403, "Your role cannot view the safety report")
    q = {}
    if g.role != "owner" and not can("reports"):
        q["project_id"] = {"$in": [str(p["_id"]) for p in t.find("projects", {"team.user_id": g.uid})]}
    if request.args.get("project_id"):
        q["project_id"] = request.args["project_id"]
    since = a_date(request.args.get("from"), "From", required=False) or (date.fromisoformat(sales.today()) - timedelta(days=365)).isoformat()
    incs = t.find("incidents", {**q, "date": {"$gte": since}})
    today = sales.today()
    by_kind, by_month = {}, {}
    for i in incs:
        by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
        by_month.setdefault(i["date"][:7], {"month": i["date"][:7], "total": 0, "serious": 0})
        by_month[i["date"][:7]]["total"] += 1
        by_month[i["date"][:7]]["serious"] += 1 if serious(i) else 0
    actions = [{**a, "incident": i["number"], "incident_id": str(i["_id"]), "project_name": i["project_name"]}
               for i in t.find("incidents", {**q, "status": {"$ne": "closed"}}) for a in i.get("actions", []) if not a.get("done_at")]
    projs = t.find("projects", {"status": {"$in": ["planning", "active", "on_hold"]}, **({"_id": {"$in": [oid(x) for x in q["project_id"]["$in"]]}} if isinstance(q.get("project_id"), dict) else {})})
    if isinstance(q.get("project_id"), str):
        projs = [p for p in projs if str(p["_id"]) == q["project_id"]]
    since_lti = []
    for p in projs:
        last = db.incidents.find_one({"company_id": g.cid, "project_id": str(p["_id"]), "kind": "lost_time"}, sort=[("date", -1)])
        start = last["date"] if last else (p.get("start") or (p["created_at"].date().isoformat() if p.get("created_at") else today))
        since_lti.append({"project_id": str(p["_id"]), "project": p["name"], "days": max(0, (date.fromisoformat(today) - date.fromisoformat(start[:10])).days),
                          "since": "last lost-time injury" if last else "project start"})
    insps = t.find("inspections", {**q, "date": {"$gte": since}})
    fails = {}
    for x in insps:
        for r in x["results"]:
            if r["result"] == "fail":
                k = (x["template_name"], r["text"])
                fails[k] = fails.get(k, 0) + 1
    return jsonify({"from": since, "incidents": len(incs), "serious": sum(1 for i in incs if serious(i)),
                    "lost_days": sum(i.get("lost_days") or 0 for i in incs), "open": sum(1 for i in incs if i["status"] != "closed"),
                    "by_kind": [{"kind": k, "label": INCIDENT_KINDS[k], "count": v} for k, v in sorted(by_kind.items(), key=lambda x: -x[1])],
                    "by_month": sorted(by_month.values(), key=lambda x: x["month"]),
                    "open_actions": len(actions), "overdue_actions": sorted([a for a in actions if a.get("due") and a["due"] < today], key=lambda a: a["due"]),
                    "days_without_lti": sorted(since_lti, key=lambda x: x["days"]),
                    "inspections": len(insps), "avg_score": r1(sum(x["score"] for x in insps) / len(insps)) if insps else None,
                    "top_fails": [{"checklist": k[0], "item": k[1], "count": v} for k, v in sorted(fails.items(), key=lambda x: -x[1])[:10]],
                    "talks": len(t.find("toolbox_talks", {**q, "date": {"$gte": since}}))})


def check_safety(now):
    """Corrective actions past their due date: the owner hears once a day."""
    today = now.date().isoformat()
    for i in db.incidents.find({"company_id": g.cid, "status": {"$ne": "closed"}, "actions": {"$elemMatch": {"done_at": None, "due": {"$lt": today}}}}):
        for a in i["actions"]:
            if not a.get("done_at") and a.get("due") and a["due"] < today:
                notify.send("safety_action", [a["owner_id"]], f"Safety action overdue since {a['due']} ({i['number']}, {i['project_name']}): {a['text']}",
                            f"/app/projects/{i['project_id']}?tab=safety", project_id=i["project_id"], key=f"safety-act:{i['_id']}:{a['id']}:{today}",
                            level="warn", skip_self=False)
