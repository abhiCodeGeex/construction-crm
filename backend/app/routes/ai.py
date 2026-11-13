"""Phase L block 3 — AI helpers (v4 §15): follow-up drafts, a BOQ from drawings, progress summaries from site photos.

All three use Claude (Anthropic API) with the company's own key (Settings → AI; the WhatsApp assistant's key is used
when no separate key is set). Nothing is sent or saved without a person: each helper returns a draft that someone
reads, changes and then sends / adds / shares.
  * Follow-up draft (a lead): a WhatsApp or email message from the lead's facts — stage, what was last said and done,
    the proposal, the next follow-up. With AI off, a plain template draft is offered instead.
  * BOQ from drawings (an estimate): Claude reads up to five drawings (image or PDF) and lists the work with quantities
    and units; each line is matched to the company's rate library where a name fits. The estimator ticks the lines
    to add to the estimate (a draft estimate only), and checks every quantity — the screen says so.
  * Progress summary (a site report, or a project's last N days): Claude looks at the photos and the report text and
    writes what was done, what it sees (and any safety concern), and a client-ready update. It never moves the plan:
    the stage progress it suggests is for the PM to accept.
Mode "sandbox" gives fixed sample answers without calling the API (for training and tests). Every call is logged with
its token use (Settings → AI shows the month's total).
"""
import base64
import json
import os
import re

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..config import Config
from ..db import db, oid, serialize
from ..security import api, can
from ..services import sales

bp = Blueprint("ai", __name__)
MODES = ("off", "claude", "sandbox")
DEFAULT_MODEL = "claude-opus-5-5"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MAX_FILES = 5
MAX_PHOTOS = 8


class AiError(Exception):
    pass


def ai_settings(company=None):
    c = company or g.company
    s = {"mode": "off", "api_key": None, "model": DEFAULT_MODEL, **(c.get("ai") or {})}
    if not s.get("api_key") and (c.get("assistant") or {}).get("api_key"):
        s["api_key"], s["key_from"] = c["assistant"]["api_key"], "assistant"
    return s


@bp.get("/settings/ai")
@api("settings", write=False)
def get_ai():
    s = ai_settings()
    month = t.now().strftime("%Y-%m")
    use = list(db.ai_usage.aggregate([{"$match": {"company_id": g.cid, "month": month}},
                                      {"$group": {"_id": "$feature", "calls": {"$sum": 1}, "input": {"$sum": "$input_tokens"}, "output": {"$sum": "$output_tokens"}}}]))
    return jsonify({"mode": s["mode"], "model": s["model"], "api_key_set": bool(s.get("api_key")), "key_from": s.get("key_from"), "modes": MODES,
                    "usage": {"month": month, "features": [{"feature": u["_id"], "calls": u["calls"], "input_tokens": u["input"], "output_tokens": u["output"]} for u in use]}})


@bp.put("/settings/ai")
@api("settings")
def put_ai():
    d = request.get_json(force=True) or {}
    s = {k: v for k, v in (g.company.get("ai") or {}).items()}
    if "mode" in d:
        s["mode"] = d["mode"] if d["mode"] in MODES else abort(400, "Mode: off, claude or sandbox")
    if d.get("api_key"):
        s["api_key"] = d["api_key"].strip()[:300]
    if d.get("clear_key"):
        s["api_key"] = None
    if "model" in d:
        s["model"] = (d.get("model") or DEFAULT_MODEL).strip()[:60]
    if s.get("mode") == "claude" and not (s.get("api_key") or (g.company.get("assistant") or {}).get("api_key")):
        abort(400, "Enter the Anthropic API key to use Claude")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"ai": s}})
    g.company["ai"] = s
    t.audit("update", "companies", g.company["_id"], note=f"AI helpers: {s.get('mode', 'off')}")
    return get_ai()


def need_ai():
    s = ai_settings()
    if s["mode"] == "off":
        abort(409, "AI is off — the Owner turns it on in Settings → AI")
    return s


def file_block(key, images_only=False):
    f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the file first")
    ext = os.path.splitext(f["name"])[1].lower()
    path = os.path.join(Config.UPLOAD_DIR, key)
    if not os.path.exists(path):
        abort(400, f"{f['name']} is missing on the server")
    if ext in IMAGE_TYPES:
        kind, media = "image", IMAGE_TYPES[ext]
    elif ext == ".pdf" and not images_only:
        kind, media = "document", "application/pdf"
    else:
        abort(400, f"{f['name']}: use an image (PNG, JPG, WEBP) or a PDF")
    if os.path.getsize(path) > 15 * 1024 * 1024:
        abort(400, f"{f['name']} is too large for AI (15 MB at most)")
    with open(path, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode()
    return {"type": kind, "source": {"type": "base64", "media_type": media, "data": data}}, f["name"]


def call_claude(s, feature, system, content, schema, effort="low", max_tokens=4000):
    """One structured call. Returns the parsed JSON object, or raises AiError with a reason a person can read."""
    import anthropic
    client = anthropic.Anthropic(api_key=s["api_key"], max_retries=1, timeout=120.0)
    kwargs = dict(model=s.get("model") or DEFAULT_MODEL, max_tokens=max_tokens, system=system,
                  output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                  messages=[{"role": "user", "content": content}])
    if effort != "low":
        kwargs["thinking"] = {"type": "adaptive"}
    try:
        try:  # server-side refusal fallback: a declined request is re-run on a fallback model in the same call
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        except TypeError:  # an SDK without the fallbacks parameter
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise AiError("The Anthropic API key was not accepted — check it in Settings → AI")
    except anthropic.RateLimitError:
        raise AiError("The AI service is busy — try again in a minute")
    except anthropic.APIStatusError as e:
        raise AiError(f"The AI service refused the request ({e.status_code})")
    except anthropic.APIConnectionError:
        raise AiError("Could not reach the AI service")
    u = getattr(resp, "usage", None)
    db.ai_usage.insert_one({"company_id": g.cid, "user_id": g.uid, "feature": feature, "model": kwargs["model"], "month": t.now().strftime("%Y-%m"),
                            "input_tokens": getattr(u, "input_tokens", 0) or 0, "output_tokens": getattr(u, "output_tokens", 0) or 0, "at": t.now()})
    if resp.stop_reason == "refusal":
        raise AiError("The AI declined this request")
    if resp.stop_reason == "max_tokens":
        raise AiError("The answer was too long — try fewer drawings or photos")
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(raw)
    except ValueError:
        raise AiError("The AI answer could not be read — try again")


def run(s, feature, system, content, schema, sandbox, **kw):
    if s["mode"] == "sandbox":
        db.ai_usage.insert_one({"company_id": g.cid, "user_id": g.uid, "feature": feature, "model": "sandbox", "month": t.now().strftime("%Y-%m"),
                                "input_tokens": 0, "output_tokens": 0, "at": t.now()})
        return sandbox(), "sandbox"
    if not s.get("api_key"):
        abort(409, "Enter the Anthropic API key in Settings → AI")
    try:
        return call_claude(s, feature, system, content, schema, **kw), "claude"
    except AiError as e:
        abort(502, str(e))


# ============================== follow-up drafts ==============================
FOLLOWUP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["subject", "body"],
                   "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}
PURPOSES = {"check_in": "a friendly check-in that moves the lead to its next step", "proposal": "a follow-up on the proposal that was sent",
            "visit": "asking to fix the site visit or design meeting", "revive": "reviving a lead that went quiet", "thanks": "a thank-you after a meeting"}


def lead_facts(lead):
    c = db.contacts.find_one({"_id": oid(lead["contact_id"])}) if lead.get("contact_id") else None
    prop = db.proposals.find_one({"company_id": g.cid, "lead_id": str(lead["_id"])}, sort=[("created_at", -1)])
    nxt = db.followups.find_one({"company_id": g.cid, "lead_id": str(lead["_id"]), "status": "open"}, sort=[("due", 1)])
    acts = [{"what": a.get("kind") or a.get("type"), "text": (a.get("text") or "")[:200], "at": str(a.get("at"))[:10]} for a in (lead.get("activities") or [])[-8:]]
    return {"client": c and c["name"], "first_name": c and c["name"].split()[0], "service": lead.get("service"), "project_type": lead.get("project_type"),
            "location": lead.get("location"), "stage": lead.get("stage"), "budget": lead.get("budget"), "title": lead.get("title"),
            "proposal": prop and {"number": prop.get("number"), "status": prop.get("status"), "sent": str(prop.get("sent_at") or "")[:10] or None},
            "next_followup": nxt and {"title": nxt["title"], "due": nxt["due"]}, "recent": acts,
            "salesperson": g.user.get("name"), "company": g.company["name"]}


def template_draft(fs, channel, purpose):
    hi = f"Hi {fs['first_name'] or 'there'},"
    body = {"proposal": f"{hi} hope you had a chance to go through our proposal{(' ' + fs['proposal']['number']) if fs.get('proposal') else ''}. "
                        "Happy to walk you through it or adjust anything — when would suit you for a quick call?",
            "visit": f"{hi} we'd love to see the site and understand what you have in mind. Would this week work for a visit? Please share a time that suits you.",
            "revive": f"{hi} it's been a while — just checking whether your {fs.get('project_type') or 'project'} plans are still on. We're here whenever you're ready.",
            "thanks": f"{hi} thank you for your time today. We'll share the next steps shortly; do write if anything comes to mind meanwhile.",
            }.get(purpose, f"{hi} just following up on your {fs.get('project_type') or 'project'}"
                           f"{(' in ' + fs['location']) if fs.get('location') else ''}. What would be a good next step for you?")
    sign = f"\n\n— {fs['salesperson']}, {fs['company']}" if channel == "email" else f" — {fs['salesperson']}, {fs['company']}"
    return {"subject": f"Your {fs.get('project_type') or 'project'} with {fs['company']}", "body": body + sign}


@bp.post("/leads/<lid>/ai/followup")
@api("followups")
def followup_draft(lid):
    lead = sales.load_lead(lid)
    d = request.get_json(force=True) or {}
    channel = d.get("channel") if d.get("channel") in ("whatsapp", "email") else "whatsapp"
    purpose = d.get("purpose") if d.get("purpose") in PURPOSES else "check_in"
    fs = lead_facts(lead)
    s = ai_settings()
    if s["mode"] == "off":
        return jsonify({**template_draft(fs, channel, purpose), "source": "template", "channel": channel})
    system = (f"You write sales follow-up messages for {g.company['name']}, a design and construction firm, in the voice of {fs['salesperson']}. "
              f"Write {PURPOSES[purpose]}, as a {'WhatsApp message: 2-4 short sentences, no subject line needed (put a short one anyway)' if channel == 'whatsapp' else 'short email with a subject line'}. "
              "Use only the facts given; never invent prices, dates, discounts or promises. Warm, plain, professional; in English unless the extra "
              "instruction asks for another language. Sign off with the salesperson's name and the company.")
    extra = (d.get("instruction") or "").strip()[:300]
    content = [{"type": "text", "text": "FACTS (JSON):\n" + json.dumps(fs, default=str) + (f"\n\nEXTRA INSTRUCTION: {extra}" if extra else "")}]
    out, src = run(s, "followup", system, content, FOLLOWUP_SCHEMA, lambda: {**template_draft(fs, channel, purpose), "subject": "[Sandbox] " + template_draft(fs, channel, purpose)["subject"]})
    return jsonify({"subject": (out.get("subject") or "")[:200], "body": (out.get("body") or "")[:3000], "source": src, "channel": channel})


# ============================== BOQ from drawings ==============================
BOQ_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines", "notes"],
              "properties": {"notes": {"type": "string"},
                             "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                  "required": ["description", "qty", "unit", "room", "work_type", "basis"],
                                                                  "properties": {"description": {"type": "string"}, "qty": {"type": "number"},
                                                                                 "unit": {"type": "string"}, "room": {"type": "string"},
                                                                                 "work_type": {"type": "string"}, "basis": {"type": "string"}}}}}}


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


def match_rate(desc, unit, rates):
    """The rate-library item whose name shares the most words with the line (and the same unit, when it has one)."""
    want, best, score = words(desc), None, 0
    for r in rates:
        common = len(want & words(r["name"]))
        if not common:
            continue
        sc = common + (0.5 if unit and r.get("unit") and unit.lower().replace(" ", "") == r["unit"].lower().replace(" ", "") else 0)
        if sc > score:
            best, score = r, sc
    return best if score >= 1 else None


def sandbox_boq(names, notes):
    return {"notes": f"Sandbox answer for {', '.join(names) or 'the drawings'} — sample lines, not read from the drawing.",
            "lines": [{"description": "Vitrified floor tiles 600x600", "qty": 220, "unit": "sq ft", "room": "Living", "work_type": "Flooring", "basis": "Living 20 x 11 ft"},
                      {"description": "Gypsum false ceiling", "qty": 180, "unit": "sq ft", "room": "Living", "work_type": "False ceiling", "basis": "Ceiling plan"},
                      {"description": "Wall putty and two coats emulsion paint", "qty": 640, "unit": "sq ft", "room": "Living", "work_type": "Painting", "basis": "Walls 62 ft run x 10.3 ft"},
                      {"description": "Electrical points (light and power)", "qty": 18, "unit": "nos", "room": "Living", "work_type": "Electrical", "basis": "Electrical layout symbols"}]}


@bp.post("/estimates/<eid>/ai/boq")
@api("proposals")
def boq_from_drawings(eid):
    from .lead_money import load_estimate
    from ..services.defaults import WORK_TYPES
    e, lead = load_estimate(eid)
    if e["status"] not in ("draft", "refused"):
        abort(409, "Add lines to a draft estimate")
    s = need_ai()
    d = request.get_json(force=True) or {}
    keys = list(dict.fromkeys(d.get("files") or []))
    if not keys:
        abort(400, "Choose the drawings to read")
    if len(keys) > MAX_FILES:
        abort(400, f"Up to {MAX_FILES} drawings at a time")
    blocks, names = [], []
    for k in keys:
        b, n = file_block(k)
        blocks.append(b)
        names.append(n)
    notes = (d.get("notes") or "").strip()[:1000]
    system = ("You are a quantity surveyor for an Indian interior design and construction firm. From the drawings, list the bill of quantities: "
              "every item of work with its quantity and unit (sq ft, rft, nos, cu m, kg, sq m — use the drawing's unit system), the room it is in, "
              f"and a work type from this list: {', '.join(WORK_TYPES)}. In 'basis' say how you got the quantity (dimensions read, count of symbols). "
              "Only list what the drawings show or the notes ask for; when a dimension cannot be read, say so in 'basis' and give your best estimate. "
              "Put anything the estimator must check in 'notes'. Do not give rates or prices.")
    content = blocks + [{"type": "text", "text": f"Drawings: {', '.join(names)}.\nScope notes from the estimator: {notes or 'none'}\nProject: {lead.get('project_type') or ''} {lead.get('service') or ''}, {lead.get('location') or ''}."}]
    out, src = run(s, "boq", system, content, BOQ_SCHEMA, lambda: sandbox_boq(names, notes), effort="medium", max_tokens=16000)
    rates = t.find("rate_library", {"active": True})
    mats = [r for r in rates if r["kind"] in ("material", "product")]
    labs = [r for r in rates if r["kind"] == "labour"]
    lines = []
    for ln in (out.get("lines") or [])[:150]:
        desc = (ln.get("description") or "").strip()[:200]
        if not desc:
            continue
        try:
            qty = max(0.0, round(float(ln.get("qty") or 0), 2))
        except (TypeError, ValueError):
            qty = 0.0
        unit = (ln.get("unit") or "").strip()[:20] or None
        m, lb = match_rate(desc, unit, mats), match_rate(desc, unit, labs)
        row = {"id": t.sid(), "description": desc, "qty": qty, "unit": unit, "room": (ln.get("room") or "").strip()[:60] or None,
               "work_type": ln.get("work_type") if ln.get("work_type") in WORK_TYPES else None, "basis": (ln.get("basis") or "").strip()[:300] or None,
               "material_rate_id": m and str(m["_id"]), "material_rate_name": m and m["name"],
               "labour_rate_id": lb and str(lb["_id"]), "labour_rate_name": lb and lb["name"]}
        if not g.hide_costs:
            row.update(material_rate=m and m["rate"], labour_rate=lb and lb["rate"])
        lines.append(row)
    draft = t.insert("ai_drafts", {"kind": "boq", "estimate_id": eid, "lead_id": e["lead_id"], "files": names, "notes": (out.get("notes") or "")[:2000],
                                   "lines": lines, "source": src, "applied": False})
    return jsonify({"draft_id": str(draft["_id"]), "lines": lines, "notes": draft["notes"], "source": src,
                    "warning": "Drafted by AI from the drawings — check every quantity before you add it."})


@bp.post("/estimates/<eid>/ai/boq/apply")
@api("proposals")
def boq_apply(eid):
    from .lead_money import load_estimate, clean_lines, compute
    e, lead = load_estimate(eid)
    if e["status"] not in ("draft", "refused"):
        abort(409, "Add lines to a draft estimate")
    d = request.get_json(force=True) or {}
    draft = t.get("ai_drafts", d.get("draft_id") or "") if d.get("draft_id") else abort(400, "Which draft?")
    if draft.get("estimate_id") != eid:
        abort(400, "This draft belongs to another estimate")
    chosen = {x.get("id"): x for x in d.get("lines") or []}  # the estimator's edits win over the draft
    if not chosen:
        abort(400, "Tick the lines to add")
    add = []
    for ln in draft["lines"]:
        if ln["id"] not in chosen:
            continue
        x = {**ln, **{k: v for k, v in chosen[ln["id"]].items() if k in ("description", "qty", "unit", "room", "work_type", "material_rate_id", "labour_rate_id")}}
        rates = {str(r["_id"]): r["rate"] for r in t.find("rate_library", {"_id": {"$in": [oid(i) for i in (x.get("material_rate_id"), x.get("labour_rate_id")) if i]}})}
        add.append({"description": x["description"], "qty": x["qty"], "unit": x.get("unit"), "room": x.get("room"), "work_type": x.get("work_type"),
                    "qty_source": "manual", "material_rate_id": x.get("material_rate_id"), "labour_rate_id": x.get("labour_rate_id"),
                    "material_rate": rates.get(x.get("material_rate_id"), 0), "labour_rate": rates.get(x.get("labour_rate_id"), 0)})
    if not add:
        abort(400, "None of the ticked lines are in the draft")
    keep = [{k: v for k, v in ln.items() if k not in ("material_cost", "labour_cost", "line_cost")} for ln in e["lines"]]
    est = {"lines": clean_lines(keep + add, lead), **{k: e[k] for k in ("overhead_pct", "markup_pct", "discount_pct", "tax_pct")}}
    compute(est, lead)
    upd = t.update("estimates", eid, {"lines": est["lines"], "totals": est["totals"]})
    t.update("ai_drafts", str(draft["_id"]), {"applied": True, "applied_lines": len(add)}, audit_it=False)
    sales.log(e["lead_id"], "estimate", f"{len(add)} line(s) added to {e['number']} from drawings (AI draft, checked by {g.user.get('name')})", estimate_id=eid)
    return jsonify(t.out(upd))


# ============================== progress summaries from site photos ==============================
SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "observations", "safety_concerns", "client_update", "stages"],
                  "properties": {"summary": {"type": "string"}, "client_update": {"type": "string"},
                                 "observations": {"type": "array", "items": {"type": "string"}},
                                 "safety_concerns": {"type": "array", "items": {"type": "string"}},
                                 "stages": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["stage", "progress", "why"],
                                                                       "properties": {"stage": {"type": "string"}, "progress": {"type": "integer"}, "why": {"type": "string"}}}}}}


def report_text(r):
    parts = [f"Date {r['date']}; on site {r.get('headcount') or 0}"]
    if r.get("weather", {}).get("kind"):
        parts.append(f"weather {r['weather']['kind']}")
    for w in r.get("work", []):
        parts.append(f"work — {w['stage_name']}{(' / ' + w['task_title']) if w.get('task_title') else ''}: {w['note']}")
    for k in ("materials", "equipment", "safety", "visitors"):
        if r.get(k):
            parts.append(f"{k}: {r[k]}")
    return "; ".join(parts)


def summarise(p, reports, feature):
    s = need_ai()
    photos = [ph for r in reports for ph in r.get("photos", []) if os.path.splitext(ph["name"])[1].lower() in IMAGE_TYPES][-MAX_PHOTOS:]
    if not photos and not any(r.get("work") for r in reports):
        abort(400, "There are no photos or work notes to summarise")
    content = []
    for ph in photos:
        b, n = file_block(ph["key"], images_only=True)
        content += [b, {"type": "text", "text": f"Photo: {ph.get('caption') or n}{(' — ' + ph['stage_name']) if ph.get('stage_name') else ''}{(' — ' + ph['room']) if ph.get('room') else ''}"}]
    stages = [{"stage": st["name"], "progress_now": st.get("progress", 0)} for st in p.get("stages", [])]
    content.append({"type": "text", "text": "SITE REPORTS:\n" + "\n".join(report_text(r) for r in reports) + "\n\nSTAGES (JSON):\n" + json.dumps(stages)})
    system = (f"You are a construction project manager at {g.company['name']} reviewing site photos and daily reports of '{p['name']}'. "
              "Write: 'summary' — 3-5 sentences on the work done, for the team; 'observations' — what you see in the photos (quality, finish, "
              "what is complete or pending); 'safety_concerns' — only real ones you can see (missing PPE, open edges, loose cables), else empty; "
              "'client_update' — a short warm update for the client without internal problems or costs; 'stages' — for stages the photos or notes "
              "show work on, your estimate of overall progress 0-100 with why. Never invent work you cannot see or read.")
    sb = lambda: {"summary": f"Sandbox summary of {len(reports)} report(s) and {len(photos)} photo(s).", "observations": [f"{len(photos)} photo(s) reviewed (sandbox)"],
                  "safety_concerns": [], "client_update": f"Work on {p['name']} is moving ahead as planned this week.",
                  "stages": [{"stage": st["name"], "progress": min(100, (st.get("progress") or 0) + 10), "why": "Sandbox estimate"} for st in p.get("stages", [])[:1]]}
    out, src = run(s, feature, system, content, SUMMARY_SCHEMA, sb, effort="medium", max_tokens=8000)
    by_name = {st["name"].lower(): st for st in p.get("stages", [])}
    sug = []
    for x in out.get("stages") or []:
        st = by_name.get((x.get("stage") or "").lower())
        if st:
            sug.append({"stage_id": st["id"], "stage_name": st["name"], "now": st.get("progress", 0),
                        "suggested": max(0, min(100, int(x.get("progress") or 0))), "why": (x.get("why") or "")[:300]})
    return {"summary": (out.get("summary") or "")[:3000], "observations": [str(o)[:300] for o in (out.get("observations") or [])[:15]],
            "safety_concerns": [str(o)[:300] for o in (out.get("safety_concerns") or [])[:10]], "client_update": (out.get("client_update") or "")[:2000],
            "stages": sug, "photos": len(photos), "reports": len(reports), "source": src, "by": g.user.get("name"), "at": t.now()}


@bp.post("/site-reports/<rid>/ai/summary")
@api(None)
def report_summary(rid):
    from .site_reports import access
    r = t.get("site_reports", rid)
    p = access(r["project_id"], write=True)
    out = summarise(p, [r], "photo_summary")
    t.update("site_reports", rid, {"ai_summary": out}, audit_it=False)
    return jsonify(serialize(out))


@bp.post("/projects/<pid>/ai/progress-summary")
@api(None)
def project_summary(pid):
    from datetime import date, timedelta
    from .site_reports import access
    p = access(pid)
    if not (can("projects", True) or can("site", True)):
        abort(403, "Your role cannot write progress summaries")
    days = (request.get_json(force=True) or {}).get("days") or 7
    try:
        days = max(1, min(31, int(days)))
    except (TypeError, ValueError):
        abort(400, "Days is a number")
    since = (date.fromisoformat(sales.today()) - timedelta(days=days - 1)).isoformat()
    reports = t.find("site_reports", {"project_id": pid, "date": {"$gte": since}}, sort=[("date", 1)])
    if not reports:
        abort(400, f"No site reports in the last {days} day(s)")
    out = summarise(p, reports, "progress_summary")
    x = t.insert("ai_drafts", {"kind": "progress", "project_id": pid, "project_name": p["name"], "from": since, "to": sales.today(), **out})
    return jsonify(serialize(x)), 201


@bp.get("/projects/<pid>/ai/progress-summary")
@api(None)
def project_summaries(pid):
    from .site_reports import access
    access(pid)
    return jsonify([serialize(x) for x in t.find("ai_drafts", {"kind": "progress", "project_id": pid}, sort=[("created_at", -1)], limit=20)])
