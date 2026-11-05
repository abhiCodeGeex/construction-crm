"""Lead journey steps 5-7 (C+2): rate library, internal estimates with approval, pre-sales expenses and receipts,
proposal tracking (versions, sent, accepted / rejected, expiry), negotiation rounds and competitors, and the
hand-over of everything to the project when the lead is won."""
from datetime import date

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, sales
from ..services.defaults import (RATE_KINDS, MEASURE_SOURCES, WORK_TYPES, EXPENSE_CATEGORIES, RECEIPT_KINDS,
                                 PAYMENT_MODES, PROPOSAL_CHANNELS, REJECT_REASONS, STAKEHOLDER_ROLES)
from ..services.sales import load_lead, log
from .lead_steps import open_lead, num, client_email, measurements, room_calc

bp = Blueprint("lead_money", __name__)


def money_text(v):
    from .followups import money
    return money(v) or "—"


def a_date(v, field, required=True):
    if v in (None, ""):
        if required:
            abort(400, f"{field} is required")
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        abort(400, f"{field} must be a date (YYYY-MM-DD)")


def approver_ids():
    return notify.managers()


def require_approver():
    if not sales.is_manager():
        abort(403, "Only the owner or the sales manager can approve")


# ---------------- rate library ----------------
def clean_rate(d):
    if d.get("kind") not in RATE_KINDS:
        abort(400, f"Kind must be one of: {', '.join(RATE_KINDS)}")
    name = (d.get("name") or "").strip()
    unit = (d.get("unit") or "").strip()
    if not name or not unit:
        abort(400, "Name and unit (e.g. sq ft, nos, kg) are required")
    if d.get("category") and d["category"] not in WORK_TYPES:
        abort(400, "Category must be one of the work types")
    return {"kind": d["kind"], "name": name, "unit": unit, "rate": num(d.get("rate"), "Rate", required=True),
            "category": d.get("category") or None, "brand": (d.get("brand") or "").strip() or None,
            "notes": (d.get("notes") or "").strip() or None, "active": d.get("active", True) is not False}


@bp.get("/rates")
@api("proposals", write=False)
def list_rates():
    q = {k: request.args[k] for k in ("kind", "category") if request.args.get(k)}
    if request.args.get("active") != "all":
        q["active"] = True
    return jsonify({"rates": serialize(t.find("rate_library", q, sort=[("kind", 1), ("category", 1), ("name", 1)])),
                    "kinds": RATE_KINDS, "work_types": WORK_TYPES})


@bp.post("/rates")
@api("proposals")
def create_rate():
    return jsonify(serialize(t.insert("rate_library", clean_rate(request.get_json(force=True) or {})))), 201


@bp.put("/rates/<rid>")
@api("proposals")
def update_rate(rid):
    t.get("rate_library", rid)
    return jsonify(serialize(t.update("rate_library", rid, clean_rate(request.get_json(force=True) or {}))))


@bp.delete("/rates/<rid>")
@api("proposals")
def delete_rate(rid):
    t.get("rate_library", rid)
    if db.estimates.count_documents({"company_id": g.cid, "$or": [{"lines.material_rate_id": rid}, {"lines.labour_rate_id": rid}]}):
        t.update("rate_library", rid, {"active": False})  # kept for the estimates that used it
        return jsonify({"ok": True, "archived": True})
    t.delete("rate_library", rid)
    return jsonify({"ok": True})


# ---------------- estimates (internal costing) ----------------
def compute(est, lead):
    """Quantities from measurements, then direct cost -> overheads -> markup -> discount -> tax, with margin."""
    m = measurements(lead)
    rooms = {r["id"]: {**r, **room_calc(r, m["unit"])} for r in m["rooms"]}
    mat = lab = 0.0
    for ln in est["lines"]:
        if ln.get("qty_source") and ln["qty_source"] != "manual":
            room = rooms.get(ln.get("room_id"))
            ln["qty"] = room[ln["qty_source"]] if room else 0
            ln["room"] = room["name"] if room else ln.get("room")
        ln["material_cost"] = round(ln["qty"] * ln["material_rate"], 2)
        ln["labour_cost"] = round(ln["qty"] * ln["labour_rate"], 2)
        ln["line_cost"] = round(ln["material_cost"] + ln["labour_cost"], 2)
        mat += ln["material_cost"]
        lab += ln["labour_cost"]
    direct = mat + lab
    overheads = direct * est["overhead_pct"] / 100
    cost = direct + overheads
    markup = cost * est["markup_pct"] / 100
    price = cost + markup
    discount = price * est["discount_pct"] / 100
    subtotal = price - discount
    tax = subtotal * est["tax_pct"] / 100
    margin = subtotal - cost
    est["totals"] = {k: round(v, 2) for k, v in {
        "material": mat, "labour": lab, "direct_cost": direct, "overheads": overheads, "cost": cost, "markup_amount": markup,
        "price": price, "discount": discount, "subtotal": subtotal, "tax": tax, "total": subtotal + tax, "margin": margin,
        "margin_pct": (margin / subtotal * 100) if subtotal else 0}.items()}
    return est


def clean_lines(rows, lead):
    m = measurements(lead)
    room_ids = {r["id"]: r for r in m["rooms"]}
    lines = []
    for r in rows or []:
        desc = (r.get("description") or "").strip()
        if not desc:
            abort(400, "Each line needs a description")
        src = r.get("qty_source") or "manual"
        if src != "manual" and src not in MEASURE_SOURCES:
            abort(400, "Quantity must be typed or taken from a measurement")
        if r.get("room_id") and r["room_id"] not in room_ids:
            abort(400, "Room not found in the measurements")
        if src != "manual" and not r.get("room_id"):
            abort(400, f"Choose the room to measure “{desc}” from")
        if r.get("work_type") and r["work_type"] not in WORK_TYPES:
            abort(400, "Unknown work type")
        ln = {"id": r.get("id") or t.sid(), "description": desc, "room_id": r.get("room_id"),
              "room": room_ids[r["room_id"]]["name"] if r.get("room_id") else (r.get("room") or "").strip() or None,
              "work_type": r.get("work_type"), "unit": (r.get("unit") or "").strip() or None, "qty_source": src,
              "qty": num(r.get("qty"), f"Quantity of {desc}", required=src == "manual") or 0,
              "material_rate": num(r.get("material_rate"), f"Material rate of {desc}") or 0,
              "labour_rate": num(r.get("labour_rate"), f"Labour rate of {desc}") or 0,
              "material_rate_id": r.get("material_rate_id"), "labour_rate_id": r.get("labour_rate_id")}
        for k in ("material_rate_id", "labour_rate_id"):
            if ln[k] and not db.rate_library.find_one({"_id": oid(ln[k]), "company_id": g.cid}):
                abort(400, "Rate not found in the rate library")
        lines.append(ln)
    return lines


def pct(v, field, default):
    v = default if v in (None, "") else v
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 100:
        abort(400, f"{field} must be between 0 and 100")
    return float(v)


def load_estimate(eid):
    e = t.get("estimates", eid)
    return e, load_lead(e["lead_id"])


@bp.get("/leads/<_id>/estimates")
@api("proposals", write=False)
def list_estimates(_id):
    lead = load_lead(_id)
    m = measurements(lead)
    return jsonify({"estimates": [t.out(e) for e in t.find("estimates", {"lead_id": _id}, sort=[("version", 1)])],
                    "rooms": [{**r, **room_calc(r, m["unit"])} for r in m["rooms"]], "measure_sources": MEASURE_SOURCES,
                    "work_types": WORK_TYPES, "limits": {k: sales.settings()[k] for k in ("max_discount_pct", "min_margin_pct")},
                    "tax_pct": g.company.get("tax_rate", 0)})


@bp.post("/leads/<_id>/estimates")
@api("proposals")
def create_estimate(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    version = db.estimates.count_documents({"company_id": g.cid, "lead_id": _id}) + 1
    base = {"lines": [], "overhead_pct": 0.0, "markup_pct": 0.0, "discount_pct": 0.0, "tax_pct": float(g.company.get("tax_rate") or 0)}
    if d.get("copy_from"):
        src, _ = load_estimate(d["copy_from"])
        if src["lead_id"] != _id:
            abort(400, "Copy from an estimate of this lead")
        base = {k: src[k] for k in base}
    est = compute({**base, "lead_id": _id, "lead_title": lead["title"], "version": version,
                   "number": t.next_number("EST", "EST"), "title": (d.get("title") or f"Estimate v{version}").strip(),
                   "status": "draft", "approval": None}, lead)
    e = t.insert("estimates", est)
    log(_id, "estimate", f"Estimate {e['number']} (v{version}) started" + (" from an earlier version" if d.get("copy_from") else ""),
        estimate_id=str(e["_id"]))
    return jsonify(t.out(e)), 201


@bp.put("/estimates/<eid>")
@api("proposals")
def update_estimate(eid):
    e, lead = load_estimate(eid)
    open_lead(e["lead_id"])
    if e["status"] not in ("draft", "refused"):
        abort(409, f"This estimate is {e['status'].replace('_', ' ')}; start a new version to change it")
    d = request.get_json(force=True) or {}
    est = {"lines": clean_lines(d.get("lines", e["lines"]), lead),
           "overhead_pct": pct(d.get("overhead_pct"), "Overheads %", e["overhead_pct"]),
           "markup_pct": pct(d.get("markup_pct"), "Markup %", e["markup_pct"]),
           "discount_pct": pct(d.get("discount_pct"), "Discount %", e["discount_pct"]),
           "tax_pct": pct(d.get("tax_pct"), "Tax %", e["tax_pct"]),
           "title": (d.get("title") or e["title"]).strip(), "status": "draft"}
    compute(est, lead)
    upd = t.update("estimates", eid, est)
    log(e["lead_id"], "estimate", f"Estimate {e['number']} edited: {len(est['lines'])} line(s), total {money_text(est['totals']['total'])}, "
        f"margin {est['totals']['margin_pct']:.1f}%", estimate_id=eid)
    return jsonify(t.out(upd))


@bp.post("/estimates/<eid>/submit")
@api("proposals")
def submit_estimate(eid):
    """Within the limits it is approved at once; a margin below the minimum or a discount above the limit waits
    for the owner / sales manager."""
    e, lead = load_estimate(eid)
    open_lead(e["lead_id"])
    if e["status"] not in ("draft", "refused"):
        abort(409, f"This estimate is already {e['status'].replace('_', ' ')}")
    if not e["lines"]:
        abort(400, "Add at least one line")
    compute(e, lead)
    s = sales.settings()
    reasons = []
    if e["totals"]["margin_pct"] < s["min_margin_pct"]:
        reasons.append(f"margin {e['totals']['margin_pct']:.1f}% is below {s['min_margin_pct']:g}%")
    if e["discount_pct"] > s["max_discount_pct"]:
        reasons.append(f"discount {e['discount_pct']:g}% is above {s['max_discount_pct']:g}%")
    approval = {"reasons": reasons, "requested_by": g.user.get("name"), "requested_by_id": g.uid, "requested_at": t.now()}
    if reasons and not sales.is_manager():
        upd = t.update("estimates", eid, {"status": "pending_approval", "approval": approval, "lines": e["lines"], "totals": e["totals"]})
        log(e["lead_id"], "estimate", f"Estimate {e['number']} sent for approval: {'; '.join(reasons)}", estimate_id=eid)
        notify.send("approval_needed", approver_ids(), f"Estimate {e['number']} for {lead['title']} needs approval ({'; '.join(reasons)})",
                    f"/app/leads/{e['lead_id']}", e["lead_id"])
        return jsonify(t.out(upd))
    approval.update(decided_by=g.user.get("name"), decided_at=t.now(),
                    note="within the limits" if not reasons else "approved by the approver who prepared it")
    return jsonify(t.out(approve_estimate(e, lead, approval)))


def approve_estimate(e, lead, approval):
    eid = str(e["_id"])
    upd = t.update("estimates", eid, {"status": "approved", "approval": approval, "lines": e["lines"], "totals": e["totals"]})
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"estimate_value": e["totals"]["total"]}})
    log(e["lead_id"], "estimate", f"Estimate {e['number']} approved ({approval['note']}) — total {money_text(e['totals']['total'])}, "
        f"margin {e['totals']['margin_pct']:.1f}%", estimate_id=eid)
    return upd


@bp.post("/estimates/<eid>/decide")
@api("proposals")
def decide_estimate(eid):
    e, lead = load_estimate(eid)
    open_lead(e["lead_id"])
    require_approver()
    if e["status"] != "pending_approval":
        abort(409, "This estimate is not waiting for approval")
    d = request.get_json(force=True) or {}
    note = (d.get("note") or "").strip()
    approval = {**e["approval"], "decided_by": g.user.get("name"), "decided_at": t.now(), "note": note or "approved"}
    if d.get("approve"):
        upd = approve_estimate(e, lead, approval)
    else:
        if not note:
            abort(400, "Say why it is refused")
        upd = t.update("estimates", eid, {"status": "refused", "approval": approval})
        log(e["lead_id"], "estimate", f"Estimate {e['number']} refused by {g.user.get('name')}: {note}", estimate_id=eid)
    notify.send("approval_decided", [e["approval"].get("requested_by_id")],
                f"Estimate {e['number']} {'approved' if d.get('approve') else 'refused'}" + (f": {note}" if note else ""),
                f"/app/leads/{e['lead_id']}", e["lead_id"])
    return jsonify(t.out(upd))


@bp.delete("/estimates/<eid>")
@api("proposals")
def delete_estimate(eid):
    e, _ = load_estimate(eid)
    open_lead(e["lead_id"])
    if e["status"] in ("approved", "pending_approval"):
        abort(409, f"An {e['status'].replace('_', ' ')} estimate is kept; start a new version instead")
    t.delete("estimates", eid)
    log(e["lead_id"], "estimate", f"Estimate {e['number']} deleted (was {e['status']})")
    return jsonify({"ok": True})


# ---------------- pre-sales expenses and receipts ----------------
@bp.get("/leads/<_id>/money")
@api("leads")
def lead_money(_id):
    load_lead(_id)
    exp = t.find("lead_expenses", {"lead_id": _id}, sort=[("date", -1)])
    rec = t.find("lead_receipts", {"lead_id": _id}, sort=[("date", -1)])
    return jsonify({"expenses": serialize(exp), "receipts": serialize(rec), "categories": EXPENSE_CATEGORIES,
                    "receipt_kinds": RECEIPT_KINDS, "modes": PAYMENT_MODES,
                    "totals": {"spent": round(sum(x["amount"] for x in exp), 2),
                               "received": round(sum(x["amount"] for x in rec if x.get("status") != "void"), 2)}})


@bp.post("/leads/<_id>/expenses")
@api("leads")
def add_expense(_id):
    open_lead(_id)
    d = request.get_json(force=True) or {}
    if d.get("category") not in EXPENSE_CATEGORIES:
        abort(400, f"Category must be one of: {', '.join(EXPENSE_CATEGORIES)}")
    amount = num(d.get("amount"), "Amount", required=True, positive=True)
    x = t.insert("lead_expenses", {"lead_id": _id, "category": d["category"], "amount": amount, "date": a_date(d.get("date"), "Date"),
                                   "note": (d.get("note") or "").strip() or None, "file_key": d.get("file_key"), "visit_id": None})
    log(_id, "expense", f"Pre-sales expense: {d['category']} {money_text(amount)}" + (f" — {x['note']}" if x["note"] else ""))
    return jsonify(serialize(x)), 201


@bp.delete("/lead_expenses/<xid>")
@api("leads")
def delete_expense(xid):
    x = t.get("lead_expenses", xid)
    open_lead(x["lead_id"])
    if x.get("visit_id"):
        abort(409, "This is a site visit's cost; change it in the visit report")
    t.delete("lead_expenses", xid)
    log(x["lead_id"], "expense", f"Expense removed: {x['category']} {money_text(x['amount'])}")
    return jsonify({"ok": True})


def record_receipt(lead, d):
    if d.get("kind") not in RECEIPT_KINDS:
        abort(400, f"Kind must be one of: {', '.join(RECEIPT_KINDS)}")
    if d.get("mode") not in PAYMENT_MODES:
        abort(400, f"Mode must be one of: {', '.join(PAYMENT_MODES)}")
    amount = num(d.get("amount"), "Amount", required=True, positive=True)
    rd = a_date(d.get("date"), "Date")
    if rd > sales.today():
        abort(400, "A receipt cannot be dated in the future")
    if d["mode"] != "Cash" and not (d.get("reference") or "").strip():
        abort(400, "Enter the transaction / cheque reference")
    _id = str(lead["_id"])
    r = t.insert("lead_receipts", {"lead_id": _id, "lead_title": lead["title"], "number": t.next_number("RCT", "RCT"),
                                   "kind": d["kind"], "amount": amount, "date": rd, "mode": d["mode"],
                                   "reference": (d.get("reference") or "").strip() or None,
                                   "note": (d.get("note") or "").strip() or None, "status": "received",
                                   "project_id": lead.get("project_id")})
    log(_id, "receipt", f"{d['kind']} received: {money_text(amount)} by {d['mode']}" + (f" ({r['reference']})" if r["reference"] else "")
        + f" — receipt {r['number']}")
    notify.send("advance_received", notify.role_users("accounts") + notify.managers() + [lead.get("owner_id")],
                f"{d['kind']} {money_text(amount)} received for {lead['title']} (receipt {r['number']})", f"/app/leads/{_id}", _id)
    return r


@bp.post("/leads/<_id>/receipts")
@api("leads")
def add_receipt(_id):
    r = record_receipt(open_lead(_id), request.get_json(force=True) or {})
    return jsonify(serialize(r)), 201


@bp.post("/lead_receipts/<rid>/void")
@api("leads")
def void_receipt(rid):
    if g.role != "owner":
        abort(403, "Only the owner can void a receipt")
    r = t.get("lead_receipts", rid)
    if r.get("status") == "void":
        abort(409, "Already void")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the receipt is void")
    t.update("lead_receipts", rid, {"status": "void", "void_reason": reason, "voided_at": t.now(), "voided_by": g.user.get("name")})
    log(r["lead_id"], "receipt", f"Receipt {r['number']} ({money_text(r['amount'])}) voided — {reason}")
    return jsonify({"ok": True})


# ---------------- proposals (tracking; the builder and e-signature come in Phase D) ----------------
def load_proposal(pid):
    p = t.get("proposals", pid)
    return p, load_lead(p["lead_id"])


@bp.get("/leads/<_id>/proposals")
@api("proposals", write=False)
def list_proposals(_id):
    load_lead(_id)
    return jsonify({"proposals": serialize(t.find("proposals", {"lead_id": _id}, sort=[("version", 1)])),
                    "channels": PROPOSAL_CHANNELS, "reject_reasons": REJECT_REASONS})


@bp.post("/leads/<_id>/proposals")
@api("proposals")
def create_proposal(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    est = None
    if d.get("estimate_id"):
        est = t.get("estimates", d["estimate_id"], required=False)
        if not est or est["lead_id"] != _id:
            abort(400, "Estimate not found on this lead")
        if est["status"] != "approved":
            abort(400, "Only an approved estimate can go into a proposal")
    value = est["totals"]["total"] if est else num(d.get("value"), "Value", required=True, positive=True)
    valid = a_date(d.get("valid_until"), "Valid until")
    if valid <= sales.today():
        abort(400, "Valid until must be in the future")
    if d.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
        abort(400, "Upload the proposal file first")
    version = db.proposals.count_documents({"company_id": g.cid, "lead_id": _id}) + 1
    p = t.insert("proposals", {"lead_id": _id, "lead_title": lead["title"], "number": t.next_number("PRO", "PRO"), "version": version,
                               "title": (d.get("title") or f"Proposal v{version}").strip(), "estimate_id": str(est["_id"]) if est else None,
                               "estimate_number": est and est["number"], "value": value, "valid_until": valid,
                               "file_key": d.get("file_key"), "notes": (d.get("notes") or "").strip() or None, "status": "draft",
                               "sent_at": None, "response": None, "revision_of": d.get("revision_of")})
    log(_id, "proposal", f"Proposal {p['number']} (v{version}) prepared — {money_text(value)}, valid until {valid}"
        + (f", from estimate {est['number']}" if est else ""), proposal_id=str(p["_id"]))
    return jsonify(serialize(p)), 201


@bp.delete("/proposals/<pid>")
@api("proposals")
def delete_proposal(pid):
    p, _ = load_proposal(pid)
    open_lead(p["lead_id"])
    if p["status"] != "draft":
        abort(409, "Only a draft proposal can be deleted")
    t.delete("proposals", pid)
    log(p["lead_id"], "proposal", f"Draft proposal {p['number']} deleted")
    return jsonify({"ok": True})


def supersede(lead_id, keep):
    for o in t.find("proposals", {"lead_id": lead_id, "status": {"$in": ["sent", "revision_requested"]}}):
        if str(o["_id"]) != keep:
            t.update("proposals", str(o["_id"]), {"status": "superseded"})


@bp.post("/proposals/<pid>/send")
@api("proposals")
def send_proposal(pid):
    p, lead = load_proposal(pid)
    open_lead(p["lead_id"])
    if p["status"] != "draft":
        abort(409, f"This proposal is already {p['status'].replace('_', ' ')}")
    d = request.get_json(force=True) or {}
    channel = d.get("channel")
    if channel not in PROPOSAL_CHANNELS:
        abort(400, f"How was it sent? {', '.join(PROPOSAL_CHANNELS)}")
    if p["valid_until"] <= sales.today():
        abort(409, "The proposal's validity has passed; make a new version")
    supersede(p["lead_id"], pid)
    upd = t.update("proposals", pid, {"status": "sent", "sent_at": t.now(), "channel": channel, "sent_by": g.user.get("name")})
    # an accepted proposal stays the lead's value; a later one sent for discussion does not replace it
    value = {} if lead.get("accepted_proposal_id") else {"proposal_value": p["value"]}
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {**value, "last_activity_at": t.now()}})
    log(p["lead_id"], "proposal", f"Proposal {p['number']} sent by {channel.replace('_', ' ')} — {money_text(p['value'])}", proposal_id=pid)
    if channel == "email":
        import os
        from ..config import Config
        atts = []
        if p.get("file_key"):
            f = db.files.find_one({"company_id": g.cid, "key": p["file_key"]})
            with open(os.path.join(Config.UPLOAD_DIR, p["file_key"]), "rb") as fh:
                atts.append((f["name"], fh.read()))
        c = db.contacts.find_one({"_id": oid(lead.get("contact_id"))}, {"email": 1})
        result = notify.deliver(g.company, (c or {}).get("email"), f"Proposal {p['number']} — {lead['title']}",
                                f"Dear {lead.get('contact_name')},\n\nPlease find our proposal for {lead['title']}: "
                                f"{money_text(p['value'])}, valid until {p['valid_until']}.\n\nRegards,\n{g.company['name']}", atts)
        log(p["lead_id"], "email", f"Proposal {p['number']} emailed to the client: {result}", outcome=result, auto=True)
    return jsonify(serialize(upd))


@bp.post("/proposals/<pid>/respond")
@api("proposals")
def respond_proposal(pid):
    """The client's answer: accepted (only one per lead), rejected with a reason, or a revision requested."""
    p, lead = load_proposal(pid)
    open_lead(p["lead_id"])
    if p["status"] != "sent":
        abort(409, "Only a sent proposal can be answered")
    d = request.get_json(force=True) or {}
    result = d.get("result")
    comment = (d.get("comment") or "").strip() or None
    if result == "accepted":
        if db.proposals.find_one({"company_id": g.cid, "lead_id": p["lead_id"], "status": "accepted"}):
            abort(409, "Another proposal of this lead is already accepted")
        upd = t.update("proposals", pid, {"status": "accepted", "response": {"at": t.now(), "by": g.user.get("name"), "comment": comment}})
        supersede(p["lead_id"], pid)
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {"proposal_value": p["value"], "accepted_proposal_id": pid}})
        text = f"Proposal {p['number']} accepted by the client — {money_text(p['value'])}"
    elif result in ("rejected", "revision_requested"):
        if d.get("reason") not in REJECT_REASONS:
            abort(400, f"Choose the reason: {', '.join(REJECT_REASONS)}")
        upd = t.update("proposals", pid, {"status": result, "response": {"at": t.now(), "by": g.user.get("name"),
                                                                          "reason": d["reason"], "comment": comment}})
        text = f"Proposal {p['number']} {'rejected' if result == 'rejected' else 'needs a revision'} — {d['reason']}"
    else:
        abort(400, "Result must be accepted, rejected or revision requested")
    log(p["lead_id"], "proposal", text + (f": {comment}" if comment else ""), proposal_id=pid)
    notify.send("proposal_response", [lead.get("owner_id")] + (notify.managers() if result != "accepted" else []),
                f"{lead['title']}: {text}", f"/app/leads/{p['lead_id']}", p["lead_id"])
    return jsonify(serialize(upd))


# ---------------- negotiation and competitors ----------------
@bp.post("/leads/<_id>/negotiation")
@api("leads")
def add_round(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    asked = num(d.get("asked"), "Our price", required=True, positive=True)
    offered = num(d.get("offered"), "Client's offer", required=True, positive=True)
    if offered > asked:
        abort(400, "The client's offer is higher than our price — check the figures")
    disc = round((asked - offered) / asked * 100, 2)
    limit = sales.settings()["max_discount_pct"]
    needs = disc > limit and not sales.is_manager()
    rnd = {"id": t.sid(), "at": t.now(), "by": g.user.get("name"), "by_id": g.uid, "asked": asked, "offered": offered,
           "discount_pct": disc, "note": (d.get("note") or "").strip() or None,
           "approval": {"status": "pending"} if needs else {"status": "not_needed" if disc <= limit else "approved",
                                                             "by": None if disc <= limit else g.user.get("name")}}
    db.leads.update_one({"_id": lead["_id"]}, {"$push": {"negotiation": rnd}, "$set": {"last_activity_at": t.now()}})
    log(_id, "negotiation", f"Negotiation: we asked {money_text(asked)}, client offered {money_text(offered)} ({disc:g}% off)"
        + (f" — needs approval (limit {limit:g}%)" if needs else "") + (f" — {rnd['note']}" if rnd["note"] else ""))
    if needs:
        notify.send("approval_needed", approver_ids(), f"Discount {disc:g}% on {lead['title']} needs approval "
                    f"({money_text(asked)} → {money_text(offered)})", f"/app/leads/{_id}", _id)
    return jsonify(serialize(rnd)), 201


@bp.post("/leads/<_id>/negotiation/<rid>/decide")
@api("leads")
def decide_round(_id, rid):
    lead = open_lead(_id)
    require_approver()
    rounds = list(lead.get("negotiation") or [])
    r = next((x for x in rounds if x["id"] == rid), None) or abort(404, "round not found")
    if r["approval"]["status"] != "pending":
        abort(409, "This discount is not waiting for approval")
    d = request.get_json(force=True) or {}
    note = (d.get("note") or "").strip()
    if not d.get("approve") and not note:
        abort(400, "Say why it is refused")
    r["approval"] = {"status": "approved" if d.get("approve") else "refused", "by": g.user.get("name"), "at": t.now(), "note": note or None}
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"negotiation": rounds}})
    log(_id, "negotiation", f"Discount {r['discount_pct']:g}% {r['approval']['status']} by {g.user.get('name')}" + (f": {note}" if note else ""))
    notify.send("approval_decided", [r.get("by_id")], f"Discount {r['discount_pct']:g}% on {lead['title']} {r['approval']['status']}",
                f"/app/leads/{_id}", _id)
    return jsonify(serialize(r))


@bp.post("/leads/<_id>/competitors")
@api("leads")
def add_competitor(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip() or abort(400, "Name the competitor")
    comp = list(lead.get("competitors") or [])
    if any(c["name"].lower() == name.lower() for c in comp):
        abort(409, f"{name} is already listed")
    c = {"id": t.sid(), "name": name, "price": num(d.get("price"), "Their price"), "notes": (d.get("notes") or "").strip() or None}
    db.leads.update_one({"_id": lead["_id"]}, {"$push": {"competitors": c}})
    log(_id, "negotiation", f"Competitor noted: {name}" + (f" at {money_text(c['price'])}" if c["price"] else ""))
    return jsonify(serialize(c)), 201


@bp.delete("/leads/<_id>/competitors/<cid_>")
@api("leads")
def remove_competitor(_id, cid_):
    lead = open_lead(_id)
    c = next((x for x in lead.get("competitors") or [] if x["id"] == cid_), None) or abort(404, "competitor not found")
    db.leads.update_one({"_id": lead["_id"]}, {"$pull": {"competitors": {"id": cid_}}})
    log(_id, "negotiation", f"Competitor removed: {c['name']}")
    return jsonify({"ok": True})


# ---------------- won: everything moves to the project ----------------
def hand_over_to_project(lead, project, pm_id, advance=None):
    """Called by win_lead once the project exists: nothing gathered on the lead is retyped."""
    from .lead_steps import measurements as meas
    _id, pid = str(lead["_id"]), str(project["_id"])
    if advance and advance.get("amount"):
        record_receipt({**lead, "project_id": pid}, advance)
    accepted = db.proposals.find_one({"company_id": g.cid, "lead_id": _id, "status": "accepted"})
    visits = [{"at": v["at"], "report": v.get("report"), "site_checklist": v.get("site_checklist")}
              for v in db.lead_visits.find({"company_id": g.cid, "lead_id": _id, "status": "done"})]
    handover = {"lead_id": _id, "brief": lead.get("brief"), "measurements": meas(lead) if lead.get("measurements") else None,
                "stakeholders": lead.get("stakeholders") or [], "ballpark": lead.get("ballpark"),
                "accepted_proposal": {k: accepted.get(k) for k in ("number", "title", "value", "valid_until", "file_key")} if accepted else None,
                "visits": visits, "questionnaire": (lead.get("questionnaire") or {}).get("answers")}
    team = list(project.get("team") or [])
    for p in lead.get("stakeholders") or []:
        if not any(m.get("contact_id") == p["contact_id"] for m in team):
            team.append({"id": t.sid(), "contact_id": p["contact_id"], "name": p["name"], "kind": "external", "access": "view",
                         "project_role": STAKEHOLDER_ROLES.get(p["role"], "Other")})
    db.projects.update_one({"_id": project["_id"]}, {"$set": {"lead_handover": handover, "team": team}})
    db.lead_files.update_many({"company_id": g.cid, "lead_id": _id}, {"$set": {"project_id": pid}})
    db.lead_receipts.update_many({"company_id": g.cid, "lead_id": _id}, {"$set": {"project_id": pid}})
    pm = db.users.find_one({"_id": oid(pm_id)}, {"name": 1})
    due = date.fromordinal(date.today().toordinal() + 2).isoformat()
    t.insert("followups", {"title": f"Hand-off meeting: sales → PM for {project['code']} {project['name']}", "due": due,
                           "priority": "high", "channel": "meeting", "owner_id": pm_id, "owner_name": pm and pm["name"],
                           "status": "open", "kind": "handoff", "related": {"type": "project", "id": pid, "label": project["name"],
                                                                            "contact_id": project.get("client_id")}})
    log(_id, "won", f"Handed over to {project['code']}: brief, measurements, {len(lead.get('stakeholders') or [])} decision-maker(s), "
        f"{db.lead_files.count_documents({'company_id': g.cid, 'lead_id': _id})} file(s)"
        + (f", accepted proposal {accepted['number']}" if accepted else "") + "; hand-off meeting set for the PM")
    client_email(lead, f"Welcome to {g.company['name']} — {project['name']}",
                 f"Dear {lead.get('contact_name')},\n\nThank you for choosing {g.company['name']}. Your project {project['code']} "
                 f"{project['name']} is set up and {pm and pm['name']} is your project manager.\n\nRegards,\n{g.company['name']}")


@bp.get("/projects/<pid>/handover")
@api("projects", write=False)
def project_handover(pid):
    from .projects import load
    p = load(pid)
    h = p.get("lead_handover")
    if not h:
        return jsonify(None)
    files = [{**serialize(f), "url": f"/api/files/{f['key']}"} for f in t.find("lead_files", {"project_id": pid})]
    out = {**serialize(h), "files": files}
    if g.hide_costs or not can("finance") and not can("proposals"):
        out.pop("ballpark", None)
        out["accepted_proposal"] = out["accepted_proposal"] and {k: v for k, v in out["accepted_proposal"].items() if k != "value"}
    else:
        out["receipts"] = serialize(t.find("lead_receipts", {"project_id": pid}))
    return jsonify(out)
