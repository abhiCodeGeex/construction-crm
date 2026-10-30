"""Finance (section 12): costs per milestone with budget control, invoices, payments, retention, timesheets."""
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import register_crud, num
from ..db import db
from ..security import api, MANAGER_ROLES
from ..services import budget as B
from ..services.pricing import invoice_totals

bp = Blueprint("finance", __name__)

OVERSPEND_REASONS = ("client", "ours", "price_rise")


def _overspend_change_order(cost, project, stage):
    """Client changed something -> client pays: draft change order for the overspend."""
    markup = num((g.company.get("overspend_markup_pct")), 10)
    co = t.insert("change_orders", {
        "number": t.next_number("CO", "CO"), "project_id": cost["project_id"], "project_name": project["name"],
        "stage_id": stage["id"], "title": f"Overspend on {stage['name']} (client change)",
        "description": cost.get("description") or "", "reason": "client", "category": "variation",
        "raised_by_type": "site", "cost_impact": cost["overspend_amount"],
        "price_impact": round(cost["overspend_amount"] * (1 + markup / 100), 2),
        "time_impact_days": 0, "status": "draft", "source": {"type": "cost", "id": str(cost["_id"])},
    })
    t.update("costs", str(cost["_id"]), {"change_order_id": str(co["_id"])}, audit_it=False)
    return co


def post_cost(d):
    pid, stage_id = d.get("project_id"), d.get("stage_id")
    project = t.get("projects", pid)
    stage = B.find_stage(project, stage_id) if stage_id else None
    if stage_id and not stage:
        abort(400, "Unknown milestone")
    amount = round(num(d.get("amount")), 2)
    if amount <= 0:
        abort(400, "Amount must be positive")
    spent = B.stage_spent(pid, stage_id) if stage else 0
    budget = (stage or {}).get("budget") or 0
    over = round(max(0.0, spent + amount - max(budget, spent)), 2) if budget else 0
    reason = d.get("overspend_reason")
    if over and reason and reason not in OVERSPEND_REASONS:
        abort(400, "Overspend reason must be client, ours or price_rise")
    manager = g.role in MANAGER_ROLES
    status = "approved" if (not over or manager or d.get("pre_approved")) else "pending_approval"
    if over and status == "approved" and not reason and not d.get("pre_approved"):
        abort(400, "This cost takes the milestone over budget — choose why (client change, our mistake, price rise)")
    cost = t.insert("costs", {
        "project_id": pid, "project_name": project["name"], "stage_id": stage_id,
        "stage_name": stage["name"] if stage else None, "head": d.get("head", "material"), "amount": amount,
        "description": d.get("description"), "date": d.get("date") or datetime.utcnow().date().isoformat(),
        "vendor_id": d.get("vendor_id"), "po_id": d.get("po_id"), "receipt": d.get("receipt"),
        "status": status, "overspend_amount": over or None, "overspend_reason": reason if over else None,
        "rate_item_id": d.get("rate_item_id"), "qty": num(d.get("qty"), None), "petty_cash": bool(d.get("petty_cash")),
    })
    if status == "pending_approval":
        t.notify(f"Cost of {amount:,.0f} on {project['name']} · {stage['name']} is over budget and needs approval",
                 level="red", role="pm", project_id=pid, link=f"/projects/{pid}")
    else:
        _after_approval(cost, project, stage)
    return cost


def _after_approval(cost, project, stage):
    if stage:
        B.recalc_stage(cost["project_id"], stage["id"])
        if cost.get("overspend_amount") and cost.get("overspend_reason") == "client":
            _overspend_change_order(cost, project, stage)
    # learn from it: real costs update the rate library
    if cost.get("rate_item_id") and cost.get("qty"):
        item = t.get("rate_library", cost["rate_item_id"], required=False)
        if item:
            actual = round(cost["amount"] / cost["qty"], 2)
            history = (item.get("actuals") or [])[-9:] + [actual]
            t.update("rate_library", cost["rate_item_id"], {
                "last_actual": actual, "actuals": history,
                "suggested_rate": round(sum(history) / len(history), 2)}, audit_it=False)


@bp.get("/costs")
@api("finance", write=False)
def list_costs():
    q = {k: request.args[k] for k in ("project_id", "stage_id", "head", "status") if request.args.get(k)}
    return jsonify(t.out(t.find("costs", q, sort=[("date", -1)])))


@bp.post("/costs")
@api(None)
def create_cost():
    # site staff can log site expenses / petty cash; everyone else needs finance write
    from ..security import can
    d = request.get_json(force=True) or {}
    if not (can("finance", True) or (g.role == "site" and d.get("petty_cash"))):
        abort(403, "Your role cannot record costs")
    return jsonify(t.out(post_cost(d))), 201


@bp.post("/costs/<_id>/approve")
@api("finance")
def approve_cost(_id):
    if g.role not in MANAGER_ROLES:
        abort(403, "Manager approval required")
    d = request.get_json(force=True) or {}
    cost = t.get("costs", _id)
    if cost["status"] != "pending_approval":
        abort(409, "Not waiting for approval")
    reason = d.get("overspend_reason") or cost.get("overspend_reason")
    if cost.get("overspend_amount") and reason not in OVERSPEND_REASONS:
        abort(400, "Record why it went over: client, ours or price_rise")
    cost = t.update("costs", _id, {"status": "approved", "overspend_reason": reason,
                                   "approved_by": g.user.get("name"), "approved_at": t.now()})
    project = t.get("projects", cost["project_id"])
    _after_approval(cost, project, B.find_stage(project, cost.get("stage_id")))
    return jsonify(t.out(t.get("costs", _id)))


@bp.post("/costs/<_id>/reject")
@api("finance")
def reject_cost(_id):
    if g.role not in MANAGER_ROLES:
        abort(403)
    return jsonify(t.out(t.update("costs", _id, {"status": "rejected", "rejected_by": g.user.get("name")})))


@bp.delete("/costs/<_id>")
@api("finance")
def delete_cost(_id):
    cost = t.delete("costs", _id)
    if cost.get("stage_id"):
        B.recalc_stage(cost["project_id"], cost["stage_id"])
    return jsonify({"ok": True})


# ---------------- invoices ----------------
def _prep_invoice(d, existing):
    d.setdefault("status", "draft")
    d.setdefault("basis", "milestone")
    d.setdefault("payments", [])
    d.setdefault("tax_pct", g.company.get("tax_rate", 18))
    d.setdefault("issue_date", datetime.utcnow().date().isoformat())
    d.setdefault("due_date", (datetime.utcnow() + timedelta(days=15)).date().isoformat())
    if existing and existing.get("status") in ("paid",) and d.get("items") != existing.get("items"):
        abort(409, "Paid invoices cannot be edited")
    if d.get("project_id"):
        p = t.get("projects", d["project_id"], required=False)
        if p:
            d["project_name"] = p["name"]
            d.setdefault("client_id", p.get("client_id"))
            d.setdefault("client_name", p.get("client_name"))
    return invoice_totals(d)


register_crud(bp, "invoices", "finance", search=("number", "client_name", "project_name"),
              filters=("project_id", "status", "basis", "client_id"), prepare=_prep_invoice, number=("INV", "INV"))


@bp.post("/invoices/from-schedule")
@api("finance")
def invoice_from_schedule():
    """Invoice a contract payment-schedule line (milestone billing)."""
    d = request.get_json(force=True) or {}
    contract = t.get("contracts", d.get("contract_id"))
    line = next((s for s in contract["payment_schedule"] if s["id"] == d.get("schedule_id")), None) \
        or abort(404, "Schedule line not found")
    if line.get("invoiced"):
        abort(409, "Already invoiced")
    inv = t.insert("invoices", _prep_invoice({
        "number": t.next_number("INV", "INV"), "project_id": contract["project_id"], "contract_id": str(contract["_id"]),
        "basis": "milestone", "status": "sent", "retention_pct": num(d.get("retention_pct")),
        "items": [{"description": f"{contract['number']} · {line['label']} ({line['percent']}%)", "qty": 1,
                   "rate": line["amount"]}], "schedule_id": line["id"], "tax_pct": contract.get("tax_pct", 18),
    }, None))
    for s in contract["payment_schedule"]:
        if s["id"] == line["id"]:
            s["invoiced"] = True
            s["invoice_id"] = str(inv["_id"])
    t.update("contracts", str(contract["_id"]), {"payment_schedule": contract["payment_schedule"]})
    _payment_reminders(inv)
    return jsonify(t.out(inv)), 201


@bp.post("/invoices/progress")
@api("finance")
def progress_claim():
    """% complete / progress claim: bills contract value x % complete minus earlier claims."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    contract = B.contract_for(pid) or abort(409, "Project has no active contract")
    pct = num(d.get("percent"))
    if not 0 < pct <= 100:
        abort(400, "Percent complete must be 1-100")
    earlier = sum(i["subtotal"] for i in t.find("invoices", {"project_id": pid, "basis": "progress",
                                                             "status": {"$ne": "void"}}))
    amount = round(contract["value"] * pct / 100 - earlier, 2)
    if amount <= 0:
        abort(409, "Nothing new to claim at this percentage")
    inv = t.insert("invoices", _prep_invoice({
        "number": t.next_number("INV", "INV"), "project_id": pid, "contract_id": str(contract["_id"]),
        "basis": "progress", "status": "sent", "percent_complete": pct,
        "retention_pct": num(d.get("retention_pct"), 5),
        "items": [{"description": f"Progress claim — {pct}% complete (less previous claims)", "qty": 1,
                   "rate": amount}], "tax_pct": contract.get("tax_pct", 18)}, None))
    _payment_reminders(inv)
    return jsonify(t.out(inv)), 201


@bp.post("/invoices/deposit")
@api("finance")
def deposit_invoice():
    """Client deposit for products, collected before ordering."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    sels = t.find("selections", {"project_id": pid, "status": "client_approved"})
    total = sum(s.get("total_client", 0) for s in sels)
    pct = num(d.get("percent"), g.company.get("deposit_pct", 50))
    if not total:
        abort(409, "No client-approved selections to take a deposit on")
    inv = t.insert("invoices", _prep_invoice({
        "number": t.next_number("INV", "INV"), "project_id": pid, "basis": "deposit", "status": "sent",
        "items": [{"description": f"Product deposit {pct}% on {len(sels)} approved selections", "qty": 1,
                   "rate": round(total * pct / 100, 2)}], "tax_pct": 0}, None))
    return jsonify(t.out(inv)), 201


def _payment_reminders(inv):
    """Reminders before and after the due date (section 16)."""
    due = datetime.fromisoformat(inv["due_date"])
    for offset, label in ((-3, "due in 3 days"), (1, "overdue 1 day"), (7, "overdue 7 days — escalate")):
        t.insert("followups", {
            "title": f"Invoice {inv['number']} {label}", "due": (due + timedelta(days=offset)).date().isoformat(),
            "status": "open", "priority": "high" if offset > 1 else "normal", "auto": True,
            "owner_id": g.uid, "role": "accounts", "related": {"type": "invoice", "id": str(inv["_id"])},
            "channel": "email",
        })


def record_payment(inv, amount, method, ref=None, by=None):
    amount = round(num(amount), 2)
    if amount <= 0:
        abort(400, "Amount must be positive")
    payment = {"id": t.sid(), "amount": amount, "method": method, "ref": ref, "at": t.now(), "by": by}
    inv["payments"] = (inv.get("payments") or []) + [payment]
    inv = invoice_totals(inv)
    updated = t.update("invoices", str(inv["_id"]), {"payments": inv["payments"], "paid": inv["paid"],
                                                     "status": inv["status"], "paid_at": t.now()
                                                     if inv["status"] == "paid" else None})
    if updated["status"] == "paid":
        db.followups.update_many({"company_id": g.cid, "related.id": str(inv["_id"]), "status": "open", "auto": True},
                                 {"$set": {"status": "cancelled", "cancel_reason": "Paid"}})
        t.notify(f"Invoice {updated['number']} paid in full", level="success", role="accounts",
                 project_id=updated.get("project_id"), link="/finance")
    return updated


@bp.post("/invoices/<_id>/payments")
@api("finance")
def add_payment(_id):
    d = request.get_json(force=True) or {}
    inv = t.get("invoices", _id)
    if inv["status"] == "draft":
        inv["status"] = "sent"
    return jsonify(t.out(record_payment(inv, d.get("amount"), d.get("method", "bank"), d.get("ref"),
                                        g.user.get("name"))))


@bp.post("/invoices/<_id>/send")
@api("finance")
def send_invoice(_id):
    inv = t.get("invoices", _id)
    inv = t.update("invoices", _id, {"status": "sent" if inv["status"] == "draft" else inv["status"],
                                     "sent_at": t.now()})
    if not t.find("followups", {"related.id": _id}):
        _payment_reminders(inv)
    return jsonify(t.out(inv))


@bp.post("/invoices/<_id>/release-retention")
@api("finance")
def release_retention(_id):
    inv = t.get("invoices", _id)
    if not inv.get("retention") or inv.get("retention_released"):
        abort(409, "No retention to release")
    rel = t.insert("invoices", _prep_invoice({
        "number": t.next_number("INV", "INV"), "project_id": inv.get("project_id"), "basis": "retention",
        "status": "sent", "items": [{"description": f"Retention release for {inv['number']}", "qty": 1,
                                     "rate": inv["retention"]}], "tax_pct": 0}, None))
    t.update("invoices", _id, {"retention_released": True, "retention_invoice_id": str(rel["_id"])})
    return jsonify(t.out(rel)), 201


@bp.post("/invoices/<_id>/pay-link")
@api("finance")
def pay_link(_id):
    """Simulated payment-gateway link (Razorpay/Stripe in production)."""
    t.get("invoices", _id)
    link = f"/portal/pay/{_id}?ref=plink_{uuid.uuid4().hex[:10]}"
    return jsonify(t.out(t.update("invoices", _id, {"pay_link": link})))


# ---------------- timesheets ----------------
def _prep_timesheet(d, existing):
    d["hours"] = num(d.get("hours"))
    d.setdefault("user_id", g.uid)
    d.setdefault("user_name", g.user.get("name"))
    d.setdefault("date", datetime.utcnow().date().isoformat())
    if d.get("project_id"):
        p = t.get("projects", d["project_id"], required=False)
        d["project_name"] = p["name"] if p else None
    return d


register_crud(bp, "timesheets", "followups", search=("project_name", "note", "user_name"),
              filters=("project_id", "user_id", "stage_id", "date"), prepare=_prep_timesheet, sort=("date", -1))
