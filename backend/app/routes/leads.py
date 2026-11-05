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
                                 ACTIVITY_TYPES, LOGGABLE_ACTIVITIES, CALL_OUTCOMES, TEMPERATURES, CONTACT_CHANNELS,
                                 STAGE_REQUIREMENTS, FOLLOWUP_CHANNELS)
from ..services import notify, sales
from ..services.sales import load_lead, log
from .contacts import EMAIL_RE

bp = Blueprint("leads", __name__)

FIELDS = ("title", "contact_id", "service", "project_type", "location", "area", "area_unit", "budget", "timeline",
          "source", "source_detail", "referred_by", "owner_id", "notes", "temperature", "probability",
          "expected_close", "preferred_language", "best_time", "preferred_channel", "branch", "tags")
# shown in the timeline when an edit changes them (old -> new)
FIELD_LABELS = {"title": "Title", "contact_id": "Enquirer", "service": "Service", "project_type": "Project type",
                "location": "Location", "area": "Area", "area_unit": "Area unit", "budget": "Budget",
                "timeline": "Timeline", "source": "Source", "source_detail": "Source detail",
                "referred_by": "Referred by", "owner_id": "Salesperson", "notes": "Notes",
                "temperature": "Temperature", "probability": "Probability %", "expected_close": "Expected close",
                "preferred_language": "Language", "best_time": "Best time to call",
                "preferred_channel": "Preferred channel", "branch": "Branch", "tags": "Tags"}


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
    q = {"company_id": g.cid, "status": {"$in": ["open", "on_hold"]}, "$or": ors}
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
    if out.get("temperature") is not None and out["temperature"] not in TEMPERATURES:
        abort(400, "Temperature must be hot, warm or cold")
    if out.get("probability") not in (None, ""):
        p = out["probability"]
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0 <= p <= 100:
            abort(400, "Probability must be between 0 and 100")
    elif "probability" in out:
        out["probability"] = None  # back to the stage's default
    if out.get("expected_close"):
        try:
            out["expected_close"] = date.fromisoformat(str(out["expected_close"])[:10]).isoformat()
        except ValueError:
            abort(400, "Expected close must be a date (YYYY-MM-DD)")
    if out.get("preferred_channel") and out["preferred_channel"] not in CONTACT_CHANNELS:
        abort(400, f"Preferred channel must be one of: {', '.join(CONTACT_CHANNELS)}")
    if out.get("branch") and out["branch"] not in [b.get("name") for b in g.company.get("branches", [])]:
        abort(400, "Branch must be one of the company's branches")
    if "tags" in out:
        if not isinstance(out["tags"], list):
            abort(400, "Tags must be a list")
        out["tags"] = list(dict.fromkeys(str(x).strip() for x in out["tags"] if str(x).strip()))
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
    if lead.get("status") == "open":
        rules = sales.stage_rules(lead["service"], lead["stage"])
        days = sales.days_in_stage(lead)
        data.update(days_in_stage=days, max_days=rules.get("max_days"),
                    over_limit=bool(rules.get("max_days")) and days > rules["max_days"],
                    stage_checklist=rules["checklist"], stage_requires=[STAGE_REQUIREMENTS.get(r, r) for r in rules["requires"]],
                    missing=sales.missing_for(lead, lead["stage"]))
    prob = sales.probability(lead) if lead.get("status") == "open" else (100 if lead.get("status") == "won" else 0)
    value = sales.lead_value(lead)
    data.update(probability_effective=prob, value=value, weighted_value=round(value * prob / 100, 2),
                score=sales.score(lead))
    return data


history_entry = sales.entry


def lead_link(lead_or_id):
    return f"/app/leads/{lead_or_id if isinstance(lead_or_id, str) else lead_or_id['_id']}"


# ---------------- meta & pipelines ----------------
@bp.get("/leads/meta")
@api("leads", write=False)
def meta():
    services = [s for s in SERVICES if s in g.company.get("modules", [])]
    staff_list = [{"id": str(u["_id"]), "name": u["name"], "role": u["role"]}
             for u in db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}})]
    pms = [u for u in staff_list if "w" in effective_perms(u["role"], g.company).get("projects", "")]
    return jsonify({"sources": LEAD_SOURCES, "project_types": PROJECT_TYPES, "timelines": LEAD_TIMELINES,
                    "services": services, "pipelines": {s: pipeline(s) for s in services},
                    "loss_reasons": loss_reasons(), "activity_types": LOGGABLE_ACTIVITIES, "staff": staff_list,
                    "call_outcomes": CALL_OUTCOMES, "temperatures": TEMPERATURES, "channels": CONTACT_CHANNELS,
                    "branches": [b.get("name") for b in g.company.get("branches", [])],
                    "requirements": STAGE_REQUIREMENTS, "is_manager": sales.is_manager(),
                    "stage_rules": {s: {st: sales.stage_rules(s, st) for st in pipeline(s)} for s in services},
                    "sales_settings": sales_settings_out(),
                    "project_managers": pms, "form_key": g.company.get("lead_form_key") if can("settings") else None})


def sales_settings_out():
    s = sales.settings()
    return {k: s.get(k) for k in sales.SALES_DEFAULTS}


@bp.put("/leads/settings")
@api("settings")
def put_sales_settings():
    """Settings -> Sales: manager, response target, approval limits, visibility, escalation days, stage rules."""
    d = request.get_json(force=True) or {}
    s = dict(g.company.get("sales") or {})
    if "manager_id" in d:
        s["manager_id"] = str(staff(d["manager_id"], "Sales manager")["_id"]) if d["manager_id"] else None
    for k, lo, hi in (("response_minutes", 1, 10080), ("max_discount_pct", 0, 100), ("min_margin_pct", 0, 100),
                      ("hot_idle_days", 1, 365), ("followup_escalate_days", 1, 365)):
        if k in d:
            v = d[k]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                abort(400, f"{k.replace('_', ' ').capitalize()} must be between {lo} and {hi}")
            s[k] = v
    if "own_leads_only" in d:
        s["own_leads_only"] = bool(d["own_leads_only"])
    if "stage_rules" in d:
        rules = {}
        for service, stages in (d["stage_rules"] or {}).items():
            if service not in SERVICES:
                abort(400, "Unknown service")
            rules[service] = {}
            for stage, r in (stages or {}).items():
                if stage not in pipeline(service):
                    abort(400, f"'{stage}' is not a stage of the {service} pipeline")
                req = [x for x in (r.get("requires") or [])]
                bad = [x for x in req if x not in STAGE_REQUIREMENTS]
                if bad:
                    abort(400, f"Unknown required step: {', '.join(bad)}")
                items = list(dict.fromkeys(str(x).strip() for x in (r.get("checklist") or []) if str(x).strip()))
                md, pr = r.get("max_days"), r.get("probability")
                if md not in (None, "") and (not isinstance(md, int) or isinstance(md, bool) or md < 1):
                    abort(400, f"Day limit for {stage} must be a whole number of days")
                if pr not in (None, "") and (not isinstance(pr, (int, float)) or isinstance(pr, bool) or not 0 <= pr <= 100):
                    abort(400, f"Probability for {stage} must be between 0 and 100")
                rules[service][stage] = {"checklist": items, "requires": req, "max_days": md or None,
                                         "probability": pr if pr not in ("",) else None}
        s["stage_rules"] = {**(s.get("stage_rules") or {}), **rules}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"sales": s}})
    t.audit("update", "sales_settings", g.company["_id"], note=", ".join(sorted(d)))
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return meta()


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
    q = {"status": {"$ne": "merged"}, **sales.visible_q()}
    for k in ("service", "status", "stage", "source", "temperature", "branch"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("tag"):
        q["tags"] = request.args["tag"]
    if request.args.get("owner_id") == "none":
        q["owner_id"] = None
    elif request.args.get("owner_id") and not sales.restricted():
        q["owner_id"] = request.args["owner_id"]
    if request.args.get("q"):
        rx = {"$regex": re.escape(request.args["q"]), "$options": "i"}
        q["$or"] = [{"title": rx}, {"contact_name": rx}, {"location": rx}]
    return jsonify([present(x) for x in t.find("leads", q, sort=[("created_at", -1)])])


def notify_assignment(lead, previous_owner=None):
    """New or changed salesperson: the salesperson is told; a lead nobody owns goes to the sales manager."""
    lid = str(lead["_id"])
    if lead.get("owner_id"):
        notify.send("lead_reassigned" if previous_owner else "lead_assigned", [lead["owner_id"]],
                    f"{lead['title']} ({lead.get('contact_name')}) is now yours", lead_link(lid), lid)
        if previous_owner and previous_owner != lead["owner_id"]:
            notify.send("lead_reassigned", [previous_owner],
                        f"{lead['title']} was reassigned to {lead.get('owner_name')}", lead_link(lid), lid)
    else:
        notify.send("lead_unassigned", notify.managers(),
                    f"{lead['title']} ({lead.get('source')}) has no salesperson yet", lead_link(lid), lid)


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
    if "owner_id" not in d:
        data["owner_id"], data["owner_name"] = g.uid, g.user.get("name")
    stage = pipeline(data["service"])[0]
    who = f", assigned to {data.get('owner_name')}" if data.get("owner_id") else ", unassigned"
    data.update(status="open", stage=stage, stage_entered_at=t.now(), first_response_at=None,
                activities=[history_entry("created", f"Lead created ({data['source']}){who}")],
                stage_history=[{"stage": stage, "at": t.now(), "by": g.user.get("name")}])
    if new_contact:  # everything is valid: now the enquirer becomes a contact
        data["contact_id"] = str(t.insert("contacts", new_contact)["_id"])
    lead = t.insert("leads", data)
    notify_assignment(lead)
    return jsonify(present(lead)), 201


@bp.get("/leads/<_id>")
@api("leads")
def get_lead(_id):
    data = present(load_lead(_id))
    data["bids"] = [present_bid(b) for b in t.find("bids", {"lead_id": _id}, sort=[("due_date", 1)])]
    return jsonify(data)


def editable(lead):
    if lead["status"] != "open":
        hint = {"lost": " — reopen it first", "on_hold": " — resume it first"}.get(lead["status"], "")
        abort(409, f"This lead is {lead['status'].replace('_', ' ')} and read-only{hint}")


def show(field, v):
    """A field value as the timeline shows it."""
    if v in (None, "", []):
        return "—"
    if field in ("contact_id", "referred_by"):
        c = db.contacts.find_one({"_id": oid(v), "company_id": g.cid}, {"name": 1})
        return c["name"] if c else str(v)
    if field == "owner_id":
        u = db.users.find_one({"_id": oid(v), "company_id": g.cid}, {"name": 1})
        return u["name"] if u else str(v)
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def changes_of(lead, data):
    return [{"field": FIELD_LABELS[k], "from": show(k, lead.get(k)), "to": show(k, data[k])}
            for k in FIELDS if k in data and (lead.get(k) or None) != (data[k] or None)]


@bp.put("/leads/<_id>")
@api("leads")
def update_lead(_id):
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    data = clean(d, lead)
    raw = {"$push": {}}
    if data.get("service", lead["service"]) != lead["service"] and lead["stage"] not in pipeline(data["service"]):
        data["stage"] = pipeline(data["service"])[0]
        data["stage_entered_at"] = t.now()
        raw["$push"]["stage_history"] = {"stage": data["stage"], "at": t.now(), "by": g.user.get("name"),
                                         "from": lead["stage"]}
    reassigned = "owner_id" in data and data["owner_id"] != lead.get("owner_id")
    if reassigned and data.get("owner_id") and lead.get("owner_id"):
        # reassigning a lead hands over the previous salesperson's open follow-ups on it
        db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open",
                                  "owner_id": lead["owner_id"]},
                                 {"$set": {"owner_id": data["owner_id"], "owner_name": data["owner_name"]}})
    diff = changes_of(lead, data)
    if not diff and "stage" not in data:
        return jsonify(present(lead))
    text = "Edited: " + "; ".join(f"{c['field']} {c['from']} → {c['to']}" for c in diff)
    raw["$push"]["activities"] = history_entry("edit", text, changes=diff)
    updated = t.update("leads", _id, data, raw=raw)
    if reassigned:
        notify_assignment(updated, lead.get("owner_id"))
    return jsonify(present(updated))


@bp.delete("/leads/<_id>")
@api("leads")
def delete_lead(_id):
    if g.role != "owner":
        abort(403, "Only the owner can delete a lead; record it as lost instead")
    lead = load_lead(_id)
    if lead["status"] == "won" and t.get("projects", lead.get("project_id"), required=False):
        abort(409, "Won leads cannot be deleted while their project exists")
    if db.lead_receipts.count_documents({"company_id": g.cid, "lead_id": _id, "status": {"$ne": "void"}}):
        abort(409, "Money was received on this lead; void its receipts first (or record the lead as lost)")
    t.delete("leads", _id)
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Lead deleted"}})
    db.bids.update_many({"company_id": g.cid, "lead_id": _id}, {"$set": {"lead_id": None, "lead_title": None}})
    db.notifications.delete_many({"company_id": g.cid, "lead_id": _id})  # no bell entry may point at a deleted lead
    # the lead's own records go with it; files leave storage too
    from .lead_steps import delete_stored
    for f in db.lead_files.find({"company_id": g.cid, "lead_id": _id, "project_id": None}):
        delete_stored(f["key"])
    db.lead_files.delete_many({"company_id": g.cid, "lead_id": _id, "project_id": None})
    for coll in ("lead_visits", "lead_expenses", "lead_receipts", "estimates", "proposals"):
        db[coll].delete_many({"company_id": g.cid, "lead_id": _id})
    return jsonify({"ok": True})


def change_stage(lead, stage, override_reason=None):
    """Forward moves need every stage passed to meet its exit rules (no skipping); moving back is free.
    The Owner may override with a reason, which is logged."""
    _id = str(lead["_id"])
    stages = pipeline(lead["service"])
    if stage not in stages:
        abort(400, f"'{stage}' is not a stage of the {lead['service']} pipeline")
    if stage == lead["stage"]:
        return lead
    cur = stages.index(lead["stage"]) if lead["stage"] in stages else 0
    target = stages.index(stage)
    missing = []
    for st in (stages[cur:target] if target > cur else []):
        missing += [f"{st}: {m}" for m in sales.missing_for(lead, st)]
    text = f"Moved from {lead['stage']} to {stage}"
    if missing:
        if not override_reason:
            abort(409, "Not ready to move on. Still to do — " + " · ".join(missing))
        if g.role != "owner":
            abort(403, "Only the owner can move a lead past unfinished steps")
        text += f" (owner override: {override_reason}; skipped {', '.join(missing)})"
    hist = {"stage": stage, "at": t.now(), "by": g.user.get("name"), "from": lead["stage"]}
    return t.update("leads", _id, {"stage": stage, "stage_entered_at": t.now()},
                    raw={"$push": {"stage_history": hist, "activities": history_entry("stage", text)}})


@bp.post("/leads/<_id>/stage")
@api("leads")
def move_stage(_id):
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    return jsonify(present(change_stage(lead, d.get("stage"), (d.get("override_reason") or "").strip() or None)))


@bp.post("/leads/<_id>/checklist")
@api("leads")
def tick(_id):
    """Tick or untick an item of a stage's checklist."""
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    stage, item = d.get("stage"), d.get("item")
    if stage not in pipeline(lead["service"]) or item not in sales.stage_rules(lead["service"], stage)["checklist"]:
        abort(400, "That item is not on this stage's checklist")
    ticked = dict(lead.get("checklist") or {})
    items = dict(ticked.get(stage) or {})
    if d.get("done"):
        items[item] = {"by": g.user.get("name"), "at": t.now()}
        text = f"Checklist ({stage}): ticked “{item}”"
    else:
        items.pop(item, None)
        text = f"Checklist ({stage}): unticked “{item}”"
    ticked[stage] = items
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"checklist": ticked}})
    log(_id, "checklist", text)
    return jsonify(present(load_lead(_id)))


CONTACT_TYPES = ("call", "email", "whatsapp", "meeting")


@bp.post("/leads/<_id>/activities")
@api("leads")
def add_activity(_id):
    """§2 call / email / WhatsApp log and meeting notes. A call or meeting needs its outcome and the next step."""
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    kind = d.get("type")
    if kind == "site_visit":
        abort(400, "Book the site visit as an appointment (Visits tab) so it is scheduled, reminded and reported")
    if kind not in LOGGABLE_ACTIVITIES:
        abort(400, f"Activity type must be one of: {', '.join(LOGGABLE_ACTIVITIES)}")
    if not (d.get("text") or "").strip():
        abort(400, "Write what happened")
    outcome = (d.get("outcome") or "").strip() or None
    if kind == "call" and outcome not in CALL_OUTCOMES:
        abort(400, f"Choose the call outcome: {', '.join(CALL_OUTCOMES)}")
    if kind == "meeting" and not outcome:
        abort(400, "Record the outcome of the meeting")
    next_due = d.get("next_due") or None
    if kind in ("call", "meeting") and outcome != "Wrong number" and not next_due:
        abort(400, "Set the next follow-up date (the next step)")
    if next_due:
        try:
            next_due = date.fromisoformat(str(next_due)[:10]).isoformat()
        except ValueError:
            abort(400, "Next follow-up must be a date (YYYY-MM-DD)")
        if next_due < sales.today():
            abort(400, "The next follow-up cannot be in the past")
    duration = d.get("duration_min")
    if duration not in (None, "") and (not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0):
        abort(400, "Duration must be a number of minutes")
    act = history_entry(kind, d["text"].strip(), outcome=outcome, template_id=d.get("template_id"),
                        duration_min=duration or None, next_due=next_due)
    changes = {"last_activity_at": t.now()}
    if kind in CONTACT_TYPES and not lead.get("first_response_at"):
        changes["first_response_at"] = t.now()
    updated = t.update("leads", _id, changes, raw={"$push": {"activities": act}})
    if next_due:
        owner = lead.get("owner_id") or g.uid
        u = db.users.find_one({"_id": oid(owner)}, {"name": 1})
        t.insert("followups", {"title": (d.get("next_title") or "").strip() or f"Follow up: {lead['title']}",
                               "due": next_due, "priority": "normal",
                               "channel": d.get("next_channel") if d.get("next_channel") in FOLLOWUP_CHANNELS else kind,
                               "owner_id": owner, "owner_name": u and u["name"], "status": "open",
                               "related": {"type": "lead", "id": _id, "label": lead["title"],
                                           "contact_id": lead.get("contact_id")}})
    return jsonify(present(updated)), 201


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
    pm = project_manager(d.get("pm_id"))
    extra = []
    if lead.get("owner_id") and lead["owner_id"] != d["pm_id"]:
        extra.append({"user_id": lead["owner_id"], "name": lead.get("owner_name"), "project_role": "Sales", "access": "view"})
    value = num(d.get("value"), "Value") if d.get("value") not in (None, "") else \
        ((bid or {}).get("value") or lead.get("proposal_value") or lead.get("budget") or 0)
    project = new_project({
        "name": (d.get("project_name") or lead["title"]).strip(), "services": [lead["service"]],
        "client_id": lead["contact_id"], "project_type": lead.get("project_type"), "start": d.get("start"),
        "area": lead.get("area") or 0, "area_unit": lead.get("area_unit", "sqft"), "value": value,
        "referred_by": lead.get("referred_by"), "site": {"line1": lead.get("location")},
        "description": lead.get("notes"),
    }, d["pm_id"], extra, {"lead_id": _id, **({"bid_id": str(bid["_id"])} if bid else {})})
    pid, code = str(project["_id"]), project["code"]
    act = history_entry("won", f"Won — project {code} created, PM {pm['name']}, value {money_text(value)}" +
                        (f" (bid {bid['title']})" if bid else ""), project_id=pid)
    t.update("leads", _id, {"status": "won", "won_at": t.now(), "project_id": pid,
                            "project_code": code, "won_value": project.get("value")},
             raw={"$push": {"activities": act, "stage_history": {"stage": "Won", "at": t.now(), "by": g.user.get("name"),
                                                                 "from": lead["stage"]}}})
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"related": {"type": "project", "id": pid, "label": project["name"]}}})
    close_bids(_id, "won", {"project_id": pid, "project_code": code})
    from .lead_money import hand_over_to_project
    hand_over_to_project(lead, project, d["pm_id"], d.get("advance"))
    link = f"/app/projects/{pid}"
    notify.send("project_pm", [d["pm_id"]], f"You are the project manager of {code} {project['name']} (won by "
                f"{g.user.get('name')})", link, _id)
    notify.send("lead_won", notify.managers() + [lead.get("owner_id")], f"{lead['title']} won — {money_text(value)}, "
                f"project {code}", link, _id)
    notify.send("advance_received", notify.role_users("accounts"),
                f"New project {code} {project['name']}: contract value {money_text(value)}", link, _id)
    return project


def money_text(v):
    from .followups import money
    return money(v) or "—"


def lose_lead(lead, reason, note=None, competitor=None, competitor_price=None, reengage_on=None):
    """Lost: reason (company list), note, who won it and at what price, and optionally a day to try again."""
    _id = str(lead["_id"])
    bits = [f"Lost — {reason}"] + ([note] if note else []) + \
        ([f"to {competitor}" + (f" at {money_text(competitor_price)}" if competitor_price else "")] if competitor else []) + \
        ([f"re-engage on {reengage_on}"] if reengage_on else [])
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": _id, "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Lead lost"}})
    close_bids(_id, "lost", {"loss_reason": reason, "loss_note": note, "competitor": competitor,
                             "competitor_price": competitor_price})
    if reengage_on:  # §16 re-engage lost / cold leads: a follow-up for that day, owned by the salesperson
        owner = lead.get("owner_id") or (notify.managers() or [g.uid])[0]
        u = db.users.find_one({"_id": oid(owner)}, {"name": 1})
        t.insert("followups", {"title": f"Re-engage: {lead['title']}", "due": reengage_on, "priority": "normal",
                               "channel": "call", "owner_id": owner, "owner_name": u and u["name"], "status": "open",
                               "kind": "reengage", "related": {"type": "lead", "id": _id, "label": lead["title"],
                                                               "contact_id": lead.get("contact_id")}})
    updated = t.update("leads", _id, {"status": "lost", "lost_at": t.now(), "loss_reason": reason, "loss_note": note,
                                      "competitor": competitor, "competitor_price": competitor_price,
                                      "reengage_on": reengage_on, "lost_from_stage": lead["stage"]},
                       raw={"$push": {"activities": history_entry("lost", " · ".join(bits)), "stage_history": {
                           "stage": "Lost", "at": t.now(), "by": g.user.get("name"), "from": lead["stage"]}}})
    notify.send("lead_lost", notify.managers() + [lead.get("owner_id")],
                f"{lead['title']} lost — {reason}" + (f" (to {competitor})" if competitor else ""), lead_link(_id), _id)
    return updated


def loss_details(d):
    """Competitor, their price and the re-engage date given with a loss."""
    competitor = (d.get("competitor") or "").strip() or None
    price = num(d.get("competitor_price"), "Competitor price") if d.get("competitor_price") not in (None, "") else None
    reengage = d.get("reengage_on") or None
    if reengage:
        try:
            reengage = date.fromisoformat(str(reengage)[:10]).isoformat()
        except ValueError:
            abort(400, "Re-engage date must be a date (YYYY-MM-DD)")
        if reengage <= sales.today():
            abort(400, "The re-engage date must be in the future")
    if price and not competitor:
        abort(400, "Name the competitor whose price you entered")
    return {"competitor": competitor, "competitor_price": price, "reengage_on": reengage}


def close_bids(lead_id, result, extra):
    """A lead's submitted bids take the lead's result, so the hit rate and the register stay true."""
    for b in t.find("bids", {"lead_id": lead_id, "decision": "bid", "status": "submitted"}):
        t.update("bids", str(b["_id"]), {"status": result, "result_at": t.now(), **extra})


@bp.post("/leads/<_id>/win")
@api("leads")
def win(_id):
    lead = load_lead(_id)
    editable(lead)
    project = win_lead(lead, request.get_json(force=True) or {})
    return jsonify({"lead": present(t.get("leads", _id)), "project_id": str(project["_id"])})


@bp.post("/leads/<_id>/lose")
@api("leads")
def lose(_id):
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    return jsonify(present(lose_lead(lead, loss_reason(d), d.get("note"), **loss_details(d))))


@bp.post("/leads/<_id>/reopen")
@api("leads")
def reopen(_id):
    lead = load_lead(_id)
    if lead["status"] != "lost":
        abort(409, "Only lost leads can be reopened")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip()
    stage = lead.get("lost_from_stage") if lead.get("lost_from_stage") in pipeline(lead["service"]) else pipeline(lead["service"])[0]
    db.followups.update_many({"company_id": g.cid, "related.id": _id, "kind": "reengage", "status": "open"},
                             {"$set": {"status": "cancelled", "outcome": "Lead reopened"}})
    act = history_entry("reopened", f"Reopened at {stage}" + (f" — {reason}" if reason else ""))
    return jsonify(present(t.update("leads", _id, {"status": "open", "stage": stage, "stage_entered_at": t.now(),
                                                   "loss_reason": None, "loss_note": None, "competitor": None,
                                                   "competitor_price": None, "reengage_on": None},
                                    raw={"$push": {"activities": act, "stage_history": {
                                        "stage": stage, "at": t.now(), "by": g.user.get("name"), "from": "Lost"}}})))


@bp.post("/leads/<_id>/hold")
@api("leads")
def hold(_id):
    """On hold: out of the active pipeline (not a loss) until the resume date, when it comes back on its own."""
    lead = load_lead(_id)
    editable(lead)
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    if not reason:
        abort(400, "Say why the lead is on hold")
    try:
        resume_on = date.fromisoformat(str(d.get("resume_on") or "")[:10]).isoformat()
    except ValueError:
        abort(400, "Choose the date to resume (YYYY-MM-DD)")
    if resume_on <= sales.today():
        abort(400, "The resume date must be in the future")
    act = history_entry("on_hold", f"On hold until {resume_on} — {reason}")
    return jsonify(present(t.update("leads", _id, {"status": "on_hold", "hold_reason": reason, "resume_on": resume_on,
                                                   "held_at": t.now()}, raw={"$push": {"activities": act}})))


def resume_lead(lead, text):
    _id = str(lead["_id"])
    # time on hold does not count as time in the stage
    held = (t.now() - lead["held_at"]) if lead.get("held_at") else None
    entered = (lead.get("stage_entered_at") or lead["created_at"]) + held if held else lead.get("stage_entered_at")
    updated = t.update("leads", _id, {"status": "open", "hold_reason": None, "resume_on": None, "held_at": None,
                                      "stage_entered_at": entered},
                       raw={"$push": {"activities": history_entry("resumed", text)}})
    return updated


@bp.post("/leads/<_id>/resume")
@api("leads")
def resume(_id):
    lead = load_lead(_id)
    if lead["status"] != "on_hold":
        abort(409, "Only a lead on hold can be resumed")
    return jsonify(present(resume_lead(lead, f"Resumed at {lead['stage']} (was on hold: {lead.get('hold_reason')})")))


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
    extra = loss_details(d)
    lead = t.get("leads", b["lead_id"], required=False) if b.get("lead_id") else None
    if lead and lead["status"] in ("open", "on_hold"):
        lose_lead(lead, reason, d.get("note"), **extra)  # closes this bid too
    else:
        t.update("bids", _id, {"status": "lost", "result_at": t.now(), "loss_reason": reason, "loss_note": d.get("note"),
                               "competitor": extra["competitor"], "competitor_price": extra["competitor_price"]})
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
        notify.send("lead_assigned" if dup.get("owner_id") else "lead_unassigned",
                    [dup["owner_id"]] if dup.get("owner_id") else notify.managers(),
                    f"{name} enquired again on the website about {dup['title']}"
                    + (" (the lead is on hold)" if dup["status"] == "on_hold" else ""), lead_link(dup), str(dup["_id"]),
                    skip_self=False)
        return jsonify({"ok": True}), 201
    contact = t.insert("contacts", {"name": name, "kind": "person", "types": ["client"], "phone": phone or None,
                                    "email": email or None, "compliance": []})
    stage = (c.get("pipelines") or {}).get(service, PIPELINE)[0]
    lead = t.insert("leads", {
        "title": f"{name} – {d.get('project_type') or service} enquiry", "contact_id": str(contact["_id"]),
        "contact_name": name, "phone_key": norm_phone(phone), "email_key": email or None, "service": service,
        "project_type": d.get("project_type") if d.get("project_type") in PROJECT_TYPES else None,
        "location": (d.get("location") or "")[:200] or None,
        "timeline": d.get("timeline") if d.get("timeline") in LEAD_TIMELINES else None,
        "budget": d.get("budget") if isinstance(d.get("budget"), (int, float)) and d["budget"] >= 0 else None,
        "area_unit": "sqft", "source": "Website form", "owner_id": None, "owner_name": None, "status": "open",
        "stage": stage, "stage_entered_at": t.now(), "notes": note or None, "first_response_at": None,
        "activities": [history_entry("created", "Lead created (Website form), unassigned")],
        "stage_history": [{"stage": stage, "at": t.now(), "by": "Website form"}]})
    notify_assignment(lead)
    return jsonify({"ok": True}), 201


# ---------------- sales report (§2 conversion by source, service, salesperson; win/loss reasons) ----------------
@bp.get("/reports/sales")
@api("leads", write=False)
def sales_report():
    q = {"status": {"$ne": "merged"}, **sales.visible_q()}
    if request.args.get("from"):
        q.setdefault("created_at", {})["$gte"] = datetime.fromisoformat(request.args["from"])
    if request.args.get("to"):
        q.setdefault("created_at", {})["$lt"] = datetime.fromisoformat(request.args["to"]) + timedelta(days=1)
    leads = t.find("leads", q)

    def group(key):
        out = {}
        for x in leads:
            k = x.get(key) or ("Unassigned" if key == "owner_name" else "—")
            r = out.setdefault(k, {"key": k, "leads": 0, "open": 0, "on_hold": 0, "won": 0, "lost": 0,
                                   "won_value": 0.0, "response_hours": []})
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
