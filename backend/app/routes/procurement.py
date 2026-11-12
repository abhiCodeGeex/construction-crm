"""Phase H — procurement. Blocks 1-2: purchase requests, RFQs with quotes side by side, purchase orders.

* A purchase request (PR) asks for material on a project stage. Raised by Procurement / PM / Owner, or by a Site
  Supervisor on the project (who never sees prices), or by ordering a selection that has no supplier.
* An RFQ asks several suppliers for prices on request lines; quotes are compared side by side next to the rate
  library; awarding (whole or per line) makes one draft PO per supplier, with a reason when the lowest is not chosen.
* A purchase order commits money against the stage budget (the *ordered* figure). It is numbered on approval (no gaps
  from deleted drafts): within the company limit and budget it is approved on submit; above the limit an Owner
  approves; over a stage budget a manager on the project approves with a reason. Sent by email and WhatsApp; changed
  only by an amendment (an increase is approved again); cancelled only with nothing received.
Who: procurement rw (Owner, PM, Procurement). Owner and Procurement reach every project; others the projects they are on.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, budget, project_events as ev, sales
from ..services.defaults import VENDOR_TYPES, OVERSPEND_REASONS, SIGNOFF_METHODS
from .finance import settings as fin_settings
from .lead_money import a_date, money_text
from .lead_steps import num
from .projects import member

bp = Blueprint("procurement", __name__)

PR_SOURCES = ("site", "pm", "selection")


def r2(v):
    return round((v or 0) + 1e-9, 2)


# ---------------- access ----------------
def all_projects():
    return g.role in ("owner", "procurement", "accounts")


def project(pid, write=False):
    if not can("procurement") and g.role != "site":
        abort(403, "Your role cannot view procurement")
    p = t.get("projects", pid)
    if not (all_projects() or member(p)):
        abort(404, "project not found")
    if write and not can("procurement", True):
        abort(403, "Your role cannot change procurement")
    return p


def site_member(p):
    return g.role == "site" and member(p) is not None


def visible_projects():
    if all_projects():
        return None
    return [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]


def scoped(q):
    ids = visible_projects()
    if ids is not None:
        q["project_id"] = {"$in": ids} if "project_id" not in q else q["project_id"]
    return q


def stage_of(p, sid):
    return next((s for s in p.get("stages", []) if s["id"] == sid), None) or abort(400, "Choose a stage of this project")


def vendor(cid_):
    v = db.contacts.find_one({"_id": oid(cid_), "company_id": g.cid}) if cid_ and len(str(cid_)) == 24 else None
    if not v or not set(v.get("types") or []) & set(VENDOR_TYPES):
        abort(400, "Choose a supplier, subcontractor, contractor or consultant")
    return v


def compliance_warning(v):
    from datetime import date
    today = date.today().isoformat()
    expired = [d.get("name") or d.get("type") for d in v.get("compliance") or [] if d.get("expiry") and d["expiry"] < today]
    return f"Compliance expired: {', '.join(expired)}" if expired else None  # decision H-8: warn, never block


# ---------------- purchase requests ----------------
def clean_pr_lines(rows, p):
    out = []
    for r in (rows or [])[:50]:
        desc = (r.get("description") or "").strip()[:200]
        rate = None
        if r.get("rate_id"):
            rate = db.rate_library.find_one({"_id": oid(r["rate_id"]), "company_id": g.cid}) or abort(400, "Rate library item not found")
            desc = desc or rate["name"]
        desc or abort(400, "Each line needs an item")
        qty = num(r.get("qty"), f"Quantity of {desc}", required=True, positive=True)
        st = stage_of(p, r.get("stage_id")) if r.get("stage_id") else None
        out.append({"id": r.get("id") or t.sid(), "description": desc, "rate_id": rate and str(rate["_id"]), "qty": qty,
                    "unit": (r.get("unit") or (rate or {}).get("unit") or "").strip()[:20] or None,
                    "needed_by": a_date(r.get("needed_by"), "Needed by", required=False), "stage_id": st and st["id"],
                    "status": "open", "po_id": None})
    if not out:
        abort(400, "Add at least one line")
    return out


def new_request(p, d, source):
    st = stage_of(p, d.get("stage_id"))
    lines = clean_pr_lines(d.get("lines"), p)
    for ln in lines:
        ln["stage_id"] = ln["stage_id"] or st["id"]
    pr = t.insert("purchase_requests", {"number": t.next_number("PR", "PR"), "project_id": str(p["_id"]), "project_name": p["name"],
                                        "project_code": p.get("code"), "stage_id": st["id"], "stage_name": st["name"], "lines": lines,
                                        "location": d.get("location") if d.get("location") in ("site", "office") else "site",
                                        "note": (d.get("note") or "").strip()[:500] or None, "source": source,
                                        "selection_id": d.get("selection_id"), "requested_by": g.uid,
                                        "requested_by_name": g.user.get("name"), "status": "open"})
    what = ", ".join(f"{ln['qty']:g} {ln['unit'] or ''} {ln['description']}" for ln in lines)
    notify.send("pr_raised", list(dict.fromkeys(notify.role_users("procurement") + ev.managers(p))), f"{pr['number']} on {p['name']}: {what[:200]}",
                "/app/procurement?tab=requests", project_id=str(p["_id"]))
    return pr


@bp.post("/projects/<pid>/purchase-requests")
@api(None)
def add_request(pid):
    if not (can("procurement", True) or g.role == "site"):
        abort(403, "Your role cannot raise purchase requests")
    p = project(pid)
    if not (can("procurement", True) or site_member(p)):
        abort(403, "Your role cannot raise purchase requests")
    d = request.get_json(force=True) or {}
    pr = new_request(p, d, "site" if g.role == "site" else "pm")
    return jsonify(serialize(pr)), 201


@bp.get("/projects/<pid>/purchase-requests")
@api(None)
def project_requests(pid):
    project(pid)
    return jsonify(serialize(t.find("purchase_requests", {"project_id": pid}, sort=[("created_at", -1)])))


@bp.get("/purchase-requests")
@api("procurement", write=False)
def all_requests():
    q = scoped({})
    if request.args.get("status"):
        q["status"] = {"$in": request.args["status"].split(",")}
    return jsonify(serialize(t.find("purchase_requests", q, sort=[("created_at", -1)], limit=500)))


@bp.post("/purchase-requests/<rid>/cancel")
@api(None)
def cancel_request(rid):
    pr = t.get("purchase_requests", rid)
    project(pr["project_id"])
    if not (can("procurement", True) or pr["requested_by"] == g.uid):
        abort(403, "Only Procurement or the person who asked can cancel")
    if pr["status"] not in ("open", "quoting"):
        abort(409, "Lines of this request are already ordered")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why")
    return jsonify(serialize(t.update("purchase_requests", rid, {"status": "cancelled", "cancel_reason": reason[:300]})))


@bp.put("/purchase-requests/<rid>")
@api(None)
def edit_request(rid):
    """Phase I: change an open request (lines, stage, location, note) before any of it is priced or ordered."""
    pr = t.get("purchase_requests", rid)
    p = project(pr["project_id"])
    if not (can("procurement", True) or pr["requested_by"] == g.uid):
        abort(403, "Only Procurement or the person who asked can change it")
    if pr["status"] != "open" or any(ln["status"] != "open" for ln in pr["lines"]):
        abort(409, "Only an open request that is not being priced or ordered is changed; cancel it and ask again")
    d = request.get_json(force=True) or {}
    ch = {}
    if "stage_id" in d:
        st = stage_of(p, d["stage_id"])
        ch.update(stage_id=st["id"], stage_name=st["name"])
    if "lines" in d:
        ch["lines"] = clean_pr_lines(d["lines"], p)
        for ln in ch["lines"]:
            ln["stage_id"] = ln["stage_id"] or ch.get("stage_id") or pr["stage_id"]
    if "location" in d:
        ch["location"] = d["location"] if d["location"] in ("site", "office") else "site"
    if "note" in d:
        ch["note"] = (d.get("note") or "").strip()[:500] or None
    return jsonify(serialize(t.update("purchase_requests", rid, ch)))


# ---------------- RFQs ----------------
@bp.post("/rfqs")
@api("procurement")
def add_rfq():
    d = request.get_json(force=True) or {}
    p = project(d.get("project_id"), write=True)
    lines = []
    prs = []
    for rid in dict.fromkeys(d.get("request_ids") or []):
        pr = db.purchase_requests.find_one({"_id": oid(rid), "company_id": g.cid, "project_id": str(p["_id"])}) if len(str(rid)) == 24 else None
        if not pr or pr["status"] not in ("open", "quoting"):
            abort(400, "Choose open purchase requests of this project")
        prs.append(pr)
        lines += [{"id": t.sid(), "pr_id": str(pr["_id"]), "pr_number": pr["number"], "pr_line_id": ln["id"], "description": ln["description"],
                   "rate_id": ln.get("rate_id"), "qty": ln["qty"], "unit": ln.get("unit"), "stage_id": ln["stage_id"]}
                  for ln in pr["lines"] if ln["status"] == "open"]
    if not lines:
        abort(400, "Choose the purchase requests to price")
    sups = []
    for sid in dict.fromkeys(d.get("supplier_ids") or []):
        v = vendor(sid)
        sups.append({"contact_id": sid, "name": v["name"], "email": v.get("email"), "warning": compliance_warning(v), "sent": None})
    if not sups:
        abort(400, "Ask at least one supplier")
    rfq = t.insert("rfqs", {"number": t.next_number("RFQ", "RFQ"), "project_id": str(p["_id"]), "project_name": p["name"],
                            "request_ids": [str(x["_id"]) for x in prs], "lines": lines, "suppliers": sups,
                            "due_date": a_date(d.get("due_date") or sales.today(), "Quotes due"), "quotes": [], "status": "draft",
                            "note": (d.get("note") or "").strip()[:500] or None, "created_by_name": g.user.get("name")})
    for pr in prs:
        db.purchase_requests.update_one({"_id": pr["_id"]}, {"$set": {"status": "quoting", "rfq_id": str(rfq["_id"])}})
    return jsonify(serialize(rfq)), 201


def load_rfq(rid, write=False):
    rfq = t.get("rfqs", rid)
    project(rfq["project_id"], write)
    return rfq


@bp.get("/rfqs")
@api("procurement", write=False)
def list_rfqs():
    q = scoped({})
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify(serialize(t.find("rfqs", q, sort=[("created_at", -1)], limit=300)))


@bp.get("/rfqs/<rid>")
@api("procurement", write=False)
def get_rfq(rid):
    return jsonify(serialize(load_rfq(rid)))


@bp.put("/rfqs/<rid>")
@api("procurement")
def edit_rfq(rid):
    """Phase I: change the due date, note and suppliers of an open RFQ; a supplier who has quoted stays on it."""
    rfq = load_rfq(rid, True)
    if rfq["status"] not in ("draft", "sent"):
        abort(409, "This RFQ is closed")
    d = request.get_json(force=True) or {}
    ch = {}
    if "due_date" in d:
        ch["due_date"] = a_date(d["due_date"], "Quotes due")
    if "note" in d:
        ch["note"] = (d.get("note") or "").strip()[:500] or None
    if "supplier_ids" in d:
        quoted = {q["supplier_id"] for q in rfq["quotes"]}
        want = list(dict.fromkeys(d.get("supplier_ids") or []))
        gone = quoted - set(want)
        if gone:
            abort(409, "A supplier who has quoted cannot be taken off the RFQ")
        have = {s["contact_id"]: s for s in rfq["suppliers"]}
        sups = []
        for sid in want:
            if sid in have:
                sups.append(have[sid])
            else:
                v = vendor(sid)
                sups.append({"contact_id": sid, "name": v["name"], "email": v.get("email"), "warning": compliance_warning(v), "sent": None})
        if not sups:
            abort(400, "Ask at least one supplier")
        ch["suppliers"] = sups
    return jsonify(serialize(t.update("rfqs", rid, ch)))


@bp.post("/rfqs/<rid>/send")
@api("procurement")
def send_rfq(rid):
    from ..services import messaging
    rfq = load_rfq(rid, True)
    if rfq["status"] not in ("draft", "sent"):
        abort(409, "This RFQ is closed")
    body = "\n".join([f"Request for quotation {rfq['number']} — {rfq['project_name']}", f"Please quote by {rfq['due_date']}.", ""]
                     + [f"• {ln['qty']:g} {ln.get('unit') or ''} {ln['description']}" for ln in rfq["lines"]]
                     + ([f"\n{rfq['note']}"] if rfq.get("note") else []) + [f"\nRegards,\n{g.user.get('name')}\n{g.company['name']}"])
    sups = []
    for s in rfq["suppliers"]:
        c = db.contacts.find_one({"_id": oid(s["contact_id"])}) or {}
        mail = notify.deliver(g.company, c.get("email"), f"Request for quotation {rfq['number']}", body)
        wa = messaging.notify_contact(c, f"{g.company['name']}: request for quotation {rfq['number']} ({len(rfq['lines'])} item(s)), "
                                         f"please quote by {rfq['due_date']}.", "rfq", rid)
        sups.append({**s, "sent": mail, "whatsapp": wa})
    upd = t.update("rfqs", rid, {"suppliers": sups, "status": "sent", "sent_at": t.now()})
    return jsonify(serialize(upd))


def record_quote(rfq, supplier_id, d):
    if rfq["status"] not in ("draft", "sent"):
        abort(409, "This RFQ is closed")
    sup = next((s for s in rfq["suppliers"] if s["contact_id"] == supplier_id), None) or abort(400, "This supplier was not asked")
    ids = {ln["id"] for ln in rfq["lines"]}
    rates = {}
    for r in d.get("lines") or []:
        if r.get("line_id") in ids and r.get("rate") not in (None, ""):
            rates[r["line_id"]] = num(r["rate"], "Rate")
    if not rates:
        abort(400, "Give a rate for at least one line")
    if d.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
        abort(400, "Upload the quote first")
    q = {"id": t.sid(), "supplier_id": supplier_id, "supplier_name": sup["name"], "rates": rates,
         "tax_pct": num(d.get("tax_pct"), "Tax %") if d.get("tax_pct") not in (None, "") else float(g.company.get("tax_rate") or 0),
         "delivery_days": int(d.get("delivery_days") or 0), "validity": a_date(d.get("validity"), "Valid until", required=False),
         "terms": (d.get("terms") or "").strip()[:500] or None, "file_key": d.get("file_key"), "late": sales.today() > rfq["due_date"],
         "by": g.user.get("name"), "at": t.now()}
    quotes = [x for x in rfq["quotes"] if x["supplier_id"] != supplier_id] + [q]
    return t.update("rfqs", str(rfq["_id"]), {"quotes": quotes})


@bp.post("/rfqs/<rid>/quotes")
@api("procurement")
def add_quote(rid):
    rfq = load_rfq(rid, True)
    d = request.get_json(force=True) or {}
    return jsonify(serialize(record_quote(rfq, d.get("supplier_id"), d))), 201


def quote_total(rfq, q, line_ids=None):
    sub = sum(q["rates"][ln["id"]] * ln["qty"] for ln in rfq["lines"] if ln["id"] in q["rates"] and (line_ids is None or ln["id"] in line_ids))
    return r2(sub), r2(sub * q["tax_pct"] / 100)


@bp.get("/rfqs/<rid>/compare")
@api("procurement", write=False)
def compare(rid):
    rfq = load_rfq(rid)
    lines = []
    for ln in rfq["lines"]:
        rate = db.rate_library.find_one({"_id": oid(ln["rate_id"])}) if ln.get("rate_id") else None
        offers = {q["supplier_id"]: q["rates"][ln["id"]] for q in rfq["quotes"] if ln["id"] in q["rates"]}
        best = min(offers.values()) if offers else None
        lines.append({**ln, "library_rate": (rate or {}).get("rate"), "last_actual": (rate or {}).get("last_actual"),
                      "offers": [{"supplier_id": s, "rate": v, "amount": r2(v * ln["qty"]), "lowest": v == best} for s, v in offers.items()]})
    totals = []
    complete = [q for q in rfq["quotes"] if len(q["rates"]) == len(rfq["lines"])]
    for q in rfq["quotes"]:
        sub, tax = quote_total(rfq, q)
        totals.append({"supplier_id": q["supplier_id"], "supplier_name": q["supplier_name"], "subtotal": sub, "tax": tax, "total": r2(sub + tax),
                       "complete": q in complete, "delivery_days": q["delivery_days"], "validity": q.get("validity"), "terms": q.get("terms"),
                       "late": q.get("late"), "file_key": q.get("file_key")})
    lowest = min((x["subtotal"] for x in totals if x["complete"]), default=None)
    for x in totals:
        x["lowest"] = x["complete"] and x["subtotal"] == lowest
    return jsonify(serialize({"rfq": rfq, "lines": lines, "quotes": totals}))


@bp.post("/rfqs/<rid>/award")
@api("procurement")
def award(rid):
    """Award a whole quote ({supplier_id}) or per line ({lines: [{line_id, supplier_id}]}): one draft PO per supplier.
    Choosing anything dearer than the lowest complete quote needs a reason."""
    rfq = load_rfq(rid, True)
    p = project(rfq["project_id"], True)
    if rfq["status"] not in ("draft", "sent"):
        abort(409, "Already awarded or closed")
    d = request.get_json(force=True) or {}
    quotes = {q["supplier_id"]: q for q in rfq["quotes"]}
    if d.get("supplier_id"):
        q = quotes.get(d["supplier_id"]) or abort(400, "That supplier has not quoted")
        picks = {ln["id"]: d["supplier_id"] for ln in rfq["lines"] if ln["id"] in q["rates"]}
    else:
        picks = {x["line_id"]: x["supplier_id"] for x in d.get("lines") or [] if x.get("supplier_id") in quotes
                 and x["line_id"] in quotes[x["supplier_id"]]["rates"]}
    if not picks:
        abort(400, "Choose what to award")
    chosen = sum(quotes[s]["rates"][lid] * next(ln["qty"] for ln in rfq["lines"] if ln["id"] == lid) for lid, s in picks.items())
    cheapest = sum(min(q["rates"][lid] for q in rfq["quotes"] if lid in q["rates"]) * next(ln["qty"] for ln in rfq["lines"] if ln["id"] == lid)
                   for lid in picks)
    reason = (d.get("reason") or "").strip()
    if chosen > cheapest + 0.01 and not reason:
        abort(400, f"The award costs {money_text(chosen - cheapest)} more than the lowest prices: say why (delivery, quality, terms)")
    pos = []
    for sid in dict.fromkeys(picks.values()):
        q = quotes[sid]
        lines = [{"description": ln["description"], "rate_id": ln.get("rate_id"), "stage_id": ln["stage_id"], "qty": ln["qty"],
                  "unit": ln.get("unit"), "unit_cost": q["rates"][ln["id"]], "tax_pct": q["tax_pct"], "pr_id": ln["pr_id"], "pr_line_id": ln["pr_line_id"]}
                 for ln in rfq["lines"] if picks.get(ln["id"]) == sid]
        pos.append(new_po(p, vendor(sid), lines, {"source": "rfq", "rfq_id": rid, "rfq_number": rfq["number"], "award_reason": reason or None,
                                                  "expected_date": a_date(d.get("expected_date"), "Expected", required=False),
                                                  "terms": q.get("terms")}))
    t.update("rfqs", rid, {"status": "awarded", "awarded": {"by": g.user.get("name"), "at": t.now(), "reason": reason or None,
                                                             "po_ids": [str(x["_id"]) for x in pos]}})
    return jsonify(serialize([present_po(x) for x in pos])), 201


# ---------------- purchase orders ----------------
def clean_po_lines(rows, p):
    out = []
    for r in (rows or [])[:80]:
        desc = (r.get("description") or "").strip()[:200] or abort(400, "Each line needs a description")
        st = stage_of(p, r.get("stage_id"))
        qty = num(r.get("qty"), f"Quantity of {desc}", required=True, positive=True)
        unit_cost = num(r.get("unit_cost"), f"Rate of {desc}", required=True)
        tax_pct = num(r.get("tax_pct"), "Tax %") if r.get("tax_pct") not in (None, "") else float(g.company.get("tax_rate") or 0)
        cost = r2(qty * unit_cost)
        out.append({"id": r.get("id") or t.sid(), "description": desc, "rate_id": r.get("rate_id"), "stage_id": st["id"], "stage_name": st["name"],
                    "qty": qty, "unit": (r.get("unit") or "").strip()[:20] or None, "unit_cost": unit_cost, "tax_pct": tax_pct,
                    "cost": cost, "tax": r2(cost * tax_pct / 100), "selection_id": r.get("selection_id"), "pr_id": r.get("pr_id"),
                    "pr_line_id": r.get("pr_line_id"), "received_qty": r.get("received_qty", 0), "accepted_qty": r.get("accepted_qty", 0),
                    "billed_qty": r.get("billed_qty", 0), "short_closed_qty": r.get("short_closed_qty", 0)})
    if not out:
        abort(400, "Add at least one line")
    return out


def po_totals(lines):
    cost = r2(sum(x["cost"] for x in lines))
    tax = r2(sum(x["tax"] for x in lines))
    return {"cost": cost, "tax": tax, "total": r2(cost + tax)}


def new_po(p, v, lines, extra):
    lines = clean_po_lines(lines, p)
    po = t.insert("purchase_orders", {"number": None, "project_id": str(p["_id"]), "project_name": p["name"], "project_code": p.get("code"),
                                      "vendor_id": str(v["_id"]), "vendor_name": v["name"], "vendor_email": v.get("email"),
                                      "vendor_warning": compliance_warning(v), "lines": lines, **po_totals(lines),
                                      "delivery_address": ((p.get("site") or {}).get("line1") or None), "expected_date": None,
                                      "terms": None, "source": "direct", "direct_reason": None, "status": "draft", "approval": None,
                                      "revisions": [], "acknowledged": None, "vendor_updates": [], "created_by_name": g.user.get("name"),
                                      **{k: v_ for k, v_ in extra.items()}})
    for ln in lines:
        if ln.get("pr_id"):
            db.purchase_requests.update_one({"_id": oid(ln["pr_id"]), "lines.id": ln["pr_line_id"]},
                                            {"$set": {"lines.$.status": "ordered", "lines.$.po_id": str(po["_id"])}})
            pr = db.purchase_requests.find_one({"_id": oid(ln["pr_id"])})
            if pr and all(x["status"] == "ordered" for x in pr["lines"]):
                db.purchase_requests.update_one({"_id": pr["_id"]}, {"$set": {"status": "ordered"}})
    return po


def present_po(po):
    data = t.out(serialize(po))  # unit_cost / cost are cost fields: the Site Supervisor sees items and quantities only
    if g.hide_costs:
        for k in ("total", "tax"):
            data.pop(k, None)
        for ln in data.get("lines", []):
            ln.pop("tax", None)
    return data


def load_po(poid, write=False):
    po = t.get("purchase_orders", poid)
    p = project(po["project_id"], write)
    return po, p


@bp.post("/purchase-orders")
@api("procurement")
def add_po():
    d = request.get_json(force=True) or {}
    p = project(d.get("project_id"), write=True)
    po = new_po(p, vendor(d.get("vendor_id")), d.get("lines"), {
        "expected_date": a_date(d.get("expected_date"), "Expected", required=False), "terms": (d.get("terms") or "").strip()[:1000] or None,
        "delivery_address": (d.get("delivery_address") or "").strip()[:300] or ((p.get("site") or {}).get("line1") or None),
        "direct_reason": (d.get("direct_reason") or "").strip()[:300] or None})
    return jsonify(present_po(po)), 201


@bp.get("/purchase-orders")
@api(None)
def list_pos():
    if not can("procurement") and g.role != "site":
        abort(403, "Your role cannot view purchase orders")
    q = scoped({})
    for k in ("status", "project_id", "vendor_id"):
        if request.args.get(k):
            q[k] = {"$in": request.args[k].split(",")} if k == "status" else request.args[k]
    if g.role == "site":
        q["status"] = {"$in": budget.PO_OPEN}
    return jsonify([present_po(x) for x in t.find("purchase_orders", q, sort=[("created_at", -1)], limit=500)])


@bp.get("/purchase-orders/<poid>")
@api(None)
def get_po(poid):
    po, p = load_po(poid)
    data = present_po(po)
    if not g.hide_costs:
        from .proposals import branding
        data["company"] = branding(g.company)
        data["client_receipts"] = round(sum(r["amount"] for r in db.receipts.find({"company_id": g.cid, "project_id": po["project_id"],
                                                                                    "status": "received"})), 2)  # E4 hint
    data["receipts"] = serialize(t.find("goods_receipts", {"po_id": poid}, sort=[("created_at", 1)]))
    return jsonify(data)


@bp.put("/purchase-orders/<poid>")
@api("procurement")
def edit_po(poid):
    po, p = load_po(poid, True)
    if po["status"] not in ("draft", "rejected"):
        abort(409, "An approved PO is changed by an amendment")
    d = request.get_json(force=True) or {}
    ch = {"status": "draft"}
    if "lines" in d:
        ch["lines"] = clean_po_lines(d["lines"], p)
        ch.update(po_totals(ch["lines"]))
    if "vendor_id" in d:
        v = vendor(d["vendor_id"])
        ch.update(vendor_id=str(v["_id"]), vendor_name=v["name"], vendor_email=v.get("email"), vendor_warning=compliance_warning(v))
    for k in ("terms", "delivery_address", "direct_reason"):
        if k in d:
            ch[k] = (d[k] or "").strip()[:1000] or None
    if "expected_date" in d:
        ch["expected_date"] = a_date(d["expected_date"], "Expected", required=False)
    return jsonify(present_po(t.update("purchase_orders", poid, ch)))


@bp.delete("/purchase-orders/<poid>")
@api("procurement")
def delete_po(poid):
    po, _ = load_po(poid, True)
    if po["status"] not in ("draft", "rejected"):
        abort(409, "An approved PO is cancelled, not deleted")
    for ln in po["lines"]:
        if ln.get("pr_id"):
            db.purchase_requests.update_one({"_id": oid(ln["pr_id"]), "lines.id": ln["pr_line_id"]}, {"$set": {"lines.$.status": "open", "lines.$.po_id": None}})
            db.purchase_requests.update_one({"_id": oid(ln["pr_id"]), "status": "ordered"}, {"$set": {"status": "open"}})
        if ln.get("selection_id"):
            db.selections.update_one({"_id": oid(ln["selection_id"])}, {"$set": {"po_id": None, "po_draft": None}})
    t.delete("purchase_orders", poid)
    return jsonify({"ok": True})


def budget_check(po, p, exclude=True):
    """-> {stage_id: overspend} for the stages this PO takes over budget."""
    by_stage = {}
    for ln in po["lines"]:
        left = max(0.0, ln["qty"] - ln.get("billed_qty", 0) - ln.get("short_closed_qty", 0)) * ln["unit_cost"]
        by_stage[ln["stage_id"]] = by_stage.get(ln["stage_id"], 0) + left
    out = {}
    for sid, amount in by_stage.items():
        over = budget.over_budget_po(p, sid, amount, str(po["_id"]) if exclude else None)
        if over:
            out[sid] = over
    return out


def is_project_approver(p):
    from .finance import is_approver
    return is_approver(p)


def approve_now(po, p, by_reason=None):
    ch = {"status": "approved", "approval": {**(po.get("approval") or {}), "status": "approved", "by": g.user.get("name"), "by_id": g.uid,
                                             "at": t.now(), "overspend_reason": by_reason}}
    if not po.get("number"):
        ch["number"] = t.next_number("PO", "PO")
    upd = t.update("purchase_orders", str(po["_id"]), ch)
    ev.log(po["project_id"], "cost", f"Purchase order {upd['number']} approved: {upd['vendor_name']}, {money_text(upd['total'])}")
    return upd


@bp.post("/purchase-orders/<poid>/submit")
@api("procurement")
def submit_po(poid):
    """Within the limit and the stage budgets: approved at once. Above the limit: an Owner. Over budget: a manager on
    the project, with a reason (decision H-1)."""
    po, p = load_po(poid, True)
    if po["status"] not in ("draft", "rejected"):
        abort(409, "Already submitted")
    s = fin_settings()
    limit = s["po_approval_limit"]
    if po["source"] == "direct" and po["cost"] > limit and not po.get("direct_reason"):  # the limit is on the value before tax
        abort(400, f"A direct PO above {money_text(limit)} (no RFQ) needs a reason")
    over = budget_check(po, p)
    needs = []
    if po["cost"] > limit:
        needs.append("owner")
    if over:
        needs.append("budget")
    if not needs:
        return jsonify(present_po(approve_now(po, p)))
    if g.role == "owner" and not over:
        return jsonify(present_po(approve_now(po, p)))
    upd = t.update("purchase_orders", poid, {"status": "waiting_approval", "approval": {
        "status": "pending", "needs": needs, "over_budget": {k: v for k, v in over.items()}, "requested_by": g.user.get("name"),
        "requested_by_id": g.uid, "requested_at": t.now()}})
    who = ev.owners() if "owner" in needs else []
    if "budget" in needs:
        who += ev.managers(p) + ev.owners()
    notify.send("po_approval", list(dict.fromkeys(who)), f"PO for {po['vendor_name']} on {p['name']}: {money_text(po['total'])}"
                + (" — over the stage budget" if over else " — above the approval limit"), f"/app/purchase-orders/{poid}",
                project_id=po["project_id"])
    return jsonify(present_po(upd))


@bp.post("/purchase-orders/<poid>/approve")
@api("procurement")
def approve_po(poid):
    po, p = load_po(poid, True)
    if po["status"] != "waiting_approval":
        abort(409, "This PO is not waiting for approval")
    needs = (po.get("approval") or {}).get("needs", [])
    if "owner" in needs and g.role != "owner":
        abort(403, "Above the approval limit: an Owner approves")
    reason = (request.get_json(force=True) or {}).get("overspend_reason")
    if "budget" in needs:
        if not is_project_approver(p):
            abort(403, "Over the stage budget: an Owner or the project's Project Manager approves")
        if budget_check(po, p) and reason not in OVERSPEND_REASONS:
            abort(400, f"This PO takes a stage over its budget: say why ({', '.join(OVERSPEND_REASONS.values())})")
    upd = approve_now(po, p, reason)
    notify.send("po_decided", [po["approval"].get("requested_by_id")], f"PO {upd['number']} for {po['vendor_name']} approved",
                f"/app/purchase-orders/{poid}", project_id=po["project_id"])
    return jsonify(present_po(upd))


@bp.post("/purchase-orders/<poid>/reject")
@api("procurement")
def reject_po(poid):
    po, p = load_po(poid, True)
    if po["status"] != "waiting_approval":
        abort(409, "This PO is not waiting for approval")
    if not (g.role == "owner" or is_project_approver(p)):
        abort(403, "Only an approver can reject")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why")
    upd = t.update("purchase_orders", poid, {"status": "rejected", "approval": {**po["approval"], "status": "rejected", "reason": reason[:300],
                                                                                 "by": g.user.get("name"), "at": t.now()}})
    notify.send("po_decided", [po["approval"].get("requested_by_id")], f"PO for {po['vendor_name']} rejected: {reason}",
                f"/app/purchase-orders/{poid}", project_id=po["project_id"])
    return jsonify(present_po(upd))


def po_text(po):
    lines = [f"Purchase order {po['number']}" + (f" (revision {len(po['revisions'])})" if po.get("revisions") else ""),
             f"Project: {po['project_name']}", f"Deliver to: {po.get('delivery_address') or '—'}" + (f" by {po['expected_date']}" if po.get("expected_date") else ""), ""]
    lines += [f"• {ln['qty']:g} {ln.get('unit') or ''} {ln['description']} @ {money_text(ln['unit_cost'])} = {money_text(ln['cost'])}" for ln in po["lines"]]
    lines += ["", f"Amount {money_text(po['cost'])} + tax {money_text(po['tax'])} = {money_text(po['total'])}"]
    if po.get("terms"):
        lines += ["", po["terms"]]
    return "\n".join(lines) + f"\n\nPlease acknowledge this order.\n{g.user.get('name')}, {g.company['name']}"


@bp.post("/purchase-orders/<poid>/send")
@api("procurement")
def send_po(poid):
    from ..services import messaging
    po, p = load_po(poid, True)
    if po["status"] not in ("approved", "sent", "acknowledged", "part_received"):
        abort(409, "Approve the PO before sending it")
    d = request.get_json(force=True) or {}
    mail = notify.deliver(g.company, po.get("vendor_email"), f"Purchase order {po['number']} from {g.company['name']}", po_text(po)) \
        if d.get("email", True) else None
    c = db.contacts.find_one({"_id": oid(po["vendor_id"])}) or {}
    wa = messaging.notify_contact(c, f"{g.company['name']}: purchase order {po['number']} for {po['project_name']}, "
                                     f"{money_text(po['total'])}. Please acknowledge it in your portal.", "po", poid) if d.get("whatsapp") else None
    upd = t.update("purchase_orders", poid, {"status": "sent" if po["status"] == "approved" else po["status"], "sent_at": t.now(),
                                             "sent": {"email": mail, "whatsapp": wa, "by": g.user.get("name"), "at": t.now()}})
    for ln in po["lines"]:  # F: a selection is ordered once its PO goes to the supplier
        if ln.get("selection_id"):
            db.selections.update_one({"_id": oid(ln["selection_id"])}, {"$set": {"po_id": poid, "po_number": po["number"],
                                                                                 "po_expected": po.get("expected_date")}})
    ev.log(po["project_id"], "cost", f"Purchase order {po['number']} sent to {po['vendor_name']}" + (f" — email {mail}" if mail else ""))
    return jsonify(present_po(upd))


def acknowledge_po(po, ack):
    upd = t.update("purchase_orders", str(po["_id"]), {"acknowledged": {**ack, "recorded_by": g.user.get("name"), "at": t.now()},
                                                       "status": "acknowledged" if po["status"] == "sent" else po["status"]})
    notify.send("po_acknowledged", notify.role_users("procurement"), f"{po['vendor_name']} acknowledged {po['number']}",
                f"/app/purchase-orders/{po['_id']}", project_id=po["project_id"])
    return upd


@bp.post("/purchase-orders/<poid>/acknowledge")
@api("procurement")
def staff_ack(poid):
    po, _ = load_po(poid, True)
    if po["status"] != "sent":
        abort(409, "Only a sent PO is acknowledged")
    d = request.get_json(force=True) or {}
    if d.get("method") not in SIGNOFF_METHODS:
        abort(400, f"How did they acknowledge? {', '.join(SIGNOFF_METHODS)}")
    name = (d.get("name") or "").strip() or abort(400, "Who acknowledged it?")
    return jsonify(present_po(acknowledge_po(po, {"name": name[:120], "method": d["method"], "date": a_date(d.get("date") or sales.today(), "Date")})))


@bp.post("/purchase-orders/<poid>/amend")
@api("procurement")
def amend_po(poid):
    """Change an approved PO: a numbered revision with what changed and why. An increase is approved again."""
    po, p = load_po(poid, True)
    if po["status"] not in ("approved", "sent", "acknowledged", "part_received"):
        abort(409, "Edit a draft directly; a closed or cancelled PO is not amended")
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip() or abort(400, "Say why the order changes")
    old = {ln["id"]: ln for ln in po["lines"]}
    lines = clean_po_lines([{**old.get(r.get("id"), {}), **r} for r in d.get("lines") or []], p)
    for ln in lines:
        prev = old.get(ln["id"])
        if prev and ln["qty"] < max(prev.get("received_qty", 0), prev.get("billed_qty", 0)):
            abort(400, f"{ln['description']}: already received or billed {max(prev.get('received_qty', 0), prev.get('billed_qty', 0)):g}")
    gone = [x for x in old.values() if x["id"] not in {ln["id"] for ln in lines} and (x.get("received_qty") or x.get("billed_qty"))]
    if gone:
        abort(400, f"{gone[0]['description']} was already received; keep it on the order")
    tt = po_totals(lines)
    rev = {"rev": len(po.get("revisions", [])) + 1, "reason": reason[:300], "by": g.user.get("name"), "at": t.now(),
           "old_total": po["total"], "new_total": tt["total"]}
    ch = {"lines": lines, **tt, "revisions": po.get("revisions", []) + [rev]}
    if tt["total"] > po["total"] + 0.01:
        ch.update(status="draft", sent_before=True)  # an increase is approved again (submit), then sent again
    upd = t.update("purchase_orders", poid, ch)
    ev.log(po["project_id"], "cost", f"PO {po['number']} amended (rev {rev['rev']}): {money_text(po['total'])} → {money_text(tt['total'])} — {reason}")
    return jsonify(present_po(upd))


@bp.post("/purchase-orders/<poid>/cancel")
@api("procurement")
def cancel_po(poid):
    po, _ = load_po(poid, True)
    if po["status"] in ("cancelled", "closed"):
        abort(409, "Already closed")
    if any(ln.get("received_qty") or ln.get("billed_qty") for ln in po["lines"]):
        abort(409, "Goods were received or billed on this PO; short-close what is left instead")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the order is cancelled")
    upd = t.update("purchase_orders", poid, {"status": "cancelled", "cancel_reason": reason[:300], "cancelled_at": t.now()})
    for ln in po["lines"]:
        if ln.get("pr_id"):
            db.purchase_requests.update_one({"_id": oid(ln["pr_id"]), "lines.id": ln["pr_line_id"]}, {"$set": {"lines.$.status": "open", "lines.$.po_id": None}})
            db.purchase_requests.update_one({"_id": oid(ln["pr_id"]), "status": "ordered"}, {"$set": {"status": "open"}})
    ev.log(po["project_id"], "cost", f"PO {po.get('number') or 'draft'} cancelled: {reason}")
    return jsonify(present_po(upd))


# ---------------- selections ordered through procurement (F -> H) ----------------
def order_selection(s, p, opt):
    """The client's chosen option goes on the supplier's open draft PO for this project, or becomes a purchase request
    when it has no supplier. No cost is recorded here: the bill becomes the cost (block 3)."""
    line = {"description": f"{s['item']}: {opt['name']}"[:200], "rate_id": opt.get("rate_id"), "stage_id": s["stage_id"], "qty": opt.get("qty") or 1,
            "unit": opt.get("unit"), "unit_cost": opt.get("unit_cost") or 0, "selection_id": str(s["_id"])}
    if opt.get("supplier_id"):
        draft = db.purchase_orders.find_one({"company_id": g.cid, "project_id": s["project_id"], "vendor_id": opt["supplier_id"],
                                             "status": "draft", "source": "selection"})
        if draft:
            lines = clean_po_lines(draft["lines"] + [line], p)
            t.update("purchase_orders", str(draft["_id"]), {"lines": lines, **po_totals(lines)})
            po = draft
        else:
            po = new_po(p, vendor(opt["supplier_id"]), [line], {"source": "selection"})
        return {"po_id": str(po["_id"]), "po_draft": True}
    pr = new_request(p, {"stage_id": s["stage_id"], "selection_id": str(s["_id"]),
                         "lines": [{"description": line["description"], "qty": line["qty"], "unit": line["unit"], "rate_id": line["rate_id"]}],
                         "note": f"Selection: {s['item']} — the client chose {opt['name']}"}, "selection")
    return {"pr_id": str(pr["_id"]), "pr_number": pr["number"]}


# ---------------- block 3: goods received, returns ----------------
REJECT_REASONS = ["Damaged", "Wrong item", "Short", "Quality"]


def po_status_after_receipt(po):
    lines = po["lines"]
    if all(ln.get("accepted_qty", 0) + ln.get("short_closed_qty", 0) >= ln["qty"] - 1e-9 for ln in lines):
        return "received"
    if any(ln.get("received_qty", 0) for ln in lines):
        return "part_received"
    return po["status"]


@bp.post("/purchase-orders/<poid>/receipts")
@api(None)
def receive(poid):
    """Goods received on site or at the office: received, accepted and rejected qty per line, photos, challan no.
    Procurement / PM / Owner, or a Site Supervisor on the project (who never sees prices)."""
    po, p = load_po(poid)
    if not (can("procurement", True) or site_member(p)):
        abort(403, "Your role cannot record deliveries")
    if po["status"] not in ("approved", "sent", "acknowledged", "part_received"):
        abort(409, "Only an approved, open PO receives goods")
    d = request.get_json(force=True) or {}
    pct = fin_settings()["over_receipt_pct"]
    by_id = {ln["id"]: ln for ln in po["lines"]}
    rows = []
    for r in d.get("lines") or []:
        ln = by_id.get(r.get("line_id")) or abort(400, "Choose lines of this PO")
        got = num(r.get("received"), f"Received {ln['description']}", required=True)
        rejected = num(r.get("rejected"), "Rejected") or 0
        if rejected > got:
            abort(400, f"{ln['description']}: rejected is more than received")
        if rejected and r.get("reason") not in REJECT_REASONS:
            abort(400, f"Why was {ln['description']} rejected? {', '.join(REJECT_REASONS)}")
        accepted = got - rejected
        if ln.get("accepted_qty", 0) + accepted > ln["qty"] * (1 + pct / 100) + 1e-9:
            abort(400, f"{ln['description']}: {ln.get('accepted_qty', 0) + accepted:g} accepted is more than the {ln['qty']:g} ordered "
                       f"(+{pct:g}% allowed)")
        if got:
            rows.append({"line_id": ln["id"], "description": ln["description"], "unit": ln.get("unit"), "received": got, "accepted": accepted,
                         "rejected": rejected, "reason": r.get("reason") if rejected else None, "returned": 0,
                         "rate_id": ln.get("rate_id"), "unit_cost": ln.get("unit_cost")})  # Phase I: stock at site
    if not rows:
        abort(400, "Enter what was received")
    photos = []
    for key in dict.fromkeys(d.get("photos") or []):
        f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the photo first")
        photos.append({"key": key, "name": f["name"]})
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "A delivery cannot be in the future")
    from .site_plus import receiving_location  # Phase I: received at the site or into a company warehouse
    loc = receiving_location(d.get("location"))
    grn = t.insert("goods_receipts", {"number": t.next_number("GRN", "GRN"), "po_id": poid, "po_number": po["number"], "project_id": po["project_id"],
                                      "location": loc,
                                      "project_name": po["project_name"], "vendor_id": po["vendor_id"], "vendor_name": po["vendor_name"], "date": day,
                                      "lines": rows, "photos": photos, "challan": (d.get("challan") or "").strip()[:60] or None,
                                      "site_report_id": d.get("site_report_id"), "received_by": g.user.get("name"), "returns": []})
    for r in rows:
        ln = by_id[r["line_id"]]
        ln["received_qty"] = ln.get("received_qty", 0) + r["received"]
        ln["accepted_qty"] = ln.get("accepted_qty", 0) + r["accepted"]
    t.update("purchase_orders", poid, {"lines": po["lines"], "status": po_status_after_receipt(po)})
    for r in rows:  # Phase I: a selection whose PO line is fully received is delivered
        ln = by_id[r["line_id"]]
        if ln.get("selection_id") and ln.get("accepted_qty", 0) >= ln["qty"] - 1e-9:
            db.selections.update_one({"_id": oid(ln["selection_id"]), "company_id": g.cid, "status": "ordered"},
                                     {"$set": {"status": "delivered", "delivered_at": t.now(), "delivered_grn": grn["number"]},
                                      "$push": {"history": {"status": "delivered", "by": g.user.get("name"), "at": t.now(), "grn": grn["number"]}}})
    ev.log(po["project_id"], "cost", f"{grn['number']}: goods received on {po['number']} from {po['vendor_name']}"
           + (" (some rejected)" if any(r["rejected"] for r in rows) else ""))
    if any(r["rejected"] for r in rows):
        what = ", ".join(f"{r['rejected']:g} {r['description']} ({r['reason'].lower()})" for r in rows if r["rejected"])
        notify.send("goods_rejected", list(dict.fromkeys(notify.role_users("procurement") + ev.managers(p))),
                    f"{grn['number']} on {po['number']} ({po['vendor_name']}): {what}", f"/app/purchase-orders/{poid}", project_id=po["project_id"])
    return jsonify(serialize(grn)), 201


@bp.post("/goods-receipts/<gid>/reverse")
@api("procurement")
def reverse_grn(gid):
    """Phase I: a delivery recorded by mistake is reversed whole — only when nothing of it is billed, returned or used."""
    grn = t.get("goods_receipts", gid)
    po, _ = load_po(grn["po_id"], True)
    if grn.get("reversed"):
        abort(409, "Already reversed")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the delivery is reversed")
    if grn.get("returns"):
        abort(409, "Goods of this delivery were returned; it cannot be reversed")
    by_id = {ln["id"]: ln for ln in po["lines"]}
    for r in grn["lines"]:
        ln = by_id.get(r["line_id"])
        if ln and ln.get("accepted_qty", 0) - r["accepted"] < ln.get("billed_qty", 0) - 1e-9:
            abort(409, f"{r['description']} of this delivery is already billed")
    from .site_plus import loc_key, item_key, balance_of
    where = loc_key(grn)
    for r in grn["lines"]:
        have = balance_of(where, item_key(r))
        if r["accepted"] and (not have or have["balance"] < r["accepted"] - 1e-9):
            abort(409, f"{r['description']} of this delivery has been used or moved; it cannot be reversed")
    for r in grn["lines"]:
        ln = by_id.get(r["line_id"])
        if ln:
            ln["received_qty"] = max(0, ln.get("received_qty", 0) - r["received"])
            ln["accepted_qty"] = max(0, ln.get("accepted_qty", 0) - r["accepted"])
    status = po_status_after_receipt(po)
    if status == po["status"] and po["status"] in ("part_received", "received") and not any(ln.get("received_qty") for ln in po["lines"]):
        status = "acknowledged" if po.get("acknowledged") else "sent"
    t.update("purchase_orders", grn["po_id"], {"lines": po["lines"], "status": status})
    upd = t.update("goods_receipts", gid, {"reversed": {"reason": reason[:300], "by": g.user.get("name"), "at": t.now()},
                                            "lines": [{**r, "received": 0, "accepted": 0, "rejected": 0, "was": {k: r[k] for k in ("received", "accepted", "rejected")}}
                                                      for r in grn["lines"]]})
    ev.log(grn["project_id"], "cost", f"{grn['number']} reversed: {reason}")
    return jsonify(serialize(upd))


@bp.post("/goods-receipts/<gid>/return")
@api("procurement")
def return_goods(gid):
    """Goods sent back to the supplier: accepted qty drops and is never billed; the PO line is open again."""
    grn = t.get("goods_receipts", gid)
    po, _ = load_po(grn["po_id"], True)
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip() or abort(400, "Say why the goods go back")
    by_id = {ln["id"]: ln for ln in po["lines"]}
    rets = []
    for r in d.get("lines") or []:
        row = next((x for x in grn["lines"] if x["line_id"] == r.get("line_id")), None) or abort(400, "Choose lines of this receipt")
        qty = num(r.get("qty"), "Quantity", required=True, positive=True)
        ln = by_id[row["line_id"]]
        if qty > row["accepted"] - row.get("returned", 0) + 1e-9 or ln.get("accepted_qty", 0) - qty < ln.get("billed_qty", 0) - 1e-9:
            abort(400, f"{row['description']}: cannot return more than was accepted and not yet billed")
        row["returned"] = row.get("returned", 0) + qty
        ln["accepted_qty"] = ln.get("accepted_qty", 0) - qty
        rets.append({"line_id": row["line_id"], "description": row["description"], "qty": qty})
    if not rets:
        abort(400, "Choose what goes back")
    t.update("goods_receipts", gid, {"lines": grn["lines"], "returns": grn.get("returns", []) + [
        {"lines": rets, "reason": reason[:300], "by": g.user.get("name"), "at": t.now()}]})
    upd = t.update("purchase_orders", str(po["_id"]), {"lines": po["lines"], "status": po_status_after_receipt(po)})
    notify.deliver(g.company, po.get("vendor_email"), f"Return against {po['number']}",
                   "We are returning: " + ", ".join(f"{r['qty']:g} {r['description']}" for r in rets) + f".\nReason: {reason}\n\n{g.company['name']}")
    return jsonify(present_po(upd))


@bp.post("/purchase-orders/<poid>/short-close")
@api("procurement")
def short_close(poid):
    """The rest of a PO is not coming: the open value leaves the stage budget."""
    po, _ = load_po(poid, True)
    if po["status"] not in ("approved", "sent", "acknowledged", "part_received", "received"):
        abort(409, "Only an open PO is short-closed")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the rest is not coming")
    for ln in po["lines"]:
        ln["short_closed_qty"] = max(0.0, ln["qty"] - max(ln.get("accepted_qty", 0), ln.get("billed_qty", 0)))
    done = all(ln.get("billed_qty", 0) + 1e-9 >= ln.get("accepted_qty", 0) for ln in po["lines"])
    upd = t.update("purchase_orders", poid, {"lines": po["lines"], "status": "closed" if done else "received", "short_close_reason": reason[:300]})
    return jsonify(present_po(upd))


@bp.get("/goods-receipts")
@api(None)
def list_grns():
    if not can("procurement") and g.role != "site":
        abort(403, "Your role cannot view deliveries")
    q = scoped({})
    for k in ("project_id", "po_id", "date"):
        if request.args.get(k):
            q[k] = request.args[k]
    return jsonify(serialize(t.find("goods_receipts", q, sort=[("created_at", -1)], limit=300)))


# ---------------- block 3: vendor bills, three-way match, payments ----------------
def bill_writer():
    if not (can("finance", True) or can("procurement", True)):
        abort(403, "Your role cannot enter vendor bills")


def match(po, lines):
    """Per line: billed qty <= accepted and not yet billed; billed rate within the tolerance of the PO rate."""
    tol = fin_settings()["match_rate_tolerance_pct"] / 100
    by_id = {ln["id"]: ln for ln in po["lines"]}
    out = []
    for b in lines:
        ln = by_id[b["line_id"]]
        free = ln.get("accepted_qty", 0) - ln.get("billed_qty", 0)
        if b["qty"] > free + 1e-9:
            out.append(f"{ln['description']}: billed {b['qty']:g}, received and not billed {free:g}")
        if b["rate"] > ln["unit_cost"] * (1 + tol) + 1e-9:
            out.append(f"{ln['description']}: rate {money_text(b['rate'])} against {money_text(ln['unit_cost'])} on the PO")
    return out


def clean_bill(d, po):
    by_id = {ln["id"]: ln for ln in po["lines"]}
    lines = []
    for r in d.get("lines") or []:
        ln = by_id.get(r.get("line_id")) or abort(400, "Choose lines of the PO")
        qty = num(r.get("qty"), f"Quantity of {ln['description']}", required=True, positive=True)
        rate = num(r.get("rate"), f"Rate of {ln['description']}") if r.get("rate") not in (None, "") else ln["unit_cost"]
        tax_pct = num(r.get("tax_pct"), "Tax %") if r.get("tax_pct") not in (None, "") else ln["tax_pct"]
        amt = r2(qty * rate)
        lines.append({"line_id": ln["id"], "description": ln["description"], "stage_id": ln["stage_id"], "stage_name": ln["stage_name"],
                      "qty": qty, "rate": rate, "amount": amt, "tax_pct": tax_pct, "tax": r2(amt * tax_pct / 100), "rate_id": ln.get("rate_id")})
    if not lines:
        abort(400, "Add the billed lines")
    return lines


def create_bill(po, d, source="staff"):
    no = (d.get("bill_no") or "").strip()[:40] or abort(400, "Enter the supplier's bill number")
    if db.vendor_bills.find_one({"company_id": g.cid, "vendor_id": po["vendor_id"], "bill_no": no, "status": {"$ne": "void"}}, {"_id": 1}):
        abort(409, f"Bill {no} from {po['vendor_name']} is already entered")
    lines = clean_bill(d, po)
    sub, tax = r2(sum(x["amount"] for x in lines)), r2(sum(x["tax"] for x in lines))
    expected = r2(sum(x["qty"] * next(ln["unit_cost"] for ln in po["lines"] if ln["id"] == x["line_id"]) for x in lines))
    problems = match(po, lines)
    if not problems and abs(sub - expected) > fin_settings()["match_amount_tolerance"] + 1e-9:
        problems.append(f"Bill amount {money_text(sub)} against {money_text(expected)} on the PO")
    if d.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
        abort(400, "Upload the bill first")
    status = "draft" if source == "portal" else ("on_hold" if problems else "matched")
    bill = t.insert("vendor_bills", {"vendor_id": po["vendor_id"], "vendor_name": po["vendor_name"], "bill_no": no,
                                     "date": a_date(d.get("date") or sales.today(), "Bill date"),
                                     "due_date": a_date(d.get("due_date") or sales.today(), "Due date"), "po_id": str(po["_id"]),
                                     "po_number": po["number"], "project_id": po["project_id"], "project_name": po["project_name"],
                                     "lines": lines, "amount": sub, "tax": tax, "total": r2(sub + tax), "paid": 0, "file_key": d.get("file_key"),
                                     "problems": problems, "status": status, "cost_ids": [], "entered_by": g.user.get("name"), "source": source})
    if status == "on_hold":
        notify.send("bill_on_hold", list(dict.fromkeys(notify.role_users("accounts") + ev.owners())),
                    f"Bill {no} from {po['vendor_name']} on {po['number']} does not match: {problems[0]}", "/app/procurement?tab=bills",
                    project_id=po["project_id"])
    return bill


@bp.post("/vendor-bills")
@api(None)
def add_bill():
    bill_writer()
    d = request.get_json(force=True) or {}
    po, _ = load_po(d.get("po_id"))
    if po["status"] in ("draft", "waiting_approval", "rejected", "cancelled"):
        abort(409, "Bill an approved PO")
    return jsonify(serialize(create_bill(po, d))), 201


@bp.post("/vendor-bills/<bid>/check")
@api(None)
def check_bill(bid):
    """A draft bill (uploaded by the supplier in the portal) checked by staff: matched or on hold."""
    bill_writer()
    bill = t.get("vendor_bills", bid)
    po, _ = load_po(bill["po_id"])
    if bill["status"] != "draft":
        abort(409, "Only a draft bill is checked")
    problems = match(po, bill["lines"])
    return jsonify(serialize(t.update("vendor_bills", bid, {"problems": problems, "status": "on_hold" if problems else "matched"})))


def post_costs(bill, po, p, approved):
    """One cost per stage of the bill (Material, or Subcontract for subcontractor / contractor vendors)."""
    from .finance import learn, submit
    v = db.contacts.find_one({"_id": oid(bill["vendor_id"])}) or {}
    category = "Subcontract" if set(v.get("types") or []) & {"subcontractor", "contractor"} else "Material"
    stages = {}
    for b in bill["lines"]:
        stages.setdefault(b["stage_id"], []).append(b)
    ids = []
    for sid, rows in stages.items():
        amt, tax = r2(sum(x["amount"] for x in rows)), r2(sum(x["tax"] for x in rows))
        one = rows[0] if len(rows) == 1 else None
        c = t.insert("costs", {"project_id": bill["project_id"], "project_name": p["name"], "project_code": p.get("code"), "stage_id": sid,
                               "stage_name": rows[0]["stage_name"], "category": category, "vendor_id": bill["vendor_id"], "vendor_name": bill["vendor_name"],
                               "date": bill["date"], "description": (f"{bill['bill_no']} ({po['number']}): " + ", ".join(x["description"] for x in rows))[:300],
                               "amount": amt, "tax": tax, "total": r2(amt + tax), "qty": one and one["qty"], "unit": None,
                               "rate_id": one and one.get("rate_id"), "rate_name": None, "bill_no": bill["bill_no"], "files": [], "kind": "cost",
                               "created_by": g.uid, "created_by_name": g.user.get("name"), "po_id": str(po["_id"]), "bill_id": str(bill["_id"]),
                               "status": "draft"})
        if approved:  # the PO was approved against the budget: a matched bill needs no second budget question (H2)
            c = t.update("costs", str(c["_id"]), {"status": "approved", "approved_by": "Matched to " + po["number"], "decided_at": t.now(),
                                                  "submitted_at": t.now(), "over_budget": 0})
            budget.recalc_stage(t.get("projects", bill["project_id"]), sid)
            learn(c)
        else:
            submit(c, p)
        ids.append(str(c["_id"]))
    return ids


def apply_bill(bill, po, p, approved):
    by_id = {ln["id"]: ln for ln in po["lines"]}
    for b in bill["lines"]:
        by_id[b["line_id"]]["billed_qty"] = by_id[b["line_id"]].get("billed_qty", 0) + b["qty"]
    st = po["status"]
    if st == "received" and all(ln.get("billed_qty", 0) + ln.get("short_closed_qty", 0) >= ln["qty"] - 1e-9 for ln in po["lines"]):
        st = "closed"
    t.update("purchase_orders", str(po["_id"]), {"lines": po["lines"], "status": st})
    ids = post_costs(bill, po, p, approved)
    return t.update("vendor_bills", str(bill["_id"]), {"status": "approved", "cost_ids": ids, "approved_by": g.user.get("name"), "approved_at": t.now()})


@bp.post("/vendor-bills/<bid>/approve")
@api(None)
def approve_bill(bid):
    bill_writer()
    bill = t.get("vendor_bills", bid)
    po, p = load_po(bill["po_id"])
    if bill["status"] != "matched":
        abort(409, "Only a matched bill is approved here; a mismatch needs an override")
    problems = match(po, bill["lines"])  # something may have changed since it was entered
    if problems:
        t.update("vendor_bills", bid, {"status": "on_hold", "problems": problems})
        abort(409, f"No longer matches: {problems[0]}")
    return jsonify(serialize(apply_bill(bill, po, p, True)))


@bp.post("/vendor-bills/<bid>/override")
@api(None)
def override_bill(bid):
    """A mismatched bill accepted anyway (Owner or Accounts, with a reason): its cost goes through the usual approval."""
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can accept a bill that does not match")
    bill = t.get("vendor_bills", bid)
    po, p = load_po(bill["po_id"])
    if bill["status"] != "on_hold":
        abort(409, "This bill is not on hold")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the bill is accepted")
    bill = t.update("vendor_bills", bid, {"override": {"reason": reason[:300], "by": g.user.get("name"), "at": t.now()}})
    return jsonify(serialize(apply_bill(bill, po, p, False)))


@bp.post("/vendor-bills/<bid>/void")
@api(None)
def void_bill(bid):
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void a bill")
    bill = t.get("vendor_bills", bid)
    po, _ = load_po(bill["po_id"])
    if bill["status"] == "void":
        abort(409, "Already void")
    if bill.get("paid"):
        abort(409, "Payments were recorded against this bill; void them first")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the bill is void")
    if bill["status"] == "approved":
        by_id = {ln["id"]: ln for ln in po["lines"]}
        for b in bill["lines"]:
            by_id[b["line_id"]]["billed_qty"] = max(0.0, by_id[b["line_id"]].get("billed_qty", 0) - b["qty"])
        t.update("purchase_orders", str(po["_id"]), {"lines": po["lines"], "status": "received" if po["status"] == "closed" else po["status"]})
        for cid_ in bill.get("cost_ids", []):  # voiding the bill voids its cost (H2)
            c = db.costs.find_one({"_id": oid(cid_)})
            if c and c["status"] != "void":
                db.costs.update_one({"_id": c["_id"]}, {"$set": {"status": "void", "void_reason": f"Bill {bill['bill_no']} void: {reason}"[:300]}})
                budget.recalc_stage(t.get("projects", c["project_id"]), c["stage_id"])
    return jsonify(serialize(t.update("vendor_bills", bid, {"status": "void", "void_reason": reason[:300]})))


def bill_balance(b):
    return r2(b["total"] - b.get("paid", 0))


@bp.get("/vendor-bills")
@api(None)
def list_bills():
    if not (can("finance") or can("procurement")):
        abort(403, "Your role cannot view vendor bills")
    q = scoped({})
    for k in ("status", "vendor_id", "project_id", "po_id"):
        if request.args.get(k):
            q[k] = {"$in": request.args[k].split(",")} if k == "status" else request.args[k]
    return jsonify([{**serialize(b), "balance": bill_balance(b)} for b in t.find("vendor_bills", q, sort=[("created_at", -1)], limit=500)])


@bp.post("/vendor-payments")
@api("finance")
def pay_vendor():
    """A payment made to a supplier outside the CRM, recorded against their approved bills."""
    from ..services.defaults import PAYMENT_MODES
    d = request.get_json(force=True) or {}
    if d.get("mode") not in PAYMENT_MODES:
        abort(400, f"Mode must be one of: {', '.join(PAYMENT_MODES)}")
    amount = r2(num(d.get("amount"), "Amount", required=True, positive=True))
    if d["mode"] != "Cash" and not (d.get("reference") or "").strip():
        abort(400, "Enter the transaction / cheque reference")
    allocs = []
    for a in d.get("allocations") or []:
        b = db.vendor_bills.find_one({"_id": oid(a.get("bill_id")), "company_id": g.cid}) if len(str(a.get("bill_id"))) == 24 else None
        if not b or b["status"] not in ("approved", "part_paid"):
            abort(400, "Allocate to approved bills")
        part = r2(num(a.get("amount"), "Amount", required=True, positive=True))
        if part > bill_balance(b) + 0.01:
            abort(400, f"Bill {b['bill_no']} has {money_text(bill_balance(b))} left")
        allocs.append((b, part))
    if not allocs or abs(sum(x for _, x in allocs) - amount) > 0.01:
        abort(400, "Allocate the whole amount to bills")
    if len({b["vendor_id"] for b, _ in allocs}) != 1:
        abort(400, "One payment pays one supplier")
    vp = t.insert("vendor_payments", {"vendor_id": allocs[0][0]["vendor_id"], "vendor_name": allocs[0][0]["vendor_name"], "amount": amount,
                                      "date": a_date(d.get("date") or sales.today(), "Date"), "mode": d["mode"],
                                      "reference": (d.get("reference") or "").strip() or None, "status": "paid",
                                      "allocations": [{"bill_id": str(b["_id"]), "bill_no": b["bill_no"], "amount": x} for b, x in allocs],
                                      "by": g.user.get("name")})
    for b, x in allocs:
        paid = r2(b.get("paid", 0) + x)
        db.vendor_bills.update_one({"_id": b["_id"]}, {"$set": {"paid": paid, "status": "paid" if paid >= b["total"] - 0.01 else "part_paid"}})
    return jsonify(serialize(vp)), 201


@bp.post("/vendor-payments/<vid>/void")
@api("finance")
def void_payment(vid):
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void a payment")
    vp = t.get("vendor_payments", vid)
    if vp["status"] == "void":
        abort(409, "Already void")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why")
    for a in vp["allocations"]:
        b = db.vendor_bills.find_one({"_id": oid(a["bill_id"])})
        paid = r2(b.get("paid", 0) - a["amount"])
        db.vendor_bills.update_one({"_id": b["_id"]}, {"$set": {"paid": paid, "status": "part_paid" if paid > 0.01 else "approved"}})
    return jsonify(serialize(t.update("vendor_payments", vid, {"status": "void", "void_reason": reason[:300]})))


@bp.get("/finance/payables")
@api("finance", write=False)
def payables():
    from datetime import date
    from .invoices import BUCKETS, bucket
    today = date.fromisoformat(sales.today())
    sums, rows, by_vendor = {k: 0.0 for k, _ in BUCKETS}, [], {}
    for b in t.find("vendor_bills", scoped({"status": {"$in": ["approved", "part_paid"]}}), sort=[("due_date", 1)]):
        late = (today - date.fromisoformat(b["due_date"])).days
        bal = bill_balance(b)
        sums[bucket(late)] = r2(sums[bucket(late)] + bal)
        v = by_vendor.setdefault(b["vendor_name"], {"vendor": b["vendor_name"], "balance": 0.0})
        v["balance"] = r2(v["balance"] + bal)
        rows.append({**serialize(b), "balance": bal, "days_late": max(late, 0)})
    return jsonify({"rows": rows, "buckets": [{"key": k, "label": lbl, "total": sums[k]} for k, lbl in BUCKETS],
                    "total": r2(sum(sums.values())), "by_vendor": sorted(by_vendor.values(), key=lambda x: -x["balance"])})


# ---------------- block 4: the supplier portal ----------------
from ..security import portal  # noqa: E402

VENDOR_VISIBLE = ["approved", "sent", "acknowledged", "part_received", "received", "closed"]


def vendor_view(po):
    """Only this supplier's own prices; never our budget, stage totals, other quotes or margin."""
    return {"id": str(po["_id"]), "number": po["number"], "project": po["project_name"], "status": po["status"],
            "expected_date": po.get("expected_date"), "delivery_address": po.get("delivery_address"), "terms": po.get("terms"),
            "acknowledged": po.get("acknowledged"), "revision": len(po.get("revisions", [])),
            "lines": [{"id": ln["id"], "description": ln["description"], "qty": ln["qty"], "unit": ln.get("unit"), "rate": ln["unit_cost"],
                       "amount": ln["cost"], "tax_pct": ln["tax_pct"], "received": ln.get("received_qty", 0), "accepted": ln.get("accepted_qty", 0),
                       "billed": ln.get("billed_qty", 0)} for ln in po["lines"]],
            "amount": po["cost"], "tax": po["tax"], "total": po["total"]}


def my_po(poid):
    po = db.purchase_orders.find_one({"_id": oid(poid), "company_id": g.cid}) if poid and len(poid) == 24 else None
    if not po or po["vendor_id"] != g.contact_id or po["status"] not in VENDOR_VISIBLE:
        abort(404, "purchase order not found")
    return po


@bp.get("/portal/purchase-orders")
@portal
def portal_pos():
    rows = [vendor_view(po) for po in db.purchase_orders.find({"company_id": g.cid, "vendor_id": g.contact_id, "status": {"$in": VENDOR_VISIBLE}})
            .sort("created_at", -1)]
    bills = [{"bill_no": b["bill_no"], "po_number": b.get("po_number"), "date": b["date"], "total": b["total"], "paid": b.get("paid", 0),
              "status": b["status"], "due_date": b.get("due_date")}
             for b in db.vendor_bills.find({"company_id": g.cid, "vendor_id": g.contact_id, "status": {"$ne": "void"}}).sort("date", -1)]
    rfqs = [{"id": str(r["_id"]), "number": r["number"], "project": r["project_name"], "due_date": r["due_date"],
             "lines": [{"id": ln["id"], "description": ln["description"], "qty": ln["qty"], "unit": ln.get("unit")} for ln in r["lines"]],
             "my_quote": next(({"rates": q["rates"], "tax_pct": q["tax_pct"], "delivery_days": q["delivery_days"]} for q in r["quotes"]
                               if q["supplier_id"] == g.contact_id), None)}
            for r in db.rfqs.find({"company_id": g.cid, "status": "sent", "suppliers.contact_id": g.contact_id})]
    return jsonify(serialize({"purchase_orders": rows, "bills": bills, "rfqs": rfqs}))


@bp.post("/portal/purchase-orders/<poid>/acknowledge")
@portal
def portal_ack(poid):
    po = my_po(poid)
    if po["status"] != "sent":
        abort(409, "Already acknowledged")
    name = ((request.get_json(force=True) or {}).get("name") or "").strip() or abort(400, "Type your name")
    acknowledge_po(po, {"name": name[:120], "method": "Portal", "date": sales.today(), "contact_id": g.contact_id})
    return jsonify({"ok": True})


@bp.post("/portal/purchase-orders/<poid>/delivery-date")
@portal
def portal_delivery(poid):
    po = my_po(poid)
    if po["status"] in ("received", "closed"):
        abort(409, "Everything is delivered")
    d = request.get_json(force=True) or {}
    day = a_date(d.get("date"), "Delivery date")
    if day < sales.today():
        abort(400, "The date is in the past")
    upd = {"date": day, "was": po.get("expected_date"), "note": (d.get("note") or "").strip()[:300] or None, "by": g.user.get("name"), "at": t.now()}
    t.update("purchase_orders", poid, {"expected_date": day, "vendor_updates": po.get("vendor_updates", []) + [upd]})
    if po.get("expected_date") and day > po["expected_date"]:
        p = db.projects.find_one({"_id": oid(po["project_id"])})
        notify.send("po_delivery_changed", list(dict.fromkeys(notify.role_users("procurement") + ev.managers(p))),
                    f"{po['vendor_name']} moved {po['number']} from {po['expected_date']} to {day}" + (f": {upd['note']}" if upd["note"] else ""),
                    f"/app/purchase-orders/{poid}", project_id=po["project_id"], level="warn")
    return jsonify({"ok": True})


@bp.post("/portal/purchase-orders/<poid>/invoice")
@portal
def portal_invoice(poid):
    """The supplier uploads their invoice: a draft bill for staff to check against the PO and receipts."""
    po = my_po(poid)
    d = request.get_json(force=True) or {}
    if not d.get("file_key"):
        abort(400, "Upload the invoice")
    bill = create_bill(po, d, source="portal")
    notify.send("vendor_invoice", list(dict.fromkeys(notify.role_users("procurement") + notify.role_users("accounts"))),
                f"{po['vendor_name']} uploaded bill {bill['bill_no']} for {po['number']} ({money_text(bill['total'])})", "/app/procurement?tab=bills",
                project_id=po["project_id"])
    return jsonify({"ok": True, "bill_no": bill["bill_no"]}), 201


@bp.post("/portal/rfqs/<rid>/quote")
@portal
def portal_quote(rid):
    rfq = db.rfqs.find_one({"_id": oid(rid), "company_id": g.cid}) if len(rid) == 24 else None
    if not rfq or not any(s["contact_id"] == g.contact_id for s in rfq["suppliers"]):
        abort(404, "request for quotation not found")
    record_quote(rfq, g.contact_id, request.get_json(force=True) or {})
    return jsonify({"ok": True})


# ---------------- block 4: reports ----------------
@bp.get("/reports/procurement")
@api("procurement", write=False)
def report():
    from datetime import date
    today = sales.today()
    q = scoped({})
    money = not g.hide_costs and (can("finance") or can("procurement", True))
    pos = list(db.purchase_orders.find({**q, "company_id": g.cid, "status": {"$nin": ["draft", "rejected", "cancelled"]}}))
    by_status = {}
    for po in pos:
        x = by_status.setdefault(po["status"], {"status": po["status"], "count": 0, "value": 0.0})
        x["count"] += 1
        x["value"] = r2(x["value"] + po["cost"])
    late, ontime = [], {}
    for po in pos:
        due = po.get("expected_date")
        if not due:
            continue
        sup = ontime.setdefault(po["vendor_name"], {"vendor": po["vendor_name"], "orders": 0, "on_time": 0})
        sup["orders"] += 1
        first = db.goods_receipts.find_one({"company_id": g.cid, "po_id": str(po["_id"])}, sort=[("date", 1)])
        if po["status"] in ("received", "closed") and first and first["date"] <= due:
            sup["on_time"] += 1
        if po["status"] not in ("received", "closed") and due < today:
            late.append({"number": po["number"], "vendor": po["vendor_name"], "project": po["project_name"], "expected_date": due,
                         "days_late": (date.fromisoformat(today) - date.fromisoformat(due)).days})
    for s in ontime.values():
        s["on_time_pct"] = round(s["on_time"] / s["orders"] * 100) if s["orders"] else None
    data = {"po_status": sorted(by_status.values(), key=lambda x: x["status"]), "late": sorted(late, key=lambda x: -x["days_late"]),
            "suppliers": sorted(ontime.values(), key=lambda x: x["vendor"]),
            "open_requests": db.purchase_requests.count_documents({**q, "company_id": g.cid, "status": {"$in": ["open", "quoting"]}}),
            "money_view": money}
    if not money:
        for x in data["po_status"]:
            x.pop("value", None)
        return jsonify(data)
    spend = {}
    variance = []
    for b in db.vendor_bills.find({**q, "company_id": g.cid, "status": {"$in": ["approved", "part_paid", "paid"]}}):
        spend[b["vendor_name"]] = r2(spend.get(b["vendor_name"], 0) + b["amount"])
        for ln in b["lines"]:
            if ln.get("rate_id"):
                rate = db.rate_library.find_one({"_id": oid(ln["rate_id"])}, {"name": 1, "rate": 1})
                if rate and rate.get("rate"):
                    variance.append({"item": rate["name"], "vendor": b["vendor_name"], "billed_rate": ln["rate"], "library_rate": rate["rate"],
                                     "variance_pct": round((ln["rate"] - rate["rate"]) / rate["rate"] * 100, 1)})
    data.update(spend=[{"vendor": k, "amount": v} for k, v in sorted(spend.items(), key=lambda kv: -kv[1])],
                price_variance=sorted(variance, key=lambda x: -abs(x["variance_pct"]))[:50])
    return jsonify(data)
