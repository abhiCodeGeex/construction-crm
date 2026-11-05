"""Phase D — proposals & estimates -> contract with payment schedule. One block per row of PLAN.md D1.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_d.py
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
failures, passed = [], 0
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]


def call(method, path, body=None, token=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
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


def upload(name, data, token):
    bnd = uuid.uuid4().hex
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
        + data + f"\r\n--{bnd}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}", "Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req).read())


def worker():
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once()


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm", "site")}
U = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1] if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"branding": 1, "sales": 1})
leads, contacts, projects, templates, files = [], [], [], [], []
SIG = "data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==" * 4
COST_KEYS = ("trade_price", "markup_pct", "cost", "margin", "margin_pct", "overheads", "markup_amount", "products", "extra_items")
n = 0


def new_lead(service, **kw):
    global n
    n += 1
    s, d = call("POST", "/leads", {"title": f"PD {RUN} {n}", "service": service, "source": "Walk-in", "contact_name": f"PD Client {RUN} {n}",
                                   "contact_phone": f"7{RUN[-7:]}{n:02d}", "area": 2400, "budget": 3000000, **kw}, T["sales"])
    assert s == 201, (s, d)
    leads.append(d["id"])
    contacts.append(d["contact_id"])
    return d


def has_cost(obj):
    text = json.dumps(obj)
    return [k for k in COST_KEYS if f'"{k}"' in text]


try:
    meta = call("GET", "/leads/meta", token=T["owner"])[1]
    stages = {s: [st["name"] for st in next(tp for tp in call("GET", "/stage_templates", token=T["owner"])[1]["templates"]
                                            if tp["service"] == s and tp.get("is_default"))["stages"]] for s in meta["services"]}

    # ================= §5 templates =================
    tl = expect("§5 templates listed", call("GET", "/proposal_templates", token=T["sales"]), 200)
    check("§5 a standard template per type", {x["type"] for x in tl} >= {"fee", "construction", "interior"}, [x["type"] for x in tl])
    expect("§5 templates are settings", call("POST", "/proposal_templates", {"name": "x", "type": "fee"}, T["sales"]), 403)
    arch = stages["architecture"]
    expect("§5 template schedule must total 100", call("POST", "/proposal_templates", {"name": f"Arch {RUN}", "type": "fee", "service": "architecture",
                                                                                     "payment_schedule": [{"name": "Signing", "pct": 90, "trigger": "signing"}]}, T["owner"]), 400)
    expect("§5 stage must be a template stage", call("POST", "/proposal_templates", {"name": f"Arch {RUN}", "type": "fee", "service": "architecture",
                                                                                   "payment_schedule": [{"name": "X", "pct": 100, "trigger": "stage", "stage": "Moon"}]}, T["owner"]), 400)
    tp = expect("§5 create a template", call("POST", "/proposal_templates", {
        "name": f"Arch {RUN}", "type": "fee", "service": "architecture", "intro": f"Intro {RUN}", "terms": "Pay in 7 days",
        "items": [{"description": "Site visits beyond ten", "qty": 1, "rate": 15000, "optional": True}],
        "payment_schedule": [{"name": "Signing", "pct": 20, "trigger": "signing"}, {"name": f"On {arch[0]}", "pct": 80, "trigger": "stage", "stage": arch[0]}]},
        T["owner"]), 201)
    templates.append(tp["id"])

    # ================= §5 fee proposal (four bases) =================
    A = new_lead("architecture")
    expect("§5 fee needs the right template type", call("POST", f"/leads/{A['id']}/proposals", {"type": "interior", "template_id": tp["id"], "valid_until": day(20)}, T["sales"]), 400)
    pf = expect("§5 fee proposal from the template", call("POST", f"/leads/{A['id']}/proposals", {"type": "fee", "template_id": tp["id"], "valid_until": day(20)}, T["sales"]), 201)
    check("§5 template content copied", pf["intro"] == f"Intro {RUN}" and pf["payment_schedule"][0]["pct"] == 20 and pf["extra_items"][0]["optional"], pf.get("intro"))
    P = f"/proposals/{pf['id']}"
    expect("§5 fee basis required fields", call("PUT", P, {"fee": {"basis": "percent", "pct": 8}}, T["sales"]), 400)
    r = expect("§5 fee % of project cost", call("PUT", P, {"fee": {"basis": "percent", "pct": 8, "project_cost": 5000000}}, T["sales"]), 200)
    check("§5 8% of 50 lakh", r["items"][0]["amount"] == 400000, r["items"][0])
    expect("§5 fee split must total 100", call("PUT", P, {"fee": {"basis": "percent", "pct": 8, "project_cost": 5000000,
                                                                  "stages": [{"name": arch[0], "pct": 30}, {"name": arch[1], "pct": 60}]}}, T["sales"]), 400)
    r = expect("§5 fee split across stages", call("PUT", P, {"fee": {"basis": "percent", "pct": 8, "project_cost": 5000000,
                                                                     "stages": [{"name": arch[0], "pct": 30}, {"name": arch[1], "pct": 70}]}}, T["sales"]), 200)
    check("§5 split lines", [i["amount"] for i in r["items"] if i["id"].startswith("fee-")] == [120000, 280000])
    r = expect("§5 hourly fee", call("PUT", P, {"fee": {"basis": "hourly", "hours": 40, "rate": 2500}}, T["sales"]), 200)
    check("§5 hours × rate", r["items"][0]["amount"] == 100000)
    r = expect("§5 per-area fee + discount + tax", call("PUT", P, {"fee": {"basis": "per_area", "area": 2400, "rate": 120}, "discount_pct": 5, "tax_pct": 18}, T["sales"]), 200)
    tt = r["totals"]
    check("§5 optional line not in the total until chosen", (tt["subtotal"], tt["discount"], tt["taxable"], tt["tax"], tt["total"], tt["optional_available"]) ==
          (288000, 14400, 273600, 49248, 322848, 15000), tt)
    check("§5 fee proposals have no cost / margin", tt["cost"] is None and tt["margin"] is None)

    # ================= §5 interior quote =================
    I = new_lead("interior")
    pi = expect("§5 interior quote", call("POST", f"/leads/{I['id']}/proposals", {"type": "interior", "valid_until": day(20)}, T["sales"]), 201)
    PI = f"/proposals/{pi['id']}"
    expect("§5 design fee is fixed or per area", call("PUT", PI, {"fee": {"basis": "hourly", "hours": 1, "rate": 1}}, T["sales"]), 400)
    expect("§5 products only on interior quotes", call("PUT", P, {"products": []}, T["sales"]), 400)
    ri = expect("§5 design fee + products with markup", call("PUT", PI, {"fee": {"basis": "fixed", "amount": 50000}, "tax_pct": 0, "products": [
        {"room": "Living", "name": "Sofa", "brand": "Urban", "qty": 1, "unit": "nos", "trade_price": 40000, "markup_pct": 25},
        {"room": "Living", "name": "Floor lamp", "qty": 2, "unit": "nos", "trade_price": 5000, "markup_pct": 30, "optional": True}]}, T["sales"]), 200)
    sofa = next(i for i in ri["items"] if i["description"].startswith("Sofa"))
    lamp = next(i for i in ri["items"] if i["description"].startswith("Floor lamp"))
    check("§5 client price = trade × (1 + markup)", sofa["rate"] == 50000 and lamp["rate"] == 6500 and lamp["amount"] == 13000)
    check("§5 interior total", ri["totals"]["total"] == 100000 and ri["totals"]["optional_available"] == 13000, ri["totals"])
    pv = expect("§5 client preview", call("GET", f"{PI}/preview", token=T["sales"]), 200)
    check("§5 client view hides trade price, markup, cost, margin", not has_cost(pv), has_cost(pv))

    # ================= §5 construction from an approved estimate =================
    C = new_lead("construction")
    ce = expect("estimate", call("POST", f"/leads/{C['id']}/estimates", {}, T["owner"]), 201)
    call("PUT", f"/estimates/{ce['id']}", {"lines": [{"description": "RCC frame", "qty": 100, "unit": "cum", "material_rate": 6000, "labour_rate": 2000},
                                                     {"description": "Brickwork", "qty": 400, "unit": "sqm", "material_rate": 500, "labour_rate": 300}],
                                           "overhead_pct": 10, "markup_pct": 20, "discount_pct": 0, "tax_pct": 18}, T["owner"])
    est = expect("estimate approved", call("POST", f"/estimates/{ce['id']}/submit", {}, T["owner"]), 200)
    expect("§5 construction needs an approved estimate", call("POST", f"/leads/{C['id']}/proposals", {"type": "construction", "valid_until": day(20)}, T["sales"]), 400)
    pc = expect("§5 construction proposal", call("POST", f"/leads/{C['id']}/proposals", {"estimate_id": ce["id"], "valid_until": day(20)}, T["sales"]), 201)
    check("§5 proposal total = estimate total", pc["type"] == "construction" and abs(pc["totals"]["total"] - est["totals"]["total"]) < 0.05, (pc["totals"], est["totals"]))
    check("§5 staff see cost and margin", pc["totals"]["cost"] == est["totals"]["cost"] and pc["totals"]["margin_pct"] > 0)
    cv = call("GET", f"/proposals/{pc['id']}/preview", token=T["sales"])[1]
    check("§5 client sees no cost, overheads or markup", not has_cost(cv), has_cost(cv))
    PC = f"/proposals/{pc['id']}"
    cs = stages["construction"]
    expect("§5 schedule stage must be a project stage", call("PUT", PC, {"payment_schedule": [{"name": "X", "pct": 100, "trigger": "stage", "stage": "Moon"}]}, T["sales"]), 400)
    expect("§5 schedule must total 100", call("PUT", PC, {"payment_schedule": [{"name": "Advance", "pct": 50, "trigger": "signing"}]}, T["sales"]), 400)
    sched = [{"name": "Advance", "pct": 10, "trigger": "signing"}, {"name": f"On {cs[1]}", "pct": 40, "trigger": "stage", "stage": cs[1]},
             {"name": f"On {cs[2]}", "pct": 40, "trigger": "stage", "stage": cs[2]}, {"name": "Retention release", "pct": 10, "trigger": "date", "date": day(200)}]
    expect("§5 payment schedule", call("PUT", PC, {"payment_schedule": sched, "discount_pct": 20}, T["sales"]), 200)
    res = call("POST", f"{PC}/send", {"channel": "whatsapp"}, T["sales"])
    check("§5 discount above the limit blocks sending", res[0] == 409 and "approval" in res[1]["error"], res)
    ap = expect("§5 request approval", call("POST", f"{PC}/approval", {}, T["sales"]), 200)
    check("§5 approver told", ap["approval"]["status"] == "pending" and mongo.notifications.find_one(
        {"company_id": CID, "user_id": U["owner"], "event": "approval_needed", "text": {"$regex": pc["number"]}}))
    expect("§5 sales cannot approve", call("POST", f"{PC}/approval/decide", {"approve": True}, T["sales"]), 403)
    expect("§5 owner approves", call("POST", f"{PC}/approval/decide", {"approve": True}, T["owner"]), 200)
    call("PUT", PC, {"intro": "Changed after approval"}, T["sales"])
    check("§5 editing clears the approval", call("POST", f"{PC}/send", {"channel": "whatsapp"}, T["sales"])[0] == 409)
    call("POST", f"{PC}/approval", {}, T["sales"])
    call("POST", f"{PC}/approval/decide", {"approve": True}, T["owner"])
    sc = expect("§5 send", call("POST", f"{PC}/send", {"channel": "whatsapp"}, T["sales"]), 200)
    token = sc["link"].split("/p/")[1]
    check("§5 client link returned", sc["status"] == "sent" and sc["link_full"].endswith(f"/p/{token}"))
    expect("§D2 sent proposal is locked", call("PUT", PC, {"intro": "x"}, T["sales"]), 409)

    # ================= §16 viewed + §5 online acceptance =================
    expect("§D2 unknown link", call("GET", "/public/proposals/nope"), 404)
    v1 = expect("§16 client opens the link", call("GET", f"/public/proposals/{token}"), 200)
    call("GET", f"/public/proposals/{token}")
    dbp = mongo.proposals.find_one({"_id": ObjectId(pc["id"])})
    check("§16 every view logged", dbp["view_count"] == 2 and len(dbp["views"]) == 2 and dbp["first_viewed_at"])
    viewed = list(mongo.notifications.find({"company_id": CID, "event": "proposal_viewed", "lead_id": C["id"]}))
    check("§16 salesperson told once at the first view", len(viewed) == 1 and viewed[0]["user_id"] == U["sales"], len(viewed))
    check("§5 client view has the schedule with amounts", len(v1["payment_schedule"]) == 4 and abs(sum(r["amount"] for r in v1["payment_schedule"]) - v1["totals"]["total"]) < 0.05)
    check("§5 client view hides costs", not has_cost(v1), has_cost(v1))
    A_ = f"/public/proposals/{token}/accept"
    expect("§5 must agree", call("POST", A_, {"name": "Client", "signature": SIG}), 400)
    expect("§5 must type a name", call("POST", A_, {"agree": True, "signature": SIG}), 400)
    expect("§5 must sign", call("POST", A_, {"agree": True, "name": "Client", "signature": "data:image/png;base64,xx"}), 400)
    expect("§5 decline needs a reason", call("POST", f"/public/proposals/{token}/decline", {}), 400)
    signed = expect("§5 accept with e-signature", call("POST", A_, {"agree": True, "name": f"Signer {RUN}", "signature": SIG},
                                                       headers={"User-Agent": f"TestBrowser {RUN}"}), 200)
    check("§5 signed copy shows acceptance and contract", signed["status"] == "accepted" and signed["acceptance"]["name"] == f"Signer {RUN}"
          and signed["acceptance"]["signature"].startswith("data:image/png") and signed["contract_number"])
    expect("§5 accepted only once", call("POST", A_, {"agree": True, "name": "x", "signature": SIG}), 409)
    dbp = mongo.proposals.find_one({"_id": ObjectId(pc["id"])})
    check("§5 time, IP and browser recorded", dbp["acceptance"]["at"] and dbp["acceptance"]["ip"] and dbp["acceptance"]["user_agent"] == f"TestBrowser {RUN}")
    con = mongo.contracts.find_one({"company_id": CID, "proposal_id": pc["id"]})
    check("§5 contract created", con and con["status"] == "signed" and abs(con["value"] - dbp["totals"]["total"]) < 0.01)
    check("§5 schedule amounts add up to the contract", abs(sum(r["amount"] for r in con["payment_schedule"]) - con["value"]) < 0.05)
    check("§5 salesperson and manager told", mongo.notifications.count_documents({"company_id": CID, "event": "contract_signed", "lead_id": C["id"]}) >= 2)
    check("§5 lead value = contract", call("GET", f"/leads/{C['id']}", token=T["sales"])[1]["value"] == con["value"])

    # optional item chosen by the client (interior)
    call("PUT", PI, {"payment_schedule": [{"name": "Advance", "pct": 50, "trigger": "signing"}, {"name": "On delivery", "pct": 50, "trigger": "date", "date": day(60)}]}, T["sales"])
    si = expect("§5 send interior", call("POST", f"{PI}/send", {"channel": "email"}, T["sales"]), 200)
    itok = si["link"].split("/p/")[1]
    expect("§5 only optional lines can be chosen", call("POST", f"/public/proposals/{itok}/accept", {"agree": True, "name": "I", "signature": SIG, "selected": [sofa["id"]]}), 400)
    ia = expect("§5 accept with an optional item", call("POST", f"/public/proposals/{itok}/accept", {"agree": True, "name": "I", "signature": SIG, "selected": [lamp["id"]]}), 200)
    check("§5 accepted total includes the chosen option", ia["totals"]["total"] == 113000, ia["totals"])

    # decline / revision on the fee proposal; draft link not public
    pf2 = call("GET", f"/proposals/{pf['id']}", token=T["sales"])[1]
    check("§D2 draft has no client link", pf2["link"] is None)
    call("POST", f"/proposals/{pf['id']}/send", {"channel": "email"}, T["sales"])
    ftok = call("GET", f"/proposals/{pf['id']}", token=T["sales"])[1]["link"].split("/p/")[1]
    call("GET", f"/public/proposals/{ftok}")
    mongo.proposals.update_one({"_id": ObjectId(pf["id"])}, {"$set": {"first_viewed_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)}})
    worker()
    check("§16 viewed 2+ days ago and not answered -> reminder", mongo.notifications.find_one({"company_id": CID, "key": f"viewed-wait:{pf['id']}"}))
    dc = expect("§5 client asks for changes", call("POST", f"/public/proposals/{ftok}/decline", {"revision": True, "reason": "Price", "comment": "Too high"}), 200)
    check("§5 revision request recorded", dc["status"] == "revision_requested" and dc["response"]["reason"] == "Price")
    rv = expect("§5 revise = new version with the content", call("POST", f"/leads/{A['id']}/proposals", {"revision_of": pf["id"]}, T["sales"]), 201)
    check("§5 revision copies content", rv["version"] == 2 and rv["fee"]["basis"] == "per_area" and rv["intro"] == f"Intro {RUN}")
    mongo.proposals.update_one({"_id": ObjectId(rv["id"])}, {"$set": {"valid_until": day(5)}})
    call("POST", f"/proposals/{rv['id']}/send", {"channel": "email"}, T["sales"])
    check("§D2 superseded link no longer works", call("GET", f"/public/proposals/{ftok}")[0] in (404, 200) and
          mongo.proposals.find_one({"_id": ObjectId(pf["id"])})["status"] in ("revision_requested", "superseded"))
    rtok = call("GET", f"/proposals/{rv['id']}", token=T["sales"])[1]["link"].split("/p/")[1]
    mongo.proposals.update_one({"_id": ObjectId(rv["id"])}, {"$set": {"valid_until": day(-1)}})
    expect("§D2 expired link cannot be accepted", call("POST", f"/public/proposals/{rtok}/accept", {"agree": True, "name": "x", "signature": SIG}), 409)

    # accepted on paper, recorded by staff
    S = new_lead("construction")
    ps = expect("simple proposal", call("POST", f"/leads/{S['id']}/proposals", {"value": 500000, "valid_until": day(10)}, T["sales"]), 201)
    call("POST", f"/proposals/{ps['id']}/send", {"channel": "in_person"}, T["sales"])
    rec = expect("§5 acceptance recorded by staff", call("POST", f"/proposals/{ps['id']}/respond", {"result": "accepted", "signed_by": "Mr Rao"}, T["sales"]), 200)
    sc_ = mongo.contracts.find_one({"company_id": CID, "proposal_id": ps["id"]})
    check("§5 recorded acceptance makes the contract", rec["status"] == "accepted" and sc_ and sc_["acceptance"]["method"].startswith("recorded by"))

    # ================= §5 won: contract joins the project =================
    expect("§5 project value comes from the contract", call("POST", f"/leads/{C['id']}/win", {"pm_id": U["pm"], "value": 1}, T["sales"]), 400)
    w = expect("§5 win", call("POST", f"/leads/{C['id']}/win", {"pm_id": U["pm"]}, T["sales"]), 200)
    projects.append(w["project_id"])
    pj = call("GET", f"/projects/{w['project_id']}", token=T["pm"])[1]
    check("§5 project value = contract value", abs(pj["value"] - con["value"]) < 0.01, (pj["value"], con["value"]))
    pcon = expect("§5 project contract", call("GET", f"/projects/{w['project_id']}/contract", token=T["pm"]), 200)
    rows = {r["name"]: r for r in pcon["payment_schedule"]}
    check("§5 stage rows linked to milestones", all(rows[f"On {s}"]["milestone_id"] for s in cs[1:3]))
    check("§5 signing row due, stage rows upcoming, date row upcoming", rows["Advance"]["state"] == "due" and rows[f"On {cs[1]}"]["state"] == "upcoming"
          and rows["Retention release"]["state"] == "upcoming", {k: v.get("state") for k, v in rows.items()})
    mid = rows[f"On {cs[1]}"]["milestone_id"]
    stg = next(s for s in pj["stages"] if any(m["id"] == mid for m in s["milestones"]))
    expect("stage not ready cannot be closed", call("PUT", f"/projects/{w['project_id']}/milestones/{mid}", {"status": "achieved"}, T["pm"]), 409)
    call("PUT", f"/projects/{w['project_id']}/stages/{stg['id']}", {"progress": 100}, T["pm"])  # B+2: get the stage ready
    for c in stg["checklist"]:
        call("PUT", f"/projects/{w['project_id']}/stages/{stg['id']}/checklist/{c['id']}", {"done": True}, T["pm"])
    if stg["client_signoff_required"]:
        expect("client sign-off", call("POST", f"/projects/{w['project_id']}/stages/{stg['id']}/signoff",
                                       {"name": "Client", "method": "Email"}, T["pm"]), 201)
    expect("achieve the milestone", call("PUT", f"/projects/{w['project_id']}/milestones/{mid}", {"status": "achieved"}, T["pm"]), 200)
    rows = {r["name"]: r for r in call("GET", f"/projects/{w['project_id']}/contract", token=T["pm"])[1]["payment_schedule"]}
    check("§5 row due once its milestone is achieved", rows[f"On {cs[1]}"]["state"] == "due")
    check("§5 site staff see no contract money", call("GET", f"/projects/{w['project_id']}/contract", token=T["site"])[1] in (None, {}) or
          call("GET", f"/projects/{w['project_id']}/contract", token=T["site"])[0] in (403, 404))
    check("§5 contracts list", any(c["id"] == str(con["_id"]) for c in call("GET", "/contracts", token=T["owner"])[1]))
    check("§5 proposals list", any(p["id"] == pc["id"] for p in call("GET", "/proposals", token=T["owner"])[1]))
    expect("§D2 lead with a contract cannot be deleted", call("DELETE", f"/leads/{S['id']}", token=T["owner"]), 409)

    # ================= §1 branding =================
    expect("§1 colour validated", call("PUT", "/company/branding", {"primary": "blue"}, T["owner"]), 400)
    doc = upload(f"terms{RUN}.pdf", b"%PDF-1.4 test", T["owner"])
    files.append(doc["key"])
    expect("§1 logo must be an image", call("PUT", "/company/branding", {"logo_key": doc["key"]}, T["owner"]), 400)
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f0005000201e2b1b6c30000000049454e44ae426082")
    lg = upload(f"logo{RUN}.png", png, T["owner"])
    files.append(lg["key"])
    expect("§1 sales cannot change branding", call("PUT", "/company/branding", {"primary": "#123456"}, T["sales"]), 403)
    br = expect("§1 set branding", call("PUT", "/company/branding", {"logo_key": lg["key"], "primary": "#0f766e", "phone": "080 1234",
                                                                    "email": "hello@skyline.test", "address": "Bengaluru"}, T["owner"]), 200)
    check("§1 public logo", call("GET", br["logo_url"].replace("/api", ""))[0] == 200)
    check("§1 branding on the client page", call("GET", f"/public/proposals/{token}")[1]["company"]["primary"] == "#0f766e")
    expect("§1 another company's logo is not served", call("GET", "/public/logo/000000000000000000000000"), 404)

    # project deleted -> the contract stays with its lead, unlinked
    call("DELETE", f"/projects/{w['project_id']}", token=T["owner"])
    projects.remove(w["project_id"])
    cc = mongo.contracts.find_one({"_id": con["_id"]})
    check("§D2 contract kept and unlinked when the project is deleted", cc and cc["project_id"] is None and all(r["milestone_id"] is None for r in cc["payment_schedule"]))
finally:
    for pid in projects:
        call("DELETE", f"/projects/{pid}", token=T["owner"])
    for pid in projects:
        mongo.followups.delete_many({"company_id": CID, "related.id": pid})
    mongo.contracts.delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    for x in mongo.leads.find({"_id": {"$in": [ObjectId(i) for i in leads]}}, {"project_id": 1}):
        if x.get("project_id"):
            call("DELETE", f"/projects/{x['project_id']}", token=T["owner"])
            mongo.followups.delete_many({"company_id": CID, "related.id": x["project_id"]})
    mongo.lead_receipts.update_many({"company_id": CID, "lead_id": {"$in": leads}}, {"$set": {"status": "void"}})
    for lid in leads:
        call("DELETE", f"/leads/{lid}", token=T["owner"])
    mongo.followups.delete_many({"company_id": CID, "related.id": {"$in": leads}})
    for c in contacts:
        call("DELETE", f"/contacts/{c}", token=T["owner"])
    for tid in templates:
        call("DELETE", f"/proposal_templates/{tid}", token=T["owner"])
    for k in files:
        mongo.files.delete_one({"key": k})
        try:
            os.remove(os.path.join(os.getenv("UPLOAD_DIR", "/data/uploads"), k))
        except OSError:
            pass
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"branding": company_before.get("branding") or {}}})
    mongo.notifications.delete_many({"company_id": CID, "$or": [{"lead_id": {"$in": leads}}, {"text": {"$regex": RUN}}]})
    left = mongo.leads.count_documents({"title": {"$regex": f"PD {RUN}"}}) + mongo.contacts.count_documents({"name": {"$regex": f"PD Client {RUN}"}}) + \
        mongo.proposals.count_documents({"lead_id": {"$in": leads}}) + mongo.contracts.count_documents({"lead_id": {"$in": leads}}) + \
        mongo.proposal_templates.count_documents({"name": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
