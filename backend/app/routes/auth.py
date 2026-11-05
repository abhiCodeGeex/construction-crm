import hashlib
import secrets
import threading
import time
from datetime import timedelta

from flask import Blueprint, request, jsonify, abort, g

from ..config import Config
from ..db import db, oid, serialize
from ..security import (hash_password, check_password, create_token, auth_required, effective_perms, ROLE_LABELS,
                        INTERNAL_ROLES, EXTERNAL_ROLES)
from ..services import notify
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
        "branding": {"primary": "#1f6feb", "logo_key": None},
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
    if d["new"] == d.get("current"):
        abort(400, "The new password is the same as the current one")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"password": hash_password(d["new"]),
                                                        "password_changed_ms": int(time.time() * 1000)}})
    db.audit_logs.insert_one({"company_id": g.cid, "user_id": g.uid, "user_name": user["name"], "action": "password_changed",
                              "collection": "users", "doc_id": g.uid, "changes": None, "note": None, "at": now()})
    # other devices are signed out; this one carries on with a new session
    company = db.companies.find_one({"_id": oid(g.cid)})
    return jsonify(_session(db.users.find_one({"_id": user["_id"]}), company))


# ---------------- forgot password (B+1) ----------------
RESET_MINUTES = 60          # a reset link works for one hour, once
RESET_PER_HOUR = 3          # at most three links per user per hour
FORGOT_MESSAGE = ("If an account exists for this email, a link to choose a new password has been sent to it. "
                  "It works for 60 minutes. No email after a few minutes? Your company may not have email set up "
                  "yet: ask your company Owner to reset your password from Users.")


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@bp.post("/auth/forgot")
def forgot_password():
    """Always gives the same answer, so nobody can find out which emails have an account."""
    email = ((request.get_json(force=True) or {}).get("email") or "").strip().lower()
    if not email:
        abort(400, "Enter your email")
    user = db.users.find_one({"email": email})
    company = user and db.companies.find_one({"_id": oid(user["company_id"])})
    ok = (user and user.get("active") is not False and company and not company.get("deleted_at")
          and company.get("status") != "suspended")
    recent = ok and db.password_resets.count_documents(
        {"user_id": str(user["_id"]), "created_at": {"$gte": now() - timedelta(hours=1)}})
    if ok and recent < RESET_PER_HOUR and notify.email_ready(company):
        token = secrets.token_urlsafe(32)
        db.password_resets.insert_one({"token_hash": _hash(token), "user_id": str(user["_id"]),
                                       "company_id": str(company["_id"]), "created_at": now(), "used_at": None,
                                       "expires_at": now() + timedelta(minutes=RESET_MINUTES),
                                       "ip": request.headers.get("X-Forwarded-For", request.remote_addr)})
        base = (notify.email_settings(company).get("app_url") or request.host_url).rstrip("/")
        body = (f"Hello {user['name']},\n\nSomeone (hopefully you) asked to reset your BuildSuite password for "
                f"{company['name']}.\n\nChoose a new password here (the link works for {RESET_MINUTES} minutes, "
                f"once):\n{base}/reset/{token}\n\nIf you did not ask for this, ignore this email: your password "
                f"stays the same.\n\n— {company['name']} · BuildSuite")
        # sent in the background: the answer takes the same time whether or not the email has an account
        threading.Thread(target=_send_reset, args=(company, user, body), daemon=True).start()
    return jsonify({"ok": True, "message": FORGOT_MESSAGE})


def _send_reset(company, user, body):
    result = notify.deliver(company, user["email"], "Reset your BuildSuite password", body)
    db.audit_logs.insert_one({"company_id": str(company["_id"]), "user_id": str(user["_id"]),
                              "user_name": user["name"], "action": "password_reset_requested",
                              "collection": "users", "doc_id": str(user["_id"]), "changes": None,
                              "note": f"reset link email: {result}", "at": now()})


def _reset_doc(token):
    r = db.password_resets.find_one({"token_hash": _hash(token or "")})
    if not r or r.get("used_at") or r["expires_at"] < now():
        abort(410, "This link has expired or was already used. Ask for a new one from the sign-in page.")
    user = db.users.find_one({"_id": oid(r["user_id"]), "company_id": r["company_id"]})
    if not user or user.get("active") is False:
        abort(410, "This account is no longer active")
    return r, user


@bp.get("/auth/reset/<token>")
def reset_check(token):
    _, user = _reset_doc(token)
    name, _, domain = user["email"].partition("@")
    return jsonify({"valid": True, "email": f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"})


@bp.post("/auth/reset/<token>")
def reset_password(token):
    r, user = _reset_doc(token)
    pw = (request.get_json(force=True) or {}).get("password") or ""
    if len(pw) < 6:
        abort(400, "New password must be at least 6 characters")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"password": hash_password(pw),
                                                        "password_changed_ms": int(time.time() * 1000)}})
    # this link and every other open link of the user stop working
    db.password_resets.update_many({"user_id": r["user_id"], "used_at": None}, {"$set": {"used_at": now()}})
    db.audit_logs.insert_one({"company_id": r["company_id"], "user_id": r["user_id"], "user_name": user["name"],
                              "action": "password_reset", "collection": "users", "doc_id": r["user_id"],
                              "changes": None, "note": "new password chosen from an emailed link", "at": now()})
    return jsonify({"ok": True})
