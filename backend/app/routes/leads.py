"""Leads & sales pipeline (requirements §2): capture once, per-service pipelines, activity log, win -> project,
loss reasons, bid/tender register, public website form and the sales report."""
import re
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, ROLE_PERMS, effective_perms
from ..services.defaults import (LEAD_SOURCES, PIPELINE, SERVICES, PROJECT_TYPES, LOSS_REASONS, LEAD_TIMELINES,
                                 ACTIVITY_TYPES)
from .contacts import EMAIL_RE

bp = Blueprint("leads", __name__)

FIELDS = ("title", "contact_id", "service", "project_type", "location", "area", "area_unit", "budget", "timeline",
          "source", "source_detail", "referred_by", "owner_id", "notes")


# ---------------- helpers ----------------
def pipeline(service):
    return (g.company.get("pipelines") or {}).get(service) or PIPELINE


def loss_reasons():
    return g.company.get("loss_reasons") or LOSS_REASONS


def num(v, field):
    if v in (None, ""):
        return None
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
        abort(400, f"{field} must be a positive number")
    return float(v)


def staff(uid, field="Salesperson"):
    u = db.users.find_one({"_id": oid(uid), "company_id": g.cid, "kind": "staff", "active": {"$ne": False}})
    if not u:
        abort(400, f"{field} must be an active staff user")
    return u


def norm_phone(p):
    digits = re.sub(r"\D", "", p or "")
    return digits[-10:] if len(digits) >= 10 else digits


def find_duplicate(phone, email, exclude=None):
    """§2 'captured once': an open lead for the same phone or email already exists."""
    ors = []
    if norm_phone(phone):
        ors.append({"phone_key": norm_phone(phone)})
    if email:
        ors.append({"email_key": email.strip().lower()})
    if not ors:
        return None
    q = {"company_id": g.cid, "status": "open", "$or": ors}
    if exclude:
        q["_id"] = {"$ne": oid(exclude)}
    return db.leads.find_one(q)


def clean(d, existing=None, new_contact=None):
    out = {k: d[k] for k in FIELDS if k in d}
    m = {**(existing or {}), **out}
    if not (m.get("title") or "").strip():
        abort(400, "Lead title is required (e.g. 'Mehta villa – new build')")
    out["title"] = m["title"].strip()
    if m.get("service") not in SERVICES:
        abort(400, "Choose the service: architecture, construction or interior")
    if m["service"] not in g.company.get("modules", []):
        abort(400, f"The {m['service']} module is not enabled for your company")
    if m.get("source") not in LEAD_SOURCES:
        abort(400, f"Source must be one of: {', '.join(LEAD_SOURCES)}")
    if m["source"] == "Referral" and not m.get("referred_by"):
        abort(400, "A referral lead needs the contact who referred it")
    if m.get("referred_by"):
        if not t.get("contacts", m["referred_by"], required=False):
            abort(400, "Referrer not found")
    if m.get("project_type") and m["project_type"] not in PROJECT_TYPES:
        abort(400, f"Project type must be one of: {', '.join(PROJECT_TYPES)}")
    if m.get("timeline") and m["timeline"] not in LEAD_TIMELINES:
        abort(400, f"Timeline must be one of: {', '.join(LEAD_TIMELINES)}")
    if "area" in out:
        out["area"] = num(out["area"], "Area")
    if m.get("area_unit", "sqft") not in ("sqft", "sqm"):
        abort(400, "Area unit must be sq ft or m²")
    out["area_unit"] = m.get("area_unit", "sqft")
    if "budget" in out:
        out["budget"] = num(out["budget"], "Budget")
    if out.get("owner_id"):
        out["owner_name"] = staff(out["owner_id"])["name"]
    elif "owner_id" in out:
        out["owner_name"] = None
    if new_contact or m.get("contact_id"):
        c = new_contact or t.get("contacts", m["contact_id"], required=False)
        if not c:
            abort(400, "Contact not found")
        out.update(contact_name=c["name"], phone_key=norm_phone(c.get("phone")),
                   email_key=(c.get("email") or "").lower() or None)
    elif m.get("source") == "Repeat client":
        abort(400, "A repeat-client lead must be linked to the existing contact")
    else:
        abort(400, "Link a contact or enter the enquirer's name")
    return out


def contact_from_payload(d):
    """The client contact to create from the enquiry when no existing contact was chosen. Not saved here:
    the caller inserts it only after the whole lead is valid, so a refused lead leaves no stray contact."""
    if d.get("contact_id") or not (d.get("contact_name") or "").strip():
        return None
    if d.get("source") == "Repeat client":
        abort(400, "A repeat-client lead must be linked to the existing contact")
    email = (d.get("contact_email") or "").strip().lower() or None
    if email and not EMAIL_RE.match(email):
        abort(400, "Email is not valid")
    if not norm_phone(d.get("contact_phone")) and not email:
        abort(400, "Enter a phone number or email for the enquirer")
    dup = find_duplicate(d.get("contact_phone"), email)
    if dup and not d.get("force"):
        abort(409, f"An open lead already exists for this enquirer: {dup['title']}|{dup['_id']}")
    return {"name": d["contact_name"].strip(), "kind": "company" if d.get("contact_is_company") else "person",
            "types": ["client"], "phone": d.get("contact_phone"), "email": email,
            "referred_by": d.get("referred_by"), "compliance": []}


def present(lead):
    data = serialize(lead)
    data["pipeline"] = pipeline(lead.get("service"))
    nxt = db.followups.find_one({"company_id": g.cid, "related.type": "lead", "related.id": str(lead["_id"]),
                                 "status": "open"}, sort=[("due", 1)])
    data["next_followup"] = {"id": str(nxt["_id"]), "title": nxt["title"], "due": nxt["due"],
                             "overdue": nxt["due"] < date.today().isoformat()} if nxt else None
    data["can_edit"] = can("leads", True)
    return data


def history_entry(kind, text, **extra):
    return {"id": t.sid(), "type": kind, "text": text, "at": t.now(), "by": g.user.get("name"), "by_id": g.uid, **extra}


# ---------------- meta & pipelines ----------------
@bp.get("/leads/meta")
@api("leads", write=False)
def meta():
    services = [s for s in SERVICES if s in g.company.get("modules", [])]
    sales = [{"id": str(u["_id"]), "name": u["name"], "role": u["role"]}
             for u in db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}})]
    pms = [u for u in sales if "w" in effective_perms(u["role"], g.company).get("projects", "")]
    return jsonify({"sources": LEAD_SOURCES, "project_types": PROJECT_TYPES, "timelines": LEAD_TIMELINES,
                    "services": services, "pipelines": {s: pipeline(s) for s in services},
                    "loss_reasons": loss_reasons(), "activity_types": ACTIVITY_TYPES, "staff": sales,
                    "project_managers": pms, "form_key": g.company.get("lead_form_key") if can("settings") else None})


@bp.put("/leads/pipelines")
@api("settings")
def set_pipelines():
    d = request.get_json(force=True) or {}
    changes = {}
    for service, stages in (d.get("pipelines") or {}).items():
        if service not in SERVICES:
            abort(400, "Unknown service")
        stages = [s.strip() for s in stages if isinstance(s, str) and s.strip()]
        if not stages:
            abort(400, f"The {service} pipeline needs at least one stage")
        if len({s.lower() for s in stages}) != len(stages):
            abort(400, "Stage names must be unique")
        if {"won", "lost"} & {s.lower() for s in stages}:
            abort(400, "Won and Lost are fixed end states; do not add them as stages")
        in_use = db.leads.distinct("stage", {"company_id": g.cid, "service": service, "status": "open"})
        missing = [s for s in in_use if s not in stages]
        if missing:
            abort(409, f"Open leads are still in: {', '.join(missing)}. Move them first.")
        changes[f"pipelines.{service}"] = stages
    if "loss_reasons" in d:
        reasons = [r.strip() for r in d["loss_reasons"] if isinstance(r, str) and r.strip()]
        if not reasons:
            abort(400, "Keep at least one loss reason")
        changes["loss_reasons"] = list(dict.fromkeys(reasons))
    if not changes:
        abort(400, "Nothing to update")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": changes})
    t.audit("update", "pipelines", g.company["_id"], note=", ".join(changes))
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return meta()


@bp.post("/leads/form-key")
@api("settings")
def rotate_form_key():
    key = secrets.token_urlsafe(16)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"lead_form_key": key}})
    t.audit("update", "lead_form", g.company["_id"], note="Website form link regenerated")
    return jsonify({"form_key": key})


# ---------------- leads ----------------
@bp.get("/leads")
@api("leads")
def list_leads():
    q = {}
    for k in ("service", "status", "stage", "source"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("owner_id") == "none":
        q["owner_id"] = None
    elif request.args.get("owner_id"):
        q["owner_id"] = request.args["owner_id"]
    if request.args.get("q"):
        rx = {"$regex": re.escape(request.args["q"]), "$options": "i"}
        q["$or"] = [{"title": rx}, {"contact_name": rx}, {"location": rx}]
    return jsonify([present(x) for x in t.find("leads", q, sort=[("created_at", -1)])])


@bp.post("/leads")
@api("leads")
def create_lead():
    d = request.get_json(force=True) or {}
    new_contact = contact_from_payload(d)
    data = clean(d, new_contact=new_contact)
    if d.get("contact_id") and not d.get("force") and request.args.get("force") != "1":
        c = t.get("contacts", d["contact_id"])
        dup = find_duplicate(c.get("phone"), c.get("email"))
        if dup:
            abort(409, f"An open lead already exists for this enquirer: {dup['title']}|{dup['_id']}")
    data.setdefault("owner_id", g.uid)
    if data["owner_id"] == g.uid:
        data["owner_name"] = g.user.get("name")
    stage = pipeline(data["service"])[0]
    data.update(status="open", stage=stage, activities=[],
                stage_history=[{"stage": stage, "at": t.now(), "by": g.user.get("name")}], first_response_at=None)
    if new_contact:  # everything is valid: now the enquirer becomes a contact
        data["contact_id"] = str(t.insert("contacts", new_contact)["_id"])
    return jsonify(present(t.insert("leads", data))), 201


@bp.get("/leads/<_id>")
@api("leads")
def get_lead(_id):
    data = present(t.get("leads", _id))
    data["bids"] = [present_bid(b) for b in t.find("bids", {"lead_id": _id}, sort=[("due_date", 1)])]
    return jsonify(data)


def editable(lead):
    if lead["status"] != "open":
        abort(409, f"This lead is {lead['status']} and read-only" + (" — reopen it first" if lead["status"] == "lost" else ""))


@bp.put("/leads/<_id>")
@api("leads")
def update_lead(_id):
    lead = t.get("leads", _id)
    editable(lead)
    d = request.get_json(force=True) or {}
    data = clean(d, lead)
    if data.get("service", lead["service"]) != lead["service"] and lead["stage"] not in pipeline(data["service"]):
        data["stage"] = pipeline(data["service"])[0]
    if data.get("owner_id") and lead.get("owner_id") and data["owner_id"] != lead["owner_id"]:
        # reassigning a lead hands over the previous salesperson's open follow-ups on it
        db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open",
                                  "owner_id": lead["owner_id"]},
                                 {"$set": {"owner_id": data["owner_id"], "owner_name": data["owner_name"]}})
    return jsonify(present(t.update("leads", _id, data)))


@bp.delete("/leads/<_id>")
@api("leads")
def delete_lead(_id):
    if g.role != "owner":
        abort(403, "Only the owner can delete a lead; record it as lost instead")
    lead = t.get("leads", _id)
    if lead["status"] == "won" and t.get("projects", lead.get("project_id"), required=False):
        abort(409, "Won leads cannot be deleted while their project exists")
    t.delete("leads", _id)
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Lead deleted"}})
    db.bids.update_many({"company_id": g.cid, "lead_id": _id}, {"$set": {"lead_id": None, "lead_title": None}})
    return jsonify({"ok": True})


@bp.post("/leads/<_id>/stage")
@api("leads")
def move_stage(_id):
    lead = t.get("leads", _id)
    editable(lead)
    stage = (request.get_json(force=True) or {}).get("stage")
    if stage not in pipeline(lead["service"]):
        abort(400, f"'{stage}' is not a stage of the {lead['service']} pipeline")
    if stage == lead["stage"]:
        return jsonify(present(lead))
    entry = {"stage": stage, "at": t.now(), "by": g.user.get("name"), "from": lead["stage"]}
    act = history_entry("stage", f"Moved from {lead['stage']} to {stage}")
    return jsonify(present(t.update("leads", _id, {"stage": stage},
                                    raw={"$push": {"stage_history": entry, "activities": act}})))


@bp.post("/leads/<_id>/activities")
@api("leads")
def add_activity(_id):
    """§2 call / email / WhatsApp log and meeting notes."""
    lead = t.get("leads", _id)
    editable(lead)
    d = request.get_json(force=True) or {}
    if d.get("type") not in ACTIVITY_TYPES:
        abort(400, f"Activity type must be one of: {', '.join(ACTIVITY_TYPES)}")
    if not (d.get("text") or "").strip():
        abort(400, "Write what happened")
    act = history_entry(d["type"], d["text"].strip(), outcome=d.get("outcome"),
                        template_id=d.get("template_id"))
    changes = {"last_activity_at": t.now()}
    if not lead.get("first_response_at"):
        changes["first_response_at"] = t.now()
    return jsonify(present(t.update("leads", _id, changes, raw={"$push": {"activities": act}}))), 201


def project_manager(pm_id):
    if not pm_id:
        abort(400, "Choose the project manager for the new project")
    pm = staff(pm_id, "Project manager")
    if "w" not in effective_perms(pm["role"], g.company).get("projects", ""):
        abort(400, f"{pm['name']} cannot manage projects; choose a user whose role can edit projects")
    return pm


def loss_reason(d):
    if d.get("reason") not in loss_reasons():
        abort(400, f"Choose a loss reason: {', '.join(loss_reasons())}")
    return d["reason"]


def win_lead(lead, d, bid=None):
    """Won -> Phase B project with the lead's client, service, area, value and referral. Linked bids follow."""
    from .projects import new_project
    _id = str(lead["_id"])
    project_manager(d.get("pm_id"))
    extra = []
    if lead.get("owner_id") and lead["owner_id"] != d["pm_id"]:
        extra.append({"user_id": lead["owner_id"], "name": lead.get("owner_name"), "project_role": "Sales", "access": "view"})
    value = num(d.get("value"), "Value") if d.get("value") not in (None, "") else \
        ((bid or {}).get("value") or lead.get("budget") or 0)
    project = new_project({
        "name": (d.get("project_name") or lead["title"]).strip(), "services": [lead["service"]],
        "client_id": lead["contact_id"], "project_type": lead.get("project_type"), "start": d.get("start"),
        "area": lead.get("area") or 0, "area_unit": lead.get("area_unit", "sqft"), "value": value,
        "referred_by": lead.get("referred_by"), "site": {"line1": lead.get("location")},
        "description": lead.get("notes"),
    }, d["pm_id"], extra, {"lead_id": _id, **({"bid_id": str(bid["_id"])} if bid else {})})
    act = history_entry("won", f"Won — project {project['code']} created" + (f" (bid {bid['title']})" if bid else ""),
                        project_id=str(project["_id"]))
    t.update("leads", _id, {"status": "won", "won_at": t.now(), "project_id": str(project["_id"]),
                            "project_code": project["code"], "won_value": project.get("value")},
             raw={"$push": {"activities": act, "stage_history": {"stage": "Won", "at": t.now(), "by": g.user.get("name"),
                                                                 "from": lead["stage"]}}})
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"related": {"type": "project", "id": str(project["_id"]), "label": project["name"]}}})
    close_bids(_id, "won", {"project_id": str(project["_id"]), "project_code": project["code"]})
    return project


def lose_lead(lead, reason, note=None):
    _id = str(lead["_id"])
    act = history_entry("lost", f"Lost — {reason}" + (f": {note}" if note else ""))
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Lead lost"}})
    close_bids(_id, "lost", {"loss_reason": reason, "loss_note": note})
    return t.update("leads", _id, {"status": "lost", "lost_at": t.now(), "loss_reason": reason,
                                   "loss_note": note, "lost_from_stage": lead["stage"]},
                    raw={"$push": {"activities": act, "stage_history": {
                        "stage": "Lost", "at": t.now(), "by": g.user.get("name"), "from": lead["stage"]}}})


def close_bids(lead_id, result, extra):
    """A lead's submitted bids take the lead's result, so the hit rate and the register stay true."""
    for b in t.find("bids", {"lead_id": lead_id, "decision": "bid", "status": "submitted"}):
        t.update("bids", str(b["_id"]), {"status": result, "result_at": t.now(), **extra})


@bp.post("/leads/<_id>/win")
@api("leads")
def win(_id):
    lead = t.get("leads", _id)
    editable(lead)
    project = win_lead(lead, request.get_json(force=True) or {})
    return jsonify({"lead": present(t.get("leads", _id)), "project_id": str(project["_id"])})


@bp.post("/leads/<_id>/lose")
@api("leads")
def lose(_id):
    lead = t.get("leads", _id)
    editable(lead)
    d = request.get_json(force=True) or {}
    return jsonify(present(lose_lead(lead, loss_reason(d), d.get("note"))))


@bp.post("/leads/<_id>/reopen")
@api("leads")
def reopen(_id):
    lead = t.get("leads", _id)
    if lead["status"] != "lost":
        abort(409, "Only lost leads can be reopened")
    stage = lead.get("lost_from_stage") if lead.get("lost_from_stage") in pipeline(lead["service"]) else pipeline(lead["service"])[0]
    act = history_entry("reopened", f"Reopened at {stage}")
    return jsonify(present(t.update("leads", _id, {"status": "open", "stage": stage, "loss_reason": None, "loss_note": None},
                                    raw={"$push": {"activities": act, "stage_history": {
                                        "stage": stage, "at": t.now(), "by": g.user.get("name"), "from": "Lost"}}})))


# ---------------- bid / tender register ----------------
BID_STATUSES = ("preparing", "submitted", "won", "lost")


def clean_bid(d, existing=None):
    if existing and existing.get("status") in ("won", "lost"):
        abort(409, f"This bid is {existing['status']} and read-only")
    m = {**(existing or {}), **d}
    out = {}
    if not (m.get("title") or "").strip():
        abort(400, "Bid title is required")
    out["title"] = m["title"].strip()
    for k in ("reference", "notes", "decision_reason"):
        if k in d:
            out[k] = d[k]
    if m.get("due_date") in (None, ""):
        abort(400, "Bid due date is required")
    try:
        out["due_date"] = date.fromisoformat(str(m["due_date"])[:10]).isoformat()
    except ValueError:
        abort(400, "Due date must be a date (YYYY-MM-DD)")
    lead = None
    if "lead_id" in d and not d["lead_id"]:
        out["lead_id"], out["lead_title"] = None, None
    elif m.get("lead_id"):
        lead = t.get("leads", m["lead_id"], required=False) or abort(400, "Lead not found")
        if d.get("lead_id") and d["lead_id"] != (existing or {}).get("lead_id") and lead["status"] != "open":
            abort(400, "Link the bid to an open lead")
        out["lead_id"], out["lead_title"] = m["lead_id"], lead["title"]
    service = lead["service"] if lead else m.get("service")  # a bid for a lead is the same job
    if service and service not in g.company.get("modules", []):
        abort(400, "Service must be an enabled module")
    out["service"] = service
    if "value" in d:
        out["value"] = num(d["value"], "Bid value")
    client_id = lead["contact_id"] if lead else m.get("client_id")
    if client_id:
        c = t.get("contacts", client_id, required=False) or abort(400, "Client contact not found")
        out["client_id"], out["client_name"] = client_id, c["name"]
    elif "client_id" in d:
        out["client_id"], out["client_name"] = None, None
    decision = m.get("decision", "pending")
    if decision not in ("pending", "bid", "no_bid"):
        abort(400, "Decision must be pending, bid or no-bid")
    if decision == "no_bid" and not (m.get("decision_reason") or "").strip():
        abort(400, "Record why you decided not to bid")
    out["decision"] = decision
    status = m.get("status", "preparing")
    if status in ("won", "lost"):
        abort(400, "Record the result with Won or Lost on the bid, so the project and the lead follow")
    if status not in BID_STATUSES:
        abort(400, "Invalid bid status")
    if decision != "bid" and status != "preparing":
        abort(400, "Only bids you decided to submit can be submitted")
    out["status"] = status
    if status == "submitted" and (existing or {}).get("status") != "submitted":
        out["submitted_at"] = t.now().isoformat()
    return out


def present_bid(b):
    data = serialize(b)
    if b.get("lead_id"):
        lead = db.leads.find_one({"_id": oid(b["lead_id"]), "company_id": g.cid}, {"status": 1})
        data["lead_status"] = lead and lead["status"]
    data["overdue"] = b.get("status") == "preparing" and b.get("decision") != "no_bid" and \
        b["due_date"] < date.today().isoformat()
    return data


def submitted_bid(_id):
    b = t.get("bids", _id)
    if b.get("status") in ("won", "lost"):
        abort(409, f"This bid is already {b['status']}")
    if b.get("decision") != "bid" or b.get("status") != "submitted":
        abort(400, "Mark the bid as submitted before recording the result")
    return b


@bp.get("/bids")
@api("leads")
def list_bids():
    q = {k: request.args[k] for k in ("status", "decision", "service") if request.args.get(k)}
    rows = t.find("bids", q, sort=[("due_date", 1)])
    decided = [b for b in t.find("bids", {"status": {"$in": ["won", "lost"]}})]
    won = sum(1 for b in decided if b["status"] == "won")
    return jsonify({"bids": [present_bid(b) for b in rows],
                    "hit_rate": round(won / len(decided) * 100, 1) if decided else None,
                    "won": won, "decided": len(decided)})


@bp.post("/bids")
@api("leads")
def create_bid():
    return jsonify(present_bid(t.insert("bids", clean_bid(request.get_json(force=True) or {})))), 201


@bp.put("/bids/<_id>")
@api("leads")
def update_bid(_id):
    b = t.get("bids", _id)
    return jsonify(present_bid(t.update("bids", _id, clean_bid(request.get_json(force=True) or {}, b))))


def project_from_bid(b, d):
    """Project straight from a won bid: its client, service and value; the bid's author joins as Sales (view)."""
    from .projects import new_project
    client_id = d.get("client_id") or b.get("client_id")
    if not client_id:
        abort(400, "Choose the client for the project")
    client = t.get("contacts", client_id, required=False) or abort(400, "Client contact not found")
    if not b.get("service"):
        abort(400, "Choose the service on the bid before recording the win")
    pm = project_manager(d.get("pm_id"))
    extra = []
    author = db.users.find_one({"_id": oid(b.get("created_by")), "company_id": g.cid, "kind": "staff"})
    if author and str(author["_id"]) != d["pm_id"]:
        extra.append({"user_id": str(author["_id"]), "name": author["name"], "project_role": "Sales", "access": "view"})
    project = new_project({
        "name": (d.get("project_name") or b["title"]).strip(), "services": [b["service"]],
        "client_id": client_id, "start": d.get("start"),
        "value": num(d.get("value"), "Value") if d.get("value") not in (None, "") else (b.get("value") or 0),
        "description": b.get("notes"),
    }, str(pm["_id"]), extra, {"bid_id": str(b["_id"])})
    t.update("bids", str(b["_id"]), {"project_id": str(project["_id"]), "project_code": project["code"],
                                     "client_id": client_id, "client_name": client["name"]})
    return project


@bp.post("/bids/<_id>/won")
@api("leads")
def bid_won(_id):
    """Won bid -> project. With a linked lead the lead is won (same path as Mark as won); otherwise the
    project is created straight from the bid's client, service and value."""
    b = submitted_bid(_id)
    d = request.get_json(force=True) or {}
    lead = t.get("leads", b["lead_id"], required=False) if b.get("lead_id") else None
    if lead and lead["status"] == "lost":
        abort(409, f"The linked lead '{lead['title']}' is lost. Reopen it or unlink it from the bid first.")
    if lead and lead["status"] == "won":  # the job was already converted: point the bid at that project
        t.update("bids", _id, {"status": "won", "result_at": t.now(), "project_id": lead.get("project_id"),
                               "project_code": lead.get("project_code")})
    elif lead:
        win_lead(lead, d, b)
    else:
        project_from_bid(b, d)
        t.update("bids", _id, {"status": "won", "result_at": t.now()})
    return jsonify(present_bid(t.get("bids", _id)))


@bp.post("/bids/<_id>/project")
@api("leads")
def bid_project(_id):
    """A won bid that has no project (won before projects were created from bids, or its project was deleted)."""
    b = t.get("bids", _id)
    if b.get("status") != "won":
        abort(400, "Only a won bid can start a project")
    if t.get("projects", b.get("project_id"), required=False):
        abort(409, f"This bid already has project {b.get('project_code')}")
    project = project_from_bid(b, request.get_json(force=True) or {})
    lead = t.get("leads", b["lead_id"], required=False) if b.get("lead_id") else None
    if lead and lead["status"] == "won" and not t.get("projects", lead.get("project_id"), required=False):
        t.update("leads", b["lead_id"], {"project_id": str(project["_id"]), "project_code": project["code"]},
                 raw={"$push": {"activities": history_entry("note", f"Project {project['code']} started from bid {b['title']}")}})
    return jsonify(present_bid(t.get("bids", _id)))


@bp.post("/bids/<_id>/lost")
@api("leads")
def bid_lost(_id):
    b = submitted_bid(_id)
    d = request.get_json(force=True) or {}
    reason = loss_reason(d)
    lead = t.get("leads", b["lead_id"], required=False) if b.get("lead_id") else None
    if lead and lead["status"] == "open":
        lose_lead(lead, reason, d.get("note"))  # closes this bid too
    else:
        t.update("bids", _id, {"status": "lost", "result_at": t.now(), "loss_reason": reason, "loss_note": d.get("note")})
    return jsonify(present_bid(t.get("bids", _id)))


@bp.delete("/bids/<_id>")
@api("leads")
def delete_bid(_id):
    b = t.get("bids", _id)
    if b.get("status") == "won" and t.get("projects", b.get("project_id"), required=False):
        abort(409, "Won bids cannot be deleted while their project exists")
    t.delete("bids", _id)
    return jsonify({"ok": True})


# ---------------- public website form (§2 source "Website form") ----------------
@bp.get("/public/lead-form/<key>")
def public_form_info(key):
    c = db.companies.find_one({"lead_form_key": key, "deleted_at": None})
    if not c or c.get("status") in ("suspended", "read_only", "cancelled"):
        abort(404, "This form is not available")
    return jsonify({"company": c["name"], "services": [s for s in SERVICES if s in c.get("modules", [])],
                    "project_types": PROJECT_TYPES, "timelines": LEAD_TIMELINES})


@bp.post("/public/lead-form/<key>")
def public_form_submit(key):
    c = db.companies.find_one({"lead_form_key": key, "deleted_at": None})
    if not c or c.get("status") in ("suspended", "read_only", "cancelled"):
        abort(404, "This form is not available")
    d = request.get_json(force=True) or {}
    if d.get("website"):  # honeypot: humans never see this field
        return jsonify({"ok": True}), 201
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    window = datetime.utcnow() - timedelta(minutes=10)
    if db.form_hits.count_documents({"ip": ip, "at": {"$gte": window}}) >= 5:
        abort(429, "Too many enquiries from this connection. Please try again later.")
    name = (d.get("name") or "").strip()
    phone, email = (d.get("phone") or "").strip(), (d.get("email") or "").strip().lower()
    if not name or len(name) > 120:
        abort(400, "Please enter your name")
    if not norm_phone(phone) and not email:
        abort(400, "Please enter a phone number or email")
    if email and not EMAIL_RE.match(email):
        abort(400, "Please enter a valid email")
    services = [s for s in SERVICES if s in c.get("modules", [])]
    service = d.get("service") if d.get("service") in services else services[0]
    db.form_hits.insert_one({"ip": ip, "at": datetime.utcnow(), "company_id": str(c["_id"])})
    g.cid, g.uid, g.user, g.company = str(c["_id"]), None, {"name": "Website form"}, c
    dup = find_duplicate(phone, email)
    note = (d.get("message") or "").strip()[:2000]
    if dup:  # captured once: add the new enquiry to the existing open lead instead of a duplicate
        t.update("leads", str(dup["_id"]), {}, raw={"$push": {"activities": history_entry(
            "note", f"New website enquiry from {name}: {note or '(no message)'}")}})
        return jsonify({"ok": True}), 201
    contact = t.insert("contacts", {"name": name, "kind": "person", "types": ["client"], "phone": phone or None,
                                    "email": email or None, "compliance": []})
    stage = (c.get("pipelines") or {}).get(service, PIPELINE)[0]
    t.insert("leads", {
        "title": f"{name} – {d.get('project_type') or service} enquiry", "contact_id": str(contact["_id"]),
        "contact_name": name, "phone_key": norm_phone(phone), "email_key": email or None, "service": service,
        "project_type": d.get("project_type") if d.get("project_type") in PROJECT_TYPES else None,
        "location": (d.get("location") or "")[:200] or None,
        "timeline": d.get("timeline") if d.get("timeline") in LEAD_TIMELINES else None,
        "budget": d.get("budget") if isinstance(d.get("budget"), (int, float)) and d["budget"] >= 0 else None,
        "area_unit": "sqft", "source": "Website form", "owner_id": None, "owner_name": None, "status": "open",
        "stage": stage, "notes": note or None, "activities": [], "first_response_at": None,
        "stage_history": [{"stage": stage, "at": t.now(), "by": "Website form"}]})
    return jsonify({"ok": True}), 201


# ---------------- sales report (§2 conversion by source, service, salesperson; win/loss reasons) ----------------
@bp.get("/reports/sales")
@api("leads", write=False)
def sales_report():
    q = {}
    if request.args.get("from"):
        q.setdefault("created_at", {})["$gte"] = datetime.fromisoformat(request.args["from"])
    if request.args.get("to"):
        q.setdefault("created_at", {})["$lt"] = datetime.fromisoformat(request.args["to"]) + timedelta(days=1)
    leads = t.find("leads", q)

    def group(key):
        out = {}
        for x in leads:
            k = x.get(key) or ("Unassigned" if key == "owner_name" else "—")
            r = out.setdefault(k, {"key": k, "leads": 0, "open": 0, "won": 0, "lost": 0, "won_value": 0.0,
                                   "response_hours": []})
            r["leads"] += 1
            r[x["status"]] += 1
            if x["status"] == "won":
                r["won_value"] += x.get("won_value") or x.get("budget") or 0
            if x.get("first_response_at"):
                r["response_hours"].append((x["first_response_at"] - x["created_at"]).total_seconds() / 3600)
        rows = []
        for r in out.values():
            closed = r["won"] + r["lost"]
            hrs = r.pop("response_hours")
            rows.append({**r, "won_value": round(r["won_value"], 2),
                         "conversion": round(r["won"] / closed * 100, 1) if closed else None,
                         "avg_response_hours": round(sum(hrs) / len(hrs), 1) if hrs else None})
        return sorted(rows, key=lambda r: -r["leads"])

    pipelines = {}
    for s in [s for s in SERVICES if s in g.company.get("modules", [])]:
        pipelines[s] = [{"stage": st, "count": sum(1 for x in leads if x["status"] == "open" and x["service"] == s and x["stage"] == st),
                         "value": round(sum(x.get("budget") or 0 for x in leads if x["status"] == "open" and x["service"] == s
                                            and x["stage"] == st), 2)} for st in pipeline(s)]
    reasons = {}
    for x in leads:
        if x["status"] == "lost":
            reasons[x.get("loss_reason") or "—"] = reasons.get(x.get("loss_reason") or "—", 0) + 1
    closed = [x for x in leads if x["status"] in ("won", "lost")]
    won = sum(1 for x in closed if x["status"] == "won")
    decided = t.find("bids", {"status": {"$in": ["won", "lost"]}})
    return jsonify({
        "totals": {"leads": len(leads), "open": sum(1 for x in leads if x["status"] == "open"), "won": won,
                   "lost": len(closed) - won, "conversion": round(won / len(closed) * 100, 1) if closed else None,
                   "open_value": round(sum(x.get("budget") or 0 for x in leads if x["status"] == "open"), 2),
                   "won_value": round(sum(x.get("won_value") or x.get("budget") or 0 for x in leads if x["status"] == "won"), 2)},
        "pipelines": pipelines, "by_source": group("source"), "by_service": group("service"),
        "by_salesperson": group("owner_name"),
        "loss_reasons": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])],
        "bids": {"decided": len(decided), "won": sum(1 for b in decided if b["status"] == "won"),
                 "hit_rate": round(sum(1 for b in decided if b["status"] == "won") / len(decided) * 100, 1) if decided else None},
    })
