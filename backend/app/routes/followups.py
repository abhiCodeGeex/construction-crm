"""Follow-up tasks, reminders and message templates (requirements §16, MVP scope — no automatic sequences)."""
import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify
from ..services.defaults import FOLLOWUP_CHANNELS

bp = Blueprint("followups", __name__)

PRIORITIES = ("low", "normal", "high")
MANAGERS = ("owner", "pm")
TEMPLATE_CHANNELS = ("email", "sms", "whatsapp")
MERGE_FIELDS = ("client", "name", "project", "amount", "company", "date", "salesperson")


def _date(v, field, required=False):
    if v in (None, ""):
        if required:
            abort(400, f"{field} is required")
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        abort(400, f"{field} must be a date (YYYY-MM-DD)")


def related_doc(rel):
    """Validate the lead / contact / project a follow-up belongs to; returns a label for display."""
    if not rel:
        return None
    kind, rid = rel.get("type"), rel.get("id")
    if kind == "lead":
        doc = t.get("leads", rid, required=False) or abort(400, "Lead not found")
        return {"type": "lead", "id": rid, "label": doc["title"], "contact_id": doc.get("contact_id")}
    if kind == "contact":
        doc = t.get("contacts", rid, required=False) or abort(400, "Contact not found")
        return {"type": "contact", "id": rid, "label": doc["name"], "contact_id": rid}
    if kind == "project":
        from .projects import load
        doc = load(rid)  # must be able to see the project
        return {"type": "project", "id": rid, "label": doc["name"], "contact_id": doc.get("client_id")}
    abort(400, "Follow-up must relate to a lead, contact or project")


def visible_q():
    return {} if g.role in MANAGERS else {"$or": [{"owner_id": g.uid}, {"created_by": g.uid}]}


def get_visible(_id):
    f = t.get("followups", _id)
    if g.role not in MANAGERS and g.uid not in (f.get("owner_id"), f.get("created_by")):
        abort(404, "follow-up not found")
    return f


def present(f):
    data = serialize(f)
    today = date.today().isoformat()
    data["overdue"] = f["status"] == "open" and f["due"] < today
    data["due_today"] = f["status"] == "open" and f["due"] == today
    return data


def clean(d, existing=None):
    m = {**(existing or {}), **d}
    out = {}
    if not (m.get("title") or "").strip():
        abort(400, "Follow-up title is required")
    out["title"] = m["title"].strip()
    out["due"] = _date(m.get("due"), "Due date", required=True)
    if m.get("priority", "normal") not in PRIORITIES:
        abort(400, "Priority must be low, normal or high")
    out["priority"] = m.get("priority", "normal")
    if m.get("channel") and m["channel"] not in FOLLOWUP_CHANNELS:
        abort(400, f"Channel must be one of: {', '.join(FOLLOWUP_CHANNELS)}")
    out["channel"] = m.get("channel")
    owner = m.get("owner_id") or g.uid
    u = db.users.find_one({"_id": oid(owner), "company_id": g.cid, "kind": "staff", "active": {"$ne": False}})
    if not u:
        abort(400, "Owner must be an active staff user")
    if owner != g.uid and g.role not in MANAGERS and not can("leads", True):
        abort(403, "Only managers and sales can assign follow-ups to someone else")
    out["owner_id"], out["owner_name"] = owner, u["name"]
    if "notes" in d:
        out["notes"] = d["notes"]
    if "related" in d or existing is None:
        out["related"] = related_doc(m.get("related"))
    return out


@bp.get("/followups/meta")
@api("followups", write=False)
def meta():
    staff = [{"id": str(u["_id"]), "name": u["name"]} for u in
             db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}}, {"name": 1})]
    return jsonify({"priorities": PRIORITIES, "channels": FOLLOWUP_CHANNELS, "staff": staff,
                    "can_view_all": g.role in MANAGERS, "merge_fields": MERGE_FIELDS})


@bp.get("/followups")
@api("followups")
def list_followups():
    q = visible_q()
    for k in ("status", "priority"):
        if request.args.get(k):
            q[k] = request.args[k]
    if request.args.get("owner_id"):
        if g.role not in MANAGERS and request.args["owner_id"] != g.uid:
            abort(403, "You can only view your own follow-ups")
        q = {**q, "owner_id": request.args["owner_id"]}
    if request.args.get("related_type"):
        q["related.type"] = request.args["related_type"]
    if request.args.get("related_id"):
        q["related.id"] = request.args["related_id"]
    return jsonify([present(f) for f in t.find("followups", q, sort=[("due", 1), ("priority", -1)])])


@bp.get("/followups/today")
@api("followups", write=False)
def today():
    """§16 "Today's follow-ups": overdue, due today, next 7 days. Managers may pass ?owner_id= or ?all=1."""
    q = {"status": "open"}
    if request.args.get("all") == "1" and g.role in MANAGERS:
        pass
    elif request.args.get("owner_id") and g.role in MANAGERS:
        q["owner_id"] = request.args["owner_id"]
    else:
        q["owner_id"] = g.uid
    today_s = date.today().isoformat()
    week = (date.today() + timedelta(days=7)).isoformat()
    rows = [present(f) for f in t.find("followups", {**q, "due": {"$lte": week}}, sort=[("due", 1)])]
    order = {"high": 0, "normal": 1, "low": 2}
    bucket = lambda b: sorted([r for r in rows if b(r)], key=lambda r: (r["due"], order[r["priority"]]))
    return jsonify({"overdue": bucket(lambda r: r["due"] < today_s), "today": bucket(lambda r: r["due"] == today_s),
                    "upcoming": bucket(lambda r: r["due"] > today_s)})


@bp.post("/followups")
@api("followups")
def create():
    d = clean(request.get_json(force=True) or {})
    d["status"] = "open"
    f = t.insert("followups", d)
    rel = d.get("related") or {}
    notify.send("followup_assigned", [d["owner_id"]], f"{g.user.get('name')} gave you a follow-up: {d['title']} "
                f"(due {d['due']})", f"/app/leads/{rel['id']}" if rel.get("type") == "lead" else "/app/followups",
                rel.get("id") if rel.get("type") == "lead" else None)
    return jsonify(present(f)), 201


@bp.put("/followups/<_id>")
@api("followups")
def update(_id):
    f = get_visible(_id)
    if f["status"] != "open":
        abort(409, f"This follow-up is {f['status']}; reopen it to change it")
    return jsonify(present(t.update("followups", _id, clean(request.get_json(force=True) or {}, f))))


@bp.post("/followups/<_id>/done")
@api("followups")
def done(_id):
    """Completing a follow-up records the outcome and logs it on the lead (§16 'logged on the timeline')."""
    f = get_visible(_id)
    if f["status"] != "open":
        abort(409, f"This follow-up is already {f['status']}")
    d = request.get_json(force=True) or {}
    outcome = (d.get("outcome") or "").strip()
    if not outcome:
        abort(400, "Record the outcome (what happened)")
    upd = t.update("followups", _id, {"status": "done", "done_at": t.now(), "outcome": outcome, "done_by": g.user.get("name")})
    rel = f.get("related") or {}
    if rel.get("type") == "lead":
        lead = t.get("leads", rel["id"], required=False)
        if lead and lead["status"] == "open":
            act = {"id": t.sid(), "type": f.get("channel") if f.get("channel") in ("call", "email", "whatsapp", "meeting", "site_visit") else "note",
                   "text": f"Follow-up done: {f['title']} — {outcome}", "at": t.now(), "by": g.user.get("name"), "by_id": g.uid,
                   "followup_id": _id}
            changes = {"last_activity_at": t.now()}
            if not lead.get("first_response_at"):
                changes["first_response_at"] = t.now()
            t.update("leads", rel["id"], changes, raw={"$push": {"activities": act}})
    if d.get("next_due"):
        t.insert("followups", {**{k: f[k] for k in ("title", "priority", "channel", "owner_id", "owner_name", "related")},
                               "due": _date(d["next_due"], "Next follow-up date"), "status": "open",
                               "notes": d.get("next_notes"), "previous_id": _id})
    return jsonify(present(upd))


@bp.post("/followups/<_id>/cancel")
@api("followups")
def cancel(_id):
    f = get_visible(_id)
    if f["status"] != "open":
        abort(409, f"This follow-up is already {f['status']}")
    return jsonify(present(t.update("followups", _id, {"status": "cancelled", "outcome": (request.get_json(force=True) or {}).get("reason")})))


@bp.post("/followups/<_id>/reopen")
@api("followups")
def reopen(_id):
    f = get_visible(_id)
    if f["status"] == "open":
        abort(409, "Already open")
    return jsonify(present(t.update("followups", _id, {"status": "open", "done_at": None, "outcome": None})))


@bp.delete("/followups/<_id>")
@api("followups")
def delete(_id):
    f = get_visible(_id)
    if f.get("created_by") != g.uid and g.role != "owner":
        abort(403, "Only the person who created it (or the owner) can delete a follow-up")
    t.delete("followups", _id)
    return jsonify({"ok": True})


# ---------------- message templates ----------------
def clean_tpl(d, existing=None):
    m = {**(existing or {}), **d}
    if not (m.get("name") or "").strip():
        abort(400, "Template name is required")
    if m.get("channel") not in TEMPLATE_CHANNELS:
        abort(400, "Channel must be email, SMS or WhatsApp")
    body = (m.get("body") or "").strip()
    if not body:
        abort(400, "Template text is required")
    unknown = sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", body)) - set(MERGE_FIELDS))
    if unknown:
        abort(400, f"Unknown merge field(s): {', '.join(unknown)}. Use: {', '.join(MERGE_FIELDS)}")
    if m["channel"] == "sms" and len(body) > 480:
        abort(400, "SMS templates must be at most 480 characters")
    return {"name": m["name"].strip(), "channel": m["channel"], "body": body, "subject": m.get("subject")}


@bp.get("/message_templates")
@api("followups", write=False)
def list_templates():
    q = {"channel": request.args["channel"]} if request.args.get("channel") else {}
    return jsonify(serialize(t.find("message_templates", q, sort=[("channel", 1), ("name", 1)])))


@bp.post("/message_templates")
@api("settings")
def create_template():
    return jsonify(serialize(t.insert("message_templates", clean_tpl(request.get_json(force=True) or {})))), 201


@bp.put("/message_templates/<_id>")
@api("settings")
def update_template(_id):
    tpl = t.get("message_templates", _id)
    return jsonify(serialize(t.update("message_templates", _id, clean_tpl(request.get_json(force=True) or {}, tpl))))


@bp.delete("/message_templates/<_id>")
@api("settings")
def delete_template(_id):
    t.get("message_templates", _id)
    t.delete("message_templates", _id)
    return jsonify({"ok": True})


@bp.post("/message_templates/<_id>/render")
@api("followups", write=False)
def render(_id):
    """Fill merge fields from a lead / contact / project. Unknown values stay visible as {{field}}."""
    tpl = t.get("message_templates", _id)
    d = request.get_json(force=True) or {}
    ctx = {"company": g.company["name"], "date": date.today().strftime("%d %b %Y"), "salesperson": g.user.get("name")}
    if d.get("lead_id"):
        lead = t.get("leads", d["lead_id"])
        ctx.update(client=lead.get("contact_name"), name=lead.get("contact_name"), project=lead["title"],
                   amount=money(lead.get("budget")))
        if lead.get("owner_name"):
            ctx["salesperson"] = lead["owner_name"]
    if d.get("project_id"):
        from .projects import load
        p = load(d["project_id"])
        ctx.update(project=p["name"], client=p.get("client_name") or ctx.get("client"))
        if not g.hide_costs:
            ctx["amount"] = money(p.get("value"))
    if d.get("contact_id"):
        c = t.get("contacts", d["contact_id"])
        ctx.update(client=c["name"], name=c["name"])
    for k, v in (d.get("values") or {}).items():
        if k in MERGE_FIELDS and v not in (None, ""):
            ctx[k] = str(v)
    fill = lambda s: re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda mm: str(ctx.get(mm.group(1)) or mm.group(0)), s or "")
    text = fill(tpl["body"])
    return jsonify({"channel": tpl["channel"], "subject": fill(tpl.get("subject")), "text": text,
                    "missing": sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", text)))})


def money(v):
    """Same format the app shows: INR in lakh/crore grouping (₹65,00,000), other currencies in thousands."""
    if v in (None, ""):
        return None
    cur = g.company.get("currency", "INR")
    n = int(round(v))
    if cur != "INR":
        return f"{cur} {n:,}"
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"{'-' if n < 0 else ''}₹{s}"


# ---------------- timelines (§16 "logged on the contact and project timeline") ----------------
def _timeline(followups, leads):
    rows = [{"kind": "followup", "at": f.get("done_at") or f["created_at"], "status": f["status"], "title": f["title"],
             "due": f["due"], "owner": f.get("owner_name"), "outcome": f.get("outcome"), "id": str(f["_id"]),
             "related": f.get("related")} for f in followups]
    for lead in leads:
        for a in lead.get("activities", []):
            rows.append({"kind": "activity", "at": a["at"], "type": a["type"], "title": a["text"], "owner": a.get("by"),
                         "lead_id": str(lead["_id"]), "lead": lead["title"]})
    return serialize(sorted(rows, key=lambda r: r["at"], reverse=True))


@bp.get("/contacts/<_id>/timeline")
@api("contacts", write=False)
def contact_timeline(_id):
    t.get("contacts", _id)
    leads = t.find("leads", {"contact_id": _id})
    lead_ids = [str(x["_id"]) for x in leads]
    projects = [str(p["_id"]) for p in t.find("projects", {"$or": [{"client_id": _id}, {"team.contact_id": _id}]})]
    fq = {"$or": [{"related.contact_id": _id}, {"related.id": {"$in": lead_ids + projects + [_id]}}]}
    if g.role not in MANAGERS:
        fq = {"$and": [fq, visible_q()]}
    return jsonify(_timeline(t.find("followups", fq), leads))


@bp.get("/projects/<_id>/followups")
@api("projects")
def project_followups(_id):
    from .projects import load
    load(_id)
    leads = t.find("leads", {"project_id": _id})
    fq = {"related.id": {"$in": [_id] + [str(x["_id"]) for x in leads]}}
    if g.role not in MANAGERS:
        fq = {"$and": [fq, visible_q()]}
    return jsonify(_timeline(t.find("followups", fq), leads))


# ---------------- report (§16 overdue follow-ups per user) ----------------
@bp.get("/reports/followups")
@api("followups", write=False)
def report():
    if g.role not in MANAGERS:
        abort(403, "Only the owner and project managers can see everyone's follow-ups")
    today_s = date.today().isoformat()
    rows = {}
    for f in t.find("followups", {}):
        r = rows.setdefault(f.get("owner_id"), {"owner": f.get("owner_name") or "—", "open": 0, "overdue": 0, "done": 0,
                                                "done_on_time": 0, "cancelled": 0})
        if f["status"] == "open":
            r["open"] += 1
            if f["due"] < today_s:
                r["overdue"] += 1
        elif f["status"] == "done":
            r["done"] += 1
            if f.get("done_at") and f["done_at"].date().isoformat() <= f["due"]:
                r["done_on_time"] += 1
        else:
            r["cancelled"] += 1
    out = []
    for r in rows.values():
        r["on_time_pct"] = round(r["done_on_time"] / r["done"] * 100, 1) if r["done"] else None
        out.append(r)
    return jsonify(sorted(out, key=lambda r: -r["overdue"]))
