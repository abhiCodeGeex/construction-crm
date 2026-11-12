"""Authorization endpoints: the role matrix, per-area probes used to test access, company settings, audit."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import (api, auth_required, portal, can, AREAS, ROLE_PERMS, ROLE_LABELS, INTERNAL_ROLES,
                        EXTERNAL_ROLES, HIDE_COST_ROLES)
from ..services.subscription import check_modules

bp = Blueprint("access", __name__)


@bp.get("/access/matrix")
@auth_required
def matrix():
    return jsonify({
        "areas": AREAS,
        "roles": [{"role": r, "label": ROLE_LABELS[r], "kind": "staff", "perms": ROLE_PERMS[r],
                   "hide_costs": r in HIDE_COST_ROLES} for r in INTERNAL_ROLES]
        + [{"role": r, "label": ROLE_LABELS[r], "kind": "external", "perms": {}, "hide_costs": True}
           for r in EXTERNAL_ROLES],
    })


def _probe(area):
    if area not in AREAS:
        abort(404, "Unknown area")
    write = request.method != "GET"
    if write:
        t.audit("probe", area, None, note=f"write {area}")
    # sample record that contains cost fields — stripped for roles that must not see costs
    sample = {"area": area, "name": f"Sample {area} record", "client_price": 120000,
              "trade_price": 90000, "margin": 30000, "budget": 500000, "spent": 410000}
    return jsonify({"ok": True, "area": area, "access": "write" if write else "read", "role": g.role,
                    "sample": t.out(sample)})


for _area in AREAS:
    bp.add_url_rule(f"/access/probe/{_area}", f"probe_{_area}",
                    api(_area)(lambda a=_area: _probe(a)), methods=["GET", "POST"])


@bp.get("/company")
@api("settings", write=False)
def get_company():
    c = serialize(g.company)
    c.pop("counters", None)
    return jsonify(c)


@bp.put("/company")
@api("settings")
def update_company():
    d = request.get_json(force=True) or {}
    changes = {k: d[k] for k in ("name", "modules", "currency", "tax_rate", "gstin", "city", "branches",
                                 "allow_support_login") if k in d}
    if "modules" in changes:
        changes["modules"] = [m for m in changes["modules"] if m in ("architecture", "construction", "interior")]
        if not changes["modules"]:
            abort(400, "Enable at least one module")
        check_modules(changes["modules"])
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": changes})
    t.audit("update", "companies", g.company["_id"], before=g.company, after={**g.company, **changes})
    return get_company()


@bp.get("/audit")
@api("settings", write=False)
def audit_log():
    rows = db.audit_logs.find({"company_id": g.cid}).sort("at", -1).limit(int(request.args.get("limit", 200)))
    return jsonify(serialize(list(rows)))


@bp.get("/portal/me")
@portal
def portal_me():
    contact = db.contacts.find_one({"company_id": g.cid, "_id": oid(g.contact_id)}) if g.contact_id else None
    return jsonify({"role": g.role, "label": ROLE_LABELS[g.role], "contact": t.out(contact),
                    "company": {"name": g.company["name"], "branding": g.company.get("branding"), **brand(g.company)}})


def brand(company):
    """Phase I: the client portal shows the company's logo and colour (§1 branding on the client portal)."""
    from .proposals import branding
    b = branding(company)
    return {"logo_url": b["logo_url"], "primary": b["primary"], "currency": b["currency"]}
