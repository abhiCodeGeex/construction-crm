"""Proposals, estimates, interior quotes, contracts and the rate library (section 5)."""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import register_crud, num
from ..db import db
from ..security import api
from ..services import budget as B
from ..services.pricing import compute_proposal

bp = Blueprint("sales", __name__)


def _prep_proposal(d, existing):
    d.setdefault("type", "estimate")
    d.setdefault("status", "draft")
    d.setdefault("version", 1)
    d.setdefault("tax_pct", g.company.get("tax_rate", 18))
    d.setdefault("payment_schedule", [])
    if existing and existing.get("status") in ("accepted",) and g.role != "owner":
        abort(409, "Accepted proposals cannot be edited — create a new version or a change order")
    for it in d.get("items", []):
        it.setdefault("id", t.sid())
    if d.get("project_id"):
        p = t.get("projects", d["project_id"], required=False)
        d["project_name"] = p["name"] if p else None
        d.setdefault("client_id", p.get("client_id") if p else None)
    if d.get("lead_id") and not d.get("client_id"):
        lead = t.get("leads", d["lead_id"], required=False)
        d["client_id"] = lead.get("contact_id") if lead else None
    if d.get("client_id"):
        c = t.get("contacts", d["client_id"], required=False)
        d["client_name"] = c["name"] if c else None
    return compute_proposal(d)


register_crud(bp, "proposals", "proposals", search=("number", "title", "client_name", "project_name"),
              filters=("status", "type", "project_id", "lead_id"), prepare=_prep_proposal, number=("PRO", "PRO"))


@bp.post("/proposals/<_id>/version")
@api("proposals")
def new_version(_id):
    p = t.get("proposals", _id)
    copy = {k: v for k, v in p.items() if k not in ("_id", "status", "signature", "accepted_at", "sent_at",
                                                     "viewed_at", "created_at", "updated_at")}
    copy["version"] = p.get("version", 1) + 1
    copy["status"] = "draft"
    copy["previous_id"] = _id
    t.update("proposals", _id, {"status": "superseded"})
    return jsonify(t.out(t.insert("proposals", compute_proposal(copy)))), 201


@bp.post("/proposals/<_id>/send")
@api("proposals")
def send_proposal(_id):
    p = t.update("proposals", _id, {"status": "sent", "sent_at": t.now()})
    from .engage import schedule_sequence
    schedule_sequence("proposal", _id, f"proposal {p['number']} v{p.get('version', 1)}", owner_id=g.uid)
    return jsonify(t.out(p))


def accept_proposal(p, signature_name, signed_by="client"):
    """Online acceptance -> contract with milestone payment schedule; milestone budgets from estimate."""
    if p["status"] == "accepted":
        return db.contracts.find_one({"company_id": g.cid, "proposal_id": str(p["_id"])})
    if p["status"] not in ("sent", "viewed", "draft"):
        abort(409, f"Proposal is {p['status']}")
    pid = p.get("project_id")
    if not pid and p.get("lead_id"):
        from .projects import create_project
        lead = t.get("leads", p["lead_id"])
        service = {"fee": lead.get("service") or "architecture", "estimate": "construction",
                   "interior": "interior"}[p.get("type", "estimate")]
        proj = create_project({"name": lead["title"], "services": [service], "client_id": p.get("client_id"),
                               "address": lead.get("location"), "area": lead.get("area"), "value": p["total"],
                               "lead_id": p["lead_id"]})
        pid = str(proj["_id"])
        t.update("leads", p["lead_id"], {"status": "won", "stage": "Won", "project_id": pid, "won_at": t.now()})
        t.update("proposals", str(p["_id"]), {"project_id": pid, "project_name": proj["name"]}, audit_it=False)
    project = t.get("projects", pid)

    # budgets per milestone taken from the accepted estimate (items tagged with a stage)
    by_stage = {}
    for it in p.get("items", []):
        if it.get("stage_id") and (not it.get("optional") or it.get("included")):
            by_stage[it["stage_id"]] = by_stage.get(it["stage_id"], 0) + (it.get("line_cost") or it.get("amount") or 0)
    for s in project.get("stages", []):
        if s["id"] in by_stage:
            s["budget"] = round(s.get("budget", 0) + by_stage[s["id"]], 2)

    taxable = p["total"] - p.get("tax", 0)
    schedule = []
    for row in p.get("payment_schedule") or []:
        pct = num(row.get("percent"))
        stage = B.find_stage(project, row.get("stage_id")) if row.get("stage_id") else None
        schedule.append({"id": t.sid(), "label": row.get("label") or (stage["name"] if stage else "Payment"),
                         "stage_id": row.get("stage_id"), "percent": pct,
                         "amount": round(taxable * pct / 100, 2), "invoiced": False})
    contract = t.insert("contracts", {
        "number": t.next_number("CON", "CON"), "project_id": pid, "project_name": project["name"],
        "proposal_id": str(p["_id"]), "client_id": p.get("client_id"), "client_name": p.get("client_name"),
        "original_value": round(taxable, 2), "value": round(taxable, 2), "tax_pct": p.get("tax_pct", 18),
        "change_orders_total": 0, "payment_schedule": schedule, "status": "active", "type": p.get("type"),
    })
    # project value = sum of its active contracts (fee + estimate + interior on design-and-build jobs)
    value = sum(c["value"] for c in db.contracts.find({"company_id": g.cid, "project_id": pid, "status": "active"}))
    t.update("projects", pid, {"stages": project["stages"], "value": round(value, 2)})
    for s in project["stages"]:
        if s["id"] in by_stage:
            B.recalc_stage(pid, s["id"])
    t.update("proposals", str(p["_id"]), {"status": "accepted", "accepted_at": t.now(), "project_id": pid,
                                          "signature": {"name": signature_name, "by": signed_by, "at": t.now()}})
    db.followups.update_many({"company_id": g.cid, "related.id": str(p["_id"]), "status": "open", "auto": True},
                             {"$set": {"status": "cancelled", "cancel_reason": "Proposal accepted"}})
    t.notify(f"Proposal {p['number']} accepted by {signature_name}", level="success", role="sales",
             project_id=pid, link=f"/projects/{pid}")
    return contract


@bp.post("/proposals/<_id>/accept")
@api("proposals")
def accept_internal(_id):
    d = request.get_json(force=True) or {}
    contract = accept_proposal(t.get("proposals", _id), d.get("signature_name") or g.user.get("name"), "staff")
    return jsonify(t.out(contract))


@bp.post("/proposals/<_id>/reject")
@api("proposals")
def reject_proposal(_id):
    d = request.get_json(force=True) or {}
    return jsonify(t.out(t.update("proposals", _id, {"status": "rejected", "reject_reason": d.get("reason")})))


register_crud(bp, "contracts", "proposals", search=("number", "project_name", "client_name"),
              filters=("project_id", "status"))


def _prep_rate(d, existing):
    d["rate"] = num(d.get("rate"))
    return d


register_crud(bp, "rate_library", "proposals", search=("name", "category", "code"), filters=("kind", "category"),
              prepare=_prep_rate, sort=("name", 1))
