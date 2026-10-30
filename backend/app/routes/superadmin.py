"""Super Admin authentication & authorization (section 18). Platform-level only: no company private data."""
from flask import Blueprint, request, jsonify, abort, g

from ..db import db, oid, serialize
from ..security import superadmin, check_password, create_token, hash_password, SA_ROLES
from ..services.subscription import usage
from ..tenancy import now

bp = Blueprint("superadmin", __name__)

SA_AREAS = ["dashboard", "companies", "plans", "coupons", "billing", "reports", "support", "announcements",
            "settings"]
SA_LABELS = {"owner": "Owner (Super Admin)", "billing": "Billing staff", "support": "Support staff",
             "sales": "Sales staff", "viewer": "Viewer"}


def sa_audit(action, target=None, note=None):
    db.sa_audit.insert_one({"by": g.sa.get("name"), "role": g.sa.get("role"), "action": action,
                            "target": target, "note": note, "at": now()})


def _sa_perms(role):
    allowed = SA_ROLES.get(role, set())
    out = {}
    for area in SA_AREAS:
        if "*" in allowed or area in allowed:
            out[area] = "rw"
        elif area == "companies" and "companies_read" in allowed:
            out[area] = "r"
    return out


@bp.post("/sa/login")
def login():
    d = request.get_json(force=True) or {}
    u = db.superadmin_users.find_one({"email": (d.get("email") or "").strip().lower()})
    if not u or not check_password(d.get("password", ""), u["password"]):
        abort(401, "Wrong email or password")
    if u.get("active") is False:
        abort(403, "This Super Admin user is deactivated")
    # two-factor is required for every Super Admin user (demo TOTP is a fixed code until a real authenticator is wired)
    if not d.get("code"):
        return jsonify({"two_factor_required": True}), 200
    if d["code"] != u.get("totp_demo"):
        abort(401, "Wrong two-factor code")
    token = create_token({"uid": str(u["_id"]), "kind": "superadmin", "role": u["role"], "name": u["name"]})
    db.sa_audit.insert_one({"by": u["name"], "role": u["role"], "action": "login", "at": now()})
    return jsonify({"token": token, "user": serialize(u), "permissions": _sa_perms(u["role"])})


@bp.get("/sa/me")
@superadmin("dashboard")
def me():
    u = db.superadmin_users.find_one({"_id": oid(g.sa["uid"])})
    return jsonify({"user": serialize(u), "permissions": _sa_perms(u["role"]), "labels": SA_LABELS})


@bp.get("/sa/matrix")
@superadmin("dashboard")
def matrix():
    return jsonify({"areas": SA_AREAS,
                    "roles": [{"role": r, "label": SA_LABELS[r], "perms": _sa_perms(r)} for r in SA_ROLES]})


@bp.get("/sa/dashboard")
@superadmin("dashboard")
def dashboard():
    by_status = {}
    for c in db.companies.find({"deleted_at": None}, {"status": 1}):
        by_status[c.get("status", "trial")] = by_status.get(c.get("status", "trial"), 0) + 1
    return jsonify({"companies": {"total": sum(by_status.values()), **by_status},
                    "users": db.users.count_documents({"kind": "staff"}),
                    "portal_users": db.users.count_documents({"kind": "external"})})


# ---------------- companies (platform fields only) ----------------
PUBLIC = ("name", "types", "modules", "plan_code", "status", "trial_ends", "city", "owner_email", "created_at",
          "allow_support_login")


@bp.get("/sa/companies")
@superadmin("companies")
def companies():
    out = []
    for c in db.companies.find({"deleted_at": None}).sort("created_at", -1):
        row = serialize({k: c.get(k) for k in PUBLIC})
        row["id"] = str(c["_id"])
        row["usage"] = usage(c)
        out.append(row)
    return jsonify(out)


@bp.post("/sa/companies/<_id>/action")
@superadmin("companies")
def company_action(_id):
    d = request.get_json(force=True) or {}
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    action = d.get("action")
    if action == "suspend":
        changes = {"status": "suspended", "suspended_at": now(), "suspend_reason": d.get("reason")}
    elif action == "reactivate":
        changes = {"status": "active", "suspended_at": None}
    else:
        abort(400, "Unknown action")
    db.companies.update_one({"_id": c["_id"]}, {"$set": changes})
    sa_audit(action, _id, d.get("reason"))
    return jsonify({"ok": True, "status": changes["status"]})


# ---------------- probes for testing Super Admin role permissions ----------------
def _probe(area):
    return jsonify({"ok": True, "area": area, "access": "write" if request.method != "GET" else "read",
                    "role": g.sa.get("role")})


for _area in SA_AREAS:
    bp.add_url_rule(f"/sa/probe/{_area}", f"sa_probe_{_area}",
                    superadmin(_area)(lambda a=_area: _probe(a)), methods=["GET", "POST"])


# ---------------- Super Admin team ----------------
@bp.get("/sa/team")
@superadmin("settings")
def team():
    return jsonify(serialize(list(db.superadmin_users.find({}, {"totp_demo": 0}))))


@bp.post("/sa/team")
@superadmin("settings")
def add_team():
    d = request.get_json(force=True) or {}
    email = (d.get("email") or "").strip().lower()
    if not d.get("name") or not email or d.get("role") not in SA_ROLES:
        abort(400, "Name, email and a valid role are required")
    if len(d.get("password") or "") < 8:
        abort(400, "Super Admin passwords must be at least 8 characters")
    if db.superadmin_users.find_one({"email": email}):
        abort(409, "Email already in use")
    doc = {"name": d["name"], "email": email, "role": d["role"], "password": hash_password(d["password"]),
           "totp_demo": "123456", "active": True, "created_at": now()}
    doc["_id"] = db.superadmin_users.insert_one(doc).inserted_id
    sa_audit("add_team_member", email, d["role"])
    doc.pop("totp_demo")
    return jsonify(serialize(doc)), 201


@bp.put("/sa/team/<_id>")
@superadmin("settings")
def update_team(_id):
    d = request.get_json(force=True) or {}
    if _id == g.sa["uid"]:
        abort(409, "You cannot change your own Super Admin access")
    changes = {}
    if d.get("role") in SA_ROLES:
        changes["role"] = d["role"]
    if "active" in d:
        changes["active"] = bool(d["active"])
    db.superadmin_users.update_one({"_id": oid(_id)}, {"$set": changes})
    sa_audit("update_team_member", _id, str(changes))
    return jsonify({"ok": True})


@bp.get("/sa/audit")
@superadmin("dashboard")
def audit():
    return jsonify(serialize(list(db.sa_audit.find().sort("at", -1).limit(300))))
