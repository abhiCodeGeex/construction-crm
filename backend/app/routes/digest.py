"""Phase J block 4 — the PM's morning screen, message reports, and email in the shared inbox (v4 §17).

* Digest (one morning screen): per project the user is on (Owner: every live project) — done yesterday (tasks done,
  site reports, approved site updates), late tasks, stuck (blocked / waiting tasks, field updates nobody settled,
  urgent messages), budget warnings (stages at 80 % or more). In the app at /digest; at the company's digest time the
  worker sends it as a notification and, to staff who opted in, on WhatsApp.
* Message reports: who writes most and about what — inbound WhatsApp, portal and email messages and site-worker
  updates per contact and topic, by channel, and how fast the team answers (first reply).
* Inbound email: a secret webhook address (for the mail provider's inbound parse — SendGrid, Mailgun, Postmark or a
  forwarding rule) puts an email from a known contact into that contact's project thread, routed like WhatsApp.
  The team's reply in the inbox already goes back by email. Unknown senders wait in an "unmatched" list.
"""
import secrets
from datetime import timedelta, date

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, messaging as wa
from ..services.budget import budget_rows

bp = Blueprint("digest", __name__)
LIVE = ["planning", "active", "on_hold"]


def my_projects(user_id=None, role=None):
    uid, role = user_id or g.uid, role or g.role
    q = {"company_id": g.cid, "status": {"$in": LIVE}, "deleted_at": None}
    if role != "owner":
        q["team.user_id"] = uid
    return list(db.projects.find(q).sort("name", 1))


def build(user_id=None, role=None, today=None):
    from .field import local_now
    today = today or local_now(t.now()).date()
    yday, iso = (today - timedelta(days=1)).isoformat(), today.isoformat()
    start = t.now() - timedelta(hours=36)
    out, totals = [], {"done": 0, "late": 0, "stuck": 0, "budget": 0}
    hide = role not in (None, "owner", "pm", "accounts") if role else g.hide_costs
    for p in my_projects(user_id, role):
        pid = str(p["_id"])
        tasks = [(s, tk) for s in p.get("stages", []) for tk in s.get("tasks", [])]
        done = [a["text"] for a in db.project_activity.find({"company_id": g.cid, "project_id": pid, "kind": {"$in": ["task", "field"]},
                                                             "at": {"$gte": start}}).sort("at", 1)
                if a["text"].endswith("→ done") or "Task done" in a["text"]]
        reports = db.site_reports.count_documents({"company_id": g.cid, "project_id": pid, "date": yday})
        late = [{"task": tk["title"], "stage": s["name"], "end": tk["end"], "days": (today - date.fromisoformat(tk["end"])).days,
                 "assignee": tk.get("assignee_name")}
                for s, tk in tasks if tk.get("end") and tk["end"] < iso and tk.get("status") != "done"]
        stuck = [{"what": tk["title"], "why": ((tk.get("waiting_on") or {}).get("note") or tk.get("notes") or "blocked"),
                  "since": (tk.get("waiting_on") or {}).get("since")} for s, tk in tasks if tk.get("status") == "blocked"]
        for f in db.field_updates.find({"company_id": g.cid, "project_id": pid, "status": {"$in": ["open", "pending", "awaiting"]}}):
            if f.get("urgent") or f["created_at"] < t.now() - timedelta(hours=12):
                stuck.append({"what": f"{f['worker_name']}: {(f.get('text') or f['kind'])[:80]}", "why": "urgent" if f.get("urgent") else f"{f['kind']} not settled",
                              "since": f["created_at"].date().isoformat()})
        budget = [] if hide else [{"stage": r["name"], "pct": r["pct"], "level": r["level"]} for r in budget_rows(p) if r["level"] in ("amber", "red")]
        row = {"project_id": pid, "project": p["name"], "done": done[-15:], "site_report": reports > 0, "late": late, "stuck": stuck, "budget": budget}
        for k in ("late", "stuck", "budget"):
            totals[k] += len(row[k])
        totals["done"] += len(done)
        out.append(row)
    attention = sorted(out, key=lambda r: -(len(r["late"]) * 2 + len(r["stuck"]) * 3 + len(r["budget"])))
    return {"day": iso, "yesterday": yday, "projects": attention, "totals": totals}


@bp.get("/digest")
@api(None)
def digest():
    if not (can("site") or g.role in ("owner", "pm")):
        abort(403, "Your role has no project digest")
    return jsonify(build())


def digest_text(dg, name):
    tt = dg["totals"]
    lines = [f"Good morning {name} — {dg['day']}: {tt['done']} done yesterday, {tt['late']} late, {tt['stuck']} stuck, {tt['budget']} budget warnings."]
    for r in dg["projects"][:8]:
        bits = []
        if r["late"]:
            bits.append(f"{len(r['late'])} late ({r['late'][0]['task']})")
        if r["stuck"]:
            bits.append(f"{len(r['stuck'])} stuck ({r['stuck'][0]['what'][:40]})")
        if r["budget"]:
            bits.append("budget " + ", ".join(f"{b['stage']} {b['pct']:g}%" for b in r["budget"][:2]))
        if not r["site_report"]:
            bits.append("no site report yesterday")
        if bits:
            lines.append(f"• {r['project']}: " + "; ".join(bits))
    return "\n".join(lines)


def check_digest(now):
    from .field import fsettings, local_now
    s = fsettings()
    if not s.get("digest_on"):
        return
    local = local_now(now)
    day = local.date().isoformat()
    if local.strftime("%H:%M") < s["digest_time"] or (g.company.get("field_runs") or {}).get("digest") == day:
        return
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"field_runs.digest": day}})
    g.company.setdefault("field_runs", {})["digest"] = day
    for u in db.users.find({"company_id": g.cid, "kind": "staff", "active": {"$ne": False}, "role": {"$in": ["owner", "pm"]}}):
        dg = build(str(u["_id"]), u["role"], local.date())
        if not dg["projects"]:
            continue
        text = digest_text(dg, u["name"].split(" ")[0])
        notify.send("pm_digest", [str(u["_id"])], text[:1500], "/app/digest", key=f"digest:{u['_id']}:{day}", skip_self=False)
        if u.get("whatsapp_opt_in") and wa.phone_e164(u.get("phone")):
            try:
                wa.send({"id": f"u:{u['_id']}", "name": u["name"], "phone": u["phone"], "whatsapp_opt_in": u["whatsapp_opt_in"]},
                        text, kind="pm_digest", ref=day)
            except Exception:  # noqa: BLE001 — quota: the app notification is enough
                pass


@bp.put("/me/whatsapp")
@api(None)
def my_whatsapp():
    """Staff agree to get their digest on WhatsApp (their own mobile number on the profile)."""
    on = bool((request.get_json(force=True) or {}).get("opt_in"))
    u = db.users.find_one({"_id": oid(g.uid)})
    if on and not wa.phone_e164(u.get("phone")):
        abort(400, "Add your mobile number to your profile first")
    db.users.update_one({"_id": u["_id"]}, {"$set": {"whatsapp_opt_in": {"at": t.now(), "how": "self"} if on else None}})
    return jsonify({"opt_in": on})


# ============================== message reports ==============================
@bp.get("/reports/messages")
@api(None)
def message_report():
    if not (can("reports") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view message reports")
    days = request.args.get("days", "30")
    days = int(days) if days.isdigit() and 1 <= int(days) <= 365 else abort(400, "Days: 1-365")
    since = t.now() - timedelta(days=days)
    pq = {} if g.role == "owner" else {"project_id": {"$in": [str(p["_id"]) for p in my_projects()]}}
    inbound = list(db.messages.find({"company_id": g.cid, "created_at": {"$gte": since}, **pq,
                                     "$or": [{"side": "contact"}, {"direction": "in", "channel": {"$in": ["whatsapp", "email"]}}]}))
    field = list(db.field_updates.find({"company_id": g.cid, "created_at": {"$gte": since}, **pq}))
    people, topics, channels = {}, {}, {}
    for m in inbound:
        if m.get("channel") in ("whatsapp", "email") and m.get("direction") == "in" and m.get("routed"):
            continue  # also kept in the project thread; count it once
        ch = m.get("via") or m.get("channel")
        who = people.setdefault(m.get("contact_id") or m.get("from"), {"name": m.get("contact_name") or m.get("from"), "count": 0, "topics": {},
                                                                       "channels": {}, "last": None, "urgent": 0, "kind": "worker" if m.get("worker_id") else "contact"})
        if m.get("worker_id") and m.get("field_update_id"):
            continue  # counted from the field update below
        who["count"] += 1
        tp = m.get("topic") or "general"
        who["topics"][tp] = who["topics"].get(tp, 0) + 1
        who["channels"][ch] = who["channels"].get(ch, 0) + 1
        who["urgent"] += 1 if m.get("urgent") else 0
        who["last"] = max(filter(None, [who["last"], m["created_at"]]))
        topics[tp] = topics.get(tp, 0) + 1
        channels[ch] = channels.get(ch, 0) + 1
    for f in field:
        who = people.setdefault(f"w:{f['worker_id']}", {"name": f["worker_name"], "count": 0, "topics": {}, "channels": {}, "last": None,
                                                        "urgent": 0, "kind": "worker"})
        who["count"] += 1
        tp = {"material": "material_needed", "help": "need_clarification", "done": "work_done"}.get(f["kind"], f.get("topic") or "general")
        who["topics"][tp] = who["topics"].get(tp, 0) + 1
        who["channels"]["whatsapp"] = who["channels"].get("whatsapp", 0) + 1
        who["urgent"] += 1 if f.get("urgent") else 0
        who["last"] = max(filter(None, [who["last"], f["created_at"]]))
        topics[tp] = topics.get(tp, 0) + 1
        channels["whatsapp (site)"] = channels.get("whatsapp (site)", 0) + 1
    # first reply: for each inbound thread message, the next team message in that thread
    waits = []
    for m in inbound:
        if m.get("side") != "contact" or not m.get("project_id"):
            continue
        r = db.messages.find_one({"company_id": g.cid, "project_id": m["project_id"], "contact_id": m["contact_id"], "side": "team",
                                  "created_at": {"$gt": m["created_at"]}}, sort=[("created_at", 1)])
        if r:
            waits.append((r["created_at"] - m["created_at"]).total_seconds() / 60)
    rows = sorted(({**v, "topics": sorted(v["topics"].items(), key=lambda x: -x[1]), "last": v["last"] and v["last"].isoformat()}
                   for v in people.values() if v["count"]), key=lambda x: -x["count"])
    unanswered = sum(1 for m in inbound if m.get("side") == "contact" and not m.get("read_by_team"))
    return jsonify({"days": days, "people": rows[:50], "topics": sorted(topics.items(), key=lambda x: -x[1]),
                    "channels": sorted(channels.items(), key=lambda x: -x[1]), "messages": sum(v["count"] for v in people.values()),
                    "first_reply_minutes": round(sorted(waits)[len(waits) // 2], 1) if waits else None, "answered": len(waits),
                    "unanswered": unanswered,
                    "calls": calls(since)})


def calls(since):
    """Calls logged on leads (the lead timeline 'call' entries) per person."""
    out = {}
    for ld in db.leads.find({"company_id": g.cid, "activities.kind": "call"}, {"activities": 1}):
        for a in ld.get("activities", []):
            if a.get("kind") == "call" and a.get("at") and a["at"] >= since:
                out[a.get("by") or "—"] = out.get(a.get("by") or "—", 0) + 1
    return sorted(out.items(), key=lambda x: -x[1])


# ============================== inbound email ==============================
@bp.get("/settings/inbound-email")
@api("settings", write=False)
def get_inbound():
    s = g.company.get("inbound_email") or {}
    return jsonify({"enabled": bool(s.get("token")), "webhook_url": f"/api/webhooks/email/{g.cid}/{s['token']}" if s.get("token") else None,
                    "unmatched": db.messages.count_documents({"company_id": g.cid, "channel": "email", "direction": "in", "matched": False})})


@bp.post("/settings/inbound-email")
@api("settings")
def set_inbound():
    on = (request.get_json(force=True) or {}).get("enabled", True)
    s = {"token": secrets.token_urlsafe(24)} if on else {}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"inbound_email": s}})
    g.company["inbound_email"] = s
    t.audit("update", "companies", g.company["_id"], note="Inbound email " + ("address made" if on else "turned off"))
    return get_inbound()


def address_of(v):
    v = (v or "").strip()
    if "<" in v and ">" in v:
        v = v[v.index("<") + 1:v.index(">")]
    return v.strip().lower()


@bp.post("/webhooks/email/<cid_>/<token>")
def inbound_email(cid_, token):
    company = db.companies.find_one({"_id": oid(cid_), "deleted_at": None}) if len(cid_) == 24 else None
    s = (company or {}).get("inbound_email") or {}
    if not company or not s.get("token") or not secrets.compare_digest(token, s["token"]):
        abort(404)
    g.cid, g.company, g.uid, g.role, g.user = cid_, company, None, None, {"name": "Email"}
    d = request.get_json(silent=True) or request.form.to_dict() or {}
    frm = address_of(d.get("from") or d.get("sender") or d.get("From"))
    subject = (d.get("subject") or d.get("Subject") or "").strip()[:300]
    text = (d.get("text") or d.get("stripped-text") or d.get("TextBody") or d.get("body-plain") or "").strip()
    # keep only the new part of a reply
    for marker in ("\nOn ", "\n-----Original", "\n> "):
        if marker in text and text.index(marker) > 0:
            text = text[:text.index(marker)].strip()
    if not frm or not (text or subject):
        abort(400, "from and text are required")
    msg_id = (d.get("message_id") or d.get("Message-Id") or d.get("MessageID") or "")[:300] or None
    if msg_id and db.messages.find_one({"company_id": cid_, "provider_id": msg_id, "channel": "email"}):
        return jsonify({"ok": True, "duplicate": True})
    contact = db.contacts.find_one({"company_id": cid_, "email": {"$regex": f"^{__import__('re').escape(frm)}$", "$options": "i"}})
    body = (f"{subject}\n\n{text}" if subject and not subject.lower().startswith("re:") else text or subject)[:4000]
    routed = None
    if contact:
        from .insights import route_inbound
        routed = route_inbound(contact, body, via="email")
    t.insert("messages", {"channel": "email", "direction": "in", "contact_id": contact and str(contact["_id"]),
                          "contact_name": (contact or {}).get("name") or frm, "from": frm, "subject": subject, "text": body,
                          "provider_id": msg_id, "status": "received", "matched": bool(contact), "routed": routed})
    if not contact:
        notify.send("email_in", notify.managers(), f"Email from an unknown sender {frm}: {subject or text[:80]}", "/app/inbox?tab=email",
                    skip_self=False)
    return jsonify({"ok": True, "matched": bool(contact), "routed": bool(routed)})


@bp.get("/inbox/email")
@api("messages", write=False)
def email_list():
    q = {"channel": "email", "direction": "in"}
    if request.args.get("unmatched"):
        q["matched"] = False
    return jsonify(serialize(t.find("messages", q, sort=[("created_at", -1)], limit=200)))
