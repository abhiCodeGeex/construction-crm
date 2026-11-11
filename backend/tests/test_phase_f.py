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
projects, keys = [], []


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
finally:
    for p_ in projects:
        mongo.costs.update_many({"company_id": CID, "project_id": p_}, {"$set": {"status": "void"}})
        for d_ in mongo.documents.find({"company_id": CID, "project_id": p_}):  # sent revisions are kept by the app; the test removes them
            mongo.documents.update_one({"_id": d_["_id"]}, {"$set": {"versions": [{**v, "sent": []} for v in d_["versions"]]}})
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for k in keys:
        mongo.files.delete_one({"key": k})
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
