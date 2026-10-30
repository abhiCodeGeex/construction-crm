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
            "company_id": cid, "name": contact_name or name, "person": name, "email": email, "types": [role],
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


if __name__ == "__main__":
    ensure_indexes()
    run()
    if os.getenv("SEED_DEMO", "1") == "1":
        demo()
        print("demo users ready")
