"""Phase I block 2 — progress claims, retention and client deposits (§12 "invoices by milestone, % complete or progress
claim; advance payments, client deposits for products, retention held and released"; §16 "retention release when the
defects period ends"; §7 "client deposits collected before ordering").

* A contract is billed by its milestone schedule (Phase D/E) or by progress, never both: the basis is fixed once the
  contract has its first invoice. Change-order rows stay on the schedule either way.
* Progress basis: a schedule of values splits the contract value over the stages (default pro rata of the stage
  budgets, else evenly). A claim states each stage's cumulative % complete; the invoice bills the increase since the
  last claim, its tax split in the contract's own ratio (as a schedule row is).
* Retention: a % of every contract invoice (schedule, change order or progress) is held — the invoice's balance leaves
  it out. Release creates a *retention* invoice (no new tax: it was on the original invoices) for up to what is held;
  the defects period ends `defects_days` after the handover date, and the worker reminds Accounts and the PM then.
* Selection deposit: an invoice for a % of the chosen option's price (company setting, default 50 %). Ordering without
  a paid deposit warns, or is refused when the company says so.
Writers: Owner, Accounts, a PM on the project (finance rw). Never Site or portal.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales
from .finance import finance_project, settings as fin_settings
from .lead_money import a_date, money_text
from .lead_steps import num
from .invoices import base_doc, totals, present, r2, require_write

bp = Blueprint("claims", __name__)

BILLING_DEFAULTS = {"basis": "schedule", "retention_pct": 0, "defects_days": 365, "handover_date": None}


def billing(c):
    return {**BILLING_DEFAULTS, **(c.get("billing") or {})}


def contract_invoices(c, kinds=("schedule", "progress")):
    return list(db.invoices.find({"company_id": g.cid, "contract_id": str(c["_id"]), "kind": {"$in": list(kinds)}, "status": {"$ne": "void"}}))


def retention_of(c, amount):
    """What is held back of a contract invoice of this amount (tax included)."""
    return r2(amount * float(billing(c)["retention_pct"] or 0) / 100)


def tax_ratio(c):
    ct = c.get("totals") or {}
    return (ct.get("taxable") or c["value"]) / (ct.get("total") or c["value"]) if c["value"] else 1


def load_contract(cid_):
    c = t.get("contracts", cid_)
    if not c.get("project_id"):
        abort(409, "The contract has no project yet: win the lead first")
    p = finance_project(c["project_id"])
    return c, p


# ---------------- billing basis, retention terms ----------------
@bp.get("/contracts/<cid_>/billing")
@api("finance", write=False)
def get_billing(cid_):
    c, p = load_contract(cid_)
    return jsonify(billing_view(c, p))


def billing_view(c, p):
    b = billing(c)
    held = retention_held(c)
    out = {**b, "has_invoices": bool(contract_invoices(c)), "retention": held, "can_write": can("finance", True)}
    if b["handover_date"]:
        out["defects_end"] = (date.fromisoformat(b["handover_date"]) + timedelta(days=int(b["defects_days"]))).isoformat()
    if b["basis"] == "progress":
        out["values"] = schedule_of_values(c, p)
    return out


@bp.put("/contracts/<cid_>/billing")
@api("finance")
def put_billing(cid_):
    c, p = load_contract(cid_)
    require_write(p)
    d = request.get_json(force=True) or {}
    b = billing(c)
    locked = bool(contract_invoices(c))
    if "basis" in d and d["basis"] != b["basis"]:
        if d["basis"] not in ("schedule", "progress"):
            abort(400, "Bill by the payment schedule or by progress")
        if locked:
            abort(409, "This contract already has invoices: its billing basis is fixed")
        b["basis"] = d["basis"]
    if "retention_pct" in d and d["retention_pct"] != b["retention_pct"]:
        v = num(d["retention_pct"], "Retention %", required=True)
        if v > 20:
            abort(400, "Retention is at most 20%")
        if locked:
            abort(409, "This contract already has invoices: the retention % is fixed")
        b["retention_pct"] = v
    if "defects_days" in d:
        v = int(num(d["defects_days"], "Defects period", required=True))
        if not 0 <= v <= 1830:
            abort(400, "The defects period is 0 to 1830 days")
        b["defects_days"] = v
    if "handover_date" in d:
        b["handover_date"] = a_date(d["handover_date"], "Handover date", required=False)
    if "values" in d and b["basis"] == "progress":
        b["values"] = clean_values(c, p, d["values"])
    t.update("contracts", cid_, {"billing": b})
    ev.log(c["project_id"], "cost", f"Contract {c['number']} billing: {'progress claims' if b['basis'] == 'progress' else 'payment schedule'}"
           + (f", retention {b['retention_pct']:g}%" if b["retention_pct"] else ""))
    return jsonify(billing_view(t.get("contracts", cid_), p))


# ---------------- schedule of values and progress claims ----------------
def base_value(c):
    """The contract value billed by progress: the signed value (change orders keep their own schedule rows)."""
    return float(c["value"])


def schedule_of_values(c, p):
    """Per stage of the contract's service: value, claimed % so far (from the claims, void ones ignored), progress now."""
    stages = [s for s in p.get("stages", []) if s.get("service") == c.get("service")] or p.get("stages", [])
    saved = {v["stage_id"]: v["value"] for v in (billing(c).get("values") or [])}
    if saved:
        vals = {s["id"]: saved.get(s["id"], 0) for s in stages}
    else:
        budgets = {s["id"]: float(s.get("budget") or 0) for s in stages}
        tot = sum(budgets.values())
        vals = {s["id"]: base_value(c) * (budgets[s["id"]] / tot if tot else 1 / len(stages)) for s in stages} if stages else {}
    claimed = {}
    for inv in contract_invoices(c, ("progress",)):
        for ln in inv.get("claim") or []:
            claimed[ln["stage_id"]] = max(claimed.get(ln["stage_id"], 0), ln["to_pct"])
    rows = [{"stage_id": s["id"], "stage": s["name"], "value": r2(vals.get(s["id"], 0)), "claimed_pct": claimed.get(s["id"], 0),
             "progress": s.get("progress", 0), "claimed": r2(vals.get(s["id"], 0) * claimed.get(s["id"], 0) / 100)} for s in stages]
    # rounding: the values always add up to the contract
    if rows and not saved:
        rows[-1]["value"] = r2(rows[-1]["value"] + base_value(c) - sum(r["value"] for r in rows))
    return rows


def clean_values(c, p, rows):
    stage_ids = {s["id"] for s in p.get("stages", [])}
    out = []
    for r in rows or []:
        if r.get("stage_id") not in stage_ids:
            abort(400, "A value line names a stage of this project")
        out.append({"stage_id": r["stage_id"], "value": r2(num(r.get("value"), "Stage value") or 0)})
    if abs(sum(x["value"] for x in out) - base_value(c)) > 0.5:
        abort(400, f"The stage values must add up to the contract value ({money_text(base_value(c))})")
    if contract_invoices(c, ("progress",)):
        abort(409, "Claims exist: the schedule of values is fixed")
    return out


@bp.get("/contracts/<cid_>/claims")
@api("finance", write=False)
def list_claims(cid_):
    c, p = load_contract(cid_)
    if billing(c)["basis"] != "progress":
        abort(409, "This contract is billed by its payment schedule")
    return jsonify({"values": schedule_of_values(c, p), "claims": [present(i) for i in contract_invoices(c, ("progress",))],
                    "retention_pct": billing(c)["retention_pct"]})


@bp.post("/contracts/<cid_>/claims")
@api("finance")
def make_claim(cid_):
    """A progress claim: each stage's cumulative % complete; billed is the increase since the last claim."""
    c, p = load_contract(cid_)
    require_write(p)
    if billing(c)["basis"] != "progress":
        abort(409, "This contract is billed by its payment schedule")
    if any(i["status"] == "draft" for i in contract_invoices(c, ("progress",))):
        abort(409, "Send or delete the draft claim first")
    sov = {r["stage_id"]: r for r in schedule_of_values(c, p)}
    ratio = tax_ratio(c)
    lines, claim = [], []
    for x in (request.get_json(force=True) or {}).get("lines") or []:
        r = sov.get(x.get("stage_id")) or abort(400, "Claim against a stage of the contract")
        pct = num(x.get("pct"), f"% complete of {r['stage']}", required=True)
        if not 0 <= pct <= 100:
            abort(400, "% complete is 0 to 100")
        if pct < r["claimed_pct"]:
            abort(400, f"{r['stage']} was already claimed at {r['claimed_pct']:g}%; a claim is cumulative")
        if pct == r["claimed_pct"]:
            continue
        amount = r2(r["value"] * (pct - r["claimed_pct"]) / 100)
        taxable = r2(amount * ratio)
        lines.append({"id": t.sid(), "description": f"{r['stage']}: {r['claimed_pct']:g}% → {pct:g}% complete", "qty": 1, "rate": taxable,
                      "amount": taxable, "tax_pct": r2((amount - taxable) / taxable * 100) if taxable else 0, "tax": r2(amount - taxable)})
        claim.append({"stage_id": r["stage_id"], "stage": r["stage"], "from_pct": r["claimed_pct"], "to_pct": pct, "amount": amount})
    if not lines:
        abort(400, "Raise the % complete of at least one stage")
    n = len(contract_invoices(c, ("progress",))) + 1
    tot = totals(lines)
    inv = t.insert("invoices", {**base_doc("progress", p, c), "lines": lines, **tot, "claim": claim, "claim_no": n,
                                "schedule_row": f"Progress claim {n}", "retention": retention_of(c, tot["total"])})
    ev.log(c["project_id"], "cost", f"Progress claim {n} drafted: {money_text(tot['total'])}")
    return jsonify(present(inv)), 201


# ---------------- retention ----------------
def retention_held(c):
    held = r2(sum(i.get("retention", 0) for i in contract_invoices(c, ("schedule", "progress")) if i["status"] != "draft"))
    released = r2(sum(i["total"] for i in contract_invoices(c, ("retention",)) if i["status"] != "draft"))
    drafts = r2(sum(i["total"] for i in contract_invoices(c, ("retention",)) if i["status"] == "draft"))
    return {"held": held, "released": released, "draft": drafts, "balance": r2(held - released - drafts)}


@bp.post("/contracts/<cid_>/retention/release")
@api("finance")
def release_retention(cid_):
    c, p = load_contract(cid_)
    require_write(p)
    if g.role not in ("owner", "accounts") and not any(m.get("user_id") == g.uid and m.get("project_role") == "Project Manager" for m in p.get("team", [])):
        abort(403, "Only an Owner, Accounts or the project's PM releases retention")
    h = retention_held(c)
    if h["balance"] <= 0:
        abort(409, "No retention is held on this contract")
    d = request.get_json(force=True) or {}
    amount = r2(num(d.get("amount"), "Amount", positive=True) or h["balance"] * float(d.get("pct") or 100) / 100)
    if amount > h["balance"] + 0.01:
        abort(400, f"Only {money_text(h['balance'])} of retention is held")
    why = (d.get("reason") or "").strip()[:200] or "Retention release"
    line = {"id": t.sid(), "description": why, "qty": 1, "rate": amount, "amount": amount, "tax_pct": 0, "tax": 0}
    inv = t.insert("invoices", {**base_doc("retention", p, c), "lines": [line], **totals([line]), "schedule_row": "Retention release",
                                "notes": "Retention held on earlier invoices; the tax on it was charged on those invoices."})
    ev.log(c["project_id"], "cost", f"Retention release drafted: {money_text(amount)} of {money_text(h['balance'])} held")
    return jsonify(present(inv)), 201


def check_retention(now):
    """Worker (Phase I): the defects period of a contract with retention held ends today -> Accounts and the PM, once."""
    today = now.date()
    for c in db.contracts.find({"company_id": g.cid, "billing.retention_pct": {"$gt": 0}, "billing.handover_date": {"$ne": None}}):
        b = billing(c)
        end = date.fromisoformat(b["handover_date"]) + timedelta(days=int(b["defects_days"]))
        if end > today or (today - end).days > 30:
            continue
        h = retention_held(c)
        if h["balance"] <= 0:
            continue
        p = db.projects.find_one({"_id": oid(c["project_id"])}) or {}
        notify.send("invoice_due", list(dict.fromkeys(notify.role_users("accounts") + ev.managers(p))),
                    f"{p.get('name', '')}: the defects period of contract {c['number']} ended {end.isoformat()} — release the "
                    f"retention held ({money_text(h['balance'])})", f"/app/projects/{c['project_id']}?tab=money",
                    project_id=c["project_id"], key=f"retention:{c['_id']}:{end.isoformat()}")


# ---------------- deposits for selections ----------------
@bp.post("/selections/<sid>/deposit")
@api("finance")
def selection_deposit(sid):
    s = t.get("selections", sid)
    p = finance_project(s["project_id"])
    require_write(p)
    opt = next((o for o in s.get("options", []) if o["id"] == s.get("chosen_option_id")), None) or abort(409, "The client has not chosen yet")
    if s.get("deposit_invoice_id"):
        old = db.invoices.find_one({"_id": oid(s["deposit_invoice_id"])})
        if old and old["status"] != "void":
            abort(409, f"A deposit invoice exists for this item ({old.get('number') or 'draft'})")
    d = request.get_json(force=True) or {}
    pct = num(d.get("pct"), "Deposit %") or fin_settings()["selection_deposit_pct"]
    if not 0 < pct <= 100:
        abort(400, "Deposit % is 1 to 100")
    amount = r2(opt["price"] * pct / 100)
    if amount <= 0:
        abort(409, "The chosen option has no client price")
    tax_pct = float(g.company.get("tax_rate") or 0)
    line = {"id": t.sid(), "description": f"Deposit {pct:g}% for {s['item']}: {opt['name']}" + (f" ({s['room']})" if s.get("room") else ""),
            "qty": 1, "rate": amount, "amount": amount, "tax_pct": tax_pct, "tax": r2(amount * tax_pct / 100)}
    c = db.contracts.find_one({"company_id": g.cid, "project_id": s["project_id"]})
    inv = t.insert("invoices", {**base_doc("deposit", p, c), "lines": [line], **totals([line]), "selection_id": sid,
                                "schedule_row": f"Deposit: {s['item']}"})
    t.update("selections", sid, {"deposit_invoice_id": str(inv["_id"]), "deposit_pct": pct})
    ev.log(s["project_id"], "cost", f"Deposit invoice drafted for {s['item']}: {money_text(inv['total'])}")
    return jsonify(present(inv)), 201


def deposit_state(s):
    """None (no deposit asked), 'paid', or 'unpaid' — read when the item is ordered."""
    if not s.get("deposit_invoice_id"):
        return None
    inv = db.invoices.find_one({"_id": oid(s["deposit_invoice_id"])}, {"status": 1})
    if not inv or inv["status"] == "void":
        return None
    return "paid" if inv["status"] == "paid" else "unpaid"
