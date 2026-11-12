"""Phase G block 4 — WhatsApp: settings, opt-in, sending templates, and the provider's webhook.

* Settings -> WhatsApp: provider, phone number id, access token, app secret, verify token; secrets never sent back.
* Opt-in per contact (who, how, when) by staff, or by the portal user themself; an inbound STOP opts out.
* Message templates (Phase C) are rendered and **sent** on WhatsApp when set up and the contact opted in; otherwise they
  are logged exactly as before. Sending counts against the plan's WhatsApp messages.
* The webhook moves a message sent -> delivered -> read / failed; a failed message tells its sender.
"""
import json

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal
from ..services import notify, messaging as wa

bp = Blueprint("whatsapp", __name__)
SECRETS = ("access_token", "app_secret")
OPT_HOW = ["Portal tick", "Written", "Verbal", "WhatsApp message"]


@bp.get("/settings/messaging")
@api("settings", write=False)
def get_settings():
    s = wa.settings()
    out = {k: v for k, v in s.items() if k not in SECRETS}
    out.update({f"{k}_set": bool(s.get(k)) for k in SECRETS})
    out.update(providers=wa.PROVIDERS, ready=wa.ready(), webhook_url=f"/api/webhooks/messages/{g.cid}")
    return jsonify(out)


@bp.put("/settings/messaging")
@api("settings")
def put_settings():
    d = request.get_json(force=True) or {}
    s = wa.settings()
    if "provider" in d:
        if d["provider"] not in (None, "", *wa.PROVIDERS):
            abort(400, f"Provider: {', '.join(wa.PROVIDERS)}")
        s["provider"] = d["provider"] or None
    for k in ("phone_number_id", "verify_token"):
        if k in d:
            s[k] = (d[k] or "").strip() or None
    for k in SECRETS:
        if d.get(k):
            s[k] = d[k].strip()
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"messaging": s}})
    t.audit("update", "companies", g.company["_id"], note="WhatsApp settings changed")
    g.company["messaging"] = s
    return get_settings()


# ---------------- opt-in ----------------
@bp.put("/contacts/<cid_>/whatsapp")
@api("contacts")
def contact_opt(cid_):
    c = t.get("contacts", cid_)
    d = request.get_json(force=True) or {}
    if d.get("opt_in"):
        if d.get("how") not in OPT_HOW:
            abort(400, f"How did they agree? {', '.join(OPT_HOW)}")
        if not wa.phone_e164(c.get("phone")):
            abort(400, "The contact needs a mobile number")
        ch = {"whatsapp_opt_in": {"at": t.now(), "how": d["how"], "by": g.user.get("name")}, "whatsapp_opt_out": None}
    else:
        ch = {"whatsapp_opt_in": None, "whatsapp_opt_out": {"at": t.now(), "how": "staff", "by": g.user.get("name")}}
    return jsonify(serialize(t.update("contacts", cid_, ch)))


@bp.put("/portal/whatsapp")
@portal
def portal_opt():
    c = db.contacts.find_one({"_id": oid(g.contact_id), "company_id": g.cid}) or abort(404, "contact not found")
    on = bool((request.get_json(force=True) or {}).get("opt_in"))
    if on and not wa.phone_e164(c.get("phone")):
        abort(400, "Add your mobile number first (ask the team)")
    ch = {"whatsapp_opt_in": {"at": t.now(), "how": "Portal tick", "by": g.user.get("name")}, "whatsapp_opt_out": None} if on else \
        {"whatsapp_opt_in": None, "whatsapp_opt_out": {"at": t.now(), "how": "portal", "by": g.user.get("name")}}
    db.contacts.update_one({"_id": c["_id"]}, {"$set": ch})
    return jsonify({"opt_in": on})


@bp.get("/portal/whatsapp")
@portal
def portal_opt_get():
    c = db.contacts.find_one({"_id": oid(g.contact_id), "company_id": g.cid}) or {}
    return jsonify({"opt_in": wa.opted_in(c), "has_phone": bool(wa.phone_e164(c.get("phone"))), "available": wa.ready()})


# ---------------- sending templates ----------------
@bp.post("/message_templates/<tid>/send")
@api("messages")
def send_template(tid):
    """Render a template for a contact (with the lead / project for its merge fields) and send it on WhatsApp, or log it."""
    from .followups import render as render_route
    tpl = t.get("message_templates", tid)
    d = request.get_json(force=True) or {}
    c = (t.get("contacts", d["contact_id"], required=False) if d.get("contact_id") else None) or abort(400, "Choose the contact")
    text = (d.get("text") or "").strip() or render_route(tid).get_json().get("text")  # same merge as the preview
    if "{{" in (text or ""):
        abort(400, "Fill every merge field before sending")
    m = wa.send(c, text, kind="template", ref=tid, template=tpl.get("provider_template"))
    if d.get("lead_id"):  # the lead's timeline keeps every message, sent or logged
        from ..services.sales import log
        log(d["lead_id"], "whatsapp", f"WhatsApp to {c['name']} ({m['status']}): {text[:200]}")
    return jsonify(serialize(m)), 201


@bp.get("/contacts/<cid_>/whatsapp")
@api("contacts", write=False)
def contact_messages(cid_):
    t.get("contacts", cid_)
    return jsonify(serialize(list(db.messages.find({"company_id": g.cid, "channel": "whatsapp", "contact_id": cid_}).sort("created_at", -1).limit(100))))


# ---------------- the provider's webhook ----------------
@bp.get("/webhooks/messages/<cid_>")
def webhook_verify(cid_):
    """Meta's subscription check: echo hub.challenge when the verify token matches."""
    company = db.companies.find_one({"_id": oid(cid_)}) if len(cid_) == 24 else None
    s = wa.settings(company) if company else {}
    if request.args.get("hub.mode") == "subscribe" and s.get("verify_token") and request.args.get("hub.verify_token") == s["verify_token"]:
        return request.args.get("hub.challenge", ""), 200, {"Content-Type": "text/plain"}
    abort(403, "Verify token does not match")


@bp.post("/webhooks/messages/<cid_>")
def webhook(cid_):
    company = db.companies.find_one({"_id": oid(cid_), "deleted_at": None}) if len(cid_) == 24 else None
    raw = request.get_data()
    if not company or not wa.verify(company, raw, request.headers.get("X-Hub-Signature-256")):
        abort(400, "Bad signature")
    g.cid, g.company, g.uid, g.user = cid_, company, None, {"name": "WhatsApp"}
    body = json.loads(raw or b"{}")
    order = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for st in value.get("statuses", []):
                m = db.messages.find_one({"company_id": cid_, "provider_id": st.get("id")})
                if not m or order.get(st.get("status"), 0) <= order.get(m["status"], 0):
                    continue
                err = (st.get("errors") or [{}])[0].get("title") if st.get("status") == "failed" else None
                db.messages.update_one({"_id": m["_id"]}, {"$set": {"status": st["status"], "error": err, f"{st['status']}_at": t.now()}})
                if st["status"] == "failed" and m.get("by_id"):
                    notify.send("whatsapp_failed", [m["by_id"]], f"WhatsApp to {m.get('contact_name')} failed: {err or 'unknown error'}",
                                f"/app/contacts/{m.get('contact_id')}", skip_self=False)
            for msg in value.get("messages", []):  # inbound: STOP opts out; anything else is kept against the contact
                frm = msg.get("from")
                text = ((msg.get("text") or {}).get("body") or "").strip()
                contact = next((c for c in db.contacts.find({"company_id": cid_, "phone": {"$ne": None}}, {"phone": 1, "name": 1})
                                if wa.phone_e164(c.get("phone")) == frm), None)
                if not contact:
                    continue
                if text.upper() in ("STOP", "UNSUBSCRIBE"):
                    db.contacts.update_one({"_id": contact["_id"]}, {"$set": {"whatsapp_opt_in": None,
                                                                              "whatsapp_opt_out": {"at": t.now(), "how": "STOP", "by": "WhatsApp"}}})
                if db.messages.find_one({"company_id": cid_, "provider_id": msg.get("id"), "direction": "in"}) and msg.get("id"):
                    continue  # the provider sent it again
                routed = None
                if text and text.upper() not in ("STOP", "UNSUBSCRIBE"):
                    from .insights import route_inbound  # Phase I: into the project's thread, to the right person
                    routed = route_inbound(contact, text)
                t.insert("messages", {"channel": "whatsapp", "direction": "in", "contact_id": str(contact["_id"]), "contact_name": contact["name"],
                                      "from": frm, "text": text[:4000], "provider_id": msg.get("id"), "status": "received", "routed": routed})
    return jsonify({"ok": True})
