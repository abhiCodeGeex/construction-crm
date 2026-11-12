"""Authentication, role permissions, module gating and tenant status checks."""
import time
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
import jwt
from flask import request, g, abort

from .config import Config
from .db import db, oid

AREAS = [
    "leads", "contacts", "projects", "proposals", "documents", "selections", "procurement",
    "change_orders", "finance", "site", "followups", "messages", "reports", "settings", "users",
]

# role -> {area: "r" | "rw"}
_ALL = {a: "rw" for a in AREAS}
ROLE_PERMS = {
    "owner": _ALL,
    "sales": {"leads": "rw", "contacts": "rw", "proposals": "rw", "followups": "rw", "messages": "rw",
              "projects": "r", "documents": "r", "reports": "r"},
    "pm": {"projects": "rw", "change_orders": "rw", "site": "rw", "followups": "rw", "messages": "rw",
           "documents": "rw", "contacts": "rw", "proposals": "r", "procurement": "rw", "finance": "rw",
           "selections": "rw", "reports": "r", "leads": "r"},
    "designer": {"documents": "rw", "selections": "rw", "projects": "r", "followups": "rw", "messages": "rw",
                 "contacts": "r", "change_orders": "rw", "finance": "r", "proposals": "r"},
    "estimator": {"proposals": "rw", "projects": "r", "contacts": "r", "procurement": "r", "followups": "rw",
                  "leads": "r"},
    "site": {"site": "rw", "projects": "r", "documents": "r", "messages": "rw", "followups": "rw",
             "change_orders": "r", "procurement": "r"},
    "procurement": {"procurement": "rw", "contacts": "rw", "selections": "r", "projects": "r", "messages": "rw",
                    "followups": "rw", "finance": "r"},
    "accounts": {"finance": "rw", "projects": "r", "contacts": "r", "reports": "r", "procurement": "r",
                 "change_orders": "r", "followups": "rw", "messages": "rw", "proposals": "r"},
}
INTERNAL_ROLES = list(ROLE_PERMS.keys())
EXTERNAL_ROLES = ["client", "subcontractor", "vendor", "consultant"]
MANAGER_ROLES = {"owner", "pm"}
# roles that must never see cost price / margin
HIDE_COST_ROLES = {"site", "client", "subcontractor", "vendor", "consultant"}
COST_FIELDS = {"trade_price", "material_rate", "labour_rate", "cost", "line_cost", "subtotal_cost",
               "margin", "margin_pct", "markup_pct", "overheads", "markup_amount", "budget", "spent", "cost_rate", "unit_cost",
               "daily_rate"}  # Phase I: a site worker's daily rate

ROLE_LABELS = {
    "owner": "Owner / Admin", "sales": "Sales / BD", "pm": "Project Manager", "designer": "Architect / Designer",
    "estimator": "Estimator / QS", "site": "Site Supervisor", "procurement": "Procurement", "accounts": "Accounts",
    "client": "Client", "subcontractor": "Subcontractor", "vendor": "Vendor / Supplier", "consultant": "Consultant",
}

SA_ROLES = {
    "owner": {"*"},
    "billing": {"dashboard", "billing", "reports"},
    "support": {"dashboard", "support", "companies_read"},
    "sales": {"dashboard", "companies", "companies_read", "coupons"},
    "viewer": {"dashboard", "reports", "companies_read"},
}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(payload: dict) -> str:
    data = dict(payload)
    data["exp"] = datetime.utcnow() + timedelta(hours=Config.TOKEN_HOURS)
    data["iat"] = int(time.time())
    data["iat_ms"] = int(time.time() * 1000)  # sessions started before a password change are refused (_load_tenant)
    return jwt.encode(data, Config.SECRET_KEY, algorithm="HS256")


def _read_token():
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else request.args.get("t")
    if not token:
        abort(401, "Please sign in first")
    try:
        return jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        abort(401, "Your session has expired. Sign in again.")
    except jwt.InvalidTokenError:
        abort(401, "Your session is not valid any more. Sign in again.")


# write endpoints a read-only (unpaid) tenant may still call
READ_ONLY_ALLOW = ("/api/billing", "/api/auth", "/api/support")


def _load_tenant(payload):
    # role / active state are read from the database on every request, so a role change or
    # deactivation takes effect immediately instead of when the token expires
    user = db.users.find_one({"_id": oid(payload.get("uid")), "company_id": payload.get("cid")})
    if not user or user.get("active") is False:
        abort(401, "User is deactivated or no longer exists")
    if (payload.get("iat_ms") or 0) < (user.get("password_changed_ms") or 0):
        abort(401, "Your password was changed. Sign in again with the new password.")
    g.user = {**payload, "name": user["name"]}
    if payload.get("support_session"):  # Phase I: platform support logged in with the company's permission
        g.user["name"] = f"{payload.get('sa_name') or 'Platform'} (support, as {user['name']})"
    g.uid = str(user["_id"])
    g.cid = user["company_id"]
    g.role = user["role"]
    g.kind = user["kind"]
    g.contact_id = user.get("contact_id")
    g.hide_costs = g.role in HIDE_COST_ROLES
    company = db.companies.find_one({"_id": oid(g.cid)})
    if not company or company.get("deleted_at"):
        abort(401, "Company not found")
    if company.get("status") == "suspended":
        abort(403, "Company account is suspended. Contact support.")
    if company.get("status") == "pending":
        abort(403, "Your company is waiting for approval by the platform.")
    g.company = company
    g.perms = effective_perms(g.role, company)
    if company.get("status") in ("read_only", "cancelled") and request.method != "GET" \
            and not request.path.startswith(READ_ONLY_ALLOW):
        abort(402, "Subscription payment overdue — account is read-only until paid.")


def auth_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        payload = _read_token()
        if payload.get("kind") == "superadmin":
            abort(403, "Use the Super Admin panel")
        _load_tenant(payload)
        return f(*a, **kw)
    return wrapper


def effective_perms(role, company=None):
    """Code defaults merged with optional per-company overrides (company.role_overrides[role][area]).
    New areas added by future modules appear automatically for every company; a company's own
    customisations are never overwritten because they live in a separate field."""
    perms = dict(ROLE_PERMS.get(role, {}))
    for area, level in ((company or {}).get("role_overrides", {}).get(role, {})).items():
        if area in AREAS and level in ("", "r", "rw"):
            perms[area] = level
    return {a: lvl for a, lvl in perms.items() if lvl}


def can(area, write=False, role=None):
    perms = effective_perms(role, getattr(g, "company", None)) if role else g.perms
    level = perms.get(area, "")
    return "w" in level if write else "r" in level


def api(area=None, module=None, write=None, staff=True):
    """Auth + tenant + permission decorator. write=None infers from HTTP method."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            payload = _read_token()
            if payload.get("kind") == "superadmin":
                abort(403, "Super Admin cannot access company data")
            _load_tenant(payload)
            if staff and g.kind != "staff":
                abort(403, "Staff only")
            if area:
                w = write if write is not None else request.method not in ("GET", "HEAD")
                if not can(area, w):
                    abort(403, f"Your role cannot {'change' if w else 'view'} {area.replace('_', ' ')}")
            if module and module not in g.company.get("modules", []):
                abort(403, f"The {module} module is not enabled for this company")
            return f(*a, **kw)
        return wrapper
    return deco


def portal(f):
    """External users (client / vendor / subcontractor / consultant)."""
    @wraps(f)
    def wrapper(*a, **kw):
        payload = _read_token()
        _load_tenant(payload)
        if g.kind != "external":
            abort(403, "Portal users only")
        return f(*a, **kw)
    return wrapper


def superadmin(perm="dashboard"):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            payload = _read_token()
            if payload.get("kind") != "superadmin":
                abort(403, "Super Admin only")
            sa_user = db.superadmin_users.find_one({"_id": oid(payload.get("uid"))})
            if not sa_user or sa_user.get("active") is False:
                abort(401, "Super Admin user is deactivated")
            g.sa = {**payload, "role": sa_user["role"], "name": sa_user["name"]}
            allowed = SA_ROLES.get(sa_user["role"], set())
            write = request.method not in ("GET", "HEAD")
            needed = perm if (write or perm != "companies") else "companies_read"
            if "*" not in allowed and needed not in allowed and perm not in allowed:
                abort(403, "Your Super Admin role cannot do this")
            return f(*a, **kw)
        return wrapper
    return deco
