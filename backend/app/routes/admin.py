"""Company setup (§1): stage templates incl. RIBA / AIA presets (§4), role permission editor, branches,
currency, tax and numbering formats, file uploads for compliance documents (§3)."""
import os
import uuid

from flask import Blueprint, request, jsonify, abort, g, send_from_directory
from werkzeug.utils import secure_filename

from .. import tenancy as t
from ..config import Config
from ..db import db, serialize
from ..security import api, auth_required, AREAS, ROLE_PERMS, ROLE_LABELS, INTERNAL_ROLES, effective_perms
from ..services.defaults import SERVICES, TEMPLATE_PRESETS, template_stages
from ..services.subscription import limits, usage

bp = Blueprint("admin", __name__)


# ---------------- stage templates ----------------
def clean_template(dat, existing=None):
    name = (dat.get("name", (existing or {}).get("name")) or "").strip()
    if not name:
        abort(400, "Template name is required")
    service = dat.get("service", (existing or {}).get("service"))
    if service not in SERVICES:
        abort(400, "Choose architecture, construction or interior")
    stages = dat.get("stages", (existing or {}).get("stages")) or []
    if not stages:
        abort(400, "A template needs at least one stage")
    clean = []
    for s in stages:
        n = (s.get("name") or "").strip()
        days = s.get("duration_days")
        if not n:
            abort(400, "Every stage needs a name")
        if not isinstance(days, int) or not 1 <= days <= 3650:
            abort(400, f"{n}: duration must be 1-3650 days")
        clean.append({"name": n, "duration_days": days})
    if len({s["name"].lower() for s in clean}) != len(clean):
        abort(400, "Stage names must be unique within a template")
    return {"name": name, "service": service, "stages": clean}


def _single_default(service, keep_id):
    db.stage_templates.update_many({"company_id": g.cid, "service": service, "_id": {"$ne": keep_id}},
                                   {"$set": {"is_default": False}})


@bp.get("/stage_templates")
@api("projects", write=False)
def list_templates():
    rows = t.find("stage_templates", {}, sort=[("service", 1), ("name", 1)])
    return jsonify({"templates": serialize(rows),
                    "presets": [{"key": k, "name": v["name"], "service": v["service"], "stages": v["stages"]}
                                for k, v in TEMPLATE_PRESETS.items()]})


@bp.post("/stage_templates")
@api("settings")
def create_template():
    dat = request.get_json(force=True) or {}
    if dat.get("preset"):
        preset = TEMPLATE_PRESETS.get(dat["preset"]) or abort(400, "Unknown preset")
        dat = {"name": preset["name"], "service": preset["service"], "stages": template_stages(preset["stages"])}
    doc = clean_template(dat)
    if t.find("stage_templates", {"name": doc["name"], "service": doc["service"]}):
        abort(409, f"A {doc['service']} template called {doc['name']} already exists")
    doc["is_default"] = bool(dat.get("is_default"))
    created = t.insert("stage_templates", doc)
    if doc["is_default"]:
        _single_default(doc["service"], created["_id"])
    return jsonify(serialize(created)), 201


@bp.put("/stage_templates/<_id>")
@api("settings")
def update_template(_id):
    existing = t.get("stage_templates", _id)
    dat = request.get_json(force=True) or {}
    doc = clean_template(dat, existing)
    if doc["service"] != existing["service"] and existing.get("is_default"):
        abort(409, "Make another template the default before moving this one to a different service")
    if dat.get("is_default"):
        doc["is_default"] = True
    updated = t.update("stage_templates", _id, doc)
    if updated.get("is_default"):
        _single_default(updated["service"], updated["_id"])
    return jsonify(serialize(updated))


@bp.delete("/stage_templates/<_id>")
@api("settings")
def delete_template(_id):
    tpl = t.get("stage_templates", _id)
    if tpl.get("is_default"):
        abort(409, "This is the default template for its service; make another one default first")
    t.delete("stage_templates", _id)
    return jsonify({"ok": True})


# ---------------- role permission editor ----------------
LOCKED = {("owner", a) for a in AREAS}  # the owner always keeps full access, so nobody can lock the company out


@bp.get("/roles")
@api("settings", write=False)
def roles():
    overrides = g.company.get("role_overrides", {})
    return jsonify({"areas": AREAS, "roles": [
        {"role": r, "label": ROLE_LABELS[r], "defaults": ROLE_PERMS[r], "overrides": overrides.get(r, {}),
         "effective": effective_perms(r, g.company), "locked": r == "owner"} for r in INTERNAL_ROLES]})


@bp.put("/roles/<role>")
@api("settings")
def set_role(role):
    if role not in INTERNAL_ROLES:
        abort(404, "Unknown role")
    if role == "owner":
        abort(409, "The owner role always has full access")
    perms = (request.get_json(force=True) or {}).get("perms") or {}
    clean = {}
    for area, level in perms.items():
        if area not in AREAS:
            abort(400, f"Unknown area {area}")
        if level not in ("", "r", "rw"):
            abort(400, "Level must be none, read or read + write")
        if ROLE_PERMS[role].get(area, "") != level:  # store only differences from the code defaults
            clean[area] = level
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {f"role_overrides.{role}": clean}})
    t.audit("update", "roles", g.company["_id"], note=f"{ROLE_LABELS[role]}: {clean or 'reset to default'}")
    g.company = db.companies.find_one({"_id": g.company["_id"]})
    return roles()


# ---------------- company setup ----------------
SETTINGS_FIELDS = ("name", "city", "gstin", "currency", "tax_rate", "branches", "numbering", "allow_support_login",
                   "modules", "branding")
CURRENCIES = ("INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD")


@bp.put("/company/setup")
@api("settings")
def company_setup():
    dat = request.get_json(force=True) or {}
    changes = {}
    if "currency" in dat:
        if dat["currency"] not in CURRENCIES:
            abort(400, "Unsupported currency")
        changes["currency"] = dat["currency"]
    if "tax_rate" in dat:
        if not isinstance(dat["tax_rate"], (int, float)) or not 0 <= dat["tax_rate"] <= 100:
            abort(400, "Tax rate must be 0-100%")
        changes["tax_rate"] = float(dat["tax_rate"])
    if "tax_label" in dat:
        changes["tax_label"] = (dat["tax_label"] or "Tax")[:20]
    if "branches" in dat:
        names = []
        clean = []
        for b in dat["branches"] or []:
            n = (b.get("name") or "").strip()
            if not n:
                abort(400, "Every branch needs a name")
            names.append(n.lower())
            clean.append({"name": n, "city": b.get("city"), "address": b.get("address"), "gstin": b.get("gstin")})
        if not clean:
            abort(400, "Keep at least one branch")
        if len(set(names)) != len(names):
            abort(400, "Branch names must be unique")
        in_use = {p.get("branch") for p in t.find("projects", {"branch": {"$ne": None}})}
        removed = in_use - {b["name"] for b in clean}
        if removed:
            abort(409, f"Branch in use by projects: {', '.join(sorted(removed))}")
        changes["branches"] = clean
    if "numbering" in dat:
        fmt = (dat["numbering"] or {}).get("PRJ") or "PRJ-{n:04d}"
        if "{n" not in fmt:
            abort(400, "Number format must contain {n}, e.g. PRJ-{year}-{n:03d}")
        try:
            sample = fmt.format(n=1, year=2026)
        except (KeyError, ValueError, IndexError):
            abort(400, "Number format can only use {n} and {year}, e.g. PRJ-{year}-{n:03d}")
        if len(sample) > 30:
            abort(400, "Number format is too long")
        changes["numbering.PRJ"] = fmt
    if not changes:
        abort(400, "Nothing to update")
    before = dict(g.company)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": changes})
    after = db.companies.find_one({"_id": g.company["_id"]})
    t.audit("update", "companies", g.company["_id"], before=before, after=after)
    c = serialize(after)
    c.pop("counters", None)
    return jsonify(c)


@bp.get("/company/numbering/preview")
@api("settings", write=False)
def numbering_preview():
    fmt = request.args.get("format") or "PRJ-{n:04d}"
    nxt = (g.company.get("counters") or {}).get("PRJ", 0) + 1
    try:
        return jsonify({"next": fmt.format(n=nxt, year=t.now().year)})
    except (KeyError, ValueError, IndexError):
        abort(400, "Invalid format")


# ---------------- uploads (compliance documents) ----------------
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx"}
MAX_BYTES = 20 * 1024 * 1024


@bp.post("/uploads")
@api(None)
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        abort(400, "Choose a file")
    name = secure_filename(f.filename) or "file"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        abort(400, "Allowed files: PDF, image or Word document")
    key = f"{g.cid}_{uuid.uuid4().hex[:12]}_{name}"
    path = os.path.join(Config.UPLOAD_DIR, key)
    f.save(path)
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        os.remove(path)
        abort(400, "File is larger than 20 MB")
    lim = limits()["storage_gb"]
    if lim and usage(g.company)["storage_bytes"] + size > lim * 1024 ** 3:
        os.remove(path)
        abort(402, "Storage limit reached — buy extra storage or upgrade.")
    db.files.insert_one({"company_id": g.cid, "key": key, "name": name, "size": size, "uploaded_by": g.uid,
                         "at": t.now()})
    return jsonify({"key": key, "name": name, "size": size, "url": f"/api/files/{key}"}), 201


@bp.get("/files/<key>")
@auth_required
def get_file(key):
    if not key.startswith(f"{g.cid}_") or not db.files.find_one({"company_id": g.cid, "key": key}):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, key, as_attachment=request.args.get("download") == "1")
