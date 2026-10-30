"""Super Admin panel (section 18). Platform-level only: never returns a company's private data."""
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from ..config import Config
from ..crud import num
from ..db import db, oid, serialize
from ..security import superadmin, check_password, create_token, hash_password
from ..services.defaults import COMPANY_TYPES
from ..services.subscription import usage, limits
from ..services.tenant_setup import bootstrap_company
from ..tenancy import now

bp = Blueprint("superadmin", __name__)

COMPANY_PUBLIC = ("name", "types", "modules", "plan_code", "billing_cycle", "status", "trial_ends", "next_renewal",
                  "city", "gstin", "phone", "owner_email", "created_at", "addons", "price_locked", "coupon",
                  "cancelled_at", "cancel_reason", "deleted_at", "allow_support_login", "notes", "feature_flags")


def sa_audit(action, target=None, note=None):
    db.sa_audit.insert_one({"by": g.sa.get("name"), "by_id": g.sa.get("uid"), "role": g.sa.get("role"),
                            "action": action, "target": target, "note": note, "at": now()})


def _company(c):
    data = {k: c.get(k) for k in COMPANY_PUBLIC}
    data["id"] = str(c["_id"])
    return serialize(data)


@bp.post("/sa/login")
def login():
    d = request.get_json(force=True) or {}
    u = db.superadmin_users.find_one({"email": (d.get("email") or "").lower()})
    if not u or not check_password(d.get("password", ""), u["password"]):
        abort(401, "Wrong email or password")
    # two-factor: a 6-digit code is required (demo code is shown in README / seeded as totp_demo)
    if u.get("totp_demo") and d.get("code") != u["totp_demo"]:
        abort(401, "Two-factor code required" if not d.get("code") else "Wrong two-factor code")
    token = create_token({"uid": str(u["_id"]), "kind": "superadmin", "role": u["role"], "name": u["name"]})
    db.sa_audit.insert_one({"by": u["name"], "action": "login", "at": now()})
    return jsonify({"token": token, "user": serialize(u)})


# ---------------- dashboard ----------------
def _monthly_value(c):
    plan = db.plans.find_one({"code": c.get("plan_code")}) or {}
    if c.get("billing_cycle") == "yearly":
        return (c.get("price_locked") or plan.get("price_yearly", 0)) / 12
    return c.get("price_locked") or plan.get("price_monthly", 0)


@bp.get("/sa/dashboard")
@superadmin("dashboard")
def dashboard():
    companies = list(db.companies.find({"deleted_at": None}))
    by_status = {}
    for c in companies:
        by_status[c.get("status", "trial")] = by_status.get(c.get("status", "trial"), 0) + 1
    month = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (month - timedelta(days=1)).replace(day=1)
    paid = lambda a, b: sum(i["total"] for i in db.platform_invoices.find(
        {"status": "paid", "paid_at": {"$gte": a, "$lt": b}}))
    year_start = month.replace(month=1)
    overdue = []
    for i in db.platform_invoices.find({"status": {"$in": ["due", "overdue"]}}):
        days = (now() - i["due_date"]).days if isinstance(i.get("due_date"), datetime) else 0
        if days > 0:
            overdue.append({"company": i.get("company_name"), "company_id": i["company_id"], "number": i["number"],
                            "amount": i["total"], "days_late": days})
    storage = sum(f.get("size", 0) for f in db.files.find({}, {"size": 1}))
    return jsonify({
        "companies": {"total": len(companies), **by_status},
        "mrr": round(sum(_monthly_value(c) for c in companies if c.get("status") == "active"), 2),
        "revenue_this_month": round(paid(month, now() + timedelta(days=1)), 2),
        "revenue_last_month": round(paid(last_month, month), 2),
        "revenue_this_year": round(paid(year_start, now() + timedelta(days=1)), 2),
        "signups_this_month": db.companies.count_documents({"created_at": {"$gte": month}}),
        "trials_converted": db.companies.count_documents({"converted_at": {"$gte": month}}),
        "cancellations_this_month": db.companies.count_documents({"cancelled_at": {"$gte": month}}),
        "overdue": sorted(overdue, key=lambda x: -x["days_late"]),
        "health": {"api": "ok", "db": "ok" if db.command("ping").get("ok") else "down",
                   "errors_24h": 0, "storage_bytes": storage},
    })


# ---------------- companies ----------------
@bp.get("/sa/companies")
@superadmin("companies")
def companies():
    q = {"deleted_at": None} if request.args.get("deleted") != "1" else {"deleted_at": {"$ne": None}}
    for k in ("plan_code", "status", "city"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("q"):
        q["name"] = {"$regex": request.args["q"], "$options": "i"}
    if request.args.get("from"):
        q["created_at"] = {"$gte": datetime.fromisoformat(request.args["from"])}
    out = []
    for c in db.companies.find(q).sort("created_at", -1):
        row = _company(c)
        row["usage"] = usage(c)
        out.append(row)
    return jsonify(out)


@bp.get("/sa/companies/<_id>")
@superadmin("companies")
def company(_id):
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    owner = db.users.find_one({"company_id": _id, "role": "owner"}, {"name": 1, "email": 1, "phone": 1})
    return jsonify({**_company(c), "owner": serialize(owner), "usage": usage(c), "limits": limits(c),
                    "invoices": serialize(list(db.platform_invoices.find({"company_id": _id}).sort("created_at", -1))),
                    "tickets": serialize(list(db.support_tickets.find({"company_id": _id}).sort("created_at", -1))),
                    "support_sessions": serialize(list(db.sa_audit.find({"target": _id, "action": "login_as"})))})


@bp.post("/sa/companies")
@superadmin("companies")
def create_company():
    d = request.get_json(force=True) or {}
    if not d.get("name") or not d.get("owner_email"):
        abort(400, "Company name and owner email are required")
    email = d["owner_email"].lower()
    if db.users.find_one({"email": email}):
        abort(409, "Owner email already in use")
    types = d.get("types") or ["contractor"]
    c = {"name": d["name"], "types": types, "modules": [COMPANY_TYPES[t] for t in types if t in COMPANY_TYPES],
         "plan_code": d.get("plan_code", "basic"), "billing_cycle": d.get("billing_cycle", "monthly"),
         "status": "trial", "trial_ends": now() + timedelta(days=Config.TRIAL_DAYS), "city": d.get("city"),
         "gstin": d.get("gstin"), "currency": "INR", "tax_rate": 18.0, "tax_label": "GST",
         "branding": {"primary": "#1f6feb"}, "counters": {}, "numbering": {}, "owner_email": email,
         "created_at": now(), "onboarded_by": g.sa.get("name")}
    c["_id"] = db.companies.insert_one(c).inserted_id
    pw = d.get("password") or uuid.uuid4().hex[:10]
    db.users.insert_one({"company_id": str(c["_id"]), "name": d.get("owner_name") or "Owner", "email": email,
                         "password": hash_password(pw), "role": "owner", "kind": "staff", "active": True,
                         "created_at": now()})
    bootstrap_company(str(c["_id"]), c["modules"])
    sa_audit("create_company", str(c["_id"]), c["name"])
    return jsonify({**_company(c), "temp_password": pw}), 201


@bp.post("/sa/companies/<_id>/action")
@superadmin("companies")
def company_action(_id):
    d = request.get_json(force=True) or {}
    action = d.get("action")
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    changes = {}
    if action == "approve" or action == "reactivate":
        changes = {"status": "active" if c.get("status") != "trial" or action == "reactivate" else "trial",
                   "suspended_at": None}
        if action == "approve":
            changes["approved_at"] = now()
    elif action == "suspend":
        changes = {"status": "suspended", "suspended_at": now(), "suspend_reason": d.get("reason")}
    elif action == "delete":
        # deletion keeps a backup for 30 days
        changes = {"deleted_at": now(), "purge_after": now() + timedelta(days=30), "status": "cancelled"}
    elif action == "restore":
        changes = {"deleted_at": None, "purge_after": None, "status": "active"}
    elif action == "extend_trial":
        base = c.get("trial_ends") if isinstance(c.get("trial_ends"), datetime) and c["trial_ends"] > now() else now()
        changes = {"trial_ends": base + timedelta(days=int(num(d.get("days"), 7))), "status": "trial"}
    elif action == "free_months":
        base = c.get("next_renewal") if isinstance(c.get("next_renewal"), datetime) else now()
        changes = {"next_renewal": base + timedelta(days=30 * int(num(d.get("months"), 1))), "status": "active"}
    elif action == "change_plan":
        plan = db.plans.find_one({"code": d.get("plan_code")}) or abort(404, "Plan not found")
        changes = {"plan_code": plan["code"], "price_locked": plan["price_monthly"]}
    elif action == "modules":
        changes = {"modules": d.get("modules", [])}
    elif action == "features":
        changes = {"feature_flags": d.get("features", {})}
    elif action == "note":
        db.companies.update_one({"_id": c["_id"]}, {"$push": {"notes": {"text": d.get("text"), "by": g.sa.get("name"),
                                                                         "at": now()}}})
    elif action == "reset_owner_password":
        pw = uuid.uuid4().hex[:10]
        db.users.update_one({"company_id": _id, "role": "owner"}, {"$set": {"password": hash_password(pw)}})
        sa_audit("reset_password", _id)
        return jsonify({"temp_password": pw})
    else:
        abort(400, "Unknown action")
    if changes:
        db.companies.update_one({"_id": c["_id"]}, {"$set": changes})
    sa_audit(action, _id, d.get("reason") or d.get("text"))
    return jsonify(_company(db.companies.find_one({"_id": c["_id"]})))


@bp.post("/sa/companies/<_id>/login-as")
@superadmin("support")
def login_as(_id):
    """Log in as a company to help — only with its permission, always logged."""
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    if not c.get("allow_support_login"):
        abort(403, "The company has not allowed support access")
    owner = db.users.find_one({"company_id": _id, "role": "owner"}) or abort(404)
    token = create_token({"uid": str(owner["_id"]), "cid": _id, "role": "owner", "kind": "staff",
                          "name": f"{g.sa.get('name')} (support)", "support_session": True})
    sa_audit("login_as", _id, "Support session")
    return jsonify({"token": token})


@bp.get("/sa/companies/<_id>/export")
@superadmin("support")
def export(_id):
    """Data export for a company on request (their data belongs to them)."""
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    if not c.get("export_requested") and not request.args.get("force"):
        abort(403, "The company has not requested an export")
    from ..db import TENANT_COLLECTIONS
    data = {name: serialize(list(db[name].find({"company_id": _id}))) for name in TENANT_COLLECTIONS}
    sa_audit("export", _id)
    return jsonify(data)


# ---------------- plans & coupons ----------------
@bp.get("/sa/plans")
@superadmin("dashboard")
def plans():
    return jsonify(serialize(list(db.plans.find().sort("price_monthly", 1))))


@bp.post("/sa/plans")
@bp.put("/sa/plans/<_id>")
@superadmin("plans")
def save_plan(_id=None):
    d = request.get_json(force=True) or {}
    fields = ("code", "name", "price_monthly", "max_users", "max_projects", "max_modules", "whatsapp_messages",
              "storage_gb", "support", "viewer", "active", "features")
    plan = {k: d.get(k) for k in fields if k in d}
    for k in ("price_monthly", "max_users", "max_projects", "max_modules", "whatsapp_messages", "storage_gb"):
        if k in plan and plan[k] not in (None, ""):
            plan[k] = num(plan[k])
        elif k in plan:
            plan[k] = None
    if "price_monthly" in plan:
        plan["price_yearly"] = plan["price_monthly"] * 10  # yearly = 2 months free
        plan["price_monthly_gst"] = round(plan["price_monthly"] * 1.18, 2)
    if _id:
        # existing companies keep their price until renewal (price_locked on the company)
        db.plans.update_one({"_id": oid(_id)}, {"$set": plan})
    else:
        plan.setdefault("active", True)
        _id = db.plans.insert_one(plan).inserted_id
    sa_audit("save_plan", str(_id), plan.get("name"))
    return jsonify(serialize(db.plans.find_one({"_id": oid(_id)})))


@bp.get("/sa/coupons")
@superadmin("coupons")
def coupons():
    return jsonify(serialize(list(db.coupons.find().sort("created_at", -1))))


@bp.post("/sa/coupons")
@superadmin("coupons")
def create_coupon():
    d = request.get_json(force=True) or {}
    doc = {"code": (d.get("code") or "").upper(), "percent": num(d.get("percent")), "months": int(num(d.get("months"), 1)),
           "active": True, "created_at": now(), "description": d.get("description")}
    if not doc["code"]:
        abort(400, "Code required")
    db.coupons.insert_one(doc)
    sa_audit("create_coupon", doc["code"])
    return jsonify(serialize(doc)), 201


@bp.put("/sa/coupons/<_id>")
@superadmin("coupons")
def update_coupon(_id):
    d = request.get_json(force=True) or {}
    db.coupons.update_one({"_id": oid(_id)}, {"$set": {"active": bool(d.get("active"))}})
    return jsonify({"ok": True})


# ---------------- billing ----------------
def issue_invoice(company, prorate_from=None):
    """Platform GST invoice for a subscription period."""
    plan = db.plans.find_one({"code": company.get("plan_code")}) or abort(400, "Company has no plan")
    yearly = company.get("billing_cycle") == "yearly"
    base = plan["price_yearly"] if yearly else plan["price_monthly"]
    lines = [{"description": f"{plan['name']} plan — {'yearly' if yearly else 'monthly'}", "sac": Config.PLATFORM_SAC,
              "amount": base}]
    addons = company.get("addons", {})
    if addons.get("extra_users"):
        lines.append({"description": f"Extra users × {addons['extra_users']}", "sac": Config.PLATFORM_SAC,
                      "amount": 500 * addons["extra_users"] * (12 if yearly else 1)})
    if addons.get("extra_storage_gb"):
        packs = addons["extra_storage_gb"] // 100
        lines.append({"description": f"Extra storage {addons['extra_storage_gb']} GB", "sac": Config.PLATFORM_SAC,
                      "amount": 500 * packs * (12 if yearly else 1)})
    if prorate_from and prorate_from != plan["code"] and isinstance(company.get("next_renewal"), datetime):
        old = db.plans.find_one({"code": prorate_from}) or {}
        days_left = max((company["next_renewal"] - now()).days, 0)
        credit = round((old.get("price_monthly", 0)) * days_left / 30, 2)
        if credit:
            lines.append({"description": f"Proration credit for unused {old.get('name')} ({days_left} days)",
                          "sac": Config.PLATFORM_SAC, "amount": -credit})
    sub = sum(l["amount"] for l in lines)
    coupon = company.get("coupon")
    if coupon and coupon.get("months_left", 0) > 0:
        disc = round(sub * coupon["percent"] / 100, 2)
        lines.append({"description": f"Coupon {coupon['code']} ({coupon['percent']}% off)", "amount": -disc,
                      "sac": Config.PLATFORM_SAC})
        sub -= disc
        db.companies.update_one({"_id": company["_id"]}, {"$inc": {"coupon.months_left": -1}})
    sub = max(round(sub, 2), 0)
    gst = round(sub * Config.GST_RATE / 100, 2)
    counter = db.platform_counters.find_one_and_update({"_id": "invoice"}, {"$inc": {"n": 1}}, upsert=True,
                                                       return_document=True)
    inv = {"number": f"BS/{now().year}/{counter['n']:05d}", "company_id": str(company["_id"]),
           "company_name": company["name"], "company_gstin": company.get("gstin"),
           "platform_gstin": Config.PLATFORM_GSTIN, "lines": lines, "subtotal": sub,
           "cgst": round(gst / 2, 2), "sgst": round(gst / 2, 2), "gst": gst, "total": round(sub + gst, 2),
           "status": "due", "due_date": now() + timedelta(days=Config.GRACE_DAYS), "created_at": now(),
           "period": "yearly" if yearly else "monthly", "attempts": 0}
    inv["_id"] = db.platform_invoices.insert_one(inv).inserted_id
    return inv


@bp.get("/sa/invoices")
@superadmin("billing")
def invoices():
    q = {}
    for k in ("status", "company_id"):
        if request.args.get(k):
            q[k] = request.args[k]
    return jsonify(serialize(list(db.platform_invoices.find(q).sort("created_at", -1).limit(500))))


@bp.post("/sa/billing/run")
@superadmin("billing")
def run_billing():
    """Daily billing job: trials ending, renewals due, failed-payment retries, grace period -> read-only."""
    issued, readonly, reminders = 0, 0, 0
    for c in db.companies.find({"deleted_at": None, "status": {"$in": ["trial", "active", "read_only"]}}):
        trial_over = c.get("status") == "trial" and isinstance(c.get("trial_ends"), datetime) and c["trial_ends"] <= now()
        renewal_due = c.get("status") == "active" and isinstance(c.get("next_renewal"), datetime) and c["next_renewal"] <= now()
        open_inv = db.platform_invoices.find_one({"company_id": str(c["_id"]), "status": {"$in": ["due", "overdue"]}})
        if (trial_over or renewal_due) and not open_inv:
            issue_invoice(c)
            issued += 1
            if trial_over:
                db.companies.update_one({"_id": c["_id"]}, {"$set": {"status": "active", "converted_at": now(),
                                                                     "next_renewal": now() + timedelta(days=30)}})
        if open_inv:
            db.platform_invoices.update_one({"_id": open_inv["_id"]}, {"$inc": {"attempts": 1},
                                                                       "$set": {"status": "overdue"}
                                                                       if open_inv["due_date"] < now() else {}})
            reminders += 1
            if open_inv["due_date"] < now() and c.get("status") != "read_only":
                db.companies.update_one({"_id": c["_id"]}, {"$set": {"status": "read_only"}})
                readonly += 1
    sa_audit("billing_run", note=f"{issued} invoices, {reminders} reminders, {readonly} read-only")
    return jsonify({"issued": issued, "reminders": reminders, "read_only": readonly})


@bp.post("/sa/companies/<_id>/invoice")
@superadmin("billing")
def manual_invoice(_id):
    c = db.companies.find_one({"_id": oid(_id)}) or abort(404)
    return jsonify(serialize(issue_invoice(c))), 201


@bp.post("/sa/invoices/<_id>/action")
@superadmin("billing")
def invoice_action(_id):
    d = request.get_json(force=True) or {}
    inv = db.platform_invoices.find_one({"_id": oid(_id)}) or abort(404)
    if d.get("action") == "mark_paid":
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {
            "status": "paid", "paid_at": now(), "method": d.get("method", "bank_transfer"), "ref": d.get("ref")}})
        c = db.companies.find_one({"_id": oid(inv["company_id"])})
        renewal = now() + timedelta(days=365 if c.get("billing_cycle") == "yearly" else 30)
        db.companies.update_one({"_id": c["_id"]}, {"$set": {"status": "active", "next_renewal": renewal}})
    elif d.get("action") == "refund":
        amount = num(d.get("amount"), inv["total"])
        counter = db.platform_counters.find_one_and_update({"_id": "credit"}, {"$inc": {"n": 1}}, upsert=True,
                                                           return_document=True)
        db.platform_invoices.insert_one({
            "number": f"CN/{now().year}/{counter['n']:05d}", "type": "credit_note", "against": inv["number"],
            "company_id": inv["company_id"], "company_name": inv["company_name"], "subtotal": -round(amount / 1.18, 2),
            "gst": -round(amount - amount / 1.18, 2), "total": -amount, "status": "refunded", "created_at": now(),
            "reason": d.get("reason")})
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"refunded": amount}})
    elif d.get("action") == "void":
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"status": "void"}})
    else:
        abort(400, "Unknown action")
    sa_audit(f"invoice_{d.get('action')}", inv["number"])
    return jsonify(serialize(db.platform_invoices.find_one({"_id": inv["_id"]})))


@bp.get("/sa/reports/gst")
@superadmin("billing")
def gst_report():
    rows = db.platform_invoices.aggregate([
        {"$match": {"status": {"$in": ["paid", "refunded"]}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}},
                    "taxable": {"$sum": "$subtotal"}, "gst": {"$sum": "$gst"}, "total": {"$sum": "$total"},
                    "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}}])
    return jsonify([{"month": r["_id"], **{k: round(v, 2) if isinstance(v, float) else v
                                           for k, v in r.items() if k != "_id"}} for r in rows])


@bp.get("/sa/reports/overview")
@superadmin("reports")
def reports():
    by_plan, by_city, by_month = {}, {}, {}
    for i in db.platform_invoices.find({"status": "paid"}):
        c = db.companies.find_one({"_id": oid(i["company_id"])}, {"plan_code": 1, "city": 1}) or {}
        by_plan[c.get("plan_code") or "—"] = by_plan.get(c.get("plan_code") or "—", 0) + i["subtotal"]
        by_city[c.get("city") or "—"] = by_city.get(c.get("city") or "—", 0) + i["subtotal"]
        m = i["created_at"].strftime("%Y-%m")
        by_month[m] = by_month.get(m, 0) + i["subtotal"]
    churn = [{"company": c["name"], "reason": c.get("cancel_reason"), "at": c.get("cancelled_at")}
             for c in db.companies.find({"cancelled_at": {"$ne": None}})]
    total_trials = db.companies.count_documents({"trial_ends": {"$ne": None}})
    converted = db.companies.count_documents({"converted_at": {"$ne": None}})
    features = []
    from ..db import TENANT_COLLECTIONS
    for name in TENANT_COLLECTIONS:
        if name in ("users", "notifications", "stage_templates", "message_templates", "support_tickets"):
            continue
        features.append({"feature": name, "records": db[name].estimated_document_count()})
    features.sort(key=lambda f: -f["records"])
    return jsonify({"by_plan": by_plan, "by_city": by_city, "by_month": dict(sorted(by_month.items())),
                    "churn": serialize(churn),
                    "trial_conversion": round(converted / total_trials * 100, 1) if total_trials else None,
                    "feature_usage": features})


@bp.get("/sa/usage")
@superadmin("dashboard")
def usage_report():
    rows = []
    for c in db.companies.find({"deleted_at": None}):
        u, lim = usage(c), limits(c)
        wa_cost = round(u["whatsapp_messages"] * 0.115 * 1.18, 2)
        near = []
        if lim["users"] and u["users"] >= lim["users"] * 0.8:
            near.append("users")
        if lim["projects"] and u["projects"] >= lim["projects"] * 0.8:
            near.append("projects")
        if lim["whatsapp"] and u["whatsapp_messages"] >= lim["whatsapp"] * 0.8:
            near.append("whatsapp")
        rows.append({"id": str(c["_id"]), "name": c["name"], "plan": lim["plan"], "usage": u, "limits": lim,
                     "whatsapp_cost": wa_cost, "pays_monthly": round(_monthly_value(c), 2), "near_limit": near})
    return jsonify(rows)


# ---------------- support, announcements, settings, audit ----------------
@bp.get("/sa/tickets")
@superadmin("support")
def tickets():
    q = {"status": request.args["status"]} if request.args.get("status") else {}
    return jsonify(serialize(list(db.support_tickets.find(q).sort("created_at", -1))))


@bp.post("/sa/tickets/<_id>/reply")
@superadmin("support")
def ticket_reply(_id):
    d = request.get_json(force=True) or {}
    upd = {"$push": {"replies": {"by": g.sa.get("name"), "side": "support", "text": d.get("text"), "at": now()}}}
    if d.get("status"):
        upd["$set"] = {"status": d["status"]}
    db.support_tickets.update_one({"_id": oid(_id)}, upd)
    sa_audit("ticket_reply", _id)
    return jsonify(serialize(db.support_tickets.find_one({"_id": oid(_id)})))


@bp.get("/sa/announcements")
@superadmin("dashboard")
def announcements():
    return jsonify(serialize(list(db.announcements.find().sort("created_at", -1))))


@bp.post("/sa/announcements")
@superadmin("announcements")
def announce():
    d = request.get_json(force=True) or {}
    doc = {"title": d.get("title"), "body": d.get("body"), "kind": d.get("kind", "feature"),
           "audience": d.get("audience", "all"), "active": True, "email": bool(d.get("email")),
           "created_at": now(), "by": g.sa.get("name")}
    db.announcements.insert_one(doc)
    sa_audit("announcement", note=doc["title"])
    return jsonify(serialize(doc)), 201


@bp.put("/sa/announcements/<_id>")
@superadmin("announcements")
def update_announcement(_id):
    d = request.get_json(force=True) or {}
    db.announcements.update_one({"_id": oid(_id)}, {"$set": {"active": bool(d.get("active"))}})
    return jsonify({"ok": True})


@bp.get("/sa/settings")
@superadmin("dashboard")
def get_settings():
    s = db.platform_settings.find_one({"_id": "settings"}) or {}
    for k in ("whatsapp_token", "smtp_password", "gateway_secret"):
        if s.get(k):
            s[k] = "••••••" + str(s[k])[-4:]
    return jsonify(serialize(s))


@bp.put("/sa/settings")
@superadmin("settings")
def save_settings():
    d = request.get_json(force=True) or {}
    d = {k: v for k, v in d.items() if not (isinstance(v, str) and v.startswith("••••"))}
    d.pop("id", None)
    db.platform_settings.update_one({"_id": "settings"}, {"$set": d}, upsert=True)
    sa_audit("settings")
    return get_settings()


@bp.get("/sa/audit")
@superadmin("dashboard")
def audit():
    return jsonify(serialize(list(db.sa_audit.find().sort("at", -1).limit(300))))


@bp.get("/sa/team")
@superadmin("settings")
def team():
    return jsonify(serialize(list(db.superadmin_users.find())))


@bp.post("/sa/team")
@superadmin("settings")
def add_team():
    d = request.get_json(force=True) or {}
    doc = {"name": d.get("name"), "email": (d.get("email") or "").lower(), "role": d.get("role", "viewer"),
           "password": hash_password(d.get("password") or "changeme"), "totp_demo": "123456", "created_at": now()}
    db.superadmin_users.insert_one(doc)
    sa_audit("add_team", note=doc["email"])
    return jsonify(serialize(doc)), 201
