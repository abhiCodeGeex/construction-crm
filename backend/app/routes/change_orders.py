"""Phase E block 4 — change orders (§11).

draft -> priced -> sent to the client -> approved / rejected; withdrawn at any point before a decision.
* Lines carry an internal cost and a client price (tax at the company rate); the time impact is in working days.
* The client's approval is recorded by staff (who, how, when, file) — portal approval is Phase G. A change caused by
  *our error* is approved internally by an Owner, with no client price.
* Approving: the stage budget grows by the cost; the signed contract is never edited — it gets the change order,
  a `revised_value` and a new payment-schedule row (due on approval or when the stage completes), invoiced like any
  other row; a project without a contract invoices the change order directly. The time impact moves the stage's
  open tasks and everything that depends on them, logged as a client-change delay once a baseline exists.
Who: raise and price — Owner, PM, Designer on the project (change_orders: rw); approve — Owner or the project's PM.
Site and Accounts read (Site never sees cost).
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales, workdays
from ..services.defaults import SIGNOFF_METHODS, DELAY_REASONS
from ..services.project_events import PM_ROLE
from .finance import finance_project
from .lead_money import a_date, money_text
from .lead_steps import num
from .projects import member, save_stages, baseline, record_delay, all_tasks

bp = Blueprint("change_orders", __name__)

CO_REASONS = {"client_request": "Client request", "design_change": "Design change", "site_condition": "Site condition found",
              "authority": "Authority requirement", "our_error": "Our error"}
PAYMENT_WHEN = {"on_approval": "On approval", "stage": "When the stage is complete"}


def r2(v):
    return round(v + 1e-9, 2)


def load_co(cid_):
    co = t.get("change_orders", cid_)
    p = access(co["project_id"])
    return co, p


def access(pid, write=False):
    if not (can("change_orders") or can("finance")):
        abort(403, "Your role cannot view change orders")
    p = finance_project(pid)
    if write and not (can("change_orders", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change change orders on this project")
    return p


def is_approver(p):
    return g.role == "owner" or any(m.get("user_id") == g.uid and m.get("project_role") == PM_ROLE for m in p.get("team", []))


def out(co):
    return t.out(serialize(co))


def clean_lines(rows, our_error):
    lines = []
    for r in (rows or [])[:50]:
        desc = (r.get("description") or "").strip()[:200] or abort(400, "Each line needs a description")
        qty = num(r.get("qty"), f"Quantity for {desc}", required=True, positive=True)
        cost_rate = num(r.get("cost_rate"), f"Cost rate for {desc}") or 0
        price_rate = 0 if our_error else (num(r.get("price_rate"), f"Price for {desc}") or 0)
        lines.append({"id": r.get("id") or t.sid(), "description": desc, "qty": qty, "unit": (r.get("unit") or "").strip()[:20] or None,
                      "cost_rate": cost_rate, "price_rate": price_rate, "cost": r2(qty * cost_rate), "price": r2(qty * price_rate)})
    return lines


def totals(lines, tax_pct):
    cost = r2(sum(x["cost"] for x in lines))
    price = r2(sum(x["price"] for x in lines))
    tax = r2(price * tax_pct / 100)
    return {"cost": cost, "price": price, "tax": tax, "total": r2(price + tax), "margin": r2(price - cost)}


def stage_of(p, sid):
    return next((s for s in p.get("stages", []) if s["id"] == sid), None) or abort(400, "Choose a stage of this project")


def clean(d, p, co=None):
    ch = {}
    if "stage_id" in d or co is None:
        s = stage_of(p, d.get("stage_id"))
        ch.update(stage_id=s["id"], stage_name=s["name"])
    if "title" in d or co is None:
        ch["title"] = (d.get("title") or "").strip()[:150] or abort(400, "Give the change a title")
    if "description" in d:
        ch["description"] = (d.get("description") or "").strip()[:2000] or None
    if "reason" in d or co is None:
        if d.get("reason") not in CO_REASONS:
            abort(400, f"Why is it changing? {', '.join(CO_REASONS.values())}")
        ch["reason"] = d["reason"]
    if "time_days" in d:
        v = d.get("time_days") or 0
        if not isinstance(v, int) or isinstance(v, bool) or not -60 <= v <= 365:
            abort(400, "Time impact is a whole number of working days (-60 to 365)")
        ch["time_days"] = v
    if "payment" in d:
        if d["payment"] not in PAYMENT_WHEN:
            abort(400, f"When is it paid? {', '.join(PAYMENT_WHEN.values())}")
        ch["payment"] = d["payment"]
    if "files" in d:
        files = []
        for key in dict.fromkeys(d.get("files") or []):
            f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the file first")
            files.append({"key": f["key"], "name": f["name"], "size": f["size"]})
        ch["files"] = files[:10]
    reason = ch.get("reason", (co or {}).get("reason"))
    if "lines" in d or (co and "reason" in ch):
        ch["lines"] = clean_lines(d.get("lines", (co or {}).get("lines")), reason == "our_error")
        ch["totals"] = totals(ch["lines"], (co or {}).get("tax_pct", float(g.company.get("tax_rate") or 0)))
    return ch


def new_co(p, d, extra=None):
    doc = {"number": t.next_number("CO", "CO"), "project_id": str(p["_id"]), "project_name": p["name"], "project_code": p.get("code"),
           "status": "draft", "description": None, "time_days": 0, "payment": "on_approval", "files": [], "lines": [],
           "tax_pct": float(g.company.get("tax_rate") or 0), "totals": totals([], 0), "raised_by": g.uid,
           "raised_by_name": g.user.get("name"), **clean(d, p), **(extra or {})}
    if doc["lines"]:
        doc["totals"] = totals(doc["lines"], doc["tax_pct"])
    return t.insert("change_orders", doc)


# ---------------- reading ----------------
@bp.get("/projects/<pid>/change_orders")
@api(None)
def project_cos(pid):
    p = access(pid)
    rows = [out(c) for c in t.find("change_orders", {"project_id": pid}, sort=[("created_at", -1)])]
    approved = [c for c in rows if c["status"] == "approved"]
    return jsonify({"change_orders": rows, "reasons": CO_REASONS, "payment_when": PAYMENT_WHEN, "methods": SIGNOFF_METHODS,
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "approved_total": r2(sum((c.get("totals") or {}).get("total", 0) for c in approved)),
                    "can_write": can("change_orders", True) and (g.role == "owner" or member(p) is not None),
                    "can_approve": is_approver(p), "is_owner": g.role == "owner",
                    "has_contract": bool(db.contracts.find_one({"company_id": g.cid, "project_id": pid}, {"_id": 1}))})


@bp.get("/change_orders")
@api(None)
def all_cos():
    if not (can("change_orders") or can("finance")):
        abort(403, "Your role cannot view change orders")
    q = {}
    if g.role not in ("owner", "accounts"):
        q["project_id"] = {"$in": [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify({"change_orders": [out(c) for c in t.find("change_orders", q, sort=[("created_at", -1)], limit=500)],
                    "reasons": CO_REASONS})


# ---------------- writing ----------------
@bp.post("/projects/<pid>/change_orders")
@api(None)
def add_co(pid):
    p = access(pid, write=True)
    co = new_co(p, request.get_json(force=True) or {})
    ev.log(pid, "cost", f"Change order {co['number']} raised: {co['title']} ({CO_REASONS[co['reason']]})")
    return jsonify(out(co)), 201


@bp.put("/change_orders/<cid_>")
@api(None)
def edit_co(cid_):
    co, p = load_co(cid_)
    access(co["project_id"], write=True)
    if co["status"] not in ("draft", "priced"):
        abort(409, "Only a draft or priced change order can be changed")
    ch = clean(request.get_json(force=True) or {}, p, co)
    ch["status"] = "draft"  # a change to a priced order needs pricing again
    return jsonify(out(t.update("change_orders", cid_, ch)))


@bp.post("/change_orders/<cid_>/price")
@api(None)
def price_co(cid_):
    co, p = load_co(cid_)
    access(co["project_id"], write=True)
    if co["status"] != "draft":
        abort(409, "Only a draft is priced")
    if not co["lines"]:
        abort(400, "Add the lines: what it costs us and what the client pays")
    if co["reason"] != "our_error" and co["totals"]["total"] <= 0:
        abort(400, "A change the client pays for needs a price")
    return jsonify(out(t.update("change_orders", cid_, {"status": "priced", "priced_at": t.now(), "priced_by": g.user.get("name")})))


@bp.post("/change_orders/<cid_>/send")
@api(None)
def send_co(cid_):
    co, p = load_co(cid_)
    access(co["project_id"], write=True)
    if co["status"] != "priced":
        abort(409, "Price the change order before sending it")
    if co["reason"] == "our_error":
        abort(409, "A change caused by our error is approved internally by an Owner, not sent to the client")
    upd = t.update("change_orders", cid_, {"status": "sent", "sent_at": t.now(), "sent_by": g.user.get("name")})
    ev.log(co["project_id"], "cost", f"Change order {co['number']} sent to the client: {money_text(co['totals']['total'])}")
    return jsonify(out(upd))


def decided(co, p, text):
    notify.send("co_decided", list(dict.fromkeys([co["raised_by"]] + ev.managers(p))), text,
                f"/app/projects/{p['_id']}?tab=changes", project_id=str(p["_id"]))


@bp.post("/change_orders/<cid_>/approve")
@api(None)
def approve_co(cid_):
    co, p = load_co(cid_)
    d = request.get_json(force=True) or {}
    if co["reason"] == "our_error":
        if g.role != "owner":
            abort(403, "Only an Owner approves a change caused by our error")
        if co["status"] != "priced":
            abort(409, "Price it (its cost to us) first")
        approval = {"name": g.user.get("name"), "method": "Internal (our error)", "date": sales.today(), "note": (d.get("note") or "").strip() or None}
    else:
        if not is_approver(p):
            abort(403, "Only an Owner or the project's Project Manager records the client's approval")
        if co["status"] != "sent":
            abort(409, "Send the change order to the client first")
        if d.get("method") not in SIGNOFF_METHODS:
            abort(400, f"How did the client approve? {', '.join(SIGNOFF_METHODS)}")
        name = (d.get("name") or "").strip() or abort(400, "Who approved it for the client?")
        day = a_date(d.get("date") or sales.today(), "Date")
        if day > sales.today():
            abort(400, "The approval cannot be dated in the future")
        if d.get("file_key") and not db.files.find_one({"company_id": g.cid, "key": d["file_key"]}):
            abort(400, "Upload the signed copy first")
        approval = {"name": name[:120], "method": d["method"], "date": day, "note": (d.get("note") or "").strip()[:300] or None,
                    "file_key": d.get("file_key") or None}
    approval.update(recorded_by=g.user.get("name"), recorded_at=t.now())
    upd = t.update("change_orders", cid_, {"status": "approved", "approval": approval, "approved_at": t.now()})
    effects = apply_change(upd, t.get("projects", co["project_id"]))
    upd = t.update("change_orders", cid_, {"effects": effects})
    decided(upd, p, f"Change order {co['number']} approved: {co['title']}" + (f", {money_text(co['totals']['total'])}" if co["totals"]["total"] else ""))
    return jsonify(out(upd))


def apply_change(co, p):
    """What an approved change does to the project, the contract and the plan. Returns a summary kept on the order."""
    pid, sid, tt = str(p["_id"]), co["stage_id"], co["totals"]
    eff = {"budget_added": tt["cost"], "schedule_row_id": None, "revised_value": None, "moved_tasks": []}
    stage = next((s for s in p["stages"] if s["id"] == sid), None)
    if stage is None:
        return eff
    stage["budget"] = r2((stage.get("budget") or 0) + tt["cost"])
    client_pays = co["reason"] != "our_error" and tt["total"] > 0
    contract = db.contracts.find_one({"company_id": g.cid, "project_id": pid}) if client_pays else None
    if contract:
        gate = next((m for m in stage.get("milestones", []) if m.get("gate")), None)
        row = {"id": t.sid(), "name": f"Change order {co['number']}: {co['title']}", "pct": round(tt["total"] / contract["value"] * 100, 2),
               "amount": tt["total"], "taxable": tt["price"], "tax": tt["tax"], "co_id": str(co["_id"]),
               "trigger": "approval" if co["payment"] == "on_approval" else "stage"}
        if row["trigger"] == "stage":
            row.update(stage=stage["name"], milestone_id=gate and gate["id"])
        revised = r2((contract.get("revised_value") or contract["value"]) + tt["total"])
        db.contracts.update_one({"_id": contract["_id"]}, {"$push": {"payment_schedule": row, "change_orders": {
            "id": str(co["_id"]), "number": co["number"], "title": co["title"], "total": tt["total"], "at": t.now()}},
            "$set": {"revised_value": revised}})
        eff.update(schedule_row_id=row["id"], revised_value=revised)
    if client_pays:
        p["value"] = r2((p.get("value") or 0) + tt["total"])
    days = co.get("time_days") or 0
    if days:
        cal = workdays.calendar()
        old_end = stage.get("end")
        tasks = all_tasks(p)
        moved = [tk["id"] for tk in stage.get("tasks", []) if tk["status"] != "done"]
        queue = list(moved)
        while queue:  # and everything that depends on them, once each
            cur = queue.pop(0)
            for tid, (_, tk) in tasks.items():
                if tid not in moved and cur in (tk.get("depends_on") or []) and tk["status"] != "done":
                    moved.append(tid)
                    queue.append(tid)
        for tid in moved:
            tk = tasks[tid][1]
            tk["start"] = workdays.add_working(tk["start"], days, cal) if tk.get("start") else None
            tk["end"] = workdays.add_working(tk["end"], days, cal) if tk.get("end") else None
        if old_end:
            stage["end"] = workdays.add_working(old_end, days, cal)
        eff["moved_tasks"] = [tasks[x][1]["title"] for x in moved]
        if baseline(p) and old_end and days > 0:
            record_delay({"project_id": pid, "kind": "stage", "item_id": sid, "title": stage["name"], "from": old_end, "to": stage["end"],
                          "days": days, "reason": "client_change", "reason_label": DELAY_REASONS["client_change"][0],
                          "party": DELAY_REASONS["client_change"][1], "note": f"Change order {co['number']}"})
    db.projects.update_one({"_id": p["_id"]}, {"$set": {"value": p.get("value")}})
    save_stages(pid, p)
    ev.log(pid, "cost", f"Change order {co['number']} approved: budget +{money_text(tt['cost'])}"
           + (f", contract now {money_text(eff['revised_value'])}" if eff["revised_value"] else "")
           + (f", {days:+d} working days on {stage['name']}" if days else ""))
    return eff


@bp.post("/change_orders/<cid_>/reject")
@api(None)
def reject_co(cid_):
    co, p = load_co(cid_)
    if not is_approver(p):
        abort(403, "Only an Owner or the project's Project Manager records the client's answer")
    if co["status"] != "sent":
        abort(409, "Only a change order sent to the client can be rejected")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the client rejected it")
    upd = t.update("change_orders", cid_, {"status": "rejected", "decision_reason": reason[:300], "decided_at": t.now()})
    decided(upd, p, f"Change order {co['number']} rejected by the client: {reason}")
    return jsonify(out(upd))


@bp.post("/change_orders/<cid_>/withdraw")
@api(None)
def withdraw_co(cid_):
    co, p = load_co(cid_)
    access(co["project_id"], write=True)
    if co["status"] not in ("draft", "priced", "sent"):
        abort(409, "This change order is already decided")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why it is withdrawn")
    return jsonify(out(t.update("change_orders", cid_, {"status": "withdrawn", "decision_reason": reason[:300], "decided_at": t.now()})))


@bp.post("/change_orders/<cid_>/invoice")
@api("finance")
def invoice_co(cid_):
    """A project without a signed contract invoices an approved change order directly (with a contract it is a
    payment-schedule row, invoiced from the schedule)."""
    from .invoices import base_doc, totals as inv_totals, present
    co, p = load_co(cid_)
    if co["status"] != "approved" or co["reason"] == "our_error" or not co["totals"]["total"]:
        abort(409, "Only an approved change the client pays for is invoiced")
    if (co.get("effects") or {}).get("schedule_row_id"):
        abort(409, "This change order is on the contract's payment schedule; invoice it from there")
    if co.get("invoice_id"):
        abort(409, "This change order is already invoiced")
    lines = [{"id": t.sid(), "description": f"{co['number']} {ln['description']}", "qty": ln["qty"], "rate": ln["price_rate"],
              "amount": ln["price"], "tax_pct": co["tax_pct"], "tax": r2(ln["price"] * co["tax_pct"] / 100)} for ln in co["lines"] if ln["price"]]
    inv = t.insert("invoices", {**base_doc("manual", p), "co_id": cid_, "co_number": co["number"], "lines": lines, **inv_totals(lines)})
    t.update("change_orders", cid_, {"invoice_id": str(inv["_id"])})
    return jsonify(present(inv)), 201
