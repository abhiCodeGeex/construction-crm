from datetime import timedelta

from flask import Blueprint, request, jsonify, abort, g

from ..config import Config
from ..db import db, oid, serialize
from ..security import (hash_password, check_password, create_token, auth_required, effective_perms, ROLE_LABELS,
                        INTERNAL_ROLES, EXTERNAL_ROLES)
from ..services.defaults import COMPANY_TYPES
from ..services.subscription import limits, check_modules
from ..services.tenant_setup import bootstrap_company
from ..tenancy import now

bp = Blueprint("auth", __name__)


def _session(user, company):
    token = create_token({
        "uid": str(user["_id"]), "cid": str(company["_id"]), "role": user["role"], "kind": user["kind"],
        "name": user["name"], "contact_id": user.get("contact_id"),
    })
    return {"token": token, **_profile(user, company)}


def _profile(user, company):
    return {
        "user": serialize(user),
        "company": serialize({k: v for k, v in company.items() if k not in ("counters", "notes")}),
        "permissions": effective_perms(user["role"], company),
        "limits": limits(company),
        "roles": {"internal": INTERNAL_ROLES, "external": EXTERNAL_ROLES, "labels": ROLE_LABELS},
    }


@bp.post("/auth/signup")
def signup():
    d = request.get_json(force=True) or {}
    for f in ("company_name", "name", "email", "password"):
        if not d.get(f):
            abort(400, f"{f.replace('_', ' ')} is required")
    email = d["email"].strip().lower()
    if db.users.find_one({"email": email}):
        abort(409, "An account with this email already exists")
    types = d.get("company_types") or ["architect", "contractor", "interior"]
    modules = [COMPANY_TYPES[t] for t in types if t in COMPANY_TYPES]
    plan = db.plans.find_one({"code": d.get("plan_code") or "pro"}) or db.plans.find_one({})
    company = {
        "name": d["company_name"], "types": types, "modules": modules,
        "plan_code": plan["code"] if plan else None, "billing_cycle": "monthly",
        "status": "trial", "trial_ends": now() + timedelta(days=Config.TRIAL_DAYS),
        "currency": "INR", "tax_rate": 18.0, "tax_label": "GST", "gstin": d.get("gstin"),
        "city": d.get("city"), "phone": d.get("phone"),
        "branches": [{"name": "Head office", "city": d.get("city")}],
        "branding": {"primary": "#1f6feb", "logo": None},
        "numbering": {}, "counters": {}, "allow_support_login": False,
        "created_at": now(), "owner_email": email,
    }
    check_modules(modules, company)
    company["_id"] = db.companies.insert_one(company).inserted_id
    user = {
        "company_id": str(company["_id"]), "name": d["name"], "email": email,
        "password": hash_password(d["password"]), "role": "owner", "kind": "staff", "active": True,
        "phone": d.get("phone"), "created_at": now(),
    }
    user["_id"] = db.users.insert_one(user).inserted_id
    bootstrap_company(str(company["_id"]), modules)
    return jsonify(_session(user, company)), 201


@bp.post("/auth/login")
def login():
    d = request.get_json(force=True) or {}
    user = db.users.find_one({"email": (d.get("email") or "").strip().lower()})
    if not user or not check_password(d.get("password", ""), user.get("password", "")):
        abort(401, "Wrong email or password")
    if user.get("active") is False:
        abort(403, "This user has been deactivated")
    company = db.companies.find_one({"_id": oid(user["company_id"])})
    if not company or company.get("deleted_at"):
        abort(403, "Company not found")
    if company.get("status") == "suspended":
        abort(403, "Company account is suspended. Contact support.")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login": now()}})
    return jsonify(_session(user, company))


@bp.get("/auth/me")
@auth_required
def me():
    user = db.users.find_one({"_id": oid(g.uid)})
    return jsonify(_profile(user, g.company))


@bp.post("/auth/password")
@auth_required
def change_password():
    d = request.get_json(force=True) or {}
    user = db.users.find_one({"_id": oid(g.uid)})
    if not check_password(d.get("current", ""), user["password"]):
        abort(400, "Current password is wrong")
    if len(d.get("new", "")) < 6:
        abort(400, "New password must be at least 6 characters")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"password": hash_password(d["new"])}})
    return jsonify({"ok": True})
