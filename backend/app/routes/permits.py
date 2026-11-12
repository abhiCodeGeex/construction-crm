"""Phase I block 4 — authority / planning approvals and mood boards (§6).

* Approvals register (§6 "authority / planning approvals: submission date, conditions, approval status"): each permit
  names the authority, its reference, when it was submitted, the fee, the documents sent, and moves
  preparing → submitted → query raised → approved / rejected. An approval carries its conditions (ticked when met) and
  how long it is valid. The worker tells the project's managers when a submission has had no answer for 30 days and
  when an approval runs out within 30 days. A pending permit shows as waiting on the authority.
* Mood boards (§6 "mood boards and 3D renders for interior projects"): boards of images per room, shared with the
  client when ready; the client likes or comments on each image in the portal.
Who: documents rw (Owner, PM, Designer) on projects they are on; others with documents read access see them.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, portal
from ..services import notify, project_events as ev, sales
from .lead_money import a_date
from .lead_steps import num
from .projects import load, member

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ["Planning permission", "Building permit", "Fire NOC", "Environmental clearance", "Structural stability",
                "Occupancy / completion certificate", "Society / landlord NOC", "Utility connection", "Other"]
PERMIT_STATUSES = {"preparing": "Preparing", "submitted": "Submitted", "query": "Query raised", "approved": "Approved", "rejected": "Rejected"}
PERMIT_FLOW = {"preparing": ["submitted"], "submitted": ["query", "approved", "rejected"], "query": ["submitted", "approved", "rejected"],
               "rejected": ["submitted"], "approved": []}


def access(pid, write=False):
    if not can("documents"):
        abort(403, "Your role cannot view approvals")
    p = load(pid)
    if write and not (can("documents", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change approvals on this project")
    return p


def files_of(keys):
    out = []
    for key in dict.fromkeys(keys or []):
        f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the file first")
        out.append({"key": key, "name": f["name"], "url": f"/api/files/{key}"})
    return out[:20]


# ============================== approvals register ==============================
def present(x):
    data = serialize(x)
    today = sales.today()
    data["expiring"] = x["status"] == "approved" and bool(x.get("valid_until")) and x["valid_until"] <= (date.fromisoformat(today) + timedelta(days=30)).isoformat()
    data["expired"] = x["status"] == "approved" and bool(x.get("valid_until")) and x["valid_until"] < today
    data["open_conditions"] = sum(1 for c in x.get("conditions", []) if not c.get("met"))
    return data


def clean(d, p, x=None):
    ch = {}
    if "type" in d or x is None:
        if d.get("type") not in PERMIT_TYPES:
            abort(400, f"Type: {', '.join(PERMIT_TYPES)}")
        ch["type"] = d["type"]
    if "title" in d:
        ch["title"] = (d.get("title") or "").strip()[:150] or None
    if "authority_id" in d:
        if d["authority_id"]:
            c = db.contacts.find_one({"_id": oid(d["authority_id"]), "company_id": g.cid}) or abort(400, "Authority not found")
            ch.update(authority_id=d["authority_id"], authority_name=c["name"])
        else:
            ch.update(authority_id=None, authority_name=None)
    if "authority" in d and not ch.get("authority_name"):
        ch["authority_name"] = (d.get("authority") or "").strip()[:120] or None
    for k, n in (("reference", 80), ("notes", 1000)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or None
    for k, label in (("submitted_on", "Submitted on"), ("valid_until", "Valid until"), ("expected_by", "Expected by")):
        if k in d:
            ch[k] = a_date(d[k], label, required=False)
    if "fee" in d:
        ch["fee"] = num(d.get("fee"), "Fee") or None
    if "stage_id" in d:
        st = next((s for s in p.get("stages", []) if s["id"] == d["stage_id"]), None) if d["stage_id"] else None
        if d["stage_id"] and not st:
            abort(400, "Stage not found")
        ch.update(stage_id=st and st["id"], stage_name=st and st["name"])
    if "documents" in d:
        ch["documents"] = files_of(d["documents"])
    return ch


@bp.get("/projects/<pid>/permits")
@api(None)
def list_permits(pid):
    p = access(pid)
    rows = [present(x) for x in t.find("permits", {"project_id": pid}, sort=[("created_at", 1)])]
    return jsonify({"permits": rows, "types": PERMIT_TYPES, "statuses": PERMIT_STATUSES,
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "can_write": can("documents", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/permits")
@api(None)
def add_permit(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    x = t.insert("permits", {"project_id": pid, "project_name": p["name"], "status": "preparing", "title": None, "authority_id": None,
                             "authority_name": None, "reference": None, "submitted_on": None, "expected_by": None, "valid_until": None,
                             "fee": None, "stage_id": None, "stage_name": None, "documents": [], "conditions": [], "notes": None,
                             "history": [{"status": "preparing", "by": g.user.get("name"), "at": t.now()}], **clean(d, p)})
    ev.log(pid, "file", f"Approval register: {x['type']}" + (f" ({x['authority_name']})" if x.get("authority_name") else ""))
    return jsonify(present(x)), 201


def load_permit(xid, write=True):
    x = t.get("permits", xid)
    return x, access(x["project_id"], write)


@bp.put("/permits/<xid>")
@api(None)
def edit_permit(xid):
    x, p = load_permit(xid)
    return jsonify(present(t.update("permits", xid, clean(request.get_json(force=True) or {}, p, x))))


@bp.post("/permits/<xid>/status")
@api(None)
def permit_status(xid):
    x, p = load_permit(xid)
    d = request.get_json(force=True) or {}
    st = d.get("status")
    if st not in PERMIT_FLOW.get(x["status"], []):
        abort(409, f"From {PERMIT_STATUSES[x['status']]} it can go to: {', '.join(PERMIT_STATUSES[s] for s in PERMIT_FLOW[x['status']]) or 'nothing'}")
    day = a_date(d.get("date") or sales.today(), "Date")
    note = (d.get("note") or "").strip()[:500] or None
    ch = {"status": st, "history": x.get("history", []) + [{"status": st, "date": day, "note": note, "by": g.user.get("name"), "at": t.now()}]}
    if st == "submitted":
        if not (x.get("reference") or d.get("reference")):
            abort(400, "Enter the submission's reference (application / file number)")
        ch.update(submitted_on=day, reference=(d.get("reference") or x.get("reference")))
    if st == "query":
        note or abort(400, "What did the authority ask?")
    if st == "rejected":
        note or abort(400, "Why was it rejected?")
    if st == "approved":
        ch.update(approved_on=day, valid_until=a_date(d.get("valid_until"), "Valid until", required=False) or x.get("valid_until"))
        conds = [{"id": t.sid(), "text": c.strip()[:300], "met": False, "met_on": None} for c in d.get("conditions") or [] if str(c).strip()]
        ch["conditions"] = x.get("conditions", []) + conds
    upd = t.update("permits", xid, ch)
    ev.log(x["project_id"], "file", f"{x['type']}: {PERMIT_STATUSES[st].lower()}" + (f" — {note}" if note else ""))
    if st in ("query", "approved", "rejected"):
        notify.send("drawing_approved", ev.managers(p), f"{p['name']}: {x['type']} {PERMIT_STATUSES[st].lower()}" + (f" — {note}" if note else ""),
                    f"/app/projects/{p['_id']}?tab=documents", project_id=x["project_id"])
    if st == "approved" and x.get("stage_id"):
        from .site_plus import offer_check
        if not db.permits.find_one({"company_id": g.cid, "project_id": x["project_id"], "stage_id": x["stage_id"], "status": {"$ne": "approved"}}, {"_id": 1}):
            offer_check(p, x["stage_id"], "approv", "all approvals received")
    return jsonify(present(upd))


@bp.post("/permits/<xid>/conditions")
@api(None)
def add_condition(xid):
    x, _ = load_permit(xid)
    text = ((request.get_json(force=True) or {}).get("text") or "").strip()[:300] or abort(400, "What is the condition?")
    return jsonify(present(t.update("permits", xid, {"conditions": x.get("conditions", []) + [{"id": t.sid(), "text": text, "met": False, "met_on": None}]})))


@bp.put("/permits/<xid>/conditions/<cid_>")
@api(None)
def set_condition(xid, cid_):
    x, _ = load_permit(xid)
    met = bool((request.get_json(force=True) or {}).get("met"))
    conds = x.get("conditions", [])
    c = next((c for c in conds if c["id"] == cid_), None) or abort(404, "condition not found")
    c.update(met=met, met_on=sales.today() if met else None, met_by=g.user.get("name") if met else None)
    return jsonify(present(t.update("permits", xid, {"conditions": conds})))


@bp.delete("/permits/<xid>")
@api(None)
def delete_permit(xid):
    x, _ = load_permit(xid)
    if x["status"] != "preparing":
        abort(409, "Only an approval still being prepared is removed")
    t.delete("permits", xid)
    return jsonify({"ok": True})


def check_permits(now):
    """Worker: submitted with no answer for 30 days, or approved and running out within 30 days -> the project's managers, once."""
    today = now.date()
    for x in db.permits.find({"company_id": g.cid, "status": {"$in": ["submitted", "approved"]}}):
        p = db.projects.find_one({"_id": oid(x["project_id"])})
        if not p or p.get("status") not in ("planning", "active", "on_hold"):
            continue
        link = f"/app/projects/{p['_id']}?tab=documents"
        if x["status"] == "submitted" and x.get("submitted_on") and (today - date.fromisoformat(x["submitted_on"])).days >= 30:
            notify.send("transmittal_waiting", ev.managers(p), f"{p['name']}: {x['type']} submitted {x['submitted_on']} — no answer from "
                        f"{x.get('authority_name') or 'the authority'} yet; follow it up", link, project_id=x["project_id"],
                        key=f"permit-wait:{x['_id']}:{x['submitted_on']}", level="warn")
        if x["status"] == "approved" and x.get("valid_until") and date.fromisoformat(x["valid_until"]) - today <= timedelta(days=30):
            notify.send("transmittal_waiting", ev.managers(p), f"{p['name']}: {x['type']} is valid until {x['valid_until']} — renew it",
                        link, project_id=x["project_id"], key=f"permit-exp:{x['_id']}:{x['valid_until']}", level="warn")


# ============================== mood boards ==============================
def board_view(b, portal_view=False):
    data = serialize(b)
    for it in data.get("items", []):
        it["url"] = f"/api/files/{it['key']}" if it.get("key") else it.get("image_url")
        if portal_view:
            mine = [r for r in it.get("reactions", []) if r.get("contact_id") == g.contact_id]
            it["liked"] = any(r.get("like") for r in mine)
            it["comments"] = [r for r in it.get("reactions", []) if r.get("comment")]
            it.pop("reactions", None)
    return data


def clean_items(rows, old=None):
    keep = {i["id"]: i for i in (old or {}).get("items", [])}
    out = []
    for r in (rows or [])[:60]:
        it = {"id": r.get("id") or t.sid(), "note": (r.get("note") or "").strip()[:200] or None,
              "reactions": keep.get(r.get("id"), {}).get("reactions", [])}
        if r.get("key"):
            db.files.find_one({"company_id": g.cid, "key": r["key"]}) or abort(400, "Upload the image first")
            it["key"] = r["key"]
        elif str(r.get("image_url") or "").startswith(("http://", "https://")):
            it["image_url"] = r["image_url"][:500]
        else:
            abort(400, "Each item is an uploaded image or an image link")
        out.append(it)
    return out


@bp.get("/projects/<pid>/boards")
@api(None)
def list_boards(pid):
    p = access(pid)
    return jsonify({"boards": [board_view(b) for b in t.find("mood_boards", {"project_id": pid}, sort=[("created_at", 1)])],
                    "can_write": can("documents", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/boards")
@api(None)
def add_board(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    b = t.insert("mood_boards", {"project_id": pid, "project_name": p["name"], "title": (d.get("title") or "").strip()[:120] or abort(400, "Name the board"),
                                 "room": (d.get("room") or "").strip()[:80] or None, "items": clean_items(d.get("items")), "shared": bool(d.get("shared")),
                                 "by": g.user.get("name")})
    return jsonify(board_view(b)), 201


@bp.put("/boards/<bid>")
@api(None)
def edit_board(bid):
    b = t.get("mood_boards", bid)
    access(b["project_id"], write=True)
    d = request.get_json(force=True) or {}
    ch = {}
    if "title" in d:
        ch["title"] = (d.get("title") or "").strip()[:120] or abort(400, "Name the board")
    if "room" in d:
        ch["room"] = (d.get("room") or "").strip()[:80] or None
    if "items" in d:
        ch["items"] = clean_items(d["items"], b)
    if "shared" in d:
        ch["shared"] = bool(d["shared"])
        if ch["shared"] and not b.get("shared"):
            ev.log(b["project_id"], "file", f"Mood board “{b['title']}” shared with the client")
    return jsonify(board_view(t.update("mood_boards", bid, ch)))


@bp.delete("/boards/<bid>")
@api(None)
def delete_board(bid):
    b = t.get("mood_boards", bid)
    access(b["project_id"], write=True)
    t.delete("mood_boards", bid)
    return jsonify({"ok": True})


@bp.get("/portal/projects/<pid>/boards")
@portal
def portal_boards(pid):
    from .site_reports import portal_project, is_client
    p = portal_project(pid)
    if not is_client(p):
        return jsonify([])
    return jsonify([board_view(b, True) for b in db.mood_boards.find({"company_id": g.cid, "project_id": pid, "shared": True}).sort("created_at", 1)])


@bp.post("/portal/boards/<bid>/react")
@portal
def portal_react(bid):
    """The client likes an image or comments on it; the board's designer and the PM are told of a comment."""
    from .site_reports import portal_project, is_client
    b = db.mood_boards.find_one({"_id": oid(bid), "company_id": g.cid, "shared": True}) or abort(404, "board not found")
    p = portal_project(b["project_id"])
    if not is_client(p):
        abort(404, "board not found")
    d = request.get_json(force=True) or {}
    it = next((i for i in b["items"] if i["id"] == d.get("item_id")), None) or abort(404, "image not found")
    comment = (d.get("comment") or "").strip()[:500] or None
    reactions = [r for r in it.get("reactions", []) if not (r.get("contact_id") == g.contact_id and not r.get("comment") and "like" in d)]
    if "like" in d:
        reactions.append({"contact_id": g.contact_id, "name": g.user.get("name"), "like": bool(d["like"]), "at": t.now()})
    if comment:
        reactions.append({"contact_id": g.contact_id, "name": g.user.get("name"), "comment": comment, "at": t.now()})
    it["reactions"] = reactions
    db.mood_boards.update_one({"_id": b["_id"]}, {"$set": {"items": b["items"]}})
    if comment:
        notify.send("document_comment", ev.managers(p), f"{p['name']}: {g.user.get('name')} on the mood board “{b['title']}”: {comment[:120]}",
                    f"/app/projects/{p['_id']}?tab=documents", project_id=b["project_id"])
    return jsonify(board_view(db.mood_boards.find_one({"_id": b["_id"]}), True))
