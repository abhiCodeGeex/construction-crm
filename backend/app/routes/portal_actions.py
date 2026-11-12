"""Phase G block 1 — approvals in the client portal, and comments on documents.

A portal approval runs the same code as one recorded by staff (`signoff_stage`, `decide_change_order`, `choose_option`,
`set_drawing_status`, `ack_transmittal`); it records method "Portal", the person's typed name, contact, time, IP and
browser. A portal user acts only on what was sent to them (their project, their transmittal); anything else is 404.
Who: the project role on the team decides — *Client*: sign-off, change orders, selections, approving drawings sent for
approval. Consultants: comment on and return drawings sent to them. Everyone on the team: acknowledge a transmittal
sent to them, comment on documents sent to them. Never cost: portal responses carry prices only.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, portal
from ..services import notify, project_events as ev, sales
from ..services.defaults import DRAWING_STATUSES, TRANSMITTAL_PURPOSES
from .change_orders import decide_change_order
from .documents import set_drawing_status, ack_transmittal, access as doc_access
from .project_work import signoff_stage, _open_stage
from .projects import gate_missing, save_stages
from .proposals import visitor, MAX_SIGNATURE
from .selections import choose_option
from .site_reports import portal_project

bp = Blueprint("portal_actions", __name__)

SIGNOFF_MISSING = "Client sign-off not recorded"


def my_role(p):
    return next((m.get("project_role") for m in p.get("team", []) if m.get("contact_id") == g.contact_id), None)


def require_client(p):
    if my_role(p) != "Client":
        abort(403, "Only the client can do this")


def person(d):
    """Typed full name + 'I approve' tick: the portal's signature for everything except change orders."""
    name = (d.get("name") or "").strip()[:120] or abort(400, "Type your full name")
    if not d.get("agree"):
        abort(400, "Tick the box to confirm")
    return {"name": name, "method": "Portal", "date": sales.today(), "contact_id": g.contact_id,
            "note": (d.get("note") or "").strip()[:500] or None, **visitor()}


def project_of(collection, _id):
    doc = db[collection].find_one({"_id": oid(_id), "company_id": g.cid}) if _id and len(str(_id)) == 24 else None
    if not doc:
        abort(404, "not found")
    return doc, portal_project(doc["project_id"])  # 404 unless this person is on that project's team


def sent_to_me(doc):
    """The latest transmittal that sent this document to me: (transmittal, item) or (None, None)."""
    tr = db.transmittals.find_one({"company_id": g.cid, "to.contact_id": g.contact_id, "items.document_id": str(doc["_id"])},
                                  sort=[("created_at", -1)])
    item = tr and next(i for i in tr["items"] if i["document_id"] == str(doc["_id"]))
    return tr, item


# ---------------- what is waiting for me ----------------
@bp.get("/portal/projects/<pid>/actions")
@portal
def actions(pid):
    p = portal_project(pid)
    role = my_role(p)
    client = role == "Client"
    out = {"role": role, "signoffs": [], "change_orders": [], "selections": [], "documents": [], "transmittals": []}
    if client:
        for s in p.get("stages", []):
            gm = next((m for m in s.get("milestones", []) if m.get("gate")), None)
            if s.get("client_signoff_required") and not s.get("signoff") and gm and gm["status"] != "achieved":
                missing = gate_missing(p, s)
                if missing == [SIGNOFF_MISSING]:  # everything else is done: only the client's sign-off is missing
                    out["signoffs"].append({"stage_id": s["id"], "name": s["name"], "service": s.get("service")})
        for co in db.change_orders.find({"company_id": g.cid, "project_id": pid, "status": "sent", "reason": {"$ne": "our_error"}}):
            out["change_orders"].append({"id": str(co["_id"]), "number": co["number"], "title": co["title"], "description": co.get("description"),
                                         "stage_name": co["stage_name"], "time_days": co.get("time_days") or 0,
                                         "lines": [{"description": ln["description"], "qty": ln["qty"], "unit": ln.get("unit"), "price": ln["price"]}
                                                   for ln in co["lines"] if ln["price"]],
                                         "price": co["totals"]["price"], "tax": co["totals"]["tax"], "total": co["totals"]["total"],
                                         "files": [{"name": f["name"], "url": f"/api/files/{f['key']}"} for f in co.get("files", [])]})
        for s in db.selections.find({"company_id": g.cid, "project_id": pid, "status": {"$in": ["open", "options_sent"]}}):
            if s.get("options"):
                out["selections"].append({"id": str(s["_id"]), "item": s["item"], "room": s.get("room"), "due_date": s.get("due_date"),
                                          "allowance": s.get("allowance"),
                                          "options": [{"id": o["id"], "name": o["name"], "brand": o.get("brand"), "price": o["price"],
                                                       "lead_days": o.get("lead_days"),
                                                       "photo": f"/api/files/{o['file_key']}" if o.get("file_key") else None} for o in s["options"]]})
    for doc in db.documents.find({"company_id": g.cid, "project_id": pid}):
        tr, item = sent_to_me(doc)
        if not tr:
            continue
        current = item["rev"] == doc["current_rev"]
        comments = list(db.document_comments.find({"company_id": g.cid, "document_id": str(doc["_id"]), "contact_id": g.contact_id}).sort("created_at", 1))
        out["documents"].append({"id": str(doc["_id"]), "number": doc.get("number"), "name": doc["name"], "rev": item["rev"],
                                 "current_rev": doc["current_rev"], "superseded": not current, "purpose": tr["purpose"],
                                 "purpose_label": TRANSMITTAL_PURPOSES[tr["purpose"]], "status": DRAWING_STATUSES.get(doc.get("status") or "", None),
                                 "url": f"/api/files/{item['file_key']}", "transmittal": tr["number"],
                                 "can_approve": client and current and tr["purpose"] == "for_approval" and doc["kind"] == "drawing"
                                 and doc.get("status") not in ("approved", "for_construction"),
                                 "can_comment": current and tr["purpose"] in ("for_approval", "for_comment"),
                                 "comments": [{"text": c["text"], "author": c["author"], "side": c["side"], "status": c["status"],
                                               "at": c["created_at"], "reply": c.get("reply")} for c in comments]})
    for tr in db.transmittals.find({"company_id": g.cid, "project_id": pid, "to.contact_id": g.contact_id}).sort("created_at", -1):
        out["transmittals"].append({"id": str(tr["_id"]), "number": tr["number"], "purpose": TRANSMITTAL_PURPOSES[tr["purpose"]],
                                    "at": tr["created_at"], "items": [f"{i.get('number') or i['name']} {i['rev']}" for i in tr["items"]],
                                    "acknowledged": tr.get("acknowledged")})
    return jsonify(serialize(out))


# ---------------- approvals ----------------
@bp.post("/portal/projects/<pid>/stages/<sid>/signoff")
@portal
def portal_signoff(pid, sid):
    p = portal_project(pid)
    require_client(p)
    stage = next((s for s in p.get("stages", []) if s["id"] == sid), None) or abort(404, "stage not found")
    _open_stage(p, stage)
    if not stage.get("client_signoff_required"):
        abort(409, "This stage does not need your sign-off")
    if stage.get("signoff"):
        abort(409, "Already signed off")
    signoff_stage(p, stage, person(request.get_json(force=True) or {}))
    return jsonify({"ok": True}), 201


@bp.post("/portal/change_orders/<cid_>/approve")
@portal
def portal_co_approve(cid_):
    co, p = project_of("change_orders", cid_)
    require_client(p)
    if co["status"] != "sent" or co["reason"] == "our_error":
        abort(409, "This change order is not waiting for your approval")
    d = request.get_json(force=True) or {}
    approval = person(d)
    sig = d.get("signature") or ""
    if not sig.startswith("data:image/png;base64,") or len(sig) > MAX_SIGNATURE or len(sig) < 200:
        abort(400, "Sign in the box: a change order changes your contract")
    decide_change_order(co, p, {**approval, "signature": sig}, True)
    return jsonify({"ok": True})


@bp.post("/portal/change_orders/<cid_>/reject")
@portal
def portal_co_reject(cid_):
    co, p = project_of("change_orders", cid_)
    require_client(p)
    if co["status"] != "sent" or co["reason"] == "our_error":
        abort(409, "This change order is not waiting for your answer")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Tell us why")
    decide_change_order(co, p, {"name": g.user.get("name"), "method": "Portal", "contact_id": g.contact_id, **visitor()}, False, reason)
    return jsonify({"ok": True})


@bp.post("/portal/selections/<sid>/choose")
@portal
def portal_choose(sid):
    s, p = project_of("selections", sid)
    require_client(p)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "A choice is already recorded; ask the team to reopen it")
    d = request.get_json(force=True) or {}
    opt = next((o for o in s.get("options", []) if o["id"] == d.get("option_id")), None) or abort(400, "Choose one of the options")
    choose_option(s, p, opt, person(d))
    return jsonify({"ok": True})


@bp.post("/portal/selections/<sid>/reject")
@portal
def portal_reject_options(sid):
    """§7 "client approves or rejects each item in the portal": none of the options suits — the team is asked for others."""
    s, p = project_of("selections", sid)
    require_client(p)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "A choice is already recorded; ask the team to reopen it")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:500] or abort(400, "Tell the team what you would like instead")
    rej = {"by": g.user.get("name"), "contact_id": g.contact_id, "reason": reason, "at": t.now(), "options": [o["name"] for o in s.get("options", [])]}
    db.selections.update_one({"_id": s["_id"]}, {"$set": {"status": "open", "client_rejected": rej}, "$push": {"rejections": rej}})
    ev.log(str(p["_id"]), "file", f"Client asked for other options for {s['item']}: {reason}")
    notify.send("selection_chosen", ev.managers(p), f"{p['name']}: {g.user.get('name')} would like other options for {s['item']} — {reason}",
                f"/app/projects/{p['_id']}?tab=selections", project_id=str(p["_id"]), skip_self=False)
    return jsonify({"ok": True})


def my_document(did):
    doc, p = project_of("documents", did)
    tr, item = sent_to_me(doc)
    if not tr:
        abort(404, "not found")
    if item["rev"] != doc["current_rev"]:
        abort(409, f"{item['rev']} has been superseded by {doc['current_rev']}; you will receive the new revision")
    return doc, p, tr


@bp.post("/portal/documents/<did>/approve")
@portal
def portal_approve_drawing(did):
    doc, p, tr = my_document(did)
    require_client(p)
    if tr["purpose"] != "for_approval" or doc["kind"] != "drawing":
        abort(409, "This was sent for information or comment, not for approval")
    if doc.get("status") in ("approved", "for_construction"):
        abort(409, "Already approved")
    who = person(request.get_json(force=True) or {})
    set_drawing_status(doc, p, "approved", {"method": "Portal", "approved_by": who["name"], "ip": who["ip"]})
    return jsonify({"ok": True})


def add_comment(doc, p, text, side, file_key=None, author=None):
    if file_key and not db.files.find_one({"company_id": g.cid, "key": file_key}):
        abort(400, "Upload the file first")
    c = t.insert("document_comments", {"project_id": doc["project_id"], "document_id": str(doc["_id"]), "document_name": doc["name"],
                                       "number": doc.get("number"), "rev": doc["current_rev"], "side": side,
                                       "author": author or g.user.get("name"), "contact_id": getattr(g, "contact_id", None) if side != "team" else None,
                                       "user_id": g.uid if side == "team" else None, "text": text[:2000], "file_key": file_key,
                                       "status": "open", "reply": None})
    return c


@bp.post("/portal/documents/<did>/comments")
@portal
def portal_comment(did):
    doc, p, tr = my_document(did)
    if tr["purpose"] not in ("for_approval", "for_comment"):
        abort(409, "This was sent for information")
    d = request.get_json(force=True) or {}
    text = (d.get("text") or "").strip() or abort(400, "Write your comment")
    side = "client" if my_role(p) == "Client" else "consultant"
    c = add_comment(doc, p, text, side, d.get("file_key"))
    ev.log(doc["project_id"], "file", f"Comment on {doc.get('number') or doc['name']} {doc['current_rev']} from {g.user.get('name')}")
    notify.send("document_comment", ev.managers(p), f"{g.user.get('name')} on {doc.get('number') or doc['name']} {doc['current_rev']}: {text[:120]}",
                f"/app/projects/{p['_id']}?tab=documents", project_id=doc["project_id"])
    return jsonify(serialize(c)), 201


@bp.post("/portal/documents/<did>/return")
@portal
def portal_return(did):
    """Returned with comments: the drawing goes back to work in progress for a new revision."""
    doc, p, tr = my_document(did)
    if tr["purpose"] not in ("for_approval", "for_comment"):
        abort(409, "This was sent for information")
    text = ((request.get_json(force=True) or {}).get("comment") or "").strip() or abort(400, "Say what has to change")
    side = "client" if my_role(p) == "Client" else "consultant"
    add_comment(doc, p, text, side)
    if doc["kind"] == "drawing":
        set_drawing_status(doc, p, "wip", {"method": "Portal", "returned_by": g.user.get("name")})
    notify.send("document_comment", ev.managers(p), f"{g.user.get('name')} returned {doc.get('number') or doc['name']} {doc['current_rev']}: {text[:120]}",
                f"/app/projects/{p['_id']}?tab=documents", project_id=doc["project_id"], level="warn")
    return jsonify({"ok": True})


@bp.post("/portal/transmittals/<tid>/acknowledge")
@portal
def portal_ack(tid):
    tr, p = project_of("transmittals", tid)
    if not any(r["contact_id"] == g.contact_id for r in tr["to"]):
        abort(404, "not found")
    if tr.get("acknowledged"):
        abort(409, "Already acknowledged")
    who = person({**(request.get_json(force=True) or {}), "agree": True})
    ack_transmittal(tr, {"by": who["name"], "date": who["date"], "note": who["note"], "method": "Portal", "ip": who["ip"]})
    return jsonify({"ok": True})


# ---------------- staff side of document comments ----------------
@bp.get("/documents/<did>/comments")
@api(None)
def staff_comments(did):
    doc = t.get("documents", did)
    doc_access(doc["project_id"])
    return jsonify(serialize(t.find("document_comments", {"document_id": did}, sort=[("created_at", 1)])))


@bp.get("/projects/<pid>/document-comments")
@api(None)
def project_comments(pid):
    doc_access(pid)
    q = {"project_id": pid}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify(serialize(t.find("document_comments", q, sort=[("created_at", -1)], limit=300)))


@bp.post("/document_comments/<cid_>/reply")
@api(None)
def reply(cid_):
    c = t.get("document_comments", cid_)
    p = doc_access(c["project_id"], write=True)
    text = ((request.get_json(force=True) or {}).get("text") or "").strip() or abort(400, "Write the reply")
    upd = t.update("document_comments", cid_, {"reply": {"text": text[:2000], "by": g.user.get("name"), "at": t.now()}, "status": "answered"})
    contact = db.contacts.find_one({"_id": oid(c["contact_id"]), "company_id": g.cid}) if c.get("contact_id") else None
    if contact and contact.get("email"):
        notify.deliver(g.company, contact["email"], f"Reply on {c.get('number') or c['document_name']} — {p['name']}",
                       f"Your comment: {c['text']}\n\nOur reply: {text}\n\n— {g.user.get('name')}, {g.company['name']}")
    return jsonify(serialize(upd))


@bp.put("/document_comments/<cid_>")
@api(None)
def close_comment(cid_):
    c = t.get("document_comments", cid_)
    doc_access(c["project_id"], write=True)
    st = (request.get_json(force=True) or {}).get("status")
    if st not in ("open", "answered", "closed"):
        abort(400, "Status: open, answered or closed")
    return jsonify(serialize(t.update("document_comments", cid_, {"status": st})))


@bp.post("/document_comments/<cid_>/task")
@api(None)
def comment_to_task(cid_):
    """Turn a comment into a task on the document's stage (due in a week) — the B+2 pattern of comment -> work."""
    from datetime import date, timedelta
    c = t.get("document_comments", cid_)
    p = doc_access(c["project_id"], write=True)
    if not can("projects", True):
        abort(403, "Your role cannot add tasks")
    doc = t.get("documents", c["document_id"])
    stage = next((s for s in p.get("stages", []) if s["id"] == doc.get("stage_id")), None) or abort(409, "Give the document a stage first")
    _open_stage(p, stage)
    start = sales.today()
    task = {"id": t.sid(), "title": f"{c.get('number') or c['document_name']}: {c['text'][:120]}", "start": start,
            "end": (date.fromisoformat(start) + timedelta(days=7)).isoformat(), "status": "todo", "progress": 0, "depends_on": [], "links": [],
            "assignee_id": None, "assignee_name": None, "priority": "normal", "checklist": [], "files": [],
            "notes": f"From {c['author']}'s comment on {c['rev']}"}
    stage.setdefault("tasks", []).append(task)
    save_stages(c["project_id"], p)
    upd = t.update("document_comments", cid_, {"task_id": task["id"]})
    return jsonify(serialize(upd)), 201
