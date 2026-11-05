"""Company users: internal staff (counted against the plan) and external portal users (free)."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid
from ..security import api, hash_password, INTERNAL_ROLES, EXTERNAL_ROLES
from ..services.subscription import check_user_limit, limits, usage

bp = Blueprint("users", __name__)


def open_work(uid):
    """Work that would be orphaned if this user stopped logging in."""
    tasks = [(p, tk) for p in db.projects.find({"company_id": g.cid, "stages.tasks.assignee_id": uid})
             for s in p.get("stages", []) for tk in s.get("tasks", []) if tk.get("assignee_id") == uid and tk.get("status") != "done"]
    return {"leads": db.leads.count_documents({"company_id": g.cid, "owner_id": uid, "status": {"$in": ["open", "on_hold"]}}),
            "followups": db.followups.count_documents({"company_id": g.cid, "owner_id": uid, "status": "open"}),
            "tasks": len(tasks),
            "visits": db.lead_visits.count_documents({"company_id": g.cid, "staff.id": uid,
                                                      "status": {"$in": ["scheduled", "confirmed"]}})}


def hand_over(uid, to):
    """Open leads and follow-ups move to `to`; open tasks move where `to` is on the project team, else unassigned;
    on upcoming visits `to` takes the user's place."""
    db.leads.update_many({"company_id": g.cid, "owner_id": uid, "status": {"$in": ["open", "on_hold"]}},
                         {"$set": {"owner_id": str(to["_id"]), "owner_name": to["name"]}})
    db.followups.update_many({"company_id": g.cid, "owner_id": uid, "status": "open"},
                             {"$set": {"owner_id": str(to["_id"]), "owner_name": to["name"]}})
    for p in db.projects.find({"company_id": g.cid, "stages.tasks.assignee_id": uid}):
        on_team = any(m.get("user_id") == str(to["_id"]) for m in p.get("team", []))
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                if tk.get("assignee_id") == uid and tk.get("status") != "done":
                    tk["assignee_id"], tk["assignee_name"] = (str(to["_id"]), to["name"]) if on_team else (None, None)
        db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": p["stages"]}})
    for v in db.lead_visits.find({"company_id": g.cid, "staff.id": uid, "status": {"$in": ["scheduled", "confirmed"]}}):
        staff = [s for s in v["staff"] if s["id"] != uid]
        if not any(s["id"] == str(to["_id"]) for s in staff):
            staff.append({"id": str(to["_id"]), "name": to["name"]})
        db.lead_visits.update_one({"_id": v["_id"]}, {"$set": {"staff": staff}})


@bp.get("/users")
@api("users", write=False)
def list_users():
    q = {}
    if request.args.get("kind"):
        q["kind"] = request.args["kind"]
    return jsonify([t.out(u) for u in t.find("users", q, sort=[("kind", -1), ("name", 1)])])


@bp.post("/users")
@api("users")
def create_user():
    d = request.get_json(force=True) or {}
    name, email, role = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("role")
    if not name or not email:
        abort(400, "Name and email are required")
    if role not in INTERNAL_ROLES + EXTERNAL_ROLES:
        abort(400, "Invalid role")
    if role == "owner" and g.role != "owner":
        abort(403, "Only an owner can create another owner")
    if len(d.get("password") or "") < 6:
        abort(400, "Password must be at least 6 characters")
    if db.users.find_one({"email": email}):
        abort(409, "Email already in use")
    external = role in EXTERNAL_ROLES
    if not external and not d.get("whatsapp_only"):
        check_user_limit()
    doc = {"name": name, "email": email, "phone": d.get("phone"), "role": role,
           "kind": "external" if external else "staff", "password": hash_password(d["password"]), "active": True,
           "whatsapp_only": bool(d.get("whatsapp_only")) and role == "site"}
    if external:
        # every portal user is linked to a contact record (client, vendor, subcontractor, consultant)
        if d.get("contact_id"):
            t.get("contacts", d["contact_id"])
            if db.users.find_one({"company_id": g.cid, "contact_id": d["contact_id"]}):
                abort(409, "This contact already has a portal login")
            doc["contact_id"] = d["contact_id"]
        else:
            types = {"client": "client", "vendor": "supplier", "subcontractor": "subcontractor",
                     "consultant": "consultant"}[role]
            contact = t.insert("contacts", {"name": d.get("org") or name, "kind": "company", "email": email,
                                            "phone": d.get("phone"), "types": [types], "compliance": []})
            doc["contact_id"] = str(contact["_id"])
    return jsonify(t.out(t.insert("users", doc))), 201


@bp.put("/users/<_id>")
@api("users")
def update_user(_id):
    d = request.get_json(force=True) or {}
    user = t.get("users", _id)
    changes = {k: d[k] for k in ("name", "phone") if k in d}
    handover = None
    if "role" in d and d["role"] != user["role"]:
        allowed = INTERNAL_ROLES if user["kind"] == "staff" else EXTERNAL_ROLES
        if d["role"] not in allowed:
            abort(400, "Cannot switch between staff and portal roles")
        if "owner" in (d["role"], user["role"]) and g.role != "owner":
            abort(403, "Only an owner can grant or remove the owner role")
        if user["role"] == "owner" and _id == g.uid:
            abort(409, "You cannot remove your own owner role")
        changes["role"] = d["role"]
    if "active" in d:
        if _id == g.uid and not d["active"]:
            abort(409, "You cannot deactivate yourself")
        if d["active"] and user.get("active") is False and user["kind"] == "staff" and not user.get("whatsapp_only"):
            check_user_limit()
        changes["active"] = bool(d["active"])
        if not d["active"] and user.get("active") is not False and user["kind"] == "staff":
            work = open_work(_id)
            if any(work.values()):
                if not d.get("handover_to"):
                    abort(409, f"{user['name']} still has {work['leads']} open lead(s), {work['followups']} open "
                               f"follow-up(s), {work['tasks']} open task(s) and {work['visits']} upcoming visit(s). "
                               "Choose who takes them over.")
                if d["handover_to"] == _id:
                    abort(400, "Hand the work over to someone else")
                to = db.users.find_one({"_id": oid(d["handover_to"]), "company_id": g.cid, "kind": "staff",
                                        "active": {"$ne": False}}) or abort(400, "Hand over to an active staff user")
                handover = (work, to)
    if d.get("password"):
        if len(d["password"]) < 6:
            abort(400, "Password must be at least 6 characters")
        changes["password"] = hash_password(d["password"])
    if user["role"] == "owner" and (changes.get("active") is False or changes.get("role", "owner") != "owner"):
        if db.users.count_documents({"company_id": g.cid, "role": "owner", "active": {"$ne": False}}) <= 1:
            abort(409, "A company needs at least one active owner")
    updated = t.update("users", _id, changes)
    if changes.get("active") is False and (g.company.get("sales") or {}).get("manager_id") == _id:
        db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"sales.manager_id": None}})
        t.audit("update", "sales_settings", g.company["_id"], note=f"Sales manager {user['name']} deactivated; owners take over")
    if handover:
        hand_over(_id, handover[1])
        t.audit("update", "users", _id, note=f"Open work handed over to {handover[1]['name']}: {handover[0]}")
    return jsonify(t.out(updated))


@bp.get("/users/<_id>/open-work")
@api("users", write=False)
def user_open_work(_id):
    t.get("users", _id)
    return jsonify(open_work(_id))


@bp.get("/users/summary")
@api("users", write=False)
def summary():
    return jsonify({"limits": limits(), "usage": usage(g.company)})
