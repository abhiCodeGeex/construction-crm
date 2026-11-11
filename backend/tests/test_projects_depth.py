"""Phase B+ blocks 2-4 — stage closing rules and client sign-off, task checklists, comments with @mentions, task
files, stage templates, working days and holidays, link types with lag, baseline and delays with reasons,
moving dependent tasks, the project timeline, meetings and minutes, waiting on whom (also in the client portal),
project health, finish forecast and their scheduled checks. Cleans up everything it creates.

    docker compose exec backend python tests/test_projects_depth.py
"""
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
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


def upload(name, token):
    boundary = uuid.uuid4().hex
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "designer", "site", "sales")}
T["client"] = login("client@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
NAME = {u["email"].split("@")[0]: u["name"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"email_settings": 1, "calendar": 1})
projects, contacts = [], []


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def proj(pid, who="owner"):
    return call("GET", f"/projects/{pid}", token=T[who])[1]


def stage_of(p, name=None, service=None):
    return next(s for s in p["stages"] if (name is None or s["name"] == name) and (service is None or s["service"] == service))


def task_of(p, title):
    return next(tk for s in p["stages"] for tk in s["tasks"] if tk["title"] == title)


def activity(pid, group=None):
    return call("GET", f"/projects/{pid}/activity" + (f"?group={urllib.parse.quote(group)}" if group else ""), token=T["owner"])[1]


import urllib.parse  # noqa: E402

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
smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 2528), SMTPHandler)
threading.Thread(target=smtp.serve_forever, daemon=True).start()

try:
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"calendar": ""}})  # default calendar for the test
    p = expect("project", call("POST", "/projects", {"name": f"Depth {RUN}", "services": ["construction", "interior"],
                                                     "start": day(0), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    for who, role, acc in (("pm", "Project Manager", "edit"), ("designer", "Architect", "view"), ("site", "Site Supervisor", "view")):
        call("POST", f"/projects/{pid}/team", {"user_id": U[who], "project_role": role, "access": acc}, T["owner"])
    p = proj(pid)

    # ===================== BLOCK 2 · stage closing rules =====================
    con = stage_of(p, service="construction")
    inte = stage_of(p, service="interior")
    check("construction stage: default closing checklist", [c["text"] for c in con["checklist"]] ==
          ["Quality inspection passed", "Site photos uploaded", "Snags for this stage closed"], con["checklist"])
    check("construction: no client sign-off needed; interior: needed", con["client_signoff_required"] is False
          and inte["client_signoff_required"] is True)
    check("gate milestone flagged", con["gate"]["milestone_id"] and not con["gate"]["closed"])
    check("not ready: says why (progress, checklist)", any("Progress is 0%" in m for m in con["gate"]["missing"])
          and any("Checklist not ticked" in m for m in con["gate"]["missing"]), con["gate"])
    gid = con["gate"]["milestone_id"]
    r = expect("closing a stage that is not ready is refused", call("PUT", f"/projects/{pid}/milestones/{gid}", {"status": "achieved"}, T["pm"]), 409)
    check("refusal lists what is missing", "cannot be closed yet" in r.get("error", "") and "Checklist" in r["error"], r)
    expect("PM cannot override", call("PUT", f"/projects/{pid}/milestones/{gid}", {"status": "achieved", "override_reason": "x"}, T["pm"]), 403)
    expect("Owner overrides with a reason", call("PUT", f"/projects/{pid}/milestones/{gid}",
                                                {"status": "achieved", "override_reason": f"Client urgent {RUN}"}, T["owner"]), 200)
    check("override shown on the timeline", any("owner override" in a["text"] and RUN in a["text"] for a in activity(pid)["rows"]))
    check("closed stage cannot be edited", call("POST", f"/projects/{pid}/stages/{con['id']}/checklist", {"text": "x"}, T["pm"])[0] == 409)
    call("PUT", f"/projects/{pid}/milestones/{gid}", {"status": "pending"}, T["owner"])
    ms = next(m for m in stage_of(proj(pid), service="construction")["milestones"] if m["id"] == gid)
    check("reopened: override cleared", ms["status"] == "pending" and not ms.get("override_reason"))

    expect("checklist item text required", call("POST", f"/projects/{pid}/stages/{con['id']}/checklist", {"text": " "}, T["pm"]), 400)
    r = expect("add checklist item", call("POST", f"/projects/{pid}/stages/{con['id']}/checklist", {"text": f"Curing done {RUN}"}, T["pm"]), 201)
    expect("same item twice refused", call("POST", f"/projects/{pid}/stages/{con['id']}/checklist", {"text": f"curing done {RUN}"}, T["pm"]), 409)
    expect("view-only member cannot tick", call("PUT", f"/projects/{pid}/stages/{con['id']}/checklist/{con['checklist'][0]['id']}",
                                               {"done": True}, T["designer"]), 403)
    items = stage_of(r, service="construction")["checklist"]
    for c in items:
        call("PUT", f"/projects/{pid}/stages/{con['id']}/checklist/{c['id']}", {"done": True}, T["pm"])
    con = stage_of(proj(pid), service="construction")
    check("ticks record who", all(c["done"] and c["done_by"] == NAME["pm"] for c in con["checklist"]))
    extra = next(c for c in con["checklist"] if RUN in c["text"])
    expect("remove checklist item", call("DELETE", f"/projects/{pid}/stages/{con['id']}/checklist/{extra['id']}", token=T["pm"]), 200)
    check("checklist ticks on the timeline", len([a for a in activity(pid, "Stages & milestones")["rows"] if "ticked" in a["text"]]) >= 3)

    # tasks, priority, task checklist
    r = expect("task with priority", call("POST", f"/projects/{pid}/stages/{con['id']}/tasks",
                                          {"title": f"Pour {RUN}", "start": day(0), "end": day(2), "assignee_id": U["site"],
                                           "priority": "urgent"}, T["pm"]), 201)
    pour = task_of(r, f"Pour {RUN}")
    check("priority saved", pour["priority"] == "urgent")
    expect("bad priority", call("PUT", f"/projects/{pid}/tasks/{pour['id']}", {"priority": "asap"}, T["pm"]), 400)
    expect("assignee (view access) adds a checklist item", call("POST", f"/projects/{pid}/tasks/{pour['id']}/checklist",
                                                               {"text": "Shuttering checked"}, T["site"]), 201)
    expect("not the assignee, view only: refused", call("POST", f"/projects/{pid}/tasks/{pour['id']}/checklist", {"text": "x"}, T["designer"]), 403)
    call("POST", f"/projects/{pid}/tasks/{pour['id']}/checklist", {"text": "Concrete grade checked"}, T["pm"])
    pour = task_of(proj(pid), f"Pour {RUN}")
    r = expect("done with open checklist refused", call("PUT", f"/projects/{pid}/tasks/{pour['id']}", {"status": "done"}, T["site"]), 409)
    check("refusal names the open items", "Shuttering checked" in r.get("error", ""), r)
    call("PUT", f"/projects/{pid}/tasks/{pour['id']}", {"status": "in_progress"}, T["site"])
    call("PUT", f"/projects/{pid}/tasks/{pour['id']}/checklist/{pour['checklist'][0]['id']}", {"done": True}, T["site"])
    check("progress follows the ticks", task_of(proj(pid), f"Pour {RUN}")["progress"] == 50)
    call("PUT", f"/projects/{pid}/tasks/{pour['id']}/checklist/{pour['checklist'][1]['id']}", {"done": True}, T["site"])
    expect("all ticked: done", call("PUT", f"/projects/{pid}/tasks/{pour['id']}", {"status": "done"}, T["site"]), 200)
    call("POST", f"/projects/{pid}/tasks/{pour['id']}/checklist", {"text": "Photos uploaded"}, T["site"])
    check("a new open item reopens a done task", task_of(proj(pid), f"Pour {RUN}")["status"] == "in_progress")
    pour = task_of(proj(pid), f"Pour {RUN}")
    call("DELETE", f"/projects/{pid}/tasks/{pour['id']}/checklist/{pour['checklist'][2]['id']}", token=T["site"])
    call("PUT", f"/projects/{pid}/tasks/{pour['id']}", {"status": "done"}, T["site"])

    # comments and @mentions
    text = f"Please check the slab level @{NAME['pm']} {RUN}"
    c1 = expect("view member comments", call("POST", f"/projects/{pid}/tasks/{pour['id']}/comments", {"text": text}, T["designer"]), 201)
    check("mention found", c1["mentions"] == [U["pm"]], c1["mentions"])
    check("mentioned person told", any(RUN in n["text"] for n in bell("pm", event="mentioned", project_id=pid)))
    check("assignee told about a comment", any(RUN in n["text"] for n in bell("site", event="task_comment", project_id=pid)))
    check("author not told", not bell("designer", event="mentioned", project_id=pid))
    expect("empty comment refused", call("POST", f"/projects/{pid}/tasks/{pour['id']}/comments", {"text": ""}, T["pm"]), 400)
    lst = expect("comments listed", call("GET", f"/projects/{pid}/tasks/{pour['id']}/comments", token=T["site"]), 200)
    check("comment in the list", lst and lst[-1]["by"] == NAME["designer"])
    check("comment count on the task", task_of(proj(pid), f"Pour {RUN}")["comment_count"] == 1)
    expect("someone else cannot delete it", call("DELETE", f"/projects/{pid}/comments/{c1['id']}", token=T["site"]), 403)
    expect("outsider cannot comment", call("POST", f"/projects/{pid}/tasks/{pour['id']}/comments", {"text": "hi"}, T["sales"]), 404)
    c2 = call("POST", f"/projects/{pid}/tasks/{pour['id']}/comments", {"text": f"Done {RUN}"}, T["pm"])[1]
    expect("author deletes own comment", call("DELETE", f"/projects/{pid}/comments/{c2['id']}", token=T["pm"]), 200)

    # files
    up = upload(f"slab{RUN}.png", T["site"])
    expect("upload required", call("POST", f"/projects/{pid}/tasks/{pour['id']}/files", {"key": "nope"}, T["site"]), 400)
    r = expect("assignee attaches a photo", call("POST", f"/projects/{pid}/tasks/{pour['id']}/files", {"key": up["key"], "caption": "Slab"}, T["site"]), 201)
    f = task_of(r, f"Pour {RUN}")["files"][0]
    check("file with caption and who", f["caption"] == "Slab" and f["by"] == NAME["site"])
    expect("same file twice refused", call("POST", f"/projects/{pid}/tasks/{pour['id']}/files", {"key": up["key"]}, T["site"]), 409)
    expect("view member (not uploader) cannot remove", call("DELETE", f"/projects/{pid}/tasks/{pour['id']}/files/{f['id']}", token=T["designer"]), 403)
    expect("uploader removes it", call("DELETE", f"/projects/{pid}/tasks/{pour['id']}/files/{f['id']}", token=T["site"]), 200)
    check("stored file removed too", not mongo.files.find_one({"key": up["key"]}))
    check("comments and files on the timeline", len(activity(pid, "Comments & files")["rows"]) >= 3)

    # high issue on a stage blocks closing; sign-off for interior
    iss = expect("high issue on the stage", call("POST", f"/projects/{pid}/issues", {"title": f"Crack {RUN}", "severity": "high",
                                                                                    "stage_id": con["id"]}, T["pm"]), 201)
    con = stage_of(proj(pid), service="construction")
    check("high issue listed as missing", any("high-severity issue" in m for m in con["gate"]["missing"]), con["gate"])
    call("PUT", f"/projects/{pid}/issues/{iss['id']}", {"status": "closed"}, T["pm"])
    con = stage_of(proj(pid), service="construction")
    check("ready once the issue is closed", con["gate"]["missing"] == [], con["gate"])
    expect("PM closes a ready stage", call("PUT", f"/projects/{pid}/milestones/{gid}", {"status": "achieved"}, T["pm"]), 200)
    expect("a closed stage takes no new task", call("POST", f"/projects/{pid}/stages/{con['id']}/tasks",
                                                    {"title": "Late add", "start": day(0), "end": day(1)}, T["pm"]), 409)
    expect("a gate milestone cannot be deleted", call("DELETE", f"/projects/{pid}/milestones/{inte['gate']['milestone_id']}", token=T["pm"]), 409)
    moved = stage_of(expect("move the interior stage end", call("PUT", f"/projects/{pid}/stages/{inte['id']}", {"end": day(300)}, T["pm"]), 200),
                     service="interior")
    gate = next(m for m in moved["milestones"] if m.get("gate"))
    check("an open gate follows its stage end", gate["due"] == moved["end"] == day(300), (gate["due"], moved["end"]))
    back = stage_of(call("PUT", f"/projects/{pid}/stages/{inte['id']}", {"end": inte["end"]}, T["pm"])[1], service="interior")
    check("and back again", next(m for m in back["milestones"] if m.get("gate"))["due"] == back["end"], back["end"])
    expect("bad issue stage", call("POST", f"/projects/{pid}/issues", {"title": "x", "stage_id": "nope"}, T["pm"]), 404)

    expect("sign-off: method required", call("POST", f"/projects/{pid}/stages/{inte['id']}/signoff", {"name": "Mr C"}, T["pm"]), 400)
    so = expect("record client sign-off", call("POST", f"/projects/{pid}/stages/{inte['id']}/signoff",
                                               {"name": f"Mr Client {RUN}", "method": "WhatsApp", "note": "Approved the moodboard"}, T["pm"]), 201)
    check("sign-off saved with who recorded it", stage_of(so, service="interior")["signoff"]["recorded_by"] == NAME["pm"])
    check("managers told about the sign-off", any(RUN in n["text"] for n in bell("owner", event="signoff_recorded", project_id=pid)))
    expect("remove sign-off", call("DELETE", f"/projects/{pid}/stages/{inte['id']}/signoff", token=T["pm"]), 200)
    check("missing again after removal", "Client sign-off not recorded" in stage_of(proj(pid), service="interior")["gate"]["missing"])

    # templates carry the closing checklist
    tpls = call("GET", "/stage_templates", token=T["owner"])[1]["templates"]
    tpl = next(x for x in tpls if x["service"] == "construction" and x.get("is_default"))
    check("template stages have a checklist and sign-off rule", all("checklist" in s and "client_signoff" in s for s in tpl["stages"]))
    before_tpl = json.loads(json.dumps(tpl["stages"]))
    stages = [{**s, "checklist": ["A", "a"]} if i == 0 else s for i, s in enumerate(tpl["stages"])]
    expect("duplicate checklist items refused", call("PUT", f"/stage_templates/{tpl['id']}", {"stages": stages}, T["owner"]), 400)
    stages = [{**s, "checklist": [f"Level survey {RUN}"], "client_signoff": True} if i == 0 else s for i, s in enumerate(tpl["stages"])]
    expect("template checklist saved", call("PUT", f"/stage_templates/{tpl['id']}", {"stages": stages}, T["owner"]), 200)
    p2 = call("POST", "/projects", {"name": f"Depth {RUN} tpl", "services": ["construction"], "start": day(0)}, T["owner"])[1]
    projects.append(p2["id"])
    check("new project uses the template's checklist", [c["text"] for c in p2["stages"][0]["checklist"]] == [f"Level survey {RUN}"]
          and p2["stages"][0]["client_signoff_required"] is True, p2["stages"][0].get("checklist"))
    call("PUT", f"/stage_templates/{tpl['id']}", {"stages": before_tpl}, T["owner"])

    # ===================== BLOCK 3 · working days, links, baseline, delays, timeline =====================
    from app.services import workdays
    cal = {"working_days": [0, 1, 2, 3, 4], "holidays": [{"date": "2026-12-25", "name": "Christmas"}]}
    check("add working days skips weekends", workdays.add_working("2026-12-04", 1, cal) == "2026-12-07")  # Fri -> Mon
    check("…and holidays", workdays.add_working("2026-12-24", 1, cal) == "2026-12-28")  # Thu -> (Fri 25 holiday) -> Mon
    check("working days between (both ends)", workdays.between("2026-12-21", "2026-12-25", cal) == 4)
    check("shift counts working days later", workdays.shift("2026-12-24", "2026-12-28", cal) == 1)
    cdef = expect("calendar defaults", call("GET", "/settings/calendar", token=T["site"]), 200)
    check("default Monday-Saturday", cdef["working_days"] == [0, 1, 2, 3, 4, 5] and cdef["weekdays"][0] == "Mon")
    expect("staff cannot change it", call("PUT", "/settings/calendar", {"working_days": [0]}, T["pm"]), 403)
    expect("at least one day", call("PUT", "/settings/calendar", {"working_days": []}, T["owner"]), 400)
    expect("holiday needs a name", call("PUT", "/settings/calendar", {"working_days": [0, 1, 2, 3, 4], "holidays": [{"date": day(3)}]}, T["owner"]), 400)
    expect("save calendar", call("PUT", "/settings/calendar", {"working_days": [0, 1, 2, 3, 4, 5],
                                                              "holidays": [{"date": day(9), "name": f"Festival {RUN}"}]}, T["owner"]), 200)
    CAL = {"working_days": [0, 1, 2, 3, 4, 5], "holidays": [{"date": day(9), "name": "Festival"}]}

    sid2 = stage_of(proj(pid), service="interior")["id"]
    r = call("POST", f"/projects/{pid}/stages/{sid2}/tasks", {"title": f"A {RUN}", "start": day(1), "end": day(4)}, T["pm"])[1]
    A = task_of(r, f"A {RUN}")
    expect("bad link type", call("POST", f"/projects/{pid}/stages/{sid2}/tasks", {"title": "x", "start": day(1), "end": day(2),
                                                                                 "links": [{"task_id": A["id"], "type": "XX"}]}, T["pm"]), 400)
    expect("lag must be whole days", call("POST", f"/projects/{pid}/stages/{sid2}/tasks", {"title": "x", "start": day(1), "end": day(2),
                                                                                          "links": [{"task_id": A["id"], "lag": 1.5}]}, T["pm"]), 400)
    r = expect("start-to-start link", call("POST", f"/projects/{pid}/stages/{sid2}/tasks",
                                           {"title": f"B {RUN}", "start": day(1), "end": day(6),
                                            "links": [{"task_id": A["id"], "type": "SS", "lag": 0}]}, T["pm"]), 201)
    B = task_of(r, f"B {RUN}")
    check("SS link kept, depends_on in step", B["links"] == [{"task_id": A["id"], "type": "SS", "lag": 0}] and B["depends_on"] == [A["id"]])
    check("SS same start: no conflict", B["conflict"] is False)
    expect("SS: cannot start before the other starts", call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "in_progress"}, T["pm"]), 409)
    call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"status": "in_progress"}, T["pm"])
    expect("SS: can start once the other started", call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "in_progress"}, T["pm"]), 200)
    r = call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"links": [{"task_id": A["id"], "type": "SS", "lag": 2}]}, T["pm"])[1]
    check("SS with lag 2: same start is a conflict", task_of(r, f"B {RUN}")["conflict"] is True)
    r = call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"links": [{"task_id": A["id"], "type": "FF", "lag": 0}]}, T["pm"])[1]
    check("FF: B ends after A, fine", task_of(r, f"B {RUN}")["conflict"] is False)
    expect("FF: cannot finish before the other finishes", call("PUT", f"/projects/{pid}/tasks/{B['id']}", {"status": "done"}, T["pm"]), 409)
    r = call("POST", f"/projects/{pid}/stages/{sid2}/tasks", {"title": f"C {RUN}", "start": day(5), "end": day(7),
                                                              "depends_on": [A["id"]]}, T["pm"])[1]
    C = task_of(r, f"C {RUN}")
    check("old style depends_on still works (FS)", C["links"] == [{"task_id": A["id"], "type": "FS", "lag": 0}])

    expect("move later before a baseline: no reason needed", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"end": day(8)}, T["pm"]), 200)
    expect("view member cannot set a baseline", call("POST", f"/projects/{pid}/baseline", {}, T["designer"]), 403)
    bl = expect("set baseline", call("POST", f"/projects/{pid}/baseline", {"note": f"Agreed {RUN}"}, T["pm"]), 201)
    check("baseline on the project", bl["baseline"]["note"] == f"Agreed {RUN}" and bl["baseline"]["slip_days"] == 0)
    check("tasks show 0 slip", task_of(bl, f"C {RUN}")["baseline"]["slip_days"] == 0)
    r = expect("moved later without a reason: refused", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"end": day(11)}, T["pm"]), 409)
    check("refusal explains", "delay reason" in r.get("error", ""), r)
    expect("bad reason", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"end": day(11), "delay_reason": "lazy"}, T["pm"]), 409)
    r = expect("moved later with a reason", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"end": day(11), "delay_reason": "material",
                                                                                            "delay_note": f"Tiles late {RUN}"}, T["pm"]), 200)
    exp_days = workdays.shift(day(8), day(11), CAL)
    check("slip vs baseline in working days", task_of(r, f"C {RUN}")["baseline"]["slip_days"] == exp_days, task_of(r, f"C {RUN}")["baseline"])
    dl = expect("delays list", call("GET", f"/projects/{pid}/delays", token=T["designer"]), 200)
    row = dl["rows"][0]
    check("delay recorded with party and working days", row["party"] == "vendor" and row["days"] == exp_days and row["note"] == f"Tiles late {RUN}", row)
    check("totals per party", dl["by_party"][0]["party"] == "vendor" and dl["by_party"][0]["days"] == exp_days)
    expect("moving earlier needs no reason", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"end": day(10)}, T["pm"]), 200)
    st_ = stage_of(proj(pid), service="interior")
    expect("stage end later needs a reason", call("PUT", f"/projects/{pid}/stages/{st_['id']}", {"end": day(200)}, T["pm"]), 409)
    expect("stage end later with a reason", call("PUT", f"/projects/{pid}/stages/{st_['id']}", {"end": day(200), "delay_reason": "client_change"}, T["pm"]), 200)
    gm = next(m for m in stage_of(proj(pid), service="interior")["milestones"] if m.get("gate"))
    expect("milestone later needs a reason", call("PUT", f"/projects/{pid}/milestones/{gm['id']}", {"due": day(210)}, T["pm"]), 409)
    expect("…with a reason", call("PUT", f"/projects/{pid}/milestones/{gm['id']}", {"due": day(210), "delay_reason": "authority"}, T["pm"]), 200)
    check("client party totals", any(x["party"] == "client" for x in call("GET", f"/projects/{pid}/delays", token=T["pm"])[1]["by_party"]))

    # move the tasks that depend on it too
    before_c = task_of(proj(pid), f"C {RUN}")
    r = expect("move A and its dependents", call("PUT", f"/projects/{pid}/tasks/{A['id']}", {"start": day(2), "end": day(5),
                                                                                             "shift_dependents": True,
                                                                                             "delay_reason": "labour"}, T["pm"]), 200)
    after_c = task_of(r, f"C {RUN}")
    delta = workdays.shift(day(1), day(2), CAL)
    check("dependent moved by the same working days", after_c["start"] == workdays.add_working(before_c["start"], delta, CAL)
          and after_c["end"] == workdays.add_working(before_c["end"], delta, CAL), (before_c["start"], after_c["start"]))
    check("'moved with' on the timeline", any("Moved with" in a["text"] for a in activity(pid, "Schedule & delays")["rows"]))

    # timeline filters
    sched = activity(pid, "Schedule & delays")["rows"]
    check("schedule filter holds schedule, baseline and delays only", sched and all(a["kind"] in ("schedule", "baseline", "delay") for a in sched))
    check("baseline on the timeline", any(a["kind"] == "baseline" and RUN in a["text"] for a in sched))
    check("team filter", any("added as Project Manager" in a["text"] for a in activity(pid, "Team")["rows"]))
    call("PUT", f"/projects/{pid}", {"description": f"Desc {RUN}"}, T["pm"])
    check("edits filter: details changed", any("description" in a["text"] for a in activity(pid, "Edits")["rows"]))
    expect("unknown filter", call("GET", f"/projects/{pid}/activity?group=Nope", token=T["owner"]), 400)
    check("timeline newest first", activity(pid)["rows"][0]["at"] >= activity(pid)["rows"][-1]["at"])

    # ===================== BLOCK 4 · meetings, waiting on whom, health, forecast =====================
    call("PUT", "/settings/email", {"host": "127.0.0.1", "port": 2528, "from_address": "crm@skyline.test", "use_tls": False}, T["owner"])
    vend = call("POST", "/contacts", {"name": f"Consultant {RUN}", "kind": "person", "types": ["consultant"],
                                      "email": f"cons{RUN}@x.test"}, T["owner"])[1]
    contacts.append(vend["id"])
    expect("meeting: title required", call("POST", f"/projects/{pid}/meetings", {"at": f"{day(1)}T10:00"}, T["pm"]), 400)
    expect("meeting: staff must be on the team", call("POST", f"/projects/{pid}/meetings", {"title": "x", "at": f"{day(1)}T10:00",
                                                                                           "staff": [U["sales"]]}, T["pm"]), 400)
    expect("view member cannot plan meetings", call("POST", f"/projects/{pid}/meetings", {"title": "x", "at": f"{day(1)}T10:00"}, T["designer"]), 403)
    at = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    m = expect("plan a meeting", call("POST", f"/projects/{pid}/meetings", {"title": f"Site review {RUN}", "at": at.strftime("%Y-%m-%dT%H:%M"),
                                                                           "place": "Site office", "staff": [U["pm"], U["designer"]],
                                                                           "contacts": [vend["id"]], "agenda": "Slab, tiles"}, T["owner"]), 201)
    check("attendees told", any(RUN in n["text"] for n in bell("designer", event="meeting_scheduled", project_id=pid)))
    at2 = at + timedelta(hours=2)
    call("PUT", f"/projects/{pid}/meetings/{m['id']}", {"at": at2.strftime("%Y-%m-%dT%H:%M")}, T["owner"])
    check("moved meeting: told again", any("Moved" in n["text"] for n in bell("designer", event="meeting_scheduled", project_id=pid)))
    worker(at2 - timedelta(hours=1))
    worker(at2 - timedelta(minutes=30))
    check("reminder in the last 2 hours, once", len([n for n in bell("designer", event="meeting_reminder", project_id=pid) if RUN in n["text"]]) == 1)
    expect("publish empty minutes refused", call("POST", f"/projects/{pid}/meetings/{m['id']}/publish", {}, T["owner"]), 400)
    call("PUT", f"/projects/{pid}/meetings/{m['id']}", {"notes": "Slab checked", "decisions": ["Use 600x600 tiles"],
                                                         "actions": [{"text": f"Order tiles {RUN}", "owner_id": U["designer"]}]}, T["owner"])
    expect("action without stage/date refused", call("POST", f"/projects/{pid}/meetings/{m['id']}/publish", {}, T["owner"]), 400)
    expect("action owner must be on the team", call("PUT", f"/projects/{pid}/meetings/{m['id']}", {"actions": [{"text": "x", "owner_id": U["sales"]}]}, T["owner"]), 400)
    call("PUT", f"/projects/{pid}/meetings/{m['id']}", {"actions": [{"text": f"Order tiles {RUN}", "owner_id": U["designer"],
                                                                      "stage_id": sid2, "due": day(6)}]}, T["owner"])
    pub = expect("publish minutes", call("POST", f"/projects/{pid}/meetings/{m['id']}/publish", {}, T["owner"]), 200)
    check("published", pub["status"] == "published" and pub["actions"][0]["task_id"])
    tk = task_of(proj(pid), f"Order tiles {RUN}")
    check("action became a task with owner, date and source", tk["assignee_id"] == U["designer"] and tk["end"] == day(6)
          and f"Site review {RUN}" in tk["notes"], tk)
    check("action owner told about the task", any(f"Order tiles {RUN}" in n["text"] for n in bell("designer", event="task_assigned", project_id=pid)))
    check("staff attendees told minutes are out", any(RUN in n["text"] for n in bell("designer", event="meeting_minutes", project_id=pid)))
    check("minutes emailed to staff and the consultant", pub["emailed"].get(f"cons{RUN}@x.test") == "sent"
          and pub["emailed"].get("designer@skyline.test") == "sent", pub["emailed"])
    check("email holds decisions and actions", any("Use 600x600 tiles" in x and f"Order tiles {RUN}" in x for x in mails))
    expect("published minutes are locked", call("PUT", f"/projects/{pid}/meetings/{m['id']}", {"notes": "x"}, T["owner"]), 409)
    expect("publish twice refused", call("POST", f"/projects/{pid}/meetings/{m['id']}/publish", {}, T["owner"]), 409)
    expect("PM cannot delete published minutes", call("DELETE", f"/projects/{pid}/meetings/{m['id']}", token=T["pm"]), 403)
    check("meetings on the timeline", len(activity(pid, "Meetings")["rows"]) >= 3)
    check("meetings listed", call("GET", f"/projects/{pid}/meetings", token=T["designer"])[1][0]["title"] == f"Site review {RUN}")

    # waiting on whom
    expect("bad waiting party", call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"status": "blocked", "waiting_on": {"party": "aliens"}}, T["pm"]), 400)
    call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"status": "blocked", "waiting_on": {"party": "client", "note": f"Tile choice {RUN}"}}, T["pm"])
    iss2 = call("POST", f"/projects/{pid}/issues", {"title": f"Permit {RUN}", "severity": "medium"}, T["pm"])[1]
    call("PUT", f"/projects/{pid}/issues/{iss2['id']}", {"waiting_on": {"party": "authority", "note": "Municipal visit"}}, T["pm"])
    w = expect("waiting list", call("GET", f"/projects/{pid}/waiting", token=T["designer"]), 200)
    kinds = {(r["kind"], r["party"]) for r in w["rows"]}
    check("blocked task waiting on the client", ("task", "client") in kinds, kinds)
    check("issue waiting on the authority", ("issue", "authority") in kinds, kinds)
    check("summary per party", {x["party"] for x in w["by_party"]} >= {"client", "authority"})
    allw = expect("across projects, client only", call("GET", "/waiting?party=client", token=T["pm"]), 200)
    check("cross-project list filtered", allw and all(r["party"] == "client" for r in allw) and any(r["project_id"] == pid for r in allw))
    pv = expect("client portal", call("GET", f"/portal/projects/{pid}", token=T["client"]), 200)
    check("portal: waiting on you", any(f"C {RUN}" in r["title"] and r["note"] == f"Tile choice {RUN}" for r in pv["waiting_on_you"]), pv.get("waiting_on_you"))
    check("portal: nothing for other parties", all("Permit" not in r["title"] for r in pv["waiting_on_you"]))
    call("PUT", f"/projects/{pid}/tasks/{C['id']}", {"status": "todo"}, T["pm"])
    check("unblocked: no longer waiting", not any(r["kind"] == "task" and f"C {RUN}" in r["title"]
                                                  for r in call("GET", f"/projects/{pid}/waiting", token=T["pm"])[1]["rows"]))

    # health and forecast
    h = expect("health", call("GET", f"/projects/{pid}/health", token=T["designer"]), 200)
    check("six parts adding up to the score", len(h["parts"]) == 6 and sum(x["points"] for x in h["parts"]) == h["score"]
          and sum(x["max"] for x in h["parts"]) == 100, h)
    check("each part says why", all(x["why"] for x in h["parts"]))
    old = call("POST", "/projects", {"name": f"Depth {RUN} late", "services": ["construction"], "start": day(-30)}, T["owner"])[1]
    projects.append(old["id"])
    s0 = old["stages"][0]
    call("PUT", f"/projects/{old['id']}/stages/{s0['id']}", {"start": day(-30), "end": day(-2), "progress": 25}, T["owner"])
    fc = call("GET", f"/projects/{old['id']}/health", token=T["owner"])[1]["forecast"]
    st0 = next(x for x in fc["stages"] if x["id"] == s0["id"])
    check("forecast: 25% in a month means late", st0["late_days"] > 0 and st0["forecast"] > day(-2), st0)
    check("forecast message in plain words", "finishes" in fc["message"] and s0["name"] in fc["message"], fc["message"])
    for i in range(3):
        call("POST", f"/projects/{old['id']}/issues", {"title": f"High {RUN} {i}", "severity": "high"}, T["owner"])
    r = call("POST", f"/projects/{old['id']}/stages/{old['stages'][1]['id']}/tasks", {"title": f"Late {RUN}", "start": day(-20), "end": day(-10)}, T["owner"])
    call("PUT", f"/projects/{old['id']}/tasks/{task_of(r[1], f'Late {RUN}')['id']}", {"status": "blocked"}, T["owner"])
    h2 = call("GET", f"/projects/{old['id']}/health", token=T["owner"])[1]
    check("troubled project goes red", h2["grade"] == "red" and h2["score"] < 50, (h2["score"], [(x["key"], x["points"]) for x in h2["parts"]]))
    lst = call("GET", "/projects", token=T["owner"])[1]
    row = next(x for x in lst if x["id"] == old["id"])
    check("projects list shows health", row["health"]["grade"] == "red")
    home = call("GET", "/home", token=T["owner"])[1]
    check("home lists projects at risk", any(x["id"] == old["id"] for x in home.get("projects_at_risk", [])))
    call("POST", f"/projects/{old['id']}/team", {"user_id": U["pm"], "project_role": "Project Manager", "access": "edit"}, T["owner"])
    worker()
    worker()
    check("turned red: managers told once", len([n for n in bell("pm", event="project_at_risk") if old["id"] in (n.get("project_id") or "")]) == 1)
    check("grade remembered", mongo.projects.find_one({"_id": ObjectId(old["id"])})["health_grade"] == "red")

    # deleting a project removes its comments, timeline, meetings and delays
    call("DELETE", f"/projects/{pid}", token=T["owner"])
    projects.remove(pid)
    left = sum(mongo[c].count_documents({"company_id": CID, "project_id": pid})
               for c in ("project_comments", "project_activity", "project_meetings", "project_delays", "notifications"))
    check("project delete cascades", left == 0, left)
finally:
    for p_ in projects:
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for c_ in contacts:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"email_settings": company_before.get("email_settings") or {}}})
    if company_before.get("calendar"):
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"calendar": company_before["calendar"]}})
    else:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"calendar": ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.contacts.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.project_activity.count_documents({"company_id": CID, "text": {"$regex": RUN}})
    check("cleanup: nothing left", left == 0, left)
    smtp.shutdown()

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
