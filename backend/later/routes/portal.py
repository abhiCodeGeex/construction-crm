"""Client portal (section 13) and vendor portal. Clients see progress and approve; never costs or margins."""
import uuid

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import portal
from .delivery import apply_change_order, add_comment
from .engage import log_message
from .finance import record_payment
from .sales import accept_proposal

bp = Blueprint("portal", __name__)

CLIENT_STAGE_FIELDS = ("id", "name", "service", "status", "progress", "start", "end")
CLIENT_SELECTION_FIELDS = ("id", "room", "name", "category", "finish", "dimensions", "photo", "qty", "client_price",
                           "total_client", "allowance", "over_allowance", "status", "client_decision", "client_note",
                           "lead_time_days", "project_id")


def _pick(doc, fields):
    data = serialize(doc)
    return {k: data.get(k) for k in fields}


def _my_project(pid):
    p = db.projects.find_one({"_id": oid(pid), "company_id": g.cid})
    if not p or not _allowed(p):
        abort(404, "Project not found")
    return p


def _allowed(p):
    if g.role == "client":
        return p.get("client_id") == g.contact_id
    return any(m.get("contact_id") == g.contact_id for m in p.get("team", []))


def _stop_sequences(ref_id, why):
    db.followups.update_many({"company_id": g.cid, "related.id": ref_id, "status": "open", "auto": True},
                             {"$set": {"status": "cancelled", "cancel_reason": why}})


@bp.get("/portal/me")
@portal
def me():
    contact = db.contacts.find_one({"_id": oid(g.contact_id), "company_id": g.cid})
    c = g.company
    return jsonify({"contact": serialize(contact), "role": g.role,
                    "company": {"name": c["name"], "branding": c.get("branding"), "currency": c.get("currency")}})


@bp.get("/portal/projects")
@portal
def projects():
    q = {"company_id": g.cid}
    q.update({"client_id": g.contact_id} if g.role == "client" else {"team.contact_id": g.contact_id})
    out = []
    for p in db.projects.find(q):
        stages = p.get("stages", [])
        out.append({"id": str(p["_id"]), "name": p["name"], "code": p.get("code"), "address": p.get("address"),
                    "status": p.get("status"), "services": p.get("services"),
                    "progress": round(sum(s.get("progress", 0) for s in stages) / len(stages)) if stages else 0})
    return jsonify(out)


@bp.get("/portal/projects/<pid>")
@portal
def project(pid):
    p = _my_project(pid)
    stages = p.get("stages", [])
    base = {"company_id": g.cid, "project_id": pid}
    photos = []
    for r in db.site_reports.find(base).sort("date", -1).limit(30):
        for ph in r.get("photos", []):
            photos.append({**ph, "date": r.get("date"), "work_done": r.get("work_done")})
    docs = db.documents.find({**base, "$or": [{"shared": True}, {"approval": {"$in": ["pending", "approved", "rejected"]}}]})
    invoices = db.invoices.find({**base, "status": {"$nin": ["draft", "void"]}}).sort("issue_date", -1)
    proposals = db.proposals.find({"company_id": g.cid, "client_id": g.contact_id,
                                   "status": {"$in": ["sent", "viewed", "accepted", "rejected"]}})
    data = {
        "project": {"id": pid, "name": p["name"], "address": p.get("address"), "status": p.get("status"),
                    "services": p.get("services"), "value": p.get("value"),
                    "progress": round(sum(s.get("progress", 0) for s in stages) / len(stages)) if stages else 0,
                    "stages": [_pick(s, CLIENT_STAGE_FIELDS) for s in stages]},
        "photos": photos,
        "documents": [{"id": str(d["_id"]), "name": d["name"], "kind": d.get("kind"), "folder": d.get("folder"),
                       "approval": d.get("approval"), "latest": serialize(d.get("latest")), "room": d.get("room"),
                       "comments": serialize(d.get("comments", []))} for d in docs],
        "design_options": serialize(list(db.design_options.find({**base, "status": {"$ne": "draft"}}))),
        "selections": [_pick(s, CLIENT_SELECTION_FIELDS) for s in db.selections.find(base).sort("room", 1)],
        "change_orders": [{"id": str(c["_id"]), "number": c.get("number"), "title": c.get("title"),
                           "description": c.get("description"), "price_impact": c.get("price_impact"),
                           "time_impact_days": c.get("time_impact_days"), "status": c.get("status")}
                          for c in db.change_orders.find({**base, "reason": "client",
                                                          "status": {"$in": ["pending_client", "approved", "rejected"]}})],
        "invoices": [{"id": str(i["_id"]), "number": i["number"], "issue_date": i.get("issue_date"),
                      "due_date": i.get("due_date"), "total": i.get("total"), "amount_due": i.get("amount_due"),
                      "paid": i.get("paid"), "status": i.get("status"), "items": serialize(i.get("items"))}
                     for i in invoices],
        "proposals": [{"id": str(x["_id"]), "number": x["number"], "title": x.get("title"), "type": x.get("type"),
                       "version": x.get("version"), "total": x.get("total"), "tax": x.get("tax"),
                       "subtotal": x.get("subtotal"), "discount_amount": x.get("discount_amount"),
                       "status": x["status"], "terms": x.get("terms"), "payment_schedule": x.get("payment_schedule"),
                       "items": [{k: it.get(k) for k in ("section", "description", "qty", "unit", "rate", "amount",
                                                         "optional", "included")} for it in x.get("items", [])],
                       "project_id": x.get("project_id")} for x in proposals
                      if not x.get("project_id") or x.get("project_id") == pid],
        "messages": serialize(list(db.messages.find({**base, "contact_id": g.contact_id}).sort("created_at", -1).limit(50))),
    }
    return jsonify(data)


# ---------------- approvals ----------------
@bp.post("/portal/proposals/<_id>/view")
@portal
def view_proposal(_id):
    p = db.proposals.find_one({"_id": oid(_id), "company_id": g.cid, "client_id": g.contact_id}) or abort(404)
    if p["status"] == "sent":
        db.proposals.update_one({"_id": p["_id"]}, {"$set": {"status": "viewed", "viewed_at": t.now()}})
        # alert when a proposal is viewed but not accepted
        t.notify(f"{p.get('client_name')} viewed proposal {p['number']}", level="info", role="sales",
                 link=f"/proposals/{_id}")
    return jsonify({"ok": True})


@bp.post("/portal/proposals/<_id>/accept")
@portal
def accept(_id):
    p = db.proposals.find_one({"_id": oid(_id), "company_id": g.cid, "client_id": g.contact_id}) or abort(404)
    name = (request.get_json(force=True) or {}).get("signature_name")
    if not name:
        abort(400, "Type your full name to sign")
    contract = accept_proposal(p, name, "client")
    return jsonify({"ok": True, "contract_number": contract.get("number")})


@bp.post("/portal/proposals/<_id>/reject")
@portal
def reject(_id):
    p = db.proposals.find_one({"_id": oid(_id), "company_id": g.cid, "client_id": g.contact_id}) or abort(404)
    db.proposals.update_one({"_id": p["_id"]}, {"$set": {"status": "rejected",
                                                         "reject_reason": (request.get_json(force=True) or {}).get("reason")}})
    _stop_sequences(_id, "Client responded")
    return jsonify({"ok": True})


@bp.post("/portal/selections/<_id>/decision")
@portal
def selection_decision(_id):
    s = db.selections.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404)
    _my_project(s["project_id"])
    d = request.get_json(force=True) or {}
    approve = bool(d.get("approve"))
    t.update("selections", _id, {"status": "client_approved" if approve else "proposed",
                                 "client_decision": "approved" if approve else "rejected",
                                 "client_note": d.get("note"), "decided_at": t.now()})
    t.notify(f"Client {'approved' if approve else 'rejected'} {s['name']} ({s.get('room')})",
             level="success" if approve else "yellow", role="designer", project_id=s["project_id"])
    _stop_sequences(_id, "Client decided")
    return jsonify({"ok": True})


@bp.post("/portal/change_orders/<_id>/decision")
@portal
def co_decision(_id):
    co = db.change_orders.find_one({"_id": oid(_id), "company_id": g.cid, "status": "pending_client"}) or abort(404)
    _my_project(co["project_id"])
    d = request.get_json(force=True) or {}
    if d.get("approve"):
        apply_change_order(co, "client", d.get("signature_name") or g.user.get("name"))
    else:
        t.update("change_orders", _id, {"status": "rejected", "reject_reason": d.get("note")})
        _stop_sequences(_id, "Client rejected")
    return jsonify({"ok": True})


@bp.post("/portal/documents/<_id>/decision")
@portal
def doc_decision(_id):
    doc = db.documents.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404)
    _my_project(doc["project_id"])
    d = request.get_json(force=True) or {}
    status = "approved" if d.get("approve") else "rejected"
    t.update("documents", _id, {"approval": status, "approval_note": d.get("note"), "approved_rev":
                                doc.get("latest", {}).get("rev"), "decided_at": t.now()})
    t.notify(f"Client {status} {doc['name']} {doc.get('latest', {}).get('rev', '')}", level="info", role="designer",
             project_id=doc["project_id"])
    _stop_sequences(_id, "Client decided")
    return jsonify({"ok": True})


@bp.post("/portal/documents/<_id>/comments")
@portal
def doc_comment(_id):
    doc = db.documents.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404)
    _my_project(doc["project_id"])
    d = request.get_json(force=True) or {}
    d.setdefault("make", "change_request" if d.get("request_change") else "task")
    return jsonify(add_comment(_id, d, g.user.get("name"), side="client")), 201


@bp.post("/portal/design_options/<_id>/choose")
@portal
def choose_option(_id):
    opt = db.design_options.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404)
    _my_project(opt["project_id"])
    choice = (request.get_json(force=True) or {}).get("option_id")
    if not any(o["id"] == choice for o in opt.get("options", [])):
        abort(400, "Unknown option")
    t.update("design_options", _id, {"chosen": choice, "status": "approved", "chosen_at": t.now()})
    t.notify(f"Client chose an option for {opt.get('title')}", level="success", role="designer",
             project_id=opt["project_id"])
    return jsonify({"ok": True})


@bp.post("/portal/invoices/<_id>/pay")
@portal
def pay(_id):
    """Simulated online payment through the gateway."""
    inv = db.invoices.find_one({"_id": oid(_id), "company_id": g.cid}) or abort(404)
    _my_project(inv["project_id"])
    amount = (request.get_json(force=True) or {}).get("amount") or round(inv["amount_due"] - inv.get("paid", 0), 2)
    record_payment(inv, amount, "online", f"pay_{uuid.uuid4().hex[:12]}", g.user.get("name"))
    return jsonify({"ok": True})


@bp.post("/portal/messages")
@portal
def message():
    d = request.get_json(force=True) or {}
    _my_project(d.get("project_id"))
    from .engage import route_topic
    from ..services.defaults import ROUTING
    topic = route_topic(d.get("body"))
    msg = log_message({"channel": "portal", "direction": "in", "body": d.get("body"), "project_id": d["project_id"],
                       "contact_id": g.contact_id, "from_name": g.user.get("name"), "topic": topic,
                       "routed_to_role": ROUTING.get(topic, "pm"), "status": "open"})
    db.followups.update_many({"company_id": g.cid, "related.id": d["project_id"], "status": "open", "auto": True,
                              "related.type": "client_reply"}, {"$set": {"status": "cancelled"}})
    return jsonify(serialize(msg)), 201


# ---------------- vendor portal ----------------
@bp.get("/portal/purchase-orders")
@portal
def vendor_pos():
    if g.role != "vendor":
        return jsonify([])
    rows = db.purchase_orders.find({"company_id": g.cid, "vendor_id": g.contact_id,
                                    "status": {"$nin": ["draft", "pending_approval"]}}).sort("created_at", -1)
    return jsonify(serialize(list(rows)))


@bp.post("/portal/purchase-orders/<_id>/update")
@portal
def vendor_update(_id):
    po = db.purchase_orders.find_one({"_id": oid(_id), "company_id": g.cid, "vendor_id": g.contact_id}) or abort(404)
    d = request.get_json(force=True) or {}
    upd = {"id": t.sid(), "text": d.get("text"), "expected_date": d.get("expected_date"), "at": t.now(),
           "by": g.user.get("name")}
    changes = {"expected_date": d["expected_date"]} if d.get("expected_date") else {}
    if d.get("backorder"):
        changes["backorder"] = True
    db.purchase_orders.update_one({"_id": po["_id"]}, {"$set": changes, "$push": {"vendor_updates": upd}})
    t.notify(f"{po.get('vendor_name')} updated {po['number']}: {d.get('text')}", level="info", role="procurement")
    return jsonify({"ok": True})
