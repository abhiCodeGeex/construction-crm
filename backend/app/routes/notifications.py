"""The bell (C+1): each staff user's notifications, their preferences, and the company's email (SMTP) settings."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify
from ..services.defaults import NOTIFY_EVENTS

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
@api(None)
def mine():
    q = {"company_id": g.cid, "user_id": g.uid}
    if request.args.get("unread") == "1":
        q["read_at"] = None
    rows = list(db.notifications.find(q).sort("created_at", -1).limit(int(request.args.get("limit", 50))))
    return jsonify({"items": serialize(rows),
                    "unread": db.notifications.count_documents({"company_id": g.cid, "user_id": g.uid, "read_at": None})})


@bp.post("/notifications/<_id>/read")
@api(None)
def read(_id):
    db.notifications.update_one({"_id": oid(_id), "company_id": g.cid, "user_id": g.uid, "read_at": None},
                                {"$set": {"read_at": t.now()}})
    return jsonify({"ok": True})


@bp.post("/notifications/read-all")
@api(None)
def read_all():
    db.notifications.update_many({"company_id": g.cid, "user_id": g.uid, "read_at": None}, {"$set": {"read_at": t.now()}})
    return jsonify({"ok": True})


PROJECT_EVENTS = {"project_pm", "project_added", "task_assigned", "task_due", "task_overdue", "task_blocked", "mentioned",
                  "task_comment", "meeting_scheduled", "meeting_reminder", "meeting_minutes", "project_at_risk", "signoff_recorded",
                  "stage_done", "milestone_achieved", "milestone_late", "issue_raised"}


FINANCE_EVENTS = {"cost_approval", "cost_decided", "budget_alert"}

GROUPS = ["Leads & sales", "Projects", "Finance", "Contacts"]


def notify_group(event):
    """Heading the event is listed under in the notification settings."""
    if event in PROJECT_EVENTS:
        return "Projects"
    if event in FINANCE_EVENTS:
        return "Finance"
    if event.startswith("compliance"):
        return "Contacts"
    return "Leads & sales"


@bp.get("/notifications/prefs")
@api(None)
def prefs():
    user = db.users.find_one({"_id": oid(g.uid)}, {"notify_prefs": 1})
    p = user.get("notify_prefs") or {}
    return jsonify({"events": [{"event": k, "label": v[0], "critical": v[1], "group": notify_group(k),
                                "in_app": k not in (p.get("off") or []) or v[1],
                                "email": k not in (p.get("email_off") or [])}
                               for k, v in sorted(NOTIFY_EVENTS.items(), key=lambda kv: GROUPS.index(notify_group(kv[0])))],
                    "email_ready": notify.email_ready()})


@bp.put("/notifications/prefs")
@api(None)
def set_prefs():
    d = request.get_json(force=True) or {}
    off, email_off = [], []
    for row in d.get("events") or []:
        ev = row.get("event")
        if ev not in NOTIFY_EVENTS:
            abort(400, f"Unknown notification: {ev}")
        if not row.get("in_app") and not NOTIFY_EVENTS[ev][1]:
            off.append(ev)
        if not row.get("email"):
            email_off.append(ev)
    db.users.update_one({"_id": oid(g.uid)}, {"$set": {"notify_prefs": {"off": off, "email_off": email_off}}})
    t.audit("update", "notify_prefs", g.uid, note=f"{len(off)} off in app, {len(email_off)} off by email")
    return prefs()


# ---------------- email (SMTP) settings ----------------
def email_out():
    s = dict(g.company.get("email_settings") or {})
    if s.get("password"):
        s["password"] = "••••••"
    return {**s, "ready": notify.email_ready()}


@bp.get("/settings/email")
@api("settings", write=False)
def get_email():
    return jsonify(email_out())


@bp.put("/settings/email")
@api("settings")
def put_email():
    d = request.get_json(force=True) or {}
    cur = dict(g.company.get("email_settings") or {})
    if not d.get("host"):  # switching email off
        db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"email_settings": {}}})
        t.audit("update", "email_settings", g.company["_id"], note="Email switched off")
        g.company = db.companies.find_one({"_id": g.company["_id"]})
        return jsonify(email_out())
    from .contacts import EMAIL_RE
    port = d.get("port") or 587
    if not isinstance(port, int) or not 1 <= port <= 65535:
        abort(400, "Port must be a number between 1 and 65535")
    sender = (d.get("from_address") or "").strip()
    if not EMAIL_RE.match(sender):
        abort(400, "From address must be an email address")
    s = {"host": d["host"].strip(), "port": port, "username": (d.get("username") or "").strip() or None,
         "use_tls": bool(d.get("use_tls")), "from_address": sender,
         "app_url": (d.get("app_url") or request.host_url).rstrip("/"),
         "password": cur.get("password") if d.get("password") in (None, "", "••••••") else d["password"]}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"email_settings": s}})
    t.audit("update", "email_settings", g.company["_id"], note=f"Email via {s['host']}:{port}")
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return jsonify(email_out())


@bp.post("/settings/email/test")
@api("settings")
def test_email():
    to = (request.get_json(force=True) or {}).get("to") or db.users.find_one({"_id": oid(g.uid)})["email"]
    result = notify.deliver(g.company, to, f"Test email from {g.company['name']}",
                            "Email notifications from BuildSuite are working.")
    if result != "sent":
        abort(400, f"Test email not sent: {result}")
    return jsonify({"ok": True, "to": to})
