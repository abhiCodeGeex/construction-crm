"""Phase G block 2 — the client's invoices in the portal, and paying them online.

* The client (project role *Client*) sees the project's sent / part-paid / paid invoices and credit notes, never drafts
  or void ones, with the receipts against them.
* **Pay** creates a payment link for the balance (or a part of it); a new link cancels the previous one. Links last 7
  days. Staff can create the same link to share it, and a sent invoice email carries it when payments are set up.
* The provider's signed webhook is the only way a payment becomes a receipt (mode *Online*, the provider's payment id
  as reference) through the same `record_receipt` staff use; the same payment never makes a second receipt.
* Settings -> Online payments: provider, keys and webhook secret; secrets are never sent back.
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, abort, g, current_app

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal
from ..services import notify, payments as pay, sales
from .invoices import present as present_invoice, balance, record_receipt
from .lead_money import money_text
from .lead_steps import num
from .proposals import branding
from .site_reports import portal_project

bp = Blueprint("payments", __name__)
SECRETS = ("key_secret", "webhook_secret")


# ---------------- Settings -> Online payments ----------------
@bp.get("/settings/payments")
@api("settings", write=False)
def get_settings():
    s = pay.settings(g.company)
    out = {k: v for k, v in s.items() if k not in SECRETS}
    out.update({f"{k}_set": bool(s.get(k)) for k in SECRETS})
    out.update(providers=pay.PROVIDERS, enabled=pay.enabled(g.company),
               webhook_url=f"/api/webhooks/payments/{s['provider'] or '<provider>'}/{g.cid}")
    return jsonify(out)


@bp.put("/settings/payments")
@api("settings")
def put_settings():
    d = request.get_json(force=True) or {}
    s = pay.settings(g.company)
    if "provider" in d:
        if d["provider"] not in (None, "", *pay.PROVIDERS):
            abort(400, f"Provider: {', '.join(pay.PROVIDERS)}")
        s["provider"] = d["provider"] or None
    if "mode" in d:
        if d["mode"] not in ("test", "live"):
            abort(400, "Mode is test or live")
        s["mode"] = d["mode"]
    if "key_id" in d:
        s["key_id"] = (d["key_id"] or "").strip() or None
    for k in SECRETS:
        if d.get(k):  # empty keeps the stored secret
            s[k] = d[k].strip()
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"payments": s}})
    t.audit("update", "companies", g.company["_id"], note="online payment settings changed")
    g.company["payments"] = s
    return get_settings()


# ---------------- links ----------------
def client_customer(inv):
    c = db.contacts.find_one({"_id": oid(inv["client_id"]), "company_id": g.cid}) if inv.get("client_id") else None
    return {"name": (c or {}).get("name") or inv.get("client_name"), "email": (c or {}).get("email"), "phone": (c or {}).get("phone")}


def make_link(inv, amount=None):
    if not pay.enabled(g.company):
        abort(409, "Online payments are not set up (Settings -> Online payments)")
    if inv["kind"] == "credit_note" or inv["status"] not in ("sent", "part_paid"):
        abort(409, "Only a sent invoice with something left to pay can be paid online")
    left = balance(inv)
    amount = round(num(amount, "Amount") if amount not in (None, "") else left, 2)
    if amount <= 0 or amount > left + 0.01:
        abort(400, f"Pay up to {money_text(left)}")
    for old in db.payment_links.find({"company_id": g.cid, "invoice_id": str(inv["_id"]), "status": "created"}):
        pay.cancel_link(g.company, old)
        db.payment_links.update_one({"_id": old["_id"]}, {"$set": {"status": "cancelled"}})
    base = request.host_url
    try:
        link = pay.create_link(g.company, inv, amount, client_customer(inv), base)
    except pay.PaymentError as e:
        abort(502, str(e))
    doc = t.insert("payment_links", {"invoice_id": str(inv["_id"]), "invoice_number": inv["number"], "project_id": inv.get("project_id"),
                                     "amount": amount, **link, "status": "created", "events": [],
                                     "created_by_name": g.user.get("name")})
    return doc


def link_out(doc):
    return {"url": doc["url"], "amount": doc["amount"], "provider": doc["provider"],
            "expires_at": datetime.fromtimestamp(doc["expires_at"], tz=timezone.utc).isoformat()}


@bp.post("/invoices/<iid>/pay-link")
@api("finance")
def staff_link(iid):
    from .invoices import load_invoice
    inv = load_invoice(iid)
    return jsonify(link_out(make_link(inv, (request.get_json(force=True) or {}).get("amount")))), 201


# ---------------- the client's invoices ----------------
def client_project(pid):
    p = portal_project(pid)
    if not any(m.get("contact_id") == g.contact_id and m.get("project_role") == "Client" for m in p.get("team", [])):
        abort(403, "Only the client sees the project's invoices")
    return p


def portal_view(inv):
    data = present_invoice(inv)
    for k in ("created_by_name", "sent_by", "early_reason", "emailed"):
        data.pop(k, None)
    return data


@bp.get("/portal/projects/<pid>/invoices")
@portal
def portal_invoices(pid):
    client_project(pid)
    rows = [portal_view(i) for i in db.invoices.find({"company_id": g.cid, "project_id": pid, "status": {"$in": ["sent", "part_paid", "paid"]}})
            .sort("date", -1)]
    receipts = [{"number": r["number"], "date": r["date"], "amount": r["amount"], "mode": r["mode"],
                 "invoices": [a["invoice_number"] for a in r["allocations"]]}
                for r in db.receipts.find({"company_id": g.cid, "project_id": pid, "status": "received"}).sort("date", -1)]
    return jsonify({"invoices": rows, "receipts": receipts, "pay_enabled": pay.enabled(g.company),
                    "balance": round(sum(r["balance"] for r in rows if r["kind"] != "credit_note"), 2)})


@bp.get("/portal/invoices/<iid>")
@portal
def portal_invoice(iid):
    inv = db.invoices.find_one({"_id": oid(iid), "company_id": g.cid, "status": {"$in": ["sent", "part_paid", "paid"]}}) if len(iid) == 24 else None
    if not inv or not inv.get("project_id"):
        abort(404, "invoice not found")
    client_project(inv["project_id"])
    data = portal_view(inv)
    data["company"] = branding(g.company)
    return jsonify(data)


@bp.post("/portal/invoices/<iid>/pay")
@portal
def portal_pay(iid):
    inv = db.invoices.find_one({"_id": oid(iid), "company_id": g.cid}) if len(iid) == 24 else None
    if not inv or not inv.get("project_id"):
        abort(404, "invoice not found")
    client_project(inv["project_id"])
    return jsonify(link_out(make_link(inv, (request.get_json(force=True) or {}).get("amount")))), 201


# ---------------- the provider's webhook (no login: signed) ----------------
@bp.post("/webhooks/payments/<provider>/<cid_>")
def webhook(provider, cid_):
    company = db.companies.find_one({"_id": oid(cid_), "deleted_at": None}) if len(cid_) == 24 else None
    raw = request.get_data()
    if not company or not pay.verify(company, provider, request.headers, raw):
        abort(400, "Bad signature")
    g.cid, g.company, g.uid, g.role, g.kind, g.hide_costs = cid_, company, None, None, "system", False
    g.user = {"name": f"Online payment ({pay.PROVIDERS.get(provider, provider)})"}
    try:
        event = pay.parse_event(provider, json.loads(raw or b"{}"))
    except ValueError:
        abort(400, "Bad body")
    if not event:
        return jsonify({"ok": True, "ignored": True})
    link = db.payment_links.find_one({"company_id": cid_, "provider": provider, "ref": event["link_ref"]})
    if not link:
        return jsonify({"ok": True, "ignored": "unknown link"})
    if db.payment_links.find_one({"company_id": cid_, "events.payment_id": event["payment_id"]}, {"_id": 1}):
        return jsonify({"ok": True, "duplicate": True})  # the provider retried: one payment, one receipt
    db.payment_links.update_one({"_id": link["_id"]}, {"$set": {"status": "paid", "paid_at": t.now()}, "$push": {"events": {**event, "at": t.now()}}})
    inv = db.invoices.find_one({"_id": oid(link["invoice_id"])})
    p = db.projects.find_one({"_id": oid(inv["project_id"])})
    amount = min(event["amount"], balance(inv))
    if amount <= 0:
        current_app.logger.warning("payment %s for an invoice with nothing left to pay", event["payment_id"])
        return jsonify({"ok": True, "overpaid": event["amount"]})
    rc = record_receipt(p, amount, sales.today(), "Online", event["payment_id"], f"Paid online ({event.get('method') or provider})",
                        [(inv, amount)], {"payment_link_id": str(link["_id"]), "provider": provider})
    customer = client_customer(inv)
    if customer.get("email"):
        notify.deliver(company, customer["email"], f"Payment received — {inv['number']}",
                       f"Thank you. We received {money_text(amount)} against invoice {inv['number']} ({inv.get('project_name') or ''}).\n"
                       f"Receipt {rc['number']}, reference {event['payment_id']}.\n\n{company['name']}")
    return jsonify({"ok": True, "receipt": rc["number"]})


# ---------------- sandbox provider: a test checkout page (no real money) ----------------
SANDBOX_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test payment</title><style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;color:#111}}
.box{{border:1px solid #ddd;border-radius:12px;padding:1.5rem}}button{{background:#4f46e5;color:#fff;border:0;border-radius:8px;padding:.7rem 1.2rem;font-size:1rem;cursor:pointer}}
.warn{{background:#fff7ed;color:#9a3412;padding:.5rem .7rem;border-radius:8px;font-size:.9rem}}</style></head><body><div class="box">
<p class="warn">Sandbox: a test payment. No money moves.</p><h2>{company}</h2><p>Invoice {number}</p><p style="font-size:1.6rem"><strong>{amount}</strong></p>
{action}</div></body></html>"""


def sandbox_link(ref):
    link = db.payment_links.find_one({"provider": "sandbox", "ref": ref})
    if not link:
        abort(404, "payment link not found")
    company = db.companies.find_one({"_id": oid(link["company_id"])})
    if pay.settings(company)["provider"] != "sandbox":
        abort(404, "payment link not found")
    return link, company


@bp.get("/payments/sandbox/<ref>")
def sandbox_page(ref):
    link, company = sandbox_link(ref)
    action = "<p>Paid. Thank you.</p>" if link["status"] == "paid" else \
        ("<p>This link is no longer valid.</p>" if link["status"] != "created" else
         f'<form method="post" action="/api/payments/sandbox/{ref}"><button type="submit">Pay (test)</button></form>')
    return SANDBOX_PAGE.format(company=company["name"], number=link["invoice_number"], amount=money_text(link["amount"]), action=action), 200, \
        {"Content-Type": "text/html; charset=utf-8"}


@bp.post("/payments/sandbox/<ref>")
def sandbox_pay(ref):
    """The sandbox 'provider' pays: it calls our own webhook with a signed body, exactly as Razorpay would."""
    link, company = sandbox_link(ref)
    if link["status"] != "created":
        return sandbox_page(ref)
    raw = json.dumps(pay.sandbox_event(ref, link["amount"])).encode()
    sig = pay.sign(pay.settings(company)["webhook_secret"], raw)
    with current_app.test_request_context(f"/api/webhooks/payments/sandbox/{company['_id']}", method="POST", data=raw,
                                          headers={pay.SIG_HEADER["sandbox"]: sig, "Content-Type": "application/json"}):
        webhook("sandbox", str(company["_id"]))
    return sandbox_page(ref)
