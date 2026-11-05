"""Real-world regression: company isolation on every newer feature, and each role doing its real job — and being
refused everything outside it. Realistic construction / interior situations (client scope change, monsoon, late
material, festival holiday, unpaid subscription, a staff member leaving). Cleans up everything it creates.

    docker compose exec backend python tests/test_realworld.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("API", "http://localhost:5000/api")
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
    ok = res[0] in status if isinstance(status, tuple) else res[0] == status
    check(name, ok, f"got {res[0]} {res[1].get('error', '') if isinstance(res[1], dict) else ''}")
    return res[1]


def login(email, pw="Demo@123"):
    s, d = call("POST", "/auth/login", {"email": email, "password": pw})
    assert s == 200, (email, s, d)
    return d["token"]


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
ROLES = ("owner", "sales", "pm", "designer", "estimator", "site", "procurement", "accounts")
T = {r: login(f"{r}@skyline.test") for r in ROLES}
for r in ("client", "vendor", "subcontractor", "consultant"):
    T[r] = login(f"{r}@skyline.test")
T["nest"] = login("owner@nest.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
NEST = mongo.users.find_one({"email": "owner@nest.test"})["company_id"]
contact_of = lambda e: mongo.users.find_one({"email": e})["contact_id"]
projects, temp_users = [], []

try:
    # ---------- a real project: design-and-build villa, the client and a vendor on the team ----------
    p = expect("villa project", call("POST", "/projects", {"name": f"Villa {RUN}", "services": ["architecture", "construction"],
                                                           "start": day(0), "value": 4500000, "client_id": contact_of("client@skyline.test")},
                                     T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    for who, role, acc in (("pm", "Project Manager", "edit"), ("designer", "Architect", "edit"), ("site", "Site Supervisor", "view"),
                           ("accounts", "Accounts", "view")):
        call("POST", f"/projects/{pid}/team", {"user_id": U[who], "project_role": role, "access": acc}, T["owner"])
    call("POST", f"/projects/{pid}/team", {"contact_id": contact_of("vendor@skyline.test"), "project_role": "Supplier"}, T["owner"])
    p = call("GET", f"/projects/{pid}", token=T["owner"])[1]
    arch = next(s for s in p["stages"] if s["service"] == "architecture")
    cons = next(s for s in p["stages"] if s["service"] == "construction")
    call("PUT", f"/projects/{pid}/stages/{cons['id']}", {"budget": 800000}, T["owner"])
    r = call("POST", f"/projects/{pid}/stages/{cons['id']}/tasks", {"title": f"Footing {RUN}", "start": day(0), "end": day(5),
                                                                    "assignee_id": U["site"]}, T["pm"])[1]
    task = next(t for s in r["stages"] for t in s["tasks"] if t["title"] == f"Footing {RUN}")
    call("POST", f"/projects/{pid}/tasks/{task['id']}/comments", {"text": f"Level check {RUN}"}, T["pm"])
    call("POST", f"/projects/{pid}/baseline", {}, T["pm"])
    m = call("POST", f"/projects/{pid}/meetings", {"title": f"Kick-off {RUN}", "at": f"{day(1)}T05:00", "staff": [U["pm"]]}, T["pm"])[1]

    # ================= company isolation: Nest must never reach Skyline's project =================
    for path in (f"/projects/{pid}", f"/projects/{pid}/activity", f"/projects/{pid}/health", f"/projects/{pid}/waiting",
                 f"/projects/{pid}/delays", f"/projects/{pid}/meetings", f"/projects/{pid}/baselines", f"/projects/{pid}/dashboard",
                 f"/projects/{pid}/tasks/{task['id']}/comments", f"/projects/{pid}/contract", f"/projects/{pid}/handover"):
        s = call("GET", path, token=T["nest"])[0]
        check(f"isolation: Nest cannot read {path.replace(pid, '<id>')}", s in (403, 404), s)
    for method, path, body in (("POST", f"/projects/{pid}/tasks/{task['id']}/comments", {"text": "x"}),
                               ("POST", f"/projects/{pid}/stages/{cons['id']}/checklist", {"text": "x"}),
                               ("POST", f"/projects/{pid}/stages/{arch['id']}/signoff", {"name": "x", "method": "Email"}),
                               ("POST", f"/projects/{pid}/baseline", {}),
                               ("POST", f"/projects/{pid}/meetings", {"title": "x", "at": f"{day(1)}T05:00"}),
                               ("PUT", f"/projects/{pid}/meetings/{m['id']}", {"notes": "x"}),
                               ("POST", f"/projects/{pid}/meetings/{m['id']}/publish", {}),
                               ("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "done"}),
                               ("DELETE", f"/projects/{pid}", None)):
        s = call(method, path, body, T["nest"])[0]
        check(f"isolation: Nest cannot {method} {path.replace(pid, '<id>').replace(task['id'], '<t>')}", s in (403, 404), s)
    nw = call("GET", "/waiting", token=T["nest"])[1]
    check("isolation: Nest's waiting list holds nothing of Skyline", all(r_["project_id"] != pid for r_ in nw))
    check("isolation: Nest's calendar is its own", call("GET", "/settings/calendar", token=T["nest"])[0] == 200)
    check("isolation: Nest project list has no Skyline project", all(x["id"] != pid for x in call("GET", "/projects", token=T["nest"])[1]))

    # ================= Site Supervisor: does site work, never sees money, cannot run the project =================
    sp = expect("site sees the project they are on", call("GET", f"/projects/{pid}", token=T["site"]), 200)
    check("site: no project value", "value" not in sp)
    check("site: no stage budgets", all("budget" not in s for s in sp["stages"]))
    sd = call("GET", f"/projects/{pid}/dashboard", token=T["site"])[1]
    check("site: dashboard without budget", "budget" not in sd)
    mongo.costs.insert_one({"company_id": CID, "project_id": pid, "amount": 900000, "status": "approved", "note": f"rt {RUN}"})
    oh = call("GET", f"/projects/{pid}/health", token=T["owner"])[1]
    check("owner: health says the budget is overspent", "Spent more" in next(x for x in oh["parts"] if x["key"] == "budget")["why"])
    sh = expect("site: health", call("GET", f"/projects/{pid}/health", token=T["site"]), 200)
    bpart = next((x for x in sh["parts"] if x["key"] == "budget"), None)
    check("site: health does not reveal spending", bpart is None or "spent" not in bpart["why"].lower(), bpart)
    mongo.costs.delete_many({"company_id": CID, "note": f"rt {RUN}"})
    expect("site updates own task", call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "in_progress"}, T["site"]), 200)
    expect("site adds a step to own task", call("POST", f"/projects/{pid}/tasks/{task['id']}/checklist", {"text": "Rebar checked"}, T["site"]), 201)
    expect("site comments", call("POST", f"/projects/{pid}/tasks/{task['id']}/comments", {"text": "Started"}, T["site"]), 201)
    expect("site cannot rename the task", call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"title": "x"}, T["site"]), 403)
    expect("site cannot add tasks", call("POST", f"/projects/{pid}/stages/{cons['id']}/tasks", {"title": "x", "start": day(0), "end": day(1)}, T["site"]), 403)
    expect("site cannot set a baseline", call("POST", f"/projects/{pid}/baseline", {}, T["site"]), 403)
    expect("site cannot tick the stage closing checklist", call("PUT", f"/projects/{pid}/stages/{cons['id']}/checklist/{cons['checklist'][0]['id']}",
                                                               {"done": True}, T["site"]), 403)
    expect("site cannot plan meetings", call("POST", f"/projects/{pid}/meetings", {"title": "x", "at": f"{day(1)}T05:00"}, T["site"]), 403)
    expect("site has no leads", call("GET", "/leads", token=T["site"]), 403)
    expect("site cannot see another project", call("GET", f"/projects/{mongo.projects.find_one({'company_id': CID, '_id': {'$ne': ObjectId(pid)}, 'team.user_id': {'$ne': U['site']}})['_id']}", token=T["site"]), 404)
    expect("site cannot change the calendar", call("PUT", "/settings/calendar", {"working_days": [0]}, T["site"]), 403)

    # ================= Architect / Designer: design stages only =================
    expect("designer edits the design stage", call("PUT", f"/projects/{pid}/stages/{arch['id']}", {"name": arch["name"]}, T["designer"]), 200)
    expect("designer adds a design task", call("POST", f"/projects/{pid}/stages/{arch['id']}/tasks",
                                              {"title": f"Concept {RUN}", "start": day(0), "end": day(3)}, T["designer"]), 201)
    expect("designer cannot touch the construction stage", call("POST", f"/projects/{pid}/stages/{cons['id']}/tasks",
                                                               {"title": "x", "start": day(0), "end": day(3)}, T["designer"]), 403)
    expect("designer cannot change the team", call("POST", f"/projects/{pid}/team", {"user_id": U["sales"], "project_role": "Sales", "access": "view"}, T["designer"]), 403)

    # ================= Project Manager: runs the project, cannot override or delete =================
    expect("PM cannot close a stage that is not ready", call("PUT", f"/projects/{pid}/milestones/{cons['gate']['milestone_id']}",
                                                            {"status": "achieved", "override_reason": "push"}, T["pm"]), 403)
    expect("PM cannot delete the project", call("DELETE", f"/projects/{pid}", token=T["pm"]), 403)
    expect("PM plans a meeting", call("POST", f"/projects/{pid}/meetings", {"title": f"Review {RUN}", "at": f"{day(2)}T05:00"}, T["pm"]), 201)

    # ================= Accounts / Sales / Estimator / Procurement: read-only on projects =================
    for role in ("accounts", "sales", "estimator", "procurement"):
        s = call("PUT", f"/projects/{pid}", {"name": "x"}, T[role])[0]
        check(f"{role}: cannot edit the project", s == 403, s)
    expect("accounts (on the team, view) reads the project", call("GET", f"/projects/{pid}", token=T["accounts"]), 200)
    expect("accounts sees the value", call("GET", f"/projects/{pid}", token=T["accounts"]), 200)
    check("accounts sees money", "value" in call("GET", f"/projects/{pid}", token=T["accounts"])[1])
    expect("sales (not on the team) cannot open it", call("GET", f"/projects/{pid}", token=T["sales"]), 404)
    expect("accounts cannot comment-free-write tasks", call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "done"}, T["accounts"]), 403)

    # ================= portal users =================
    cp = expect("client sees own project in the portal", call("GET", f"/portal/projects/{pid}", token=T["client"]), 200)
    check("client: no money in the portal", "value" not in cp and all("budget" not in s for s in cp["stages"]))
    expect("client cannot use staff APIs", call("GET", f"/projects/{pid}", token=T["client"]), 403)
    expect("client cannot read comments", call("GET", f"/projects/{pid}/tasks/{task['id']}/comments", token=T["client"]), 403)
    vp = expect("vendor on the team sees the project", call("GET", f"/portal/projects/{pid}", token=T["vendor"]), 200)
    check("vendor: no 'waiting on you' meant for the client", vp.get("waiting_on_you") == [])
    expect("subcontractor not on the team: no access", call("GET", f"/portal/projects/{pid}", token=T["subcontractor"]), 404)
    expect("consultant not on the team: no access", call("GET", f"/portal/projects/{pid}", token=T["consultant"]), 404)

    # ================= real situations =================
    # client changes the scope after the baseline -> delay on the client
    expect("scope change pushes the footing", call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"end": day(9), "delay_reason": "client_change",
                                                                                                    "delay_note": "Basement added"}, T["pm"]), 200)
    # monsoon: weather delay counts against nobody
    expect("monsoon delay", call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"end": day(12), "delay_reason": "weather"}, T["pm"]), 200)
    dl = call("GET", f"/projects/{pid}/delays", token=T["owner"])[1]
    parties = {x["party"]: x["days"] for x in dl["by_party"]}
    check("delays split by who caused them", "client" in parties and "none" in parties, parties)
    # vendor late -> blocked task waiting on the vendor, visible to the client? no
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "blocked", "waiting_on": {"party": "vendor", "note": "Steel"}}, T["pm"])
    check("client portal does not show vendor waits", call("GET", f"/portal/projects/{pid}", token=T["client"])[1]["waiting_on_you"] == [])
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "blocked", "waiting_on": {"party": "client", "note": f"Tile choice {RUN}"}}, T["pm"])
    check("client portal shows what waits on them", any(RUN in (w_["note"] or "") for w_ in call("GET", f"/portal/projects/{pid}", token=T["client"])[1]["waiting_on_you"]))
    # a staff member leaves: deactivated user is locked out at once
    tmp = call("POST", "/users", {"name": f"Leaver {RUN}", "email": f"leaver{RUN}@skyline.test", "role": "site", "password": "Leave@1"}, T["owner"])[1]
    temp_users.append(tmp["id"])
    lt = login(f"leaver{RUN}@skyline.test", "Leave@1")
    call("PUT", f"/users/{tmp['id']}", {"active": False}, T["owner"])
    expect("deactivated user locked out immediately", call("GET", "/auth/me", token=lt), 401)
    # unpaid subscription: read-only company can read but not write
    mongo.companies.update_one({"_id": ObjectId(NEST)}, {"$set": {"status": "read_only"}})
    expect("read-only company: reads still work", call("GET", "/projects", token=T["nest"]), 200)
    expect("read-only company: writes refused", call("POST", "/projects", {"name": "x", "services": ["interior"]}, T["nest"]), 402)
    mongo.companies.update_one({"_id": ObjectId(NEST)}, {"$set": {"status": "active"}})
    # festival holiday: a lag skips it
    cal_before = mongo.companies.find_one({"_id": ObjectId(CID)}).get("calendar")
    call("PUT", "/settings/calendar", {"working_days": [0, 1, 2, 3, 4, 5], "holidays": [{"date": day(1), "name": f"Diwali {RUN}"}]}, T["owner"])
    from app.services import workdays
    check("holiday skipped when counting", workdays.add_working(day(0), 1, {"working_days": [0, 1, 2, 3, 4, 5, 6],
                                                                           "holidays": [{"date": day(1), "name": "x"}]}) == day(2))
    if cal_before:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"calendar": cal_before}})
    else:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"calendar": ""}})
    # wrong / odd input never crashes
    for body in ({"end": "31-12-2026"}, {"start": day(5), "end": day(1)}, {"links": [{"task_id": task["id"]}]}, {"priority": None},
                 {"waiting_on": {"party": None}}, {"title": "🏗️ " * 50}):
        s = call("PUT", f"/projects/{pid}/tasks/{task['id']}", body, T["pm"])[0]
        check(f"bad task input refused cleanly {list(body)}", s in (200, 400, 409), s)
finally:
    for p_ in projects:
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for u_ in temp_users:
        mongo.users.delete_one({"_id": ObjectId(u_)})
    mongo.companies.update_one({"_id": ObjectId(NEST)}, {"$set": {"status": "active"}})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    left = mongo.projects.count_documents({"name": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
