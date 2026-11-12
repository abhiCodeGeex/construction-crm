"""Phase K block 4 — automatic follow-up sequences and rules (v4 §16).

A sequence = a trigger, then steps: wait N days → do something (send a message template, make a follow-up task,
notify someone). The worker starts a run for each new matching record and runs the steps when they fall due.
A run stops by itself when the client replies (any message from the contact after the run began), and when the record
moves on (the proposal is accepted, the selection chosen, the change order approved, the invoice paid, the lead won …).

Triggers (each only for records that happen after the sequence was switched on, so old data is never messaged):
  lead_new            a new enquiry
  site_visit_done     a site visit marked done
  proposal_sent       a proposal sent and not yet answered
  lead_lost           a lead recorded as lost (re-engage later)
  lead_cold           an open lead with no activity for `cold_days`
  approval_pending    a selection, change order or drawing waiting for the client
  invoice_overdue     an invoice past its due date
  handover            a project completed (warranty / maintenance check-ins, reviews and referrals)
  anniversary         a year since a project was completed (every year)
"""
import re
from datetime import timedelta, date

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, messaging as wa

bp = Blueprint("sequences", __name__)
TRIGGERS = {"lead_new": "New enquiry", "site_visit_done": "Site visit done", "proposal_sent": "Proposal sent", "lead_lost": "Lead lost",
            "lead_cold": "Lead gone cold", "approval_pending": "Client approval pending", "invoice_overdue": "Invoice overdue",
            "handover": "Project handed over", "anniversary": "Handover anniversary"}
ACTIONS = ("message", "task", "notify")
ROLES = ("owner", "pm", "sales", "accounts", "designer", "site", "procurement")

PRESETS = [
    {"name": "After an enquiry (day 1, 3, 7)", "trigger": "lead_new", "steps": [
        {"wait_days": 1, "action": "task", "title": "Call {{client}} about {{project}}"},
        {"wait_days": 2, "action": "message", "template": "Follow-up after enquiry"},
        {"wait_days": 4, "action": "task", "title": "Second follow-up: {{project}}"}]},
    {"name": "Proposal sent — chase", "trigger": "proposal_sent", "steps": [
        {"wait_days": 3, "action": "task", "title": "Ask {{client}} about the proposal"},
        {"wait_days": 4, "action": "notify", "role": "owner", "text": "Proposal for {{project}} unanswered for a week"}]},
    {"name": "Re-engage lost leads after 90 days", "trigger": "lead_lost", "steps": [{"wait_days": 90, "action": "message", "template": "Re-engage cold lead"}]},
    {"name": "After handover — warranty and review", "trigger": "handover", "steps": [
        {"wait_days": 7, "action": "task", "title": "Ask {{client}} for a review and a referral"},
        {"wait_days": 30, "action": "task", "title": "1-month check-in: {{project}}"},
        {"wait_days": 335, "action": "task", "title": "Warranty check before the year ends: {{project}}"}]},
]


def clean(d, seq=None):
    ch = {}
    if "name" in d or seq is None:
        ch["name"] = (d.get("name") or "").strip()[:120] or abort(400, "Name the sequence")
    if "trigger" in d or seq is None:
        ch["trigger"] = d.get("trigger") if d.get("trigger") in TRIGGERS else abort(400, f"Trigger: {', '.join(TRIGGERS)}")
    if "cold_days" in d:
        v = d["cold_days"]
        ch["cold_days"] = v if isinstance(v, int) and 3 <= v <= 365 else abort(400, "Cold after 3-365 days")
    for k in ("stop_on_reply", "stop_on_change", "active"):
        if k in d:
            ch[k] = bool(d[k])
    if "steps" in d or seq is None:
        steps = []
        for i, s in enumerate((d.get("steps") or [])[:10]):
            wait = s.get("wait_days")
            if not isinstance(wait, int) or not 0 <= wait <= 400:
                abort(400, f"Step {i + 1}: wait 0-400 days")
            act = s.get("action") if s.get("action") in ACTIONS else abort(400, f"Step {i + 1}: action message, task or notify")
            step = {"wait_days": wait, "action": act}
            if act == "message":
                tpl = db.message_templates.find_one({"company_id": g.cid, "$or": [{"_id": oid(s["template_id"])} if s.get("template_id") and len(s["template_id"]) == 24 else {"_id": None},
                                                                                  {"name": s.get("template")}]})
                tpl or abort(400, f"Step {i + 1}: choose a message template")
                step.update(template_id=str(tpl["_id"]), template=tpl["name"], channel=tpl["channel"])
            elif act == "task":
                step["title"] = (s.get("title") or "").strip()[:150] or abort(400, f"Step {i + 1}: task title")
            else:
                step["role"] = s.get("role") if s.get("role") in ROLES + ("record_owner",) else abort(400, f"Step {i + 1}: who to notify")
                step["text"] = (s.get("text") or "").strip()[:300] or abort(400, f"Step {i + 1}: notification text")
            steps.append(step)
        ch["steps"] = steps or abort(400, "Add at least one step")
    return ch


@bp.get("/sequences")
@api("followups", write=False)
def list_seq():
    rows = serialize(t.find("sequences", {}, sort=[("created_at", 1)]))
    for s in rows:
        s["running"] = db.sequence_runs.count_documents({"company_id": g.cid, "sequence_id": s["id"], "status": "running"})
        s["finished"] = db.sequence_runs.count_documents({"company_id": g.cid, "sequence_id": s["id"], "status": {"$in": ["done", "stopped"]}})
    return jsonify({"sequences": rows, "triggers": TRIGGERS, "presets": PRESETS,
                    "templates": [{"id": str(x["_id"]), "name": x["name"], "channel": x["channel"]} for x in db.message_templates.find({"company_id": g.cid})]})


def managers_only():
    if g.role not in ("owner", "pm") and not (g.role == "sales" and g.user.get("is_sales_manager")):
        abort(403, "Only the Owner or a manager sets up automatic sequences")


@bp.post("/sequences")
@api("followups")
def add_seq():
    managers_only()
    d = request.get_json(force=True) or {}
    s = t.insert("sequences", {"cold_days": 14, "stop_on_reply": True, "stop_on_change": True, "active": True, **clean(d)})
    return jsonify(serialize(s)), 201


@bp.put("/sequences/<sid>")
@api("followups")
def edit_seq(sid):
    managers_only()
    s = t.get("sequences", sid)
    ch = clean(request.get_json(force=True) or {}, s)
    if ch.get("active") and not s.get("active"):
        ch["created_at"] = t.now()  # switched back on: only new records from now
    return jsonify(serialize(t.update("sequences", sid, ch)))


@bp.delete("/sequences/<sid>")
@api("followups")
def delete_seq(sid):
    managers_only()
    t.get("sequences", sid)
    db.sequence_runs.update_many({"company_id": g.cid, "sequence_id": sid, "status": "running"}, {"$set": {"status": "stopped", "reason": "sequence deleted"}})
    db.sequences.delete_one({"_id": oid(sid)})
    return jsonify({"ok": True})


@bp.get("/sequences/runs")
@api("followups", write=False)
def runs():
    q = {}
    for k in ("sequence_id", "entity_id", "status"):
        if request.args.get(k):
            q[k] = request.args[k]
    return jsonify(serialize(t.find("sequence_runs", q, sort=[("started_at", -1)], limit=300)))


@bp.post("/sequences/runs/<rid>/stop")
@api("followups")
def stop_run(rid):
    r = t.get("sequence_runs", rid)
    if r["status"] != "running":
        abort(409, "Not running")
    return jsonify(serialize(t.update("sequence_runs", rid, {"status": "stopped", "reason": f"stopped by {g.user['name']}", "next_at": None})))


# ============================== the engine (worker) ==============================
def candidates(seq, now):
    """(entity_type, id, contact_id, owner_id, label, still_waiting_fn) for records the trigger matches."""
    since = seq["created_at"]
    trig = seq["trigger"]
    cid = g.cid
    if trig == "lead_new":
        for x in db.leads.find({"company_id": cid, "created_at": {"$gte": since}, "status": "open"}):
            yield "lead", x
    elif trig == "lead_lost":
        for x in db.leads.find({"company_id": cid, "status": "lost", "updated_at": {"$gte": since}}):
            yield "lead", x
    elif trig == "lead_cold":
        cut = now - timedelta(days=seq.get("cold_days") or 14)
        for x in db.leads.find({"company_id": cid, "status": "open", "$or": [{"last_activity_at": {"$lte": cut}}, {"last_activity_at": None, "created_at": {"$lte": cut}}],
                                "updated_at": {"$gte": since - timedelta(days=365)}}):
            yield "lead", x
    elif trig == "site_visit_done":
        for x in db.lead_visits.find({"company_id": cid, "status": "done", "done_at": {"$gte": since}}):
            yield "visit", x
    elif trig == "proposal_sent":
        for x in db.proposals.find({"company_id": cid, "status": "sent", "sent_at": {"$gte": since}}):
            yield "proposal", x
    elif trig == "approval_pending":
        for x in db.selections.find({"company_id": cid, "status": "options_sent", "sent_at": {"$gte": since}}):
            yield "selection", x
        for x in db.change_orders.find({"company_id": cid, "status": "sent", "sent_at": {"$gte": since}}):
            yield "change_order", x
    elif trig == "invoice_overdue":
        for x in db.invoices.find({"company_id": cid, "status": "sent", "due_date": {"$lt": now.date().isoformat()}, "sent_at": {"$gte": since}}):
            yield "invoice", x
    elif trig == "handover":
        for x in db.projects.find({"company_id": cid, "status": "completed", "updated_at": {"$gte": since}}):
            yield "project", x
    elif trig == "anniversary":
        md = now.strftime("-%m-%d")
        for x in db.projects.find({"company_id": cid, "status": "completed"}):
            done = (x.get("completed_at") or x.get("updated_at"))
            if done and done.strftime("-%m-%d") == md and done.year < now.year:
                yield "project", x


def still_waiting(kind, x, trigger=None):
    """False when the record has moved on (the reason a run stops)."""
    cur = db[{"lead": "leads", "visit": "lead_visits", "proposal": "proposals", "selection": "selections", "change_order": "change_orders",
              "invoice": "invoices", "project": "projects"}[kind]].find_one({"_id": x["_id"]})
    if not cur:
        return "record deleted"
    st = cur.get("status")
    moved = {"lead": lambda: st == "won" if trigger == "lead_lost" else st != "open",
             "proposal": lambda: st != "sent", "selection": lambda: st != "options_sent", "change_order": lambda: st != "sent",
             "invoice": lambda: st != "sent" or (cur.get("paid") or 0) >= (cur.get("total") or 0) - 0.005}.get(kind)
    return f"{kind.replace('_', ' ')} moved on ({st})" if moved and moved() else None


def contact_of(kind, x):
    if kind in ("lead", "proposal", "visit"):
        lead = x if kind == "lead" else db.leads.find_one({"_id": oid(x.get("lead_id"))}) if x.get("lead_id") else None
        return (lead or {}).get("contact_id"), (lead or {}).get("owner_id"), lead
    if kind == "project":
        return x.get("client_id"), next((m["user_id"] for m in x.get("team", []) if m.get("project_role") == "Project Manager" and m.get("user_id")), None), None
    p = db.projects.find_one({"_id": oid(x["project_id"])}) if x.get("project_id") else None
    return (p or {}).get("client_id") or x.get("client_id"), next((m["user_id"] for m in (p or {}).get("team", []) if m.get("project_role") == "Project Manager" and m.get("user_id")), None), None


def label_of(kind, x):
    return x.get("title") or x.get("name") or x.get("item") or x.get("number") or kind


def start_runs(seq, now):
    for kind, x in candidates(seq, now):
        key = f"{seq['_id']}:{kind}:{x['_id']}" + (f":{now.year}" if seq["trigger"] == "anniversary" else "")
        if db.sequence_runs.find_one({"company_id": g.cid, "key": key}, {"_id": 1}):
            continue
        contact_id, owner_id, _ = contact_of(kind, x)
        first = seq["steps"][0]["wait_days"]
        db.sequence_runs.insert_one({"company_id": g.cid, "key": key, "sequence_id": str(seq["_id"]), "sequence_name": seq["name"], "entity_type": kind,
                                     "entity_id": str(x["_id"]), "label": label_of(kind, x), "contact_id": contact_id, "owner_id": owner_id,
                                     "started_at": now, "step": 0, "next_at": now + timedelta(days=first), "status": "running", "log": [],
                                     "created_at": now, "updated_at": now})


def fill(text, ctx):
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1)) or m.group(0)), text or "")


def run_step(seq, r, now):
    kind = r["entity_type"]
    coll = {"lead": "leads", "visit": "lead_visits", "proposal": "proposals", "selection": "selections", "change_order": "change_orders",
            "invoice": "invoices", "project": "projects"}[kind]
    x = db[coll].find_one({"_id": oid(r["entity_id"])})
    if not x:
        return "record deleted"
    if seq.get("stop_on_change", True):
        why = still_waiting(kind, x, seq["trigger"])
        if why:
            return why
    contact = db.contacts.find_one({"_id": oid(r["contact_id"])}) if r.get("contact_id") and len(r["contact_id"]) == 24 else None
    if seq.get("stop_on_reply", True) and contact and db.messages.find_one({"company_id": g.cid, "contact_id": r["contact_id"], "created_at": {"$gt": r["started_at"]},
                                                                            "$or": [{"side": "contact"}, {"direction": "in"}]}, {"_id": 1}):
        return "the client replied"
    step = seq["steps"][r["step"]]
    owner = db.users.find_one({"_id": oid(r["owner_id"])}) if r.get("owner_id") else None
    ctx = {"client": (contact or {}).get("name"), "name": (contact or {}).get("name"), "project": label_of(kind, x), "company": g.company["name"],
           "date": date.today().strftime("%d %b %Y"), "salesperson": (owner or {}).get("name")}
    lead_id = str(x["_id"]) if kind == "lead" else x.get("lead_id")
    if step["action"] == "message":
        tpl = db.message_templates.find_one({"_id": oid(step["template_id"])})
        if not tpl:
            result = "template deleted"
        elif not contact:
            result = "no contact"
        else:
            text = fill(tpl["body"], ctx)
            if tpl["channel"] == "whatsapp":
                result = wa.notify_contact(contact, text, kind="sequence", ref=str(r["_id"])) or "not sent (no WhatsApp opt-in)"
            elif tpl["channel"] == "email":
                result = notify.deliver(g.company, contact.get("email"), fill(tpl.get("subject") or tpl["name"], ctx), text)
            else:
                from ..services import sms
                try:
                    m = sms.send(contact, text, kind="sequence", ref=str(r["_id"]))
                    result = (m or {}).get("status", "sent") if isinstance(m, dict) else str(m)
                except Exception as e:  # noqa: BLE001
                    result = f"not sent: {e}"
            if lead_id:
                from ..services.sales import log
                log(lead_id, tpl["channel"], f"Automatic ({seq['name']}): {text[:200]} — {result}")
    elif step["action"] == "task":
        uid = r.get("owner_id") or (notify.managers() or [None])[0]
        u = db.users.find_one({"_id": oid(uid)}) if uid else None
        rel = {"type": "lead", "id": lead_id, "label": label_of(kind, x), "contact_id": r.get("contact_id")} if lead_id else \
            {"type": "project", "id": r["entity_id"] if kind == "project" else x.get("project_id"), "label": label_of(kind, x), "contact_id": r.get("contact_id")}
        f = t.insert("followups", {"title": fill(step["title"], ctx), "due": now.date().isoformat(), "priority": "normal", "channel": None,
                                   "owner_id": uid, "owner_name": (u or {}).get("name"), "related": rel, "status": "open",
                                   "notes": f"From the automatic sequence “{seq['name']}”", "sequence_run_id": str(r["_id"])})
        notify.send("sequence_task", [uid], f"{f['title']} (sequence: {seq['name']})", "/app/followups", lead_id, skip_self=False)
        result = "task made"
    else:
        who = [r.get("owner_id")] if step["role"] == "record_owner" else notify.role_users(step["role"])
        notify.send("sequence_task", who, fill(step["text"], ctx), "/app/followups", lead_id, skip_self=False, key=f"seq:{r['_id']}:{r['step']}")
        result = f"notified {step['role']}"
    return {"done": result}


def check_sequences(now):
    for seq in db.sequences.find({"company_id": g.cid, "active": True}):
        start_runs(seq, now)
        for r in db.sequence_runs.find({"company_id": g.cid, "sequence_id": str(seq["_id"]), "status": "running", "next_at": {"$lte": now}}):
            res = run_step(seq, r, now)
            if isinstance(res, str):
                db.sequence_runs.update_one({"_id": r["_id"]}, {"$set": {"status": "stopped", "reason": res, "next_at": None, "updated_at": now}})
                continue
            nxt = r["step"] + 1
            entry = {"step": r["step"] + 1, "action": seq["steps"][r["step"]]["action"], "result": res["done"], "at": now}
            ch = {"step": nxt, "updated_at": now}
            if nxt < len(seq["steps"]):
                ch["next_at"] = now + timedelta(days=seq["steps"][nxt]["wait_days"])
            else:
                ch.update(status="done", next_at=None)
            db.sequence_runs.update_one({"_id": r["_id"]}, {"$set": ch, "$push": {"log": entry}})
