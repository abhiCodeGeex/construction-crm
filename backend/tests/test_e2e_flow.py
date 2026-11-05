"""End-to-end story: one website enquiry followed all the way to a completed project, switching roles at each
handover and checking follow-ups throughout. Complements the per-phase suites.

    docker compose exec backend python tests/test_e2e_flow.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = os.getenv("API", "http://localhost:5000/api")


def drop_test_logins(emails):
    """Users have no delete endpoint (deactivation keeps history), so tests remove their own test logins directly."""
    from pymongo import MongoClient
    MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")].users.delete_many({"email": {"$in": emails}})

PW = "Demo@123"
RUN = str(int(time.time() * 1000))[-8:]
failures, passed, step_results = [], 0, []
current = {"name": None, "ok": 0, "bad": 0}


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


def step(name):
    if current["name"]:
        step_results.append(dict(current))
    current.update(name=name, ok=0, bad=0)


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        current["ok"] += 1
    else:
        current["bad"] += 1
        failures.append(f"[{current['name']}] {name} -> {detail}")


def ok(name, res, status=200):
    check(name, res[0] == status, f"got {res[0]} {res[1].get('error', '') if isinstance(res[1], dict) else ''}")
    return res[1]


def login(email, pw=PW):
    s, d = call("POST", "/auth/login", {"email": email, "password": pw})
    assert s == 200, (email, s, d)
    return d["token"]


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm", "designer", "site", "accounts")}
uid = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1] if u["kind"] == "staff"}
cleanup = {"followups": [], "projects": [], "leads": [], "contacts": [], "users": []}
name, phone = f"Anita Desai {RUN}", f"9{RUN[-7:]}42"

# 1 -------------------------------------------------------------------------------------------------
step("1. Website enquiry arrives")
key = call("GET", "/leads/meta", token=T["owner"])[1]["form_key"]
ok("public form accepts enquiry", call("POST", f"/public/lead-form/{key}", {
    "name": name, "phone": phone, "email": f"anita{RUN}@example.test", "service": "construction",
    "project_type": "New build", "location": "Whitefield, Bengaluru", "timeline": "3–6 months",
    "message": "G+2 house on 30x40 plot"}, headers={"X-Forwarded-For": f"10.99.{RUN[-3:-1]}.{int(RUN[-2:]) % 250}"}), 201)
lead = next((x for x in call("GET", "/leads?owner_id=none&source=Website%20form", token=T["owner"])[1] if x["contact_name"] == name), None)
check("lead is created, unassigned, at first stage", lead and lead["owner_id"] is None and lead["stage"] == "Lead", lead)
LID = lead["id"]
cleanup["leads"].append(LID)
cleanup["contacts"].append(lead["contact_id"])
contact = call("GET", f"/contacts/{lead['contact_id']}", token=T["owner"])[1]
check("enquirer saved as a Client contact", contact["types"] == ["client"] and contact["phone"] == phone)
check("home shows it as unassigned", call("GET", "/home", token=T["owner"])[1]["leads"]["unassigned"] >= 1)

# 2 -------------------------------------------------------------------------------------------------
step("2. Owner assigns the lead to Sales")
upd = ok("assign salesperson", call("PUT", f"/leads/{LID}", {"owner_id": uid["sales"], "budget": 6500000, "area": 3600}, T["owner"]))
check("salesperson set", upd["owner_name"].startswith("Sales"))
check("sales sees it in their leads", any(x["id"] == LID for x in call("GET", f"/leads?owner_id={uid['sales']}", token=T["sales"])[1]))
check("no follow-up yet is flagged", upd["next_followup"] is None)

# 3 -------------------------------------------------------------------------------------------------
step("3. Sales responds and plans follow-ups")
ok("log first call", call("POST", f"/leads/{LID}/activities", {"type": "call", "text": "Discussed plot, floors and budget — wants a site visit this week",
                                                               "outcome": "Reached", "next_due": day(1)}, T["sales"]), 201)
check("first response recorded", call("GET", f"/leads/{LID}", token=T["sales"])[1]["first_response_at"] is not None)
f_over = ok("follow-up already overdue", call("POST", "/followups", {"title": f"Send sample floor plans {RUN}", "due": day(-1),
                                                                    "priority": "high", "channel": "email",
                                                                    "related": {"type": "lead", "id": LID}}, T["sales"]), 201)
f_today = ok("follow-up due today", call("POST", "/followups", {"title": f"Confirm site visit time {RUN}", "due": day(0),
                                                               "channel": "call", "related": {"type": "lead", "id": LID}}, T["sales"]), 201)
f_pm = ok("follow-up assigned to PM", call("POST", "/followups", {"title": f"Join site visit and check soil {RUN}", "due": day(2),
                                                                 "owner_id": uid["pm"], "channel": "site_visit",
                                                                 "related": {"type": "lead", "id": LID}}, T["sales"]), 201)
cleanup["followups"] += [f_over["id"], f_today["id"], f_pm["id"]]
td = call("GET", "/followups/today", token=T["sales"])[1]
check("sales Today: overdue bucket", f_over["id"] in [x["id"] for x in td["overdue"]])
check("sales Today: today bucket", f_today["id"] in [x["id"] for x in td["today"]])
check("PM's item not on sales' Today", f_pm["id"] not in [x["id"] for b in td.values() for x in b])
check("PM sees assigned item in upcoming", f_pm["id"] in [x["id"] for x in call("GET", "/followups/today", token=T["pm"])[1]["upcoming"]])
check("accounts cannot see sales' follow-ups", not any(f["id"] == f_over["id"] for f in call("GET", "/followups", token=T["accounts"])[1]))
home = call("GET", "/home", token=T["sales"])[1]["followups"]
check("home counts overdue/today", home["overdue"] >= 1 and home["today"] >= 1, home)
nf = call("GET", f"/leads/{LID}", token=T["sales"])[1]["next_followup"]
check("lead card shows earliest open follow-up (overdue)", nf and nf["id"] == f_over["id"] and nf["overdue"])

# 4 -------------------------------------------------------------------------------------------------
step("4. Follow-ups are edited, completed, chained")
ok("edit due date & priority", call("PUT", f"/followups/{f_over['id']}", {"due": day(0), "priority": "normal"}, T["sales"]))
check("edit moves it out of overdue", f_over["id"] in [x["id"] for x in call("GET", "/followups/today", token=T["sales"])[1]["today"]])
ok("outcome required to complete", call("POST", f"/followups/{f_over['id']}/done", {}, T["sales"]), 400)
ok("complete with outcome", call("POST", f"/followups/{f_over['id']}/done", {"outcome": "Plans emailed"}, T["sales"]))
ok("cannot edit a completed follow-up", call("PUT", f"/followups/{f_over['id']}", {"title": "x"}, T["sales"]), 409)
ok("PM completes their item and chains the next", call("POST", f"/followups/{f_pm['id']}/done", {
    "outcome": "Soil looks firm; recommend test", "next_due": day(7), "next_notes": "Chase soil report"}, T["pm"]))
chained = [f for f in call("GET", f"/followups?related_id={LID}", token=T["pm"])[1] if f.get("previous_id") == f_pm["id"]]
check("next follow-up created for the same owner", len(chained) == 1 and chained[0]["owner_id"] == uid["pm"] and chained[0]["due"] == day(7))
cleanup["followups"] += [f["id"] for f in chained]
acts = [a["text"] for a in call("GET", f"/leads/{LID}", token=T["sales"])[1]["activities"]]
check("completions logged on the lead", any("Plans emailed" in a for a in acts) and any("Soil looks firm" in a for a in acts), acts)
ok("PM cannot delete a follow-up Sales created", call("DELETE", f"/followups/{f_today['id']}", token=T["pm"]), 403)
ok("cancel", call("POST", f"/followups/{f_today['id']}/cancel", {"reason": "Merged with call"}, T["sales"]))
ok("reopen", call("POST", f"/followups/{f_today['id']}/reopen", {}, T["sales"]))

# 5 -------------------------------------------------------------------------------------------------
step("5. Lead moves through every pipeline stage")
m = call("GET", "/leads/meta", token=T["sales"])[1]
stages = m["pipelines"]["construction"]
for item in m["stage_rules"]["construction"]["Lead"]["checklist"]:
    ok(f"tick {item}", call("POST", f"/leads/{LID}/checklist", {"stage": "Lead", "item": item, "done": True}, T["sales"]))
ok("move to Site visit (Lead checklist done, first call logged)", call("POST", f"/leads/{LID}/stage", {"stage": "Site visit"}, T["sales"]))
# visit, measurements, brief, estimate and proposal are recorded by the owner here (Phase C+ blocks 2-4 test them)
for st in stages[2:]:
    ok(f"move to {st}", call("POST", f"/leads/{LID}/stage", {"stage": st, "override_reason": "e2e: steps covered in later suites"}, T["owner"]))
hist = [h["stage"] for h in call("GET", f"/leads/{LID}", token=T["sales"])[1]["stage_history"]]
check("history covers every stage in order", hist == stages, hist)
tpl = next(t for t in call("GET", "/message_templates", token=T["sales"])[1] if t["name"] == "Budget discussion")
r = ok("render budget template", call("POST", f"/message_templates/{tpl['id']}/render", {"lead_id": LID}, T["sales"]))
check("merge fields filled", name in r["text"] and "65,00,000" in r["text"] and not r["missing"], r)
ok("log template as sent", call("POST", f"/leads/{LID}/activities", {"type": "email", "text": f"EMAIL sent: {r['text']}",
                                                                      "template_id": tpl["id"]}, T["sales"]), 201)

# 6 -------------------------------------------------------------------------------------------------
step("6. Lead is won and becomes a project")
won = ok("win with PM", call("POST", f"/leads/{LID}/win", {"pm_id": uid["pm"], "start": day(0)}, T["sales"]))
PID = won["project_id"]
cleanup["projects"].append(PID)
p = call("GET", f"/projects/{PID}", token=T["pm"])[1]
check("project carries the lead", p["client_name"] == name and p["value"] == 6500000 and p["area"] == 3600
      and p["project_type"] == "New build" and p["site"]["line1"] == "Whitefield, Bengaluru", p)
check("construction template stages created", [s["name"] for s in p["stages"]] ==
      ["Pre-construction", "Foundation", "Structure", "MEP", "Finishing", "Handover"])
roles = {m.get("user_id") or m.get("contact_id"): (m["project_role"], m["access"]) for m in p["team"]}
check("PM edit, Sales view, client on team", roles.get(uid["pm"]) == ("Project Manager", "edit")
      and roles.get(uid["sales"]) == ("Sales", "view") and roles.get(lead["contact_id"]) == ("Client", "view"), roles)
check("lead locked as won", call("POST", f"/leads/{LID}/stage", {"stage": "Lead"}, T["sales"])[0] == 409)
moved = call("GET", f"/followups?related_id={PID}", token=T["pm"])[1]
check("open follow-ups moved to the project", {f["id"] for f in moved} >= {f_today["id"], chained[0]["id"]}, [f["title"] for f in moved])
pf = call("GET", f"/projects/{PID}/followups", token=T["pm"])[1]
check("project timeline shows lead history", any(x["kind"] == "activity" and "Discussed plot" in x["title"] for x in pf))
h = call("GET", f"/contacts/{lead['contact_id']}/history", token=T["sales"])[1]
check("contact history shows the project as Client", any(x["id"] == PID and "Client" in x["roles"] for x in h["projects"]))
ok("Sales cannot edit the project", call("PUT", f"/projects/{PID}", {"name": "x"}, T["sales"]), 403)

# 7 -------------------------------------------------------------------------------------------------
step("7. PM sets up the team, schedule and budgets")
consultant = next(u["contact_id"] for u in call("GET", "/users", token=T["owner"])[1] if u["role"] == "consultant")
ok("add architect (edit)", call("POST", f"/projects/{PID}/team", {"user_id": uid["designer"], "project_role": "Architect", "access": "edit"}, T["pm"]), 201)
ok("add site supervisor (view)", call("POST", f"/projects/{PID}/team", {"user_id": uid["site"], "project_role": "Site Supervisor"}, T["pm"]), 201)
ok("add structural consultant", call("POST", f"/projects/{PID}/team", {"contact_id": consultant, "project_role": "Structural Consultant"}, T["pm"]), 201)
p = ok("add architecture service (design-and-build)", call("PUT", f"/projects/{PID}", {"services": ["construction", "architecture"]}, T["pm"]))
st = {s["name"]: s for s in p["stages"]}
check("architecture stages appended", "Schematic design" in st)
pre, found = st["Pre-construction"], st["Foundation"]
ok("budget on Foundation", call("PUT", f"/projects/{PID}/stages/{found['id']}", {"budget": 750000}, T["pm"]))
p = ok("design task (architect)", call("POST", f"/projects/{PID}/stages/{st['Construction documents']['id']}/tasks", {
    "title": "Structural drawings", "start": day(0), "end": day(10), "assignee_id": uid["designer"]}, T["pm"]), 201)
dwg = next(t for s in p["stages"] for t in s["tasks"] if t["title"] == "Structural drawings")
p = ok("site task depends on drawings", call("POST", f"/projects/{PID}/stages/{pre['id']}/tasks", {
    "title": "Site clearing and marking", "start": day(11), "end": day(13), "assignee_id": uid["site"], "depends_on": [dwg["id"]]}, T["pm"]), 201)
clr = next(t for s in p["stages"] for t in s["tasks"] if t["title"] == "Site clearing and marking")
p = ok("foundation task depends on clearing", call("POST", f"/projects/{PID}/stages/{found['id']}/tasks", {
    "title": "Excavation and footing", "start": day(14), "end": day(25), "assignee_id": uid["site"], "depends_on": [clr["id"]]}, T["pm"]), 201)
exc = next(t for s in p["stages"] for t in s["tasks"] if t["title"] == "Excavation and footing")
check("no date conflicts in a well-planned chain", not any(t["conflict"] for s in p["stages"] for t in s["tasks"]))
ok("extra milestone", call("POST", f"/projects/{PID}/stages/{found['id']}/milestones", {"name": "Plinth beam cast", "due": day(25)}, T["pm"]), 201)

# 8 -------------------------------------------------------------------------------------------------
step("8. Delivery: each role does their part")
ok("site cannot start clearing before drawings are done", call("PUT", f"/projects/{PID}/tasks/{clr['id']}", {"status": "in_progress"}, T["site"]), 409)
ok("architect starts drawings", call("PUT", f"/projects/{PID}/tasks/{dwg['id']}", {"status": "in_progress"}, T["designer"]))
ok("architect cannot touch the site task", call("PUT", f"/projects/{PID}/tasks/{clr['id']}", {"status": "done"}, T["designer"]), 403)
ok("architect finishes drawings", call("PUT", f"/projects/{PID}/tasks/{dwg['id']}", {"status": "done"}, T["designer"]))
ok("site starts clearing", call("PUT", f"/projects/{PID}/tasks/{clr['id']}", {"status": "in_progress"}, T["site"]))
ok("site cannot rename its task", call("PUT", f"/projects/{PID}/tasks/{clr['id']}", {"title": "x"}, T["site"]), 403)
ok("site finishes clearing", call("PUT", f"/projects/{PID}/tasks/{clr['id']}", {"status": "done"}, T["site"]))
iss = ok("site raises an issue", call("POST", f"/projects/{PID}/issues", {"title": "Rock found at 4 ft", "severity": "high",
                                                                        "owner_id": uid["pm"]}, T["site"]), 201)
fu_site = ok("PM sets a follow-up for site", call("POST", "/followups", {"title": f"Send rock-breaking quote {RUN}", "due": day(1),
                                                                         "owner_id": uid["site"], "related": {"type": "project", "id": PID}}, T["pm"]), 201)
cleanup["followups"].append(fu_site["id"])
check("site sees it on Today (upcoming)", fu_site["id"] in [x["id"] for x in call("GET", "/followups/today", token=T["site"])[1]["upcoming"]])
ok("site completes it", call("POST", f"/followups/{fu_site['id']}/done", {"outcome": "Quote from vendor received"}, T["site"]))
ok("site starts excavation", call("PUT", f"/projects/{PID}/tasks/{exc['id']}", {"status": "in_progress"}, T["site"]))
ok("PM closes the issue", call("PUT", f"/projects/{PID}/issues/{iss['id']}", {"status": "closed"}, T["pm"]))
ok("site completes excavation", call("PUT", f"/projects/{PID}/tasks/{exc['id']}", {"status": "done"}, T["site"]))
p = call("GET", f"/projects/{PID}", token=T["pm"])[1]
sp = {s["name"]: (s["progress"], s["status"]) for s in p["stages"]}
check("stages with all tasks done are 100% and done", sp["Pre-construction"] == (100, "done") and sp["Foundation"] == (100, "done")
      and sp["Construction documents"] == (100, "done"), sp)
check("project progress rises", 0 < p["progress"] < 100, p["progress"])
ms = [m for s in p["stages"] if s["name"] == "Foundation" for m in s["milestones"]]
for m in ms:
    ok(f"achieve milestone {m['name']}", call("PUT", f"/projects/{PID}/milestones/{m['id']}", {"status": "achieved"}, T["pm"]))
dash = call("GET", f"/projects/{PID}/dashboard", token=T["pm"])[1]
check("dashboard: tasks, issues, budget", dash["tasks"]["done"] == 3 and dash["open_issues"] == 0
      and dash["budget"]["budget"] == 750000, dash["tasks"])
check("dashboard: next milestones exclude achieved ones", not any(m["id"] in [x["id"] for x in ms] for m in dash["next_milestones"]))
site_view = call("GET", f"/projects/{PID}", token=T["site"])[1]
check("site never sees value or budgets", "value" not in site_view and all("budget" not in s for s in site_view["stages"]))

# 9 -------------------------------------------------------------------------------------------------
step("9. Client gets portal access and follows progress")
pu = ok("owner grants portal access", call("POST", "/users", {"name": name, "email": f"anita{RUN}@portal.test", "role": "client",
                                                               "password": "Client@1", "contact_id": lead["contact_id"]}, T["owner"]), 201)
cleanup["users"].append(pu["id"])
ct = login(f"anita{RUN}@portal.test", "Client@1")
pp = call("GET", "/portal/projects", token=ct)[1]
check("client sees exactly their project", [x["id"] for x in pp] == [PID], pp)
pv = call("GET", f"/portal/projects/{PID}", token=ct)[1]
check("portal shows progress and stages without money", pv["progress"] == p["progress"] and "value" not in pv
      and all("budget" not in s and "tasks" not in s for s in pv["stages"]))
check("portal shows achieved milestones", any(m["status"] == "achieved" for s in pv["stages"] for m in s["milestones"]))

# 10 ------------------------------------------------------------------------------------------------
step("10. Project closes out; reports reflect the journey")
ok("put on hold", call("PUT", f"/projects/{PID}", {"status": "on_hold"}, T["pm"]))
ok("mark completed", call("PUT", f"/projects/{PID}", {"status": "completed"}, T["pm"]))
hist = call("GET", f"/projects/{PID}/history", token=T["pm"])[1]
check("history recorded every change", len(hist) >= 15 and hist[-1]["action"] == "create", len(hist))
rep = call("GET", "/reports/sales", token=T["sales"])[1]
web = next(r for r in rep["by_source"] if r["key"] == "Website form")
check("sales report counts the won web lead", web["won"] >= 1 and web["won_value"] >= 6500000)
fr = call("GET", "/reports/followups", token=T["pm"])[1]
check("follow-up report lists users", any(r["owner"].startswith("Site") and r["done"] >= 1 for r in fr), fr)

step(None)

# ---------------- cleanup ----------------
for f in cleanup["followups"]:
    call("DELETE", f"/followups/{f}", token=T["owner"])
for f in call("GET", "/followups", token=T["owner"])[1]:
    if RUN in f["title"]:
        call("DELETE", f"/followups/{f['id']}", token=T["owner"])
for u in cleanup["users"]:
    call("PUT", f"/users/{u}", {"active": False}, T["owner"])
for p_ in cleanup["projects"]:
    call("DELETE", f"/projects/{p_}", token=T["owner"])
for l_ in cleanup["leads"]:
    call("DELETE", f"/leads/{l_}", token=T["owner"])
drop_test_logins([u["email"] for u in call("GET", "/users", token=T["owner"])[1] if u["id"] in cleanup["users"]])
for c_ in cleanup["contacts"]:
    call("DELETE", f"/contacts/{c_}", token=T["owner"])

print()
for s in step_results:
    mark = "PASS" if not s["bad"] else "FAIL"
    print(f"  {mark}  {s['name']}  ({s['ok']} checks{', ' + str(s['bad']) + ' failed' if s['bad'] else ''})")
print(f"\npassed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
