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


def m008_phase_d():
    """Phase D: one editable proposal template per enabled service (fee / construction / interior), indexes."""
    from .services.defaults import SERVICE_PROPOSAL_TYPE, TEMPLATE_TEXT, PROPOSAL_TYPES
    for c in db.companies.find({}):
        cid = str(c["_id"])
        for service in c.get("modules", []):
            ptype = SERVICE_PROPOSAL_TYPE.get(service)
            if not ptype or db.proposal_templates.find_one({"company_id": cid, "type": ptype}):
                continue
            db.proposal_templates.insert_one({"company_id": cid, "name": f"Standard {PROPOSAL_TYPES[ptype].lower()}", "type": ptype,
                                              "service": service, **TEMPLATE_TEXT[ptype], "scope_text": None, "items": [],
                                              "fee": None, "payment_schedule": [], "created_at": now(), "created_by": None})
    db.proposals.create_index("token", sparse=True)
    db.proposals.create_index([("company_id", 1), ("lead_id", 1)])
    db.contracts.create_index([("company_id", 1), ("lead_id", 1)])
    db.contracts.create_index([("company_id", 1), ("project_id", 1)])


def m009_projects_plus():
    """B+1: Super Admin two-factor uses a real authenticator app, so the fixed demo code goes; everyone sets up
    their app at the next sign-in. Indexes for project notifications and password-reset links."""
    db.superadmin_users.update_many({}, {"$unset": {"totp_demo": ""}})
    # audit rows written before B+1 kept the password hash of a reset; keep only "changed"
    db.audit_logs.update_many({"changes.password": {"$exists": True}},
                              {"$set": {"changes.password": {"from": "•••", "to": "••• (changed)"}}})
    db.notifications.create_index([("company_id", 1), ("project_id", 1)], sparse=True)
    db.password_resets.create_index("token_hash", unique=True)
    db.password_resets.create_index("expires_at", expireAfterSeconds=0)  # Mongo removes used-up links itself


def m010_stage_gates():
    """B+2: every stage closes through its '<stage> complete' milestone (the gate) with a closing checklist and,
    where the service needs it, the client's sign-off. Template stages get the service defaults; open stages of
    existing projects get them too (stages already done keep an empty checklist and need no sign-off)."""
    from .services.defaults import gate_defaults
    from .tenancy import sid
    for tpl in db.stage_templates.find({}):
        gate = gate_defaults(tpl.get("service"))
        stages = [{**gate, **s} if isinstance(s, dict) else s for s in tpl.get("stages", [])]
        db.stage_templates.update_one({"_id": tpl["_id"]}, {"$set": {"stages": stages}})
    for p in db.projects.find({}):
        changed = False
        for s in p.get("stages", []):
            if "checklist" not in s:
                done = s.get("status") == "done"
                gate = gate_defaults(s.get("service"))
                s["checklist"] = [] if done else [{"id": sid(), "text": x, "done": False,
                                                    "done_by": None, "done_at": None} for x in gate["checklist"]]
                s["client_signoff_required"] = False if done else gate["client_signoff"]
                s.setdefault("signoff", None)
                changed = True
            gm = next((m for m in s.get("milestones", []) if m.get("name") == f"{s['name']} complete"), None)
            if gm and not gm.get("gate"):
                gm["gate"] = True
                changed = True
            for tk in s.get("tasks", []):
                for k, v in (("priority", "normal"), ("checklist", []), ("files", [])):
                    if k not in tk:
                        tk[k] = v
                        changed = True
        if changed:
            db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": p["stages"]}})
    db.project_comments.create_index([("company_id", 1), ("project_id", 1), ("task_id", 1)])
    db.project_activity.create_index([("company_id", 1), ("project_id", 1), ("at", -1)])


def m011_plan_meetings():
    """B+3 / B+4: indexes for delays and meetings."""
    db.project_delays.create_index([("company_id", 1), ("project_id", 1), ("at", -1)])
    db.project_meetings.create_index([("company_id", 1), ("project_id", 1), ("at", -1)])
    db.project_meetings.create_index([("company_id", 1), ("status", 1), ("at", 1)])


def m012_finance():
    """Phase E: indexes for costs (per project and stage, and the company list)."""
    db.costs.create_index([("company_id", 1), ("project_id", 1), ("stage_id", 1), ("status", 1)])
    db.costs.create_index([("company_id", 1), ("status", 1), ("date", -1)])


def m013_invoices():
    """Phase E block 2: invoices per project, by status and due date (overdue reminders)."""
    db.invoices.create_index([("company_id", 1), ("project_id", 1), ("created_at", -1)])
    db.invoices.create_index([("company_id", 1), ("status", 1), ("due_date", 1)])


def m014_receipts():
    """Phase E block 3: receipts per project."""
    db.receipts.create_index([("company_id", 1), ("project_id", 1), ("date", -1)])


def m015_change_orders():
    """Phase E block 4: change orders per project and by status (the unanswered reminder)."""
    db.change_orders.create_index([("company_id", 1), ("project_id", 1), ("created_at", -1)])
    db.change_orders.create_index([("company_id", 1), ("status", 1), ("sent_at", 1)])


def m016_documents():
    """Phase F block 1: the document library per project (and the file lookup that keeps each file in one place)."""
    db.documents.create_index([("company_id", 1), ("project_id", 1), ("folder", 1)])
    db.documents.create_index([("company_id", 1), ("versions.file_key", 1)])


def m017_transmittals():
    """Phase F block 2: transmittals per project and the unacknowledged reminder."""
    db.transmittals.create_index([("company_id", 1), ("project_id", 1), ("created_at", -1)])
    db.transmittals.create_index([("company_id", 1), ("acknowledged", 1), ("created_at", 1)])


def m018_selections():
    """Phase F block 3: selections per project and by due date (reminders, waiting on client)."""
    db.selections.create_index([("company_id", 1), ("project_id", 1), ("stage_id", 1)])
    db.selections.create_index([("company_id", 1), ("status", 1), ("due_date", 1)])


def m019_site_reports():
    """Phase F block 4: one site report per project per day."""
    db.site_reports.create_index([("company_id", 1), ("project_id", 1), ("date", -1)], unique=True)


def m020_portal_actions():
    """Phase G block 1: comments on documents from the client and consultants."""
    db.document_comments.create_index([("company_id", 1), ("project_id", 1), ("status", 1)])
    db.document_comments.create_index([("company_id", 1), ("document_id", 1), ("created_at", 1)])


def m021_payments():
    """Phase G block 2: payment links per invoice; one provider payment makes one receipt."""
    db.payment_links.create_index([("company_id", 1), ("invoice_id", 1), ("status", 1)])
    db.payment_links.create_index([("provider", 1), ("ref", 1)], unique=True)
    db.payment_links.create_index([("company_id", 1), ("events.payment_id", 1)])


def m022_messages():
    """Phase G blocks 3-4: portal threads per project and contact, and WhatsApp messages (the plan's quota counts them)."""
    db.messages.create_index([("company_id", 1), ("project_id", 1), ("contact_id", 1), ("created_at", 1)])
    db.messages.create_index([("company_id", 1), ("channel", 1), ("direction", 1), ("created_at", -1)])
    db.messages.create_index([("company_id", 1), ("provider_id", 1)])


def m023_procurement():
    """Phase H: requests, RFQs and purchase orders per project; POs by supplier and expected date (reminders)."""
    db.purchase_requests.create_index([("company_id", 1), ("project_id", 1), ("status", 1)])
    db.rfqs.create_index([("company_id", 1), ("project_id", 1), ("status", 1)])
    db.purchase_orders.create_index([("company_id", 1), ("project_id", 1), ("status", 1)])
    db.purchase_orders.create_index([("company_id", 1), ("vendor_id", 1), ("status", 1), ("expected_date", 1)])
    db.goods_receipts.create_index([("company_id", 1), ("po_id", 1)])
    db.vendor_bills.create_index([("company_id", 1), ("vendor_id", 1), ("bill_no", 1)])
    db.costs.create_index([("company_id", 1), ("po_id", 1)])


MIGRATIONS = [
    ("001_plans", m001_plans),
    ("002_superadmin_owner", m002_superadmin_owner),
    ("003_stage_template_durations", m003_stage_template_durations),
    ("004_project_indexes", m004_project_indexes),
    ("005_contact_types", m005_contact_types),
    ("006_phase_c", m006_phase_c),
    ("007_leads_deep", m007_leads_deep),
    ("008_phase_d", m008_phase_d),
    ("009_projects_plus", m009_projects_plus),
    ("010_stage_gates", m010_stage_gates),
    ("011_plan_meetings", m011_plan_meetings),
    ("012_finance", m012_finance),
    ("013_invoices", m013_invoices),
    ("014_receipts", m014_receipts),
    ("015_change_orders", m015_change_orders),
    ("016_documents", m016_documents),
    ("017_transmittals", m017_transmittals),
    ("018_selections", m018_selections),
    ("019_site_reports", m019_site_reports),
    ("020_portal_actions", m020_portal_actions),
    ("021_payments", m021_payments),
    ("022_messages", m022_messages),
    ("023_procurement", m023_procurement),
]


def run():
    done = {m["_id"] for m in db.schema_migrations.find({}, {"_id": 1})}
    for key, fn in MIGRATIONS:
        if key in done:
            continue
        fn()
        db.schema_migrations.insert_one({"_id": key, "applied_at": now()})
        print(f"migration applied: {key}")
