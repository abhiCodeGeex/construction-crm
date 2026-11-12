"""Phase K block 5 — accounting integration (v4 §12, §15): Tally, Zoho Books, QuickBooks, Xero.

* Tally (Prime / ERP 9): an XML file to import (Gateway of Tally → Import → Vouchers) — the party ledgers (clients under
  Sundry Debtors, vendors and subcontractors under Sundry Creditors) and the vouchers: Sales (invoices, with CGST / SGST /
  IGST ledgers), Receipt, Purchase (approved vendor bills, input GST) and Payment, for a date range. Ledger names are
  set to match the company's books.
* Zoho Books, QuickBooks Online, Xero: connected with the app's OAuth credentials (client id / secret and a refresh
  token from the provider's developer console). "Sync" pushes the invoices and receipts (and bills) not sent yet; each
  record keeps the provider's id, so it is never sent twice; failures are listed with the provider's reason. A daily
  automatic sync is optional. The sandbox provider records a sync without sending anything (for trying it out).
"""
import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from xml.sax.saxutils import escape

from flask import Blueprint, request, jsonify, abort, g, Response

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import gst as gstmod

bp = Blueprint("accounting", __name__)
PROVIDERS = {"none": "Not connected", "tally": "Tally (XML import)", "zoho": "Zoho Books", "quickbooks": "QuickBooks Online", "xero": "Xero",
             "sandbox": "Sandbox (test only, nothing is sent)"}
SECRETS = ("client_secret", "refresh_token", "access_token")
LEDGERS = {"sales": "Sales", "purchase": "Purchase", "cgst_out": "Output CGST", "sgst_out": "Output SGST", "igst_out": "Output IGST",
           "cgst_in": "Input CGST", "sgst_in": "Input SGST", "igst_in": "Input IGST", "bank": "Bank Account", "cash": "Cash",
           "debtors_group": "Sundry Debtors", "creditors_group": "Sundry Creditors"}


def asettings(company=None):
    s = (company or g.company).get("accounting") or {}
    return {"provider": "none", "ledgers": {**LEDGERS, **(s.get("ledgers") or {})}, "auto_sync": False, "client_id": None, "client_secret": None,
            "refresh_token": None, "access_token": None, "token_expires": None, "org_id": None, "region": "in", **{k: v for k, v in s.items() if k != "ledgers"}}


def money_only():
    if g.role not in ("owner", "accounts"):
        abort(403, "Only the Owner or Accounts connects the books")


@bp.get("/settings/accounting")
@api("finance", write=False)
def get_acc():
    money_only()
    s = asettings()
    out = {k: v for k, v in s.items() if k not in SECRETS}
    out.update({f"{k}_set": bool(s.get(k)) for k in SECRETS})
    out.update(providers=PROVIDERS, status=status_counts())
    return jsonify(serialize(out))


@bp.put("/settings/accounting")
@api("finance")
def put_acc():
    money_only()
    d = request.get_json(force=True) or {}
    s = asettings()
    if "provider" in d:
        s["provider"] = d["provider"] if d["provider"] in PROVIDERS else abort(400, f"Provider: {', '.join(PROVIDERS)}")
    if "ledgers" in d:
        s["ledgers"] = {k: (str(d["ledgers"].get(k) or LEDGERS[k]).strip()[:80]) for k in LEDGERS}
    for k in ("client_id", "org_id"):
        if k in d:
            s[k] = (d.get(k) or "").strip() or None
    if "region" in d:
        s["region"] = d["region"] if d["region"] in ("in", "com", "eu", "com.au") else abort(400, "Zoho region: in, com, eu or com.au")
    for k in ("client_secret", "refresh_token"):
        if d.get(k):
            s[k] = d[k].strip()
    if "auto_sync" in d:
        s["auto_sync"] = bool(d["auto_sync"])
    if s["provider"] in ("zoho", "quickbooks", "xero") and not (s.get("client_id") and s.get("client_secret") and s.get("refresh_token")):
        abort(400, "Enter the client id, client secret and refresh token from the provider's developer console")
    if s["provider"] in ("zoho", "quickbooks", "xero") and not s.get("org_id"):
        abort(400, {"zoho": "Organisation id", "quickbooks": "Company (realm) id", "xero": "Tenant id"}[s["provider"]] + " is required")
    s["access_token"], s["token_expires"] = None, None  # new credentials: get a fresh token
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"accounting": s}})
    g.company["accounting"] = s
    t.audit("update", "companies", g.company["_id"], note=f"Accounting: {PROVIDERS[s['provider']]}")
    return get_acc()


# ============================== the records ==============================
def period():
    a = request.args.get("from") or (date.today().replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()
    b = request.args.get("to") or date.today().isoformat()
    try:
        date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        abort(400, "Dates as YYYY-MM-DD")
    return a, b


def records(a, b, kinds=("invoice", "receipt", "bill", "payment")):
    q = lambda extra: {"company_id": g.cid, "date": {"$gte": a, "$lte": b}, **extra}
    out = []
    if "invoice" in kinds:
        out += [("invoice", x) for x in db.invoices.find(q({"number": {"$ne": None}, "status": {"$nin": ["draft", "void"]}, "kind": {"$ne": "credit_note"}}))]
    if "receipt" in kinds:
        out += [("receipt", x) for x in db.receipts.find(q({"status": {"$ne": "void"}}))]
    if "bill" in kinds:
        out += [("bill", x) for x in db.vendor_bills.find(q({"status": {"$in": ["approved", "part_paid", "paid"]}}))]
    if "payment" in kinds:
        out += [("payment", x) for x in db.vendor_payments.find(q({"status": {"$ne": "void"}}))]
    return out


def gst_split(x, kind):
    tax = x.get("tax") or 0
    if kind == "invoice":
        gs = x.get("gst") or gstmod.split(tax, x.get("client_gstin"), x.get("client_state"))
    else:
        vend = db.contacts.find_one({"_id": oid(x["vendor_id"])}) if x.get("vendor_id") and len(str(x["vendor_id"])) == 24 else None
        gs = gstmod.split(tax, (vend or {}).get("gstin"), (vend or {}).get("state"))
    return gs or {"cgst": 0, "sgst": 0, "igst": 0}


def party_of(kind, x):
    if kind in ("invoice", "receipt"):
        name = x.get("client_name")
        if not name and x.get("client_id"):
            c = db.contacts.find_one({"_id": oid(x["client_id"])}) if len(str(x["client_id"])) == 24 else None
            name = (c or {}).get("name")
        return name or "Cash customer", "debtors_group"
    return x.get("vendor_name") or "Vendor", "creditors_group"


# ============================== Tally XML ==============================
def amt(v):
    return f"{v:.2f}"


def entry(ledger, amount, party=False):
    """Tally: negative = debit, positive = credit (ISDEEMEDPOSITIVE Yes for debits)."""
    deemed = "Yes" if amount < 0 else "No"
    return (f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(ledger)}</LEDGERNAME><ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
            f"<ISPARTYLEDGER>{'Yes' if party else 'No'}</ISPARTYLEDGER><AMOUNT>{amt(amount)}</AMOUNT></ALLLEDGERENTRIES.LIST>")


def voucher(kind, x, L):
    d = x["date"].replace("-", "")
    party, _ = party_of(kind, x)
    gs = gst_split(x, kind) if kind in ("invoice", "bill") else None
    if kind == "invoice":
        vt, no, total = "Sales", x["number"], x["total"]
        rows = [entry(party, -total, True), entry(L["sales"], x["subtotal"])]
        rows += [entry(L[k + "_out"], gs[k]) for k in ("cgst", "sgst", "igst") if gs[k]]
    elif kind == "receipt":
        vt, no, total = "Receipt", x["number"], x["amount"]
        rows = [entry(L["cash"] if x.get("mode") == "cash" else L["bank"], -total), entry(party, total, True)]
    elif kind == "bill":
        vt, no, total = "Purchase", x["bill_no"], x["total"]
        rows = [entry(party, total, True), entry(L["purchase"], -x["amount"])]
        rows += [entry(L[k + "_in"], -gs[k]) for k in ("cgst", "sgst", "igst") if gs[k]]
    else:
        vt, no, total = "Payment", x.get("reference") or str(x["_id"])[-6:], x["amount"]
        rows = [entry(party, -total, True), entry(L["cash"] if x.get("mode") == "cash" else L["bank"], total)]
    narr = f"{x.get('project_name') or ''} {x.get('note') or ''}".strip()
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="{vt}" ACTION="Create"><DATE>{d}</DATE><VOUCHERTYPENAME>{vt}</VOUCHERTYPENAME>'
            f"<VOUCHERNUMBER>{escape(str(no))}</VOUCHERNUMBER><PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME><NARRATION>{escape(narr)}</NARRATION>"
            f"{''.join(rows)}</VOUCHER></TALLYMESSAGE>")


@bp.get("/accounting/tally.xml")
@api("finance", write=False)
def tally_xml():
    money_only()
    a, b = period()
    kinds = tuple(k for k in (request.args.get("what") or "invoice,receipt,bill,payment").split(",") if k in ("invoice", "receipt", "bill", "payment"))
    L = asettings()["ledgers"]
    recs = records(a, b, kinds)
    parties = {}
    for kind, x in recs:
        name, grp = party_of(kind, x)
        parties[name] = L[grp]
    masters = "".join(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{escape(n, {chr(34): "&quot;"})}" ACTION="Create"><NAME>{escape(n)}</NAME>'
                      f"<PARENT>{escape(grp)}</PARENT><ISBILLWISEON>Yes</ISBILLWISEON></LEDGER></TALLYMESSAGE>" for n, grp in sorted(parties.items()))
    vouchers = "".join(voucher(k, x, L) for k, x in sorted(recs, key=lambda kx: kx[1]["date"]))
    company = escape(g.company.get("tally_company") or g.company["name"])
    xml = (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>"
           f"<STATICVARIABLES><SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>{masters}{vouchers}"
           f"</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    for kind, x in recs:
        db.accounting_sync.update_one({"company_id": g.cid, "kind": kind, "doc_id": str(x["_id"]), "provider": "tally"},
                                      {"$set": {"status": "exported", "number": x.get("number") or x.get("bill_no"), "at": t.now()}}, upsert=True)
    return Response(xml, mimetype="application/xml", headers={"Content-Disposition": f'attachment; filename="tally-{a}-to-{b}.xml"'})


# ============================== online providers ==============================
def _http(method, url, body=None, headers=None, form=False):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    h.setdefault("Accept", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}"), None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        msg = body.get("message") or body.get("error_description") or body.get("Message") or (body.get("Fault") or {}).get("Error", [{}])[0].get("Detail") or str(e)
        return None, str(msg)[:300]
    except OSError as e:
        return None, f"could not reach the provider: {e}"


TOKEN_URLS = {"zoho": lambda s: f"https://accounts.zoho.{s.get('region') or 'in'}/oauth/v2/token",
              "quickbooks": lambda s: "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
              "xero": lambda s: "https://identity.xero.com/connect/token"}


def token(s):
    if s.get("access_token") and s.get("token_expires") and s["token_expires"] > t.now():
        return s["access_token"]
    import base64
    body = {"grant_type": "refresh_token", "refresh_token": s["refresh_token"]}
    headers = {}
    if s["provider"] == "zoho":
        body.update(client_id=s["client_id"], client_secret=s["client_secret"])
    else:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{s['client_id']}:{s['client_secret']}".encode()).decode()
    res, err = _http("POST", TOKEN_URLS[s["provider"]](s), body, headers, form=True)
    if err or not res.get("access_token"):
        abort(502, f"{PROVIDERS[s['provider']]} sign-in failed: {err or res}")
    s.update(access_token=res["access_token"], token_expires=t.now() + timedelta(seconds=int(res.get("expires_in", 3600)) - 60))
    if res.get("refresh_token"):
        s["refresh_token"] = res["refresh_token"]  # QuickBooks and Xero rotate it
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"accounting": s}})
    return s["access_token"]


def push(s, kind, x):
    """Send one record; returns (external id, error)."""
    prov = s["provider"]
    if prov == "sandbox":
        return f"SBX-{kind[:3].upper()}-{str(x['_id'])[-8:]}", None
    party, _ = party_of(kind, x)
    tok = token(s)
    if prov == "zoho":
        base = f"https://www.zohoapis.{s.get('region') or 'in'}/books/v3"
        auth = {"Authorization": f"Zoho-oauthtoken {tok}"}
        q = f"?organization_id={s['org_id']}"
        if kind == "invoice":
            cust, err = _http("GET", f"{base}/contacts{q}&contact_name={urllib.parse.quote(party)}", headers=auth)
            if err:
                return None, err
            cid = ((cust or {}).get("contacts") or [{}])[0].get("contact_id")
            if not cid:
                made, err = _http("POST", f"{base}/contacts{q}", {"contact_name": party, "contact_type": "customer", "gst_no": x.get("client_gstin")}, auth)
                if err:
                    return None, err
                cid = made["contact"]["contact_id"]
            body = {"customer_id": cid, "invoice_number": x["number"], "date": x["date"], "due_date": x.get("due_date"), "ignore_auto_number_generation": True,
                    "line_items": [{"name": ln["description"][:100], "rate": ln["rate"], "quantity": ln["qty"], "hsn_or_sac": ln.get("hsn")} for ln in x["lines"]]}
            res, err = _http("POST", f"{base}/invoices{q}", body, auth)
            return (res or {}).get("invoice", {}).get("invoice_id"), err
        if kind == "receipt":
            body = {"customer_name": party, "payment_mode": x.get("mode") or "banktransfer", "amount": x["amount"], "date": x["date"], "reference_number": x["number"]}
            res, err = _http("POST", f"{base}/customerpayments{q}", body, auth)
            return (res or {}).get("payment", {}).get("payment_id"), err
        return None, "Zoho: bills and vendor payments go through the Tally / CSV export"
    if prov == "quickbooks":
        base = f"https://quickbooks.api.intuit.com/v3/company/{s['org_id']}"
        auth = {"Authorization": f"Bearer {tok}"}
        cust, err = _http("GET", f"{base}/query?query=" + urllib.parse.quote(f"select Id from Customer where DisplayName = '{party.replace(chr(39), '')}'"), headers=auth)
        if err:
            return None, err
        cid = (((cust or {}).get("QueryResponse") or {}).get("Customer") or [{}])[0].get("Id")
        if not cid:
            made, err = _http("POST", f"{base}/customer", {"DisplayName": party}, auth)
            if err:
                return None, err
            cid = made["Customer"]["Id"]
        if kind == "invoice":
            body = {"CustomerRef": {"value": cid}, "DocNumber": x["number"][:21], "TxnDate": x["date"], "DueDate": x.get("due_date"),
                    "Line": [{"DetailType": "SalesItemLineDetail", "Amount": ln["amount"], "Description": ln["description"],
                              "SalesItemLineDetail": {"Qty": ln["qty"], "UnitPrice": ln["rate"]}} for ln in x["lines"]]}
            res, err = _http("POST", f"{base}/invoice", body, auth)
            return ((res or {}).get("Invoice") or {}).get("Id"), err
        if kind == "receipt":
            res, err = _http("POST", f"{base}/payment", {"CustomerRef": {"value": cid}, "TotalAmt": x["amount"], "TxnDate": x["date"], "PaymentRefNum": x["number"]}, auth)
            return ((res or {}).get("Payment") or {}).get("Id"), err
        return None, "QuickBooks: bills and vendor payments go through the Tally / CSV export"
    # xero
    auth = {"Authorization": f"Bearer {tok}", "xero-tenant-id": s["org_id"]}
    if kind == "invoice":
        body = {"Invoices": [{"Type": "ACCREC", "Contact": {"Name": party}, "InvoiceNumber": x["number"], "Date": x["date"], "DueDate": x.get("due_date") or x["date"],
                              "Status": "AUTHORISED", "LineItems": [{"Description": ln["description"], "Quantity": ln["qty"], "UnitAmount": ln["rate"],
                                                                     "AccountCode": "200"} for ln in x["lines"]]}]}
        res, err = _http("PUT", "https://api.xero.com/api.xro/2.0/Invoices", body, auth)
        return (((res or {}).get("Invoices") or [{}])[0]).get("InvoiceID"), err
    if kind == "bill":
        body = {"Invoices": [{"Type": "ACCPAY", "Contact": {"Name": party}, "InvoiceNumber": x["bill_no"], "Date": x["date"], "DueDate": x.get("due_date") or x["date"],
                              "Status": "AUTHORISED", "LineItems": [{"Description": ln.get("description", "Purchase"), "Quantity": ln.get("qty") or 1,
                                                                     "UnitAmount": ln.get("rate") or ln.get("amount"), "AccountCode": "300"} for ln in x["lines"]]}]}
        res, err = _http("PUT", "https://api.xero.com/api.xro/2.0/Invoices", body, auth)
        return (((res or {}).get("Invoices") or [{}])[0]).get("InvoiceID"), err
    return None, "Xero: receipts and payments are matched in Xero's bank reconciliation"


def sync(a=None, b=None):
    s = asettings()
    if s["provider"] not in ("zoho", "quickbooks", "xero", "sandbox"):
        abort(409, "Connect Zoho Books, QuickBooks or Xero first (Tally uses the XML export)")
    a = a or (date.today() - timedelta(days=60)).isoformat()
    b = b or date.today().isoformat()
    sent = failed = skipped = 0
    for kind, x in records(a, b, ("invoice", "receipt", "bill")):
        done = db.accounting_sync.find_one({"company_id": g.cid, "kind": kind, "doc_id": str(x["_id"]), "provider": s["provider"], "status": "synced"})
        if done:
            skipped += 1
            continue
        ext, err = push(s, kind, x)
        if ext:
            sent += 1
        else:
            failed += 1
        db.accounting_sync.update_one({"company_id": g.cid, "kind": kind, "doc_id": str(x["_id"]), "provider": s["provider"]},
                                      {"$set": {"status": "synced" if ext else "failed", "external_id": ext, "error": None if ext else err,
                                                "number": x.get("number") or x.get("bill_no"), "at": t.now()}}, upsert=True)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"accounting.last_sync": {"at": t.now(), "sent": sent, "failed": failed}}})
    return {"sent": sent, "failed": failed, "already": skipped}


@bp.post("/accounting/sync")
@api("finance")
def sync_now():
    money_only()
    d = request.get_json(force=True) or {}
    return jsonify(sync(d.get("from"), d.get("to")))


def status_counts():
    s = asettings()
    prov = s["provider"]
    by = {st: db.accounting_sync.count_documents({"company_id": g.cid, "provider": prov, "status": st}) for st in ("synced", "failed", "exported")}
    return {**by, "last_sync": s.get("last_sync")}


@bp.get("/accounting/log")
@api("finance", write=False)
def sync_log():
    money_only()
    q = {"provider": asettings()["provider"]}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify(serialize(t.find("accounting_sync", q, sort=[("at", -1)], limit=300)))


def check_accounting(now):
    """Daily automatic sync (once a day, after 02:00 UTC) when switched on."""
    s = asettings()
    if not s.get("auto_sync") or s["provider"] not in ("zoho", "quickbooks", "xero", "sandbox"):
        return
    last = (s.get("last_sync") or {}).get("at")
    if last and last.date() == now.date() or now.hour < 2:
        return
    try:
        sync()
    except Exception:  # noqa: BLE001 — a provider outage must not stop the other checks
        db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"accounting.last_sync": {"at": now, "sent": 0, "failed": -1}}})
