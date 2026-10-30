"""Follow-ups & templates (section 16), shared inbox, WhatsApp one-tap messages, routing,
morning work messages and PM digest (section 17). The WhatsApp provider is simulated."""
import re
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..crud import register_crud
from ..db import db, oid, serialize
from ..security import api, auth_required
from ..services import budget as B
from ..services.defaults import ROUTING, ROUTING_KEYWORDS, URGENT_KEYWORDS

bp = Blueprint("engage", __name__)


# ---------------- follow-ups ----------------
def _prep_followup(d, existing):
    d.setdefault("status", "open")
    d.setdefault("priority", "normal")
    d.setdefault("owner_id", g.uid)
    if d.get("status") == "done" and (not existing or existing.get("status") != "done"):
        d["done_at"] = t.now().isoformat()
    if d.get("owner_id"):
        u = db.users.find_one({"_id": oid(d["owner_id"])})
        d["owner_name"] = u["name"] if u else None
    return d


register_crud(bp, "followups", "followups", search=("title", "notes"),
              filters=("status", "owner_id", "priority", "related.type", "related.id"),
              prepare=_prep_followup, sort=("due", 1))


@bp.get("/followups-today")
@api("followups", write=False)
def today_followups():
    """'Today's follow-ups' for the current user — overdue items highlighted."""
    today = datetime.utcnow().date().isoformat()
    q = {"status": "open", "due": {"$lte": today},
         "$or": [{"owner_id": g.uid}, {"role": g.role}]}
    if request.args.get("all") and g.role in ("owner", "pm"):
        q.pop("$or")
    rows = t.find("followups", q, sort=[("due", 1)])
    for r in rows:
        r["overdue"] = r.get("due", today) < today
    return jsonify(t.out(rows))


def schedule_sequence(kind, ref_id, label, owner_id=None):
    """Follow-up sequence (day 1, 3, 7). Stops automatically when the client replies/approves/pays."""
    base = datetime.utcnow()
    for day in (1, 3, 7):
        t.insert("followups", {
            "title": f"Chase {label} (day {day})", "due": (base + timedelta(days=day)).date().isoformat(),
            "status": "open", "priority": "high" if day == 7 else "normal", "owner_id": owner_id or g.uid,
            "related": {"type": kind, "id": ref_id}, "auto": True, "channel": "whatsapp" if day > 1 else "email",
        })


# ---------------- templates ----------------
register_crud(bp, "message_templates", "messages", search=("name", "body"), filters=("channel",), sort=("name", 1))


def render(body, ctx):
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1), m.group(0))), body or "")


@bp.post("/message_templates/<_id>/render")
@api("messages", write=False)
def render_template(_id):
    tpl = t.get("message_templates", _id)
    ctx = {"company": g.company["name"]}
    d = request.get_json(force=True) or {}
    if d.get("project_id"):
        p = t.get("projects", d["project_id"], required=False)
        if p:
            ctx.update(project=p["name"], client=p.get("client_name"), site=p.get("address"))
    if d.get("contact_id"):
        c = t.get("contacts", d["contact_id"], required=False)
        if c:
            ctx.update(client=c["name"], name=c["name"])
    ctx.update(d.get("context") or {})
    return jsonify({"text": render(tpl["body"], ctx), "channel": tpl["channel"]})


# ---------------- messages / shared inbox ----------------
def route_topic(body, button=None):
    if button and button in ROUTING:
        return button
    text = (body or "").lower()
    for words, topic in ROUTING_KEYWORDS:
        if any(w in text for w in words):
            return topic
    return "general"


def log_message(d):
    doc = {
        "company_id": g.cid, "channel": d.get("channel", "whatsapp"), "direction": d.get("direction", "out"),
        "body": d.get("body", ""), "project_id": d.get("project_id"), "contact_id": d.get("contact_id"),
        "user_id": d.get("user_id"), "from_name": d.get("from_name"), "to_name": d.get("to_name"),
        "to_phone": d.get("to_phone"), "from_phone": d.get("from_phone"), "button": d.get("button"),
        "topic": d.get("topic"), "routed_to_role": d.get("routed_to_role"), "urgent": d.get("urgent", False),
        "status": d.get("status", "sent" if d.get("direction", "out") == "out" else "open"),
        "attachments": d.get("attachments", []), "voice_note": d.get("voice_note"),
        "record": d.get("record"), "thread_id": d.get("thread_id"), "created_at": t.now(),
        "cost": 0.115 if d.get("channel", "whatsapp") == "whatsapp" and d.get("direction", "out") == "out" else 0,
    }
    doc["_id"] = db.messages.insert_one(doc).inserted_id
    return doc


@bp.get("/messages")
@api("messages", write=False)
def inbox():
    q = {"company_id": g.cid}
    for k in ("project_id", "channel", "status", "direction", "topic", "contact_id"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("mine") and g.role != "owner":
        q["routed_to_role"] = g.role
    rows = list(db.messages.find(q).sort("created_at", -1).limit(int(request.args.get("limit", 200))))
    return jsonify(serialize(rows))


@bp.post("/messages")
@api("messages")
def send_message():
    d = request.get_json(force=True) or {}
    if not d.get("body"):
        abort(400, "Message is empty")
    if d.get("channel", "whatsapp") == "whatsapp":
        _check_whatsapp_quota()
    msg = log_message({**d, "direction": "out", "from_name": g.user.get("name"), "status": "sent"})
    if d.get("reply_to"):
        db.messages.update_one({"_id": oid(d["reply_to"]), "company_id": g.cid},
                               {"$set": {"status": "answered", "answered_by": g.user.get("name")}})
    return jsonify(serialize(msg)), 201


@bp.post("/messages/<_id>/status")
@api("messages")
def message_status(_id):
    d = request.get_json(force=True) or {}
    changes = {"status": d.get("status", "closed")}
    if d.get("routed_to_role"):  # re-route to another person
        changes.update(routed_to_role=d["routed_to_role"], status="open")
    db.messages.update_one({"_id": oid(_id), "company_id": g.cid}, {"$set": changes})
    return jsonify(serialize(db.messages.find_one({"_id": oid(_id)})))


def _check_whatsapp_quota():
    from ..services.subscription import limits
    lim = limits()["whatsapp"]
    extra = g.company.get("addons", {}).get("extra_whatsapp", 0)
    if lim:
        month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = db.messages.count_documents({"company_id": g.cid, "channel": "whatsapp", "direction": "out",
                                            "created_at": {"$gte": month}})
        if used >= lim + extra:
            abort(402, "Monthly WhatsApp message limit reached — buy an extra 1,000 messages add-on.")


BUTTON_LABELS = {"material_needed": "Material needed", "work_done": "Work done", "need_help": "Need help",
                 "need_clarification": "Need clarification", "payment": "Payment status"}


@bp.post("/whatsapp/inbound")
@api(None)
def inbound():
    """Simulates the Meta Cloud API webhook: a worker/client taps a button or sends a message.
    The message becomes a CRM record and is routed to the right person; only urgent items reach the PM."""
    d = request.get_json(force=True) or {}
    body = d.get("body", "")
    button = d.get("button")
    topic = route_topic(body, button)
    role = (g.company.get("routing") or {}).get(topic) or ROUTING.get(topic, "pm")
    urgent = any(w in body.lower() for w in URGENT_KEYWORDS)
    sender = None
    if d.get("from_user_id"):
        sender = db.users.find_one({"_id": oid(d["from_user_id"]), "company_id": g.cid})
    record = None
    project_id = d.get("project_id")
    name = (sender or {}).get("name") or d.get("from_name") or d.get("from_phone") or "Unknown"
    if button == "material_needed" and project_id:
        pr = t.insert("purchase_requests", {"number": t.next_number("PR", "PR"), "title": f"Material request: {body or 'from site'}",
                                            "project_id": project_id, "status": "open", "requested_by": name,
                                            "quotes": [], "source": "whatsapp", "delivery_location": "site"})
        record = {"type": "purchase_request", "id": str(pr["_id"])}
    elif button in ("need_clarification", "need_help") and project_id:
        f = t.insert("followups", {"title": f"{BUTTON_LABELS[button]} from {name}: {body[:80]}", "status": "open",
                                   "priority": "high" if urgent else "normal", "role": role,
                                   "due": datetime.utcnow().date().isoformat(),
                                   "related": {"type": "project", "id": project_id}})
        record = {"type": "followup", "id": str(f["_id"])}
    elif button == "work_done" and project_id and d.get("task_id"):
        record = {"type": "task", "id": d["task_id"], "awaiting": "supervisor approval"}
    elif button == "payment":
        reply = _payment_status_reply(sender)
        log_message({"channel": "whatsapp", "direction": "out", "body": reply, "to_name": name,
                     "project_id": project_id, "topic": "payment"})
        role = None
    msg = log_message({**d, "channel": d.get("channel", "whatsapp"), "direction": "in", "from_name": name,
                       "user_id": d.get("from_user_id"), "topic": topic, "routed_to_role": role, "urgent": urgent,
                       "record": record, "status": "open" if role else "answered"})
    if urgent:
        t.notify(f"URGENT from {name}: {body[:100]}", level="red", role="pm", project_id=project_id, link="/inbox")
    elif role:
        t.notify(f"{BUTTON_LABELS.get(button, 'Message')} from {name}", level="info", role=role,
                 project_id=project_id, link="/inbox")
    return jsonify(serialize(msg)), 201


def _payment_status_reply(user):
    if not user:
        return "We could not find your record. Your supervisor will call you."
    paid = list(db.costs.find({"company_id": g.cid, "head": {"$in": ["labour", "subcontractor"]},
                               "payee_user_id": str(user["_id"])}).sort("date", -1).limit(1))
    if paid:
        return f"Hi {user['name']}, your last payment of ₹{paid[0]['amount']:,.0f} was approved on {paid[0]['date']}."
    return f"Hi {user['name']}, no payment is due right now. Accounts will message you when it is approved."


def trade_handoff(project, stage, task):
    """Trade sequence: when one trade marks work done, the next trade is told the area is ready."""
    nxt = task.get("next_trade")
    if not nxt:
        return
    workers = list(db.users.find({"company_id": g.cid, "trade": {"$regex": f"^{re.escape(nxt)}$", "$options": "i"}}))
    room = task.get("room") or stage["name"]
    for w in workers:
        log_message({"channel": "whatsapp", "direction": "out", "user_id": str(w["_id"]), "to_name": w["name"],
                     "to_phone": w.get("phone"), "project_id": str(project["_id"]), "topic": "schedule",
                     "body": f"{project['name']}: {room} is ready for {nxt.lower()} from tomorrow."})
    if project.get("client_id"):
        log_message({"channel": "whatsapp", "direction": "out", "contact_id": project["client_id"],
                     "to_name": project.get("client_name"), "project_id": str(project["_id"]), "topic": "progress",
                     "body": f"Update on {project['name']}: {task['title']} in {room} is complete."})


@bp.post("/projects/<_id>/morning-messages")
@api("projects", write=False)
def morning_messages(_id):
    """Builds each worker's day from the schedule: site, room, task, latest drawing, supervisor."""
    project = t.get("projects", _id)
    supervisor = db.users.find_one({"_id": oid(project.get("supervisor_id"))}) if project.get("supervisor_id") else None
    sent = []
    today = datetime.utcnow().date().isoformat()
    for stage in project.get("stages", []):
        if stage.get("status") == "done":
            continue
        for task in stage.get("tasks", []):
            if task.get("status") == "done" or not task.get("assignee_id"):
                continue
            if task.get("due") and task["due"] < today and stage.get("status") != "in_progress":
                continue
            worker = db.users.find_one({"_id": oid(task["assignee_id"]), "company_id": g.cid})
            if not worker:
                continue
            drawing = "—"
            if task.get("drawing_id"):
                doc = t.get("documents", task["drawing_id"], required=False)
                if doc:
                    drawing = f"{doc['name']} {doc.get('latest', {}).get('rev', '')}"
            body = (f"Good morning {worker['name']}! Site: {project['name']} ({project.get('address') or ''}). "
                    f"Room: {task.get('room') or stage['name']}. Task: {task['title']}. Drawing: {drawing}. "
                    f"Supervisor: {(supervisor or {}).get('name', 'PM')}.")
            if task.get("measurements"):
                body += f" Measurements: {task['measurements']}."
            sent.append(serialize(log_message({"channel": "whatsapp", "direction": "out", "user_id": str(worker["_id"]),
                                               "to_name": worker["name"], "to_phone": worker.get("phone"),
                                               "project_id": _id, "topic": "schedule", "body": body,
                                               "buttons": list(BUTTON_LABELS)})))
    return jsonify(sent)


@bp.post("/projects/<_id>/client-update")
@api("projects", write=False)
def client_update(_id):
    """Automatic progress update with photos to the client."""
    p = t.get("projects", _id)
    if not p.get("client_id"):
        abort(409, "Project has no client")
    stages = p.get("stages", [])
    progress = round(sum(s.get("progress", 0) for s in stages) / len(stages)) if stages else 0
    current = next((s["name"] for s in stages if s.get("status") == "in_progress"), None)
    photos = []
    for r in t.find("site_reports", {"project_id": _id}, sort=[("date", -1)], limit=1):
        photos = r.get("photos", [])[:3]
    body = f"Hi {p.get('client_name') or ''}, {p['name']} is {progress}% complete." + \
           (f" Current stage: {current}." if current else "") + " See photos in your portal."
    return jsonify(serialize(log_message({"channel": "whatsapp", "direction": "out", "contact_id": p["client_id"],
                                          "to_name": p.get("client_name"), "project_id": _id, "topic": "progress",
                                          "body": body, "attachments": photos})))


@bp.get("/pm-digest")
@api("projects", write=False)
def pm_digest():
    """One morning screen: done yesterday, late, stuck, budget warnings, urgent messages."""
    today = datetime.utcnow().date()
    yesterday = (today - timedelta(days=1)).isoformat()
    q = {"status": {"$in": ["active", "planning"]}}
    if g.role == "pm":
        q["pm_id"] = g.uid
    projects = t.find("projects", q)
    done, late, stuck, budget = [], [], [], []
    for p in projects:
        for s in p.get("stages", []):
            if s.get("alert_level") in ("yellow", "red"):
                budget.append({"project": p["name"], "project_id": str(p["_id"]), "stage": s["name"],
                               "level": s["alert_level"], "spent": s.get("spent"), "budget": s.get("budget")})
            if s.get("status") != "done" and s.get("end") and s["end"] < today.isoformat():
                late.append({"project": p["name"], "project_id": str(p["_id"]), "item": s["name"], "due": s["end"]})
            for task in s.get("tasks", []):
                if task.get("status") == "blocked":
                    stuck.append({"project": p["name"], "project_id": str(p["_id"]), "item": task["title"]})
                elif task.get("status") != "done" and task.get("due") and task["due"] < today.isoformat():
                    late.append({"project": p["name"], "project_id": str(p["_id"]), "item": task["title"],
                                 "due": task["due"]})
    for a in db.audit_logs.find({"company_id": g.cid, "collection": "projects",
                                 "at": {"$gte": datetime.fromisoformat(yesterday)}}):
        for k, ch in (a.get("changes") or {}).items():
            if k == "stages":
                for s in ch.get("to") or []:
                    for task in s.get("tasks", []):
                        if task.get("status") == "done":
                            done.append({"item": task["title"], "stage": s["name"]})
    seen = set()
    done = [x for x in done if not (x["item"] in seen or seen.add(x["item"]))]
    urgent = list(db.messages.find({"company_id": g.cid, "urgent": True, "status": "open"}).limit(20))
    pending_costs = t.find("costs", {"status": "pending_approval"})
    calls_saved = db.messages.count_documents({"company_id": g.cid, "direction": "in",
                                               "created_at": {"$gte": datetime.fromisoformat(yesterday)}})
    return jsonify({
        "done_yesterday": done[:30], "late": late, "stuck": stuck, "budget_warnings": budget,
        "urgent_messages": serialize(urgent), "pending_cost_approvals": t.out(pending_costs),
        "messages_handled_without_call": calls_saved,
    })


@bp.get("/inbox-stats")
@api("messages", write=False)
def inbox_stats():
    rows = list(db.messages.aggregate([
        {"$match": {"company_id": g.cid, "direction": "in"}},
        {"$group": {"_id": {"from": "$from_name", "topic": "$topic"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 30}]))
    return jsonify([{"from": r["_id"].get("from"), "topic": r["_id"].get("topic"), "count": r["count"]} for r in rows])
