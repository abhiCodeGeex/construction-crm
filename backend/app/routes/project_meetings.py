"""Projects in depth (Phase B+ block 4): meetings and minutes, project health, finish forecast, waiting on whom.

Meetings: plan (date, place, attendees, agenda) -> attendees are told; after the meeting write the minutes
(notes, decisions, action items with an owner, due date and stage) -> Publish: every action becomes a task on
the project, the minutes are emailed to every attendee with an email address and staff attendees are told."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, project_events as ev, project_health
from .lead_steps import when, fmt
from .projects import load, require_edit, find_stage, save_stages, d

bp = Blueprint("project_meetings", __name__)


def _meeting(_id, mid):
    m = db.project_meetings.find_one({"_id": oid(mid), "company_id": g.cid, "project_id": _id})
    return m or abort(404, "meeting not found")


def _clean(p, dat, existing=None):
    out = {}
    if "title" in dat or not existing:
        out["title"] = (dat.get("title") or "").strip()[:150] or abort(400, "Meeting title is required")
    if "at" in dat or not existing:
        if not dat.get("at"):
            abort(400, "Meeting date and time are required")
        out["at"] = when(dat["at"])  # the browser sends UTC, like site visits
    for k in ("place", "agenda", "notes"):
        if k in dat:
            out[k] = (dat.get(k) or "").strip()[:5000] or None
    if "staff" in dat:
        team = {m["user_id"]: m["name"] for m in p.get("team", []) if m.get("user_id")}
        bad = [u for u in dat["staff"] or [] if u not in team]
        if bad:
            abort(400, "Staff attendees must be on the project team")
        out["staff"] = [{"user_id": u, "name": team[u]} for u in dict.fromkeys(dat["staff"] or [])]
    if "contacts" in dat:
        rows = []
        for c in dict.fromkeys(dat["contacts"] or []):
            doc = db.contacts.find_one({"_id": oid(c), "company_id": g.cid}) or abort(400, "Contact not found")
            rows.append({"contact_id": c, "name": doc["name"], "email": doc.get("email")})
        out["contacts"] = rows
    if "decisions" in dat:
        out["decisions"] = [str(x).strip()[:500] for x in (dat["decisions"] or []) if str(x).strip()][:50]
    if "actions" in dat:
        acts = []
        for a in dat["actions"] or []:
            text = (a.get("text") or "").strip()
            if not text:
                continue
            owner = a.get("owner_id")
            if owner and not any(m.get("user_id") == owner for m in p.get("team", [])):
                abort(400, f"Action “{text[:40]}”: the owner must be on the project team")
            if a.get("stage_id"):
                find_stage(p, a["stage_id"])
            acts.append({"id": a.get("id") or t.sid(), "text": text[:300], "owner_id": owner or None,
                         "due": d(a.get("due"), "Action due date"), "stage_id": a.get("stage_id") or None,
                         "task_id": a.get("task_id")})
        out["actions"] = acts[:50]
    return out


@bp.get("/projects/<_id>/meetings")
@api("projects")
def list_meetings(_id):
    load(_id)
    return jsonify(serialize(list(db.project_meetings.find({"company_id": g.cid, "project_id": _id}).sort("at", -1))))


@bp.post("/projects/<_id>/meetings")
@api("projects")
def add_meeting(_id):
    p = load(_id)
    require_edit(p)
    doc = {"company_id": g.cid, "project_id": _id, "staff": [], "contacts": [], "decisions": [], "actions": [],
           "place": None, "agenda": None, "notes": None, "status": "planned", "created_by": g.uid,
           "created_by_name": g.user.get("name"), "created_at": t.now(), **_clean(p, request.get_json(force=True) or {})}
    doc["_id"] = db.project_meetings.insert_one(doc).inserted_id
    at_text = fmt(doc["at"])
    ev.log(_id, "meeting", f"Meeting planned: {doc['title']} on {at_text}", meeting_id=str(doc["_id"]))
    notify.send("meeting_scheduled", [s["user_id"] for s in doc["staff"]],
                f"{doc['title']} ({p['name']}) on {at_text}" + (f" at {doc['place']}" if doc["place"] else ""), ev.link(p),
                project_id=_id)
    return jsonify(serialize(doc)), 201


@bp.put("/projects/<_id>/meetings/<mid>")
@api("projects")
def update_meeting(_id, mid):
    p = load(_id)
    require_edit(p)
    m = _meeting(_id, mid)
    if m["status"] == "published":
        abort(409, "Published minutes cannot be changed. Add a follow-up meeting instead.")
    changes = _clean(p, request.get_json(force=True) or {}, m)
    if "at" in changes and changes["at"] != m["at"]:
        ev.log(_id, "meeting", f"Meeting moved: {m['title']} → {fmt(changes['at'])}", meeting_id=mid)
        notify.send("meeting_scheduled", [s["user_id"] for s in changes.get("staff", m["staff"])],
                    f"Moved: {m['title']} ({p['name']}) now on {fmt(changes['at'])}", ev.link(p),
                    project_id=_id)
    db.project_meetings.update_one({"_id": m["_id"]}, {"$set": {**changes, "updated_at": t.now()}})
    return jsonify(serialize(_meeting(_id, mid)))


@bp.delete("/projects/<_id>/meetings/<mid>")
@api("projects")
def delete_meeting(_id, mid):
    p = load(_id)
    require_edit(p)
    m = _meeting(_id, mid)
    if m["status"] == "published" and g.role != "owner":
        abort(403, "Only the Owner can delete published minutes")
    db.project_meetings.delete_one({"_id": m["_id"]})
    ev.log(_id, "meeting", f"Meeting deleted: {m['title']}", meeting_id=mid)
    return jsonify({"ok": True})


@bp.post("/projects/<_id>/meetings/<mid>/publish")
@api("projects")
def publish(_id, mid):
    """Turn each action into a task (in its stage, assigned to its owner, due on its date), email the minutes to
    every attendee with an email address, and tell staff attendees."""
    p = load(_id)
    require_edit(p)
    m = _meeting(_id, mid)
    if m["status"] == "published":
        abort(409, "These minutes are already published")
    if not (m.get("notes") or m.get("decisions") or m.get("actions")):
        abort(400, "Write the minutes first: notes, decisions or action items")
    missing = [a["text"][:40] for a in m["actions"] if not (a.get("stage_id") and a.get("due"))]
    if missing:
        abort(400, f"Each action needs a stage and a due date: {', '.join(missing)}")
    held = m["at"].strftime("%d %b %Y")
    for a in m["actions"]:
        stage = find_stage(p, a["stage_id"])
        start = min(a["due"], max(t.now().date().isoformat(), stage.get("start") or a["due"]))
        task = {"id": t.sid(), "title": a["text"][:150], "start": start, "end": a["due"], "status": "todo", "progress": 0,
                "depends_on": [], "links": [], "assignee_id": a["owner_id"], "priority": "normal", "checklist": [],
                "files": [], "notes": f"From the meeting “{m['title']}” on {held}", "meeting_id": mid,
                "assignee_name": next((x["name"] for x in p["team"] if x.get("user_id") == a["owner_id"]), None)}
        stage.setdefault("tasks", []).append(task)
        a["task_id"] = task["id"]
    if m["actions"]:
        save_stages(_id, p)
    lines = [f"Minutes — {m['title']}", f"Project: {p['name']}", f"Date: {fmt(m['at'])}"
             + (f" · {m['place']}" if m.get("place") else ""),
             "Attendees: " + ", ".join([s["name"] for s in m["staff"]] + [c["name"] for c in m["contacts"]])]
    if m.get("notes"):
        lines += ["", "Notes", m["notes"]]
    if m.get("decisions"):
        lines += ["", "Decisions"] + [f"• {x}" for x in m["decisions"]]
    if m.get("actions"):
        names = {x["user_id"]: x["name"] for x in p["team"] if x.get("user_id")}
        lines += ["", "Actions"] + [f"• {a['text']} — {names.get(a['owner_id'], 'unassigned')}, by {a['due']}" for a in m["actions"]]
    body = "\n".join(lines) + f"\n\n— {g.company['name']}"
    emails = {}
    for s in m["staff"]:
        u = db.users.find_one({"_id": oid(s["user_id"])}, {"email": 1})
        if u and u.get("email"):
            emails[u["email"]] = s["name"]
    for c in m["contacts"]:
        if c.get("email"):
            emails[c["email"]] = c["name"]
    sent = {addr: notify.deliver(g.company, addr, f"Minutes: {m['title']} — {p['name']}", body) for addr in emails}
    db.project_meetings.update_one({"_id": m["_id"]}, {"$set": {"status": "published", "published_at": t.now(),
                                                                "published_by": g.user.get("name"), "actions": m["actions"],
                                                                "emailed": sent}})
    ok = sum(1 for v in sent.values() if v == "sent")
    ev.log(_id, "meeting", f"Minutes published: {m['title']} — {len(m['actions'])} action(s) became tasks, "
           f"emailed to {ok} of {len(sent)} attendee(s)", meeting_id=mid)
    notify.send("meeting_minutes", [s["user_id"] for s in m["staff"]], f"Minutes of {m['title']} ({p['name']}) are published",
                ev.link(p), project_id=_id)
    return jsonify(serialize(_meeting(_id, mid)))


# ---------------- health, forecast, waiting on whom ----------------
@bp.get("/projects/<_id>/health")
@api("projects")
def project_health_view(_id):
    return jsonify(project_health.health(load(_id)))


@bp.get("/projects/<_id>/waiting")
@api("projects")
def project_waiting(_id):
    return jsonify(project_health.waiting(load(_id)))


@bp.get("/waiting")
@api("projects")
def all_waiting():
    """Everything held up across the projects I can see, optionally for one party (e.g. ?party=client)."""
    q = {"company_id": g.cid, "status": {"$in": ["planning", "active", "on_hold"]}}
    if g.role != "owner":
        q["team.user_id"] = g.uid
    party = request.args.get("party")
    rows = []
    for p in db.projects.find(q):
        for r in project_health.waiting(p)["rows"]:
            if not party or r["party"] == party:
                rows.append({**r, "project_id": str(p["_id"]), "project": p["name"]})
    rows.sort(key=lambda r: -r["days"])
    return jsonify(rows)

