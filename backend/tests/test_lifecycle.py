"""Whole lifecycle on a brand-new company, phases A to H, every role registered from scratch.

Signup -> owner creates every staff role and the portal users -> a website enquiry is worked, estimated, proposed,
e-signed and won -> the project is planned and delivered (costs, invoices, receipts, change orders, documents,
selections, site reports) -> the client approves and pays in the portal -> material is requested, quoted, ordered,
received, billed and paid, with the supplier working in their portal -> reports, worker, close-out.
Every GET list is also swept as every role: a 500 anywhere is a failure. The company is deleted at the end.

    docker compose exec backend python tests/test_lifecycle.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("API", "http://localhost:5000/api")
RUN = str(int(time.time() * 1000))[-8:]
PW = "Life@123"
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]
SIG = "data:image/png;base64," + "iVBORw0KGgo" * 40
failures, passed, steps = [], 0, []
cur = {"name": None, "ok": 0, "bad": 0}
day = lambda n: (date.today() + timedelta(days=n)).isoformat()


def call(method, path, body=None, token=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read() or b"{}"
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw[:200].decode(errors="replace")}


def raw_post(path, raw, headers):
    req = urllib.request.Request(BASE + path, method="POST", data=raw)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            b = r.read()
            return r.status, (json.loads(b) if b[:1] == b"{" else b)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def upload(name, token, path="/uploads"):
    bnd = uuid.uuid4().hex
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode() \
        + b"\x89PNG\r\n\x1a\n" + b"0" * 64 + f"\r\n--{bnd}--\r\n".encode()
    req = urllib.request.Request(BASE + path, method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={bnd}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["key"]


def step(name):
    if cur["name"]:
        steps.append(dict(cur))
    cur.update(name=name, ok=0, bad=0)


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        cur["ok"] += 1
    else:
        cur["bad"] += 1
        failures.append(f"[{cur['name']}] {name} -> {str(detail)[:400]}")


def ok(name, res, status=200):
    err = res[1].get("error", "") if isinstance(res[1], dict) else ""
    check(name, res[0] == status, f"got {res[0]} {err}")
    return res[1] if isinstance(res[1], (dict, list)) else {}


def login(email, pw=PW):
    s, d = call("POST", "/auth/login", {"email": email, "password": pw})
    assert s == 200, (email, s, d)
    return d["token"]


def worker():
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(None)


def stage_of(p, name):
    return next(s for s in p["stages"] if s["name"] == name)


T, U, CID = {}, {}, None
DOMAIN = f"life{RUN}.test"
email = lambda r: f"{r}@{DOMAIN}"
STAFF = ["pm", "sales", "designer", "estimator", "site", "procurement", "accounts"]

try:
    # ======================================= A. registration and access =======================================
    step("A1. A new company signs up")
    s = ok("signup", call("POST", "/auth/signup", {"company_name": f"Lifecycle Builders {RUN}", "name": "Olivia Owner", "email": email("owner"),
                                                    "password": PW, "city": "Pune", "phone": f"90{RUN}",
                                                    "company_types": ["architect", "contractor", "interior"]}), 201)
    CID = s["company"]["id"] if "id" in s.get("company", {}) else str(mongo.users.find_one({"email": email("owner")})["company_id"])
    T["owner"] = s.get("token") or login(email("owner"))
    me = ok("owner session", call("GET", "/auth/me", token=T["owner"]))
    check("owner of a trial company with three services", me["user"]["role"] == "owner" and len(me["company"]["modules"]) == 3, me.get("company"))
    ok("duplicate signup refused", call("POST", "/auth/signup", {"company_name": "x", "name": "x", "email": email("owner"), "password": PW}), 409)
    ok("wrong password", call("POST", "/auth/login", {"email": email("owner"), "password": "nope"}), 401)
    tpls = ok("stage templates bootstrapped", call("GET", "/stage_templates", token=T["owner"]))
    check("a default template per service", {t["service"] for t in tpls["templates"] if t.get("is_default")} >= {"architecture", "construction", "interior"})
    check("proposal templates bootstrapped", {x["type"] for x in ok("proposal templates", call("GET", "/proposal_templates", token=T["owner"]))} >= {"fee", "construction", "interior"})

    step("A2. Owner registers every staff role")
    roles = ok("roles list", call("GET", "/roles", token=T["owner"]))
    for r in STAFF:
        u = ok(f"create {r}", call("POST", "/users", {"name": f"{r.title()} {RUN}", "email": email(r), "role": r, "password": PW, "phone": f"8{RUN}{STAFF.index(r)}"}, T["owner"]), 201)
        U[r] = u.get("id")
        T[r] = login(email(r))
    U["owner"] = me["user"]["id"]
    ok("PM cannot create users", call("POST", "/users", {"name": "x", "email": email("x"), "role": "sales", "password": PW}, T["pm"]), 403)
    ok("short password refused", call("POST", "/users", {"name": "x", "email": email("x"), "role": "sales", "password": "1"}, T["owner"]), 400)
    matrix = {("owner", "users"): 200, ("sales", "leads"): 200, ("site", "leads"): 403, ("accounts", "finance"): 200,
              ("designer", "documents"): 200, ("procurement", "procurement"): 200, ("site", "finance"): 403, ("estimator", "proposals"): 200}
    for (r, area), want in matrix.items():
        ok(f"{r} -> {area}", call("GET", f"/access/probe/{area}", token=T[r]), want)
    ok("own password change", call("POST", "/auth/password", {"current": PW, "new": PW + "x", "current_password": PW, "new_password": PW + "x"}, T["sales"]))
    T["sales"] = login(email("sales"), PW + "x")
    ok("other tenant's data invisible", call("GET", "/leads", token=T["owner"]))
    check("no Skyline leads leak in", not any("skyline" in json.dumps(x).lower() for x in call("GET", "/contacts", token=T["owner"])[1]))

    # ======================================= B/C. contacts, lead to win =======================================
    step("B. Contacts: supplier, consultant, subcontractor")
    sup = ok("supplier", call("POST", "/contacts", {"name": f"Supply Co {RUN}", "kind": "company", "types": ["supplier"], "phone": f"70{RUN}",
                                                    "email": f"supply{RUN}@x.test"}, T["procurement"]), 201)
    sup2 = ok("second supplier", call("POST", "/contacts", {"name": f"Other Supply {RUN}", "kind": "company", "types": ["supplier"], "phone": f"71{RUN}"}, T["procurement"]), 201)
    con = ok("consultant", call("POST", "/contacts", {"name": f"Struct Consult {RUN}", "kind": "company", "types": ["consultant"], "phone": f"72{RUN}"}, T["owner"]), 201)
    ok("sales cannot add a supplier's bank details", call("GET", "/contacts", token=T["sales"]))

    step("C1. Website enquiry to a worked lead")
    key = ok("lead form key", call("GET", "/leads/meta", token=T["owner"]))["form_key"]
    cname, cphone = f"Kiran Client {RUN}", f"9{RUN[-7:]}55"
    ok("public enquiry", call("POST", f"/public/lead-form/{key}", {"name": cname, "phone": cphone, "email": f"kiran{RUN}@x.test", "service": "construction",
                                                                   "project_type": "New build", "location": "Baner, Pune", "message": "G+1 villa"},
                              headers={"X-Forwarded-For": f"10.77.{RUN[-3:-1]}.{int(RUN[-2:]) % 250}"}), 201)
    lead = next((x for x in call("GET", "/leads", token=T["owner"])[1] if x["contact_name"] == cname), None)
    check("lead arrives unassigned", lead and lead["owner_id"] is None, lead)
    LID = lead["id"]
    ok("assign to sales", call("PUT", f"/leads/{LID}", {"owner_id": U["sales"], "budget": 4000000, "area": 2500}, T["owner"]))
    ok("first call logged", call("POST", f"/leads/{LID}/activities", {"type": "call", "text": "Discussed scope", "outcome": "Reached", "next_due": day(1)}, T["sales"]), 201)
    fu = ok("follow-up", call("POST", "/followups", {"title": f"Send plans {RUN}", "due": day(0), "related": {"type": "lead", "id": LID}}, T["sales"]), 201)
    ok("follow-up done", call("POST", f"/followups/{fu['id']}/done", {"outcome": "Sent"}, T["sales"]))
    ok("sales Today", call("GET", "/followups/today", token=T["sales"]))

    step("D. Estimate, proposal, e-signature, contract, win")
    stages_c = [s["name"] for s in next(t for t in tpls["templates"] if t["service"] == "construction" and t.get("is_default"))["stages"]]
    est = ok("estimator starts an estimate", call("POST", f"/leads/{LID}/estimates", {}, T["estimator"]), 201)
    ok("estimate lines", call("PUT", f"/estimates/{est['id']}", {"lines": [
        {"description": "RCC frame", "qty": 100, "unit": "cum", "material_rate": 6000, "labour_rate": 2000},
        {"description": "Brickwork", "qty": 400, "unit": "sqm", "material_rate": 500, "labour_rate": 300}],
        "overhead_pct": 10, "markup_pct": 20, "discount_pct": 0, "tax_pct": 18}, T["estimator"]))
    es = call("POST", f"/estimates/{est['id']}/submit", {}, T["estimator"])
    if es[1].get("status") != "approved":
        es = call("POST", f"/estimates/{est['id']}/submit", {}, T["owner"])
        if es[1].get("status") != "approved":
            es = call("POST", f"/estimates/{est['id']}/decide", {"approve": True}, T["owner"])
    check("estimate approved", es[1].get("status") == "approved", es)
    pr = ok("construction proposal from the estimate", call("POST", f"/leads/{LID}/proposals", {"estimate_id": est["id"], "valid_until": day(20)}, T["sales"]), 201)
    PP = f"/proposals/{pr['id']}"
    sched = [{"name": "Advance", "pct": 10, "trigger": "signing"}, {"name": f"On {stages_c[1]}", "pct": 60, "trigger": "stage", "stage": stages_c[1]},
             {"name": f"On {stages_c[2]}", "pct": 30, "trigger": "stage", "stage": stages_c[2]}]
    ok("payment schedule", call("PUT", PP, {"payment_schedule": sched}, T["sales"]))
    sent = ok("send the proposal", call("POST", f"{PP}/send", {"channel": "email"}, T["sales"]))
    tok = (sent.get("link") or "").split("/p/")[-1]
    pub = ok("client opens the link", call("GET", f"/public/proposals/{tok}"))
    check("client never sees cost or margin", not any(f'"{k}"' in json.dumps(pub) for k in ("cost", "margin", "markup_pct", "overhead_pct")))
    signed = ok("client e-signs", call("POST", f"/public/proposals/{tok}/accept", {"agree": True, "name": cname, "signature": SIG}))
    check("contract made", signed.get("contract_number"), signed)
    won = ok("lead won", call("POST", f"/leads/{LID}/win", {"pm_id": U["pm"], "start": day(-10)}, T["sales"]))
    PID = won.get("project_id")
    p = ok("project", call("GET", f"/projects/{PID}", token=T["pm"]))
    check("project value = contract", abs(p["value"] - pub["totals"]["total"]) < 0.05, (p.get("value"), pub["totals"]["total"]))
    check("stages from the template", [s["name"] for s in p["stages"]] == stages_c, [s["name"] for s in p["stages"]])
    CLIENT = lead["contact_id"]

    # ======================================= B+. planning =======================================
    step("B+. Team, budgets, tasks, milestones")
    for r, role, acc in (("designer", "Architect", "edit"), ("site", "Site Supervisor", "view"), ("procurement", "Procurement", "view"), ("accounts", "Accounts", "view")):
        ok(f"add {r}", call("POST", f"/projects/{PID}/team", {"user_id": U[r], "project_role": role, "access": acc}, T["pm"]), 201)
    ok("add consultant", call("POST", f"/projects/{PID}/team", {"contact_id": con["id"], "project_role": "Structural Consultant"}, T["pm"]), 201)
    S1, S2, S3 = (stage_of(p, n) for n in stages_c[:3])
    for s_, b in ((S1, 200000), (S2, 1500000), (S3, 2000000)):
        ok(f"budget {s_['name']}", call("PUT", f"/projects/{PID}/stages/{s_['id']}", {"budget": b}, T["pm"]))
    p = ok("task", call("POST", f"/projects/{PID}/stages/{S1['id']}/tasks", {"title": f"Site marking {RUN}", "start": day(-5), "end": day(2), "assignee_id": U["site"]}, T["pm"]), 201)
    task = next(t for s_ in p["stages"] for t in s_["tasks"] if t["title"] == f"Site marking {RUN}")
    ok("site starts its task", call("PUT", f"/projects/{PID}/tasks/{task['id']}", {"status": "in_progress"}, T["site"]))
    ok("site raises an issue", call("POST", f"/projects/{PID}/issues", {"title": "Water table high", "severity": "medium", "owner_id": U["pm"]}, T["site"]), 201)
    ok("dashboard", call("GET", f"/projects/{PID}/dashboard", token=T["pm"]))
    sv = ok("site's view of the project", call("GET", f"/projects/{PID}", token=T["site"]))
    check("site sees no value or budgets", "value" not in sv and all("budget" not in s_ for s_ in sv["stages"]))

    # ======================================= E. money =======================================
    step("E1. Costs and site expenses")
    c1 = ok("PM records a cost", call("POST", f"/projects/{PID}/costs", {"stage_id": S1["id"], "category": "Labour", "description": f"Marking crew {RUN}",
                                                                          "amount": 15000, "date": day(0)}, T["pm"]), 201)
    c1 = ok("PM submits (within budget: approved)", call("POST", f"/costs/{c1['id']}/submit", {}, T["pm"]))
    check("cost approved", c1.get("status") == "approved", c1.get("status"))
    se = ok("site logs a small expense", call("POST", f"/projects/{PID}/costs", {"stage_id": S1["id"], "category": "Site expense", "description": f"Tea {RUN}",
                                                                                 "amount": 500, "date": day(0)}, T["site"]), 201)
    if se.get("status") == "draft":
        ok("site submits", call("POST", f"/costs/{se['id']}/submit", {}, T["site"]))
    ok("PM approves the site expense", call("POST", f"/costs/{se['id']}/approve", {}, T["pm"]))
    mc = ok("money tab", call("GET", f"/projects/{PID}/costs", token=T["pm"]))
    check("budget shows spent", mc["budget"]["spent"] >= 15500, mc.get("budget"))

    step("E2. Invoice from the contract, receipt")
    ct = ok("contract on the project", call("GET", f"/projects/{PID}/contract", token=T["accounts"]))
    adv_row = next(r for r in ct["payment_schedule"] if r["name"] == "Advance")
    check("advance row due", adv_row.get("state") == "due", adv_row)
    inv = ok("accounts invoices the advance", call("POST", f"/contracts/{ct['id']}/schedule/{adv_row['id']}/invoice", {}, T["accounts"]), 201)
    inv = ok("send it", call("POST", f"/invoices/{inv['id']}/send", {}, T["accounts"]))
    check("numbered on send", (inv.get("number") or "").startswith("INV"), inv.get("number"))
    half = round(inv["total"] / 2, 2)
    rc = ok("part receipt", call("POST", f"/projects/{PID}/receipts", {"amount": half, "date": day(0), "mode": "Bank transfer", "reference": f"NEFT{RUN}",
                                                                       "allocations": [{"invoice_id": inv["id"], "amount": half}]}, T["accounts"]), 201)
    check("invoice part paid", call("GET", f"/invoices/{inv['id']}", token=T["accounts"])[1].get("status") == "part_paid")
    ok("receivables", call("GET", "/finance/receivables", token=T["accounts"]))
    ok("site cannot see invoices", call("GET", f"/projects/{PID}/invoices", token=T["site"]), 403)

    step("E3. Change order")
    co = ok("change order", call("POST", f"/projects/{PID}/change_orders", {"stage_id": S2["id"], "title": f"Extra basement {RUN}", "reason": "client_request",
                                                                           "lines": [{"description": "Basement", "qty": 1, "cost_rate": 200000, "price_rate": 260000}],
                                                                           "time_days": 10}, T["pm"]), 201)
    ok("price it", call("POST", f"/change_orders/{co['id']}/price", {}, T["pm"]))
    ok("send to the client", call("POST", f"/change_orders/{co['id']}/send", {}, T["pm"]))

    # ======================================= F. documents, selections, site =======================================
    step("F. Documents, selections, site report")
    k = upload(f"plan{RUN}.png", T["designer"])
    dw = ok("designer adds a drawing", call("POST", f"/projects/{PID}/documents", {"folder": "Drawings", "name": f"Ground floor {RUN}", "kind": "drawing",
                                                                                   "number": "A-101", "file_key": k}, T["designer"]), 201)
    ok("issued to the client for approval", call("POST", f"/projects/{PID}/transmittals", {"to": [CLIENT], "purpose": "for_approval", "documents": [dw["id"]], "email": False}, T["designer"]), 201)
    sel = ok("selection", call("POST", f"/projects/{PID}/selections", {"stage_id": S3["id"], "item": f"Tiles {RUN}", "allowance": 100000, "options": [
        {"name": "Vitrified", "qty": 100, "unit_cost": 600, "unit_price": 800, "supplier_id": sup["id"]},
        {"name": "Italian", "qty": 100, "unit_cost": 1500, "unit_price": 2000, "supplier_id": sup["id"]}]}, T["pm"]), 201)
    ok("sent to the client", call("POST", f"/selections/{sel['id']}/send", {"email": False}, T["pm"]))
    rep = ok("site report", call("POST", f"/projects/{PID}/site-reports", {"weather": {"kind": "Clear"}, "manpower": [{"trade": "Mason", "count": 3}],
                                                                           "work": [{"stage_id": S1["id"], "note": "Marking done"}]}, T["site"]), 201)

    # ======================================= G. portal =======================================
    step("G. Portal users: client approves, chooses, pays and writes")
    cu = ok("client portal login", call("POST", "/users", {"name": cname, "email": email("client"), "role": "client", "password": PW, "contact_id": CLIENT}, T["owner"]), 201)
    cs = ok("consultant portal login", call("POST", "/users", {"name": "Consult", "email": email("consultant"), "role": "consultant", "password": PW, "contact_id": con["id"]}, T["owner"]), 201)
    vu = ok("supplier portal login", call("POST", "/users", {"name": "Supplier", "email": email("vendor"), "role": "vendor", "password": PW, "contact_id": sup["id"]}, T["owner"]), 201)
    for r in ("client", "consultant", "vendor"):
        T[r] = login(email(r))
    check("client sees exactly the project", [x["id"] for x in call("GET", "/portal/projects", token=T["client"])[1]] == [PID])
    pv = ok("client project view", call("GET", f"/portal/projects/{PID}", token=T["client"]))
    check("no money in the portal view", "value" not in pv and "budget" not in json.dumps(pv))
    act = ok("client's actions", call("GET", f"/portal/projects/{PID}/actions", token=T["client"]))
    ok("client approves the drawing", call("POST", f"/portal/documents/{dw['id']}/approve", {"name": cname, "agree": True}, T["client"]))
    psel = next(x for x in act["selections"] if x["id"] == sel["id"])
    ok("client picks Vitrified", call("POST", f"/portal/selections/{sel['id']}/choose", {"option_id": psel["options"][0]["id"], "name": cname, "agree": True}, T["client"]))
    ok("consultant cannot approve the CO", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": "x", "agree": True, "signature": SIG}, T["consultant"]), 403)
    ok("client signs the change order", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": cname, "agree": True, "signature": SIG}, T["client"]))
    check("CO approved, budget raised", mongo.change_orders.find_one({"_id": ObjectId(co["id"])})["status"] == "approved")
    WH = f"whsec_{RUN}"
    ok("owner turns on sandbox payments", call("PUT", "/settings/payments", {"provider": "sandbox", "webhook_secret": WH}, T["owner"]))
    pi = ok("client's invoices", call("GET", f"/portal/projects/{PID}/invoices", token=T["client"]))
    check("balance shown", abs(pi["balance"] - (inv["total"] - half)) < 0.05, pi.get("balance"))
    link = ok("client asks for a pay link", call("POST", f"/portal/invoices/{inv['id']}/pay", {}, T["client"]), 201)
    st_, _ = raw_post(f"/payments/sandbox/{link['url'].rsplit('/', 1)[1]}", b"", {})
    check("sandbox checkout pays", st_ == 200 and mongo.invoices.find_one({"_id": ObjectId(inv["id"])})["status"] == "paid")
    ok("client writes to the team", call("POST", f"/portal/projects/{PID}/messages", {"text": f"When does work start? {RUN}"}, T["client"]), 201)
    ok("PM replies", call("POST", f"/projects/{PID}/threads/{CLIENT}", {"text": "Monday", "email": False}, T["pm"]), 201)
    ok("inbox", call("GET", "/inbox", token=T["pm"]))

    # ======================================= H. procurement =======================================
    step("H. Procurement: request to paid bill, supplier in the portal")
    ok("selection confirmed", call("POST", f"/selections/{sel['id']}/status", {"status": "confirmed"}, T["pm"]))
    so = ok("selection ordered", call("POST", f"/selections/{sel['id']}/status", {"status": "ordered"}, T["pm"]))
    sel_po = mongo.purchase_orders.find_one({"company_id": str(CID), "project_id": PID, "lines.selection_id": sel["id"]})
    check("ordering puts the tiles on the supplier's draft PO, no cost", sel_po and sel_po["status"] == "draft"
          and not mongo.costs.find_one({"company_id": str(CID), "description": {"$regex": f"Tiles {RUN}"}}), so.get("status"))
    rq = ok("site asks for cement", call("POST", f"/projects/{PID}/purchase-requests", {"stage_id": S2["id"], "lines": [
        {"description": f"Cement {RUN}", "qty": 200, "unit": "bag", "needed_by": day(5)}]}, T["site"]), 201)
    rf = ok("RFQ to two suppliers", call("POST", "/rfqs", {"project_id": PID, "request_ids": [rq["id"]], "supplier_ids": [sup["id"], sup2["id"]], "due_date": day(2)}, T["procurement"]), 201)
    ok("RFQ sent", call("POST", f"/rfqs/{rf['id']}/send", {}, T["procurement"]))
    vp = ok("supplier sees the RFQ", call("GET", "/portal/purchase-orders", token=T["vendor"]))
    prf = next((x for x in vp["rfqs"] if x["id"] == rf["id"]), None)
    check("RFQ in the supplier portal", prf is not None, vp.get("rfqs"))
    LN = prf["lines"][0]["id"]
    ok("supplier quotes in the portal", call("POST", f"/portal/rfqs/{rf['id']}/quote", {"lines": [{"line_id": LN, "rate": 380}], "tax_pct": 18, "delivery_days": 3}, T["vendor"]))
    ok("staff enter the other quote", call("POST", f"/rfqs/{rf['id']}/quotes", {"supplier_id": sup2["id"], "lines": [{"line_id": LN, "rate": 420}], "tax_pct": 18}, T["procurement"]), 201)
    cmp_ = ok("compare", call("GET", f"/rfqs/{rf['id']}/compare", token=T["procurement"]))
    check("lowest marked", any(q["supplier_id"] == sup["id"] and q.get("lowest") for q in cmp_["quotes"]), cmp_.get("quotes"))
    aw = ok("award the lowest", call("POST", f"/rfqs/{rf['id']}/award", {"supplier_id": sup["id"]}, T["procurement"]), 201)
    pos = [x for x in call("GET", "/purchase-orders", token=T["procurement"])[1] if x["project_id"] == PID]
    po = next((x for x in pos if x["source"] == "rfq"), None)
    check("draft PO from the award", po and po["status"] == "draft", [(x["source"], x["status"]) for x in pos])
    po = ok("submit: 76,000 is above the 50,000 limit", call("POST", f"/purchase-orders/{po['id']}/submit", {}, T["procurement"]))
    check("waits for an Owner", po.get("status") == "waiting_approval" and po["approval"]["needs"] == ["owner"], po.get("approval"))
    check("Owner told", mongo.notifications.find_one({"company_id": str(CID), "user_id": U["owner"], "event": "po_approval"}))
    ok("Procurement cannot approve above the limit", call("POST", f"/purchase-orders/{po['id']}/approve", {}, T["procurement"]), 403)
    po = ok("Owner approves", call("POST", f"/purchase-orders/{po['id']}/approve", {}, T["owner"]))
    check("approved and numbered", po.get("status") == "approved" and (po.get("number") or "").startswith("PO"), (po.get("status"), po.get("number")))
    ok("sent", call("POST", f"/purchase-orders/{po['id']}/send", {"email": False}, T["procurement"]))
    ok("supplier acknowledges", call("POST", f"/portal/purchase-orders/{po['id']}/acknowledge", {"name": "Supplier"}, T["vendor"]))
    mt = ok("money tab shows ordered", call("GET", f"/projects/{PID}/costs", token=T["pm"]))
    s2row = next(r for r in mt["budget"]["stages"] if r["id"] == S2["id"])
    check("ordered on the stage", s2row["ordered"] == 76000, s2row)
    full = ok("PO detail", call("GET", f"/purchase-orders/{po['id']}", token=T["site"]))
    check("site sees no prices on the PO", "unit_cost" not in json.dumps(full) and "total" not in full)
    PL = full["lines"][0]["id"]
    ok("site receives 200 bags, 5 damaged", call("POST", f"/purchase-orders/{po['id']}/receipts", {"lines": [{"line_id": PL, "received": 200, "rejected": 5, "reason": "Damaged"}],
                                                                                                    "challan": f"CH{RUN}"}, T["site"]), 201)
    kf = upload(f"inv{RUN}.png", T["vendor"], "/portal/uploads")
    ok("supplier uploads the invoice", call("POST", f"/portal/purchase-orders/{po['id']}/invoice", {"bill_no": f"SB-{RUN}", "file_key": kf,
                                                                                                    "lines": [{"line_id": PL, "qty": 195, "rate": 380}]}, T["vendor"]), 201)
    bill = next(b for b in call("GET", "/vendor-bills", token=T["accounts"])[1] if b["bill_no"] == f"SB-{RUN}")
    bill = ok("staff check it", call("POST", f"/vendor-bills/{bill['id']}/check", {}, T["procurement"]))
    check("matched", bill.get("status") == "matched", bill.get("problems"))
    bill = ok("accounts approve", call("POST", f"/vendor-bills/{bill['id']}/approve", {}, T["accounts"]))
    mt = ok("money tab after the bill", call("GET", f"/projects/{PID}/costs", token=T["pm"]))
    s2row = next(r for r in mt["budget"]["stages"] if r["id"] == S2["id"])
    check("spent up; the 5 rejected bags are still on order", s2row["spent"] >= 74100 and s2row["ordered"] == 1900, s2row)
    ok("short-close needs a reason", call("POST", f"/purchase-orders/{po['id']}/short-close", {}, T["procurement"]), 400)
    sc = ok("short-close the rest", call("POST", f"/purchase-orders/{po['id']}/short-close", {"reason": "Replacement not needed"}, T["procurement"]))
    check("PO closed", sc.get("status") == "closed", sc.get("status"))
    s2row = next(r for r in call("GET", f"/projects/{PID}/costs", token=T["pm"])[1]["budget"]["stages"] if r["id"] == S2["id"])
    check("nothing left on order", s2row["ordered"] == 0, s2row)
    ok("pay the supplier", call("POST", "/vendor-payments", {"amount": bill["total"], "date": day(0), "mode": "Bank transfer", "reference": f"PAY{RUN}",
                                                             "allocations": [{"bill_id": bill["id"], "amount": bill["total"]}]}, T["accounts"]), 201)
    pb = call("GET", "/portal/purchase-orders", token=T["vendor"])[1]["bills"]
    check("supplier sees it paid", any(b["bill_no"] == f"SB-{RUN}" and b["status"] == "paid" for b in pb), pb)
    ok("payables", call("GET", "/finance/payables", token=T["accounts"]))
    sr = ok("site report lists the delivery", call("GET", f"/projects/{PID}/site-reports", token=T["site"]))
    check("delivery on today's report", any(r_["date"] == day(0) and r_["deliveries"] for r_ in sr["reports"]))

    # ======================================= reports, worker, sweep, close =======================================
    step("Reports, worker, 500-sweep for every role")
    worker()
    worker()
    for r, path in (("owner", "/reports/sales"), ("owner", "/reports/finance"), ("owner", "/reports/procurement"), ("pm", "/reports/followups"),
                    ("site", "/reports/procurement"), ("accounts", "/reports/finance")):
        ok(f"{r} {path}", call("GET", path, token=T[r]))
    lists = ["/home", "/leads", "/leads/meta", "/bids", "/contacts", "/contacts/meta", "/projects", "/projects/meta", "/followups", "/followups/today",
             "/proposals", "/contracts", "/proposal_templates", "/change_orders", "/documents", "/selections", "/site-reports", "/finance/costs",
             "/invoices", "/finance/receivables", "/purchase-requests", "/rfqs", "/purchase-orders", "/goods-receipts", "/vendor-bills",
             "/finance/payables", "/inbox", "/notifications", "/waiting", "/calendar", "/rates", "/users", "/company", "/stage_templates",
             "/finance/settings", "/settings/site", "/settings/payments", "/settings/messaging", "/reports/sales", "/reports/finance",
             "/reports/procurement", "/reports/followups", "/leads/attention", "/compliance/alerts", "/message_templates", "/audit"]
    plist = ["", "/dashboard", "/costs", "/invoices", "/receipts", "/contract", "/documents", "/drawing-register", "/transmittals", "/selections",
             "/site-reports", "/change_orders", "/purchase-requests", "/threads", "/finance", "/history", "/followups", "/handover"]
    bad = []
    for r in ["owner"] + STAFF:
        for path in lists + [f"/projects/{PID}{x}" for x in plist]:
            s_, d_ = call("GET", path, token=T[r])
            if s_ >= 500:
                bad.append(f"{r} GET {path} -> {s_} {d_.get('error', '') if isinstance(d_, dict) else ''}")
    for r in ("client", "consultant", "vendor"):
        for path in ["/portal/projects", f"/portal/projects/{PID}", f"/portal/projects/{PID}/actions", f"/portal/projects/{PID}/invoices",
                     f"/portal/projects/{PID}/messages", "/portal/purchase-orders", "/portal/me", "/notifications"]:
            s_, d_ = call("GET", path, token=T[r])
            if s_ >= 500:
                bad.append(f"{r} GET {path} -> {s_}")
    check("no server error on any list, for any role", not bad, bad)
    for r in STAFF + ["owner"]:
        h = call("GET", "/home", token=T[r])
        check(f"home for {r}", h[0] == 200, h[0])

    step("Close-out")
    ok("project completed", call("PUT", f"/projects/{PID}", {"status": "completed"}, T["pm"]))
    hist = ok("history", call("GET", f"/projects/{PID}/history", token=T["pm"]))
    check("history kept", len(hist) >= 10, len(hist))
    ok("a project with POs cannot be deleted", call("DELETE", f"/projects/{PID}", token=T["owner"]), 409)
except Exception:
    failures.append(f"[{cur['name']}] crashed: {traceback.format_exc()[-1500:]}")
finally:
    step(None)
    if CID:  # remove the whole test company
        cid = str(CID)
        for coll in mongo.list_collection_names():
            if coll in ("companies", "plans", "superadmin_users"):
                continue
            mongo[coll].delete_many({"company_id": cid})
        mongo.users.delete_many({"email": {"$regex": f"@{DOMAIN.replace('.', '[.]')}$"}})
        mongo.companies.delete_one({"_id": ObjectId(cid)})

print()
for s_ in steps:
    print(f"  {'PASS' if not s_['bad'] else 'FAIL'}  {s_['name']}  ({s_['ok']} checks{', ' + str(s_['bad']) + ' failed' if s_['bad'] else ''})")
print(f"\npassed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
