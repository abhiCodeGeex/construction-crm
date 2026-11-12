"""Plan limits enforced inside the app (section 18 rules)."""
from flask import g, abort

from ..db import db


def company_plan(company=None):
    company = company or g.company
    return db.plans.find_one({"code": company.get("plan_code")}) or {}


def counted_users(company_id):
    # site workers on WhatsApp only and external portal users are free
    return db.users.count_documents({
        "company_id": company_id, "kind": "staff", "active": {"$ne": False}, "whatsapp_only": {"$ne": True}})


def active_projects(company_id):
    return db.projects.count_documents({"company_id": company_id, "status": {"$in": ["active", "planning"]}})


def limits(company=None):
    company = company or g.company
    plan = company_plan(company)
    extra_users = company.get("addons", {}).get("extra_users", 0)
    return {
        "plan": plan.get("name"),
        "users": (plan.get("max_users") or 0) + extra_users if plan.get("max_users") else None,
        "projects": plan.get("max_projects"),
        "modules": plan.get("max_modules"),
        "whatsapp": (plan.get("whatsapp_messages") + company.get("addons", {}).get("extra_whatsapp", 0)) if plan.get("whatsapp_messages") else None,
        "storage_gb": (plan.get("storage_gb") or 0) + company.get("addons", {}).get("extra_storage_gb", 0),
    }


def check_user_limit():
    lim = limits()["users"]
    if lim and counted_users(g.cid) >= lim:
        abort(402, f"Your {limits()['plan']} plan includes {lim} users. Upgrade or buy an extra-user add-on.")


def check_project_limit():
    lim = limits()["projects"]
    if lim and active_projects(g.cid) >= lim:
        abort(402, f"Your {limits()['plan']} plan allows {lim} active projects. Upgrade to add more.")


def check_modules(modules, company=None):
    lim = limits(company)["modules"]
    if lim and len(modules) > lim:
        abort(402, f"Your plan includes {lim} module(s). Upgrade to Pro for all three.")


def _month_start():
    from datetime import datetime
    n = datetime.utcnow()
    return datetime(n.year, n.month, 1)


def usage(company):
    cid = str(company["_id"])
    storage = sum(d.get("size", 0) for d in db.files.find({"company_id": cid}, {"size": 1}))
    return {
        "users": counted_users(cid),
        "free_users": db.users.count_documents({"company_id": cid, "$or": [{"kind": "external"}, {"whatsapp_only": True}]}),
        "projects": active_projects(cid),
        "storage_bytes": storage,
        # the plan's WhatsApp allowance is per month: count this calendar month only
        "whatsapp_messages": db.messages.count_documents({"company_id": cid, "channel": "whatsapp", "direction": "out",
                                                          "created_at": {"$gte": _month_start()}}),
    }
