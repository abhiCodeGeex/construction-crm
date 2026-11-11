"""Phase F — documents and drawings, selections, daily site reports. One block per row of PLAN.md F1.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_f.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

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


def fetch(path, token):
    """Status of a file download (binary, not JSON)."""
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


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
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + b"\x89PNG\r\n\x1a\n" + b"0" * 64 + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/uploads", method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement")}
T["client"] = login("client@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"document_folders": 1, "site_settings": 1})
projects, keys, contacts_made, rates_made = [], [], [], []


def bell(user, **q):
    return list(mongo.notifications.find({"company_id": CID, "user_id": U[user], **q}))


def worker(now=None):
    from app import create_app
    from app.worker import run_once
    with create_app().app_context():
        run_once(now)


def up(name, who="pm"):
    f = upload(f"{name}{RUN}.png", T[who])
    keys.append(f["key"])
    return f["key"]


try:
    p = expect("project", call("POST", "/projects", {"name": f"PhaseF {RUN}", "services": ["architecture", "construction", "interior"],
                                                     "start": day(-20), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    for who, role, acc in (("pm", "Project Manager", "edit"), ("designer", "Architect", "edit"), ("site", "Site Supervisor", "view")):
        call("POST", f"/projects/{pid}/team", {"user_id": U[who], "project_role": role, "access": acc}, T["owner"])
    p = call("GET", f"/projects/{pid}", token=T["owner"])[1]
    arch = next(s for s in p["stages"] if s["service"] == "architecture")
    cons = next(s for s in p["stages"] if s["service"] == "construction")

    # ================= block 1 · document library =================
    lib = expect("library", call("GET", f"/projects/{pid}/documents", token=T["pm"]), 200)
    check("folders: every project + each service's", all(f in lib["folders"] for f in ("Contract", "Client documents", "Concept", "Structural", "Layouts"))
          and lib["virtual_folders"] == ["From the lead", "Task files"] and lib["can_write"], lib["folders"])
    expect("sales not on the project: not found", call("GET", f"/projects/{pid}/documents", token=T["sales"]), 404)
    expect("accounts has no document access", call("GET", f"/projects/{pid}/documents", token=T["accounts"]), 403)
    k0 = up("plan-r0")
    base = {"folder": "Drawings", "name": f"Ground floor plan {RUN}", "kind": "drawing", "number": "A-101", "stage_id": arch["id"], "file_key": k0}
    expect("folder must exist", call("POST", f"/projects/{pid}/documents", {**base, "folder": "Snacks"}, T["pm"]), 400)
    expect("file must be uploaded", call("POST", f"/projects/{pid}/documents", {**base, "file_key": "nope"}, T["pm"]), 400)
    expect("site cannot add documents", call("POST", f"/projects/{pid}/documents", base, T["site"]), 403)
    doc = expect("designer adds a drawing", call("POST", f"/projects/{pid}/documents", base, T["designer"]), 201)
    check("first revision R0, stage kept", doc["current_rev"] == "R0" and doc["stage_name"] == arch["name"] and doc["current"]["file_key"] == k0, doc)
    expect("a file goes in the library once", call("POST", f"/projects/{pid}/documents", {**base, "name": "dup"}, T["pm"]), 409)
    check("site can read the library", any(d["id"] == doc["id"] for d in call("GET", f"/projects/{pid}/documents", token=T["site"])[1]["documents"]))
    k1 = up("plan-r1")
    doc = expect("new revision", call("POST", f"/documents/{doc['id']}/versions", {"file_key": k1, "note": "Kitchen moved"}, T["pm"]), 201)
    check("R1 current, R0 kept", doc["current_rev"] == "R1" and [v["rev"] for v in doc["versions"]] == ["R0", "R1"] and doc["versions"][1]["note"] == "Kitchen moved")
    check("old revision still downloadable", fetch(f"/files/{k0}", T["site"]) == 200)
    doc = expect("remove R0", call("DELETE", f"/documents/{doc['id']}/versions/R0", token=T["pm"]), 200)
    check("R0 file deleted (quota freed)", not mongo.files.find_one({"key": k0}) and fetch(f"/files/{k0}", T["pm"]) == 404 and doc["current_rev"] == "R1")
    expect("the only revision stays", call("DELETE", f"/documents/{doc['id']}/versions/R1", token=T["pm"]), 409)
    k2 = up("plan-r2")
    doc = expect("next revision after a removal", call("POST", f"/documents/{doc['id']}/versions", {"file_key": k2}, T["pm"]), 201)
    check("numbering continues: R2", doc["current_rev"] == "R2")
    doc = expect("edit: shared with the client, folder", call("PUT", f"/documents/{doc['id']}", {"shared": True, "folder": "Approvals"}, T["designer"]), 200)
    check("edited", doc["shared"] is True and doc["folder"] == "Approvals")
    expect("bad kind", call("PUT", f"/documents/{doc['id']}", {"kind": "poem"}, T["pm"]), 400)

    # task files are listed, not copied
    t1 = expect("task", call("POST", f"/projects/{pid}/stages/{cons['id']}/tasks", {"title": f"Footing {RUN}", "start": day(0), "end": day(3)}, T["pm"]), 201)
    t1 = next(tk for s in t1["stages"] for tk in s["tasks"] if tk["title"] == f"Footing {RUN}")
    kt = up("site-photo")
    call("POST", f"/projects/{pid}/tasks/{t1['id']}/files", {"key": kt}, T["pm"])
    lib = call("GET", f"/projects/{pid}/documents", token=T["pm"])[1]
    check("task files listed under Task files", any(f["key"] == kt and f["task"] == f"Footing {RUN}" for f in lib["task_files"]))
    check("stored once", mongo.files.count_documents({"key": kt}) == 1 and not mongo.documents.find_one({"versions.file_key": kt}))

    # Settings -> document folders
    expect("folder twice", call("PUT", "/settings/document-folders", {"all": ["A", "a"]}, T["owner"]), 400)
    expect("automatic folder names reserved", call("PUT", "/settings/document-folders", {"all": ["From the lead"]}, T["owner"]), 400)
    expect("PM cannot change company folders", call("PUT", "/settings/document-folders", {"all": ["X"]}, T["pm"]), 403)
    expect("owner sets folders", call("PUT", "/settings/document-folders", {"all": ["Contract", f"Handover {RUN}"], "architecture": ["Drawings", "Approvals"],
                                                                           "construction": ["Structural"], "interior": ["Layouts"]}, T["owner"]), 200)
    check("project folders follow", f"Handover {RUN}" in call("GET", f"/projects/{pid}/documents", token=T["pm"])[1]["folders"])

    k3 = up("spec")
    d2 = expect("a spec to delete", call("POST", f"/projects/{pid}/documents", {"folder": "Contract", "name": f"Spec {RUN}", "kind": "specification", "file_key": k3}, T["pm"]), 201)
    expect("delete the document", call("DELETE", f"/documents/{d2['id']}", token=T["pm"]), 200)
    check("its files are gone", not mongo.files.find_one({"key": k3}))

    # ================= block 2 · drawing register and transmittals =================
    expect("a drawing needs a number", call("POST", f"/projects/{pid}/documents", {"folder": "Drawings", "name": "x", "kind": "drawing", "file_key": up("nonum")}, T["pm"]), 400)
    expect("drawing numbers are unique on the project", call("POST", f"/projects/{pid}/documents", {"folder": "Drawings", "name": "x", "kind": "drawing",
                                                                                                  "number": "a-101", "file_key": up("dupnum")}, T["pm"]), 409)
    check("superseded on a new revision", [v.get("status") for v in doc["versions"]] == ["superseded", "wip"], [v.get("status") for v in doc["versions"]])
    expect("bad status", call("PUT", f"/documents/{doc['id']}/status", {"status": "done"}, T["designer"]), 400)
    expect("site cannot set status", call("PUT", f"/documents/{doc['id']}/status", {"status": "for_approval"}, T["site"]), 403)
    expect("for approval", call("PUT", f"/documents/{doc['id']}/status", {"status": "for_approval"}, T["designer"]), 200)
    expect("approved", call("PUT", f"/documents/{doc['id']}/status", {"status": "approved"}, T["designer"]), 200)
    check("PM told the drawing is approved", any("A-101" in n["text"] for n in bell("pm", event="drawing_approved")))
    reg = expect("drawing register", call("GET", f"/projects/{pid}/drawing-register", token=T["site"]), 200)
    row = next(r for r in reg["drawings"] if r["number"] == "A-101")
    check("register: number, current revision, status, not issued yet", row["rev"] == "R2" and row["status"] == "approved" and row["last_issued"] is None, row)

    tl = call("GET", f"/projects/{pid}/transmittals", token=T["pm"])[1]
    client_person = next(x for x in tl["people"] if x["role"] == "Client")
    tbody = {"to": [client_person["contact_id"]], "purpose": "for_approval", "documents": [doc["id"]], "note": f"Please approve {RUN}"}
    expect("purpose required", call("POST", f"/projects/{pid}/transmittals", {**tbody, "purpose": "because"}, T["pm"]), 400)
    expect("only people on the project", call("POST", f"/projects/{pid}/transmittals", {**tbody, "to": [str(ObjectId())]}, T["pm"]), 400)
    expect("documents required", call("POST", f"/projects/{pid}/transmittals", {**tbody, "documents": []}, T["pm"]), 400)
    expect("site cannot issue", call("POST", f"/projects/{pid}/transmittals", tbody, T["site"]), 403)
    tr = expect("issue to the client", call("POST", f"/projects/{pid}/transmittals", tbody, T["designer"]), 201)
    check("numbered TRN, the revision recorded, email result kept per person", tr["number"].startswith("TRN") and tr["items"][0]["rev"] == "R2"
          and client_person["contact_id"] in tr["emailed"], tr)
    d_after = mongo.documents.find_one({"_id": ObjectId(doc["id"])})
    check("the revision shows where it went", d_after["versions"][-1]["sent"][0]["number"] == tr["number"])
    expect("a sent revision cannot be removed", call("DELETE", f"/documents/{doc['id']}/versions/R2", token=T["pm"]), 409)
    expect("a document with a sent revision is kept", call("DELETE", f"/documents/{doc['id']}", token=T["owner"]), 409)
    reg = call("GET", f"/projects/{pid}/drawing-register", token=T["pm"])[1]
    check("register shows the issue", next(r for r in reg["drawings"] if r["number"] == "A-101")["last_issued_rev"] == "R2")
    pj = call("GET", f"/projects/{pid}", token=T["owner"])[1]
    item = next(c for c in next(x for x in pj["stages"] if x["id"] == arch["id"])["checklist"] if c["text"].lower().startswith("drawings issued"))
    check("stage check offered, not ticked", item.get("suggested", {}).get("number") == tr["number"] and not item["done"], item)
    doc = expect("revision after issue", call("POST", f"/documents/{doc['id']}/versions", {"file_key": up("plan-r3")}, T["designer"]), 201)
    check("R2 kept and superseded, R3 in progress", doc["versions"][-2]["rev"] == "R2" and doc["versions"][-2]["status"] == "superseded"
          and doc["status"] == "wip")
    expect("acknowledge: who", call("POST", f"/transmittals/{tr['id']}/acknowledge", {}, T["pm"]), 400)
    ack = expect("acknowledged", call("POST", f"/transmittals/{tr['id']}/acknowledge", {"by": "Client Co."}, T["pm"]), 200)
    check("acknowledgement kept", ack["acknowledged"]["by"] == "Client Co.")
    expect("acknowledged once", call("POST", f"/transmittals/{tr['id']}/acknowledge", {"by": "x"}, T["pm"]), 409)
    tr2 = expect("issue for comment", call("POST", f"/projects/{pid}/transmittals", {**tbody, "purpose": "for_comment", "email": False}, T["pm"]), 201)
    mongo.transmittals.update_one({"_id": ObjectId(tr2["id"])}, {"$set": {"created_at": mongo.transmittals.find_one({"_id": ObjectId(tr2["id"])})["created_at"] - timedelta(days=8)}})
    worker()
    worker()
    check("not acknowledged in 7 days: sender reminded once", len([n for n in bell("pm", event="transmittal_waiting") if tr2["number"] in n["text"]]) == 1)

    # ================= block 3 · selections =================
    intr = next(x for x in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if x["service"] == "interior")
    sup = expect("supplier", call("POST", "/contacts", {"name": f"Stone Co {RUN}", "kind": "company", "types": ["supplier"], "phone": f"95{RUN}"}, T["owner"]), 201)
    contacts_made.append(sup["id"])
    rate = expect("product in the rate library", call("POST", "/rates", {"kind": "product", "name": f"Quartz slab {RUN}", "unit": "slab", "rate": 55000,
                                                                          "brand": "Caesarstone"}, T["owner"]), 201)
    rates_made.append(rate["id"])
    expect("site has no selections", call("GET", f"/projects/{pid}/selections", token=T["site"]), 403)
    expect("item required", call("POST", f"/projects/{pid}/selections", {"stage_id": intr["id"]}, T["designer"]), 400)
    expect("stage required", call("POST", f"/projects/{pid}/selections", {"stage_id": "x", "item": "y"}, T["designer"]), 400)
    sel = expect("designer adds a selection", call("POST", f"/projects/{pid}/selections", {"stage_id": intr["id"], "item": f"Kitchen countertop {RUN}",
                                                                                         "room": "Kitchen", "allowance": 50000}, T["designer"]), 201)
    empty = call("POST", f"/projects/{pid}/selections", {"stage_id": intr["id"], "item": f"Empty {RUN}"}, T["designer"])[1]
    expect("send needs options", call("POST", f"/selections/{empty['id']}/send", {}, T["designer"]), 400)
    expect("bad product", call("PUT", f"/selections/{sel['id']}", {"options": [{"name": "x", "rate_id": str(ObjectId())}]}, T["designer"]), 400)
    sel = expect("options", call("PUT", f"/selections/{sel['id']}", {"options": [
        {"name": "Granite", "qty": 1, "unit_cost": 40000, "unit_price": 48000, "lead_days": 10},
        {"name": "Quartz", "qty": 1, "unit_cost": 55000, "unit_price": 65000, "lead_days": 20, "supplier_id": sup["id"], "rate_id": rate["id"]}]}, T["designer"]), 200)
    quartz = sel["options"][1]
    check("option from the rate library and supplier", quartz["unit"] == "slab" and quartz["brand"] == "Caesarstone" and quartz["supplier_name"] == sup["name"], quartz)
    expected_due = (date.fromisoformat(intr["start"]) - timedelta(days=20)).isoformat()
    check("choice due = stage start minus the longest lead time", sel["due_date"] == expected_due, (sel["due_date"], expected_due))
    sent = expect("send the options", call("POST", f"/selections/{sel['id']}/send", {}, T["designer"]), 200)
    check("options sent, email result kept", sent["status"] == "options_sent" and sent["emailed"])
    expect("choice: how", call("POST", f"/selections/{sel['id']}/choice", {"option_id": quartz["id"], "name": "Mrs C"}, T["designer"]), 400)
    expect("choice: one of the options", call("POST", f"/selections/{sel['id']}/choice", {"option_id": "nope", "name": "Mrs C", "method": "Email"}, T["designer"]), 400)
    ch = expect("client chose quartz", call("POST", f"/selections/{sel['id']}/choice", {"option_id": quartz["id"], "name": "Mrs C", "method": "WhatsApp"}, T["designer"]), 200)
    check("chosen, difference over the allowance", ch["status"] == "chosen" and ch["difference"] == 15000 and ch["choice"]["method"] == "WhatsApp", ch.get("difference"))
    check("PM told of the choice", any(f"Kitchen countertop {RUN}" in n["text"] for n in bell("pm", event="selection_chosen")))
    expect("a chosen item is not edited", call("PUT", f"/selections/{sel['id']}", {"allowance": 1}, T["designer"]), 409)
    lst = call("GET", f"/projects/{pid}/selections", token=T["pm"])[1]
    check("summary: allowance, chosen, difference", lst["summary"]["difference"] == 15000 and lst["summary"]["chosen"] == 65000, lst["summary"])
    co = expect("over the allowance: change order", call("POST", f"/selections/{sel['id']}/change-order", {}, T["designer"]), 201)
    check("change order for the difference, cost in the option's ratio", co["change_order"]["totals"]["price"] == 15000
          and abs(co["change_order"]["totals"]["cost"] - 15000 * 55000 / 65000) < 0.02 and co["change_order"]["status"] == "draft", co["change_order"]["totals"])
    expect("one change order per item", call("POST", f"/selections/{sel['id']}/change-order", {}, T["designer"]), 409)
    expect("reopen needs a reason", call("POST", f"/selections/{sel['id']}/reopen", {}, T["designer"]), 400)
    ro = expect("reopen", call("POST", f"/selections/{sel['id']}/reopen", {"reason": "Client changed mind"}, T["designer"]), 200)
    check("reopened: choice cleared, history kept", ro["status"] == "options_sent" and ro["chosen"] is None and ro["history"][-1]["was"] == "Quartz")
    granite = sel["options"][0]
    call("POST", f"/selections/{sel['id']}/choice", {"option_id": granite["id"], "name": "Mrs C", "method": "In person"}, T["designer"])
    expect("within the allowance: no change order", call("POST", f"/selections/{sel['id']}/change-order", {}, T["designer"]), 409)
    expect("forward only (chosen -> ordered skips confirm)", call("POST", f"/selections/{sel['id']}/status", {"status": "ordered"}, T["designer"]), 409)
    expect("confirmed", call("POST", f"/selections/{sel['id']}/status", {"status": "confirmed"}, T["designer"]), 200)
    od = expect("PM orders it", call("POST", f"/selections/{sel['id']}/status", {"status": "ordered"}, T["pm"]), 200)
    cst = mongo.costs.find_one({"company_id": CID, "selection_id": sel["id"]})
    check("ordering records the cost in Finance", cst and cst["amount"] == 40000 and od["cost_id"] == str(cst["_id"]) and cst["status"] in ("submitted", "approved"), cst)
    call("DELETE", f"/selections/{empty['id']}", token=T["designer"])
    expect("installed", call("POST", f"/selections/{sel['id']}/status", {"status": "installed"}, T["designer"]), 200)
    item = next(c for c in next(x for x in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if x["id"] == intr["id"])["checklist"]
                if "selection" in c["text"].lower())
    check("all installed: the stage check is offered, not ticked", item.get("suggested") and not item["done"], item)
    late = call("POST", f"/projects/{pid}/selections", {"stage_id": intr["id"], "item": f"Wallpaper {RUN}", "due_date": day(-2)}, T["designer"])[1]
    w = call("GET", f"/projects/{pid}/waiting", token=T["pm"])[1]
    check("a late choice is waiting on the client", any(r["kind"] == "selection" and r["party"] == "client" and f"Wallpaper {RUN}" in r["title"] for r in w["rows"]), w["rows"])
    worker()
    worker()
    check("late choice: PM reminded once", len([n for n in bell("pm", event="selection_due") if f"Wallpaper {RUN}" in n["text"]]) == 1)
    mine = next(x for x in call("GET", f"/projects/{pid}/selections", token=T["designer"])[1]["selections"] if x["id"] == sel["id"])
    check("designer (finance read) sees the option cost", "unit_cost" in mine["options"][0] and "cost" in mine["options"][0])

    # ================= block 4 · daily site reports, portal =================
    from datetime import datetime as _dt
    from app.services import workdays as _wd  # noqa: E402
    CAL = call("GET", "/settings/calendar", token=T["owner"])[1]
    expect("designer has no site reports", call("GET", f"/projects/{pid}/site-reports", token=T["designer"]), 403)
    sl = expect("site supervisor's list", call("GET", f"/projects/{pid}/site-reports", token=T["site"]), 200)
    check("site supervisor can write", sl["can_write"] and not sl["has_today"])
    expect("no future report", call("POST", f"/projects/{pid}/site-reports", {"date": day(1)}, T["site"]), 400)
    expect("no old report by the site", call("POST", f"/projects/{pid}/site-reports", {"date": day(-3)}, T["site"]), 409)
    expect("work needs a stage", call("POST", f"/projects/{pid}/site-reports", {"work": [{"stage_id": "x", "note": "y"}]}, T["site"]), 400)
    ph = up("site-day")
    rep = expect("today's report", call("POST", f"/projects/{pid}/site-reports", {
        "weather": {"kind": "Rain", "note": "Light showers"}, "manpower": [{"trade": "Mason", "count": 4}, {"trade": "Helper", "count": 2}],
        "work": [{"stage_id": cons["id"], "note": f"Footing excavation {RUN}"}], "materials": "Cement 50 bags",
        "photos": [{"key": ph, "caption": "Excavation", "shareable": True}]}, T["site"]), 201)
    check("headcount and weather", rep["headcount"] == 6 and rep["weather"]["kind"] == "Rain" and rep["editable"], rep)
    expect("one report a day", call("POST", f"/projects/{pid}/site-reports", {}, T["site"]), 409)
    expect("bad weather", call("PUT", f"/site-reports/{rep['id']}", {"weather": {"kind": "Snowstorm"}}, T["site"]), 400)
    expect("edit today", call("PUT", f"/site-reports/{rep['id']}", {"visitors": "Structural consultant"}, T["site"]), 200)
    pj = call("GET", f"/projects/{pid}", token=T["owner"])[1]
    photo_item = next(c for c in next(x for x in pj["stages"] if x["id"] == cons["id"])["checklist"] if "photo" in c["text"].lower())
    check("photos of a construction stage offer its check", photo_item.get("suggested") and not photo_item["done"], photo_item)
    expect("issue needs a title", call("POST", f"/site-reports/{rep['id']}/issues", {}, T["site"]), 400)
    ri = expect("issue from the site", call("POST", f"/site-reports/{rep['id']}/issues", {"title": f"Water logging {RUN}", "severity": "high",
                                                                                        "stage_id": cons["id"]}, T["site"]), 201)
    iss = mongo.project_issues.find_one({"company_id": CID, "site_report_id": rep["id"]})
    check("became a project issue", iss and iss["severity"] == "high" and ri["issues"][0]["issue_id"] == str(iss["_id"]))
    check("managers told of the high issue", any(f"Water logging {RUN}" in n["text"] for n in bell("pm", event="issue_raised")))
    gate = next(x for x in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if x["id"] == cons["id"])["gate"]
    check("the high issue holds the stage gate", any("high-severity" in m for m in gate["missing"]), gate)
    before = next(x for x in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if x["id"] == cons["id"])["end"]
    expect("delay needs a reason", call("POST", f"/site-reports/{rep['id']}/delays", {"stage_id": cons["id"], "days": 1}, T["site"]), 400)
    rd = expect("delay from the site", call("POST", f"/site-reports/{rep['id']}/delays", {"reason": "weather", "stage_id": cons["id"], "days": 1,
                                                                                        "note": f"Rain {RUN}"}, T["site"]), 201)
    dl = mongo.project_delays.find_one({"company_id": CID, "site_report_id": rep["id"]})
    check("in the delay log with the report as source", dl and dl["source"] == "site_report" and dl["reason"] == "weather" and rd["delays"][0]["days"] == 1)
    check("the plan does not move", next(x for x in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if x["id"] == cons["id"])["end"] == before)
    check("PM told to review the plan", any(f"Rain" in n["text"] or "lost 1" in n["text"] for n in bell("pm", event="site_delay")))
    mongo.site_reports.update_one({"_id": ObjectId(rep["id"])}, {"$set": {"date": day(-3)}})
    expect("locked after the next day", call("PUT", f"/site-reports/{rep['id']}", {"visitors": "x"}, T["site"]), 409)
    expect("an Owner can still correct it", call("PUT", f"/site-reports/{rep['id']}", {"visitors": "Corrected"}, T["owner"]), 200)
    mongo.site_reports.update_one({"_id": ObjectId(rep["id"])}, {"$set": {"date": day(0)}})
    dayv = expect("today's reports across projects", call("GET", "/site-reports", token=T["site"]), 200)
    check("this project reported today", any(r["project_id"] == pid and r["report"] for r in dayv["rows"]))
    expect("cut-off: a time", call("PUT", "/settings/site", {"cutoff": "7pm"}, T["owner"]), 400)
    expect("PM cannot set the cut-off", call("PUT", "/settings/site", {"cutoff": "18:30"}, T["pm"]), 403)
    expect("owner sets the cut-off", call("PUT", "/settings/site", {"cutoff": "18:30"}, T["owner"]), 200)

    # missing report: a second active project with a supervisor and no report
    p2 = expect("second project", call("POST", "/projects", {"name": f"PhaseF quiet {RUN}", "services": ["construction"], "start": day(-20)}, T["owner"]), 201)
    projects.append(p2["id"])
    call("POST", f"/projects/{p2['id']}/team", {"user_id": U["site"], "project_role": "Site Supervisor", "access": "view"}, T["owner"])
    call("POST", f"/projects/{p2['id']}/team", {"user_id": U["pm"], "project_role": "Project Manager", "access": "edit"}, T["owner"])
    today_ = date.today()
    worker(_dt(today_.year, today_.month, today_.day, 17, 45))  # 23:15 local (UTC+5:30), after the cut-off
    worker(_dt(today_.year, today_.month, today_.day, 17, 50))
    miss = [n for n in bell("site", event="site_report_missing") if f"PhaseF quiet {RUN}" in n["text"] and "today" in n["text"]]
    if _wd.is_working(today_.isoformat(), CAL):
        check("no report by the cut-off: supervisor told once", len(miss) == 1, [n["text"] for n in miss])
    check("a project that reported is quiet", not [n for n in bell("site", event="site_report_missing") if f"PhaseF {RUN}:" in n["text"]])
    yday = (today_ - timedelta(days=1)).isoformat()
    if _wd.is_working(yday, CAL):
        check("still none the next day: managers told", any(yday in n["text"] and f"PhaseF quiet {RUN}" in n["text"] for n in bell("pm", event="site_report_missing")))

    # the client portal (read only)
    pp = expect("client: shareable photos", call("GET", f"/portal/projects/{pid}/photos", token=T["client"]), 200)
    check("only shareable photos", len(pp["photos"]) == 1 and pp["photos"][0]["caption"] == "Excavation")
    pdocs = expect("client: documents", call("GET", f"/portal/projects/{pid}/documents", token=T["client"]), 200)
    a101 = next((x for x in pdocs if x["number"] == "A-101"), None)
    check("a shared drawing: the current revision", a101 and a101["rev"] == "R3", pdocs)
    expect("un-share the drawing", call("PUT", f"/documents/{doc['id']}", {"shared": False}, T["pm"]), 200)
    pdocs = call("GET", f"/portal/projects/{pid}/documents", token=T["client"])[1]
    a101 = next((x for x in pdocs if x["number"] == "A-101"), None)
    check("not shared: the latest revision issued to the client (R3 went out for comment)", a101 and a101["rev"] == "R3", pdocs)
    mongo.documents.update_one({"_id": ObjectId(doc["id"])}, {"$set": {"versions.2.sent": []}})  # as if R3 had not been issued
    pdocs = call("GET", f"/portal/projects/{pid}/documents", token=T["client"])[1]
    check("…then the client sees R2, the revision issued to them", next((x for x in pdocs if x["number"] == "A-101"), {}).get("rev") == "R2", pdocs)
    psel = expect("client: selections", call("GET", f"/portal/projects/{pid}/selections", token=T["client"]), 200)
    opts = [o for x in psel for o in x["options"]]
    check("selections with prices, never cost", opts and all("cost" not in o and "unit_cost" not in o for o in opts) and any(o["price"] for o in opts), psel[:1])
finally:
    for p_ in projects:
        mongo.costs.update_many({"company_id": CID, "project_id": p_}, {"$set": {"status": "void"}})
        for d_ in mongo.documents.find({"company_id": CID, "project_id": p_}):  # sent revisions are kept by the app; the test removes them
            mongo.documents.update_one({"_id": d_["_id"]}, {"$set": {"versions": [{**v, "sent": []} for v in d_["versions"]]}})
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for k in keys:
        mongo.files.delete_one({"key": k})
    mongo.change_orders.delete_many({"company_id": CID, "project_id": {"$in": projects}})
    for c_ in contacts_made:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    for r_ in rates_made:
        mongo.rate_library.delete_one({"_id": ObjectId(r_)})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    for f in ("document_folders", "site_settings"):
        if company_before.get(f) is not None:
            mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {f: company_before[f]}})
        else:
            mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {f: ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.documents.count_documents({"company_id": CID, "project_id": {"$in": projects}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
