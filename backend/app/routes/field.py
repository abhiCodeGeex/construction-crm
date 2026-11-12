"""Phase J blocks 1-3 — WhatsApp for site workers, one-tap replies, trade sequence, QR codes and job cards (v4 §17).

* Site workers (Phase I list) get a WhatsApp opt-in and a language (English / Hindi). They are not users and are not
  counted against the plan's users.
* Job card per task: room, trade, the workers on it, the drawings, measurements, reference photos and instructions.
  It has a public link (token) a worker opens on the phone without signing in.
* Morning message: at the company's set time the worker loop sends each opted-in worker today's work (site and address,
  room, task, job card link, supervisor and phone) in their language, with three one-tap buttons:
  Material needed / Work done / Need help.
* Replies (button, text, voice note or photo) become field updates:
    material -> a purchase request (after the worker says what is needed), procurement and the supervisor are told;
    done     -> a task update waiting for the supervisor's approval; approval marks the task done;
    help     -> a question (RFI-lite) routed by the company's routing rules; the answer goes back on WhatsApp.
  Urgent words (accident, injury ...) notify the PM at once and escalate to the Owners when nobody acknowledges in time.
* Trade sequence: when a task with a room is done, the next trade in that room (by the task links, else by the company's
  trade order) is told the room is ready — on the app and on WhatsApp to its workers.
* QR code per room: a public page with the room's latest drawings (current revision) and specs (chosen selections).
"""
import secrets
import urllib.request
import json
from datetime import datetime, timedelta, date

from flask import Blueprint, request, jsonify, abort, g, has_request_context, send_from_directory, Response

from .. import tenancy as t
from ..config import Config
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, messaging as wa
from ..services.defaults import ROUTING, ROUTING_KEYWORDS, URGENT_KEYWORDS
from .lead_money import a_date

bp = Blueprint("field", __name__)
LIVE = ["planning", "active", "on_hold"]
DEFAULT_TRADES = ["Civil", "Plumbing", "Electrical", "False ceiling", "Carpentry", "Tiling", "Painting", "Fixtures", "Cleaning"]
KINDS = {"material": "Material needed", "done": "Work done", "help": "Need help"}
HI_KINDS = {"material": "सामग्री चाहिए", "done": "काम पूरा", "help": "मदद चाहिए"}
WORDS = {"material": ("material", "saman", "samaan", "सामग्री", "सामान", "cement", "sand", "tiles", "need "),
         "done": ("done", "finished", "complete", "पूरा", "हो गया", "khatam"),
         "help": ("help", "doubt", "question", "clarif", "मदद", "समझ", "sawal")}
FIELD_STATUSES = ["awaiting", "open", "pending", "approved", "rejected", "answered", "closed"]


# ============================== settings ==============================
def fsettings(company=None):
    return {"morning_on": False, "morning_time": "07:30", "utc_offset": 330, "trade_sequence": DEFAULT_TRADES,
            "escalate_minutes": 30, "routing": {}, "urgent_words": [], "digest_on": False, "digest_time": "08:00",
            **((company or g.company).get("field") or {})}


def local_now(now, company=None):
    return now + timedelta(minutes=fsettings(company)["utc_offset"])


def routing_role(topic, company=None):
    return {**ROUTING, **(fsettings(company).get("routing") or {})}.get(topic, "pm")


def urgent_words(company=None):
    return list(URGENT_KEYWORDS) + [w.lower() for w in fsettings(company).get("urgent_words") or []]


def is_urgent(text):
    low = (text or "").lower()
    return any(w in low for w in urgent_words())


def topic_of(text):
    low = (text or "").lower()
    return next((tp for words, tp in ROUTING_KEYWORDS if any(w in low for w in words)), "general")


def hhmm(v, label):
    v = (v or "").strip()
    try:
        datetime.strptime(v, "%H:%M")
    except ValueError:
        abort(400, f"{label} as HH:MM")
    return v


@bp.get("/settings/field")
@api(None)
def get_field_settings():
    if not (can("settings") or can("site") or can("projects")):
        abort(403, "Your role cannot view these settings")
    return jsonify({**fsettings(), "kinds": KINDS, "routing_defaults": ROUTING, "urgent_defaults": list(URGENT_KEYWORDS),
                    "roles": ["owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator"]})


@bp.put("/settings/field")
@api("settings")
def put_field_settings():
    d = request.get_json(force=True) or {}
    s = fsettings()
    for k in ("morning_on", "digest_on"):
        if k in d:
            s[k] = bool(d[k])
    for k, label in (("morning_time", "Morning message time"), ("digest_time", "PM digest time")):
        if k in d:
            s[k] = hhmm(d[k], label)
    if "utc_offset" in d:
        v = d["utc_offset"]
        s["utc_offset"] = v if isinstance(v, int) and -720 <= v <= 840 else abort(400, "Time zone offset in minutes (-720 to 840)")
    if "escalate_minutes" in d:
        v = d["escalate_minutes"]
        s["escalate_minutes"] = v if isinstance(v, int) and 5 <= v <= 1440 else abort(400, "Escalate after 5-1440 minutes")
    if "trade_sequence" in d:
        seq = [str(x).strip()[:40] for x in d["trade_sequence"] or [] if str(x).strip()]
        s["trade_sequence"] = list(dict.fromkeys(seq)) or abort(400, "Add at least one trade")
    if "routing" in d:
        roles = {"owner", "pm", "site", "designer", "sales", "accounts", "procurement", "estimator"}
        rt = {}
        for topic, role in (d["routing"] or {}).items():
            if role not in roles:
                abort(400, f"Routing for {topic}: unknown role {role}")
            rt[str(topic)[:40]] = role
        s["routing"] = rt
    if "urgent_words" in d:
        s["urgent_words"] = list(dict.fromkeys(str(w).strip().lower()[:30] for w in d["urgent_words"] or [] if str(w).strip()))[:50]
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"field": s}})
    g.company["field"] = s
    t.audit("update", "companies", g.company["_id"], note="Field / WhatsApp worker settings changed")
    return get_field_settings()


# ============================== helpers ==============================
def base_url(company=None):
    company = company or g.company
    url = (company.get("email_settings") or {}).get("app_url")
    if not url and has_request_context():
        url = request.host_url
    return (url or "").rstrip("/")


def project(pid, write=False):
    from .site_plus import site_access
    return site_access(pid, write)


def task_of(p, tid):
    for s in p.get("stages", []):
        for tk in s.get("tasks", []):
            if tk["id"] == tid:
                return s, tk
    abort(404, "Task not found")


def supervisor(p):
    """The Site Supervisor on the team (else the PM): name and phone for the worker."""
    ids = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("kind") != "external"]
    users = list(db.users.find({"_id": {"$in": [oid(i) for i in ids]}, "active": {"$ne": False}}, {"name": 1, "phone": 1, "role": 1}))
    u = next((x for x in users if x["role"] == "site"), None) or next((x for x in users if str(x["_id"]) in ev.managers(p)), None)
    return {"id": str(u["_id"]), "name": u["name"], "phone": u.get("phone")} if u else None


def site_people(p):
    """Who hears about field updates: the site supervisors on the team plus the managers."""
    ids = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("kind") != "external"]
    sups = [str(u["_id"]) for u in db.users.find({"_id": {"$in": [oid(i) for i in ids]}, "role": "site", "active": {"$ne": False}}, {"_id": 1})]
    return list(dict.fromkeys(sups + ev.managers(p)))


def worker_contact(w):
    """A site worker in the shape messaging.send expects."""
    return {"id": f"w:{w['_id']}", "name": w["name"], "phone": w.get("phone"), "whatsapp_opt_in": w.get("whatsapp_opt_in"),
            "whatsapp_opt_out": w.get("whatsapp_opt_out")}


def buttons_for(lang):
    names = HI_KINDS if lang == "hi" else KINDS
    return [(k, names[k]) for k in ("material", "done", "help")]


def say(w, en, hi, kind, ref=None, buttons=False, extra=None):
    """Send a message to a worker in their language; never raises (a quota problem must not stop the action)."""
    lang = w.get("language") or "en"
    try:
        return wa.send(worker_contact(w), hi if lang == "hi" else en, kind=kind, ref=ref,
                       buttons=buttons_for(lang) if buttons else None, extra={"worker_id": str(w["_id"]), **(extra or {})})
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": getattr(e, "description", str(e))}


# ============================== job cards ==============================
def card_of(pid, tid, create=False):
    c = db.job_cards.find_one({"company_id": g.cid, "project_id": pid, "task_id": tid})
    if not c and create:
        c = t.insert("job_cards", {"project_id": pid, "task_id": tid, "room": None, "trade": None, "worker_ids": [], "workers": [],
                                   "document_ids": [], "measurements": [], "photos": [], "instructions": None,
                                   "token": secrets.token_urlsafe(18)})
    return c


def drawings(pid, ids=None, room=None):
    q = {"company_id": g.cid, "project_id": pid, "deleted_at": None}
    if ids is not None:
        q["_id"] = {"$in": [oid(i) for i in ids if len(i) == 24]}
    elif room:
        q["room"] = room
    else:
        return []
    out = []
    for d in db.documents.find(q).sort("name", 1):
        cur = (d.get("versions") or [None])[-1]
        if cur:
            out.append({"id": str(d["_id"]), "name": d["name"], "number": d.get("number"), "kind": d.get("kind"), "rev": cur.get("rev"),
                        "status": cur.get("status"), "file_key": cur["file_key"], "file_name": cur.get("name") or d["name"]})
    return out


def card_view(p, c, tk=None, public_token=None):
    pid = str(p["_id"])
    if tk is None:
        tk = next((x for s in p.get("stages", []) for x in s.get("tasks", []) if x["id"] == c["task_id"]), {}) or {}
    files = lambda key: f"/api/public/f/{public_token}/{key}" if public_token else f"/api/files/{key}"
    docs = drawings(pid, c.get("document_ids") or [])
    return {"id": str(c["_id"]), "project_id": pid, "project_name": p["name"], "address": p.get("site_address") or p.get("address"),
            "task_id": c["task_id"], "task": tk.get("title"), "start": tk.get("start"), "end": tk.get("end"), "status": tk.get("status"),
            "room": c.get("room"), "trade": c.get("trade"), "workers": c.get("workers", []), "worker_ids": c.get("worker_ids", []),
            "instructions": c.get("instructions"), "measurements": c.get("measurements", []),
            "photos": [{**ph, "url": files(ph["key"])} for ph in c.get("photos", [])],
            "drawings": [{**d, "url": files(d["file_key"])} for d in docs], "document_ids": c.get("document_ids", []),
            "supervisor": supervisor(p), "link": f"{base_url()}/j/{c['token']}", "token": c["token"]}


@bp.get("/projects/<pid>/tasks/<tid>/job")
@api(None)
def get_job(pid, tid):
    p = project(pid)
    _, tk = task_of(p, tid)
    c = card_of(pid, tid, create=True)
    return jsonify(card_view(p, c, tk))


@bp.put("/projects/<pid>/tasks/<tid>/job")
@api(None)
def put_job(pid, tid):
    p = project(pid, write=True)
    _, tk = task_of(p, tid)
    c = card_of(pid, tid, create=True)
    d = request.get_json(force=True) or {}
    ch = {}
    for k, n in (("room", 80), ("trade", 40)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or None
    if "instructions" in d:
        ch["instructions"] = (d.get("instructions") or "").strip()[:2000] or None
    if "worker_ids" in d:
        ws = list(db.site_workers.find({"company_id": g.cid, "_id": {"$in": [oid(x) for x in d["worker_ids"] or [] if len(x) == 24]}}))
        if len(ws) != len(set(d["worker_ids"] or [])):
            abort(400, "A worker on the job card was not found")
        ch["worker_ids"] = [str(w["_id"]) for w in ws]
        ch["workers"] = [{"id": str(w["_id"]), "name": w["name"], "trade": w.get("trade"), "phone": w.get("phone")} for w in ws]
    if "document_ids" in d:
        ids = list(dict.fromkeys(d["document_ids"] or []))
        found = drawings(pid, ids)
        if len(found) != len(ids):
            abort(400, "A drawing on the job card is not on this project")
        ch["document_ids"] = ids
    if "measurements" in d:
        rows = []
        for m in d["measurements"] or []:
            label = (m.get("label") or "").strip()[:80]
            if label:
                rows.append({"label": label, "value": (str(m.get("value") or "")).strip()[:80]})
        ch["measurements"] = rows[:40]
    if "photos" in d:
        from .site_plus import files_of
        ch["photos"] = files_of(d["photos"], limit=12)
    c = t.update("job_cards", str(c["_id"]), ch)
    return jsonify(card_view(p, c, tk))


@bp.post("/projects/<pid>/tasks/<tid>/job/send")
@api(None)
def send_job(pid, tid):
    """Send the job card link to its workers on WhatsApp now."""
    p = project(pid, write=True)
    _, tk = task_of(p, tid)
    c = card_of(pid, tid) or abort(400, "Fill the job card first")
    if not c.get("worker_ids"):
        abort(400, "Add the workers to the job card first")
    out = []
    for w in db.site_workers.find({"company_id": g.cid, "_id": {"$in": [oid(x) for x in c["worker_ids"]]}}):
        link = f"{base_url()}/j/{c['token']}"
        m = say(w, f"Job card — {p['name']}: {tk['title']}{' (' + c['room'] + ')' if c.get('room') else ''}. Drawings and measurements: {link}",
                f"जॉब कार्ड — {p['name']}: {tk['title']}{' (' + c['room'] + ')' if c.get('room') else ''}। ड्रॉइंग और नाप: {link}",
                "worker_job", ref=str(c["_id"]), buttons=True, extra={"project_id": pid, "task_ids": [tid]})
        out.append({"worker": w["name"], "status": m.get("status"), "error": m.get("error")})
    return jsonify(out)


@bp.get("/projects/<pid>/job-cards")
@api(None)
def list_jobs(pid):
    p = project(pid)
    tasks = {tk["id"]: tk for s in p.get("stages", []) for tk in s.get("tasks", [])}
    rows = [card_view(p, c, tasks.get(c["task_id"])) for c in db.job_cards.find({"company_id": g.cid, "project_id": pid}) if c["task_id"] in tasks]
    return jsonify(rows)


# ============================== public pages (no sign-in) ==============================
def public_company(cid):
    company = db.companies.find_one({"_id": oid(cid), "deleted_at": None})
    if not company:
        abort(404)
    g.cid, g.company, g.uid, g.role, g.user, g.hide_costs = cid, company, None, None, {"name": "Public"}, True
    return company


def by_token(token):
    c = db.job_cards.find_one({"token": token}) if token else None
    if c:
        return "job", c
    r = db.room_codes.find_one({"token": token}) if token else None
    if r:
        return "room", r
    abort(404, "This link is not valid")


@bp.get("/public/job/<token>")
def public_job(token):
    kind, c = by_token(token)
    if kind != "job":
        abort(404, "This link is not valid")
    company = public_company(c["company_id"])
    p = db.projects.find_one({"_id": oid(c["project_id"]), "company_id": c["company_id"]}) or abort(404)
    return jsonify({**card_view(p, c, public_token=token), "company": company["name"]})


def room_view(p, room, token=None):
    pid = str(p["_id"])
    files = lambda key: f"/api/public/f/{token}/{key}" if token else f"/api/files/{key}"
    specs = []
    for s in db.selections.find({"company_id": g.cid, "project_id": pid, "room": room}).sort("item", 1):
        opt = next((o for o in s.get("options", []) if o.get("id") == s.get("chosen_option_id")), None)
        specs.append({"item": s["item"], "status": s.get("status"), "choice": opt and opt.get("name"),
                      "spec": opt and (opt.get("spec") or opt.get("description")), "brand": opt and opt.get("brand")})
    tasks = {tk["id"]: tk for st in p.get("stages", []) for tk in st.get("tasks", [])}
    jobs = [{"task": tasks[c["task_id"]]["title"], "trade": c.get("trade"), "status": tasks[c["task_id"]].get("status"),
             "token": c["token"]} for c in db.job_cards.find({"company_id": g.cid, "project_id": pid, "room": room}) if c["task_id"] in tasks]
    return {"project_name": p["name"], "room": room, "address": p.get("site_address") or p.get("address"),
            "drawings": [{**d, "url": files(d["file_key"])} for d in drawings(pid, room=room)], "specs": specs, "jobs": jobs}


@bp.get("/public/room/<token>")
def public_room(token):
    kind, r = by_token(token)
    if kind != "room":
        abort(404, "This link is not valid")
    company = public_company(r["company_id"])
    p = db.projects.find_one({"_id": oid(r["project_id"]), "company_id": r["company_id"]}) or abort(404)
    return jsonify({**room_view(p, r["room"], token), "company": company["name"]})


@bp.get("/public/f/<token>/<key>")
def public_file(token, key):
    """A file shown on a job card or room page: only the files that page lists."""
    kind, c = by_token(token)
    public_company(c["company_id"])
    p = db.projects.find_one({"_id": oid(c["project_id"]), "company_id": c["company_id"]}) or abort(404)
    if kind == "job":
        allowed = {d["file_key"] for d in drawings(c["project_id"], c.get("document_ids") or [])} | {ph["key"] for ph in c.get("photos", [])}
    else:
        allowed = {d["file_key"] for d in drawings(c["project_id"], room=c["room"])}
    if key not in allowed or not key.startswith(f"{c['company_id']}_"):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, key)


# ============================== rooms and QR codes ==============================
def rooms_of(pid):
    names = set()
    for col in ("job_cards", "documents", "selections"):
        names.update(x for x in db[col].distinct("room", {"company_id": g.cid, "project_id": pid}) if x)
    return sorted(names)


@bp.get("/projects/<pid>/rooms")
@api(None)
def list_rooms(pid):
    p = project(pid)
    codes = {r["room"]: r for r in db.room_codes.find({"company_id": g.cid, "project_id": pid})}
    out = []
    for room in sorted(set(rooms_of(pid)) | set(codes)):
        v = room_view(p, room)
        r = codes.get(room)
        out.append({"room": room, "drawings": len(v["drawings"]), "specs": len(v["specs"]), "jobs": len(v["jobs"]),
                    "token": r and r["token"], "link": r and f"{base_url()}/r/{r['token']}"})
    return jsonify(out)


@bp.post("/projects/<pid>/rooms/qr")
@api(None)
def room_qr(pid):
    project(pid, write=True)
    room = ((request.get_json(force=True) or {}).get("room") or "").strip()[:80] or abort(400, "Which room?")
    r = db.room_codes.find_one({"company_id": g.cid, "project_id": pid, "room": room})
    if not r:
        r = t.insert("room_codes", {"project_id": pid, "room": room, "token": secrets.token_urlsafe(18)})
    return jsonify({"room": room, "token": r["token"], "link": f"{base_url()}/r/{r['token']}"}), 201


@bp.get("/qr.svg")
def qr_svg():
    """An SVG QR code for a link of this app (job card or room page); used by the print views."""
    import segno
    data = (request.args.get("data") or "")[:400]
    if not data:
        abort(400, "data is required")
    buf = __import__("io").BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=6, border=2)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


# ============================== morning work message ==============================
def todays_work(day, company=None):
    """Per opted-in-or-not worker: today's open tasks on live projects where the worker is on the job card."""
    iso = day.isoformat() if isinstance(day, date) else day
    by_worker = {}
    for p in db.projects.find({"company_id": g.cid, "status": {"$in": LIVE}, "deleted_at": None}):
        pid = str(p["_id"])
        tasks = {tk["id"]: tk for s in p.get("stages", []) for tk in s.get("tasks", [])}
        sup = None
        for c in db.job_cards.find({"company_id": g.cid, "project_id": pid, "worker_ids.0": {"$exists": True}}):
            tk = tasks.get(c["task_id"])
            if not tk or tk.get("status") == "done" or not tk.get("start") or not tk.get("end") or not tk["start"] <= iso <= tk["end"]:
                continue
            sup = sup or supervisor(p) or {}
            for wid in c["worker_ids"]:
                by_worker.setdefault(wid, []).append({"project": p, "card": c, "task": tk, "sup": sup})
    out = []
    for w in db.site_workers.find({"company_id": g.cid, "_id": {"$in": [oid(x) for x in by_worker]}, "active": {"$ne": False}}):
        out.append((w, by_worker[str(w["_id"])]))
    return out


def morning_text(w, jobs):
    base = base_url()
    hi = (w.get("language") or "en") == "hi"
    lines = [f"सुप्रभात {w['name']}। आज का काम:" if hi else f"Good morning {w['name']}. Today's work:"]
    seen_sup = []
    for j in jobs:
        p, c, tk = j["project"], j["card"], j["task"]
        addr = p.get("site_address") or p.get("address")
        lines.append(f"• {p['name']}{' — ' + addr if addr else ''}")
        lines.append(f"  {c.get('room') + ': ' if c.get('room') else ''}{tk['title']}{' (' + c['trade'] + ')' if c.get('trade') else ''}")
        lines.append(f"  {'जॉब कार्ड / ड्रॉइंग' if hi else 'Job card / drawing'}: {base}/j/{c['token']}")
        if j["sup"].get("name") and j["sup"]["name"] not in seen_sup:
            seen_sup.append(j["sup"]["name"])
            lines.append(f"  {'सुपरवाइज़र' if hi else 'Supervisor'}: {j['sup']['name']}{' ' + j['sup']['phone'] if j['sup'].get('phone') else ''}")
    lines.append("सामग्री चाहिए, काम पूरा या मदद — नीचे बटन दबाएँ या आवाज़ संदेश भेजें।" if hi else
                 "Tap a button below (or send a voice note) when you need material, finish, or need help.")
    return "\n".join(lines)


def send_morning(day, only=None):
    sent = []
    for w, jobs in todays_work(day):
        if only and str(w["_id"]) not in only:
            continue
        text = morning_text(w, jobs)
        lang = w.get("language") or "en"
        try:
            m = wa.send(worker_contact(w), text, kind="worker_morning", ref=day.isoformat(), buttons=buttons_for(lang),
                        extra={"worker_id": str(w["_id"]), "project_id": str(jobs[0]["project"]["_id"]),
                               "task_ids": [j["task"]["id"] for j in jobs]})
        except Exception as e:  # noqa: BLE001 — quota used up: stop, the rest are logged as not sent
            m = {"status": "failed", "error": getattr(e, "description", str(e))}
        sent.append({"worker_id": str(w["_id"]), "worker": w["name"], "tasks": len(jobs), "status": m.get("status"), "error": m.get("error")})
    return sent


@bp.get("/worker-messages/preview")
@api(None)
def preview_morning():
    if not (can("site") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view worker messages")
    day = a_date(request.args.get("day") or date.today().isoformat(), "Day")
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return jsonify([{"worker_id": str(w["_id"]), "worker": w["name"], "language": w.get("language") or "en",
                     "whatsapp": wa.opted_in(w) and bool(wa.phone_e164(w.get("phone"))), "tasks": len(jobs), "text": morning_text(w, jobs)}
                    for w, jobs in todays_work(day)])


@bp.post("/worker-messages/send")
@api("site")
def send_morning_now():
    d = request.get_json(force=True) or {}
    day = a_date(d.get("day") or date.today().isoformat(), "Day")
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return jsonify(send_morning(day, d.get("worker_ids")))


def check_morning(now):
    s = fsettings()
    if not s["morning_on"]:
        return
    local = local_now(now)
    day = local.date()
    if local.strftime("%H:%M") < s["morning_time"] or (g.company.get("field_runs") or {}).get("morning") == day.isoformat():
        return
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"field_runs.morning": day.isoformat()}})
    g.company.setdefault("field_runs", {})["morning"] = day.isoformat()
    send_morning(day)


# ============================== worker replies ==============================
def find_worker(cid, phone):
    for w in db.site_workers.find({"company_id": cid, "phone": {"$ne": None}}):
        if wa.phone_e164(w.get("phone")) == phone:
            return w
    return None


def last_context(w):
    """The project and tasks of the last work message this worker got (36 h)."""
    since = t.now() - timedelta(hours=36)
    m = db.messages.find_one({"company_id": g.cid, "worker_id": str(w["_id"]), "direction": {"$in": ["out", "logged"]},
                              "kind": {"$in": ["worker_morning", "worker_job", "worker_ready"]}, "created_at": {"$gte": since}},
                             sort=[("created_at", -1)])
    if m and m.get("project_id"):
        return m["project_id"], m.get("task_ids") or []
    c = db.job_cards.find_one({"company_id": g.cid, "worker_ids": str(w["_id"])}, sort=[("updated_at", -1)])
    return (c["project_id"], [c["task_id"]]) if c else (None, [])


def kind_of(msg, text):
    if msg.get("type") == "interactive":
        bid = ((msg.get("interactive") or {}).get("button_reply") or {}).get("id")
        if bid in KINDS:
            return bid, True
    if msg.get("type") == "button":
        payload = ((msg.get("button") or {}).get("payload") or "").lower()
        if payload in KINDS:
            return payload, True
    low = (text or "").lower()
    for k in ("done", "material", "help"):
        if any(wd in low for wd in WORDS[k]):
            return k, False
    return None, False


def media_of(msg):
    for typ in ("audio", "voice", "image", "video", "document"):
        if msg.get(typ):
            return {"type": "voice" if typ in ("audio", "voice") else typ, "media_id": msg[typ].get("id"),
                    "mime": msg[typ].get("mime_type"), "caption": msg[typ].get("caption")}
    return None


def fetch_media(media):
    """WhatsApp Cloud media: look up the URL and keep the file with the company's uploads (best effort)."""
    s = wa.settings()
    if s.get("provider") != "whatsapp_cloud" or not media.get("media_id"):
        return None
    try:
        req = urllib.request.Request(f"{wa.GRAPH}/{media['media_id']}", headers={"Authorization": f"Bearer {s['access_token']}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            url = json.loads(r.read())["url"]
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {s['access_token']}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(16 * 1024 * 1024)
        ext = {"voice": "ogg", "image": "jpg", "video": "mp4"}.get(media["type"], "bin")
        key = f"{g.cid}_{secrets.token_hex(12)}.{ext}"
        import os
        with open(os.path.join(Config.UPLOAD_DIR, key), "wb") as f:
            f.write(data)
        db.files.insert_one({"company_id": g.cid, "key": key, "name": f"whatsapp-{media['type']}.{ext}", "size": len(data),
                             "uploaded_by": None, "at": t.now()})
        return key
    except Exception:  # noqa: BLE001 — the record keeps the media id; staff can still hear it on the phone
        return None


def field_people(p, kind, topic):
    role = routing_role({"material": "material_needed", "help": "need_clarification"}.get(kind, topic))
    staff = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("kind") != "external"]
    roles = {str(u["_id"]): u["role"] for u in db.users.find({"_id": {"$in": [oid(x) for x in staff]}}, {"role": 1})}
    target = [u for u in staff if roles.get(u) == role] or (notify.role_users(role) if role in ("accounts", "procurement") else [])
    if kind == "done":
        target = []
    return list(dict.fromkeys(target + site_people(p)))


def worker_inbound(company, w, msg, text):
    """One inbound WhatsApp message from a site worker. Returns the field update it made or added to."""
    kind, tapped = kind_of(msg, text)
    media = media_of(msg)
    if media:
        media["key"] = fetch_media(media)
        text = text or media.get("caption") or ""
    pid, task_ids = last_context(w)
    p = db.projects.find_one({"_id": oid(pid), "company_id": g.cid}) if pid else None
    if not p:
        say(w, "We could not find your site. Please call your supervisor.", "आपकी साइट नहीं मिली। कृपया सुपरवाइज़र को फ़ोन करें।", "worker_reply")
        return None
    pid = str(p["_id"])
    tasks = {tk["id"]: tk for s in p.get("stages", []) for tk in s.get("tasks", [])}
    tid = next((x for x in task_ids if x in tasks and tasks[x].get("status") != "done"), None) or next((x for x in task_ids if x in tasks), None)
    urgent = is_urgent(text)
    # a detail after a button (text / voice / photo within 30 min) goes to that record
    waiting = db.field_updates.find_one({"company_id": g.cid, "worker_id": str(w["_id"]), "status": "awaiting",
                                         "created_at": {"$gte": t.now() - timedelta(minutes=30)}}, sort=[("created_at", -1)])
    if waiting and not tapped:
        return complete(p, w, waiting, text, media, urgent)
    if kind is None:
        kind = "other"
    rec = t.insert("field_updates", {
        "project_id": pid, "project_name": p["name"], "task_id": tid, "task_title": tid and tasks[tid]["title"],
        "worker_id": str(w["_id"]), "worker_name": w["name"], "worker_phone": w.get("phone"), "kind": kind,
        "text": (text or "")[:2000] or None, "media": [media] if media else [], "topic": topic_of(text), "urgent": urgent,
        "status": "awaiting", "pr_id": None, "answer": None, "escalate_at": None, "escalated": False, "acknowledged_at": None})
    if not (tapped and kind in ("material", "help") and not text and not media):
        return complete(p, w, rec, None, None, urgent, fresh=True)
    ask ={"material": ("What material and how much? Send text, a voice note or a photo.", "कौन सी सामग्री और कितनी? लिखें, आवाज़ संदेश या फ़ोटो भेजें।"),
           "help": ("What is the question? Send text, a voice note or a photo.", "क्या सवाल है? लिखें, आवाज़ संदेश या फ़ोटो भेजें।")}[kind]
    say(w, *ask, "worker_reply", ref=str(rec["_id"]))
    return rec


def complete(p, w, rec, text, media, urgent, fresh=False):
    """The record has its detail: make the CRM record and tell the right people."""
    ch = {}
    if not fresh:
        if text:
            ch["text"] = ((rec.get("text") or "") + "\n" + text).strip()[:2000]
        if media:
            ch["media"] = rec.get("media", []) + [media]
        urgent = urgent or rec.get("urgent")
        ch["topic"] = topic_of(ch.get("text") or rec.get("text"))
    ch["urgent"] = urgent
    kind = rec["kind"]
    full = {**rec, **ch}
    what = full.get("text") or ("voice note" if any(m["type"] == "voice" for m in full.get("media", [])) else "photo" if full.get("media") else "")
    pid = str(p["_id"])
    if kind == "material":
        from .procurement import new_request
        st = next((s for s in p.get("stages", []) for tk in s.get("tasks", []) if tk["id"] == rec.get("task_id")), None) or (p.get("stages") or [None])[0]
        if st:
            g.user = {"name": f"{w['name']} (WhatsApp)"}
            pr = new_request(p, {"stage_id": st["id"], "location": "site", "note": f"From {w['name']} on WhatsApp: {what}"[:500],
                                 "lines": [{"description": (full.get("text") or "Material (see voice note / photo)")[:200], "qty": 1, "unit": "lot"}]},
                             "whatsapp")
            ch.update(pr_id=str(pr["_id"]), pr_number=pr["number"])
        ch["status"] = "open"
        ack = (f"Noted. Request {ch.get('pr_number', '')} sent to the office.", f"नोट किया। अनुरोध {ch.get('pr_number', '')} ऑफिस को भेजा गया।")
    elif kind == "done":
        ch["status"] = "pending"
        ack = ("Thanks. The supervisor will check and confirm.", "धन्यवाद। सुपरवाइज़र जाँच कर पुष्टि करेंगे।")
    elif kind == "help":
        ch["status"] = "open"
        ack = ("Your question is with the team. You will get the answer here.", "आपका सवाल टीम के पास है। जवाब यहीं मिलेगा।")
    else:
        ch["status"] = "open"
        ack = ("Message received.", "संदेश मिल गया।")
    if urgent:
        ch["escalate_at"] = t.now() + timedelta(minutes=fsettings()["escalate_minutes"])
    rec = t.update("field_updates", str(rec["_id"]), ch)
    label = {"material": "needs material", "done": "says work is done", "help": "needs help", "other": "wrote"}[kind]
    text_ = f"{'URGENT · ' if urgent else ''}{w['name']} {label} — {p['name']}{': ' + rec['task_title'] if rec.get('task_title') else ''}: {what[:140]}"
    who = field_people(p, kind, rec.get("topic"))
    if urgent:
        who = list(dict.fromkeys(who + ev.managers(p)))
    notify.send("field_update", who, text_, f"/app/projects/{pid}?tab=field", project_id=pid, skip_self=False, level="warn" if urgent else "info")
    ev.log(pid, "field", text_)
    say(w, *ack, "worker_reply", ref=str(rec["_id"]))
    return rec


# ============================== field updates (staff) ==============================
def load_update(fid, write=True):
    r = t.get("field_updates", fid)
    p = project(r["project_id"], write=write)
    return r, p


@bp.get("/field-updates")
@api(None)
def list_updates():
    if not (can("site") or can("procurement") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view field updates")
    q = {}
    if request.args.get("project_id"):
        project(request.args["project_id"])
        q["project_id"] = request.args["project_id"]
    elif g.role not in ("owner", "procurement"):
        q["project_id"] = {"$in": [str(x["_id"]) for x in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]}
    if request.args.get("status"):
        q["status"] = {"$in": request.args["status"].split(",")}
    if request.args.get("kind"):
        q["kind"] = request.args["kind"]
    rows = serialize(t.find("field_updates", q, sort=[("created_at", -1)], limit=300))
    for r in rows:
        for m in r.get("media", []):
            m["url"] = f"/api/files/{m['key']}" if m.get("key") else None
    return jsonify(rows)


def done_task(p, tid, by_name):
    from .projects import find_task, check_checklist, check_predecessors, save_stages
    stage, task = find_task(p, tid)
    if task["status"] == "done":
        return task
    before = task["status"]
    task.update(status="done", progress=100, waiting_on=None)
    try:
        check_checklist(task)
        check_predecessors(p, task)
    except Exception:
        task["status"] = before
        raise
    save_stages(str(p["_id"]), p)
    ev.log(str(p["_id"]), "task", f"Task done (site worker update approved by {by_name}): {task['title']}", task_id=tid)
    after_task_done(p, task)
    return task


@bp.post("/field-updates/<fid>/approve")
@api("site")
def approve_update(fid):
    r, p = load_update(fid)
    if r["kind"] != "done" or r["status"] != "pending":
        abort(409, "Only a pending 'work done' update can be approved")
    if r.get("task_id"):
        done_task(p, r["task_id"], g.user["name"])
    r = t.update("field_updates", fid, {"status": "approved", "decided_by": g.user["name"], "decided_at": t.now(), "acknowledged_at": t.now()})
    w = db.site_workers.find_one({"_id": oid(r["worker_id"])})
    if w:
        say(w, f"Approved: {r.get('task_title') or 'your work'}. Thank you.", f"स्वीकृत: {r.get('task_title') or 'आपका काम'}। धन्यवाद।", "worker_reply", ref=fid)
    return jsonify(serialize(r))


@bp.post("/field-updates/<fid>/reject")
@api("site")
def reject_update(fid):
    r, p = load_update(fid)
    if r["kind"] != "done" or r["status"] != "pending":
        abort(409, "Only a pending 'work done' update can be sent back")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:500] or abort(400, "Say what is still to do")
    r = t.update("field_updates", fid, {"status": "rejected", "reason": reason, "decided_by": g.user["name"], "decided_at": t.now(),
                                        "acknowledged_at": t.now()})
    w = db.site_workers.find_one({"_id": oid(r["worker_id"])})
    if w:
        say(w, f"Not done yet — {reason}", f"अभी पूरा नहीं — {reason}", "worker_reply", ref=fid, buttons=True,
            extra={"project_id": r["project_id"], "task_ids": [r["task_id"]] if r.get("task_id") else []})
    return jsonify(serialize(r))


@bp.post("/field-updates/<fid>/answer")
@api(None)
def answer_update(fid):
    r, p = load_update(fid, write=False)
    from .projects import member
    if not ((can("site", True) or can("projects", True) or can("documents", True)) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot answer field questions")
    if r["status"] in ("answered", "closed", "approved", "rejected") and r["kind"] != "other":
        abort(409, "This update is already settled")
    text = ((request.get_json(force=True) or {}).get("text") or "").strip()[:1000] or abort(400, "Write the answer")
    r = t.update("field_updates", fid, {"status": "answered", "answer": text, "answered_by": g.user["name"], "answered_at": t.now(),
                                        "acknowledged_at": r.get("acknowledged_at") or t.now()})
    w = db.site_workers.find_one({"_id": oid(r["worker_id"])})
    m = say(w, f"Answer from {g.user['name']}: {text}", f"{g.user['name']} का जवाब: {text}", "worker_reply", ref=fid) if w else {}
    return jsonify({**serialize(r), "sent": m.get("status")})


@bp.post("/field-updates/<fid>/ack")
@api(None)
def ack_update(fid):
    r, p = load_update(fid, write=False)
    if r.get("acknowledged_at"):
        return jsonify(serialize(r))
    return jsonify(serialize(t.update("field_updates", fid, {"acknowledged_at": t.now(), "acknowledged_by": g.user["name"]})))


@bp.post("/field-updates/<fid>/close")
@api(None)
def close_update(fid):
    r, p = load_update(fid, write=False)
    if not (can("site", True) or can("procurement", True)):
        abort(403, "Your role cannot close field updates")
    return jsonify(serialize(t.update("field_updates", fid, {"status": "closed", "closed_by": g.user["name"], "closed_at": t.now(),
                                                             "acknowledged_at": r.get("acknowledged_at") or t.now()})))


def check_escalations(now):
    """Urgent field updates nobody acknowledged in time go to the Owners (once)."""
    for r in db.field_updates.find({"company_id": g.cid, "urgent": True, "escalated": False, "acknowledged_at": None,
                                    "escalate_at": {"$ne": None, "$lte": now}}):
        db.field_updates.update_one({"_id": r["_id"]}, {"$set": {"escalated": True, "escalated_at": now}})
        notify.send("field_escalated", ev.owners(), f"Escalated — nobody answered {r['worker_name']} on {r['project_name']}: {(r.get('text') or '')[:140]}",
                    f"/app/projects/{r['project_id']}?tab=field", project_id=r["project_id"], skip_self=False, level="warn",
                    key=f"field-esc:{r['_id']}")


# ============================== trade sequence ==============================
def after_task_done(p, task):
    """The next trade in the room hears that it is ready."""
    pid = str(p["_id"])
    card = db.job_cards.find_one({"company_id": g.cid, "project_id": pid, "task_id": task["id"]})
    tasks = {tk["id"]: tk for s in p.get("stages", []) for tk in s.get("tasks", [])}
    nxt = [tk for tk in tasks.values() if task["id"] in (tk.get("depends_on") or []) and tk.get("status") != "done"]
    if not nxt and card and card.get("room") and card.get("trade"):
        seq = [x.lower() for x in fsettings()["trade_sequence"]]
        cards = [c for c in db.job_cards.find({"company_id": g.cid, "project_id": pid, "room": card["room"], "trade": {"$ne": None}})
                 if c["task_id"] in tasks and tasks[c["task_id"]].get("status") != "done" and c["task_id"] != task["id"]]
        here = seq.index(card["trade"].lower()) if card["trade"].lower() in seq else None
        later = [c for c in cards if c["trade"].lower() in seq and (here is None or seq.index(c["trade"].lower()) > here)]
        if later:
            first = min(seq.index(c["trade"].lower()) for c in later)
            nxt = [tasks[c["task_id"]] for c in later if seq.index(c["trade"].lower()) == first]
    told = []
    for tk in nxt:
        c = db.job_cards.find_one({"company_id": g.cid, "project_id": pid, "task_id": tk["id"]}) or {}
        room = c.get("room") or (card or {}).get("room")
        msg = f"Ready for you: {tk['title']}{' in ' + room if room else ''} — {task['title']} is done ({p['name']})"
        notify.send("trade_ready", list(dict.fromkeys([tk.get("assignee_id")] + site_people(p))), msg, f"/app/projects/{pid}?tab=plan",
                    project_id=pid, skip_self=False, key=f"trade-ready:{pid}:{tk['id']}:{task['id']}")
        for w in db.site_workers.find({"company_id": g.cid, "_id": {"$in": [oid(x) for x in c.get("worker_ids", [])]}}):
            say(w, f"{room or p['name']} is ready for you: {tk['title']}. Job card: {base_url()}/j/{c['token']}",
                f"{room or p['name']} आपके लिए तैयार है: {tk['title']}। जॉब कार्ड: {base_url()}/j/{c['token']}",
                "worker_ready", ref=tk["id"], buttons=True, extra={"project_id": pid, "task_ids": [tk["id"]]})
        ev.log(pid, "field", msg, task_id=tk["id"])
        told.append(tk["id"])
    return told
