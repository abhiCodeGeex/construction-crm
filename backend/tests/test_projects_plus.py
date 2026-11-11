"""Phase B+ block 1 — project notifications, compliance alerts, forgot / change password, sessions after a
password change, Super Admin two-factor with an authenticator app. Cleans up everything it creates.

    docker compose exec backend python tests/test_projects_plus.py
"""
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import totp  # noqa: E402

BASE = os.getenv("API", "http://localhost:5000/api")
PW, SA_PW = "Demo@123", "Admin@12345"
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


def login(email, pw=PW):
    s, d = call("POST", "/auth/login", {"email": email, "password": pw})
    assert s == 200, (email, s, d)
    return d["token"]


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "designer", "site", "procurement", "sales")}
U = {u["email"].split("@")[0]: u["id"] for u in call("GET", "/users", token=T["owner"])[1] if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"email_settings": 1})
projects, contacts, temp_users = [], [], []


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def proj(pid):
    return call("GET", f"/projects/{pid}", token=T["owner"])[1]


# a tiny SMTP server so the reset email is tested for real (the backend runs in this container)
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
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 2527), SMTPHandler)
threading.Thread(target=smtp.serve_forever, daemon=True).start()


def wait_mail(fragment, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        hit = [m for m in mails if fragment in m]
        if hit:
            return hit[-1]
        time.sleep(0.2)
    return None


SA_FIELDS = ("totp_secret", "totp_pending", "totp_last_step", "login_fails", "locked_until", "totp_enrolled_at")
sa_before = {u["email"]: {k: u.get(k) for k in SA_FIELDS} for u in mongo.superadmin_users.find({})}

try:
    # =============== 1. who is told about project changes ===============
    p = expect("project created", call("POST", "/projects", {"name": f"Plus {RUN}", "services": ["construction"],
                                                             "start": day(0)}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    check("creator is the Project Manager", any(m.get("user_id") == U["owner"] and m["project_role"] == "Project Manager"
                                                for m in p["team"]))
    expect("add PM to the team", call("POST", f"/projects/{pid}/team", {"user_id": U["pm"], "project_role": "Project Manager",
                                                                       "access": "edit"}, T["owner"]), 201)
    n = bell("pm", event="project_added", project_id=pid)
    check("added to a project: told, with role and access", len(n) == 1 and "as Project Manager (edit access)" in n[0]["text"]
          and n[0]["link"] == f"/app/projects/{pid}", n)
    call("POST", f"/projects/{pid}/team", {"user_id": U["designer"], "project_role": "Architect", "access": "view"}, T["owner"])
    call("POST", f"/projects/{pid}/team", {"user_id": U["site"], "project_role": "Site Supervisor", "access": "view"}, T["owner"])
    check("designer told too", len(bell("designer", event="project_added", project_id=pid)) == 1)
    check("nobody is told about their own action", not bell("owner", event="project_added", project_id=pid))

    st = p["stages"][0]
    r = expect("task assigned", call("POST", f"/projects/{pid}/stages/{st['id']}/tasks",
                                     {"title": f"Footing {RUN}", "start": day(0), "end": day(3), "assignee_id": U["designer"]},
                                     T["owner"]), 201)
    task = next(tk for s in r["stages"] for tk in s["tasks"] if tk["title"] == f"Footing {RUN}")
    n = bell("designer", event="task_assigned", project_id=pid)
    check("task assigned: assignee told with stage, project and dates", len(n) == 1 and st["name"] in n[0]["text"]
          and f"Plus {RUN}" in n[0]["text"] and day(3) in n[0]["text"], n)
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"title": f"Footing {RUN} B"}, T["owner"])
    check("editing a task (same assignee) does not re-notify", len(bell("designer", event="task_assigned", project_id=pid)) == 1)
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"assignee_id": U["site"]}, T["owner"])
    check("reassigned: the new assignee is told", len(bell("site", event="task_assigned", project_id=pid)) == 1)
    check("reassigned: the old one not again", len(bell("designer", event="task_assigned", project_id=pid)) == 1)

    expect("assignee marks it blocked", call("PUT", f"/projects/{pid}/tasks/{task['id']}",
                                             {"status": "blocked", "notes": "Waiting for steel"}, T["site"]), 200)
    n = bell("pm", event="task_blocked", project_id=pid)
    check("blocked: project managers told, with the reason", len(n) == 1 and "Waiting for steel" in n[0]["text"], n)
    check("blocked: every PM on the team (owner is PM too)", len(bell("owner", event="task_blocked", project_id=pid)) == 1)
    check("blocked: not the person who did it", not bell("site", event="task_blocked", project_id=pid))
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "todo"}, T["site"])
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "blocked"}, T["site"])
    check("blocked again later: told again", len(bell("pm", event="task_blocked", project_id=pid)) == 2)

    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"status": "done"}, T["site"])
    n = bell("pm", event="stage_done", project_id=pid)
    check("stage complete when its last task is done: managers told", len(n) == 1 and st["name"] in n[0]["text"], n)
    call("PUT", f"/projects/{pid}/tasks/{task['id']}", {"progress": 100}, T["site"])
    check("stage complete told only once", len(bell("pm", event="stage_done", project_id=pid)) == 1)

    ms = st["milestones"][0]
    for c in st["checklist"]:  # B+2: the stage closes once its closing checklist is ticked
        call("PUT", f"/projects/{pid}/stages/{st['id']}/checklist/{c['id']}", {"done": True}, T["owner"])
    expect("milestone achieved", call("PUT", f"/projects/{pid}/milestones/{ms['id']}", {"status": "achieved"}, T["owner"]), 200)
    check("milestone achieved: managers told", len(bell("pm", event="milestone_achieved", project_id=pid)) == 1)

    expect("high issue raised", call("POST", f"/projects/{pid}/issues", {"title": f"Crack {RUN}", "severity": "high",
                                                                         "owner_id": U["designer"]}, T["site"]), 201)
    check("high issue: owner of the issue told", len(bell("designer", event="issue_raised", project_id=pid)) == 1)
    check("high issue: project managers told", len(bell("pm", event="issue_raised", project_id=pid)) == 1)
    call("POST", f"/projects/{pid}/issues", {"title": f"Paint {RUN}", "severity": "low", "owner_id": U["designer"]}, T["site"])
    check("low issue: only its owner", len(bell("designer", event="issue_raised", project_id=pid)) == 2
          and len(bell("pm", event="issue_raised", project_id=pid)) == 1)

    # =============== 2. scheduled reminders (worker) ===============
    st2 = p["stages"][1]
    r = call("POST", f"/projects/{pid}/stages/{st2['id']}/tasks", {"title": f"Due {RUN}", "start": day(0), "end": day(1),
                                                                    "assignee_id": U["designer"]}, T["owner"])[1]
    due_task = next(tk for s in r["stages"] for tk in s["tasks"] if tk["title"] == f"Due {RUN}")
    r = call("POST", f"/projects/{pid}/stages/{st2['id']}/tasks", {"title": f"Late {RUN}", "start": day(-8), "end": day(-4),
                                                                    "assignee_id": U["site"]}, T["owner"])[1]
    late_task = next(tk for s in r["stages"] for tk in s["tasks"] if tk["title"] == f"Late {RUN}")
    ms2 = st2["milestones"][0]
    call("PUT", f"/projects/{pid}/milestones/{ms2['id']}", {"due": day(-2)}, T["owner"])
    worker()
    check("due tomorrow: assignee reminded", len(bell("designer", event="task_due", project_id=pid)) == 1)
    n = bell("site", event="task_overdue", project_id=pid)
    check("overdue: assignee told how late", len(n) == 1 and "4 day(s)" in n[0]["text"], n)
    esc = [x for x in bell("pm", event="task_overdue", project_id=pid) if "days overdue" in x["text"]]
    check("overdue 3+ days: managers told, with who it is", len(esc) == 1 and "Site" in esc[0]["text"], esc)
    n = bell("pm", event="milestone_late", project_id=pid)
    check("milestone late: managers told", len(n) == 1 and "2 day(s) late" in n[0]["text"], n)
    worker()
    check("running again sends nothing twice", len(bell("designer", event="task_due", project_id=pid)) == 1
          and len(bell("site", event="task_overdue", project_id=pid)) == 1 and len(bell("pm", event="milestone_late", project_id=pid)) == 1)
    call("PUT", f"/projects/{pid}/tasks/{late_task['id']}", {"end": day(-1)}, T["owner"])
    worker()
    check("rescheduled task: reminded again for the new date", len(bell("site", event="task_overdue", project_id=pid)) == 2)
    call("PUT", f"/projects/{pid}/tasks/{due_task['id']}", {"status": "done"}, T["designer"])
    worker(datetime.utcnow() + timedelta(days=3))
    check("done tasks are never chased", not [x for x in bell("designer", event="task_overdue", project_id=pid)
                                               if f"Due {RUN}" in x["text"]])
    # preferences: a normal reminder can be switched off, a critical one cannot
    pr = call("GET", "/notifications/prefs", token=T["designer"])[1]
    groups = {e["event"]: e["group"] for e in pr["events"]}
    check("settings list project events under Projects", groups.get("task_assigned") == "Projects"
          and groups.get("milestone_late") == "Projects" and groups.get("compliance_expired") == "Contacts"
          and groups.get("lead_assigned") == "Leads & sales", groups)
    order = [e["group"] for e in pr["events"]]
    check("settings grouped in order (each heading once)", order == sorted(order, key=["Leads & sales", "Projects", "Finance", "Procurement", "Documents & site", "Contacts"].index))
    rows = [{**e, "in_app": False} if e["event"] in ("task_due", "task_assigned") else e for e in pr["events"]]
    call("PUT", "/notifications/prefs", {"events": rows}, T["designer"])
    r = call("POST", f"/projects/{pid}/stages/{st2['id']}/tasks", {"title": f"Pref {RUN}", "start": day(0), "end": day(1),
                                                                    "assignee_id": U["designer"]}, T["owner"])[1]
    check("critical (task assigned) still arrives when switched off",
          any(f"Pref {RUN}" in x["text"] for x in bell("designer", event="task_assigned", project_id=pid)))
    worker()
    check("switched-off reminder (due tomorrow) not sent",
          not any(f"Pref {RUN}" in x["text"] for x in bell("designer", event="task_due", project_id=pid)))
    call("PUT", "/notifications/prefs", {"events": [{**e, "in_app": True, "email": True} for e in pr["events"]]}, T["designer"])
    # projects that are not running get no reminders
    p2 = call("POST", "/projects", {"name": f"Plus {RUN} hold", "services": ["construction"], "start": day(-10)}, T["owner"])[1]
    projects.append(p2["id"])
    call("POST", f"/projects/{p2['id']}/stages/{p2['stages'][0]['id']}/tasks",
         {"title": f"Hold {RUN}", "start": day(-9), "end": day(-5), "assignee_id": U["owner"]}, T["owner"])
    call("PUT", f"/projects/{p2['id']}", {"status": "on_hold"}, T["owner"])
    worker()
    check("on-hold project: no reminders", not mongo.notifications.count_documents({"company_id": CID, "project_id": p2["id"],
                                                                                   "event": {"$in": ["task_overdue", "milestone_late"]}}))

    # =============== 3. compliance expiry ===============
    c = expect("vendor with documents", call("POST", "/contacts", {"name": f"Vendor {RUN}", "kind": "company", "types": ["supplier"],
                                                                    "compliance": [
        {"type": "insurance", "name": "Insurance A", "expiry": day(20)},
        {"type": "licence", "name": "Licence B", "expiry": day(5)},
        {"type": "certificate", "name": "Cert C", "expiry": day(-2)},
        {"type": "other", "name": "Valid D", "expiry": day(100)},
        {"type": "other", "name": "Forever E"}]}, T["owner"]), 201)
    contacts.append(c["id"])
    worker()
    mine = lambda u: [x for x in bell(u) if x["event"].startswith("compliance") and f"Vendor {RUN}" in x["text"]]
    texts = " | ".join(x["text"] for x in mine("owner"))
    check("30-day warning", "Insurance A" in texts and "in 20 day(s)" in texts, texts)
    check("7-day warning", "Licence B" in texts and "in 5 day(s)" in texts, texts)
    check("expired alert", any(x["event"] == "compliance_expired" and "Cert C" in x["text"] for x in mine("owner")), texts)
    check("valid / no-expiry documents: nothing", "Valid D" not in texts and "Forever E" not in texts, texts)
    check("Procurement told too", len(mine("procurement")) == 3, len(mine("procurement")))
    check("others not told", not mine("sales"))
    check("links to the contact", all(x["link"] == f"/app/contacts/{c['id']}" for x in mine("owner")))
    worker()
    check("no duplicates on the next run", len(mine("owner")) == 3)
    worker(datetime.utcnow() + timedelta(days=15))
    check("same document, now inside 7 days: warned again", len([x for x in mine("owner") if "Insurance A" in x["text"]]) == 2)
    docs = call("GET", f"/contacts/{c['id']}", token=T["owner"])[1]["compliance"]
    renewed = [{**d_, "expiry": day(400)} if d_["name"] == "Cert C" else d_ for d_ in docs]
    call("PUT", f"/contacts/{c['id']}", {"compliance": renewed}, T["owner"])
    worker()
    check("renewed document: no more alerts", len([x for x in mine("owner") if "Cert C" in x["text"]]) == 1)

    # =============== 4. forgot password ===============
    temp = expect("temp staff user", call("POST", "/users", {"name": f"Temp {RUN}", "email": f"temp{RUN}@skyline.test",
                                                             "role": "sales", "password": "First@1"}, T["owner"]), 201)
    temp_users.append(temp["id"])
    temp_email = f"temp{RUN}@skyline.test"
    old_token = login(temp_email, "First@1")
    r = expect("forgot: email not set up yet", call("POST", "/auth/forgot", {"email": temp_email}), 200)
    check("forgot: no link made without email", mongo.password_resets.count_documents({"user_id": temp["id"]}) == 0)
    check("forgot: the answer says what to do", "ask your company Owner" in r["message"])
    expect("forgot: email required", call("POST", "/auth/forgot", {"email": ""}), 400)
    call("PUT", "/settings/email", {"host": "127.0.0.1", "port": 2527, "from_address": "crm@skyline.test", "use_tls": False,
                                    "app_url": "http://crm.test"}, T["owner"])
    r1 = call("POST", "/auth/forgot", {"email": "nobody-" + RUN + "@skyline.test"})
    r2 = call("POST", "/auth/forgot", {"email": temp_email.upper()})
    check("same answer whether or not the account exists", r1 == r2 and r1[0] == 200, (r1, r2))
    mail = wait_mail(f"Temp {RUN}")
    check("reset email sent", mail is not None and "Reset your BuildSuite password" in mail, len(mails))
    m = re.search(r"/reset/([A-Za-z0-9_\-]+)", mail or "")
    token = m.group(1) if m else ""
    check("link uses the company's app address", "http://crm.test/reset/" in (mail or ""))
    check("only a hash of the link is stored", token and not mongo.password_resets.find_one({"token_hash": token})
          and mongo.password_resets.find_one({"user_id": temp["id"]}))
    ck = expect("link check", call("GET", f"/auth/reset/{token}"), 200)
    check("link check shows a masked email", ck["email"].startswith("te") and "•" in ck["email"] and ck["email"].endswith("@skyline.test"), ck)
    expect("wrong link refused", call("GET", "/auth/reset/not-a-real-token"), 410)
    expect("short password refused", call("POST", f"/auth/reset/{token}", {"password": "abc"}), 400)
    expect("new password saved", call("POST", f"/auth/reset/{token}", {"password": "Second@2"}), 200)
    s, d = call("GET", "/auth/me", token=old_token)
    check("session from before the reset is signed out", s == 401 and "password was changed" in d.get("error", ""), (s, d))
    check("old password no longer works", call("POST", "/auth/login", {"email": temp_email, "password": "First@1"})[0] == 401)
    new_token = login(temp_email, "Second@2")
    check("new password works", call("GET", "/auth/me", token=new_token)[0] == 200)
    expect("link works only once", call("POST", f"/auth/reset/{token}", {"password": "Third@3"}), 410)
    for _ in range(2):
        call("POST", "/auth/forgot", {"email": temp_email})
    time.sleep(1)
    count = len([x for x in mails if f"Temp {RUN}" in x])
    call("POST", "/auth/forgot", {"email": temp_email})  # 4th in the hour
    time.sleep(1.5)
    check("at most 3 links per hour", len([x for x in mails if f"Temp {RUN}" in x]) == count == 3, count)
    mongo.password_resets.delete_many({"user_id": temp["id"]})
    call("POST", "/auth/forgot", {"email": temp_email})
    rd = mongo.password_resets.find_one({"user_id": temp["id"]})
    mongo.password_resets.insert_one({"token_hash": "x" * 64, "user_id": temp["id"], "company_id": CID, "created_at": datetime.utcnow(),
                                      "used_at": None, "expires_at": datetime.utcnow() - timedelta(minutes=1)})
    from app.routes.auth import _hash
    mongo.password_resets.update_one({"token_hash": "x" * 64}, {"$set": {"token_hash": _hash("expired-" + RUN)}})
    expect("expired link refused", call("GET", f"/auth/reset/expired-{RUN}"), 410)
    check("audit: reset recorded", mongo.audit_logs.find_one({"company_id": CID, "doc_id": temp["id"], "action": "password_reset"}))
    call("PUT", f"/users/{temp['id']}", {"active": False}, T["owner"])
    mongo.password_resets.delete_many({"user_id": temp["id"]})
    call("POST", "/auth/forgot", {"email": temp_email})
    time.sleep(0.5)
    check("deactivated user: no link", mongo.password_resets.count_documents({"user_id": temp["id"]}) == 0)
    call("PUT", f"/users/{temp['id']}", {"active": True}, T["owner"])

    # =============== 5. change my own password, owner reset, audit ===============
    tok = login(temp_email, "Second@2")
    expect("change: wrong current", call("POST", "/auth/password", {"current": "nope", "new": "Fourth@4"}, tok), 400)
    expect("change: too short", call("POST", "/auth/password", {"current": "Second@2", "new": "abc"}, tok), 400)
    expect("change: same as before", call("POST", "/auth/password", {"current": "Second@2", "new": "Second@2"}, tok), 400)
    other_device = login(temp_email, "Second@2")
    time.sleep(1.1)  # sessions are compared by the second
    ch = expect("change own password", call("POST", "/auth/password", {"current": "Second@2", "new": "Fourth@4"}, tok), 200)
    check("change returns a new session", ch.get("token") and ch["token"] != tok and ch["user"]["email"] == temp_email)
    check("this device carries on", call("GET", "/auth/me", token=ch["token"])[0] == 200)
    check("other devices signed out", call("GET", "/auth/me", token=other_device)[0] == 401)
    time.sleep(1.1)
    expect("owner resets the password", call("PUT", f"/users/{temp['id']}", {"password": "Fifth@5"}, T["owner"]), 200)
    check("after an owner reset the user is signed out", call("GET", "/auth/me", token=ch["token"])[0] == 401)
    login(temp_email, "Fifth@5")
    rows = list(mongo.audit_logs.find({"company_id": CID, "doc_id": temp["id"], "changes.password": {"$exists": True}}))
    check("audit never stores the password hash", rows and all(r_["changes"]["password"]["to"] == "••• (changed)" for r_ in rows), rows[:1])
    check("no audit row anywhere holds a hash", mongo.audit_logs.count_documents({"changes.password.to": {"$regex": r"^\$2"}}) == 0)

    # =============== 6. Super Admin two-factor ===============
    for e in sa_before:  # start every account un-enrolled; restored at the end
        mongo.superadmin_users.update_one({"email": e}, {"$set": {k: None for k in SA_FIELDS}})
    sa = "superadmin@buildsuite.test"
    expect("wrong password", call("POST", "/sa/login", {"email": sa, "password": "nope"}), 401)
    mongo.superadmin_users.update_one({"email": sa}, {"$set": {"login_fails": 0}})
    s1 = expect("first sign-in: set-up step", call("POST", "/sa/login", {"email": sa, "password": SA_PW}), 200)
    check("set-up gives a secret and a QR link", s1.get("two_factor_setup") and len(s1.get("secret", "")) >= 32
          and s1["otpauth"].startswith("otpauth://totp/BuildSuite") and f"secret={s1['secret']}" in s1["otpauth"], s1)
    s1b = call("POST", "/sa/login", {"email": sa, "password": SA_PW})[1]
    check("same secret until confirmed (QR stays valid)", s1b.get("secret") == s1["secret"])
    w = expect("wrong code during set-up", call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": "000000"}), 401)
    check("says how many attempts are left", "4 attempts left" in w.get("error", ""), w)
    code = totp.now_code(s1["secret"])
    ok = expect("code from the app confirms set-up", call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": code}), 200)
    check("signed in with a token, no secret returned", ok.get("token") and "totp_secret" not in ok["user"]
          and "totp_pending" not in ok["user"], ok.get("user"))
    u = mongo.superadmin_users.find_one({"email": sa})
    check("enrolled; pending cleared; failures reset", u["totp_secret"] == s1["secret"] and not u.get("totp_pending")
          and u["login_fails"] == 0)
    check("set-up recorded in the platform audit", mongo.sa_audit.find_one({"by": u["name"], "action": "two_factor_set_up"}))
    s2 = call("POST", "/sa/login", {"email": sa, "password": SA_PW})[1]
    check("next sign-in asks for the code only (no secret again)", s2 == {"two_factor_required": True}, s2)
    expect("the same code cannot be used twice", call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": code}), 401)
    nxt = totp.code_at(s1["secret"], totp.current_step() + 1)
    sat = expect("a fresh code works", call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": nxt}), 200)["token"]
    check("old demo code is gone", call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": "123456"})[0] == 401)
    me = call("GET", "/sa/me", token=sat)[1]
    check("/sa/me never shows the secret", "totp_secret" not in me["user"] and "totp_last_step" not in me["user"])
    team = call("GET", "/sa/team", token=sat)[1]
    check("team list: no secrets, two-factor status shown", all("totp_secret" not in x and "password" not in x for x in team)
          and next(x for x in team if x["email"] == sa)["two_factor"] == "on"
          and next(x for x in team if x["email"] == "sa-billing@buildsuite.test")["two_factor"] == "not set up")
    # lock after 5 wrong attempts
    mongo.superadmin_users.update_one({"email": sa}, {"$set": {"login_fails": 0}})
    for _ in range(4):
        call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": "111111"})
    l5 = call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": "111111"})
    check("5th wrong attempt locks the account", l5[0] == 401 and "locked for 15 minutes" in l5[1].get("error", ""), l5)
    lk = call("POST", "/sa/login", {"email": sa, "password": SA_PW, "code": totp.code_at(s1["secret"], totp.current_step() + 1)})
    check("locked: even the right code is refused", lk[0] == 423 and "Try again in" in lk[1].get("error", ""), lk)
    check("lock recorded", mongo.sa_audit.find_one({"by": u["name"], "action": "locked"}))
    mongo.superadmin_users.update_one({"email": sa}, {"$set": {"locked_until": None, "login_fails": 0}})
    # add a member, they set up at first sign-in; owner can reset it
    mail_ = f"sa-{RUN}@buildsuite.test"
    nm = expect("add a Super Admin member", call("POST", "/sa/team", {"name": f"SA {RUN}", "email": mail_, "role": "viewer",
                                                                     "password": "Member@123"}, sat), 201)
    check("new member: no password or secret returned", "password" not in nm and nm["two_factor"] == "not set up", nm)
    m1 = call("POST", "/sa/login", {"email": mail_, "password": "Member@123"})[1]
    check("new member sets up at first sign-in", m1.get("two_factor_setup"))
    mt = expect("member enrolled", call("POST", "/sa/login", {"email": mail_, "password": "Member@123",
                                                              "code": totp.now_code(m1["secret"])}), 200)["token"]
    expect("viewer cannot reset anyone's two-factor", call("PUT", f"/sa/team/{nm['id']}", {"reset_two_factor": True}, mt), 403)
    expect("owner cannot change own access", call("PUT", f"/sa/team/{ok['user']['id']}", {"reset_two_factor": True}, sat), 409)
    expect("owner resets the member's two-factor", call("PUT", f"/sa/team/{nm['id']}", {"reset_two_factor": True}, sat), 200)
    m2 = call("POST", "/sa/login", {"email": mail_, "password": "Member@123"})[1]
    check("after a reset: set up again with a new secret", m2.get("two_factor_setup") and m2["secret"] != m1["secret"])
    expect("nothing to change refused", call("PUT", f"/sa/team/{nm['id']}", {}, sat), 400)
    expect("unknown member", call("PUT", f"/sa/team/{'0' * 24}", {"active": False}, sat), 404)
    mongo.superadmin_users.delete_one({"email": mail_})

    # =============== 7. clean-up of project notifications ===============
    call("DELETE", f"/projects/{pid}", token=T["owner"])
    projects.remove(pid)
    check("deleting a project removes its notifications",
          mongo.notifications.count_documents({"company_id": CID, "project_id": pid}) == 0)
finally:
    for p_ in projects:
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for c_ in contacts:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    for u_ in temp_users:
        mongo.users.delete_one({"_id": ObjectId(u_)})
        mongo.password_resets.delete_many({"user_id": u_})
        mongo.notifications.delete_many({"user_id": u_})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"email_settings": company_before.get("email_settings") or {}}})
    for e, vals in sa_before.items():
        mongo.superadmin_users.update_one({"email": e}, {"$set": vals})
    mongo.superadmin_users.delete_many({"email": {"$regex": f"sa-{RUN}"}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": f"Plus {RUN}"}}) + \
        mongo.contacts.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.notifications.count_documents({"company_id": CID, "text": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)
    smtp.shutdown()

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
