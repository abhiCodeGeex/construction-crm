"""Phase J block 7 — the subscription charged automatically (v4 §18 "charged automatically through Razorpay or Stripe").

* The Owner sets up autopay (card or UPI mandate) under Settings → Subscription. The platform's gateway (Super Admin
  settings: sandbox, Razorpay or Stripe) holds the mandate; the sandbox makes it active at once.
    Razorpay: a customer and a recurring-token authorisation order; the mandate is active when the signed webhook
              says `token.confirmed`.
    Stripe:   a customer and a SetupIntent (off-session); active on `setup_intent.succeeded`.
* The daily billing run charges an open invoice of a company with an active mandate: once when it is issued, then once a
  day up to three tries. Success marks the invoice paid (renewal moves on). A failed try is kept with the gateway's
  reason and the Owner is emailed; after the third the company pays by hand and the read-only rule applies as before.
* Live gateways answer through the signed webhook /api/webhooks/billing/<gateway> (HMAC-SHA256 of the body with the
  webhook secret; Stripe's t=…,v1=… header): payment captured -> paid, payment failed -> a failed try.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import uuid

from flask import Blueprint, request, jsonify, abort, g

from ..db import db, oid, serialize
from ..security import api
from ..tenancy import now

bp = Blueprint("autopay", __name__)
GATEWAYS = ("sandbox", "razorpay", "stripe")
MAX_TRIES = 3
METHODS = ("card", "upi")


def psettings():
    return db.platform_settings.find_one({"_id": "settings"}) or {}


def gateway():
    return psettings().get("gateway") or "sandbox"


def _http(url, data=None, auth=None, form=False, method="POST"):
    body = None
    headers = {}
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode() if form else json.dumps(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read() or b"{}"), None
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error") or {}
        except ValueError:
            err = {}
        return None, (err.get("description") or err.get("message") or str(e)) if isinstance(err, dict) else str(err)
    except OSError as e:
        return None, f"The payment gateway could not be reached: {e}"


def _rzp_auth(s):
    return "Basic " + base64.b64encode(f"{s.get('gateway_key')}:{s.get('gateway_secret')}".encode()).decode()


def _stripe_auth(s):
    return f"Bearer {s.get('gateway_secret')}"


def flatten(prefix, d, out=None):
    out = {} if out is None else out
    for k, v in d.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            flatten(key, v, out)
        else:
            out[key] = v
    return out


# ============================== setting up the mandate ==============================
def owner_only():
    if g.role != "owner":
        abort(403, "Only the Owner manages the subscription")


@bp.get("/billing/autopay")
@api(None)
def get_autopay():
    owner_only()
    return jsonify(serialize({"gateway": gateway(), "autopay": g.company.get("autopay"), "max_tries": MAX_TRIES}))


@bp.post("/billing/autopay")
@api(None)
def setup_autopay():
    owner_only()
    d = request.get_json(force=True) or {}
    method = d.get("method") if d.get("method") in METHODS else abort(400, "Card or UPI")
    gw, s, c = gateway(), psettings(), g.company
    ap = {"gateway": gw, "method": method, "status": "pending", "since": now(), "mandate_id": None, "customer_id": None, "tries": 0,
          "last_error": None, "set_by": g.user.get("name")}
    if gw == "sandbox":  # a test card "4000 0000 0000 0002" (or UPI "fail@upi") makes every charge fail, for trying the retries
        ap.update(status="active", mandate_id=f"SBX-MDT-{uuid.uuid4().hex[:10]}", customer_id=f"SBX-CUS-{uuid.uuid4().hex[:8]}",
                  test_fail=(d.get("test") in ("4000000000000002", "fail@upi")), label=f"{method.upper()} (sandbox)")
    elif gw == "razorpay":
        cust, err = _http("https://api.razorpay.com/v1/customers", {"name": c["name"], "email": c.get("owner_email"), "fail_existing": "0",
                                                                   "notes": {"company_id": g.cid}}, _rzp_auth(s))
        if err:
            abort(502, f"Razorpay: {err}")
        order, err = _http("https://api.razorpay.com/v1/orders", {
            "amount": 100 if method == "card" else 0, "currency": "INR", "customer_id": cust["id"], "method": "upi" if method == "upi" else "card",
            "payment_capture": True, "notes": {"company_id": g.cid, "purpose": "autopay"},
            "token": {"max_amount": 50000000, "frequency": "as_presented", "expire_at": int(time.time()) + 10 * 365 * 86400}}, _rzp_auth(s))
        if err:
            abort(502, f"Razorpay: {err}")
        ap.update(customer_id=cust["id"], checkout={"key": s.get("gateway_key"), "order_id": order["id"], "customer_id": cust["id"],
                                                    "recurring": "1"})
    else:  # stripe
        cust, err = _http("https://api.stripe.com/v1/customers", flatten("", {"name": c["name"], "email": c.get("owner_email") or "",
                                                                              "metadata": {"company_id": g.cid}}), _stripe_auth(s), form=True)
        if err:
            abort(502, f"Stripe: {err}")
        si, err = _http("https://api.stripe.com/v1/setup_intents", flatten("", {"customer": cust["id"], "usage": "off_session",
                                                                                "metadata": {"company_id": g.cid}}), _stripe_auth(s), form=True)
        if err:
            abort(502, f"Stripe: {err}")
        ap.update(customer_id=cust["id"], checkout={"client_secret": si["client_secret"], "publishable_key": s.get("gateway_key")})
    db.companies.update_one({"_id": c["_id"]}, {"$set": {"autopay": ap}})
    g.company["autopay"] = ap
    # an invoice already open is charged at once when the mandate is active
    paid = None
    if ap["status"] == "active":
        inv = db.platform_invoices.find_one({"company_id": g.cid, "status": {"$in": ["due", "overdue"]}, "type": "invoice"})
        if inv:
            paid = charge(db.companies.find_one({"_id": c["_id"]}), inv)
    return jsonify(serialize({"autopay": ap, "charged": paid})), 201


@bp.delete("/billing/autopay")
@api(None)
def cancel_autopay():
    owner_only()
    ap = g.company.get("autopay") or abort(409, "Autopay is not set up")
    s = psettings()
    if ap.get("gateway") == "razorpay" and ap.get("mandate_id") and ap.get("customer_id"):
        _http(f"https://api.razorpay.com/v1/customers/{ap['customer_id']}/tokens/{ap['mandate_id']}/cancel", {}, _rzp_auth(s), method="PUT")
    if ap.get("gateway") == "stripe" and ap.get("mandate_id"):
        _http(f"https://api.stripe.com/v1/payment_methods/{ap['mandate_id']}/detach", {}, _stripe_auth(s), form=True)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"autopay": {**ap, "status": "cancelled", "cancelled_at": now()}}})
    return jsonify({"ok": True})


# ============================== charging ==============================
def mail_owner(c, subject, text):
    from ..services import notify
    from .platform import platform_mail
    if c.get("owner_email"):
        notify.deliver(platform_mail(), c["owner_email"], subject, text)


def failed(c, inv, reason, day=None):
    ap = c.get("autopay") or {}
    tries = (inv.get("charge_tries") or 0) + 1
    db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"charge_tries": tries, "charge_error": reason, "charged_on": day or now().date().isoformat()},
                                                          "$push": {"charges": {"at": now(), "status": "failed", "error": reason}}})
    db.companies.update_one({"_id": c["_id"]}, {"$set": {"autopay.last_error": reason, "autopay.tries": tries}})
    left = MAX_TRIES - tries
    mail_owner(c, f"BuildSuite: payment of {inv['number']} failed",
               f"We could not charge {inv['total']:,.2f} for invoice {inv['number']}: {reason}.\n"
               + (f"We will try again tomorrow ({left} more {'try' if left == 1 else 'tries'})." if left > 0 else
                  "Please pay it from Settings → Subscription; automatic retries have stopped."))
    return {"status": "failed", "error": reason, "tries": tries}


def charge(c, inv, day=None):
    """One try to charge an open invoice on the company's active mandate."""
    from .platform import mark_paid
    ap = c.get("autopay") or {}
    if ap.get("status") != "active" or inv["status"] not in ("due", "overdue") or (inv.get("charge_tries") or 0) >= MAX_TRIES:
        return None
    day = day or now().date().isoformat()
    if inv.get("charged_on") == day or inv.get("charge_pending"):
        return None  # once a day; a live charge waits for its webhook
    s = psettings()
    amount = int(round(inv["total"] * 100))
    if ap["gateway"] == "sandbox":
        if ap.get("test_fail"):
            return failed(c, inv, "Card declined (sandbox test card)", day)
        ref = f"SBX-AUTO-{uuid.uuid4().hex[:10]}"
        db.platform_invoices.update_one({"_id": inv["_id"]}, {"$push": {"charges": {"at": now(), "status": "paid", "ref": ref}}})
        mark_paid(inv, "autopay", ref)
        mail_owner(c, f"BuildSuite: {inv['number']} paid", f"Invoice {inv['number']} ({inv['total']:,.2f}) was charged to your {ap.get('method', 'card')}. Thank you.")
        return {"status": "paid", "ref": ref}
    if ap["gateway"] == "razorpay":
        order, err = _http("https://api.razorpay.com/v1/orders", {"amount": amount, "currency": "INR", "payment_capture": True,
                                                                  "notes": {"invoice_id": str(inv["_id"]), "company_id": inv["company_id"]}}, _rzp_auth(s))
        if not err:
            pay, err = _http("https://api.razorpay.com/v1/payments/create/recurring", {
                "email": c.get("owner_email"), "contact": c.get("phone") or "", "amount": amount, "currency": "INR", "order_id": order["id"],
                "customer_id": ap["customer_id"], "token": ap["mandate_id"], "recurring": "1",
                "notes": {"invoice_id": str(inv["_id"]), "company_id": inv["company_id"]}}, _rzp_auth(s))
    else:
        pay, err = _http("https://api.stripe.com/v1/payment_intents", flatten("", {
            "amount": amount, "currency": "inr", "customer": ap["customer_id"], "payment_method": ap["mandate_id"], "off_session": "true",
            "confirm": "true", "metadata": {"invoice_id": str(inv["_id"]), "company_id": inv["company_id"]}}), _stripe_auth(s), form=True)
    if err:
        return failed(c, inv, err, day)
    db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"charge_pending": True, "charged_on": day},
                                                          "$push": {"charges": {"at": now(), "status": "pending", "ref": (pay or {}).get("id")}}})
    return {"status": "pending", "ref": (pay or {}).get("id")}


# ============================== webhook ==============================
def verify(gw, raw):
    secret = psettings().get("gateway_webhook_secret") or ""
    if not secret:
        return False
    if gw == "stripe":
        parts = dict(x.split("=", 1) for x in (request.headers.get("Stripe-Signature") or "").split(",") if "=" in x)
        if not parts.get("t") or not parts.get("v1"):
            return False
        mac = hmac.new(secret.encode(), f"{parts['t']}.".encode() + raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, parts["v1"]) and abs(time.time() - int(parts["t"])) < 600
    header = request.headers.get("X-Razorpay-Signature") or request.headers.get("X-Signature") or ""
    return bool(header) and hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), header)


def settle(invoice_id, ok, ref=None, reason=None):
    from .platform import mark_paid
    inv = db.platform_invoices.find_one({"_id": oid(invoice_id)}) if invoice_id and len(invoice_id) == 24 else None
    if not inv:
        return "unknown invoice"
    db.platform_invoices.update_one({"_id": inv["_id"]}, {"$set": {"charge_pending": False}})
    if inv["status"] == "paid":
        return "already paid"
    c = db.companies.find_one({"_id": oid(inv["company_id"])})
    if ok:
        mark_paid(inv, "autopay", ref)
        mail_owner(c, f"BuildSuite: {inv['number']} paid", f"Invoice {inv['number']} ({inv['total']:,.2f}) was charged automatically. Thank you.")
        return "paid"
    failed(c, {**inv, "charge_pending": False}, reason or "declined")
    return "failed"


def activate(company_id, mandate_id):
    c = db.companies.find_one({"_id": oid(company_id)}) if company_id and len(company_id) == 24 else None
    if not c or not c.get("autopay"):
        return "unknown company"
    db.companies.update_one({"_id": c["_id"]}, {"$set": {"autopay.status": "active", "autopay.mandate_id": mandate_id, "autopay.active_at": now()}})
    return "active"


@bp.post("/webhooks/billing/<gw>")
def billing_webhook(gw):
    if gw not in GATEWAYS:
        abort(404)
    raw = request.get_data()
    if gw != gateway() or not verify(gw, raw):
        abort(400, "Bad signature")
    ev = json.loads(raw or b"{}")
    kind = ev.get("event") or ev.get("type")
    result = "ignored"
    if gw in ("razorpay", "sandbox"):
        pay = (((ev.get("payload") or {}).get("payment") or {}).get("entity")) or {}
        notes = pay.get("notes") or {}
        if kind in ("payment.captured", "order.paid") and notes.get("invoice_id"):
            result = settle(notes["invoice_id"], True, pay.get("id"))
        elif kind == "payment.failed" and notes.get("invoice_id"):
            result = settle(notes["invoice_id"], False, reason=pay.get("error_description"))
        elif kind == "token.confirmed":
            tok = ((ev.get("payload") or {}).get("token") or {}).get("entity") or {}
            result = activate((tok.get("notes") or notes).get("company_id"), tok.get("id"))
    else:
        obj = (ev.get("data") or {}).get("object") or {}
        meta = obj.get("metadata") or {}
        if kind == "payment_intent.succeeded":
            result = settle(meta.get("invoice_id"), True, obj.get("id"))
        elif kind == "payment_intent.payment_failed":
            result = settle(meta.get("invoice_id"), False, reason=((obj.get("last_payment_error") or {}).get("message")))
        elif kind == "setup_intent.succeeded":
            result = activate(meta.get("company_id"), obj.get("payment_method"))
    return jsonify({"ok": True, "result": result})
