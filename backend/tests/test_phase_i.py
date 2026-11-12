"""Phase I â€” closing the gaps in the built modules. One section per block of PLAN.md Phase I.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_i.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("API", "http://localhost:5000/api")
PW = "Demo@123"
RUN = str(int(time.time() * 1000))[-8:]
SIG = "data:image/png;base64," + "iVBORw0KGgo" * 40
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


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name} -> {detail}")


def expect(name, res, status=200):
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


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator")}
T["client"] = login("client@skyline.test")
T["vendor"] = login("vendor@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"finance": 1, "tax_mode": 1, "state": 1, "gstin": 1, "warehouses": 1, "markup_rules": 1})
projects, leads, contacts_made, keys = [], [], [], []

try:
    # ======================================= block 1 =======================================
    # --- stage budgets from the accepted estimate ---
    tpl = next(x for x in call("GET", "/stage_templates", token=T["owner"])[1]["templates"] if x["service"] == "construction" and x.get("is_default"))
    ST = [s["name"] for s in tpl["stages"]]
    lead = expect("lead", call("POST", "/leads", {"title": f"PhaseI villa {RUN}", "service": "construction", "source": "Walk-in",
                                                   "contact_name": f"Ira Client {RUN}", "contact_phone": f"6{RUN[-7:]}21",
                                                   "contact_email": f"ira{RUN}@x.test"}, T["sales"]), 201)
    assert "id" in lead, lead
    LID = lead["id"]
    leads.append(LID)
    contacts_made.append(lead["contact_id"])
    est = expect("estimate", call("POST", f"/leads/{LID}/estimates", {}, T["estimator"]), 201)
    expect("estimate lines tagged to stages", call("PUT", f"/estimates/{est['id']}", {"lines": [
        {"description": "Footings", "qty": 10, "unit": "cum", "material_rate": 5000, "labour_rate": 1000, "stage": ST[1]},  # 60,000
        {"description": "Frame", "qty": 20, "unit": "cum", "material_rate": 5000, "labour_rate": 1000, "stage": ST[2]},     # 120,000
        {"description": "Misc", "qty": 1, "unit": "lot", "material_rate": 18000, "labour_rate": 0}],                       # 18,000 untagged
        "overhead_pct": 10, "markup_pct": 20, "discount_pct": 0, "tax_pct": 18}, T["estimator"]))
    es = call("POST", f"/estimates/{est['id']}/submit", {}, T["owner"])
    if es[1].get("status") != "approved":
        es = call("POST", f"/estimates/{est['id']}/decide", {"approve": True}, T["owner"])
    check("estimate approved", es[1].get("status") == "approved", es)
    e_saved = mongo.estimates.find_one({"_id": ObjectId(est["id"])})
    check("estimate line keeps its stage", e_saved["lines"][0].get("stage") == ST[1], e_saved["lines"][0])
    pr = expect("proposal from the estimate", call("POST", f"/leads/{LID}/proposals", {"estimate_id": est["id"], "valid_until": day(20)}, T["sales"]), 201)
    expect("schedule", call("PUT", f"/proposals/{pr['id']}", {"payment_schedule": [{"name": "Advance", "pct": 100, "trigger": "signing"}]}, T["sales"]))
    sent = expect("send", call("POST", f"/proposals/{pr['id']}/send", {"channel": "email"}, T["sales"]))
    tok = (sent.get("link") or "").split("/p/")[-1]
    expect("client signs", call("POST", f"/public/proposals/{tok}/accept", {"agree": True, "name": "Ira", "signature": SIG}))
    won = expect("won", call("POST", f"/leads/{LID}/win", {"pm_id": U["pm"], "start": day(-5)}, T["sales"]))
    PID = won["project_id"]
    projects.append(PID)
    p = call("GET", f"/projects/{PID}", token=T["owner"])[1]
    b = {s["name"]: s.get("budget", 0) for s in p["stages"]}
    # cost incl. 10% overheads: 66,000 / 132,000; untagged 19,800 spread 1:2 -> +6,600 / +13,200
    check("I1.1 tagged stage budget from the estimate cost", abs(b[ST[1]] - 72600) < 1, b)
    check("I1.1 second stage", abs(b[ST[2]] - 145200) < 1, b)
    check("I1.1 untagged stages stay 0", b[ST[0]] == 0 and b[ST[3]] == 0, b)
    check("I1.1 budgets total the estimate cost", abs(sum(b.values()) - 217800) < 1, sum(b.values()))
    for who, role, acc in (("site", "Site Supervisor", "view"), ("accounts", "Accounts", "view")):
        call("POST", f"/projects/{PID}/team", {"user_id": U[who], "project_role": role, "access": acc}, T["owner"])
    plan = expect("I1.1 PM sees the budget plan", call("GET", f"/projects/{PID}/budget-from-estimate", token=T["pm"]))
    check("I1.1 plan names the estimate", plan.get("estimate_number") and plan["tagged"], plan)
    expect("I1.1 site cannot see the plan", call("GET", f"/projects/{PID}/budget-from-estimate", token=T["site"]), 403)
    stages = mongo.projects.find_one({"_id": ObjectId(PID)})["stages"]
    stages[1]["budget"] = 1
    mongo.projects.update_one({"_id": ObjectId(PID)}, {"$set": {"stages": stages}})
    r = expect("I1.1 re-apply one stage", call("POST", f"/projects/{PID}/budget-from-estimate", {"stage_ids": [stages[1]["id"]]}, T["pm"]))
    check("I1.1 re-applied", r["updated"] == 1 and abs(mongo.projects.find_one({"_id": ObjectId(PID)})["stages"][1]["budget"] - 72600) < 1, r)
    np_ = expect("project without a lead", call("POST", "/projects", {"name": f"PhaseI bare {RUN}", "services": ["construction"], "start": day(0)}, T["owner"]), 201)
    projects.append(np_["id"])
    check("I1.1 no estimate -> null plan", call("GET", f"/projects/{np_['id']}/budget-from-estimate", token=T["owner"])[1] is None)
    expect("I1.1 no estimate -> apply refused", call("POST", f"/projects/{np_['id']}/budget-from-estimate", {}, T["owner"]), 409)

    # --- GST split ---
    CLIENT = lead["contact_id"]
    expect("I1.2 GST needs a state", call("PUT", "/company/setup", {"tax_mode": "gst", "state": None, "gstin": None}, T["owner"]), 400)
    expect("I1.2 bad state", call("PUT", "/company/setup", {"state": "Atlantis"}, T["owner"]), 400)
    expect("I1.2 bad GSTIN", call("PUT", "/company/setup", {"gstin": "123"}, T["owner"]), 400)
    expect("I1.2 GST on, Maharashtra", call("PUT", "/company/setup", {"tax_mode": "gst", "state": "Maharashtra"}, T["owner"]))
    expect("client in Karnataka", call("PUT", f"/contacts/{CLIENT}", {"state": "Karnataka"}, T["owner"]))
    expect("I1.2 bad HSN", call("POST", f"/projects/{PID}/invoices", {"lines": [{"description": "x", "qty": 1, "rate": 100, "hsn": "12"}]}, T["accounts"]), 400)
    inv = expect("I1.2 manual invoice", call("POST", f"/projects/{PID}/invoices", {"lines": [
        {"description": "Extra work", "qty": 1, "rate": 10000, "tax_pct": 18, "hsn": "995411"}]}, T["accounts"]), 201)
    check("I1.2 other state -> IGST", inv["gst"] and inv["gst"]["mode"] == "inter" and inv["gst"]["igst"] == 1800 and inv["gst"]["cgst"] == 0, inv.get("gst"))
    check("I1.2 place of supply named", inv["gst"]["place_of_supply"] == "29-Karnataka", inv["gst"])
    check("I1.2 HSN kept on the line", inv["lines"][0]["hsn"] == "995411", inv["lines"][0])
    call("DELETE", f"/invoices/{inv['id']}", token=T["accounts"])
    expect("client in Maharashtra", call("PUT", f"/contacts/{CLIENT}", {"state": "Maharashtra"}, T["owner"]))
    inv = expect("I1.2 intra-state invoice", call("POST", f"/projects/{PID}/invoices", {"lines": [
        {"description": "Extra work", "qty": 1, "rate": 10001, "tax_pct": 18}]}, T["accounts"]), 201)
    g_ = inv["gst"]
    check("I1.2 same state -> CGST + SGST", g_["mode"] == "intra" and g_["igst"] == 0 and abs(g_["cgst"] + g_["sgst"] - inv["tax"]) < 0.001, g_)
    s_inv = expect("I1.2 send", call("POST", f"/invoices/{inv['id']}/send", {}, T["accounts"]))
    check("I1.2 GST stored on issue", mongo.invoices.find_one({"_id": ObjectId(inv["id"])}).get("gst", {}).get("mode") == "intra")
    expect("client moves to Karnataka", call("PUT", f"/contacts/{CLIENT}", {"state": "Karnataka"}, T["owner"]))
    check("I1.2 issued invoice keeps its split", call("GET", f"/invoices/{inv['id']}", token=T["accounts"])[1]["gst"]["mode"] == "intra")
    cn = expect("I1.2 credit note", call("POST", f"/invoices/{inv['id']}/credit-note", {"amount": 1180.12, "reason": "discount"}, T["accounts"]), 201)
    check("I1.2 credit note follows the invoice's place of supply", cn.get("gst") and cn["gst"]["mode"] == "intra" and cn["gst"]["cgst"] > 0, cn.get("gst"))
    gs = expect("I1.2 GST summary", call("GET", f"/finance/gst?month={date.today().isoformat()[:7]}", token=T["accounts"]))
    mine = [x for x in gs["rows"] if x["id"] in (inv["id"], cn["id"])]
    check("I1.2 summary lists the invoice and the credit note", len(mine) == 2 and any(x["taxable"] < 0 for x in mine), mine)
    check("I1.2 summary per HSN", any(h["hsn"] for h in gs["by_hsn"]), gs["by_hsn"])
    expect("I1.2 PM cannot see the GST summary", call("GET", "/finance/gst", token=T["pm"]), 403)
    expect("I1.2 bad month", call("GET", "/finance/gst?month=2026-1", token=T["owner"]), 400)

    # --- receipts on account ---
    def sent_invoice(rate):
        i = expect("invoice", call("POST", f"/projects/{PID}/invoices", {"lines": [{"description": f"Work {rate}", "qty": 1, "rate": rate, "tax_pct": 0}]}, T["accounts"]), 201)
        return expect("send", call("POST", f"/invoices/{i['id']}/send", {}, T["accounts"]))

    i1, i2 = sent_invoice(1000), sent_invoice(300)
    expect("I1.3 part allocation without on-account refused", call("POST", f"/projects/{PID}/receipts", {
        "amount": 1500, "mode": "Cash", "date": day(0), "allocations": [{"invoice_id": i1["id"], "amount": 1000}]}, T["accounts"]), 400)
    expect("I1.3 over-allocation refused", call("POST", f"/projects/{PID}/receipts", {
        "amount": 500, "mode": "Cash", "date": day(0), "on_account": True, "allocations": [{"invoice_id": i1["id"], "amount": 1000}]}, T["accounts"]), 400)
    rc = expect("I1.3 receipt with the rest on account", call("POST", f"/projects/{PID}/receipts", {
        "amount": 1500, "mode": "Cash", "date": day(0), "on_account": True, "allocations": [{"invoice_id": i1["id"], "amount": 1000}]}, T["accounts"]), 201)
    check("I1.3 500 on account", rc["unallocated"] == 500, rc)
    only = expect("I1.3 all on account", call("POST", f"/projects/{PID}/receipts", {"amount": 50, "mode": "Cash", "date": day(0), "on_account": True}, T["accounts"]), 201)
    check("I1.3 nothing allocated", only["unallocated"] == 50 and only["allocations"] == [], only)
    expect("I1.3 apply more than the invoice owes", call("POST", f"/receipts/{rc['id']}/apply", {"invoice_id": i2["id"], "amount": 400}, T["accounts"]), 400)
    a = expect("I1.3 apply to the second invoice", call("POST", f"/receipts/{rc['id']}/apply", {"invoice_id": i2["id"]}, T["accounts"]))
    check("I1.3 200 left on account", a["unallocated"] == 200, a)
    check("I1.3 second invoice paid", mongo.invoices.find_one({"_id": ObjectId(i2["id"])})["status"] == "paid")
    expect("I1.3 designer (finance read only) cannot apply", call("POST", f"/receipts/{rc['id']}/apply", {"invoice_id": i2["id"]}, T["designer"]), 403)
    expect("I1.3 void the receipt", call("POST", f"/receipts/{rc['id']}/void", {"reason": "bounced"}, T["accounts"]))
    st = [mongo.invoices.find_one({"_id": ObjectId(x["id"])}) for x in (i1, i2)]
    check("I1.3 void takes back every part", all(x["status"] == "sent" and x["paid"] == 0 for x in st), [(x["status"], x["paid"]) for x in st])
    expect("I1.3 nothing on account after void", call("POST", f"/receipts/{rc['id']}/apply", {"invoice_id": i1["id"]}, T["accounts"]), 409)

    # --- client reminder series ---
    expect("I1.4 bad reminder days", call("PUT", "/finance/settings", {"client_reminder_days": [1, 200]}, T["owner"]), 400)
    expect("I1.4 reminder days", call("PUT", "/finance/settings", {"client_reminder_days": [-3, 0, 1, 7, 14]}, T["owner"]))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for off, suffix in ((-3, ":-3"), (0, ":0"), (1, ""), (14, ":14")):
        due = (now.date() - timedelta(days=off)).isoformat()
        mongo.invoices.update_one({"_id": ObjectId(i1["id"])}, {"$set": {"due_date": due}})
        worker(now)
        r_ = mongo.reminders.find_one({"company_id": CID, "key": f"client-inv:{i1['id']}:{due}{suffix}"})
        check(f"I1.4 client reminded at {off:+d} days", r_ is not None, off)
    worker(now)
    check("I1.4 not twice", mongo.reminders.count_documents({"company_id": CID, "key": {"$regex": f"^client-inv:{i1['id']}"}}) == 4)

    # --- petty cash ---
    expect("I1.5 PM cannot give petty cash", call("POST", "/finance/petty-cash", {"kind": "advance", "holder_id": U["site"], "amount": 3000}, T["pm"]), 403)
    expect("I1.5 holder must be staff", call("POST", "/finance/petty-cash", {"kind": "advance", "holder_id": str(ObjectId()), "amount": 3000}, T["accounts"]), 400)
    adv = expect("I1.5 accounts gives the site 3000", call("POST", "/finance/petty-cash", {"kind": "advance", "holder_id": U["site"], "amount": 3000, "date": day(0)}, T["accounts"]), 201)
    pc = expect("I1.5 site sees own float", call("GET", "/finance/petty-cash", token=T["site"]))
    check("I1.5 balance 3000", pc["mine"] and pc["mine"]["balance"] >= 3000, pc.get("mine"))
    base = pc["mine"]["balance"]
    S1 = p["stages"][1]["id"]
    c1 = expect("I1.5 site expense from the float", call("POST", f"/projects/{PID}/costs", {"stage_id": S1, "description": "Tea and nails", "amount": 1000,
                                                                                             "date": day(0), "paid_from_float": True}, T["site"]), 201)
    check("I1.5 balance down", call("GET", "/finance/petty-cash", token=T["site"])[1]["mine"]["balance"] == base - 1000)
    expect("I1.5 more than the float refused", call("POST", f"/projects/{PID}/costs", {"stage_id": S1, "description": "Big", "amount": base,
                                                                                       "date": day(0), "paid_from_float": True}, T["site"]), 400)
    expect("I1.5 return more than held refused", call("POST", "/finance/petty-cash", {"kind": "return", "holder_id": U["site"], "amount": 99999}, T["accounts"]), 400)
    expect("I1.5 return 500", call("POST", "/finance/petty-cash", {"kind": "return", "holder_id": U["site"], "amount": 500}, T["accounts"]), 201)
    check("I1.5 balance after return", call("GET", "/finance/petty-cash", token=T["site"])[1]["mine"]["balance"] == base - 1500)
    check("I1.5 PM sees no float of others", call("GET", "/finance/petty-cash", token=T["pm"])[1]["holders"] == [])
    allrows = call("GET", "/finance/petty-cash", token=T["owner"])[1]
    check("I1.5 owner sees the site's float", any(h["holder_id"] == U["site"] for h in allrows["holders"]), allrows["holders"])
    expect("I1.5 PM rejects the expense", call("POST", f"/costs/{c1['id']}/reject", {"reason": "no bill"}, T["pm"]))
    check("I1.5 rejected expense gives the cash back", call("GET", "/finance/petty-cash", token=T["site"])[1]["mine"]["balance"] == base - 500)
    expect("I1.5 void the advance needs a reason", call("POST", f"/petty-cash/{adv['id']}/void", {}, T["accounts"]), 400)

    # ======================================= block 2 =======================================
    CON = mongo.contracts.find_one({"company_id": CID, "project_id": PID})
    CONID, CVAL = str(CON["_id"]), CON["value"]
    bl = expect("I2.1 billing terms", call("GET", f"/contracts/{CONID}/billing", token=T["accounts"]))
    check("I2.1 schedule basis by default", bl["basis"] == "schedule" and bl["retention_pct"] == 0, bl)
    expect("I2.1 retention over 20% refused", call("PUT", f"/contracts/{CONID}/billing", {"retention_pct": 25}, T["accounts"]), 400)
    expect("I2.1 designer cannot change billing", call("PUT", f"/contracts/{CONID}/billing", {"retention_pct": 5}, T["designer"]), 403)
    bl = expect("I2.1 progress basis, 5% retention", call("PUT", f"/contracts/{CONID}/billing", {"basis": "progress", "retention_pct": 5, "defects_days": 365}, T["accounts"]))
    check("I2.1 values cover the contract", abs(sum(v["value"] for v in bl["values"]) - CVAL) < 0.05, (sum(v["value"] for v in bl["values"]), CVAL))
    row = CON["payment_schedule"][0]
    expect("I2.1 schedule row refused on a progress contract", call("POST", f"/contracts/{CONID}/schedule/{row['id']}/invoice", {}, T["accounts"]), 409)
    sov = expect("I2.2 schedule of values", call("GET", f"/contracts/{CONID}/claims", token=T["accounts"]))["values"]
    v1 = next(v for v in sov if v["value"] > 0)
    expect("I2.2 bad %", call("POST", f"/contracts/{CONID}/claims", {"lines": [{"stage_id": v1["stage_id"], "pct": 120}]}, T["accounts"]), 400)
    expect("I2.2 nothing claimed", call("POST", f"/contracts/{CONID}/claims", {"lines": []}, T["accounts"]), 400)
    c1 = expect("I2.2 claim 40%", call("POST", f"/contracts/{CONID}/claims", {"lines": [{"stage_id": v1["stage_id"], "pct": 40}]}, T["accounts"]), 201)
    check("I2.2 claim bills 40% of the stage value", abs(c1["total"] - v1["value"] * 0.4) < 0.05, (c1["total"], v1["value"]))
    check("I2.2 5% retention held", abs(c1["retention"] - c1["total"] * 0.05) < 0.02 and abs(c1["balance"] - (c1["total"] - c1["retention"])) < 0.02, c1)
    expect("I2.2 one draft claim at a time", call("POST", f"/contracts/{CONID}/claims", {"lines": [{"stage_id": v1["stage_id"], "pct": 50}]}, T["accounts"]), 409)
    expect("I2.2 send claim 1", call("POST", f"/invoices/{c1['id']}/send", {}, T["accounts"]))
    expect("I2.2 a claim is cumulative", call("POST", f"/contracts/{CONID}/claims", {"lines": [{"stage_id": v1["stage_id"], "pct": 30}]}, T["accounts"]), 400)
    c2 = expect("I2.2 claim 60%", call("POST", f"/contracts/{CONID}/claims", {"lines": [{"stage_id": v1["stage_id"], "pct": 60}]}, T["accounts"]), 201)
    check("I2.2 second claim bills the increase", abs(c2["total"] - v1["value"] * 0.2) < 0.05 and c2["claim"][0]["from_pct"] == 40, c2.get("claim"))
    expect("I2.2 basis fixed once invoiced", call("PUT", f"/contracts/{CONID}/billing", {"basis": "schedule"}, T["accounts"]), 409)
    expect("I2.2 retention fixed once invoiced", call("PUT", f"/contracts/{CONID}/billing", {"retention_pct": 10}, T["accounts"]), 409)
    pay = round(c1["total"] - c1["retention"], 2)
    expect("I2.3 client pays the claim less retention", call("POST", f"/projects/{PID}/receipts", {"amount": pay, "mode": "Cash", "date": day(0),
                                                                                                "allocations": [{"invoice_id": c1["id"], "amount": pay}]}, T["accounts"]), 201)
    check("I2.3 claim paid though retention is held", mongo.invoices.find_one({"_id": ObjectId(c1["id"])})["status"] == "paid")
    bl = expect("billing", call("GET", f"/contracts/{CONID}/billing", token=T["accounts"]))
    check("I2.3 retention held = claim 1's", abs(bl["retention"]["balance"] - c1["retention"]) < 0.02, bl["retention"])
    fin = call("GET", f"/projects/{PID}/finance", token=T["accounts"])[1]
    check("I2.3 project money shows retention held", abs(fin["retention_held"] - c1["retention"]) < 0.02, fin.get("retention_held"))
    expect("I2.4 release more than held", call("POST", f"/contracts/{CONID}/retention/release", {"amount": c1["retention"] + 100}, T["accounts"]), 400)
    rel = expect("I2.4 release half", call("POST", f"/contracts/{CONID}/retention/release", {"pct": 50}, T["accounts"]), 201)
    check("I2.4 release invoice without new tax", rel["kind"] == "retention" and rel["tax"] == 0 and abs(rel["total"] - c1["retention"] / 2) < 0.02, rel)
    bl = call("GET", f"/contracts/{CONID}/billing", token=T["accounts"])[1]
    check("I2.4 draft release reserves the amount", abs(bl["retention"]["balance"] - c1["retention"] / 2) < 0.02, bl["retention"])
    expect("I2.4 send the release", call("POST", f"/invoices/{rel['id']}/send", {}, T["accounts"]))
    gs = call("GET", f"/finance/gst?month={date.today().isoformat()[:7]}", token=T["accounts"])[1]
    check("I2.4 release is not in the GST summary", not any(x["id"] == rel["id"] for x in gs["rows"]))
    expect("I2.5 defects period ends today", call("PUT", f"/contracts/{CONID}/billing", {"defects_days": 0, "handover_date": day(0)}, T["accounts"]))
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    key = f"retention:{CONID}:{day(0)}"
    check("I2.5 Accounts told to release retention", mongo.notifications.count_documents({"company_id": CID, "key": key, "user_id": U["accounts"]}) == 1)
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    check("I2.5 once", mongo.notifications.count_documents({"company_id": CID, "key": key, "user_id": U["accounts"]}) == 1)

    # --- deposits for selections ---
    sel = expect("selection", call("POST", f"/projects/{PID}/selections", {"stage_id": p["stages"][3]["id"], "item": f"Sofa {RUN}", "room": "Living",
                                                                          "allowance": 40000, "options": [{"name": "Grey sofa", "qty": 1, "unit_cost": 30000, "unit_price": 50000}]}, T["owner"]), 201)
    expect("I2.6 deposit before a choice refused", call("POST", f"/selections/{sel['id']}/deposit", {}, T["accounts"]), 409)
    expect("choice", call("POST", f"/selections/{sel['id']}/choice", {"option_id": sel["options"][0]["id"], "method": "In person", "name": "Ira"}, T["owner"]))
    dep = expect("I2.6 deposit invoice (50% by default)", call("POST", f"/selections/{sel['id']}/deposit", {}, T["accounts"]), 201)
    check("I2.6 deposit = 50% of the price + tax", dep["kind"] == "deposit" and dep["subtotal"] == 25000, dep)
    expect("I2.6 one deposit per item", call("POST", f"/selections/{sel['id']}/deposit", {}, T["accounts"]), 409)
    check("I2.6 selection shows the deposit", call("GET", f"/projects/{PID}/selections", token=T["owner"])[1]["selections"][0].get("deposit"))
    expect("I2.6 require deposits", call("PUT", "/finance/settings", {"require_selection_deposit": True}, T["owner"]))
    expect("confirm", call("POST", f"/selections/{sel['id']}/status", {"status": "confirmed"}, T["owner"]))
    expect("I2.6 ordering refused until the deposit is paid", call("POST", f"/selections/{sel['id']}/status", {"status": "ordered"}, T["owner"]), 409)
    expect("I2.6 send deposit", call("POST", f"/invoices/{dep['id']}/send", {}, T["accounts"]))
    expect("I2.6 pay deposit", call("POST", f"/projects/{PID}/receipts", {"amount": dep["total"], "mode": "Cash", "date": day(0),
                                                                        "allocations": [{"invoice_id": dep["id"], "amount": dep["total"]}]}, T["accounts"]), 201)
    o = expect("I2.6 ordered once the deposit is paid", call("POST", f"/selections/{sel['id']}/status", {"status": "ordered"}, T["owner"]))
    check("I2.6 no warning flag", not o.get("ordered_without_deposit"), o)
    SEL = sel["id"]

    # ======================================= block 3 =======================================
    VENDOR = mongo.users.find_one({"email": "vendor@skyline.test"})["contact_id"]
    S2 = p["stages"][2]["id"]
    # --- photos with time, place, stage, room ---
    k1 = upload(f"site{RUN}.png", T["site"])["key"]
    keys.append(k1)
    sr = expect("site report", call("POST", f"/projects/{PID}/site-reports", {"date": day(0), "photos": [
        {"key": k1, "caption": "Slab", "lat": 18.5204, "lng": 73.8567, "accuracy_m": 12, "taken_at": "2026-11-12T09:30:00+05:30",
         "stage_id": S2, "room": "Living"}]}, T["site"]), 201)
    ph = sr["photos"][0]
    check("I3.1 photo keeps place, time, stage and room", ph["lat"] == 18.5204 and ph["taken_at"].startswith("2026-11-12T09:30")
          and ph["stage_name"] == p["stages"][2]["name"] and ph["room"] == "Living", ph)
    expect("I3.1 bad location refused", call("PUT", f"/site-reports/{sr['id']}", {"photos": [{"key": k1, "lat": 99, "lng": 10}]}, T["site"]), 400)
    again = expect("I3.1 edit keeps the first place", call("PUT", f"/site-reports/{sr['id']}", {"photos": [{"key": k1, "lat": 1, "lng": 1, "caption": "x"}]}, T["site"]))
    check("I3.1 place not overwritten", again["photos"][0]["lat"] == 18.5204, again["photos"][0])

    # --- stock: receiving location, consumption, transfer ---
    expect("I3.2 warehouses", call("PUT", "/settings/warehouses", {"warehouses": [{"name": f"Main store {RUN}", "address": "Hadapsar"}]}, T["owner"]))
    WH = call("GET", "/settings/warehouses", token=T["procurement"])[1][0]["id"]
    po = expect("PO", call("POST", "/purchase-orders", {"project_id": PID, "vendor_id": VENDOR, "expected_date": day(3),
                                                        "lines": [{"description": f"Cement {RUN}", "qty": 100, "unit": "bag", "unit_cost": 300, "stage_id": S2, "tax_pct": 0},
                                                                  {"description": f"Steel {RUN}", "qty": 10, "unit": "bundle", "unit_cost": 1500, "stage_id": S2, "tax_pct": 0}],
                                                        "direct_reason": "urgent"}, T["procurement"]), 201)
    sub = call("POST", f"/purchase-orders/{po['id']}/submit", {}, T["procurement"])
    check("PO approved on submit", sub[1].get("status") == "approved", sub)
    expect("send PO", call("POST", f"/purchase-orders/{po['id']}/send", {"email": False}, T["procurement"]))
    pol = call("GET", f"/purchase-orders/{po['id']}", token=T["procurement"])[1]["lines"]
    expect("I3.2 bad receiving location", call("POST", f"/purchase-orders/{po['id']}/receipts", {"location": "nowhere", "lines": [
        {"line_id": pol[0]["id"], "received": 60}]}, T["site"]), 400)
    expect("I3.2 cement received at site", call("POST", f"/purchase-orders/{po['id']}/receipts", {"lines": [{"line_id": pol[0]["id"], "received": 60}]}, T["site"]), 201)
    expect("I3.2 steel received into the warehouse", call("POST", f"/purchase-orders/{po['id']}/receipts", {"location": WH, "lines": [
        {"line_id": pol[1]["id"], "received": 10}]}, T["procurement"]), 201)
    st_site = expect("I3.2 site stock (site view)", call("GET", f"/projects/{PID}/stock", token=T["site"]))
    cem = next((r for r in st_site["rows"] if r["description"] == f"Cement {RUN}"), None)
    check("I3.2 60 bags on site", cem and cem["balance"] == 60, st_site["rows"])
    check("I3.2 site sees no stock value", cem and "value" not in cem and "rate" not in cem, cem)
    check("I3.2 steel is not on site", not any(r["description"] == f"Steel {RUN}" for r in st_site["rows"]))
    wst = expect("I3.2 warehouse stock", call("GET", f"/warehouses/{WH}/stock", token=T["procurement"]))
    stl = next((r for r in wst["rows"] if r["description"] == f"Steel {RUN}"), None)
    check("I3.2 steel in the warehouse with its value", stl and stl["balance"] == 10 and stl["value"] == 15000, stl)
    expect("I3.2 site cannot see the warehouse", call("GET", f"/warehouses/{WH}/stock", token=T["site"]), 403)
    expect("I3.3 use more than on site refused", call("POST", f"/projects/{PID}/stock/consume", {"lines": [{"key": cem["key"], "qty": 61}]}, T["site"]), 400)
    expect("I3.3 site uses 25 bags on a stage", call("POST", f"/projects/{PID}/stock/consume", {"lines": [{"key": cem["key"], "qty": 25, "stage_id": S2}],
                                                                                              "site_report_id": sr["id"]}, T["site"]), 201)
    expect("I3.3 site cannot transfer", call("POST", "/stock/transfer", {"from": f"w:{WH}", "to": f"p:{PID}", "lines": [{"key": stl["key"], "qty": 4}]}, T["site"]), 403)
    expect("I3.3 transfer more than held refused", call("POST", "/stock/transfer", {"from": f"w:{WH}", "to": f"p:{PID}", "lines": [{"key": stl["key"], "qty": 11}]}, T["procurement"]), 400)
    expect("I3.3 warehouse sends 4 t to site", call("POST", "/stock/transfer", {"from": f"w:{WH}", "to": f"p:{PID}", "lines": [{"key": stl["key"], "qty": 4}]}, T["procurement"]), 201)
    rows = {r["description"]: r for r in call("GET", f"/projects/{PID}/stock", token=T["pm"])[1]["rows"]}
    check("I3.3 site balance after use and transfer", rows[f"Cement {RUN}"]["balance"] == 35 and rows[f"Steel {RUN}"]["balance"] == 4, rows)
    check("I3.3 warehouse left with 6", next(r for r in call("GET", f"/warehouses/{WH}/stock", token=T["owner"])[1]["rows"]
                                             if r["description"] == f"Steel {RUN}")["balance"] == 6)
    expect("I3.3 count adjustment needs a reason", call("POST", f"/projects/{PID}/stock/adjust", {"key": cem["key"], "counted": 33}, T["procurement"]), 400)
    expect("I3.3 count adjustment", call("POST", f"/projects/{PID}/stock/adjust", {"key": cem["key"], "counted": 33, "reason": "2 bags spoilt"}, T["procurement"]), 201)
    check("I3.3 counted balance", next(r for r in call("GET", f"/projects/{PID}/stock", token=T["pm"])[1]["rows"] if r["key"] == cem["key"])["balance"] == 33)
    expect("I3.3 warehouse holding stock cannot be removed", call("PUT", "/settings/warehouses", {"warehouses": []}, T["owner"]), 409)

    # --- attendance ---
    w1 = expect("I3.4 site worker", call("POST", "/site-workers", {"name": f"Ramu {RUN}", "trade": "Mason", "daily_rate": 800}, T["pm"]), 201)
    expect("I3.4 site cannot see the daily rate", call("GET", "/site-workers", token=T["site"]))
    check("I3.4 rate hidden from site", all("daily_rate" not in w for w in call("GET", "/site-workers", token=T["site"])[1]))
    att = expect("I3.4 attendance sheet", call("GET", f"/projects/{PID}/attendance?date={day(0)}", token=T["site"]))
    check("I3.4 staff and workers listed", any(x["person"] == f"w:{w1['id']}" for x in att["people"]) and any(x["kind"] == "staff" for x in att["people"]))
    expect("I3.4 unknown person refused", call("PUT", f"/projects/{PID}/attendance", {"date": day(0), "rows": [{"person": "w:nobody", "status": "present"}]}, T["site"]), 400)
    expect("I3.4 out before in refused", call("PUT", f"/projects/{PID}/attendance", {"date": day(0), "rows": [
        {"person": f"w:{w1['id']}", "status": "present", "in": "18:00", "out": "09:00"}]}, T["site"]), 400)
    expect("I3.4 older than yesterday refused", call("PUT", f"/projects/{PID}/attendance", {"date": day(-3), "rows": []}, T["site"]), 409)
    expect("I3.4 today", call("PUT", f"/projects/{PID}/attendance", {"date": day(0), "rows": [
        {"person": f"w:{w1['id']}", "status": "present", "in": "09:00", "out": "18:00", "ot_hours": 2},
        {"person": f"u:{U['site']}", "status": "half_day"}]}, T["site"]))
    sh = expect("I3.4 yesterday (edited twice, one sheet)", call("PUT", f"/projects/{PID}/attendance", {"date": day(-1), "rows": [
        {"person": f"w:{w1['id']}", "status": "absent"}]}, T["site"]))
    sh = expect("I3.4 yesterday again", call("PUT", f"/projects/{PID}/attendance", {"date": day(-1), "rows": [
        {"person": f"w:{w1['id']}", "status": "half_day"}]}, T["site"]))
    check("I3.4 one sheet per day", mongo.attendance.count_documents({"company_id": CID, "project_id": PID}) == 2)
    month = day(0)[:7]
    summ = expect("I3.4 month summary (PM)", call("GET", f"/projects/{PID}/attendance/summary?month={month}", token=T["pm"]))
    ram = next((x for x in summ["rows"] if x["person"] == f"w:{w1['id']}"), {})
    if day(-1)[:7] == month:
        check("I3.4 days counted with half days", ram.get("days") == 1.5 and ram.get("ot_hours") == 2, ram)
        check("I3.4 labour cost for the PM", ram.get("cost") == 1200, ram)
    s_site = call("GET", f"/projects/{PID}/attendance/summary?month={month}", token=T["site"])[1]
    check("I3.4 no labour cost for site", all("cost" not in x for x in s_site["rows"]), s_site["rows"])

    # --- snags ---
    expect("I3.5 snag needs a title", call("POST", f"/projects/{PID}/snags", {}, T["site"]), 400)
    expect("I3.5 assignee must be on the team", call("POST", f"/projects/{PID}/snags", {"title": "x", "assignee_id": U["designer"]}, T["site"]), 400)
    k2 = upload(f"snag{RUN}.png", T["site"])["key"]
    keys.append(k2)
    sn = expect("I3.5 snag with photo", call("POST", f"/projects/{PID}/snags", {"title": f"Chipped tile {RUN}", "location": "Kitchen", "stage_id": S2,
                                                                              "assignee_id": U["pm"], "due": day(-1), "priority": "high", "photos": [k2]}, T["site"]), 201)
    check("I3.5 numbered, open, overdue", sn["number"] and sn["status"] == "open" and sn["overdue"], sn)
    check("I3.5 assignee told", mongo.notifications.count_documents({"company_id": CID, "user_id": U["pm"], "event": "snag_assigned"}) >= 1)
    expect("I3.5 close before fixed refused", call("POST", f"/snags/{sn['id']}/close", {}, T["site"]), 409)
    expect("I3.5 PM fixes it", call("POST", f"/snags/{sn['id']}/fixed", {"note": "Replaced", "photos": [k2]}, T["pm"]))
    expect("I3.5 fixer cannot close own fix", call("POST", f"/snags/{sn['id']}/close", {}, T["pm"]), 409)
    expect("I3.5 reopen needs a reason", call("POST", f"/snags/{sn['id']}/reopen", {}, T["site"]), 400)
    expect("I3.5 reopened", call("POST", f"/snags/{sn['id']}/reopen", {"reason": "still chipped"}, T["site"]))
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    check("I3.5 overdue snag chased once", mongo.notifications.count_documents({"company_id": CID, "key": f"snag-due:{sn['id']}:{day(-1)}", "user_id": U["pm"]}) == 1)
    expect("fixed again", call("POST", f"/snags/{sn['id']}/fixed", {"note": "Replaced again"}, T["pm"]))
    cl = expect("I3.5 site checks and closes", call("POST", f"/snags/{sn['id']}/close", {}, T["site"]))
    check("I3.5 closed with history", cl["status"] == "closed" and len(cl["history"]) == 5, cl.get("history"))
    lst = expect("I3.5 list", call("GET", f"/projects/{PID}/snags", token=T["owner"]))
    check("I3.5 counts", lst["counts"]["closed"] >= 1)
    expect("I3.5 closed snag not edited", call("PUT", f"/snags/{sn['id']}", {"title": "x"}, T["site"]), 409)

    # --- installation checklist ---
    checks = call("GET", "/install-checks", token=T["site"])[1]
    part = expect("I3.6 half the checks", call("POST", f"/selections/{SEL}/install", {"checks": [{"text": c, "done": i < 2} for i, c in enumerate(checks)]}, T["site"]))
    check("I3.6 not installed until every check", part["status"] == "ordered" and part["installation"]["checks"][0]["by"], part.get("status"))
    full = expect("I3.6 every check ticked", call("POST", f"/selections/{SEL}/install", {"checks": [{"text": c, "done": True} for c in checks], "photos": [k1]}, T["site"]))
    check("I3.6 installed", full["status"] == "installed" and full["installation"]["photos"], full.get("status"))
    expect("I3.6 installed once", call("POST", f"/selections/{SEL}/install", {"checks": []}, T["site"]), 409)

    # ======================================= block 4 =======================================
    # --- markup rules and the product catalogue ---
    expect("I4.1 markup over 500% refused", call("PUT", "/settings/markup", {"default_pct": 900}, T["owner"]), 400)
    expect("I4.1 markup rules", call("PUT", "/settings/markup", {"default_pct": 20, "by_category": {"Furniture": 40}, "by_client": {CLIENT: 10}}, T["owner"]))
    expect("I4.1 site cannot see markups", call("GET", "/settings/markup", token=T["site"]), 403)
    expect("I4.1 bad product link", call("POST", "/rates", {"kind": "product", "name": "x", "unit": "nos", "rate": 1, "url": "javascript:alert(1)"}, T["estimator"]), 400)
    prod = expect("I4.1 product with catalogue fields", call("POST", "/rates", {"kind": "product", "name": f"Armchair {RUN}", "unit": "nos", "rate": 1000,
        "category": "Furniture", "brand": "Acme", "sku": "AC-12", "dimensions": "80 x 75 x 90 cm", "finish": "Teak / linen", "lead_days": 21,
        "supplier_id": VENDOR, "photos": [k1], "url": "https://example.com/armchair"}, T["estimator"]), 201)
    rates_made = [prod["id"]]
    pr_ = next((x for x in call("GET", "/products", token=T["designer"])[1]["products"] if x["id"] == prod["id"]), {})
    check("I4.1 catalogue shows the fields", pr_.get("sku") == "AC-12" and pr_.get("supplier_name") and pr_.get("photo_urls"), pr_)
    check("I4.1 client price from the category markup", pr_.get("suggested_price") == 1400 and pr_.get("markup_source") == "category", pr_)
    site_view = next((x for x in call("GET", "/products", token=T["site"])[1]["products"] if x["id"] == prod["id"]), {})
    check("I4.1 site sees no trade price", "rate" not in site_view and "suggested_price" not in site_view, site_view)
    check("I4.1 search", len(call("GET", "/products?q=ac-12", token=T["designer"])[1]["products"]) == 1)
    s4 = expect("I4.2 option priced by the client's markup", call("POST", f"/projects/{PID}/selections", {"stage_id": S2, "item": f"Chair {RUN}", "room": "Study",
        "allowance": 5000, "options": [{"name": "Armchair", "rate_id": prod["id"], "qty": 2, "unit_cost": 1000}]}, T["owner"]), 201)
    o4 = s4["options"][0]
    check("I4.2 client rule beats the category", o4["unit_price"] == 1100 and o4.get("markup_source") == "client", o4)
    expect("choose", call("POST", f"/selections/{s4['id']}/choice", {"option_id": o4["id"], "method": "Email", "name": "Ira"}, T["owner"]))
    mg = expect("I4.3 selection margin report", call("GET", f"/projects/{PID}/selections/margin", token=T["pm"]))
    study = next((r for r in mg["rooms"] if r["room"] == "Study"), {})
    check("I4.3 margin by room", study.get("cost") == 2000 and study.get("price") == 2200 and study.get("margin") == 200, study)
    expect("I4.3 site cannot see margins", call("GET", f"/projects/{PID}/selections/margin", token=T["site"]), 403)
    # --- add from a link: only public pages; the parser reads Open Graph / schema.org ---
    for bad in ("http://127.0.0.1/p", "http://localhost:5000/api/health", "ftp://example.com/x", "http://10.0.0.5/x", "http://169.254.169.254/latest"):
        expect(f"I4.4 refused {bad}", call("POST", "/products/clip", {"url": bad}, T["designer"]), 400)
    expect("I4.4 site cannot clip", call("POST", "/products/clip", {"url": "https://example.com"}, T["site"]), 403)
    from app.routes.catalogue import parse_product
    page = ('<html><head><title>Fallback</title><meta property="og:image" content="/img/a.jpg">'
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Oslo Lamp","sku":"OL-1",'
            '"brand":{"@type":"Brand","name":"Lumo"},"offers":{"@type":"Offer","price":"4,250.00","priceCurrency":"INR"}}</script></head></html>')
    got = parse_product(page, "https://shop.example.com/oslo")
    check("I4.4 parser reads the product", got["name"] == "Oslo Lamp" and got["price"] == 4250 and got["brand"] == "Lumo" and got["sku"] == "OL-1"
          and got["image_url"] == "https://shop.example.com/img/a.jpg", got)
    got2 = parse_product('<meta property="og:title" content="Rug &amp; Co"><meta property="product:price:amount" content="999">', "https://x.example.com/r")
    check("I4.4 Open Graph fallback", got2["name"] == "Rug & Co" and got2["price"] == 999, got2)

    # --- allowance credit ---
    sc = expect("allowance item", call("POST", f"/projects/{PID}/selections", {"stage_id": S2, "item": f"Tiles {RUN}", "allowance": 50000,
                                                                              "options": [{"name": "Plain tile", "qty": 1, "unit_cost": 30000, "unit_price": 40000}]}, T["owner"]), 201)
    expect("choose", call("POST", f"/selections/{sc['id']}/choice", {"option_id": sc["options"][0]["id"], "method": "Email", "name": "Ira"}, T["owner"]))
    cr = expect("I4.5 under the allowance -> credit change order", call("POST", f"/selections/{sc['id']}/change-order", {}, T["owner"]), 201)["change_order"]
    check("I4.5 credit is negative", cr["totals"]["price"] == -10000 and cr.get("credit"), cr.get("totals"))
    before = mongo.contracts.find_one({"_id": ObjectId(CONID)})
    expect("price", call("POST", f"/change_orders/{cr['id']}/price", {}, T["owner"]))
    expect("send", call("POST", f"/change_orders/{cr['id']}/send", {}, T["owner"]))
    expect("I4.5 client agrees", call("POST", f"/change_orders/{cr['id']}/approve", {"method": "Email", "name": "Ira"}, T["owner"]))
    after = mongo.contracts.find_one({"_id": ObjectId(CONID)})
    check("I4.5 contract goes down by the credit", abs((before.get("revised_value") or before["value"]) + cr["totals"]["total"] - after["revised_value"]) < 0.02
          and abs(after.get("credit_due", 0) + cr["totals"]["total"]) < 0.02, (after.get("revised_value"), after.get("credit_due")))

    # --- delivered status from the goods receipt ---
    expect("deposits not required", call("PUT", "/finance/settings", {"require_selection_deposit": False}, T["owner"]))
    sd = expect("selection with a supplier", call("POST", f"/projects/{PID}/selections", {"stage_id": S2, "item": f"Lamp {RUN}", "options": [
        {"name": "Oslo", "qty": 2, "unit_cost": 2000, "unit_price": 3000, "supplier_id": VENDOR}]}, T["owner"]), 201)
    expect("choose", call("POST", f"/selections/{sd['id']}/choice", {"option_id": sd["options"][0]["id"], "method": "Email", "name": "Ira"}, T["owner"]))
    expect("confirm", call("POST", f"/selections/{sd['id']}/status", {"status": "confirmed"}, T["owner"]))
    od = expect("order", call("POST", f"/selections/{sd['id']}/status", {"status": "ordered"}, T["owner"]))
    spo = od.get("po_id") or mongo.selections.find_one({"_id": ObjectId(sd["id"])}).get("po_draft")
    spo = spo if isinstance(spo, str) else (spo or {}).get("id")
    check("I4.6 selection is on a draft PO", spo, od)
    call("POST", f"/purchase-orders/{spo}/submit", {}, T["procurement"])
    expect("send", call("POST", f"/purchase-orders/{spo}/send", {"email": False}, T["procurement"]))
    lns = call("GET", f"/purchase-orders/{spo}", token=T["procurement"])[1]["lines"]
    ln = next(x for x in lns if x.get("selection_id") == sd["id"])
    expect("part received", call("POST", f"/purchase-orders/{spo}/receipts", {"lines": [{"line_id": ln["id"], "received": 1}]}, T["site"]), 201)
    check("I4.6 part delivery is not delivered", mongo.selections.find_one({"_id": ObjectId(sd["id"])})["status"] == "ordered")
    expect("rest received", call("POST", f"/purchase-orders/{spo}/receipts", {"lines": [{"line_id": ln["id"], "received": 1}]}, T["site"]), 201)
    check("I4.6 full receipt -> delivered", mongo.selections.find_one({"_id": ObjectId(sd["id"])})["status"] == "delivered")
    expect("I4.6 delivered -> installed by the checklist", call("POST", f"/selections/{sd['id']}/install",
                                                                 {"checks": [{"text": "Fitted", "done": True}]}, T["site"]))
    expect("I4.6 no step back to delivered", call("POST", f"/selections/{sd['id']}/status", {"status": "delivered"}, T["owner"]), 409)

    # --- editing requests and RFQs, reversing a delivery ---
    preq = expect("request", call("POST", f"/projects/{PID}/purchase-requests", {"stage_id": S2, "lines": [{"description": f"Sand {RUN}", "qty": 3, "unit": "cum"}]}, T["site"]), 201)
    e = expect("I4.7 requester edits the request", call("PUT", f"/purchase-requests/{preq['id']}", {"lines": [{"description": f"Sand {RUN}", "qty": 5, "unit": "cum"}], "note": "more"}, T["site"]))
    check("I4.7 request changed", e["lines"][0]["qty"] == 5 and e["note"] == "more", e)
    expect("I4.7 someone else cannot", call("PUT", f"/purchase-requests/{preq['id']}", {"note": "x"}, T["accounts"]), 403)
    rfq = expect("RFQ", call("POST", "/rfqs", {"project_id": PID, "request_ids": [preq["id"]], "supplier_ids": [VENDOR], "due_date": day(3)}, T["procurement"]), 201)
    expect("I4.7 request in an RFQ is fixed", call("PUT", f"/purchase-requests/{preq['id']}", {"note": "y"}, T["site"]), 409)
    sup2 = expect("second supplier", call("POST", "/contacts", {"name": f"Sand Co {RUN}", "kind": "company", "types": ["supplier"], "phone": f"73{RUN}"}, T["procurement"]), 201)
    contacts_made.append(sup2["id"])
    r2_ = expect("I4.7 RFQ: new due date, second supplier", call("PUT", f"/rfqs/{rfq['id']}", {"due_date": day(5), "supplier_ids": [VENDOR, sup2["id"]]}, T["procurement"]))
    check("I4.7 RFQ changed", r2_["due_date"] == day(5) and len(r2_["suppliers"]) == 2, r2_)
    expect("quote", call("POST", f"/rfqs/{rfq['id']}/quotes", {"supplier_id": VENDOR, "lines": [{"line_id": rfq["lines"][0]["id"], "rate": 1200}]}, T["procurement"]), 201)
    expect("I4.7 a supplier who quoted stays", call("PUT", f"/rfqs/{rfq['id']}", {"supplier_ids": [sup2["id"]]}, T["procurement"]), 409)
    grns = list(mongo.goods_receipts.find({"po_id": po["id"]}))
    used = next(x for x in grns if (x.get("location") or {}).get("kind") == "site")
    expect("I4.8 a delivery partly used cannot be reversed", call("POST", f"/goods-receipts/{used['_id']}/reverse", {"reason": "typo"}, T["procurement"]), 409)
    po2 = expect("PO", call("POST", "/purchase-orders", {"project_id": PID, "vendor_id": VENDOR, "expected_date": day(2),
                                                         "lines": [{"description": f"Grit {RUN}", "qty": 5, "unit": "cum", "unit_cost": 1000, "stage_id": S2, "tax_pct": 0}]}, T["procurement"]), 201)
    call("POST", f"/purchase-orders/{po2['id']}/submit", {}, T["procurement"])
    call("POST", f"/purchase-orders/{po2['id']}/send", {"email": False}, T["procurement"])
    l2 = call("GET", f"/purchase-orders/{po2['id']}", token=T["procurement"])[1]["lines"][0]
    gr = expect("wrong delivery", call("POST", f"/purchase-orders/{po2['id']}/receipts", {"lines": [{"line_id": l2["id"], "received": 5}]}, T["procurement"]), 201)
    expect("I4.8 reverse needs a reason", call("POST", f"/goods-receipts/{gr['id']}/reverse", {}, T["procurement"]), 400)
    expect("I4.8 site cannot reverse", call("POST", f"/goods-receipts/{gr['id']}/reverse", {"reason": "x"}, T["site"]), 403)
    expect("I4.8 reverse", call("POST", f"/goods-receipts/{gr['id']}/reverse", {"reason": "entered on the wrong PO"}, T["procurement"]))
    po2b = call("GET", f"/purchase-orders/{po2['id']}", token=T["procurement"])[1]
    check("I4.8 PO open again", po2b["status"] in ("sent", "acknowledged") and not po2b["lines"][0].get("accepted_qty"), po2b["status"])
    check("I4.8 stock gone", not any(r["description"] == f"Grit {RUN}" and r["balance"] for r in call("GET", f"/projects/{PID}/stock", token=T["pm"])[1]["rows"]))
    expect("I4.8 twice refused", call("POST", f"/goods-receipts/{gr['id']}/reverse", {"reason": "again"}, T["procurement"]), 409)

    # --- authority approvals register ---
    expect("I4.9 not on the team", call("POST", f"/projects/{PID}/permits", {"type": "Building permit"}, T["designer"]), 404)
    call("POST", f"/projects/{PID}/team", {"user_id": U["designer"], "project_role": "Architect", "access": "edit"}, T["owner"])
    expect("I4.9 unknown type", call("POST", f"/projects/{PID}/permits", {"type": "Licence to fly"}, T["designer"]), 400)
    pm_ = expect("I4.9 building permit", call("POST", f"/projects/{PID}/permits", {"type": "Building permit", "authority": "Pune Municipal Corporation",
                                                                                  "fee": 25000, "stage_id": p["stages"][0]["id"], "documents": [k1]}, T["designer"]), 201)
    expect("I4.9 straight to approved refused", call("POST", f"/permits/{pm_['id']}/status", {"status": "approved"}, T["designer"]), 409)
    expect("I4.9 submit needs the reference", call("POST", f"/permits/{pm_['id']}/status", {"status": "submitted"}, T["designer"]), 400)
    expect("I4.9 submitted", call("POST", f"/permits/{pm_['id']}/status", {"status": "submitted", "reference": "BP/2026/123", "date": day(-40)}, T["designer"]))
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    check("I4.9 no answer in 30 days -> PM told", mongo.notifications.count_documents({"company_id": CID, "key": f"permit-wait:{pm_['id']}:{day(-40)}", "user_id": U["pm"]}) == 1)
    expect("I4.9 query needs a note", call("POST", f"/permits/{pm_['id']}/status", {"status": "query"}, T["designer"]), 400)
    expect("I4.9 query", call("POST", f"/permits/{pm_['id']}/status", {"status": "query", "note": "Fire exit width"}, T["designer"]))
    expect("resubmit", call("POST", f"/permits/{pm_['id']}/status", {"status": "submitted"}, T["designer"]))
    ap = expect("I4.9 approved with conditions", call("POST", f"/permits/{pm_['id']}/status", {"status": "approved", "valid_until": day(20),
                                                                                             "conditions": ["Tree plantation", "Rainwater harvesting"]}, T["designer"]))
    check("I4.9 conditions and expiry", ap["open_conditions"] == 2 and ap["expiring"], ap)
    c0 = ap["conditions"][0]["id"]
    ap = expect("I4.9 condition met", call("PUT", f"/permits/{pm_['id']}/conditions/{c0}", {"met": True}, T["designer"]))
    check("I4.9 one condition left", ap["open_conditions"] == 1)
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    check("I4.9 renewal reminder", mongo.notifications.count_documents({"company_id": CID, "key": f"permit-exp:{pm_['id']}:{day(20)}"}) >= 1)
    expect("I4.9 an approved permit is not deleted", call("DELETE", f"/permits/{pm_['id']}", token=T["designer"]), 409)
    check("I4.9 site sees the register read-only", call("GET", f"/projects/{PID}/permits", token=T["site"])[1]["can_write"] is False)

    # --- mood boards ---
    CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
    pp = expect("portal project", call("POST", "/projects", {"name": f"PhaseI boards {RUN}", "services": ["interior"], "start": day(0), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    projects.append(pp["id"])
    expect("I4.10 board needs an image or link", call("POST", f"/projects/{pp['id']}/boards", {"title": "Living", "items": [{"note": "x"}]}, T["owner"]), 400)
    bd = expect("I4.10 board", call("POST", f"/projects/{pp['id']}/boards", {"title": "Living", "room": "Living", "items": [
        {"key": k1, "note": "Warm wood"}, {"image_url": "https://images.example.com/sofa.jpg", "note": "Low sofa"}]}, T["owner"]), 201)
    check("I4.10 not shared yet", call("GET", f"/portal/projects/{pp['id']}/boards", token=T["client"])[1] == [])
    expect("share", call("PUT", f"/boards/{bd['id']}", {"shared": True}, T["owner"]))
    pb = expect("I4.10 client sees the shared board", call("GET", f"/portal/projects/{pp['id']}/boards", token=T["client"]))
    check("I4.10 two images", len(pb) == 1 and len(pb[0]["items"]) == 2, pb)
    it0 = pb[0]["items"][0]["id"]
    expect("I4.10 like", call("POST", f"/portal/boards/{bd['id']}/react", {"item_id": it0, "like": True}, T["client"]))
    rr = expect("I4.10 comment", call("POST", f"/portal/boards/{bd['id']}/react", {"item_id": it0, "comment": "Love this"}, T["client"]))
    check("I4.10 liked and commented", rr["items"][0]["liked"] and rr["items"][0]["comments"][0]["comment"] == "Love this", rr["items"][0])
    staff = call("GET", f"/projects/{pp['id']}/boards", token=T["owner"])[1]["boards"][0]["items"][0]
    check("I4.10 team sees the reactions", len(staff.get("reactions", [])) == 2, staff)
    expect("I4.10 other portal users cannot react", call("POST", f"/portal/boards/{bd['id']}/react", {"item_id": it0, "like": True}, T["vendor"]), 404)

    # ======================================= block 5 =======================================
    # --- change requests from the client and the site ---
    PP = pp["id"]
    expect("I5.1 request needs a title", call("POST", f"/portal/projects/{PP}/change-requests", {}, T["client"]), 400)
    rq = expect("I5.1 client asks for a change", call("POST", f"/portal/projects/{PP}/change-requests", {"title": f"Add a skylight {RUN}",
                                                                                                       "description": "Over the stairs"}, T["client"]), 201)
    co_c = mongo.change_orders.find_one({"_id": ObjectId(rq["id"])})
    check("I5.1 a draft change order marked as the client's", co_c["status"] == "draft" and co_c["requested"]["kind"] == "client" and co_c["reason"] == "client_request", co_c.get("requested"))
    mine = expect("I5.1 client sees their request", call("GET", f"/portal/projects/{PP}/change-requests", token=T["client"]))
    check("I5.1 being priced, no price shown yet", mine and mine[0]["state"] == "Being priced" and mine[0]["total"] is None, mine)
    expect("I5.1 a supplier cannot ask", call("POST", f"/portal/projects/{PP}/change-requests", {"title": "x"}, T["vendor"]), 404)
    sr_ = expect("I5.2 site asks for a change", call("POST", f"/projects/{PID}/change-requests", {"title": f"Rock found {RUN}", "stage_id": S2}, T["site"]), 201)
    check("I5.2 site request is a site-condition draft", sr_["reason"] == "site_condition" and sr_["requested"]["kind"] == "site", sr_)
    expect("I5.2 not on the team", call("POST", f"/projects/{PP}/change-requests", {"title": "x"}, T["site"]), 404)
    # --- new tasks from a change order ---
    expect("I5.3 bad new task", call("PUT", f"/change_orders/{sr_['id']}", {"new_tasks": [{"title": "Break rock", "days": 0}]}, T["pm"]), 400)
    expect("I5.3 price with new tasks", call("PUT", f"/change_orders/{sr_['id']}", {"new_tasks": [{"title": f"Break rock {RUN}", "days": 2},
        {"title": f"Clear debris {RUN}", "days": 1}], "lines": [{"description": "Rock breaking", "qty": 1, "cost_rate": 5000, "price_rate": 8000}]}, T["pm"]))
    for st_, body in (("price", {}), ("send", {}), ("approve", {"method": "Email", "name": "Ira"})):
        expect(f"CO {st_}", call("POST", f"/change_orders/{sr_['id']}/{st_}", body, T["pm"]))
    stg = next(s for s in mongo.projects.find_one({"_id": ObjectId(PID)})["stages"] if s["id"] == S2)
    nts = [tk for tk in stg["tasks"] if tk.get("co_id") == sr_["id"]]
    check("I5.3 tasks added to the stage, one after the other", len(nts) == 2 and nts[0]["end"] < nts[1]["start"], [(x["title"], x["start"], x["end"]) for x in nts])
    # --- proposals in the portal ---
    props = expect("I5.4 client's proposals", call("GET", "/portal/proposals", token=T["client"]))
    check("I5.4 a list (with links when sent)", isinstance(props, list) and all(x.get("link") is None or x["link"].startswith("/p/") for x in props), props[:2])
    # --- reports ---
    expect("an open snag", call("POST", f"/projects/{PID}/snags", {"title": f"Loose rail {RUN}", "due": day(-2)}, T["site"]), 201)
    pr_rep = expect("I5.5 projects report", call("GET", "/reports/projects", token=T["owner"]))
    check("I5.5 report sections", all(k in pr_rep for k in ("delayed", "milestones", "open_items")))
    check("I5.5 open items count snags and approvals", any(r["project_id"] == PID for r in pr_rep["open_items"]), [r["project"] for r in pr_rep["open_items"]][:5])
    cf = expect("I5.6 cash flow", call("GET", "/reports/cashflow", token=T["accounts"]))
    this = next(m for m in cf["months"] if m["month"] == day(0)[:7])
    check("I5.6 seven months, this month has money in", len(cf["months"]) == 7 and this["in"] > 0, this)
    expect("I5.6 site cannot see cash flow", call("GET", "/reports/cashflow", token=T["site"]), 403)
    tm = expect("I5.7 team workload", call("GET", "/reports/team", token=T["owner"]))
    check("I5.7 capacity and people", tm["capacity_days"] > 0 and any(x["user_id"] == U["pm"] for x in tm["people"]), tm.get("capacity_days"))
    wt = expect("I5.8 waiting longest", call("GET", "/reports/waiting", token=T["owner"]))
    check("I5.8 approvals and payments lists", "approvals" in wt and "payments" in wt)
    # --- inbound WhatsApp routed to the project and the right person ---
    from flask import g as fg
    from app import create_app
    from app.routes.insights import route_inbound
    with create_app().test_request_context():
        comp = mongo.companies.find_one({"_id": ObjectId(CID)})
        fg.cid, fg.company, fg.uid, fg.user, fg.role = CID, comp, None, {"name": "WhatsApp"}, None
        contact = mongo.contacts.find_one({"_id": ObjectId(CLIENT_CONTACT)})
        call("POST", f"/projects/{PP}/team", {"user_id": U["accounts"], "project_role": "Accounts", "access": "view"}, T["owner"])
        res = route_inbound(contact, f"When is the next payment due? {RUN}")
        res2 = route_inbound(contact, f"There was an accident on site {RUN}")
    check("I5.9 routed to the project, topic payment", res and res["project_id"] == PP and res["topic"] == "payment" and U["accounts"] in res["to"], res)
    check("I5.9 urgent words flagged", res2 and res2["urgent"], res2)
    th = expect("I5.9 joins the client's thread", call("GET", f"/projects/{PP}/threads/{CLIENT_CONTACT}", token=T["owner"]))
    check("I5.9 thread shows the WhatsApp message", any(m.get("via") == "whatsapp" and RUN in m["text"] for m in th), [m.get("text") for m in th][-2:])

    # ======================================= block 6 =======================================
    from app.security import create_token
    SA = {}
    for u in mongo.superadmin_users.find({"active": {"$ne": False}}):
        SA.setdefault(u["role"], create_token({"uid": str(u["_id"]), "kind": "superadmin", "role": u["role"], "name": u["name"]}))
    sa_before = mongo.platform_settings.find_one({"_id": "settings"})
    # a fresh company for the platform checks
    email6 = f"owner6{RUN}@sub.test"
    sg = expect("signup", call("POST", "/auth/signup", {"company_name": f"Sub Co {RUN}", "name": "Sub Owner", "email": email6, "password": "secret12",
                                                        "company_types": ["contractor"], "plan_code": "pro", "city": "Pune", "gstin": "27ABCDE1234F1Z5"}), 201)
    C6, O6 = sg["company"]["id"], sg["token"]
    signups = [C6]
    dash = expect("I6.1 dashboard", call("GET", "/sa/dashboard", token=SA["owner"]))
    check("I6.1 dashboard figures", all(k in dash for k in ("mrr", "revenue_this_month", "signups_this_month", "overdue", "health")) and dash["health"]["db"] == "ok", list(dash))
    found = expect("I6.2 search companies", call("GET", "/sa/companies?q=" + urllib.parse.quote(f"Sub Co {RUN}"), token=SA["owner"]))
    check("I6.2 found by name", len(found) == 1 and found[0]["id"] == C6, found)
    prof = expect("I6.2 company profile", call("GET", f"/sa/companies/{C6}", token=SA["owner"]))
    check("I6.2 profile: owner, usage, invoices", prof["owner"]["email"] == email6 and "usage" in prof and prof["invoices"] == [], prof.get("owner"))
    check("I6.2 no private data in the profile", not any(k in json.dumps(prof) for k in ('"leads"', '"costs"', '"contacts"')))
    if "viewer" in SA:
        expect("I6.3 viewer cannot add plans", call("POST", "/sa/plans", {"code": "x", "name": "x", "price_monthly": 1}, SA["viewer"]), 403)
    tiny = expect("I6.3 new plan", call("POST", "/sa/plans", {"code": f"tiny{RUN}", "name": f"Tiny {RUN}", "price_monthly": 1000, "max_users": 1,
                                                             "max_projects": 2, "max_modules": 1, "storage_gb": 1}, SA["owner"]), 201)
    check("I6.3 yearly = 10 months", tiny["price_yearly"] == 10000, tiny)
    expect("I6.3 duplicate code", call("POST", "/sa/plans", {"code": f"tiny{RUN}", "name": "x", "price_monthly": 5}, SA["owner"]), 409)
    cp = expect("I6.4 coupon", call("POST", "/sa/coupons", {"code": f"save{RUN}", "percent": 20, "months": 3}, SA["owner"]), 201)
    expect("I6.4 coupon over 100%", call("POST", "/sa/coupons", {"code": f"bad{RUN}", "percent": 120}, SA["owner"]), 400)
    # company actions
    for act, body in (("extend_trial", {"days": 7}), ("free_months", {"months": 1}), ("modules", {"modules": ["construction", "interior"]}),
                      ("features", {"features": {"whatsapp": False, "procurement": True}}), ("addons", {"extra_users": 2, "extra_storage_gb": 150}),
                      ("note", {"text": "Called the owner"})):
        expect(f"I6.5 {act}", call("POST", f"/sa/companies/{C6}/action", {"action": act, **body}, SA["owner"]))
    c6 = mongo.companies.find_one({"_id": ObjectId(C6)})
    check("I6.5 actions applied", c6["modules"] == ["construction", "interior"] and c6["feature_flags"] == {"whatsapp": False, "procurement": True}
          and c6["addons"] == {"extra_users": 2, "extra_storage_gb": 100} and c6["notes"][0]["text"] == "Called the owner", c6.get("addons"))
    expect("I6.5 unknown action", call("POST", f"/sa/companies/{C6}/action", {"action": "fly"}, SA["owner"]), 400)
    if "sales" in SA:
        expect("I6.5 sales can extend a trial", call("POST", f"/sa/companies/{C6}/action", {"action": "extend_trial", "days": 1}, SA["sales"]))
    rp = expect("I6.6 reset the owner's password", call("POST", f"/sa/companies/{C6}/action", {"action": "reset_owner_password"}, SA["owner"]))
    check("I6.6 old session ends", call("GET", "/billing/subscription", token=O6)[0] == 401)
    O6 = expect("I6.6 owner signs in with the new password", call("POST", "/auth/login", {"email": email6, "password": rp["temp_password"]}))["token"]
    # support login with permission
    expect("I6.7 login-as refused without permission", call("POST", f"/sa/companies/{C6}/login-as", {"reason": "help"}, SA["owner"]), 403)
    expect("allow support", call("PUT", "/company", {"allow_support_login": True}, O6))
    expect("I6.7 reason required", call("POST", f"/sa/companies/{C6}/login-as", {}, SA["owner"]), 400)
    if "billing" in SA:
        expect("I6.7 billing staff cannot log in as a company", call("POST", f"/sa/companies/{C6}/login-as", {"reason": "x"}, SA["billing"]), 403)
    la = expect("I6.7 support session", call("POST", f"/sa/companies/{C6}/login-as", {"reason": "Owner asked for help with invoices"}, SA["owner"]))
    check("I6.7 support token works for an hour", la["expires_in_minutes"] == 60 and call("GET", "/users", token=la["token"])[0] == 200)
    check("I6.7 logged on both sides", mongo.sa_audit.find_one({"action": "login_as", "target": C6}) and
          mongo.audit_logs.find_one({"company_id": C6, "action": "support_login"}))
    # self-service subscription
    sub = expect("I6.8 subscription", call("GET", "/billing/subscription", token=O6))
    check("I6.8 plan, usage, plans", sub["plan"]["code"] == "pro" and sub["usage"]["users"] == 1 and len(sub["plans"]) >= 3, sub.get("plan"))
    expect("I6.8 two modules do not fit a one-module plan", call("POST", "/billing/change", {"plan_code": "basic"}, O6), 409)
    expect("back to one module", call("POST", f"/sa/companies/{C6}/action", {"action": "modules", "modules": ["construction"]}, SA["owner"]))
    expect("I6.8 bad coupon", call("POST", "/billing/change", {"plan_code": "basic", "coupon": "NOPE"}, O6), 400)
    ch6 = expect("I6.8 move to Basic with a coupon (trial: no invoice yet)", call("POST", "/billing/change", {"plan_code": "basic", "coupon": f"save{RUN}"}, O6))
    check("I6.8 plan changed, coupon held", mongo.companies.find_one({"_id": ObjectId(C6)})["coupon"]["months_left"] == 3 and ch6["invoice"] is None, ch6)
    expect("I6.8 only the Owner manages it", call("GET", "/billing/subscription", token=T["pm"]), 403)
    # billing: trial ends -> invoice -> grace -> read-only -> paid -> active
    mongo.companies.update_one({"_id": ObjectId(C6)}, {"$set": {"trial_ends": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1), "modules": ["construction"]}})
    expect("I6.9 billing run", call("POST", "/sa/billing/run", {}, SA["owner"]))
    inv6 = mongo.platform_invoices.find_one({"company_id": C6, "type": "invoice"})
    check("I6.9 trial over -> first invoice", inv6 and inv6["status"] == "due", inv6 and inv6["status"])
    check("I6.9 coupon applied, GST intra-state (both Karnataka? no: 27 vs 29 -> IGST)", inv6 and any("Coupon" in ln["description"] for ln in inv6["lines"])
          and inv6["igst"] == inv6["gst"] and abs(inv6["total"] - inv6["subtotal"] * 1.18) < 0.05, inv6 and inv6["lines"])
    check("I6.9 add-ons billed", inv6 and any("Extra users" in ln["description"] for ln in inv6["lines"]))
    mongo.platform_invoices.update_one({"_id": inv6["_id"]}, {"$set": {"due_date": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1), "reminded_on": None}})
    call("POST", "/sa/billing/run", {}, SA["owner"])
    check("I6.9 past the grace period -> read-only", mongo.companies.find_one({"_id": ObjectId(C6)})["status"] == "read_only")
    expect("I6.9 read-only blocks writes", call("POST", "/contacts", {"name": "x", "kind": "person"}, O6), 402)
    dash = call("GET", "/sa/dashboard", token=SA["owner"])[1]
    check("I6.9 dashboard lists the overdue company", any(x["company_id"] == C6 for x in dash["overdue"]))
    pd = expect("I6.10 owner pays online (sandbox)", call("POST", f"/billing/invoices/{inv6['_id']}/pay", {}, O6))
    c6 = mongo.companies.find_one({"_id": ObjectId(C6)})
    check("I6.10 paid -> active with a renewal date", pd["status"] == "paid" and c6["status"] == "active" and c6.get("next_renewal") and c6.get("converted_at"), c6["status"])
    expect("I6.10 refund needs a reason", call("POST", f"/sa/invoices/{inv6['_id']}/action", {"action": "refund", "amount": 100}, SA["owner"]), 400)
    expect("I6.10 partial refund", call("POST", f"/sa/invoices/{inv6['_id']}/action", {"action": "refund", "amount": 100, "reason": "goodwill"}, SA["owner"]))
    check("I6.10 credit note", mongo.platform_invoices.find_one({"type": "credit_note", "against": inv6["number"]}))
    mi = expect("I6.10 manual invoice", call("POST", f"/sa/companies/{C6}/invoice", {"note": "Onboarding"}, SA["owner"]), 201)
    expect("I6.10 bad method", call("POST", f"/sa/invoices/{mi['id']}/action", {"action": "mark_paid", "method": "gold"}, SA["owner"]), 400)
    expect("I6.10 bank transfer recorded", call("POST", f"/sa/invoices/{mi['id']}/action", {"action": "mark_paid", "method": "bank_transfer", "ref": "UTR1"}, SA["owner"]))
    gr = expect("I6.10 GST report", call("GET", "/sa/reports/gst", token=SA["owner"]))
    check("I6.10 GST report has this month", any(r["month"] == datetime.now().strftime("%Y-%m") for r in gr), gr[:2])
    # usage alerts, plan change by the platform
    expect("no add-ons", call("POST", f"/sa/companies/{C6}/action", {"action": "addons", "extra_users": 0, "extra_storage_gb": 0}, SA["owner"]))
    expect("I6.11 move to Tiny", call("POST", f"/sa/companies/{C6}/action", {"action": "change_plan", "plan_code": f"tiny{RUN}"}, SA["owner"]))
    worker(datetime.now(timezone.utc).replace(tzinfo=None))
    owner6 = mongo.users.find_one({"email": email6})
    check("I6.11 owner told: near the user limit", mongo.notifications.count_documents({"company_id": C6, "user_id": str(owner6["_id"]), "event": "plan_limit"}) >= 1)
    us = expect("I6.11 usage report", call("GET", "/sa/usage", token=SA["owner"]))
    check("I6.11 near-limit flagged", any(r["id"] == C6 and r["near_limit"] for r in us))
    # support tickets
    tk = expect("I6.12 ticket from the company", call("POST", "/support/tickets", {"subject": f"Invoice question {RUN}", "text": "How do I add GST?"}, O6), 201)
    check("I6.12 support sees it", any(x["id"] == tk["id"] for x in call("GET", "/sa/tickets", token=SA["owner"])[1]))
    expect("I6.12 support answers", call("POST", f"/sa/tickets/{tk['id']}/reply", {"text": "Settings → Currency, tax & numbering", "status": "waiting"}, SA["owner"]))
    check("I6.12 owner told", mongo.notifications.count_documents({"company_id": C6, "event": "support_reply"}) == 1)
    tr = expect("I6.12 company replies", call("POST", f"/support/tickets/{tk['id']}/reply", {"text": "Thanks"}, O6))
    check("I6.12 thread and status", len(tr["replies"]) == 3 and tr["status"] == "open", tr.get("status"))
    # announcements
    an = expect("I6.13 announcement for Tiny companies", call("POST", "/sa/announcements", {"title": f"New feature {RUN}", "body": "Stock at site",
                                                                                           "audience": {"plans": [f"tiny{RUN}"]}}, SA["owner"]), 201)
    check("I6.13 Tiny company sees it", any(a["title"] == f"New feature {RUN}" for a in call("GET", "/announcements", token=O6)[1]))
    check("I6.13 others do not", not any(a["title"] == f"New feature {RUN}" for a in call("GET", "/announcements", token=T["owner"])[1]))
    # platform settings, legal pages
    st = expect("I6.14 settings", call("PUT", "/sa/settings", {"platform_name": "BuildSuite", "terms": f"Terms {RUN}", "gateway_secret": "sk_live_123456789"}, SA["owner"]))
    check("I6.14 secret masked", st["gateway_secret"].startswith("••••") and "123456789" not in json.dumps(st), st.get("gateway_secret"))
    call("PUT", "/sa/settings", {"gateway_secret": st["gateway_secret"]}, SA["owner"])
    check("I6.14 masked value never overwrites", (mongo.platform_settings.find_one({"_id": "settings"}) or {}).get("gateway_secret") == "sk_live_123456789")
    check("I6.14 public terms", call("GET", "/public/legal/terms")[1]["text"] == f"Terms {RUN}")
    # data export on request
    expect("I6.15 export without a request", call("GET", f"/sa/companies/{C6}/export", token=SA["owner"]), 403)
    expect("I6.15 owner asks for an export", call("POST", "/billing/export", {}, O6))
    ex = expect("I6.15 export", call("GET", f"/sa/companies/{C6}/export", token=SA["owner"]))
    check("I6.15 export has the data, never passwords", "users" in ex and ex["users"] and all("password" not in u for u in ex["users"]), list(ex)[:5])
    # signup approval
    mongo.platform_settings.update_one({"_id": "settings"}, {"$set": {"signup_needs_approval": True}}, upsert=True)
    email7 = f"owner7{RUN}@sub.test"
    pend = expect("I6.16 signup waits for approval", call("POST", "/auth/signup", {"company_name": f"Pending Co {RUN}", "name": "P", "email": email7,
                                                                                  "password": "secret12", "company_types": ["interior"]}), 201)
    check("I6.16 no session yet", pend.get("pending") and "token" not in pend, pend)
    C7 = str(mongo.users.find_one({"email": email7})["company_id"])
    signups.append(C7)
    expect("I6.16 login blocked", call("POST", "/auth/login", {"email": email7, "password": "secret12"}), 200)
    t7 = call("POST", "/auth/login", {"email": email7, "password": "secret12"})[1].get("token")
    expect("I6.16 pending company cannot work", call("GET", "/contacts", token=t7), 403)
    expect("I6.16 approve", call("POST", f"/sa/companies/{C7}/action", {"action": "approve"}, SA["owner"]))
    expect("I6.16 approved company works", call("GET", "/contacts", token=t7))
    mongo.platform_settings.update_one({"_id": "settings"}, {"$set": {"signup_needs_approval": False}})
    # reports, delete / restore / purge
    ov = expect("I6.17 reports", call("GET", "/sa/reports/overview", token=SA["owner"]))
    check("I6.17 report sections", all(k in ov for k in ("by_plan", "by_month", "churn", "trial_conversion", "feature_usage")))
    expect("I6.18 cancel needs a reason", call("POST", "/billing/cancel", {}, O6), 400)
    expect("I6.18 owner cancels", call("POST", "/billing/cancel", {"reason": "Too expensive"}, O6))
    check("I6.18 churn reason recorded", any(x["reason"] == "Too expensive" for x in call("GET", "/sa/reports/overview", token=SA["owner"])[1]["churn"]))
    expect("I6.19 delete", call("POST", f"/sa/companies/{C7}/action", {"action": "delete"}, SA["owner"]))
    expect("I6.19 deleted company signed out", call("GET", "/contacts", token=t7), 401)
    expect("I6.19 restore", call("POST", f"/sa/companies/{C7}/action", {"action": "restore"}, SA["owner"]))
    expect("I6.19 restored company works", call("GET", "/contacts", token=t7))
    expect("delete again", call("POST", f"/sa/companies/{C7}/action", {"action": "delete"}, SA["owner"]))
    mongo.companies.update_one({"_id": ObjectId(C7)}, {"$set": {"purge_after": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)}})
    expect("purge run", call("POST", "/sa/billing/run", {}, SA["owner"]))
    check("I6.19 purged after 30 days", mongo.companies.find_one({"_id": ObjectId(C7)}) is None and not mongo.users.find_one({"email": email7}))

    # ======================================= block 7 =======================================
    # --- calendar feed ---
    t_body = {"title": f"Pour slab {RUN}", "start": day(1), "end": day(3), "assignee_id": U["pm"]}
    expect("a task for the PM", call("POST", f"/projects/{PID}/stages/{S2}/tasks", t_body, T["owner"]), 201)
    link = expect("I7.1 calendar link", call("GET", "/calendar/link", token=T["pm"]))["url"]
    req = urllib.request.Request("http://localhost:5000" + link)
    with urllib.request.urlopen(req) as r_:
        ics, ctype = r_.read().decode(), r_.headers.get("Content-Type")
    check("I7.1 an iCalendar feed", ctype.startswith("text/calendar") and ics.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in ics, ctype)
    check("I7.1 the PM's task is in it", f"Pour slab {RUN}" in ics and f"DTSTART;VALUE=DATE:{day(1).replace('-', '')}" in ics)
    check("I7.1 the token never shows in user lists", "calendar_token" not in json.dumps(call("GET", "/users", token=T["owner"])[1]))
    new = expect("I7.1 reset the link", call("POST", "/calendar/link/reset", {}, T["pm"]))["url"]
    try:
        urllib.request.urlopen("http://localhost:5000" + link)
        old_ok = True
    except urllib.error.HTTPError as e_:
        old_ok = e_.code != 404
    check("I7.1 old link stops", not old_ok and new != link)
    # --- SMS with DLT templates ---
    sms_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"sms": 1}).get("sms")
    expect("I7.2 bad sender id", call("PUT", "/settings/sms", {"sender_id": "TOOLONG1"}, T["owner"]), 400)
    st7 = expect("I7.2 sandbox SMS", call("PUT", "/settings/sms", {"provider": "sandbox", "sender_id": "BLDSUT", "dlt_entity_id": "1201159000000000001"}, T["owner"]))
    check("I7.2 ready, no key shown", st7["ready"] and "auth_key" not in st7)
    expect("I7.2 bad DLT id", call("POST", "/message_templates", {"name": f"SMS {RUN}", "channel": "sms", "body": "Hi {{client}}", "dlt_template_id": "12"}, T["owner"]), 400)
    stp = expect("I7.2 SMS template with its DLT id", call("POST", "/message_templates", {"name": f"SMS {RUN}", "channel": "sms", "body": "Hi {{client}}, your site visit is confirmed.",
                                                                                     "dlt_template_id": "1207161234567890123"}, T["owner"]), 201)
    sm = expect("I7.2 SMS sent (sandbox)", call("POST", f"/message_templates/{stp['id']}/sms", {"contact_id": CLIENT, "text": "Hi Ira, your site visit is confirmed."}, T["owner"]), 201)
    check("I7.2 stored as an SMS", sm["channel"] == "sms" and sm["status"] in ("sent", "failed") and sm["dlt_template_id"] == "1207161234567890123", sm)
    expect("I7.2 live provider without a DLT id refused", (call("PUT", "/settings/sms", {"provider": "msg91", "auth_key": "k" * 20}, T["owner"]),
                                                           call("POST", "/message_templates", {"name": f"SMS2 {RUN}", "channel": "sms", "body": "Hello"}, T["owner"]))[0], 200)
    no_dlt = mongo.message_templates.find_one({"company_id": CID, "name": f"SMS2 {RUN}"})
    expect("I7.2 needs the DLT id", call("POST", f"/message_templates/{no_dlt['_id']}/sms", {"contact_id": CLIENT, "text": "Hello"}, T["owner"]), 400)
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"sms": sms_before}})
    mongo.message_templates.delete_many({"company_id": CID, "name": {"$regex": f"{RUN}$"}})
    # --- backups ---
    bk = expect("I7.3 backup now", call("POST", "/sa/backups/run", {}, SA["owner"]), 201)
    check("I7.3 backup ok", bk["status"] == "ok" and bk["documents"] > 0, bk)
    bl = expect("I7.3 backups list", call("GET", "/sa/backups", token=SA["owner"]))
    check("I7.3 listed with its collections", bl["backups"] and bl["backups"][0]["name"] == bk["last_name"] and bl["backups"][0]["collections"] > 10, bl["backups"][:1])
    check("I7.3 dashboard shows the last backup", call("GET", "/sa/dashboard", token=SA["owner"])[1]["health"]["backup_status"] == "ok")
    if "viewer" in SA:
        expect("I7.3 a viewer cannot run backups", call("POST", "/sa/backups/run", {}, SA["viewer"]), 403)
    # --- language ---
    expect("I7.4 unknown language", call("PUT", "/me/language", {"language": "xx"}, T["site"]), 400)
    expect("I7.4 site supervisor picks Hindi", call("PUT", "/me/language", {"language": "hi"}, T["site"]))
    check("I7.4 kept on the user", call("GET", "/auth/me", token=T["site"])[1]["user"].get("language") == "hi")
    expect("I7.4 portal user too", call("PUT", "/me/language", {"language": "hi"}, T["client"]))
    mongo.users.update_many({"email": {"$in": ["site@skyline.test", "client@skyline.test"]}}, {"$unset": {"language": ""}})

finally:
    # ---------------- clean up (KEEP=1 leaves the data for a look in the browser) ----------------
    pids = projects if not os.getenv("KEEP") else []
    if os.getenv("KEEP"):
        print("kept projects:", projects)
        leads, contacts_made = [], []
    for col in ("invoices", "receipts", "costs", "contracts", "change_orders", "reminders", "notifications", "project_events",
                "selections", "purchase_orders", "purchase_requests", "goods_receipts", "stock_moves", "attendance", "snags",
                "site_reports", "project_activity", "permits", "mood_boards", "rfqs", "vendor_bills", "messages"):
        mongo[col].delete_many({"company_id": CID, "project_id": {"$in": pids}})
    mongo.petty_cash.delete_many({"company_id": CID})
    mongo.costs.delete_many({"company_id": CID, "paid_from_float": True, "project_id": {"$in": pids}})
    mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
    for col in ("estimates", "proposals", "lead_receipts", "contracts", "followups"):
        mongo[col].delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    mongo.leads.delete_many({"_id": {"$in": [ObjectId(x) for x in leads]}})
    mongo.contacts.delete_many({"_id": {"$in": [ObjectId(x) for x in contacts_made]}})
    mongo.stock_moves.delete_many({"company_id": CID, "loc": {"$regex": "^w:"}})
    mongo.rate_library.delete_many({"company_id": CID, "name": {"$regex": f"{RUN}$"}})
    mongo.site_workers.delete_many({"company_id": CID, "name": {"$regex": f"{RUN}$"}})
    mongo.files.delete_many({"company_id": CID, "key": {"$in": keys}})
    for cid6 in (globals().get("signups") or []):  # block 6 companies
        for name in mongo.list_collection_names():
            mongo[name].delete_many({"company_id": cid6})
        mongo.companies.delete_one({"_id": ObjectId(cid6)})
        mongo.platform_invoices.delete_many({"company_id": cid6})
        mongo.sa_audit.delete_many({"target": cid6})
    mongo.plans.delete_many({"code": {"$regex": f"^tiny{RUN}"}})
    mongo.coupons.delete_many({"code": {"$regex": f"{RUN}$"}})
    mongo.announcements.delete_many({"title": {"$regex": f"{RUN}$"}})
    mongo.support_tickets.delete_many({"subject": {"$regex": f"{RUN}$"}})
    if "sa_before" in globals():
        if sa_before:
            mongo.platform_settings.replace_one({"_id": "settings"}, sa_before, upsert=True)
        else:
            mongo.platform_settings.delete_one({"_id": "settings"})
    restore = {k: company_before.get(k) for k in ("finance", "tax_mode", "state", "gstin", "warehouses", "markup_rules")}
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": restore})

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
