"""Online payments (Phase G block 2) behind one small interface, so a second provider (Stripe) plugs in later.

Providers:
* `razorpay` — Payment Links API (INR: UPI, cards, net banking). Test mode with test keys until live keys are entered.
  The webhook is signed with HMAC-SHA256 of the raw body using the webhook secret (`X-Razorpay-Signature`).
* `sandbox` — no network and no real money: a demo / test provider whose link opens a page with a *Pay (test)* button.
  Signed the same way (`X-Sandbox-Signature`), so the webhook path is identical. Never use it for real clients.

Money only becomes a receipt through the provider's signed webhook, never from the browser's return page.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

PROVIDERS = {"razorpay": "Razorpay", "sandbox": "Sandbox (test only, no real money)"}
SIG_HEADER = {"razorpay": "X-Razorpay-Signature", "sandbox": "X-Sandbox-Signature"}
LINK_DAYS = 7


def settings(company):
    return {"provider": None, "key_id": None, "key_secret": None, "webhook_secret": None, "mode": "test", **(company.get("payments") or {})}


def enabled(company):
    s = settings(company)
    if s["provider"] == "sandbox":
        return bool(s["webhook_secret"])
    return s["provider"] == "razorpay" and all(s.get(k) for k in ("key_id", "key_secret", "webhook_secret"))


def sign(secret, raw):
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify(company, provider, headers, raw):
    s = settings(company)
    if provider != s["provider"] or not s.get("webhook_secret"):
        return False
    got = headers.get(SIG_HEADER.get(provider, ""), "")
    return bool(got) and hmac.compare_digest(got, sign(s["webhook_secret"], raw))


def _razorpay(s, method, path, body=None):
    req = urllib.request.Request(f"https://api.razorpay.com/v1{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{s['key_id']}:{s['key_secret']}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("error", {}).get("description") or str(e)
        raise PaymentError(f"Razorpay: {detail}")
    except OSError as e:
        raise PaymentError(f"Razorpay could not be reached: {e}")


class PaymentError(Exception):
    pass


def create_link(company, invoice, amount, customer, base_url):
    """-> {provider, ref, url, expires_at}"""
    s = settings(company)
    expires = int(time.time()) + LINK_DAYS * 86400
    if s["provider"] == "razorpay":
        r = _razorpay(s, "POST", "/payment_links", {
            "amount": int(round(amount * 100)), "currency": company.get("currency", "INR"), "accept_partial": False,
            "description": f"Invoice {invoice['number']} — {invoice.get('project_name') or ''}"[:200],
            "reference_id": f"{invoice['number']}-{uuid.uuid4().hex[:6]}", "expire_by": expires,
            "customer": {k: v for k, v in {"name": customer.get("name"), "email": customer.get("email"),
                                           "contact": customer.get("phone")}.items() if v},
            "notify": {"sms": False, "email": False}, "reminder_enable": False,
            "notes": {"invoice_id": str(invoice["_id"]), "company_id": str(company["_id"])}})
        return {"provider": "razorpay", "ref": r["id"], "url": r["short_url"], "expires_at": expires}
    if s["provider"] == "sandbox":
        ref = f"sbx_{uuid.uuid4().hex[:16]}"
        return {"provider": "sandbox", "ref": ref, "url": f"{base_url.rstrip('/')}/api/payments/sandbox/{ref}", "expires_at": expires}
    raise PaymentError("Online payments are not set up")


def cancel_link(company, link):
    s = settings(company)
    if link["provider"] == "razorpay" and s["provider"] == "razorpay":
        try:
            _razorpay(s, "POST", f"/payment_links/{link['ref']}/cancel")
        except PaymentError:
            pass  # already paid / expired at the provider: our record still closes


def parse_event(provider, body):
    """-> {"type": "paid", "link_ref", "payment_id", "amount"} or None for events we ignore."""
    if body.get("event") != "payment_link.paid":
        return None
    pl = (body.get("payload") or {}).get("payment_link", {}).get("entity", {})
    pay = (body.get("payload") or {}).get("payment", {}).get("entity", {})
    if not pl.get("id") or not pay.get("id"):
        return None
    return {"type": "paid", "link_ref": pl["id"], "payment_id": pay["id"], "amount": round((pay.get("amount") or 0) / 100, 2),
            "method": pay.get("method")}


def sandbox_event(link_ref, amount):
    """The body a sandbox payment sends to the webhook — the same shape as Razorpay's payment_link.paid."""
    return {"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": link_ref}},
        "payment": {"entity": {"id": f"pay_sbx_{uuid.uuid4().hex[:14]}", "amount": int(round(amount * 100)), "method": "test"}}}}
