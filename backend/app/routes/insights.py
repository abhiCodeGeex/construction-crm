"""Phase I block 5 — change requests from the client and the site, proposals in the portal, the missing reports and
inbound WhatsApp routed to the project and the right person.

* Change requests (§11 "change request raised by client, site or designer"): the client raises one in the portal, a
  Site Supervisor on the project from the site. Each becomes a *draft* change order (reason client request / site
  condition) marked with who asked; the PM prices it as usual. The client sees their requests and where they stand.
* Proposals in the portal (§13 "approve … quotes"): proposals sent to the client's contact are listed with their open
  link, so the client approves or answers them from one place.
* Reports (§14, §16): projects — delayed, upcoming milestones, open snags and issues, approvals pending; finance —
  cash flow by month (money received and paid, then what is due in and out); team — workload per person over the next
  four weeks against working days; follow-ups — client approvals and payments waiting longest.
* Inbound WhatsApp (§17 "routing rules send each item to the right person; escalation only for urgent items"): a message
  from a contact on a live project joins that project's thread with them; words about payment, material or design go
  to Accounts, Procurement or the designer on the project, everything to the PM, urgent words as a warning.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can, portal
from ..services import notify, project_events as ev, sales, workdays
from ..services.defaults import ROUTING, ROUTING_KEYWORDS, URGENT_KEYWORDS
from .projects import load, member

bp = Blueprint("insights", __name__)

LIVE = ["planning", "active", "on_hold"]


def r2(v):
    return round((v or 0) + 1e-9, 2)


# ============================== change requests ==============================
def open_stage(p, stage_id=None):
    if stage_id:
        return next((s for s in p.get("stages", []) if s["id"] == stage_id), None) or abort(400, "Stage not found")
    return next((s for s in p.get("stages", []) if s.get("status") != "done"), None) or (p.get("stages") or [None])[-1] or abort(409, "The project has no stages")


def make_request(p, d, who, kind):
    from .change_orders import new_co
    title = (d.get("title") or "").strip()[:150] or abort(400, "What would you like changed?")
    desc = (d.get("description") or "").strip()[:2000] or None
    st = open_stage(p, d.get("stage_id"))
    co = new_co(p, {"stage_id": st["id"], "title": title, "description": desc, "files": d.get("files") or [],
                    "reason": "client_request" if kind == "client" else "site_condition"},
                {"requested": {"kind": kind, "name": who, "at": t.now(), "contact_id": getattr(g, "contact_id", None) if kind == "client" else None}})
    ev.log(str(p["_id"]), "cost", f"Change requested by {'the client' if kind == 'client' else 'site'} ({who}): {title}")
    notify.send("co_decided", ev.managers(p), f"{p['name']}: change requested by {who} — {title}. Price it on the Change orders tab.",
                f"/app/projects/{p['_id']}?tab=changes", project_id=str(p["_id"]), skip_self=False)
    return co


@bp.post("/projects/<pid>/change-requests")
@api(None)
def site_request(pid):
    """A Site Supervisor (or anyone on the project who reads change orders) asks for a change."""
    if not (can("change_orders") or can("site", True)):
        abort(403, "Your role cannot ask for changes")
    p = load(pid)
    if g.role != "owner" and not member(p):
        abort(403, "Only people on the project ask for changes")
    co = make_request(p, request.get_json(force=True) or {}, g.user.get("name"), "site")
    from .change_orders import out
    return jsonify(out(co)), 201


@bp.get("/portal/projects/<pid>/change-requests")
@portal
def portal_requests(pid):
    from .site_reports import portal_project, is_client
    p = portal_project(pid)
    if not is_client(p):
        return jsonify([])
    rows = db.change_orders.find({"company_id": g.cid, "project_id": pid, "requested.contact_id": g.contact_id}).sort("created_at", -1)
    label = {"draft": "Being priced", "priced": "Being priced", "sent": "Priced — waiting for your approval", "approved": "Approved",
             "rejected": "Declined", "withdrawn": "Withdrawn"}
    return jsonify([{"id": str(c["_id"]), "number": c["number"], "title": c["title"], "description": c.get("description"),
                     "status": c["status"], "state": label.get(c["status"], c["status"]), "at": c["created_at"],
                     "total": c["totals"]["total"] if c["status"] in ("sent", "approved") else None} for c in rows])


@bp.post("/portal/projects/<pid>/change-requests")
@portal
def portal_request(pid):
    from .site_reports import portal_project, is_client
    p = portal_project(pid)
    if not is_client(p):
        abort(403, "Only the client asks for changes")
    co = make_request(p, request.get_json(force=True) or {}, g.user.get("name"), "client")
    return jsonify({"id": str(co["_id"]), "number": co["number"], "title": co["title"], "status": co["status"]}), 201


# ============================== proposals in the portal ==============================
@bp.get("/portal/proposals")
@portal
def portal_proposals():
    """Proposals sent to this client's contact (any of its leads): number, value, validity and the signing link."""
    leads = [str(x["_id"]) for x in db.leads.find({"company_id": g.cid, "contact_id": g.contact_id}, {"_id": 1})]
    out = []
    for p in db.proposals.find({"company_id": g.cid, "lead_id": {"$in": leads}, "status": {"$in": ["sent", "viewed", "accepted", "declined", "changes_requested"]}},
                               {"number": 1, "title": 1, "status": 1, "value": 1, "valid_until": 1, "token": 1, "sent_at": 1, "version": 1}).sort("sent_at", -1):
        out.append({"number": p.get("number"), "title": p.get("title"), "status": p["status"], "value": p.get("value"), "version": p.get("version"),
                    "valid_until": p.get("valid_until"), "link": f"/p/{p['token']}" if p.get("token") else None})
    return jsonify(serialize(out))


# ============================== reports ==============================
def visible_projects(extra=None):
    q = {"company_id": g.cid, "status": {"$in": LIVE}, **(extra or {})}
    if g.role not in ("owner", "accounts"):
        q["team.user_id"] = g.uid
    return list(db.projects.find(q))


@bp.get("/reports/projects")
@api("reports", write=False)
def projects_report():
    from ..services.project_health import health
    today = sales.today()
    in14 = (date.fromisoformat(today) + timedelta(days=14)).isoformat()
    delayed, milestones, rows = [], [], []
    for p in visible_projects():
        pid = str(p["_id"])
        late_stages = [s["name"] for s in p.get("stages", []) if s.get("status") != "done" and s.get("end") and s["end"] < today]
        late_tasks = sum(1 for s in p.get("stages", []) for tk in s.get("tasks", []) if tk["status"] != "done" and tk.get("end") and tk["end"] < today)
        try:
            fc = health(p)["forecast"]
        except Exception:  # a project without dates has no forecast
            fc = {}
        if late_stages or late_tasks or (fc.get("late_days") or 0) > 0:
            delayed.append({"project_id": pid, "project": f"{p.get('code') or ''} {p['name']}".strip(), "late_stages": late_stages,
                            "late_tasks": late_tasks, "late_days": fc.get("late_days") or 0, "finish": fc.get("finish")})
        for s in p.get("stages", []):
            for m in s.get("milestones", []):
                if m.get("status") != "achieved" and m.get("due") and m["due"] <= in14:
                    milestones.append({"project_id": pid, "project": p["name"], "stage": s["name"], "milestone": m["name"], "due": m["due"],
                                       "late": m["due"] < today})
        rows.append({"project_id": pid, "project": f"{p.get('code') or ''} {p['name']}".strip(),
                     "snags_open": db.snags.count_documents({"company_id": g.cid, "project_id": pid, "status": {"$ne": "closed"}}),
                     "snags_late": db.snags.count_documents({"company_id": g.cid, "project_id": pid, "status": {"$ne": "closed"}, "due": {"$lt": today, "$ne": None}}),
                     "issues_open": db.project_issues.count_documents({"company_id": g.cid, "project_id": pid, "status": {"$ne": "closed"}}),
                     "approvals_pending": db.permits.count_documents({"company_id": g.cid, "project_id": pid, "status": {"$in": ["submitted", "query"]}}),
                     "change_orders_waiting": db.change_orders.count_documents({"company_id": g.cid, "project_id": pid, "status": "sent"})})
    return jsonify({"delayed": sorted(delayed, key=lambda x: -x["late_days"]), "milestones": sorted(milestones, key=lambda x: x["due"]),
                    "open_items": [r for r in rows if any(v for k, v in r.items() if k not in ("project_id", "project"))]})


def month_of(d):
    return (d.isoformat() if hasattr(d, "isoformat") else str(d))[:7]


@bp.get("/reports/cashflow")
@api("finance", write=False)
def cashflow():
    """Money in and out by month: the last three months as it happened, the next three from what is due."""
    if g.role not in ("owner", "accounts") and g.hide_costs:
        abort(403, "Your role cannot see cash flow")
    today = date.fromisoformat(sales.today())
    first = date(today.year, today.month, 1)
    months = []
    for k in range(-3, 4):
        y, m = divmod(first.month - 1 + k, 12)
        months.append(f"{first.year + y}-{m + 1:02d}")
    rows = {m: {"month": m, "in": 0.0, "out": 0.0, "expected_in": 0.0, "expected_out": 0.0} for m in months}
    pids = None if g.role in ("owner", "accounts") else [str(p["_id"]) for p in visible_projects()]
    scope = {} if pids is None else {"project_id": {"$in": pids}}
    for r in db.receipts.find({"company_id": g.cid, "status": "received", **scope}, {"amount": 1, "date": 1}):
        if month_of(r["date"]) in rows:
            rows[month_of(r["date"])]["in"] += r["amount"]
    for r in db.lead_receipts.find({"company_id": g.cid, "status": "received"}, {"amount": 1, "date": 1, "project_id": 1}):
        if month_of(r["date"]) in rows and (pids is None or r.get("project_id") in pids):
            rows[month_of(r["date"])]["in"] += r["amount"]
    for v in db.vendor_payments.find({"company_id": g.cid, "status": {"$ne": "void"}, **scope}, {"amount": 1, "date": 1}):
        if month_of(v["date"]) in rows:
            rows[month_of(v["date"])]["out"] += v["amount"]
    for c in db.costs.find({"company_id": g.cid, "status": "approved", "bill_id": None, **scope}, {"amount": 1, "tax": 1, "date": 1}):
        if month_of(c["date"]) in rows:  # costs paid directly (no supplier bill)
            rows[month_of(c["date"])]["out"] += c["amount"] + (c.get("tax") or 0)
    from .invoices import balance
    this = month_of(today)
    for inv in db.invoices.find({"company_id": g.cid, "status": {"$in": ["sent", "part_paid"]}, "kind": {"$ne": "credit_note"}, **scope}):
        m = max(month_of(inv.get("due_date") or today), this)  # overdue counts as expected now
        if m in rows:
            rows[m]["expected_in"] += balance(inv)
    for b in db.vendor_bills.find({"company_id": g.cid, "status": {"$in": ["approved", "part_paid"]}, **scope}):
        m = max(month_of(b.get("due_date") or today), this)
        if m in rows:
            rows[m]["expected_out"] += b["total"] - b.get("paid", 0)
    for po in db.purchase_orders.find({"company_id": g.cid, "status": {"$in": ["approved", "sent", "acknowledged", "part_received"]}, **scope}):
        left = sum((ln["qty"] - ln.get("billed_qty", 0) - ln.get("short_closed_qty", 0)) * ln.get("unit_cost", 0) * (1 + ln.get("tax_pct", 0) / 100)
                   for ln in po["lines"])
        m = max(month_of(po.get("expected_date") or today), this)
        if m in rows and left > 0:
            rows[m]["expected_out"] += left  # ordered, not yet billed: paid about when it arrives
    out, running = [], 0.0
    for m in months:
        x = {k: r2(v) if isinstance(v, float) else v for k, v in rows[m].items()}
        x["net"] = r2(x["in"] + x["expected_in"] - x["out"] - x["expected_out"])
        running = r2(running + x["net"])
        x["running"] = running
        x["past"] = m < this
        out.append(x)
    return jsonify({"months": out})


@bp.get("/reports/team")
@api("reports", write=False)
def team_report():
    """Open tasks per person, overdue, and working days of work in the next four weeks against the days available."""
    today = date.fromisoformat(sales.today())
    end = today + timedelta(days=27)
    cal = workdays.calendar()
    capacity = sum(1 for k in range(28) if workdays.is_working(today + timedelta(days=k), cal))
    people = {}
    for p in visible_projects():
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                if tk["status"] == "done" or not tk.get("assignee_id"):
                    continue
                x = people.setdefault(tk["assignee_id"], {"user_id": tk["assignee_id"], "name": tk.get("assignee_name"), "open": 0, "overdue": 0,
                                                          "load_days": 0, "projects": set()})
                x["open"] += 1
                x["projects"].add(p["name"])
                if tk.get("end") and tk["end"] < today.isoformat():
                    x["overdue"] += 1
                if tk.get("start") and tk.get("end"):
                    a, b = max(date.fromisoformat(tk["start"]), today), min(date.fromisoformat(tk["end"]), end)
                    if tk["end"] < today.isoformat():
                        a, b = today, today  # overdue work still needs a day
                    x["load_days"] += sum(1 for k in range((b - a).days + 1) if workdays.is_working(a + timedelta(days=k), cal)) if b >= a else 0
    rows = []
    for u in db.users.find({"company_id": g.cid, "kind": {"$ne": "external"}, "active": {"$ne": False}}, {"name": 1, "role": 1}):
        x = people.get(str(u["_id"]), {"user_id": str(u["_id"]), "open": 0, "overdue": 0, "load_days": 0, "projects": set()})
        x["name"] = u["name"]
        x["role"] = u.get("role")
        x["projects"] = sorted(x["projects"])
        x["utilisation_pct"] = round(x["load_days"] / capacity * 100) if capacity else None
        rows.append(x)
    return jsonify({"capacity_days": capacity, "from": today.isoformat(), "to": end.isoformat(),
                    "people": sorted(rows, key=lambda r: -(r["utilisation_pct"] or 0))})


@bp.get("/reports/waiting")
@api("followups", write=False)
def waiting_longest():
    """Client approvals and payments waiting longest (§16 reports)."""
    today = date.fromisoformat(sales.today())
    pids = [str(p["_id"]) for p in visible_projects()]
    names = {str(p["_id"]): p["name"] for p in db.projects.find({"_id": {"$in": [oid(x) for x in pids]}}, {"name": 1})}

    def days(since):
        if not since:
            return 0
        d = since.date() if hasattr(since, "date") else date.fromisoformat(str(since)[:10])
        return (today - d).days

    approvals = []
    for co in db.change_orders.find({"company_id": g.cid, "project_id": {"$in": pids}, "status": "sent"}):
        approvals.append({"kind": "Change order", "what": f"{co['number']} {co['title']}", "project": names.get(co["project_id"]),
                          "project_id": co["project_id"], "since": co.get("sent_at"), "days": days(co.get("sent_at"))})
    for s in db.selections.find({"company_id": g.cid, "project_id": {"$in": pids}, "status": "options_sent"}):
        approvals.append({"kind": "Selection", "what": s["item"], "project": names.get(s["project_id"]), "project_id": s["project_id"],
                          "since": s.get("options_sent_at") or s.get("updated_at"), "days": days(s.get("options_sent_at") or s.get("updated_at"))})
    for tr in db.transmittals.find({"company_id": g.cid, "project_id": {"$in": pids}, "acknowledged": None, "purpose": "for_approval"}):
        approvals.append({"kind": "Drawings for approval", "what": tr["number"], "project": names.get(tr["project_id"]), "project_id": tr["project_id"],
                          "since": tr["created_at"], "days": days(tr["created_at"])})
    payments = []
    from .invoices import balance
    if can("finance"):
        for inv in db.invoices.find({"company_id": g.cid, "project_id": {"$in": pids}, "status": {"$in": ["sent", "part_paid"]}, "kind": {"$ne": "credit_note"}}):
            late = days(inv.get("due_date")) if inv.get("due_date") else 0
            if late > 0:
                payments.append({"kind": "Invoice", "what": inv["number"], "client": inv.get("client_name"), "project": inv.get("project_name"),
                                 "project_id": inv.get("project_id"), "amount": balance(inv), "days": late})
    return jsonify(serialize({"approvals": sorted(approvals, key=lambda x: -x["days"])[:50], "payments": sorted(payments, key=lambda x: -x["days"])[:50]}))


# ============================== inbound WhatsApp routing ==============================
def route_inbound(contact, text):
    """Called for each inbound WhatsApp message (not STOP) from a known contact. Returns where it went."""
    projects = list(db.projects.find({"company_id": g.cid, "status": {"$in": LIVE}, "team.contact_id": str(contact["_id"])}).sort("updated_at", -1))
    if not projects:
        return None
    p = projects[0]  # the contact's most recently active project
    pid, cid_ = str(p["_id"]), str(contact["_id"])
    low = text.lower()
    topic = next((tp for words, tp in ROUTING_KEYWORDS if any(w in low for w in words)), "general")
    urgent = any(w in low for w in URGENT_KEYWORDS)
    role = ROUTING.get(topic, "pm")
    staff = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("kind") != "external"]
    roles = {str(u["_id"]): u["role"] for u in db.users.find({"_id": {"$in": [oid(x) for x in staff]}}, {"role": 1})}
    target = [u for u in staff if roles.get(u) == role] or (notify.role_users(role) if role in ("accounts", "procurement") else [])
    who = list(dict.fromkeys(target + ev.managers(p)))
    t.insert("messages", {"project_id": pid, "project_name": p["name"], "contact_id": cid_, "contact_name": contact["name"],
                          "channel": "portal", "via": "whatsapp", "side": "contact", "author": contact["name"], "user_id": None,
                          "text": text[:4000], "files": [], "read_by_team": False, "read_by_contact": True, "topic": topic, "urgent": urgent})
    notify.send("portal_message", who, f"{'URGENT · ' if urgent else ''}{contact['name']} on WhatsApp ({p['name']}): {text[:140]}",
                f"/app/inbox?project={pid}&contact={cid_}", project_id=pid, skip_self=False, level="warn" if urgent else "info")
    return {"project_id": pid, "topic": topic, "urgent": urgent, "to": who}
