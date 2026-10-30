"""Milestone budget control (section 12): live spent, 80% / 100% alerts, variance."""
from flask import g

from .. import tenancy as t
from ..db import db, oid


def stage_spent(project_id, stage_id):
    rows = db.costs.aggregate([
        {"$match": {"company_id": g.cid, "project_id": project_id, "stage_id": stage_id, "status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    rows = list(rows)
    return round(rows[0]["total"], 2) if rows else 0.0


def find_stage(project, stage_id):
    for s in project.get("stages", []):
        if s["id"] == stage_id:
            return s
    return None


def usage_level(budget, spent):
    if not budget:
        return "none"
    pct = spent / budget * 100
    if pct >= 100:
        return "red"
    if pct >= 80:
        return "yellow"
    return "green"


def recalc_stage(project_id, stage_id):
    """Recompute a stage's spent figure and raise an alert the first time it crosses 80% / 100%."""
    project = t.get("projects", project_id)
    stage = find_stage(project, stage_id)
    if not stage:
        return None
    spent = stage_spent(project_id, stage_id)
    level = usage_level(stage.get("budget", 0), spent)
    previous = stage.get("alert_level", "green")
    order = {"none": 0, "green": 0, "yellow": 1, "red": 2}
    db.projects.update_one(
        {"_id": project["_id"], "stages.id": stage_id},
        {"$set": {"stages.$.spent": spent, "stages.$.alert_level": level}})
    if order[level] > order.get(previous, 0):
        pct = round(spent / stage["budget"] * 100) if stage.get("budget") else 0
        text = (f"{project['name']} · {stage['name']}: {pct}% of budget spent"
                + (" — new purchases need manager approval." if level == "red" else "."))
        t.notify(text, level=level, role="pm", project_id=project_id, link=f"/projects/{project_id}")
        if level == "red":
            t.notify(text, level=level, role="owner", project_id=project_id, link=f"/projects/{project_id}")
    return spent


def needs_manager_approval(project_id, stage_id, amount):
    """At or over 100% of the milestone budget every new cost needs a manager's approval."""
    project = t.get("projects", project_id)
    stage = find_stage(project, stage_id)
    if not stage or not stage.get("budget"):
        return False
    return stage_spent(project_id, stage_id) + amount > stage["budget"]


def variance(project):
    rows = []
    for s in project.get("stages", []):
        spent = stage_spent(str(project["_id"]), s["id"])
        budget = s.get("budget", 0) or 0
        rows.append({
            "stage_id": s["id"], "stage": s["name"], "service": s.get("service"),
            "estimate": budget, "spent": spent, "difference": round(budget - spent, 2),
            "pct": round(spent / budget * 100, 1) if budget else None,
            "level": usage_level(budget, spent),
        })
    overspend = list(db.costs.aggregate([
        {"$match": {"company_id": g.cid, "project_id": str(project["_id"]), "overspend_reason": {"$ne": None}}},
        {"$group": {"_id": "$overspend_reason", "total": {"$sum": "$overspend_amount"}}},
    ]))
    return {
        "rows": rows,
        "total_estimate": round(sum(r["estimate"] for r in rows), 2),
        "total_spent": round(sum(r["spent"] for r in rows), 2),
        "overspend_by_reason": {o["_id"]: round(o["total"], 2) for o in overspend},
    }


def project_financials(project):
    pid = str(project["_id"])
    contract = db.contracts.find_one({"company_id": g.cid, "project_id": pid, "status": "active"})
    revenue = contract["value"] if contract else project.get("value", 0) or 0
    cost = sum(c["amount"] for c in db.costs.find({"company_id": g.cid, "project_id": pid, "status": "approved"}))
    invoiced = sum(i.get("total", 0) for i in db.invoices.find({"company_id": g.cid, "project_id": pid,
                                                                  "status": {"$ne": "void"}}))
    received = sum(i.get("paid", 0) for i in db.invoices.find({"company_id": g.cid, "project_id": pid}))
    profit = revenue - cost
    return {
        "contract_value": round(revenue, 2), "cost_to_date": round(cost, 2),
        "budget": round(sum(s.get("budget", 0) or 0 for s in project.get("stages", [])), 2),
        "invoiced": round(invoiced, 2), "received": round(received, 2),
        "receivable": round(invoiced - received, 2),
        "profit": round(profit, 2), "margin_pct": round(profit / revenue * 100, 1) if revenue else None,
    }


def contract_for(project_id):
    return db.contracts.find_one({"company_id": g.cid, "project_id": project_id, "status": "active"})


def project_by_id(project_id):
    return db.projects.find_one({"company_id": g.cid, "_id": oid(project_id)})


def can_set_budget():
    return g.role in ("owner", "pm", "estimator", "accounts")
