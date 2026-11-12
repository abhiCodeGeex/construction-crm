"""Phase K — v4 "Phase 2". One section per block of PLAN.md Phase K. Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_k.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("API", "http://localhost:5000/api")
PW = "Demo@123"
RUN = str(int(time.time() * 1000))[-8:]
failures, passed = [], 0
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]


def call(method, path, body=None, token=None, form=None):
    data = json.dumps(body).encode() if body is not None else (urllib.parse.urlencode(form).encode() if form is not None else None)
    req = urllib.request.Request(BASE + path, method=method, data=data)
    req.add_header("Content-Type", "application/json" if form is None else "application/x-www-form-urlencoded")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw or b"{}") if raw[:1] in (b"{", b"[") or not raw else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw or b"{}") if raw[:1] in (b"{", b"[") or not raw else {"error": raw[:200]})


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


def upload(name, token, content=b"0" * 64, path="/uploads"):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        k = json.loads(r.read())["key"]
    keys.append(k)
    return k


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement")}
T["client"] = login("client@skyline.test")
T["sub"] = login("subcontractor@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
SUB_CONTACT = mongo.users.find_one({"email": "subcontractor@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"timesheets": 1, "accounting": 1, "assistant": 1, "phone": 1, "messaging": 1})
sub_before = mongo.contacts.find_one({"_id": ObjectId(SUB_CONTACT)}, {"types": 1, "compliance": 1, "sub_rating": 1})
client_before = mongo.contacts.find_one({"_id": ObjectId(CLIENT_CONTACT)}, {"phone": 1, "whatsapp_opt_in": 1, "whatsapp_opt_out": 1})
users_before = {u["_id"]: u.get("phone") for u in mongo.users.find({"company_id": CID, "kind": "staff"})}
projects, keys, contacts_made, leads, seqs = [], [], [], [], []

try:
    p = expect("project", call("POST", "/projects", {"name": f"PhaseK {RUN}", "services": ["interior"], "start": day(-20), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    PID = p["id"]
    projects.append(PID)
    for who, role in (("pm", "Project Manager"), ("designer", "Architect"), ("site", "Site Supervisor"), ("accounts", "Accounts")):
        call("POST", f"/projects/{PID}/team", {"user_id": U[who], "project_role": role, "access": "edit"}, T["owner"])
    mongo.contacts.update_one({"_id": ObjectId(SUB_CONTACT)}, {"$set": {"types": ["subcontractor"], "compliance": []}, "$unset": {"sub_rating": ""}})
    call("POST", f"/projects/{PID}/team", {"contact_id": SUB_CONTACT, "project_role": "Subcontractor"}, T["owner"])
    p = call("GET", f"/projects/{PID}", token=T["owner"])[1]
    S0 = p["stages"][0]["id"]

    # ======================================= block 1: subcontractors =======================================
    sub2 = expect("second subcontractor", call("POST", "/contacts", {"name": f"Volt Electricals {RUN}", "kind": "company", "types": ["subcontractor"],
                                                                     "email": f"volt{RUN}@x.test"}, T["owner"]), 201)
    notsub = expect("a supplier", call("POST", "/contacts", {"name": f"Supply Co {RUN}", "kind": "company", "types": ["supplier"]}, T["owner"]), 201)
    contacts_made += [sub2["id"], notsub["id"]]
    expect("K1.1 needs lines", call("POST", f"/projects/{PID}/subcontracts", {"title": "x", "lines": []}, T["pm"]), 400)
    sc = expect("K1.1 work package", call("POST", f"/projects/{PID}/subcontracts", {
        "title": f"Electrical works {RUN}", "trade": "Electrical", "stage_id": S0, "due_date": day(5),
        "lines": [{"description": "Wiring points", "qty": 40, "unit": "pts", "est_rate": 900}, {"description": "DB fixing", "qty": 2, "unit": "nos", "est_rate": 4000}]}, T["pm"]), 201)
    check("K1.1 numbered, draft", sc["number"].startswith("SC") and sc["status"] == "draft" and len(sc["lines"]) == 2, sc)
    expect("K1.1 sales cannot", call("POST", f"/projects/{PID}/subcontracts", {"title": "x", "lines": [{"description": "x", "qty": 1}]}, T["sales"]), 404)
    expect("K1.2 invite a supplier refused", call("POST", f"/subcontracts/{sc['id']}/invite", {"contact_ids": [notsub["id"]]}, T["pm"]), 400)
    inv = expect("K1.2 invite two subcontractors", call("POST", f"/subcontracts/{sc['id']}/invite", {"contact_ids": [SUB_CONTACT, sub2["id"]]}, T["pm"]))
    check("K1.2 bidding", inv["status"] == "bidding" and len(inv["bidders"]) == 2, inv.get("status"))
    lines = inv["lines"]
    ps = expect("K1.3 subcontractor sees it in the portal", call("GET", "/portal/subcontracts", token=T["sub"]))
    mine = next((x for x in ps if x["id"] == sc["id"]), None)
    check("K1.3 scope without the estimate rates", mine and "est_rate" not in json.dumps(mine["lines"]), mine)
    expect("K1.3 every line priced", call("POST", f"/portal/subcontracts/{sc['id']}/bid", {"lines": [{"line_id": lines[0]["id"], "rate": 850}]}, T["sub"]), 400)
    b1 = expect("K1.3 portal bid", call("POST", f"/portal/subcontracts/{sc['id']}/bid", {"lines": [{"line_id": lines[0]["id"], "rate": 850}, {"line_id": lines[1]["id"], "rate": 4200}],
                                                                                         "days": 12, "note": "Copper wire by us"}, T["sub"]), 201)
    check("K1.3 total", b1["my_bid"]["total"] == 40 * 850 + 2 * 4200, b1["my_bid"])
    expect("K1.3 team enters a bid sent by email", call("POST", f"/subcontracts/{sc['id']}/bids", {"contact_id": sub2["id"], "lines": [{"line_id": lines[0]["id"], "rate": 800},
                                                                                                                                     {"line_id": lines[1]["id"], "rate": 5000}], "days": 15}, T["pm"]), 201)
    cmp_ = expect("K1.4 compare", call("GET", f"/subcontracts/{sc['id']}/compare", token=T["pm"]))
    check("K1.4 lowest first, vs estimate", cmp_["bidders"][0]["contact_id"] == sub2["id"] and cmp_["estimate_total"] == 44000
          and cmp_["rows"][0]["bids"][sub2["id"]]["lowest"], cmp_["bidders"])
    cs = expect("K1.4 site sees no rates", call("GET", f"/subcontracts/{sc['id']}/compare", token=T["site"]))
    check("K1.4 hidden", cs["estimate_total"] is None and "est_rate" not in json.dumps(cs["rows"][0]["line"]), cs.get("estimate_total"))
    expect("K1.5 not the lowest needs a reason", call("POST", f"/subcontracts/{sc['id']}/award", {"contact_id": SUB_CONTACT, "retention_pct": 5}, T["pm"]), 400)
    mongo.contacts.update_one({"_id": ObjectId(SUB_CONTACT)}, {"$set": {"compliance": [{"id": "lic1", "name": "Electrical licence", "expiry": day(-3)}]}})
    expect("K1.5 expired licence warned", call("POST", f"/subcontracts/{sc['id']}/award", {"contact_id": SUB_CONTACT, "reason": "Better quality, faster"}, T["pm"]), 409)
    aw = expect("K1.5 award anyway", call("POST", f"/subcontracts/{sc['id']}/award", {"contact_id": SUB_CONTACT, "reason": "Better quality, faster", "accept_expired": True,
                                                                                         "retention_pct": 5, "start": day(0), "end": day(20)}, T["pm"]))
    check("K1.5 awarded with agreement no", aw["status"] == "awarded" and aw["award"]["agreement_no"].startswith("SCA") and aw["award"]["accepted_expired"] == ["Electrical licence"], aw.get("award"))
    st_, html = call("GET", f"/subcontracts/{sc['id']}/agreement", token=T["pm"])
    check("K1.5 printable agreement", st_ == 200 and b"Subcontract agreement" in html and b"5% is held" in html.replace(b"5%", b"5%"), st_)
    # certificates
    c1 = expect("K1.6 certificate 1", call("POST", f"/subcontracts/{sc['id']}/certificates", {"measured": [{"line_id": lines[0]["id"], "qty_to_date": 20}]}, T["pm"]), 201)
    check("K1.6 gross, retention, net", c1["gross_this"] == 17000 and c1["retention"] == 850 and c1["net"] == 16150, c1)
    expect("K1.6 one draft at a time", call("POST", f"/subcontracts/{sc['id']}/certificates", {"measured": []}, T["pm"]), 409)
    expect("K1.6 pay before approval", call("POST", f"/sub-certificates/{c1['id']}/pay", {}, T["accounts"]), 409)
    a1 = expect("K1.6 approve", call("POST", f"/sub-certificates/{c1['id']}/approve", {}, T["pm"]))
    cost = mongo.costs.find_one({"_id": ObjectId(a1["cost_id"])})
    check("K1.6 cost booked as Subcontract", cost and cost["category"] == "Subcontract" and cost["amount"] == 17000 and cost["status"] == "approved", cost)
    expect("K1.6 quantity cannot go down", call("POST", f"/subcontracts/{sc['id']}/certificates", {"measured": [{"line_id": lines[0]["id"], "qty_to_date": 10}]}, T["pm"]), 400)
    expect("K1.6 not over 110%", call("POST", f"/subcontracts/{sc['id']}/certificates", {"measured": [{"line_id": lines[0]["id"], "qty_to_date": 50}]}, T["pm"]), 400)
    c2 = expect("K1.6 certificate 2", call("POST", f"/subcontracts/{sc['id']}/certificates", {"measured": [{"line_id": lines[0]["id"], "qty_to_date": 40}, {"line_id": lines[1]["id"], "qty_to_date": 2}]}, T["pm"]), 201)
    check("K1.6 only the new work", c2["previous"] == 17000 and c2["gross_this"] == 17000 + 8400 and c2["number"] == 2, c2)
    call("POST", f"/sub-certificates/{c2['id']}/approve", {}, T["pm"])
    expect("K1.7 overpay refused", call("POST", f"/sub-certificates/{c1['id']}/pay", {"amount": 99999}, T["accounts"]), 400)
    pd = expect("K1.7 pay certificate 1", call("POST", f"/sub-certificates/{c1['id']}/pay", {"ref": "NEFT1"}, T["accounts"]))
    check("K1.7 paid", pd["status"] == "paid" and pd["paid"] == 16150, pd)
    expect("K1.8 rating needed", call("POST", f"/subcontracts/{sc['id']}/complete", {"rating": {"quality": 5}}, T["pm"]), 400)
    done = expect("K1.8 complete and rate", call("POST", f"/subcontracts/{sc['id']}/complete", {"rating": {"quality": 5, "time": 4, "safety": 4, "communication": 3}}, T["pm"]))
    rel = done["release_certificate"]
    check("K1.8 retention release certificate", rel and rel["kind"] == "release" and rel["net"] == 850 + 1270, rel)
    check("K1.8 rating kept on the subcontractor", mongo.contacts.find_one({"_id": ObjectId(SUB_CONTACT)})["sub_rating"] == {"avg": 4.0, "jobs": 1})
    subs = expect("K1.9 subcontractor list", call("GET", "/subcontractors", token=T["procurement"]))
    me = next((x for x in subs if x["id"] == SUB_CONTACT), None)
    check("K1.9 rating, jobs, expired docs", me and me["rating"]["avg"] == 4.0 and me["awarded"] >= 1 and me["expired_docs"] == ["Electrical licence"], me)
    pv = next(x for x in call("GET", "/portal/subcontracts", token=T["sub"])[1] if x["id"] == sc["id"])
    check("K1.9 subcontractor sees award and certificates", pv["awarded_to_me"] and len(pv["certificates"]) == 2, pv)
    expect("K1.9 other subcontractor's portal does not list it", call("POST", f"/portal/subcontracts/{sc['id']}/bid", {}, T["client"]), 404)

    # ======================================= block 2: RFIs and submittals =======================================
    k_ph = upload("crack.png", T["site"])
    expect("K2.1 subject needed", call("POST", f"/projects/{PID}/rfis", {"question": "x"}, T["site"]), 400)
    r1 = expect("K2.1 RFI from site", call("POST", f"/projects/{PID}/rfis", {"subject": f"Beam depth at grid C {RUN}", "question": "Drawing shows 450, site has 400. Which?",
                                                                           "files": [k_ph], "priority": "high"}, T["site"]), 201)
    check("K2.1 to the architect by default, due date set", r1["to_user_id"] == U["designer"] and r1["due_date"] and r1["number"].startswith("RFI"), r1)
    check("K2.1 architect told", mongo.notifications.find_one({"company_id": CID, "user_id": U["designer"], "event": "rfi_new"}) is not None)
    expect("K2.2 site cannot answer", call("POST", f"/rfis/{r1['id']}/answer", {"text": "x"}, T["site"]), 403)
    a = expect("K2.2 architect answers with cost impact", call("POST", f"/rfis/{r1['id']}/answer", {"text": "Use 450, add the extra steel", "cost_impact": True,
                                                                                                     "distribution": [SUB_CONTACT]}, T["designer"]))
    check("K2.2 answered, change request drafted, distributed", a["status"] == "answered" and a["co_number"] and a["distribution"][0]["contact_id"] == SUB_CONTACT, a)
    check("K2.2 asker told", mongo.notifications.find_one({"company_id": CID, "user_id": U["site"], "event": "rfi_answered"}) is not None)
    expect("K2.2 answered twice", call("POST", f"/rfis/{r1['id']}/answer", {"text": "again"}, T["designer"]), 409)
    expect("K2.3 reopen needs why", call("POST", f"/rfis/{r1['id']}/reopen", {}, T["site"]), 400)
    ro = expect("K2.3 reopen", call("POST", f"/rfis/{r1['id']}/reopen", {"reason": "What about the lintel?"}, T["site"]))
    check("K2.3 open again with history", ro["status"] == "open" and ro["history"][0]["reopened_because"], ro)
    pr = expect("K2.4 subcontractor asks in the portal", call("POST", f"/portal/projects/{PID}/rfis", {"subject": f"Switch heights {RUN}", "question": "1200 or 1350?"}, T["sub"]), 201)
    expect("K2.4 client cannot raise RFIs", call("POST", f"/portal/projects/{PID}/rfis", {"subject": "x", "question": "y"}, T["client"]), 403)
    pl = expect("K2.4 subcontractor's RFIs", call("GET", f"/portal/projects/{PID}/rfis", token=T["sub"]))
    check("K2.4 own and distributed", {x["id"] for x in pl} >= {pr["id"], r1["id"]}, [x["number"] for x in pl])
    mongo.rfis.update_one({"_id": ObjectId(pr["id"])}, {"$set": {"due_date": day(-2)}})
    worker()
    check("K2.5 overdue reminder", mongo.notifications.find_one({"company_id": CID, "event": "rfi_due", "key": f"rfi-due:{pr['id']}:{date.today().isoformat()}"}) is not None)
    dg = call("GET", "/digest", token=T["pm"])[1]
    row = next((r for r in dg["projects"] if r["project_id"] == PID), {})
    check("K2.5 overdue RFI in the digest", any("RFI waiting" in (x.get("why") or "") for x in row.get("stuck", [])), row.get("stuck"))
    k_sd = upload("shopdwg.pdf", T["sub"], path="/portal/uploads")
    expect("K2.6 client cannot submit", call("POST", f"/portal/projects/{PID}/submittals", {"kind": "Shop drawing", "title": "x", "files": [k_sd]}, T["client"]), 403)
    expect("K2.6 needs a file", call("POST", f"/portal/projects/{PID}/submittals", {"kind": "Shop drawing", "title": "x"}, T["sub"]), 400)
    sb = expect("K2.6 shop drawing submitted", call("POST", f"/portal/projects/{PID}/submittals", {"kind": "Shop drawing", "title": f"DB layout {RUN}", "files": [k_sd],
                                                                                                    "subcontract_id": sc["id"]}, T["sub"]), 201)
    check("K2.6 reviewer is the architect", sb["reviewer_id"] == U["designer"] and sb["status"] == "submitted" and sb["subcontract_title"], sb)
    expect("K2.7 revise needs a note", call("POST", f"/submittals/{sb['id']}/review", {"decision": "revise_resubmit"}, T["designer"]), 400)
    rv = expect("K2.7 revise and resubmit", call("POST", f"/submittals/{sb['id']}/review", {"decision": "revise_resubmit", "note": "Show the earthing"}, T["designer"]))
    check("K2.7 sent back", rv["status"] == "revise_resubmit" and rv["current"]["decision"] == "revise_resubmit", rv["status"])
    k_sd2 = upload("shopdwg2.pdf", T["sub"], path="/portal/uploads")
    rs = expect("K2.7 rev 2", call("POST", f"/portal/submittals/{sb['id']}/resubmit", {"files": [k_sd2], "note": "Earthing added"}, T["sub"]))
    check("K2.7 rev 2 waiting", rs["status"] == "submitted" and rs["current"]["rev"] == 2, rs.get("current"))
    ap = expect("K2.7 approved as noted", call("POST", f"/submittals/{sb['id']}/review", {"decision": "approved_as_noted", "note": "Label the circuits"}, T["designer"]))
    check("K2.7 status", ap["status"] == "approved_as_noted", ap["status"])
    rep = expect("K2.8 RFI report", call("GET", "/reports/rfis", token=T["owner"]))
    mine = next((x for x in rep if x["project_id"] == PID), None)
    check("K2.8 open, overdue, submittals", mine and mine["open"] == 2 and mine["overdue"] >= 1 and mine["submittals"].get("approved_as_noted") == 1, mine)

    # ======================================= block 3: timesheets =======================================
    rates = {U["designer"]: {"cost": 600, "bill": 1500}, U["pm"]: {"cost": 800, "bill": 2000}}
    expect("K3.1 rates (owner)", call("PUT", "/settings/timesheets", {"capacity_hours": 8, "rates": rates}, T["owner"]))
    expect("K3.1 future day", call("POST", "/timesheets", {"project_id": PID, "date": day(1), "hours": 2}, T["designer"]), 400)
    expect("K3.1 quarter hours", call("POST", "/timesheets", {"project_id": PID, "date": day(0), "hours": 1.1}, T["designer"]), 400)
    expect("K3.1 not on the project", call("POST", "/timesheets", {"project_id": PID, "date": day(0), "hours": 2}, T["sales"]), 404)
    e1 = expect("K3.1 log hours", call("POST", "/timesheets", {"project_id": PID, "stage_id": S0, "date": day(0), "hours": 6, "note": "Revisions"}, T["designer"]), 201)
    e2 = expect("K3.1 log more", call("POST", "/timesheets", {"project_id": PID, "date": day(-1), "hours": 3.5, "billable": False}, T["designer"]), 201)
    check("K3.1 cost from the rate", e1["cost"] == 3600 and e1["status"] == "draft", e1)
    expect("K3.1 over 24 h a day", call("POST", "/timesheets", {"project_id": PID, "date": day(0), "hours": 19}, T["designer"]), 400)
    wk = expect("K3.2 my week", call("GET", f"/timesheets?week={day(0)}", token=T["designer"]))
    check("K3.2 totals per day", wk["totals"][day(0)] == 6 and len(wk["days"]) == 7, wk.get("totals"))
    sm = expect("K3.2 submit the week", call("POST", "/timesheets/submit", {"week": day(0)}, T["designer"]))
    check("K3.2 submitted (this week's entries)", sm["submitted"] >= 1, sm)
    check("K3.2 PM told", mongo.notifications.find_one({"company_id": CID, "user_id": U["pm"], "event": "timesheet"}) is not None)
    expect("K3.2 submitted entry locked", call("PUT", f"/timesheets/{e1['id']}", {"hours": 1}, T["designer"]), 409)
    expect("K3.3 designer cannot approve", call("GET", "/timesheets/approvals", token=T["designer"]), 403)
    apl = expect("K3.3 PM's approvals", call("GET", "/timesheets/approvals", token=T["pm"]))
    check("K3.3 listed", any(x["id"] == e1["id"] for x in apl), len(apl))
    expect("K3.3 return needs a reason", call("POST", "/timesheets/decide", {"ids": [e1["id"]], "decision": "reject"}, T["pm"]), 400)
    if mongo.timesheets.find_one({"_id": ObjectId(e2["id"])})["status"] != "submitted":  # last week's entry when today is Monday
        call("POST", "/timesheets/submit", {"week": day(-1)}, T["designer"])
    dc = expect("K3.3 approve", call("POST", "/timesheets/decide", {"ids": [e1["id"], e2["id"]], "decision": "approve"}, T["pm"]))
    check("K3.3 approved", dc["decided"] == 2, dc)
    bh = expect("K3.4 billable hours", call("GET", f"/projects/{PID}/billable-hours", token=T["accounts"]))
    check("K3.4 only billable", bh["total"] == 9000 and bh["people"][0]["hours"] == 6, bh)
    ih = expect("K3.4 invoice the hours", call("POST", f"/projects/{PID}/invoice-hours", {}, T["accounts"]), 201)
    check("K3.4 draft invoice, hours × bill rate", ih["status"] == "draft" and ih["lines"][0]["qty"] == 6 and ih["lines"][0]["rate"] == 1500 and ih["subtotal"] == 9000, ih.get("lines"))
    expect("K3.4 nothing left to invoice", call("POST", f"/projects/{PID}/invoice-hours", {}, T["accounts"]), 409)
    expect("K3.4 deleting the draft frees the hours", call("DELETE", f"/invoices/{ih['id']}", token=T["accounts"]))
    check("K3.4 hours free again", call("GET", f"/projects/{PID}/billable-hours", token=T["accounts"])[1]["total"] == 9000)
    tr = expect("K3.5 report", call("GET", f"/reports/timesheets?from={day(-7)}&to={day(0)}", token=T["owner"]))
    d_ = next((x for x in tr["people"] if x["name"].lower().startswith("architect") or x["hours"] == 9.5), None)
    check("K3.5 hours, billable %, utilisation", d_ and d_["hours"] == 9.5 and d_["billable_pct"] == round(6 / 9.5 * 100, 1) and d_["utilisation"] is not None, tr["people"])
    tid1 = expect("task A", call("POST", f"/projects/{PID}/stages/{S0}/tasks", {"title": f"Concept A {RUN}", "start": day(0), "end": day(2), "assignee_id": U["designer"]}, T["owner"]), 201)
    expect("task B", call("POST", f"/projects/{PID}/stages/{S0}/tasks", {"title": f"Concept B {RUN}", "start": day(1), "end": day(3), "assignee_id": U["designer"]}, T["owner"]), 201)
    rc = expect("K3.6 resource calendar", call("GET", f"/resources?from={day(0)}&to={day(4)}", token=T["pm"]))
    dz = next(x for x in rc["people"] if x["user_id"] == U["designer"])
    check("K3.6 tasks per day, overbooked when two overlap", len(dz["days"][day(1)]["tasks"]) >= 2 and dz["days"][day(0)]["hours"] == 6
          and (day(1) in dz["overbooked"] or date.fromisoformat(day(1)).weekday() == 6), dz["overbooked"])
    expect("K3.6 site cannot plan people", call("GET", "/resources", token=T["site"]), 403)

    # ======================================= block 4: sequences =======================================
    sl = expect("K4.1 sequences and presets", call("GET", "/sequences", token=T["owner"]))
    check("K4.1 presets and triggers", len(sl["presets"]) >= 3 and "lead_cold" in sl["triggers"], list(sl))
    expect("K4.1 sales cannot set up", call("POST", "/sequences", {"name": "x", "trigger": "lead_new", "steps": [{"wait_days": 0, "action": "task", "title": "x"}]}, T["accounts"]), 403)
    expect("K4.1 unknown template", call("POST", "/sequences", {"name": "x", "trigger": "lead_new", "steps": [{"wait_days": 0, "action": "message", "template": "Nope"}]}, T["owner"]), 400)
    sq = expect("K4.1 enquiry sequence", call("POST", "/sequences", {"name": f"Enquiry {RUN}", "trigger": "lead_new", "steps": [
        {"wait_days": 0, "action": "task", "title": "Call {{client}} about {{project}}"},
        {"wait_days": 2, "action": "message", "template": "Follow-up after enquiry"},
        {"wait_days": 4, "action": "notify", "role": "owner", "text": "{{project}} still open after a week"}]}, T["owner"]), 201)
    seqs.append(sq["id"])
    lead = expect("a new enquiry", call("POST", "/leads", {"title": f"Kitchen enquiry {RUN}", "service": "interior", "source": "Walk-in",
                                                          "contact_name": f"Seq Client {RUN}", "contact_phone": f"7{RUN[-7:]}31"}, T["sales"]), 201)
    leads.append(lead["id"])
    lead2 = expect("a second enquiry", call("POST", "/leads", {"title": f"Bath enquiry {RUN}", "service": "interior", "source": "Walk-in",
                                                              "contact_name": f"Seq Two {RUN}", "contact_phone": f"7{RUN[-7:]}32"}, T["sales"]), 201)
    leads.append(lead2["id"])
    now = datetime.utcnow()
    worker(now)
    run = mongo.sequence_runs.find_one({"company_id": CID, "sequence_id": sq["id"], "entity_id": lead["id"]})
    task = mongo.followups.find_one({"company_id": CID, "sequence_run_id": str(run["_id"])}) if run else None
    check("K4.2 run started, day-0 task made", run and run["step"] == 1 and task and task["title"] == f"Call Seq Client {RUN} about Kitchen enquiry {RUN}", (run and run.get("log"), task))
    worker(now)
    check("K4.2 not twice", mongo.followups.count_documents({"company_id": CID, "sequence_run_id": str(run["_id"])}) == 1)
    worker(now + timedelta(days=2, minutes=5))
    run = mongo.sequence_runs.find_one({"_id": run["_id"]})
    check("K4.3 day-2 message step ran (logged on the lead)", run["step"] == 2 and run["log"][-1]["action"] == "message", run["log"])
    lt = mongo.leads.find_one({"_id": ObjectId(lead["id"])})
    check("K4.3 on the lead timeline", any("Automatic" in (a.get("text") or "") for a in lt.get("activities", [])), [a.get("text") for a in lt.get("activities", [])][-2:])
    # the second lead's client replies -> its run stops
    r2 = mongo.sequence_runs.find_one({"company_id": CID, "sequence_id": sq["id"], "entity_id": lead2["id"]})
    mongo.messages.insert_one({"company_id": CID, "contact_id": r2["contact_id"], "channel": "whatsapp", "direction": "in", "text": "yes call me",
                               "created_at": datetime.utcnow() + timedelta(seconds=1)})
    mongo.leads.update_one({"_id": ObjectId(lead["id"])}, {"$set": {"status": "lost"}})  # the first lead is lost
    worker(now + timedelta(days=6, minutes=10))  # both runs' third step falls due
    r2 = mongo.sequence_runs.find_one({"_id": r2["_id"]})
    check("K4.4 stops when the client replies", r2["status"] == "stopped" and r2["reason"] == "the client replied", (r2["status"], r2.get("reason")))
    run = mongo.sequence_runs.find_one({"_id": run["_id"]})
    check("K4.4 stops when the record moves on", run["status"] == "stopped" and "moved on" in run["reason"], (run["status"], run.get("reason")))
    rl = expect("K4.5 runs list", call("GET", f"/sequences/runs?sequence_id={sq['id']}", token=T["owner"]))
    check("K4.5 both runs", len(rl) == 2, len(rl))
    old = expect("K4.6 old records are not picked up", call("POST", "/sequences", {"name": f"Lost {RUN}", "trigger": "lead_lost", "steps": [{"wait_days": 0, "action": "notify", "role": "owner", "text": "x"}]}, T["owner"]), 201)
    seqs.append(old["id"])
    mongo.sequences.update_one({"_id": ObjectId(old["id"])}, {"$set": {"created_at": datetime.utcnow() + timedelta(hours=1)}})
    worker(now + timedelta(days=6, minutes=11))
    check("K4.6 nothing started for leads lost before it was switched on", mongo.sequence_runs.count_documents({"company_id": CID, "sequence_id": old["id"]}) == 0)

    # ======================================= block 5: accounting =======================================
    inv1 = expect("an invoice", call("POST", f"/projects/{PID}/invoices", {"lines": [{"description": "Design fee", "qty": 1, "rate": 100000, "tax_pct": 18}]}, T["accounts"]), 201)
    sent = expect("sent", call("POST", f"/invoices/{inv1['id']}/send", {}, T["accounts"]))
    expect("K5.1 PM cannot connect the books", call("PUT", "/settings/accounting", {"provider": "tally"}, T["pm"]), 403)
    expect("K5.1 Zoho needs credentials", call("PUT", "/settings/accounting", {"provider": "zoho"}, T["owner"]), 400)
    st = expect("K5.1 Tally with own ledger names", call("PUT", "/settings/accounting", {"provider": "tally", "ledgers": {"sales": "Design Fees", "bank": "HDFC Bank"}}, T["accounts"]))
    check("K5.1 saved", st["ledgers"]["sales"] == "Design Fees" and st["ledgers"]["purchase"] == "Purchase", st["ledgers"])
    s_, xml = call("GET", f"/accounting/tally.xml?from={day(-1)}&to={day(0)}", token=T["accounts"])
    check("K5.2 Tally XML", s_ == 200 and b"<ENVELOPE>" in xml and b'VCHTYPE="Sales"' in xml and sent["number"].encode() in xml and b"Design Fees" in xml, xml[:300] if isinstance(xml, bytes) else xml)
    expect("K5.3 sync needs an online provider", call("POST", "/accounting/sync", {}, T["accounts"]), 409)
    call("PUT", "/settings/accounting", {"provider": "sandbox"}, T["accounts"])
    sy = expect("K5.3 sync (sandbox)", call("POST", "/accounting/sync", {"from": day(-1), "to": day(0)}, T["accounts"]))
    check("K5.3 sent", sy["sent"] >= 1 and sy["failed"] == 0, sy)
    sy2 = expect("K5.3 again", call("POST", "/accounting/sync", {"from": day(-1), "to": day(0)}, T["accounts"]))
    check("K5.3 never twice", sy2["sent"] == 0 and sy2["already"] >= 1, sy2)
    lg = expect("K5.4 sync log", call("GET", "/accounting/log", token=T["accounts"]))
    check("K5.4 external id kept", any(x["number"] == sent["number"] and x["external_id"].startswith("SBX-") for x in lg), lg[:2])
    gs = expect("K5.4 status counts", call("GET", "/settings/accounting", token=T["owner"]))
    check("K5.4 secrets never sent back", "client_secret" not in gs and gs["status"]["synced"] >= 1, gs.get("status"))

    # ======================================= block 6: assistant and phone =======================================
    expect("K6.1 claude needs a key", call("PUT", "/settings/assistant", {"mode": "claude"}, T["owner"]), 400)
    asx = expect("K6.1 FAQ mode with an FAQ", call("PUT", "/settings/assistant", {"mode": "faq", "faqs": [{"q": "What are your office hours?", "a": "Mon-Sat, 10am to 7pm."}]}, T["owner"]))
    check("K6.1 saved", asx["mode"] == "faq" and asx["faqs"][0]["a"].startswith("Mon"), asx)
    t1 = expect("K6.2 an FAQ", call("POST", "/assistant/try", {"contact_id": CLIENT_CONTACT, "text": "what are the office hours?"}, T["owner"]))
    check("K6.2 answered from the FAQ", t1["answer"] == "Mon-Sat, 10am to 7pm." and not t1["handoff"], t1)
    t2 = expect("K6.2 how much is due", call("POST", "/assistant/try", {"contact_id": CLIENT_CONTACT, "text": "How much payment is due?"}, T["owner"]))
    check("K6.2 amount due from the project", t2["answer"] and "due" in t2["answer"] and not t2["handoff"], t2)
    t3 = expect("K6.2 a complaint", call("POST", "/assistant/try", {"contact_id": CLIENT_CONTACT, "text": "I want a discount on the sofa"}, T["owner"]))
    check("K6.2 unknown -> handed over", t3["handoff"] and t3["answer"] is None, t3)
    t4 = expect("K6.2 urgent", call("POST", "/assistant/try", {"contact_id": CLIENT_CONTACT, "text": "there was an accident, what is the progress"}, T["owner"]))
    check("K6.2 urgent always handed over", t4["handoff"] and t4["how"] == "urgent", t4)
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"assistant.mode": "claude", "assistant.api_key": "sk-ant-invalid-test"}})
    t5 = expect("K6.3 Claude unavailable falls back to FAQ answers", call("POST", "/assistant/try", {"contact_id": CLIENT_CONTACT, "text": "what are the office hours?"}, T["owner"]))
    check("K6.3 fallback", t5["answer"] == "Mon-Sat, 10am to 7pm." and t5["how"].startswith("faq (claude unavailable"), t5)
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"assistant.mode": "faq"}})
    # through the WhatsApp webhook
    import hashlib
    import hmac
    APP = f"k{RUN}"
    call("PUT", "/settings/messaging", {"provider": "sandbox", "app_secret": APP}, T["owner"])
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {"phone": f"93{RUN}", "whatsapp_opt_in": {"at": datetime.utcnow(), "how": "Written"}, "whatsapp_opt_out": None}})
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"from": f"9193{RUN}", "id": f"wamid.k{RUN}", "type": "text", "text": {"body": "what are the office hours?"}}]}}]}]}).encode()
    req = urllib.request.Request(BASE + f"/webhooks/messages/{CID}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Hub-Signature-256", "sha256=" + hmac.new(APP.encode(), body, hashlib.sha256).hexdigest())
    urllib.request.urlopen(req).read()
    ans = mongo.messages.find_one({"company_id": CID, "author": "Assistant", "contact_id": CLIENT_CONTACT}, sort=[("created_at", -1)])
    check("K6.4 the assistant answered in the thread", ans and ans["text"] == "Mon-Sat, 10am to 7pm." and ans["assistant"]["sent"] == "sent", ans)
    # phone
    ph = expect("K6.5 phone system (sandbox)", call("PUT", "/settings/phone", {"provider": "sandbox", "greeting": "Welcome to Skyline."}, T["owner"]))
    check("K6.5 webhook addresses", ph["webhook_incoming"] and ph["menu"][0]["digit"] == "1", ph)
    hook = ph["webhook_incoming"][4:].rsplit("/", 1)[0]
    expect("K6.5 wrong token", call("POST", f"/webhooks/voice/{CID}/nope/incoming", form={"CallSid": "x"}), 404)
    mongo.users.update_many({"company_id": CID, "role": "accounts"}, {"$set": {"phone": "9800000033"}})
    sid = f"CA{RUN}"
    s_, x1 = call("POST", f"{hook}/incoming", form={"CallSid": sid, "From": f"+9193{RUN}"})
    check("K6.6 greeting and menu", s_ == 200 and b"<Gather" in x1 and b"Welcome to Skyline." in x1 and b"press 3" in x1, x1[:200])
    c_ = mongo.calls.find_one({"company_id": CID, "call_sid": sid})
    check("K6.6 caller recognised", c_ and c_["contact_id"] == CLIENT_CONTACT, c_)
    s_, x2 = call("POST", f"{hook}/menu", form={"CallSid": sid, "Digits": "3"})
    check("K6.6 put through to accounts on the caller's project", s_ == 200 and b"<Dial" in x2 and b"919800000033" in x2, x2)
    s_, x3 = call("POST", f"{hook}/status", form={"CallSid": sid, "DialCallStatus": "no-answer"})
    c_ = mongo.calls.find_one({"_id": c_["_id"]})
    check("K6.7 missed call logged", c_["status"] == "missed" and c_["option"].startswith("Accounts"), c_)
    check("K6.7 call-back follow-up and alert", mongo.followups.find_one({"company_id": CID, "title": {"$regex": "^Call back"}, "notes": {"$regex": RUN}}) is not None
          and mongo.notifications.find_one({"company_id": CID, "event": "call_missed", "key": f"call-missed:{c_['_id']}"}) is not None)
    lc = expect("K6.8 log a call by hand", call("POST", "/calls", {"contact_id": CLIENT_CONTACT, "direction": "out", "duration": 180, "note": "Discussed tiles"}, T["pm"]), 201)
    check("K6.8 logged", lc["duration"] == 180 and lc["routed_name"], lc)
    cl = expect("K6.8 call list", call("GET", f"/calls?contact_id={CLIENT_CONTACT}", token=T["owner"]))
    check("K6.8 both calls", len([x for x in cl if x["id"] in (str(c_["_id"]), lc["id"])]) == 2, len(cl))

    # ======================================= block 7: 3D models =======================================
    k_bad = upload("model.png", T["designer"])
    expect("K7.1 not a model file", call("POST", f"/projects/{PID}/models", {"file_key": k_bad}, T["designer"]), 400)
    k_glb = upload("house.glb", T["designer"], b"glTF" + b"\x00" * 60)
    m1 = expect("K7.1 a GLB model", call("POST", f"/projects/{PID}/models", {"file_key": k_glb, "title": f"House v1 {RUN}", "shared": True}, T["designer"]), 201)
    check("K7.1 format and version", m1["format"] == "glb" and m1["version"] == 1 and m1["url"].startswith("/api/files/"), m1)
    k_ifc = upload("house.ifc", T["designer"], b"ISO-10303-21;" + b"0" * 50)
    m2 = expect("K7.2 IFC v2 replacing v1", call("POST", f"/projects/{PID}/models", {"file_key": k_ifc, "title": f"House v2 {RUN}", "previous_id": m1["id"]}, T["designer"]), 201)
    check("K7.2 before / after link", m2["version"] == 2 and m2["previous_id"] == m1["id"] and mongo.models3d.find_one({"_id": ObjectId(m1["id"])})["superseded_by"] == m2["id"], m2)
    expect("K7.3 a point is needed", call("POST", f"/models/{m2['id']}/comments", {"text": "x"}, T["pm"]), 400)
    c1 = expect("K7.3 comment pinned on the model", call("POST", f"/models/{m2['id']}/comments", {"text": "Window too small", "point": [1.2, 3.4, -0.5], "camera": [5, 5, 5]}, T["pm"]), 201)
    expect("K7.4 client sees shared only", call("POST", f"/portal/models/{m2['id']}/comments", {"text": "x", "point": [0, 0, 0]}, T["client"]), 404)
    pc = expect("K7.4 client comments on the shared model", call("POST", f"/portal/models/{m1['id']}/comments", {"text": "Can we add a skylight?", "point": [0, 5, 0]}, T["client"]), 201)
    pm_ = expect("K7.4 portal list", call("GET", f"/portal/projects/{PID}/models", token=T["client"]))
    check("K7.4 one shared model", [x["id"] for x in pm_] == [m1["id"]], [x["id"] for x in pm_])
    tk = expect("K7.5 comment becomes a task", call("POST", f"/models/{m2['id']}/comments/{c1['id']}/task", {"stage_id": S0}, T["designer"]), 201)
    check("K7.5 resolved with the task", next(c for c in tk["comments"] if c["id"] == c1["id"])["task_id"], tk["comments"])
    ch = expect("K7.5 client comment becomes a change request", call("POST", f"/models/{m1['id']}/comments/{pc['id']}/change", {}, T["pm"]), 201)
    co = mongo.change_orders.find_one({"_id": ObjectId(next(c for c in ch["comments"] if c["id"] == pc["id"])["co_id"])})
    check("K7.5 the client's request", co and co["requested"]["kind"] == "client" and "skylight" in co["title"], co and co.get("requested"))
    expect("K7.6 a model with a task is kept", call("DELETE", f"/models/{m2['id']}", token=T["designer"]), 409)
    expect("K7.6 site cannot add models", call("POST", f"/projects/{PID}/models", {"file_key": k_glb}, T["site"]), 403)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    failures.append(f"crashed: {e}")
finally:
    pids = projects if not os.getenv("KEEP") else []
    for col in ("notifications", "project_activity", "subcontracts", "sub_certificates", "costs", "rfis", "submittals", "timesheets", "invoices", "change_orders",
                "messages", "models3d", "receipts"):
        mongo[col].delete_many({"company_id": CID, "project_id": {"$in": pids}})
    mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
    for sid_ in seqs:
        mongo.sequence_runs.delete_many({"company_id": CID, "sequence_id": sid_})
        mongo.sequences.delete_one({"_id": ObjectId(sid_)})
    mongo.followups.delete_many({"company_id": CID, "$or": [{"related.id": {"$in": leads}}, {"title": {"$regex": "^Call back"}}, {"sequence_run_id": {"$exists": True}}]})
    lead_contacts = [x.get("contact_id") for x in mongo.leads.find({"_id": {"$in": [ObjectId(x) for x in leads]}})]
    mongo.leads.delete_many({"_id": {"$in": [ObjectId(x) for x in leads]}})
    mongo.contacts.delete_many({"_id": {"$in": [ObjectId(x) for x in contacts_made + [c for c in lead_contacts if c]]}})
    mongo.messages.delete_many({"company_id": CID, "contact_id": {"$in": [c for c in lead_contacts if c]}})
    mongo.messages.delete_many({"company_id": CID, "$or": [{"from": f"9193{RUN}"}, {"to": f"9193{RUN}"}]})
    mongo.calls.delete_many({"company_id": CID, "$or": [{"call_sid": f"CA{RUN}"}, {"note": "Discussed tiles"}]})
    mongo.accounting_sync.delete_many({"company_id": CID})
    mongo.files.delete_many({"company_id": CID, "key": {"$in": keys}})
    mongo.notifications.delete_many({"company_id": CID, "event": {"$in": ["sequence_task", "call_missed", "rfi_due", "assistant_handoff"]}})
    restore = {k: company_before.get(k) for k in ("timesheets", "accounting", "assistant", "phone", "messaging")}
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": restore})
    mongo.contacts.update_one({"_id": ObjectId(SUB_CONTACT)}, {"$set": {"types": sub_before.get("types"), "compliance": sub_before.get("compliance") or []},
                                                                "$unset": {"sub_rating": ""}})
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {k: client_before.get(k) for k in ("phone", "whatsapp_opt_in", "whatsapp_opt_out")}})
    for uid_, ph_ in users_before.items():
        mongo.users.update_one({"_id": uid_}, {"$set": {"phone": ph_}})

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
