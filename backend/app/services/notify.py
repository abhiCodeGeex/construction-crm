"""Notifications (C+1): one in-app bell per staff user plus email when the company has set up email (SMTP).

Every notification goes through `send`, which applies the user's preferences, skips duplicates (a `key` per
reminder, so the scheduled checks can run every minute) and emails a copy when email is configured."""
import smtplib
import threading
from email.message import EmailMessage

from flask import g

from ..db import db, oid
from .defaults import NOTIFY_EVENTS


def _now():
    from ..tenancy import now
    return now()


def email_settings(company=None):
    return ((company or g.company).get("email_settings") or {})


def email_ready(company=None):
    s = email_settings(company)
    return bool(s.get("host") and s.get("from_address"))


def deliver(company, to, subject, body, attachments=()):
    """Send one email with the company's SMTP settings. Returns 'sent' or the reason it was not sent."""
    s = email_settings(company)
    if not email_ready(company):
        return "email not set up"
    if not to:
        return "no email address"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s["from_address"], to
    msg.set_content(body)
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    try:
        with smtplib.SMTP(s["host"], int(s.get("port") or 587), timeout=15) as smtp:
            if s.get("use_tls"):
                smtp.starttls()
            if s.get("username"):
                smtp.login(s["username"], s.get("password") or "")
            smtp.send_message(msg)
        return "sent"
    except Exception as e:  # the reason is shown where the email was logged
        return f"failed: {e}"


def managers(company=None):
    """Sales manager from Settings -> Sales, else every active Owner."""
    company = company or g.company
    cid = str(company["_id"])
    mid = (company.get("sales") or {}).get("manager_id")
    if mid and db.users.find_one({"_id": oid(mid), "company_id": cid, "kind": "staff", "active": {"$ne": False}}):
        return [mid]
    return [str(u["_id"]) for u in db.users.find({"company_id": cid, "role": "owner", "active": {"$ne": False}}, {"_id": 1})]


def role_users(*roles, company=None):
    cid = str((company or g.company)["_id"])
    return [str(u["_id"]) for u in db.users.find({"company_id": cid, "kind": "staff", "role": {"$in": list(roles)},
                                                  "active": {"$ne": False}}, {"_id": 1})]


def send(event, user_ids, text, link=None, lead_id=None, key=None, level="info", company=None, skip_self=True):
    """Notify each user once. `key` makes a reminder idempotent per user (e.g. 'visit-2h:<visit id>')."""
    company = company or g.company
    cid = str(company["_id"])
    label, critical = NOTIFY_EVENTS[event]
    me = getattr(g, "uid", None)
    sent = []
    for uid in dict.fromkeys(u for u in user_ids if u):
        if skip_self and uid == me:
            continue
        user = db.users.find_one({"_id": oid(uid), "company_id": cid, "kind": "staff", "active": {"$ne": False}})
        if not user:
            continue
        prefs = user.get("notify_prefs") or {}
        if not critical and event in (prefs.get("off") or []):
            continue
        if key and db.notifications.find_one({"company_id": cid, "user_id": uid, "key": key}, {"_id": 1}):
            continue
        doc = {"company_id": cid, "user_id": uid, "event": event, "title": label, "text": text, "link": link,
               "lead_id": lead_id, "key": key, "level": level, "read_at": None, "created_at": _now(),
               "email": None}
        wants_email = email_ready(company) and user.get("email") and event not in (prefs.get("email_off") or [])
        doc["email"] = "queued" if wants_email else None
        nid = db.notifications.insert_one(doc).inserted_id
        if wants_email:
            base = email_settings(company).get("app_url") or ""
            body = f"{text}\n\n{base.rstrip('/') + link if base and link else ''}\n\n— {company['name']} · BuildSuite"
            threading.Thread(target=_mail, args=(company, user["email"], f"{label}: {text[:80]}", body, nid),
                             daemon=True).start()
        sent.append(uid)
    return sent


def _mail(company, to, subject, body, nid):
    db.notifications.update_one({"_id": nid}, {"$set": {"email": deliver(company, to, subject, body)}})
