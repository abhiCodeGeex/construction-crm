from datetime import datetime, date

from bson import ObjectId
from flask.json.provider import DefaultJSONProvider
from pymongo import MongoClient, ASCENDING

from .config import Config

client = MongoClient(Config.MONGO_URI, tz_aware=False)
db = client[Config.MONGO_DB]


def oid(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def serialize(doc):
    """Recursively turn Mongo documents into JSON-friendly dicts (_id -> id)."""
    if isinstance(doc, list):
        return [serialize(d) for d in doc]
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k == "_id":
                out["id"] = str(v)
            elif k == "password":
                continue
            else:
                out[k] = serialize(v)
        return out
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, (datetime, date)):
        return iso(doc)
    return doc


def iso(v):
    """Times are stored as naive UTC; they leave the API marked as UTC ('Z') so browsers show local time."""
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.isoformat() + "Z"
    return v.isoformat()


class JSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, (datetime, date)):
            return iso(o)
        return super().default(o)


TENANT_COLLECTIONS = [
    "users", "leads", "bids", "contacts", "projects", "stage_templates", "proposals", "contracts",
    "rate_library", "documents", "design_options", "products", "selections", "purchase_requests",
    "purchase_orders", "change_orders", "costs", "invoices", "site_reports", "snags", "followups",
    "message_templates", "messages", "notifications", "timesheets", "support_tickets", "project_issues",
]


def ensure_indexes():
    for name in TENANT_COLLECTIONS:
        db[name].create_index([("company_id", ASCENDING)])
    db.users.create_index("email", unique=True)
    db.superadmin_users.create_index("email", unique=True)
    db.audit_logs.create_index([("company_id", ASCENDING), ("at", ASCENDING)])
    db.projects.create_index([("company_id", ASCENDING), ("client_id", ASCENDING)])
    db.costs.create_index([("company_id", ASCENDING), ("project_id", ASCENDING), ("stage_id", ASCENDING)])
