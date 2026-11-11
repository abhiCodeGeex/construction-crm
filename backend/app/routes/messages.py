"""Phase G block 3 — message threads between each portal user and the team, and the staff Inbox.

* One private thread per project per portal contact: a client never sees a subcontractor's thread.
* A portal message tells the project's managers and the staff who already wrote in that thread; a staff reply reaches
  the portal user by email (and by WhatsApp when they opted in — block 4).
* Staff with the `messages` area read and answer the threads of projects they are on (Owner: every project).
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, portal
from ..services import notify, project_events as ev
from .projects import load, member
from .site_reports import portal_project

bp = Blueprint("messages", __name__)


def clean(d):
    text = (d.get("text") or "").strip()[:4000]
    files = []
    for key in dict.fromkeys(d.get("files") or []):
        f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the file first")
        files.append({"key": f["key"], "name": f["name"], "size": f["size"]})
    if not text and not files:
        abort(400, "Write a message")
    return text, files[:10]


def out(m):
    data = serialize(m)
    for f in data.get("files", []):
        f["url"] = f"/api/files/{f['key']}"
    return data


def thread_q(pid, contact_id):
    return {"company_id": g.cid, "project_id": pid, "contact_id": contact_id}


# ---------------- portal ----------------
@bp.get("/portal/projects/<pid>/messages")
@portal
def portal_thread(pid):
    portal_project(pid)
    q = thread_q(pid, g.contact_id)
    rows = [out(m) for m in db.messages.find({**q, "channel": "portal"}).sort("created_at", 1)]
    db.messages.update_many({**q, "side": "team", "read_by_contact": False}, {"$set": {"read_by_contact": True}})
    return jsonify(rows)


@bp.post("/portal/projects/<pid>/messages")
@portal
def portal_post(pid):
    p = portal_project(pid)
    text, files = clean(request.get_json(force=True) or {})
    m = t.insert("messages", {"project_id": pid, "project_name": p["name"], "contact_id": g.contact_id, "contact_name": g.user.get("name"),
                              "channel": "portal", "side": "contact", "author": g.user.get("name"), "user_id": None, "text": text,
                              "files": files, "read_by_team": False, "read_by_contact": True})
    writers = [x["user_id"] for x in db.messages.find({**thread_q(pid, g.contact_id), "side": "team"}, {"user_id": 1}) if x.get("user_id")]
    notify.send("portal_message", list(dict.fromkeys(ev.managers(p) + writers)), f"{g.user.get('name')} ({p['name']}): {text[:140]}",
                f"/app/inbox?project={pid}&contact={g.contact_id}", project_id=pid, skip_self=False)
    return jsonify(out(m)), 201


# ---------------- staff ----------------
def staff_project(pid, write=False):
    if not can("messages", write):
        abort(403, "Your role cannot use messages")
    return load(pid)


def portal_contacts(p):
    ids = [m["contact_id"] for m in p.get("team", []) if m.get("contact_id")]
    users = {u["contact_id"]: u for u in db.users.find({"company_id": g.cid, "kind": "external", "contact_id": {"$in": ids},
                                                         "active": {"$ne": False}}, {"contact_id": 1, "name": 1, "email": 1})}
    return [{"contact_id": m["contact_id"], "name": m["name"], "role": m.get("project_role"), "portal": m["contact_id"] in users}
            for m in p.get("team", []) if m.get("contact_id")]


def summary(pid, contact):
    q = {**thread_q(pid, contact["contact_id"]), "channel": "portal"}
    last = db.messages.find_one(q, sort=[("created_at", -1)])
    return {**contact, "unread": db.messages.count_documents({**q, "side": "contact", "read_by_team": False}),
            "last": last and {"text": last["text"][:160], "author": last["author"], "at": last["created_at"], "side": last["side"]}}


@bp.get("/projects/<pid>/threads")
@api(None)
def threads(pid):
    p = staff_project(pid)
    return jsonify([summary(pid, c) for c in portal_contacts(p)])


@bp.get("/projects/<pid>/threads/<contact_id>")
@api(None)
def thread(pid, contact_id):
    p = staff_project(pid)
    if contact_id not in [c["contact_id"] for c in portal_contacts(p)]:
        abort(404, "not on this project")
    q = {**thread_q(pid, contact_id), "channel": "portal"}
    rows = [out(m) for m in db.messages.find(q).sort("created_at", 1)]
    db.messages.update_many({**q, "side": "contact", "read_by_team": False}, {"$set": {"read_by_team": True}})
    return jsonify(rows)


@bp.post("/projects/<pid>/threads/<contact_id>")
@api(None)
def reply(pid, contact_id):
    p = staff_project(pid, write=True)
    if g.role != "owner" and not member(p):
        abort(403, "Only people on the project answer its messages")
    contact = next((c for c in portal_contacts(p) if c["contact_id"] == contact_id), None) or abort(404, "not on this project")
    text, files = clean(request.get_json(force=True) or {})
    m = t.insert("messages", {"project_id": pid, "project_name": p["name"], "contact_id": contact_id, "contact_name": contact["name"],
                              "channel": "portal", "side": "team", "author": g.user.get("name"), "user_id": g.uid, "text": text,
                              "files": files, "read_by_team": True, "read_by_contact": False})
    db.messages.update_many({**thread_q(pid, contact_id), "side": "contact", "read_by_team": False}, {"$set": {"read_by_team": True}})
    c = db.contacts.find_one({"_id": oid(contact_id), "company_id": g.cid})
    result = notify.deliver(g.company, (c or {}).get("email"), f"Message from {g.company['name']} — {p['name']}",
                            f"{text}\n\n— {g.user.get('name')}\nReply in your portal.")
    try:  # block 4: also by WhatsApp when the contact opted in
        from ..services import messaging
        wa = messaging.notify_contact(c or {}, f"{g.company['name']}: {text[:900]}")
    except ImportError:
        wa = None
    m = t.update("messages", str(m["_id"]), {"emailed": result, "whatsapp": wa})
    return jsonify(out(m)), 201


@bp.get("/inbox")
@api("messages", write=False)
def inbox():
    """Every portal thread of the projects you are on, unread first."""
    q = {"company_id": g.cid, "status": {"$ne": "cancelled"}}
    if g.role != "owner":
        q["team.user_id"] = g.uid
    rows = []
    for p in db.projects.find(q, {"name": 1, "code": 1, "team": 1}):
        for c in portal_contacts(p):
            s = summary(str(p["_id"]), c)
            if s["last"]:
                rows.append({**s, "project_id": str(p["_id"]), "project": f"{p.get('code') or ''} {p['name']}".strip()})
    rows.sort(key=lambda r: (-r["unread"], -(r["last"]["at"].timestamp())))
    return jsonify(serialize({"threads": rows, "unread": sum(r["unread"] for r in rows)}))
