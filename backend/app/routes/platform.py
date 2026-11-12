"""Phase I block 6 — the Super Admin panel and subscriptions (§18). Ported from `later/routes/superadmin.py` onto the
current app; platform-level only, never a company's private data (clients, costs, documents).

Super Admin (by area of `SA_ROLES`):
* Dashboard: companies by status, MRR, revenue this / last month / year, signups, trials converted, cancellations,
  overdue payments with days late, system health (database, storage, errors).
* Companies: list with search and filters, profile (owner, plan, usage, payment history, tickets, support sessions,
  notes), create manually (temporary owner password), approve / suspend / reactivate / delete (kept 30 days, then
  purged) / restore, extend the trial, give free months, change the plan, switch modules and features, internal
  notes, reset the owner's password, log in as the company (only when it allowed support, one hour, always logged),
  export its data when it asked for it.
* Plans and coupons; add-ons (extra users, storage packs) on the company. A plan's new price applies to new signups —
  a company keeps its locked price until renewal.
* Billing: GST invoices with the platform GSTIN and SAC code, a daily run (trial ends → first invoice; renewal due →
  invoice; unpaid → reminders; 7 days past due → read-only; nothing is deleted), manual payments, refunds as credit
  notes, void, the monthly GST report.
* Usage per company against its plan, alerts near a limit (80 %), WhatsApp cost against what the company pays.
* Support tickets raised from inside the CRM; announcements to all or filtered companies; platform settings (keys
  masked), terms and privacy pages; revenue / churn / conversion / feature-use reports.
Company (Owner): Settings → Subscription — plan, usage, invoices, change plan or cycle (prorated), coupon, cancel, pay;
support tickets; data export request; read announcements.
"""
import uuid
from datetime import datetime, timedelta

import jwt
from flask import Blueprint, request, jsonify, abort, g

from ..config import Config
from ..db import db, oid, serialize, TENANT_COLLECTIONS
from ..security import superadmin, hash_password, api
from ..services.defaults import COMPANY_TYPES
from ..services.subscription import usage, limits
from ..tenancy import now
from .lead_steps import num

bp = Blueprint("platform", __name__)

COMPANY_PUBLIC = ("name", "types", "modules", "plan_code", "billing_cycle", "status", "trial_ends", "next_renewal", "city", "gstin",
                  "owner_email", "created_at", "addons", "price_locked", "coupon", "cancelled_at", "cancel_reason", "deleted_at",
                  "purge_after", "allow_support_login", "notes", "feature_flags", "approved_at", "export_requested")
STATUSES = ("pending", "trial", "active", "read_only", "suspended", "cancelled")
FEATURES = ("whatsapp", "online_payments", "procurement", "portal", "selections", "site_reports")
ADDON_PRICES = {"extra_user": 500, "storage_100gb": 500}  # per month, before GST
WA_COST = 0.115  # Meta utility message, before GST (requirements §17)


def sa_audit(action, target=None, note=None):
    db.sa_audit.insert_one({"by": g.sa.get("name"), "by_id": g.sa.get("uid"), "role": g.sa.get("role"),
                            "action": action, "target": target, "note": note, "at": now()})


def r2(v):
    return round((v or 0) + 1e-9, 2)


def company_row(c):
    data = {k: c.get(k) for k in COMPANY_PUBLIC}
    data["id"] = str(c["_id"])
    return serialize(data)


def load_company(_id):
    return (db.companies.find_one({"_id": oid(_id)}) if len(_id) == 24 else None) or abort(404, "company not found")


def plan_of(code):
    return db.plans.find_one({"code": code}) or {}


def monthly_value(c):
    plan = plan_of(c.get("plan_code"))
    if c.get("billing_cycle") == "yearly":
        return (c.get("price_locked") or plan.get("price_yearly", 0)) / 12
    return c.get("price_locked") or plan.get("price_monthly", 0)


def as_dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


# ============================== dashboard ==============================
@bp.get("/sa/dashboard")
@superadmin("dashboard")
def dashboard():
    companies = list(db.companies.find({"deleted_at": None}))
    by_status = {}
    for c in companies:
        by_status[c.get("status", "trial")] = by_status.get(c.get("status", "trial"), 0) + 1
    month = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (month - timedelta(days=1)).replace(day=1)
    year_start = month.replace(month=1)

    def paid(a, b):
        return r2(sum(i["subtotal"] for i in db.platform_invoices.find({"status": "paid", "paid_at": {"$gte": a, "$lt": b}})))

    overdue = []
    for i in db.platform_invoices.find({"status": {"$in": ["due", "overdue"]}}):
        days = (now() - i["due_date"]).days if isinstance(i.get("due_date"), datetime) else 0
        if days > 0:
            overdue.append({"company": i.get("company_name"), "company_id": i["company_id"], "number": i["number"], "amount": i["total"], "days_late": days})
    storage = sum(f.get("size", 0) for f in db.files.find({}, {"size": 1}))
    try:
        db_ok = bool(db.command("ping").get("ok"))
    except Exception:
        db_ok = False
    backup = db.platform_settings.find_one({"_id": "backup"}) or {}
    return jsonify(serialize({
        "companies": {"total": len(companies), **by_status},
        "users": db.users.count_documents({"kind": "staff"}), "portal_users": db.users.count_documents({"kind": "external"}),
        "mrr": r2(sum(monthly_value(c) for c in companies if c.get("status") == "active")),
        "revenue_this_month": paid(month, now() + timedelta(days=1)), "revenue_last_month": paid(last_month, month),
        "revenue_this_year": paid(year_start, now() + timedelta(days=1)),
        "signups_this_month": db.companies.count_documents({"created_at": {"$gte": month}}),
        "trials_converted": db.companies.count_documents({"converted_at": {"$gte": month}}),
        "cancellations_this_month": db.companies.count_documents({"cancelled_at": {"$gte": month}}),
        "overdue": sorted(overdue, key=lambda x: -x["days_late"]),
        "health": {"api": "ok", "db": "ok" if db_ok else "down", "storage_bytes": storage,
                   "errors_24h": db.error_log.count_documents({"at": {"$gte": now() - timedelta(days=1)}}),
                   "last_backup": backup.get("last_ok"), "backup_status": backup.get("status")}}))


# ============================== companies ==============================
@bp.get("/sa/companies")
@superadmin("companies")
def companies():
    q = {"deleted_at": None} if request.args.get("deleted") != "1" else {"deleted_at": {"$ne": None}}
    for k in ("plan_code", "status", "city"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("q"):
        import re
        q["name"] = {"$regex": re.escape(request.args["q"]), "$options": "i"}
    if request.args.get("from"):
        q["created_at"] = {"$gte": as_dt(request.args["from"]) or abort(400, "From must be a date")}
    out = []
    for c in db.companies.find(q).sort("created_at", -1):
        row = company_row(c)
        row["usage"] = usage(c)
        out.append(row)
    return jsonify(out)


@bp.get("/sa/companies/<_id>")
@superadmin("companies")
def company(_id):
    c = load_company(_id)
    owner = db.users.find_one({"company_id": _id, "role": "owner"}, {"name": 1, "email": 1, "phone": 1})
    return jsonify(serialize({**company_row(c), "owner": owner, "usage": usage(c), "limits": limits(c), "monthly_value": r2(monthly_value(c)),
                              "invoices": list(db.platform_invoices.find({"company_id": _id}).sort("created_at", -1)),
                              "tickets": list(db.support_tickets.find({"company_id": _id}).sort("created_at", -1)),
                              "support_sessions": list(db.sa_audit.find({"target": _id, "action": "login_as"}).sort("at", -1))}))


@bp.post("/sa/companies")
@superadmin("companies")
def create_company():
    """A company onboarded by the sales team: trial, temporary owner password."""
    from ..services.tenant_setup import bootstrap_company
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip() or abort(400, "Company name is required")
    email = (d.get("owner_email") or "").strip().lower() or abort(400, "Owner email is required")
    if db.users.find_one({"email": email}):
        abort(409, "Owner email already in use")
    types = [x for x in (d.get("types") or ["contractor"]) if x in COMPANY_TYPES] or abort(400, "Choose the company type")
    plan = db.plans.find_one({"code": d.get("plan_code") or "basic", "active": True}) or abort(400, "Plan not found")
    c = {"name": name, "types": types, "modules": [COMPANY_TYPES[x] for x in types], "plan_code": plan["code"],
         "billing_cycle": d.get("billing_cycle") if d.get("billing_cycle") in ("monthly", "yearly") else "monthly",
         "status": "trial", "trial_ends": now() + timedelta(days=Config.TRIAL_DAYS), "city": d.get("city"), "gstin": d.get("gstin"),
         "currency": "INR", "tax_rate": 18.0, "tax_label": "GST", "branding": {}, "counters": {}, "numbering": {},
         "owner_email": email, "price_locked": plan["price_monthly"], "allow_support_login": False, "deleted_at": None,
         "created_at": now(), "onboarded_by": g.sa.get("name")}
    c["_id"] = db.companies.insert_one(c).inserted_id
    pw = uuid.uuid4().hex[:10]
    db.users.insert_one({"company_id": str(c["_id"]), "name": (d.get("owner_name") or "Owner").strip()[:80], "email": email,
                         "password": hash_password(pw), "role": "owner", "kind": "staff", "active": True, "created_at": now(),
                         "must_change_password": True})
    bootstrap_company(str(c["_id"]), c["modules"])
    sa_audit("create_company", str(c["_id"]), name)
    return jsonify({**company_row(c), "temp_password": pw}), 201


@bp.post("/sa/companies/<_id>/action")
@superadmin("companies")
def company_action(_id):
    d = request.get_json(force=True) or {}
    action = d.get("action")
    c = load_company(_id)
    changes = {}
    if action == "approve":
        if c.get("status") != "pending":
            abort(409, "Only a company waiting for approval is approved")
        changes = {"status": "trial", "approved_at": now(), "trial_ends": now() + timedelta(days=Config.TRIAL_DAYS)}
    elif action == "suspend":
        changes = {"status": "suspended", "suspended_at": now(), "suspend_reason": d.get("reason"), "status_before": c.get("status")}
    elif action == "reactivate":
        changes = {"status": c.get("status_before") if c.get("status_before") in ("trial", "active") else "active", "suspended_at": None}
    elif action == "delete":  # kept for 30 days, then purged by the worker
        changes = {"deleted_at": now(), "purge_after": now() + timedelta(days=30), "status_before": c.get("status"), "status": "cancelled"}
    elif action == "restore":
        if not c.get("deleted_at"):
            abort(409, "The company is not deleted")
        changes = {"deleted_at": None, "purge_after": None, "status": c.get("status_before") or "active"}
    elif action == "extend_trial":
        days = int(num(d.get("days"), "Days", required=True, positive=True))
        base = as_dt(c.get("trial_ends")) if as_dt(c.get("trial_ends")) and as_dt(c.get("trial_ends")) > now() else now()
        changes = {"trial_ends": base + timedelta(days=days), "status": "trial"}
    elif action == "free_months":
        months = int(num(d.get("months"), "Months", required=True, positive=True))
        base = as_dt(c.get("next_renewal")) or now()
        changes = {"next_renewal": base + timedelta(days=30 * months), "status": "active" if c.get("status") != "trial" else "trial"}
    elif action == "change_plan":
        plan = db.plans.find_one({"code": d.get("plan_code"), "active": True}) or abort(404, "Plan not found")
        changes = {"plan_code": plan["code"], "price_locked": plan["price_monthly"]}
    elif action == "modules":
        mods = [m for m in d.get("modules") or [] if m in COMPANY_TYPES.values()] or abort(400, "Choose at least one module")
        changes = {"modules": mods}
    elif action == "features":
        changes = {"feature_flags": {k: bool(v) for k, v in (d.get("features") or {}).items() if k in FEATURES}}
    elif action == "addons":
        changes = {"addons": {"extra_users": int(num(d.get("extra_users"), "Extra users") or 0),
                              "extra_storage_gb": int(num(d.get("extra_storage_gb"), "Extra storage") or 0) // 100 * 100}}
    elif action == "note":
        text = (d.get("text") or "").strip()[:1000] or abort(400, "Write the note")
        db.companies.update_one({"_id": c["_id"]}, {"$push": {"notes": {"text": text, "by": g.sa.get("name"), "at": now()}}})
    elif action == "reset_owner_password":
        pw = uuid.uuid4().hex[:10]
        res = db.users.update_one({"company_id": _id, "role": "owner"}, {"$set": {"password": hash_password(pw), "must_change_password": True,
                                                                                    "password_changed_ms": int(now().timestamp() * 1000)}})
        if not res.matched_count:
            abort(404, "The company has no owner")
        sa_audit("reset_owner_password", _id)
        return jsonify({"temp_password": pw})
    else:
        abort(400, "Unknown action")
    if changes:
        db.companies.update_one({"_id": c["_id"]}, {"$set": changes})
    sa_audit(action, _id, d.get("reason") or d.get("text") or (str(changes)[:300] if changes else None))
    return jsonify(company_row(db.companies.find_one({"_id": c["_id"]})))


@bp.post("/sa/companies/<_id>/login-as")
@superadmin("support")
def login_as(_id):
    """Log in as a company to help — only when it allowed support access; one hour; every session is logged."""
    c = load_company(_id)
    if not c.get("allow_support_login"):
        abort(403, "The company has not allowed support access (Settings → Company)")
    owner = db.users.find_one({"company_id": _id, "role": "owner", "active": {"$ne": False}}) or abort(404, "The company has no owner")
    reason = (request.get_json(force=True) or {}).get("reason") or abort(400, "Say why you are logging in")
    payload = {"uid": str(owner["_id"]), "cid": _id, "role": "owner", "kind": "staff", "support_session": True,
               "sa_name": g.sa.get("name"), "exp": datetime.utcnow() + timedelta(hours=1), "iat_ms": int(now().timestamp() * 1000)}
    token = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
    sa_audit("login_as", _id, str(reason)[:300])
    db.audit_logs.insert_one({"company_id": _id, "at": now(), "user_name": f"{g.sa.get('name')} (platform support)", "action": "support_login",
                              "entity": "companies", "entity_id": _id, "changes": {"reason": str(reason)[:300]}})
    return jsonify({"token": token, "expires_in_minutes": 60})


@bp.get("/sa/companies/<_id>/export")
@superadmin("support")
def export(_id):
    """The company's data when it asked for it (its data belongs to it)."""
    c = load_company(_id)
    if not c.get("export_requested"):
        abort(403, "The company has not asked for an export (Settings → Subscription)")
    data = {name: serialize(list(db[name].find({"company_id": _id}, {"password": 0, "totp_secret": 0}))) for name in TENANT_COLLECTIONS}
    data["company"] = company_row(c)
    db.companies.update_one({"_id": c["_id"]}, {"$set": {"export_requested": None, "exported_at": now()}})
    sa_audit("export", _id)
    return jsonify(data)


# ============================== plans, coupons ==============================
PLAN_NUMBERS = ("price_monthly", "max_users", "max_projects", "max_modules", "whatsapp_messages", "storage_gb")


@bp.get("/sa/plans")
@superadmin("dashboard")
def plans():
    return jsonify(serialize(list(db.plans.find().sort("price_monthly", 1))))


@bp.post("/sa/plans")
@superadmin("plans")
def add_plan():
    res = save_plan(None)
    res.status_code = 201
    return res


@bp.put("/sa/plans/<_id>")
@superadmin("plans")
def edit_plan(_id):
    return save_plan(_id)


def save_plan(_id):
    d = request.get_json(force=True) or {}
    plan = {}
    for k in ("code", "name", "support", "description"):
        if k in d:
            plan[k] = (str(d[k] or "")).strip()[:120] or None
    for k in PLAN_NUMBERS:
        if k in d:
            plan[k] = num(d[k], k.replace("_", " ")) if d[k] not in (None, "") else None
    if "active" in d:
        plan["active"] = bool(d["active"])
    if "price_monthly" in plan:
        plan["price_monthly"] or abort(400, "A plan needs a monthly price")
        plan["price_yearly"] = plan["price_monthly"] * 10  # yearly = 2 months free
        plan["price_monthly_gst"] = r2(plan["price_monthly"] * (1 + Config.GST_RATE / 100))
    if _id:
        # a new price applies to new signups; companies keep `price_locked` until they renew
        plan.pop("code", None)
        db.plans.update_one({"_id": oid(_id)}, {"$set": plan})
    else:
        if not plan.get("code") or not plan.get("name") or "price_monthly" not in plan:
            abort(400, "Code, name and monthly price are required")
        if db.plans.find_one({"code": plan["code"]}):
            abort(409, "A plan with this code exists")
        plan.setdefault("active", True)
        plan["created_at"] = now()
        _id = str(db.plans.insert_one(plan).inserted_id)
    sa_audit("save_plan", _id, plan.get("name"))
    return jsonify(serialize(db.plans.find_one({"_id": oid(_id)})))


@bp.get("/sa/coupons")
@superadmin("coupons")
def coupons():
    return jsonify(serialize(list(db.coupons.find().sort("created_at", -1))))


@bp.post("/sa/coupons")
@superadmin("coupons")
def create_coupon():
    d = request.get_json(force=True) or {}
    code = (d.get("code") or "").strip().upper()[:30] or abort(400, "Coupon code required")
    pct = num(d.get("percent"), "Percent", required=True, positive=True)
    if pct > 100:
        abort(400, "Percent is at most 100")
    if db.coupons.find_one({"code": code}):
        abort(409, "That code exists")
    doc = {"code": code, "percent": pct, "months": int(num(d.get("months"), "Months") or 1), "active": True, "used": 0,
           "max_uses": int(num(d.get("max_uses"), "Uses") or 0) or None, "expires": d.get("expires") or None,
           "description": (d.get("description") or "").strip()[:200] or None, "created_at": now(), "by": g.sa.get("name")}
    db.coupons.insert_one(doc)
    sa_audit("create_coupon", code)
    return jsonify(serialize(doc)), 201


@bp.put("/sa/coupons/<_id>")
@superadmin("coupons")
def update_coupon(_id):
    d = request.get_json(force=True) or {}
    db.coupons.update_one({"_id": oid(_id)}, {"$set": {"active": bool(d.get("active"))}})
    sa_audit("update_coupon", _id, f"active={bool(d.get('active'))}")
    return jsonify({"ok": True})


def apply_coupon(company, code):
    cp = db.coupons.find_one({"code": (code or "").strip().upper(), "active": True}) or abort(400, "That coupon is not valid")
    if cp.get("expires") and cp["expires"] < now().date().isoformat():
        abort(400, "That coupon has expired")
    if cp.get("max_uses") and cp.get("used", 0) >= cp["max_uses"]:
        abort(400, "That coupon has been used up")
    db.coupons.update_one({"_id": cp["_id"]}, {"$inc": {"used": 1}})
    coupon = {"code": cp["code"], "percent": cp["percent"], "months_left": cp["months"]}
    db.companies.update_one({"_id": company["_id"]}, {"$set": {"coupon": coupon}})
    return coupon


# ============================== billing ==============================
def next_number(kind, prefix):
    counter = db.platform_counters.find_one_and_update({"_id": kind}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
    return f"{prefix}/{now().year}/{counter['n']:05d}"


def issue_invoice(company, prorate_from=None, note=None):
    """A platform GST invoice for the next subscription period (with add-ons, proration credit and coupon)."""
    plan = plan_of(company.get("plan_code")) or abort(400, "The company has no plan")
    yearly = company.get("billing_cycle") == "yearly"
    base = (company.get("price_locked") or plan["price_monthly"]) * (10 if yearly else 1)
    months = 12 if yearly else 1
    lines = [{"description": f"{plan['name']} plan — {'yearly' if yearly else 'monthly'}", "sac": Config.PLATFORM_SAC, "amount": r2(base)}]
    addons = company.get("addons") or {}
    if addons.get("extra_users"):
        lines.append({"description": f"Extra users × {addons['extra_users']}", "sac": Config.PLATFORM_SAC,
                      "amount": ADDON_PRICES["extra_user"] * addons["extra_users"] * months})
    if addons.get("extra_storage_gb"):
        packs = addons["extra_storage_gb"] // 100
        lines.append({"description": f"Extra storage {addons['extra_storage_gb']} GB", "sac": Config.PLATFORM_SAC,
                      "amount": ADDON_PRICES["storage_100gb"] * packs * months})
    if prorate_from and prorate_from["code"] != plan["code"] and as_dt(company.get("next_renewal")):
        days_left = max((as_dt(company["next_renewal"]) - now()).days, 0)
        credit = r2(prorate_from.get("price_monthly", 0) * days_left / 30)
        if credit:
            lines.append({"description": f"Unused {prorate_from.get('name')} ({days_left} days)", "sac": Config.PLATFORM_SAC, "amount": -credit})
    sub = sum(ln["amount"] for ln in lines)
    coupon = company.get("coupon")
    if coupon and coupon.get("months_left", 0) > 0:
        disc = r2(sub * coupon["percent"] / 100)
        lines.append({"description": f"Coupon {coupon['code']} ({coupon['percent']:g}% off)", "sac": Config.PLATFORM_SAC, "amount": -disc})
        sub -= disc
        db.companies.update_one({"_id": company["_id"]}, {"$inc": {"coupon.months_left": -1}})
    sub = max(r2(sub), 0)
    gst = r2(sub * Config.GST_RATE / 100)
    from ..services.gst import state_code
    inter = state_code(company.get("gstin")) not in (None, state_code(Config.PLATFORM_GSTIN))
    inv = {"number": next_number("invoice", "BS"), "type": "invoice", "company_id": str(company["_id"]), "company_name": company["name"],
           "company_gstin": company.get("gstin"), "platform_gstin": Config.PLATFORM_GSTIN, "lines": lines, "subtotal": sub,
           "cgst": 0 if inter else r2(gst / 2), "sgst": 0 if inter else r2(gst - r2(gst / 2)), "igst": gst if inter else 0,
           "gst": gst, "total": r2(sub + gst), "status": "due", "due_date": now() + timedelta(days=Config.GRACE_DAYS),
           "created_at": now(), "period": "yearly" if yearly else "monthly", "attempts": 0, "note": note}
    inv["_id"] = db.platform_invoices.insert_one(inv).inserted_id
    owner_email = company.get("owner_email")
    if owner_email:  # emailed through the platform mail settings when they exist
        from ..services import notify
        notify.deliver(platform_mail(), owner_email, f"BuildSuite invoice {inv['number']}",
                       f"Invoice {inv['number']} for {company['name']}: {inv['total']:,.2f} including GST, due "
                       f"{inv['due_date'].date().isoformat()}.\nPay it from Settings → Subscription.")
    return inv


def platform_mail():
    """Platform email settings shaped like a company's (notify.deliver reads `email_out`)."""
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    return {"name": "BuildSuite", "email_out": s.get("email_out") or {}}


def mark_paid(inv, method, ref=None):
    db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"status": "paid", "paid_at": now(), "method": method, "ref": ref}})
    c = db.companies.find_one({"_id": oid(inv["company_id"])})
    if c and inv.get("type", "invoice") == "invoice":
        start = max(as_dt(c.get("next_renewal")) or now(), now())
        renewal = start + timedelta(days=365 if c.get("billing_cycle") == "yearly" else 30)
        ch = {"next_renewal": renewal}
        if c.get("status") in ("trial", "read_only", "active"):
            ch["status"] = "active"
            if not c.get("converted_at"):  # the first paid invoice turns a trial into a customer
                ch["converted_at"] = now()
        plan = plan_of(c.get("plan_code"))
        ch["price_locked"] = plan.get("price_monthly", c.get("price_locked"))  # a renewal takes today's price
        db.companies.update_one({"_id": c["_id"]}, {"$set": ch})


@bp.get("/sa/invoices")
@superadmin("billing")
def invoices():
    q = {k: request.args[k] for k in ("status", "company_id") if request.args.get(k)}
    return jsonify(serialize(list(db.platform_invoices.find(q).sort("created_at", -1).limit(500))))


def billing_run(when=None):
    """Daily: trial ended → first invoice; renewal due → invoice; open invoice → a reminder (once a day);
    7 days past due → read-only (nothing deleted); deleted companies past their 30 days are purged."""
    when = when or now()
    issued = readonly = reminders = purged = 0
    day = when.date().isoformat()
    for c in db.companies.find({"deleted_at": None, "status": {"$in": ["trial", "active", "read_only"]}}):
        cid_ = str(c["_id"])
        open_inv = db.platform_invoices.find_one({"company_id": cid_, "status": {"$in": ["due", "overdue"]}, "type": "invoice"})
        trial_over = c.get("status") == "trial" and as_dt(c.get("trial_ends")) and as_dt(c["trial_ends"]) <= when
        renewal_due = c.get("status") == "active" and as_dt(c.get("next_renewal")) and as_dt(c["next_renewal"]) <= when
        if (trial_over or renewal_due) and not open_inv:
            issue_invoice(c)
            issued += 1
            continue
        if open_inv:
            late = (when - open_inv["due_date"]).days if isinstance(open_inv.get("due_date"), datetime) else 0
            if open_inv.get("reminded_on") != day:
                db.platform_invoices.update_one({"_id": open_inv["_id"]}, {"$inc": {"attempts": 1}, "$set": {
                    "reminded_on": day, "status": "overdue" if late > 0 else "due"}})
                reminders += 1
            if late > 0 and c.get("status") != "read_only":
                db.companies.update_one({"_id": c["_id"]}, {"$set": {"status": "read_only", "read_only_since": when}})
                readonly += 1
    for c in db.companies.find({"deleted_at": {"$ne": None}, "purge_after": {"$lte": when}}):
        cid_ = str(c["_id"])
        for name in TENANT_COLLECTIONS + ["files", "audit_logs", "reminders", "lead_files", "estimates", "invoices", "receipts"]:
            db[name].delete_many({"company_id": cid_})
        db.companies.delete_one({"_id": c["_id"]})
        purged += 1
    return {"issued": issued, "reminders": reminders, "read_only": readonly, "purged": purged}


@bp.post("/sa/billing/run")
@superadmin("billing")
def run_billing():
    res = billing_run()
    sa_audit("billing_run", note=str(res))
    return jsonify(res)


@bp.post("/sa/companies/<_id>/invoice")
@superadmin("billing")
def manual_invoice(_id):
    return jsonify(serialize(issue_invoice(load_company(_id), note=(request.get_json(force=True) or {}).get("note")))), 201


@bp.post("/sa/invoices/<_id>/action")
@superadmin("billing")
def invoice_action(_id):
    d = request.get_json(force=True) or {}
    inv = db.platform_invoices.find_one({"_id": oid(_id)}) or abort(404, "invoice not found")
    action = d.get("action")
    if action == "mark_paid":  # bank transfer, cheque
        if inv["status"] not in ("due", "overdue"):
            abort(409, "Only an unpaid invoice is marked paid")
        if d.get("method") not in ("bank_transfer", "cheque", "upi", "cash"):
            abort(400, "How was it paid? bank_transfer, cheque, upi, cash")
        mark_paid(inv, d["method"], (d.get("ref") or "").strip()[:60] or None)
    elif action == "refund":
        if inv["status"] != "paid":
            abort(409, "Only a paid invoice is refunded")
        amount = r2(num(d.get("amount"), "Amount", positive=True) or inv["total"])
        if amount > inv["total"] - inv.get("refunded", 0) + 0.01:
            abort(400, "More than what is left on the invoice")
        reason = (d.get("reason") or "").strip()[:300] or abort(400, "Say why it is refunded")
        sub = r2(amount / (1 + Config.GST_RATE / 100))
        db.platform_invoices.insert_one({"number": next_number("credit", "CN"), "type": "credit_note", "against": inv["number"],
                                         "company_id": inv["company_id"], "company_name": inv["company_name"], "subtotal": -sub,
                                         "gst": -r2(amount - sub), "total": -amount, "status": "refunded", "created_at": now(), "reason": reason})
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$inc": {"refunded": amount}})
    elif action == "void":
        if inv["status"] not in ("due", "overdue"):
            abort(409, "Only an unpaid invoice is voided")
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"status": "void", "void_reason": d.get("reason")}})
    else:
        abort(400, "Unknown action")
    sa_audit(f"invoice_{action}", inv["number"], d.get("reason") or d.get("ref"))
    return jsonify(serialize(db.platform_invoices.find_one({"_id": inv["_id"]})))


@bp.get("/sa/reports/gst")
@superadmin("billing")
def gst_report():
    """Monthly totals of tax collected (paid invoices and refunds) for the GST return."""
    rows = db.platform_invoices.aggregate([
        {"$match": {"status": {"$in": ["paid", "refunded"]}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}}, "taxable": {"$sum": "$subtotal"},
                    "gst": {"$sum": "$gst"}, "cgst": {"$sum": "$cgst"}, "sgst": {"$sum": "$sgst"}, "igst": {"$sum": "$igst"},
                    "total": {"$sum": "$total"}, "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}}])
    return jsonify([{"month": r["_id"], **{k: r2(v) if isinstance(v, float) else v for k, v in r.items() if k != "_id"}} for r in rows])


@bp.get("/sa/reports/overview")
@superadmin("reports")
def reports():
    by_plan, by_city, by_month = {}, {}, {}
    names = {}
    for i in db.platform_invoices.find({"status": "paid"}):
        c = names.get(i["company_id"]) or db.companies.find_one({"_id": oid(i["company_id"])}, {"plan_code": 1, "city": 1}) or {}
        names[i["company_id"]] = c
        by_plan[c.get("plan_code") or "—"] = r2(by_plan.get(c.get("plan_code") or "—", 0) + i["subtotal"])
        by_city[c.get("city") or "—"] = r2(by_city.get(c.get("city") or "—", 0) + i["subtotal"])
        m = i["created_at"].strftime("%Y-%m")
        by_month[m] = r2(by_month.get(m, 0) + i["subtotal"])
    churn = [{"company": c["name"], "reason": c.get("cancel_reason"), "at": c.get("cancelled_at")} for c in db.companies.find({"cancelled_at": {"$ne": None}})]
    trials = db.companies.count_documents({"trial_ends": {"$ne": None}})
    converted = db.companies.count_documents({"converted_at": {"$ne": None}})
    features = []
    for name in TENANT_COLLECTIONS:
        if name in ("users", "notifications", "stage_templates", "message_templates", "support_tickets"):
            continue
        features.append({"feature": name, "records": db[name].estimated_document_count(),
                         "companies": len(db[name].distinct("company_id"))})
    features.sort(key=lambda f: -f["records"])
    return jsonify(serialize({"by_plan": by_plan, "by_city": by_city, "by_month": dict(sorted(by_month.items())), "churn": churn,
                              "cancel_reasons": {r: sum(1 for x in churn if x["reason"] == r) for r in {x["reason"] for x in churn}},
                              "trial_conversion": round(converted / trials * 100, 1) if trials else None,
                              "feature_usage": features[:12], "least_used": features[-6:]}))


def near_limits(c):
    u, lim = usage(c), limits(c)
    near = []
    for key, used in (("users", u["users"]), ("projects", u["projects"]), ("whatsapp", u["whatsapp_messages"]),
                      ("storage_gb", u["storage_bytes"] / 1024 ** 3)):
        cap = lim.get(key)
        if cap and used >= cap * 0.8:
            near.append({"what": key, "used": round(used, 2), "limit": cap})
    return u, lim, near


@bp.get("/sa/usage")
@superadmin("dashboard")
def usage_report():
    rows = []
    for c in db.companies.find({"deleted_at": None}):
        u, lim, near = near_limits(c)
        rows.append({"id": str(c["_id"]), "name": c["name"], "plan": lim["plan"], "usage": u, "limits": lim,
                     "whatsapp_cost": r2(u["whatsapp_messages"] * WA_COST * (1 + Config.GST_RATE / 100)),
                     "pays_monthly": r2(monthly_value(c)), "near_limit": near})
    return jsonify(rows)


# ============================== support, announcements, settings ==============================
@bp.get("/sa/tickets")
@superadmin("support")
def tickets():
    q = {"status": request.args["status"]} if request.args.get("status") else {}
    return jsonify(serialize(list(db.support_tickets.find(q).sort("created_at", -1).limit(300))))


@bp.post("/sa/tickets/<_id>/reply")
@superadmin("support")
def ticket_reply(_id):
    d = request.get_json(force=True) or {}
    tk = db.support_tickets.find_one({"_id": oid(_id)}) or abort(404, "ticket not found")
    text = (d.get("text") or "").strip()[:4000]
    if not text and not d.get("status"):
        abort(400, "Write a reply")
    upd = {"$set": {"updated_at": now()}}
    if text:
        upd["$push"] = {"replies": {"by": g.sa.get("name"), "side": "support", "text": text, "at": now()}}
    if d.get("status") in ("open", "waiting", "closed"):
        upd["$set"]["status"] = d["status"]
    db.support_tickets.update_one({"_id": tk["_id"]}, upd)
    if text:
        from ..services import notify
        comp = db.companies.find_one({"_id": oid(tk["company_id"])})
        if comp:
            notify.send("support_reply", [tk["user_id"]], f"Support answered your ticket “{tk['subject']}”", "/app/settings?tab=support",
                        company=comp, skip_self=False)
    sa_audit("ticket_reply", _id)
    return jsonify(serialize(db.support_tickets.find_one({"_id": tk["_id"]})))


@bp.get("/sa/announcements")
@superadmin("dashboard")
def announcements():
    return jsonify(serialize(list(db.announcements.find().sort("created_at", -1))))


@bp.post("/sa/announcements")
@superadmin("announcements")
def announce():
    d = request.get_json(force=True) or {}
    title = (d.get("title") or "").strip()[:150] or abort(400, "Give the announcement a title")
    aud = d.get("audience") or {}
    doc = {"title": title, "body": (d.get("body") or "").strip()[:4000], "kind": d.get("kind") if d.get("kind") in ("feature", "maintenance", "billing") else "feature",
           "audience": {"plans": [p for p in aud.get("plans") or []], "statuses": [s for s in aud.get("statuses") or [] if s in STATUSES]},
           "active": True, "email": bool(d.get("email")), "created_at": now(), "by": g.sa.get("name"), "emailed": 0}
    doc["_id"] = db.announcements.insert_one(doc).inserted_id
    if doc["email"]:
        from ..services import notify
        for c in db.companies.find(audience_query(doc)):
            if c.get("owner_email"):
                notify.deliver(platform_mail(), c["owner_email"], doc["title"], doc["body"])
                doc["emailed"] += 1
        db.announcements.update_one({"_id": doc["_id"]}, {"$set": {"emailed": doc["emailed"]}})
    sa_audit("announcement", note=title)
    return jsonify(serialize(doc)), 201


def audience_query(a):
    q = {"deleted_at": None}
    if a["audience"].get("plans"):
        q["plan_code"] = {"$in": a["audience"]["plans"]}
    if a["audience"].get("statuses"):
        q["status"] = {"$in": a["audience"]["statuses"]}
    return q


@bp.put("/sa/announcements/<_id>")
@superadmin("announcements")
def update_announcement(_id):
    d = request.get_json(force=True) or {}
    db.announcements.update_one({"_id": oid(_id)}, {"$set": {"active": bool(d.get("active"))}})
    sa_audit("announcement_active", _id, str(bool(d.get("active"))))
    return jsonify({"ok": True})


SECRETS = ("whatsapp_token", "smtp_password", "gateway_secret", "sms_key")


def masked_settings():
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    for k in SECRETS:
        if s.get(k):
            s[k] = "••••" + str(s[k])[-4:]
    s.pop("_id", None)
    return s


@bp.get("/sa/settings")
@superadmin("dashboard")
def get_settings():
    return jsonify(serialize(masked_settings()))


@bp.put("/sa/settings")
@superadmin("settings")
def save_settings():
    d = request.get_json(force=True) or {}
    allowed = ("platform_name", "logo_url", "login_message", "default_tax_rate", "default_currency", "terms", "privacy",
               "whatsapp_phone_id", "whatsapp_token", "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from",
               "gateway", "gateway_key", "gateway_secret", "sms_provider", "sms_key", "signup_needs_approval")
    ch = {k: v for k, v in d.items() if k in allowed and not (isinstance(v, str) and v.startswith("••••"))}
    if "smtp_host" in ch or "smtp_user" in ch:
        cur = db.platform_settings.find_one({"_id": "settings"}) or {}
        ch["email_out"] = {"host": ch.get("smtp_host", cur.get("smtp_host")), "port": int(ch.get("smtp_port", cur.get("smtp_port")) or 587),
                           "user": ch.get("smtp_user", cur.get("smtp_user")), "password": ch.get("smtp_password", cur.get("smtp_password")),
                           "from_email": ch.get("smtp_from", cur.get("smtp_from"))}
    db.platform_settings.update_one({"_id": "settings"}, {"$set": ch}, upsert=True)
    sa_audit("settings", note=", ".join(k for k in ch if k not in SECRETS) + (" + secrets" if any(k in SECRETS for k in ch) else ""))
    return jsonify(serialize(masked_settings()))


@bp.get("/public/legal/<kind>")
def legal(kind):
    if kind not in ("terms", "privacy"):
        abort(404)
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    return jsonify({"kind": kind, "text": s.get(kind) or "", "platform": s.get("platform_name") or "BuildSuite"})


@bp.get("/public/platform")
def public_platform():
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    return jsonify({"name": s.get("platform_name") or "BuildSuite", "logo_url": s.get("logo_url"), "login_message": s.get("login_message")})


# ============================== the company's side ==============================
def owner_only():
    if g.role != "owner":
        abort(403, "Only the Owner manages the subscription")


@bp.get("/billing/subscription")
@api(None)
def my_subscription():
    owner_only()
    c = g.company
    u, lim, near = near_limits(c)
    return jsonify(serialize({"plan": plan_of(c.get("plan_code")), "status": c.get("status"), "billing_cycle": c.get("billing_cycle") or "monthly",
                              "trial_ends": c.get("trial_ends"), "next_renewal": c.get("next_renewal"), "price_locked": c.get("price_locked"),
                              "coupon": c.get("coupon"), "addons": c.get("addons") or {}, "usage": u, "limits": lim, "near_limit": near,
                              "plans": list(db.plans.find({"active": True}).sort("price_monthly", 1)),
                              "invoices": list(db.platform_invoices.find({"company_id": g.cid}).sort("created_at", -1).limit(50)),
                              "export_requested": c.get("export_requested"), "addon_prices": ADDON_PRICES}))


@bp.post("/billing/change")
@api(None)
def change_plan():
    """Upgrade, downgrade or switch cycle: the change starts now; the unused part of the old plan is credited."""
    owner_only()
    c = g.company
    d = request.get_json(force=True) or {}
    plan = db.plans.find_one({"code": d.get("plan_code") or c.get("plan_code"), "active": True}) or abort(404, "Plan not found")
    cycle = d.get("billing_cycle") or c.get("billing_cycle") or "monthly"
    if cycle not in ("monthly", "yearly"):
        abort(400, "Monthly or yearly")
    from ..services.subscription import counted_users, active_projects
    if plan.get("max_users") and counted_users(g.cid) > plan["max_users"] + (c.get("addons") or {}).get("extra_users", 0):
        abort(409, f"You have more users than the {plan['name']} plan allows; deactivate some first")
    if plan.get("max_projects") and active_projects(g.cid) > plan["max_projects"]:
        abort(409, f"You have more active projects than the {plan['name']} plan allows")
    if plan.get("max_modules") and len(c.get("modules") or []) > plan["max_modules"]:
        abort(409, f"The {plan['name']} plan includes {plan['max_modules']} module(s); switch some off first")
    old = plan_of(c.get("plan_code"))
    if d.get("coupon"):
        apply_coupon(c, d["coupon"])
    db.companies.update_one({"_id": c["_id"]}, {"$set": {"plan_code": plan["code"], "billing_cycle": cycle, "price_locked": plan["price_monthly"]}})
    fresh = db.companies.find_one({"_id": c["_id"]})
    inv = None
    if c.get("status") != "trial":
        for o in db.platform_invoices.find({"company_id": g.cid, "status": {"$in": ["due", "overdue"]}, "type": "invoice"}):
            db.platform_invoices.update_one({"_id": o["_id"]}, {"$set": {"status": "void", "void_reason": "replaced by a plan change"}})
        inv = issue_invoice(fresh, prorate_from=old if old.get("code") != plan["code"] else None, note="Plan change")
    db.sa_audit.insert_one({"by": g.user.get("name"), "role": "company owner", "action": "company_plan_change", "target": g.cid,
                            "note": f"{old.get('code')} → {plan['code']} ({cycle})", "at": now()})
    return jsonify(serialize({"plan": plan, "invoice": inv}))


@bp.post("/billing/cancel")
@api(None)
def cancel():
    owner_only()
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:300] or abort(400, "Tell us why you are leaving")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"cancelled_at": now(), "cancel_reason": reason, "status": "cancelled"}})
    db.sa_audit.insert_one({"by": g.user.get("name"), "role": "company owner", "action": "company_cancelled", "target": g.cid, "note": reason, "at": now()})
    return jsonify({"ok": True, "message": "Cancelled. Your data stays read-only; ask for an export from here any time."})


@bp.post("/billing/invoices/<_id>/pay")
@api(None)
def pay_invoice(_id):
    """Card / UPI payment of a platform invoice. The sandbox gateway pays at once (no real money); a live gateway
    sends the payment through its signed webhook, as company payments do (Phase G)."""
    owner_only()
    inv = db.platform_invoices.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404, "invoice not found")
    if inv["status"] not in ("due", "overdue"):
        abort(409, "This invoice is not open")
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    if (s.get("gateway") or "sandbox") != "sandbox":
        abort(409, "Pay by bank transfer to the account on the invoice; online card payment is not set up yet")
    mark_paid(inv, "sandbox", f"SBX-{uuid.uuid4().hex[:10]}")
    return jsonify(serialize(db.platform_invoices.find_one({"_id": inv["_id"]})))


@bp.post("/billing/export")
@api(None)
def request_export():
    owner_only()
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"export_requested": now()}})
    return jsonify({"ok": True})


@bp.get("/support/tickets")
@api(None)
def my_tickets():
    q = {"company_id": g.cid} if g.role == "owner" else {"company_id": g.cid, "user_id": g.uid}
    return jsonify(serialize(list(db.support_tickets.find(q).sort("created_at", -1).limit(100))))


@bp.post("/support/tickets")
@api(None)
def raise_ticket():
    d = request.get_json(force=True) or {}
    subject = (d.get("subject") or "").strip()[:150] or abort(400, "What is it about?")
    text = (d.get("text") or "").strip()[:4000] or abort(400, "Describe the problem")
    doc = {"company_id": g.cid, "company_name": g.company["name"], "user_id": g.uid, "user_name": g.user.get("name"), "subject": subject,
           "priority": d.get("priority") if d.get("priority") in ("low", "normal", "high") else "normal", "status": "open",
           "replies": [{"by": g.user.get("name"), "side": "company", "text": text, "at": now()}], "created_at": now(), "updated_at": now()}
    doc["_id"] = db.support_tickets.insert_one(doc).inserted_id
    return jsonify(serialize(doc)), 201


@bp.post("/support/tickets/<_id>/reply")
@api(None)
def reply_ticket(_id):
    tk = db.support_tickets.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404, "ticket not found")
    if g.role != "owner" and tk["user_id"] != g.uid:
        abort(404, "ticket not found")
    text = ((request.get_json(force=True) or {}).get("text") or "").strip()[:4000] or abort(400, "Write a reply")
    db.support_tickets.update_one({"_id": tk["_id"]}, {"$push": {"replies": {"by": g.user.get("name"), "side": "company", "text": text, "at": now()}},
                                                        "$set": {"status": "open", "updated_at": now()}})
    return jsonify(serialize(db.support_tickets.find_one({"_id": tk["_id"]})))


@bp.get("/announcements")
@api(None)
def my_announcements():
    rows = []
    for a in db.announcements.find({"active": True}).sort("created_at", -1).limit(20):
        aud = a.get("audience") or {}
        if aud.get("plans") and g.company.get("plan_code") not in aud["plans"]:
            continue
        if aud.get("statuses") and g.company.get("status") not in aud["statuses"]:
            continue
        rows.append({"id": str(a["_id"]), "title": a["title"], "body": a.get("body"), "kind": a.get("kind"), "at": a["created_at"]})
    return jsonify(serialize(rows))


def check_usage_alerts(now_):
    """Worker (per company): near a plan limit (80 %) → the Owners, once a month per limit."""
    from ..services import notify, project_events
    _, lim, near = near_limits(g.company)
    month = now_.strftime("%Y-%m")
    for n in near:
        notify.send("plan_limit", project_events.owners(), f"You have used {n['used']:g} of the {n['limit']:g} {n['what'].replace('_', ' ')} "
                    f"in your {lim['plan']} plan — upgrade or add more in Settings → Subscription", "/app/settings?tab=subscription",
                    key=f"limit:{n['what']}:{month}", level="warn")
