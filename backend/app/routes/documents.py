"""Phase F block 1 — the project document library.

* Folders: the company's defaults per service (Settings), plus two read-only folders that list what already exists
  without copying it: *From the lead* (lead files moved on the win) and *Task files* (B+2). Each stored file is
  counted once against the storage quota, wherever it is listed.
* A document has versions R0, R1, …; the latest is current, older ones stay downloadable. Removing a version deletes
  its stored file. A version sent in a transmittal (block 2) is never deleted.
Who: documents rw (Owner, PM, Designer) on projects they are on; documents r (Sales, Site) read.
"""
import os

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import project_events as ev
from ..services import notify
from ..services.defaults import DOC_FOLDERS, DOC_KINDS, DRAWING_STATUSES, TRANSMITTAL_PURPOSES, DISCIPLINES
from ..config import Config
from .lead_steps import delete_stored
from .projects import load, member

bp = Blueprint("documents", __name__)

FROM_LEAD, TASK_FILES = "From the lead", "Task files"


def folder_defaults(company=None):
    custom = (company or g.company).get("document_folders") or {}
    return {k: custom.get(k, v) for k, v in DOC_FOLDERS.items()}


def folders_for(p):
    f = folder_defaults()
    out = list(f["all"])
    for s in p.get("services", []):
        out += [x for x in f.get(s, []) if x not in out]
    return out


def access(pid, write=False):
    if not can("documents"):
        abort(403, "Your role cannot view documents")
    p = load(pid)  # Owner: every project; everyone else: projects they are on
    if write and not (can("documents", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change documents")
    return p


def rev_name(n):
    return f"R{n}"


def upload_row(key, note=None):
    f = db.files.find_one({"company_id": g.cid, "key": key}) if key else None
    if not f:
        abort(400, "Upload the file first")
    if db.documents.find_one({"company_id": g.cid, "versions.file_key": key}, {"_id": 1}):
        abort(409, "This file is already in the library")
    return {"file_key": f["key"], "name": f["name"], "size": f["size"], "note": (note or "").strip()[:300] or None,
            "by": g.user.get("name"), "by_id": g.uid, "at": t.now(), "sent": []}


def clean(d, p, doc=None):
    ch = {}
    if "folder" in d or doc is None:
        if d.get("folder") not in folders_for(p):
            abort(400, f"Choose a folder: {', '.join(folders_for(p))}")
        ch["folder"] = d["folder"]
    if "name" in d or doc is None:
        ch["name"] = (d.get("name") or "").strip()[:150] or abort(400, "Give the document a name")
    if "kind" in d or doc is None:
        if (d.get("kind") or "other") not in DOC_KINDS:
            abort(400, f"Kind must be one of: {', '.join(DOC_KINDS)}")
        ch["kind"] = d.get("kind") or "other"
    if "stage_id" in d:
        s = next((x for x in p.get("stages", []) if x["id"] == d["stage_id"]), None) if d["stage_id"] else None
        if d["stage_id"] and not s:
            abort(400, "Stage not found")
        ch.update(stage_id=s and s["id"], stage_name=s and s["name"])
    if "room" in d:
        ch["room"] = (d.get("room") or "").strip()[:80] or None
    if "tags" in d:
        ch["tags"] = [str(x).strip()[:30] for x in (d.get("tags") or []) if str(x).strip()][:10]
    if "shared" in d:
        ch["shared"] = bool(d["shared"])  # shown to the client in the portal
    kind = ch.get("kind", (doc or {}).get("kind"))
    if kind == "drawing":  # block 2: the drawing register
        if "number" in d or doc is None or (doc and doc.get("kind") != "drawing"):
            number = (d.get("number") or "").strip().upper()[:20] or abort(400, "A drawing needs a number, e.g. A-101")
            clash = db.documents.find_one({"company_id": g.cid, "project_id": str(p["_id"]), "kind": "drawing", "number": number,
                                           **({"_id": {"$ne": doc["_id"]}} if doc else {})}, {"_id": 1})
            if clash:
                abort(409, f"Drawing {number} already exists on this project")
            ch["number"] = number
        if "discipline" in d:
            if d["discipline"] and d["discipline"] not in DISCIPLINES:
                abort(400, f"Discipline must be one of: {', '.join(DISCIPLINES)}")
            ch["discipline"] = d["discipline"] or None
        if "scale" in d:
            ch["scale"] = (d.get("scale") or "").strip()[:20] or None
    return ch


def present(doc):
    data = serialize(doc)
    cur = doc["versions"][-1] if doc.get("versions") else None
    data["current"] = cur and {**serialize(cur), "url": f"/api/files/{cur['file_key']}"}
    for v in data["versions"]:
        v["url"] = f"/api/files/{v['file_key']}"
    return data


@bp.get("/projects/<pid>/documents")
@api(None)
def list_documents(pid):
    p = access(pid)
    docs = [present(x) for x in t.find("documents", {"project_id": pid}, sort=[("folder", 1), ("name", 1)])]
    lead_files = [{**serialize(f), "url": f"/api/files/{f['key']}"} for f in t.find("lead_files", {"project_id": pid})]
    task_files = [{**f, "task": tk["title"], "stage": s["name"], "url": f"/api/files/{f['key']}"}
                  for s in p.get("stages", []) for tk in s.get("tasks", []) for f in tk.get("files", [])]
    return jsonify({"folders": folders_for(p), "virtual_folders": [FROM_LEAD, TASK_FILES], "kinds": DOC_KINDS,
                    "documents": docs, "lead_files": lead_files, "task_files": task_files,
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "can_write": can("documents", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/documents")
@api(None)
def add_document(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    first = upload_row(d.get("file_key"), d.get("note"))
    ch = clean(d, p)
    first.update(rev=rev_name(0), n=0, status="wip" if ch["kind"] == "drawing" else None)
    doc = t.insert("documents", {"project_id": pid, "project_name": p["name"], "stage_id": None, "stage_name": None, "room": None,
                                 "tags": [], "shared": False, "created_by_name": g.user.get("name"), "number": None, "discipline": None,
                                 "scale": None, **ch, "versions": [first], "current_rev": rev_name(0), "status": first["status"]})
    ev.log(pid, "file", f"Document added: {doc['name']} {doc['current_rev']} ({doc['folder']})")
    return jsonify(present(doc)), 201


@bp.put("/documents/<did>")
@api(None)
def edit_document(did):
    doc = t.get("documents", did)
    p = access(doc["project_id"], write=True)
    return jsonify(present(t.update("documents", did, clean(request.get_json(force=True) or {}, p, doc))))


@bp.post("/documents/<did>/versions")
@api(None)
def add_version(did):
    doc = t.get("documents", did)
    access(doc["project_id"], write=True)
    d = request.get_json(force=True) or {}
    n = doc["versions"][-1]["n"] + 1
    drawing = doc["kind"] == "drawing"
    row = {**upload_row(d.get("file_key"), d.get("note")), "rev": rev_name(n), "n": n, "status": "wip" if drawing else None}
    older = [{**v, "status": "superseded"} if drawing and v.get("status") else v for v in doc["versions"]]  # a new revision supersedes
    upd = t.update("documents", did, {"current_rev": row["rev"], "versions": older + [row], "status": row["status"]})
    ev.log(doc["project_id"], "file", f"New revision: {doc['name']} {row['rev']}" + (f" — {row['note']}" if row["note"] else ""))
    return jsonify(present(upd)), 201


@bp.delete("/documents/<did>/versions/<rev>")
@api(None)
def delete_version(did, rev):
    doc = t.get("documents", did)
    access(doc["project_id"], write=True)
    v = next((x for x in doc["versions"] if x["rev"] == rev), None) or abort(404, "revision not found")
    if v.get("sent"):
        abort(409, f"{rev} was sent in a transmittal and is kept; upload a new revision instead")
    if len(doc["versions"]) == 1:
        abort(409, "This is the only revision; delete the document instead")
    rest = [x for x in doc["versions"] if x["rev"] != rev]
    if v is doc["versions"][-1] and doc["kind"] == "drawing":  # the previous revision is current again
        rest[-1] = {**rest[-1], "status": "wip"}
    upd = t.update("documents", did, {"versions": rest, "current_rev": rest[-1]["rev"], "status": rest[-1].get("status")})
    delete_stored(v["file_key"])
    ev.log(doc["project_id"], "file", f"Revision removed: {doc['name']} {rev}")
    return jsonify(present(upd))


@bp.delete("/documents/<did>")
@api(None)
def delete_document(did):
    doc = t.get("documents", did)
    access(doc["project_id"], write=True)
    if any(v.get("sent") for v in doc["versions"]):
        abort(409, "A revision of this document was sent in a transmittal; the document is kept")
    t.delete("documents", did)
    for v in doc["versions"]:
        delete_stored(v["file_key"])
    ev.log(doc["project_id"], "file", f"Document deleted: {doc['name']}")
    return jsonify({"ok": True})


@bp.get("/documents")
@api("documents", write=False)
def recent_documents():
    """Documents & drawings page: the latest documents across the projects you can see."""
    q = {}
    if g.role != "owner":
        q["project_id"] = {"$in": [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]}
    if request.args.get("kind"):
        q["kind"] = request.args["kind"]
    return jsonify({"documents": [present(x) for x in t.find("documents", q, sort=[("updated_at", -1)], limit=200)], "kinds": DOC_KINDS})


# ---------------- Settings -> document folders ----------------
@bp.get("/settings/document-folders")
@api(None)
def get_folders():
    return jsonify(folder_defaults())


@bp.put("/settings/document-folders")
@api("settings")
def put_folders():
    d = request.get_json(force=True) or {}
    out = {}
    for k in DOC_FOLDERS:
        names = [str(x).strip()[:60] for x in (d.get(k) or []) if str(x).strip()]
        if len(set(n.lower() for n in names)) != len(names):
            abort(400, "A folder name is listed twice")
        if any(n in (FROM_LEAD, TASK_FILES) for n in names):
            abort(400, f"“{FROM_LEAD}” and “{TASK_FILES}” are filled automatically")
        out[k] = names[:30]
    if not out["all"]:
        abort(400, "Keep at least one folder for every project")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"document_folders": out}})
    return jsonify(out)


# ---------------- block 2: drawing register and transmittals ----------------
@bp.put("/documents/<did>/status")
@api(None)
def drawing_status(did):
    """Status of the current revision of a drawing: work in progress -> for comment -> for approval -> approved /
    for construction. Older revisions are superseded automatically."""
    doc = t.get("documents", did)
    p = access(doc["project_id"], write=True)
    if doc["kind"] != "drawing":
        abort(400, "Only drawings carry a status")
    st = (request.get_json(force=True) or {}).get("status")
    if st not in DRAWING_STATUSES or st == "superseded":
        abort(400, f"Status must be one of: {', '.join(v for k, v in DRAWING_STATUSES.items() if k != 'superseded')}")
    vs = doc["versions"][:-1] + [{**doc["versions"][-1], "status": st, "status_at": t.now(), "status_by": g.user.get("name")}]
    upd = t.update("documents", did, {"versions": vs, "status": st})
    ev.log(doc["project_id"], "file", f"Drawing {doc['number']} {doc['current_rev']}: {DRAWING_STATUSES[st]}")
    if st in ("approved", "for_construction"):
        notify.send("drawing_approved", ev.managers(p), f"{doc['number']} {doc['name']} {doc['current_rev']} is {DRAWING_STATUSES[st].lower()} "
                    f"({p['name']})", f"/app/projects/{p['_id']}?tab=documents", project_id=doc["project_id"])
    return jsonify(present(upd))


@bp.get("/projects/<pid>/drawing-register")
@api(None)
def drawing_register(pid):
    access(pid)
    rows = []
    for doc in t.find("documents", {"project_id": pid, "kind": "drawing"}, sort=[("number", 1)]):
        cur = doc["versions"][-1]
        issued = [s for v in doc["versions"] for s in v.get("sent", [])]
        rows.append({"id": str(doc["_id"]), "number": doc.get("number"), "name": doc["name"], "discipline": doc.get("discipline"),
                     "scale": doc.get("scale"), "stage_name": doc.get("stage_name"), "rev": cur["rev"], "status": cur.get("status"),
                     "revisions": len(doc["versions"]), "last_issued": max((s["at"] for s in issued), default=None),
                     "last_issued_rev": next((v["rev"] for v in reversed(doc["versions"]) if v.get("sent")), None), "url": f"/api/files/{cur['file_key']}"})
    return jsonify({"drawings": serialize(rows), "statuses": DRAWING_STATUSES, "disciplines": DISCIPLINES})


def team_contacts(p):
    return {m["contact_id"]: m for m in p.get("team", []) if m.get("contact_id")}


@bp.get("/projects/<pid>/transmittals")
@api(None)
def list_transmittals(pid):
    p = access(pid)
    people = [{"contact_id": cid_, "name": m["name"], "role": m.get("project_role")} for cid_, m in team_contacts(p).items()]
    return jsonify({"transmittals": serialize(t.find("transmittals", {"project_id": pid}, sort=[("created_at", -1)])),
                    "purposes": TRANSMITTAL_PURPOSES, "people": people})


@bp.post("/projects/<pid>/transmittals")
@api(None)
def send_transmittal(pid):
    """Issue the current revision of chosen documents to people on the project (client, consultants, contractors),
    by email with the files attached. Those revisions are then kept for good."""
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    if d.get("purpose") not in TRANSMITTAL_PURPOSES:
        abort(400, f"Purpose: {', '.join(TRANSMITTAL_PURPOSES.values())}")
    people = team_contacts(p)
    to = list(dict.fromkeys(d.get("to") or []))
    if not to or any(c not in people for c in to):
        abort(400, "Send to people on the project team (client, consultants, contractors)")
    docs = []
    for did in dict.fromkeys(d.get("documents") or []):
        doc = db.documents.find_one({"_id": oid(did), "company_id": g.cid, "project_id": pid}) if len(str(did)) == 24 else None
        docs.append(doc or abort(400, "Choose documents of this project"))
    if not docs:
        abort(400, "Choose at least one document")
    number = t.next_number("TRN", "TRN")
    items = [{"document_id": str(x["_id"]), "number": x.get("number"), "name": x["name"], "rev": x["current_rev"], "kind": x["kind"],
              "stage_id": x.get("stage_id"), "file_key": x["versions"][-1]["file_key"]} for x in docs]
    recipients = []
    for cid_ in to:
        c = db.contacts.find_one({"_id": oid(cid_), "company_id": g.cid}) or {}
        recipients.append({"contact_id": cid_, "name": people[cid_]["name"], "role": people[cid_].get("project_role"), "email": c.get("email")})
    tr = t.insert("transmittals", {"number": number, "project_id": pid, "project_name": p["name"], "purpose": d["purpose"],
                                   "note": (d.get("note") or "").strip()[:1000] or None, "items": items, "to": recipients,
                                   "sent_by": g.uid, "sent_by_name": g.user.get("name"), "emailed": {}, "acknowledged": None})
    tid = str(tr["_id"])
    for x in docs:  # the issued revision is kept for good and shows where it went
        vs = x["versions"][:-1] + [{**x["versions"][-1], "sent": x["versions"][-1].get("sent", []) + [
            {"transmittal_id": tid, "number": number, "purpose": d["purpose"], "at": t.now(), "to": [r["name"] for r in recipients]}]}]
        db.documents.update_one({"_id": x["_id"]}, {"$set": {"versions": vs}})
    emailed = {}
    if d.get("email", True):
        files = []
        for it in items:
            try:
                with open(os.path.join(Config.UPLOAD_DIR, it["file_key"]), "rb") as fh:
                    files.append((f"{it['number'] or it['name']} {it['rev']}{os.path.splitext(it['file_key'])[1]}", fh.read()))
            except OSError:
                pass
        body = "\n".join([f"Transmittal {number} — {p['name']}", f"Purpose: {TRANSMITTAL_PURPOSES[d['purpose']]}", ""]
                         + [f"{it['number'] + ' ' if it['number'] else ''}{it['name']} — {it['rev']}" for it in items]
                         + ([f"\n{tr['note']}"] if tr["note"] else []) + [f"\nRegards,\n{g.user.get('name')}\n{g.company['name']}"])
        for r in recipients:
            emailed[r["contact_id"]] = notify.deliver(g.company, r["email"], f"Transmittal {number}: {p['name']}", body, files)
        tr = t.update("transmittals", tid, {"emailed": emailed})
    ev.log(pid, "file", f"Transmittal {number} ({TRANSMITTAL_PURPOSES[d['purpose']]}) to {', '.join(r['name'] for r in recipients)}: "
           + ", ".join(f"{it['number'] or it['name']} {it['rev']}" for it in items))
    notify.send("transmittal_sent", ev.managers(p), f"{number} sent to {', '.join(r['name'] for r in recipients)} ({len(items)} document(s), "
                f"{p['name']})", f"/app/projects/{pid}?tab=documents", project_id=pid)
    # the client got drawings of a stage: offer that stage's "Drawings issued to the client" check (an editor still ticks it)
    if any(r["role"] == "Client" for r in recipients):
        stages = {it["stage_id"] for it in items if it["kind"] == "drawing" and it["stage_id"]}
        fresh = db.projects.find_one({"_id": p["_id"]})
        changed = False
        for s in fresh.get("stages", []):
            if s["id"] in stages:
                for c in s.get("checklist", []):
                    if c["text"].lower().startswith("drawings issued") and not c.get("done"):
                        c["suggested"] = {"by": "transmittal", "number": number, "at": t.now().isoformat()}
                        changed = True
        if changed:
            db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": fresh["stages"]}})
    return jsonify(serialize(tr)), 201


@bp.post("/transmittals/<tid>/acknowledge")
@api(None)
def acknowledge(tid):
    tr = t.get("transmittals", tid)
    access(tr["project_id"], write=True)
    if tr.get("acknowledged"):
        abort(409, "Already acknowledged")
    d = request.get_json(force=True) or {}
    by = (d.get("by") or "").strip() or abort(400, "Who acknowledged it?")
    from .lead_money import a_date
    from ..services import sales
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "The date cannot be in the future")
    upd = t.update("transmittals", tid, {"acknowledged": {"by": by[:120], "date": day, "note": (d.get("note") or "").strip()[:300] or None,
                                                          "recorded_by": g.user.get("name")}})
    return jsonify(serialize(upd))
