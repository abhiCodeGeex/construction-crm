"""Phase L — v4 "Phase 3". One section per block of PLAN.md Phase L. Cleans up everything it creates.

    docker compose exec backend python tests/test_phase_l.py
"""
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
# a 1x1 PNG, so the AI helpers have a real image to send
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def call(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            b = r.read()
            if raw:
                return r.status, b, dict(r.headers)
            return r.status, (json.loads(b or b"{}") if b[:1] in (b"{", b"[") or not b else b)
    except urllib.error.HTTPError as e:
        b = e.read()
        if raw:
            return e.code, b, {}
        return e.code, (json.loads(b or b"{}") if b[:1] in (b"{", b"[") or not b else {"error": b[:200]})


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


def upload(name, token, content=b"0" * 64):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
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


day = lambda n: (date.today() + timedelta(days=n)).isoformat()
T = {r: login(f"{r}@skyline.test") for r in ("owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator")}
T["client"] = login("client@skyline.test")
users = call("GET", "/users", token=T["owner"])[1]
U = {u["email"].split("@")[0]: u["id"] for u in users if u["kind"] == "staff"}
CID = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
CLIENT_CONTACT = mongo.users.find_one({"email": "client@skyline.test"})["contact_id"]
company_before = mongo.companies.find_one({"_id": ObjectId(CID)}, {"safety": 1, "ai": 1, "marketplace": 1, "fx_rates": 1, "currency": 1})
projects, keys, leads, contacts_made, workers_made, rates_made = [], [], [], [], [], []
other_cid = None

try:
    p = expect("project", call("POST", "/projects", {"name": f"PhaseL {RUN}", "services": ["interior"], "start": day(-30), "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    PID = p["id"]
    projects.append(PID)
    for who, role in (("pm", "Project Manager"), ("site", "Site Supervisor"), ("designer", "Interior Designer")):
        call("POST", f"/projects/{PID}/team", {"user_id": U[who], "project_role": role, "access": "edit"}, T["owner"])
    p = call("GET", f"/projects/{PID}", token=T["owner"])[1]
    S0 = p["stages"][0]["id"]
    w = expect("site worker", call("POST", "/site-workers", {"name": f"Ramesh {RUN}", "trade": "Carpenter", "language": "ta", "phone": "9876500001"}, T["site"]), 201)
    workers_made.append(w["id"])

    # ======================================= block 1: offline field app =======================================
    bs = expect("L1.1 bootstrap", call("GET", "/mobile/bootstrap", token=T["site"]))
    mine = next((x for x in bs["projects"] if x["id"] == PID), None)
    check("L1.1 my project with stages, people and templates", mine and mine["stages"] and any(x["person"] == f"w:{w['id']}" for x in mine["people"])
          and bs["inspection_templates"] and bs["incident_kinds"] and mine["can_write"], mine and list(mine))
    expect("L1.1 designer has no field app", call("GET", "/mobile/bootstrap", token=T["designer"]), 403)
    expect("L1.1 sales has no field app", call("GET", "/mobile/bootstrap", token=T["sales"]), 403)
    ph = upload("site1.jpg", T["site"], PNG)
    ops = [
        {"op_id": f"op-{RUN}-1", "kind": "site_report", "project_id": PID, "made_at": datetime.utcnow().isoformat(),
         "data": {"weather": {"kind": "Clear"}, "manpower": [{"trade": "Carpenter", "count": 3}], "work": [{"stage_id": S0, "note": "Wardrobe carcass fixed"}],
                  "photos": [{"key": ph, "caption": "Wardrobe", "lat": 19.07, "lng": 72.87, "taken_at": datetime.utcnow().isoformat() + "Z"}]}},
        {"op_id": f"op-{RUN}-2", "kind": "attendance", "project_id": PID, "data": {"rows": [{"person": f"w:{w['id']}", "status": "present", "in": "09:00"}]}},
        {"op_id": f"op-{RUN}-3", "kind": "snag", "project_id": PID, "data": {"title": f"Chipped laminate {RUN}", "location": "Bedroom 1", "photos": [ph]}},
        {"op_id": f"op-{RUN}-4", "kind": "snag", "project_id": PID, "data": {}},
        {"op_id": "x", "kind": "snag", "project_id": PID, "data": {"title": "short id"}},
        {"op_id": f"op-{RUN}-5", "kind": "teleport", "project_id": PID, "data": {}},
    ]
    sy = expect("L1.2 sync a queue", call("POST", "/mobile/sync", {"ops": ops}, T["site"]))
    res = {r["op_id"]: r for r in sy["results"]}
    check("L1.2 report, attendance, snag applied", all(res[f"op-{RUN}-{i}"]["ok"] for i in (1, 2, 3)), sy["results"])
    check("L1.2 bad one refused with the reason, the rest go on", not res[f"op-{RUN}-4"]["ok"] and res[f"op-{RUN}-4"]["status"] == 400 and "wrong" in res[f"op-{RUN}-4"]["error"],
          res[f"op-{RUN}-4"])
    check("L1.2 short id and unknown kind refused", not res["x"]["ok"] and not res[f"op-{RUN}-5"]["ok"], (res["x"], res[f"op-{RUN}-5"]))
    check("L1.2 counts", sy["applied"] == 3 and sy["failed"] == 3, (sy["applied"], sy["failed"]))
    rep = mongo.site_reports.find_one({"company_id": CID, "project_id": PID, "date": date.today().isoformat()})
    check("L1.2 report saved with GPS photo", rep and rep["headcount"] == 3 and rep["photos"][0]["lat"] == 19.07, rep and rep.get("photos"))
    again = expect("L1.3 the same queue again", call("POST", "/mobile/sync", {"ops": ops[:3]}, T["site"]))
    check("L1.3 applied once (replayed)", all(r.get("replayed") for r in again["results"]) and mongo.snags.count_documents({"company_id": CID, "project_id": PID}) == 1,
          again["results"])
    # a second phone writes the same day: merged, not refused
    ops2 = [{"op_id": f"op-{RUN}-6", "kind": "site_report", "project_id": PID,
             "data": {"manpower": [{"trade": "Painter", "count": 2}, {"trade": "Carpenter", "count": 4}], "work": [{"stage_id": S0, "note": "Primer on walls"}], "safety": "All in helmets"}},
            {"op_id": f"op-{RUN}-7", "kind": "attendance", "project_id": PID, "data": {"rows": [{"person": f"u:{U['site']}", "status": "present"}]}}]
    s2 = expect("L1.4 second phone, same day", call("POST", "/mobile/sync", {"ops": ops2}, T["pm"]))
    check("L1.4 merged", s2["results"][0]["ok"] and s2["results"][0]["merged"], s2["results"])
    rep = mongo.site_reports.find_one({"_id": rep["_id"]})
    check("L1.4 work added, trade replaced, photo kept", len(rep["work"]) == 2 and rep["headcount"] == 6 and len(rep["photos"]) == 1 and rep["safety"] == "All in helmets",
          (rep["work"], rep["manpower"], rep["headcount"]))
    sheet = mongo.attendance.find_one({"company_id": CID, "project_id": PID, "date": date.today().isoformat()})
    check("L1.4 attendance rows merged", sheet and {r["person"] for r in sheet["rows"]} == {f"w:{w['id']}", f"u:{U['site']}"}, sheet and sheet["rows"])
    snag_id = res[f"op-{RUN}-3"]["id"]
    fx = expect("L1.5 snag fixed offline", call("POST", "/mobile/sync", {"ops": [{"op_id": f"op-{RUN}-8", "kind": "snag_fixed", "data": {"snag_id": snag_id, "note": "Re-laminated"}}]}, T["site"]))
    check("L1.5 fixed", fx["results"][0]["ok"] and mongo.snags.find_one({"_id": ObjectId(snag_id)})["status"] == "fixed", fx["results"])
    # an old report is locked: refused, kept on the phone
    old = expect("L1.6 two-day-old report refused", call("POST", "/mobile/sync", {"ops": [{"op_id": f"op-{RUN}-9", "kind": "site_report", "project_id": PID,
                                                                                           "data": {"date": day(-3), "work": [{"stage_id": S0, "note": "late"}]}}]}, T["site"]))
    check("L1.6 409 with the reason", old["results"][0]["status"] == 409 and not old["results"][0]["ok"], old["results"])
    expect("L1.6 sales cannot sync a site report", call("POST", "/mobile/sync", {"ops": [{"op_id": f"op-{RUN}-10", "kind": "snag", "project_id": PID, "data": {"title": "x"}}]}, T["sales"]))
    check("L1.6 permission still applies", not mongo.snags.find_one({"company_id": CID, "title": "x", "project_id": PID}))
    expect("L1.7 too many at once", call("POST", "/mobile/sync", {"ops": [{}] * 101}, T["site"]), 400)
    lg = expect("L1.7 sync log", call("GET", "/mobile/sync-log", token=T["site"]))
    check("L1.7 my operations listed", any(x["op_id"] == f"op-{RUN}-1" for x in lg) and not any(x["op_id"] == f"op-{RUN}-6" for x in lg), len(lg))

    # ======================================= block 2: safety =======================================
    expect("L2.1 what happened", call("POST", f"/projects/{PID}/incidents", {"kind": "near_miss"}, T["site"]), 400)
    expect("L2.1 injury needs the person", call("POST", f"/projects/{PID}/incidents", {"kind": "injury", "description": "Cut hand"}, T["site"]), 400)
    expect("L2.1 not in the future", call("POST", f"/projects/{PID}/incidents", {"kind": "near_miss", "description": "x", "date": day(2)}, T["site"]), 400)
    nm = expect("L2.1 near miss", call("POST", f"/projects/{PID}/incidents", {"kind": "near_miss", "description": f"Plank fell from scaffold {RUN}", "time": "11:20"}, T["site"]), 201)
    check("L2.1 numbered, low, not serious", nm["number"].startswith("INC") and nm["severity"] == "low" and not nm["serious"], nm)
    check("L2.1 near miss: no alarm", not mongo.notifications.find_one({"company_id": CID, "event": "safety_incident", "project_id": PID}))
    inj = expect("L2.2 lost-time injury (offline sync)", call("POST", "/mobile/sync", {"ops": [{"op_id": f"op-{RUN}-11", "kind": "incident", "project_id": PID, "data": {
        "kind": "lost_time", "description": f"Fall from ladder {RUN}", "people": [{"name": f"Ramesh {RUN}", "person": f"w:{w['id']}", "injury": "Sprained ankle"}],
        "lost_days": 3, "immediate_action": "First aid, taken to clinic"}}]}, T["site"]))
    INC = inj["results"][0]["id"]
    check("L2.2 applied", inj["results"][0]["ok"], inj["results"])
    check("L2.2 PM and Owner alerted", {n["user_id"] for n in mongo.notifications.find({"company_id": CID, "event": "safety_incident", "project_id": PID})} >= {U["pm"], U["owner"]})
    expect("L2.3 site cannot investigate", call("POST", f"/incidents/{INC}/investigate", {"root_cause": "Unsafe act", "findings": "x"}, T["site"]), 403)
    expect("L2.3 root cause from the list", call("POST", f"/incidents/{INC}/investigate", {"root_cause": "Bad luck", "findings": "x"}, T["pm"]), 400)
    expect("L2.3 serious one: investigate before close", call("POST", f"/incidents/{INC}/close", {}, T["pm"]), 409)
    iv = expect("L2.3 investigate", call("POST", f"/incidents/{INC}/investigate", {"root_cause": "Unsafe condition", "findings": "Ladder not footed on wet floor"}, T["pm"]))
    check("L2.3 investigating", iv["status"] == "investigating" and iv["investigation"]["findings"], iv["status"])
    expect("L2.4 action owner on the team", call("POST", f"/incidents/{INC}/actions", {"text": "Ladder training", "owner_id": U["sales"]}, T["pm"]), 400)
    ac = expect("L2.4 corrective action", call("POST", f"/incidents/{INC}/actions", {"text": "Toolbox talk on ladders", "owner_id": U["site"], "due": day(-1)}, T["pm"]), 201)
    AID = ac["actions"][0]["id"]
    check("L2.4 overdue flagged, owner told", ac["actions"][0]["overdue"] and mongo.notifications.find_one({"company_id": CID, "user_id": U["site"], "event": "safety_action"}))
    worker()
    check("L2.4 overdue reminder", mongo.notifications.find_one({"company_id": CID, "event": "safety_action", "key": f"safety-act:{INC}:{AID}:{date.today().isoformat()}"}) is not None)
    expect("L2.5 open action blocks close", call("POST", f"/incidents/{INC}/close", {}, T["pm"]), 409)
    expect("L2.5 someone else cannot mark it done", call("POST", f"/incidents/{INC}/actions/{AID}/done", {}, T["designer"]), 403)
    dn = expect("L2.5 owner marks it done", call("POST", f"/incidents/{INC}/actions/{AID}/done", {"note": "Held on Monday"}, T["site"]))
    check("L2.5 done", dn["actions"][0]["done_at"], dn["actions"])
    cl = expect("L2.5 close", call("POST", f"/incidents/{INC}/close", {"note": "Ladders checked daily now"}, T["pm"]))
    check("L2.5 closed", cl["status"] == "closed")
    expect("L2.5 reopen needs why", call("POST", f"/incidents/{INC}/reopen", {}, T["pm"]), 400)
    st = expect("L2.6 checklists", call("GET", "/settings/safety", token=T["site"]))
    check("L2.6 three ready-made", st["is_default"] and len(st["templates"]) == 3, len(st["templates"]))
    tpl = st["templates"][0]
    expect("L2.6 answer every item", call("POST", f"/projects/{PID}/inspections", {"template_id": tpl["id"], "results": [{"item_id": tpl["items"][0]["id"], "result": "pass"}]}, T["site"]), 400)
    resl = [{"item_id": it["id"], "result": "pass"} for it in tpl["items"]]
    resl[0] = {"item_id": tpl["items"][0]["id"], "result": "fail"}
    expect("L2.6 a fail needs a note", call("POST", f"/projects/{PID}/inspections", {"template_id": tpl["id"], "results": resl}, T["site"]), 400)
    resl[0]["note"] = "Two helpers without helmets"
    resl[-1] = {"item_id": tpl["items"][-1]["id"], "result": "na"}
    ins = expect("L2.6 weekly inspection", call("POST", f"/projects/{PID}/inspections", {"template_id": tpl["id"], "results": resl}, T["site"]), 201)
    n_items = len(tpl["items"])
    check("L2.6 score = passed / (passed + failed)", ins["score"] == round(100 * (n_items - 2) / (n_items - 1), 1) and ins["failed"] == 1 and ins["critical_failed"] == 1, ins["score"])
    sg = mongo.snags.find_one({"_id": ObjectId(ins["results"][0]["snag_id"])})
    check("L2.6 failed item -> high snag, due tomorrow", sg and sg["priority"] == "high" and sg["due"] == day(1) and sg["source"]["inspection_id"] == ins["id"], sg)
    check("L2.6 critical fail tells the PM", mongo.notifications.find_one({"company_id": CID, "user_id": U["pm"], "event": "inspection_failed"}) is not None)
    expect("L2.7 site cannot change checklists", call("PUT", "/settings/safety", {"templates": []}, T["site"]), 403)
    expect("L2.7 keep one", call("PUT", "/settings/safety", {"templates": []}, T["owner"]), 400)
    cs = expect("L2.7 own checklist", call("PUT", "/settings/safety", {"templates": st["templates"] + [{"name": f"Handover {RUN}", "kind": "handover",
                                                                                                      "items": [{"text": "Keys handed over"}, {"text": "Snags closed", "critical": True}]}]}, T["owner"]))
    check("L2.7 saved", not cs["is_default"] and len(cs["templates"]) == 4 and cs["templates"][3]["kind"] == "handover", len(cs["templates"]))
    expect("L2.8 talk needs people", call("POST", f"/projects/{PID}/toolbox-talks", {"topic": "Ladders"}, T["site"]), 400)
    tb = expect("L2.8 toolbox talk", call("POST", f"/projects/{PID}/toolbox-talks", {"topic": "Ladder safety", "attendees": [f"w:{w['id']}", f"u:{U['site']}"]}, T["site"]), 201)
    check("L2.8 attendees named", tb["count"] == 2 and tb["attendees"][0]["name"], tb)
    sr = expect("L2.9 safety report", call("GET", f"/reports/safety?project_id={PID}", token=T["owner"]))
    check("L2.9 counts", sr["incidents"] == 2 and sr["serious"] == 1 and sr["lost_days"] == 3 and sr["inspections"] == 1 and sr["talks"] == 1, sr)
    check("L2.9 days since LTI and top fails", sr["days_without_lti"][0]["since"] == "last lost-time injury" and sr["top_fails"][0]["count"] == 1, sr["days_without_lti"])
    expect("L2.9 sales cannot", call("GET", "/reports/safety", token=T["estimator"]), 403)

    # ======================================= block 3: AI =======================================
    lead = expect("lead", call("POST", "/leads", {"title": f"Villa interiors {RUN}", "contact_name": f"Anita Rao {RUN}", "contact_phone": f"6{RUN[-7:]}41", "service": "interior",
                                                    "location": "Pune", "source": "Walk-in"}, T["sales"]), 201)
    leads.append(lead["id"])
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"ai": {"mode": "off"}}})
    fd = expect("L3.1 AI off: template draft", call("POST", f"/leads/{lead['id']}/ai/followup", {"channel": "whatsapp", "purpose": "visit"}, T["sales"]))
    check("L3.1 template names the client", fd["source"] == "template" and "Anita" in fd["body"] and "visit" in fd["body"], fd)
    expect("L3.1 BOQ needs AI on", call("POST", "/estimates/000000000000000000000000/ai/boq", {}, T["estimator"]), 404)
    expect("L3.2 claude needs a key", call("PUT", "/settings/ai", {"mode": "claude"}, T["owner"]), 400)
    expect("L3.2 sales cannot change", call("PUT", "/settings/ai", {"mode": "sandbox"}, T["sales"]), 403)
    ai = expect("L3.2 sandbox mode", call("PUT", "/settings/ai", {"mode": "sandbox"}, T["owner"]))
    check("L3.2 key never returned", ai["mode"] == "sandbox" and "api_key" not in ai, ai)
    fs = expect("L3.3 sandbox follow-up", call("POST", f"/leads/{lead['id']}/ai/followup", {"channel": "email", "purpose": "proposal"}, T["sales"]))
    check("L3.3 sandbox draft", fs["source"] == "sandbox" and fs["subject"].startswith("[Sandbox]"), fs)
    est = expect("estimate", call("POST", f"/leads/{lead['id']}/estimates", {"title": "AI"}, T["estimator"]), 201)
    rt = expect("rate", call("POST", "/rates", {"kind": "material", "name": f"Vitrified floor tiles {RUN}", "unit": "sq ft", "rate": 65, "category": "Flooring"}, T["estimator"]), 201)
    rates_made.append(rt["id"])
    dwg = upload("plan.png", T["estimator"], PNG)
    cad = upload("plan.dwg", T["estimator"])
    expect("L3.4 drawings needed", call("POST", f"/estimates/{est['id']}/ai/boq", {}, T["estimator"]), 400)
    expect("L3.4 DWG is not read", call("POST", f"/estimates/{est['id']}/ai/boq", {"files": [cad]}, T["estimator"]), 400)
    bq = expect("L3.4 BOQ draft from a drawing", call("POST", f"/estimates/{est['id']}/ai/boq", {"files": [dwg], "notes": "Living room only"}, T["estimator"]))
    tile = next((x for x in bq["lines"] if "tiles" in x["description"]), None)
    check("L3.4 lines with qty, unit; rate matched from the library", len(bq["lines"]) == 4 and tile and tile["material_rate_id"] == rt["id"] and tile["material_rate"] == 65
          and bq["source"] == "sandbox" and "check every quantity" in bq["warning"], tile)
    expect("L3.5 tick lines", call("POST", f"/estimates/{est['id']}/ai/boq/apply", {"draft_id": bq["draft_id"], "lines": []}, T["estimator"]), 400)
    ap = expect("L3.5 add two (one edited)", call("POST", f"/estimates/{est['id']}/ai/boq/apply", {"draft_id": bq["draft_id"],
                                                                                                    "lines": [{"id": tile["id"], "qty": 200}, {"id": bq["lines"][1]["id"]}]}, T["estimator"]))
    check("L3.5 estimate lines and totals", len(ap["lines"]) == 2 and ap["lines"][0]["qty"] == 200 and ap["lines"][0]["material_cost"] == 200 * 65, (ap.get("lines"), ap.get("totals")))
    sm = expect("L3.6 summary of today's report", call("POST", f"/site-reports/{rep['_id']}/ai/summary", {}, T["site"]))
    check("L3.6 summary, client update, suggested progress (not applied)", sm["summary"] and sm["client_update"] and sm["photos"] == 1 and sm["stages"][0]["stage_id"] == S0
          and mongo.projects.find_one({"_id": ObjectId(PID)})["stages"][0].get("progress", 0) == p["stages"][0].get("progress", 0), sm)
    check("L3.6 kept on the report", mongo.site_reports.find_one({"_id": rep["_id"]}).get("ai_summary", {}).get("source") == "sandbox")
    pw = expect("L3.7 weekly project summary", call("POST", f"/projects/{PID}/ai/progress-summary", {"days": 7}, T["pm"]), 201)
    check("L3.7 saved", pw["reports"] == 1 and len(call("GET", f"/projects/{PID}/ai/progress-summary", token=T["pm"])[1]) == 1, pw.get("reports"))
    expect("L3.7 client cannot", call("POST", f"/projects/{PID}/ai/progress-summary", {}, T["client"]), 403)
    us = expect("L3.8 usage counted", call("GET", "/settings/ai", token=T["owner"]))
    check("L3.8 four features this month", {u["feature"] for u in us["usage"]["features"]} >= {"followup", "boq", "photo_summary", "progress_summary"}, us["usage"])
    # claude mode with a bad key: a clear 502, nothing saved
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"ai": {"mode": "claude", "api_key": "sk-ant-invalid-" + RUN}}})
    bad = call("POST", f"/leads/{lead['id']}/ai/followup", {"purpose": "check_in"}, T["sales"])
    check("L3.9 bad key -> readable error", bad[0] == 502 and ("key" in bad[1].get("error", "") or "reach" in bad[1].get("error", "")), bad)
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"ai": {"mode": "sandbox"}}})

    # ======================================= block 4: marketplace =======================================
    expect("L4.1 publish needs selling on", call("POST", f"/marketplace-selling/{rt['id']}", {"price": 80}, T["owner"]), 409)
    prod = expect("product", call("POST", "/rates", {"kind": "product", "name": f"Teak veneer panel {RUN}", "unit": "sheet", "rate": 2400, "brand": "Greenply", "category": "Furniture"}, T["owner"]), 201)
    rates_made.append(prod["id"])
    call("PUT", "/marketplace-selling", {"enabled": True, "contact_email": f"sales{RUN}@skyline.test"}, T["owner"])
    expect("L4.1 only products", call("POST", f"/marketplace-selling/{rt['id']}", {"price": 80}, T["owner"]), 400)
    sl = expect("L4.1 publish a product", call("POST", f"/marketplace-selling/{prod['id']}", {"price": 3100}, T["owner"]))
    check("L4.1 listed", any(x["id"] == prod["id"] and x["listed"] and x["list_price"] == 3100 for x in sl["products"]))
    mi = mongo.market_items.find_one({"product_id": prod["id"]})
    check("L4.1 no cost on the listing", mi and "rate" not in mi and mi["price"] == 3100, mi)
    # a second company (the buyer) — made directly, like the platform would
    other = mongo.companies.insert_one({"name": f"Buyer Interiors {RUN}", "status": "active", "deleted_at": None, "modules": ["interior"], "currency": "INR",
                                        "city": "Pune", "counters": {}, "created_at": datetime.utcnow()})
    other_cid = str(other.inserted_id)
    from app.security import hash_password
    mongo.users.insert_one({"company_id": other_cid, "email": f"buyer{RUN}@x.test", "name": "Buyer Owner", "role": "owner", "kind": "staff",
                            "active": True, "password": hash_password(PW), "created_at": datetime.utcnow()})
    TB = login(f"buyer{RUN}@x.test")
    own = call("GET", "/marketplace", token=T["owner"])[1]
    check("L4.2 seller does not see own listing", all(x["id"] != str(mi["_id"]) for x in own["items"]))
    br = expect("L4.2 buyer browses", call("GET", "/marketplace?q=" + urllib.parse.quote(f"Teak veneer panel {RUN}"), token=TB))
    it = next((x for x in br["items"] if x["id"] == str(mi["_id"])), None)
    check("L4.2 found with seller, no cost", it and it["seller_name"] == "Skyline Interiors" or (it and it["seller_name"]), it)
    check("L4.2 nothing private", it and not set(it) & {"rate", "seller_company_id", "product_id", "seller_email"}, it and sorted(it))
    expect("L4.2 site cannot use it", call("GET", "/marketplace", token=T["site"]), 403)
    ad = expect("L4.3 add to my catalogue", call("POST", f"/marketplace/{mi['_id']}/add", {}, TB), 201)
    check("L4.3 at list price, supplier added", ad["rate"] == 3100 and ad["supplier_name"] and ad["market_item_id"] == str(mi["_id"]), ad)
    check("L4.3 supplier contact in the buyer's company", mongo.contacts.find_one({"company_id": other_cid, "_id": ObjectId(ad["supplier_id"])})["types"] == ["supplier"])
    expect("L4.3 twice refused", call("POST", f"/marketplace/{mi['_id']}/add", {}, TB), 409)
    call("POST", f"/marketplace-selling/{prod['id']}", {"price": 3300}, T["owner"])
    it2 = call("GET", f"/marketplace/{mi['_id']}", token=TB)[1]
    check("L4.4 buyer sees the price change", it2["price_changed"] and it2["price"] == 3300, it2)
    up = expect("L4.4 update my price", call("POST", f"/marketplace/{mi['_id']}/update-price", {}, TB))
    check("L4.4 updated", up["rate"] == 3300 and not call("GET", f"/marketplace/{mi['_id']}", token=TB)[1]["price_changed"])
    expect("L4.5 quantity needed", call("POST", f"/marketplace/{mi['_id']}/enquire", {}, TB), 400)
    eq = expect("L4.5 ask for a quote", call("POST", f"/marketplace/{mi['_id']}/enquire", {"qty": 40, "needed_by": day(14), "note": "Matching edge band"}, TB), 201)
    check("L4.5 seller notified", mongo.notifications.find_one({"company_id": CID, "event": "market_enquiry", "user_id": U["owner"]}) is not None)
    rc = expect("L4.6 seller sees it", call("GET", "/marketplace-enquiries", token=T["owner"]))
    check("L4.6 received", any(x["id"] == eq["id"] for x in rc["received"]))
    expect("L4.6 site cannot quote", call("POST", f"/marketplace-enquiries/{eq['id']}/reply", {"price": 3000}, T["site"]), 403)
    expect("L4.6 buyer cannot quote own enquiry", call("POST", f"/marketplace-enquiries/{eq['id']}/reply", {"price": 3000}, TB), 404)
    rq = expect("L4.6 seller quotes", call("POST", f"/marketplace-enquiries/{eq['id']}/reply", {"price": 3050, "lead_days": 10}, T["owner"]))
    check("L4.6 quoted, buyer sees it", rq["status"] == "quoted" and call("GET", "/marketplace-enquiries", token=TB)[1]["sent"][0]["reply"]["price"] == 3050)
    st_, img, hd = call("GET", f"/public/market/img/{mi['_id']}/0", raw=True)
    check("L4.7 no photo -> 404", st_ == 404, st_)
    call("PUT", "/marketplace-selling", {"enabled": False}, T["owner"])
    check("L4.7 selling off unlists", mongo.market_items.find_one({"_id": mi["_id"]})["published"] is False)
    expect("L4.7 gone for buyers", call("GET", f"/marketplace/{mi['_id']}", token=TB), 404)

    # ======================================= block 5: model linked to progress, AR =======================================
    k_glb = upload("house.glb", T["designer"], b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 56)
    m = expect("model", call("POST", f"/projects/{PID}/models", {"file_key": k_glb, "title": "House", "shared": True}, T["designer"]), 201)
    tk = expect("task", call("POST", f"/projects/{PID}/stages/{S0}/tasks", {"title": f"Wardrobes {RUN}", "start": day(-10), "end": day(-2)}, T["pm"]), 201)
    TID = next(x["id"] for s in tk["stages"] for x in s.get("tasks", []) if x["title"] == f"Wardrobes {RUN}") if "stages" in tk else tk["id"]
    expect("L5.1 stage of this project", call("PUT", f"/models/{m['id']}/links", {"links": [{"element": "Wardrobe_L", "stage_id": "nope"}]}, T["designer"]), 400)
    expect("L5.1 twice", call("PUT", f"/models/{m['id']}/links", {"links": [{"element": "A", "stage_id": S0}, {"element": "A", "stage_id": S0}]}, T["designer"]), 400)
    lk = expect("L5.1 link parts", call("PUT", f"/models/{m['id']}/links", {"links": [{"element": "Wardrobe_L", "label": "Left wardrobe", "stage_id": S0, "task_id": TID},
                                                                                     {"element": "ifc:1234", "stage_id": S0}]}, T["designer"]))
    check("L5.1 linked", lk["linked"] == 2 and lk["links"][0]["task_title"] == f"Wardrobes {RUN}", lk.get("links"))
    pr = expect("L5.2 progress", call("GET", f"/models/{m['id']}/progress", token=T["site"]))
    w_el = next(x for x in pr["elements"] if x["element"] == "Wardrobe_L")
    check("L5.2 task past its end -> late", w_el["status"] == "late", w_el)
    mongo.projects.update_one({"_id": ObjectId(PID), "stages.id": S0}, {"$set": {"stages.$.tasks.$[t].status": "done", "stages.$.tasks.$[t].progress": 100}},
                              array_filters=[{"t.id": TID}])
    pr = call("GET", f"/models/{m['id']}/progress", token=T["site"])[1]
    check("L5.2 done -> green", next(x for x in pr["elements"] if x["element"] == "Wardrobe_L")["status"] == "done" and pr["counts"].get("done") == 1, pr["counts"])
    pp = expect("L5.3 client sees progress colours", call("GET", f"/portal/models/{m['id']}/progress", token=T["client"]))
    check("L5.3 no task ids for the client", pp["elements"] and "task_id" not in pp["elements"][0], pp["elements"])
    k_obj = upload("old.obj", T["designer"], b"v 0 0 0\n")
    mo = expect("obj model", call("POST", f"/projects/{PID}/models", {"file_key": k_obj, "title": "Old"}, T["designer"]), 201)
    expect("L5.4 AR needs GLB", call("POST", f"/models/{mo['id']}/ar", {}, T["designer"]), 400)
    expect("L5.4 site cannot make AR links", call("POST", f"/models/{m['id']}/ar", {}, T["site"]), 403)
    ar = expect("L5.4 AR link", call("POST", f"/models/{m['id']}/ar", {"scale": "fixed"}, T["designer"]))
    token = ar["ar_url"].rsplit("/", 1)[-1]
    pub = expect("L5.5 public AR page data", call("GET", f"/public/ar/{token}"))
    check("L5.5 model source", pub["src"].endswith("/model.glb") and pub["scale"] == "fixed" and pub["title"] == "House", pub)
    st_, body, hd = call("GET", f"/public/ar/{token}/model.glb", raw=True)
    check("L5.5 the phone's AR app can fetch it", st_ == 200 and body[:4] == b"glTF" and hd.get("Access-Control-Allow-Origin") == "*", (st_, hd.get("Content-Type")))
    check("L5.5 wrong extension", call("GET", f"/public/ar/{token}/model.obj", raw=True)[0] == 404)
    call("POST", f"/models/{m['id']}/ar", {"off": True}, T["designer"])
    expect("L5.6 withdrawn", call("GET", f"/public/ar/{token}"), 404)
    check("L5.6 client never sees the AR token", all(x.get("ar_url") is None for x in call("GET", f"/portal/projects/{PID}/models", token=T["client"])[1]))

    # ======================================= block 6: reports and dashboards =======================================
    ds = expect("L6.1 datasets for sales", call("GET", "/report-builder", token=T["sales"]))
    names = {x["key"] for x in ds["datasets"]}
    check("L6.1 sales: leads yes, invoices and costs no", "leads" in names and "invoices" not in names and "costs" not in names, names)
    expect("L6.1 site cannot run costs", call("POST", "/report-builder/run", {"dataset": "costs"}, T["site"]), 403)
    expect("L6.1 unknown grouping", call("POST", "/report-builder/run", {"dataset": "leads", "group_by": ["salary"]}, T["owner"]), 400)
    r1 = expect("L6.2 leads by source", call("POST", "/report-builder/run", {"dataset": "leads", "group_by": ["source"], "measures": ["count", "budget"], "range": {"last_days": 30}}, T["owner"]))
    check("L6.2 grouped with totals", r1["rows"] and r1["totals"]["count"] == r1["matched"] and r1["columns"][0]["label"] == "Source", r1["columns"])
    rs = call("POST", "/report-builder/run", {"dataset": "leads", "group_by": ["owner"]}, T["sales"])[1]
    check("L6.2 salesperson sees own leads only", all(r["keys"][0] in ("Sales User", mongo.users.find_one({"_id": ObjectId(U["sales"])})["name"]) for r in rs["rows"]), rs["rows"])
    r2_ = expect("L6.3 incidents by kind and month", call("POST", "/report-builder/run", {"dataset": "incidents", "group_by": ["kind", "month"], "measures": ["count", "lost_days"],
                                                                                          "filters": {"project": [f"PhaseL {RUN}"]}}, T["pm"]))
    check("L6.3 two groups", sorted(r["keys"][0] for r in r2_["rows"]) == ["lost_time", "near_miss"] and r2_["totals"]["lost_days"] == 3, r2_["rows"])
    st_, csvb, hd = call("POST", "/report-builder/csv", {"dataset": "incidents", "group_by": ["kind"], "filters": {"project": [f"PhaseL {RUN}"]}}, T["pm"], raw=True)
    check("L6.4 CSV", st_ == 200 and csvb.decode().startswith("Kind,Incidents") and "Total" in csvb.decode(), csvb[:80])
    vals = expect("L6.4 filter values", call("GET", "/report-builder/values?dataset=incidents&dim=kind", token=T["pm"]))
    check("L6.4 values", "lost_time" in vals, vals)
    expect("L6.5 only owner or PM share", call("POST", "/saved-reports", {"name": "x", "shared": True, "spec": {"dataset": "leads"}}, T["sales"]), 403)
    sv = expect("L6.5 save and schedule", call("POST", "/saved-reports", {"name": f"Safety {RUN}", "shared": True, "spec": {"dataset": "incidents", "group_by": ["kind"]},
                                                                          "schedule": {"every": "week", "to": [U["owner"]]}}, T["pm"]), 201)
    check("L6.5 sales sees the shared report but cannot run it", any(x["id"] == sv["id"] and not x["can_run"] for x in call("GET", "/saved-reports", token=T["sales"])[1]))
    expect("L6.5 someone else cannot edit", call("PUT", f"/saved-reports/{sv['id']}", {"name": "y"}, T["sales"]), 403)
    rr = expect("L6.5 run saved", call("GET", f"/saved-reports/{sv['id']}/run", token=T["owner"]))
    check("L6.5 named", rr["name"] == f"Safety {RUN}")
    monday = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time()).replace(hour=9)
    worker(monday)
    check("L6.6 weekly email marked sent on Monday", mongo.saved_reports.find_one({"_id": ObjectId(sv["id"])})["schedule"]["last_sent"] == monday.date().isoformat())
    expect("L6.7 only owner shares dashboards", call("POST", "/dashboards", {"name": "x", "shared": True}, T["pm"]), 403)
    db_ = expect("L6.7 my dashboard", call("POST", "/dashboards", {"name": f"Board {RUN}", "widgets": [
        {"title": "Open leads", "chart": "kpi", "spec": {"dataset": "leads", "measures": ["count"], "filters": {"status": ["open"]}}},
        {"chart": "bar", "report_id": sv["id"]}, {"chart": "pie", "spec": {"dataset": "invoices", "group_by": ["status"], "measures": ["total"]}}]}, T["owner"]), 201)
    dd = expect("L6.7 data", call("GET", f"/dashboards/{db_['id']}/data", token=T["owner"]))
    check("L6.7 three widgets with results", len(dd["widgets"]) == 3 and all("result" in x for x in dd["widgets"]) and dd["widgets"][1]["title"] == f"Safety {RUN}", [x.get("error") for x in dd["widgets"]])
    expect("L6.7 others cannot see a private dashboard", call("GET", f"/dashboards/{db_['id']}/data", token=T["pm"]), 404)
    call("PUT", f"/dashboards/{db_['id']}", {"shared": True}, T["owner"])
    sd = call("GET", f"/dashboards/{db_['id']}/data", token=T["sales"])[1]
    check("L6.8 shared: sales sees leads, not invoices", "result" in sd["widgets"][0] and "error" in sd["widgets"][2] and "error" in sd["widgets"][1], [x.get("error") for x in sd["widgets"]])
    call("DELETE", f"/saved-reports/{sv['id']}", token=T["pm"])
    check("L6.9 deleting a report removes its widget", len(mongo.dashboards.find_one({"_id": ObjectId(db_["id"])})["widgets"]) == 2)

    # ======================================= block 7: languages and per-project currency =======================================
    expect("L7.1 Tamil", call("PUT", "/me/language", {"language": "ta"}, T["site"]))
    expect("L7.1 unknown language", call("PUT", "/me/language", {"language": "xx"}, T["site"]), 400)
    call("PUT", "/me/language", {"language": "en"}, T["site"])
    expect("L7.2 worker language", call("PUT", f"/site-workers/{w['id']}", {"language": "zz"}, T["site"]), 400)
    from app import create_app
    with create_app().test_request_context():
        from flask import g
        from app.routes.field import morning_text, buttons_for
        g.company = mongo.companies.find_one({"_id": ObjectId(CID)})
        txt = morning_text({"name": "Ramesh", "language": "ta"}, [])
        btn = buttons_for("bn")
    check("L7.2 Tamil morning message", txt.startswith("காலை வணக்கம் Ramesh"), txt[:40])
    check("L7.2 Bengali buttons", [b[1] for b in btn] == ["মাল লাগবে", "কাজ শেষ", "সাহায্য দরকার"], btn)
    expect("L7.3 unsupported currency", call("POST", "/projects", {"name": f"Dubai {RUN}", "services": ["interior"], "currency": "XYZ"}, T["owner"]), 400)
    pu = expect("L7.3 project in AED", call("POST", "/projects", {"name": f"Dubai villa {RUN}", "services": ["interior"], "currency": "AED", "client_id": CLIENT_CONTACT}, T["owner"]), 201)
    projects.append(pu["id"])
    check("L7.3 kept", pu["currency"] == "AED", pu.get("currency"))
    check("L7.3 default is the company's", p.get("currency") == (company_before.get("currency") or "INR"), p.get("currency"))
    inv = expect("L7.4 invoice in the project's currency", call("POST", f"/projects/{pu['id']}/invoices", {"lines": [{"description": "Design fee", "qty": 1, "rate": 10000}]}, T["owner"]), 201)
    check("L7.4 AED", inv.get("currency") == "AED", inv.get("currency"))
    expect("L7.5 currency locked after invoicing", call("PUT", f"/projects/{pu['id']}", {"currency": "USD"}, T["owner"]), 409)
    expect("L7.6 bad rate", call("PUT", "/company/setup", {"fx_rates": {"AED": -1}}, T["owner"]), 400)
    expect("L7.6 exchange rates", call("PUT", "/company/setup", {"fx_rates": {"AED": 22.5}}, T["owner"]))
    rp = expect("L7.6 report adds up in the company currency", call("POST", "/report-builder/run", {"dataset": "invoices", "group_by": ["currency"], "measures": ["total"],
                                                                                                    "filters": {"project": [f"Dubai villa {RUN}"]}}, T["owner"]))
    check("L7.6 AED converted", rp["rows"] and rp["rows"][0]["keys"] == ["AED"] and rp["rows"][0]["total"] == round(inv["total"] * 22.5, 2), rp["rows"])
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": {"ai": {"mode": "claude", "api_key": "sk-ant-secret-" + RUN}}})
    co = expect("L7.7 company settings", call("GET", "/company", token=T["owner"]))
    check("L7.7 saved keys never returned", co["ai"]["api_key"] == "•••" and f"sk-ant-secret-{RUN}" not in json.dumps(co), co.get("ai"))
except Exception:  # noqa: BLE001 — report what passed and failed so far, then the crash
    import traceback
    traceback.print_exc()
    failures.append("CRASH (see the traceback above)")
finally:
    pids = projects if not os.getenv("KEEP") else []
    for col in ("notifications", "project_activity", "site_reports", "attendance", "snags", "incidents", "inspections", "toolbox_talks", "invoices", "models3d", "ai_drafts"):
        mongo[col].delete_many({"company_id": CID, "project_id": {"$in": pids}})
    mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
    mongo.sync_ops.delete_many({"company_id": CID, "op_id": {"$regex": f"^op-{RUN}"}})
    mongo.sync_ops.delete_many({"company_id": CID, "op_id": "x"})
    lead_contacts = [x.get("contact_id") for x in mongo.leads.find({"_id": {"$in": [ObjectId(x) for x in leads]}})]
    mongo.estimates.delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    mongo.ai_drafts.delete_many({"company_id": CID, "lead_id": {"$in": leads}})
    mongo.followups.delete_many({"company_id": CID, "related.id": {"$in": leads}})
    mongo.leads.delete_many({"_id": {"$in": [ObjectId(x) for x in leads]}})
    mongo.contacts.delete_many({"_id": {"$in": [ObjectId(x) for x in contacts_made + [c for c in lead_contacts if c]]}})
    mongo.site_workers.delete_many({"_id": {"$in": [ObjectId(x) for x in workers_made]}})
    mongo.rate_library.delete_many({"_id": {"$in": [ObjectId(x) for x in rates_made]}})
    mongo.market_items.delete_many({"product_id": {"$in": rates_made}})
    mongo.market_enquiries.delete_many({"seller_company_id": CID})
    mongo.files.delete_many({"company_id": CID, "key": {"$in": keys}})
    mongo.ai_usage.delete_many({"company_id": CID})
    mongo.saved_reports.delete_many({"company_id": CID, "name": {"$regex": RUN}})
    mongo.dashboards.delete_many({"company_id": CID, "name": {"$regex": RUN}})
    mongo.notifications.delete_many({"company_id": CID, "event": {"$in": ["safety_incident", "safety_action", "inspection_failed", "market_enquiry"]}})
    if other_cid:
        for col in ("users", "contacts", "rate_library", "audit_logs", "notifications"):
            mongo[col].delete_many({"company_id": other_cid})
        mongo.market_enquiries.delete_many({"buyer_company_id": other_cid})
        mongo.companies.delete_one({"_id": ObjectId(other_cid)})
    restore = {k: company_before.get(k) for k in ("safety", "ai", "marketplace", "fx_rates")}
    mongo.companies.update_one({"_id": ObjectId(CID)}, {"$set": restore})

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
