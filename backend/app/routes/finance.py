"""Phase E block 1 — costs against the project and stage, with approval and budget control (§12, §4.7).

Who does what:
* Finance writers (Owner, PM, Accounts) record any cost. Owner and Accounts see every project's money;
  everyone else only projects they are on.
* A Site Supervisor on the project may log a *site expense* up to the company limit; it always waits for approval
  and they see only their own entries.
* Approvers: an Owner, or a Project Manager on that project's team. Within the stage budget a cost entered by an
  approver or by Accounts is approved on submit; a cost that takes the stage over its budget always waits and
  needs a reason (client change, our mistake, price rise).
* Only approved costs are actual; submitted ones are committed. Approved costs are voided, never deleted.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, budget, project_events as ev, sales
from ..services.defaults import (COST_CATEGORIES, VENDOR_TYPES, OVERSPEND_REASONS, FINANCE_DEFAULTS)
from .lead_money import a_date, money_text
from .lead_steps import num
from .projects import member
from ..services.project_events import PM_ROLE

bp = Blueprint("finance", __name__)

SITE_EXPENSE = "Site expense"


def settings(company=None):
    return {**FINANCE_DEFAULTS, **((company or g.company).get("finance") or {})}


# ---------------- access ----------------
def finance_project(pid):
    """Owner and Accounts reach every project's money; everyone else only projects they are on."""
    p = t.get("projects", pid)
    if g.role in ("owner", "accounts") or member(p):
        return p
    abort(404, "project not found")


def site_only():
    """A Site Supervisor without finance access: may log and see their own site expenses."""
    return not can("finance") and g.role == "site"


def require_read():
    if not (can("finance") or g.role == "site"):
        abort(403, "Your role cannot view finance")


def is_approver(p):
    if g.role == "owner":
        return True
    return can("finance", True) and any(m.get("user_id") == g.uid and m.get("project_role") == PM_ROLE for m in p.get("team", []))


def approvers(p, over=False):
    """Project managers on the team (else Owners); Owners too when the cost takes a stage over budget."""
    return list(dict.fromkeys(ev.managers(p) + (ev.owners() if over else [])))


def load_cost(cid):
    c = t.get("costs", cid)
    p = finance_project(c["project_id"])
    if site_only() and c["created_by"] != g.uid:
        abort(404, "cost not found")
    return c, p


def can_change(c):
    return c["created_by"] == g.uid or can("finance", True)


# ---------------- cleaning ----------------
def clean(d, p, cost=None):
    out = {}
    cur = cost or {}
    if "stage_id" in d or cost is None:
        stage = next((s for s in p.get("stages", []) if s["id"] == d.get("stage_id")), None) or abort(400, "Choose a stage of this project")
        out.update(stage_id=stage["id"], stage_name=stage["name"])
    if site_only():
        out["category"] = SITE_EXPENSE
    elif "category" in d or cost is None:
        if d.get("category") not in COST_CATEGORIES:
            abort(400, f"Category must be one of: {', '.join(COST_CATEGORIES)}")
        out["category"] = d["category"]
    if "vendor_id" in d:
        if d["vendor_id"]:
            v = db.contacts.find_one({"_id": oid(d["vendor_id"]), "company_id": g.cid}) or abort(400, "Vendor not found")
            if not set(v.get("types") or []) & set(VENDOR_TYPES):
                abort(400, f"{v['name']} is not a supplier, subcontractor, contractor or consultant")
            out.update(vendor_id=d["vendor_id"], vendor_name=v["name"])
        else:
            out.update(vendor_id=None, vendor_name=None)
    if "date" in d or cost is None:
        out["date"] = a_date(d.get("date"), "Date")
        if out["date"] > sales.today():
            abort(400, "A cost cannot be dated in the future")
    if "description" in d or cost is None:
        out["description"] = (d.get("description") or "").strip()[:300] or abort(400, "Say what the cost is for")
    if "amount" in d or cost is None:
        out["amount"] = round(num(d.get("amount"), "Amount", required=True, positive=True), 2)
    if "tax" in d:
        out["tax"] = round(num(d.get("tax"), "Tax") or 0, 2)
    if "qty" in d:
        out["qty"] = num(d.get("qty"), "Quantity") or None
    if "unit" in d:
        out["unit"] = (d.get("unit") or "").strip()[:20] or None
    if "rate_id" in d:
        if d["rate_id"]:
            r = db.rate_library.find_one({"_id": oid(d["rate_id"]), "company_id": g.cid}) or abort(400, "Rate library item not found")
            out.update(rate_id=d["rate_id"], rate_name=r["name"], unit=out.get("unit") or r["unit"])
        else:
            out.update(rate_id=None, rate_name=None)
    if "bill_no" in d:
        out["bill_no"] = (d.get("bill_no") or "").strip()[:60] or None
    if "files" in d:
        files = []
        for key in dict.fromkeys(d.get("files") or []):
            f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the bill first")
            files.append({"key": f["key"], "name": f["name"], "size": f["size"]})
        out["files"] = files[:10]
    if "paid_from_float" in d:  # Phase I: paid from the recorder's petty cash float
        out["paid_from_float"] = bool(d["paid_from_float"])
    out["total"] = round(out.get("amount", cur.get("amount", 0)) + out.get("tax", cur.get("tax", 0) or 0), 2)
    if out.get("paid_from_float", cur.get("paid_from_float")):
        holder = cur.get("created_by") or g.uid
        mine_now = cur.get("total", 0) if cur.get("paid_from_float") and cur.get("status") not in ("rejected", "void") else 0
        left = petty_balance(holder)["balance"] + mine_now
        if out["total"] > left + 0.01:
            abort(400, f"The petty cash float has only {money_text(left)} left; ask Accounts for more or pay it another way")
    if site_only() and out.get("amount", cur.get("amount", 0)) > settings()["site_expense_limit"]:
        abort(403, f"A site expense is at most {money_text(settings()['site_expense_limit'])}; ask the PM or Accounts to record it")
    return out


# ---------------- rate library learns from real costs ----------------
def learn(c, add=True):
    if not (c.get("rate_id") and c.get("qty")):
        return
    r = db.rate_library.find_one({"_id": oid(c["rate_id"]), "company_id": g.cid})
    if not r:
        return
    actuals = [a for a in (r.get("actuals") or []) if a["cost_id"] != str(c["_id"])]
    if add:
        actuals.append({"cost_id": str(c["_id"]), "rate": round(c["amount"] / c["qty"], 2), "date": c["date"],
                        "project": c.get("project_name")})
    actuals = actuals[-10:]
    sug = round(sum(a["rate"] for a in actuals) / len(actuals), 2) if len(actuals) >= 3 else None
    db.rate_library.update_one({"_id": r["_id"]}, {"$set": {"actuals": actuals, "suggested_rate": sug,
                                                            "last_actual": actuals[-1]["rate"] if actuals else None}})


# ---------------- views ----------------
def perms(p):
    return {"can_add": can("finance", True), "can_add_site_expense": site_only() and member(p) is not None,
            "can_approve": is_approver(p), "can_void": g.role in ("owner", "accounts"),
            "can_set_budget": not g.hide_costs and (is_approver(p) or g.role == "accounts"),
            "site_expense_limit": settings()["site_expense_limit"]}


@bp.get("/projects/<pid>/costs")
@api(None)
def project_costs(pid):
    require_read()
    p = finance_project(pid)
    q = {"project_id": pid}
    if site_only():
        q["created_by"] = g.uid
    costs = t.find("costs", q, sort=[("date", -1), ("created_at", -1)])
    data = {"costs": serialize(costs), "perms": perms(p), "categories": COST_CATEGORIES, "reasons": OVERSPEND_REASONS,
            "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])]}
    if not g.hide_costs:
        rows = budget.budget_rows(p)
        data["budget"] = {"stages": rows, "budget": round(sum(r["budget"] for r in rows), 2),
                          "spent": round(sum(r["spent"] for r in rows), 2), "committed": round(sum(r["committed"] for r in rows), 2)}
    return jsonify(data)


@bp.get("/finance/costs")
@api("finance", write=False)
def all_costs():
    q = {k: request.args[k] for k in ("status", "project_id", "category", "vendor_id") if request.args.get(k)}
    if g.role not in ("owner", "accounts"):
        mine = [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]
        q["project_id"] = q["project_id"] if q.get("project_id") in mine else {"$in": mine}
    return jsonify({"costs": serialize(t.find("costs", q, sort=[("date", -1), ("created_at", -1)], limit=500)),
                    "categories": COST_CATEGORIES})


# ---------------- writes ----------------
@bp.post("/projects/<pid>/costs")
@api(None)
def add_cost(pid):
    if not (can("finance", True) or site_only()):
        abort(403, "Your role cannot record costs")
    p = finance_project(pid)
    if site_only() and not member(p):
        abort(403, "Only a site supervisor on this project can log its site expenses")
    d = request.get_json(force=True) or {}
    doc = {"project_id": pid, "project_name": p["name"], "project_code": p.get("code"), "vendor_id": None, "vendor_name": None,
           "tax": 0, "qty": None, "unit": None, "rate_id": None, "rate_name": None, "bill_no": None, "files": [],
           "status": "draft", "kind": "site_expense" if site_only() else "cost", "created_by": g.uid,
           "created_by_name": g.user.get("name"), **clean(d, p)}
    c = t.insert("costs", doc)
    ev.log(pid, "cost", f"Cost recorded: {c['description']} {money_text(c['amount'])} ({c['stage_name']})")
    if d.get("submit") or site_only():
        c = submit(c, p)
    return jsonify(serialize(c)), 201


@bp.put("/costs/<cid>")
@api(None)
def edit_cost(cid):
    c, p = load_cost(cid)
    if not can_change(c):
        abort(403, "Only the person who recorded it or Finance can change a cost")
    if c["status"] not in ("draft", "rejected"):
        abort(409, "Only a draft or a rejected cost can be changed")
    upd = t.update("costs", cid, {**clean(request.get_json(force=True) or {}, p, c), "status": "draft", "reject_reason": None})
    return jsonify(serialize(upd))


@bp.delete("/costs/<cid>")
@api(None)
def delete_cost(cid):
    c, _ = load_cost(cid)
    if not can_change(c):
        abort(403, "Only the person who recorded it or Finance can remove a cost")
    if c["status"] not in ("draft", "rejected"):
        abort(409, "A submitted or approved cost cannot be deleted; void it instead")
    t.delete("costs", cid)
    return jsonify({"ok": True})


def submit(c, p):
    over = budget.over_budget(p, c["stage_id"], c["amount"])
    auto = c["kind"] != "site_expense" and not over and (is_approver(p) or g.role == "accounts")
    ch = {"status": "approved" if auto else "submitted", "submitted_at": t.now(), "over_budget": over}
    if auto:
        ch.update(approved_by=g.user.get("name"), approved_by_id=g.uid, decided_at=t.now())
    c = t.update("costs", str(c["_id"]), ch)
    if auto:
        budget.recalc_stage(p, c["stage_id"])
        learn(c)
    else:
        notify.send("cost_approval", approvers(p, over > 0),
                    f"{c['created_by_name']}: {c['description']} {money_text(c['amount'])} on {p['name']} · {c['stage_name']}"
                    + (f" — {money_text(over)} over the stage budget" if over else ""),
                    f"/app/projects/{p['_id']}?tab=money", project_id=str(p["_id"]))
    return c


@bp.post("/costs/<cid>/submit")
@api(None)
def submit_cost(cid):
    c, p = load_cost(cid)
    if not can_change(c):
        abort(403, "Only the person who recorded it or Finance can submit a cost")
    if c["status"] != "draft":
        abort(409, "Only a draft can be submitted")
    return jsonify(serialize(submit(c, p)))


def decided(c, p, text):
    notify.send("cost_decided", [c["created_by"]], text, f"/app/projects/{p['_id']}?tab=money", project_id=str(p["_id"]))


@bp.post("/costs/<cid>/approve")
@api("finance")
def approve_cost(cid):
    c, p = load_cost(cid)
    if not is_approver(p):
        abort(403, "Only an Owner or a Project Manager on this project can approve costs")
    if c["status"] != "submitted":
        abort(409, "Only a submitted cost can be approved")
    d = request.get_json(force=True) or {}
    over = budget.over_budget(p, c["stage_id"], c["amount"])
    ch = {"status": "approved", "approved_by": g.user.get("name"), "approved_by_id": g.uid, "decided_at": t.now(),
          "over_budget": over, "overspend_reason": None}
    if over:
        if d.get("overspend_reason") not in OVERSPEND_REASONS:
            abort(400, f"This takes {c['stage_name']} {money_text(over)} over its budget: say why "
                       f"({', '.join(OVERSPEND_REASONS.values())})")
        ch.update(overspend_reason=d["overspend_reason"], overspend_amount=over,
                  overspend_markup_pct=settings()["overspend_markup_pct"] if d["overspend_reason"] == "client_change" else None)
    c = t.update("costs", cid, ch)
    budget.recalc_stage(p, c["stage_id"])
    learn(c)
    if over and d["overspend_reason"] == "client_change":
        from .change_orders import new_co
        price = round(over * (1 + settings()["overspend_markup_pct"] / 100), 2)
        co = new_co(p, {"stage_id": c["stage_id"], "title": f"Overspend: {c['description']}"[:150], "reason": "client_request",
                        "description": f"{c['stage_name']} went {money_text(over)} over its budget because the client changed something "
                                       f"(cost {c['description']}). Draft for the client to pay; review before sending.",
                        "lines": [{"description": c["description"], "qty": 1, "cost_rate": over, "price_rate": price}]},
                    {"from_cost_id": cid})
        c = t.update("costs", cid, {"change_order_id": str(co["_id"]), "change_order_number": co["number"]})
    ev.log(str(p["_id"]), "cost", f"Cost approved: {c['description']} {money_text(c['amount'])}"
           + (f" — over budget ({OVERSPEND_REASONS[c['overspend_reason']]})" if over else ""))
    decided(c, p, f"Approved: {c['description']} {money_text(c['amount'])}")
    return jsonify(serialize(c))


@bp.post("/costs/<cid>/reject")
@api("finance")
def reject_cost(cid):
    c, p = load_cost(cid)
    if not is_approver(p):
        abort(403, "Only an Owner or a Project Manager on this project can reject costs")
    if c["status"] != "submitted":
        abort(409, "Only a submitted cost can be rejected")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the cost is rejected")
    c = t.update("costs", cid, {"status": "rejected", "reject_reason": reason[:300], "decided_at": t.now(),
                                "approved_by": g.user.get("name"), "approved_by_id": g.uid})
    decided(c, p, f"Rejected: {c['description']} {money_text(c['amount'])} — {reason}")
    return jsonify(serialize(c))


@bp.post("/costs/<cid>/void")
@api("finance")
def void_cost(cid):
    c, p = load_cost(cid)
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void a cost")
    if c["status"] != "approved":
        abort(409, "Only an approved cost is voided; delete a draft instead")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the cost is void")
    c = t.update("costs", cid, {"status": "void", "void_reason": reason[:300], "voided_at": t.now(), "voided_by": g.user.get("name")})
    budget.recalc_stage(t.get("projects", c["project_id"]), c["stage_id"])
    learn(c, add=False)
    ev.log(str(p["_id"]), "cost", f"Cost voided: {c['description']} {money_text(c['amount'])} — {reason}")
    return jsonify(serialize(c))


# ---------------- settings and the rate library ----------------
@bp.get("/finance/settings")
@api(None)
def get_settings():
    return jsonify({**settings(), "reasons": OVERSPEND_REASONS})


@bp.put("/finance/settings")
@api("settings")
def put_settings():
    d = request.get_json(force=True) or {}
    s = settings()
    if "site_expense_limit" in d:
        s["site_expense_limit"] = num(d["site_expense_limit"], "Site expense limit", required=True)
    if "overspend_markup_pct" in d:
        v = num(d["overspend_markup_pct"], "Overspend markup %", required=True)
        if v > 100:
            abort(400, "Overspend markup % must be at most 100")
        s["overspend_markup_pct"] = v
    for k, label, cap in (("po_approval_limit", "PO approval limit", None), ("match_rate_tolerance_pct", "Rate tolerance %", 100),
                          ("match_amount_tolerance", "Amount tolerance", None), ("over_receipt_pct", "Over-receipt %", 100)):
        if k in d:  # Phase H (procurement)
            v = num(d[k], label, required=True)
            if cap is not None and v > cap:
                abort(400, f"{label} must be at most {cap}")
            s[k] = v
    if "client_reminder_days" in d:  # Phase I
        days = d["client_reminder_days"]
        if not isinstance(days, list) or len(days) > 8 or any(not isinstance(x, int) or isinstance(x, bool) or not -30 <= x <= 90 for x in days):
            abort(400, "Client reminders are up to 8 whole days between -30 (before the due date) and 90 (after it)")
        s["client_reminder_days"] = sorted(set(days))
    if "selection_deposit_pct" in d:
        v = num(d["selection_deposit_pct"], "Selection deposit %", required=True)
        if not 0 < v <= 100:
            abort(400, "Selection deposit % is 1 to 100")
        s["selection_deposit_pct"] = v
    if "require_selection_deposit" in d:
        s["require_selection_deposit"] = bool(d["require_selection_deposit"])
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"finance": s}})
    return jsonify(s)


@bp.post("/rates/<rid>/use-suggested")
@api("proposals")
def use_suggested(rid):
    r = t.get("rate_library", rid)
    if not r.get("suggested_rate"):
        abort(409, "No suggestion yet: it needs at least 3 approved costs with this item and a quantity")
    return jsonify(serialize(t.update("rate_library", rid, {"rate": r["suggested_rate"]})))


# ---------------- Phase I block 1: stage budgets from the accepted estimate (§12) ----------------
def estimate_for(p):
    """The estimate behind the accepted proposal of the project's lead, else the lead's latest approved estimate."""
    if not p.get("lead_id"):
        return None
    prop = db.proposals.find_one({"company_id": g.cid, "lead_id": p["lead_id"], "status": "accepted", "estimate_id": {"$ne": None}})
    if prop:
        e = db.estimates.find_one({"_id": oid(prop["estimate_id"]), "company_id": g.cid})
        if e:
            return e
    return db.estimates.find_one({"company_id": g.cid, "lead_id": p["lead_id"], "status": "approved"}, sort=[("created_at", -1)])


def budget_plan(p, est=None):
    """Budget per stage = the estimate's cost (direct + overheads, never the client price) of the lines tagged to that
    stage; untagged lines are spread over the tagged stages pro rata, or evenly over the estimate's service when none
    is tagged. Returns None when there is no estimate."""
    est = est or estimate_for(p)
    if not est:
        return None
    oh = 1 + float(est.get("overhead_pct") or 0) / 100
    by_name = {}
    for s in p.get("stages", []):
        by_name.setdefault(s["name"].strip().lower(), s)
    tagged, loose = {}, 0.0
    for ln in est.get("lines", []):
        cost = float(ln.get("line_cost") or 0) * oh
        s = by_name.get((ln.get("stage") or "").strip().lower())
        if s:
            tagged[s["id"]] = tagged.get(s["id"], 0) + cost
        else:
            loose += cost
    if tagged:
        base = sum(tagged.values())
        plan = {sid: v + loose * v / base for sid, v in tagged.items()} if base else tagged
    else:
        lead = db.leads.find_one({"_id": oid(p["lead_id"])}, {"service": 1}) or {}
        pool = [s for s in p.get("stages", []) if s.get("service") == lead.get("service")] or p.get("stages", [])
        plan = {s["id"]: loose / len(pool) for s in pool} if pool else {}
    rows = [{"stage_id": s["id"], "stage": s["name"], "current": s.get("budget", 0) or 0, "proposed": round(plan.get(s["id"], 0), 2)}
            for s in p.get("stages", [])]
    return {"estimate_id": str(est["_id"]), "estimate_number": est.get("number"), "tagged": bool(tagged),
            "total": round(sum(r["proposed"] for r in rows), 2), "rows": rows}


def apply_budget_plan(p, plan, only_empty=True, stage_ids=None):
    """Write the proposed budgets; on the win only stages still at 0 are filled."""
    want = {r["stage_id"]: r["proposed"] for r in plan["rows"]
            if (stage_ids is None or r["stage_id"] in stage_ids) and (not only_empty or not r["current"]) and r["proposed"]}
    if not want:
        return 0
    stages = [{**s, "budget": want[s["id"]]} if s["id"] in want else s for s in p["stages"]]
    db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": stages}})
    ev.log(str(p["_id"]), "cost", f"Stage budgets set from estimate {plan['estimate_number']}: "
           + ", ".join(f"{s['name']} {money_text(want[s['id']])}" for s in stages if s["id"] in want))
    return len(want)


def budget_editor(p):
    if g.hide_costs or not (is_approver(p) or g.role == "accounts"):
        abort(403, "Only an Owner, Accounts or a Project Manager on this project sets budgets")


@bp.get("/projects/<pid>/budget-from-estimate")
@api("finance", write=False)
def get_budget_plan(pid):
    p = finance_project(pid)
    budget_editor(p)
    return jsonify(budget_plan(p))


@bp.post("/projects/<pid>/budget-from-estimate")
@api("finance")
def post_budget_plan(pid):
    p = finance_project(pid)
    budget_editor(p)
    plan = budget_plan(p) or abort(409, "This project has no approved estimate to take budgets from")
    d = request.get_json(force=True) or {}
    ids = d.get("stage_ids")
    n = apply_budget_plan(p, plan, only_empty=False, stage_ids=set(ids) if isinstance(ids, list) else None)
    for s in t.get("projects", pid)["stages"]:
        budget.recalc_stage(t.get("projects", pid), s["id"])
    return jsonify({"updated": n, "plan": budget_plan(t.get("projects", pid))})


# ---------------- Phase I block 1: petty cash floats (§12 "site expenses and petty cash") ----------------
PETTY_KINDS = {"advance": "Cash given", "return": "Cash returned"}


def petty_spent(holder_id):
    """Costs the holder paid from the float; drafts count (the cash is gone), rejected and void ones do not."""
    return round(sum(c["amount"] + (c.get("tax") or 0) for c in db.costs.find(
        {"company_id": g.cid, "created_by": holder_id, "paid_from_float": True, "status": {"$nin": ["rejected", "void"]}},
        {"amount": 1, "tax": 1})), 2)


def petty_balance(holder_id):
    given = returned = 0.0
    for e in db.petty_cash.find({"company_id": g.cid, "holder_id": holder_id, "status": {"$ne": "void"}}):
        if e["kind"] == "advance":
            given += e["amount"]
        else:
            returned += e["amount"]
    spent = petty_spent(holder_id)
    return {"given": round(given, 2), "returned": round(returned, 2), "spent": spent, "balance": round(given - returned - spent, 2)}


@bp.get("/finance/petty-cash")
@api(None)
def petty_cash():
    """Owner and Accounts see every float; anyone else only their own."""
    everyone = g.role in ("owner", "accounts")
    holders = {e["holder_id"]: e["holder_name"] for e in db.petty_cash.find({"company_id": g.cid}, {"holder_id": 1, "holder_name": 1})}
    if not everyone:
        holders = {g.uid: g.user.get("name")} if g.uid in holders else {}
    rows = [{"holder_id": h, "holder_name": n, **petty_balance(h)} for h, n in holders.items()]
    q = {} if everyone else {"holder_id": g.uid}
    entries = serialize(t.find("petty_cash", q, sort=[("date", -1), ("created_at", -1)], limit=300))
    spends = serialize(t.find("costs", {**({} if everyone else {"created_by": g.uid}), "paid_from_float": True},
                              sort=[("date", -1)], limit=300))
    staff = [{"id": str(u["_id"]), "name": u["name"]} for u in db.users.find(
        {"company_id": g.cid, "kind": {"$ne": "external"}, "active": {"$ne": False}}, {"name": 1}).sort("name", 1)] if everyone else []
    return jsonify({"holders": sorted(rows, key=lambda r: r["holder_name"] or ""), "entries": entries, "spends": spends,
                    "can_write": everyone, "kinds": PETTY_KINDS, "staff": staff,
                    "mine": petty_balance(g.uid) if g.uid in holders else None})


@bp.post("/finance/petty-cash")
@api(None)
def add_petty_cash():
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts gives or takes back petty cash")
    d = request.get_json(force=True) or {}
    if d.get("kind") not in PETTY_KINDS:
        abort(400, "Say whether cash is given or returned")
    u = db.users.find_one({"_id": oid(d.get("holder_id")), "company_id": g.cid, "kind": {"$ne": "external"}, "active": {"$ne": False}}) \
        or abort(400, "Choose a staff member")
    amount = round(num(d.get("amount"), "Amount", required=True, positive=True), 2)
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "Petty cash cannot be dated in the future")
    hid = str(u["_id"])
    if d["kind"] == "return" and amount > petty_balance(hid)["balance"] + 0.01:
        abort(400, f"{u['name']} holds only {money_text(petty_balance(hid)['balance'])}")
    e = t.insert("petty_cash", {"holder_id": hid, "holder_name": u["name"], "kind": d["kind"], "amount": amount, "date": day,
                                "mode": d.get("mode") or "Cash", "note": (d.get("note") or "").strip()[:300] or None,
                                "status": "active", "by_name": g.user.get("name")})
    notify.send("receipt_recorded", [hid], f"Petty cash {PETTY_KINDS[d['kind']].lower()}: {money_text(amount)} "
                f"(balance {money_text(petty_balance(hid)['balance'])})", "/app/finance?tab=petty")
    return jsonify(serialize(e)), 201


@bp.post("/petty-cash/<eid>/void")
@api(None)
def void_petty_cash(eid):
    if g.role not in ("owner", "accounts"):
        abort(403, "Only an Owner or Accounts can void a petty cash entry")
    e = t.get("petty_cash", eid)
    if e["status"] == "void":
        abort(409, "Already void")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the entry is void")
    if e["kind"] == "advance" and petty_balance(e["holder_id"])["balance"] - e["amount"] < -0.01:
        abort(409, "Part of this cash is already spent; record a return instead")
    return jsonify(serialize(t.update("petty_cash", eid, {"status": "void", "void_reason": reason[:300], "voided_by": g.user.get("name")})))
