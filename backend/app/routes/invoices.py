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
from ..services.defaults import PAYMENT_MODES
from .proposals import present_contract, branding
from ..services import gst

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
    """What the client owes now: retention held back (Phase I) is not due until it is released."""
    return r2(inv["total"] - inv.get("retention", 0) - inv.get("credited", 0) - inv.get("paid", 0))


def status_for(inv):
    if balance(inv) <= 0:
        return "paid"
    return "part_paid" if inv.get("paid") else "sent"


def gst_of(inv):
    """Stored when the invoice is issued; worked out live for a draft (Phase I block 1)."""
    if inv.get("gst") is not None or inv.get("number"):
        return inv.get("gst")
    return gst.split(inv.get("tax", 0), inv.get("client_gstin"), inv.get("client_state"))


def present(inv):
    data = serialize(inv)
    data["gst"] = gst_of(inv)
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
            "client_email": (c or {}).get("email"), "client_gstin": (c or {}).get("gstin"), "client_state": (c or {}).get("state"),
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
    from .claims import billing, retention_of
    if billing(c)["basis"] == "progress" and not row.get("co_id"):
        abort(409, "This contract is billed by progress claims, not by its payment schedule")
    early = None
    if row.get("state") != "due":
        reason = ((request.get_json(force=True) or {}).get("early_reason") or "").strip()
        if g.role != "owner" or not reason:
            abort(409, f"“{row['name']}” is not due yet ({row.get('state')}); only the Owner can invoice it early, with a reason")
        early = reason[:300]
    ct = c.get("totals") or {}
    ratio = (ct.get("taxable") or c["value"]) / (ct.get("total") or c["value"]) if c["value"] else 1
    amount = row["amount"]
    taxable = r2(row["taxable"]) if "taxable" in row else r2(amount * ratio)  # a change order row carries its own tax
    desc = row["name"] if row.get("co_id") else f"{row['name']} ({row['pct']:g}% of contract {c['number']})"
    line = {"id": t.sid(), "description": desc, "qty": 1,
            "rate": taxable, "amount": taxable, "tax_pct": r2((amount - taxable) / taxable * 100) if taxable else 0, "tax": r2(amount - taxable)}
    inv = t.insert("invoices", {**base_doc("schedule", p, c), "schedule_row_id": row_id, "schedule_row": row["name"],
                                "early_reason": early, "lines": [line], **totals([line]), "retention": retention_of(c, amount)})
    rows = [{**r, "status": "invoiced", "invoice_id": str(inv["_id"])} if r["id"] == row_id else r for r in c["payment_schedule"]]
    db.contracts.update_one({"_id": c["_id"]}, {"$set": {"payment_schedule": rows}})
    if p:
        ev.log(str(p["_id"]), "cost", f"Invoice drafted for “{row['name']}”: {money_text(amount)}" + (f" (early: {early})" if early else ""))
    return jsonify(present(inv)), 201


# ---------------- manual invoices ----------------
def hsn_code(v):
    """HSN (goods) or SAC (services) code: 4 to 8 digits, optional."""
    v = str(v or "").strip()
    if v and not (v.isdigit() and 4 <= len(v) <= 8):
        abort(400, "HSN / SAC code must be 4 to 8 digits")
    return v or None


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
                    "tax_pct": tax_pct, "tax": r2(amount * tax_pct / 100), "hsn": hsn_code(r.get("hsn"))})
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
    ch["gst"] = gst.split(inv["tax"], inv.get("client_gstin"), inv.get("client_state"))
    upd = t.update("invoices", iid, ch)
    result = None
    if d.get("email"):
        from ..services import payments as pay
        text = email_text(upd)
        if pay.enabled(g.company) and upd.get("project_id"):
            from .payments import make_link
            text += f"\n\nPay online: {make_link(upd)['url']}"
        result = notify.deliver(g.company, inv.get("client_email"), f"Invoice {upd['number']} from {g.company['name']}", text)
        upd = t.update("invoices", iid, {"emailed": result})
    if d.get("whatsapp") and upd.get("client_id"):
        from ..services import messaging, payments as pay
        c = db.contacts.find_one({"_id": oid(upd["client_id"]), "company_id": g.cid}) or {}
        msg = f"{g.company['name']}: invoice {upd['number']} for {money_text(upd['total'])}, due {upd['due_date']}."
        if pay.enabled(g.company) and upd.get("project_id"):
            from .payments import make_link
            msg += f" Pay online: {make_link(upd)['url']}"
        upd = t.update("invoices", iid, {"whatsapp": messaging.notify_contact(c, msg, "invoice", iid) or "not sent"})
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
    room = balance(inv)
    if amount > room:
        abort(400, f"A credit note cannot exceed what is left to pay on the invoice ({money_text(room)})")
    reason = (d.get("reason") or "").strip() or abort(400, "Say why the credit is given")
    ratio = inv["subtotal"] / inv["total"] if inv["total"] else 1
    taxable = r2(amount * ratio)
    line = {"id": t.sid(), "description": f"Credit against {inv['number']}: {reason[:150]}", "qty": 1, "rate": taxable,
            "amount": taxable, "tax_pct": r2((amount - taxable) / taxable * 100) if taxable else 0, "tax": r2(amount - taxable)}
    cn = t.insert("invoices", {**{k: inv.get(k) for k in ("project_id", "project_name", "project_code", "contract_id", "contract_number",
                                                           "lead_id", "client_id", "client_name", "client_email", "client_gstin",
                                                           "client_state", "client_address", "tax_label")},
                               "gst": gst.split(r2(amount - taxable), inv.get("client_gstin"), inv.get("client_state")),
                               "kind": "credit_note", "number": t.next_number("CRN", "CRN"), "status": "sent", "credit_of": iid,
                               "credit_of_number": inv["number"], "reason": reason[:300], "date": sales.today(), "due_date": None,
                               "paid": 0, "credited": 0, "notes": None, "lines": [line], **totals([line]), "sent_at": t.now(),
                               "created_by_name": g.user.get("name")})
    credited = r2(inv.get("credited", 0) + amount)
    t.update("invoices", iid, {"credited": credited, "status": status_for({**inv, "credited": credited})})
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
    if request.args.get("status") == "unpaid":
        q["status"] = {"$in": ["sent", "part_paid"]}
        q["kind"] = {"$ne": "credit_note"}
    for k in ("status", "kind", "project_id"):
        if request.args.get(k) and not (k == "status" and request.args[k] == "unpaid"):
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


# ---------------- block 3: receipts against invoices ----------------
def check_payment(d):
    """Same rules as a lead receipt (lead_money.check_receipt): mode, amount, not in the future, reference unless cash."""
    if d.get("mode") not in PAYMENT_MODES:
        abort(400, f"Mode must be one of: {', '.join(PAYMENT_MODES)}")
    amount = r2(num(d.get("amount"), "Amount", required=True, positive=True))
    day = a_date(d.get("date"), "Date")
    if day > sales.today():
        abort(400, "A receipt cannot be dated in the future")
    if d["mode"] != "Cash" and not (d.get("reference") or "").strip():
        abort(400, "Enter the transaction / cheque reference")
    return amount, day


def apply_payment(inv, amount, entry):
    """Add (or with a negative amount take back) money received against an invoice; status follows the balance."""
    paid = r2(inv.get("paid", 0) + amount)
    pays = [x for x in inv.get("payments") or [] if x["id"] != entry["id"]] + ([entry] if amount > 0 else [])
    upd = t.update("invoices", str(inv["_id"]), {"paid": paid, "payments": pays, "status": status_for({**inv, "paid": paid})})
    if upd.get("schedule_row_id") and upd.get("contract_id") and (upd["status"] == "paid") != (inv["status"] == "paid"):
        _row_status(upd, "paid" if upd["status"] == "paid" else "invoiced")
    return upd


def _row_status(inv, status):
    c = db.contracts.find_one({"_id": oid(inv["contract_id"])})
    if c:
        rows = [{**r, "status": status} if r.get("invoice_id") == str(inv["_id"]) else r for r in c["payment_schedule"]]
        db.contracts.update_one({"_id": c["_id"]}, {"$set": {"payment_schedule": rows}})


def open_invoice(iid, pid):
    inv = db.invoices.find_one({"_id": oid(iid), "company_id": g.cid}) if iid else None
    if not inv or inv.get("project_id") != pid or inv["kind"] == "credit_note" or inv["status"] not in ("sent", "part_paid"):
        abort(400, "Choose an open (sent, not fully paid) invoice of this project")
    return inv


def tell(p, text):
    notify.send("receipt_recorded", list(dict.fromkeys(ev.managers(p) + notify.role_users("accounts"))), text,
                f"/app/projects/{p['_id']}?tab=money", project_id=str(p["_id"]))


@bp.get("/projects/<pid>/receipts")
@api("finance", write=False)
def project_receipts(pid):
    finance_project(pid)
    advances = [serialize(r) for r in t.find("lead_receipts", {"project_id": pid, "status": "received"}, sort=[("date", 1)])]
    return jsonify({"receipts": serialize(t.find("receipts", {"project_id": pid}, sort=[("date", -1), ("created_at", -1)])),
                    "advances": advances, "modes": PAYMENT_MODES, "can_write": can("finance", True),
                    "can_void": g.role in ("owner", "accounts")})


@bp.post("/projects/<pid>/receipts")
@api("finance")
def add_receipt(pid):
    p = finance_project(pid)
    d = request.get_json(force=True) or {}
    amount, day = check_payment(d)
    allocs, seen = [], set()
    for a in d.get("allocations") or []:
        if a.get("invoice_id") in seen:
            abort(400, "Each invoice once per receipt")
        seen.add(a.get("invoice_id"))
        inv = open_invoice(a.get("invoice_id"), pid)
        part = r2(num(a.get("amount"), f"Amount for {inv['number']}", required=True, positive=True))
        if part > balance(inv):
            abort(400, f"{inv['number']} has {money_text(balance(inv))} left to pay")
        allocs.append((inv, part))
    spread = r2(sum(x for _, x in allocs))
    if spread > amount + 0.01:
        abort(400, f"The allocations ({money_text(spread)}) are more than the {money_text(amount)} received")
    if not allocs and not d.get("on_account"):
        abort(400, "Say which invoice(s) this payment settles, or keep it on account")
    if spread < amount - 0.01 and not d.get("on_account"):
        abort(400, f"Allocate the whole {money_text(amount)} to invoices, or keep the rest on account")
    rc = record_receipt(p, amount, day, d["mode"], (d.get("reference") or "").strip() or None, (d.get("note") or "").strip()[:300] or None, allocs)
    return jsonify(serialize(rc)), 201


@bp.post("/receipts/<rid>/apply")
@api("finance")
def apply_on_account(rid):
    """Money held on account (Phase I block 1) settles an invoice later, in part or in full."""
    rc = t.get("receipts", rid)
    p = finance_project(rc["project_id"])
    if not can("finance", True):
        abort(403, "Your role cannot allocate receipts")
    if rc["status"] != "received" or rc.get("unallocated", 0) <= 0:
        abort(409, "Nothing of this receipt is held on account")
    d = request.get_json(force=True) or {}
    inv = open_invoice(d.get("invoice_id"), rc["project_id"])
    part = r2(num(d.get("amount"), "Amount", positive=True) or min(rc["unallocated"], balance(inv)))
    if part > rc["unallocated"] + 0.01:
        abort(400, f"Only {money_text(rc['unallocated'])} of {rc['number']} is on account")
    if part > balance(inv) + 0.01:
        abort(400, f"{inv['number']} has {money_text(balance(inv))} left to pay")
    allocs = [a for a in rc["allocations"] if a["invoice_id"] != str(inv["_id"])]
    before = next((a["amount"] for a in rc["allocations"] if a["invoice_id"] == str(inv["_id"])), 0)
    allocs.append({"invoice_id": str(inv["_id"]), "invoice_number": inv["number"], "amount": r2(before + part)})
    apply_payment(inv, part, {"id": f"{rid}:{len(rc['allocations'])}", "kind": "receipt", "number": rc["number"], "amount": part, "date": sales.today()})
    upd = t.update("receipts", rid, {"allocations": allocs, "unallocated": r2(rc["unallocated"] - part)})
    text = f"{money_text(part)} of receipt {rc['number']} (on account) applied to {inv['number']}"
    ev.log(rc["project_id"], "cost", text)
    tell(p, text)
    return jsonify(serialize(upd))


def record_receipt(p, amount, day, mode, reference, note, allocs, extra=None):
    """Money received against invoices — recorded by staff, or by a signed online-payment webhook (Phase G)."""
    pid = str(p["_id"])
    rc = t.insert("receipts", {"number": t.next_number("RCT", "RCT"), "project_id": pid, "project_name": p["name"],
                               "project_code": p.get("code"), "client_id": p.get("client_id"), "amount": amount, "date": day,
                               "mode": mode, "reference": reference, "note": note, "status": "received",
                               "allocations": [{"invoice_id": str(i["_id"]), "invoice_number": i["number"], "amount": x} for i, x in allocs],
                               "unallocated": r2(amount - sum(x for _, x in allocs)),
                               "created_by_name": g.user.get("name"), **(extra or {})})
    for inv, part in allocs:
        apply_payment(inv, part, {"id": str(rc["_id"]), "kind": "receipt", "number": rc["number"], "amount": part, "date": day})
    text = f"{money_text(amount)} received on {p['name']} ({mode}), receipt {rc['number']} for " + \
        (", ".join(i["number"] for i, _ in allocs) or "no invoice yet") + \
        (f" — {money_text(rc['unallocated'])} held on account" if rc["unallocated"] > 0 else "")
    ev.log(pid, "cost", text)
    tell(p, text)
    return rc


@bp.post("/receipts/<rid>/void")
@api("finance")
def void_receipt(rid):
    rc = t.get("receipts", rid)
    finance_project(rc["project_id"])
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void a receipt")
    if rc["status"] == "void":
        abort(409, "Already void")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the receipt is void")
    for a in rc["allocations"]:
        inv = db.invoices.find_one({"_id": oid(a["invoice_id"])})
        if inv:
            # the receipt may have reached this invoice in several parts (on account, Phase I): take all of them back
            parts = [x for x in inv.get("payments") or [] if x["id"] == rid or x["id"].startswith(rid + ":")]
            paid = r2(inv.get("paid", 0) - (sum(x["amount"] for x in parts) if parts else a["amount"]))
            pays = [x for x in inv.get("payments") or [] if x not in parts]
            upd_inv = t.update("invoices", str(inv["_id"]), {"paid": paid, "payments": pays, "status": status_for({**inv, "paid": paid})})
            if upd_inv.get("schedule_row_id") and upd_inv.get("contract_id") and inv["status"] == "paid" and upd_inv["status"] != "paid":
                _row_status(upd_inv, "invoiced")
    upd = t.update("receipts", rid, {"status": "void", "unallocated": 0, "void_reason": reason[:300], "voided_at": t.now(), "voided_by": g.user.get("name")})
    ev.log(rc["project_id"], "cost", f"Receipt {rc['number']} ({money_text(rc['amount'])}) voided: {reason}")
    return jsonify(serialize(upd))


@bp.post("/lead_receipts/<rid>/apply")
@api("finance")
def apply_advance(rid):
    """An advance taken on the lead (moved to the project on the win) settles one of the project's invoices."""
    adv = t.get("lead_receipts", rid)
    if not adv.get("project_id"):
        abort(409, "This advance is not on a project yet")
    p = finance_project(adv["project_id"])
    if adv.get("status") != "received" or adv.get("applied_invoice_id"):
        abort(409, "This advance is already applied or void")
    inv = open_invoice((request.get_json(force=True) or {}).get("invoice_id"), adv["project_id"])
    if adv["amount"] > balance(inv) + 0.01:
        abort(400, f"The advance ({money_text(adv['amount'])}) is more than {inv['number']} has left to pay ({money_text(balance(inv))})")
    apply_payment(inv, adv["amount"], {"id": rid, "kind": "advance", "number": adv["number"], "amount": adv["amount"], "date": adv["date"]})
    t.update("lead_receipts", rid, {"applied_invoice_id": str(inv["_id"]), "applied_invoice_number": inv["number"], "applied_at": t.now()})
    text = f"Advance {adv['number']} ({money_text(adv['amount'])}) applied to {inv['number']}"
    ev.log(adv["project_id"], "cost", text)
    tell(p, text)
    return jsonify(present(t.get("invoices", str(inv["_id"]))))


# ---------------- receivables ----------------
BUCKETS = (("current", "Not yet due"), ("d30", "1-30 days late"), ("d60", "31-60 days late"), ("d90", "61-90 days late"),
           ("d90p", "Over 90 days late"))


def bucket(days_late):
    if days_late <= 0:
        return "current"
    return "d30" if days_late <= 30 else "d60" if days_late <= 60 else "d90" if days_late <= 90 else "d90p"


@bp.get("/finance/receivables")
@api("finance", write=False)
def receivables():
    from datetime import date
    q = {**visible_query(), "status": {"$in": ["sent", "part_paid"]}, "kind": {"$ne": "credit_note"}}
    today = date.fromisoformat(sales.today())
    rows, sums, by_client = [], {k: 0.0 for k, _ in BUCKETS}, {}
    for inv in t.find("invoices", q, sort=[("due_date", 1)]):
        late = (today - date.fromisoformat(inv["due_date"])).days if inv.get("due_date") else 0
        b, bal = bucket(late), balance(inv)
        sums[b] = r2(sums[b] + bal)
        name = inv.get("client_name") or "-"
        c = by_client.setdefault(name, {"client": name, "balance": 0.0, "oldest_days": 0})
        c["balance"] = r2(c["balance"] + bal)
        c["oldest_days"] = max(c["oldest_days"], late)
        rows.append({**present(inv), "days_late": max(late, 0), "bucket": b})
    return jsonify({"rows": rows, "buckets": [{"key": k, "label": label, "total": sums[k]} for k, label in BUCKETS],
                    "total": r2(sum(sums.values())), "by_client": sorted(by_client.values(), key=lambda x: -x["balance"])})


# ---------------- GST summary for filing (Phase I block 1) ----------------
@bp.get("/finance/gst")
@api("finance", write=False)
def gst_summary():
    """Output tax of issued invoices in a month (credit notes taken off): totals and per HSN / SAC code."""
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can see the GST summary")
    month = request.args.get("month") or sales.today()[:7]
    if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
        abort(400, "Month must be YYYY-MM")
    tot = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "invoices": 0, "credit_notes": 0}
    by_hsn, rows = {}, []
    zero = {"cgst": 0, "sgst": 0, "igst": 0, "mode": None, "place_of_supply": None}
    # a retention release carries no tax of its own: its tax was on the invoices it was held from
    for inv in t.find("invoices", {"status": {"$ne": "void"}, "number": {"$ne": None}, "date": {"$regex": f"^{month}"},
                                   "kind": {"$ne": "retention"}}, sort=[("date", 1)]):
        sign = -1 if inv["kind"] == "credit_note" else 1
        split = inv.get("gst") or gst.split(inv["tax"], inv.get("client_gstin"), inv.get("client_state")) or zero
        tot["credit_notes" if sign < 0 else "invoices"] += 1
        tot["taxable"] = r2(tot["taxable"] + sign * inv["subtotal"])
        for k in ("cgst", "sgst", "igst"):
            tot[k] = r2(tot[k] + sign * split[k])
        for ln in inv["lines"]:
            h = by_hsn.setdefault(ln.get("hsn") or "—", {"hsn": ln.get("hsn") or "—", "taxable": 0.0, "tax": 0.0})
            h["taxable"] = r2(h["taxable"] + sign * ln["amount"])
            h["tax"] = r2(h["tax"] + sign * ln["tax"])
        rows.append({"id": str(inv["_id"]), "number": inv["number"], "kind": inv["kind"], "date": inv["date"],
                     "client": inv.get("client_name"), "client_gstin": inv.get("client_gstin"), "place_of_supply": split.get("place_of_supply"),
                     "taxable": sign * inv["subtotal"], **{k: sign * split[k] for k in ("cgst", "sgst", "igst")}})
    return jsonify({"month": month, "enabled": gst.enabled(), "totals": tot, "by_hsn": sorted(by_hsn.values(), key=lambda x: x["hsn"]),
                    "rows": rows})
