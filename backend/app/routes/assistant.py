"""Phase K block 6 — the WhatsApp assistant and the phone system (IVR) with call logging (v4 §16 / Phase 2).

Assistant: answers a client's common questions on WhatsApp from the facts of their project — progress, the next
milestone, what is due to pay, who their PM is, the last site report — and the company's own FAQ list.
  * mode "faq": keyword matching only (no AI, nothing leaves the server);
  * mode "claude": Claude (Anthropic API, the company's own key) writes the answer from the same facts and FAQs and
    says when a person must take over. Low effort, structured JSON reply, server-side refusal fallback.
  The message still lands in the project thread (Phase I routing); the assistant's answer is added to the thread so the
  team sees it. Urgent messages, complaints and anything it is not sure of go to the team ("handoff"), never guessed.
Phone (IVR): the provider (Twilio, Exotel, or the sandbox) calls our webhook on an incoming call. The caller hears the
  greeting and a menu (1 sales, 2 my project, 3 accounts …), the call is put through to the right person (the role on
  the caller's project, else anyone in that role), and every call is logged with its duration and recording.
  A missed call becomes a call-back follow-up. Calls with a known contact go on their open lead's timeline.
"""
import json
import re
import secrets
from datetime import date, timedelta
from xml.sax.saxutils import escape

from flask import Blueprint, request, jsonify, abort, g, Response

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, messaging as wa

bp = Blueprint("assistant", __name__)
MODES = ("off", "faq", "claude")
DEFAULT_MODEL = "claude-opus-5-5"
LIVE = ["planning", "active", "on_hold"]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer", "handoff"],
          "properties": {"answer": {"type": "string"}, "handoff": {"type": "boolean"}}}


def asettings(company=None):
    return {"mode": "off", "api_key": None, "model": DEFAULT_MODEL, "faqs": [], "handoff_text": "Thank you — your project team will reply shortly.",
            **((company or g.company).get("assistant") or {})}


@bp.get("/settings/assistant")
@api("settings", write=False)
def get_assistant():
    s = asettings()
    return jsonify({**{k: v for k, v in s.items() if k != "api_key"}, "api_key_set": bool(s.get("api_key")), "modes": MODES})


@bp.put("/settings/assistant")
@api("settings")
def put_assistant():
    d = request.get_json(force=True) or {}
    s = asettings()
    if "mode" in d:
        s["mode"] = d["mode"] if d["mode"] in MODES else abort(400, "Mode: off, faq or claude")
    if d.get("api_key"):
        s["api_key"] = d["api_key"].strip()
    if "model" in d:
        s["model"] = (d.get("model") or DEFAULT_MODEL).strip()[:60]
    if "handoff_text" in d:
        s["handoff_text"] = (d.get("handoff_text") or "").strip()[:300] or asettings({})["handoff_text"]
    if "faqs" in d:
        faqs = []
        for f in (d["faqs"] or [])[:60]:
            q, a = (f.get("q") or "").strip()[:200], (f.get("a") or "").strip()[:1000]
            if q and a:
                faqs.append({"q": q, "a": a})
        s["faqs"] = faqs
    if s["mode"] == "claude" and not s.get("api_key"):
        abort(400, "Enter the Anthropic API key for the Claude assistant")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"assistant": s}})
    g.company["assistant"] = s
    t.audit("update", "companies", g.company["_id"], note=f"WhatsApp assistant: {s['mode']}")
    return get_assistant()


# ---------------- what the assistant knows about the caller ----------------
def facts(contact):
    """The project facts a client may ask about (no internal costs)."""
    cid_ = str(contact["_id"])
    out = []
    for p in db.projects.find({"company_id": g.cid, "status": {"$in": LIVE}, "team.contact_id": cid_}).sort("updated_at", -1).limit(3):
        pid = str(p["_id"])
        stages = p.get("stages", [])
        prog = round(sum(s.get("progress", 0) for s in stages) / len(stages)) if stages else 0
        today = date.today().isoformat()
        ms = sorted([(m.get("date") or m.get("due"), m.get("name") or m.get("title")) for s in stages for m in s.get("milestones", [])
                     if (m.get("date") or m.get("due") or "") >= today and not m.get("done")])
        cur = next((s["name"] for s in stages if s.get("status") not in ("done",)), None)
        pm = next((m for m in p.get("team", []) if m.get("project_role") == "Project Manager" and m.get("user_id")), None)
        pmu = db.users.find_one({"_id": oid(pm["user_id"])}) if pm else None
        due = [i for i in db.invoices.find({"company_id": g.cid, "project_id": pid, "status": {"$in": ["sent", "part_paid"]}})]
        bal = round(sum((i.get("total") or 0) - (i.get("paid") or 0) - (i.get("credited") or 0) for i in due), 2)
        last_rep = db.site_reports.find_one({"company_id": g.cid, "project_id": pid}, sort=[("date", -1)])
        out.append({"project": p["name"], "status": p.get("status"), "progress_pct": prog, "current_stage": cur,
                    "next_milestone": ms[0][1] if ms else None, "next_milestone_date": ms[0][0] if ms else None,
                    "pm": pmu and pmu["name"], "pm_phone": pmu and pmu.get("phone"),
                    "amount_due": bal, "invoices_due": [{"number": i.get("number"), "due_date": i.get("due_date")} for i in due][:5],
                    "currency": g.company.get("currency") or "INR", "last_site_report": last_rep and last_rep.get("date"),
                    "planned_end": p.get("end")})
    return out


def money(v, cur):
    return f"{'₹' if cur == 'INR' else cur + ' '}{v:,.0f}"


def faq_answer(text, fs, faqs):
    """Keyword answers: a matching FAQ, else a known intent about the project, else None (hand over)."""
    low = text.lower()
    words = set(re.findall(r"[a-zऀ-ॿ]{3,}", low))
    best, score = None, 0
    for f in faqs:
        qw = set(re.findall(r"[a-zऀ-ॿ]{3,}", f["q"].lower()))
        sc = len(words & qw) / max(1, len(qw))
        if sc > score:
            best, score = f, sc
    if best and score >= 0.5:
        return best["a"]
    if not fs:
        return None
    p = fs[0]
    if any(w in low for w in ("pay", "due", "invoice", "bill", "amount", "balance", "भुगतान")):
        if p["amount_due"] > 0:
            return f"For {p['project']}, {money(p['amount_due'], p['currency'])} is due" + (
                f" (invoice {p['invoices_due'][0]['number']}, due {p['invoices_due'][0]['due_date']})" if p["invoices_due"] else "") + ". You can pay from your portal."
        return f"Nothing is due on {p['project']} right now. Thank you!"
    if any(w in low for w in ("progress", "status", "update", "how far", "प्रगति")):
        return (f"{p['project']} is {p['progress_pct']}% complete" + (f", now in {p['current_stage']}" if p["current_stage"] else "") + "."
                + (f" Next: {p['next_milestone']} by {p['next_milestone_date']}." if p["next_milestone"] else ""))
    if any(w in low for w in ("when", "finish", "complete", "handover", "milestone", "कब")):
        if p["next_milestone"]:
            return f"The next milestone on {p['project']} is {p['next_milestone']}, planned for {p['next_milestone_date']}."
        return f"{p['project']} is planned to finish on {p['planned_end']}." if p.get("planned_end") else None
    if any(w in low for w in ("manager", "contact", "call", "phone", "number")) and p["pm"]:
        return f"Your project manager is {p['pm']}" + (f" ({p['pm_phone']})" if p["pm_phone"] else "") + "."
    return None


def claude_answer(text, fs, s):
    """Claude writes the answer from the facts and FAQs; returns (answer, handoff)."""
    import anthropic
    client = anthropic.Anthropic(api_key=s["api_key"], max_retries=1, timeout=30.0)
    system = (f"You are the WhatsApp assistant of {g.company['name']}, a design and construction firm. You answer a client's question "
              "about their own project using ONLY the facts and FAQs below. Write 1-3 short sentences in the client's language (English or Hindi). "
              "Set handoff=true, with a polite holding reply, when the facts do not answer the question, when the client is unhappy or complains, "
              "asks for a change, a discount, or anything needing a decision, or mentions safety. Never invent dates, amounts or promises; "
              "never mention internal costs.\n\nFACTS (JSON):\n" + json.dumps(fs, default=str) +
              "\n\nFAQS:\n" + "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in s.get("faqs", [])))
    kwargs = dict(model=s.get("model") or DEFAULT_MODEL, max_tokens=1024, system=system,
                  output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                  messages=[{"role": "user", "content": text[:2000]}])
    try:  # server-side refusal fallback: a declined request is re-run on a fallback model in the same call
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except TypeError:  # an SDK without the fallbacks parameter
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        return None, True
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        out = json.loads(raw)
    except ValueError:
        return None, True
    return (out.get("answer") or "").strip()[:1000] or None, bool(out.get("handoff"))


def answer_for(contact, text):
    """(answer, handoff, how). Urgent words always hand over."""
    s = asettings()
    if s["mode"] == "off":
        return None, True, "off"
    from .field import is_urgent
    if is_urgent(text):
        return None, True, "urgent"
    fs = facts(contact)
    if s["mode"] == "claude" and s.get("api_key"):
        try:
            ans, hand = claude_answer(text, fs, s)
            return ans, hand or not ans, "claude"
        except Exception as e:  # noqa: BLE001 — an API outage falls back to the keyword answers
            ans = faq_answer(text, fs, s.get("faqs", []))
            return ans, not ans, f"faq (claude unavailable: {type(e).__name__})"
    ans = faq_answer(text, fs, s.get("faqs", []))
    return ans, not ans, "faq"


def reply_inbound(contact, text, routed):
    """Called after an inbound WhatsApp from a client was routed to the project thread."""
    s = asettings()
    if s["mode"] == "off" or not routed:
        return None
    contact = db.contacts.find_one({"_id": contact["_id"]}) or contact  # the webhook loads only name and phone
    ans, hand, how = answer_for(contact, text)
    out = ans if ans and not hand else (ans + "\n" + s["handoff_text"] if ans else s["handoff_text"])
    m = wa.notify_contact(contact, out, kind="assistant", ref=routed["project_id"])
    t.insert("messages", {"project_id": routed["project_id"], "project_name": (db.projects.find_one({"_id": oid(routed["project_id"])}) or {}).get("name"),
                          "contact_id": str(contact["_id"]), "contact_name": contact["name"], "channel": "portal", "via": "whatsapp", "side": "team",
                          "author": "Assistant", "user_id": None, "text": out, "files": [], "read_by_team": not hand, "read_by_contact": True,
                          "assistant": {"how": how, "handoff": hand, "sent": m}})
    if hand:
        notify.send("assistant_handoff", routed["to"], f"{contact['name']} needs a person: {text[:140]}",
                    f"/app/inbox?project={routed['project_id']}&contact={contact['_id']}", project_id=routed["project_id"], skip_self=False)
    return {"answer": out, "handoff": hand, "how": how}


@bp.post("/assistant/try")
@api("settings")
def try_it():
    """Ask the assistant as a given contact — shows what it would answer (nothing is sent)."""
    d = request.get_json(force=True) or {}
    c = t.get("contacts", d.get("contact_id") or abort(400, "Choose a client"))
    text = (d.get("text") or "").strip() or abort(400, "Type a question")
    ans, hand, how = answer_for(c, text)
    return jsonify({"answer": ans, "handoff": hand, "how": how, "facts": facts(c)})


# ============================== phone system (IVR) ==============================
DEFAULT_MENU = [{"digit": "1", "label": "Sales and new projects", "role": "sales"}, {"digit": "2", "label": "Your project", "role": "pm"},
                {"digit": "3", "label": "Accounts and payments", "role": "accounts"}]


def psettings(company=None):
    return {"provider": "off", "token": None, "greeting": None, "menu": DEFAULT_MENU, "record": True, **((company or g.company).get("phone") or {})}


@bp.get("/settings/phone")
@api("settings", write=False)
def get_phone():
    s = psettings()
    base = f"/api/webhooks/voice/{g.cid}/{s['token']}" if s.get("token") else None
    return jsonify({**{k: v for k, v in s.items() if k != "token"}, "webhook_incoming": base and base + "/incoming",
                    "webhook_status": base and base + "/status", "exotel_dial_url": base and base + "/dial"})


@bp.put("/settings/phone")
@api("settings")
def put_phone():
    d = request.get_json(force=True) or {}
    s = psettings()
    if "provider" in d:
        s["provider"] = d["provider"] if d["provider"] in ("off", "twilio", "exotel", "sandbox") else abort(400, "Provider: twilio, exotel or sandbox")
    if "greeting" in d:
        s["greeting"] = (d.get("greeting") or "").strip()[:300] or None
    if "record" in d:
        s["record"] = bool(d["record"])
    if "menu" in d:
        menu = []
        for m in d["menu"] or []:
            if str(m.get("digit")) not in "123456789" or len(str(m.get("digit"))) != 1:
                abort(400, "Each option is one digit 1-9")
            if m.get("role") not in ("owner", "pm", "sales", "accounts", "designer", "site", "procurement"):
                abort(400, f"Option {m.get('digit')}: choose a role")
            menu.append({"digit": str(m["digit"]), "label": (m.get("label") or "").strip()[:60] or abort(400, "Each option needs a label"), "role": m["role"]})
        if len({m["digit"] for m in menu}) != len(menu):
            abort(400, "Each digit once")
        s["menu"] = menu or abort(400, "Add at least one option")
    if s["provider"] != "off" and not s.get("token"):
        s["token"] = secrets.token_urlsafe(18)
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"phone": s}})
    g.company["phone"] = s
    return get_phone()


def voice_company(cid_, token):
    company = db.companies.find_one({"_id": oid(cid_), "deleted_at": None}) if len(cid_) == 24 else None
    s = psettings(company) if company else {}
    if not company or not s.get("token") or not secrets.compare_digest(token, s["token"]) or s["provider"] == "off":
        abort(404)
    g.cid, g.company, g.uid, g.role, g.user, g.hide_costs = cid_, company, None, None, {"name": "Phone"}, True
    return s


def caller(phone):
    e164 = wa.phone_e164(phone)
    if not e164:
        return None
    for c in db.contacts.find({"company_id": g.cid, "phone": {"$ne": None}}, {"name": 1, "phone": 1}):
        if wa.phone_e164(c.get("phone")) == e164:
            return c
    return None


def twiml(body):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', mimetype="text/xml")


def arg(*names):
    for n in names:
        v = request.values.get(n)
        if v:
            return v
    return None


@bp.route("/webhooks/voice/<cid_>/<token>/incoming", methods=["GET", "POST"])
def voice_incoming(cid_, token):
    s = voice_company(cid_, token)
    sid = arg("CallSid", "CallSid".lower()) or secrets.token_hex(8)
    frm = arg("From", "CallFrom")
    c = caller(frm)
    if not db.calls.find_one({"company_id": g.cid, "call_sid": sid}):
        t.insert("calls", {"call_sid": sid, "direction": "in", "from": frm, "contact_id": c and str(c["_id"]), "contact_name": c and c["name"],
                           "status": "ringing", "option": None, "routed_to": None, "duration": None, "recording_url": None, "provider": s["provider"]})
    greet = s.get("greeting") or f"Thank you for calling {g.company['name']}."
    menu = " ".join(f"For {m['label']}, press {m['digit']}." for m in s["menu"])
    action = f"/api/webhooks/voice/{cid_}/{token}/menu"
    return twiml(f'<Gather numDigits="1" action="{action}" method="POST" timeout="6"><Say>{escape(greet)} {escape(menu)}</Say></Gather>'
                 f'<Redirect method="POST">{action}?Digits=0</Redirect>')


def target_for(call, digit, s):
    opt = next((m for m in s["menu"] if m["digit"] == digit), None) or s["menu"][0]
    who = None
    if call.get("contact_id"):  # the role on the caller's own live project
        p = db.projects.find_one({"company_id": g.cid, "status": {"$in": LIVE}, "team.contact_id": call["contact_id"]}, sort=[("updated_at", -1)])
        ids = [m["user_id"] for m in (p or {}).get("team", []) if m.get("user_id")]
        if ids:
            who = db.users.find_one({"_id": {"$in": [oid(x) for x in ids]}, "role": opt["role"], "active": {"$ne": False}, "phone": {"$ne": None}})
    who = who or db.users.find_one({"company_id": g.cid, "kind": "staff", "role": opt["role"], "active": {"$ne": False}, "phone": {"$nin": [None, ""]}})
    who = who or db.users.find_one({"company_id": g.cid, "kind": "staff", "role": "owner", "active": {"$ne": False}, "phone": {"$nin": [None, ""]}})
    return opt, who


def route_call(cid_, token):
    s = voice_company(cid_, token)
    sid = arg("CallSid")
    call = db.calls.find_one({"company_id": g.cid, "call_sid": sid}) or abort(404)
    opt, who = target_for(call, arg("Digits", "digits") or "0", s)
    db.calls.update_one({"_id": call["_id"]}, {"$set": {"option": opt["label"], "role": opt["role"], "routed_to": who and str(who["_id"]),
                                                        "routed_name": who and who["name"], "status": "connecting"}})
    return s, who


@bp.route("/webhooks/voice/<cid_>/<token>/menu", methods=["POST"])
def voice_menu(cid_, token):
    s, who = route_call(cid_, token)
    status = f"/api/webhooks/voice/{cid_}/{token}/status"
    if not who:
        return twiml(f"<Say>Sorry, nobody can take your call now. We will call you back.</Say><Redirect method=\"POST\">{status}?DialCallStatus=no-answer</Redirect>")
    rec = ' record="record-from-answer"' if s.get("record") else ""
    return twiml(f'<Say>Connecting you.</Say><Dial action="{status}" method="POST" timeout="25"{rec}>{escape(wa.phone_e164(who["phone"]) or who["phone"])}</Dial>')


@bp.route("/webhooks/voice/<cid_>/<token>/dial", methods=["GET"])
def voice_dial_exotel(cid_, token):
    """Exotel's Connect applet asks which number to dial (plain text)."""
    s, who = route_call(cid_, token)
    return Response(wa.phone_e164(who["phone"]) if who else "", mimetype="text/plain")


@bp.route("/webhooks/voice/<cid_>/<token>/status", methods=["GET", "POST"])
def voice_status(cid_, token):
    voice_company(cid_, token)
    call = db.calls.find_one({"company_id": g.cid, "call_sid": arg("CallSid")})
    if not call:
        return twiml("")
    st = (arg("DialCallStatus", "DialCallStatus".lower(), "Status", "CallStatus") or "completed").lower()
    answered = st in ("completed", "answered")
    dur = arg("DialCallDuration", "DialCallDuration".lower(), "CallDuration", "Duration")
    ch = {"status": "answered" if answered else "missed", "duration": int(dur) if dur and str(dur).isdigit() else None,
          "recording_url": arg("RecordingUrl", "RecordingUrl".lower()), "ended_at": t.now()}
    db.calls.update_one({"_id": call["_id"]}, {"$set": ch})
    log_on_lead(call, ch)
    if not answered:
        who = [call["routed_to"]] if call.get("routed_to") else notify.managers()
        name = call.get("contact_name") or call.get("from")
        notify.send("call_missed", who, f"Missed call from {name}" + (f" ({call['option']})" if call.get("option") else ""), "/app/followups",
                    skip_self=False, level="warn", key=f"call-missed:{call['_id']}")
        owner = who[0] if who else None
        u = db.users.find_one({"_id": oid(owner)}) if owner else None
        if u:
            t.insert("followups", {"title": f"Call back {name}", "due": date.today().isoformat(), "priority": "high", "channel": "call",
                                   "owner_id": owner, "owner_name": u["name"], "status": "open", "notes": f"Missed call {call.get('from')}",
                                   "related": {"type": "contact", "id": call["contact_id"], "label": name, "contact_id": call["contact_id"]} if call.get("contact_id") else None})
    return twiml("<Hangup/>" if not answered else "")


def log_on_lead(call, ch):
    if not call.get("contact_id"):
        return
    lead = db.leads.find_one({"company_id": g.cid, "contact_id": call["contact_id"], "status": "open"}, sort=[("updated_at", -1)])
    if lead:
        from ..services.sales import log
        log(str(lead["_id"]), "call", f"{'Incoming' if call.get('direction', 'in') == 'in' else 'Outgoing'} call {ch.get('status')}"
            + (f", {ch['duration']} s" if ch.get("duration") else "") + (f" — {call.get('option')}" if call.get("option") else ""))


@bp.get("/calls")
@api(None)
def list_calls():
    if not (can("leads") or can("contacts") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view calls")
    q = {}
    if request.args.get("contact_id"):
        q["contact_id"] = request.args["contact_id"]
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify(serialize(t.find("calls", q, sort=[("created_at", -1)], limit=300)))


@bp.post("/calls")
@api(None)
def log_call():
    """A call made or taken on a mobile, logged by hand."""
    if not (can("leads", True) or can("contacts", True) or g.role in ("owner", "pm")):
        abort(403, "Your role cannot log calls")
    d = request.get_json(force=True) or {}
    c = t.get("contacts", d.get("contact_id") or abort(400, "Choose the contact"))
    direction = d.get("direction") if d.get("direction") in ("in", "out") else abort(400, "Direction: in or out")
    st = d.get("status") if d.get("status") in ("answered", "missed", "no_answer") else "answered"
    dur = d.get("duration")
    if dur is not None and (not isinstance(dur, int) or not 0 <= dur <= 36000):
        abort(400, "Duration in seconds")
    call = t.insert("calls", {"call_sid": None, "direction": direction, "from": c.get("phone"), "contact_id": str(c["_id"]), "contact_name": c["name"],
                              "status": st, "duration": dur, "note": (d.get("note") or "").strip()[:1000] or None, "routed_to": g.uid,
                              "routed_name": g.user["name"], "provider": "manual", "recording_url": None})
    log_on_lead(call, {"status": st, "duration": dur})
    return jsonify(serialize(call)), 201
