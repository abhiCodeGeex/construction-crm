"""Contacts & companies (requirements §3)."""
import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db
from ..security import api, can
from ..services.defaults import CONTACT_TYPES, COMPLIANCE_TYPES

bp = Blueprint("contacts", __name__)

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FIELDS = ("name", "kind", "types", "org_id", "designation", "email", "phone", "alt_phone", "website", "address", "city",
          "state", "pincode", "trade_category", "rating", "notes", "gstin", "pan", "bank", "trade_account_no",
          "discount_pct", "compliance", "referred_by", "tags")
EXPIRY_WARNING_DAYS = 30


def _iso(v, field):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        abort(400, f"{field} must be a date (YYYY-MM-DD)")


def clean_contact(d, existing=None):
    data = {k: d[k] for k in FIELDS if k in d}
    merged = {**(existing or {}), **data}
    name = (merged.get("name") or "").strip()
    if not name:
        abort(400, "Name is required")
    data["name"] = name
    if merged.get("kind", "company") not in ("company", "person"):
        abort(400, "Kind must be company or person")
    data["kind"] = merged.get("kind", "company")
    types = merged.get("types") or []
    bad = [x for x in types if x not in CONTACT_TYPES]
    if bad:
        abort(400, f"Unknown contact type: {', '.join(bad)}")
    data["types"] = list(dict.fromkeys(types))
    if merged.get("email") and not EMAIL_RE.match(merged["email"]):
        abort(400, "Email is not valid")
    if merged.get("email"):
        data["email"] = merged["email"].strip().lower()
    if merged.get("gstin"):
        data["gstin"] = merged["gstin"].strip().upper()
        if not GSTIN_RE.match(data["gstin"]):
            abort(400, "GSTIN must be 15 characters, e.g. 29ABCDE1234F1Z5")
    if merged.get("pan"):
        data["pan"] = merged["pan"].strip().upper()
        if not PAN_RE.match(data["pan"]):
            abort(400, "PAN must be 10 characters, e.g. ABCDE1234F")
    if "rating" in data:
        r = data["rating"]
        if r in (None, "", 0):
            data["rating"] = None
        elif not isinstance(r, (int, float)) or not 1 <= r <= 5:
            abort(400, "Rating must be 1 to 5")
    if "discount_pct" in data:
        dp = data["discount_pct"]
        if dp in (None, ""):
            data["discount_pct"] = None
        elif not isinstance(dp, (int, float)) or not 0 <= dp <= 100:
            abort(400, "Discount must be between 0 and 100%")
    if "bank" in data:
        bank = data["bank"] or {}
        if bank.get("ifsc"):
            bank["ifsc"] = bank["ifsc"].strip().upper()
            if not IFSC_RE.match(bank["ifsc"]):
                abort(400, "IFSC must be 11 characters, e.g. HDFC0001234")
        if bank.get("account_no") and not re.fullmatch(r"[0-9]{6,20}", str(bank["account_no"])):
            abort(400, "Bank account number must be 6-20 digits")
        if existing and str(bank.get("account_no", "")).startswith("••"):
            bank["account_no"] = (existing.get("bank") or {}).get("account_no")  # unchanged masked value
        data["bank"] = {k: bank.get(k) for k in ("account_name", "account_no", "ifsc", "bank_name", "branch")}
    if "compliance" in data:
        docs = []
        for c in data["compliance"] or []:
            if not c.get("name"):
                abort(400, "Each compliance document needs a name")
            if c.get("type", "other") not in COMPLIANCE_TYPES:
                abort(400, "Compliance type must be insurance, licence, certificate or other")
            issue, expiry = _iso(c.get("issue_date"), "Issue date"), _iso(c.get("expiry"), "Expiry date")
            if issue and expiry and expiry < issue:
                abort(400, f"{c['name']}: expiry is before issue date")
            docs.append({"id": c.get("id") or t.sid(), "type": c.get("type", "other"), "name": c["name"],
                         "number": c.get("number"), "issuer": c.get("issuer"), "issue_date": issue,
                         "expiry": expiry, "file": c.get("file")})
        data["compliance"] = docs
    for ref in ("org_id", "referred_by"):
        if merged.get(ref):
            if existing and merged[ref] == str(existing["_id"]):
                abort(400, "A contact cannot point to itself")
            other = t.get("contacts", merged[ref], required=False)
            if not other:
                abort(400, f"{'Company' if ref == 'org_id' else 'Referrer'} not found")
            if ref == "org_id" and other.get("kind") != "company":
                abort(400, "A person can only belong to a company contact")
    if data["kind"] == "company":
        data["org_id"] = None
    return data


def compliance_status(doc, today=None):
    today = today or date.today()
    if not doc.get("expiry"):
        return "no_expiry"
    exp = date.fromisoformat(doc["expiry"])
    if exp < today:
        return "expired"
    if exp <= today + timedelta(days=EXPIRY_WARNING_DAYS):
        return "expiring"
    return "valid"


def present(c):
    """Serialize a contact for the current viewer: bank details only for finance/procurement editors."""
    data = t.out(c)
    for doc in data.get("compliance", []):
        doc["status"] = compliance_status(doc)
    statuses = [d["status"] for d in data.get("compliance", [])]
    data["compliance_alert"] = "expired" if "expired" in statuses else "expiring" if "expiring" in statuses else None
    if data.get("bank") and not (can("finance", True) or can("procurement", True)):
        acc = str(data["bank"].get("account_no") or "")
        data["bank"] = {"account_name": data["bank"].get("account_name"), "bank_name": data["bank"].get("bank_name"),
                        "account_no": ("••••" + acc[-4:]) if acc else None, "ifsc": None, "masked": True}
    if data.get("org_id"):
        org = t.get("contacts", data["org_id"], required=False)
        data["org_name"] = org["name"] if org else None
    return data


@bp.get("/contacts/meta")
@api("contacts", write=False)
def meta():
    return jsonify({"types": CONTACT_TYPES, "compliance_types": COMPLIANCE_TYPES,
                    "expiry_warning_days": EXPIRY_WARNING_DAYS})


@bp.get("/contacts")
@api("contacts")
def list_contacts():
    q = {}
    if request.args.get("q"):
        rx = {"$regex": re.escape(request.args["q"]), "$options": "i"}
        q["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}, {"trade_category": rx}, {"city": rx}]
    if request.args.get("type"):
        q["types"] = request.args["type"]
    if request.args.get("kind"):
        q["kind"] = request.args["kind"]
    if request.args.get("org_id"):
        q["org_id"] = request.args["org_id"]
    rows = [present(c) for c in t.find("contacts", q, sort=[("name", 1)])]
    if request.args.get("alert"):
        rows = [r for r in rows if r["compliance_alert"]]
    return jsonify(rows)


@bp.post("/contacts")
@api("contacts")
def create_contact():
    return jsonify(present(t.insert("contacts", clean_contact(request.get_json(force=True) or {})))), 201


@bp.get("/contacts/<_id>")
@api("contacts")
def get_contact(_id):
    return jsonify(present(t.get("contacts", _id)))


@bp.put("/contacts/<_id>")
@api("contacts")
def update_contact(_id):
    existing = t.get("contacts", _id)
    data = clean_contact(request.get_json(force=True) or {}, existing)
    if "bank" in data and not (can("finance", True) or can("procurement", True)):
        data.pop("bank")  # roles that cannot see bank details cannot change them either
    return jsonify(present(t.update("contacts", _id, data)))


@bp.delete("/contacts/<_id>")
@api("contacts")
def delete_contact(_id):
    t.get("contacts", _id)
    used = db.projects.count_documents({"company_id": g.cid, "$or": [{"client_id": _id}, {"team.contact_id": _id}]})
    if used:
        abort(409, f"This contact is on {used} project(s). Remove them from the project team first.")
    if db.users.count_documents({"company_id": g.cid, "contact_id": _id}):
        abort(409, "This contact has a portal login. Deactivate the portal user instead.")
    if db.contacts.count_documents({"company_id": g.cid, "org_id": _id}):
        abort(409, "People are linked to this company. Move or delete them first.")
    t.delete("contacts", _id)
    return jsonify({"ok": True})


@bp.get("/contacts/<_id>/history")
@api("contacts", write=False)
def history(_id):
    """Past projects together (with this contact's role on each) and relationship / referral history."""
    contact = t.get("contacts", _id)
    projects = []
    for p in db.projects.find({"company_id": g.cid, "$or": [{"client_id": _id}, {"team.contact_id": _id}]}):
        roles = [m["project_role"] for m in p.get("team", []) if m.get("contact_id") == _id]
        if p.get("client_id") == _id and "Client" not in roles:
            roles.insert(0, "Client")
        projects.append({"id": str(p["_id"]), "code": p.get("code"), "name": p["name"], "status": p.get("status"),
                         "roles": roles, "value": None if g.hide_costs else p.get("value"), "start": p.get("start")})
    referred_contacts = [{"id": str(c["_id"]), "name": c["name"], "types": c.get("types", [])}
                         for c in db.contacts.find({"company_id": g.cid, "referred_by": _id})]
    referred_projects = [{"id": str(p["_id"]), "name": p["name"], "status": p.get("status"), "value": p.get("value")}
                         for p in db.projects.find({"company_id": g.cid, "referred_by": _id})]
    people = [{"id": str(c["_id"]), "name": c["name"], "designation": c.get("designation"), "email": c.get("email"),
               "phone": c.get("phone")} for c in db.contacts.find({"company_id": g.cid, "org_id": _id})]
    referrer = t.get("contacts", contact["referred_by"], required=False) if contact.get("referred_by") else None
    portal = db.users.find_one({"company_id": g.cid, "contact_id": _id}, {"email": 1, "role": 1, "active": 1})
    return jsonify({
        "projects": projects, "people": people,
        "referred_by": {"id": str(referrer["_id"]), "name": referrer["name"]} if referrer else None,
        "referred_contacts": referred_contacts, "referred_projects": referred_projects,
        "referred_value": None if g.hide_costs else sum(p["value"] or 0 for p in referred_projects
                                                        if p["status"] != "cancelled"),
        "portal_user": t.out(portal) if portal else None,
    })


@bp.get("/compliance/alerts")
@api("contacts", write=False)
def compliance_alerts():
    """Expired and soon-to-expire compliance documents across all contacts (§3 expiry alerts)."""
    limit = (date.today() + timedelta(days=EXPIRY_WARNING_DAYS)).isoformat()
    rows = []
    for c in t.find("contacts", {"compliance.expiry": {"$lte": limit}}):
        for doc in c.get("compliance", []):
            status = compliance_status(doc)
            if status in ("expired", "expiring"):
                rows.append({"contact_id": str(c["_id"]), "contact": c["name"], "document": doc["name"],
                             "type": doc["type"], "expiry": doc["expiry"], "status": status,
                             "days": (date.fromisoformat(doc["expiry"]) - date.today()).days})
    return jsonify(sorted(rows, key=lambda r: r["expiry"]))
