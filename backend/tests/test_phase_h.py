"""Phase H — procurement: requests, RFQs, purchase orders, receipts, vendor bills, vendor portal. One block per row of PLAN.md H1.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_h.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("API", "http://localhost:5000/api")
PW = "Demo@123"
RUN = str(int(time.time() * 1000))[-8:]
failures, passed = [], 0
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def fetch(path, token):
    """Status of a file download (binary, not JSON)."""
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name} -> {detail}")


def expect(name, res, status):
    check(name, res[0] == status, f"got {res[0]} {res[1].get('error', '') if isinstance(res[1], dict) else ''}")
    return res[1]


def login(email):
    s, d = call("POST", "/auth/login", {"email": email, "password": PW})
    assert s == 200, (email, s, d)
    return d["token"]


def upload(name, token, path="/uploads"):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + b"\x89PNG\r\n\x1a\n" + b"0" * 64 + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator")}
T["vendor"] = login("vendor@skyline.test")
T["client"] = login("client@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"document_folders": 1, "site_settings": 1})
projects, keys, contacts_made, rates_made = [], [], [], []
finance_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"finance": 1}).get("finance")
VENDOR_CONTACT = mongo.users.find_one({"email": "vendor@skyline.test"})["contact_id"]


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def up(name, who="pm"):
    f = upload(f"{name}{RUN}.png", T[who])
    keys.append(f["key"])
    return f["key"]


try:
    p = expect("project", call("POST", "/projects", {"name": f"PhaseH {RUN}", "services": ["construction"], "start": day(-10)}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    for who, role, acc in (("pm", "Project Manager", "edit"), ("site", "Site Supervisor", "view")):
        call("POST", f"/projects/{pid}/team", {"user_id": U[who], "project_role": role, "access": acc}, T["owner"])
    p2 = expect("a project the site is not on", call("POST", "/projects", {"name": f"PhaseH other {RUN}", "services": ["construction"], "start": day(0)}, T["owner"]), 201)
    projects.append(p2["id"])
    S1, S2 = p["stages"][1]["id"], p["stages"][2]["id"]
    call("PUT", f"/projects/{pid}/stages/{S1}", {"budget": 100000}, T["owner"])
    sup = {}
    for k, extra in (("A", {}), ("B", {}), ("C", {"compliance": [{"type": "insurance", "name": "Policy", "expiry": day(-5)}]})):
        c = expect(f"supplier {k}", call("POST", "/contacts", {"name": f"Supplier {k} {RUN}", "kind": "company", "types": ["supplier"],
                                                                "email": f"sup{k.lower()}{RUN}@example.test", "phone": f"9{k == 'A' and 1 or k == 'B' and 2 or 3}{RUN}", **extra}, T["owner"]), 201)
        sup[k] = c["id"]
        contacts_made.append(c["id"])
    plain = expect("not a supplier", call("POST", "/contacts", {"name": f"Friend {RUN}", "kind": "person", "types": ["client"], "phone": f"94{RUN}"}, T["owner"]), 201)
    contacts_made.append(plain["id"])
    rate = expect("rate item", call("POST", "/rates", {"kind": "material", "name": f"TMT steel {RUN}", "unit": "kg", "rate": 95}, T["owner"]), 201)
    rates_made.append(rate["id"])

    # ================= block 1 · purchase requests, RFQs, quotes =================
    expect("site on another project: 404", call("POST", f"/projects/{p2['id']}/purchase-requests", {"stage_id": p2["stages"][0]["id"], "lines": [{"description": "x", "qty": 1}]}, T["site"]), 404)
    expect("estimator (read only) cannot raise", call("POST", f"/projects/{pid}/purchase-requests", {"stage_id": S1, "lines": [{"description": "x", "qty": 1}]}, T["estimator"]), 403)
    expect("lines required", call("POST", f"/projects/{pid}/purchase-requests", {"stage_id": S1, "lines": []}, T["site"]), 400)
    pr = expect("site supervisor asks for steel", call("POST", f"/projects/{pid}/purchase-requests", {"stage_id": S1, "note": f"Columns {RUN}",
                                                                                                     "lines": [{"rate_id": rate["id"], "qty": 500, "needed_by": day(5)},
                                                                                                               {"description": "Binding wire", "qty": 20, "unit": "kg"}]}, T["site"]), 201)
    check("numbered PR, from the site, item from the rate library", pr["number"].startswith("PR") and pr["source"] == "site"
          and pr["lines"][0]["description"] == f"TMT steel {RUN}" and pr["lines"][0]["unit"] == "kg", pr)
    check("Procurement and the PM told", any(pr["number"] in n["text"] for n in bell("procurement", event="pr_raised"))
          and any(pr["number"] in n["text"] for n in bell("pm", event="pr_raised")))
    expect("RFQ needs suppliers of a supplier type", call("POST", "/rfqs", {"project_id": pid, "request_ids": [pr["id"]], "supplier_ids": [plain["id"]]}, T["procurement"]), 400)
    rfq = expect("RFQ to three suppliers", call("POST", "/rfqs", {"project_id": pid, "request_ids": [pr["id"]], "supplier_ids": [sup["A"], sup["B"], sup["C"]],
                                                                 "due_date": day(2)}, T["procurement"]), 201)
    check("expired compliance warns, does not block", next(s_ for s_ in rfq["suppliers"] if s_["contact_id"] == sup["C"])["warning"], rfq["suppliers"])
    check("request is being priced", mongo.purchase_requests.find_one({"_id": ObjectId(pr["id"])})["status"] == "quoting")
    sent = expect("send the RFQ", call("POST", f"/rfqs/{rfq['id']}/send", {}, T["procurement"]), 200)
    check("email result per supplier", all(s_["sent"] for s_ in sent["suppliers"]) and sent["status"] == "sent")
    L1, L2 = rfq["lines"][0]["id"], rfq["lines"][1]["id"]
    expect("a supplier not asked", call("POST", f"/rfqs/{rfq['id']}/quotes", {"supplier_id": plain["id"], "lines": [{"line_id": L1, "rate": 1}]}, T["procurement"]), 400)
    expect("a quote needs rates", call("POST", f"/rfqs/{rfq['id']}/quotes", {"supplier_id": sup["A"], "lines": []}, T["procurement"]), 400)
    call("POST", f"/rfqs/{rfq['id']}/quotes", {"supplier_id": sup["A"], "lines": [{"line_id": L1, "rate": 100}, {"line_id": L2, "rate": 80}], "tax_pct": 18, "delivery_days": 3}, T["procurement"])
    call("POST", f"/rfqs/{rfq['id']}/quotes", {"supplier_id": sup["B"], "lines": [{"line_id": L1, "rate": 92}, {"line_id": L2, "rate": 85}], "tax_pct": 18, "delivery_days": 9}, T["procurement"])
    cmp_ = expect("compare quotes", call("GET", f"/rfqs/{rfq['id']}/compare", token=T["procurement"]), 200)
    l1 = next(x for x in cmp_["lines"] if x["id"] == L1)
    check("side by side with the rate library", l1["library_rate"] == 95 and {o["supplier_id"]: o["lowest"] for o in l1["offers"]} == {sup["A"]: False, sup["B"]: True}, l1)
    lowest = next(x for x in cmp_["quotes"] if x["lowest"])
    check("lowest complete quote marked", lowest["supplier_id"] == sup["B"] and lowest["subtotal"] == 92 * 500 + 85 * 20, cmp_["quotes"])
    expect("dearer award needs a reason", call("POST", f"/rfqs/{rfq['id']}/award", {"supplier_id": sup["A"]}, T["procurement"]), 400)
    pos = expect("split award: steel from B, wire from A (each the lowest per line)", call("POST", f"/rfqs/{rfq['id']}/award", {
        "lines": [{"line_id": L1, "supplier_id": sup["B"]}, {"line_id": L2, "supplier_id": sup["A"]}]}, T["procurement"]), 201)
    check("one draft PO per supplier, no number yet", len(pos) == 2 and all(x["status"] == "draft" and x["number"] is None for x in pos), pos)
    poB = next(x for x in pos if x["vendor_id"] == sup["B"])
    poA = next(x for x in pos if x["vendor_id"] == sup["A"])
    check("PO carries the quoted rate and the stage", poB["lines"][0]["unit_cost"] == 92 and poB["lines"][0]["stage_id"] == S1 and poB["cost"] == 46000, poB)
    check("the request is ordered", mongo.purchase_requests.find_one({"_id": ObjectId(pr["id"])})["status"] == "ordered")
    expect("awarded once", call("POST", f"/rfqs/{rfq['id']}/award", {"supplier_id": sup["B"]}, T["procurement"]), 409)

    # ================= block 2 · purchase orders =================
    ok1 = expect("within the limit and budget: approved on submit", call("POST", f"/purchase-orders/{poB['id']}/submit", {}, T["procurement"]), 200)
    check("numbered on approval", ok1["status"] == "approved" and ok1["number"].startswith("PO"), ok1)
    row = next(r for r in call("GET", f"/projects/{pid}/costs", token=T["pm"])[1]["budget"]["stages"] if r["id"] == S1)
    check("the stage shows the order as ordered, not spent", row["ordered"] == 46000 and row["spent"] == 0, row)
    big = {"project_id": pid, "vendor_id": sup["C"], "lines": [{"description": f"Shuttering {RUN}", "qty": 1, "unit_cost": 60000, "stage_id": S2, "tax_pct": 0}]}
    d1 = expect("direct PO", call("POST", "/purchase-orders", big, T["procurement"]), 201)
    expect("a direct PO over the limit needs a reason", call("POST", f"/purchase-orders/{d1['id']}/submit", {}, T["procurement"]), 400)
    call("PUT", f"/purchase-orders/{d1['id']}", {"direct_reason": "Only local supplier"}, T["procurement"])
    w1 = expect("above the limit: waits", call("POST", f"/purchase-orders/{d1['id']}/submit", {}, T["procurement"]), 200)
    check("waiting for an Owner", w1["status"] == "waiting_approval" and w1["approval"]["needs"] == ["owner"] and w1["number"] is None, w1.get("approval"))
    check("Owners asked", any(f"Supplier C {RUN}" in n["text"] for n in bell("owner", event="po_approval")))
    expect("Procurement cannot approve above the limit", call("POST", f"/purchase-orders/{d1['id']}/approve", {}, T["procurement"]), 403)
    a1 = expect("Owner approves", call("POST", f"/purchase-orders/{d1['id']}/approve", {}, T["owner"]), 200)
    check("approved and numbered, raiser told", a1["status"] == "approved" and a1["number"] and any(a1["number"] in n["text"] for n in bell("procurement", event="po_decided")))
    over = {"project_id": pid, "vendor_id": sup["A"], "lines": [{"description": f"Cement {RUN}", "qty": 150, "unit_cost": 400, "stage_id": S1, "tax_pct": 0}],
            "direct_reason": "Urgent pour"}
    d2 = call("POST", "/purchase-orders", over, T["pm"])[1]
    w2 = expect("over the stage budget and the limit: waits", call("POST", f"/purchase-orders/{d2['id']}/submit", {}, T["pm"]), 200)
    check("46,000 already ordered + 60,000 = 6,000 over a 100,000 budget", sorted(w2["approval"]["needs"]) == ["budget", "owner"]
          and w2["approval"]["over_budget"][S1] == 6000, w2["approval"])
    check("the Owners asked (the PM raised it)", any(f"Supplier A {RUN}" in n["text"] and 'over the stage budget' in n['text'] for n in bell("owner", event="po_approval")))
    expect("reject needs a reason", call("POST", f"/purchase-orders/{d2['id']}/reject", {}, T["owner"]), 400)
    expect("approve over budget needs a reason", call("POST", f"/purchase-orders/{d2['id']}/approve", {}, T["owner"]), 400)
    a2 = expect("Owner approves over budget with a reason", call("POST", f"/purchase-orders/{d2['id']}/approve", {"overspend_reason": "price_rise"}, T["owner"]), 200)
    check("the reason is kept", (a2.get("approval") or {}).get("overspend_reason") == "price_rise", a2)
    row = next(r for r in call("GET", f"/projects/{pid}/costs", token=T["pm"])[1]["budget"]["stages"] if r["id"] == S1)
    check("ordered adds up: 46,000 + 60,000", row["ordered"] == 106000, row)

    sp = expect("send the PO", call("POST", f"/purchase-orders/{ok1['id']}/send", {"whatsapp": True}, T["procurement"]), 200)
    check("sent: email result kept, WhatsApp logged when not set up", sp["status"] == "sent" and sp["sent"]["email"], sp.get("sent"))
    expect("acknowledge: how", call("POST", f"/purchase-orders/{ok1['id']}/acknowledge", {"name": "Mr B"}, T["procurement"]), 400)
    ak = expect("supplier acknowledged by phone", call("POST", f"/purchase-orders/{ok1['id']}/acknowledge", {"name": "Mr B", "method": "Phone"}, T["procurement"]), 200)
    check("acknowledged", ak["status"] == "acknowledged" and ak["acknowledged"]["method"] == "Phone")
    expect("an approved PO is not edited", call("PUT", f"/purchase-orders/{ok1['id']}", {"terms": "x"}, T["procurement"]), 409)
    expect("an amendment needs a reason", call("POST", f"/purchase-orders/{ok1['id']}/amend", {"lines": ok1["lines"]}, T["procurement"]), 400)
    am = expect("amend: more steel", call("POST", f"/purchase-orders/{ok1['id']}/amend", {"reason": "Extra columns", "lines": [{**ok1["lines"][0], "qty": 550}]}, T["procurement"]), 200)
    check("an increase goes back for approval, keeps its number, revision 1", am["status"] == "draft" and am["number"] == ok1["number"] and am["revisions"][0]["rev"] == 1
          and am["revisions"][0]["new_total"] > am["revisions"][0]["old_total"], am)
    re_ = call("POST", f"/purchase-orders/{ok1['id']}/submit", {}, T["procurement"])[1]
    check("re-approved", re_["status"] in ("approved", "waiting_approval") and re_["number"] == ok1["number"], re_["status"])
    expect("cancel needs a reason", call("POST", f"/purchase-orders/{a1['id']}/cancel", {}, T["procurement"]), 400)
    expect("cancel (nothing received)", call("POST", f"/purchase-orders/{a1['id']}/cancel", {"reason": "Client dropped shuttering"}, T["procurement"]), 200)
    expect("a draft can be deleted", call("DELETE", f"/purchase-orders/{poA['id']}", token=T["procurement"]), 200)
    check("its request line is open again", next(ln for ln in mongo.purchase_requests.find_one({"_id": ObjectId(pr["id"])})["lines"] if ln["id"] == rfq["lines"][1]["pr_line_id"])["status"] == "open")
    sv = expect("site sees POs without prices", call("GET", f"/purchase-orders?project_id={pid}", token=T["site"]), 200)
    check("no money for the site", sv and all("unit_cost" not in ln and "cost" not in ln for x in sv for ln in x["lines"]) and all("total" not in x for x in sv), sv[:1])

    # selections are ordered through procurement
    intr = call("POST", f"/projects/{pid}/selections", {"stage_id": S1, "item": f"Door handles {RUN}", "options": [
        {"name": "Brass", "qty": 10, "unit_cost": 800, "unit_price": 1200, "supplier_id": sup["A"]}]}, T["pm"])[1]
    call("POST", f"/selections/{intr['id']}/send", {"email": False}, T["pm"])
    call("POST", f"/selections/{intr['id']}/choice", {"option_id": intr["options"][0]["id"], "name": "Client", "method": "Email"}, T["pm"])
    call("POST", f"/selections/{intr['id']}/status", {"status": "confirmed"}, T["pm"])
    od = expect("order the selection", call("POST", f"/selections/{intr['id']}/status", {"status": "ordered"}, T["pm"]), 200)
    spo = mongo.purchase_orders.find_one({"_id": ObjectId(od["po_id"])})
    check("a line on the supplier's draft PO, no cost", spo and spo["source"] == "selection" and spo["status"] == "draft"
          and spo["lines"][0]["selection_id"] == intr["id"] and spo["lines"][0]["cost"] == 8000
          and not mongo.costs.find_one({"company_id": CID, "selection_id": intr["id"]}), spo and spo["lines"])

    # ================= block 3 · goods received, bills, payments =================
    po = call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]
    if po["status"] == "waiting_approval":
        call("POST", f"/purchase-orders/{ok1['id']}/approve", {"overspend_reason": "client_change"}, T["owner"])
    call("POST", f"/purchase-orders/{ok1['id']}/send", {}, T["procurement"])
    po = call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]
    check("the steel order is open again after re-approval", po["status"] in ("sent", "acknowledged") and po["lines"][0]["qty"] == 550, po["status"])
    LN = po["lines"][0]["id"]
    expect("a rejection needs a reason", call("POST", f"/purchase-orders/{ok1['id']}/receipts", {"lines": [{"line_id": LN, "received": 300, "rejected": 10}]}, T["site"]), 400)
    k = up("challan")
    g1 = expect("the site supervisor records a delivery", call("POST", f"/purchase-orders/{ok1['id']}/receipts", {
        "lines": [{"line_id": LN, "received": 300, "rejected": 10, "reason": "Damaged"}], "challan": f"CH-{RUN}", "photos": [k]}, T["site"]), 201)
    check("numbered GRN, accepted = received - rejected", g1["number"].startswith("GRN") and g1["lines"][0]["accepted"] == 290, g1)
    check("Procurement told of the rejection", any(g1["number"] in n["text"] for n in bell("procurement", event="goods_rejected")))
    po = call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]
    check("part received", po["status"] == "part_received" and po["lines"][0]["accepted_qty"] == 290, po["status"])
    expect("more than ordered (+5%) refused", call("POST", f"/purchase-orders/{ok1['id']}/receipts", {"lines": [{"line_id": LN, "received": 300}]}, T["pm"]), 400)
    call("POST", f"/purchase-orders/{ok1['id']}/receipts", {"lines": [{"line_id": LN, "received": 260}]}, T["pm"])
    check("fully received", call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]["status"] == "received")
    expect("a return needs a reason", call("POST", f"/goods-receipts/{g1['id']}/return", {"lines": [{"line_id": LN, "qty": 20}]}, T["procurement"]), 400)
    expect("return 20 to the supplier", call("POST", f"/goods-receipts/{g1['id']}/return", {"lines": [{"line_id": LN, "qty": 20}], "reason": "Rusted"}, T["procurement"]), 200)
    po = call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]
    check("returned qty is no longer accepted: open again", po["lines"][0]["accepted_qty"] == 530 and po["status"] == "part_received", po["lines"][0])
    expect("site cannot enter bills", call("POST", "/vendor-bills", {"po_id": ok1["id"], "bill_no": "x", "lines": [{"line_id": LN, "qty": 1}]}, T["site"]), 403)
    spent0 = next(r for r in call("GET", f"/projects/{pid}/costs", token=T["pm"])[1]["budget"]["stages"] if r["id"] == S1)
    b1 = expect("a bill that matches", call("POST", "/vendor-bills", {"po_id": ok1["id"], "bill_no": f"B-{RUN}", "due_date": day(10),
                                                                      "lines": [{"line_id": LN, "qty": 530, "rate": 92}]}, T["procurement"]), 201)
    check("matched", b1["status"] == "matched" and b1["amount"] == 48760 and not b1["problems"], b1)
    expect("the same bill twice", call("POST", "/vendor-bills", {"po_id": ok1["id"], "bill_no": f"B-{RUN}", "lines": [{"line_id": LN, "qty": 1}]}, T["procurement"]), 409)
    ab = expect("approve the matched bill", call("POST", f"/vendor-bills/{b1['id']}/approve", {}, T["accounts"]), 200)
    c1 = mongo.costs.find_one({"company_id": CID, "bill_id": b1["id"]})
    check("the bill becomes an approved cost with the PO and bill on it", c1 and c1["status"] == "approved" and c1["po_id"] == ok1["id"]
          and c1["amount"] == 48760 and ab["cost_ids"] == [str(c1["_id"])], c1)
    row = next(r for r in call("GET", f"/projects/{pid}/costs", token=T["pm"])[1]["budget"]["stages"] if r["id"] == S1)
    check("spent up, ordered down by the same amount", row["spent"] == spent0["spent"] + 48760 and abs(row["ordered"] - (spent0["ordered"] - 48760)) < 0.02, (spent0, row))
    b2 = expect("billed more than received", call("POST", "/vendor-bills", {"po_id": ok1["id"], "bill_no": f"B2-{RUN}", "lines": [{"line_id": LN, "qty": 10}]}, T["procurement"]), 201)
    check("on hold, with the reason", b2["status"] == "on_hold" and "received and not billed 0" in b2["problems"][0], b2.get("problems"))
    check("Accounts told the bill is on hold", any(f"B2-{RUN}" in n["text"] for n in bell("accounts", event="bill_on_hold")))
    expect("only a matched bill is approved", call("POST", f"/vendor-bills/{b2['id']}/approve", {}, T["accounts"]), 409)
    expect("an override needs Owner / Accounts", call("POST", f"/vendor-bills/{b2['id']}/override", {"reason": "x"}, T["procurement"]), 403)
    expect("an override needs a reason", call("POST", f"/vendor-bills/{b2['id']}/override", {}, T["accounts"]), 400)
    ov = expect("Accounts accepts it anyway", call("POST", f"/vendor-bills/{b2['id']}/override", {"reason": "Loading charges agreed by phone"}, T["accounts"]), 200)
    c2 = mongo.costs.find_one({"company_id": CID, "bill_id": b2["id"]})
    check("an overridden bill's cost goes through cost approval", ov["status"] == "approved" and c2["status"] in ("submitted", "approved"), c2 and c2["status"])
    call("POST", f"/purchase-orders/{d2['id']}/send", {}, T["procurement"])
    CL = call("GET", f"/purchase-orders/{d2['id']}", token=T["procurement"])[1]["lines"][0]["id"]
    call("POST", f"/purchase-orders/{d2['id']}/receipts", {"lines": [{"line_id": CL, "received": 150}]}, T["pm"])
    b3 = call("POST", "/vendor-bills", {"po_id": d2["id"], "bill_no": f"B3-{RUN}", "lines": [{"line_id": CL, "qty": 150, "rate": 410}]}, T["procurement"])[1]
    check("rate above the 1% tolerance: on hold", b3["status"] == "on_hold" and "rate" in b3["problems"][0], b3.get("problems"))
    b4 = call("POST", "/vendor-bills", {"po_id": d2["id"], "bill_no": f"B4-{RUN}", "lines": [{"line_id": CL, "qty": 150, "rate": 400.5}]}, T["procurement"])[1]
    check("within both tolerances (rate 1%, total 100): matched", b4["status"] == "matched", b4.get("problems"))
    expect("void the mismatched one", call("POST", f"/vendor-bills/{b3['id']}/void", {"reason": "Supplier re-issued"}, T["accounts"]), 200)

    # payables and payments to the supplier (the money moves outside the CRM)
    pay = {"mode": "Bank transfer", "reference": f"UTR{RUN}", "amount": 20000, "allocations": [{"bill_id": b1["id"], "amount": 20000}]}
    expect("procurement cannot record payments", call("POST", "/vendor-payments", pay, T["procurement"]), 403)
    expect("not more than the bill", call("POST", "/vendor-payments", {**pay, "amount": 60000, "allocations": [{"bill_id": b1["id"], "amount": 60000}]}, T["accounts"]), 400)
    vp = expect("Accounts records a part payment", call("POST", "/vendor-payments", pay, T["accounts"]), 201)
    bb = next(x for x in call("GET", f"/vendor-bills?po_id={ok1['id']}", token=T["accounts"])[1] if x["id"] == b1["id"])
    check("part paid, balance left", bb["status"] == "part_paid" and bb["balance"] == round(b1["total"] - 20000, 2), bb)
    pa = expect("payables", call("GET", "/finance/payables", token=T["accounts"]), 200)
    check("payables list the supplier's balance", any(r["id"] == b1["id"] for r in pa["rows"]) and pa["total"] > 0)
    expect("a paid bill is not voided", call("POST", f"/vendor-bills/{b1['id']}/void", {"reason": "x"}, T["owner"]), 409)
    expect("void the payment", call("POST", f"/vendor-payments/{vp['id']}/void", {"reason": "Bounced"}, T["accounts"]), 200)
    expect("then the bill", call("POST", f"/vendor-bills/{b1['id']}/void", {"reason": f"Wrong GST {RUN}"}, T["owner"]), 200)
    check("voiding the bill voids its cost and the PO can be billed again", mongo.costs.find_one({"_id": c1["_id"]})["status"] == "void"
          and call("GET", f"/purchase-orders/{ok1['id']}", token=T["procurement"])[1]["lines"][0]["billed_qty"] == 10)

    # ================= block 4 · supplier portal, reminders, reports =================
    vpo = call("POST", "/purchase-orders", {"project_id": pid, "vendor_id": VENDOR_CONTACT, "expected_date": day(5),
                                            "lines": [{"description": f"Plywood {RUN}", "qty": 20, "unit": "sheet", "unit_cost": 1500, "stage_id": S2, "tax_pct": 18}]}, T["procurement"])[1]
    call("POST", f"/purchase-orders/{vpo['id']}/submit", {}, T["procurement"])
    call("POST", f"/purchase-orders/{vpo['id']}/send", {"email": False}, T["procurement"])
    vp_ = expect("supplier's purchase orders", call("GET", "/portal/purchase-orders", token=T["vendor"]), 200)
    mine = next((x for x in vp_["purchase_orders"] if x["id"] == vpo["id"]), None)
    check("their own PO with their prices", mine and mine["lines"][0]["rate"] == 1500 and mine["amount"] == 30000, mine)
    check("never our budget or other suppliers", "budget" not in json.dumps(vp_) and not any(x["id"] == d2["id"] for x in vp_["purchase_orders"]))
    expect("another supplier's PO: 404", call("POST", f"/portal/purchase-orders/{d2['id']}/acknowledge", {"name": "x"}, T["vendor"]), 404)
    expect("acknowledge: name", call("POST", f"/portal/purchase-orders/{vpo['id']}/acknowledge", {}, T["vendor"]), 400)
    expect("supplier acknowledges", call("POST", f"/portal/purchase-orders/{vpo['id']}/acknowledge", {"name": "Mr Vendor"}, T["vendor"]), 200)
    check("acknowledged in the portal", mongo.purchase_orders.find_one({"_id": ObjectId(vpo["id"])})["acknowledged"]["method"] == "Portal")
    expect("acknowledged once", call("POST", f"/portal/purchase-orders/{vpo['id']}/acknowledge", {"name": "x"}, T["vendor"]), 409)
    expect("no delivery date in the past", call("POST", f"/portal/purchase-orders/{vpo['id']}/delivery-date", {"date": day(-1)}, T["vendor"]), 400)
    expect("supplier moves the delivery later", call("POST", f"/portal/purchase-orders/{vpo['id']}/delivery-date", {"date": day(8), "note": f"Truck strike {RUN}"}, T["vendor"]), 200)
    check("Procurement and the PM told", any(f"Truck strike {RUN}" in n["text"] for n in bell("procurement", event="po_delivery_changed"))
          and any(f"Truck strike {RUN}" in n["text"] for n in bell("pm", event="po_delivery_changed")))
    rq = call("POST", f"/projects/{pid}/purchase-requests", {"stage_id": S2, "lines": [{"description": f"Laminate {RUN}", "qty": 10}]}, T["pm"])[1]
    rf = call("POST", "/rfqs", {"project_id": pid, "request_ids": [rq["id"]], "supplier_ids": [VENDOR_CONTACT, sup["A"]], "due_date": day(1)}, T["procurement"])[1]
    call("POST", f"/rfqs/{rf['id']}/send", {}, T["procurement"])
    pr_ = call("GET", "/portal/purchase-orders", token=T["vendor"])[1]
    prf = next((x for x in pr_["rfqs"] if x["id"] == rf["id"]), None)
    check("the RFQ is in the supplier's portal, without other quotes", prf and "quotes" not in prf and prf["my_quote"] is None, prf)
    expect("supplier quotes in the portal", call("POST", f"/portal/rfqs/{rf['id']}/quote", {"lines": [{"line_id": prf["lines"][0]["id"], "rate": 900}], "delivery_days": 4}, T["vendor"]), 200)
    check("the quote is on the RFQ", any(q["supplier_id"] == VENDOR_CONTACT and q["rates"][prf["lines"][0]["id"]] == 900 for q in mongo.rfqs.find_one({"_id": ObjectId(rf["id"])})["quotes"]))
    expect("an RFQ not sent to them: 404", call("POST", f"/portal/rfqs/{rfq['id']}/quote", {"lines": []}, T["vendor"]), 404)
    VL = mine["lines"][0]["id"]
    call("POST", f"/purchase-orders/{vpo['id']}/receipts", {"lines": [{"line_id": VL, "received": 20}]}, T["pm"])
    expect("an invoice needs the file", call("POST", f"/portal/purchase-orders/{vpo['id']}/invoice", {"bill_no": "V1", "lines": [{"line_id": VL, "qty": 20}]}, T["vendor"]), 400)
    try:
        upload(f"v{RUN}.png", T["vendor"])
        staff_only = False
    except urllib.error.HTTPError as e:
        staff_only = e.code == 403
    check("the staff upload route refuses a supplier", staff_only)
    try:
        upload(f"v{RUN}.mp4", T["vendor"], "/portal/uploads")
        no_video = False
    except urllib.error.HTTPError as e:
        no_video = e.code == 400
    check("portal uploads: PDF or image only", no_video)
    kf = upload(f"vinv{RUN}.png", T["vendor"], "/portal/uploads")["key"]
    keys.append(kf)
    vi = expect("supplier uploads the invoice", call("POST", f"/portal/purchase-orders/{vpo['id']}/invoice", {"bill_no": f"V-{RUN}", "file_key": kf,
                                                                                                           "lines": [{"line_id": VL, "qty": 20, "rate": 1500}]}, T["vendor"]), 201)
    vb = mongo.vendor_bills.find_one({"company_id": CID, "bill_no": f"V-{RUN}"})
    check("a draft bill for staff to check", vb and vb["status"] == "draft" and vb["source"] == "portal", vb and vb["status"])
    check("Procurement and Accounts told", any(f"V-{RUN}" in n["text"] for n in bell("accounts", event="vendor_invoice")))
    ck = expect("staff check it", call("POST", f"/vendor-bills/{vb['_id']}/check", {}, T["procurement"]), 200)
    check("matched after checking", ck["status"] == "matched", ck.get("problems"))
    call("POST", f"/vendor-bills/{vb['_id']}/approve", {}, T["accounts"])
    pb = call("GET", "/portal/purchase-orders", token=T["vendor"])[1]["bills"]
    check("the supplier sees their bill's status", any(b["bill_no"] == f"V-{RUN}" and b["status"] == "approved" for b in pb), pb)

    lp = call("POST", "/purchase-orders", {"project_id": pid, "vendor_id": sup["A"], "expected_date": day(2),
                                           "lines": [{"description": f"Sand {RUN}", "qty": 2, "unit_cost": 1000, "stage_id": S2, "tax_pct": 0}]}, T["procurement"])[1]
    call("POST", f"/purchase-orders/{lp['id']}/submit", {}, T["procurement"])
    call("POST", f"/purchase-orders/{lp['id']}/send", {"email": False}, T["procurement"])
    lp = call("GET", f"/purchase-orders/{lp['id']}", token=T["procurement"])[1]
    mongo.purchase_orders.update_one({"_id": ObjectId(lp["id"])}, {"$set": {"expected_date": day(-4)}})
    worker()
    worker()
    late = [n for n in bell("procurement", event="delivery_due") if "Delivery late" in n["text"] and lp["number"] in n["text"]]
    check("late delivery: Procurement reminded once", len(late) == 1, [n["text"] for n in late])
    check("3+ days late: Owners told", any("days late" in n["text"] and f"Supplier A {RUN}" in n["text"] for n in bell("owner", event="delivery_due")))
    rp = expect("procurement report", call("GET", "/reports/procurement", token=T["owner"]), 200)
    check("spend by supplier, PO status, price variance, late list", rp["money_view"] and any(x["vendor"] == "Vendor / Supplier Co." for x in rp["spend"])
          and rp["po_status"] and any(x["vendor"] == f"Supplier A {RUN}" for x in rp["late"]), list(rp))
    rs = expect("site sees the report without money", call("GET", "/reports/procurement", token=T["site"]), 200)
    check("no money for the site", not rs["money_view"] and "spend" not in rs and all("value" not in x for x in rs["po_status"]))
    sr = call("POST", f"/projects/{pid}/site-reports", {"weather": {"kind": "Clear"}}, T["site"])
    lst = call("GET", f"/projects/{pid}/site-reports", token=T["site"])[1]
    today_rep = next((r for r in lst["reports"] if r["date"] == day(0)), None)
    check("today's site report lists today's deliveries", today_rep and any(x["number"] == g1["number"] for x in today_rep["deliveries"]), today_rep and today_rep.get("deliveries"))
finally:
    for p_ in projects:
        mongo.costs.update_many({"company_id": CID, "project_id": p_}, {"$set": {"status": "void"}})
        for coll in ("purchase_orders", "purchase_requests", "rfqs", "goods_receipts", "vendor_bills", "vendor_payments", "invoices", "receipts", "site_reports"):
            mongo[coll].delete_many({"company_id": CID, "project_id": p_})
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    mongo.vendor_bills.delete_many({"company_id": CID, "vendor_id": {"$in": contacts_made + [VENDOR_CONTACT]}, "bill_no": {"$regex": RUN}})
    mongo.vendor_payments.delete_many({"company_id": CID, "vendor_id": {"$in": contacts_made}})
    for c_ in contacts_made:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    for r_ in rates_made:
        mongo.rate_library.delete_one({"_id": ObjectId(r_)})
    for k in keys:
        mongo.files.delete_one({"key": k})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"finance": finance_before}} if finance_before else {"$unset": {"finance": ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + mongo.purchase_orders.count_documents({"company_id": CID, "project_id": {"$in": projects}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
