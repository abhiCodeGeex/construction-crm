"""Phase D (requirements §5, §1 branding, §16 viewed alert): proposal builder for fee proposals, construction
estimates and interior quotes; templates and versions; optional items, discount and tax with approval; a private
client link with view tracking and e-signature; the contract with a payment schedule tied to project milestones."""
import os
import re
import secrets
from datetime import date

from flask import Blueprint, request, jsonify, abort, g, send_from_directory

from .. import tenancy as t
from ..config import Config
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, sales
from ..services.defaults import (PROPOSAL_TYPES, FEE_BASES, SCHEDULE_TRIGGERS, SERVICE_PROPOSAL_TYPE, TEMPLATE_TEXT,
                                 PROPOSAL_CHANNELS, REJECT_REASONS, SERVICES)
from ..services.sales import load_lead, log
from .lead_steps import open_lead, num

bp = Blueprint("proposals", __name__)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_SIGNATURE = 300_000  # bytes of the base64 PNG


def money_text(v):
    from .followups import money
    return money(v) or "—"


def a_date(v, field):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        abort(400, f"{field} must be a date (YYYY-MM-DD)")


# ---------------- payment schedule ----------------
def stages_for(service, cid=None):
    """Stage names of the service's default template: the project built on a win uses exactly these."""
    cid = cid or g.cid
    tpl = db.stage_templates.find_one({"company_id": cid, "service": service, "is_default": True}) or \
        db.stage_templates.find_one({"company_id": cid, "service": service})
    return [s["name"] for s in (tpl or {}).get("stages", [])]


def default_schedule(service):
    """10 % on signing, the rest split evenly across the service's stages (last one takes the rounding)."""
    stages = stages_for(service)
    rows = [{"id": t.sid(), "name": "Advance on signing", "pct": 10.0, "trigger": "signing"}]
    if not stages:
        rows[0]["pct"] = 100.0
        return rows
    each = round(90 / len(stages), 2)
    for i, st in enumerate(stages):
        pct = round(90 - each * (len(stages) - 1), 2) if i == len(stages) - 1 else each
        rows.append({"id": t.sid(), "name": f"On {st} complete", "pct": pct, "trigger": "stage", "stage": st})
    return rows


def clean_schedule(rows, service, require_total=False):
    stages = stages_for(service)
    out = []
    for r in rows or []:
        name = (r.get("name") or "").strip() or abort(400, "Each payment needs a name (e.g. Advance on signing)")
        pct = num(r.get("pct"), f"% for {name}", required=True, positive=True)
        trig = r.get("trigger")
        if trig not in SCHEDULE_TRIGGERS:
            abort(400, f"When is “{name}” due? {', '.join(SCHEDULE_TRIGGERS.values())}")
        row = {"id": r.get("id") or t.sid(), "name": name, "pct": round(pct, 2), "trigger": trig}
        if trig == "stage":
            if r.get("stage") not in stages:
                abort(400, f"“{name}”: choose one of the project stages ({', '.join(stages)})")
            row["stage"] = r["stage"]
        if trig == "date":
            row["date"] = a_date(r.get("date"), f"Date for {name}")
        out.append(row)
    total = round(sum(r["pct"] for r in out), 2)
    if (out or require_total) and abs(total - 100) > 0.01:
        abort(400, f"The payment schedule totals {total:g}% — it must total 100%")
    return out


# ---------------- pricing ----------------
def fee_amount(fee):
    b = fee.get("basis")
    if b == "fixed":
        return fee.get("amount") or 0
    if b == "hourly":
        return (fee.get("hours") or 0) * (fee.get("rate") or 0)
    if b == "percent":
        return (fee.get("project_cost") or 0) * (fee.get("pct") or 0) / 100
    if b == "per_area":
        return (fee.get("area") or 0) * (fee.get("rate") or 0)
    return 0


def clean_fee(d, label="Fee"):
    b = d.get("basis")
    if b not in FEE_BASES:
        abort(400, f"{label} basis: {', '.join(FEE_BASES.values())}")
    fee = {"basis": b}
    need = {"fixed": ["amount"], "hourly": ["hours", "rate"], "percent": ["pct", "project_cost"], "per_area": ["area", "rate"]}[b]
    for k in need:
        fee[k] = num(d.get(k), f"{label} {k.replace('_', ' ')}", required=True, positive=True)
    if b == "percent" and fee["pct"] > 100:
        abort(400, "Fee % cannot be above 100")
    if b == "per_area":
        fee["area_unit"] = d.get("area_unit") if d.get("area_unit") in ("sqft", "sqm") else "sqft"
    split = []
    for s in d.get("stages") or []:
        name = (s.get("name") or "").strip() or abort(400, "Each fee stage needs a name")
        split.append({"name": name, "pct": num(s.get("pct"), f"% for {name}", required=True, positive=True)})
    if split and abs(sum(s["pct"] for s in split) - 100) > 0.01:
        abort(400, "The fee split across stages must total 100%")
    fee["stages"] = split
    return fee


def clean_items(rows):
    items = []
    for r in rows or []:
        desc = (r.get("description") or "").strip() or abort(400, "Each line needs a description")
        qty = num(r.get("qty"), f"Quantity of {desc}", required=True, positive=True)
        rate = num(r.get("rate"), f"Rate of {desc}", required=True)
        items.append({"id": r.get("id") or t.sid(), "section": (r.get("section") or "").strip() or None, "description": desc,
                      "qty": qty, "unit": (r.get("unit") or "").strip() or None, "rate": rate,
                      "cost": num(r.get("cost"), f"Cost of {desc}"), "optional": bool(r.get("optional")),
                      "selected": bool(r.get("selected")) if r.get("optional") else True})
    return items


def clean_products(rows):
    out = []
    for r in rows or []:
        name = (r.get("name") or "").strip() or abort(400, "Each product needs a name")
        out.append({"id": r.get("id") or t.sid(), "room": (r.get("room") or "").strip() or None, "name": name,
                    "brand": (r.get("brand") or "").strip() or None,
                    "qty": num(r.get("qty"), f"Quantity of {name}", required=True, positive=True),
                    "unit": (r.get("unit") or "").strip() or "nos",
                    "trade_price": num(r.get("trade_price"), f"Trade price of {name}", required=True),
                    "markup_pct": num(r.get("markup_pct"), f"Markup of {name}", required=True),
                    "optional": bool(r.get("optional")), "selected": bool(r.get("selected")) if r.get("optional") else True})
    return out


def fee_text(fee):
    """How the fee was worked out, in the client's words."""
    b = fee["basis"]
    if b == "fixed":
        return "Fixed fee"
    if b == "hourly":
        return f"{fee['hours']:g} hours × {money_text(fee['rate'])} per hour"
    if b == "percent":
        return f"{fee['pct']:g}% of the project cost of {money_text(fee['project_cost'])}"
    return f"{fee['area']:g} {'m²' if fee.get('area_unit') == 'sqm' else 'sq ft'} × {money_text(fee['rate'])}"


def lines(p):
    """Client lines for the proposal type, each with its internal cost where it is known."""
    out = []
    if p["type"] == "fee" and p.get("fee"):
        base = fee_amount(p["fee"])
        if p["fee"].get("stages"):
            for i, s in enumerate(p["fee"]["stages"]):
                out.append({"id": f"fee-{i}", "section": "Professional fee", "description": f"{s['name']} — {s['pct']:g}% of the fee ({fee_text(p['fee'])})",
                            "qty": 1, "unit": "stage", "rate": round(base * s["pct"] / 100, 2), "cost": None, "optional": False, "selected": True})
        else:
            out.append({"id": "fee-0", "section": "Professional fee", "description": fee_text(p["fee"]),
                        "qty": 1, "unit": "lot", "rate": round(base, 2), "cost": None, "optional": False, "selected": True})
    if p["type"] == "construction" and p.get("estimate_id"):
        est = db.estimates.find_one({"_id": oid(p["estimate_id"]), "company_id": g.cid})
        tt = (est or {}).get("totals") or {}
        factor = tt["price"] / tt["direct_cost"] if tt.get("direct_cost") else 0
        for ln in (est or {}).get("lines", []):
            amount = round(ln["line_cost"] * factor, 2)
            qty = ln["qty"] or 1
            out.append({"id": f"est-{ln['id']}", "section": ln.get("room") or ln.get("work_type") or "Work",
                        "description": ln["description"], "qty": qty, "unit": ln.get("unit"), "rate": round(amount / qty, 4),
                        "cost": round(ln["line_cost"] * (1 + est["overhead_pct"] / 100), 2), "optional": False, "selected": True})
    if p["type"] == "interior":
        if p.get("fee"):
            out.append({"id": "fee-0", "section": "Design fee", "description": fee_text(p["fee"]),
                        "qty": 1, "unit": "lot", "rate": round(fee_amount(p["fee"]), 2), "cost": None, "optional": False, "selected": True})
        for pr in p.get("products") or []:
            out.append({"id": f"prod-{pr['id']}", "section": pr.get("room") or "Products",
                        "description": pr["name"] + (f" ({pr['brand']})" if pr.get("brand") else ""), "qty": pr["qty"], "unit": pr["unit"],
                        "rate": round(pr["trade_price"] * (1 + pr["markup_pct"] / 100), 2), "cost": round(pr["trade_price"] * pr["qty"], 2),
                        "optional": pr["optional"], "selected": pr["selected"]})
    return out + [dict(x) for x in p.get("extra_items") or []]


def compute(p, selected=None):
    """Required lines + chosen optional lines -> discount -> tax. `selected` = the client's choice of optional ids."""
    if p["type"] == "simple":
        p["items"] = []
        p["totals"] = {"subtotal": p.get("value") or 0, "discount": 0, "taxable": p.get("value") or 0, "tax": 0,
                       "total": p.get("value") or 0, "cost": None, "margin": None, "margin_pct": None, "optional_available": 0}
        return p
    items = lines(p)
    for it in items:
        it["amount"] = round(it["qty"] * it["rate"], 2)
        if it["optional"] and selected is not None:
            it["selected"] = it["id"] in selected
    chosen = [i for i in items if not i["optional"] or i["selected"]]
    subtotal = sum(i["amount"] for i in chosen)
    discount = subtotal * p.get("discount_pct", 0) / 100
    taxable = subtotal - discount
    tax = taxable * p.get("tax_pct", 0) / 100
    costs = [i.get("cost") for i in chosen]
    cost = sum(c or 0 for c in costs) if chosen and all(c is not None for c in costs) else None
    p["items"] = items
    p["totals"] = {k: (round(v, 2) if v is not None else None) for k, v in {
        "subtotal": subtotal, "discount": discount, "taxable": taxable, "tax": tax, "total": taxable + tax,
        "optional_available": sum(i["amount"] for i in items if i["optional"]), "cost": cost,
        "margin": (taxable - cost) if cost is not None else None,
        "margin_pct": ((taxable - cost) / taxable * 100) if cost is not None and taxable else None}.items()}
    p["value"] = p["totals"]["total"]
    return p


def limits_breached(p):
    s = sales.settings()
    out = []
    if p.get("discount_pct", 0) > s["max_discount_pct"]:
        out.append(f"discount {p['discount_pct']:g}% is above {s['max_discount_pct']:g}%")
    mp = (p.get("totals") or {}).get("margin_pct")
    if mp is not None and mp < s["min_margin_pct"]:
        out.append(f"margin {mp:.1f}% is below {s['min_margin_pct']:g}%")
    return out


# ---------------- views ----------------
def branding(company):
    b = company.get("branding") or {}
    return {"name": company["name"], "primary": b.get("primary") or "#1f6feb",
            "logo_url": f"/api/public/logo/{company['_id']}" if b.get("logo_key") else None,
            **{k: b.get(k) for k in ("address", "phone", "email", "website", "footer")}, "gstin": company.get("gstin"),
            "tax_label": company.get("tax_label") or "Tax", "currency": company.get("currency", "INR")}


def client_view(p, company, lead=None):
    """What the client sees: no cost, overheads, markup, trade prices or margin."""
    lead = lead or db.leads.find_one({"_id": oid(p["lead_id"])}) or {}
    tt = p.get("totals") or {}
    total = tt.get("total") or 0
    contract = db.contracts.find_one({"_id": oid(p.get("contract_id"))}) if p.get("contract_id") else None
    return serialize({
        "company": branding(company), "number": p["number"], "version": p["version"], "title": p["title"],
        "type": p["type"], "type_label": PROPOSAL_TYPES[p["type"]], "client": lead.get("contact_name"), "project": lead.get("title"),
        "intro": p.get("intro"), "scope_text": p.get("scope_text"), "terms": p.get("terms"), "valid_until": p["valid_until"],
        "items": [{k: i[k] for k in ("id", "section", "description", "qty", "unit", "rate", "amount", "optional", "selected")}
                  for i in p.get("items") or []],
        "discount_pct": p.get("discount_pct", 0), "tax_pct": p.get("tax_pct", 0),
        "totals": {k: tt.get(k) for k in ("subtotal", "discount", "taxable", "tax", "total", "optional_available")},
        "payment_schedule": [{**r, "amount": round(total * r["pct"] / 100, 2)} for r in p.get("payment_schedule") or []],
        "status": p["status"], "has_file": bool(p.get("file_key")),
        "acceptance": {k: (p.get("acceptance") or {}).get(k) for k in ("name", "at", "signature", "method")} if p.get("acceptance") else None,
        "response": {k: (p.get("response") or {}).get(k) for k in ("reason", "comment", "at")} if p.get("response") and p["status"] != "accepted" else None,
        "contract_number": contract and contract["number"],
        "expired": p["status"] == "sent" and p["valid_until"] < sales.today(),
    })


def staff_view(p):
    data = t.out(p)
    if not can("proposals", True):
        data.pop("token", None)
    data["link"] = f"/p/{p['token']}" if p.get("token") and can("proposals", True) else None
    data["breaches"] = limits_breached(p) if p["status"] == "draft" else []
    return data


def load_proposal(pid):
    p = t.get("proposals", pid)
    load_lead(p["lead_id"])
    return p


def draft(pid):
    p = load_proposal(pid)
    open_lead(p["lead_id"])
    if p["status"] != "draft":
        abort(409, f"This proposal is {p['status'].replace('_', ' ')}; revise it to make a new version")
    return p


# ---------------- staff endpoints ----------------
@bp.get("/proposals")
@api("proposals", write=False)
def all_proposals():
    q = {k: request.args[k] for k in ("status", "type") if request.args.get(k)}
    if sales.restricted():
        q["lead_id"] = {"$in": [str(x["_id"]) for x in t.find("leads", {"owner_id": g.uid})]}
    rows = t.find("proposals", q, sort=[("created_at", -1)], limit=500)
    return jsonify([{k: v for k, v in staff_view(p).items() if k not in ("items", "products", "extra_items", "views")} for p in rows])


@bp.get("/leads/<_id>/proposals")
@api("proposals", write=False)
def list_proposals(_id):
    lead = load_lead(_id)
    return jsonify({"proposals": [staff_view(p) for p in t.find("proposals", {"lead_id": _id}, sort=[("version", 1)])],
                    "channels": PROPOSAL_CHANNELS, "reject_reasons": REJECT_REASONS, "types": PROPOSAL_TYPES,
                    "default_type": SERVICE_PROPOSAL_TYPE.get(lead["service"], "fee"),
                    "templates": serialize(t.find("proposal_templates", {}, sort=[("type", 1), ("name", 1)]))})


@bp.post("/leads/<_id>/proposals")
@api("proposals")
def create_proposal(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    src = None
    if d.get("revision_of"):
        src = t.get("proposals", d["revision_of"], required=False)
        if not src or src["lead_id"] != _id:
            abort(400, "Revise a proposal of this lead")
    ptype = (src or {}).get("type") or d.get("type") or ("simple" if d.get("value") not in (None, "") and not d.get("estimate_id")
                                                        else SERVICE_PROPOSAL_TYPE.get(lead["service"], "fee"))
    if ptype not in PROPOSAL_TYPES:
        abort(400, f"Type must be one of: {', '.join(PROPOSAL_TYPES)}")
    tpl = None
    if d.get("template_id") and not src:
        tpl = t.get("proposal_templates", d["template_id"], required=False) or abort(400, "Template not found")
        if tpl["type"] != ptype:
            abort(400, "That template is for another proposal type")
    base = {"intro": None, "scope_text": None, "terms": None, "extra_items": [], "products": [], "fee": None, "estimate_id": None,
            "payment_schedule": default_schedule(lead["service"]), "discount_pct": 0.0,
            "tax_pct": float(g.company.get("tax_rate") or 0), "value": None}
    if tpl:
        base.update({k: tpl.get(k) for k in ("intro", "scope_text", "terms") if tpl.get(k)})
        base["extra_items"] = [{**i, "id": t.sid()} for i in tpl.get("items") or []]
        if tpl.get("payment_schedule"):
            base["payment_schedule"] = [{**r, "id": t.sid()} for r in tpl["payment_schedule"]]
        if tpl.get("fee"):
            base["fee"] = tpl["fee"]
    if src:
        base.update({k: src.get(k) for k in base})
    if d.get("estimate_id") or ptype == "construction" and not src:
        est = t.get("estimates", d.get("estimate_id"), required=False)
        if not est or est["lead_id"] != _id:
            abort(400, "Choose an approved estimate of this lead")
        if est["status"] != "approved":
            abort(400, "Only an approved estimate can go into a proposal")
        base.update(estimate_id=str(est["_id"]), estimate_number=est["number"], discount_pct=est["discount_pct"], tax_pct=est["tax_pct"])
    if ptype == "simple" and (not src or d.get("value") not in (None, "")):  # a revision may carry a new value
        base["value"] = num(d.get("value"), "Value", required=True, positive=True)
    valid = a_date(d.get("valid_until") or (src or {}).get("valid_until"), "Valid until")
    if valid <= sales.today():
        abort(400, "Valid until must be in the future")
    if d.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
        abort(400, "Upload the proposal file first")
    last = db.proposals.find_one({"company_id": g.cid, "lead_id": _id}, {"version": 1}, sort=[("version", -1)])
    version = (last or {}).get("version", 0) + 1  # max + 1: deleted drafts never free a number
    p = compute({**base, "type": ptype, "lead_id": _id, "lead_title": lead["title"], "number": t.next_number("PRO", "PRO"),
                 "version": version, "title": (d.get("title") or f"{PROPOSAL_TYPES[ptype]} v{version}").strip(),
                 "valid_until": valid, "file_key": d.get("file_key") or (src or {}).get("file_key"), "status": "draft",
                 "sent_at": None, "response": None, "approval": None, "revision_of": d.get("revision_of"), "token": None,
                 "views": [], "view_count": 0, "first_viewed_at": None, "last_viewed_at": None})
    if p["type"] == "simple" and not p.get("value"):
        abort(400, "Enter the proposal value")
    p = t.insert("proposals", p)
    log(_id, "proposal", f"Proposal {p['number']} (v{version}, {PROPOSAL_TYPES[ptype].lower()}) prepared — {money_text(p['value'])}, "
        f"valid until {valid}" + (f", revising {src['number']}" if src else "") + (f", from template {tpl['name']}" if tpl else ""),
        proposal_id=str(p["_id"]))
    return jsonify(staff_view(p)), 201


@bp.get("/proposals/<pid>")
@api("proposals", write=False)
def get_proposal(pid):
    p = load_proposal(pid)
    data = staff_view(p)
    data["meta"] = {"types": PROPOSAL_TYPES, "fee_bases": FEE_BASES, "triggers": SCHEDULE_TRIGGERS,
                    "stages": stages_for(db.leads.find_one({"_id": oid(p["lead_id"])})["service"]),
                    "limits": {k: sales.settings()[k] for k in ("max_discount_pct", "min_margin_pct")},
                    "tax_label": g.company.get("tax_label") or "Tax", "is_approver": sales.is_manager()}
    return jsonify(data)


@bp.get("/proposals/<pid>/preview")
@api("proposals", write=False)
def preview(pid):
    """The client's view, for staff (the view is not counted)."""
    return jsonify(client_view(load_proposal(pid), g.company))


@bp.put("/proposals/<pid>")
@api("proposals")
def update_proposal(pid):
    p = draft(pid)
    d = request.get_json(force=True) or {}
    lead = db.leads.find_one({"_id": oid(p["lead_id"])})
    ch = {}
    for k in ("intro", "scope_text", "terms"):
        if k in d:
            ch[k] = (d[k] or "").strip() or None
    if "title" in d:
        ch["title"] = (d["title"] or "").strip() or abort(400, "Title is required")
    if "valid_until" in d:
        ch["valid_until"] = a_date(d["valid_until"], "Valid until")
        if ch["valid_until"] <= sales.today():
            abort(400, "Valid until must be in the future")
    if "file_key" in d:
        if d["file_key"] and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
            abort(400, "Upload the proposal file first")
        ch["file_key"] = d["file_key"] or None
    for k, label in (("discount_pct", "Discount %"), ("tax_pct", "Tax %")):
        if k in d:
            v = num(d[k], label) or 0
            if v > 100:
                abort(400, f"{label} must be at most 100")
            ch[k] = v
    if "fee" in d:
        if p["type"] not in ("fee", "interior"):
            abort(400, "Only fee proposals and interior quotes have a fee")
        ch["fee"] = clean_fee(d["fee"], "Design fee" if p["type"] == "interior" else "Fee") if d["fee"] else None
        if ch["fee"] and p["type"] == "interior" and ch["fee"]["basis"] not in ("fixed", "per_area"):
            abort(400, "The design fee is fixed or per area")
    if "products" in d:
        if p["type"] != "interior":
            abort(400, "Only interior quotes have products")
        ch["products"] = clean_products(d["products"])
    if "extra_items" in d:
        ch["extra_items"] = clean_items(d["extra_items"])
    if "estimate_id" in d and p["type"] == "construction":
        est = t.get("estimates", d["estimate_id"], required=False)
        if not est or est["lead_id"] != p["lead_id"] or est["status"] != "approved":
            abort(400, "Choose an approved estimate of this lead")
        ch.update(estimate_id=d["estimate_id"], estimate_number=est["number"])
    if "value" in d and p["type"] == "simple":
        ch["value"] = num(d["value"], "Value", required=True, positive=True)
    if "payment_schedule" in d:
        ch["payment_schedule"] = clean_schedule(d["payment_schedule"], lead["service"])
    merged = compute({**p, **ch})
    ch.update(items=merged["items"], totals=merged["totals"], value=merged["value"])
    if merged["totals"] != p.get("totals") or merged["value"] != p.get("value"):
        ch["approval"] = None  # an approval covers the prices it was given; text-only edits keep it
    upd = t.update("proposals", pid, ch)
    log(p["lead_id"], "proposal", f"Proposal {p['number']} edited — {money_text(upd['value'])}", proposal_id=pid)
    return jsonify(staff_view(upd))


@bp.delete("/proposals/<pid>")
@api("proposals")
def delete_proposal(pid):
    p = draft(pid)
    t.delete("proposals", pid)
    log(p["lead_id"], "proposal", f"Draft proposal {p['number']} deleted")
    return jsonify({"ok": True})


@bp.post("/proposals/<pid>/approval")
@api("proposals")
def request_approval(pid):
    p = draft(pid)
    reasons = limits_breached(p)
    if not reasons:
        abort(400, "This proposal is within the limits; it needs no approval")
    appr = {"status": "pending", "reasons": reasons, "requested_by": g.user.get("name"), "requested_by_id": g.uid, "requested_at": t.now()}
    upd = t.update("proposals", pid, {"approval": appr})
    log(p["lead_id"], "proposal", f"Proposal {p['number']} sent for approval: {'; '.join(reasons)}", proposal_id=pid)
    notify.send("approval_needed", notify.managers(), f"Proposal {p['number']} for {p['lead_title']} needs approval ({'; '.join(reasons)})",
                f"/app/proposals/{pid}", p["lead_id"])
    return jsonify(staff_view(upd))


@bp.post("/proposals/<pid>/approval/decide")
@api("proposals")
def decide_approval(pid):
    p = draft(pid)
    if not sales.is_manager():
        abort(403, "Only the owner or the sales manager can approve")
    if (p.get("approval") or {}).get("status") != "pending":
        abort(409, "This proposal is not waiting for approval")
    d = request.get_json(force=True) or {}
    note = (d.get("note") or "").strip()
    if not d.get("approve") and not note:
        abort(400, "Say why it is refused")
    appr = {**p["approval"], "status": "approved" if d.get("approve") else "refused", "decided_by": g.user.get("name"),
            "decided_at": t.now(), "note": note or None}
    upd = t.update("proposals", pid, {"approval": appr})
    log(p["lead_id"], "proposal", f"Proposal {p['number']} {appr['status']} by {g.user.get('name')}" + (f": {note}" if note else ""), proposal_id=pid)
    notify.send("approval_decided", [p["approval"].get("requested_by_id")], f"Proposal {p['number']} {appr['status']}" + (f": {note}" if note else ""),
                f"/app/proposals/{pid}", p["lead_id"])
    return jsonify(staff_view(upd))


def supersede(lead_id, keep):
    for o in t.find("proposals", {"lead_id": lead_id, "status": {"$in": ["sent", "revision_requested"]}}):
        if str(o["_id"]) != keep:
            t.update("proposals", str(o["_id"]), {"status": "superseded"})


@bp.post("/proposals/<pid>/send")
@api("proposals")
def send_proposal(pid):
    p = draft(pid)
    lead = db.leads.find_one({"_id": oid(p["lead_id"])})
    d = request.get_json(force=True) or {}
    channel = d.get("channel")
    if channel not in PROPOSAL_CHANNELS:
        abort(400, f"How is it sent? {', '.join(PROPOSAL_CHANNELS)}")
    if p["valid_until"] <= sales.today():
        abort(409, "The proposal's validity has passed; change the date first")
    if p["type"] != "simple" and not p.get("items"):
        abort(400, "Add the priced lines before sending")
    if (p.get("totals") or {}).get("total", 0) <= 0:
        abort(400, "The proposal total must be above zero")
    clean_schedule(p.get("payment_schedule"), lead["service"], require_total=True)
    reasons = limits_breached(p)
    if reasons and not sales.is_manager() and (p.get("approval") or {}).get("status") != "approved":
        abort(409, f"Needs approval before sending: {'; '.join(reasons)}")
    supersede(p["lead_id"], pid)
    token = p.get("token") or secrets.token_urlsafe(24)
    upd = t.update("proposals", pid, {"status": "sent", "sent_at": t.now(), "channel": channel, "sent_by": g.user.get("name"), "token": token})
    if not lead.get("accepted_proposal_id"):
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {"proposal_value": p["value"], "last_activity_at": t.now()}})
    link = f"{(g.company.get('email_settings') or {}).get('app_url') or request.host_url.rstrip('/')}/p/{token}"
    log(p["lead_id"], "proposal", f"Proposal {p['number']} sent by {channel.replace('_', ' ')} — {money_text(p['value'])}", proposal_id=pid)
    if channel == "email":
        atts = []
        if p.get("file_key"):
            f = db.files.find_one({"company_id": g.cid, "key": p["file_key"]})
            with open(os.path.join(Config.UPLOAD_DIR, p["file_key"]), "rb") as fh:
                atts.append((f["name"], fh.read()))
        c = db.contacts.find_one({"_id": oid(lead.get("contact_id"))}, {"email": 1})
        result = notify.deliver(g.company, (c or {}).get("email"), f"Proposal {p['number']} — {lead['title']}",
                                f"Dear {lead.get('contact_name')},\n\nPlease find our proposal for {lead['title']}: {money_text(p['value'])}, "
                                f"valid until {p['valid_until']}.\n\nView, choose options and accept online: {link}\n\nRegards,\n{g.company['name']}", atts)
        log(p["lead_id"], "email", f"Proposal {p['number']} emailed to the client: {result}", outcome=result, auto=True)
    out = staff_view(upd)
    out["link_full"] = link
    return jsonify(out)


@bp.post("/proposals/<pid>/respond")
@api("proposals")
def respond_proposal(pid):
    """The client's answer recorded by staff (on paper, by phone): accepted, rejected or a revision requested."""
    p = load_proposal(pid)
    lead = open_lead(p["lead_id"])
    if p["status"] != "sent":
        abort(409, "Only a sent proposal can be answered")
    d = request.get_json(force=True) or {}
    result = d.get("result")
    if result == "accepted":
        signer = (d.get("signed_by") or lead.get("contact_name") or "").strip()
        return jsonify(staff_view(accept(p, lead, {"name": signer, "method": "recorded by " + (g.user.get("name") or "staff"),
                                                   "comment": (d.get("comment") or "").strip() or None, "file_key": d.get("file_key")},
                                         d.get("selected"))))
    return jsonify(staff_view(decline(p, lead, d, by=g.user.get("name"))))


def decline(p, lead, d, by):
    result = d.get("result") or ("revision_requested" if d.get("revision") else "rejected")
    if result not in ("rejected", "revision_requested"):
        abort(400, "Result must be accepted, rejected or revision requested")
    if d.get("reason") not in REJECT_REASONS:
        abort(400, f"Choose the reason: {', '.join(REJECT_REASONS)}")
    comment = (d.get("comment") or "").strip()[:2000] or None
    upd = t.update("proposals", str(p["_id"]), {"status": result, "response": {"at": t.now(), "by": by, "reason": d["reason"], "comment": comment}})
    text = f"Proposal {p['number']} {'rejected' if result == 'rejected' else 'needs a revision'} — {d['reason']}" + (f": {comment}" if comment else "")
    log(p["lead_id"], "proposal", text, proposal_id=str(p["_id"]))
    notify.send("proposal_response", [lead.get("owner_id")] + notify.managers(), f"{lead['title']}: {text}", f"/app/leads/{p['lead_id']}",
                p["lead_id"], skip_self=bool(getattr(g, "uid", None)))
    return upd


def accept(p, lead, acceptance, selected=None):
    """Accepted (signed online or recorded): final total with the chosen options, other versions superseded,
    and the contract created with the payment schedule."""
    pid = str(p["_id"])
    if db.proposals.find_one({"company_id": g.cid, "lead_id": p["lead_id"], "status": "accepted"}):
        abort(409, "Another proposal of this lead is already accepted")
    if not acceptance.get("name"):
        abort(400, "Enter the name of the person accepting")
    optional_ids = {i["id"] for i in p.get("items") or [] if i["optional"]}
    if selected is not None:
        bad = set(selected) - optional_ids
        if bad:
            abort(400, "Only optional lines can be chosen")
    final = compute(dict(p), set(selected) if selected is not None else None)
    acceptance = {**acceptance, "at": t.now(), "selected": [i["id"] for i in final["items"] if i["optional"] and i["selected"]]}
    upd = t.update("proposals", pid, {"status": "accepted", "acceptance": acceptance, "items": final["items"], "totals": final["totals"],
                                      "value": final["value"], "response": {"at": t.now(), "by": acceptance["name"]}})
    supersede(p["lead_id"], pid)
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"proposal_value": final["value"], "accepted_proposal_id": pid, "last_activity_at": t.now()}})
    total = final["totals"]["total"]
    contract = t.insert("contracts", {
        "number": t.next_number("CON", "CON"), "lead_id": p["lead_id"], "lead_title": lead["title"], "proposal_id": pid,
        "proposal_number": p["number"], "client_id": lead.get("contact_id"), "client_name": lead.get("contact_name"),
        "service": lead["service"], "value": total, "totals": final["totals"],
        "items": [i for i in final["items"] if not i["optional"] or i["selected"]],
        "terms": p.get("terms"), "scope_text": p.get("scope_text"),
        "acceptance": {k: acceptance.get(k) for k in ("name", "at", "method", "ip", "user_agent", "signature", "comment", "file_key")},
        "payment_schedule": [{**r, "amount": round(total * r["pct"] / 100, 2), "milestone_id": None} for r in p.get("payment_schedule") or []],
        "project_id": lead.get("project_id"), "status": "signed", "signed_at": t.now()})
    t.update("proposals", pid, {"contract_id": str(contract["_id"])})
    log(p["lead_id"], "proposal", f"Proposal {p['number']} accepted by {acceptance['name']} ({acceptance['method']}) — {money_text(total)}; "
        f"contract {contract['number']} created", proposal_id=pid)
    notify.send("contract_signed", [lead.get("owner_id")] + notify.managers(),
                f"{lead['title']}: proposal {p['number']} accepted — contract {contract['number']}, {money_text(total)}. Mark the lead as won.",
                f"/app/leads/{p['lead_id']}", p["lead_id"], skip_self=bool(getattr(g, "uid", None)))
    return t.get("proposals", pid)


# ---------------- the client link (no login) ----------------
def public_proposal(token):
    p = db.proposals.find_one({"token": token}) if token else None
    company = p and db.companies.find_one({"_id": oid(p["company_id"]), "deleted_at": None})
    if not p or not company or company.get("status") in ("suspended", "read_only", "cancelled") or \
            p["status"] in ("draft", "superseded"):
        abort(404, "This proposal is not available. Please ask us for the latest version.")
    g.cid, g.uid, g.company, g.role, g.user = p["company_id"], None, company, None, {"name": "Client"}
    return p, company, db.leads.find_one({"_id": oid(p["lead_id"])}) or {}


def visitor():
    return {"ip": (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:300]}


@bp.get("/public/proposals/<token>")
def public_view(token):
    p, company, lead = public_proposal(token)
    if p["status"] == "sent":
        now = t.now()
        first = not p.get("first_viewed_at")
        db.proposals.update_one({"_id": p["_id"]}, {"$set": {"last_viewed_at": now, **({"first_viewed_at": now} if first else {})},
                                                    "$inc": {"view_count": 1},
                                                    "$push": {"views": {"$each": [{"at": now, **visitor()}], "$slice": -100}}})
        if first:
            log(p["lead_id"], "proposal", f"Client opened proposal {p['number']}", proposal_id=str(p["_id"]))
            notify.send("proposal_viewed", [lead.get("owner_id")] if lead.get("owner_id") else notify.managers(),
                        f"{lead.get('contact_name')} opened proposal {p['number']} ({lead.get('title')})", f"/app/leads/{p['lead_id']}",
                        p["lead_id"], key=f"viewed:{p['_id']}")
    return jsonify(client_view(p, company, lead))


@bp.get("/public/proposals/<token>/file")
def public_file(token):
    p, _, _ = public_proposal(token)
    if not p.get("file_key"):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, p["file_key"], as_attachment=True)


@bp.post("/public/proposals/<token>/accept")
def public_accept(token):
    p, company, lead = public_proposal(token)
    if p["status"] != "sent":
        abort(409, "This proposal has already been answered")
    if p["valid_until"] < sales.today():
        abort(409, "This proposal has expired. Please ask us for a new one.")
    if lead.get("status") not in ("open", "on_hold"):
        abort(409, "This proposal is no longer open")
    d = request.get_json(force=True) or {}
    if not d.get("agree"):
        abort(400, "Please confirm that you accept the proposal and its terms")
    name = (d.get("name") or "").strip()[:120]
    if not name:
        abort(400, "Please type your full name")
    sig = d.get("signature") or ""
    if not sig.startswith("data:image/png;base64,") or len(sig) > MAX_SIGNATURE or len(sig) < 200:
        abort(400, "Please sign in the box")
    g.user = {"name": name}
    upd = accept(p, lead, {"name": name, "method": "signed online", "signature": sig, **visitor()}, d.get("selected") or [])
    c = db.contacts.find_one({"_id": oid(lead.get("contact_id"))}, {"email": 1})
    base = (company.get("email_settings") or {}).get("app_url") or request.host_url.rstrip("/")
    result = notify.deliver(company, (c or {}).get("email"), f"You accepted proposal {p['number']}",
                            f"Dear {lead.get('contact_name')},\n\nThank you — we have your acceptance of proposal {p['number']} "
                            f"({money_text(upd['value'])}). Your signed copy: {base}/p/{token}\n\nRegards,\n{company['name']}")
    log(p["lead_id"], "email", f"Signed copy emailed to the client: {result}", outcome=result, auto=True)
    return jsonify(client_view(upd, company, lead))


@bp.post("/public/proposals/<token>/decline")
def public_decline(token):
    p, company, lead = public_proposal(token)
    if p["status"] != "sent":
        abort(409, "This proposal has already been answered")
    d = request.get_json(force=True) or {}
    upd = decline(p, lead, {"result": "revision_requested" if d.get("revision") else "rejected", "reason": d.get("reason"),
                            "comment": d.get("comment")}, by=lead.get("contact_name") or "Client")
    return jsonify(client_view(upd, company, lead))


@bp.get("/public/logo/<cid>")
def public_logo(cid):
    c = db.companies.find_one({"_id": oid(cid), "deleted_at": None}, {"branding": 1})
    key = ((c or {}).get("branding") or {}).get("logo_key")
    if not key or not key.startswith(f"{cid}_"):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, key)


# ---------------- branding ----------------
@bp.put("/company/branding")
@api("settings")
def set_branding():
    d = request.get_json(force=True) or {}
    b = dict(g.company.get("branding") or {})
    if "logo_key" in d:
        if d["logo_key"]:
            f = db.files.find_one({"company_id": g.cid, "key": d["logo_key"]}) or abort(400, "Upload the logo first")
            if os.path.splitext(f["name"])[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                abort(400, "The logo must be a PNG, JPG or WEBP image")
        b["logo_key"] = d["logo_key"] or None
    if "primary" in d:
        if not HEX.match(d["primary"] or ""):
            abort(400, "Brand colour must be a hex colour like #1f6feb")
        b["primary"] = d["primary"]
    for k, n in (("address", 300), ("phone", 40), ("email", 120), ("website", 120), ("footer", 300)):
        if k in d:
            b[k] = (d[k] or "").strip()[:n] or None
    if b.get("email"):
        from .contacts import EMAIL_RE
        if not EMAIL_RE.match(b["email"]):
            abort(400, "Email is not valid")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"branding": b}})
    t.audit("update", "branding", g.company["_id"], note=", ".join(sorted(d)))
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return jsonify(branding(g.company) | {"logo_key": b.get("logo_key")})


@bp.get("/company/branding")
@api(None)
def get_branding():
    return jsonify(branding(g.company) | {"logo_key": (g.company.get("branding") or {}).get("logo_key")})


# ---------------- templates ----------------
def clean_template(d):
    if d.get("type") not in PROPOSAL_TYPES or d["type"] == "simple":
        abort(400, "Template type must be fee, construction or interior")
    name = (d.get("name") or "").strip() or abort(400, "Name the template")
    service = d.get("service") if d.get("service") in SERVICES else None
    out = {"name": name, "type": d["type"], "service": service,
           **{k: (d.get(k) or "").strip() or None for k in ("intro", "scope_text", "terms")},
           "items": clean_items(d.get("items")), "fee": clean_fee(d["fee"]) if d.get("fee") else None}
    out["payment_schedule"] = clean_schedule(d.get("payment_schedule"), service) if service else []
    if d.get("payment_schedule") and not service:
        abort(400, "Choose the service so the schedule can use its stages")
    return out


@bp.get("/proposal_templates")
@api("proposals", write=False)
def list_templates():
    return jsonify(serialize(t.find("proposal_templates", {}, sort=[("type", 1), ("name", 1)])))


@bp.post("/proposal_templates")
@api("settings")
def create_template():
    return jsonify(serialize(t.insert("proposal_templates", clean_template(request.get_json(force=True) or {})))), 201


@bp.put("/proposal_templates/<tid>")
@api("settings")
def update_template(tid):
    t.get("proposal_templates", tid)
    return jsonify(serialize(t.update("proposal_templates", tid, clean_template(request.get_json(force=True) or {}))))


@bp.delete("/proposal_templates/<tid>")
@api("settings")
def delete_template(tid):
    t.get("proposal_templates", tid)
    t.delete("proposal_templates", tid)
    return jsonify({"ok": True})


# ---------------- contracts ----------------
def present_contract(c):
    """Each schedule row is due once its trigger happened: on signing, on its date, or when its milestone is achieved."""
    data = t.out(c)
    project = db.projects.find_one({"_id": oid(c.get("project_id")), "company_id": g.cid}) if c.get("project_id") else None
    ms = {m["id"]: m for s in (project or {}).get("stages", []) for m in s.get("milestones", [])}
    today = sales.today()
    for r in data["payment_schedule"]:
        if r.get("status") in ("invoiced", "paid"):
            continue
        if r["trigger"] == "signing":
            r["state"] = "due"
        elif r["trigger"] == "date":
            r["state"] = "due" if r["date"] <= today else "upcoming"
        else:
            m = ms.get(r.get("milestone_id"))
            r["state"] = "due" if m and m.get("status") == "achieved" else ("upcoming" if m else "waiting for the project")
            r["milestone"] = m and {"name": m["name"], "due": m.get("due"), "status": m.get("status")}
    data["project_code"] = project and project.get("code")
    data["acceptance"] = {k: v for k, v in (c.get("acceptance") or {}).items() if k not in ("ip", "user_agent")} | (
        {"ip": c["acceptance"].get("ip")} if can("proposals", True) and c.get("acceptance") else {})
    return data


def link_contract(lead, project):
    """Won: the signed contract joins the project; each stage row points at that stage's 'complete' milestone."""
    c = db.contracts.find_one({"company_id": g.cid, "lead_id": str(lead["_id"]), "status": "signed"})
    if not c:
        return None
    by_stage = {}
    for s in project.get("stages", []):
        if s.get("service") == c["service"] and s.get("milestones"):
            by_stage.setdefault(s["name"], s["milestones"][0]["id"])
    rows = [{**r, "milestone_id": by_stage.get(r.get("stage")) if r["trigger"] == "stage" else None} for r in c["payment_schedule"]]
    t.update("contracts", str(c["_id"]), {"project_id": str(project["_id"]), "payment_schedule": rows})
    db.projects.update_one({"_id": project["_id"]}, {"$set": {"contract_id": str(c["_id"]), "contract_number": c["number"]}})
    # invoices raised before the win (usually the advance on signing) join the project
    db.invoices.update_many({"company_id": g.cid, "contract_id": str(c["_id"])},
                            {"$set": {"project_id": str(project["_id"]), "project_name": project["name"], "project_code": project.get("code")}})
    return c


@bp.get("/contracts")
@api("proposals", write=False)
def list_contracts():
    return jsonify([{k: v for k, v in present_contract(c).items() if k not in ("items", "acceptance")}
                    for c in t.find("contracts", {}, sort=[("signed_at", -1)])])


@bp.get("/contracts/<cid_>")
@api(None)
def get_contract(cid_):
    c = t.get("contracts", cid_)
    if not (can("proposals") or can("finance") or (c.get("project_id") and can("projects"))):
        abort(403, "Your role cannot view contracts")
    if not can("proposals") and not can("finance"):
        from .projects import load
        load(c["project_id"])  # must be on the project
    return jsonify(present_contract(c))


@bp.get("/projects/<pid>/contract")
@api("projects", write=False)
def project_contract(pid):
    from .projects import load
    load(pid)
    c = db.contracts.find_one({"company_id": g.cid, "project_id": pid})
    return jsonify(present_contract(c) if c and not g.hide_costs else None)
