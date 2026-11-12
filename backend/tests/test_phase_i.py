"""Phase I — closing the gaps in the built modules. One section per block of PLAN.md Phase I.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_i.py
"""
import json
import os
import sys
import time
import urllib.error
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
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"finance": 1, "tax_mode": 1, "state": 1, "gstin": 1})
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

finally:
    # ---------------- clean up (KEEP=1 leaves the data for a look in the browser) ----------------
    pids = projects if not os.getenv("KEEP") else []
    if os.getenv("KEEP"):
        print("kept projects:", projects)
        leads, contacts_made = [], []
    for col in ("invoices", "receipts", "costs", "contracts", "change_orders", "reminders", "notifications", "project_events",
                "selections", "purchase_orders", "purchase_requests"):
        mongo[col].delete_many({"company_id": CID, "project_id": {"$in": pids}})
    mongo.petty_cash.delete_many({"company_id": CID})
    mongo.costs.delete_many({"company_id": CID, "paid_from_float": True, "project_id": {"$in": pids}})
    mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
    for col in ("estimates", "proposals", "lead_receipts", "contracts", "followups"):
        mongo[col].delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    mongo.leads.delete_many({"_id": {"$in": [ObjectId(x) for x in leads]}})
    mongo.contacts.delete_many({"_id": {"$in": [ObjectId(x) for x in contacts_made]}})
    restore = {k: company_before.get(k) for k in ("finance", "tax_mode", "state", "gstin")}
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": restore})

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
