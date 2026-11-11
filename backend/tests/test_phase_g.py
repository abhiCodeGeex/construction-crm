"""Phase G — client portal approvals, invoices and online payments, message threads, WhatsApp. One block per row of PLAN.md G1.
Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_g.py
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
T["consultant"] = login("consultant@skyline.test")
T["subcontractor"] = login("subcontractor@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
CONSULT_CONTACT = mongo.users.find_one({"email": "consultant@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"document_folders": 1, "site_settings": 1, "payments": 1, "messaging": 1})
client_before = mongo.contacts.find_one({"_id": ObjectId(mongo.users.find_one({"email": "client@skyline.test"})["contact_id"])},
                                        {"phone": 1, "whatsapp_opt_in": 1, "whatsapp_opt_out": 1})
projects, keys, contacts_made, rates_made = [], [], [], []
tpls = []
SIG = "data:image/png;base64," + "iVBORw0KGgo" * 40


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
    p = expect("project", call("POST", "/projects", {"name": f"PhaseG {RUN}", "services": ["architecture", "interior"],
                                                     "start": day(-20), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    pid = p["id"]
    projects.append(pid)
    call("POST", f"/projects/{pid}/team", {"user_id": U["pm"], "project_role": "Project Manager", "access": "edit"}, T["owner"])
    expect("consultant on the team", call("POST", f"/projects/{pid}/team", {"contact_id": CONSULT_CONTACT, "project_role": "Consultant"}, T["pm"]), 201)
    p = call("GET", f"/projects/{pid}", token=T["owner"])[1]
    arch = next(s for s in p["stages"] if s["service"] == "architecture")
    intr = next(s for s in p["stages"] if s["service"] == "interior")

    # ================= block 1 · approvals in the portal =================
    expect("not on the team: 404", call("GET", f"/portal/projects/{pid}/actions", token=T["subcontractor"]), 404)
    act = expect("client's actions", call("GET", f"/portal/projects/{pid}/actions", token=T["client"]), 200)
    check("no sign-off asked while work is open", act["role"] == "Client" and not act["signoffs"], act["signoffs"])
    call("PUT", f"/projects/{pid}/stages/{arch['id']}", {"progress": 100}, T["pm"])
    for c in arch["checklist"]:
        call("PUT", f"/projects/{pid}/stages/{arch['id']}/checklist/{c['id']}", {"done": True}, T["pm"])
    act = call("GET", f"/portal/projects/{pid}/actions", token=T["client"])[1]
    check("sign-off asked once only the client's sign-off is missing", [x["stage_id"] for x in act["signoffs"]] == [arch["id"]], act["signoffs"])
    expect("sign-off: tick required", call("POST", f"/portal/projects/{pid}/stages/{arch['id']}/signoff", {"name": "Mrs Client"}, T["client"]), 400)
    expect("consultant cannot sign off", call("POST", f"/portal/projects/{pid}/stages/{arch['id']}/signoff", {"name": "x", "agree": True}, T["consultant"]), 403)
    expect("client signs off", call("POST", f"/portal/projects/{pid}/stages/{arch['id']}/signoff", {"name": f"Mrs Client {RUN}", "agree": True}, T["client"]), 201)
    so = next(s for s in call("GET", f"/projects/{pid}", token=T["owner"])[1]["stages"] if s["id"] == arch["id"])["signoff"]
    check("recorded as Portal with who, IP and time", so["method"] == "Portal" and so["name"] == f"Mrs Client {RUN}" and so.get("ip") is not None
          and so["contact_id"] == CLIENT_CONTACT, so)
    check("PM told", any(f"Mrs Client {RUN}" in n["text"] for n in bell("pm", event="signoff_recorded")))
    expect("signed once", call("POST", f"/portal/projects/{pid}/stages/{arch['id']}/signoff", {"name": "x", "agree": True}, T["client"]), 409)
    expect("staff cannot pick Portal as a method", call("POST", f"/projects/{pid}/stages/{intr['id']}/signoff", {"name": "x", "method": "Portal"}, T["pm"]), 400)

    # change orders
    co = call("POST", f"/projects/{pid}/change_orders", {"stage_id": intr["id"], "title": f"Extra wardrobe {RUN}", "reason": "client_request",
                                                        "lines": [{"description": "Wardrobe", "qty": 1, "cost_rate": 30000, "price_rate": 45000}], "time_days": 2}, T["pm"])[1]
    call("POST", f"/change_orders/{co['id']}/price", {}, T["pm"])
    call("POST", f"/change_orders/{co['id']}/send", {}, T["pm"])
    oe = call("POST", f"/projects/{pid}/change_orders", {"stage_id": intr["id"], "title": f"Our slip {RUN}", "reason": "our_error",
                                                        "lines": [{"description": "Rework", "qty": 1, "cost_rate": 1000}]}, T["pm"])[1]
    call("POST", f"/change_orders/{oe['id']}/price", {}, T["pm"])
    act = call("GET", f"/portal/projects/{pid}/actions", token=T["client"])[1]
    pco = next((x for x in act["change_orders"] if x["id"] == co["id"]), None)
    check("change order offered with price, never cost", pco and pco["total"] == co["totals"]["total"] or pco and pco["price"] == 45000, pco)
    check("no cost anywhere in it", pco and "cost" not in json.dumps(pco).lower(), pco)
    check("our-error orders never shown", not any(x["id"] == oe["id"] for x in act["change_orders"]))
    wait = call("GET", f"/portal/projects/{pid}", token=T["client"])[1]["waiting_on_you"]
    check("waiting on you: the change order, with its kind", any(w["kind"] == "change_order" and w["ref"] == co["id"] for w in wait), wait)
    expect("consultant cannot approve a change order", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": "x", "agree": True, "signature": SIG}, T["consultant"]), 403)
    expect("approve: drawn signature required", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": "Mrs Client", "agree": True}, T["client"]), 400)
    expect("client approves with a signature", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": f"Mrs Client {RUN}", "agree": True, "signature": SIG}, T["client"]), 200)
    cdoc = mongo.change_orders.find_one({"_id": ObjectId(co["id"])})
    check("approved through the same path: Portal, signature, effects applied", cdoc["status"] == "approved" and cdoc["approval"]["method"] == "Portal"
          and cdoc["approval"]["signature"] == SIG and cdoc.get("effects", {}).get("budget_added") == 30000, cdoc.get("approval", {}).get("method"))
    expect("decided once", call("POST", f"/portal/change_orders/{co['id']}/approve", {"name": "x", "agree": True, "signature": SIG}, T["client"]), 409)
    co2 = call("POST", f"/projects/{pid}/change_orders", {"stage_id": intr["id"], "title": f"Marble {RUN}", "reason": "client_request",
                                                         "lines": [{"description": "Marble", "qty": 1, "cost_rate": 1, "price_rate": 2}]}, T["pm"])[1]
    call("POST", f"/change_orders/{co2['id']}/price", {}, T["pm"])
    call("POST", f"/change_orders/{co2['id']}/send", {}, T["pm"])
    expect("reject: why", call("POST", f"/portal/change_orders/{co2['id']}/reject", {}, T["client"]), 400)
    expect("client rejects", call("POST", f"/portal/change_orders/{co2['id']}/reject", {"reason": "Not now"}, T["client"]), 200)
    check("rejected with Portal", mongo.change_orders.find_one({"_id": ObjectId(co2["id"])})["status"] == "rejected")

    # selections
    sel = call("POST", f"/projects/{pid}/selections", {"stage_id": intr["id"], "item": f"Sofa {RUN}", "allowance": 50000, "options": [
        {"name": "Fabric", "qty": 1, "unit_cost": 30000, "unit_price": 45000}, {"name": "Leather", "qty": 1, "unit_cost": 50000, "unit_price": 70000}]}, T["pm"])[1]
    call("POST", f"/selections/{sel['id']}/send", {"email": False}, T["pm"])
    act = call("GET", f"/portal/projects/{pid}/actions", token=T["client"])[1]
    psel = next(x for x in act["selections"] if x["id"] == sel["id"])
    check("options with price only", all("cost" not in o and "unit_cost" not in o for o in psel["options"]) and psel["options"][1]["price"] == 70000)
    expect("choose one of the options", call("POST", f"/portal/selections/{sel['id']}/choose", {"option_id": "x", "name": "a", "agree": True}, T["client"]), 400)
    expect("client chooses leather", call("POST", f"/portal/selections/{sel['id']}/choose", {"option_id": psel["options"][1]["id"], "name": "Mrs Client", "agree": True}, T["client"]), 200)
    sdoc = mongo.selections.find_one({"_id": ObjectId(sel["id"])})
    check("choice recorded as Portal", sdoc["status"] == "chosen" and sdoc["choice"]["method"] == "Portal")
    expect("chosen once", call("POST", f"/portal/selections/{sel['id']}/choose", {"option_id": psel["options"][0]["id"], "name": "a", "agree": True}, T["client"]), 409)

    # drawings: approval by the client, comments from the consultant
    k1 = up("dw1")
    dw = call("POST", f"/projects/{pid}/documents", {"folder": "Drawings", "name": f"Elevation {RUN}", "kind": "drawing", "number": "A-201",
                                                    "stage_id": arch["id"], "file_key": k1}, T["pm"])[1]
    k2 = up("dw2")
    other = call("POST", f"/projects/{pid}/documents", {"folder": "Drawings", "name": f"Section {RUN}", "kind": "drawing", "number": "A-202", "file_key": k2}, T["pm"])[1]
    people = {x["role"]: x["contact_id"] for x in call("GET", f"/projects/{pid}/transmittals", token=T["pm"])[1]["people"]}
    tr1 = call("POST", f"/projects/{pid}/transmittals", {"to": [people["Client"]], "purpose": "for_approval", "documents": [dw["id"]], "email": False}, T["pm"])[1]
    tr2 = call("POST", f"/projects/{pid}/transmittals", {"to": [people["Consultant"]], "purpose": "for_comment", "documents": [dw["id"]], "email": False}, T["pm"])[1]
    cw = call("GET", f"/portal/projects/{pid}", token=T["consultant"])[1]["waiting_on_you"]
    check("the consultant's waiting list has their transmittal, not the client's", any(w["ref"] == tr2["id"] for w in cw) and not any(w["ref"] == tr1["id"] for w in cw), cw)
    ca = call("GET", f"/portal/projects/{pid}/actions", token=T["consultant"])[1]
    cdw = next(x for x in ca["documents"] if x["id"] == dw["id"])
    check("consultant: may comment, may not approve", cdw["can_comment"] and not cdw["can_approve"], cdw)
    expect("consultant cannot approve", call("POST", f"/portal/documents/{dw['id']}/approve", {"name": "x", "agree": True}, T["consultant"]), 403)
    expect("comment needs text", call("POST", f"/portal/documents/{dw['id']}/comments", {}, T["consultant"]), 400)
    cm = expect("consultant comments", call("POST", f"/portal/documents/{dw['id']}/comments", {"text": f"Beam depth? {RUN}"}, T["consultant"]), 201)
    check("PM told of the comment", any(f"Beam depth? {RUN}" in n["text"] for n in bell("pm", event="document_comment")))
    expect("a document not sent to you: 404", call("POST", f"/portal/documents/{other['id']}/approve", {"name": "x", "agree": True}, T["client"]), 404)
    expect("approve: tick required", call("POST", f"/portal/documents/{dw['id']}/approve", {"name": "Mrs Client"}, T["client"]), 400)
    expect("client approves the drawing", call("POST", f"/portal/documents/{dw['id']}/approve", {"name": "Mrs Client", "agree": True}, T["client"]), 200)
    ddoc = mongo.documents.find_one({"_id": ObjectId(dw["id"])})
    check("drawing approved through the portal", ddoc["status"] == "approved" and ddoc["versions"][-1].get("method") == "Portal")
    check("PM told it is approved", any("A-201" in n["text"] for n in bell("pm", event="drawing_approved")))
    call("POST", f"/documents/{dw['id']}/versions", {"file_key": up("dw1b")}, T["pm"])
    expect("a superseded revision cannot be approved", call("POST", f"/portal/documents/{dw['id']}/approve", {"name": "x", "agree": True}, T["client"]), 409)
    tr3 = call("POST", f"/projects/{pid}/transmittals", {"to": [people["Consultant"]], "purpose": "for_comment", "documents": [dw["id"]], "email": False}, T["pm"])[1]
    expect("consultant returns with comments", call("POST", f"/portal/documents/{dw['id']}/return", {"comment": "Revise the canopy"}, T["consultant"]), 200)
    check("returned: back to work in progress", mongo.documents.find_one({"_id": ObjectId(dw["id"])})["status"] == "wip")

    # transmittals acknowledged in the portal
    expect("client cannot acknowledge the consultant's transmittal", call("POST", f"/portal/transmittals/{tr2['id']}/acknowledge", {"name": "x"}, T["client"]), 404)
    expect("consultant acknowledges", call("POST", f"/portal/transmittals/{tr2['id']}/acknowledge", {"name": "Mr Consultant"}, T["consultant"]), 200)
    check("acknowledged as Portal", mongo.transmittals.find_one({"_id": ObjectId(tr2["id"])})["acknowledged"]["method"] == "Portal")
    expect("acknowledged once", call("POST", f"/portal/transmittals/{tr2['id']}/acknowledge", {"name": "x"}, T["consultant"]), 409)

    # the team answers comments
    cms = expect("staff see the comments", call("GET", f"/documents/{dw['id']}/comments", token=T["pm"]), 200)
    check("both comments, with their side", {c["side"] for c in cms} == {"consultant"} and len(cms) == 2, cms)
    rp = expect("reply", call("POST", f"/document_comments/{cm['id']}/reply", {"text": "450 mm"}, T["pm"]), 200)
    check("answered", rp["status"] == "answered" and rp["reply"]["text"] == "450 mm")
    tk = expect("comment becomes a task", call("POST", f"/document_comments/{cms[1]['id']}/task", {}, T["pm"]), 201)
    check("task on the drawing's stage", any(t_["id"] == tk["task_id"] for s in call("GET", f"/projects/{pid}", token=T["pm"])[1]["stages"]
                                             if s["id"] == arch["id"] for t_ in s["tasks"]))
    expect("close a comment", call("PUT", f"/document_comments/{cm['id']}", {"status": "closed"}, T["pm"]), 200)
    ca = call("GET", f"/portal/projects/{pid}/actions", token=T["consultant"])[1]
    check("the consultant sees the reply", any(c.get("reply", {}) and c["reply"]["text"] == "450 mm" for d in ca["documents"] for c in d["comments"]), ca["documents"])

    # ================= block 2 · invoices in the portal, online payments =================
    import hashlib as _h, hmac as _hm  # noqa: E401

    def raw_post(path, raw, headers):
        req = urllib.request.Request(BASE + path, method="POST", data=raw)
        for k_, v_ in headers.items():
            req.add_header(k_, v_)
        try:
            with urllib.request.urlopen(req) as r:
                body_ = r.read()
                return r.status, (json.loads(body_) if body_[:1] == b"{" else body_)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    WH = f"whsec_{RUN}"
    expect("PM cannot set up payments", call("PUT", "/settings/payments", {"provider": "sandbox", "webhook_secret": WH}, T["pm"]), 403)
    ps = expect("owner sets up the sandbox provider", call("PUT", "/settings/payments", {"provider": "sandbox", "webhook_secret": WH}, T["owner"]), 200)
    check("secrets never sent back", "webhook_secret" not in ps and ps["webhook_secret_set"] and ps["enabled"], ps)
    inv = call("POST", f"/projects/{pid}/invoices", {"lines": [{"description": f"Design fee {RUN}", "qty": 1, "rate": 10000, "tax_pct": 0}]}, T["pm"])[1]
    draft = call("POST", f"/projects/{pid}/invoices", {"lines": [{"description": "Draft", "qty": 1, "rate": 1, "tax_pct": 0}]}, T["pm"])[1]
    inv = call("POST", f"/invoices/{inv['id']}/send", {}, T["pm"])[1]
    expect("consultant has no invoices", call("GET", f"/portal/projects/{pid}/invoices", token=T["consultant"]), 403)
    pi = expect("client's invoices", call("GET", f"/portal/projects/{pid}/invoices", token=T["client"]), 200)
    check("sent invoices only, with the balance and pay enabled", [x["id"] for x in pi["invoices"]] == [inv["id"]] and pi["balance"] == 10000 and pi["pay_enabled"], pi)
    check("no internal fields", "created_by_name" not in pi["invoices"][0])
    expect("a draft is not payable", call("POST", f"/portal/invoices/{draft['id']}/pay", {}, T["client"]), 409)
    expect("not more than the balance", call("POST", f"/portal/invoices/{inv['id']}/pay", {"amount": 10001}, T["client"]), 400)
    l1 = expect("client asks for a link", call("POST", f"/portal/invoices/{inv['id']}/pay", {"amount": 4000}, T["client"]), 201)
    l2 = expect("a part payment link", call("POST", f"/portal/invoices/{inv['id']}/pay", {"amount": 5000}, T["client"]), 201)
    ref1, ref2 = l1["url"].rsplit("/", 1)[1], l2["url"].rsplit("/", 1)[1]
    check("a new link cancels the previous one", mongo.payment_links.find_one({"ref": ref1})["status"] == "cancelled"
          and mongo.payment_links.find_one({"ref": ref2})["status"] == "created")
    body = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": ref2}},
                                                                 "payment": {"entity": {"id": f"pay_{RUN}", "amount": 500000, "method": "upi"}}}}).encode()
    good = _hm.new(WH.encode(), body, _h.sha256).hexdigest()
    expect("bad signature refused", raw_post(f"/webhooks/payments/sandbox/{CID}", body, {"X-Sandbox-Signature": "nope", "Content-Type": "application/json"}), 400)
    wh = expect("signed webhook", raw_post(f"/webhooks/payments/sandbox/{CID}", body, {"X-Sandbox-Signature": good, "Content-Type": "application/json"}), 200)
    rc = mongo.receipts.find_one({"company_id": CID, "reference": f"pay_{RUN}"})
    check("a receipt through the same path: Online, provider reference", rc and rc["mode"] == "Online" and rc["amount"] == 5000 and wh["receipt"] == rc["number"], rc)
    check("invoice part paid", mongo.invoices.find_one({"_id": ObjectId(inv["id"])})["status"] == "part_paid")
    expect("replayed by the provider", raw_post(f"/webhooks/payments/sandbox/{CID}", body, {"X-Sandbox-Signature": good, "Content-Type": "application/json"}), 200)
    check("one payment, one receipt", mongo.receipts.count_documents({"company_id": CID, "reference": f"pay_{RUN}"}) == 1)
    check("PM and accounts told", any(rc["number"] in n["text"] for n in bell("pm", event="receipt_recorded")))
    l3 = call("POST", f"/portal/invoices/{inv['id']}/pay", {}, T["client"])[1]
    check("the next link is for the balance", l3["amount"] == 5000, l3)
    st, page = raw_post(f"/payments/sandbox/{l3['url'].rsplit('/', 1)[1]}", b"", {})
    check("sandbox checkout pays through the webhook", st == 200 and mongo.invoices.find_one({"_id": ObjectId(inv["id"])})["status"] == "paid")
    pi = call("GET", f"/portal/projects/{pid}/invoices", token=T["client"])[1]
    check("client sees both payments", len(pi["receipts"]) == 2 and pi["balance"] == 0, pi["receipts"])
    expect("a paid invoice is not payable", call("POST", f"/portal/invoices/{inv['id']}/pay", {}, T["client"]), 409)
    call("PUT", "/settings/payments", {"provider": None}, T["owner"])
    inv2 = call("POST", f"/projects/{pid}/invoices", {"lines": [{"description": "x", "qty": 1, "rate": 100, "tax_pct": 0}]}, T["pm"])[1]
    call("POST", f"/invoices/{inv2['id']}/send", {}, T["pm"])
    expect("payments off: no link", call("POST", f"/portal/invoices/{inv2['id']}/pay", {}, T["client"]), 409)

    # ================= block 3 · message threads =================
    T["estimator"] = login("estimator@skyline.test")
    expect("client's thread starts empty", call("GET", f"/portal/projects/{pid}/messages", token=T["client"]), 200)
    expect("a message needs text", call("POST", f"/portal/projects/{pid}/messages", {"text": " "}, T["client"]), 400)
    m1 = expect("client writes", call("POST", f"/portal/projects/{pid}/messages", {"text": f"When does tiling start? {RUN}"}, T["client"]), 201)
    check("PM told of the portal message", any(f"When does tiling start? {RUN}" in n["text"] for n in bell("pm", event="portal_message")))
    check("the consultant's thread is separate", call("GET", f"/portal/projects/{pid}/messages", token=T["consultant"])[1] == [])
    th = expect("staff: threads of the project", call("GET", f"/projects/{pid}/threads", token=T["pm"]), 200)
    cl = next(x for x in th if x["contact_id"] == CLIENT_CONTACT)
    check("client's thread unread 1, consultant's empty", cl["unread"] == 1 and next(x for x in th if x["contact_id"] == CONSULT_CONTACT)["last"] is None, th)
    expect("sales not on the project", call("GET", f"/projects/{pid}/threads", token=T["sales"]), 404)
    expect("estimator has no messages", call("GET", "/inbox", token=T["estimator"]), 403)
    msgs = expect("open the thread", call("GET", f"/projects/{pid}/threads/{CLIENT_CONTACT}", token=T["pm"]), 200)
    check("read on opening", msgs[0]["text"].startswith("When does tiling") and call("GET", f"/projects/{pid}/threads", token=T["pm"])[1][0]["unread"] == 0)
    expect("no thread with someone not on the project", call("GET", f"/projects/{pid}/threads/{str(ObjectId())}", token=T["pm"]), 404)
    r1 = expect("PM replies", call("POST", f"/projects/{pid}/threads/{CLIENT_CONTACT}", {"text": f"Next Monday {RUN}"}, T["pm"]), 201)
    check("reply emailed (result kept), no WhatsApp yet", r1["emailed"] and r1.get("whatsapp") is None, r1)
    cm_ = call("GET", f"/portal/projects/{pid}/messages", token=T["client"])[1]
    check("client sees the reply", [x["side"] for x in cm_] == ["contact", "team"] and cm_[1]["text"] == f"Next Monday {RUN}")
    ib = expect("PM's inbox", call("GET", "/inbox", token=T["pm"]), 200)
    check("inbox lists the thread", any(x["project_id"] == pid and x["contact_id"] == CLIENT_CONTACT for x in ib["threads"]), ib)
    call("POST", f"/portal/projects/{pid}/messages", {"text": f"Thanks {RUN}"}, T["client"])
    check("unread counted again", call("GET", "/inbox", token=T["pm"])[1]["unread"] >= 1)

    # ================= block 4 · WhatsApp =================
    APP = f"appsec_{RUN}"
    expect("PM cannot set up WhatsApp", call("PUT", "/settings/messaging", {"provider": "sandbox", "app_secret": APP}, T["pm"]), 403)
    ms_ = expect("owner sets up the sandbox", call("PUT", "/settings/messaging", {"provider": "sandbox", "app_secret": APP, "verify_token": f"vt{RUN}"}, T["owner"]), 200)
    check("secrets never sent back", "app_secret" not in ms_ and ms_["app_secret_set"] and ms_["ready"], ms_)
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {"phone": f"98{RUN}"}})
    wc = expect("a contact", call("POST", "/contacts", {"name": f"WA Person {RUN}", "kind": "person", "types": ["client"], "phone": f"97{RUN}"}, T["owner"]), 201)
    contacts_made.append(wc["id"])
    tpl = expect("template", call("POST", "/message_templates", {"name": f"Hello {RUN}", "channel": "whatsapp", "body": "Hello {{client}}, from {{company}}"}, T["owner"]), 201)
    tpls.append(tpl["id"])
    nm = expect("send without opt-in", call("POST", f"/message_templates/{tpl['id']}/send", {"contact_id": wc["id"]}, T["sales"]), 201)
    check("refused without opt-in (stored as failed)", nm["status"] == "failed" and "opted" in nm["error"], nm)
    expect("opt-in: how", call("PUT", f"/contacts/{wc['id']}/whatsapp", {"opt_in": True}, T["sales"]), 400)
    expect("opt-in recorded", call("PUT", f"/contacts/{wc['id']}/whatsapp", {"opt_in": True, "how": "Verbal"}, T["sales"]), 200)
    used_before = mongo.messages.count_documents({"company_id": CID, "channel": "whatsapp", "direction": "out"})
    sm = expect("send the template", call("POST", f"/message_templates/{tpl['id']}/send", {"contact_id": wc["id"]}, T["sales"]), 201)
    check("sent with the merge filled, counted against the plan", sm["status"] == "sent" and sm["text"] == f"Hello WA Person {RUN}, from " + mongo.companies.find_one({"_id": ObjectId(CID)})["name"]
          and sm["to"] == f"9197{RUN}" and mongo.messages.count_documents({"company_id": CID, "channel": "whatsapp", "direction": "out"}) == used_before + 1, sm)

    def wh(body, secret=APP):
        raw = json.dumps(body).encode()
        return raw_post(f"/webhooks/messages/{CID}", raw, {"X-Hub-Signature-256": "sha256=" + _hm.new(secret.encode(), raw, _h.sha256).hexdigest(),
                                                           "Content-Type": "application/json"})

    status = lambda pid_, st: {"entry": [{"changes": [{"value": {"statuses": [{"id": pid_, "status": st}]}}]}]}
    expect("bad signature", wh(status(sm["provider_id"], "delivered"), "wrong"), 400)
    expect("delivered", wh(status(sm["provider_id"], "delivered")), 200)
    expect("an older status is ignored", wh(status(sm["provider_id"], "sent")), 200)
    check("status moves forward only", mongo.messages.find_one({"_id": ObjectId(sm["id"])})["status"] == "delivered")
    sm2 = call("POST", f"/message_templates/{tpl['id']}/send", {"contact_id": wc["id"]}, T["sales"])[1]
    failed = {"entry": [{"changes": [{"value": {"statuses": [{"id": sm2["provider_id"], "status": "failed", "errors": [{"title": "Number not on WhatsApp"}]}]}}]}]}
    wh(failed)
    check("a failed message tells its sender", any("Number not on WhatsApp" in n["text"] for n in bell("sales", event="whatsapp_failed")))
    st_, ch_ = 0, ""
    req = urllib.request.Request(BASE + f"/webhooks/messages/{CID}?hub.mode=subscribe&hub.verify_token=vt{RUN}&hub.challenge=abc{RUN}")
    with urllib.request.urlopen(req) as r_:
        st_, ch_ = r_.status, r_.read().decode()
    check("Meta's verify handshake", st_ == 200 and ch_ == f"abc{RUN}")
    wh({"entry": [{"changes": [{"value": {"messages": [{"from": f"9197{RUN}", "id": "wamid.in1", "text": {"body": "STOP"}}]}}]}]})
    check("STOP opts out", mongo.contacts.find_one({"_id": ObjectId(wc["id"])}).get("whatsapp_opt_in") is None)
    nm2 = call("POST", f"/message_templates/{tpl['id']}/send", {"contact_id": wc["id"]}, T["sales"])[1]
    check("after STOP nothing is sent", nm2["status"] == "failed")

    po = expect("client opts in from the portal", call("PUT", "/portal/whatsapp", {"opt_in": True}, T["client"]), 200)
    check("portal opt-in", po["opt_in"] and call("GET", "/portal/whatsapp", token=T["client"])[1]["opt_in"])
    r2 = call("POST", f"/projects/{pid}/threads/{CLIENT_CONTACT}", {"text": f"Site visit at 10 {RUN}"}, T["pm"])[1]
    check("a reply also goes by WhatsApp once opted in", r2.get("whatsapp") == "sent", r2.get("whatsapp"))
    k9 = up("wa-doc")
    d9 = call("POST", f"/projects/{pid}/documents", {"folder": "Contract", "name": f"Brochure {RUN}", "kind": "other", "file_key": k9}, T["pm"])[1]
    tr9 = expect("transmittal also by WhatsApp", call("POST", f"/projects/{pid}/transmittals", {"to": [people["Client"]], "purpose": "for_information",
                                                                                                 "documents": [d9["id"]], "email": False, "whatsapp": True}, T["pm"]), 201)
    check("WhatsApp result per person", tr9["whatsapp"][people["Client"]] == "sent", tr9.get("whatsapp"))

    # decision G-6: the client is reminded of an overdue invoice once
    inv3 = call("POST", f"/projects/{pid}/invoices", {"lines": [{"description": f"Reminder test {RUN}", "qty": 1, "rate": 500, "tax_pct": 0}]}, T["pm"])[1]
    call("POST", f"/invoices/{inv3['id']}/send", {}, T["pm"])
    mongo.invoices.update_one({"_id": ObjectId(inv3["id"])}, {"$set": {"due_date": day(-1)}})
    worker()
    worker()
    rem = list(mongo.reminders.find({"company_id": CID, "key": {"$regex": inv3["id"]}}))
    check("overdue invoice: the client reminded once, by WhatsApp too", len(rem) == 1 and rem[0]["whatsapp"] == "sent", rem)
    call("PUT", "/settings/messaging", {"provider": None}, T["owner"])
    lg = call("POST", f"/message_templates/{tpl['id']}/send", {"contact_id": CLIENT_CONTACT}, T["sales"])[1]
    check("not set up: log only, not counted", lg["status"] == "logged" and lg["direction"] == "logged", lg)
finally:
    for p_ in projects:
        mongo.costs.update_many({"company_id": CID, "project_id": p_}, {"$set": {"status": "void"}})
        mongo.invoices.delete_many({"company_id": CID, "project_id": p_})
        mongo.receipts.delete_many({"company_id": CID, "project_id": p_})
        for d_ in mongo.documents.find({"company_id": CID, "project_id": p_}):
            mongo.documents.update_one({"_id": d_["_id"]}, {"$set": {"versions": [{**v, "sent": []} for v in d_["versions"]]}})
        call("DELETE", f"/projects/{p_}", token=T["owner"])
    for k in keys:
        mongo.files.delete_one({"key": k})
    mongo.notifications.delete_many({"company_id": CID, "text": {"$regex": RUN}})
    mongo.payment_links.delete_many({"company_id": CID, "project_id": {"$in": projects}})
    mongo.messages.delete_many({"company_id": CID, "$or": [{"project_id": {"$in": projects}}, {"text": {"$regex": RUN}},
                                                            {"contact_id": {"$in": [CLIENT_CONTACT] + contacts_made}, "channel": "whatsapp"}]})
    mongo.reminders.delete_many({"company_id": CID, "project_id": {"$in": projects}})
    for t_ in tpls:
        call("DELETE", f"/message_templates/{t_}", token=T["owner"])
    for c_ in contacts_made:
        call("DELETE", f"/contacts/{c_}", token=T["owner"])
    mongo.contacts.update_one({"_id": ObjectId(CLIENT_CONTACT)}, {"$set": {k: client_before.get(k) for k in ("phone", "whatsapp_opt_in", "whatsapp_opt_out")}})
    if company_before.get("messaging") is not None:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"messaging": company_before["messaging"]}})
    else:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"messaging": ""}})
    if company_before.get("payments") is not None:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"payments": company_before["payments"]}})
    else:
        mongo.companies.update_one({"_id": ObjectId(CID)}, {"$unset": {"payments": ""}})
    left = mongo.projects.count_documents({"company_id": CID, "name": {"$regex": RUN}}) + \
        mongo.document_comments.count_documents({"company_id": CID, "project_id": {"$in": projects}})
    check("cleanup: nothing left", left == 0, left)

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
