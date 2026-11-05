"""Projects in depth (Phase B+): stage closing checklist and client sign-off, task checklists, comments with
@mentions and task files (block 2). Every action is written to the project timeline and the right people are told."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, project_events as ev
from ..services.defaults import SIGNOFF_METHODS
from .projects import load, require_edit, can_edit_stage, find_stage, find_task, save_stages, present, d

bp = Blueprint("project_work", __name__)

MAX_ITEMS = 30
MAX_COMMENT = 2000


def _text(dat, field="text", limit=200, label="Item"):
    v = (dat.get(field) or "").strip()
    if not v:
        abort(400, f"{label} text is required")
    return v[:limit]


def _item(items, iid):
    return next((c for c in items if c["id"] == iid), None) or abort(404, "checklist item not found")


def _open_stage(p, stage):
    gm = next((m for m in stage.get("milestones", []) if m.get("gate")), None)
    if gm and gm["status"] == "achieved":
        abort(409, f"{stage['name']} is closed. Reopen its '{gm['name']}' milestone to change it.")


# ---------------- stage closing checklist ----------------
@bp.post("/projects/<_id>/stages/<sid>/checklist")
@api("projects", write=False)
def add_stage_item(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    _open_stage(p, stage)
    text = _text(request.get_json(force=True) or {})
    items = stage.setdefault("checklist", [])
    if len(items) >= MAX_ITEMS:
        abort(400, f"A stage checklist has at most {MAX_ITEMS} items")
    if any(c["text"].lower() == text.lower() for c in items):
        abort(409, "That item is already on the checklist")
    items.append({"id": t.sid(), "text": text, "done": False, "done_by": None, "done_at": None})
    ev.log(_id, "checklist", f"{stage['name']}: checklist item added — {text}", stage_id=sid)
    return jsonify(present(save_stages(_id, p))), 201


@bp.put("/projects/<_id>/stages/<sid>/checklist/<iid>")
@api("projects", write=False)
def update_stage_item(_id, sid, iid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    _open_stage(p, stage)
    item = _item(stage.get("checklist", []), iid)
    dat = request.get_json(force=True) or {}
    if "text" in dat:
        item["text"] = _text(dat)
    if "done" in dat and bool(dat["done"]) != item["done"]:
        item.update(done=bool(dat["done"]), done_by=g.user.get("name") if dat["done"] else None,
                    done_at=t.now().isoformat() if dat["done"] else None)
        ev.log(_id, "checklist", f"{stage['name']}: {'ticked' if item['done'] else 'unticked'} “{item['text']}”", stage_id=sid)
    return jsonify(present(save_stages(_id, p)))


@bp.delete("/projects/<_id>/stages/<sid>/checklist/<iid>")
@api("projects", write=False)
def delete_stage_item(_id, sid, iid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    _open_stage(p, stage)
    item = _item(stage.get("checklist", []), iid)
    stage["checklist"] = [c for c in stage["checklist"] if c["id"] != iid]
    ev.log(_id, "checklist", f"{stage['name']}: checklist item removed — {item['text']}", stage_id=sid)
    return jsonify(present(save_stages(_id, p)))


# ---------------- client sign-off ----------------
@bp.post("/projects/<_id>/stages/<sid>/signoff")
@api("projects", write=False)
def record_signoff(_id, sid):
    """The client approved this stage: who, how, when. Recorded by staff (portal approval comes with the portal)."""
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    _open_stage(p, stage)
    dat = request.get_json(force=True) or {}
    name = (dat.get("name") or p.get("client_name") or "").strip()
    if not name:
        abort(400, "Who signed off? Type the client's name")
    if dat.get("method") not in SIGNOFF_METHODS:
        abort(400, f"How was it given? One of: {', '.join(SIGNOFF_METHODS)}")
    stage["signoff"] = {"name": name, "method": dat["method"], "date": d(dat.get("date"), "Sign-off date") or t.now().date().isoformat(),
                        "note": (dat.get("note") or "").strip() or None, "file_key": dat.get("file_key"),
                        "recorded_by": g.user.get("name"), "recorded_at": t.now().isoformat()}
    if dat.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": dat["file_key"]}):
        abort(400, "Upload the file first")
    ev.log(_id, "signoff", f"{stage['name']}: client sign-off by {name} ({dat['method']}, {stage['signoff']['date']})",
           stage_id=sid)
    saved = save_stages(_id, p)
    notify.send("signoff_recorded", ev.managers(saved), f"{name} signed off {stage['name']} on {p['name']}", ev.link(p),
                project_id=_id)
    return jsonify(present(saved)), 201


@bp.delete("/projects/<_id>/stages/<sid>/signoff")
@api("projects", write=False)
def remove_signoff(_id, sid):
    p = load(_id)
    stage = find_stage(p, sid)
    require_edit(p, stage)
    _open_stage(p, stage)
    if not stage.get("signoff"):
        abort(404, "No sign-off recorded")
    ev.log(_id, "signoff", f"{stage['name']}: client sign-off by {stage['signoff']['name']} removed", stage_id=sid)
    stage["signoff"] = None
    return jsonify(present(save_stages(_id, p)))


# ---------------- task checklist ----------------
def _can_work(p, stage, task):
    """Project editors (or design editors on design stages) and the task's assignee."""
    if not (can_edit_stage(p, stage) or task.get("assignee_id") == g.uid):
        abort(403, "Only project editors and the person the task is assigned to can do this")


@bp.post("/projects/<_id>/tasks/<tid>/checklist")
@api("projects", write=False)
def add_task_item(_id, tid):
    p = load(_id)
    stage, task = find_task(p, tid)
    _can_work(p, stage, task)
    text = _text(request.get_json(force=True) or {})
    items = task.setdefault("checklist", [])
    if len(items) >= MAX_ITEMS:
        abort(400, f"A task checklist has at most {MAX_ITEMS} items")
    items.append({"id": t.sid(), "text": text, "done": False, "done_by": None, "done_at": None})
    if task["status"] == "done":  # a new open item reopens the task
        task["status"], task["progress"] = "in_progress", 0
    ev.log(_id, "checklist", f"{task['title']}: checklist item added — {text}", task_id=tid)
    return jsonify(present(save_stages(_id, p))), 201


@bp.put("/projects/<_id>/tasks/<tid>/checklist/<iid>")
@api("projects", write=False)
def update_task_item(_id, tid, iid):
    p = load(_id)
    stage, task = find_task(p, tid)
    _can_work(p, stage, task)
    item = _item(task.get("checklist", []), iid)
    dat = request.get_json(force=True) or {}
    if "text" in dat:
        item["text"] = _text(dat)
    if "done" in dat and bool(dat["done"]) != item["done"]:
        item.update(done=bool(dat["done"]), done_by=g.user.get("name") if dat["done"] else None,
                    done_at=t.now().isoformat() if dat["done"] else None)
        if not item["done"] and task["status"] == "done":
            task["status"], task["progress"] = "in_progress", 0
        ev.log(_id, "checklist", f"{task['title']}: {'ticked' if item['done'] else 'unticked'} “{item['text']}”", task_id=tid)
    if task["status"] != "done" and task.get("checklist"):  # progress follows the ticks until the task is done
        task["progress"] = round(sum(1 for c in task["checklist"] if c["done"]) / len(task["checklist"]) * 99)
    return jsonify(present(save_stages(_id, p)))


@bp.delete("/projects/<_id>/tasks/<tid>/checklist/<iid>")
@api("projects", write=False)
def delete_task_item(_id, tid, iid):
    p = load(_id)
    stage, task = find_task(p, tid)
    _can_work(p, stage, task)
    item = _item(task.get("checklist", []), iid)
    task["checklist"] = [c for c in task["checklist"] if c["id"] != iid]
    ev.log(_id, "checklist", f"{task['title']}: checklist item removed — {item['text']}", task_id=tid)
    return jsonify(present(save_stages(_id, p)))


# ---------------- comments with @mentions ----------------
def _mentions(p, text):
    """Team staff whose name follows an @ in the text (the comment box inserts @Name for you)."""
    low = text.lower()
    return [m["user_id"] for m in p.get("team", []) if m.get("user_id") and f"@{m['name'].lower()}" in low]


@bp.get("/projects/<_id>/tasks/<tid>/comments")
@api("projects")
def list_comments(_id, tid):
    p = load(_id)
    find_task(p, tid)
    rows = db.project_comments.find({"company_id": g.cid, "project_id": _id, "task_id": tid}).sort("at", 1)
    return jsonify(serialize(list(rows)))


@bp.post("/projects/<_id>/tasks/<tid>/comments")
@api("projects", write=False)
def add_comment(_id, tid):
    """Any staff member on the project can comment (view access is enough)."""
    p = load(_id)
    stage, task = find_task(p, tid)
    text = _text(request.get_json(force=True) or {}, limit=MAX_COMMENT, label="Comment")
    mentioned = _mentions(p, text)
    doc = {"company_id": g.cid, "project_id": _id, "task_id": tid, "text": text, "mentions": mentioned,
           "by_id": g.uid, "by": g.user.get("name"), "at": t.now()}
    doc["_id"] = db.project_comments.insert_one(doc).inserted_id
    short = text if len(text) <= 120 else text[:117] + "…"
    ev.log(_id, "comment", f"{g.user.get('name')} on {task['title']}: {short}", task_id=tid)
    where = f"{task['title']} ({stage['name']}, {p['name']})"
    notify.send("mentioned", mentioned, f"{g.user.get('name')} mentioned you on {where}: {short}", ev.link(p), project_id=_id)
    if task.get("assignee_id") and task["assignee_id"] not in mentioned:
        notify.send("task_comment", [task["assignee_id"]], f"{g.user.get('name')} on {where}: {short}", ev.link(p),
                    project_id=_id)
    return jsonify(serialize(doc)), 201


@bp.delete("/projects/<_id>/comments/<cid>")
@api("projects", write=False)
def delete_comment(_id, cid):
    load(_id)
    c = db.project_comments.find_one({"_id": oid(cid), "company_id": g.cid, "project_id": _id}) or abort(404, "comment not found")
    if c["by_id"] != g.uid and g.role != "owner":
        abort(403, "Only the person who wrote it (or the Owner) can delete a comment")
    db.project_comments.delete_one({"_id": c["_id"]})
    ev.log(_id, "comment", f"Comment by {c['by']} deleted", task_id=c["task_id"])
    return jsonify({"ok": True})


# ---------------- task files and photos ----------------
@bp.post("/projects/<_id>/tasks/<tid>/files")
@api("projects", write=False)
def add_task_file(_id, tid):
    """Attach an uploaded file (POST /uploads first): drawings, site photos, delivery notes."""
    p = load(_id)
    stage, task = find_task(p, tid)
    _can_work(p, stage, task)
    dat = request.get_json(force=True) or {}
    up = db.files.find_one({"company_id": g.cid, "key": dat.get("key")}) or abort(400, "Upload the file first")
    if any(f["key"] == up["key"] for s in p["stages"] for tk in s.get("tasks", []) for f in tk.get("files", [])):
        abort(409, "This file is already attached")
    files = task.setdefault("files", [])
    if len(files) >= 50:
        abort(400, "A task has at most 50 files")
    files.append({"id": t.sid(), "key": up["key"], "name": up["name"], "size": up["size"],
                  "caption": (dat.get("caption") or "").strip()[:200] or None, "by_id": g.uid, "by": g.user.get("name"),
                  "at": t.now().isoformat()})
    ev.log(_id, "file", f"{task['title']}: file added — {up['name']}", task_id=tid)
    return jsonify(present(save_stages(_id, p))), 201


@bp.delete("/projects/<_id>/tasks/<tid>/files/<fid>")
@api("projects", write=False)
def delete_task_file(_id, tid, fid):
    p = load(_id)
    stage, task = find_task(p, tid)
    f = next((x for x in task.get("files", []) if x["id"] == fid), None) or abort(404, "file not found")
    if f["by_id"] != g.uid and not can_edit_stage(p, stage):
        abort(403, "Only the person who added it or a project editor can remove a file")
    task["files"] = [x for x in task["files"] if x["id"] != fid]
    ev.log(_id, "file", f"{task['title']}: file removed — {f['name']}", task_id=tid)
    saved = save_stages(_id, p)
    from .lead_steps import delete_stored
    delete_stored(f["key"])
    return jsonify(present(saved))

