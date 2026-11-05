"""Shared rules for the lead journey (Phase C+): sales settings, stage exit rules, value / probability / score,
visibility and the lead timeline."""
from datetime import datetime, date

from flask import g, abort

from ..db import db, oid
from .defaults import DEFAULT_STAGE_RULES, STAGE_REQUIREMENTS

SALES_DEFAULTS = {"manager_id": None, "response_minutes": 30, "max_discount_pct": 10.0, "min_margin_pct": 15.0,
                  "own_leads_only": False, "hot_idle_days": 3, "followup_escalate_days": 2}
SOURCE_POINTS = {"Referral": 20, "Repeat client": 20, "Walk-in": 15, "Website form": 10, "Houzz/portals": 10, "Ads": 5}
TEMP_POINTS = {"hot": 25, "warm": 15, "cold": 0}


def settings(company=None):
    return {**SALES_DEFAULTS, **((company or g.company).get("sales") or {})}


def stage_rules(service, stage, company=None):
    """Company rules for this stage, else the defaults for the standard stage names, else no rules."""
    custom = ((settings(company).get("stage_rules") or {}).get(service) or {}).get(stage)
    base = DEFAULT_STAGE_RULES.get(stage, {"checklist": [], "requires": [], "max_days": None, "probability": None})
    return {**base, **(custom or {})}


def is_manager(uid=None):
    uid = uid or g.uid
    return g.role == "owner" or uid == settings().get("manager_id")


def restricted():
    """Salespeople see only their own leads when the company switched that on."""
    return settings().get("own_leads_only") and g.role == "sales" and not is_manager()


def visible_q():
    return {"owner_id": g.uid} if restricted() else {}


def load_lead(_id):
    lead = db.leads.find_one({"_id": oid(_id), "company_id": g.cid, "status": {"$ne": "merged"}})
    if not lead or (restricted() and lead.get("owner_id") != g.uid):
        abort(404, "lead not found")
    return lead


def entry(kind, text, **extra):
    from ..tenancy import now, sid
    return {"id": sid(), "type": kind, "text": text, "at": now(), "by": (g.user or {}).get("name"),
            "by_id": getattr(g, "uid", None), **extra}


def log(lead_id, kind, text, **extra):
    """Append one entry to the lead timeline (the single log of everything done on a lead)."""
    from ..tenancy import now
    e = entry(kind, text, **extra)
    db.leads.update_one({"_id": oid(lead_id), "company_id": g.cid},
                        {"$push": {"activities": e}, "$set": {"updated_at": now()}})
    return e


def missing_for(lead, stage):
    """What still has to be done before the lead may leave `stage`."""
    rules = stage_rules(lead["service"], stage)
    lid = str(lead["_id"])
    ticked = (lead.get("checklist") or {}).get(stage) or {}
    out = [f"Checklist: {item}" for item in rules["checklist"] if item not in ticked]
    for req in rules["requires"]:
        ok = {
            "first_contact": lambda: bool(lead.get("first_response_at")),
            "visit_done": lambda: db.lead_visits.count_documents(
                {"company_id": g.cid, "lead_id": lid, "status": "done", "report.submitted_at": {"$ne": None}}) > 0,
            "measurements": lambda: bool((lead.get("measurements") or {}).get("rooms")
                                         or ((lead.get("measurements") or {}).get("plot") or {}).get("area")),
            "brief_complete": lambda: bool((lead.get("brief") or {}).get("complete")),
            "estimate_approved": lambda: db.estimates.count_documents(
                {"company_id": g.cid, "lead_id": lid, "status": "approved"}) > 0,
            "proposal_sent": lambda: db.proposals.count_documents(
                {"company_id": g.cid, "lead_id": lid, "sent_at": {"$ne": None}}) > 0,
        }.get(req, lambda: True)()
        if not ok:
            out.append(STAGE_REQUIREMENTS.get(req, req))
    return out


def lead_value(lead):
    return lead.get("proposal_value") or lead.get("estimate_value") or (lead.get("ballpark") or {}).get("amount") \
        or lead.get("budget") or 0


def days_in_stage(lead, now=None):
    since = lead.get("stage_entered_at") or lead.get("created_at")
    return max(0, ((now or datetime.utcnow()) - since).days) if since else 0


def probability(lead):
    if lead.get("probability") is not None:
        return lead["probability"]
    return stage_rules(lead["service"], lead["stage"]).get("probability") or 0


def score(lead, now=None):
    """0-100: source 20 + budget fit 25 + temperature 25 + last contact 15 + first response within target 15."""
    now = now or datetime.utcnow()
    s = SOURCE_POINTS.get(lead.get("source"), 0)
    bp = (lead.get("ballpark") or {}).get("amount")
    if bp and lead.get("budget"):
        s += 25 if lead["budget"] >= bp else 15 if lead["budget"] >= 0.8 * bp else 0
    else:
        s += 5
    s += TEMP_POINTS.get(lead.get("temperature"), 10)
    last = lead.get("last_activity_at")
    if last:
        age = (now - last).days
        s += 15 if age <= 7 else 8 if age <= 14 else 0
    fr = lead.get("first_response_at")
    if fr and (fr - lead["created_at"]).total_seconds() <= settings().get("response_minutes", 30) * 60:
        s += 15
    return min(100, s)


def today():
    return date.today().isoformat()
