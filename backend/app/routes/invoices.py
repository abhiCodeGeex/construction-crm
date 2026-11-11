"""Phase E block 2 — invoices (§5, §12, §1).

* A payment-schedule row of the signed contract is invoiced once it is due (on signing, on its date, or when its
  stage milestone is achieved). The row's amount includes tax, split in the contract's own ratio, so the invoices
  add up to the contract. Only the Owner may invoice an upcoming row early, with a reason.
* Manual invoices (lines × company tax rate unless a line says otherwise) cover extras.
* A draft has no number; sending issues the next INV number, so deleted drafts never leave gaps. A sent invoice is
  changed only by a credit note (CRN) and voided only with a reason (which frees its schedule row).
Finance writers (Owner, PM on the project, Accounts) raise and send; finance readers see. Never Site or portal.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales
from .finance import settings, finance_project
from .lead_money import a_date, money_text
from .lead_steps import num
from .proposals import present_contract, branding

bp = Blueprint("invoices", __name__)


def r2(v):
    return round(v + 1e-9, 2)


def add_days(day, n):
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def totals(lines):
    sub = r2(sum(ln["amount"] for ln in lines))
    tax = r2(sum(ln["tax"] for ln in lines))
    return {"subtotal": sub, "tax": tax, "total": r2(sub + tax)}


def balance(inv):
    return r2(inv["total"] - inv.get("credited", 0) - inv.get("paid", 0))


def present(inv):
    data = serialize(inv)
    data["balance"] = balance(inv) if inv["kind"] != "credit_note" else 0
    data["overdue"] = inv["status"] in ("sent", "part_paid") and inv.get("due_date") and inv["due_date"] < sales.today()
    return data


def load_invoice(iid):
    inv = t.get("invoices", iid)
    if inv.get("project_id"):
        finance_project(inv["project_id"])
    elif g.role not in ("owner", "accounts"):
        abort(404, "invoice not found")
    return inv


def client_of(project=None, contract=None):
    cid_ = (project or {}).get("client_id") or (contract or {}).get("client_id")
    c = db.contacts.find_one({"_id": oid(cid_), "company_id": g.cid}) if cid_ else None
    return {"client_id": cid_, "client_name": (c or {}).get("name") or (contract or {}).get("client_name"),
            "client_email": (c or {}).get("email"), "client_gstin": (c or {}).get("gstin"),
            "client_address": ", ".join(x for x in [(c or {}).get("address"), (c or {}).get("city")] if x) or None}


def require_write(p=None):
    if not can("finance", True):
        abort(403, "Your role cannot raise invoices")
    if p is None and g.role not in ("owner", "accounts"):
        abort(403, "Only the Owner or Accounts can invoice before the project exists")


def base_doc(kind, p, contract=None):
    return {"kind": kind, "number": None, "status": "draft", "project_id": p and str(p["_id"]), "project_name": p and p["name"],
            "project_code": p and p.get("code"), "contract_id": contract and str(contract["_id"]),
            "contract_number": contract and contract["number"], "lead_id": (contract or {}).get("lead_id") or (p or {}).get("lead_id"),
            "date": sales.today(), "due_date": add_days(sales.today(), int(settings()["invoice_due_days"])),
            "tax_label": g.company.get("tax_label") or "Tax", "paid": 0, "credited": 0, "notes": None,
            "created_by_name": g.user.get("name"), **client_of(p, contract)}


# ---------------- from the contract's payment schedule ----------------
@bp.post("/contracts/<cid_>/schedule/<row_id>/invoice")
@api("finance")
def invoice_row(cid_, row_id):
    c = t.get("contracts", cid_)
    p = finance_project(c["project_id"]) if c.get("project_id") else None
    require_write(p)
    view = present_contract(c)
    row = next((r for r in view["payment_schedule"] if r["id"] == row_id), None) or abort(404, "payment not found")
    if row.get("status") in ("invoiced", "paid"):
        abort(409, f"“{row['name']}” is already invoiced")
    early = None
    if row.get("state") != "due":
        reason = ((request.get_json(force=True) or {}).get("early_reason") or "").strip()
        if g.role != "owner" or not reason:
            abort(409, f"“{row['name']}” is not due yet ({row.get('state')}); only the Owner can invoice it early, with a reason")
        early = reason[:300]
    ct = c.get("totals") or {}
    ratio = (ct.get("taxable") or c["value"]) / (ct.get("total") or c["value"]) if c["value"] else 1
    amount = row["amount"]
    taxable = r2(amount * ratio)
    line = {"id": t.sid(), "description": f"{row['name']} ({row['pct']:g}% of contract {c['number']})", "qty": 1,
            "rate": taxable, "amount": taxable, "tax_pct": r2((amount - taxable) / taxable * 100) if taxable else 0, "tax": r2(amount - taxable)}
    inv = t.insert("invoices", {**base_doc("schedule", p, c), "schedule_row_id": row_id, "schedule_row": row["name"],
                                "early_reason": early, "lines": [line], **totals([line])})
    rows = [{**r, "status": "invoiced", "invoice_id": str(inv["_id"])} if r["id"] == row_id else r for r in c["payment_schedule"]]
    db.contracts.update_one({"_id": c["_id"]}, {"$set": {"payment_schedule": rows}})
    if p:
        ev.log(str(p["_id"]), "cost", f"Invoice drafted for “{row['name']}”: {money_text(amount)}" + (f" (early: {early})" if early else ""))
    return jsonify(present(inv)), 201


# ---------------- manual invoices ----------------
def clean_lines(rows):
    if not rows:
        abort(400, "Add at least one line")
    out = []
    default_tax = float(g.company.get("tax_rate") or 0)
    for r in rows[:50]:
        desc = (r.get("description") or "").strip()[:200] or abort(400, "Each line needs a description")
        qty = num(r.get("qty"), f"Quantity for {desc}", required=True, positive=True)
        rate = num(r.get("rate"), f"Rate for {desc}", required=True)
        tax_pct = num(r.get("tax_pct"), "Tax %") if r.get("tax_pct") not in (None, "") else default_tax
        if tax_pct > 100:
            abort(400, "Tax % must be at most 100")
        amount = r2(qty * rate)
        out.append({"id": r.get("id") or t.sid(), "description": desc, "qty": qty, "rate": rate, "amount": amount,
                    "tax_pct": tax_pct, "tax": r2(amount * tax_pct / 100)})
    return out


def clean_dates(d, inv):
    ch = {}
    if "date" in d:
        ch["date"] = a_date(d["date"], "Invoice date")
    if "due_date" in d:
        ch["due_date"] = a_date(d["due_date"], "Due date")
    if ch.get("due_date", inv.get("due_date")) < ch.get("date", inv.get("date")):
        abort(400, "The due date is before the invoice date")
    if "notes" in d:
        ch["notes"] = (d.get("notes") or "").strip()[:1000] or None
    return ch


@bp.post("/projects/<pid>/invoices")
@api("finance")
def manual_invoice(pid):
    p = finance_project(pid)
    require_write(p)
    d = request.get_json(force=True) or {}
    lines = clean_lines(d.get("lines"))
    c = db.contracts.find_one({"company_id": g.cid, "project_id": pid})
    doc = {**base_doc("manual", p, c), "lines": lines, **totals(lines)}
    doc.update(clean_dates(d, doc))
    return jsonify(present(t.insert("invoices", doc))), 201


@bp.put("/invoices/<iid>")
@api("finance")
def edit_invoice(iid):
    inv = load_invoice(iid)
    if inv["status"] != "draft":
        abort(409, "A sent invoice is not edited; issue a credit note instead")
    d = request.get_json(force=True) or {}
    ch = clean_dates(d, inv)
    if "lines" in d:
        if inv["kind"] != "manual":
            abort(400, "A schedule invoice's amount comes from the contract")
        ch["lines"] = clean_lines(d["lines"])
        ch.update(totals(ch["lines"]))
    return jsonify(present(t.update("invoices", iid, ch)))


def free_row(inv):
    if inv.get("schedule_row_id") and inv.get("contract_id"):
        c = db.contracts.find_one({"_id": oid(inv["contract_id"])})
        rows = [{k: v for k, v in r.items() if k not in ("status", "invoice_id")} if r.get("invoice_id") == str(inv["_id"]) else r
                for r in c["payment_schedule"]]
        db.contracts.update_one({"_id": c["_id"]}, {"$set": {"payment_schedule": rows}})


@bp.delete("/invoices/<iid>")
@api("finance")
def delete_invoice(iid):
    inv = load_invoice(iid)
    if inv["status"] != "draft":
        abort(409, "A sent invoice is voided, not deleted")
    free_row(inv)
    t.delete("invoices", iid)
    return jsonify({"ok": True})


def email_text(inv):
    lines = [f"{g.company['name']} — {'Credit note' if inv['kind'] == 'credit_note' else 'Invoice'} {inv['number']}",
             f"Date: {inv['date']}" + (f" · due {inv['due_date']}" if inv["kind"] != "credit_note" else ""),
             f"Project: {inv.get('project_code') or ''} {inv.get('project_name') or ''}".strip(), ""]
    lines += [f"{ln['description']}: {money_text(ln['amount'])} + {inv['tax_label']} {money_text(ln['tax'])}" for ln in inv["lines"]]
    lines += ["", f"Total: {money_text(inv['total'])}"]
    if inv.get("notes"):
        lines += ["", inv["notes"]]
    return "\n".join(lines) + f"\n\nRegards,\n{g.company['name']}"


@bp.post("/invoices/<iid>/send")
@api("finance")
def send_invoice(iid):
    inv = load_invoice(iid)
    if inv["status"] != "draft":
        abort(409, "This invoice is already sent")
    if inv["total"] <= 0:
        abort(400, "An invoice must be for more than 0")
    d = request.get_json(force=True) or {}
    ch = {"number": t.next_number("INV", "INV"), "status": "sent", "sent_at": t.now(), "sent_by": g.user.get("name"),
          "date": inv["date"] if inv["date"] >= sales.today() else sales.today()}
    ch["due_date"] = max(inv["due_date"], ch["date"])
    upd = t.update("invoices", iid, ch)
    result = None
    if d.get("email"):
        result = notify.deliver(g.company, inv.get("client_email"), f"Invoice {upd['number']} from {g.company['name']}", email_text(upd))
        upd = t.update("invoices", iid, {"emailed": result})
    if inv.get("project_id"):
        ev.log(inv["project_id"], "cost", f"Invoice {upd['number']} sent: {money_text(upd['total'])}, due {upd['due_date']}"
               + (f" — email {result}" if result else ""))
    return jsonify(present(upd))


@bp.post("/invoices/<iid>/void")
@api("finance")
def void_invoice(iid):
    inv = load_invoice(iid)
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void an invoice")
    if inv["status"] not in ("sent",) or inv["kind"] == "credit_note":
        abort(409, "Only a sent, unpaid invoice is voided (delete a draft)")
    if inv.get("paid") or inv.get("credited"):
        abort(409, "Money has been received or credited against this invoice")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the invoice is void")
    upd = t.update("invoices", iid, {"status": "void", "void_reason": reason[:300], "voided_at": t.now(), "voided_by": g.user.get("name")})
    free_row(inv)
    if inv.get("project_id"):
        ev.log(inv["project_id"], "cost", f"Invoice {inv['number']} voided — {reason}")
    return jsonify(present(upd))


@bp.post("/invoices/<iid>/credit-note")
@api("finance")
def credit_note(iid):
    inv = load_invoice(iid)
    if inv["kind"] == "credit_note" or inv["status"] not in ("sent", "part_paid", "paid"):
        abort(409, "A credit note is issued against a sent invoice")
    d = request.get_json(force=True) or {}
    amount = r2(num(d.get("amount"), "Amount", required=True, positive=True))
    room = r2(inv["total"] - inv.get("credited", 0))
    if amount > room:
        abort(400, f"A credit note cannot exceed what is left on the invoice ({money_text(room)})")
    reason = (d.get("reason") or "").strip() or abort(400, "Say why the credit is given")
    ratio = inv["subtotal"] / inv["total"] if inv["total"] else 1
    taxable = r2(amount * ratio)
    line = {"id": t.sid(), "description": f"Credit against {inv['number']}: {reason[:150]}", "qty": 1, "rate": taxable,
            "amount": taxable, "tax_pct": r2((amount - taxable) / taxable * 100) if taxable else 0, "tax": r2(amount - taxable)}
    cn = t.insert("invoices", {**{k: inv.get(k) for k in ("project_id", "project_name", "project_code", "contract_id", "contract_number",
                                                           "lead_id", "client_id", "client_name", "client_email", "client_gstin",
                                                           "client_address", "tax_label")},
                               "kind": "credit_note", "number": t.next_number("CRN", "CRN"), "status": "sent", "credit_of": iid,
                               "credit_of_number": inv["number"], "reason": reason[:300], "date": sales.today(), "due_date": None,
                               "paid": 0, "credited": 0, "notes": None, "lines": [line], **totals([line]), "sent_at": t.now(),
                               "created_by_name": g.user.get("name")})
    credited = r2(inv.get("credited", 0) + amount)
    status = "paid" if r2(inv["total"] - credited - inv.get("paid", 0)) <= 0 else inv["status"]
    t.update("invoices", iid, {"credited": credited, "status": status})
    if inv.get("project_id"):
        ev.log(inv["project_id"], "cost", f"Credit note {cn['number']} against {inv['number']}: {money_text(amount)} — {reason}")
    return jsonify(present(cn)), 201


# ---------------- reading ----------------
def visible_query():
    q = {}
    if g.role not in ("owner", "accounts"):
        mine = [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]
        q["project_id"] = {"$in": mine}
    return q


@bp.get("/projects/<pid>/invoices")
@api("finance", write=False)
def project_invoices(pid):
    finance_project(pid)
    rows = [present(i) for i in t.find("invoices", {"project_id": pid}, sort=[("created_at", -1)])]
    c = db.contracts.find_one({"company_id": g.cid, "project_id": pid})
    return jsonify({"invoices": rows, "contract": present_contract(c) if c else None, "can_write": can("finance", True), "can_void": g.role in ("owner", "accounts"),
                    "is_owner": g.role == "owner", "tax_rate": float(g.company.get("tax_rate") or 0)})


@bp.get("/invoices")
@api("finance", write=False)
def list_invoices():
    q = visible_query()
    for k in ("status", "kind", "project_id"):
        if request.args.get(k):
            if k == "project_id" and "project_id" in q and request.args[k] not in q["project_id"]["$in"]:
                return jsonify([])
            q[k] = request.args[k]
    return jsonify([present(i) for i in t.find("invoices", q, sort=[("created_at", -1)], limit=500)])


@bp.get("/invoices/<iid>")
@api("finance", write=False)
def get_invoice(iid):
    inv = load_invoice(iid)
    data = present(inv)
    data["company"] = branding(g.company)
    data["credit_notes"] = [present(c) for c in t.find("invoices", {"credit_of": iid}, sort=[("created_at", 1)])]
    return jsonify(data)
