"""Run migrations, then (when SEED_DEMO=1) create demo users for every role. Safe to run repeatedly."""
import os
from datetime import timedelta

from app.db import db, ensure_indexes
from app.migrations import run
from app.security import hash_password, INTERNAL_ROLES, EXTERNAL_ROLES, ROLE_LABELS
from app.services.tenant_setup import bootstrap_company
from app.tenancy import now

DEMO_PASSWORD = "Demo@123"
SA_TEAM = [("billing", "Billing Staff"), ("support", "Support Staff"), ("sales", "Sales Staff"), ("viewer", "Viewer")]


def company(name, email_domain, plan, types, modules, status="active"):
    existing = db.companies.find_one({"name": name})
    if existing:
        return str(existing["_id"]), False
    c = {"name": name, "types": types, "modules": modules, "plan_code": plan, "billing_cycle": "monthly",
         "status": status, "trial_ends": now() + timedelta(days=14), "currency": "INR", "tax_rate": 18.0,
         "tax_label": "GST", "city": "Bengaluru", "branches": [{"name": "Head office", "city": "Bengaluru"}],
         "branding": {"primary": "#1f6feb"}, "numbering": {}, "counters": {}, "allow_support_login": False,
         "owner_email": f"owner@{email_domain}", "created_at": now()}
    cid = str(db.companies.insert_one(c).inserted_id)
    bootstrap_company(cid, modules)
    return cid, True


def user(cid, role, email, name, kind="staff", contact_name=None):
    if db.users.find_one({"email": email}):
        return
    doc = {"company_id": cid, "name": name, "email": email, "password": hash_password(DEMO_PASSWORD), "role": role,
           "kind": kind, "active": True, "created_at": now()}
    if kind == "external":
        doc["contact_id"] = str(db.contacts.insert_one({
            "company_id": cid, "name": contact_name or name, "kind": "company", "email": email,
            "types": [{"vendor": "supplier"}.get(role, role)], "compliance": [],
            "created_at": now()}).inserted_id)
    db.users.insert_one(doc)


def demo():
    for role, name in SA_TEAM:
        db.superadmin_users.update_one({"email": f"sa-{role}@buildsuite.test"}, {"$setOnInsert": {
            "name": name, "role": role, "password": hash_password("Admin@12345"), "totp_demo": "123456",
            "active": True, "created_at": now()}}, upsert=True)

    cid, _ = company("Skyline Design & Build", "skyline.test", "pro", ["architect", "contractor", "interior"],
                     ["architecture", "construction", "interior"])
    for role in INTERNAL_ROLES:
        user(cid, role, f"{role}@skyline.test", f"{ROLE_LABELS[role]} (Skyline)")
    for role in EXTERNAL_ROLES:
        user(cid, role, f"{role}@skyline.test", f"Demo {ROLE_LABELS[role]}", "external", f"{ROLE_LABELS[role]} Co.")

    # second tenant on the Basic plan: tests data isolation and the 5-user / 1-module limits
    cid2, _ = company("Nest Interiors", "nest.test", "basic", ["interior"], ["interior"])
    user(cid2, "owner", "owner@nest.test", "Nest Owner")
    user(cid2, "designer", "designer@nest.test", "Nest Designer")



def demo_projects():
    """Phase B demo data, created through the real API so it passes the same validation as the UI."""
    from datetime import date, timedelta
    from app import create_app

    cid = str(db.companies.find_one({"name": "Skyline Design & Build"})["_id"])
    if db.projects.count_documents({"company_id": cid}):
        return
    api = create_app().test_client()
    tok = api.post("/api/auth/login", json={"email": "owner@skyline.test", "password": DEMO_PASSWORD}).json["token"]
    h = {"Authorization": f"Bearer {tok}"}

    def call(method, path, body=None):
        r = api.open(f"/api{path}", method=method, json=body, headers=h)
        assert r.status_code < 300, (path, r.status_code, r.json)
        return r.json

    day = lambda n: (date.today() + timedelta(days=n)).isoformat()
    uid = {u["email"].split("@")[0]: str(u["_id"]) for u in db.users.find({"company_id": cid})}
    contact = {u["role"]: u["contact_id"] for u in db.users.find({"company_id": cid, "kind": "external"})}

    supplier = contact["vendor"]
    call("PUT", f"/contacts/{supplier}", {
        "name": "Vendor / Supplier Co.", "types": ["supplier"], "trade_category": "Tiles & sanitaryware", "rating": 4,
        "gstin": "29AAACV1234F1Z5", "trade_account_no": "TA-7781", "discount_pct": 12,
        "bank": {"account_name": "Vendor Supplier Co", "account_no": "001234567890", "ifsc": "HDFC0001234",
                 "bank_name": "HDFC Bank"},
        "compliance": [
            {"type": "certificate", "name": "GST registration", "number": "29AAACV1234F1Z5", "expiry": None},
            {"type": "insurance", "name": "Public liability insurance", "issuer": "ICICI Lombard",
             "issue_date": day(-355), "expiry": day(10)},
            {"type": "licence", "name": "Trade licence", "issue_date": day(-400), "expiry": day(-5)}]})
    call("PUT", f"/contacts/{contact['consultant']}", {"name": "Consultant Co.", "types": ["consultant", "client"],
                                                       "trade_category": "Structural engineering", "rating": 5})
    call("POST", "/contacts", {"name": "Priya Mehta", "kind": "person", "types": ["client"],
                               "org_id": contact["client"], "email": "priya.mehta@example.test",
                               "designation": "Home owner", "referred_by": contact["consultant"]})

    p1 = call("POST", "/projects", {
        "name": "Mehta Residence", "services": ["architecture", "construction", "interior"],
        "client_id": contact["client"], "project_type": "New build", "start": day(-30), "area": 3200,
        "area_unit": "sqft", "value": 18500000, "branch": "Head office", "referred_by": contact["consultant"],
        "site": {"line1": "14 Palm Grove Road", "city": "Bengaluru", "state": "Karnataka", "pincode": "560037",
                 "country": "India", "lat": 12.9592, "lng": 77.6974}})
    pid = p1["id"]
    for email, role, access in (("pm", "Project Manager", "edit"), ("designer", "Architect", "edit"),
                                ("site", "Site Supervisor", "view"), ("estimator", "Estimator / QS", "view"),
                                ("accounts", "Accounts", "view")):
        if email != "owner":
            call("POST", f"/projects/{pid}/team", {"user_id": uid[email], "project_role": role, "access": access})
    call("POST", f"/projects/{pid}/team", {"contact_id": contact["consultant"], "project_role": "Structural Consultant"})
    call("POST", f"/projects/{pid}/team", {"contact_id": supplier, "project_role": "Supplier"})

    p = call("GET", f"/projects/{pid}")
    concept = next(s for s in p["stages"] if s["service"] == "architecture")
    found = next(s for s in p["stages"] if s["name"] == "Foundation")
    call("PUT", f"/projects/{pid}/stages/{found['id']}", {"budget": 500000})
    t1 = call("POST", f"/projects/{pid}/stages/{concept['id']}/tasks", {
        "title": "Client brief workshop", "start": concept["start"], "end": day(-25), "assignee_id": uid["designer"]})
    brief = t1["stages"][0]["tasks"][0]["id"]
    call("PUT", f"/projects/{pid}/tasks/{brief}", {"status": "done"})
    call("POST", f"/projects/{pid}/stages/{concept['id']}/tasks", {
        "title": "Concept sketches", "start": day(-24), "end": day(-10), "assignee_id": uid["designer"],
        "depends_on": [brief]})
    s2 = call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
        "title": "Excavation", "start": found["start"], "end": (date.fromisoformat(found["start"]) + timedelta(days=5)).isoformat(),
        "assignee_id": uid["site"]})
    exc = next(tk for s in s2["stages"] if s["id"] == found["id"] for tk in s["tasks"])["id"]
    call("POST", f"/projects/{pid}/stages/{found['id']}/tasks", {
        "title": "PCC and footing", "start": found["end"], "end": found["end"], "assignee_id": uid["site"],
        "depends_on": [exc]})
    call("POST", f"/projects/{pid}/issues", {"title": "Soil test report pending from lab", "severity": "high",
                                             "owner_id": uid["pm"], "due": day(3)})

    # the same firm is a partner on Mehta Residence and the client here (§3 roles per project)
    call("POST", "/projects", {"name": "Orchid Office Fit-out", "services": ["construction", "interior"],
                               "client_id": contact["consultant"], "project_type": "Fit-out", "start": day(-5),
                               "area": 450, "area_unit": "sqm", "value": 6200000, "branch": "Head office",
                               "site": {"line1": "Level 6, Orchid Towers", "city": "Bengaluru", "country": "India"}})


def demo_leads():
    """Phase C demo data via the real API."""
    from datetime import date, timedelta
    from app import create_app

    cid = str(db.companies.find_one({"name": "Skyline Design & Build"})["_id"])
    if db.leads.count_documents({"company_id": cid}):
        return
    api = create_app().test_client()
    login = lambda e: {"Authorization": "Bearer " + api.post("/api/auth/login", json={"email": e, "password": DEMO_PASSWORD}).json["token"]}
    sales, owner = login("sales@skyline.test"), login("owner@skyline.test")

    def call(h, method, path, body=None):
        r = api.open(f"/api{path}", method=method, json=body, headers=h)
        assert r.status_code < 300, (path, r.status_code, r.json)
        return r.json

    day = lambda n: (date.today() + timedelta(days=n)).isoformat()
    uid = {u["email"].split("@")[0]: str(u["_id"]) for u in db.users.find({"company_id": cid})}
    consultant = db.users.find_one({"company_id": cid, "role": "consultant"})["contact_id"]
    rows = [
        ("Sharma duplex – new build", "construction", "New build", "Referral", "Rohit Sharma", "9845012345", 4200000, "3–6 months", "Site visit"),
        ("Iyer apartment interiors", "interior", "Interior", "Houzz/portals", "Meera Iyer", "9880011223", 1800000, "1–3 months", "Proposal/Bid"),
        ("Green Leaf café fit-out", "interior", "Fit-out", "Walk-in", "Green Leaf Foods", "9900022334", 2600000, "Immediately", "Negotiation"),
        ("Rao farmhouse design", "architecture", "New build", "Ads", "Anil Rao", "9811133445", 3500000, "6–12 months", "Lead"),
        ("Kulkarni bungalow renovation", "construction", "Renovation", "Website form", "Sneha Kulkarni", "9822244556", 2900000, "1–3 months", "Lead"),
    ]
    ids = []
    for title, svc, ptype, src, name, phone, budget, tl, stage in rows:
        body = {"title": title, "service": svc, "project_type": ptype, "source": src, "contact_name": name,
                "contact_phone": phone, "budget": budget, "timeline": tl, "location": "Bengaluru", "area": 2400,
                "area_unit": "sqft", "owner_id": uid["sales"]}
        if src == "Referral":
            body["referred_by"] = consultant
        lead = call(sales, "POST", "/leads", body)
        if stage != lead["stage"]:
            call(sales, "POST", f"/leads/{lead['id']}/stage", {"stage": stage})
        ids.append(lead["id"])
    call(sales, "POST", f"/leads/{ids[0]}/activities", {"type": "call", "text": "Discussed G+1 plan and budget", "outcome": "Site visit booked"})
    call(sales, "POST", f"/leads/{ids[1]}/activities", {"type": "whatsapp", "text": "Shared portfolio of 3BHK interiors"})
    call(sales, "POST", f"/leads/{ids[2]}/activities", {"type": "meeting", "text": "Menu-board and seating layout discussed; wants quote revision"})
    call(sales, "POST", "/followups", {"title": "Confirm site visit time", "due": day(0), "priority": "high", "channel": "call",
                                       "related": {"type": "lead", "id": ids[0]}})
    call(sales, "POST", "/followups", {"title": "Send revised quote", "due": day(-2), "priority": "high", "channel": "email",
                                       "related": {"type": "lead", "id": ids[2]}})
    call(sales, "POST", "/followups", {"title": "Check if portfolio was useful", "due": day(3), "channel": "whatsapp",
                                       "related": {"type": "lead", "id": ids[1]}})
    won = call(sales, "POST", "/leads", {"title": "Nair villa interiors", "service": "interior", "project_type": "Interior",
                                         "source": "Repeat client", "contact_id": consultant, "budget": 2200000, "owner_id": uid["sales"],
                                         "force": True})
    call(sales, "POST", f"/leads/{won['id']}/win", {"pm_id": uid["pm"]})
    lost = call(sales, "POST", "/leads", {"title": "Patel office extension", "service": "construction", "source": "Ads",
                                          "contact_name": "Patel Logistics", "contact_phone": "9833355667", "budget": 5100000,
                                          "owner_id": uid["sales"]})
    call(sales, "POST", f"/leads/{lost['id']}/lose", {"reason": "Price too high", "note": "Went with a cheaper local builder"})
    call(sales, "POST", "/bids", {"title": "Municipal school block – tender", "service": "construction", "due_date": day(12),
                                  "value": 14500000, "decision": "bid", "status": "preparing", "reference": "BBMP/2026/114"})
    b = call(sales, "POST", "/bids", {"title": "Tech park lobby fit-out", "service": "interior", "due_date": day(-20),
                                      "value": 7800000, "decision": "bid", "status": "preparing",
                                      "client_id": consultant})
    call(sales, "PUT", f"/bids/{b['id']}", {"status": "submitted"})
    call(sales, "POST", f"/bids/{b['id']}/won", {"pm_id": uid["pm"]})
    call(sales, "POST", "/bids", {"title": "Hospital wing – design & build", "service": "construction", "due_date": day(5),
                                  "decision": "no_bid", "decision_reason": "Outside our capacity this quarter"})

if __name__ == "__main__":
    ensure_indexes()
    run()
    if os.getenv("SEED_DEMO", "1") == "1":
        demo()
        demo_projects()
        demo_leads()
        print("demo users ready")
