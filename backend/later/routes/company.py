"""Company settings, users, templates, audit, notifications, uploads, billing self-service, support."""
import os
import uuid
from datetime import timedelta

from flask import Blueprint, request, jsonify, abort, g, send_from_directory
from werkzeug.utils import secure_filename

from .. import tenancy as t
from ..config import Config
from ..crud import register_crud, num
from ..db import db, oid, serialize
from ..security import api, auth_required, hash_password, INTERNAL_ROLES, EXTERNAL_ROLES
from ..services.subscription import check_user_limit, check_modules, limits, usage

bp = Blueprint("company", __name__)

EDITABLE = ("name", "types", "modules", "branches", "currency", "tax_rate", "tax_label", "gstin", "numbering",
            "branding", "pipelines", "lead_sources", "markup_rules", "deposit_pct", "city", "phone", "address",
            "allow_support_login", "routing")


@bp.get("/company")
@api("settings", write=False)
def get_company():
    c = serialize(g.company)
    c.pop("counters", None)
    c.pop("notes", None)
    return jsonify({**c, "limits": limits(), "usage": usage(g.company)})


@bp.put("/company")
@api("settings")
def update_company():
    d = request.get_json(force=True) or {}
    changes = {k: d[k] for k in EDITABLE if k in d}
    if "modules" in changes:
        check_modules(changes["modules"])
        allowed = set(g.company.get("disabled_features", {}).get("modules_blocked", []))
        changes["modules"] = [m for m in changes["modules"] if m not in allowed]
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": changes})
    t.audit("update", "companies", g.company["_id"], before=g.company,
            after={**g.company, **changes})
    return get_company()


# ---------------- users ----------------
@bp.get("/users")
@api(None)
def list_users():
    users = t.find("users", {}, sort=[("name", 1)])
    return jsonify([t.out(u) for u in users])


@bp.post("/users")
@api("users")
def create_user():
    d = request.get_json(force=True) or {}
    if not d.get("email") or not d.get("name"):
        abort(400, "Name and email are required")
    role = d.get("role", "pm")
    if role not in INTERNAL_ROLES:
        abort(400, "Invalid role")
    if not d.get("whatsapp_only"):
        check_user_limit()
    email = d["email"].strip().lower()
    if db.users.find_one({"email": email}):
        abort(409, "Email already in use")
    doc = t.insert("users", {
        "name": d["name"], "email": email, "phone": d.get("phone"), "role": role, "kind": "staff",
        "password": hash_password(d.get("password") or "changeme"), "active": True,
        "whatsapp_only": bool(d.get("whatsapp_only")), "trade": d.get("trade"), "language": d.get("language", "en"),
    })
    return jsonify(t.out(doc)), 201


@bp.put("/users/<_id>")
@api("users")
def update_user(_id):
    d = request.get_json(force=True) or {}
    changes = {k: d[k] for k in ("name", "phone", "role", "active", "whatsapp_only", "trade", "language") if k in d}
    if d.get("password"):
        changes["password"] = hash_password(d["password"])
    user = t.get("users", _id)
    if changes.get("active") and user.get("active") is False and not changes.get("whatsapp_only"):
        check_user_limit()
    return jsonify(t.out(t.update("users", _id, changes)))


@bp.post("/contacts/<_id>/portal-access")
@api("contacts")
def portal_access(_id):
    """Invite a client / vendor / subcontractor / consultant to the portal (free, not counted)."""
    contact = t.get("contacts", _id)
    d = request.get_json(force=True) or {}
    email = (d.get("email") or contact.get("email") or "").strip().lower()
    if not email:
        abort(400, "Email required")
    role = d.get("role", "client")
    if role not in EXTERNAL_ROLES:
        abort(400, "Invalid portal role")
    existing = db.users.find_one({"email": email})
    if existing:
        abort(409, "Email already has a login")
    doc = t.insert("users", {
        "name": contact["name"], "email": email, "role": role, "kind": "external", "contact_id": _id,
        "password": hash_password(d.get("password") or "portal123"), "active": True,
    })
    t.update("contacts", _id, {"portal_user_id": str(doc["_id"]), "email": email}, audit_it=False)
    return jsonify(t.out(doc)), 201


# ---------------- templates / audit / notifications ----------------
register_crud(bp, "stage_templates", "settings", search=("name",), filters=("service",), sort=("service", 1))


@bp.get("/audit")
@api("settings", write=False)
def audit_log():
    q = {"company_id": g.cid}
    if request.args.get("collection"):
        q["collection"] = request.args["collection"]
    if request.args.get("doc_id"):
        q["doc_id"] = request.args["doc_id"]
    rows = db.audit_logs.find(q).sort("at", -1).limit(int(request.args.get("limit", 200)))
    return jsonify(serialize(list(rows)))


@bp.get("/notifications")
@auth_required
def notifications():
    q = {"company_id": g.cid, "$or": [{"user_id": g.uid}, {"role": g.role}, {"role": None, "user_id": None}]}
    rows = list(db.notifications.find(q).sort("created_at", -1).limit(50))
    for r in rows:
        r["read"] = g.uid in r.get("read_by", [])
    return jsonify(serialize(rows))


@bp.post("/notifications/read")
@auth_required
def notifications_read():
    ids = [oid(i) for i in (request.get_json(force=True) or {}).get("ids", [])]
    q = {"company_id": g.cid}
    if ids:
        q["_id"] = {"$in": ids}
    db.notifications.update_many(q, {"$addToSet": {"read_by": g.uid}})
    return jsonify({"ok": True})


# ---------------- uploads ----------------
@bp.post("/uploads")
@auth_required
def upload():
    files = request.files.getlist("file")
    if not files:
        abort(400, "No file")
    lim = limits()["storage_gb"]
    used = usage(g.company)["storage_bytes"]
    saved = []
    for f in files:
        name = secure_filename(f.filename or "file") or "file"
        key = f"{g.cid}_{uuid.uuid4().hex[:12]}_{name}"
        path = os.path.join(Config.UPLOAD_DIR, key)
        f.save(path)
        size = os.path.getsize(path)
        if lim and used + size > lim * 1024 ** 3:
            os.remove(path)
            abort(402, "Storage limit reached — buy extra storage or upgrade.")
        used += size
        db.files.insert_one({"company_id": g.cid, "key": key, "name": name, "size": size,
                             "content_type": f.mimetype, "uploaded_by": g.uid, "at": t.now()})
        saved.append({"key": key, "name": name, "size": size, "content_type": f.mimetype,
                      "url": f"/api/files/{key}"})
    return jsonify(saved if len(saved) > 1 else saved[0]), 201


@bp.get("/files/<key>")
@auth_required
def file(key):
    if not key.startswith(f"{g.cid}_"):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, key)


# ---------------- announcements & support ----------------
@bp.get("/announcements")
@auth_required
def announcements():
    rows = db.announcements.find({"active": True, "$or": [
        {"audience": "all"}, {"audience": g.company.get("plan_code")}]}).sort("created_at", -1).limit(10)
    return jsonify(serialize(list(rows)))


@bp.get("/support/tickets")
@api(None)
def my_tickets():
    return jsonify(serialize(list(db.support_tickets.find({"company_id": g.cid}).sort("created_at", -1))))


@bp.post("/support/tickets")
@api(None)
def new_ticket():
    d = request.get_json(force=True) or {}
    if not d.get("subject"):
        abort(400, "Subject required")
    doc = {"company_id": g.cid, "company_name": g.company["name"], "subject": d["subject"],
           "body": d.get("body"), "status": "open", "priority": d.get("priority", "normal"),
           "raised_by": g.user.get("name"), "replies": [], "created_at": t.now()}
    doc["_id"] = db.support_tickets.insert_one(doc).inserted_id
    return jsonify(serialize(doc)), 201


@bp.post("/support/tickets/<_id>/reply")
@api(None)
def ticket_reply(_id):
    d = request.get_json(force=True) or {}
    db.support_tickets.update_one({"_id": oid(_id), "company_id": g.cid}, {"$push": {"replies": {
        "by": g.user.get("name"), "side": "company", "text": d.get("text"), "at": t.now()}}})
    return jsonify({"ok": True})


# ---------------- subscription self-service ----------------
@bp.get("/billing")
@api(None)
def billing():
    plans = list(db.plans.find({"active": True}).sort("price_monthly", 1))
    invoices = list(db.platform_invoices.find({"company_id": g.cid}).sort("created_at", -1))
    c = g.company
    return jsonify({
        "status": c.get("status"), "plan_code": c.get("plan_code"), "billing_cycle": c.get("billing_cycle"),
        "trial_ends": c.get("trial_ends"), "next_renewal": c.get("next_renewal"),
        "plans": serialize(plans), "invoices": serialize(invoices), "limits": limits(), "usage": usage(c),
        "addons": c.get("addons", {}), "price_locked": c.get("price_locked"),
    })


@bp.post("/billing/change-plan")
@api("settings")
def change_plan():
    from .superadmin import issue_invoice
    d = request.get_json(force=True) or {}
    plan = db.plans.find_one({"code": d.get("plan_code"), "active": True})
    if not plan:
        abort(404, "Plan not found")
    cycle = d.get("cycle", "monthly")
    coupon = None
    if d.get("coupon"):
        coupon = db.coupons.find_one({"code": d["coupon"].upper(), "active": True})
        if not coupon:
            abort(400, "Invalid coupon")
    if plan.get("max_modules") and len(g.company.get("modules", [])) > plan["max_modules"]:
        abort(400, f"{plan['name']} allows {plan['max_modules']} module(s); disable modules first.")
    changes = {"plan_code": plan["code"], "billing_cycle": cycle,
               "price_locked": plan["price_yearly"] if cycle == "yearly" else plan["price_monthly"]}
    if coupon:
        changes["coupon"] = {"code": coupon["code"], "percent": coupon["percent"],
                             "months_left": coupon.get("months", 1)}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": changes})
    company = db.companies.find_one({"_id": g.company["_id"]})
    inv = issue_invoice(company, prorate_from=g.company.get("plan_code"))
    t.audit("update", "subscription", g.company["_id"], note=f"Plan changed to {plan['name']} ({cycle})")
    return jsonify({"ok": True, "invoice": serialize(inv)})


@bp.post("/billing/addons")
@api("settings")
def buy_addon():
    d = request.get_json(force=True) or {}
    field = {"users": "addons.extra_users", "storage": "addons.extra_storage_gb",
             "whatsapp": "addons.extra_whatsapp"}.get(d.get("type"))
    if not field:
        abort(400, "Unknown add-on")
    qty = int(num(d.get("qty"), 1)) * (100 if d["type"] == "storage" else 1000 if d["type"] == "whatsapp" else 1)
    db.companies.update_one({"_id": g.company["_id"]}, {"$inc": {field: qty}})
    return jsonify({"ok": True})


@bp.post("/billing/pay/<_id>")
@api(None)
def pay_platform_invoice(_id):
    """Simulated Razorpay/Stripe checkout: marks invoice paid and re-activates the account."""
    inv = db.platform_invoices.find_one({"_id": oid(_id), "company_id": g.cid})
    if not inv:
        abort(404)
    if inv["status"] == "paid":
        return jsonify(serialize(inv))
    db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {
        "status": "paid", "paid_at": t.now(), "method": "gateway", "gateway_ref": f"pay_{uuid.uuid4().hex[:14]}"}})
    renewal = t.now() + timedelta(days=365 if g.company.get("billing_cycle") == "yearly" else 30)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"status": "active", "next_renewal": renewal}})
    return jsonify(serialize(db.platform_invoices.find_one({"_id": inv["_id"]})))


@bp.post("/billing/cancel")
@api("settings")
def cancel_subscription():
    d = request.get_json(force=True) or {}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {
        "status": "cancelled", "cancelled_at": t.now(), "cancel_reason": d.get("reason")}})
    return jsonify({"ok": True})
