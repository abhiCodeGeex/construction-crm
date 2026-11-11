"""Phase E — costs, budget control, invoices, receipts and change orders. One block per row of PLAN.md E1.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_e.py
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


def upload(name, token):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + b"\x89PNG\r\n\x1a\n" + b"0" * 64 + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "accounts", "designer", "sales", "estimator")}
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
finance_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"finance": 1}).get("finance")
projects, contacts, rates, leads, won_projects = [], [], [], [], []


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def costs(pid, who="owner"):
    return call("GET", f"/projects/{pid}/costs", token=T[who])[1]


def cost(pid, body, who="owner", status=201):
    return expect(f"cost by {who}: {body.get('description')}", call("POST", f"/projects/{pid}/costs", body, T[who]), status)


try:
    # ================= setup: a project with stage budgets, PM on the team, site supervisor viewing =================
    p = expect("project", call("POST", "/projects", {"name": f"Finance {RUN}", "services": ["construction"], "start": day(-30)}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    for who, role in (("pm", "Project Manager"), ("site", "Site Supervisor")):
        call("POST", f"/projects/{pid}/team", {"user_id": U[who], "project_role": role, "access": "edit" if who == "pm" else "view"}, T["owner"])
    s1, s2 = p["stages"][0], p["stages"][1]
    call("PUT", f"/projects/{pid}/stages/{s1['id']}", {"budget": 100000}, T["owner"])
    vend = expect("vendor", call("POST", "/contacts", {"name": f"Cement Co {RUN}", "kind": "company", "types": ["supplier"],
                                                       "phone": f"98{RUN}"}, T["owner"]), 201)
    contacts.append(vend["id"])
    plain = expect("non-vendor contact", call("POST", "/contacts", {"name": f"Friend {RUN}", "kind": "person", "types": ["client"],
                                                                    "phone": f"97{RUN}"}, T["owner"]), 201)
    contacts.append(plain["id"])
    base = {"stage_id": s1["id"], "category": "Material", "date": day(-1), "description": f"Cement {RUN}", "amount": 10000}

    # ================= §12 record a cost =================
    expect("unknown stage", call("POST", f"/projects/{pid}/costs", {**base, "stage_id": "nope"}, T["pm"]), 400)
    expect("bad category", call("POST", f"/projects/{pid}/costs", {**base, "category": "Snacks"}, T["pm"]), 400)
    expect("vendor must be a supplier etc.", call("POST", f"/projects/{pid}/costs", {**base, "vendor_id": plain["id"]}, T["pm"]), 400)
    expect("no future date", call("POST", f"/projects/{pid}/costs", {**base, "date": day(2)}, T["pm"]), 400)
    expect("amount required", call("POST", f"/projects/{pid}/costs", {**base, "amount": None}, T["pm"]), 400)
    expect("sales cannot record costs", call("POST", f"/projects/{pid}/costs", base, T["sales"]), 403)
    bill = upload(f"bill{RUN}.png", T["pm"])
    c1 = cost(pid, {**base, "vendor_id": vend["id"], "bill_no": "B-1", "files": [bill["key"]], "tax": 1800}, "pm")
    check("draft with vendor, bill and total", c1["status"] == "draft" and c1["vendor_name"] == vend["name"]
          and c1["files"][0]["key"] == bill["key"] and c1["total"] == 11800, c1)
    check("a draft is not actual", costs(pid)["budget"]["spent"] == 0)
    c1 = expect("PM on the team submits within budget: approved at once", call("POST", f"/costs/{c1['id']}/submit", {}, T["pm"]), 200)
    check("approved on submit", c1["status"] == "approved" and c1["approved_by_id"] == U["pm"], c1)
    expect("an approved cost cannot be edited", call("PUT", f"/costs/{c1['id']}", {"amount": 1}, T["pm"]), 409)
    expect("an approved cost cannot be deleted", call("DELETE", f"/costs/{c1['id']}", token=T["pm"]), 409)

    # ================= §4.7 budget vs actual, B+4 health =================
    view = costs(pid)
    row = next(r for r in view["budget"]["stages"] if r["id"] == s1["id"])
    check("stage spent and %", row["spent"] == 10000 and row["pct"] == 10 and row["level"] == "green", row)
    dash = call("GET", f"/projects/{pid}/dashboard", token=T["pm"])[1]
    check("dashboard actual and per-stage spent", dash["budget"]["actual"] == 10000
          and next(s for s in dash["stages"] if s["id"] == s1["id"])["spent"] == 10000, dash["budget"])
    sd = call("GET", f"/projects/{pid}/dashboard", token=T["site"])[1]
    check("site sees no budget on the dashboard", "budget" not in sd and "spent" not in sd["stages"][0], list(sd))
    h = call("GET", f"/projects/{pid}/health", token=T["owner"])[1]
    hb = next(x for x in h["parts"] if x["key"] == "budget")
    check("health budget part counts real costs", "within the budget" in hb["why"], hb)

    # ================= §12 approval: accounts, committed, reject =================
    c2 = cost(pid, {**base, "description": f"Steel {RUN}", "amount": 20000, "submit": True}, "accounts")
    check("accounts within budget: approved", c2["status"] == "approved")
    expect("designer (finance read) cannot record", call("POST", f"/projects/{pid}/costs", base, T["designer"]), 403)

    # ================= §12 site expense =================
    call("PUT", "/finance/settings", {"site_expense_limit": 3000}, T["owner"])
    expect("site expense over the limit", call("POST", f"/projects/{pid}/costs", {**base, "amount": 3500, "description": f"Tea {RUN}"}, T["site"]), 403)
    se = cost(pid, {**base, "amount": 1200, "description": f"Labour tea {RUN}", "category": "Material"}, "site")
    check("site expense: category forced and always waits", se["category"] == "Site expense" and se["status"] == "submitted"
          and se["kind"] == "site_expense", se)
    check("PM asked to approve", any(RUN in n["text"] and "Labour tea" in n["text"] for n in bell("pm", event="cost_approval")))
    sv = costs(pid, "site")
    check("site sees only their own entries, no budget", [c["id"] for c in sv["costs"]] == [se["id"]] and "budget" not in sv, sv.get("costs"))
    check("site's view of the committed figure", next(r for r in costs(pid)["budget"]["stages"] if r["id"] == s1["id"])["committed"] == 1200)
    expect("site cannot approve", call("POST", f"/costs/{se['id']}/approve", {}, T["site"]), 403)
    expect("reject needs a reason", call("POST", f"/costs/{se['id']}/reject", {}, T["pm"]), 400)
    rj = expect("PM rejects", call("POST", f"/costs/{se['id']}/reject", {"reason": "No bill"}, T["pm"]), 200)
    check("rejected and the site supervisor told", rj["status"] == "rejected" and any("No bill" in n["text"] for n in bell("site", event="cost_decided")))
    check("rejected is not counted", next(r for r in costs(pid)["budget"]["stages"] if r["id"] == s1["id"])["committed"] == 0)
    fixed = expect("site fixes the rejected expense", call("PUT", f"/costs/{se['id']}", {"bill_no": "T-9"}, T["site"]), 200)
    check("back to draft", fixed["status"] == "draft" and not fixed.get("reject_reason"))
    expect("site resubmits", call("POST", f"/costs/{se['id']}/submit", {}, T["site"]), 200)
    expect("PM approves the site expense", call("POST", f"/costs/{se['id']}/approve", {}, T["pm"]), 200)

    # ================= §12 budget alerts 80 % / 100 % and the over-budget reason =================
    cost(pid, {**base, "description": f"Bricks {RUN}", "amount": 50000, "submit": True}, "pm")  # 81,200 of 100,000
    a80 = [n for n in bell("pm", event="budget_alert") if f"Finance {RUN}" in n["text"]]
    check("80 %: managers told once", len(a80) == 1 and "81%" in a80[0]["text"], [n["text"] for n in a80])
    big = cost(pid, {**base, "description": f"Tiles {RUN}", "amount": 30000, "submit": True}, "pm")
    check("over budget: waits even for the PM", big["status"] == "submitted" and big["over_budget"] == 11200, big)
    check("over budget: owners asked too", any(f"Tiles {RUN}" in n["text"] for n in bell("owner", event="cost_approval")))
    expect("over budget needs a reason", call("POST", f"/costs/{big['id']}/approve", {}, T["pm"]), 400)
    ok = expect("approved with a reason", call("POST", f"/costs/{big['id']}/approve", {"overspend_reason": "client_change"}, T["pm"]), 200)
    check("reason and markup kept", ok["overspend_reason"] == "client_change" and ok["overspend_amount"] == 11200
          and ok["overspend_markup_pct"] == 10, ok)
    a100 = [n for n in bell("owner", event="budget_alert") if f"Finance {RUN}" in n["text"] and "over budget" in n["text"]]
    check("100 %: owners told", len(a100) == 1, [n["text"] for n in a100])

    # ================= E2 void, level drops back and is announced again =================
    expect("void needs owner / accounts", call("POST", f"/costs/{big['id']}/void", {"reason": "x"}, T["pm"]), 403)
    expect("void needs a reason", call("POST", f"/costs/{big['id']}/void", {}, T["accounts"]), 400)
    expect("accounts voids", call("POST", f"/costs/{big['id']}/void", {"reason": f"Duplicate bill {RUN}"}, T["accounts"]), 200)
    row = next(r for r in costs(pid)["budget"]["stages"] if r["id"] == s1["id"])
    check("void drops the level", row["spent"] == 81200 and row["level"] == "amber", row)
    cost(pid, {**base, "description": f"Sand {RUN}", "amount": 25000, "submit": True}, "pm")
    call("POST", f"/costs/{costs(pid)['costs'][0]['id']}/approve", {"overspend_reason": "price_rise"}, T["owner"])
    a100 = [n for n in bell("owner", event="budget_alert") if f"Finance {RUN}" in n["text"] and "over budget" in n["text"]]
    check("crossing 100 % again is announced again", len(a100) == 2, [n["text"] for n in a100])

    # ================= §12 learn from it: rate library =================
    rate = expect("rate item", call("POST", "/rates", {"kind": "material", "name": f"OPC cement {RUN}", "unit": "bag", "rate": 400}, T["estimator"]), 201)
    rates.append(rate["id"])
    for i, amt in enumerate((4200, 4400, 4600)):
        cost(pid, {**base, "stage_id": s2["id"], "description": f"Cement lot {i} {RUN}", "amount": amt, "qty": 10, "rate_id": rate["id"], "submit": True}, "pm")
    r = mongo.rate_library.find_one({"_id": ObjectId(rate["id"])})
    check("actuals kept, suggestion after 3, rate unchanged", len(r["actuals"]) == 3 and r["suggested_rate"] == 440 and r["rate"] == 400, r)
    expect("designer (proposals read) cannot use the suggestion", call("POST", f"/rates/{rate['id']}/use-suggested", {}, T["designer"]), 403)
    used = expect("estimator uses the suggestion", call("POST", f"/rates/{rate['id']}/use-suggested", {}, T["estimator"]), 200)
    check("rate updated", used["rate"] == 440)

    # ================= access and the money trail =================
    expect("company cost list for accounts", call("GET", f"/finance/costs?project_id={pid}", token=T["accounts"]), 200)
    expect("site cannot list company costs", call("GET", "/finance/costs", token=T["site"]), 403)
    acts = call("GET", f"/projects/{pid}/activity", token=T["site"])[1]
    check("site's timeline has no cost entries", not [a for a in acts["rows"] if a["kind"] == "cost"] and "Money" not in acts["groups"])
    check("owner's timeline has them", any(a["kind"] == "cost" for a in call("GET", f"/projects/{pid}/activity?group=Money", token=T["owner"])[1]["rows"]))
    expect("a project with approved costs cannot be deleted", call("DELETE", f"/projects/{pid}", token=T["owner"]), 409)

    # ================= block 2 · invoices =================
    tax_rate = float(mongo.companies.find_one({"_id": ObjectId(CID)}).get("tax_rate") or 0)
    s_, L = call("POST", "/leads", {"title": f"PE {RUN}", "service": "construction", "source": "Walk-in", "contact_name": f"PE Client {RUN}",
                                    "contact_phone": f"6{RUN[-7:]}55", "contact_email": f"pe{RUN}@example.test", "budget": 3000000}, T["sales"])
    assert s_ == 201, L
    leads.append(L["id"])
    contacts.append(L["contact_id"])
    pr = expect("simple proposal", call("POST", f"/leads/{L['id']}/proposals", {"value": 590000, "valid_until": day(10)}, T["sales"]), 201)
    call("POST", f"/proposals/{pr['id']}/send", {"channel": "in_person"}, T["sales"])
    expect("accepted on paper", call("POST", f"/proposals/{pr['id']}/respond", {"result": "accepted", "signed_by": "Mr PE"}, T["sales"]), 200)
    con = mongo.contracts.find_one({"company_id": CID, "proposal_id": pr["id"]})
    CON = str(con["_id"])
    sched = con["payment_schedule"]
    check("schedule rows add up to the contract", abs(sum(r["amount"] for r in sched) - con["value"]) < 0.05, sched)
    sign_row = next(r for r in sched if r["trigger"] == "signing")
    stage_row = next(r for r in sched if r["trigger"] == "stage")

    # §5 invoice the advance on signing before the project exists
    expect("PM cannot invoice before the project exists", call("POST", f"/contracts/{CON}/schedule/{sign_row['id']}/invoice", {}, T["pm"]), 403)
    adv = expect("accounts invoices the advance on signing", call("POST", f"/contracts/{CON}/schedule/{sign_row['id']}/invoice", {}, T["accounts"]), 201)
    check("draft: no number yet, amount = the row, tax split in the contract's ratio", adv["number"] is None and adv["status"] == "draft"
          and abs(adv["total"] - sign_row["amount"]) < 0.02 and abs(adv["subtotal"] + adv["tax"] - adv["total"]) < 0.02
          and abs(adv["subtotal"] / adv["total"] - con["totals"]["taxable"] / con["totals"]["total"]) < 0.001, adv)
    check("client details on the invoice", adv["client_name"] == f"PE Client {RUN}" and adv["client_email"] == f"pe{RUN}@example.test", adv)
    expect("a row is invoiced once", call("POST", f"/contracts/{CON}/schedule/{sign_row['id']}/invoice", {}, T["owner"]), 409)

    w = expect("lead won with an advance", call("POST", f"/leads/{L['id']}/win", {"pm_id": U["pm"], "advance": {
        "kind": "Token / booking advance", "amount": 20000, "date": day(0), "mode": "UPI", "reference": f"UPI{RUN}"}}, T["sales"]), 200)
    WP = w["project_id"]
    won_projects.append(WP)
    pi = call("GET", f"/projects/{WP}/invoices", token=T["pm"])[1]
    check("the pre-win invoice joined the project", [i["id"] for i in pi["invoices"]] == [adv["id"]] and pi["invoices"][0]["project_id"] == WP, pi["invoices"])
    rows = {r["id"]: r for r in pi["contract"]["payment_schedule"]}
    check("schedule shows the invoiced row and the upcoming stage row", rows[sign_row["id"]].get("status") == "invoiced"
          and rows[stage_row["id"]].get("state") == "upcoming", rows[stage_row["id"]])
    expect("site cannot see invoices", call("GET", f"/projects/{WP}/invoices", token=T["site"]), 403)

    # §5 upcoming rows: only the Owner, with a reason
    expect("PM cannot invoice an upcoming row", call("POST", f"/contracts/{CON}/schedule/{stage_row['id']}/invoice", {}, T["pm"]), 409)
    expect("Owner needs a reason to invoice early", call("POST", f"/contracts/{CON}/schedule/{stage_row['id']}/invoice", {}, T["owner"]), 409)
    early = expect("Owner invoices early with a reason", call("POST", f"/contracts/{CON}/schedule/{stage_row['id']}/invoice",
                                                             {"early_reason": f"Client asked {RUN}"}, T["owner"]), 201)
    check("early reason kept", early["early_reason"] == f"Client asked {RUN}")
    expect("delete the early draft", call("DELETE", f"/invoices/{early['id']}", token=T["owner"]), 200)
    rows = {r["id"]: r for r in call("GET", f"/projects/{WP}/invoices", token=T["pm"])[1]["contract"]["payment_schedule"]}
    check("deleting the draft frees the row", rows[stage_row["id"]].get("status") is None and rows[stage_row["id"]]["state"] == "upcoming")

    # sending issues the number
    sent = expect("send the advance invoice", call("POST", f"/invoices/{adv['id']}/send", {}, T["accounts"]), 200)
    check("number issued on send", sent["status"] == "sent" and sent["number"] and sent["number"].startswith("INV"), sent.get("number"))
    expect("a sent invoice is not edited", call("PUT", f"/invoices/{adv['id']}", {"notes": "x"}, T["accounts"]), 409)
    expect("a sent invoice is not deleted", call("DELETE", f"/invoices/{adv['id']}", token=T["accounts"]), 409)
    expect("sent twice", call("POST", f"/invoices/{adv['id']}/send", {}, T["accounts"]), 409)

    # the stage milestone is achieved -> the row is due
    pj = call("GET", f"/projects/{WP}", token=T["owner"])[1]
    st = next(s for s in pj["stages"] if s["name"] == stage_row["stage"])
    expect("owner closes the stage", call("PUT", f"/projects/{WP}/milestones/{st['gate']['milestone_id']}",
                                          {"status": "achieved", "override_reason": f"Test {RUN}"}, T["owner"]), 200)
    due = expect("PM invoices the now-due stage row", call("POST", f"/contracts/{CON}/schedule/{stage_row['id']}/invoice", {}, T["pm"]), 201)
    due = expect("PM sends it", call("POST", f"/invoices/{due['id']}/send", {}, T["pm"]), 200)

    # manual invoice
    expect("manual: lines required", call("POST", f"/projects/{WP}/invoices", {"lines": []}, T["pm"]), 400)
    expect("manual: due before date", call("POST", f"/projects/{WP}/invoices", {"lines": [{"description": "x", "qty": 1, "rate": 1}],
                                                                                 "date": day(0), "due_date": day(-1)}, T["pm"]), 400)
    man = expect("manual invoice", call("POST", f"/projects/{WP}/invoices", {"lines": [{"description": f"Extra window {RUN}", "qty": 2, "rate": 1000},
                                                                                        {"description": "Exempt", "qty": 1, "rate": 500, "tax_pct": 0}]}, T["pm"]), 201)
    check("company tax on lines unless set", man["subtotal"] == 2500 and abs(man["tax"] - 2000 * tax_rate / 100) < 0.02, man)
    man = expect("edit the draft lines", call("PUT", f"/invoices/{man['id']}", {"lines": [{"description": f"Extra window {RUN}", "qty": 3, "rate": 1000}]}, T["pm"]), 200)
    check("totals recomputed", man["subtotal"] == 3000)
    expect("schedule invoice lines are fixed", call("PUT", f"/invoices/{due['id']}", {"lines": [{"description": "x", "qty": 1, "rate": 1}]}, T["pm"]), 409)
    man = expect("send manual", call("POST", f"/invoices/{man['id']}/send", {}, T["pm"]), 200)

    # credit note
    expect("credit note above the invoice", call("POST", f"/invoices/{man['id']}/credit-note", {"amount": man["total"] + 1, "reason": "x"}, T["accounts"]), 400)
    expect("credit note needs a reason", call("POST", f"/invoices/{man['id']}/credit-note", {"amount": 100}, T["accounts"]), 400)
    cn = expect("credit note", call("POST", f"/invoices/{man['id']}/credit-note", {"amount": 1000, "reason": f"One window less {RUN}"}, T["accounts"]), 201)
    check("credit note numbered CRN, tax split", cn["number"].startswith("CRN") and cn["kind"] == "credit_note"
          and abs(cn["subtotal"] + cn["tax"] - 1000) < 0.02, cn)
    mi = call("GET", f"/invoices/{man['id']}", token=T["accounts"])[1]
    check("invoice balance after the credit", mi["credited"] == 1000 and abs(mi["balance"] - (man["total"] - 1000)) < 0.02
          and mi["credit_notes"][0]["id"] == cn["id"], mi)

    # void
    expect("PM cannot void", call("POST", f"/invoices/{due['id']}/void", {"reason": "x"}, T["pm"]), 403)
    expect("credited invoice cannot be voided", call("POST", f"/invoices/{man['id']}/void", {"reason": "x"}, T["accounts"]), 409)
    expect("void needs a reason", call("POST", f"/invoices/{due['id']}/void", {}, T["accounts"]), 400)
    expect("accounts voids", call("POST", f"/invoices/{due['id']}/void", {"reason": f"Wrong stage {RUN}"}, T["accounts"]), 200)
    rows = {r["id"]: r for r in call("GET", f"/projects/{WP}/invoices", token=T["pm"])[1]["contract"]["payment_schedule"]}
    check("void frees the row, which is due again", rows[stage_row["id"]].get("status") is None and rows[stage_row["id"]]["state"] == "due")
    allinv = call("GET", f"/invoices?project_id={WP}", token=T["accounts"])[1]
    check("company invoice list", {i["kind"] for i in allinv} == {"schedule", "manual", "credit_note"}, [i["kind"] for i in allinv])
    expect("a project with sent invoices cannot be deleted", call("DELETE", f"/projects/{WP}", token=T["owner"]), 409)

    # ================= block 3 · receipts, advances, receivables, reminders =================
    rv = call("GET", f"/projects/{WP}/receipts", token=T["accounts"])[1]
    advance = next(a for a in rv["advances"] if a["amount"] == 20000)
    check("the lead's advance is listed on the project", advance["number"].startswith("RCT") and not advance.get("applied_invoice_id"), rv["advances"])
    expect("an advance needs an open invoice", call("POST", f"/lead_receipts/{advance['id']}/apply", {"invoice_id": cn["id"]}, T["accounts"]), 400)
    ap = expect("apply the advance to the advance-on-signing invoice", call("POST", f"/lead_receipts/{advance['id']}/apply", {"invoice_id": adv["id"]}, T["accounts"]), 200)
    check("part paid by the advance", ap["status"] == "part_paid" and ap["paid"] == 20000 and ap["payments"][0]["kind"] == "advance", ap)
    expect("an advance is applied once", call("POST", f"/lead_receipts/{advance['id']}/apply", {"invoice_id": man["id"]}, T["accounts"]), 409)
    expect("an applied advance cannot be voided", call("POST", f"/lead_receipts/{advance['id']}/void", {"reason": "x"}, T["owner"]), 409)

    left_adv = ap["balance"]
    man_now = call("GET", f"/invoices/{man['id']}", token=T["accounts"])[1]
    body = {"amount": left_adv + 500, "date": day(0), "mode": "Bank transfer", "reference": f"NEFT{RUN}",
            "allocations": [{"invoice_id": adv["id"], "amount": left_adv}, {"invoice_id": man["id"], "amount": 500}]}
    expect("bad mode", call("POST", f"/projects/{WP}/receipts", {**body, "mode": "Barter"}, T["accounts"]), 400)
    expect("no future receipt", call("POST", f"/projects/{WP}/receipts", {**body, "date": day(1)}, T["accounts"]), 400)
    expect("reference for non-cash", call("POST", f"/projects/{WP}/receipts", {**body, "reference": ""}, T["accounts"]), 400)
    expect("allocations required", call("POST", f"/projects/{WP}/receipts", {**body, "allocations": []}, T["accounts"]), 400)
    expect("allocate the whole amount", call("POST", f"/projects/{WP}/receipts", {**body, "amount": left_adv + 600}, T["accounts"]), 400)
    expect("not more than the balance", call("POST", f"/projects/{WP}/receipts", {**body, "amount": left_adv + 1, "allocations": [
        {"invoice_id": adv["id"], "amount": left_adv + 1}]}, T["accounts"]), 400)
    expect("each invoice once", call("POST", f"/projects/{WP}/receipts", {**body, "allocations": [
        {"invoice_id": man["id"], "amount": 250}, {"invoice_id": man["id"], "amount": 250}], "amount": 500}, T["accounts"]), 400)
    expect("a credit note is not paid", call("POST", f"/projects/{WP}/receipts", {**body, "amount": 500, "allocations": [
        {"invoice_id": cn["id"], "amount": 500}]}, T["accounts"]), 400)
    expect("site cannot record receipts", call("POST", f"/projects/{WP}/receipts", body, T["site"]), 403)
    rc = expect("one payment settles two invoices", call("POST", f"/projects/{WP}/receipts", body, T["accounts"]), 201)
    a2 = call("GET", f"/invoices/{adv['id']}", token=T["accounts"])[1]
    m2 = call("GET", f"/invoices/{man['id']}", token=T["accounts"])[1]
    check("receipt numbered RCT", rc["number"].startswith("RCT") and len(rc["allocations"]) == 2)
    check("advance invoice paid", a2["status"] == "paid" and a2["balance"] == 0, (a2["status"], a2["balance"]))
    check("manual invoice part paid", m2["status"] == "part_paid" and abs(m2["balance"] - (man_now["balance"] - 500)) < 0.02, (m2["status"], m2["balance"]))
    rows = {r["id"]: r for r in call("GET", f"/projects/{WP}/invoices", token=T["pm"])[1]["contract"]["payment_schedule"]}
    check("the contract payment shows paid", rows[sign_row["id"]].get("status") == "paid", rows[sign_row["id"]])
    check("PM told of the payment", any(rc["number"] in n["text"] for n in bell("pm", event="receipt_recorded")))
    expect("a paid invoice cannot be voided", call("POST", f"/invoices/{adv['id']}/void", {"reason": "x"}, T["accounts"]), 409)
    expect("credit note limited to what is left to pay", call("POST", f"/invoices/{man['id']}/credit-note",
                                                           {"amount": m2["balance"] + 1, "reason": "x"}, T["accounts"]), 400)

    unpaid = call("GET", "/invoices?status=unpaid", token=T["accounts"])[1]
    check("unpaid list has the part-paid invoice, not the paid one", man["id"] in [i["id"] for i in unpaid] and adv["id"] not in [i["id"] for i in unpaid])
    rec = call("GET", "/finance/receivables", token=T["accounts"])[1]
    mine = next(r for r in rec["rows"] if r["id"] == man["id"])
    check("receivables: balance in the not-yet-due bucket", mine["bucket"] == "current" and abs(mine["balance"] - m2["balance"]) < 0.02
          and any(b["key"] == "current" and b["total"] >= m2["balance"] for b in rec["buckets"]), mine)
    check("receivables by client", any(c["client"] == f"PE Client {RUN}" for c in rec["by_client"]))
    expect("site cannot see receivables", call("GET", "/finance/receivables", token=T["site"]), 403)

    # overdue reminders
    mongo.invoices.update_one({"_id": ObjectId(man["id"])}, {"$set": {"due_date": day(-8)}})
    worker()
    worker()
    late = [n for n in bell("accounts", event="invoice_overdue") if man_now["number"] in n["text"]]
    check("overdue: accounts told once", len(late) == 1, [n["text"] for n in late])
    check("overdue: the project's PM told", any(man_now["number"] in n["text"] for n in bell("pm", event="invoice_overdue")))
    check("7 days late: owners told", any("days overdue" in n["text"] and man_now["number"] in n["text"] for n in bell("owner", event="invoice_overdue")))
    check("a paid invoice is never chased", not [n for n in bell("accounts") if a2["number"] in n["text"] and n["event"] in ("invoice_due", "invoice_overdue")])
    rec = call("GET", "/finance/receivables", token=T["accounts"])[1]
    check("receivables: now 1-30 days late", next(r for r in rec["rows"] if r["id"] == man["id"])["bucket"] == "d30")

    # void a receipt
    expect("PM cannot void a receipt", call("POST", f"/receipts/{rc['id']}/void", {"reason": "x"}, T["pm"]), 403)
    expect("void needs a reason", call("POST", f"/receipts/{rc['id']}/void", {}, T["accounts"]), 400)
    expect("accounts voids the receipt", call("POST", f"/receipts/{rc['id']}/void", {"reason": f"Bounced {RUN}"}, T["accounts"]), 200)
    a3 = call("GET", f"/invoices/{adv['id']}", token=T["accounts"])[1]
    m3 = call("GET", f"/invoices/{man['id']}", token=T["accounts"])[1]
    check("void takes the money back", a3["status"] == "part_paid" and a3["paid"] == 20000 and m3["status"] == "sent" and m3["paid"] == 0,
          (a3["status"], a3["paid"], m3["status"], m3["paid"]))
    rows = {r["id"]: r for r in call("GET", f"/projects/{WP}/invoices", token=T["pm"])[1]["contract"]["payment_schedule"]}
    check("the contract payment is back to invoiced", rows[sign_row["id"]].get("status") == "invoiced")
    expect("voided twice", call("POST", f"/receipts/{rc['id']}/void", {"reason": "x"}, T["accounts"]), 409)
finally:
    for c in mongo.costs.find({"company_id": CID, "project_id": {"$in": projects}}):
        mongo.costs.update_one({"_id": c["_id"]}, {"$set": {"status": "void"}})
    mongo.invoices.delete_many({"company_id": CID, "$or": [{"project_id": {"$in": projects + won_projects}}, {"lead_id": {"$in": leads}}]})
    mongo.receipts.delete_many({"company_id": CID, "project_id": {"$in": projects + won_projects}})
    for p_ in projects + won_projects:
        call("DELETE", f"/projects/{p_}", token=T["owner"])
        mongo.followups.delete_many({"company_id": CID, "related.id": p_})
    mongo.contracts.delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    mongo.lead_receipts.update_many({"company_id": CID, "lead_id": {"$in": leads}}, {"$set": {"status": "void"}})
    for l_ in leads:
        call("DELETE", f"/leads/{l_}", token=T["owner"])
        mongo.followups.delete_many({"company_id": CID, "related.id": l_})
        mongo.notifications.delete_many({"company_id": CID, "lead_id": l_})
    for c_ in contacts:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    for r_ in rates:
        mongo.rate_library.delete_one({"_id": ObjectId(r_)})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"finance": finance_before}} if finance_before else {"$unset": {"finance": ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.costs.count_documents({"company_id": CID, "description": {"$regex": RUN}}) + \
        mongo.leads.count_documents({"company_id": CID, "title": f"PE {RUN}"}) + mongo.invoices.count_documents({"company_id": CID, "lead_id": {"$in": leads}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
