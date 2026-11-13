"""Phase I block 7 — calendar feed, SMS settings, backups and language (§15).

* Calendar (§15 "Google / Outlook calendar"): each staff user has a private feed link (an iCalendar URL with a secret
  token) to subscribe to in Google Calendar or Outlook: their open tasks, the milestones of projects they are on,
  their follow-ups, site visits and project meetings. Resetting the link stops the old one.
* SMS (§15): Settings → SMS (provider, DLT entity id, sender id, key masked); templates carry their DLT template id.
* Backups (§15 "daily backups", §18 "backups status and restore"): the Super Admin sees the backups and can run one now.
* Language (§15 "multi-language"): English or Hindi per user (staff and portal), kept on the user.
"""
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g, Response

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, auth_required, superadmin
from ..services import sms as sms_gw

bp = Blueprint("extras", __name__)
from ..services.languages import LANGUAGES  # noqa: E402 — Phase L: English, Hindi and six more Indian languages


# ============================== calendar feed ==============================
def feed_url(u):
    return f"/api/calendar/{u['calendar_token']}.ics"


@bp.get("/calendar/link")
@api(None)
def calendar_link():
    u = db.users.find_one({"_id": oid(g.uid)})
    if not u.get("calendar_token"):
        tok = secrets.token_urlsafe(24)
        db.users.update_one({"_id": u["_id"]}, {"$set": {"calendar_token": tok}})
        u["calendar_token"] = tok
    return jsonify({"url": feed_url(u)})


@bp.post("/calendar/link/reset")
@api(None)
def calendar_reset():
    tok = secrets.token_urlsafe(24)
    db.users.update_one({"_id": oid(g.uid)}, {"$set": {"calendar_token": tok}})
    return jsonify({"url": f"/api/calendar/{tok}.ics"})


def ics_text(v):
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")[:500]


def ics_day(d):
    return d.replace("-", "")


def ics_event(uid, summary, start, end=None, all_day=True, description=None, url=None):
    lines = ["BEGIN:VEVENT", f"UID:{uid}@buildsuite", f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}", f"SUMMARY:{ics_text(summary)}"]
    if all_day:
        end_day = (date.fromisoformat(end or start) + timedelta(days=1)).isoformat()
        lines += [f"DTSTART;VALUE=DATE:{ics_day(start)}", f"DTEND;VALUE=DATE:{ics_day(end_day)}"]
    else:
        lines += [f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{(end or start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}"]
    if description:
        lines.append(f"DESCRIPTION:{ics_text(description)}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("END:VEVENT")
    return lines


@bp.get("/calendar/<token>.ics")
def calendar_feed(token):
    """Public by its secret token only. Events from 30 days back to a year ahead."""
    u = db.users.find_one({"calendar_token": token, "active": {"$ne": False}, "kind": "staff"}) if token and len(token) > 20 else None
    if not u:
        abort(404)
    cid_, uid = u["company_id"], str(u["_id"])
    since = (date.today() - timedelta(days=30)).isoformat()
    until = (date.today() + timedelta(days=365)).isoformat()
    ev = []
    q = {"company_id": cid_, "status": {"$in": ["planning", "active", "on_hold"]}}
    if u["role"] != "owner":
        q["team.user_id"] = uid
    for p in db.projects.find(q, {"name": 1, "stages": 1}):
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                if tk.get("assignee_id") == uid and tk["status"] != "done" and tk.get("start") and tk.get("end") and tk["end"] >= since:
                    ev += ics_event(f"task-{tk['id']}", f"{tk['title']} · {p['name']}", tk["start"], tk["end"], description=f"Stage {s['name']}")
            for m in s.get("milestones", []):
                if m.get("due") and since <= m["due"] <= until and m.get("status") != "achieved":
                    ev += ics_event(f"ms-{m['id']}", f"◆ {m['name']} · {p['name']}", m["due"])
    for f in db.followups.find({"company_id": cid_, "owner_id": uid, "status": "open", "due": {"$gte": since, "$lte": until}}):
        ev += ics_event(f"fu-{f['_id']}", f"Follow-up: {f['title']}", f["due"])
    for v in db.lead_visits.find({"company_id": cid_, "status": {"$in": ["scheduled", "confirmed"]}, "$or": [{"owner_id": uid}, {"attendee_ids": uid}]}):
        at = v.get("at")
        if isinstance(at, datetime):
            ev += ics_event(f"visit-{v['_id']}", f"Site visit: {v.get('lead_title') or v.get('title') or ''}", at, at + timedelta(minutes=int(v.get("duration_min") or 60)),
                            all_day=False, description=v.get("address") or v.get("location"))
    for m in db.project_meetings.find({"company_id": cid_, "status": {"$ne": "cancelled"}, "$or": [{"attendee_ids": uid}, {"created_by": uid}]}):
        at = m.get("at")
        if isinstance(at, datetime) and at.date().isoformat() >= since:
            ev += ics_event(f"mtg-{m['_id']}", f"Meeting: {m.get('title')}", at, at + timedelta(minutes=int(m.get("duration_min") or 60)), all_day=False,
                            description=m.get("place"))
    company = db.companies.find_one({"_id": oid(cid_)}, {"name": 1}) or {}
    body = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BuildSuite//CRM//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
                        f"X-WR-CALNAME:{ics_text(company.get('name', 'BuildSuite'))} — {ics_text(u['name'])}", *ev, "END:VCALENDAR"]) + "\r\n"
    return Response(body, mimetype="text/calendar", headers={"Cache-Control": "private, max-age=300"})


# ============================== SMS settings ==============================
@bp.get("/settings/sms")
@api("settings", write=False)
def get_sms():
    s = sms_gw.settings()
    out = {k: v for k, v in s.items() if k not in sms_gw.SECRETS}
    out.update(auth_key_set=bool(s.get("auth_key")), providers=sms_gw.PROVIDERS, ready=sms_gw.ready())
    return jsonify(out)


@bp.put("/settings/sms")
@api("settings")
def put_sms():
    s = sms_gw.clean_settings(request.get_json(force=True) or {}, sms_gw.settings())
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"sms": s}})
    t.audit("update", "companies", g.company["_id"], note="SMS settings changed")
    g.company["sms"] = s
    return get_sms()


@bp.post("/message_templates/<tid>/sms")
@api("messages")
def send_sms_template(tid):
    """Send an SMS template to a contact (rendered like the preview), or log it when SMS is not set up."""
    from .followups import render as render_route
    tpl = t.get("message_templates", tid)
    if tpl["channel"] != "sms":
        abort(400, "This is not an SMS template")
    d = request.get_json(force=True) or {}
    c = (t.get("contacts", d["contact_id"], required=False) if d.get("contact_id") else None) or abort(400, "Choose the contact")
    text = (d.get("text") or "").strip() or render_route(tid).get_json().get("text")
    if "{{" in (text or ""):
        abort(400, "Fill every merge field before sending")
    m = sms_gw.send(c, text, tpl.get("dlt_template_id"), kind="template", ref=tid)
    if d.get("lead_id"):
        from ..services.sales import log
        log(d["lead_id"], "note", f"SMS to {c['name']} ({m['status']}): {text[:200]}")
    return jsonify(serialize(m)), 201


# ============================== backups (Super Admin) ==============================
@bp.get("/sa/backups")
@superadmin("settings")
def sa_backups():
    from ..backup import list_backups, KEEP, HOUR
    return jsonify(serialize({"status": db.platform_settings.find_one({"_id": "backup"}) or {}, "backups": list_backups(), "keep": KEEP, "hour": HOUR}))


@bp.post("/sa/backups/run")
@superadmin("settings")
def sa_backup_now():
    from ..backup import run_backup
    from .platform import sa_audit
    res = run_backup("manual")
    sa_audit("backup_now", note=res.get("status"))
    return jsonify(serialize(res)), (201 if res.get("status") == "ok" else 500)


# ============================== language ==============================
@bp.put("/me/language")
@auth_required
def set_language():
    lang = (request.get_json(force=True) or {}).get("language")
    if lang not in LANGUAGES:
        abort(400, f"Language: {', '.join(LANGUAGES)}")
    db.users.update_one({"_id": oid(g.uid)}, {"$set": {"language": lang}})
    return jsonify({"language": lang})


@bp.get("/languages")
def languages():
    return jsonify(LANGUAGES)
