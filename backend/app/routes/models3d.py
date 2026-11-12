"""Phase K block 7 — 3D models in the browser (v4 §19 Phase 2).

A model file (GLB / glTF, OBJ, or IFC from Revit / ArchiCAD) per project, shown with Three.js (IFC through web-ifc) —
orbit, zoom, comments pinned on a point of the model (x, y, z plus the camera view), a comment becomes a task or a
change request. Versions: a new upload can replace an earlier model ("previous"), and the viewer shows before / after
side by side with the cameras linked. Shared models appear in the client portal, where the client can comment too.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal, can
from ..services import notify, project_events as ev, sales
from .projects import load, member

bp = Blueprint("models3d", __name__)
FORMATS = {"glb": "GLB", "gltf": "glTF", "obj": "OBJ", "ifc": "IFC"}


def access(pid, write=False):
    if not (can("documents") or can("projects") or can("site")):
        abort(403, "Your role cannot view models")
    p = load(pid)
    if write and not (can("documents", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change models on this project")
    return p


def out(m, client=False):
    d = serialize(m)
    d["url"] = f"/api/files/{m['file_key']}"
    d["comments"] = [{**c, "at": c["at"].isoformat() if hasattr(c.get("at"), "isoformat") else c.get("at")} for c in m.get("comments", [])
                     if not client or c.get("side") == "client" or c.get("shared")]
    d["open"] = sum(1 for c in m.get("comments", []) if c["status"] == "open")
    return d


def vec(v, label, n=3):
    if not isinstance(v, list) or len(v) != n or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < 1e7 for x in v):
        abort(400, f"{label}: {n} numbers")
    return [round(float(x), 4) for x in v]


@bp.get("/projects/<pid>/models")
@api(None)
def list_models(pid):
    access(pid)
    return jsonify([out(m) for m in t.find("models3d", {"project_id": pid}, sort=[("created_at", -1)])])


@bp.post("/projects/<pid>/models")
@api(None)
def add_model(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    f = db.files.find_one({"company_id": g.cid, "key": d.get("file_key")}) if d.get("file_key") else None
    f or abort(400, "Upload the model file first")
    ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
    ext in FORMATS or abort(400, "Model files: GLB, glTF, OBJ or IFC")
    prev = None
    if d.get("previous_id"):
        prev = db.models3d.find_one({"_id": oid(d["previous_id"]), "company_id": g.cid, "project_id": pid}) or abort(400, "Earlier model not found")
    m = t.insert("models3d", {"project_id": pid, "project_name": p["name"], "title": (d.get("title") or "").strip()[:120] or f["name"],
                              "room": (d.get("room") or "").strip()[:80] or None, "format": ext, "file_key": f["key"], "file_name": f["name"],
                              "size": f.get("size"), "version": (prev or {}).get("version", 0) + 1, "previous_id": prev and str(prev["_id"]),
                              "shared": bool(d.get("shared")), "comments": []})
    if prev:
        db.models3d.update_one({"_id": prev["_id"]}, {"$set": {"superseded_by": str(m["_id"])}})
    ev.log(pid, "file", f"3D model added: {m['title']} ({FORMATS[ext]}, v{m['version']})")
    return jsonify(out(m)), 201


def load_model(mid, write=False):
    m = t.get("models3d", mid)
    return m, access(m["project_id"], write)


@bp.put("/models/<mid>")
@api(None)
def edit_model(mid):
    m, p = load_model(mid, True)
    d = request.get_json(force=True) or {}
    ch = {}
    if "title" in d:
        ch["title"] = (d.get("title") or "").strip()[:120] or abort(400, "Title is required")
    if "room" in d:
        ch["room"] = (d.get("room") or "").strip()[:80] or None
    if "shared" in d:
        ch["shared"] = bool(d["shared"])
    return jsonify(out(t.update("models3d", mid, ch)))


@bp.delete("/models/<mid>")
@api(None)
def delete_model(mid):
    m, p = load_model(mid, True)
    if any(c.get("task_id") or c.get("co_id") for c in m.get("comments", [])):
        abort(409, "A comment on this model became a task or a change request; the model is kept")
    db.models3d.delete_one({"_id": m["_id"]})
    db.models3d.update_many({"company_id": g.cid, "superseded_by": mid}, {"$set": {"superseded_by": None}})
    return jsonify({"ok": True})


def add_comment(m, d, side, author):
    text = (d.get("text") or "").strip()[:1000] or abort(400, "Write the comment")
    c = {"id": t.sid(), "text": text, "point": vec(d.get("point"), "Point on the model"),
         "camera": vec(d.get("camera"), "Camera position") if d.get("camera") is not None else None,
         "side": side, "author": author, "at": t.now(), "status": "open", "task_id": None, "co_id": None, "shared": side == "client" or bool(d.get("shared"))}
    db.models3d.update_one({"_id": m["_id"]}, {"$push": {"comments": c}, "$set": {"updated_at": t.now()}})
    return c


@bp.post("/models/<mid>/comments")
@api(None)
def team_comment(mid):
    m, p = load_model(mid)
    if not (can("documents", True) or can("projects", True) or can("site", True)):
        abort(403, "Your role cannot comment")
    return jsonify(add_comment(m, request.get_json(force=True) or {}, "team", g.user["name"])), 201


def find_comment(m, cid_):
    return next((c for c in m.get("comments", []) if c["id"] == cid_), None) or abort(404, "Comment not found")


def set_comment(m, cid_, ch):
    db.models3d.update_one({"_id": m["_id"], "comments.id": cid_}, {"$set": {f"comments.$.{k}": v for k, v in ch.items()}})


@bp.post("/models/<mid>/comments/<cid_>/resolve")
@api(None)
def resolve(mid, cid_):
    m, p = load_model(mid, True)
    c = find_comment(m, cid_)
    set_comment(m, cid_, {"status": "open" if c["status"] == "resolved" else "resolved"})
    return jsonify(out(t.get("models3d", mid)))


@bp.post("/models/<mid>/comments/<cid_>/task")
@api(None)
def to_task(mid, cid_):
    from .projects import find_stage, require_edit, clean_task, save_stages
    m, p = load_model(mid, True)
    c = find_comment(m, cid_)
    if c.get("task_id"):
        abort(409, "This comment is already a task")
    d = request.get_json(force=True) or {}
    stage = find_stage(p, d.get("stage_id") or abort(400, "Choose the stage"))
    require_edit(p, stage)
    task = {"id": t.sid(), "status": "todo", "progress": 0, "depends_on": [], "links": [], "assignee_id": None, "assignee_name": None,
            "priority": "normal", "checklist": [], "files": [], "source": {"kind": "model", "model_id": mid, "comment_id": cid_}}
    task.update(clean_task({"title": d.get("title") or c["text"][:100], "start": d.get("start") or sales.today(),
                            "end": d.get("end") or d.get("start") or sales.today(), "notes": f"From a comment on the 3D model {m['title']}: {c['text']}"}, p))
    stage.setdefault("tasks", []).append(task)
    save_stages(str(p["_id"]), p)
    set_comment(m, cid_, {"task_id": task["id"], "task_title": task["title"], "status": "resolved"})
    return jsonify(out(t.get("models3d", mid))), 201


@bp.post("/models/<mid>/comments/<cid_>/change")
@api(None)
def to_change(mid, cid_):
    from .insights import make_request
    m, p = load_model(mid)
    if not (can("change_orders") or can("site", True) or can("documents", True)):
        abort(403, "Your role cannot ask for changes")
    c = find_comment(m, cid_)
    if c.get("co_id"):
        abort(409, "This comment is already a change request")
    co = make_request(p, {"title": c["text"][:150], "description": f"From a comment on the 3D model {m['title']} by {c['author']}: {c['text']}"},
                      c["author"] if c["side"] == "client" else g.user["name"], "client" if c["side"] == "client" else "site")
    set_comment(m, cid_, {"co_id": str(co["_id"]), "co_number": co["number"], "status": "resolved"})
    return jsonify(out(t.get("models3d", mid))), 201


# ---------------- portal ----------------
@bp.get("/portal/projects/<pid>/models")
@portal
def portal_models(pid):
    from .site_reports import portal_project
    portal_project(pid)
    return jsonify([out(m, client=True) for m in db.models3d.find({"company_id": g.cid, "project_id": pid, "shared": True}).sort("created_at", -1)])


@bp.post("/portal/models/<mid>/comments")
@portal
def portal_comment(mid):
    from .site_reports import portal_project
    m = db.models3d.find_one({"_id": oid(mid), "company_id": g.cid, "shared": True}) or abort(404, "model not found")
    p = portal_project(m["project_id"])
    c = add_comment(m, request.get_json(force=True) or {}, "client", g.user["name"])
    notify.send("model_comment", ev.managers(p), f"{g.user['name']} commented on the 3D model {m['title']} ({p['name']}): {c['text'][:140]}",
                f"/app/projects/{p['_id']}?tab=documents", project_id=str(p["_id"]), skip_self=False)
    return jsonify(c), 201
