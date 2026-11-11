"""Projects in depth (Phase B+ block 3): the project timeline, baselines (the agreed plan), delays with their
reason and who caused them, and the company's working days and holidays."""
from datetime import date

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, serialize
from ..security import api, can
from ..services import project_events as ev, workdays
from ..services.defaults import DELAY_REASONS, WAITING_PARTIES, WEEKDAYS, LINK_TYPES
from .projects import load, require_edit, all_tasks, d

bp = Blueprint("project_plan", __name__)


# ---------------- working days and holidays (Settings -> Projects calendar) ----------------
@bp.get("/settings/calendar")
@api(None)
def get_calendar():
    return jsonify({**workdays.calendar(), "weekdays": WEEKDAYS})


@bp.put("/settings/calendar")
@api("settings")
def put_calendar():
    dat = request.get_json(force=True) or {}
    days = dat.get("working_days")
    if not isinstance(days, list) or not days or any(x not in range(7) for x in days):
        abort(400, "Choose at least one working day (0 = Monday … 6 = Sunday)")
    hols, seen = [], set()
    for h in dat.get("holidays") or []:
        day = d(h.get("date"), "Holiday date", required=True)
        name = (h.get("name") or "").strip()
        if not name:
            abort(400, f"Give the holiday on {day} a name")
        if day in seen:
            abort(400, f"{day} is listed twice")
        seen.add(day)
        hols.append({"date": day, "name": name[:80]})
    cal = {"working_days": sorted(set(days)), "holidays": sorted(hols, key=lambda x: x["date"])}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"calendar": cal}})
    t.audit("update", "calendar", g.company["_id"], note=f"{len(cal['working_days'])} working days a week, {len(hols)} holidays")
    return jsonify({**cal, "weekdays": WEEKDAYS})


# ---------------- baseline: the agreed plan ----------------
@bp.post("/projects/<_id>/baseline")
@api("projects")
def set_baseline(_id):
    """Freeze today's dates as the plan everyone agreed. From then on, a date moved later needs a reason, and
    every task and stage shows how many working days it is behind (or ahead of) this plan."""
    p = load(_id)
    require_edit(p)
    note = ((request.get_json(force=True) or {}).get("note") or "").strip()[:300] or None
    snap = {"id": t.sid(), "at": t.now().isoformat(), "by": g.user.get("name"), "note": note,
            "project_end": p.get("planned_end"),
            "stages": {s["id"]: {"start": s.get("start"), "end": s.get("end")} for s in p.get("stages", [])},
            "tasks": {tid: {"start": tk.get("start"), "end": tk.get("end")} for tid, (_, tk) in all_tasks(p).items()}}
    count = len(p.get("baselines") or [])
    t.update("projects", _id, {}, raw={"$push": {"baselines": snap}})
    ev.log(_id, "baseline", f"Baseline {count + 1} set: planned finish {p.get('planned_end')}" + (f" — {note}" if note else ""))
    from .projects import present
    return jsonify(present(t.get("projects", _id))), 201


@bp.get("/projects/<_id>/baselines")
@api("projects")
def list_baselines(_id):
    p = load(_id)
    return jsonify([{k: b[k] for k in ("id", "at", "by", "note", "project_end")} for b in reversed(p.get("baselines") or [])])


# ---------------- delays ----------------
@bp.get("/projects/<_id>/delays")
@api("projects")
def list_delays(_id):
    """Every date moved later after the baseline, with the reason and who caused it; totals per party."""
    load(_id)
    rows = list(db.project_delays.find({"company_id": g.cid, "project_id": _id}).sort("at", -1))
    by_party, by_reason = {}, {}
    for r in rows:
        by_party[r["party"]] = by_party.get(r["party"], 0) + r["days"]
        by_reason[r["reason_label"]] = by_reason.get(r["reason_label"], 0) + r["days"]
    labels = {**WAITING_PARTIES, "none": "Nobody (weather / site)", "other": "Other"}
    return jsonify({"rows": serialize(rows),
                    "by_party": sorted([{"party": k, "label": labels.get(k, k), "days": v} for k, v in by_party.items()],
                                       key=lambda x: -x["days"]),
                    "by_reason": sorted([{"reason": k, "days": v} for k, v in by_reason.items()], key=lambda x: -x["days"]),
                    "reasons": [{"value": k, "label": v[0], "party": v[1]} for k, v in DELAY_REASONS.items()]})


# ---------------- the project timeline ----------------
@bp.get("/projects/<_id>/activity")
@api("projects")
def activity(_id):
    load(_id)
    q = {"company_id": g.cid, "project_id": _id}
    group = request.args.get("group")
    if group:
        kinds = ev.ACTIVITY_GROUPS.get(group) or abort(400, "Unknown filter")
        q["kind"] = {"$in": kinds}
    money = can("finance") and not g.hide_costs  # cost entries carry amounts
    if not money:
        q["kind"] = {"$in": [k for k in q["kind"]["$in"] if k != "cost"]} if group else {"$ne": "cost"}
    limit = min(int(request.args.get("limit", 200)), 500)
    rows = list(db.project_activity.find(q).sort("at", -1).limit(limit))
    return jsonify({"rows": serialize(rows), "groups": [x for x in ev.ACTIVITY_GROUPS if money or x != "Money"]})


@bp.get("/projects/plan_meta")
@api("projects", write=False)
def plan_meta():
    return jsonify({"delay_reasons": [{"value": k, "label": v[0], "party": v[1]} for k, v in DELAY_REASONS.items()],
                    "waiting_parties": [{"value": k, "label": v} for k, v in WAITING_PARTIES.items()],
                    "link_types": [{"value": k, "label": v} for k, v in LINK_TYPES.items()],
                    "calendar": workdays.calendar(), "today": date.today().isoformat()})
