"""Documents & revisions, 360 renders, design options, product library, selections, procurement,
change orders, site reports and snags (sections 6-11, 19)."""
from datetime import datetime

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import register_crud, num
from ..db import db
from ..security import api, MANAGER_ROLES
from ..services import budget as B

bp = Blueprint("delivery", __name__)


def _project_name(d):
    if d.get("project_id"):
        p = t.get("projects", d["project_id"], required=False)
        d["project_name"] = p["name"] if p else None
    return d


# ---------------- documents ----------------
def _prep_document(d, existing):
    d.setdefault("folder", "General")
    d.setdefault("kind", "drawing")
    d.setdefault("revisions", [])
    d.setdefault("comments", [])
    d.setdefault("approval", "none")
    if not existing and d.get("file"):
        d["revisions"] = [{"rev": "R0", **d.pop("file"), "by": g.user.get("name"), "at": t.now(),
                           "note": d.get("note")}]
    if d["revisions"]:
        d["latest"] = d["revisions"][-1]
    return _project_name(d)


register_crud(bp, "documents", "documents", search=("name", "folder", "phase"),
              filters=("project_id", "kind", "folder", "approval", "room"), prepare=_prep_document)


@bp.post("/documents/<_id>/revisions")
@api("documents")
def add_revision(_id):
    d = request.get_json(force=True) or {}
    doc = t.get("documents", _id)
    rev = {"rev": f"R{len(doc.get('revisions', []))}", **(d.get("file") or {}), "by": g.user.get("name"),
           "at": t.now(), "note": d.get("note")}
    changes = {"latest": rev}
    if doc.get("approval") in ("approved", "rejected"):
        changes["approval"] = "none"  # new revision needs a fresh approval
    return jsonify(t.out(t.update("documents", _id, changes, raw={"$push": {"revisions": rev}})))


@bp.post("/documents/<_id>/request-approval")
@api("documents")
def request_doc_approval(_id):
    doc = t.update("documents", _id, {"approval": "pending", "approval_requested_at": t.now(), "shared": True})
    from .engage import schedule_sequence
    schedule_sequence("approval", _id, f"approval of {doc['name']} {doc.get('latest', {}).get('rev', '')}",
                      owner_id=g.uid)
    return jsonify(t.out(doc))


@bp.post("/documents/<_id>/transmit")
@api("documents")
def transmit(_id):
    """Transmittal: which revision went to whom, and when."""
    d = request.get_json(force=True) or {}
    doc = t.get("documents", _id)
    entry = {"id": t.sid(), "to": d.get("to"), "contact_id": d.get("contact_id"),
             "rev": doc.get("latest", {}).get("rev"), "at": t.now(), "by": g.user.get("name"), "purpose": d.get("purpose")}
    return jsonify(t.out(t.update("documents", _id, {}, raw={"$push": {"transmittals": entry}})))


def add_comment(doc_id, d, author, side="staff"):
    """Comment pinned on a render; optionally becomes a task or a change request."""
    doc = t.get("documents", doc_id)
    comment = {"id": t.sid(), "x": num(d.get("x"), None), "y": num(d.get("y"), None),
               "pitch": d.get("pitch"), "yaw": d.get("yaw"), "text": d.get("text", ""),
               "by": author, "side": side, "at": t.now(), "rev": doc.get("latest", {}).get("rev")}
    make = d.get("make")
    if make == "task":
        f = t.insert("followups", {"title": f"Render comment: {comment['text'][:80]}", "status": "open",
                                   "priority": "normal", "owner_id": doc.get("created_by"),
                                   "due": datetime.utcnow().date().isoformat(),
                                   "related": {"type": "project", "id": doc.get("project_id")}})
        comment["followup_id"] = str(f["_id"])
    elif make == "change_request":
        co = t.insert("change_orders", {
            "number": t.next_number("CO", "CO"), "project_id": doc.get("project_id"),
            "project_name": doc.get("project_name"), "title": f"Change from render: {comment['text'][:60]}",
            "description": comment["text"], "raised_by_type": "client" if side == "client" else "designer",
            "reason": "client", "category": "design", "cost_impact": 0, "price_impact": 0,
            "time_impact_days": 0, "status": "draft", "source": {"type": "document", "id": doc_id}})
        comment["change_order_id"] = str(co["_id"])
    t.update("documents", doc_id, {}, raw={"$push": {"comments": comment}})
    return comment


@bp.post("/documents/<_id>/comments")
@api("documents", write=False)
def doc_comment(_id):
    return jsonify(add_comment(_id, request.get_json(force=True) or {}, g.user.get("name"))), 201


register_crud(bp, "design_options", "documents", search=("title", "room"), filters=("project_id", "status"),
              prepare=lambda d, e: _project_name({**d, "status": d.get("status", "draft"),
                                                  "options": [{"id": o.get("id") or t.sid(), **o}
                                                              for o in d.get("options", [])]}))


# ---------------- product library & selections ----------------
def _prep_product(d, existing):
    d["trade_price"] = num(d.get("trade_price"))
    rule = (g.company.get("markup_rules") or {}).get(d.get("category"))
    if not d.get("client_price"):
        d["client_price"] = round(d["trade_price"] * (1 + num(rule, 30) / 100), 2)
    d["client_price"] = num(d.get("client_price"))
    d["lead_time_days"] = int(num(d.get("lead_time_days")))
    if d.get("supplier_id"):
        c = t.get("contacts", d["supplier_id"], required=False)
        d["supplier_name"] = c["name"] if c else None
    return d


register_crud(bp, "products", "selections", search=("name", "sku", "category", "supplier_name", "finish"),
              filters=("category", "supplier_id"), prepare=_prep_product, sort=("name", 1))


SELECTION_FLOW = ["proposed", "client_approved", "ordered", "delivered", "installed"]


def _prep_selection(d, existing):
    d.setdefault("status", "proposed")
    if d.get("product_id") and (not existing or existing.get("product_id") != d.get("product_id")):
        prod = t.get("products", d["product_id"])
        for k in ("name", "sku", "category", "finish", "dimensions", "photo", "supplier_id", "supplier_name",
                  "lead_time_days"):
            d[k] = prod.get(k)
        d["trade_price"] = prod.get("trade_price", 0)
        d.setdefault("client_price", prod.get("client_price"))
        if existing:
            d["client_price"] = prod.get("client_price")
    qty = num(d.get("qty"), 1)
    d["qty"] = qty
    trade = num(d.get("trade_price"))
    if d.get("markup_pct") not in (None, ""):
        d["client_price"] = round(trade * (1 + num(d["markup_pct"]) / 100), 2)
    client_price = num(d.get("client_price"))
    d["total_trade"] = round(trade * qty, 2)
    d["total_client"] = round(client_price * qty, 2)
    d["margin"] = round(d["total_client"] - d["total_trade"], 2)
    allowance = num(d.get("allowance"))
    # a product chosen above its allowance shows the difference; client approves it before ordering
    d["over_allowance"] = round(d["total_client"] - allowance, 2) if allowance and d["total_client"] > allowance else 0
    if existing and existing.get("status") != "proposed" and existing.get("product_id") != d.get("product_id"):
        d["status"] = "proposed"  # product swap needs approval again
        d["client_decision"] = None
    return _project_name(d)


register_crud(bp, "selections", "selections", search=("name", "room", "sku", "category"),
              filters=("project_id", "room", "status"), prepare=_prep_selection, sort=("room", 1))


@bp.post("/selections/<_id>/status")
@api("selections")
def selection_status(_id):
    status = (request.get_json(force=True) or {}).get("status")
    if status not in SELECTION_FLOW:
        abort(400, "Invalid status")
    sel = t.get("selections", _id)
    if SELECTION_FLOW.index(status) >= 2 and sel["status"] == "proposed":
        abort(409, "Client must approve this item before it is ordered")
    return jsonify(t.out(t.update("selections", _id, {"status": status, f"{status}_at": t.now()})))


@bp.post("/selections/order")
@api("procurement")
def order_selections():
    """Create purchase orders (one per supplier) from client-approved selections."""
    d = request.get_json(force=True) or {}
    sels = [t.get("selections", i) for i in d.get("ids", [])]
    if not sels:
        abort(400, "Choose items to order")
    if any(s["status"] != "client_approved" for s in sels):
        abort(409, "Only client-approved items can be ordered")
    project_id = sels[0]["project_id"]
    deposit_pct = num(g.company.get("deposit_pct"), 0)
    if deposit_pct and not d.get("skip_deposit_check"):
        needed = sum(s["total_client"] for s in sels) * deposit_pct / 100
        received = sum(i.get("paid", 0) for i in t.find("invoices", {"project_id": project_id, "basis": "deposit"}))
        if received + 0.01 < needed:
            abort(409, f"Client deposit of {round(needed):,} required before ordering (received {round(received):,}). "
                       "Raise a deposit invoice first.")
    by_vendor = {}
    for s in sels:
        by_vendor.setdefault(s.get("supplier_id"), []).append(s)
    pos = []
    for vendor_id, items in by_vendor.items():
        po = create_po({
            "project_id": project_id, "vendor_id": vendor_id, "stage_id": d.get("stage_id"),
            "items": [{"description": f"{s['name']} ({s.get('room')})", "qty": s["qty"], "rate": s.get("trade_price", 0),
                       "selection_id": str(s["_id"]), "sku": s.get("sku")} for s in items],
            "source": "selections"})
        for s in items:
            t.update("selections", str(s["_id"]), {"status": "ordered", "ordered_at": t.now(), "po_id": str(po["_id"])})
        pos.append(t.out(po))
    return jsonify(pos), 201


@bp.get("/projects/<_id>/margin")
@api("selections", write=False)
def margin_report(_id):
    rows = {}
    for s in t.find("selections", {"project_id": _id}):
        r = rows.setdefault(s.get("room") or "Unassigned", {"room": s.get("room") or "Unassigned", "items": 0,
                                                             "trade": 0, "client": 0, "over_allowance": 0})
        r["items"] += 1
        r["trade"] += s.get("total_trade", 0)
        r["client"] += s.get("total_client", 0)
        r["over_allowance"] += s.get("over_allowance", 0)
    out = list(rows.values())
    for r in out:
        r["margin"] = round(r["client"] - r["trade"], 2)
        r["margin_pct"] = round(r["margin"] / r["client"] * 100, 1) if r["client"] else 0
    return jsonify(out)


# ---------------- procurement ----------------
def _po_totals(d):
    total = 0
    for it in d.get("items", []):
        it.setdefault("id", t.sid())
        it["qty"] = num(it.get("qty"), 1)
        it["rate"] = num(it.get("rate"))
        it.setdefault("received", 0)
        it.setdefault("damaged", 0)
        it["amount"] = round(it["qty"] * it["rate"], 2)
        total += it["amount"]
    d["subtotal"] = round(total, 2)
    d["tax"] = round(total * num(d.get("tax_pct"), g.company.get("tax_rate", 18)) / 100, 2)
    d["total"] = round(d["subtotal"] + d["tax"], 2)
    return d


def create_po(d):
    d = _po_totals(_project_name(d))
    if d.get("vendor_id"):
        v = t.get("contacts", d["vendor_id"], required=False)
        d["vendor_name"] = v["name"] if v else None
    d["number"] = t.next_number("PO", "PO")
    d["status"] = "draft"
    d.setdefault("deliveries", [])
    return t.insert("purchase_orders", d)


def _prep_pr(d, existing):
    d.setdefault("status", "open")
    for q in d.get("quotes", []):
        q.setdefault("id", t.sid())
        q["amount"] = num(q.get("amount"))
        if q.get("vendor_id"):
            v = t.get("contacts", q["vendor_id"], required=False)
            q["vendor_name"] = v["name"] if v else q.get("vendor_name")
    return _project_name(d)


register_crud(bp, "purchase_requests", "procurement", search=("title", "project_name"),
              filters=("project_id", "status"), prepare=_prep_pr, number=("PR", "PR"))


@bp.post("/purchase_requests/<_id>/award")
@api("procurement")
def award_quote(_id):
    """Compare vendor quotes, pick one and turn it into a PO."""
    d = request.get_json(force=True) or {}
    pr = t.get("purchase_requests", _id)
    quote = next((q for q in pr.get("quotes", []) if q["id"] == d.get("quote_id")), None) or abort(400, "Pick a quote")
    items = pr.get("items") or [{"description": pr.get("title"), "qty": 1, "rate": quote["amount"]}]
    if pr.get("items") and quote.get("amount"):
        base = sum(num(i.get("qty"), 1) * num(i.get("rate")) for i in items) or 1
        factor = quote["amount"] / base
        items = [{**i, "rate": round(num(i.get("rate")) * factor, 2)} for i in items]
    po = create_po({"project_id": pr.get("project_id"), "stage_id": pr.get("stage_id"), "vendor_id": quote.get("vendor_id"),
                    "items": items, "pr_id": _id, "expected_date": quote.get("delivery_date"),
                    "delivery_location": pr.get("delivery_location", "site")})
    t.update("purchase_requests", _id, {"status": "ordered", "awarded_quote": quote["id"], "po_id": str(po["_id"])})
    return jsonify(t.out(po)), 201


register_crud(bp, "purchase_orders", "procurement", search=("number", "vendor_name", "project_name"),
              filters=("project_id", "status", "vendor_id"),
              prepare=lambda d, e: _po_totals(_project_name(d)) if not e or e.get("status") == "draft" else
              (abort(409, "Only draft POs can be edited") if d.get("items") != e.get("items") else d),
              number=("PO", "PO"))


@bp.post("/purchase_orders/<_id>/issue")
@api("procurement")
def issue_po(_id):
    """Issuing a PO is a new purchase: over-budget milestones need manager approval first."""
    po = t.get("purchase_orders", _id)
    if po["status"] not in ("draft", "pending_approval"):
        abort(409, f"PO is already {po['status']}")
    if po.get("project_id") and po.get("stage_id") and po["status"] == "draft":
        if B.needs_manager_approval(po["project_id"], po["stage_id"], po["subtotal"]):
            if g.role not in MANAGER_ROLES:
                t.notify(f"PO {po['number']} needs approval — milestone budget exceeded", level="red", role="pm",
                         project_id=po["project_id"], link="/procurement")
                return jsonify(t.out(t.update("purchase_orders", _id, {"status": "pending_approval"})))
    if po["status"] == "pending_approval" and g.role not in MANAGER_ROLES:
        abort(403, "Waiting for manager approval")
    return jsonify(t.out(t.update("purchase_orders", _id, {"status": "issued", "issued_at": t.now(),
                                                           "approved_by": g.user.get("name")})))


@bp.post("/purchase_orders/<_id>/deliveries")
@api("procurement", write=False)
def receive_delivery(_id):
    """Delivery / receipt: partial deliveries, damaged items, receiving location."""
    if g.role not in ("owner", "pm", "procurement", "site"):
        abort(403)
    d = request.get_json(force=True) or {}
    po = t.get("purchase_orders", _id)
    if po["status"] not in ("issued", "partial"):
        abort(409, "PO must be issued before receiving")
    lines = {l["item_id"]: l for l in d.get("lines", [])}
    for it in po["items"]:
        if it["id"] in lines:
            it["received"] = round(it.get("received", 0) + num(lines[it["id"]].get("qty")), 3)
            it["damaged"] = round(it.get("damaged", 0) + num(lines[it["id"]].get("damaged")), 3)
    complete = all(it["received"] - it.get("damaged", 0) >= it["qty"] for it in po["items"])
    delivery = {"id": t.sid(), "at": t.now(), "by": g.user.get("name"), "location": d.get("location", "site"),
                "lines": d.get("lines", []), "note": d.get("note"), "photos": d.get("photos", [])}
    po = t.update("purchase_orders", _id, {"items": po["items"], "status": "delivered" if complete else "partial"},
                  raw={"$push": {"deliveries": delivery}})
    if any(num(l.get("damaged")) for l in d.get("lines", [])):
        t.notify(f"Damaged items received on {po['number']} — raise a claim", level="yellow", role="procurement",
                 link="/procurement")
    for it in po["items"]:
        if it.get("selection_id") and it["received"] >= it["qty"]:
            t.update("selections", it["selection_id"], {"status": "delivered", "delivered_at": t.now()})
    return jsonify(t.out(po))


@bp.post("/purchase_orders/<_id>/vendor-invoice")
@api("procurement")
def match_vendor_invoice(_id):
    """3-way match: PO vs received vs vendor invoice; booking it posts the cost to the milestone."""
    d = request.get_json(force=True) or {}
    po = t.get("purchase_orders", _id)
    received_value = round(sum((it["received"] - it.get("damaged", 0)) * it["rate"] for it in po["items"]), 2)
    amount = num(d.get("amount"))
    tol = 0.01 * max(received_value, 1)
    match = "matched" if abs(amount - received_value) <= tol else ("over_billed" if amount > received_value else "under_billed")
    inv = {"number": d.get("number"), "amount": amount, "date": d.get("date"), "match": match,
           "received_value": received_value, "at": t.now()}
    po = t.update("purchase_orders", _id, {"vendor_invoice": inv})
    if match == "matched" or d.get("force"):
        from .finance import post_cost
        if po.get("project_id"):
            post_cost({"project_id": po["project_id"], "stage_id": po.get("stage_id"),
                       "head": "product" if po.get("source") == "selections" else "material", "amount": amount,
                       "description": f"{po['number']} · {po.get('vendor_name') or ''} invoice {d.get('number')}",
                       "vendor_id": po.get("vendor_id"), "po_id": _id, "pre_approved": True})
        t.update("purchase_orders", _id, {"status": "invoiced"})
    return jsonify(t.out(t.get("purchase_orders", _id)))


@bp.post("/purchase_orders/<_id>/claim")
@api("procurement")
def damage_claim(_id):
    d = request.get_json(force=True) or {}
    claim = {"id": t.sid(), "type": d.get("type", "damage"), "description": d.get("description"),
             "amount": num(d.get("amount")), "status": "open", "at": t.now()}
    return jsonify(t.out(t.update("purchase_orders", _id, {}, raw={"$push": {"claims": claim}})))


# ---------------- change orders ----------------
def _prep_co(d, existing):
    d.setdefault("status", "draft")
    d["cost_impact"] = num(d.get("cost_impact"))
    if d.get("price_impact") in (None, ""):
        d["price_impact"] = d["cost_impact"]
    d["price_impact"] = num(d.get("price_impact"))
    d["time_impact_days"] = int(num(d.get("time_impact_days")))
    d.setdefault("reason", "client")
    if existing and existing.get("status") in ("approved", "rejected"):
        abort(409, "This change order is closed")
    return _project_name(d)


register_crud(bp, "change_orders", "change_orders", search=("number", "title", "project_name"),
              filters=("project_id", "status", "reason"), prepare=_prep_co, number=("CO", "CO"))


@bp.post("/change_orders/<_id>/submit")
@api("change_orders")
def submit_co(_id):
    co = t.get("change_orders", _id)
    if co["reason"] != "client":
        # our mistake / price rise: we pay — approved internally, profit goes down
        if g.role not in MANAGER_ROLES:
            abort(403, "A manager must approve internal variations")
        return jsonify(t.out(apply_change_order(co, "internal", g.user.get("name"))))
    co = t.update("change_orders", _id, {"status": "pending_client", "submitted_at": t.now()})
    from .engage import schedule_sequence
    schedule_sequence("approval", _id, f"change order {co['number']}", owner_id=g.uid)
    return jsonify(t.out(co))


def apply_change_order(co, approved_by_type, approver):
    """Approved change: contract value, schedule and milestone budget update automatically."""
    _id = str(co["_id"])
    pid = co["project_id"]
    if co["reason"] == "client":
        contract = B.contract_for(pid)
        if contract:
            t.update("contracts", str(contract["_id"]), {
                "value": round(contract["value"] + co["price_impact"], 2),
                "change_orders_total": round(contract.get("change_orders_total", 0) + co["price_impact"], 2)})
        p = t.get("projects", pid)
        t.update("projects", pid, {"value": round((p.get("value") or 0) + co["price_impact"], 2)})
    project = t.get("projects", pid)
    stage = B.find_stage(project, co.get("stage_id")) if co.get("stage_id") else None
    if stage:
        if co["cost_impact"] and co["reason"] == "client":
            stage["budget"] = round((stage.get("budget") or 0) + co["cost_impact"], 2)
        if co["time_impact_days"]:
            # shift this stage end and everything after it
            hit = False
            for s in project["stages"]:
                if s["id"] == stage["id"]:
                    hit = True
                    if s.get("end"):
                        s["end"] = _shift(s["end"], co["time_impact_days"])
                elif hit and s.get("service") == stage.get("service"):
                    if s.get("start"):
                        s["start"] = _shift(s["start"], co["time_impact_days"])
                    if s.get("end"):
                        s["end"] = _shift(s["end"], co["time_impact_days"])
        t.update("projects", pid, {"stages": project["stages"]})
        B.recalc_stage(pid, stage["id"])
    if co.get("selection_id"):
        t.update("selections", co["selection_id"], {"status": "client_approved"})
    db.followups.update_many({"company_id": g.cid, "related.id": _id, "status": "open", "auto": True},
                             {"$set": {"status": "cancelled", "cancel_reason": "Approved"}})
    t.notify(f"Change order {co['number']} approved", level="success", role="pm", project_id=pid,
             link=f"/projects/{pid}")
    return t.update("change_orders", _id, {"status": "approved", "approved_at": t.now(),
                                           "approved_by": approver, "approved_by_type": approved_by_type})


def _shift(day, n):
    from datetime import timedelta
    return (datetime.fromisoformat(day) + timedelta(days=n)).date().isoformat()


@bp.post("/change_orders/<_id>/approve")
@api("change_orders")
def approve_co_staff(_id):
    """Record a client approval received offline (signed paper / email)."""
    if g.role not in MANAGER_ROLES:
        abort(403)
    co = t.get("change_orders", _id)
    if co["status"] == "approved":
        abort(409, "Already approved")
    return jsonify(t.out(apply_change_order(co, "staff_on_behalf", g.user.get("name"))))


@bp.post("/change_orders/<_id>/reject")
@api("change_orders")
def reject_co(_id):
    d = request.get_json(force=True) or {}
    return jsonify(t.out(t.update("change_orders", _id, {"status": "rejected", "reject_reason": d.get("reason")})))


# ---------------- site ----------------
def _prep_report(d, existing):
    d.setdefault("date", datetime.utcnow().date().isoformat())
    d["labour_count"] = int(num(d.get("labour_count")))
    d.setdefault("photos", [])
    d.setdefault("author", g.user.get("name"))
    return _project_name(d)


register_crud(bp, "site_reports", "site", search=("work_done", "issues", "project_name"),
              filters=("project_id", "date"), prepare=_prep_report, sort=("date", -1))


def _prep_snag(d, existing):
    d.setdefault("status", "open")
    if d.get("status") == "closed" and (not existing or existing.get("status") != "closed"):
        d["closed_at"] = t.now().isoformat()
    return _project_name(d)


register_crud(bp, "snags", "site", search=("title", "location", "project_name"),
              filters=("project_id", "status", "assignee_id", "kind"), prepare=_prep_snag)
