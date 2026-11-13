"""Phase L block 1 — the offline field app (v4 §10, §15).

The phone keeps what a site person needs for the day (their live projects, stages and tasks, the attendance list, open
snags, today's report and inspection templates) and works without a signal. What they record — the daily report,
attendance, snags, snag fixes, photos, safety incidents and inspections — is queued on the phone and sent here when the
signal comes back.

* GET /mobile/bootstrap — everything the phone caches, for the projects the person is on.
* POST /mobile/sync — the queue. Each operation has an id made on the phone, so a queue sent twice (the signal dropped
  before the answer came back) is applied once: the stored result is returned again. Every operation goes through the
  same endpoint, rules and permissions as the web app (it is dispatched to it), so nothing offline can do more.
  Merging, because two people (or the web app) may have written the same day while the phone was offline:
    - daily report: one per project per day; if one already exists the phone's work lines, photos and notes are added
      to it and its manpower replaces the same trade's row; the report's lock (the next day) still applies;
    - attendance: the phone's rows replace the same people's rows on the day's sheet, others are kept;
  A refused operation (locked report, no permission, bad data) is returned with the reason and stays on the phone,
  marked for the person to fix or discard — it never blocks the rest of the queue.
Photos are uploaded first (POST /uploads) when the signal is back; the operations then carry the file keys.
"""
from flask import Blueprint, request, jsonify, abort, g, current_app

from .. import tenancy as t
from ..db import db, serialize
from ..security import api, can
from ..services import sales
from ..services.defaults import SNAG_PRIORITIES, ATTENDANCE_STATUSES
from .projects import member
from .site_reports import WEATHER, TRADES

bp = Blueprint("mobile", __name__)
LIVE = ["planning", "active", "on_hold"]
KINDS = ("site_report", "attendance", "snag", "snag_fixed", "incident", "inspection")
MAX_OPS = 100


def my_projects():
    q = {"status": {"$in": LIVE}}
    if g.role != "owner":
        q["team.user_id"] = g.uid
    return t.find("projects", q, sort=[("name", 1)], limit=50)


@bp.get("/mobile/bootstrap")
@api(None)
def bootstrap():
    if not can("site"):  # the Owner, PMs and site supervisors
        abort(403, "Your role does not use the field app")
    from .site_plus import people
    from .safety import templates as insp_templates, INCIDENT_KINDS, SEVERITIES
    today = sales.today()
    out = []
    for p in my_projects():
        pid = str(p["_id"])
        rep = db.site_reports.find_one({"company_id": g.cid, "project_id": pid, "date": today})
        sheet = db.attendance.find_one({"company_id": g.cid, "project_id": pid, "date": today})
        snags = list(db.snags.find({"company_id": g.cid, "project_id": pid, "status": {"$ne": "closed"}}).sort("created_at", -1).limit(100))
        out.append({"id": pid, "name": p["name"], "address": p.get("address") or p.get("site_address"),
                    "can_write": can("site", True) and (g.role == "owner" or member(p) is not None),
                    "stages": [{"id": s["id"], "name": s["name"], "service": s.get("service"),
                                "tasks": [{"id": tk["id"], "title": tk["title"], "status": tk.get("status")} for tk in s.get("tasks", [])]}
                               for s in p.get("stages", [])],
                    "people": people(p),
                    "team": [{"id": m["user_id"], "name": m["name"]} for m in p.get("team", []) if m.get("user_id")],
                    "today_report": rep and {"id": str(rep["_id"]), "headcount": rep.get("headcount"), "work": len(rep.get("work", [])),
                                             "photos": len(rep.get("photos", []))},
                    "today_attendance": sheet and {r["person"]: r["status"] for r in sheet.get("rows", [])},
                    "snags": [{"id": str(s["_id"]), "number": s["number"], "title": s["title"], "status": s["status"], "location": s.get("location"),
                               "priority": s.get("priority"), "due": s.get("due"), "assignee_id": s.get("assignee_id")} for s in snags]})
    return jsonify({"user": {"id": g.uid, "name": g.user.get("name"), "role": g.role}, "company": g.company["name"], "today": today,
                    "fetched_at": t.now().isoformat() + "Z", "projects": out, "weather": WEATHER, "trades": TRADES,
                    "attendance_statuses": list(ATTENDANCE_STATUSES), "snag_priorities": SNAG_PRIORITIES,
                    "incident_kinds": INCIDENT_KINDS, "severities": SEVERITIES,
                    "inspection_templates": [{"id": x["id"], "name": x["name"], "items": x["items"]} for x in insp_templates()]})


def dispatch(method, path, body):
    """Run one operation through the web app's own endpoint (same rules, same permissions) and return (status, json)."""
    with current_app.test_request_context(path=f"/api{path}", method=method, json=body,
                                          headers={"Authorization": request.headers.get("Authorization", ""),
                                                   "User-Agent": "field-app-sync"}):
        resp = current_app.full_dispatch_request()
    data = resp.get_json(silent=True)
    return resp.status_code, data if data is not None else {}


def merge_report(existing, d):
    """The phone's report added to the day's report already on the server."""
    body = {}
    if d.get("weather", {}).get("kind") or d.get("weather", {}).get("note"):
        body["weather"] = d["weather"]
    if d.get("manpower"):
        by_trade = {(m["trade"], m.get("contact_id")): m for m in existing.get("manpower", [])}
        for m in d["manpower"]:
            by_trade[(m.get("trade"), m.get("contact_id"))] = m
        body["manpower"] = [{"trade": m["trade"], "count": m["count"], "contact_id": m.get("contact_id")} for m in by_trade.values()]
    if d.get("work"):
        body["work"] = [{"stage_id": w["stage_id"], "task_id": w.get("task_id"), "note": w["note"]} for w in existing.get("work", [])] + list(d["work"])
    if d.get("photos"):
        have = {ph["key"] for ph in existing.get("photos", [])}
        body["photos"] = [{k: ph.get(k) for k in ("key", "caption", "shareable", "stage_id", "room", "lat", "lng", "accuracy_m", "taken_at")}
                          for ph in existing.get("photos", [])] + [ph for ph in d["photos"] if ph.get("key") not in have]
    for k in ("equipment", "materials", "visitors", "safety"):
        if d.get(k):
            body[k] = (existing.get(k) + "\n" + d[k]) if existing.get(k) and d[k] not in existing[k] else d[k]
    return body


def apply(op):
    kind, d, pid = op.get("kind"), op.get("data") or {}, op.get("project_id")
    if kind not in KINDS:
        return 400, {"error": f"Unknown operation {kind}"}
    if kind == "site_report":
        day = d.get("date") or sales.today()
        ex = db.site_reports.find_one({"company_id": g.cid, "project_id": pid, "date": day})
        if ex:
            st, res = dispatch("PUT", f"/site-reports/{ex['_id']}", merge_report(ex, d))
            return st, ({**res, "merged": True} if st == 200 else res)
        return dispatch("POST", f"/projects/{pid}/site-reports", {**d, "date": day})
    if kind == "attendance":
        day = d.get("date") or sales.today()
        sheet = db.attendance.find_one({"company_id": g.cid, "project_id": pid, "date": day})
        mine = {r["person"] for r in d.get("rows") or []}
        rows = [{k: r.get(k) for k in ("person", "status", "in", "out", "ot_hours")} for r in (sheet or {}).get("rows", []) if r["person"] not in mine]
        return dispatch("PUT", f"/projects/{pid}/attendance", {"date": day, "rows": rows + list(d.get("rows") or [])})
    if kind == "snag":
        return dispatch("POST", f"/projects/{pid}/snags", d)
    if kind == "snag_fixed":
        return dispatch("POST", f"/snags/{d.get('snag_id')}/fixed", {k: v for k, v in d.items() if k != "snag_id"})
    if kind == "incident":
        return dispatch("POST", f"/projects/{pid}/incidents", d)
    if kind == "inspection":
        return dispatch("POST", f"/projects/{pid}/inspections", d)


@bp.post("/mobile/sync")
@api(None)
def sync():
    d = request.get_json(force=True) or {}
    ops = d.get("ops") or []
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        abort(400, f"Send up to {MAX_OPS} operations at a time")
    results = []
    for op in ops:
        op_id = str(op.get("op_id") or "")[:64]
        if len(op_id) < 8:
            results.append({"op_id": op_id, "status": 400, "ok": False, "error": "Each operation needs an id made on the phone"})
            continue
        done = db.sync_ops.find_one({"company_id": g.cid, "user_id": g.uid, "op_id": op_id})
        if done:
            results.append({**done["result"], "op_id": op_id, "replayed": True})
            continue
        try:
            status, res = apply(op)
        except Exception as e:  # noqa: BLE001 — one bad operation must not lose the rest of the queue
            current_app.logger.exception("sync op failed")
            status, res = 500, {"error": f"Could not apply: {type(e).__name__}"}
        ok = 200 <= status < 300
        result = {"op_id": op_id, "kind": op.get("kind"), "status": status, "ok": ok,
                  "id": (res or {}).get("id") if ok else None, "merged": bool((res or {}).get("merged")),
                  "number": (res or {}).get("number") if ok else None, "error": None if ok else (res or {}).get("error") or f"Error {status}"}
        if ok or status in (400, 403, 404, 409):  # final answers are kept; a server error may be retried
            db.sync_ops.insert_one({"company_id": g.cid, "user_id": g.uid, "op_id": op_id, "kind": op.get("kind"),
                                    "project_id": op.get("project_id"), "made_at": str(op.get("made_at") or "")[:30] or None,
                                    "result": result, "at": t.now()})
        results.append(result)
    return jsonify({"results": results, "applied": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"]),
                    "server_time": t.now().isoformat() + "Z"})


@bp.get("/mobile/sync-log")
@api(None)
def sync_log():
    """What this person's phone sent recently (to check a queue went through)."""
    rows = list(db.sync_ops.find({"company_id": g.cid, "user_id": g.uid}).sort("at", -1).limit(50))
    return jsonify([{**r["result"], "at": serialize(r["at"]), "made_at": r.get("made_at")} for r in rows])
