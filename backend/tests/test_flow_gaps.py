"""Flow hand-offs between modules: nothing is left pointing at a missing record and no work is orphaned.
One block per row of PLAN.md "Flow hand-offs".

    docker compose exec backend python tests/test_flow_gaps.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

from pymongo import MongoClient

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


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm")}
staff = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1]}
leads, bids, projects, contacts, fus = [], [], [], [], []
n = 0


def new_lead(**kw):
    global n
    n += 1
    body = {"title": f"Gap lead {n} {RUN}", "service": "construction", "source": "Walk-in", "contact_name": f"Gap client {n} {RUN}",
            "contact_phone": f"8{RUN[-7:]}{n:02d}", "budget": 1000000, **kw}
    lead = expect(f"setup lead {n}", call("POST", "/leads", body, T["sales"]), 201)
    leads.append(lead["id"])
    contacts.append(lead["contact_id"])
    return lead


def new_bid(**kw):
    b = expect("setup bid", call("POST", "/bids", {"title": f"Gap tender {RUN}", "due_date": day(10), "decision": "bid",
                                                   "service": "construction", "value": 2500000, **kw}, T["sales"]), 201)
    bids.append(b["id"])
    return b


def fu_get(fid):
    return next((x for x in call("GET", "/followups", token=T["owner"])[1] if x["id"] == fid), {})


def submit(b, **kw):
    return expect("submit bid", call("PUT", f"/bids/{b['id']}", {"status": "submitted", **kw}, T["sales"]), 200)


try:
    # ---------------- bid won without a lead -> project straight from the bid ----------------
    b = new_bid()
    submit(b)
    expect("bid win needs a client", call("POST", f"/bids/{b['id']}/won", {"pm_id": staff["pm"]}, T["sales"]), 400)
    client = new_lead()["contact_id"]
    submit(b, client_id=client)
    expect("bid win needs a PM", call("POST", f"/bids/{b['id']}/won", {}, T["sales"]), 400)
    expect("bid win PM must manage projects", call("POST", f"/bids/{b['id']}/won", {"pm_id": staff["sales"]}, T["sales"]), 400)
    w = expect("bid won", call("POST", f"/bids/{b['id']}/won", {"pm_id": staff["pm"]}, T["sales"]), 200)
    projects.append(w.get("project_id"))
    p = call("GET", f"/projects/{w.get('project_id')}", token=T["pm"])[1]
    check("bid won -> project created with bid client, service, value", w["status"] == "won" and p.get("client_id") == client
          and p.get("services") == ["construction"] and p.get("value") == 2500000 and p.get("bid_id") == b["id"], p)
    check("bid won -> PM on the team", any(m.get("user_id") == staff["pm"] and m["access"] == "edit" for m in p.get("team", [])))
    expect("won bid is read-only", call("PUT", f"/bids/{b['id']}", {"title": "x"}, T["sales"]), 409)
    expect("won bid cannot be won twice", call("POST", f"/bids/{b['id']}/won", {"pm_id": staff["pm"]}, T["sales"]), 409)
    expect("won bid with a project cannot be deleted", call("DELETE", f"/bids/{b['id']}", token=T["sales"]), 409)

    # ---------------- bid linked to a lead: the lead is won through the bid ----------------
    L = new_lead()
    fu = expect("setup lead follow-up", call("POST", "/followups", {"title": f"Chase {RUN}", "due": day(1),
                                                                    "related": {"type": "lead", "id": L["id"]}}, T["sales"]), 201)
    fus.append(fu["id"])
    b2 = new_bid(lead_id=L["id"], client_id=None, service="interior")
    check("bid takes the lead's client and service", b2.get("client_id") == L["contact_id"] and b2.get("service") == "construction"
          and b2.get("lead_title") == L["title"], b2)
    got = call("GET", f"/leads/{L['id']}", token=T["sales"])[1]
    check("lead page lists its bids", any(x["id"] == b2["id"] for x in got.get("bids", [])))
    submit(b2)
    w2 = expect("linked bid won", call("POST", f"/bids/{b2['id']}/won", {"pm_id": staff["pm"]}, T["sales"]), 200)
    projects.append(w2.get("project_id"))
    got = call("GET", f"/leads/{L['id']}", token=T["sales"])[1]
    check("linked lead is won with the same project", got["status"] == "won" and got["project_id"] == w2.get("project_id"), got.get("status"))
    p2 = call("GET", f"/projects/{w2.get('project_id')}", token=T["pm"])[1]
    check("project from linked bid keeps lead and bid", p2.get("lead_id") == L["id"] and p2.get("bid_id") == b2["id"]
          and p2.get("value") == 2500000, p2.get("value"))
    f = fu_get(fu["id"])
    check("lead follow-ups move to the project", f.get("related", {}).get("id") == w2.get("project_id"), f.get("related"))
    expect("cannot link a bid to a won lead", call("POST", "/bids", {"title": "x", "due_date": day(3), "lead_id": L["id"]}, T["sales"]), 400)

    # ---------------- bid lost -> linked lead lost with the same reason ----------------
    L3 = new_lead()
    fu3 = expect("setup follow-up 3", call("POST", "/followups", {"title": f"Chase3 {RUN}", "due": day(1),
                                                                  "related": {"type": "lead", "id": L3["id"]}}, T["sales"]), 201)
    fus.append(fu3["id"])
    b3 = new_bid(lead_id=L3["id"])
    submit(b3)
    expect("bid loss needs a reason", call("POST", f"/bids/{b3['id']}/lost", {}, T["sales"]), 400)
    l3 = expect("linked bid lost", call("POST", f"/bids/{b3['id']}/lost", {"reason": "Price too high", "note": "L1 lower"}, T["sales"]), 200)
    got = call("GET", f"/leads/{L3['id']}", token=T["sales"])[1]
    check("linked lead lost with the bid's reason", got["status"] == "lost" and got["loss_reason"] == "Price too high"
          and l3["status"] == "lost" and l3.get("loss_reason") == "Price too high", got.get("status"))
    check("lost lead's follow-ups cancelled", fu_get(fu3["id"])["status"] == "cancelled")
    # a lost linked lead blocks winning another bid for it until reopened
    call("POST", f"/leads/{L3['id']}/reopen", {}, T["sales"])
    b3b = new_bid(lead_id=L3["id"])
    submit(b3b)
    call("POST", f"/leads/{L3['id']}/lose", {"reason": "Price too high"}, T["sales"])
    check("lead lost directly -> its submitted bid is lost", call("GET", "/bids", token=T["sales"])[1] and
          next(x for x in call("GET", "/bids", token=T["sales"])[1]["bids"] if x["id"] == b3b["id"])["status"] == "lost")

    # ---------------- lead won directly -> its submitted bid is won ----------------
    L4 = new_lead()
    b4 = new_bid(lead_id=L4["id"])
    b4p = new_bid(lead_id=L4["id"])  # still preparing: left alone
    submit(b4)
    r = expect("lead won directly", call("POST", f"/leads/{L4['id']}/win", {"pm_id": staff["pm"]}, T["sales"]), 200)
    projects.append(r["project_id"])
    allb = {x["id"]: x for x in call("GET", "/bids", token=T["sales"])[1]["bids"]}
    check("submitted bid follows the lead's win", allb[b4["id"]]["status"] == "won" and allb[b4["id"]].get("project_id") == r["project_id"])
    check("preparing bid is not touched", allb[b4p["id"]]["status"] == "preparing")
    submit(b4p)
    w4 = expect("bid for an already-won lead links its project", call("POST", f"/bids/{b4p['id']}/won", {}, T["sales"]), 200)
    check("no second project for the same lead", w4.get("project_id") == r["project_id"], w4.get("project_id"))

    # ---------------- project deleted -> nothing points at it ----------------
    pfu = expect("setup project follow-up", call("POST", "/followups", {"title": f"Site {RUN}", "due": day(2),
                                                                        "related": {"type": "project", "id": r["project_id"]}}, T["pm"]), 201)
    fus.append(pfu["id"])
    expect("owner deletes the won lead's project", call("DELETE", f"/projects/{r['project_id']}", token=T["owner"]), 200)
    projects.remove(r["project_id"])
    check("project follow-ups cancelled", fu_get(pfu["id"])["status"] == "cancelled")
    got = call("GET", f"/leads/{L4['id']}", token=T["sales"])[1]
    check("won lead keeps its result but drops the link", got["status"] == "won" and not got.get("project_id")
          and any("was deleted" in a["text"] for a in got["activities"]), got.get("project_id"))
    allb = {x["id"]: x for x in call("GET", "/bids", token=T["sales"])[1]["bids"]}
    check("bids drop the deleted project", not allb[b4["id"]].get("project_id") and not allb[b4p["id"]].get("project_id"))

    # ---------------- lead deleted -> bids unlinked ----------------
    expect("owner deletes the lead", call("DELETE", f"/leads/{L4['id']}", token=T["owner"]), 200)
    leads.remove(L4["id"])
    allb = {x["id"]: x for x in call("GET", "/bids", token=T["sales"])[1]["bids"]}
    check("bids drop the deleted lead", not allb[b4["id"]].get("lead_id"))

    # ---------------- contact delete guards ----------------
    L5 = new_lead()
    expect("contact with a lead cannot be deleted", call("DELETE", f"/contacts/{L5['contact_id']}", token=T["owner"]), 409)
    c6 = expect("setup contact", call("POST", "/contacts", {"name": f"Gap firm {RUN}", "kind": "company", "types": ["supplier"]}, T["owner"]), 201)
    contacts.append(c6["id"])
    b6 = new_bid(client_id=c6["id"])
    expect("bid client cannot be deleted", call("DELETE", f"/contacts/{c6['id']}", token=T["owner"]), 409)
    call("DELETE", f"/bids/{b6['id']}", token=T["sales"])
    ref = expect("setup referred lead", call("POST", "/leads", {"title": f"Ref {RUN}", "service": "construction", "source": "Referral",
                                                               "referred_by": c6["id"], "contact_name": f"Ref client {RUN}",
                                                               "contact_phone": f"7{RUN[-7:]}99"}, T["sales"]), 201)
    leads.append(ref["id"])
    contacts.append(ref["contact_id"])
    expect("referrer cannot be deleted", call("DELETE", f"/contacts/{c6['id']}", token=T["owner"]), 409)

    # ---------------- a project's client is listed as a client ----------------
    pc = expect("project with a supplier as client", call("POST", "/projects", {"name": f"Gap proj {RUN}", "services": ["construction"],
                                                                                "client_id": c6["id"]}, T["pm"]), 201)
    projects.append(pc["id"])
    check("client type added to the contact", "client" in call("GET", f"/contacts/{c6['id']}", token=T["owner"])[1]["types"])

    # ---------------- reassigning a lead hands over its follow-ups ----------------
    L7 = new_lead()
    fu7 = expect("setup follow-up 7", call("POST", "/followups", {"title": f"Chase7 {RUN}", "due": day(1),
                                                                  "related": {"type": "lead", "id": L7["id"]}}, T["sales"]), 201)
    fus.append(fu7["id"])
    call("PUT", f"/leads/{L7['id']}", {"owner_id": staff["owner"]}, T["sales"])
    f7 = fu_get(fu7["id"])
    check("lead reassignment moves open follow-ups", f7.get("owner_id") == staff["owner"], f7.get("owner_name"))

    # ---------------- a refused lead saves nothing ----------------
    before = len(call("GET", "/contacts", token=T["owner"])[1])
    expect("refused lead", call("POST", "/leads", {"title": f"Bad {RUN}", "service": "construction", "source": "Walk-in", "budget": -5,
                                                  "contact_name": f"Orphan {RUN}", "contact_phone": "9876500000"}, T["sales"]), 400)
    check("refused lead leaves no stray contact", len(call("GET", "/contacts", token=T["owner"])[1]) == before)

    # ---------------- new enquirer can be a company ----------------
    L8 = new_lead(contact_is_company=True)
    check("company enquirer saved as company", call("GET", f"/contacts/{L8['contact_id']}", token=T["owner"])[1]["kind"] == "company")

    # ---------------- deactivating a user hands over open work ----------------
    email = "handover.test@skyline.test"
    u = next((x for x in call("GET", "/users", token=T["owner"])[1] if x["email"] == email), None)
    if u:
        expect("reactivate test user", call("PUT", f"/users/{u['id']}", {"active": True, "role": "sales"}, T["owner"]), 200)
    else:
        u = expect("create test user", call("POST", "/users", {"name": "Handover Test", "email": email, "role": "sales",
                                                              "password": PW}, T["owner"]), 201)
    hl = new_lead(owner_id=u["id"])
    hf = expect("setup user follow-up", call("POST", "/followups", {"title": f"HO {RUN}", "due": day(1), "owner_id": u["id"],
                                                                     "related": {"type": "lead", "id": hl["id"]}}, T["sales"]), 201)
    fus.append(hf["id"])
    hp = expect("setup project for tasks", call("POST", "/projects", {"name": f"HO proj {RUN}", "services": ["construction"]}, T["pm"]), 201)
    projects.append(hp["id"])
    call("POST", f"/projects/{hp['id']}/team", {"user_id": u["id"], "project_role": "Sales", "access": "view"}, T["pm"])
    st = hp["stages"][0]["id"]
    expect("setup task", call("POST", f"/projects/{hp['id']}/stages/{st}/tasks", {"title": f"HO task {RUN}", "assignee_id": u["id"],
                                                                          "start": day(0), "end": day(3)}, T["pm"]), 201)
    hp2 = expect("setup second project", call("POST", "/projects", {"name": f"HO proj2 {RUN}", "services": ["construction"]}, T["pm"]), 201)
    projects.append(hp2["id"])
    for who in (u["id"], staff["sales"]):
        call("POST", f"/projects/{hp2['id']}/team", {"user_id": who, "project_role": "Sales", "access": "view"}, T["pm"])
    expect("setup task 2", call("POST", f"/projects/{hp2['id']}/stages/{hp2['stages'][0]['id']}/tasks",
                                {"title": f"HO task2 {RUN}", "assignee_id": u["id"], "start": day(0), "end": day(3)}, T["pm"]), 201)
    work = call("GET", f"/users/{u['id']}/open-work", token=T["owner"])[1]
    check("open work counted", work == {"leads": 1, "followups": 1, "tasks": 2}, work)
    expect("deactivate with open work needs a hand-over", call("PUT", f"/users/{u['id']}", {"active": False}, T["owner"]), 409)
    expect("cannot hand over to self", call("PUT", f"/users/{u['id']}", {"active": False, "handover_to": u["id"]}, T["owner"]), 400)
    expect("hand over and deactivate", call("PUT", f"/users/{u['id']}", {"active": False, "handover_to": staff["sales"]}, T["owner"]), 200)
    check("lead handed over", call("GET", f"/leads/{hl['id']}", token=T["sales"])[1]["owner_id"] == staff["sales"])
    check("follow-up handed over", fu_get(hf["id"])["owner_id"] == staff["sales"])
    tk = [x for s in call("GET", f"/projects/{hp['id']}", token=T["pm"])[1]["stages"] for x in s.get("tasks", [])][0]
    check("task unassigned where the new owner is not on the team", tk.get("assignee_id") is None, tk.get("assignee_name"))
    tk2 = [x for s in call("GET", f"/projects/{hp2['id']}", token=T["pm"])[1]["stages"] for x in s.get("tasks", [])][0]
    check("task moves to the new owner where they are on the team", tk2.get("assignee_id") == staff["sales"], tk2.get("assignee_name"))
    check("deactivated user has no open work", call("GET", f"/users/{u['id']}/open-work", token=T["owner"])[1]
          == {"leads": 0, "followups": 0, "tasks": 0})

    # ---------------- website form closed for read-only / cancelled companies ----------------
    key = call("GET", "/leads/meta", token=T["owner"])[1]["form_key"]
    sky = mongo.companies.find_one({"lead_form_key": key})
    for status in ("read_only", "cancelled"):
        mongo.companies.update_one({"_id": sky["_id"]}, {"$set": {"status": status}})
        s1 = call("GET", f"/public/lead-form/{key}")[0]
        s2 = call("POST", f"/public/lead-form/{key}", {"name": "Closed test", "phone": "9000000001"})[0]
        mongo.companies.update_one({"_id": sky["_id"]}, {"$set": {"status": sky.get("status", "active")}})
        check(f"website form closed when {status}", s1 == 404 and s2 == 404, (s1, s2))
finally:
    # ---------------- cleanup (order matters: projects before bids, leads before contacts) ----------------
    for f in fus:
        call("DELETE", f"/followups/{f}", token=T["owner"])
    for p in projects:
        if p:
            call("DELETE", f"/projects/{p}", token=T["owner"])
    for b in bids:
        call("DELETE", f"/bids/{b}", token=T["sales"])
    for x in leads:
        call("DELETE", f"/leads/{x}", token=T["owner"])
    for c in reversed(contacts):
        call("DELETE", f"/contacts/{c}", token=T["owner"])
    check("cleanup: no test leads left", not any(RUN in x["title"] for x in call("GET", "/leads", token=T["owner"])[1]))
    check("cleanup: no test bids left", not any(RUN in x["title"] for x in call("GET", "/bids", token=T["owner"])[1]["bids"]))
    mongo.users.delete_many({"email": "handover.test@skyline.test"})  # no delete endpoint for users: remove the test login
    check("cleanup: no test contacts left", not any(RUN in x["name"] for x in call("GET", "/contacts", token=T["owner"])[1]))

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
