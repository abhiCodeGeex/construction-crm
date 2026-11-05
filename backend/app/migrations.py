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


def m006_phase_c():
    """Phase C: loss reasons + website-form key per company, indexes, and default message templates whose
    merge fields are valid (§16). Templates a company created itself are left untouched."""
    import secrets
    from .services.defaults import LOSS_REASONS, MESSAGE_TEMPLATES, PIPELINE
    old_fields = ("{{worker}}", "{{site}}", "{{room}}", "{{task}}", "{{drawing}}", "{{supervisor}}", "{{number}}",
                  "{{due_date}}")
    for c in db.companies.find({}):
        cid = str(c["_id"])
        sets = {}
        if not c.get("loss_reasons"):
            sets["loss_reasons"] = LOSS_REASONS
        if not c.get("lead_form_key"):
            sets["lead_form_key"] = secrets.token_urlsafe(16)
        if not c.get("pipelines"):
            sets["pipelines"] = {s: PIPELINE for s in ("architecture", "construction", "interior")}
        if sets:
            db.companies.update_one({"_id": c["_id"]}, {"$set": sets})
        removed = db.message_templates.delete_many({"company_id": cid, "created_by": None, "$or": [
            {"body": {"$regex": f.replace("{", r"\{").replace("}", r"\}")}} for f in old_fields]}).deleted_count
        if removed or not db.message_templates.count_documents({"company_id": cid}):
            for tpl in MESSAGE_TEMPLATES:
                if not db.message_templates.find_one({"company_id": cid, "name": tpl["name"]}):
                    db.message_templates.insert_one({**tpl, "company_id": cid, "created_at": now(), "created_by": None})
    db.leads.create_index([("company_id", 1), ("status", 1), ("service", 1)])
    db.leads.create_index([("company_id", 1), ("phone_key", 1)])
    db.leads.create_index([("company_id", 1), ("email_key", 1)])
    db.followups.create_index([("company_id", 1), ("owner_id", 1), ("status", 1), ("due", 1)])
    db.followups.create_index([("company_id", 1), ("related.id", 1)])
    db.companies.create_index("lead_form_key")
    db.form_hits.create_index("at", expireAfterSeconds=3600)


def m007_leads_deep():
    """Phase C+: days-in-stage starts from the last stage change of existing leads; indexes for the bell,
    reminders and appointments."""
    for lead in db.leads.find({"stage_entered_at": {"$exists": False}}, {"stage_history": 1, "created_at": 1}):
        hist = lead.get("stage_history") or []
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {
            "stage_entered_at": hist[-1]["at"] if hist else lead.get("created_at")}})
    db.notifications.create_index([("company_id", 1), ("user_id", 1), ("read_at", 1), ("created_at", -1)])
    db.notifications.create_index([("company_id", 1), ("user_id", 1), ("key", 1)])
    db.lead_visits.create_index([("company_id", 1), ("lead_id", 1)])
    db.lead_visits.create_index([("company_id", 1), ("status", 1), ("at", 1)])


MIGRATIONS = [
    ("001_plans", m001_plans),
    ("002_superadmin_owner", m002_superadmin_owner),
    ("003_stage_template_durations", m003_stage_template_durations),
    ("004_project_indexes", m004_project_indexes),
    ("005_contact_types", m005_contact_types),
    ("006_phase_c", m006_phase_c),
    ("007_leads_deep", m007_leads_deep),
]


def run():
    done = {m["_id"] for m in db.schema_migrations.find({}, {"_id": 1})}
    for key, fn in MIGRATIONS:
        if key in done:
            continue
        fn()
        db.schema_migrations.insert_one({"_id": key, "applied_at": now()})
        print(f"migration applied: {key}")
