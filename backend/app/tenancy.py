"""Tenant-scoped data access. Every query and insert gets company_id injected here."""
import uuid
from datetime import datetime

from flask import g, abort

from .db import db, oid, serialize
from .security import COST_FIELDS


def now():
    return datetime.utcnow()


def sid():
    return uuid.uuid4().hex[:10]


def scoped(query=None):
    q = dict(query or {})
    q["company_id"] = g.cid
    return q


def find(name, query=None, sort=None, limit=0):
    cur = db[name].find(scoped(query))
    if sort:
        cur = cur.sort(sort)
    if limit:
        cur = cur.limit(limit)
    return list(cur)


def get(name, _id, required=True):
    doc = db[name].find_one(scoped({"_id": oid(_id)}))
    if not doc and required:
        abort(404, f"{name[:-1] if name.endswith('s') else name} not found")
    return doc


def insert(name, doc):
    doc = dict(doc)
    doc.pop("id", None)
    doc.pop("_id", None)
    doc["company_id"] = g.cid
    doc["created_at"] = doc["updated_at"] = now()
    doc["created_by"] = getattr(g, "uid", None)
    res = db[name].insert_one(doc)
    doc["_id"] = res.inserted_id
    audit("create", name, res.inserted_id, after=doc)
    return doc


def update(name, _id, changes, audit_it=True, raw=None):
    before = get(name, _id)
    changes = {k: v for k, v in changes.items() if k not in ("id", "_id", "company_id", "created_at", "created_by")}
    changes["updated_at"] = now()
    op = {"$set": changes}
    if raw:
        op.update(raw)
    db[name].update_one(scoped({"_id": before["_id"]}), op)
    after = get(name, _id)
    if audit_it:
        audit("update", name, before["_id"], before=before, after=after)
    return after


def delete(name, _id):
    before = get(name, _id)
    db[name].delete_one(scoped({"_id": before["_id"]}))
    audit("delete", name, before["_id"], before=before)
    return before


def _diff(before, after):
    if not before or not after:
        return None
    keys = set(before) | set(after)
    skip = {"updated_at", "_id", "password_changed_ms"}
    out = {k: {"from": serialize(before.get(k)), "to": serialize(after.get(k))}
           for k in keys if k not in skip and before.get(k) != after.get(k)}
    for k in SECRET_FIELDS & set(out):  # the log says it changed, never the value (not even a hash)
        out[k] = {"from": "•••", "to": "••• (changed)"}
    return out


SECRET_FIELDS = {"password", "totp_secret", "token_hash"}


def audit(action, collection, doc_id, before=None, after=None, note=None):
    db.audit_logs.insert_one({
        "company_id": getattr(g, "cid", None),
        "user_id": getattr(g, "uid", None),
        "user_name": (getattr(g, "user", None) or {}).get("name"),
        "action": action,
        "collection": collection,
        "doc_id": str(doc_id) if doc_id else None,
        "changes": _diff(before, after) if action == "update" else None,
        "note": note,
        "at": now(),
    })


def out(doc):
    """Serialize for the current viewer, stripping cost/margin fields for restricted roles."""
    data = serialize(doc)
    if getattr(g, "hide_costs", False):
        data = _strip(data)
    return data


def _strip(data):
    if isinstance(data, list):
        return [_strip(d) for d in data]
    if isinstance(data, dict):
        return {k: _strip(v) for k, v in data.items() if k not in COST_FIELDS}
    return data


def next_number(key, default_prefix):
    """Atomic per-company document numbering, e.g. INV-0001, using the company's numbering format."""
    company = db.companies.find_one_and_update(
        {"_id": oid(g.cid)}, {"$inc": {f"counters.{key}": 1}}, return_document=True)
    n = company["counters"][key]
    fmt = (company.get("numbering") or {}).get(key) or f"{default_prefix}-{{n:04d}}"
    try:
        return fmt.format(n=n, year=now().year)
    except Exception:
        return f"{default_prefix}-{n:04d}"


def notify(text, level="info", role=None, user_id=None, link=None, project_id=None, company_id=None):
    db.notifications.insert_one({
        "company_id": company_id or g.cid, "text": text, "level": level, "role": role, "user_id": user_id,
        "link": link, "project_id": project_id, "read_by": [], "created_at": now(),
    })
