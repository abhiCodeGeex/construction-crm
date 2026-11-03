"""Company users: internal staff (counted against the plan) and external portal users (free)."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db
from ..security import api, hash_password, INTERNAL_ROLES, EXTERNAL_ROLES
from ..services.subscription import check_user_limit, limits, usage

bp = Blueprint("users", __name__)


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
    if d.get("password"):
        if len(d["password"]) < 6:
            abort(400, "Password must be at least 6 characters")
        changes["password"] = hash_password(d["password"])
    if user["role"] == "owner" and (changes.get("active") is False or changes.get("role", "owner") != "owner"):
        if db.users.count_documents({"company_id": g.cid, "role": "owner", "active": {"$ne": False}}) <= 1:
            abort(409, "A company needs at least one active owner")
    return jsonify(t.out(t.update("users", _id, changes)))


@bp.get("/users/summary")
@api("users", write=False)
def summary():
    return jsonify({"limits": limits(), "usage": usage(g.company)})
