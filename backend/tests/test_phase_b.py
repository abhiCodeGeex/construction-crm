"""Phase B — contacts, projects & per-project access. One block per requirement row in PLAN.md (B1).

    docker compose exec backend python tests/test_phase_b.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = os.getenv("API", "http://localhost:5000/api")
PW = "Demo@123"
RUN = str(int(time.time() * 1000))[-8:]
failures, passed = [], 0


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
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


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm", "designer", "estimator", "site", "procurement",
                                             "accounts", "client", "consultant", "vendor", "subcontractor")}
nest = login("owner@nest.test")
staff = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1]}
contact_of = {u["role"]: u["contact_id"] for u in call("GET", "/users", token=T["owner"])[1] if u["kind"] == "external"}

# ---------------- §3.1 contact types ----------------
c1 = expect("§3.1 create company contact", call("POST", "/contacts", {
    "name": f"Acme Builders {RUN}", "kind": "company", "types": ["contractor", "developer"]}, T["pm"]), 201)
expect("§3.1 unknown type rejected", call("POST", "/contacts", {"name": "X", "types": ["wizard"]}, T["pm"]), 400)
expect("§3.1 name required", call("POST", "/contacts", {"types": ["client"]}, T["pm"]), 400)
for ty in ("client", "developer", "architect", "contractor", "subcontractor", "supplier", "consultant", "authority"):
    expect(f"§3.1 type {ty} accepted", call("POST", "/contacts", {"name": f"T {ty} {RUN}", "types": [ty]}, T["owner"]), 201)
person = expect("§3.1 person linked to company", call("POST", "/contacts", {
    "name": f"Ravi {RUN}", "kind": "person", "org_id": c1["id"], "types": ["contractor"]}, T["pm"]), 201)
check("§3.1 person shows org name", person.get("org_name") == c1["name"], person)
expect("§3.1 person cannot belong to a person", call("POST", "/contacts", {
    "name": "Y", "kind": "person", "org_id": person["id"]}, T["pm"]), 400)
rows = call("GET", "/contacts?type=developer", token=T["pm"])[1]
check("§3.1 filter by type", any(r["id"] == c1["id"] for r in rows) and all("developer" in r["types"] for r in rows))
expect("§3.1 bad email", call("POST", "/contacts", {"name": "Z", "email": "nope"}, T["pm"]), 400)

# ---------------- §3.3 trade, rating, notes ----------------
expect("§3.3 rating 6 rejected", call("PUT", f"/contacts/{c1['id']}", {"rating": 6}, T["pm"]), 400)
upd = expect("§3.3 trade/rating/notes saved", call("PUT", f"/contacts/{c1['id']}", {
    "trade_category": "Civil works", "rating": 4, "notes": "Reliable on time"}, T["pm"]), 200)
check("§3.3 values stored", upd["rating"] == 4 and upd["trade_category"] == "Civil works")

# ---------------- §3.5 tax ids, bank, trade account, discount ----------------
expect("§3.5 bad GSTIN", call("PUT", f"/contacts/{c1['id']}", {"gstin": "123"}, T["procurement"]), 400)
expect("§3.5 bad PAN", call("PUT", f"/contacts/{c1['id']}", {"pan": "ABC"}, T["procurement"]), 400)
expect("§3.5 bad IFSC", call("PUT", f"/contacts/{c1['id']}", {"bank": {"ifsc": "XX"}}, T["procurement"]), 400)
expect("§3.5 discount > 100", call("PUT", f"/contacts/{c1['id']}", {"discount_pct": 120}, T["procurement"]), 400)
expect("§3.5 valid finance fields", call("PUT", f"/contacts/{c1['id']}", {
    "gstin": "29abcde1234f1z5", "pan": "ABCDE1234F", "trade_account_no": "TA-1", "discount_pct": 7.5,
    "bank": {"account_name": "Acme", "account_no": "123456789012", "ifsc": "HDFC0001234", "bank_name": "HDFC"}},
    T["procurement"]), 200)
full = call("GET", f"/contacts/{c1['id']}", token=T["accounts"])[1]
check("§3.5 accounts sees full bank", full["bank"]["account_no"] == "123456789012" and full["gstin"] == "29ABCDE1234F1Z5", full.get("bank"))
masked = call("GET", f"/contacts/{c1['id']}", token=T["sales"])[1]
check("§3.5 sales sees masked bank", masked["bank"]["account_no"] == "••••9012" and masked["bank"]["ifsc"] is None, masked.get("bank"))
call("PUT", f"/contacts/{c1['id']}", {"bank": {"account_no": "999999999999", "ifsc": "HDFC0001234"}}, T["sales"])
check("§3.5 sales cannot change bank", call("GET", f"/contacts/{c1['id']}", token=T["accounts"])[1]["bank"]["account_no"] == "123456789012")

# ---------------- §3.4 compliance & expiry alerts ----------------
expect("§3.4 expiry before issue rejected", call("PUT", f"/contacts/{c1['id']}", {"compliance": [
    {"type": "insurance", "name": "CAR policy", "issue_date": day(0), "expiry": day(-1)}]}, T["pm"]), 400)
expect("§3.4 bad compliance type", call("PUT", f"/contacts/{c1['id']}", {"compliance": [
    {"type": "visa", "name": "x"}]}, T["pm"]), 400)
comp = expect("§3.4 compliance saved", call("PUT", f"/contacts/{c1['id']}", {"compliance": [
    {"type": "insurance", "name": "CAR policy", "expiry": day(-2)},
    {"type": "licence", "name": "Contractor licence", "expiry": day(20)},
    {"type": "certificate", "name": "ISO 9001", "expiry": day(200)}]}, T["pm"]), 200)
st = {x["name"]: x["status"] for x in comp["compliance"]}
check("§3.4 statuses", st == {"CAR policy": "expired", "Contractor licence": "expiring", "ISO 9001": "valid"}, st)
check("§3.4 contact flagged", comp["compliance_alert"] == "expired")
alerts = call("GET", "/compliance/alerts", token=T["pm"])[1]
mine = {a["document"] for a in alerts if a["contact_id"] == c1["id"]}
check("§3.4 alert list has expired + expiring only", mine == {"CAR policy", "Contractor licence"}, mine)
check("§3.4 home shows alert count", call("GET", "/home", token=T["pm"])[1].get("compliance_alerts", 0) >= 2)

# ---------------- §3.6 referrals ----------------
ref = expect("§3.6 contact referred by", call("POST", "/contacts", {
    "name": f"Referred {RUN}", "types": ["client"], "referred_by": c1["id"]}, T["sales"]), 201)
expect("§3.6 self-referral blocked", call("PUT", f"/contacts/{c1['id']}", {"referred_by": c1["id"]}, T["pm"]), 400)

# ---------------- §4.4 / §1 module gating ----------------
expect("§4.4 project needs a service", call("POST", "/projects", {"name": "No svc", "services": []}, T["pm"]), 400)
expect("§4.4 unknown service", call("POST", "/projects", {"name": "x", "services": ["plumbing"]}, T["pm"]), 400)
expect("§1 disabled module refused (Nest = interior only)",
       call("POST", "/projects", {"name": "x", "services": ["construction"]}, nest), 400)

# ---------------- §4.1 / §4.2 create from templates ----------------
P = expect("§4.2 design-and-build project", call("POST", "/projects", {
    "name": f"Test Villa {RUN}", "services": ["architecture", "construction", "interior"], "client_id": ref["id"],
    "start": day(0), "area": 2500, "area_unit": "sqft", "value": 9000000, "branch": "Head office",
    "referred_by": c1["id"], "site": {"line1": "1 MG Road", "city": "Bengaluru", "lat": 12.97, "lng": 77.59}}, T["pm"]), 201)
pid = P["id"]
names = {s["service"]: [x["name"] for x in P["stages"] if x["service"] == s["service"]] for s in P["stages"]}
check("§4.2 architecture template", names["architecture"] == ["Concept", "Schematic design", "Design development",
                                                             "Construction documents", "Approvals", "Construction support"], names)
check("§4.2 construction template", names["construction"] == ["Pre-construction", "Foundation", "Structure", "MEP",
                                                             "Finishing", "Handover"])
check("§4.2 interior template", names["interior"] == ["Brief", "Concept", "Design", "Selections", "Procurement",
                                                     "Installation", "Handover"])
check("§4.1 milestone per stage", all(len(s["milestones"]) == 1 for s in P["stages"]))
check("§4.1 project code", P["code"].startswith("PRJ"))
check("§4.5 creator is PM with edit", any(m.get("user_id") == staff["pm"] and m["access"] == "edit" for m in P["team"]))
check("§4.5 client auto on team", any(m.get("contact_id") == ref["id"] and m["project_role"] == "Client" for m in P["team"]))
check("§4.8 site + area stored", P["site"]["city"] == "Bengaluru" and P["area_unit"] == "sqft")
expect("§4.8 bad map pin", call("PUT", f"/projects/{pid}", {"site": {"lat": 120, "lng": 10}}, T["pm"]), 400)
expect("§4.8 bad area unit", call("PUT", f"/projects/{pid}", {"area_unit": "acres"}, T["pm"]), 400)
expect("§4.8 negative value", call("PUT", f"/projects/{pid}", {"value": -5}, T["pm"]), 400)
expect("§1 unknown branch", call("PUT", f"/projects/{pid}", {"branch": "Mars"}, T["pm"]), 400)
expect("§4.1 target end before start", call("PUT", f"/projects/{pid}", {"target_end": day(-10)}, T["pm"]), 400)

# ---------------- §3.2 roles per project / §4.5 team ----------------
expect("§4.5 add staff", call("POST", f"/projects/{pid}/team", {"user_id": staff["designer"], "project_role": "Architect",
                                                              "access": "edit"}, T["pm"]), 201)
expect("§4.5 add site (view)", call("POST", f"/projects/{pid}/team", {"user_id": staff["site"],
                                                                    "project_role": "Site Supervisor"}, T["pm"]), 201)
expect("§4.5 add external", call("POST", f"/projects/{pid}/team", {"contact_id": c1["id"],
                                                                 "project_role": "Main Contractor"}, T["pm"]), 201)
expect("§4.5 duplicate staff", call("POST", f"/projects/{pid}/team", {"user_id": staff["site"],
                                                                    "project_role": "Other"}, T["pm"]), 409)
expect("§4.5 bad project role", call("POST", f"/projects/{pid}/team", {"user_id": staff["sales"],
                                                                     "project_role": "Wizard"}, T["pm"]), 400)
expect("§4.5 need user or contact", call("POST", f"/projects/{pid}/team", {"project_role": "Other"}, T["pm"]), 400)
P2 = expect("§3.2 same firm as client elsewhere", call("POST", "/projects", {
    "name": f"Acme HQ {RUN}", "services": ["construction"], "client_id": c1["id"]}, T["pm"]), 201)
hist = call("GET", f"/contacts/{c1['id']}/history", token=T["pm"])[1]
roles = {h["id"]: h["roles"] for h in hist["projects"]}
check("§3.2 partner on one, client on another", roles.get(pid) == ["Main Contractor"] and roles.get(P2["id"]) == ["Client"], roles)
check("§3.1 company lists its people", any(x["id"] == person["id"] for x in hist["people"]))
check("§3.6 referrals listed", any(x["id"] == ref["id"] for x in hist["referred_contacts"])
      and any(x["id"] == pid for x in hist["referred_projects"]) and hist["referred_value"] >= 9000000, hist)
team = call("GET", f"/projects/{pid}", token=T["pm"])[1]["team"]
ext = next(m for m in team if m.get("contact_id") == c1["id"])
expect("§4.5 external cannot get edit", call("PUT", f"/projects/{pid}/team/{ext['id']}", {"access": "edit"}, T["pm"]), 400)
expect("delete contact on a project blocked", call("DELETE", f"/contacts/{c1['id']}", token=T["pm"]), 409)

# ---------------- §1 per-project visibility ----------------
check("§1 owner sees all projects", any(p["id"] == pid for p in call("GET", "/projects", token=T["owner"])[1]))
check("§1 member sees project", any(p["id"] == pid for p in call("GET", "/projects", token=T["designer"])[1]))
check("§1 non-member does not see it", not any(p["id"] == pid for p in call("GET", "/projects", token=T["estimator"])[1]))
expect("§1 non-member gets 404", call("GET", f"/projects/{pid}", token=T["estimator"]), 404)
expect("§1 other tenant gets 404", call("GET", f"/projects/{pid}", token=nest), 404)
expect("§1 no projects role", call("GET", "/projects", token=T["sales"]), 200)
expect("§1 sales (projects:r) cannot create", call("POST", "/projects", {"name": "x", "services": ["construction"]}, T["sales"]), 403)

# ---------------- stages / tasks / dependencies (§4.1, §4.6) ----------------
P = call("GET", f"/projects/{pid}", token=T["pm"])[1]
concept = next(s for s in P["stages"] if s["name"] == "Concept" and s["service"] == "architecture")
found = next(s for s in P["stages"] if s["name"] == "Foundation")
expect("§4.1 add stage", call("POST", f"/projects/{pid}/stages", {"name": "Landscape", "service": "construction",
                                                                  "start": day(100), "end": day(110)}, T["pm"]), 201)
expect("§4.1 stage service must be project's", call("POST", f"/projects/{pid}/stages", {
    "name": "x", "service": "plumbing", "start": day(1), "end": day(2)}, T["pm"]), 400)
expect("§4.1 stage end before start", call("POST", f"/projects/{pid}/stages", {
    "name": "x", "service": "construction", "start": day(5), "end": day(1)}, T["pm"]), 400)
expect("§4.1 task needs assignee on team", call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
    "title": "x", "start": day(1), "end": day(2), "assignee_id": staff["estimator"]}, T["pm"]), 400)
r = expect("§4.1 add task A", call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
    "title": "Excavate", "start": found["start"], "end": found["start"], "assignee_id": staff["site"]}, T["pm"]), 201)
A = next(tk for s in r["stages"] if s["id"] == found["id"] for tk in s["tasks"] if tk["title"] == "Excavate")
r = expect("§4.6 add task B depends on A", call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
    "title": "Footings", "start": found["start"], "end": found["end"], "depends_on": [A["id"]],
    "assignee_id": staff["site"]}, T["pm"]), 201)
B = next(tk for s in r["stages"] if s["id"] == found["id"] for tk in s["tasks"] if tk["title"] == "Footings")
check("§4.6 date conflict flagged (B starts before A ends)", B["conflict"] is True, B)
expect("§4.6 dependency loop rejected", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"depends_on": [B["id"]]}, T["pm"]), 400)
expect("§4.6 self dependency rejected", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"depends_on": [A["id"]]}, T["pm"]), 400)
expect("§4.6 unknown dependency", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"depends_on": ["nope"]}, T["pm"]), 400)
expect("§4.6 B cannot start before A done", call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "in_progress"}, T["pm"]), 409)
r = expect("§4.6 fix dates clears conflict", call("PUT", f"/projects/{pid}/tasks/{B['id']}", {
    "start": (date.fromisoformat(found["start"]) + timedelta(days=1)).isoformat()}, T["pm"]), 200)
check("§4.6 conflict cleared", not next(tk for s in r["stages"] for tk in s["tasks"] if tk["id"] == B["id"])["conflict"])

# assignee rules (§1 per-project): site is a view member but may update own task status only
expect("§1 assignee updates own task", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"status": "done"}, T["site"]), 200)
expect("§1 assignee cannot rename", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"title": "hack"}, T["site"]), 403)
expect("§1 view member cannot add task", call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
    "title": "x", "start": day(1), "end": day(2)}, T["site"]), 403)
r = call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "done"}, T["pm"])[1]
fs = next(s for s in r["stages"] if s["id"] == found["id"])
check("§4.7 stage progress from tasks = 100", fs["progress"] == 100 and fs["status"] == "done", fs)
expect("§4.7 manual progress blocked when stage has tasks", call("PUT", f"/projects/{pid}/stages/{found['id']}",
                                                                  {"progress": 10}, T["pm"]), 400)
call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "todo"}, T["pm"])
fs = next(s for s in call("GET", f"/projects/{pid}", token=T["pm"])[1]["stages"] if s["id"] == found["id"])
check("§4.7 half done = 50%", fs["progress"] == 50 and fs["status"] == "in_progress", fs)
r = call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"end": day(300)}, T["pm"])[1]
check("§B2 stage window grows to contain tasks", next(s for s in r["stages"] if s["id"] == found["id"])["end"] == day(300))
land = next(s for s in r["stages"] if s["name"] == "Landscape")
r = expect("§4.6 cross-stage dependency", call("POST", f"/projects/{pid}/stages/{land['id']}/tasks", {
    "title": "Planting", "start": day(301), "end": day(305), "depends_on": [B["id"]]}, T["pm"]), 201)
C = next(tk for s in r["stages"] if s["id"] == land["id"] for tk in s["tasks"])
expect("§4.1 cannot delete stage others depend on", call("DELETE", f"/projects/{pid}/stages/{found['id']}", token=T["pm"]), 409)
expect("§4.1 delete task", call("DELETE", f"/projects/{pid}/tasks/{C['id']}", token=T["pm"]), 200)
r = expect("§4.1 delete stage once free", call("DELETE", f"/projects/{pid}/stages/{land['id']}", token=T["pm"]), 200)
check("§4.1 stage removed", not any(s["id"] == land["id"] for s in r["stages"]))

# designer may edit design stages only
expect("§1 designer edits design-stage task", call("POST", f"/projects/{pid}/stages/{concept['id']}/tasks", {
    "title": "Sketches", "start": concept["start"], "end": concept["end"]}, T["designer"]), 201)
struct = next(s for s in call("GET", f"/projects/{pid}", token=T["pm"])[1]["stages"] if s["name"] == "Structure")
expect("§1 designer cannot edit construction stage", call("POST", f"/projects/{pid}/stages/{struct['id']}/tasks", {
    "title": "x", "start": day(1), "end": day(2)}, T["designer"]), 403)
expect("§1 designer cannot set budget", call("PUT", f"/projects/{pid}/stages/{concept['id']}", {"budget": 10}, T["designer"]), 403)
expect("§1 designer cannot edit project details", call("PUT", f"/projects/{pid}", {"name": "x"}, T["designer"]), 403)

# milestones
ms_r = expect("§4.1 add milestone", call("POST", f"/projects/{pid}/stages/{struct['id']}/milestones", {
    "name": "Slab cast", "due": day(-1)}, T["pm"]), 201)
ms = next(m for s in ms_r["stages"] for m in s["milestones"] if m["name"] == "Slab cast")
expect("§4.1 milestone date required", call("POST", f"/projects/{pid}/stages/{struct['id']}/milestones", {"name": "x"}, T["pm"]), 400)
dash = call("GET", f"/projects/{pid}/dashboard", token=T["pm"])[1]
nxt = next((m for m in dash["next_milestones"] if m["id"] == ms["id"]), None)
check("§4.7 next milestones with late flag", nxt is not None and nxt["late"] is True, dash["next_milestones"])
done_ms = call("PUT", f"/projects/{pid}/milestones/{ms['id']}", {"status": "achieved"}, T["pm"])[1]
check("§4.1 milestone achieved", next(m for s in done_ms["stages"] for m in s["milestones"] if m["id"] == ms["id"])["status"] == "achieved")

# budget vs actual, cost hiding
expect("§4.7 set stage budget", call("PUT", f"/projects/{pid}/stages/{struct['id']}", {"budget": 750000}, T["pm"]), 200)
dash = call("GET", f"/projects/{pid}/dashboard", token=T["pm"])[1]
check("§4.7 budget vs actual", dash["budget"]["budget"] == 750000 and dash["budget"]["actual"] == 0, dash["budget"])
check("§4.7 progress number", isinstance(dash["progress"], int) and 0 <= dash["progress"] <= 100)
site_view = call("GET", f"/projects/{pid}", token=T["site"])[1]
check("§1 cost hidden from site (project)", "budget_total" not in site_view and "value" not in site_view
      and all("budget" not in s for s in site_view["stages"]), [k for k in site_view if "budget" in k or k == "value"])
check("§1 cost hidden from site (dashboard)", "budget" not in call("GET", f"/projects/{pid}/dashboard", token=T["site"])[1])

# issues
iss = expect("§4.7 member raises issue", call("POST", f"/projects/{pid}/issues", {
    "title": "Water seepage", "severity": "high"}, T["site"]), 201)
expect("§4.7 bad severity", call("POST", f"/projects/{pid}/issues", {"title": "x", "severity": "huge"}, T["pm"]), 400)
check("§4.7 open issue counted", call("GET", f"/projects/{pid}/dashboard", token=T["pm"])[1]["open_issues"] >= 1)
expect("§4.7 editor closes issue", call("PUT", f"/projects/{pid}/issues/{iss['id']}", {"status": "closed"}, T["pm"]), 200)
expect("§4.7 non-member cannot raise", call("POST", f"/projects/{pid}/issues", {"title": "x"}, T["estimator"]), 404)

# ---------------- §4.4 add a service later ----------------
P3 = call("POST", "/projects", {"name": f"Shell {RUN}", "services": ["construction"]}, T["pm"])[1]
r = expect("§4.4 add interior later", call("PUT", f"/projects/{P3['id']}", {"services": ["construction", "interior"]}, T["pm"]), 200)
check("§4.4 interior stages appended", sum(1 for s in r["stages"] if s["service"] == "interior") == 7)
expect("§4.4 cannot remove a service", call("PUT", f"/projects/{P3['id']}", {"services": ["interior"]}, T["pm"]), 409)

# ---------------- §4.3 templates (+RIBA / AIA) ----------------
expect("§4.3 pm cannot edit templates", call("POST", "/stage_templates", {"preset": "riba"}, T["pm"]), 403)
tpls = call("GET", "/stage_templates", token=T["pm"])[1]
check("§4.3 presets offered", {p["key"] for p in tpls["presets"]} == {"riba", "aia"})
riba_existing = [x for x in tpls["templates"] if x["name"] == "RIBA Plan of Work 2020"]
riba = riba_existing[0] if riba_existing else expect("§4.3 add RIBA preset", call("POST", "/stage_templates", {"preset": "riba"}, T["owner"]), 201)
check("§4.3 RIBA has 8 stages", len(riba["stages"]) == 8, riba)
expect("§4.3 duplicate template", call("POST", "/stage_templates", {"preset": "riba"}, T["owner"]), 409)
expect("§4.3 duration validated", call("PUT", f"/stage_templates/{riba['id']}", {"stages": [{"name": "A", "duration_days": 0}]}, T["owner"]), 400)
expect("§4.3 make RIBA default", call("PUT", f"/stage_templates/{riba['id']}", {"is_default": True}, T["owner"]), 200)
P4 = call("POST", "/projects", {"name": f"RIBA job {RUN}", "services": ["architecture"]}, T["owner"])[1]
check("§4.3 new project uses edited default", [s["name"] for s in P4["stages"]][0] == "0 Strategic Definition",
      [s["name"] for s in P4["stages"]][:2])
default_arch = next(x for x in call("GET", "/stage_templates", token=T["owner"])[1]["templates"]
                    if x["service"] == "architecture" and x["name"] == "Default architecture")
expect("§4.3 cannot delete default", call("DELETE", f"/stage_templates/{riba['id']}", token=T["owner"]), 409)
call("PUT", f"/stage_templates/{default_arch['id']}", {"is_default": True}, T["owner"])  # restore
expect("§4.3 delete non-default", call("DELETE", f"/stage_templates/{riba['id']}", token=T["owner"]), 200)

# ---------------- §1 role permission editor ----------------
expect("§1 pm cannot edit roles", call("PUT", "/roles/sales", {"perms": {}}, T["pm"]), 403)
expect("§1 owner role locked", call("PUT", "/roles/owner", {"perms": {"users": ""}}, T["owner"]), 409)
expect("§1 bad level", call("PUT", "/roles/sales", {"perms": {"leads": "x"}}, T["owner"]), 400)
expect("§1 grant estimator projects rw", call("PUT", "/roles/estimator", {"perms": {"projects": "rw"}}, T["owner"]), 200)
expect("§1 override applies immediately", call("POST", "/projects", {"name": f"Est {RUN}", "services": ["construction"]}, T["estimator"]), 201)
me = call("GET", "/auth/me", token=T["estimator"])[1]
check("§1 /auth/me reflects override", me["permissions"].get("projects") == "rw")
roles_view = call("GET", "/roles", token=T["owner"])[1]
est = next(r for r in roles_view["roles"] if r["role"] == "estimator")
check("§1 only differences stored", est["overrides"] == {"projects": "rw"}, est["overrides"])
expect("§1 reset to default", call("PUT", "/roles/estimator", {"perms": {}}, T["owner"]), 200)
expect("§1 reset applies", call("POST", "/projects", {"name": "x", "services": ["construction"]}, T["estimator"]), 403)

# ---------------- §1 company setup: branches, currency, tax, numbering ----------------
expect("§1 numbering needs {n}", call("PUT", "/company/setup", {"numbering": {"PRJ": "JOB"}}, T["owner"]), 400)
expect("§1 numbering bad key", call("PUT", "/company/setup", {"numbering": {"PRJ": "J-{x}-{n}"}}, T["owner"]), 400)
expect("§1 bad currency", call("PUT", "/company/setup", {"currency": "XYZ"}, T["owner"]), 400)
expect("§1 bad tax", call("PUT", "/company/setup", {"tax_rate": 150}, T["owner"]), 400)
expect("§1 branch in use cannot be removed", call("PUT", "/company/setup", {"branches": [{"name": "Pune"}]}, T["owner"]), 409)
expect("§1 add branch", call("PUT", "/company/setup", {"branches": [{"name": "Head office", "city": "Bengaluru"},
                                                                    {"name": "Pune", "city": "Pune"}]}, T["owner"]), 200)
expect("§1 numbering format", call("PUT", "/company/setup", {"numbering": {"PRJ": "SKY-{year}-{n:03d}"}}, T["owner"]), 200)
P5 = call("POST", "/projects", {"name": f"Numbered {RUN}", "services": ["construction"], "branch": "Pune"}, T["owner"])[1]
check("§1 numbering applied", P5["code"].startswith(f"SKY-{date.today().year}-"), P5["code"])
call("PUT", "/company/setup", {"numbering": {"PRJ": "PRJ-{n:04d}"}}, T["owner"])

# ---------------- §1 plan limit counts planning + active ----------------
nest_projects = []
for i in range(6):
    s, d = call("POST", "/projects", {"name": f"Nest {RUN} {i}", "services": ["interior"]}, nest)
    if s != 201:
        break
    nest_projects.append(d["id"])
check("§1 Basic plan: 5 active projects max", s == 402, (s, len(nest_projects)))
if nest_projects:
    call("PUT", f"/projects/{nest_projects[0]}", {"status": "completed"}, nest)
    expect("§1 completed frees a slot", call("POST", "/projects", {"name": f"Nest {RUN} x", "services": ["interior"]}, nest), 201)
    expect("§1 reopening over limit blocked", call("PUT", f"/projects/{nest_projects[0]}", {"status": "active"}, nest), 402)

# ---------------- §13 portal ----------------
client_contact = contact_of["client"]
check("§13 client sees seeded project", any(p["name"] == "Mehta Residence" for p in call("GET", "/portal/projects", token=T["client"])[1]))
check("§13 client does not see other projects", not any(p["id"] == pid for p in call("GET", "/portal/projects", token=T["client"])[1]))
mehta = next(p for p in call("GET", "/portal/projects", token=T["client"])[1] if p["name"] == "Mehta Residence")
pv = call("GET", f"/portal/projects/{mehta['id']}", token=T["client"])[1]
check("§13 portal view has no money", "value" not in pv and all("budget" not in s for s in pv["stages"]), list(pv))
check("§13 portal view has no tasks / internal ids", all("tasks" not in s for s in pv["stages"]))
expect("§13 portal user blocked from staff API", call("GET", f"/projects/{mehta['id']}", token=T["client"]), 403)
expect("§13 client cannot open someone else's project", call("GET", f"/portal/projects/{pid}", token=T["client"]), 404)
check("§13 consultant sees both roles", {p["name"] for p in call("GET", "/portal/projects", token=T["consultant"])[1]}
      >= {"Mehta Residence", "Orchid Office Fit-out"})
check("§13 subcontractor not on any project", call("GET", "/portal/projects", token=T["subcontractor"])[1] == [])
expect("§13 staff blocked from portal API", call("GET", "/portal/projects", token=T["pm"]), 403)

# ---------------- §1 audit ----------------
hist = call("GET", f"/projects/{pid}/history", token=T["pm"])[1]
check("§1 project history recorded", len(hist) >= 5 and hist[-1]["action"] == "create", hist[-1:] if hist else hist)

# ---------------- portal invite from contact ----------------
inv = expect("portal login for existing contact", call("POST", "/users", {
    "name": f"Ref {RUN}", "email": f"ref{RUN}@test.test", "role": "client", "password": "secret1",
    "contact_id": ref["id"]}, T["owner"]), 201)
expect("second portal login for same contact", call("POST", "/users", {
    "name": "x", "email": f"ref2{RUN}@test.test", "role": "client", "password": "secret1",
    "contact_id": ref["id"]}, T["owner"]), 409)
rt = call("POST", "/auth/login", {"email": f"ref{RUN}@test.test", "password": "secret1"})[1]["token"]
check("§13 invited client sees their project", [p["id"] for p in call("GET", "/portal/projects", token=rt)[1]] == [pid])
call("PUT", f"/users/{inv['id']}", {"active": False}, T["owner"])

# ---------------- cleanup (keeps re-runs independent) ----------------
for x in [pid, P2["id"], P3["id"], P4["id"], P5["id"]] + [p["id"] for p in call("GET", "/projects", token=T["owner"])[1]
                                                          if p["name"].startswith("Est ")]:
    call("DELETE", f"/projects/{x}", token=T["owner"])
for x in nest_projects + [p["id"] for p in call("GET", "/projects", token=nest)[1] if RUN in p["name"]]:
    call("DELETE", f"/projects/{x}", token=nest)
check("§1 only owner deletes projects", call("DELETE", f"/projects/{pid}", token=T["pm"])[0] in (403, 404))
for c in call("GET", f"/contacts?q={RUN}", token=T["owner"])[1]:
    if c["kind"] == "person":
        call("DELETE", f"/contacts/{c['id']}", token=T["owner"])
for c in call("GET", f"/contacts?q={RUN}", token=T["owner"])[1]:
    call("DELETE", f"/contacts/{c['id']}", token=T["owner"])  # portal-linked ones stay (409) by design

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
