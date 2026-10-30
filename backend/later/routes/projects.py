"""Projects (section 4): Project -> Stages (milestones with budgets) -> Tasks; team; dashboard."""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import num
from ..db import db
from ..security import api
from ..services import budget as B
from ..services.subscription import check_project_limit

bp = Blueprint("projects", __name__)


def _build_stages(services, start=None):
    stages = []
    day = datetime.fromisoformat(start) if start else datetime.utcnow()
    for service in services:
        tpl = db.stage_templates.find_one({"company_id": g.cid, "service": service, "is_default": True}) \
            or db.stage_templates.find_one({"company_id": g.cid, "service": service})
        cursor = day
        for name in (tpl or {}).get("stages", []):
            end = cursor + timedelta(days=21)
            stages.append({
                "id": t.sid(), "name": name, "service": service, "status": "pending", "progress": 0,
                "start": cursor.date().isoformat(), "end": end.date().isoformat(), "budget": 0, "spent": 0,
                "alert_level": "green", "tasks": [], "depends_on": stages[-1]["id"] if stages and
                stages[-1]["service"] == service else None,
            })
            cursor = end
    return stages


def create_project(d):
    check_project_limit()
    services = [s for s in (d.get("services") or ["construction"]) if s in g.company.get("modules", [])] \
        or g.company.get("modules", [])[:1]
    doc = {
        "code": t.next_number("PRJ", "PRJ"), "name": d.get("name") or "Untitled project",
        "services": services, "client_id": d.get("client_id"), "address": d.get("address"),
        "geo": d.get("geo"), "area": num(d.get("area")), "area_unit": d.get("area_unit", "sqft"),
        "value": num(d.get("value")), "status": d.get("status", "active"), "start": d.get("start"),
        "branch": d.get("branch"), "project_type": d.get("project_type"), "lead_id": d.get("lead_id"),
        "pm_id": d.get("pm_id") or g.uid, "supervisor_id": d.get("supervisor_id"),
        "team": d.get("team", []), "rooms": d.get("rooms", []),
        "stages": _build_stages(services, d.get("start")),
    }
    if doc["client_id"]:
        c = t.get("contacts", doc["client_id"], required=False)
        doc["client_name"] = c["name"] if c else None
    return t.insert("projects", doc)


def _summary(p):
    stages = p.get("stages", [])
    progress = round(sum(s.get("progress", 0) for s in stages) / len(stages)) if stages else 0
    return {**t.out(p), "progress": progress,
            "budget_total": sum(s.get("budget", 0) or 0 for s in stages),
            "spent_total": sum(s.get("spent", 0) or 0 for s in stages)}


@bp.get("/projects")
@api("projects")
def list_projects():
    q = {}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    if request.args.get("q"):
        q["name"] = {"$regex": request.args["q"], "$options": "i"}
    if g.role == "site":
        q["$or"] = [{"supervisor_id": g.uid}, {"team.user_id": g.uid}, {"pm_id": g.uid}]
    return jsonify([_summary(p) for p in t.find("projects", q, sort=[("created_at", -1)])])


@bp.post("/projects")
@api("projects")
def new_project():
    return jsonify(t.out(create_project(request.get_json(force=True) or {}))), 201


@bp.get("/projects/<_id>")
@api("projects")
def get_project(_id):
    return jsonify(_summary(t.get("projects", _id)))


@bp.put("/projects/<_id>")
@api("projects")
def update_project(_id):
    d = request.get_json(force=True) or {}
    fields = ("name", "client_id", "address", "geo", "area", "area_unit", "value", "status", "start", "branch",
              "pm_id", "supervisor_id", "rooms", "project_type", "services")
    changes = {k: d[k] for k in fields if k in d}
    if "client_id" in changes and changes["client_id"]:
        c = t.get("contacts", changes["client_id"], required=False)
        changes["client_name"] = c["name"] if c else None
    if "services" in changes:
        p = t.get("projects", _id)
        added = [s for s in changes["services"] if s not in p.get("services", [])]
        if added:
            t.update("projects", _id, {}, raw={"$push": {"stages": {"$each": _build_stages(added)}}})
    return jsonify(_summary(t.update("projects", _id, changes)))


@bp.delete("/projects/<_id>")
@api("projects")
def delete_project(_id):
    if g.role != "owner":
        abort(403, "Only the owner can delete projects")
    t.delete("projects", _id)
    return jsonify({"ok": True})


# ---------------- stages / tasks ----------------
@bp.post("/projects/<_id>/stages")
@api("projects")
def add_stage(_id):
    d = request.get_json(force=True) or {}
    stage = {"id": t.sid(), "name": d.get("name", "New stage"), "service": d.get("service"), "status": "pending",
             "progress": 0, "start": d.get("start"), "end": d.get("end"), "budget": num(d.get("budget")),
             "spent": 0, "alert_level": "green", "tasks": [], "depends_on": d.get("depends_on")}
    t.update("projects", _id, {}, raw={"$push": {"stages": stage}})
    return jsonify(_summary(t.get("projects", _id)))


@bp.put("/projects/<_id>/stages/<stage_id>")
@api("projects")
def update_stage(_id, stage_id):
    d = request.get_json(force=True) or {}
    p = t.get("projects", _id)
    stage = B.find_stage(p, stage_id) or abort(404, "Stage not found")
    for k in ("name", "status", "start", "end", "depends_on", "service", "room"):
        if k in d:
            stage[k] = d[k]
    if "progress" in d:
        stage["progress"] = max(0, min(100, int(num(d["progress"]))))
        if stage["progress"] == 100:
            stage["status"] = "done"
        elif stage["progress"] > 0 and stage["status"] == "pending":
            stage["status"] = "in_progress"
    if "budget" in d and B.can_set_budget():
        stage["budget"] = num(d["budget"])
    t.update("projects", _id, {"stages": p["stages"]})
    if "budget" in d:
        B.recalc_stage(_id, stage_id)
    return jsonify(_summary(t.get("projects", _id)))


@bp.delete("/projects/<_id>/stages/<stage_id>")
@api("projects")
def delete_stage(_id, stage_id):
    p = t.get("projects", _id)
    t.update("projects", _id, {"stages": [s for s in p["stages"] if s["id"] != stage_id]})
    return jsonify(_summary(t.get("projects", _id)))


@bp.post("/projects/<_id>/stages/<stage_id>/tasks")
@api("projects", write=False)
def add_task(_id, stage_id):
    d = request.get_json(force=True) or {}
    task = {"id": t.sid(), "title": d.get("title", "Task"), "assignee_id": d.get("assignee_id"),
            "assignee_name": d.get("assignee_name"), "due": d.get("due"), "status": "open",
            "room": d.get("room"), "trade": d.get("trade"), "drawing_id": d.get("drawing_id"),
            "next_trade": d.get("next_trade"), "measurements": d.get("measurements")}
    if g.role not in ("owner", "pm", "site", "designer"):
        abort(403, "Your role cannot add tasks")
    db.projects.update_one({"_id": t.get("projects", _id)["_id"], "stages.id": stage_id},
                           {"$push": {"stages.$.tasks": task}})
    return jsonify(_summary(t.get("projects", _id)))


@bp.put("/projects/<_id>/stages/<stage_id>/tasks/<task_id>")
@api("projects", write=False)
def update_task(_id, stage_id, task_id):
    if g.role not in ("owner", "pm", "site", "designer"):
        abort(403, "Your role cannot change tasks")
    d = request.get_json(force=True) or {}
    p = t.get("projects", _id)
    stage = B.find_stage(p, stage_id) or abort(404)
    task = next((x for x in stage["tasks"] if x["id"] == task_id), None) or abort(404)
    was_done = task.get("status") == "done"
    for k in ("title", "assignee_id", "assignee_name", "due", "status", "room", "trade", "drawing_id",
              "next_trade", "measurements"):
        if k in d:
            task[k] = d[k]
    done = sum(1 for x in stage["tasks"] if x.get("status") == "done")
    stage["progress"] = round(done / len(stage["tasks"]) * 100) if stage["tasks"] else stage.get("progress", 0)
    if stage["progress"] == 100:
        stage["status"] = "done"
    elif stage["progress"] > 0:
        stage["status"] = "in_progress"
    t.update("projects", _id, {"stages": p["stages"]})
    if task.get("status") == "done" and not was_done:
        from .engage import trade_handoff
        trade_handoff(p, stage, task)
    return jsonify(_summary(t.get("projects", _id)))


@bp.delete("/projects/<_id>/stages/<stage_id>/tasks/<task_id>")
@api("projects")
def delete_task(_id, stage_id, task_id):
    p = t.get("projects", _id)
    stage = B.find_stage(p, stage_id) or abort(404)
    stage["tasks"] = [x for x in stage["tasks"] if x["id"] != task_id]
    t.update("projects", _id, {"stages": p["stages"]})
    return jsonify(_summary(t.get("projects", _id)))


# ---------------- team ----------------
@bp.post("/projects/<_id>/team")
@api("projects")
def add_member(_id):
    d = request.get_json(force=True) or {}
    member = {"id": t.sid(), "role": d.get("role"), "user_id": d.get("user_id"), "contact_id": d.get("contact_id"),
              "name": d.get("name")}
    if member["contact_id"] and not member["name"]:
        c = t.get("contacts", member["contact_id"], required=False)
        member["name"] = c["name"] if c else None
    if member["user_id"] and not member["name"]:
        u = t.get("users", member["user_id"], required=False)
        member["name"] = u["name"] if u else None
    t.update("projects", _id, {}, raw={"$push": {"team": member}})
    return jsonify(_summary(t.get("projects", _id)))


@bp.delete("/projects/<_id>/team/<member_id>")
@api("projects")
def remove_member(_id, member_id):
    p = t.get("projects", _id)
    t.update("projects", _id, {"team": [m for m in p.get("team", []) if m["id"] != member_id]})
    return jsonify(_summary(t.get("projects", _id)))


# ---------------- dashboard / variance ----------------
@bp.get("/projects/<_id>/dashboard")
@api("projects")
def project_dashboard(_id):
    p = t.get("projects", _id)
    today = datetime.utcnow().date().isoformat()
    upcoming = sorted([s for s in p.get("stages", []) if s.get("status") != "done" and s.get("end")],
                      key=lambda s: s["end"])[:5]
    data = {
        "project": _summary(p),
        "next_milestones": [{"id": s["id"], "name": s["name"], "end": s["end"], "late": s["end"] < today}
                            for s in upcoming],
        "open_snags": db.snags.count_documents({"company_id": g.cid, "project_id": _id, "status": {"$ne": "closed"}}),
        "open_change_orders": db.change_orders.count_documents(
            {"company_id": g.cid, "project_id": _id, "status": {"$in": ["draft", "pending_client"]}}),
        "pending_selections": db.selections.count_documents(
            {"company_id": g.cid, "project_id": _id, "status": "proposed"}),
        "pending_costs": db.costs.count_documents(
            {"company_id": g.cid, "project_id": _id, "status": "pending_approval"}),
        "alerts": [{"stage": s["name"], "level": s.get("alert_level")} for s in p.get("stages", [])
                   if s.get("alert_level") in ("yellow", "red")],
        "contract": t.out(B.contract_for(_id)) if B.contract_for(_id) else None,
    }
    if not g.hide_costs:
        data["financials"] = B.project_financials(p)
    return jsonify(data)


@bp.get("/projects/<_id>/variance")
@api("finance", write=False)
def project_variance(_id):
    return jsonify(B.variance(t.get("projects", _id)))


@bp.get("/projects/<_id>/timeline")
@api("projects")
def project_timeline(_id):
    """Everything that happened on the project: follow-ups, messages, approvals, audit trail."""
    events = []
    for a in db.audit_logs.find({"company_id": g.cid, "doc_id": _id}).sort("at", -1).limit(100):
        events.append({"at": a["at"], "type": "audit", "text": f"{a.get('user_name') or 'System'} {a['action']}d project"})
    for m in db.messages.find({"company_id": g.cid, "project_id": _id}).sort("created_at", -1).limit(100):
        events.append({"at": m["created_at"], "type": f"message:{m.get('channel')}",
                       "text": f"{m.get('from_name') or m.get('to_name') or ''}: {m.get('body', '')[:140]}"})
    for f in db.followups.find({"company_id": g.cid, "related.id": _id}):
        events.append({"at": f["created_at"], "type": "followup", "text": f"Follow-up: {f['title']} ({f['status']})"})
    for c in db.change_orders.find({"company_id": g.cid, "project_id": _id}):
        events.append({"at": c["created_at"], "type": "change_order",
                       "text": f"{c.get('number')} {c.get('title')} — {c.get('status')}"})
    events.sort(key=lambda e: e["at"], reverse=True)
    return jsonify(t.out(events))
