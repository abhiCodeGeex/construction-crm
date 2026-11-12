"""Phase I block 7 — SMS gateway (§15 notifications: email, SMS, WhatsApp, in-app).

India sends business SMS only on DLT-registered templates: every template sent by SMS carries its DLT template id,
and the company its DLT entity id and 6-letter sender id (header).
Providers:
* `msg91` — MSG91's Flow / SMS API (authkey header).
* `sandbox` — no network: stored as sent with a fake id (demos and tests).
* not set up — **log only**, as before Phase I.
Every message is stored in `messages` (`channel: sms`).
"""
import json
import re
import urllib.error
import urllib.request
import uuid

from flask import g, abort

PROVIDERS = {"msg91": "MSG91", "sandbox": "Sandbox (test only, nothing is sent)"}
SECRETS = ("auth_key",)


def settings(company=None):
    return {"provider": None, "auth_key": None, "sender_id": None, "dlt_entity_id": None, **((company or g.company).get("sms") or {})}


def ready(company=None):
    s = settings(company)
    if s["provider"] == "sandbox":
        return True
    return s["provider"] == "msg91" and all(s.get(k) for k in ("auth_key", "sender_id", "dlt_entity_id"))


def clean_settings(d, s):
    if "provider" in d:
        if d["provider"] not in (None, "", *PROVIDERS):
            abort(400, f"Provider: {', '.join(PROVIDERS)}")
        s["provider"] = d["provider"] or None
    if "sender_id" in d:
        v = (d["sender_id"] or "").strip().upper()
        if v and not re.fullmatch(r"[A-Z]{6}", v):
            abort(400, "The sender id (header) is 6 letters, e.g. BLDSUT")
        s["sender_id"] = v or None
    if "dlt_entity_id" in d:
        v = re.sub(r"\D", "", str(d["dlt_entity_id"] or ""))
        if v and not 12 <= len(v) <= 20:
            abort(400, "The DLT entity id is 12 to 20 digits")
        s["dlt_entity_id"] = v or None
    if d.get("auth_key"):
        s["auth_key"] = d["auth_key"].strip()
    return s


def _msg91(s, to, text, dlt_template_id):
    body = {"sender": s["sender_id"], "route": "4", "country": "91", "DLT_TE_ID": dlt_template_id,
            "sms": [{"message": text, "to": [to[-10:]]}]}
    req = urllib.request.Request("https://api.msg91.com/api/v2/sendsms", method="POST", data=json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("authkey", s["auth_key"])
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read() or b"{}")
            return (res.get("message") or uuid.uuid4().hex), None if res.get("type") == "success" else res.get("message")
    except urllib.error.HTTPError as e:
        return None, (e.read() or b"").decode(errors="replace")[:200] or str(e)
    except OSError as e:
        return None, f"SMS provider could not be reached: {e}"


def send(contact, text, dlt_template_id=None, kind="message", ref=None):
    """Send (or log) one SMS to a contact. A live provider needs the template's DLT id."""
    from .. import tenancy as t
    from .messaging import phone_e164
    to = phone_e164((contact or {}).get("phone"))
    s = settings()
    doc = {"channel": "sms", "direction": "out", "contact_id": str(contact["_id"]) if contact.get("_id") else contact.get("id"),
           "contact_name": contact.get("name"), "to": to, "text": text[:480], "dlt_template_id": dlt_template_id, "kind": kind, "ref": ref,
           "provider": s["provider"], "provider_id": None, "status": "logged", "error": None, "by": (g.user or {}).get("name"),
           "by_id": getattr(g, "uid", None)}
    if not to:
        doc.update(status="failed", error="No mobile number")
    elif (contact or {}).get("sms_opt_out"):
        doc.update(status="failed", error="Opted out of SMS")
    elif ready():
        if s["provider"] != "sandbox" and not dlt_template_id:
            abort(400, "This template has no DLT template id; add it in Settings → Sales & templates")
        if s["provider"] == "sandbox":
            doc.update(status="sent", provider_id=f"sms_sbx_{uuid.uuid4().hex[:12]}")
        else:
            pid, err = _msg91(s, to, text, dlt_template_id)
            doc.update(status="sent" if pid and not err else "failed", provider_id=pid, error=err)
    if doc["status"] == "logged":
        doc["direction"] = "logged"
    return t.insert("messages", doc)
