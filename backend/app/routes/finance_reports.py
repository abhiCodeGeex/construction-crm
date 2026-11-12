"""Phase E block 4 — money reports (§12).

Per project: contract -> revised value, budget, committed, actual, invoiced, received, receivable, margin.
Company: the same per project, receivables ageing, cost by category and vendor, change orders by reason, stages over
budget. Anyone with Reports sees the totals; cost, budget and margin only roles that can see finance (never Site)."""
from flask import Blueprint, jsonify, g

from ..db import db
from ..security import api, can
from .finance import finance_project
from .change_orders import CO_REASONS

bp = Blueprint("finance_reports", __name__)


def r2(v):
    return round((v or 0) + 1e-9, 2)


def money_view():
    return can("finance") and not g.hide_costs


def summary(p):
    pid = str(p["_id"])
    contract = db.contracts.find_one({"company_id": g.cid, "project_id": pid})
    contract_value = contract["value"] if contract else None
    revised = (contract.get("revised_value") or contract["value"]) if contract else p.get("value") or 0
    costs = {}
    for r in db.costs.aggregate([{"$match": {"company_id": g.cid, "project_id": pid, "status": {"$in": ["approved", "submitted"]}}},
                                 {"$group": {"_id": "$status", "total": {"$sum": "$amount"}}}]):
        costs[r["_id"]] = r["total"]
    invoiced = paid = credited = held = 0.0
    for inv in db.invoices.find({"company_id": g.cid, "project_id": pid, "status": {"$nin": ["draft", "void"]}, "kind": {"$ne": "credit_note"}}):
        # retention held (Phase I) is not billed until its release invoice
        invoiced += inv["total"] - inv.get("retention", 0)
        held += inv.get("retention", 0) - (inv["total"] if inv["kind"] == "retention" else 0)
        paid += inv.get("paid", 0)
        credited += inv.get("credited", 0)
    cos = {}
    for co in db.change_orders.find({"company_id": g.cid, "project_id": pid}, {"status": 1, "totals": 1}):
        row = cos.setdefault(co["status"], {"count": 0, "total": 0.0})
        row["count"] += 1
        row["total"] = r2(row["total"] + (co.get("totals") or {}).get("total", 0))
    out = {"project_id": pid, "code": p.get("code"), "name": p["name"], "status": p.get("status"),
           "contract_value": contract_value, "revised_value": r2(revised), "invoiced": r2(invoiced - credited), "received": r2(paid),
           "receivable": r2(invoiced - credited - paid), "to_invoice": r2(revised - (invoiced - credited)),
           "retention_held": r2(held), "change_orders": cos}
    if money_view():
        actual = r2(costs.get("approved"))
        out.update(budget=r2(sum(s.get("budget") or 0 for s in p.get("stages", []))), actual=actual, committed=r2(costs.get("submitted")),
                   margin=r2(revised - actual), margin_pct=round((revised - actual) / revised * 100, 1) if revised else None)
    return out


@bp.get("/projects/<pid>/finance")
@api("finance", write=False)
def project_finance(pid):
    return jsonify(summary(finance_project(pid)))


@bp.get("/reports/finance")
@api("reports", write=False)
def company_finance():
    from .invoices import BUCKETS, bucket, balance
    from datetime import date
    from ..services import sales
    q = {"company_id": g.cid}
    if g.role not in ("owner", "accounts"):
        q["team.user_id"] = g.uid
    projects = list(db.projects.find(q))
    pids = [str(p["_id"]) for p in projects]
    rows = [summary(p) for p in projects]
    keys = ("revised_value", "invoiced", "received", "receivable", "to_invoice") + (("budget", "actual", "committed", "margin") if money_view() else ())
    total = {k: r2(sum(r.get(k) or 0 for r in rows)) for k in keys}
    today = date.fromisoformat(sales.today())
    ageing = {k: 0.0 for k, _ in BUCKETS}
    for inv in db.invoices.find({"company_id": g.cid, "project_id": {"$in": pids}, "status": {"$in": ["sent", "part_paid"]},
                                 "kind": {"$ne": "credit_note"}}):
        late = (today - date.fromisoformat(inv["due_date"])).days if inv.get("due_date") else 0
        ageing[bucket(late)] = r2(ageing[bucket(late)] + balance(inv))
    by_reason = {}
    for co in db.change_orders.find({"company_id": g.cid, "project_id": {"$in": pids}, "status": "approved"}):
        row = by_reason.setdefault(co["reason"], {"reason": CO_REASONS.get(co["reason"], co["reason"]), "count": 0, "total": 0.0, "cost": 0.0})
        row["count"] += 1
        row["total"] = r2(row["total"] + co["totals"]["total"])
        row["cost"] = r2(row["cost"] + co["totals"]["cost"])
    data = {"projects": rows, "total": total, "ageing": [{"key": k, "label": label, "total": ageing[k]} for k, label in BUCKETS],
            "change_orders": sorted(by_reason.values(), key=lambda x: -x["total"]), "money_view": money_view()}
    if money_view():
        match = {"company_id": g.cid, "project_id": {"$in": pids}, "status": "approved"}
        data["by_category"] = [{"category": r["_id"], "total": r2(r["total"])} for r in db.costs.aggregate(
            [{"$match": match}, {"$group": {"_id": "$category", "total": {"$sum": "$amount"}}}, {"$sort": {"total": -1}}])]
        data["by_vendor"] = [{"vendor": r["_id"] or "No vendor", "total": r2(r["total"])} for r in db.costs.aggregate(
            [{"$match": match}, {"$group": {"_id": "$vendor_name", "total": {"$sum": "$amount"}}}, {"$sort": {"total": -1}}, {"$limit": 15}])]
        over = []
        for p in projects:
            for s in p.get("stages", []):
                if s.get("budget") and (s.get("spent") or 0) > s["budget"]:
                    over.append({"project": f"{p.get('code')} {p['name']}", "project_id": str(p["_id"]), "stage": s["name"],
                                 "budget": s["budget"], "spent": s["spent"], "over": r2(s["spent"] - s["budget"])})
        data["over_budget"] = sorted(over, key=lambda x: -x["over"])
    else:
        for c in data["change_orders"]:
            c.pop("cost", None)
    return jsonify(data)
