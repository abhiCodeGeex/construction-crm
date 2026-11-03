"""Versioned, idempotent data migrations.

Each migration runs once and is recorded in `schema_migrations`. Future modules add new numbered
functions to MIGRATIONS — never edit one that has already shipped — so every environment
(local, staging, production) converges to the same state without conflicts.
"""
from .db import db
from .security import hash_password
from .tenancy import now

PLANS = [
    {"code": "basic", "name": "Basic", "price_monthly": 3500, "max_users": 5, "max_projects": 5, "max_modules": 1,
     "whatsapp_messages": 1000, "storage_gb": 50, "support": "Email"},
    {"code": "pro", "name": "Pro", "price_monthly": 8500, "max_users": 15, "max_projects": None, "max_modules": 3,
     "whatsapp_messages": 5000, "storage_gb": 250, "support": "Email + chat"},
    {"code": "enterprise", "name": "Enterprise", "price_monthly": 12500, "max_users": 50, "max_projects": None,
     "max_modules": 3, "whatsapp_messages": None, "storage_gb": 1024, "support": "Priority + onboarding"},
]


def m001_plans():
    for p in PLANS:
        db.plans.update_one({"code": p["code"]}, {"$setOnInsert": {
            **p, "price_yearly": p["price_monthly"] * 10, "price_monthly_gst": round(p["price_monthly"] * 1.18, 2),
            "active": True, "created_at": now()}}, upsert=True)


def m002_superadmin_owner():
    db.superadmin_users.update_one({"email": "superadmin@buildsuite.test"}, {"$setOnInsert": {
        "name": "Platform Owner", "role": "owner", "password": hash_password("Admin@12345"),
        "totp_demo": "123456", "active": True, "created_at": now()}}, upsert=True)


def m003_stage_template_durations():
    """Phase B: template stages become {name, duration_days} (Phase A stored plain names)."""
    from .services.defaults import template_stages
    for tpl in db.stage_templates.find({"stages.0": {"$type": "string"}}):
        db.stage_templates.update_one({"_id": tpl["_id"]}, {"$set": {"stages": template_stages(tpl["stages"])}})


def m004_project_indexes():
    db.projects.create_index([("company_id", 1), ("team.user_id", 1)])
    db.projects.create_index([("company_id", 1), ("team.contact_id", 1)])
    db.contacts.create_index([("company_id", 1), ("name", 1)])
    db.project_issues.create_index([("company_id", 1), ("project_id", 1)])


def m005_contact_types():
    """Phase A created portal contacts with the portal role as type; §3 uses 'supplier' for vendors."""
    db.contacts.update_many({"types": "vendor"}, {"$set": {"types.$": "supplier"}})
    db.contacts.update_many({"kind": {"$exists": False}}, {"$set": {"kind": "company"}})
    db.contacts.update_many({"compliance": {"$exists": False}}, {"$set": {"compliance": []}})


MIGRATIONS = [
    ("001_plans", m001_plans),
    ("002_superadmin_owner", m002_superadmin_owner),
    ("003_stage_template_durations", m003_stage_template_durations),
    ("004_project_indexes", m004_project_indexes),
    ("005_contact_types", m005_contact_types),
]


def run():
    done = {m["_id"] for m in db.schema_migrations.find({}, {"_id": 1})}
    for key, fn in MIGRATIONS:
        if key in done:
            continue
        fn()
        db.schema_migrations.insert_one({"_id": key, "applied_at": now()})
        print(f"migration applied: {key}")
