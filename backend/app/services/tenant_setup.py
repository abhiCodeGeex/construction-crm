from ..db import db, oid
from ..tenancy import now
from .defaults import STAGE_TEMPLATES, MESSAGE_TEMPLATES, PIPELINE, LEAD_SOURCES


def bootstrap_company(company_id, modules):
    """Copy platform default templates into a new company (they are editable per company)."""
    platform = db.platform_settings.find_one({"_id": "settings"}) or {}
    stage_defaults = platform.get("stage_templates") or STAGE_TEMPLATES
    for service in ("architecture", "construction", "interior"):
        db.stage_templates.insert_one({
            "company_id": company_id, "service": service, "name": f"Default {service}",
            "stages": stage_defaults.get(service, STAGE_TEMPLATES[service]), "is_default": True,
            "created_at": now(),
        })
    for tpl in platform.get("message_templates") or MESSAGE_TEMPLATES:
        db.message_templates.insert_one({**tpl, "company_id": company_id, "created_at": now()})
    db.companies.update_one({"_id": oid(company_id)}, {"$set": {
        "pipelines": {m: PIPELINE for m in ("architecture", "construction", "interior")},
        "lead_sources": LEAD_SOURCES,
        "markup_rules": {"Furniture": 25, "Lighting": 30, "Decor": 35, "Fabric": 30},
        "deposit_pct": 50,
    }})
