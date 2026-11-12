"""Phase J — the rest of the MVP. One section per block of PLAN.md Phase J. Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_j.py
"""
import hashlib
import hmac
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
APP = f"secret{RUN}"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw or b"{}") if raw[:1] in (b"{", b"[") or not raw else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def raw_post(path, raw, headers):
    req = urllib.request.Request(BASE + path, method="POST", data=raw)
    for k_, v_ in headers.items():
        req.add_header(k_, v_)
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


def expect(name, res, status=200):
    check(name, res[0] == status, f"got {res[0]} {res[1].get('error', '') if isinstance(res[1], dict) else ''}")
    return res[1]


def login(email):
    s, d = call("POST", "/auth/login", {"email": email, "password": PW})
    assert s == 200, (email, s, d)
    return d["token"]


def upload(name, token):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + b"\x89PNG\r\n\x1a\n" + b"0" * 64 + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body)
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


def wh(body, secret=APP):
    raw = json.dumps(body).encode()
    return raw_post(f"/webhooks/messages/{CID}", raw, {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
                                                       "Content-Type": "application/json"})


def inbound(phone, **msg):
    return wh({"entry": [{"changes": [{"value": {"messages": [{"from": phone, "id": f"wamid.in{uuid.uuid4().hex[:12]}", **msg}]}}]}]})


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement")}
T["client"] = login("client@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"messaging": 1, "field": 1, "field_runs": 1, "inbound_email": 1})
client_before = mongo.contacts.find_one({"_id": ObjectId(CLIENT_CONTACT)}, {"phone": 1, "email": 1, "whatsapp_opt_in": 1, "whatsapp_opt_out": 1})
projects, keys, workers_made, signups = [], [], [], []
sa_before = mongo.platform_settings.find_one({"_id": "settings"})
users_before = {u["_id"]: u.get("phone") for u in mongo.users.find({"_id": {"$in": [ObjectId(U["pm"]), ObjectId(U["site"])]}})}

try:
    # ---------------- a project with a team, rooms, tasks and drawings ----------------
    expect("WhatsApp sandbox on", call("PUT", "/settings/messaging", {"provider": "sandbox", "app_secret": APP}, T["owner"]))
    p = expect("project", call("POST", "/projects", {"name": f"PhaseJ {RUN}", "services": ["interior"], "start": day(-10),
                                                     "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    PID = p["id"]
    projects.append(PID)
    for who, role in (("pm", "Project Manager"), ("site", "Site Supervisor"), ("designer", "Interior Designer"), ("procurement", "Procurement")):
        call("POST", f"/projects/{PID}/team", {"user_id": U[who], "project_role": role, "access": "edit" if who != "procurement" else "view"}, T["owner"])
    mongo.users.update_one({"_id": ObjectId(U["site"])}, {"$set": {"phone": "9811100011"}})
    p = call("GET", f"/projects/{PID}", token=T["owner"])[1]
    S0 = p["stages"][0]["id"]

    def add_task(title, start, end, **kw):
        r = expect(f"task {title}", call("POST", f"/projects/{PID}/stages/{S0}/tasks", {"title": title, "start": start, "end": end, **kw}, T["owner"]), 201)
        return next(tk for s in r["stages"] for tk in s["tasks"] if tk["title"] == title)["id"]

    T1 = add_task(f"Kitchen plumbing {RUN}", day(-1), day(1))
    T2 = add_task(f"Kitchen tiling {RUN}", day(0), day(3))
    T3 = add_task(f"Kitchen painting {RUN}", day(2), day(5))
    T4 = add_task(f"Late wiring {RUN}", day(-5), day(-2))
    k_dwg = upload("kitchen.png", T["designer"])
    dwg = expect("kitchen drawing", call("POST", f"/projects/{PID}/documents", {"folder": "Layouts", "name": f"Kitchen layout {RUN}", "kind": "drawing",
                                                                                "number": f"K-{RUN[-3:]}", "file_key": k_dwg, "room": "Kitchen"}, T["designer"]), 201)

    # ======================================= block 1 =======================================
    w1 = expect("J1.1 worker with language", call("POST", "/site-workers", {"name": f"Ramesh {RUN}", "phone": f"96{RUN}", "trade": "Plumbing",
                                                                           "language": "hi"}, T["site"]), 201)
    w2 = expect("J1.1 second worker", call("POST", "/site-workers", {"name": f"Suresh {RUN}", "phone": f"95{RUN}", "trade": "Tiling"}, T["site"]), 201)
    w3 = expect("J1.1 painter", call("POST", "/site-workers", {"name": f"Mahesh {RUN}", "phone": f"94{RUN}", "trade": "Painting"}, T["site"]), 201)
    workers_made += [w1["id"], w2["id"], w3["id"]]
    expect("J1.1 bad language", call("PUT", f"/site-workers/{w1['id']}", {"language": "fr"}, T["site"]), 400)
    nophone = expect("J1.1 worker without phone", call("POST", "/site-workers", {"name": f"Nophone {RUN}"}, T["site"]), 201)
    workers_made.append(nophone["id"])
    expect("J1.1 WhatsApp needs a mobile", call("PUT", f"/site-workers/{nophone['id']}", {"whatsapp": True}, T["site"]), 400)
    for w in (w1, w2, w3):
        r = expect("J1.1 worker opts in", call("PUT", f"/site-workers/{w['id']}", {"whatsapp": True}, T["site"]))
    check("J1.1 opt-in recorded", r.get("whatsapp_opt_in") and r["whatsapp_opt_in"]["by"], r)
    check("J1.1 workers are not users (not counted)", mongo.users.count_documents({"company_id": CID, "name": {"$regex": RUN}}) == 0)
    # job cards
    jc = expect("J1.2 job card made on first open", call("GET", f"/projects/{PID}/tasks/{T1}/job", token=T["site"]))
    check("J1.2 card has a public link and the supervisor", jc["token"] and "/j/" in jc["link"] and jc["supervisor"]["name"], jc)
    expect("J1.2 unknown worker", call("PUT", f"/projects/{PID}/tasks/{T1}/job", {"worker_ids": [str(ObjectId())]}, T["site"]), 400)
    expect("J1.2 drawing of another project", call("PUT", f"/projects/{PID}/tasks/{T1}/job", {"document_ids": [str(ObjectId())]}, T["site"]), 400)
    k_ph = upload("ref.png", T["site"])
    jc = expect("J1.2 fill the job card", call("PUT", f"/projects/{PID}/tasks/{T1}/job", {
        "room": "Kitchen", "trade": "Plumbing", "worker_ids": [w1["id"]], "document_ids": [dwg["id"]], "photos": [k_ph],
        "measurements": [{"label": "Sink height", "value": "850 mm"}, {"label": "", "value": "dropped"}], "instructions": "Use CPVC"}, T["site"]))
    check("J1.2 card saved", jc["room"] == "Kitchen" and jc["workers"][0]["name"] == w1["name"] and len(jc["drawings"]) == 1
          and jc["measurements"] == [{"label": "Sink height", "value": "850 mm"}] and len(jc["photos"]) == 1, jc)
    expect("J1.2 sales (not on the project) cannot fill", call("PUT", f"/projects/{PID}/tasks/{T1}/job", {"room": "x"}, T["sales"]), 404)
    call("PUT", f"/projects/{PID}/tasks/{T2}/job", {"room": "Kitchen", "trade": "Tiling", "worker_ids": [w2["id"]]}, T["site"])
    call("PUT", f"/projects/{PID}/tasks/{T3}/job", {"room": "Kitchen", "trade": "Painting", "worker_ids": [w3["id"]]}, T["site"])
    pub = expect("J1.3 public job card (no sign-in)", call("GET", f"/public/job/{jc['token']}"))
    check("J1.3 public card shows drawing, measurements, supervisor", pub["task"].startswith("Kitchen plumbing") and pub["drawings"][0]["url"].startswith(f"/api/public/f/{jc['token']}/")
          and pub["measurements"] and pub["company"], pub)
    st_, body_ = call("GET", pub["drawings"][0]["url"][4:])
    check("J1.3 the drawing opens from the public link", st_ == 200, st_)
    expect("J1.3 a file not on the card is refused", call("GET", f"/public/f/{jc['token']}/{CID}_nothere.png"), 404)
    expect("J1.3 bad token", call("GET", "/public/job/nope"), 404)
    # morning message
    prev = expect("J1.4 preview today's messages", call("GET", "/worker-messages/preview", token=T["site"]))
    mine = {x["worker"]: x for x in prev if RUN in x["worker"]}
    check("J1.4 workers with work today", set(mine) == {w1["name"], w2["name"]}, list(mine))
    check("J1.4 Hindi for Ramesh, with job card and supervisor", "सुप्रभात" in mine[w1["name"]]["text"] and "/j/" in mine[w1["name"]]["text"]
          and "सुपरवाइज़र" in mine[w1["name"]]["text"] and "9811100011" in mine[w1["name"]]["text"], mine[w1["name"]]["text"])
    check("J1.4 English for Suresh", mine[w2["name"]]["text"].startswith("Good morning") and "Kitchen: Kitchen tiling" in mine[w2["name"]]["text"], mine[w2["name"]]["text"])
    expect("J1.4 sales cannot preview", call("GET", "/worker-messages/preview", token=T["sales"]), 403)
    fs = expect("J1.5 settings", call("PUT", "/settings/field", {"morning_on": True, "morning_time": "00:00", "utc_offset": 330}, T["owner"]))
    check("J1.5 saved", fs["morning_on"] and fs["morning_time"] == "00:00", fs)
    expect("J1.5 bad time", call("PUT", "/settings/field", {"morning_time": "7am"}, T["owner"]), 400)
    expect("J1.5 PM cannot change settings", call("PUT", "/settings/field", {"morning_on": False}, T["pm"]), 403)
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"field_runs": ""}})
    worker()
    sent = list(mongo.messages.find({"company_id": CID, "kind": "worker_morning", "worker_id": {"$in": [w1["id"], w2["id"], w3["id"]]}}))
    check("J1.5 the worker sends the morning message", {m["worker_id"] for m in sent} == {w1["id"], w2["id"]} and all(m["status"] == "sent" for m in sent), [(m["worker_id"], m["status"]) for m in sent])
    check("J1.5 with the three buttons", all(m["buttons"] == ["material", "done", "help"] for m in sent), [m.get("buttons") for m in sent])
    check("J1.5 carries the tasks for the replies", any(m["task_ids"] == [T1] for m in sent), [m.get("task_ids") for m in sent])
    worker()
    check("J1.5 once a day", mongo.messages.count_documents({"company_id": CID, "kind": "worker_morning", "worker_id": {"$in": [w1["id"], w2["id"]]}}) == 2)
    js = expect("J1.6 send the job card now", call("POST", f"/projects/{PID}/tasks/{T1}/job/send", {}, T["site"]))
    check("J1.6 sent", js[0]["status"] == "sent", js)

    # ======================================= block 2 =======================================
    PH1, PH2 = f"9196{RUN}", f"9195{RUN}"
    expect("J2.1 bad signature", wh({"entry": []}, "wrong"), 400)
    expect("J2.1 button: material needed", inbound(PH1, type="interactive", interactive={"type": "button_reply", "button_reply": {"id": "material", "title": "x"}}))
    fu = mongo.field_updates.find_one({"company_id": CID, "worker_id": w1["id"]}, sort=[("created_at", -1)])
    check("J2.1 waits for the detail", fu and fu["kind"] == "material" and fu["status"] == "awaiting" and fu["task_id"] == T1, fu)
    ask = mongo.messages.find_one({"company_id": CID, "worker_id": w1["id"], "kind": "worker_reply"}, sort=[("created_at", -1)])
    check("J2.1 asks what is needed, in Hindi", ask and "कौन सी सामग्री" in ask["text"], ask and ask["text"])
    expect("J2.1 the detail", inbound(PH1, type="text", text={"body": "20 bags cement"}))
    fu = mongo.field_updates.find_one({"_id": fu["_id"]})
    pr = mongo.purchase_requests.find_one({"company_id": CID, "project_id": PID, "source": "whatsapp"})
    check("J2.1 became a purchase request", fu["status"] == "open" and fu["pr_id"] and pr and "20 bags cement" in pr["lines"][0]["description"], (fu, pr and pr["lines"]))
    check("J2.1 procurement told", mongo.notifications.find_one({"company_id": CID, "user_id": U["procurement"], "event": {"$in": ["pr_raised", "field_update"]},
                                                                 "text": {"$regex": "cement"}}) is not None)
    check("J2.1 the worker gets the PR number", mongo.messages.find_one({"company_id": CID, "worker_id": w1["id"], "kind": "worker_reply", "text": {"$regex": pr["number"]}}) is not None)
    # voice note for help
    expect("J2.2 help button", inbound(PH2, type="interactive", interactive={"type": "button_reply", "button_reply": {"id": "help"}}))
    expect("J2.2 voice note", inbound(PH2, type="audio", audio={"id": "media123", "mime_type": "audio/ogg"}))
    q = mongo.field_updates.find_one({"company_id": CID, "worker_id": w2["id"], "kind": "help"})
    check("J2.2 question with the voice note", q and q["status"] == "open" and q["media"][0]["type"] == "voice" and q["media"][0]["media_id"] == "media123", q)
    check("J2.2 routed to the designer (need clarification)", mongo.notifications.find_one({"company_id": CID, "user_id": U["designer"], "event": "field_update",
                                                                                           "text": {"$regex": w2["name"]}}) is not None)
    ans = expect("J2.2 designer answers", call("POST", f"/field-updates/{q['_id']}/answer", {"text": "Use 2 mm spacers"}, T["designer"]))
    check("J2.2 answer sent back on WhatsApp", ans["status"] == "answered" and ans["sent"] == "sent", ans)
    expect("J2.2 answered twice", call("POST", f"/field-updates/{q['_id']}/answer", {"text": "again"}, T["designer"]), 409)
    # one step: text with a keyword
    expect("J2.3 'work done' as text", inbound(PH1, type="text", text={"body": "plumbing done"}))
    dn = mongo.field_updates.find_one({"company_id": CID, "worker_id": w1["id"], "kind": "done"})
    check("J2.3 waits for the supervisor", dn and dn["status"] == "pending" and dn["task_id"] == T1, dn)
    lst = expect("J2.3 supervisor's list", call("GET", f"/field-updates?project_id={PID}&status=pending", token=T["site"]))
    check("J2.3 listed", any(x["id"] == str(dn["_id"]) for x in lst), lst)
    expect("J2.3 sales cannot list", call("GET", "/field-updates", token=T["sales"]), 403)
    rj = expect("J2.3 sent back with a reason", call("POST", f"/field-updates/{dn['_id']}/reject", {"reason": "Fix the leak under the sink"}, T["site"]))
    check("J2.3 rejected and told", rj["status"] == "rejected" and mongo.messages.find_one({"company_id": CID, "worker_id": w1["id"], "text": {"$regex": "leak"}}), rj)
    expect("J2.3 reject needs a reason", call("POST", f"/field-updates/{dn['_id']}/reject", {}, T["site"]), 409)
    expect("J2.4 done again (button)", inbound(PH1, type="interactive", interactive={"type": "button_reply", "button_reply": {"id": "done"}}))
    dn2 = mongo.field_updates.find_one({"company_id": CID, "worker_id": w1["id"], "kind": "done", "status": "pending"})
    check("J2.4 a done button needs no detail", dn2 is not None, dn2)
    ap = expect("J2.4 supervisor approves", call("POST", f"/field-updates/{dn2['_id']}/approve", {}, T["site"]))
    tk1 = next(tk for s in mongo.projects.find_one({"_id": ObjectId(PID)})["stages"] for tk in s["tasks"] if tk["id"] == T1)
    check("J2.4 task is done", ap["status"] == "approved" and tk1["status"] == "done" and tk1["progress"] == 100, tk1["status"])
    expect("J2.4 approve twice", call("POST", f"/field-updates/{dn2['_id']}/approve", {}, T["site"]), 409)
    # ======================================= block 3 (trade sequence, from that approval) =======================================
    ready = mongo.messages.find_one({"company_id": CID, "worker_id": w2["id"], "kind": "worker_ready"})
    check("J3.1 the next trade in the room (tiling) is told on WhatsApp", ready and "Kitchen" in ready["text"] and "tiling" in ready["text"].lower(), ready and ready["text"])
    check("J3.1 not the painter yet", mongo.messages.find_one({"company_id": CID, "worker_id": w3["id"], "kind": "worker_ready"}) is None)
    check("J3.1 supervisor notified in the app", mongo.notifications.find_one({"company_id": CID, "user_id": U["site"], "event": "trade_ready"}) is not None)
    # urgent escalation
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"field.escalate_minutes": 5}})
    expect("J2.5 urgent message", inbound(PH2, type="text", text={"body": "Accident near the scaffold, need help"}))
    ur = mongo.field_updates.find_one({"company_id": CID, "worker_id": w2["id"], "urgent": True})
    check("J2.5 urgent, PM told at once", ur and ur["escalate_at"] and mongo.notifications.find_one({"company_id": CID, "user_id": U["pm"], "event": "field_update",
                                                                                                    "text": {"$regex": "^URGENT"}}), ur)
    worker(datetime.utcnow() + timedelta(minutes=10))
    ur = mongo.field_updates.find_one({"_id": ur["_id"]})
    check("J2.5 escalated to the Owner when nobody acknowledged", ur["escalated"] and mongo.notifications.find_one({"company_id": CID, "user_id": U["owner"],
                                                                                                                  "event": "field_escalated", "key": f"field-esc:{ur['_id']}"}), ur)
    worker(datetime.utcnow() + timedelta(minutes=20))
    check("J2.5 escalated once", mongo.notifications.count_documents({"company_id": CID, "key": f"field-esc:{ur['_id']}"}) == 1)
    expect("J2.5 acknowledge", call("POST", f"/field-updates/{ur['_id']}/ack", {}, T["pm"]))
    # routing rules
    expect("J2.6 bad role in routing", call("PUT", "/settings/field", {"routing": {"payment": "pilot"}}, T["owner"]), 400)
    rs = expect("J2.6 routing rules and urgent words", call("PUT", "/settings/field", {"routing": {"design": "pm"}, "urgent_words": ["leakage"]}, T["owner"]))
    check("J2.6 saved", rs["routing"] == {"design": "pm"} and rs["urgent_words"] == ["leakage"], rs)
    from flask import g as fg
    from app import create_app
    with create_app().test_request_context():
        from app.routes.field import routing_role, is_urgent
        fg.cid, fg.company = CID, mongo.companies.find_one({"_id": ObjectId(CID)})
        check("J2.6 the company's rule wins", routing_role("design") == "pm" and routing_role("payment") == "accounts")
        check("J2.6 own urgent words", is_urgent("big LEAKAGE in bathroom") and not is_urgent("all fine"))
    # STOP from a worker
    expect("J2.7 STOP", inbound(PH2, type="text", text={"body": "STOP"}))
    check("J2.7 worker opted out", mongo.site_workers.find_one({"_id": ObjectId(w2["id"])})["whatsapp_opt_out"]["how"] == "STOP")
    expect("J2.8 unknown number ignored", inbound("919999999999", type="text", text={"body": "hello"}))
    # trade sequence by links
    call("PUT", f"/projects/{PID}/tasks/{T3}", {"links": [{"task_id": T2, "type": "FS", "lag": 0}]}, T["owner"])
    call("PUT", f"/projects/{PID}/tasks/{T2}", {"status": "in_progress"}, T["owner"])
    expect("J3.2 tiling done in the app", call("PUT", f"/projects/{PID}/tasks/{T2}", {"status": "done"}, T["owner"]))
    check("J3.2 the painter (linked) hears the kitchen is ready", mongo.messages.find_one({"company_id": CID, "worker_id": w3["id"], "kind": "worker_ready"}) is not None)
    # rooms and QR codes
    rooms = expect("J3.3 rooms of the project", call("GET", f"/projects/{PID}/rooms", token=T["site"]))
    kit = next((r for r in rooms if r["room"] == "Kitchen"), None)
    check("J3.3 kitchen with its drawing and jobs", kit and kit["drawings"] == 1 and kit["jobs"] == 3 and kit["token"] is None, rooms)
    qr = expect("J3.3 QR for the kitchen", call("POST", f"/projects/{PID}/rooms/qr", {"room": "Kitchen"}, T["site"]), 201)
    qr2 = call("POST", f"/projects/{PID}/rooms/qr", {"room": "Kitchen"}, T["site"])[1]
    check("J3.3 one code per room", qr["token"] == qr2["token"] and "/r/" in qr["link"], qr)
    rp = expect("J3.3 public room page", call("GET", f"/public/room/{qr['token']}"))
    check("J3.3 latest drawing and the jobs", rp["drawings"][0]["name"] == f"Kitchen layout {RUN}" and len(rp["jobs"]) == 3 and "cost" not in json.dumps(rp), rp)
    expect("J3.3 room token is not a job token", call("GET", f"/public/job/{qr['token']}"), 404)
    st_, svg = call("GET", "/qr.svg?data=" + urllib.parse.quote(qr["link"]))
    check("J3.3 QR image", st_ == 200 and b"<svg" in svg[:400], svg[:80] if isinstance(svg, bytes) else svg)
    lj = expect("J3.4 job cards of the project", call("GET", f"/projects/{PID}/job-cards", token=T["pm"]))
    check("J3.4 three cards", len(lj) == 3, len(lj))

    # ======================================= block 4 =======================================
    call("PUT", f"/projects/{PID}/tasks/{T4}", {"status": "blocked", "notes": "Waiting for the client's light fittings"}, T["owner"])
    dg = expect("J4.1 PM digest", call("GET", "/digest", token=T["pm"]))
    row = next((r for r in dg["projects"] if r["project_id"] == PID), None)
    check("J4.1 the project is in the PM's digest", row is not None, [r["project"] for r in dg["projects"]])
    check("J4.1 late task", any(x["task"] == f"Late wiring {RUN}" and x["days"] == 2 for x in row["late"]), row["late"])
    check("J4.1 stuck: blocked task and the open material request", any("light fittings" in (x["why"] or "") for x in row["stuck"]), row["stuck"])
    check("J4.1 done yesterday / today", any("done" in x for x in row["done"]), row["done"])
    check("J4.1 no site report yesterday", row["site_report"] is False)
    expect("J4.1 sales has no digest", call("GET", "/digest", token=T["sales"]), 403)
    expect("J4.2 opt in needs a mobile", call("PUT", "/me/whatsapp", {"opt_in": True}, T["pm"]), 400 if not mongo.users.find_one({"_id": ObjectId(U["pm"])}).get("phone") else 200)
    mongo.users.update_one({"_id": ObjectId(U["pm"])}, {"$set": {"phone": "9811100022"}})
    expect("J4.2 PM opts in to WhatsApp", call("PUT", "/me/whatsapp", {"opt_in": True}, T["pm"]))
    call("PUT", "/settings/field", {"digest_on": True, "digest_time": "00:00"}, T["owner"])
    worker()
    nd = mongo.notifications.find_one({"company_id": CID, "user_id": U["pm"], "event": "pm_digest"}, sort=[("created_at", -1)])
    check("J4.2 digest notification", nd and "late" in nd["text"] and f"PhaseJ {RUN}" in nd["text"], nd and nd["text"])
    check("J4.2 digest on WhatsApp to the PM", mongo.messages.find_one({"company_id": CID, "kind": "pm_digest", "contact_id": f"u:{U['pm']}"}) is not None)
    worker()
    check("J4.2 once a day", mongo.notifications.count_documents({"company_id": CID, "user_id": U["pm"], "event": "pm_digest", "key": {"$regex": f":{nd['key'].split(':')[-1]}$"}}) == 1)
    # inbound email
    ie = expect("J4.3 inbound email address", call("POST", "/settings/inbound-email", {"enabled": True}, T["owner"]))
    check("J4.3 secret webhook", ie["enabled"] and ie["webhook_url"].startswith(f"/api/webhooks/email/{CID}/"), ie)
    expect("J4.3 PM cannot set it", call("POST", "/settings/inbound-email", {}, T["pm"]), 403)
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {"email": f"client{RUN}@mail.test"}})
    hook = ie["webhook_url"][4:]
    expect("J4.3 wrong token", call("POST", f"/webhooks/email/{CID}/nope", {"from": "x@y.z", "text": "hi"}), 404)
    em = expect("J4.3 email from the client", call("POST", hook, {"from": f"Client <CLIENT{RUN}@mail.test>", "subject": f"Tiles {RUN}",
                                                                  "text": "Can we change the tile colour?\n\nOn Mon someone wrote:\n> old", "message_id": f"<m{RUN}@mail>"}))
    check("J4.3 matched and routed", em["matched"] and em["routed"], em)
    th = expect("J4.3 in the client's project thread", call("GET", f"/projects/{PID}/threads/{CLIENT_CONTACT}", token=T["pm"]))
    last = [m for m in th if m.get("via") == "email"]
    check("J4.3 thread entry via email, quoted reply cut", last and "tile colour" in last[-1]["text"] and "old" not in last[-1]["text"], [m["text"] for m in last])
    dup = expect("J4.3 duplicate ignored", call("POST", hook, {"from": f"client{RUN}@mail.test", "text": "x", "message_id": f"<m{RUN}@mail>"}))
    check("J4.3 duplicate flagged", dup.get("duplicate"), dup)
    un = expect("J4.3 unknown sender", call("POST", hook, {"from": f"stranger{RUN}@mail.test", "subject": "Quote?", "text": "Do you do kitchens?"}))
    check("J4.3 kept as unmatched", un["matched"] is False, un)
    ul = expect("J4.3 unmatched list", call("GET", "/inbox/email?unmatched=1", token=T["owner"]))
    check("J4.3 listed", any(m["from"] == f"stranger{RUN}@mail.test" for m in ul), ul[:1])
    expect("J4.3 needs from and text", call("POST", hook, {"subject": ""}), 400)
    rep = expect("J4.4 message report", call("GET", "/reports/messages?days=7", token=T["owner"]))
    names = [x["name"] for x in rep["people"]]
    check("J4.4 site workers and the client counted", w1["name"] in names and w2["name"] in names, names[:10])
    check("J4.4 topics and channels", any(tp == "material_needed" for tp, _ in rep["topics"]) and any(ch == "email" for ch, _ in rep["channels"]), (rep["topics"], rep["channels"]))
    expect("J4.4 bad days", call("GET", "/reports/messages?days=0", token=T["owner"]), 400)
    expect("J4.4 sales cannot", call("GET", "/reports/messages", token=T["site"]), 403)

    # ======================================= block 5 =======================================
    k360 = upload("pano.jpg", T["designer"])
    expect("J5.1 bad kind", call("POST", f"/projects/{PID}/views", {"kind": "vr", "file_key": k360, "title": "x"}, T["designer"]), 400)
    expect("J5.1 file must exist", call("POST", f"/projects/{PID}/views", {"kind": "360", "file_key": "nope", "title": "x"}, T["designer"]), 400)
    v = expect("J5.1 a 360° view", call("POST", f"/projects/{PID}/views", {"kind": "360", "file_key": k360, "title": f"Living 360 {RUN}", "room": "Living"}, T["designer"]), 201)
    r_ = expect("J5.1 a render", call("POST", f"/projects/{PID}/views", {"kind": "render", "file_key": k360, "title": f"Bedroom render {RUN}", "room": "Bedroom", "shared": True}, T["designer"]), 201)
    expect("J5.1 site cannot add", call("POST", f"/projects/{PID}/views", {"kind": "360", "file_key": k360, "title": "x"}, T["site"]), 403)
    expect("J5.2 spot needed on a 360", call("POST", f"/views/{v['id']}/comments", {"text": "Lower the TV unit"}, T["pm"]), 400)
    expect("J5.2 pitch out of range", call("POST", f"/views/{v['id']}/comments", {"text": "x", "yaw": 10, "pitch": 120}, T["pm"]), 400)
    c1 = expect("J5.2 team comment on a spot", call("POST", f"/views/{v['id']}/comments", {"text": "Lower the TV unit by 100 mm", "yaw": 35.5, "pitch": -4}, T["pm"]), 201)
    expect("J5.2 render needs x/y %", call("POST", f"/views/{r_['id']}/comments", {"text": "x", "x": 120, "y": 5}, T["pm"]), 400)
    pv = expect("J5.3 client sees only shared views", call("GET", f"/portal/projects/{PID}/views", token=T["client"]))
    check("J5.3 the render only", [x["title"] for x in pv] == [f"Bedroom render {RUN}"], [x["title"] for x in pv])
    expect("J5.3 client cannot comment on an unshared view", call("POST", f"/portal/views/{v['id']}/comments", {"text": "x", "yaw": 1, "pitch": 1}, T["client"]), 404)
    cc = expect("J5.3 client comments on the render", call("POST", f"/portal/views/{r_['id']}/comments", {"text": "Make the headboard walnut", "x": 40, "y": 55}, T["client"]), 201)
    check("J5.3 designer and PM told", mongo.notifications.find_one({"company_id": CID, "user_id": U["designer"], "event": "view_comment"}) is not None)
    tk = expect("J5.4 comment becomes a task", call("POST", f"/views/{v['id']}/comments/{c1['id']}/task", {"stage_id": S0, "end": day(4)}, T["designer"]), 201)
    c1s = next(c for c in tk["comments"] if c["id"] == c1["id"])
    pst = mongo.projects.find_one({"_id": ObjectId(PID)})
    check("J5.4 task on the stage, comment resolved", c1s["task_id"] and c1s["status"] == "resolved"
          and any(t_["id"] == c1s["task_id"] and "TV unit" in t_["title"] for s in pst["stages"] for t_ in s["tasks"]), c1s)
    expect("J5.4 only once", call("POST", f"/views/{v['id']}/comments/{c1['id']}/task", {"stage_id": S0}, T["designer"]), 409)
    ch = expect("J5.5 client comment becomes a change request", call("POST", f"/views/{r_['id']}/comments/{cc['id']}/change", {}, T["pm"]), 201)
    ccs = next(c for c in ch["comments"] if c["id"] == cc["id"])
    co = mongo.change_orders.find_one({"_id": ObjectId(ccs["co_id"])})
    check("J5.5 a draft change order, requested by the client", co and co["status"] == "draft" and co["requested"]["kind"] == "client" and "walnut" in co["title"], co and co.get("requested"))
    expect("J5.6 a view with a task is kept", call("DELETE", f"/views/{v['id']}", token=T["designer"]), 409)
    rr = expect("J5.6 resolve toggles", call("POST", f"/views/{r_['id']}/comments/{cc['id']}/resolve", {}, T["designer"]))
    check("J5.6 reopened", next(c for c in rr["comments"] if c["id"] == cc["id"])["status"] == "open")

    # ======================================= block 6 =======================================
    sel = expect("selection to link", call("POST", f"/projects/{PID}/selections", {"stage_id": S0, "item": f"Wardrobe finish {RUN}", "room": "Bedroom",
                                                                                   "options": [{"name": "Oak laminate", "qty": 1, "unit_cost": 20000, "unit_price": 30000},
                                                                                               {"name": "Walnut veneer", "qty": 1, "unit_cost": 32000, "unit_price": 45000}]}, T["owner"]), 201)
    so = sel["options"]
    k_a, k_b = upload("a.png", T["designer"]), upload("b.png", T["designer"])
    expect("J6.1 needs two options", call("POST", f"/projects/{PID}/design-options", {"title": "x", "options": [{"name": "A"}]}, T["designer"]), 400)
    expect("J6.1 linked option must belong to the selection", call("POST", f"/projects/{PID}/design-options", {"title": "x", "selection_id": sel["id"],
                                                                                                             "options": [{"name": "A", "selection_option_id": "zz"}, {"name": "B"}]}, T["designer"]), 400)
    dsn = expect("J6.1 decision with A / B / C", call("POST", f"/projects/{PID}/design-options", {
        "title": f"Wardrobe look {RUN}", "room": "Bedroom", "selection_id": sel["id"],
        "options": [{"name": "Oak, handle-less", "images": [k_a], "selection_option_id": so[0]["id"]},
                    {"name": "Walnut, brass handles", "images": [k_b], "price": 15000, "selection_option_id": so[1]["id"]},
                    {"name": "Painted white", "description": "PU paint", "price": -2000}]}, T["designer"]), 201)
    check("J6.1 labelled A B C, draft", [o["label"] for o in dsn["options"]] == ["A", "B", "C"] and dsn["status"] == "draft" and dsn["options"][0]["images"][0]["url"], dsn)
    pd = expect("J6.2 client sees nothing before it is sent", call("GET", f"/portal/projects/{PID}/design-options", token=T["client"]))
    check("J6.2 none yet", not any(x["id"] == dsn["id"] for x in pd), pd)
    sd = expect("J6.2 send to the client", call("POST", f"/design-options/{dsn['id']}/send", {}, T["designer"]))
    check("J6.2 sent", sd["status"] == "sent", sd)
    pd = expect("J6.2 in the portal", call("GET", f"/portal/projects/{PID}/design-options", token=T["client"]))
    check("J6.2 side by side", any(x["id"] == dsn["id"] and len(x["options"]) == 3 for x in pd), pd)
    expect("J6.3 must choose an option", call("POST", f"/portal/design-options/{dsn['id']}/approve", {"option_id": "zz"}, T["client"]), 400)
    rq = expect("J6.3 client asks for changes", call("POST", f"/portal/design-options/{dsn['id']}/changes", {"comment": "Show a grey option too"}, T["client"]))
    check("J6.3 changes requested", rq["status"] == "changes_requested", rq)
    expect("J6.3 not waiting any more", call("POST", f"/portal/design-options/{dsn['id']}/approve", {"option_id": dsn["options"][0]["id"]}, T["client"]), 409)
    ed = expect("J6.4 designer edits the options", call("PUT", f"/design-options/{dsn['id']}", {"options": dsn["options"] + [{"name": "Grey matt", "price": 5000}]}, T["designer"]))
    check("J6.4 back to draft with D", ed["status"] == "draft" and ed["options"][3]["label"] == "D", ed)
    call("POST", f"/design-options/{dsn['id']}/send", {}, T["designer"])
    apv = expect("J6.5 client approves B", call("POST", f"/portal/design-options/{dsn['id']}/approve", {"option_id": ed["options"][1]["id"], "comment": "Love it"}, T["client"]))
    s_ = mongo.selections.find_one({"_id": ObjectId(sel["id"])})
    co6 = mongo.change_orders.find_one({"_id": ObjectId(apv["co_id"])}) if apv.get("co_id") else None
    check("J6.5 approved", apv["status"] == "approved" and apv["approved_label"] == "B", apv)
    check("J6.5 the linked selection records the choice", s_["status"] == "chosen" and s_["chosen_option_id"] == so[1]["id"] and s_["choice"]["method"] == "Portal", s_.get("choice"))
    check("J6.5 the extra price becomes a draft change order", co6 and co6["status"] == "draft" and co6["lines"][0]["price_rate"] == 15000, co6 and co6["lines"])
    check("J6.5 managers told", mongo.notifications.find_one({"company_id": CID, "user_id": U["pm"], "event": "design_option", "text": {"$regex": "approved option B"}}) is not None)
    expect("J6.6 an approved decision cannot change", call("PUT", f"/design-options/{dsn['id']}", {"title": "x"}, T["designer"]), 409)
    expect("J6.6 nor be deleted", call("DELETE", f"/design-options/{dsn['id']}", token=T["designer"]), 409)
    expect("J6.6 site cannot add designs", call("POST", f"/projects/{PID}/design-options", {"title": "x"}, T["site"]), 403)

    # ======================================= block 7 =======================================
    from app.security import create_token
    SA = {}
    for u in mongo.superadmin_users.find({"active": {"$ne": False}}):
        SA.setdefault(u["role"], create_token({"uid": str(u["_id"]), "kind": "superadmin", "role": u["role"], "name": u["name"]}))
    mongo.platform_settings.update_one({"_id": "settings"}, {"$set": {"gateway": "sandbox", "gateway_webhook_secret": f"wh{RUN}"}}, upsert=True)
    sg = expect("signup", call("POST", "/auth/signup", {"company_name": f"Auto Co {RUN}", "name": "Auto Owner", "email": f"auto{RUN}@sub.test", "password": "secret12",
                                                        "company_types": ["contractor"], "plan_code": "pro", "city": "Pune"}), 201)
    C7, O7 = sg["company"]["id"], sg["token"]
    signups.append(C7)
    expect("J7.1 only the owner", call("POST", "/billing/autopay", {"method": "card"}, T["pm"]), 403)
    expect("J7.1 card or UPI", call("POST", "/billing/autopay", {"method": "cash"}, O7), 400)
    inv1 = expect("J7.2 an open invoice", call("POST", f"/sa/companies/{C7}/invoice", {}, SA["owner"]), 201 if True else 200)
    if not isinstance(inv1, dict) or "id" not in inv1:
        inv1 = {"id": str(mongo.platform_invoices.find_one({"company_id": C7}, sort=[("created_at", -1)])["_id"])}
    a1 = expect("J7.2 autopay with a card (sandbox)", call("POST", "/billing/autopay", {"method": "card"}, O7), 201)
    check("J7.2 mandate active, the open invoice charged at once", a1["autopay"]["status"] == "active" and a1["charged"]["status"] == "paid", a1)
    i1 = mongo.platform_invoices.find_one({"_id": ObjectId(inv1["id"])})
    c7 = mongo.companies.find_one({"_id": ObjectId(C7)})
    check("J7.2 invoice paid by autopay, company active", i1["status"] == "paid" and i1["method"] == "autopay" and c7["status"] == "active", (i1["status"], c7["status"]))
    ga = expect("J7.2 autopay status", call("GET", "/billing/autopay", token=O7))
    check("J7.2 shows the gateway", ga["gateway"] == "sandbox" and ga["autopay"]["method"] == "card", ga)
    # renewal: billing run issues and charges
    mongo.companies.update_one({"_id": ObjectId(C7)}, {"$set": {"next_renewal": datetime.utcnow() - timedelta(minutes=1)}})
    from app import create_app as ca
    from app.routes.platform import billing_run
    with ca().app_context():
        billing_run(datetime.utcnow())
    i2 = mongo.platform_invoices.find_one({"company_id": C7, "_id": {"$ne": i1["_id"]}}, sort=[("created_at", -1)])
    check("J7.3 renewal invoice charged in the billing run", i2 and i2["status"] == "paid" and i2["method"] == "autopay", i2 and i2["status"])
    # a failing card: three tries, one a day
    a2 = expect("J7.4 a card that is declined", call("POST", "/billing/autopay", {"method": "card", "test": "4000000000000002"}, O7), 201)
    mongo.companies.update_one({"_id": ObjectId(C7)}, {"$set": {"next_renewal": datetime.utcnow() - timedelta(minutes=1)}})
    with ca().app_context():
        billing_run(datetime.utcnow())
        i3 = mongo.platform_invoices.find_one({"company_id": C7, "status": {"$in": ["due", "overdue"]}})
        check("J7.4 first try failed", i3 and i3["charge_tries"] == 1 and "declined" in i3["charge_error"].lower(), i3 and i3.get("charge_tries"))
        billing_run(datetime.utcnow())
        check("J7.4 once a day", mongo.platform_invoices.find_one({"_id": i3["_id"]})["charge_tries"] == 1)
        for n in (1, 2, 3, 4):
            billing_run(datetime.utcnow() + timedelta(days=n))
    i3 = mongo.platform_invoices.find_one({"_id": i3["_id"]})
    check("J7.4 three tries, then stops", i3["charge_tries"] == 3 and i3["status"] in ("due", "overdue"), i3["charge_tries"])
    check("J7.4 the failure is kept on the company", mongo.companies.find_one({"_id": ObjectId(C7)})["autopay"]["last_error"], "")
    # signed webhook from the gateway
    mongo.platform_invoices.update_one({"_id": i3["_id"]}, {"$set": {"charge_pending": True}})
    body = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": f"pay_{RUN}", "notes": {"invoice_id": str(i3["_id"])}}}}}
    raw = json.dumps(body).encode()
    expect("J7.5 bad signature", raw_post("/webhooks/billing/sandbox", raw, {"X-Razorpay-Signature": "x", "Content-Type": "application/json"}), 400)
    expect("J7.5 wrong gateway", raw_post("/webhooks/billing/stripe", raw, {"Stripe-Signature": "t=1,v1=x", "Content-Type": "application/json"}), 400)
    sig = hmac.new(f"wh{RUN}".encode(), raw, hashlib.sha256).hexdigest()
    wr = expect("J7.5 payment captured", raw_post("/webhooks/billing/sandbox", raw, {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}))
    i3 = mongo.platform_invoices.find_one({"_id": i3["_id"]})
    check("J7.5 invoice paid from the webhook", wr["result"] == "paid" and i3["status"] == "paid" and i3["ref"] == f"pay_{RUN}", (wr, i3["status"]))
    wr2 = raw_post("/webhooks/billing/sandbox", raw, {"X-Razorpay-Signature": sig, "Content-Type": "application/json"})[1]
    check("J7.5 a repeat is harmless", wr2["result"] == "already paid", wr2)
    sm = expect("J7.6 secrets masked in SA settings", call("GET", "/sa/settings", token=SA["owner"]))
    check("J7.6 webhook secret masked", str(sm.get("gateway_webhook_secret", "")).startswith("••••"), sm.get("gateway_webhook_secret"))
    expect("J7.7 cancel autopay", call("DELETE", "/billing/autopay", token=O7))
    check("J7.7 cancelled", mongo.companies.find_one({"_id": ObjectId(C7)})["autopay"]["status"] == "cancelled")
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    failures.append(f"crashed: {e}")
finally:
    pids = projects if not os.getenv("KEEP") else []
    if os.getenv("KEEP"):
        print("kept projects:", projects)
    for col in ("notifications", "project_events", "project_activity", "selections", "purchase_requests", "change_orders", "documents", "messages",
                "job_cards", "room_codes", "field_updates", "views", "design_options"):
        mongo[col].delete_many({"company_id": CID, "project_id": {"$in": pids}})
    mongo.messages.delete_many({"company_id": CID, "worker_id": {"$in": workers_made}})
    mongo.messages.delete_many({"company_id": CID, "$or": [{"from": {"$regex": RUN}}, {"kind": "pm_digest"}]})
    mongo.notifications.delete_many({"company_id": CID, "event": {"$in": ["pm_digest", "email_in", "field_escalated"]}})
    mongo.field_updates.delete_many({"company_id": CID, "worker_id": {"$in": workers_made}})
    mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
    mongo.site_workers.delete_many({"_id": {"$in": [ObjectId(x) for x in workers_made]}})
    mongo.files.delete_many({"company_id": CID, "key": {"$in": keys}})
    for cid7 in signups:
        for name in mongo.list_collection_names():
            mongo[name].delete_many({"company_id": cid7})
        mongo.companies.delete_one({"_id": ObjectId(cid7)})
        mongo.users.delete_many({"company_id": cid7})
    if sa_before:
        mongo.platform_settings.replace_one({"_id": "settings"}, sa_before, upsert=True)
    else:
        mongo.platform_settings.delete_one({"_id": "settings"})
    restore = {k: company_before.get(k) for k in ("messaging", "field", "inbound_email")}
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": restore, "$unset": {"field_runs": ""}})
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {k: client_before.get(k) for k in ("phone", "email", "whatsapp_opt_in", "whatsapp_opt_out")}})
    for uid_, ph in users_before.items():
        mongo.users.update_one({"_id": uid_}, {"$set": {"phone": ph}, "$unset": {"whatsapp_opt_in": ""}})

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
