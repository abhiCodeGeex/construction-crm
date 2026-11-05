"""Phase C+ — leads in depth. One block per row of PLAN.md C+1 / C+2 / C+3. Cleans up everything it creates.

    docker compose exec backend python tests/test_leads_deep.py
"""
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

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


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "sales", "pm", "estimator", "accounts")}
U = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1] if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
leads, contacts, temp_users = [], [], []
n = 0
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"sales": 1, "email_settings": 1})


def new_lead(token=None, **kw):
    global n
    n += 1
    body = {"title": f"Deep {RUN} {n}", "service": "construction", "source": "Walk-in",
            "contact_name": f"Client {RUN} {n}", "contact_phone": f"8{RUN[-7:]}{n:02d}", **kw}
    s, d = call("POST", "/leads", body, token or T["sales"])
    assert s == 201, (s, d)
    leads.append(d["id"])
    contacts.append(d["contact_id"])
    return d


def get(lid, token=None):
    return call("GET", f"/leads/{lid}", token=token or T["owner"])[1]


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def ready_lead_stage(lid):
    meta = call("GET", "/leads/meta", token=T["sales"])[1]
    for item in meta["stage_rules"]["construction"]["Lead"]["checklist"]:
        call("POST", f"/leads/{lid}/checklist", {"stage": "Lead", "item": item, "done": True}, T["sales"])
    call("POST", f"/leads/{lid}/activities", {"type": "call", "text": "First call", "outcome": "Reached", "next_due": day(1)},
         T["sales"])


# a tiny SMTP server so email delivery is tested for real (the backend runs in this container)
mails = []


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 test\r\n")
        data, in_data = [], False
        while True:
            line = self.rfile.readline()
            if not line:
                return
            if in_data:
                if line in (b".\r\n", b".\n"):
                    in_data = False
                    mails.append(b"".join(data).decode(errors="replace"))
                    data = []
                    self.wfile.write(b"250 ok\r\n")
                else:
                    data.append(line)
                continue
            cmd = line[:4].upper()
            if cmd in (b"EHLO", b"HELO"):
                self.wfile.write(b"250 test\r\n")
            elif cmd == b"DATA":
                in_data = True
                self.wfile.write(b"354 go\r\n")
            elif cmd == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


socketserver.TCPServer.allow_reuse_address = True
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 2526), SMTPHandler)
threading.Thread(target=smtp.serve_forever, daemon=True).start()

try:
    # ================= C+1 sales settings =================
    m = call("GET", "/leads/meta", token=T["sales"])[1]
    check("C+1 default stage rules from the plan", m["stage_rules"]["construction"]["Lead"]["requires"] == ["first_contact"]
          and m["stage_rules"]["construction"]["Proposal/Bid"]["requires"] == ["estimate_approved", "proposal_sent"])
    expect("C+1 sales cannot change sales settings", call("PUT", "/leads/settings", {"response_minutes": 5}, T["sales"]), 403)
    expect("C+1 unknown required step", call("PUT", "/leads/settings", {"stage_rules": {"construction": {"Lead": {"requires": ["magic"]}}}}, T["owner"]), 400)
    expect("C+1 rule for a stage not in the pipeline", call("PUT", "/leads/settings", {"stage_rules": {"construction": {"Dreaming": {}}}}, T["owner"]), 400)
    expect("C+1 bad response target", call("PUT", "/leads/settings", {"response_minutes": 0}, T["owner"]), 400)
    expect("C+1 manager must be staff", call("PUT", "/leads/settings", {"manager_id": "nobody"}, T["owner"]), 400)
    s = expect("C+1 save settings", call("PUT", "/leads/settings", {"response_minutes": 30, "max_discount_pct": 10,
                                                                    "min_margin_pct": 15, "followup_escalate_days": 2,
                                                                    "hot_idle_days": 3, "manager_id": None}, T["owner"]), 200)
    check("C+1 settings returned", s["sales_settings"]["response_minutes"] == 30)

    # ================= C+2.1 new enquiry: assignment notifications =================
    L = new_lead(token=T["owner"], owner_id=U["sales"])
    check("C+2.1 created entry on the timeline", L["activities"][0]["type"] == "created" and "Walk-in" in L["activities"][0]["text"])
    check("C+2.1 salesperson notified of the new lead", any(x["lead_id"] == L["id"] and x["event"] == "lead_assigned" for x in bell("sales")))
    U0 = new_lead(owner_id=None)
    check("C+2.1 unassigned lead goes to the manager (owner)", any(x["lead_id"] == U0["id"] and x["event"] == "lead_unassigned" for x in bell("owner")))
    mine = new_lead()
    check("C+2.1 nobody is notified of their own lead", not any(x["lead_id"] == mine["id"] for x in bell("sales")))

    # ================= C+1 old -> new edit log; reassignment =================
    e = expect("C+1 edit", call("PUT", f"/leads/{L['id']}", {"budget": 4500000, "temperature": "hot", "expected_close": day(30)}, T["sales"]), 200)
    ed = e["activities"][-1]
    check("C+1 edit logged old -> new", ed["type"] == "edit" and {c["field"] for c in ed["changes"]} == {"Budget", "Temperature", "Expected close"}
          and any(c["field"] == "Temperature" and c["from"] == "—" and c["to"] == "hot" for c in ed["changes"]), ed)
    same = expect("C+1 saving without changes", call("PUT", f"/leads/{L['id']}", {"budget": 4500000}, T["sales"]), 200)
    check("C+1 no empty edit entries", len(same["activities"]) == len(e["activities"]))
    expect("C+2.2 temperature validated", call("PUT", f"/leads/{L['id']}", {"temperature": "lukewarm"}, T["sales"]), 400)
    expect("C+2.2 probability validated", call("PUT", f"/leads/{L['id']}", {"probability": 120}, T["sales"]), 400)
    expect("C+2.2 close date validated", call("PUT", f"/leads/{L['id']}", {"expected_close": "soon"}, T["sales"]), 400)
    expect("C+2.1 channel validated", call("PUT", f"/leads/{L['id']}", {"preferred_channel": "pigeon"}, T["sales"]), 400)
    check("C+3 probability defaults to the stage's (Lead 10%)", e["probability_effective"] == 10 and e["weighted_value"] == 450000, e["weighted_value"])
    p = expect("C+2.2 probability override", call("PUT", f"/leads/{L['id']}", {"probability": 40, "preferred_language": "Hindi",
                                                                             "best_time": "after 6 pm", "preferred_channel": "whatsapp",
                                                                             "tags": ["villa", "villa", " premium "]}, T["sales"]), 200)
    check("C+2.2 override used for weighted value", p["probability_effective"] == 40 and p["weighted_value"] == 1800000)
    check("C+2.1 tags cleaned", p["tags"] == ["villa", "premium"])
    check("C+3 score computed", isinstance(p["score"], int) and 0 <= p["score"] <= 100)
    r = expect("C+2.9 reassign", call("PUT", f"/leads/{L['id']}", {"owner_id": U["pm"]}, T["owner"]), 200)
    check("C+2.9 reassignment logged", "Salesperson" in r["activities"][-1]["text"] and "→" in r["activities"][-1]["text"])
    check("C+2.9 new salesperson notified", any(x["lead_id"] == L["id"] and x["event"] == "lead_reassigned" for x in bell("pm")))
    check("C+2.9 old salesperson notified", any(x["lead_id"] == L["id"] and x["event"] == "lead_reassigned" for x in bell("sales")))
    call("PUT", f"/leads/{L['id']}", {"owner_id": U["sales"]}, T["owner"])

    # ================= C+1 calls / meetings need outcome + next step =================
    A = f"/leads/{L['id']}/activities"
    expect("C+1 call needs an outcome", call("POST", A, {"type": "call", "text": "spoke"}, T["sales"]), 400)
    expect("C+1 call outcome from the list", call("POST", A, {"type": "call", "text": "spoke", "outcome": "fine", "next_due": day(1)}, T["sales"]), 400)
    expect("C+1 call needs the next step", call("POST", A, {"type": "call", "text": "spoke", "outcome": "Reached"}, T["sales"]), 400)
    expect("C+1 next step not in the past", call("POST", A, {"type": "call", "text": "spoke", "outcome": "Reached", "next_due": day(-1)}, T["sales"]), 400)
    expect("C+1 meeting needs an outcome", call("POST", A, {"type": "meeting", "text": "met", "next_due": day(2)}, T["sales"]), 400)
    expect("C+1 site visit cannot be typed", call("POST", A, {"type": "site_visit", "text": "went"}, T["sales"]), 400)
    nb = expect("C+1 a note is not first contact", call("POST", A, {"type": "note", "text": "internal"}, T["sales"]), 201)
    check("C+1 note leaves first response empty", nb["first_response_at"] is None)
    expect("C+1 wrong number needs no next step", call("POST", A, {"type": "call", "text": "wrong", "outcome": "Wrong number"}, T["sales"]), 201)
    c = expect("C+1 call with outcome and next step", call("POST", A, {"type": "call", "text": "Discussed budget", "outcome": "Reached",
                                                                       "next_due": day(2), "duration_min": 12, "next_title": f"Send brochure {RUN}"}, T["sales"]), 201)
    check("C+1 first response recorded by the call", c["first_response_at"] is not None)
    check("C+1 call stored with outcome, duration, next step", c["activities"][-1]["outcome"] == "Reached" and c["activities"][-1]["duration_min"] == 12
          and c["activities"][-1]["next_due"] == day(2))
    fu = [f for f in call("GET", f"/followups?related_id={L['id']}", token=T["sales"])[1] if f["title"] == f"Send brochure {RUN}"]
    check("C+1 next step became a follow-up", len(fu) == 1 and fu[0]["due"] == day(2) and fu[0]["owner_id"] == U["sales"], fu)

    # ================= C+1 stage exit rules =================
    S = f"/leads/{L['id']}/stage"
    lead = get(L["id"])
    check("C+1 missing items listed on the lead", any("Checklist" in x for x in lead["missing"]) and not any("First contact" in x for x in lead["missing"]))
    expect("C+1 forward move refused while the checklist is open", call("POST", S, {"stage": "Site visit"}, T["sales"]), 409)
    expect("C+1 checklist item must exist", call("POST", f"/leads/{L['id']}/checklist", {"stage": "Lead", "item": "Feng shui", "done": True}, T["sales"]), 400)
    for item in m["stage_rules"]["construction"]["Lead"]["checklist"]:
        call("POST", f"/leads/{L['id']}/checklist", {"stage": "Lead", "item": item, "done": True}, T["sales"])
    un = expect("C+1 untick", call("POST", f"/leads/{L['id']}/checklist", {"stage": "Lead", "item": "Budget confirmed", "done": False}, T["sales"]), 200)
    check("C+1 untick logged and item missing again", "unticked" in un["activities"][-1]["text"] and "Checklist: Budget confirmed" in un["missing"])
    call("POST", f"/leads/{L['id']}/checklist", {"stage": "Lead", "item": "Budget confirmed", "done": True}, T["sales"])
    expect("C+1 skipping two stages refused", call("POST", S, {"stage": "Proposal/Bid"}, T["sales"]), 409)
    mv = expect("C+1 ready lead moves on", call("POST", S, {"stage": "Site visit"}, T["sales"]), 200)
    check("C+1 days in stage restart", mv["days_in_stage"] == 0 and mv["max_days"] == 10)
    res = call("POST", S, {"stage": "Proposal/Bid"}, T["sales"])
    check("C+1 refusal names what is missing", res[0] == 409 and "Site visit done" in res[1]["error"] and "Measurements" in res[1]["error"], res)
    expect("C+1 only the owner overrides", call("POST", S, {"stage": "Proposal/Bid", "override_reason": "trust me"}, T["sales"]), 403)
    ov = expect("C+1 owner override with reason", call("POST", S, {"stage": "Proposal/Bid", "override_reason": "Visit done before the CRM"}, T["owner"]), 200)
    check("C+1 override logged with what was skipped", "owner override: Visit done before the CRM" in ov["activities"][-1]["text"]
          and "Measurements" in ov["activities"][-1]["text"])
    back = expect("C+1 moving back is free", call("POST", S, {"stage": "Lead"}, T["sales"]), 200)
    check("C+1 back move logged", back["activities"][-1]["text"] == "Moved from Proposal/Bid to Lead")
    custom = call("PUT", "/leads/settings", {"stage_rules": {"construction": {"Lead": {"checklist": [], "requires": [], "max_days": 2,
                                                                                     "probability": 15}}}}, T["owner"])
    check("C+1 custom rules saved", custom[0] == 200 and custom[1]["stage_rules"]["construction"]["Lead"]["max_days"] == 2)
    lead = get(L["id"])
    check("C+1 custom probability applies", lead["probability_effective"] == 40)  # the lead's own override still wins
    call("PUT", "/leads/settings", {"stage_rules": {"construction": {"Lead": {"checklist": m["stage_rules"]["construction"]["Lead"]["checklist"],
                                                                             "requires": ["first_contact"], "max_days": 3, "probability": 10}}}}, T["owner"])

    # ================= C+2.8 on hold / resume =================
    H = new_lead()
    expect("C+2.8 hold needs a reason", call("POST", f"/leads/{H['id']}/hold", {"resume_on": day(10)}, T["sales"]), 400)
    expect("C+2.8 resume date in the future", call("POST", f"/leads/{H['id']}/hold", {"reason": "Diwali", "resume_on": day(0)}, T["sales"]), 400)
    h = expect("C+2.8 put on hold", call("POST", f"/leads/{H['id']}/hold", {"reason": "Client travelling", "resume_on": day(10)}, T["sales"]), 200)
    check("C+2.8 on hold logged", h["status"] == "on_hold" and "On hold until" in h["activities"][-1]["text"])
    expect("C+2.8 on-hold lead is read-only", call("PUT", f"/leads/{H['id']}", {"budget": 1}, T["sales"]), 409)
    board = call("GET", "/leads?status=open&service=construction", token=T["sales"])[1]
    check("C+2.8 not on the active board", not any(x["id"] == H["id"] for x in board))
    check("C+2.8 listed under on hold", any(x["id"] == H["id"] for x in call("GET", "/leads?status=on_hold", token=T["sales"])[1]))
    rep = call("GET", "/reports/sales", token=T["owner"])[1]
    check("C+2.8 not counted as lost", rep["totals"]["lost"] >= 0 and any(r["on_hold"] >= 1 for r in rep["by_source"]))
    dup = call("POST", "/leads", {"title": "dup", "service": "construction", "source": "Walk-in", "contact_name": "x",
                                  "contact_phone": f"8{RUN[-7:]}{n:02d}"}, T["sales"])
    check("C+2.8 on-hold lead still catches duplicates", dup[0] == 409, dup)
    rs = expect("C+2.8 resume", call("POST", f"/leads/{H['id']}/resume", {}, T["sales"]), 200)
    check("C+2.8 resumed at the same stage", rs["status"] == "open" and rs["stage"] == "Lead" and "Resumed" in rs["activities"][-1]["text"])
    expect("C+2.8 resume only on hold", call("POST", f"/leads/{H['id']}/resume", {}, T["sales"]), 409)
    call("POST", f"/leads/{H['id']}/hold", {"reason": "Waiting for loan", "resume_on": day(5)}, T["sales"])
    mongo.leads.update_one({"_id": ObjectId(H["id"])}, {"$set": {"resume_on": day(0)}})
    worker()
    w = get(H["id"])
    check("C+2.8 worker brings it back on the resume date", w["status"] == "open" and "resume date" in w["activities"][-1]["text"], w["status"])
    check("C+2.8 salesperson told it resumed", any(x["lead_id"] == H["id"] and x["event"] == "lead_resumed" for x in bell("sales")))

    # ================= C+2.8 lost with competitor + re-engage; reopen =================
    LL = new_lead()
    expect("C+2.8 price without competitor", call("POST", f"/leads/{LL['id']}/lose", {"reason": "Price too high", "competitor_price": 100}, T["sales"]), 400)
    expect("C+2.8 re-engage in the future", call("POST", f"/leads/{LL['id']}/lose", {"reason": "Price too high", "reengage_on": day(0)}, T["sales"]), 400)
    lo = expect("C+2.8 lose with competitor", call("POST", f"/leads/{LL['id']}/lose", {"reason": "Chose a competitor", "competitor": f"BuildCo {RUN}",
                                                                                      "competitor_price": 3900000, "reengage_on": day(90)}, T["sales"]), 200)
    check("C+2.8 competitor stored and logged", lo["competitor"] == f"BuildCo {RUN}" and lo["competitor_price"] == 3900000
          and f"to BuildCo {RUN}" in lo["activities"][-1]["text"])
    re = [f for f in call("GET", f"/followups?related_id={LL['id']}", token=T["sales"])[1] if f["status"] == "open"]
    check("C+2.8 re-engage follow-up created", len(re) == 1 and re[0]["due"] == day(90) and re[0]["title"].startswith("Re-engage"), re)
    check("C+2.8 manager told of the loss", any(x["lead_id"] == LL["id"] and x["event"] == "lead_lost" for x in bell("owner")))
    ro = expect("C+2.8 reopen with reason", call("POST", f"/leads/{LL['id']}/reopen", {"reason": "Competitor backed out"}, T["sales"]), 200)
    check("C+2.8 reopen logged with reason", "Competitor backed out" in ro["activities"][-1]["text"] and ro["competitor"] is None)
    check("C+2.8 re-engage follow-up cancelled on reopen",
          all(f["status"] == "cancelled" for f in call("GET", f"/followups?related_id={LL['id']}", token=T["sales"])[1] if f["title"].startswith("Re-engage")))

    # ================= C+1 scheduled checks (worker) =================
    R = new_lead()
    mongo.leads.update_one({"_id": ObjectId(R["id"])}, {"$set": {"created_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=45)}})
    worker()
    worker()
    late = [x for x in bell("sales") + bell("owner") if x["lead_id"] == R["id"] and x["event"] == "response_late"]
    check("C+1 not contacted in time -> salesperson and manager, once each", sorted(x["user_id"] for x in late) == sorted([U["sales"], U["owner"]]), late)
    mongo.leads.update_one({"_id": ObjectId(R["id"])}, {"$set": {"stage_entered_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=4)}})
    worker()
    check("C+1 stuck past the day limit -> salesperson", any(x["lead_id"] == R["id"] and x["event"] == "lead_stuck" for x in bell("sales")))
    check("C+1 not yet the manager (under twice the limit)", not any(x["lead_id"] == R["id"] and x["event"] == "lead_stuck" for x in bell("owner")))
    mongo.leads.update_one({"_id": ObjectId(R["id"])}, {"$set": {"stage_entered_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)}})
    worker()
    check("C+1 past twice the limit -> manager", any(x["lead_id"] == R["id"] and x["event"] == "lead_stuck" for x in bell("owner")))
    call("PUT", f"/leads/{R['id']}", {"temperature": "hot"}, T["sales"])
    mongo.leads.update_one({"_id": ObjectId(R["id"])}, {"$set": {"last_activity_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=4)}})
    worker()
    check("C+1 hot and idle -> manager", any(x["lead_id"] == R["id"] and x["event"] == "hot_idle" for x in bell("owner")))
    f1 = expect("C+1 follow-up due today", call("POST", "/followups", {"title": f"Due {RUN}", "due": day(0), "related": {"type": "lead", "id": R["id"]}}, T["sales"]), 201)
    f2 = expect("C+1 follow-up overdue", call("POST", "/followups", {"title": f"Late {RUN}", "due": day(-5), "related": {"type": "lead", "id": R["id"]}}, T["sales"]), 201)
    worker()
    check("C+1 due-today reminder", any(x["event"] == "followup_due" and f"Due {RUN}" in x["text"] for x in bell("sales")))
    check("C+1 overdue reminder", any(x["event"] == "followup_overdue" and f"Late {RUN}" in x["text"] for x in bell("sales")))
    check("C+1 overdue past the escalation days -> manager", any(x["event"] == "followup_overdue" and f"Late {RUN}" in x["text"] for x in bell("owner")))
    before = mongo.notifications.count_documents({"company_id": CID, "lead_id": R["id"]})
    worker()
    check("C+1 running again sends nothing twice", mongo.notifications.count_documents({"company_id": CID, "lead_id": R["id"]}) == before)
    ga = call("POST", "/followups", {"title": f"For pm {RUN}", "due": day(3), "owner_id": U["pm"], "related": {"type": "lead", "id": R["id"]}}, T["sales"])
    check("C+1 follow-up given to someone -> they are told", ga[0] == 201 and any(x["event"] == "followup_assigned" and f"For pm {RUN}" in x["text"] for x in bell("pm")))

    # ================= C+1 the bell API and preferences =================
    b = expect("C+1 my notifications", call("GET", "/notifications", token=T["sales"]), 200)
    check("C+1 only my own", all(x["user_id"] == U["sales"] for x in b["items"]) and b["unread"] >= 1)
    nid = b["items"][0]["id"]
    expect("C+1 mark read", call("POST", f"/notifications/{nid}/read", {}, T["sales"]), 200)
    check("C+1 unread count drops", call("GET", "/notifications", token=T["sales"])[1]["unread"] == b["unread"] - 1)
    other = mongo.notifications.find_one({"company_id": CID, "user_id": U["owner"], "read_at": None})
    if other:
        call("POST", f"/notifications/{other['_id']}/read", {}, T["sales"])
        check("C+1 cannot read someone else's", mongo.notifications.find_one({"_id": other["_id"]})["read_at"] is None)
    pr = call("GET", "/notifications/prefs", token=T["sales"])[1]
    rows = [{**e, "in_app": False} for e in pr["events"]]
    sp = expect("C+1 save preferences", call("PUT", "/notifications/prefs", {"events": rows}, T["sales"]), 200)
    check("C+1 critical events stay on", all(e["in_app"] == e["critical"] for e in sp["events"]))
    Q = new_lead()
    call("POST", "/followups", {"title": f"Muted {RUN}", "due": day(0), "related": {"type": "lead", "id": Q["id"]}}, T["sales"])
    worker()
    check("C+1 switched-off event not sent", not any(f"Muted {RUN}" in x["text"] for x in bell("sales")))
    T2 = new_lead(token=T["owner"], owner_id=U["sales"])
    check("C+1 critical event still sent", any(x["lead_id"] == T2["id"] and x["event"] == "lead_assigned" for x in bell("sales")))
    call("PUT", "/notifications/prefs", {"events": [{**e, "in_app": True, "email": True} for e in pr["events"]]}, T["sales"])
    expect("C+1 read all", call("POST", "/notifications/read-all", {}, T["sales"]), 200)
    check("C+1 nothing unread", call("GET", "/notifications", token=T["sales"])[1]["unread"] == 0)

    # ================= C+1 email (SMTP) =================
    expect("C+1 sales cannot set up email", call("PUT", "/settings/email", {"host": "x"}, T["sales"]), 403)
    expect("C+1 from address required", call("PUT", "/settings/email", {"host": "127.0.0.1", "port": 2526, "from_address": "nope"}, T["owner"]), 400)
    es = expect("C+1 set up email", call("PUT", "/settings/email", {"host": "127.0.0.1", "port": 2526, "from_address": "crm@skyline.test",
                                                                    "username": None, "password": "secret", "use_tls": False}, T["owner"]), 200)
    check("C+1 password never returned", es["password"] == "••••••" and es["ready"])
    keep = expect("C+1 masked password kept on save", call("PUT", "/settings/email", {**es, "password": "••••••"}, T["owner"]), 200)
    check("C+1 stored password unchanged", mongo.companies.find_one({"_id": ObjectId(CID)})["email_settings"]["password"] == "secret")
    expect("C+1 test email", call("POST", "/settings/email/test", {"to": "owner@skyline.test"}, T["owner"]), 200)
    check("C+1 test email delivered", any("Test email" in x for x in mails), len(mails))
    E = new_lead(token=T["owner"], owner_id=U["sales"])
    time.sleep(1.5)
    nE = mongo.notifications.find_one({"company_id": CID, "user_id": U["sales"], "lead_id": E["id"], "event": "lead_assigned"})
    check("C+1 notification emailed", nE and nE["email"] == "sent" and any(E["title"] in x for x in mails), nE and nE["email"])
    expect("C+1 switch email off", call("PUT", "/settings/email", {"host": ""}, T["owner"]), 200)
    check("C+1 email off", not call("GET", "/settings/email", token=T["owner"])[1]["ready"])
    expect("C+1 test fails when off", call("POST", "/settings/email/test", {}, T["owner"]), 400)

    # ================= C+3 visibility: salespeople see only their own =================
    s2 = call("POST", "/users", {"name": f"Sales Two {RUN}", "email": f"sales2.{RUN}@skyline.test", "role": "sales", "password": "secret1"}, T["owner"])
    if s2[0] == 201:
        temp_users.append(s2[1]["id"])
        t2 = call("POST", "/auth/login", {"email": f"sales2.{RUN}@skyline.test", "password": "secret1"})[1]["token"]
        check("C+3 shared pipeline by default", call("GET", f"/leads/{L['id']}", token=t2)[0] == 200)
        call("PUT", "/leads/settings", {"own_leads_only": True}, T["owner"])
        check("C+3 restricted: other's lead hidden", call("GET", f"/leads/{L['id']}", token=t2)[0] == 404)
        check("C+3 restricted: list shows only own", all(x["owner_id"] == s2[1]["id"] for x in call("GET", "/leads", token=t2)[1]))
        check("C+3 owner still sees everything", call("GET", f"/leads/{L['id']}", token=T["owner"])[0] == 200)
        call("PUT", "/leads/settings", {"own_leads_only": False}, T["owner"])
    else:
        check("C+3 temp sales user", False, s2)

    # ================= C+2.3 site visits =================
    call("PUT", "/settings/email", {"host": "127.0.0.1", "port": 2526, "from_address": "crm@skyline.test", "use_tls": False}, T["owner"])
    V = new_lead(location=None, contact_email=f"client{RUN}@example.test")
    VB = f"/leads/{V['id']}/visits"
    soon = lambda hours: (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    expect("C+2.3 visit needs staff", call("POST", VB, {"at": soon(30), "address": "Plot 4"}, T["sales"]), 400)
    expect("C+2.3 visit needs a time", call("POST", VB, {"at": "tomorrow", "staff_ids": [U["pm"]], "address": "Plot 4"}, T["sales"]), 400)
    expect("C+2.3 visit needs an address", call("POST", VB, {"at": soon(30), "staff_ids": [U["pm"]]}, T["sales"]), 400)
    expect("C+2.3 staff must be active staff", call("POST", VB, {"at": soon(30), "staff_ids": ["x"], "address": "Plot 4"}, T["sales"]), 400)
    v1 = expect("C+2.3 book a visit", call("POST", VB, {"at": soon(30), "staff_ids": [U["pm"], U["sales"]], "address": f"Plot 4 {RUN}",
                                                        "duration_min": 90, "email_client": True}, T["sales"]), 201)
    check("C+2.3 booked as scheduled", v1["status"] == "scheduled" and v1["duration_min"] == 90 and len(v1["staff"]) == 2)
    check("C+2.3 staff told (not the person who booked)", any(x["event"] == "visit_assigned" and x["lead_id"] == V["id"] for x in bell("pm"))
          and not any(x["event"] == "visit_assigned" and x["lead_id"] == V["id"] for x in bell("sales")))
    time.sleep(0.5)
    check("C+2.3 client emailed the booking", any(f"Plot 4 {RUN}" in x and f"client{RUN}@example.test" in x for x in mails))
    tl = get(V["id"])["activities"]
    check("C+2.3 booking and client email on the timeline", any(a["type"] == "visit" and "booked" in a["text"] for a in tl)
          and any(a["type"] == "email" and a.get("outcome") == "sent" for a in tl))
    expect("C+2.3 cannot be done before it happens", call("POST", f"/visits/{v1['id']}/status", {"status": "done"}, T["sales"]), 400)
    expect("C+2.3 cancel needs a reason", call("POST", f"/visits/{v1['id']}/status", {"status": "cancelled"}, T["sales"]), 400)
    cf = expect("C+2.3 client confirmed", call("POST", f"/visits/{v1['id']}/status", {"status": "confirmed"}, T["sales"]), 200)
    check("C+2.3 status history", cf["status"] == "confirmed" and cf["history"][-1]["action"] == "confirmed")
    expect("C+2.3 reschedule needs a reason", call("POST", f"/visits/{v1['id']}/reschedule", {"at": soon(50)}, T["sales"]), 400)
    rs = expect("C+2.3 reschedule", call("POST", f"/visits/{v1['id']}/reschedule", {"at": soon(50), "reason": "Client asked for Saturday"}, T["sales"]), 200)
    check("C+2.3 rescheduled keeps old -> new and goes back to scheduled", rs["status"] == "scheduled" and rs["history"][-1]["reason"] == "Client asked for Saturday"
          and rs["history"][-1]["from"] != rs["history"][-1]["to"])
    check("C+2.3 staff told of the new time", any(x["event"] == "visit_changed" and x["lead_id"] == V["id"] for x in bell("pm")))
    ev = expect("C+2.3 change staff", call("PUT", f"/visits/{v1['id']}", {"staff_ids": [U["pm"], U["estimator"]]}, T["sales"]), 200)
    check("C+2.3 new staff told", [s["name"] for s in ev["staff"]] and any(x["event"] == "visit_assigned" and x["lead_id"] == V["id"] for x in bell("estimator")))
    check("C+2.3 staff change logged", "staff" in get(V["id"])["activities"][-1]["text"])
    expect("C+2.3 report only after the visit", call("PUT", f"/visits/{v1['id']}/report", {"findings": "x"}, T["sales"]), 409)
    past = expect("C+2.3 book a visit that already happened", call("POST", VB, {"at": soon(-3), "staff_ids": [U["sales"]], "address": "Plot 4"}, T["sales"]), 201)
    ready_lead_stage(V["id"])
    expect("C+2.3 into Site visit", call("POST", f"/leads/{V['id']}/stage", {"stage": "Site visit"}, T["sales"]), 200)
    check("C+2.3 visit requirement open until done + reported", "Site visit done and its report submitted" in get(V["id"])["missing"])
    dn = expect("C+2.3 mark done", call("POST", f"/visits/{past['id']}/status", {"status": "done"}, T["sales"]), 200)
    check("C+2.3 done visit counts as activity", get(V["id"])["last_activity_at"] is not None)
    check("C+2.3 done without report is not enough", "Site visit done and its report submitted" in get(V["id"])["missing"])
    expect("C+2.3 cannot reopen a done visit", call("POST", f"/visits/{past['id']}/status", {"status": "confirmed"}, T["sales"]), 409)
    expect("C+2.3 report needs findings", call("PUT", f"/visits/{past['id']}/report", {"findings": " "}, T["sales"]), 400)
    expect("C+2.3 checklist items from the list", call("PUT", f"/visits/{past['id']}/report", {"findings": "ok", "site_checklist": [{"item": "Unicorns", "value": "yes"}]}, T["sales"]), 400)
    expect("C+2.3 checklist answers yes / no / n.a.", call("PUT", f"/visits/{past['id']}/report", {"findings": "ok", "site_checklist": [{"item": "Demolition needed", "value": "maybe"}]}, T["sales"]), 400)
    rp = expect("C+2.3 submit report", call("PUT", f"/visits/{past['id']}/report", {
        "findings": "Old flooring, walls fine", "risks": "Seepage near kitchen", "recommendations": "Waterproof before tiling",
        "site_checklist": [{"item": "Demolition needed", "value": "yes", "note": "kitchen only"}, {"item": "Power supply available", "value": "na"}],
        "cost": {"travel": 800, "staff_hours": 3, "hourly_rate": 500, "other": 200}}, T["sales"]), 200)
    check("C+2.3 report and cost stored", rp["report"]["submitted_at"] and rp["cost"]["total"] == 2500 and len(rp["site_checklist"]) == 2)
    exp = list(mongo.lead_expenses.find({"company_id": CID, "lead_id": V["id"]}))
    check("C+2.3 visit cost becomes pre-sales spend", len(exp) == 1 and exp[0]["amount"] == 2500, exp)
    call("PUT", f"/visits/{past['id']}/report", {"findings": "Old flooring, walls fine", "cost": {"travel": 1000}}, T["sales"])
    exp = list(mongo.lead_expenses.find({"company_id": CID, "lead_id": V["id"]}))
    check("C+2.3 updated cost replaces the expense (no duplicate)", len(exp) == 1 and exp[0]["amount"] == 1000, exp)
    check("C+2.3 report notification to the salesperson",
          True if get(V["id"])["owner_id"] == U["sales"] else any(x["event"] == "visit_report" for x in bell("sales")))
    check("C+2.3 visit requirement met once reported", "Site visit done and its report submitted" not in get(V["id"])["missing"])

    # worker: reminders, missed, late report
    soonv = expect("C+2.3 visit tomorrow", call("POST", VB, {"at": soon(20), "staff_ids": [U["pm"]], "address": "Plot 4"}, T["sales"]), 201)
    nowv = expect("C+2.3 visit in an hour", call("POST", VB, {"at": soon(1), "staff_ids": [U["pm"]], "address": "Plot 4"}, T["sales"]), 201)
    gone = expect("C+2.3 visit that nobody closed", call("POST", VB, {"at": soon(-5), "staff_ids": [U["pm"]], "address": "Plot 4"}, T["sales"]), 201)
    late_r = expect("C+2.3 done visit without report", call("POST", VB, {"at": soon(-30), "staff_ids": [U["pm"]], "address": "Plot 4"}, T["sales"]), 201)
    call("POST", f"/visits/{late_r['id']}/status", {"status": "done"}, T["sales"])
    mongo.lead_visits.update_one({"_id": ObjectId(late_r["id"])}, {"$set": {"done_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)}})
    mails.clear()
    worker()
    worker()
    pmb = bell("pm")
    check("C+2.3 day-before reminder to staff", sum(1 for x in pmb if x["event"] == "visit_reminder" and x.get("key", "").startswith(f"visit-24:{soonv['id']}")) == 1)
    check("C+2.3 2-hour reminder to staff", sum(1 for x in pmb if x["event"] == "visit_reminder" and x.get("key", "").startswith(f"visit-2:{nowv['id']}")) == 1)
    time.sleep(0.5)
    check("C+2.3 client reminded by email once", sum(1 for x in mails if "A reminder of our visit" in x) == 1, len(mails))
    check("C+2.3 missed visit -> staff, salesperson, manager", any(x["event"] == "visit_missed" and gone["id"] in x.get("key", "") for x in bell("owner"))
          and any(x["event"] == "visit_missed" and gone["id"] in x.get("key", "") for x in pmb))
    check("C+2.3 late report -> manager", any(x["event"] == "report_late" and late_r["id"] in x.get("key", "") for x in bell("owner")))
    nos = expect("C+2.3 no-show with reason", call("POST", f"/visits/{gone['id']}/status", {"status": "no_show", "reason": "Client not home"}, T["sales"]), 200)
    check("C+2.3 no-show logged", "no-show" in get(V["id"])["activities"][-1]["text"])

    # ================= C+2.3 measurements =================
    MB = f"/leads/{V['id']}"
    expect("C+2.3 room needs a name", call("POST", f"{MB}/rooms", {"length": 10, "width": 10}, T["sales"]), 400)
    expect("C+2.3 room size positive", call("POST", f"{MB}/rooms", {"name": "Living", "length": -1, "width": 10}, T["sales"]), 400)
    expect("C+2.3 opening kind", call("POST", f"{MB}/rooms", {"name": "Living", "length": 12, "width": 10, "openings": [{"kind": "portal", "width": 1, "height": 1}]}, T["sales"]), 400)
    me = expect("C+2.3 measure a room", call("POST", f"{MB}/rooms", {"name": "Living", "length": 12, "width": 10, "height": 10, "openings": [
        {"kind": "door", "width": 3, "height": 7}, {"kind": "window", "width": 4, "height": 4, "count": 2}]}, T["sales"]), 200)
    lr = me["rooms"][0]
    check("C+2.3 areas computed", (lr["floor_area"], lr["perimeter"], lr["wall_area"], lr["openings_area"], lr["net_wall_area"]) == (120, 44, 440, 53, 387), lr)
    check("C+2.3 measurement logged", "Measured Living: 12 × 10 × 10 ft = 120 sqft floor" in get(V["id"])["activities"][-1]["text"], get(V["id"])["activities"][-1]["text"])
    expect("C+2.3 duplicate room name", call("POST", f"{MB}/rooms", {"name": "living", "length": 5, "width": 5}, T["sales"]), 409)
    k = expect("C+2.3 second room", call("POST", f"{MB}/rooms", {"name": "Kitchen", "length": 10, "width": 8}, T["sales"]), 200)
    check("C+2.3 totals", k["totals"]["floor_area"] == 200)
    kid = next(r["id"] for r in k["rooms"] if r["name"] == "Kitchen")
    ed = expect("C+2.3 edit room", call("PUT", f"{MB}/rooms/{kid}", {"name": "Kitchen", "length": 11, "width": 8}, T["sales"]), 200)
    check("C+2.3 edit logged old -> new", "length 10.0 → 11.0" in get(V["id"])["activities"][-1]["text"], get(V["id"])["activities"][-1]["text"])
    expect("C+2.3 unit cannot change under measured rooms", call("PUT", f"{MB}/measurements/unit", {"unit": "m"}, T["sales"]), 409)
    pl = expect("C+2.3 plot", call("PUT", f"{MB}/plot", {"area": 2400, "frontage": 40, "depth": 60, "floors": 3, "soil": "Red soil", "access": "12 m road"}, T["sales"]), 200)
    check("C+2.3 plot stored and logged", pl["plot"]["area"] == 2400 and "Plot area — → 2400" in get(V["id"])["activities"][-1]["text"])
    expect("C+2.3 delete room", call("DELETE", f"{MB}/rooms/{kid}", token=T["sales"]), 200)
    check("C+2.3 measurements requirement met", "Measurements recorded" not in get(V["id"])["missing"])

    # ================= C+3 lead files =================
    import uuid as _uuid
    boundary = _uuid.uuid4().hex
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"site{RUN}.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {T['sales']}")
    up = json.loads(urllib.request.urlopen(req).read())
    FB = f"/leads/{V['id']}/files"
    expect("C+3 file must be uploaded first", call("POST", FB, {"key": "nope", "folder": "photos"}, T["sales"]), 400)
    expect("C+3 folder from the list", call("POST", FB, {"key": up["key"], "folder": "misc"}, T["sales"]), 400)
    living = me["rooms"][0]["id"]
    fa = expect("C+3 attach a site photo to a room", call("POST", FB, {"key": up["key"], "folder": "photos", "room_id": living, "caption": "Living, north wall"}, T["sales"]), 201)
    check("C+3 file stored with room", fa["room"] == "Living" and fa["folder"] == "photos")
    expect("C+3 same file twice", call("POST", FB, {"key": up["key"], "folder": "photos"}, T["sales"]), 409)
    check("C+3 listed", any(f["id"] == fa["id"] for f in call("GET", FB, token=T["sales"])[1]["files"]))
    check("C+3 file logged", "File added to photos" in get(V["id"])["activities"][-1]["text"])
    expect("C+3 remove", call("DELETE", f"/lead_files/{fa['id']}", token=T["sales"]), 200)
    check("C+3 removed from storage", not mongo.files.find_one({"key": up["key"]}))

    # ================= hand-over of visits when a user leaves =================
    if temp_users:
        hv = expect("visit with the leaving user", call("POST", VB, {"at": soon(40), "staff_ids": [temp_users[0]], "address": "Plot 4"}, T["owner"]), 201)
        r409 = call("PUT", f"/users/{temp_users[0]}", {"active": False}, T["owner"])
        check("deactivation asks who takes the upcoming visit", r409[0] == 409 and "upcoming visit" in r409[1]["error"], r409)
        expect("deactivate with hand-over", call("PUT", f"/users/{temp_users[0]}", {"active": False, "handover_to": U["pm"]}, T["owner"]), 200)
        hv2 = mongo.lead_visits.find_one({"_id": ObjectId(hv["id"])})
        check("visit handed over", [s["id"] for s in hv2["staff"]] == [U["pm"]], hv2["staff"])
    # ================= C+2.2 decision-makers =================
    SB = f"/leads/{V['id']}/stakeholders"
    expect("C+2.2 role from the list", call("POST", SB, {"name": "Asha", "phone": "9000000000", "role": "Uncle"}, T["sales"]), 400)
    expect("C+2.2 name with phone or email", call("POST", SB, {"name": "Asha", "role": "Co-owner"}, T["sales"]), 400)
    expect("C+2.2 the enquirer is not added twice", call("POST", SB, {"contact_id": V["contact_id"], "role": "Co-owner"}, T["sales"]), 409)
    st = expect("C+2.2 add a co-owner (new contact)", call("POST", SB, {"name": f"Spouse {RUN}", "phone": f"7{RUN[-7:]}11", "role": "Co-owner", "main": True}, T["sales"]), 201)
    contacts.append(st[0]["contact_id"])
    st = expect("C+2.2 add the architect", call("POST", SB, {"name": f"Architect {RUN}", "email": f"arch{RUN}@example.test", "role": "Architect", "main": True}, T["sales"]), 201)
    contacts.append(st[1]["contact_id"])
    check("C+2.2 only one main decision-maker", [p["main"] for p in st] == [False, True])
    expect("C+2.2 same person twice", call("POST", SB, {"contact_id": st[0]["contact_id"], "role": "Other"}, T["sales"]), 409)
    ed = expect("C+2.2 change role", call("PUT", f"{SB}/{st[0]['id']}", {"role": "Family member"}, T["sales"]), 200)
    check("C+2.2 role change logged", "role Co-owner → Family member" in get(V["id"])["activities"][-1]["text"])
    check("C+2.2 decision-maker contact cannot be deleted", call("DELETE", f"/contacts/{st[0]['contact_id']}", token=T["owner"])[0] == 409)

    # ================= C+2.2 ballpark =================
    expect("C+2.2 package rates are owner settings", call("PUT", "/leads/package-rates", {"package_rates": {"construction": []}}, T["sales"]), 403)
    expect("C+2.2 package needs a positive rate", call("PUT", "/leads/package-rates", {"package_rates": {"construction": [{"name": "Basic", "rate": 0}]}}, T["owner"]), 400)
    expect("C+2.2 no ballpark without rates", call("POST", f"/leads/{V['id']}/ballpark", {"package": "Basic"}, T["sales"]), 400)
    expect("C+2.2 set package rates", call("PUT", "/leads/package-rates", {"package_rates": {"construction": [
        {"name": "Basic", "rate": 1800, "unit": "sqft"}, {"name": "Premium", "rate": 2400, "unit": "sqft"}, {"name": "Luxury", "rate": 38000, "unit": "sqm"}]}}, T["owner"]), 200)
    expect("C+2.2 needs the lead's area", call("POST", f"/leads/{V['id']}/ballpark", {"package": "Basic"}, T["sales"]), 400)
    call("PUT", f"/leads/{V['id']}", {"area": 2000, "area_unit": "sqft", "budget": 4000000}, T["sales"])
    bp = expect("C+2.2 ballpark", call("POST", f"/leads/{V['id']}/ballpark", {"package": "Premium"}, T["sales"]), 200)
    check("C+2.2 area × rate", bp["amount"] == 4800000 and bp["budget_gap"] == -800000, bp)
    check("C+2.2 budget gap logged", "budget is short by ₹8,00,000" in get(V["id"])["activities"][-1]["text"], get(V["id"])["activities"][-1]["text"])
    bp2 = expect("C+2.2 ballpark in m² rate", call("POST", f"/leads/{V['id']}/ballpark", {"package": "Luxury"}, T["sales"]), 200)
    check("C+2.2 unit converted", abs(bp2["amount"] - round(2000 / 10.7639 * 38000, 2)) < 1, bp2)
    check("C+3 value falls back to the ballpark", get(V["id"])["value"] == bp2["amount"])
    expect("C+2.2 package from the list", call("POST", f"/leads/{V['id']}/ballpark", {"package": "Gold"}, T["sales"]), 400)

    # ================= C+2.4 brief =================
    BB = f"/leads/{V['id']}/brief"
    expect("C+2.4 complete needs the scope", call("PUT", BB, {"style": "Modern", "complete": True}, T["sales"]), 400)
    expect("C+2.4 work type from the list", call("PUT", BB, {"scope": [{"room": "Kitchen", "work_types": ["Magic"]}]}, T["sales"]), 400)
    expect("C+2.4 each room needs work", call("PUT", BB, {"scope": [{"room": "Kitchen", "work_types": []}]}, T["sales"]), 400)
    b1 = expect("C+2.4 brief v1", call("PUT", BB, {"scope": [{"room": "Kitchen", "work_types": ["Modular kitchen", "Electrical"]}], "style": "Modern",
                                                   "materials": "Quartz top", "must_haves": "Tall unit"}, T["sales"]), 200)
    check("C+2.4 version 1", b1["version"] == 1 and not b1["complete"])
    cf = expect("C+2.4 client confirms", call("POST", f"{BB}/confirm", {"how": "whatsapp"}, T["sales"]), 200)
    check("C+2.4 confirmation stored", cf["client_confirmed"]["how"] == "whatsapp" and cf["client_confirmed"]["version"] == 1)
    same = expect("C+2.4 same brief again", call("PUT", BB, {"scope": b1["scope"], "style": "Modern", "materials": "Quartz top", "must_haves": "Tall unit"}, T["sales"]), 200)
    check("C+2.4 no new version without a change", same["version"] == 1)
    b2 = expect("C+2.4 brief v2 complete", call("PUT", BB, {"scope": b1["scope"] + [{"room": "Living", "work_types": ["False ceiling"]}], "style": "Minimal",
                                                            "materials": "Quartz top", "must_haves": "Tall unit", "complete": True}, T["sales"]), 200)
    check("C+2.4 version 2 and confirmation reset", b2["version"] == 2 and b2["client_confirmed"] is None and b2["complete"])
    txt = get(V["id"])["activities"][-1]["text"]
    check("C+2.4 what changed is logged", "Brief v2 saved — changed: Style, Scope" in txt and "confirmation again" in txt and "marked complete" in txt, txt)
    check("C+2.4 estimators told the brief is ready", any(x["event"] == "brief_ready" and x["lead_id"] == V["id"] for x in bell("estimator")))
    br = call("GET", BB, token=T["sales"])[1]
    check("C+2.4 versions kept", [v["version"] for v in br["versions"]] == [1, 2])
    check("C+2.4 brief requirement met", "Brief marked complete" not in get(V["id"])["missing"])

    # ================= C+2.4 client questionnaire (public) =================
    qn = expect("C+2.4 questionnaire link", call("POST", f"/leads/{V['id']}/questionnaire", {}, T["sales"]), 200)
    again = call("POST", f"/leads/{V['id']}/questionnaire", {}, T["sales"])[1]
    check("C+2.4 same open link reused", again["token"] == qn["token"])
    pq = expect("C+2.4 public questions", call("GET", f"/public/questionnaire/{qn['token']}"), 200)
    check("C+2.4 questions for the service", pq["project"] == V["title"] and any(q["id"] == "floors" for q in pq["questions"]) and not pq["submitted"])
    expect("C+2.4 unknown link", call("GET", "/public/questionnaire/nope"), 404)
    expect("C+2.4 needs an answer", call("POST", f"/public/questionnaire/{qn['token']}", {"answers": {}}), 400)
    expect("C+2.4 choice from the options", call("POST", f"/public/questionnaire/{qn['token']}", {"answers": {"finish": "Gold-plated"}}), 400)
    expect("C+2.4 submit answers", call("POST", f"/public/questionnaire/{qn['token']}", {"answers": {"floors": "G+2", "finish": "Premium", "hack": "x"}}), 200)
    expect("C+2.4 answers only once", call("POST", f"/public/questionnaire/{qn['token']}", {"answers": {"floors": "G+3"}}), 409)
    br = call("GET", BB, token=T["sales"])[1]
    check("C+2.4 answers on the lead (unknown questions dropped)", br["questionnaire"]["answers"] == {"floors": "G+2", "finish": "Premium"}, br["questionnaire"])
    check("C+2.4 salesperson told", any(x["event"] == "questionnaire" and x["lead_id"] == V["id"] for x in bell("sales")))
    check("C+2.4 answers logged", "answered the questionnaire" in get(V["id"])["activities"][-1]["text"])

    call("PUT", "/settings/email", {"host": ""}, T["owner"])
finally:
    smtp.shutdown()
    for lid in leads:
        call("DELETE", f"/leads/{lid}", token=T["owner"])
    mongo.followups.delete_many({"company_id": CID, "related.id": {"$in": leads}})
    mongo.notifications.delete_many({"company_id": CID, "$or": [{"lead_id": {"$in": leads}}, {"text": {"$regex": RUN}}]})
    for cid_ in contacts:
        call("DELETE", f"/contacts/{cid_}", token=T["owner"])
    for uid_ in temp_users:
        mongo.users.delete_one({"_id": ObjectId(uid_)})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"sales": company_before.get("sales") or {},
                                                                 "email_settings": company_before.get("email_settings") or {}}})
    left = mongo.leads.count_documents({"company_id": CID, "title": {"$regex": f"Deep {RUN}"}}) + \
        mongo.contacts.count_documents({"company_id": CID, "name": {"$regex": f"Client {RUN}"}}) + \
        mongo.followups.count_documents({"company_id": CID, "title": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)
    cascade = sum(mongo[c].count_documents({"company_id": CID, "lead_id": {"$in": leads}})
                  for c in ("lead_visits", "lead_expenses", "lead_files", "notifications"))
    check("deleting a lead removes its visits, expenses, files and notifications", cascade == 0, cascade)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
