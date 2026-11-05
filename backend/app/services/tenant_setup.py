import secrets

from ..db import db, oid
from ..tenancy import now
from .defaults import (STAGE_TEMPLATES, MESSAGE_TEMPLATES, PIPELINE, LEAD_SOURCES, template_stages, LOSS_REASONS,
                       SERVICE_PROPOSAL_TYPE, TEMPLATE_TEXT, PROPOSAL_TYPES)


def bootstrap_company(company_id, modules):
    """Copy platform default templates into a new company (they are editable per company)."""
    platform = db.platform_settings.find_one({"_id": "settings"}) or {}
    stage_defaults = platform.get("stage_templates") or STAGE_TEMPLATES
    for service in ("architecture", "construction", "interior"):
        db.stage_templates.insert_one({
            "company_id": company_id, "service": service, "name": f"Default {service}",
            "stages": template_stages(stage_defaults.get(service, STAGE_TEMPLATES[service])), "is_default": True,
            "created_at": now(),
        })
    for tpl in platform.get("message_templates") or MESSAGE_TEMPLATES:
        db.message_templates.insert_one({**tpl, "company_id": company_id, "created_at": now(), "created_by": None})
    for service, ptype in SERVICE_PROPOSAL_TYPE.items():
        db.proposal_templates.insert_one({"company_id": company_id, "name": f"Standard {PROPOSAL_TYPES[ptype].lower()}", "type": ptype,
                                          "service": service, **TEMPLATE_TEXT[ptype], "scope_text": None, "items": [], "fee": None,
                                          "payment_schedule": [], "created_at": now(), "created_by": None})
    db.companies.update_one({"_id": oid(company_id)}, {"$set": {
        "pipelines": {m: PIPELINE for m in ("architecture", "construction", "interior")},
        "lead_sources": LEAD_SOURCES,
        "markup_rules": {"Furniture": 25, "Lighting": 30, "Decor": 35, "Fabric": 30},
        "deposit_pct": 50,
        "loss_reasons": LOSS_REASONS, "lead_form_key": secrets.token_urlsafe(16),
    }})
