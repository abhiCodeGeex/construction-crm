"""Stage budget control (Phase E §12): spent from approved costs, 80 % / 100 % alerts, budget vs actual."""
from flask import g

from ..db import db, oid
from . import notify, project_events as ev

LEVELS = {"none": 0, "green": 0, "amber": 1, "red": 2}


PO_OPEN = ["approved", "sent", "acknowledged", "part_received", "received"]


def ordered_by_stage(pid, exclude_po=None):
    """Phase H: approved purchase-order value not billed yet, per stage (money committed to a supplier)."""
    out = {}
    q = {"company_id": g.cid, "project_id": pid, "status": {"$in": PO_OPEN}}
    if exclude_po:
        q["_id"] = {"$ne": oid(exclude_po)}
    for po in db.purchase_orders.find(q, {"lines": 1}):
        for ln in po.get("lines", []):
            left = max(0.0, ln["qty"] - ln.get("billed_qty", 0) - ln.get("short_closed_qty", 0)) * ln["unit_cost"]
            out[ln["stage_id"]] = round(out.get(ln["stage_id"], 0.0) + left, 2)
    return out


def stage_totals(pid):
    """{stage_id: {"spent": approved, "committed": submitted, "ordered": open PO value not billed}} for one project."""
    out = {}
    for r in db.costs.aggregate([{"$match": {"company_id": g.cid, "project_id": pid, "status": {"$in": ["approved", "submitted"]}}},
                                 {"$group": {"_id": {"s": "$stage_id", "st": "$status"}, "total": {"$sum": "$amount"}}}]):
        row = out.setdefault(r["_id"]["s"], {"spent": 0.0, "committed": 0.0, "ordered": 0.0})
        row["spent" if r["_id"]["st"] == "approved" else "committed"] = round(r["total"], 2)
    for sid, v in ordered_by_stage(pid).items():
        out.setdefault(sid, {"spent": 0.0, "committed": 0.0, "ordered": 0.0})["ordered"] = v
    return out


def over_budget_po(p, stage_id, amount, exclude_po=None):
    """How much a purchase order takes a stage over its budget, counting what is spent, waiting approval and already
    ordered on other POs (H: budget is checked when money is committed)."""
    stage = next((s for s in p.get("stages", []) if s["id"] == stage_id), None)
    budget = (stage or {}).get("budget") or 0
    if not budget:
        return 0.0
    pid = str(p["_id"])
    tt = stage_totals(pid).get(stage_id, {})
    used = tt.get("spent", 0) + tt.get("committed", 0) + ordered_by_stage(pid, exclude_po).get(stage_id, 0)
    return round(max(0.0, used + amount - budget) - max(0.0, used - budget), 2)


def usage_level(budget, spent):
    if not budget:
        return "none"
    pct = spent / budget * 100
    return "red" if pct >= 100 else "amber" if pct >= 80 else "green"


def recalc_stage(p, stage_id):
    """Store the stage's spent figure and tell people the first time it crosses 80 % and 100 %.
    When a void brings it back below a level, the next crossing is announced again."""
    stage = next((s for s in p.get("stages", []) if s["id"] == stage_id), None)
    if not stage:
        return
    pid = str(p["_id"])
    spent = stage_totals(pid).get(stage_id, {}).get("spent", 0.0)
    level = usage_level(stage.get("budget") or 0, spent)
    before = stage.get("alert_level") or "none"
    rounds = stage.get("alert_round", 0) + (1 if LEVELS[level] < LEVELS[before] else 0)
    db.projects.update_one({"_id": p["_id"], "stages.id": stage_id},
                           {"$set": {"stages.$.spent": spent, "stages.$.alert_level": level, "stages.$.alert_round": rounds}})
    if LEVELS[level] > LEVELS[before]:
        pct = round(spent / stage["budget"] * 100)
        text = f"{p['name']} · {stage['name']}: {pct}% of its budget spent"
        people = ev.managers(p) + (ev.owners() if level == "red" else [])
        notify.send("budget_alert", list(dict.fromkeys(people)), text + (" — over budget" if level == "red" else ""),
                    f"/app/projects/{pid}", key=f"budget-{level}:{stage_id}:{rounds}", project_id=pid,
                    level="warn", skip_self=False)


def over_budget(p, stage_id, amount, exclude=None):
    """How much this cost takes the stage over its budget (0 when it fits or the stage has no budget)."""
    stage = next((s for s in p.get("stages", []) if s["id"] == stage_id), None)
    budget = (stage or {}).get("budget") or 0
    if not budget:
        return 0.0
    q = {"company_id": g.cid, "project_id": str(p["_id"]), "stage_id": stage_id, "status": "approved"}
    if exclude:
        q["_id"] = {"$ne": oid(exclude)}
    spent = sum(c["amount"] for c in db.costs.find(q, {"amount": 1}))
    return round(max(0.0, spent + amount - budget) - max(0.0, spent - budget), 2)


def budget_rows(p):
    """Budget vs actual per stage, for the dashboard and the project's Money tab."""
    totals = stage_totals(str(p["_id"]))
    rows = []
    for s in p.get("stages", []):
        budget = s.get("budget") or 0
        tt = totals.get(s["id"], {"spent": 0.0, "committed": 0.0, "ordered": 0.0})
        rows.append({"id": s["id"], "name": s["name"], "service": s.get("service"), "budget": budget,
                     "spent": tt["spent"], "committed": tt["committed"], "ordered": tt.get("ordered", 0.0),
                     "pct": round(tt["spent"] / budget * 100, 1) if budget else None,
                     "level": usage_level(budget, tt["spent"])})
    return rows
