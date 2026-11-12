"""WhatsApp gateway (Phase G block 4). One interface, so another provider (Gupshup, Twilio) plugs in later.

Providers:
* `whatsapp_cloud` — Meta's WhatsApp Cloud API (graph.facebook.com). Free text inside the 24-hour window, otherwise an
  approved template. Delivery receipts come to the webhook signed with the app secret (`X-Hub-Signature-256`).
* `sandbox` — no network: the message is stored as sent with a fake id, and delivery receipts can be posted to the
  webhook signed the same way (for demos and tests).
* not set up — **log only**: the message is stored with status *logged*, exactly the behaviour before Phase G.
Every message is stored in `messages` (`channel: whatsapp`, `direction: out`), which the plan's WhatsApp quota counts.
Sending needs the contact's opt-in; an inbound STOP opts them out. SMS is not built (DLT registration first).
"""
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
import uuid

from flask import g, abort

from ..db import db

PROVIDERS = {"whatsapp_cloud": "WhatsApp Cloud API (Meta)", "sandbox": "Sandbox (test only, nothing is sent)"}
GRAPH = "https://graph.facebook.com/v19.0"


def settings(company=None):
    return {"provider": None, "phone_number_id": None, "access_token": None, "app_secret": None, "verify_token": None,
            **((company or g.company).get("messaging") or {})}


def ready(company=None):
    s = settings(company)
    if s["provider"] == "sandbox":
        return bool(s["app_secret"])
    return s["provider"] == "whatsapp_cloud" and all(s.get(k) for k in ("phone_number_id", "access_token", "app_secret"))


def phone_e164(phone):
    """Indian numbers by default: 10 digits -> 91XXXXXXXXXX. Returns digits only, or None."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    return digits if 11 <= len(digits) <= 15 else None


def opted_in(contact):
    return bool((contact or {}).get("whatsapp_opt_in")) and not (contact or {}).get("whatsapp_opt_out")


def check_quota():
    from .subscription import limits, usage
    lim = limits().get("whatsapp")
    if lim is not None and usage(g.company)["whatsapp_messages"] >= lim:
        abort(402, "WhatsApp messages for this month are used up — buy a WhatsApp add-on or upgrade.")


def sign(secret, raw):
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify(company, raw, header):
    s = settings(company)
    return bool(s.get("app_secret")) and bool(header) and hmac.compare_digest(header, sign(s["app_secret"], raw))


def _cloud_send(s, to, text, template=None, params=None, buttons=None):
    body = {"messaging_product": "whatsapp", "to": to}
    if buttons:  # Phase J: interactive reply buttons (max 3, titles max 20 characters)
        body.update(type="interactive", interactive={"type": "button", "body": {"text": text[:1024]}, "action": {"buttons": [
            {"type": "reply", "reply": {"id": bid, "title": title[:20]}} for bid, title in buttons[:3]]}})
    elif template:
        body.update(type="template", template={"name": template, "language": {"code": "en"},
                                               "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params or []]}]})
    else:
        body.update(type="text", text={"body": text[:4000], "preview_url": True})
    req = urllib.request.Request(f"{GRAPH}/{s['phone_number_id']}/messages", method="POST", data=json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {s['access_token']}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())["messages"][0]["id"], None
    except urllib.error.HTTPError as e:
        return None, (json.loads(e.read() or b"{}").get("error") or {}).get("message") or str(e)
    except OSError as e:
        return None, f"WhatsApp could not be reached: {e}"


def send(contact, text, kind="message", ref=None, template=None, params=None, by=None, buttons=None, extra=None):
    """Send (or log) one WhatsApp message to a contact (or a site worker). Returns the stored message.
    `buttons`: up to three (id, title) one-tap replies (Phase J)."""
    from .. import tenancy as t
    to = phone_e164((contact or {}).get("phone"))
    s = settings()
    doc = {"channel": "whatsapp", "direction": "out", "contact_id": str(contact["_id"]) if contact.get("_id") else contact.get("id"),
           "contact_name": contact.get("name"), "to": to, "text": text[:4000], "template": template, "kind": kind, "ref": ref,
           "provider": s["provider"], "provider_id": None, "status": "logged", "error": None, "by": by or (g.user or {}).get("name"),
           "by_id": getattr(g, "uid", None), "buttons": [b[0] for b in buttons or []] or None, **(extra or {})}
    if not to:
        doc.update(status="failed", error="No mobile number")
    elif not opted_in(contact):
        doc.update(status="failed", error="Not opted in to WhatsApp")
    elif ready():
        check_quota()
        if s["provider"] == "sandbox":
            doc.update(status="sent", provider_id=f"wamid.sbx_{uuid.uuid4().hex[:16]}")
        else:
            pid, err = _cloud_send(s, to, text, template, params, buttons)
            doc.update(status="sent" if pid else "failed", provider_id=pid, error=err)
    if doc["status"] == "logged":  # not set up: log only, it does not count against the plan
        doc["direction"] = "logged"
    return t.insert("messages", doc)


def notify_contact(contact, text, kind="message", ref=None):
    """Best effort for automatic messages: only when set up and the contact opted in. Returns the status or None."""
    if not contact or not opted_in(contact) or not ready():
        return None
    try:
        return send(contact, text, kind, ref)["status"]
    except Exception:  # a quota or provider problem must never break the action that triggered it
        return "failed"
