"""Phase C — leads, pipeline, bids & follow-ups. One block per requirement row in PLAN.md (C1).

    docker compose exec backend python tests/test_phase_c.py
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
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm", "designer", "estimator", "site", "accounts", "client")}
nest = login("owner@nest.test")
staff = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1]}
phone = lambda n: f"9{RUN[-7:]}{n:02d}"
created_leads, created_bids, created_fu, created_contacts, created_projects = [], [], [], [], []


def new_lead(token=T["sales"], **kw):
    body = {"title": f"Lead {RUN} {kw.get('n', 0)}", "service": "construction", "source": "Walk-in",
            "contact_name": f"Enquirer {RUN} {kw.get('n', 0)}", "contact_phone": phone(kw.get("n", 0)), **kw}
    body.pop("n", None)
    res = call("POST", "/leads", body, token)
    if res[0] == 201:
        created_leads.append(res[1]["id"])
        created_contacts.append(res[1]["contact_id"])
    return res


# ---------------- permissions ----------------
expect("§1 sales can create leads", new_lead(n=1), 201)
expect("§1 pm (leads:r) cannot create", new_lead(T["pm"], n=2), 403)
expect("§1 pm can read pipeline", call("GET", "/leads", token=T["pm"]), 200)
expect("§1 designer has no leads access", call("GET", "/leads", token=T["designer"]), 403)
expect("§1 site has no leads access", call("GET", "/leads", token=T["site"]), 403)
expect("§1 portal user blocked", call("GET", "/leads", token=T["client"]), 403)
L1 = call("GET", f"/leads/{created_leads[0]}", token=T["sales"])[1]
expect("§1 other tenant cannot read", call("GET", f"/leads/{L1['id']}", token=nest), 404)
check("§C2 shared pipeline: estimator sees sales' lead", any(x["id"] == L1["id"] for x in call("GET", "/leads", token=T["estimator"])[1]))

# ---------------- §2.0 captured once ----------------
check("§2.0 contact created from enquiry", L1["contact_name"] == f"Enquirer {RUN} 1" and L1["contact_id"])
dup = new_lead(n=1, title="Same person again")
check("§2.0 duplicate phone -> 409", dup[0] == 409 and L1["id"] in dup[1].get("error", ""), dup)
expect("§2.0 duplicate by existing contact -> 409",
       call("POST", "/leads", {"title": "x", "service": "construction", "source": "Walk-in", "contact_id": L1["contact_id"]}, T["sales"]), 409)
forced = expect("§2.0 save anyway", call("POST", "/leads", {"title": f"Second job {RUN}", "service": "interior", "source": "Repeat client",
                                                          "contact_id": L1["contact_id"], "force": True}, T["sales"]), 201)
created_leads.append(forced["id"])
expect("§2.0 needs phone or email", call("POST", "/leads", {"title": "x", "service": "construction", "source": "Walk-in",
                                                            "contact_name": "No Contact"}, T["sales"]), 400)
expect("§2.0 needs a contact", call("POST", "/leads", {"title": "x", "service": "construction", "source": "Walk-in"}, T["sales"]), 400)

# ---------------- §2.1 sources ----------------
expect("§2.1 unknown source", new_lead(n=3, source="Billboard"), 400)
expect("§2.1 referral needs referrer", new_lead(n=4, source="Referral"), 400)
ref = expect("§2.1 referral with referrer", new_lead(n=5, source="Referral", referred_by=L1["contact_id"]), 201)
expect("§2.1 repeat client needs existing contact", new_lead(n=6, source="Repeat client"), 400)
for i, src in enumerate(["Houzz/portals", "Ads"]):
    expect(f"§2.1 source {src}", new_lead(n=10 + i, source=src, source_detail="Houzz Pro" if i == 0 else "Google Ads Nov"), 201)

# ---------------- §2.2 details ----------------
expect("§2.2 bad project type", new_lead(n=20, project_type="Castle"), 400)
expect("§2.2 bad timeline", new_lead(n=21, timeline="Someday"), 400)
expect("§2.2 negative budget", new_lead(n=22, budget=-1), 400)
expect("§2.2 bad area unit", new_lead(n=23, area=10, area_unit="acres"), 400)
L2 = expect("§2.2 full details saved", new_lead(n=24, project_type="Renovation", location="Indiranagar, Bengaluru", area=180,
                                                area_unit="sqm", budget=2500000, timeline="3–6 months"), 201)
check("§2.2 values", (L2["project_type"], L2["area"], L2["area_unit"], L2["budget"], L2["timeline"]) ==
      ("Renovation", 180, "sqm", 2500000, "3–6 months"), L2)
expect("§1 disabled module refused", call("POST", "/leads", {"title": "x", "service": "construction", "source": "Walk-in",
                                                             "contact_name": "Q", "contact_phone": "9000000001"}, nest), 400)

# ---------------- §2.3 pipelines per service ----------------
meta = call("GET", "/leads/meta", token=T["sales"])[1]
check("§2.3 default pipeline from doc", meta["pipelines"]["construction"] == ["Lead", "Site visit", "Proposal/Bid", "Negotiation"])
check("§2.3 starts at first stage", L2["stage"] == "Lead")
expect("§2.3 unknown stage", call("POST", f"/leads/{L2['id']}/stage", {"stage": "Dreaming"}, T["sales"]), 400)
mv = expect("§2.3 move stage", call("POST", f"/leads/{L2['id']}/stage", {"stage": "Site visit"}, T["sales"]), 200)
check("§2.3 stage history recorded", [h["stage"] for h in mv["stage_history"]] == ["Lead", "Site visit"] and mv["stage_history"][-1]["by"])
expect("§2.3 pm cannot move", call("POST", f"/leads/{L2['id']}/stage", {"stage": "Lead"}, T["pm"]), 403)
expect("§2.3 sales cannot edit pipelines", call("PUT", "/leads/pipelines", {"pipelines": {"interior": ["A"]}}, T["sales"]), 403)
expect("§2.3 Won/Lost are not stages", call("PUT", "/leads/pipelines", {"pipelines": {"interior": ["Lead", "Won"]}}, T["owner"]), 400)
expect("§2.3 duplicate stage names", call("PUT", "/leads/pipelines", {"pipelines": {"interior": ["A", "a"]}}, T["owner"]), 400)
expect("§2.3 stage in use cannot be removed", call("PUT", "/leads/pipelines", {"pipelines": {"construction": ["Lead"]}}, T["owner"]), 409)
interior = meta["pipelines"]["interior"]
new_int = interior[:2] + ["Design presentation"] + interior[2:]
expect("§2.3 add a stage to interior only", call("PUT", "/leads/pipelines", {"pipelines": {"interior": new_int}}, T["owner"]), 200)
m2 = call("GET", "/leads/meta", token=T["sales"])[1]
check("§2.3 pipelines are separate", "Design presentation" in m2["pipelines"]["interior"] and "Design presentation" not in m2["pipelines"]["construction"])
expect("§2.3 interior stage invalid on construction lead", call("POST", f"/leads/{L2['id']}/stage", {"stage": "Design presentation"}, T["sales"]), 400)
call("PUT", "/leads/pipelines", {"pipelines": {"interior": interior}}, T["owner"])
board = call("GET", "/leads?service=construction&status=open", token=T["sales"])[1]
check("§2.3 board filter by service", board and all(x["service"] == "construction" and x["status"] == "open" for x in board))

# ---------------- §2.4 activity log ----------------
for typ in ("call", "email", "whatsapp", "meeting", "site_visit", "note"):
    expect(f"§2.4 log {typ}", call("POST", f"/leads/{L2['id']}/activities", {"type": typ, "text": f"{typ} done", "outcome": "ok"}, T["sales"]), 201)
expect("§2.4 bad activity type", call("POST", f"/leads/{L2['id']}/activities", {"type": "fax", "text": "x"}, T["sales"]), 400)
expect("§2.4 empty note", call("POST", f"/leads/{L2['id']}/activities", {"type": "note", "text": " "}, T["sales"]), 400)
acts = call("GET", f"/leads/{L2['id']}", token=T["sales"])[1]
check("§2.4 activities stored with author", sum(1 for a in acts["activities"] if a["type"] != "stage") == 6 and acts["activities"][-1]["by"])
check("§2.5 first response time captured", acts["first_response_at"] is not None)

# ---------------- §16 follow-ups ----------------
expect("§16 title required", call("POST", "/followups", {"due": day(1)}, T["sales"]), 400)
expect("§16 due required", call("POST", "/followups", {"title": "x"}, T["sales"]), 400)
expect("§16 bad priority", call("POST", "/followups", {"title": "x", "due": day(1), "priority": "urgent!"}, T["sales"]), 400)
expect("§16 related must exist", call("POST", "/followups", {"title": "x", "due": day(1), "related": {"type": "lead", "id": "000000000000000000000000"}}, T["sales"]), 400)
F_over = expect("§16 overdue follow-up", call("POST", "/followups", {"title": f"Call back {RUN}", "due": day(-2), "priority": "high",
                                                                    "channel": "call", "related": {"type": "lead", "id": L2["id"]}}, T["sales"]), 201)
F_today = expect("§16 today follow-up", call("POST", "/followups", {"title": f"Send brochure {RUN}", "due": day(0),
                                                                   "related": {"type": "lead", "id": L2["id"]}}, T["sales"]), 201)
F_up = expect("§16 upcoming follow-up", call("POST", "/followups", {"title": f"Site visit {RUN}", "due": day(4), "priority": "low",
                                                                   "related": {"type": "lead", "id": L1["id"]}}, T["sales"]), 201)
created_fu += [F_over["id"], F_today["id"], F_up["id"]]
check("§16 overdue flag", F_over["overdue"] and not F_today["overdue"] and F_today["due_today"])
td = call("GET", "/followups/today", token=T["sales"])[1]
ids = lambda b: {x["id"] for x in td[b]}
check("§16 today buckets", F_over["id"] in ids("overdue") and F_today["id"] in ids("today") and F_up["id"] in ids("upcoming"), td)
nl = call("GET", f"/leads/{L2['id']}", token=T["sales"])[1]
check("§2.4 next follow-up on lead (earliest open)", nl["next_followup"]["id"] == F_over["id"] and nl["next_followup"]["overdue"])
# visibility
check("§C2 pm (manager) sees all", any(f["id"] == F_over["id"] for f in call("GET", "/followups", token=T["pm"])[1]))
check("§C2 accounts does not see others'", not any(f["id"] == F_over["id"] for f in call("GET", "/followups", token=T["accounts"])[1]))
expect("§C2 accounts cannot open others'", call("PUT", f"/followups/{F_over['id']}", {"title": "x"}, T["accounts"]), 404)
expect("§C2 non-manager cannot view other user", call("GET", f"/followups?owner_id={staff['sales']}", token=T["accounts"]), 403)
check("§16 manager views another user's today", F_over["id"] in {x["id"] for x in call("GET", f"/followups/today?owner_id={staff['sales']}", token=T["pm"])[1]["overdue"]})
assigned = expect("§16 sales assigns to pm", call("POST", "/followups", {"title": f"Review drawings {RUN}", "due": day(1), "owner_id": staff["pm"]}, T["sales"]), 201)
created_fu.append(assigned["id"])
check("§16 assignee sees it", any(f["id"] == assigned["id"] for f in call("GET", "/followups", token=T["pm"])[1]))
expect("§16 accounts cannot assign to others", call("POST", "/followups", {"title": "x", "due": day(1), "owner_id": staff["pm"]}, T["accounts"]), 403)
# done
expect("§16 done needs outcome", call("POST", f"/followups/{F_today['id']}/done", {}, T["sales"]), 400)
dn = expect("§16 done with outcome + next", call("POST", f"/followups/{F_today['id']}/done", {"outcome": "Brochure sent", "next_due": day(5)}, T["sales"]), 200)
check("§16 status done", dn["status"] == "done")
nl = call("GET", f"/leads/{L2['id']}", token=T["sales"])[1]
check("§16 done is logged on the lead", any("Brochure sent" in a["text"] for a in nl["activities"]))
nxt = [f for f in call("GET", f"/followups?related_id={L2['id']}", token=T["sales"])[1] if f.get("previous_id") == F_today["id"]]
check("§16 next follow-up scheduled", len(nxt) == 1 and nxt[0]["due"] == day(5))
created_fu += [f["id"] for f in nxt]
expect("§16 cannot edit a done follow-up", call("PUT", f"/followups/{F_today['id']}", {"title": "x"}, T["sales"]), 409)
expect("§16 reopen", call("POST", f"/followups/{F_today['id']}/reopen", {}, T["sales"]), 200)
expect("§16 cancel", call("POST", f"/followups/{F_today['id']}/cancel", {"reason": "dup"}, T["sales"]), 200)

# timelines
tl = call("GET", f"/contacts/{L2['contact_id']}/timeline", token=T["sales"])[1]
check("§16 contact timeline has follow-ups + activities", any(r["kind"] == "followup" for r in tl) and any(r["kind"] == "activity" for r in tl))

# templates
tpls = call("GET", "/message_templates", token=T["sales"])[1]
check("§16 templates for email, sms, whatsapp", {x["channel"] for x in tpls} >= {"email", "sms", "whatsapp"})
expect("§16 sales cannot edit templates", call("POST", "/message_templates", {"name": "x", "channel": "sms", "body": "hi"}, T["sales"]), 403)
expect("§16 unknown merge field", call("POST", "/message_templates", {"name": "x", "channel": "sms", "body": "Hi {{nickname}}"}, T["owner"]), 400)
expect("§16 bad channel", call("POST", "/message_templates", {"name": "x", "channel": "fax", "body": "hi"}, T["owner"]), 400)
tpl = expect("§16 create template", call("POST", "/message_templates", {"name": f"Quote {RUN}", "channel": "whatsapp",
                                                                        "body": "Hi {{client}}, {{project}} estimate {{amount}} – {{company}}"}, T["owner"]), 201)
r = expect("§16 render with merge fields", call("POST", f"/message_templates/{tpl['id']}/render", {"lead_id": L2["id"]}, T["sales"]), 200)
check("§16 client/project/amount/company filled", f"Enquirer {RUN} 24" in r["text"] and L2["title"] in r["text"] and "25,00,000" in r["text"]
      or "2,500,000" in r["text"], r["text"])
r2 = call("POST", f"/message_templates/{tpl['id']}/render", {"contact_id": L2["contact_id"]}, T["sales"])[1]
check("§16 missing values reported", "project" in r2["missing"] and "{{project}}" in r2["text"], r2)
expect("§16 delete template", call("DELETE", f"/message_templates/{tpl['id']}", token=T["owner"]), 200)

# ---------------- §2.5 win / lose / reopen ----------------
expect("§2.5 win needs PM", call("POST", f"/leads/{L2['id']}/win", {}, T["sales"]), 400)
expect("§2.5 PM must be able to edit projects", call("POST", f"/leads/{L2['id']}/win", {"pm_id": staff["accounts"]}, T["sales"]), 400)
won = expect("§2.5 win creates project", call("POST", f"/leads/{L2['id']}/win", {"pm_id": staff["pm"]}, T["sales"]), 200)
pid = won["project_id"]
created_projects.append(pid)
proj = call("GET", f"/projects/{pid}", token=T["pm"])[1]
check("§2.5 project carries lead data", proj["client_id"] == L2["contact_id"] and proj["services"] == ["construction"]
      and proj["area"] == 180 and proj["area_unit"] == "sqm" and proj["value"] == 2500000 and proj["project_type"] == "Renovation", proj)
check("§C2 PM has edit, salesperson added as Sales", any(m.get("user_id") == staff["pm"] and m["access"] == "edit" for m in proj["team"])
      and any(m.get("user_id") == staff["sales"] and m["project_role"] == "Sales" for m in proj["team"]))
wl = won["lead"]
check("§2.5 lead won and linked", wl["status"] == "won" and wl["project_id"] == pid and wl["stage_history"][-1]["stage"] == "Won")
expect("§C2 won lead locked", call("PUT", f"/leads/{L2['id']}", {"title": "x"}, T["sales"]), 409)
expect("§C2 won lead cannot be lost", call("POST", f"/leads/{L2['id']}/lose", {"reason": "Other"}, T["sales"]), 409)
expect("§C2 won lead cannot be reopened", call("POST", f"/leads/{L2['id']}/reopen", {}, T["sales"]), 409)
moved = [f for f in call("GET", f"/followups?related_id={pid}", token=T["sales"])[1]]
check("§16 open follow-ups move to the project", any(f["id"] == F_over["id"] for f in moved), moved)
pf = call("GET", f"/projects/{pid}/followups", token=T["pm"])[1]
check("§16 project timeline shows lead history + follow-ups", any(r["kind"] == "activity" for r in pf) and any(r["kind"] == "followup" for r in pf))

expect("§2.5 loss reason required", call("POST", f"/leads/{L1['id']}/lose", {}, T["sales"]), 400)
expect("§2.5 loss reason from list", call("POST", f"/leads/{L1['id']}/lose", {"reason": "Bad vibes"}, T["sales"]), 400)
call("POST", f"/leads/{L1['id']}/stage", {"stage": "Negotiation"}, T["sales"])
lost = expect("§2.5 lose", call("POST", f"/leads/{L1['id']}/lose", {"reason": "Price too high", "note": "Cheaper quote"}, T["sales"]), 200)
check("§2.5 loss recorded", lost["status"] == "lost" and lost["loss_reason"] == "Price too high")
check("§2.5 open follow-ups cancelled on loss", call("GET", f"/followups?related_id={L1['id']}", token=T["sales"])[1][0]["status"] == "cancelled")
expect("§C2 lost lead locked", call("POST", f"/leads/{L1['id']}/activities", {"type": "note", "text": "x"}, T["sales"]), 409)
ro = expect("§C2 reopen lost", call("POST", f"/leads/{L1['id']}/reopen", {}, T["sales"]), 200)
check("§C2 reopens at the stage it was lost from", ro["status"] == "open" and ro["stage"] == "Negotiation")
call("POST", f"/leads/{L1['id']}/lose", {"reason": "Chose a competitor"}, T["sales"])
expect("§2.5 owner edits loss reasons", call("PUT", "/leads/pipelines", {"loss_reasons": ["Price too high", "Chose a competitor", "Other", "Timing"]}, T["owner"]), 200)
expect("§2.5 empty loss reasons refused", call("PUT", "/leads/pipelines", {"loss_reasons": []}, T["owner"]), 400)
call("PUT", "/leads/pipelines", {"loss_reasons": ["Price too high", "Chose a competitor", "Project postponed or cancelled",
                                                  "No response from client", "Budget not available", "Outside our services or area", "Other"]}, T["owner"])
expect("§C2 only owner deletes leads", call("DELETE", f"/leads/{ref['id']}", token=T["sales"]), 403)
expect("§C2 won leads cannot be deleted", call("DELETE", f"/leads/{L2['id']}", token=T["owner"]), 409)

# ---------------- §2.5 sales report ----------------
rep = call("GET", f"/reports/sales?from={day(0)}", token=T["sales"])[1]
src = {r["key"]: r for r in rep["by_source"]}
check("§2.5 conversion by source", src["Walk-in"]["won"] >= 1 and src["Walk-in"]["lost"] >= 1 and src["Walk-in"]["conversion"] is not None, src.get("Walk-in"))
sp = {r["key"]: r for r in rep["by_salesperson"]}
check("§2.5 conversion by salesperson", any(k.startswith("Sales") for k in sp))
check("§2.5 conversion by service", {r["key"] for r in rep["by_service"]} >= {"construction"})
check("§2.5 loss reasons", any(r["reason"] == "Chose a competitor" for r in rep["loss_reasons"]))
check("§2.5 pipeline value by stage", "construction" in rep["pipelines"] and all("value" in s for s in rep["pipelines"]["construction"]))
check("§2.5 response time reported", any(r["avg_response_hours"] is not None for r in rep["by_salesperson"]))
tot = rep["totals"]
check("§2.5 conversion math = won/(won+lost)", tot["conversion"] == round(tot["won"] / (tot["won"] + tot["lost"]) * 100, 1), tot)
expect("§1 designer cannot see sales report", call("GET", "/reports/sales", token=T["designer"]), 403)
fr = expect("§16 follow-up report (manager)", call("GET", "/reports/followups", token=T["pm"]), 200)
check("§16 overdue per user", any(r["overdue"] >= 1 for r in fr), fr)
expect("§16 follow-up report blocked for sales", call("GET", "/reports/followups", token=T["sales"]), 403)

# ---------------- §2.6 bids ----------------
expect("§2.6 due date required", call("POST", "/bids", {"title": "x"}, T["sales"]), 400)
expect("§2.6 no-bid needs a reason", call("POST", "/bids", {"title": "x", "due_date": day(5), "decision": "no_bid"}, T["sales"]), 400)
expect("§2.6 cannot submit undecided bid", call("POST", "/bids", {"title": "x", "due_date": day(5), "status": "submitted"}, T["sales"]), 400)
b1 = expect("§2.6 create bid", call("POST", "/bids", {"title": f"Tender A {RUN}", "due_date": day(-1), "decision": "bid", "value": 900000,
                                                     "service": "construction"}, T["sales"]), 201)
b2 = expect("§2.6 create bid 2", call("POST", "/bids", {"title": f"Tender B {RUN}", "due_date": day(9), "decision": "bid"}, T["sales"]), 201)
created_bids += [b1["id"], b2["id"]]
check("§2.6 overdue flag", b1["overdue"] and not b2["overdue"])
expect("§2.6 result needs submission first", call("PUT", f"/bids/{b1['id']}", {"status": "won"}, T["sales"]), 400)
before = call("GET", "/bids", token=T["sales"])[1]
for b, res in ((b1, "won"), (b2, "lost")):
    call("PUT", f"/bids/{b['id']}", {"status": "submitted"}, T["sales"])
    expect(f"§2.6 record {res}", call("PUT", f"/bids/{b['id']}", {"status": res}, T["sales"]), 200)
after = call("GET", "/bids", token=T["sales"])[1]
check("§2.6 hit rate = won / decided", after["decided"] == before["decided"] + 2 and after["won"] == before["won"] + 1
      and after["hit_rate"] == round(after["won"] / after["decided"] * 100, 1), after)
expect("§1 pm cannot create bids", call("POST", "/bids", {"title": "x", "due_date": day(1)}, T["pm"]), 403)

# ---------------- §2.1 website form ----------------
key = call("GET", "/leads/meta", token=T["owner"])[1]["form_key"]
check("§2.1 owner sees form key; sales does not", key and call("GET", "/leads/meta", token=T["sales"])[1]["form_key"] is None)
expect("§2.1 bad key 404", call("GET", "/public/lead-form/nope"), 404)
info = expect("§2.1 form info", call("GET", f"/public/lead-form/{key}"), 200)
check("§2.1 form shows company + services only", info["company"] == "Skyline Design & Build" and "services" in info and "form_key" not in info)
ip = {"X-Forwarded-For": f"10.{int(RUN[-2:])}.1.{int(RUN[-4:-2]) % 250}"}
expect("§2.1 name required", call("POST", f"/public/lead-form/{key}", {"phone": "9000000000"}, headers=ip), 400)
expect("§2.1 phone or email required", call("POST", f"/public/lead-form/{key}", {"name": "W"}, headers=ip), 400)
wp = f"8{RUN[-7:]}55"
expect("§2.1 web enquiry", call("POST", f"/public/lead-form/{key}", {"name": f"Web {RUN}", "phone": wp, "service": "interior",
                                                                     "project_type": "Interior", "message": "3BHK interiors"}, headers=ip), 201)
web = [x for x in call("GET", "/leads?source=Website%20form&owner_id=none", token=T["sales"])[1] if x["contact_name"] == f"Web {RUN}"]
check("§2.1 lands as unassigned Website-form lead", len(web) == 1 and web[0]["service"] == "interior" and web[0]["owner_id"] is None, web)
if web:
    created_leads.append(web[0]["id"])
    created_contacts.append(web[0]["contact_id"])
call("POST", f"/public/lead-form/{key}", {"name": f"Web {RUN}", "phone": wp, "message": "Following up"}, headers=ip)
web2 = [x for x in call("GET", "/leads?source=Website%20form", token=T["sales"])[1] if x["contact_name"] == f"Web {RUN}"]
check("§2.0 repeat web enquiry merged into the open lead", len(web2) == 1 and any("Following up" in a["text"] for a in web2[0]["activities"]))
s, _ = call("POST", f"/public/lead-form/{key}", {"name": "Bot", "phone": "9111111111", "website": "http://spam"}, headers=ip)
check("§2.1 honeypot silently dropped", s == 201 and not any(x["contact_name"] == "Bot" for x in call("GET", "/leads", token=T["sales"])[1]))
codes = [call("POST", f"/public/lead-form/{key}", {"name": f"R{i}", "phone": f"7{RUN[-7:]}6" + str(i)}, headers=ip)[0] for i in range(4)]
check("§2.1 rate limit (5 per 10 min per IP)", 429 in codes, codes)
for x in call("GET", "/leads?source=Website%20form", token=T["owner"])[1]:
    if x["contact_name"].startswith("R") and len(x["contact_name"]) == 2:
        created_leads.append(x["id"])
        created_contacts.append(x["contact_id"])

# ---------------- §3.6 relationship history ----------------
h = call("GET", f"/contacts/{L1['contact_id']}/history", token=T["sales"])[1]
check("§3.6 referred leads listed", any(x["id"] == ref["id"] for x in h["referred_leads"]))

# ---------------- home ----------------
hm = call("GET", "/home", token=T["sales"])[1]
check("§16 home shows my follow-ups", "followups" in hm and hm["followups"]["overdue"] >= 0 and "leads" in hm)

# ---------------- cleanup ----------------
for f in created_fu:
    call("DELETE", f"/followups/{f}", token=T["owner"])
for b in created_bids:
    call("DELETE", f"/bids/{b}", token=T["sales"])
for p in created_projects:
    call("DELETE", f"/projects/{p}", token=T["owner"])
for x in created_leads:
    call("PUT", f"/leads/{x}", {}, T["owner"])
    call("DELETE", f"/leads/{x}", token=T["owner"])
for f in call("GET", "/followups", token=T["owner"])[1]:
    if RUN in f["title"]:
        call("DELETE", f"/followups/{f['id']}", token=T["owner"])
for c in set(created_contacts):
    call("DELETE", f"/contacts/{c}", token=T["owner"])
check("cleanup: no test leads left", not any(RUN in x["title"] or RUN in (x.get("contact_name") or "") for x in call("GET", "/leads", token=T["owner"])[1]))

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
