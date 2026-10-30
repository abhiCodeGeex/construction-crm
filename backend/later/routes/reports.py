"""Home dashboard and reports (section 14)."""
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, g

from .. import tenancy as t
from ..db import db
from ..security import api, can
from ..services import budget as B

bp = Blueprint("reports", __name__)


@bp.get("/dashboard")
@api(None)
def dashboard():
    today = datetime.utcnow().date().isoformat()
    data = {"today": today}
    if can("leads"):
        open_leads = t.find("leads", {"status": "open"})
        data["pipeline"] = {"open": len(open_leads), "value": sum(l.get("budget", 0) for l in open_leads)}
    if can("projects"):
        projects = t.find("projects", {"status": {"$in": ["active", "planning"]}})
        data["projects"] = {"active": len(projects),
                            "delayed": sum(1 for p in projects for s in p.get("stages", [])
                                           if s.get("status") != "done" and s.get("end") and s["end"] < today)}
        data["budget_alerts"] = [{"project": p["name"], "project_id": str(p["_id"]), "stage": s["name"],
                                  "level": s["alert_level"]}
                                 for p in projects for s in p.get("stages", [])
                                 if s.get("alert_level") in ("yellow", "red")]
    if can("finance") and not g.hide_costs:
        inv = t.find("invoices", {"status": {"$in": ["sent", "partial"]}})
        data["receivables"] = round(sum(i.get("amount_due", 0) - i.get("paid", 0) for i in inv), 2)
        data["overdue_invoices"] = sum(1 for i in inv if i.get("due_date", today) < today)
    data["followups_today"] = db.followups.count_documents({"company_id": g.cid, "status": "open",
                                                            "due": {"$lte": today},
                                                            "$or": [{"owner_id": g.uid}, {"role": g.role}]})
    data["pending_approvals"] = {
        "costs": db.costs.count_documents({"company_id": g.cid, "status": "pending_approval"}),
        "purchase_orders": db.purchase_orders.count_documents({"company_id": g.cid, "status": "pending_approval"}),
        "change_orders": db.change_orders.count_documents({"company_id": g.cid, "status": "pending_client"}),
    }
    data["open_messages"] = db.messages.count_documents({"company_id": g.cid, "status": "open",
                                                         "routed_to_role": g.role})
    return jsonify(data)


@bp.get("/reports/sales")
@api("reports", write=False)
def sales():
    leads = t.find("leads")
    users = {str(u["_id"]): u["name"] for u in t.find("users")}

    def group(key):
        out = defaultdict(lambda: {"total": 0, "won": 0, "lost": 0, "open": 0, "value": 0, "won_value": 0})
        for l in leads:
            k = (users.get(l.get(key)) if key == "owner_id" else l.get(key)) or "—"
            r = out[k]
            r["total"] += 1
            r[l.get("status", "open")] = r.get(l.get("status", "open"), 0) + 1
            r["value"] += l.get("budget", 0)
            if l.get("status") == "won":
                r["won_value"] += l.get("budget", 0)
        rows = []
        for k, r in out.items():
            closed = r["won"] + r["lost"]
            rows.append({"key": k, **r, "conversion": round(r["won"] / closed * 100, 1) if closed else None})
        return sorted(rows, key=lambda r: -r["total"])

    stages = defaultdict(lambda: {"count": 0, "value": 0})
    for l in leads:
        if l.get("status") == "open":
            stages[l.get("stage", "Lead")]["count"] += 1
            stages[l.get("stage", "Lead")]["value"] += l.get("budget", 0)
    reasons = defaultdict(int)
    for l in leads:
        if l.get("status") == "lost":
            reasons[l.get("loss_reason") or "Not recorded"] += 1
    bids = t.find("bids")
    decided = [b for b in bids if b.get("result") in ("won", "lost")]
    return jsonify({
        "pipeline": [{"stage": k, **v} for k, v in stages.items()],
        "by_source": group("source"), "by_service": group("service"), "by_owner": group("owner_id"),
        "loss_reasons": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])],
        "bids": {"total": len(bids), "bid": sum(1 for b in bids if b.get("decision") == "bid"),
                 "hit_rate": round(sum(1 for b in decided if b["result"] == "won") / len(decided) * 100, 1)
                 if decided else None},
    })


@bp.get("/reports/projects")
@api("reports", write=False)
def projects():
    today = datetime.utcnow().date().isoformat()
    soon = (datetime.utcnow() + timedelta(days=14)).date().isoformat()
    delayed, upcoming = [], []
    for p in t.find("projects", {"status": {"$in": ["active", "planning"]}}):
        for s in p.get("stages", []):
            if s.get("status") == "done" or not s.get("end"):
                continue
            row = {"project": p["name"], "project_id": str(p["_id"]), "stage": s["name"], "end": s["end"],
                   "progress": s.get("progress", 0)}
            if s["end"] < today:
                delayed.append(row)
            elif s["end"] <= soon:
                upcoming.append(row)
    snags = t.find("snags", {"status": {"$ne": "closed"}})
    return jsonify({"delayed": delayed, "upcoming": upcoming,
                    "open_snags": [{"id": str(s["_id"]), "title": s["title"], "project": s.get("project_name"),
                                    "due": s.get("due"), "overdue": bool(s.get("due") and s["due"] < today)}
                                   for s in snags]})


@bp.get("/reports/finance")
@api("finance", write=False)
def finance():
    today = datetime.utcnow().date().isoformat()
    rows = []
    for p in t.find("projects"):
        rows.append({"project": p["name"], "project_id": str(p["_id"]), **B.project_financials(p)})
    inv = t.find("invoices", {"status": {"$in": ["sent", "partial"]}})
    ageing = defaultdict(float)
    for i in inv:
        due = i.get("due_date", today)
        days = (datetime.fromisoformat(today) - datetime.fromisoformat(due)).days
        bucket = "current" if days <= 0 else "1-30" if days <= 30 else "31-60" if days <= 60 else "60+"
        ageing[bucket] += i.get("amount_due", 0) - i.get("paid", 0)
    months = defaultdict(lambda: {"in": 0, "out": 0})
    for i in t.find("invoices"):
        for pay in i.get("payments", []):
            months[str(pay["at"])[:7]]["in"] += pay["amount"]
    for c in t.find("costs", {"status": "approved"}):
        months[str(c.get("date"))[:7]]["out"] += c["amount"]
    return jsonify({
        "projects": rows,
        "receivables": round(sum(ageing.values()), 2),
        "ageing": {k: round(v, 2) for k, v in ageing.items()},
        "cash_flow": [{"month": k, **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in sorted(months.items())],
    })


@bp.get("/reports/procurement")
@api("procurement", write=False)
def procurement():
    today = datetime.utcnow().date().isoformat()
    pos = t.find("purchase_orders")
    spend = defaultdict(float)
    for po in pos:
        if po["status"] not in ("draft", "pending_approval", "cancelled"):
            spend[po.get("vendor_name") or "—"] += po.get("total", 0)
    return jsonify({
        "pending": [t.out(p) for p in pos if p["status"] in ("draft", "pending_approval", "issued", "partial")],
        "late": [t.out(p) for p in pos if p["status"] in ("issued", "partial") and p.get("expected_date")
                 and p["expected_date"] < today],
        "spend_by_vendor": [{"vendor": k, "total": round(v, 2)} for k, v in sorted(spend.items(), key=lambda x: -x[1])],
    })


@bp.get("/reports/team")
@api("reports", write=False)
def team():
    today = datetime.utcnow().date().isoformat()
    users = t.find("users", {"kind": "staff"})
    hours = defaultdict(float)
    for ts in t.find("timesheets"):
        hours[ts.get("user_id")] += ts.get("hours", 0)
    out = []
    for u in users:
        uid = str(u["_id"])
        open_f = db.followups.count_documents({"company_id": g.cid, "owner_id": uid, "status": "open"})
        overdue = db.followups.count_documents({"company_id": g.cid, "owner_id": uid, "status": "open",
                                                "due": {"$lt": today}})
        tasks = sum(1 for p in t.find("projects", {"status": "active"}) for s in p.get("stages", [])
                    for tk in s.get("tasks", []) if tk.get("assignee_id") == uid and tk.get("status") != "done")
        out.append({"user": u["name"], "role": u["role"], "open_followups": open_f, "overdue_followups": overdue,
                    "open_tasks": tasks, "hours": round(hours.get(uid, 0), 1)})
    return jsonify(out)
