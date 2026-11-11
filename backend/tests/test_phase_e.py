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
projects, contacts, rates = [], [], []


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
finally:
    for c in mongo.costs.find({"company_id": CID, "project_id": {"$in": projects}}):
        mongo.costs.update_one({"_id": c["_id"]}, {"$set": {"status": "void"}})
    for p_ in projects:
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for c_ in contacts:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    for r_ in rates:
        mongo.rate_library.delete_one({"_id": ObjectId(r_)})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"finance": finance_before}} if finance_before else {"$unset": {"finance": ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.costs.count_documents({"company_id": CID, "description": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
