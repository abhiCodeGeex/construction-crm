"""Leads & pipeline (section 2), bid register, contacts with per-project roles (section 3)."""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import register_crud, num
from ..db import db
from ..security import api
from .projects import create_project

bp = Blueprint("crm", __name__)


def _prep_lead(d, existing):
    d.setdefault("stage", "Lead")
    d.setdefault("status", "open")
    d.setdefault("activities", [])
    d.setdefault("owner_id", g.uid)
    d["budget"] = num(d.get("budget"))
    d["area"] = num(d.get("area"))
    if d.get("contact_id"):
        c = t.get("contacts", d["contact_id"], required=False)
        d["contact_name"] = c["name"] if c else None
    return d


register_crud(bp, "leads", "leads", search=("title", "contact_name", "location"),
              filters=("status", "stage", "service", "source", "owner_id"), prepare=_prep_lead)


@bp.post("/leads/<_id>/activities")
@api("leads")
def lead_activity(_id):
    d = request.get_json(force=True) or {}
    act = {"id": t.sid(), "type": d.get("type", "note"), "text": d.get("text", ""), "at": t.now(),
           "by": g.user.get("name")}
    t.update("leads", _id, {"last_activity": t.now()}, raw={"$push": {"activities": act}})
    if d.get("follow_up_on"):
        t.insert("followups", {
            "title": d.get("follow_up_title") or f"Follow up: {t.get('leads', _id)['title']}",
            "due": d["follow_up_on"], "priority": d.get("priority", "normal"), "status": "open",
            "owner_id": g.uid, "related": {"type": "lead", "id": _id}, "channel": d.get("type"),
        })
    return jsonify(t.out(t.get("leads", _id)))


@bp.post("/leads/<_id>/stage")
@api("leads")
def lead_stage(_id):
    stage = (request.get_json(force=True) or {}).get("stage")
    lead = t.update("leads", _id, {"stage": stage}, raw={"$push": {"activities": {
        "id": t.sid(), "type": "stage", "text": f"Moved to {stage}", "at": t.now(), "by": g.user.get("name")}}})
    return jsonify(t.out(lead))


@bp.post("/leads/<_id>/win")
@api("leads")
def lead_win(_id):
    lead = t.get("leads", _id)
    if lead.get("project_id"):
        return jsonify({"project_id": lead["project_id"]})
    d = request.get_json(force=True) or {}
    project = create_project({
        "name": d.get("name") or lead["title"],
        "services": d.get("services") or [lead.get("service") or "construction"],
        "client_id": lead.get("contact_id"), "address": lead.get("location"), "area": lead.get("area"),
        "area_unit": lead.get("area_unit", "sqft"), "value": lead.get("budget"), "lead_id": _id,
        "project_type": lead.get("project_type"),
    })
    t.update("leads", _id, {"status": "won", "stage": "Won", "won_at": t.now(),
                            "project_id": str(project["_id"])})
    return jsonify({"project_id": str(project["_id"])})


@bp.post("/leads/<_id>/lose")
@api("leads")
def lead_lose(_id):
    d = request.get_json(force=True) or {}
    lead = t.update("leads", _id, {"status": "lost", "stage": "Lost", "loss_reason": d.get("reason"),
                                   "lost_at": t.now()})
    # re-engage lost/cold leads after 3-6 months (section 16)
    t.insert("followups", {"title": f"Re-engage lost lead: {lead['title']}", "status": "open",
                           "due": (datetime.utcnow() + timedelta(days=120)).date().isoformat(),
                           "owner_id": lead.get("owner_id"), "priority": "low",
                           "related": {"type": "lead", "id": _id}})
    return jsonify(t.out(lead))


register_crud(bp, "bids", "leads", search=("title", "client"), filters=("decision", "result"),
              sort=("due_date", 1))


# ---------------- contacts ----------------
def _prep_contact(d, existing):
    d.setdefault("types", [])
    d.setdefault("compliance", [])
    d["rating"] = num(d.get("rating"))
    for doc in d["compliance"]:
        doc.setdefault("id", t.sid())
    return d


register_crud(bp, "contacts", "contacts", search=("name", "org", "email", "phone", "trade_category"),
              filters=("kind",), prepare=_prep_contact, sort=("name", 1))


@bp.get("/contacts/<_id>/history")
@api("contacts")
def contact_history(_id):
    contact = t.get("contacts", _id)
    projects = t.find("projects", {"$or": [{"client_id": _id}, {"team.contact_id": _id}]})
    roles = []
    for p in projects:
        role = "Client" if p.get("client_id") == _id else next(
            (m.get("role") for m in p.get("team", []) if m.get("contact_id") == _id), None)
        roles.append({"project_id": str(p["_id"]), "project": p["name"], "role": role, "status": p.get("status"),
                      "value": p.get("value")})
    referred = t.find("leads", {"referred_by": _id})
    leads = t.find("leads", {"contact_id": _id})
    timeline = list(db.messages.find({"company_id": g.cid, "contact_id": _id}).sort("created_at", -1).limit(50))
    followups = t.find("followups", {"related.id": _id})
    return jsonify({
        "contact": t.out(contact), "projects": roles,
        "referrals": [{"id": str(r["_id"]), "title": r["title"], "status": r["status"], "budget": r.get("budget")}
                      for r in referred],
        "won_from_referrals": sum(r.get("budget", 0) for r in referred if r["status"] == "won"),
        "leads": t.out(leads), "messages": t.out(timeline), "followups": t.out(followups),
    })


@bp.get("/contacts/compliance/expiring")
@api("contacts", write=False)
def compliance_expiring():
    days = int(request.args.get("days", 30))
    limit = (datetime.utcnow() + timedelta(days=days)).date().isoformat()
    rows = []
    for c in t.find("contacts", {"compliance.expiry": {"$lte": limit}}):
        for doc in c.get("compliance", []):
            if doc.get("expiry") and doc["expiry"] <= limit:
                rows.append({"contact_id": str(c["_id"]), "contact": c["name"], "document": doc.get("name"),
                             "expiry": doc["expiry"],
                             "expired": doc["expiry"] < datetime.utcnow().date().isoformat()})
    return jsonify(sorted(rows, key=lambda r: r["expiry"]))
