"""Lead journey steps 2 and 4 (C+2): decision-makers, ballpark from package rates, the requirement brief with
versions and client confirmation, and the public client questionnaire."""
import secrets

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, sales
from ..services.defaults import STAKEHOLDER_ROLES, WORK_TYPES, QUESTIONNAIRE, SERVICES
from ..services.sales import load_lead, log
from .lead_steps import open_lead, num, client_email

bp = Blueprint("lead_brief", __name__)
SQM_TO_SQFT = 10.7639


# ---------------- decision-makers ----------------
@bp.post("/leads/<_id>/stakeholders")
@api("leads")
def add_stakeholder(_id):
    """A person who decides with the enquirer: an existing contact, or a new one created from name + phone / email."""
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    role = d.get("role")
    if role not in STAKEHOLDER_ROLES:
        abort(400, f"Role must be one of: {', '.join(STAKEHOLDER_ROLES)}")
    if d.get("contact_id"):
        c = t.get("contacts", d["contact_id"], required=False) or abort(400, "Contact not found")
    else:
        name = (d.get("name") or "").strip()
        if not name or not ((d.get("phone") or "").strip() or (d.get("email") or "").strip()):
            abort(400, "Choose a contact, or enter a name with a phone or email")
        from .contacts import EMAIL_RE
        if d.get("email") and not EMAIL_RE.match(d["email"].strip()):
            abort(400, "Email is not valid")
        c = t.insert("contacts", {"name": name, "kind": "person", "types": ["client"], "phone": (d.get("phone") or "").strip() or None,
                                  "email": (d.get("email") or "").strip().lower() or None, "compliance": []})
    cid = str(c["_id"])
    if cid == lead.get("contact_id"):
        abort(409, "This is already the enquirer of the lead")
    people = list(lead.get("stakeholders") or [])
    if any(p["contact_id"] == cid for p in people):
        abort(409, f"{c['name']} is already a decision-maker on this lead")
    main = bool(d.get("main"))
    if main:
        people = [{**p, "main": False} for p in people]
    people.append({"id": t.sid(), "contact_id": cid, "name": c["name"], "role": role, "main": main,
                   "phone": c.get("phone"), "email": c.get("email")})
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"stakeholders": people}})
    log(_id, "stakeholder", f"Decision-maker added: {c['name']} ({role}){' — main decision-maker' if main else ''}")
    return jsonify(serialize(people)), 201


@bp.put("/leads/<_id>/stakeholders/<sid>")
@api("leads")
def edit_stakeholder(_id, sid):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    people = list(lead.get("stakeholders") or [])
    p = next((x for x in people if x["id"] == sid), None) or abort(404, "decision-maker not found")
    notes = []
    if "role" in d and d["role"] != p["role"]:
        if d["role"] not in STAKEHOLDER_ROLES:
            abort(400, f"Role must be one of: {', '.join(STAKEHOLDER_ROLES)}")
        notes.append(f"role {p['role']} → {d['role']}")
        p["role"] = d["role"]
    if "main" in d and bool(d["main"]) != p["main"]:
        if d["main"]:
            for x in people:
                x["main"] = False
        p["main"] = bool(d["main"])
        notes.append("now the main decision-maker" if p["main"] else "no longer the main decision-maker")
    if notes:
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {"stakeholders": people}})
        log(_id, "stakeholder", f"{p['name']}: " + "; ".join(notes))
    return jsonify(serialize(people))


@bp.delete("/leads/<_id>/stakeholders/<sid>")
@api("leads")
def remove_stakeholder(_id, sid):
    lead = open_lead(_id)
    people = list(lead.get("stakeholders") or [])
    p = next((x for x in people if x["id"] == sid), None) or abort(404, "decision-maker not found")
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"stakeholders": [x for x in people if x["id"] != sid]}})
    log(_id, "stakeholder", f"Decision-maker removed: {p['name']} ({p['role']})")
    return jsonify({"ok": True})


# ---------------- ballpark ----------------
def package_rates(service):
    return ((sales.settings().get("package_rates") or {}).get(service)) or []


@bp.put("/leads/package-rates")
@api("settings")
def set_package_rates():
    """Settings -> Sales: packages per service (e.g. Basic / Premium / Luxury) with a rate per sq ft or m²."""
    d = request.get_json(force=True) or {}
    rates = {}
    for service, rows in (d.get("package_rates") or {}).items():
        if service not in SERVICES:
            abort(400, "Unknown service")
        clean = []
        for r in rows or []:
            name = (r.get("name") or "").strip()
            if not name:
                abort(400, "Every package needs a name")
            rate = num(r.get("rate"), f"Rate for {name}", required=True, positive=True)
            if r.get("unit", "sqft") not in ("sqft", "sqm"):
                abort(400, "Rate unit must be per sq ft or per m²")
            clean.append({"name": name, "rate": rate, "unit": r.get("unit", "sqft")})
        if len({x["name"].lower() for x in clean}) != len(clean):
            abort(400, "Package names must be unique")
        rates[service] = clean
    s = dict(g.company.get("sales") or {})
    s["package_rates"] = {**(s.get("package_rates") or {}), **rates}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"sales": s}})
    t.audit("update", "package_rates", g.company["_id"], note=", ".join(rates))
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return jsonify(s["package_rates"])


@bp.get("/leads/package-rates")
@api("leads", write=False)
def get_package_rates():
    return jsonify(sales.settings().get("package_rates") or {})


@bp.post("/leads/<_id>/ballpark")
@api("leads")
def ballpark(_id):
    """Area × package rate, so the first conversation already has a price; warns when the budget is short."""
    lead = open_lead(_id)
    pkg_name = (request.get_json(force=True) or {}).get("package")
    pkgs = package_rates(lead["service"])
    if not pkgs:
        abort(400, "Set the package rates for this service in Settings → Sales first")
    pkg = next((p for p in pkgs if p["name"] == pkg_name), None) or abort(400, "Choose one of the packages")
    if not lead.get("area"):
        abort(400, "Enter the lead's area first")
    area = lead["area"]
    lu = lead.get("area_unit", "sqft")
    if lu != pkg["unit"]:
        area = area * SQM_TO_SQFT if lu == "sqm" else area / SQM_TO_SQFT
    amount = round(area * pkg["rate"], 2)
    gap = round(lead["budget"] - amount, 2) if lead.get("budget") else None
    bp_ = {"package": pkg["name"], "rate": pkg["rate"], "unit": pkg["unit"], "area": round(area, 2), "amount": amount,
           "budget_gap": gap, "at": t.now(), "by": g.user.get("name")}
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"ballpark": bp_}})
    from .leads import money_text
    warn = f" — budget is short by {money_text(-gap)}" if gap is not None and gap < 0 else ""
    log(_id, "ballpark", f"Ballpark {pkg['name']}: {bp_['area']:g} {pkg['unit']} × {money_text(pkg['rate'])} = {money_text(amount)}{warn}")
    return jsonify(serialize(bp_))


# ---------------- requirement brief ----------------
BRIEF_TEXT = {"style": "Style", "materials": "Materials", "brands": "Brands", "must_haves": "Must-haves",
              "nice_to_haves": "Nice-to-haves", "programme": "Spaces / programme", "approvals_needed": "Approvals needed",
              "notes": "Notes"}


def clean_scope(rows):
    scope = []
    for r in rows or []:
        room = (r.get("room") or "").strip()
        if not room:
            abort(400, "Each scope row needs a room or area")
        bad = [w for w in r.get("work_types") or [] if w not in WORK_TYPES]
        if bad:
            abort(400, f"Unknown work type: {', '.join(bad)}")
        if not r.get("work_types"):
            abort(400, f"Choose the work for {room}")
        scope.append({"room": room, "work_types": list(dict.fromkeys(r["work_types"])), "notes": (r.get("notes") or "").strip() or None})
    return scope


@bp.put("/leads/<_id>/brief")
@api("leads")
def save_brief(_id):
    """Every save that changes something is a new version (v1, v2…) recording what changed; a changed brief needs
    the client's confirmation again. Marking it complete tells the estimators it is ready."""
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    old = lead.get("brief") or {}
    new = {k: (d.get(k) or "").strip() or None for k in BRIEF_TEXT}
    new["scope"] = clean_scope(d.get("scope"))
    new["complete"] = bool(d.get("complete"))
    if new["complete"] and not new["scope"]:
        abort(400, "Add the scope (rooms and the work in each) before marking the brief complete")
    changed = [BRIEF_TEXT[k] for k in BRIEF_TEXT if old.get(k) != new[k]]
    if (old.get("scope") or []) != new["scope"]:
        changed.append("Scope")
    became_complete = new["complete"] and not old.get("complete")
    if not changed and new["complete"] == bool(old.get("complete")):
        return jsonify(serialize(old))
    version = (old.get("version") or 0) + (1 if changed else 0)
    brief = {**new, "version": version, "updated_at": t.now(), "updated_by": g.user.get("name"),
             "client_confirmed": None if changed else old.get("client_confirmed")}
    raw = {"$set": {"brief": brief}}
    if changed:
        raw["$push"] = {"brief_versions": {**{k: v for k, v in brief.items() if k != "client_confirmed"}}}
    db.leads.update_one({"_id": lead["_id"]}, raw)
    bits = []
    if changed:
        bits.append(f"Brief v{version} saved — changed: {', '.join(changed)}")
        if old.get("client_confirmed"):
            bits.append("needs the client's confirmation again")
    if became_complete:
        bits.append("marked complete")
    elif old.get("complete") and not new["complete"]:
        bits.append("no longer complete")
    log(_id, "brief", "; ".join(bits))
    if became_complete:
        notify.send("brief_ready", notify.role_users("estimator", "designer"), f"Brief for {lead['title']} is ready for an estimate",
                    f"/app/leads/{_id}", _id)
    return jsonify(serialize(brief))


@bp.post("/leads/<_id>/brief/confirm")
@api("leads")
def confirm_brief(_id):
    lead = open_lead(_id)
    brief = lead.get("brief") or abort(400, "Write the brief first")
    how = (request.get_json(force=True) or {}).get("how")
    if how not in ("call", "email", "whatsapp", "meeting", "questionnaire"):
        abort(400, "How did the client confirm (call, email, WhatsApp, meeting)?")
    conf = {"at": t.now(), "by": g.user.get("name"), "how": how, "version": brief["version"]}
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"brief.client_confirmed": conf}})
    log(_id, "brief", f"Client confirmed brief v{brief['version']} ({how})")
    return jsonify(serialize({**brief, "client_confirmed": conf}))


# ---------------- client questionnaire ----------------
@bp.post("/leads/<_id>/questionnaire")
@api("leads")
def send_questionnaire(_id):
    """A single-use public link for the client to describe what they want; the answers arrive on the lead."""
    lead = open_lead(_id)
    q = lead.get("questionnaire") or {}
    if q.get("token") and not q.get("submitted_at"):
        token = q["token"]
    else:
        token = secrets.token_urlsafe(18)
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {"questionnaire": {"token": token, "sent_at": t.now(),
                                                                              "sent_by": g.user.get("name"),
                                                                              "submitted_at": None, "answers": None}}})
        log(_id, "brief", "Questionnaire link created for the client")
    link = f"/q/{token}"
    if (request.get_json(force=True) or {}).get("email_client"):
        base = (g.company.get("email_settings") or {}).get("app_url") or request.host_url.rstrip("/")
        client_email(lead, f"A few questions about {lead['title']}",
                     f"Dear {lead.get('contact_name')},\n\nPlease tell us about your project here: {base}{link}\n\nRegards,\n{g.company['name']}")
    return jsonify({"token": token, "link": link})


def questionnaire_lead(token):
    lead = db.leads.find_one({"questionnaire.token": token, "status": {"$in": ["open", "on_hold"]}})
    company = lead and db.companies.find_one({"_id": oid(lead["company_id"]), "deleted_at": None})
    if not lead or not company or company.get("status") in ("suspended", "read_only", "cancelled"):
        abort(404, "This questionnaire is not available")
    return lead, company


@bp.get("/public/questionnaire/<token>")
def public_questionnaire(token):
    lead, company = questionnaire_lead(token)
    return jsonify({"company": company["name"], "project": lead["title"], "name": lead.get("contact_name"),
                    "questions": QUESTIONNAIRE.get(lead["service"], []),
                    "submitted": bool(lead["questionnaire"].get("submitted_at"))})


@bp.post("/public/questionnaire/<token>")
def submit_questionnaire(token):
    lead, company = questionnaire_lead(token)
    if lead["questionnaire"].get("submitted_at"):
        abort(409, "These answers were already sent. Thank you!")
    questions = {q["id"]: q for q in QUESTIONNAIRE.get(lead["service"], [])}
    d = request.get_json(force=True) or {}
    answers = {}
    for qid, v in (d.get("answers") or {}).items():
        if qid not in questions:
            continue
        v = str(v or "").strip()[:2000]
        if questions[qid]["type"] == "choice" and v and v not in questions[qid]["options"]:
            abort(400, f"Choose one of the options for: {questions[qid]['label']}")
        if v:
            answers[qid] = v
    if not answers:
        abort(400, "Please answer at least one question")
    g.cid, g.uid, g.company, g.user = lead["company_id"], None, company, {"name": lead.get("contact_name") or "Client"}
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"questionnaire.answers": answers, "questionnaire.submitted_at": t.now()}})
    log(str(lead["_id"]), "brief", f"Client answered the questionnaire ({len(answers)} answers)")
    notify.send("questionnaire", [lead.get("owner_id")] if lead.get("owner_id") else notify.managers(),
                f"{lead.get('contact_name')} answered the questionnaire for {lead['title']}", f"/app/leads/{lead['_id']}",
                str(lead["_id"]))
    return jsonify({"ok": True})


@bp.get("/leads/<_id>/brief")
@api("leads")
def get_brief(_id):
    lead = load_lead(_id)
    q = lead.get("questionnaire") or {}
    return jsonify(serialize({"brief": lead.get("brief"), "versions": lead.get("brief_versions") or [],
                              "questionnaire": {k: q.get(k) for k in ("sent_at", "sent_by", "submitted_at", "answers")} | {
                                  "link": f"/q/{q['token']}" if q.get("token") else None},
                              "questions": QUESTIONNAIRE.get(lead["service"], []), "work_types": WORK_TYPES,
                              "stakeholder_roles": list(STAKEHOLDER_ROLES), "stakeholders": lead.get("stakeholders") or [],
                              "package_rates": package_rates(lead["service"]), "ballpark": lead.get("ballpark")}))
