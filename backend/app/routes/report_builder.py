"""Phase L block 6 — advanced reports and dashboards (v4 Phase 3).

* Report builder: pick a dataset (leads, projects, invoices, payments received, costs, follow-ups, site reports, safety
  incidents, timesheet hours), group by one or two fields (a month, a person, a status …), choose what to count or
  add up, filter by date range and field values. The result is a table and a chart; it exports to CSV.
  Each dataset needs the area that already guards it (finance for money, costs only for roles that see costs); the
  rows a person can see are the ones they see elsewhere (a salesperson their own leads, staff their own projects).
* Saved reports: kept for me or shared with the company; one can be emailed (CSV attached) every week or month to
  people in the company — the worker sends it on Monday / the 1st.
* Dashboards: each person arranges their own — tiles (a number), bar, line and pie charts and tables, each a saved
  report or an inline one; a company dashboard can be shared by an Owner.
"""
import csv
import io
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g, Response

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, sales

bp = Blueprint("report_builder", __name__)
CHARTS = ("table", "bar", "line", "pie", "kpi")


def month(v):
    s = v.isoformat() if hasattr(v, "isoformat") else str(v or "")
    return s[:7] or None


def day(v):
    s = v.isoformat() if hasattr(v, "isoformat") else str(v or "")
    return s[:10] or None


# dataset -> collection, guard, date field, dimensions {key: (label, getter)}, measures {key: (label, getter or None=count)}
DATASETS = {
    "leads": {"label": "Leads", "coll": "leads", "area": "leads", "date": lambda d: day(d.get("created_at")),
              "dims": {"stage": ("Stage", lambda d: d.get("stage")), "status": ("Status", lambda d: d.get("status")),
                       "source": ("Source", lambda d: d.get("source")), "service": ("Service", lambda d: d.get("service")),
                       "project_type": ("Project type", lambda d: d.get("project_type")), "owner": ("Salesperson", lambda d: d.get("owner_name")),
                       "location": ("Location", lambda d: d.get("location")), "month": ("Month created", lambda d: month(d.get("created_at")))},
              "measures": {"count": ("Leads", None), "budget": ("Budget", lambda d: d.get("budget") or 0)}},
    "projects": {"label": "Projects", "coll": "projects", "area": "projects", "date": lambda d: d.get("start") or day(d.get("created_at")),
                 "dims": {"status": ("Status", lambda d: d.get("status")), "service": ("Service", lambda d: ", ".join(d.get("services") or []) or None),
                          "project_type": ("Project type", lambda d: d.get("project_type")), "client": ("Client", lambda d: d.get("client_name")),
                          "branch": ("Branch", lambda d: d.get("branch")), "health": ("Health", lambda d: d.get("health_grade")),
                          "pm": ("Project manager", lambda d: next((m["name"] for m in d.get("team", []) if m.get("project_role") == "Project Manager"), None)),
                          "month": ("Start month", lambda d: (d.get("start") or "")[:7] or None)},
                 "measures": {"count": ("Projects", None), "value": ("Contract value", lambda d: d.get("value") or 0),
                              "progress": ("Average progress %", "avg:progress")}},
    "invoices": {"label": "Invoices", "coll": "invoices", "area": "finance", "date": lambda d: d.get("date"),
                 "dims": {"status": ("Status", lambda d: d.get("status")), "kind": ("Kind", lambda d: d.get("kind")),
                          "project": ("Project", lambda d: d.get("project_name")), "client": ("Client", lambda d: d.get("client_name")),
                          "month": ("Invoice month", lambda d: (d.get("date") or "")[:7] or None)},
                 "measures": {"count": ("Invoices", None), "total": ("Total", lambda d: d.get("total") or 0), "paid": ("Paid", lambda d: d.get("paid") or 0),
                              "due": ("Outstanding", lambda d: max(0, (d.get("total") or 0) - (d.get("paid") or 0) - (d.get("credited") or 0)) if d.get("status") not in ("void", "draft") else 0)}},
    "payments": {"label": "Payments received", "coll": "payments", "area": "finance", "date": lambda d: d.get("date") or day(d.get("created_at")),
                 "dims": {"mode": ("Mode", lambda d: d.get("mode")), "project": ("Project", lambda d: d.get("project_name")),
                          "client": ("Client", lambda d: d.get("client_name")), "month": ("Month", lambda d: (d.get("date") or day(d.get("created_at")) or "")[:7] or None)},
                 "measures": {"count": ("Payments", None), "amount": ("Amount", lambda d: d.get("amount") or 0)}},
    "costs": {"label": "Project costs", "coll": "costs", "area": "finance", "costs": True, "date": lambda d: d.get("date") or day(d.get("created_at")),
              "dims": {"category": ("Cost head", lambda d: d.get("category")), "project": ("Project", lambda d: d.get("project_name")),
                       "vendor": ("Vendor", lambda d: d.get("vendor_name") or d.get("party")), "status": ("Status", lambda d: d.get("status")),
                       "month": ("Month", lambda d: (d.get("date") or day(d.get("created_at")) or "")[:7] or None)},
              "measures": {"count": ("Entries", None), "amount": ("Amount", lambda d: d.get("amount") or 0)}},
    "followups": {"label": "Follow-ups", "coll": "followups", "area": "followups", "date": lambda d: d.get("due"),
                  "dims": {"status": ("Status", lambda d: d.get("status")), "owner": ("Owner", lambda d: d.get("owner_name")),
                           "channel": ("Channel", lambda d: d.get("channel")), "priority": ("Priority", lambda d: d.get("priority")),
                           "month": ("Due month", lambda d: (d.get("due") or "")[:7] or None)},
                  "measures": {"count": ("Follow-ups", None), "overdue": ("Overdue", lambda d: 1 if d.get("status") == "open" and (d.get("due") or "9") < sales.today() else 0)}},
    "site_reports": {"label": "Site reports", "coll": "site_reports", "area": "site", "date": lambda d: d.get("date"),
                     "dims": {"project": ("Project", lambda d: d.get("project_name")), "author": ("Written by", lambda d: d.get("author_name")),
                              "weather": ("Weather", lambda d: (d.get("weather") or {}).get("kind")), "month": ("Month", lambda d: (d.get("date") or "")[:7] or None)},
                     "measures": {"count": ("Reports", None), "headcount": ("Worker-days", lambda d: d.get("headcount") or 0),
                                  "photos": ("Photos", lambda d: len(d.get("photos") or []))}},
    "incidents": {"label": "Safety incidents", "coll": "incidents", "area": "site", "date": lambda d: d.get("date"),
                  "dims": {"kind": ("Kind", lambda d: d.get("kind")), "severity": ("Severity", lambda d: d.get("severity")),
                           "project": ("Project", lambda d: d.get("project_name")), "status": ("Status", lambda d: d.get("status")),
                           "month": ("Month", lambda d: (d.get("date") or "")[:7] or None)},
                  "measures": {"count": ("Incidents", None), "lost_days": ("Lost days", lambda d: d.get("lost_days") or 0)}},
    "hours": {"label": "Timesheet hours", "coll": "timesheets", "area": "projects", "date": lambda d: d.get("date"),
              "dims": {"person": ("Person", lambda d: d.get("user_name")), "project": ("Project", lambda d: d.get("project_name")),
                       "status": ("Status", lambda d: d.get("status")), "billable": ("Billable", lambda d: "Billable" if d.get("billable") else "Not billable"),
                       "month": ("Month", lambda d: (d.get("date") or "")[:7] or None)},
              "measures": {"count": ("Entries", None), "hours": ("Hours", lambda d: d.get("hours") or 0)}},
}


for _k, _m in (("invoices", ("total", "paid", "due")), ("payments", ("amount",)), ("costs", ("amount",)), ("projects", ("value",))):
    DATASETS[_k]["money"] = _m
    DATASETS[_k]["dims"]["currency"] = ("Currency", lambda d: d.get("currency") or g.company.get("currency") or "INR")


def fx(doc):
    """Money in a project's own currency is added up in the company's, at the rates in Settings (Phase L)."""
    base = g.company.get("currency") or "INR"
    cur = doc.get("currency") or base
    return 1.0 if cur == base else float((g.company.get("fx_rates") or {}).get(cur) or 0) or 1.0


def allowed(ds):
    spec = DATASETS.get(ds) or abort(400, "Unknown dataset")
    if not can(spec["area"]):
        abort(403, f"Your role cannot report on {spec['label'].lower()}")
    if spec.get("costs") and g.hide_costs:
        abort(403, "Your role cannot see costs")
    return spec


def scope(ds):
    """The rows this person sees elsewhere: a salesperson's own leads, staff on their projects."""
    q = {}
    if g.role == "owner" or (ds == "leads" and sales.is_manager()):
        return q
    if ds == "leads":
        return {"owner_id": g.uid}
    if ds == "followups":
        return {} if g.role in ("pm",) else {"owner_id": g.uid}
    if g.role in ("accounts",) and ds in ("invoices", "payments", "costs"):
        return q
    pids = [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]
    if ds == "projects":
        return {"_id": {"$in": [oid(x) for x in pids]}}
    if ds == "hours" and g.role not in ("pm",):
        return {"user_id": g.uid}
    return {"project_id": {"$in": pids}}


def clean_spec(d):
    ds = d.get("dataset")
    spec = allowed(ds)
    group = [x for x in (d.get("group_by") or []) if x][:2]
    for x in group:
        if x not in spec["dims"]:
            abort(400, f"Cannot group {spec['label'].lower()} by {x}")
    measures = [x for x in (d.get("measures") or ["count"]) if x][:4] or ["count"]
    for x in measures:
        if x not in spec["measures"]:
            abort(400, f"Unknown measure {x}")
    filters = {}
    for k, v in (d.get("filters") or {}).items():
        if k not in spec["dims"]:
            abort(400, f"Cannot filter on {k}")
        vals = v if isinstance(v, list) else [v]
        filters[k] = [str(x)[:100] for x in vals if x not in (None, "")][:50]
    rng = d.get("range") or {}
    out = {"dataset": ds, "group_by": group, "measures": measures, "filters": {k: v for k, v in filters.items() if v},
           "range": {"from": str(rng.get("from") or "")[:10] or None, "to": str(rng.get("to") or "")[:10] or None, "last_days": None},
           "chart": d.get("chart") if d.get("chart") in CHARTS else "table", "sort": d.get("sort") if d.get("sort") in ("value", "label") else "value",
           "limit": max(1, min(500, int(d.get("limit") or 50)))}
    if rng.get("last_days"):
        try:
            out["range"]["last_days"] = max(1, min(3650, int(rng["last_days"])))
        except (TypeError, ValueError):
            abort(400, "Last days is a number")
    return out


def execute(sp):
    spec = DATASETS[sp["dataset"]]
    frm, to = sp["range"]["from"], sp["range"]["to"]
    if sp["range"].get("last_days"):
        frm, to = (date.fromisoformat(sales.today()) - timedelta(days=sp["range"]["last_days"] - 1)).isoformat(), sales.today()
    rows = db[spec["coll"]].find({"company_id": g.cid, **scope(sp["dataset"])}).limit(20000)
    groups, n = {}, 0
    for doc in rows:
        dt = spec["date"](doc)
        if (frm and (not dt or dt < frm)) or (to and (not dt or dt > to)):
            continue
        if any(str(spec["dims"][k][1](doc) or "(none)") not in v for k, v in sp["filters"].items()):
            continue
        n += 1
        key = tuple(str(spec["dims"][k][1](doc) or "(none)") for k in sp["group_by"]) or ("All",)
        acc = groups.setdefault(key, {m: 0.0 for m in sp["measures"]} | {"_n": 0})
        acc["_n"] += 1
        for m in sp["measures"]:
            get = spec["measures"][m][1]
            if get is None:
                acc[m] += 1
            elif isinstance(get, str) and get.startswith("avg:"):
                from .projects import project_progress
                acc[m] += project_progress(doc) if get == "avg:progress" else 0
            else:
                acc[m] += float(get(doc) or 0) * (fx(doc) if m in spec.get("money", ()) else 1)
    out = []
    for key, acc in groups.items():
        row = {"keys": list(key)}
        for m in sp["measures"]:
            v = acc[m] / acc["_n"] if isinstance(spec["measures"][m][1], str) and acc["_n"] else acc[m]
            row[m] = round(v + 1e-9, 2)
        out.append(row)
    first = sp["measures"][0]
    if sp["sort"] == "label" or (sp["group_by"] and sp["group_by"][0] == "month"):
        out.sort(key=lambda r: r["keys"])
    else:
        out.sort(key=lambda r: -r[first])
    totals = {m: round(sum(r[m] for r in out) + 1e-9, 2) for m in sp["measures"] if not isinstance(spec["measures"][m][1], str)}
    return {"spec": sp, "columns": [{"key": k, "label": spec["dims"][k][0]} for k in sp["group_by"]] + [{"key": m, "label": spec["measures"][m][0], "measure": True} for m in sp["measures"]],
            "rows": out[:sp["limit"]], "more": max(0, len(out) - sp["limit"]), "totals": totals, "matched": n, "from": frm, "to": to,
            "currency": g.company.get("currency") or "INR"}


@bp.get("/report-builder")
@api(None)
def datasets():
    out = []
    for k, s in DATASETS.items():
        if can(s["area"]) and not (s.get("costs") and g.hide_costs):
            out.append({"key": k, "label": s["label"], "dims": [{"key": a, "label": b[0]} for a, b in s["dims"].items()],
                        "measures": [{"key": a, "label": b[0]} for a, b in s["measures"].items()]})
    return jsonify({"datasets": out, "charts": CHARTS})


@bp.post("/report-builder/run")
@api(None)
def run_report():
    return jsonify(execute(clean_spec(request.get_json(force=True) or {})))


@bp.get("/report-builder/values")
@api(None)
def values():
    """The values a dimension takes (for the filter pick-list)."""
    ds, dim = request.args.get("dataset"), request.args.get("dim")
    spec = allowed(ds)
    get = (spec["dims"].get(dim) or abort(400, "Unknown field"))[1]
    vals = set()
    for doc in db[spec["coll"]].find({"company_id": g.cid, **scope(ds)}).limit(5000):
        vals.add(str(get(doc) or "(none)"))
    return jsonify(sorted(vals)[:300])


def csv_of(res):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["label"] for c in res["columns"]])
    for r in res["rows"]:
        w.writerow(r["keys"][:len(res["spec"]["group_by"])] + [r[m] for m in res["spec"]["measures"]])
    if res["totals"]:
        w.writerow(["Total"] + [""] * max(0, len(res["spec"]["group_by"]) - 1) + [res["totals"].get(m, "") for m in res["spec"]["measures"]])
    return buf.getvalue()


@bp.post("/report-builder/csv")
@api(None)
def export_csv():
    res = execute(clean_spec(request.get_json(force=True) or {}))
    return Response(csv_of(res), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={res['spec']['dataset']}-report.csv"})


# ============================== saved reports ==============================
def visible_reports():
    return t.find("saved_reports", {"$or": [{"owner_id": g.uid}, {"shared": True}]}, sort=[("name", 1)])


def rep_out(r):
    d = serialize(r)
    d["mine"] = r["owner_id"] == g.uid
    try:
        allowed(r["spec"]["dataset"])
        d["can_run"] = True
    except Exception:  # noqa: BLE001 — a shared report on a dataset this role cannot see
        d["can_run"] = False
    return d


@bp.get("/saved-reports")
@api(None)
def list_saved():
    return jsonify([rep_out(r) for r in visible_reports()])


def clean_schedule(d):
    s = d.get("schedule")
    if not s or not s.get("every"):
        return None
    if s["every"] not in ("week", "month"):
        abort(400, "Email it every week or every month")
    to = []
    for uid in dict.fromkeys(s.get("to") or []):
        u = db.users.find_one({"_id": oid(uid), "company_id": g.cid, "kind": "staff"}) or abort(400, "Send it to people in the company")
        to.append({"user_id": uid, "name": u["name"]})
    if not to:
        abort(400, "Who gets the email?")
    return {"every": s["every"], "to": to, "last_sent": None}


@bp.post("/saved-reports")
@api(None)
def save_report():
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip()[:100] or abort(400, "Name the report")
    shared = bool(d.get("shared"))
    if shared and g.role not in ("owner", "pm"):
        abort(403, "Only an Owner or a PM shares reports with the company")
    r = t.insert("saved_reports", {"name": name, "spec": clean_spec(d.get("spec") or {}), "shared": shared, "owner_id": g.uid,
                                   "owner_name": g.user.get("name"), "schedule": clean_schedule(d)})
    return jsonify(rep_out(r)), 201


@bp.put("/saved-reports/<rid>")
@api(None)
def edit_saved(rid):
    r = t.get("saved_reports", rid)
    if r["owner_id"] != g.uid and g.role != "owner":
        abort(403, "Only the person who saved it (or an Owner) changes it")
    d = request.get_json(force=True) or {}
    ch = {}
    if "name" in d:
        ch["name"] = (d.get("name") or "").strip()[:100] or abort(400, "Name the report")
    if "spec" in d:
        ch["spec"] = clean_spec(d["spec"])
    if "shared" in d:
        if d["shared"] and g.role not in ("owner", "pm"):
            abort(403, "Only an Owner or a PM shares reports with the company")
        ch["shared"] = bool(d["shared"])
    if "schedule" in d:
        ch["schedule"] = clean_schedule(d)
    return jsonify(rep_out(t.update("saved_reports", rid, ch)))


@bp.delete("/saved-reports/<rid>")
@api(None)
def delete_saved(rid):
    r = t.get("saved_reports", rid)
    if r["owner_id"] != g.uid and g.role != "owner":
        abort(403, "Only the person who saved it (or an Owner) deletes it")
    t.delete("saved_reports", rid)
    db.dashboards.update_many({"company_id": g.cid}, {"$pull": {"widgets": {"report_id": rid}}})
    return jsonify({"ok": True})


@bp.get("/saved-reports/<rid>/run")
@api(None)
def run_saved(rid):
    r = t.get("saved_reports", rid)
    if r["owner_id"] != g.uid and not r.get("shared"):
        abort(404, "saved_report not found")
    return jsonify({**execute(clean_spec(r["spec"])), "name": r["name"]})


# ============================== dashboards ==============================
def dash_out(dsh):
    d = serialize(dsh)
    d["mine"] = dsh.get("owner_id") == g.uid
    return d


@bp.get("/dashboards")
@api(None)
def list_dashboards():
    return jsonify([dash_out(x) for x in t.find("dashboards", {"$or": [{"owner_id": g.uid}, {"shared": True}]}, sort=[("name", 1)])])


def clean_widgets(ws):
    out = []
    reps = {str(r["_id"]) for r in visible_reports()}
    for w in (ws or [])[:24]:
        x = {"id": w.get("id") or t.sid(), "title": (w.get("title") or "").strip()[:80] or None,
             "chart": w.get("chart") if w.get("chart") in CHARTS else "table", "width": w.get("width") if w.get("width") in (1, 2, 3) else 1,
             "report_id": None, "spec": None}
        if w.get("report_id"):
            if w["report_id"] not in reps:
                abort(400, "A widget's saved report was not found")
            x["report_id"] = w["report_id"]
        else:
            x["spec"] = clean_spec(w.get("spec") or {})
        out.append(x)
    return out


@bp.post("/dashboards")
@api(None)
def add_dashboard():
    d = request.get_json(force=True) or {}
    if d.get("shared") and g.role != "owner":
        abort(403, "Only an Owner shares a dashboard with the company")
    x = t.insert("dashboards", {"name": (d.get("name") or "").strip()[:80] or "My dashboard", "owner_id": g.uid, "owner_name": g.user.get("name"),
                                "shared": bool(d.get("shared")), "widgets": clean_widgets(d.get("widgets"))})
    return jsonify(dash_out(x)), 201


@bp.put("/dashboards/<did>")
@api(None)
def edit_dashboard(did):
    x = t.get("dashboards", did)
    if x["owner_id"] != g.uid and not (g.role == "owner" and x.get("shared")):
        abort(403, "This is someone else's dashboard")
    d = request.get_json(force=True) or {}
    ch = {}
    if "name" in d:
        ch["name"] = (d.get("name") or "").strip()[:80] or "My dashboard"
    if "widgets" in d:
        ch["widgets"] = clean_widgets(d["widgets"])
    if "shared" in d:
        if d["shared"] and g.role != "owner":
            abort(403, "Only an Owner shares a dashboard with the company")
        ch["shared"] = bool(d["shared"])
    return jsonify(dash_out(t.update("dashboards", did, ch)))


@bp.delete("/dashboards/<did>")
@api(None)
def delete_dashboard(did):
    x = t.get("dashboards", did)
    if x["owner_id"] != g.uid and g.role != "owner":
        abort(403, "This is someone else's dashboard")
    t.delete("dashboards", did)
    return jsonify({"ok": True})


@bp.get("/dashboards/<did>/data")
@api(None)
def dashboard_data(did):
    """Every widget run for this viewer: a widget on a dataset the viewer's role cannot see says so instead."""
    x = t.get("dashboards", did)
    if x["owner_id"] != g.uid and not x.get("shared"):
        abort(404, "dashboard not found")
    out = []
    for w in x.get("widgets", []):
        try:
            if w.get("report_id"):
                r = db.saved_reports.find_one({"_id": oid(w["report_id"]), "company_id": g.cid})
                if not r:
                    raise LookupError("The saved report was deleted")
                res = execute(clean_spec(r["spec"]))
                title = w.get("title") or r["name"]
            else:
                res = execute(clean_spec(w["spec"]))
                title = w.get("title") or DATASETS[w["spec"]["dataset"]]["label"]
            out.append({"id": w["id"], "title": title, "chart": w["chart"], "width": w["width"], "result": res})
        except LookupError as e:
            out.append({"id": w["id"], "title": w.get("title") or "Report", "chart": w["chart"], "width": w["width"], "error": str(e)})
        except Exception as e:  # noqa: BLE001 — HTTPException from a guard: this viewer cannot see it
            out.append({"id": w["id"], "title": w.get("title") or "Report", "chart": w["chart"], "width": w["width"],
                        "error": getattr(e, "description", None) or "Cannot show this widget"})
    return jsonify({"dashboard": dash_out(x), "widgets": out})


# ============================== scheduled emails ==============================
def check_reports(now):
    """Saved reports with a schedule: Monday for weekly, the 1st for monthly; each recipient gets it with their own access."""
    today = now.date()
    for r in db.saved_reports.find({"company_id": g.cid, "schedule": {"$ne": None}}):
        s = r["schedule"]
        due = (s["every"] == "week" and today.weekday() == 0) or (s["every"] == "month" and today.day == 1)
        if not due or s.get("last_sent") == today.isoformat():
            continue
        owner = db.users.find_one({"_id": oid(r["owner_id"]), "active": {"$ne": False}})
        if not owner:
            continue
        from ..security import effective_perms, HIDE_COST_ROLES
        saved = {k: getattr(g, k, None) for k in ("uid", "role", "user", "hide_costs", "perms")}
        try:  # run as the report's owner, so it never shows more than they see
            g.uid, g.role, g.user, g.hide_costs = str(owner["_id"]), owner["role"], owner, owner["role"] in HIDE_COST_ROLES
            g.perms = effective_perms(owner["role"], g.company)
            res = execute(clean_spec(r["spec"]))
        except Exception:  # noqa: BLE001 — the owner lost access: skip, try next time
            res = None
        finally:
            for k, v in saved.items():
                setattr(g, k, v)
        if res is None:
            continue
        body = f"{r['name']} — {res['matched']} record(s)" + (f", {res['from']} to {res['to']}" if res.get("from") else "") + ".\nThe CSV is attached."
        for rcp in s["to"]:
            u = db.users.find_one({"_id": oid(rcp["user_id"]), "active": {"$ne": False}})
            if u and u.get("email"):
                notify.deliver(g.company, u["email"], f"Report: {r['name']}", body, attachments=[(f"{r['name']}.csv", csv_of(res).encode())])
        db.saved_reports.update_one({"_id": r["_id"]}, {"$set": {"schedule.last_sent": today.isoformat()}})
