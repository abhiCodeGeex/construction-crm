"""Phase K block 2 — RFIs and submittals (v4 §6).

* RFI (request for information): a question from site, a subcontractor or a consultant to the person who must answer
  (a designer / architect on the team, or an external consultant in the portal), with photos, the drawing it is about,
  a due date and a priority. The answer goes back to the asker and is emailed to the distribution list. An answer with
  a cost or time impact can become a change request in one step. Open and overdue RFIs show in the digest and the
  waiting report; the worker reminds the answerer when one is overdue.
* Submittal: shop drawings, samples, data sheets, method statements sent for review. Each revision is reviewed:
  approved / approved as noted / revise and resubmit / rejected. Revise-and-resubmit needs a new revision.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal, can
from ..services import notify, project_events as ev, workdays
from .lead_money import a_date
from .projects import load, member

bp = Blueprint("rfis", __name__)
PRIORITIES = ["low", "normal", "high", "urgent"]
SUB_KINDS = ["Shop drawing", "Sample", "Data sheet", "Method statement", "Test certificate", "Other"]
DECISIONS = {"approved": "Approved", "approved_as_noted": "Approved as noted", "revise_resubmit": "Revise and resubmit", "rejected": "Rejected"}


def files_of(keys):
    out = []
    for key in dict.fromkeys(keys or []):
        f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the file first")
        out.append({"key": key, "name": f["name"], "url": f"/api/files/{key}"})
    return out[:10]


def access(pid, write=False):
    if not (can("projects") or can("site") or can("documents")):
        abort(403, "Your role cannot view RFIs")
    p = load(pid)
    if write and not (g.role == "owner" or member(p)):
        abort(403, "Only people on the project raise or answer RFIs")
    return p


def default_due(days=3):
    try:
        return workdays.add(date.today().isoformat(), days)
    except Exception:  # noqa: BLE001 — no calendar: plain days
        return (date.today() + timedelta(days=days)).isoformat()


def answerer(p, d):
    """The person who answers: a staff member on the team, or an external consultant / architect contact on the team."""
    if d.get("to_user_id"):
        if not any(m.get("user_id") == d["to_user_id"] for m in p.get("team", [])):
            abort(400, "The person who answers must be on the project team")
        u = db.users.find_one({"_id": oid(d["to_user_id"])})
        return {"to_user_id": d["to_user_id"], "to_contact_id": None, "to_name": u["name"]}
    if d.get("to_contact_id"):
        m = next((m for m in p.get("team", []) if m.get("contact_id") == d["to_contact_id"]), None) or abort(400, "The consultant must be on the project team")
        return {"to_user_id": None, "to_contact_id": d["to_contact_id"], "to_name": m.get("name")}
    # default: the designer / architect on the team, else the PM
    for role in ("Architect", "Interior Designer", "Project Manager"):
        m = next((m for m in p.get("team", []) if m.get("project_role") == role and m.get("user_id")), None)
        if m:
            return {"to_user_id": m["user_id"], "to_contact_id": None, "to_name": m.get("name")}
    abort(400, "Choose who answers")


def overdue(r):
    return r["status"] == "open" and r.get("due_date") and r["due_date"] < date.today().isoformat()


def rfi_out(r):
    d = serialize(r)
    d["overdue"] = overdue(r)
    return d


def new_rfi(p, d, who, kind):
    subject = (d.get("subject") or "").strip()[:200] or abort(400, "Subject is required")
    question = (d.get("question") or "").strip()[:4000] or abort(400, "Write the question")
    if d.get("priority", "normal") not in PRIORITIES:
        abort(400, "Priority: low, normal, high or urgent")
    doc = None
    if d.get("document_id"):
        doc = db.documents.find_one({"_id": oid(d["document_id"]), "company_id": g.cid, "project_id": str(p["_id"])}) or abort(400, "Drawing not found on this project")
    due = a_date(d.get("due_date"), "Answer by", required=False) or default_due(1 if d.get("priority") == "urgent" else 3)
    r = t.insert("rfis", {"number": t.next_number("RFI", "RFI"), "project_id": str(p["_id"]), "project_name": p["name"], "subject": subject,
                          "question": question, "priority": d.get("priority", "normal"), "due_date": due, "files": files_of(d.get("files")),
                          "document_id": doc and str(doc["_id"]), "document_name": doc and doc["name"], "raised_by": who, "raised_kind": kind,
                          "raised_user_id": g.uid if kind == "staff" else None, "raised_contact_id": getattr(g, "contact_id", None) if kind != "staff" else None,
                          **answerer(p, d), "status": "open", "answer": None, "distribution": [], "co_id": None})
    if r["to_user_id"]:
        notify.send("rfi_new", [r["to_user_id"]], f"{r['number']} ({p['name']}) from {who}: {subject}", f"/app/projects/{p['_id']}?tab=rfis",
                    project_id=str(p["_id"]), skip_self=False, level="warn" if r["priority"] in ("high", "urgent") else "info")
    else:
        c = db.contacts.find_one({"_id": oid(r["to_contact_id"])}) or {}
        notify.deliver(g.company, c.get("email"), f"{r['number']}: {subject} — {p['name']}", f"{question}\n\nPlease answer by {due} in your portal.")
    ev.log(str(p["_id"]), "file", f"{r['number']} raised by {who}: {subject}")
    return r


@bp.get("/projects/<pid>/rfis")
@api(None)
def list_rfis(pid):
    access(pid)
    q = {"project_id": pid}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify([rfi_out(r) for r in t.find("rfis", q, sort=[("created_at", -1)])])


@bp.get("/rfis")
@api(None)
def my_rfis():
    """RFIs waiting for my answer, and the ones I asked that are open."""
    if not (can("projects") or can("site") or can("documents")):
        abort(403, "Your role cannot view RFIs")
    rows = t.find("rfis", {"status": "open", "$or": [{"to_user_id": g.uid}, {"raised_user_id": g.uid}]}, sort=[("due_date", 1)])
    return jsonify([rfi_out(r) for r in rows])


@bp.post("/projects/<pid>/rfis")
@api(None)
def add_rfi(pid):
    p = access(pid, write=True)
    return jsonify(rfi_out(new_rfi(p, request.get_json(force=True) or {}, g.user["name"], "staff"))), 201


def answer(r, p, d, who):
    if r["status"] != "open":
        abort(409, "This RFI is already answered")
    text = (d.get("text") or "").strip()[:4000] or abort(400, "Write the answer")
    dist = []
    for cid_ in dict.fromkeys(d.get("distribution") or []):
        c = db.contacts.find_one({"_id": oid(cid_), "company_id": g.cid}) if len(cid_) == 24 else None
        if not c:
            abort(400, "A contact on the distribution list was not found")
        dist.append({"contact_id": cid_, "name": c["name"], "emailed": notify.deliver(g.company, c.get("email"), f"{r['number']} answered: {r['subject']} — {p['name']}",
                                                                                     f"Question: {r['question']}\n\nAnswer: {text}\n\n— {who}")})
    ans = {"text": text, "files": files_of(d.get("files")), "by": who, "at": t.now(),
           "cost_impact": bool(d.get("cost_impact")), "time_impact": bool(d.get("time_impact"))}
    ch = {"status": "answered", "answer": ans, "distribution": dist, "answered_days": (date.today() - r["created_at"].date()).days}
    if ans["cost_impact"] or ans["time_impact"]:  # the answer changes the work: a change request for the PM to price
        from .insights import make_request
        co = make_request(p, {"title": f"{r['number']}: {r['subject']}"[:150], "description": f"From the answer to {r['number']}: {text}"}, who, "site")
        ch.update(co_id=str(co["_id"]), co_number=co["number"])
    upd = t.update("rfis", str(r["_id"]), ch)
    if r.get("raised_user_id"):
        notify.send("rfi_answered", [r["raised_user_id"]], f"{r['number']} answered by {who}: {text[:140]}", f"/app/projects/{p['_id']}?tab=rfis",
                    project_id=str(p["_id"]), skip_self=False)
    elif r.get("raised_contact_id"):
        c = db.contacts.find_one({"_id": oid(r["raised_contact_id"])}) or {}
        notify.deliver(g.company, c.get("email"), f"{r['number']} answered — {p['name']}", f"{r['question']}\n\nAnswer: {text}")
    ev.log(str(p["_id"]), "file", f"{r['number']} answered by {who}" + (f" — {ch['co_number']} drafted" if ch.get("co_number") else ""))
    return upd


@bp.post("/rfis/<rid>/answer")
@api(None)
def answer_rfi(rid):
    r = t.get("rfis", rid)
    p = access(r["project_id"], write=True)
    if r.get("to_user_id") != g.uid and g.role not in ("owner", "pm"):
        abort(403, f"{r['to_name']} answers this RFI")
    return jsonify(rfi_out(answer(r, p, request.get_json(force=True) or {}, g.user["name"])))


@bp.post("/rfis/<rid>/close")
@api(None)
def close_rfi(rid):
    r = t.get("rfis", rid)
    access(r["project_id"], write=True)
    if r["status"] != "answered":
        abort(409, "Only an answered RFI is closed")
    return jsonify(rfi_out(t.update("rfis", rid, {"status": "closed", "closed_by": g.user["name"], "closed_at": t.now()})))


@bp.post("/rfis/<rid>/reopen")
@api(None)
def reopen_rfi(rid):
    r = t.get("rfis", rid)
    access(r["project_id"], write=True)
    if r["status"] == "open":
        abort(409, "Already open")
    why = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:500] or abort(400, "Why is the answer not enough?")
    hist = r.get("history", []) + [{"answer": r.get("answer"), "reopened_because": why, "by": g.user["name"], "at": t.now()}]
    return jsonify(rfi_out(t.update("rfis", rid, {"status": "open", "answer": None, "history": hist, "due_date": default_due(2)})))


# ---------------- portal: consultants and subcontractors ----------------
def portal_p(pid):
    from .site_reports import portal_project
    return portal_project(pid)


@bp.get("/portal/projects/<pid>/rfis")
@portal
def portal_rfis(pid):
    portal_p(pid)
    me = g.contact_id
    rows = db.rfis.find({"company_id": g.cid, "project_id": pid, "$or": [{"raised_contact_id": me}, {"to_contact_id": me}, {"distribution.contact_id": me}]}).sort("created_at", -1)
    return jsonify([rfi_out(r) for r in rows])


@bp.post("/portal/projects/<pid>/rfis")
@portal
def portal_add_rfi(pid):
    p = portal_p(pid)
    role = g.user.get("role")
    if role not in ("subcontractor", "consultant"):
        abort(403, "Clients ask the team in Messages")
    d = request.get_json(force=True) or {}
    d.pop("to_contact_id", None)
    return jsonify(rfi_out(new_rfi(p, d, g.user["name"], role))), 201


@bp.post("/portal/rfis/<rid>/answer")
@portal
def portal_answer(rid):
    r = db.rfis.find_one({"_id": oid(rid), "company_id": g.cid, "to_contact_id": g.contact_id}) or abort(404, "not found")
    p = portal_p(r["project_id"])
    return jsonify(rfi_out(answer(r, p, request.get_json(force=True) or {}, g.user["name"])))


# ============================== submittals ==============================
def sub_out(s):
    d = serialize(s)
    d["current"] = d["revisions"][-1] if d.get("revisions") else None
    d["overdue"] = s["status"] == "submitted" and s.get("due_date") and s["due_date"] < date.today().isoformat()
    return d


def reviewer_of(p, uid):
    if uid:
        if not any(m.get("user_id") == uid for m in p.get("team", [])):
            abort(400, "The reviewer must be on the project team")
        return uid, db.users.find_one({"_id": oid(uid)})["name"]
    m = next((m for role in ("Architect", "Interior Designer", "Project Manager") for m in p.get("team", []) if m.get("project_role") == role and m.get("user_id")), None)
    return (m["user_id"], m["name"]) if m else abort(400, "Choose the reviewer")


def new_submittal(p, d, who, contact_id=None):
    kind = d.get("kind") if d.get("kind") in SUB_KINDS else abort(400, f"Kind: {', '.join(SUB_KINDS)}")
    title = (d.get("title") or "").strip()[:200] or abort(400, "Title is required")
    files = files_of(d.get("files"))
    if not files:
        abort(400, "Attach the drawing, data sheet or photo of the sample")
    sc = None
    if d.get("subcontract_id"):
        sc = db.subcontracts.find_one({"_id": oid(d["subcontract_id"]), "company_id": g.cid, "project_id": str(p["_id"])}) or abort(400, "Package not found")
    rid, rname = reviewer_of(p, d.get("reviewer_id"))
    s = t.insert("submittals", {"number": t.next_number("SUBM", "SUB"), "project_id": str(p["_id"]), "project_name": p["name"], "title": title, "kind": kind,
                                "spec_section": (d.get("spec_section") or "").strip()[:60] or None, "subcontract_id": sc and str(sc["_id"]),
                                "subcontract_title": sc and sc["title"], "submitted_by": who, "submitted_contact_id": contact_id,
                                "reviewer_id": rid, "reviewer_name": rname, "due_date": a_date(d.get("due_date"), "Review by", required=False) or default_due(5),
                                "status": "submitted", "revisions": [{"rev": 1, "files": files, "note": (d.get("note") or "").strip()[:1000] or None,
                                                                      "submitted_at": t.now(), "by": who, "decision": None}]})
    notify.send("submittal", [rid], f"{s['number']} {kind} to review — {title} ({p['name']})", f"/app/projects/{p['_id']}?tab=rfis",
                project_id=str(p["_id"]), skip_self=False)
    return s


@bp.get("/projects/<pid>/submittals")
@api(None)
def list_submittals(pid):
    access(pid)
    return jsonify([sub_out(s) for s in t.find("submittals", {"project_id": pid}, sort=[("created_at", -1)])])


@bp.post("/projects/<pid>/submittals")
@api(None)
def add_submittal(pid):
    p = access(pid, write=True)
    return jsonify(sub_out(new_submittal(p, request.get_json(force=True) or {}, g.user["name"]))), 201


@bp.post("/submittals/<sid>/review")
@api(None)
def review(sid):
    s = t.get("submittals", sid)
    p = access(s["project_id"], write=True)
    if s["reviewer_id"] != g.uid and g.role != "owner":
        abort(403, f"{s['reviewer_name']} reviews this submittal")
    if s["status"] != "submitted":
        abort(409, "Nothing waiting for review")
    d = request.get_json(force=True) or {}
    dec = d.get("decision") if d.get("decision") in DECISIONS else abort(400, f"Decision: {', '.join(DECISIONS.values())}")
    note = (d.get("note") or "").strip()[:2000] or None
    if dec != "approved" and not note:
        abort(400, "Say what to change")
    revs = s["revisions"]
    revs[-1].update(decision=dec, review_note=note, review_files=files_of(d.get("files")), reviewed_by=g.user["name"], reviewed_at=t.now())
    upd = t.update("submittals", sid, {"status": dec, "revisions": revs})
    text = f"{s['number']} {s['title']}: {DECISIONS[dec]}" + (f" — {note}" if note else "")
    if s.get("submitted_contact_id"):
        c = db.contacts.find_one({"_id": oid(s["submitted_contact_id"])}) or {}
        notify.deliver(g.company, c.get("email"), f"{s['number']} reviewed — {p['name']}", text)
    notify.send("submittal_reviewed", ev.managers(p), text, f"/app/projects/{p['_id']}?tab=rfis", project_id=str(p["_id"]), skip_self=False)
    ev.log(str(p["_id"]), "file", text)
    return jsonify(sub_out(upd))


def resubmit(s, d, who):
    if s["status"] != "revise_resubmit":
        abort(409, "Only a submittal sent back for revision is resubmitted")
    files = files_of(d.get("files"))
    if not files:
        abort(400, "Attach the revised files")
    revs = s["revisions"] + [{"rev": len(s["revisions"]) + 1, "files": files, "note": (d.get("note") or "").strip()[:1000] or None,
                              "submitted_at": t.now(), "by": who, "decision": None}]
    upd = t.update("submittals", str(s["_id"]), {"status": "submitted", "revisions": revs, "due_date": default_due(5)})
    notify.send("submittal", [s["reviewer_id"]], f"{s['number']} rev {len(revs)} to review — {s['title']}", f"/app/projects/{s['project_id']}?tab=rfis",
                project_id=s["project_id"], skip_self=False)
    return upd


@bp.post("/submittals/<sid>/resubmit")
@api(None)
def team_resubmit(sid):
    s = t.get("submittals", sid)
    access(s["project_id"], write=True)
    return jsonify(sub_out(resubmit(s, request.get_json(force=True) or {}, g.user["name"])))


@bp.get("/portal/projects/<pid>/submittals")
@portal
def portal_submittals(pid):
    portal_p(pid)
    return jsonify([sub_out(s) for s in db.submittals.find({"company_id": g.cid, "project_id": pid, "submitted_contact_id": g.contact_id}).sort("created_at", -1)])


@bp.post("/portal/projects/<pid>/submittals")
@portal
def portal_add_submittal(pid):
    p = portal_p(pid)
    if g.user.get("role") not in ("subcontractor", "consultant", "vendor"):
        abort(403, "Only subcontractors, suppliers and consultants send submittals")
    d = request.get_json(force=True) or {}
    d.pop("reviewer_id", None)
    return jsonify(sub_out(new_submittal(p, d, g.user["name"], g.contact_id))), 201


@bp.post("/portal/submittals/<sid>/resubmit")
@portal
def portal_resubmit(sid):
    s = db.submittals.find_one({"_id": oid(sid), "company_id": g.cid, "submitted_contact_id": g.contact_id}) or abort(404, "not found")
    return jsonify(sub_out(resubmit(s, request.get_json(force=True) or {}, g.user["name"])))


# ============================== reports and reminders ==============================
@bp.get("/reports/rfis")
@api(None)
def rfi_report():
    if not (can("reports") or g.role in ("owner", "pm")):
        abort(403, "Your role cannot view this report")
    rows = {}
    for r in db.rfis.find({"company_id": g.cid}):
        x = rows.setdefault(r["project_id"], {"project_id": r["project_id"], "project": r["project_name"], "open": 0, "overdue": 0, "answered": 0, "days": []})
        if r["status"] == "open":
            x["open"] += 1
            x["overdue"] += 1 if overdue(r) else 0
        else:
            x["answered"] += 1
            if r.get("answered_days") is not None:
                x["days"].append(r["answered_days"])
    subs = {}
    for s in db.submittals.find({"company_id": g.cid}):
        subs.setdefault(s["project_id"], {}).setdefault(s["status"], 0)
        subs[s["project_id"]][s["status"]] += 1
    out = [{**{k: v for k, v in x.items() if k != "days"}, "avg_days": round(sum(x["days"]) / len(x["days"]), 1) if x["days"] else None,
            "submittals": subs.get(pid, {})} for pid, x in rows.items()]
    return jsonify(sorted(out, key=lambda x: -x["overdue"]))


def check_rfis(now):
    """Overdue RFIs and submittals: the person who answers hears once a day."""
    today = now.date().isoformat()
    for r in db.rfis.find({"company_id": g.cid, "status": "open", "due_date": {"$lt": today}, "to_user_id": {"$ne": None}}):
        notify.send("rfi_due", [r["to_user_id"]], f"{r['number']} overdue since {r['due_date']}: {r['subject']} ({r['project_name']})",
                    f"/app/projects/{r['project_id']}?tab=rfis", project_id=r["project_id"], key=f"rfi-due:{r['_id']}:{today}", level="warn", skip_self=False)
    for s in db.submittals.find({"company_id": g.cid, "status": "submitted", "due_date": {"$lt": today}}):
        notify.send("rfi_due", [s["reviewer_id"]], f"{s['number']} review overdue since {s['due_date']}: {s['title']}",
                    f"/app/projects/{s['project_id']}?tab=rfis", project_id=s["project_id"], key=f"sub-due:{s['_id']}:{today}", level="warn", skip_self=False)
