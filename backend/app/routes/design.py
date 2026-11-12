"""Phase J blocks 5-6 — 360° room views and renders with comments; design options A / B / C (v4 §19 MVP).

* Views: a 360° panorama (equirectangular image, shown with Pannellum) or a render (flat image) per room. Shared with
  the client or kept internal. A comment is pinned on a spot (yaw / pitch on a 360°, x / y % on a render) by the team or
  the client in the portal. A comment becomes a task on a stage or a change request (Phase I), or is resolved.
* Design options: a decision with two to four options (A, B, C, D) side by side — images, description, extra price.
  Sent to the client, who approves one (or asks for changes) in the portal. Approving: a linked selection records the
  choice (method Portal), an option with an extra price becomes a draft change order for the PM to send.
Who: the documents area (Owner, PM, Designer) on projects they are on; the client of the project in the portal.
"""
from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal, can
from ..services import notify, project_events as ev, sales
from .lead_steps import num
from .projects import load, member

bp = Blueprint("design", __name__)
VIEW_KINDS = {"360": "360° view", "render": "Render"}
LABELS = "ABCD"


def access(pid, write=False):
    if not (can("documents") or can("projects") or can("site")):
        abort(403, "Your role cannot view designs")
    p = load(pid)
    if write and not (can("documents", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change designs on this project")
    return p


def file_of(key):
    f = db.files.find_one({"company_id": g.cid, "key": key}) if key else None
    return f or abort(400, "Upload the image first")


def comment_out(c):
    return {**c, "at": c["at"].isoformat() if hasattr(c.get("at"), "isoformat") else c.get("at")}


def view_out(v, client=False):
    d = serialize(v)
    d["url"] = f"/api/files/{v['file_key']}"
    d["kind_label"] = VIEW_KINDS[v["kind"]]
    d["comments"] = [comment_out(c) for c in v.get("comments", []) if not client or c.get("side") == "client" or c.get("shared")]
    d["open"] = sum(1 for c in v.get("comments", []) if c["status"] == "open")
    return d


def clean_view(d, v=None):
    ch = {}
    if "kind" in d or v is None:
        ch["kind"] = d.get("kind") if d.get("kind") in VIEW_KINDS else abort(400, "Kind: 360 or render")
    if "file_key" in d or v is None:
        f = file_of(d.get("file_key"))
        ch.update(file_key=f["key"], file_name=f["name"])
    if "title" in d or v is None:
        ch["title"] = (d.get("title") or "").strip()[:120] or abort(400, "Title is required")
    if "room" in d:
        ch["room"] = (d.get("room") or "").strip()[:80] or None
    if "shared" in d:
        ch["shared"] = bool(d["shared"])
    return ch


def spot(d, kind):
    """Where the comment is pinned."""
    if kind == "360":
        yaw, pitch = d.get("yaw"), d.get("pitch")
        ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (yaw, pitch))
        if not ok or not -180 <= yaw <= 360 or not -90 <= pitch <= 90:
            abort(400, "Click a spot on the view (yaw -180..360, pitch -90..90)")
        return {"yaw": round(float(yaw), 2), "pitch": round(float(pitch), 2)}
    x, y = d.get("x"), d.get("y")
    ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y))
    if not ok or not 0 <= x <= 100 or not 0 <= y <= 100:
        abort(400, "Click a spot on the render (x and y 0-100 %)")
    return {"x": round(float(x), 2), "y": round(float(y), 2)}


# ============================== views (team) ==============================
@bp.get("/projects/<pid>/views")
@api(None)
def list_views(pid):
    access(pid)
    q = {"project_id": pid}
    if request.args.get("room"):
        q["room"] = request.args["room"]
    return jsonify([view_out(v) for v in t.find("views", q, sort=[("room", 1), ("created_at", 1)])])


@bp.post("/projects/<pid>/views")
@api(None)
def add_view(pid):
    p = access(pid, write=True)
    v = t.insert("views", {"project_id": pid, "project_name": p["name"], "room": None, "shared": False, "comments": [],
                           **clean_view(request.get_json(force=True) or {})})
    ev.log(pid, "file", f"{VIEW_KINDS[v['kind']]} added: {v['title']}" + (f" ({v['room']})" if v.get("room") else ""))
    return jsonify(view_out(v)), 201


def load_view(vid, write=False):
    v = t.get("views", vid)
    p = access(v["project_id"], write)
    return v, p


@bp.put("/views/<vid>")
@api(None)
def edit_view(vid):
    v, p = load_view(vid, True)
    return jsonify(view_out(t.update("views", vid, clean_view(request.get_json(force=True) or {}, v))))


@bp.delete("/views/<vid>")
@api(None)
def delete_view(vid):
    v, p = load_view(vid, True)
    if any(c.get("task_id") or c.get("co_id") for c in v.get("comments", [])):
        abort(409, "A comment on this view became a task or a change request; the view is kept")
    db.views.delete_one({"_id": v["_id"]})
    return jsonify({"ok": True})


def add_comment(v, d, side, author):
    text = (d.get("text") or "").strip()[:1000] or abort(400, "Write the comment")
    c = {"id": t.sid(), "text": text, **spot(d, v["kind"]), "side": side, "author": author, "at": t.now(), "status": "open",
         "task_id": None, "co_id": None, "shared": side == "client" or bool(d.get("shared"))}
    db.views.update_one({"_id": v["_id"]}, {"$push": {"comments": c}, "$set": {"updated_at": t.now()}})
    return c


@bp.post("/views/<vid>/comments")
@api(None)
def team_comment(vid):
    v, p = load_view(vid)
    if not (can("documents", True) or can("projects", True) or can("site", True)):
        abort(403, "Your role cannot comment")
    c = add_comment(v, request.get_json(force=True) or {}, "team", g.user["name"])
    return jsonify(comment_out(c)), 201


def find_comment(v, cid_):
    return next((c for c in v.get("comments", []) if c["id"] == cid_), None) or abort(404, "Comment not found")


def set_comment(v, cid_, ch):
    db.views.update_one({"_id": v["_id"], "comments.id": cid_}, {"$set": {f"comments.$.{k}": val for k, val in ch.items()}})


@bp.post("/views/<vid>/comments/<cid_>/resolve")
@api(None)
def resolve_comment(vid, cid_):
    v, p = load_view(vid, True)
    c = find_comment(v, cid_)
    set_comment(v, cid_, {"status": "open" if c["status"] == "resolved" else "resolved", "resolved_by": g.user["name"]})
    return jsonify(view_out(t.get("views", vid)))


@bp.post("/views/<vid>/comments/<cid_>/task")
@api(None)
def comment_to_task(vid, cid_):
    """The comment becomes a task on a stage (Owner / PM / Designer who can edit the stage)."""
    from .projects import find_stage, require_edit, clean_task, save_stages
    v, p = load_view(vid, True)
    c = find_comment(v, cid_)
    if c.get("task_id"):
        abort(409, "This comment is already a task")
    d = request.get_json(force=True) or {}
    stage = find_stage(p, d.get("stage_id") or abort(400, "Choose the stage"))
    require_edit(p, stage)
    task = {"id": t.sid(), "status": "todo", "progress": 0, "depends_on": [], "links": [], "assignee_id": None, "assignee_name": None,
            "priority": "normal", "checklist": [], "files": [],
            "source": {"kind": "view", "view_id": vid, "comment_id": cid_}}
    task.update(clean_task({"title": d.get("title") or f"{v.get('room') + ': ' if v.get('room') else ''}{c['text'][:100]}",
                            "start": d.get("start") or sales.today(), "end": d.get("end") or d.get("start") or sales.today(),
                            "notes": f"From a comment on {v['title']}: {c['text']}", **({"assignee_id": d["assignee_id"]} if d.get("assignee_id") else {})}, p))
    stage.setdefault("tasks", []).append(task)
    save_stages(str(p["_id"]), p)
    set_comment(v, cid_, {"task_id": task["id"], "task_title": task["title"], "status": "resolved"})
    return jsonify(view_out(t.get("views", vid))), 201


@bp.post("/views/<vid>/comments/<cid_>/change")
@api(None)
def comment_to_change(vid, cid_):
    from .insights import make_request
    v, p = load_view(vid)
    if not (can("change_orders") or can("site", True) or can("documents", True)):
        abort(403, "Your role cannot ask for changes")
    c = find_comment(v, cid_)
    if c.get("co_id"):
        abort(409, "This comment is already a change request")
    d = request.get_json(force=True) or {}
    co = make_request(p, {"title": d.get("title") or c["text"][:150], "description": f"From a comment on {v['title']}"
                          + (f" ({v['room']})" if v.get("room") else "") + f" by {c['author']}: {c['text']}", "stage_id": d.get("stage_id")},
                      c["author"] if c["side"] == "client" else g.user["name"], "client" if c["side"] == "client" else "site")
    set_comment(v, cid_, {"co_id": str(co["_id"]), "co_number": co["number"], "status": "resolved"})
    return jsonify(view_out(t.get("views", vid))), 201


# ============================== views (portal) ==============================
def portal_p(pid):
    from .site_reports import portal_project
    return portal_project(pid)


@bp.get("/portal/projects/<pid>/views")
@portal
def portal_views(pid):
    portal_p(pid)
    return jsonify([view_out(v, client=True) for v in db.views.find({"company_id": g.cid, "project_id": pid, "shared": True}).sort("room", 1)])


@bp.post("/portal/views/<vid>/comments")
@portal
def portal_comment(vid):
    v = db.views.find_one({"_id": oid(vid), "company_id": g.cid, "shared": True}) or abort(404, "view not found")
    p = portal_p(v["project_id"])
    c = add_comment(v, request.get_json(force=True) or {}, "client", g.user["name"])
    notify.send("view_comment", list(dict.fromkeys(ev.managers(p) + [m["user_id"] for m in p.get("team", []) if m.get("project_role") in ("Interior Designer", "Architect") and m.get("user_id")])),
                f"{g.user['name']} commented on {v['title']} ({p['name']}): {c['text'][:140]}", f"/app/projects/{p['_id']}?tab=design",
                project_id=str(p["_id"]), skip_self=False)
    return jsonify(comment_out(c)), 201


# ============================== design options ==============================
def clean_options(rows, selection):
    out = []
    for i, r in enumerate((rows or [])[:4]):
        name = (r.get("name") or "").strip()[:120] or abort(400, f"Option {LABELS[i]} needs a name")
        images = []
        for key in dict.fromkeys((im.get("key") if isinstance(im, dict) else im) for im in r.get("images") or []):
            f = file_of(key)
            images.append({"key": f["key"], "name": f["name"]})
        raw = r.get("price")
        credit = isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw < 0  # a cheaper option
        price = -(num(-raw, f"Extra price of option {LABELS[i]}") or 0) if credit else (num(raw, f"Extra price of option {LABELS[i]}") or 0)
        sel_opt = r.get("selection_option_id")
        if sel_opt and not (selection and any(o["id"] == sel_opt for o in selection.get("options", []))):
            abort(400, f"Option {LABELS[i]}: the linked selection option was not found")
        out.append({"id": r.get("id") or t.sid(), "label": LABELS[i], "name": name, "description": (r.get("description") or "").strip()[:2000] or None,
                    "images": images[:8], "price": round(price, 2), "selection_option_id": sel_opt or None})
    if len(out) < 2:
        abort(400, "Give at least two options (A and B)")
    return out


def design_out(dsn, client=False):
    d = serialize(dsn)
    for o in d["options"]:
        for im in o["images"]:
            im["url"] = f"/api/files/{im['key']}"
    return d


def clean_design(d, p, dsn=None):
    ch = {}
    if "title" in d or dsn is None:
        ch["title"] = (d.get("title") or "").strip()[:150] or abort(400, "What is the decision? (e.g. Living room — wall finish)")
    for k, n in (("room", 80), ("note", 2000)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or None
    if "due_date" in d:
        from .lead_money import a_date
        ch["due_date"] = a_date(d.get("due_date"), "Decide by", required=False)
    sel = None
    if "selection_id" in d:
        if d["selection_id"]:
            sel = db.selections.find_one({"_id": oid(d["selection_id"]), "company_id": g.cid, "project_id": str(p["_id"])}) or abort(400, "Selection not found on this project")
            ch.update(selection_id=d["selection_id"], selection_item=sel["item"])
        else:
            ch.update(selection_id=None, selection_item=None)
    elif dsn and dsn.get("selection_id"):
        sel = db.selections.find_one({"_id": oid(dsn["selection_id"])})
    if "options" in d or dsn is None:
        ch["options"] = clean_options(d.get("options"), sel)
    return ch


@bp.get("/projects/<pid>/design-options")
@api(None)
def list_designs(pid):
    access(pid)
    return jsonify([design_out(x) for x in t.find("design_options", {"project_id": pid}, sort=[("created_at", -1)])])


@bp.post("/projects/<pid>/design-options")
@api(None)
def add_design(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    dsn = t.insert("design_options", {"project_id": pid, "project_name": p["name"], "room": None, "note": None, "due_date": None,
                                      "selection_id": None, "selection_item": None, "status": "draft", "approved_option_id": None,
                                      "client_comment": None, "co_id": None, **clean_design(d, p)})
    return jsonify(design_out(dsn)), 201


def load_design(did, write=True):
    dsn = t.get("design_options", did)
    return dsn, access(dsn["project_id"], write)


@bp.put("/design-options/<did>")
@api(None)
def edit_design(did):
    dsn, p = load_design(did)
    if dsn["status"] == "approved":
        abort(409, "The client approved an option; make a new decision for a change")
    ch = clean_design(request.get_json(force=True) or {}, p, dsn)
    if dsn["status"] in ("sent", "changes_requested") and "options" in ch:
        ch["status"] = "draft"  # changed options are sent again
    return jsonify(design_out(t.update("design_options", did, ch)))


@bp.delete("/design-options/<did>")
@api(None)
def delete_design(did):
    dsn, p = load_design(did)
    if dsn["status"] == "approved":
        abort(409, "An approved decision is kept")
    db.design_options.delete_one({"_id": dsn["_id"]})
    return jsonify({"ok": True})


@bp.post("/design-options/<did>/send")
@api(None)
def send_design(did):
    dsn, p = load_design(did)
    if dsn["status"] == "approved":
        abort(409, "Already approved")
    client = next((m for m in p.get("team", []) if m.get("project_role") == "Client" and m.get("contact_id")), None) or abort(409, "Add the client to the project team first")
    c = db.contacts.find_one({"_id": oid(client["contact_id"]), "company_id": g.cid}) or {}
    body = "\n".join([f"Dear {c.get('name', 'Client')},", "", f"Please choose for {dsn['title']} ({p['name']}):"]
                     + [f"  {o['label']}. {o['name']}" + (f" (+{o['price']:g})" if o["price"] else "") for o in dsn["options"]]
                     + ["", "Open your portal to see the options side by side and approve one.", f"\nRegards,\n{g.company['name']}"])
    result = notify.deliver(g.company, c.get("email"), f"Design options: {dsn['title']} — {p['name']}", body)
    from ..services import messaging
    wa = messaging.notify_contact(c, f"{g.company['name']}: design options for {dsn['title']} are in your portal — please approve one.")
    upd = t.update("design_options", did, {"status": "sent", "sent_at": t.now(), "emailed": result, "whatsapp": wa})
    ev.log(dsn["project_id"], "file", f"Design options sent: {dsn['title']} ({len(dsn['options'])} options)")
    return jsonify(design_out(upd))


# ---------------- portal ----------------
@bp.get("/portal/projects/<pid>/design-options")
@portal
def portal_designs(pid):
    portal_p(pid)
    rows = db.design_options.find({"company_id": g.cid, "project_id": pid, "status": {"$in": ["sent", "approved", "changes_requested"]}}).sort("created_at", -1)
    return jsonify([design_out(x, client=True) for x in rows])


def portal_design(did):
    from .site_reports import is_client
    dsn = db.design_options.find_one({"_id": oid(did), "company_id": g.cid}) or abort(404, "not found")
    p = portal_p(dsn["project_id"])
    if not is_client(p):
        abort(403, "Only the client decides")
    if dsn["status"] != "sent":
        abort(409, "This decision is not waiting for you")
    return dsn, p


@bp.post("/portal/design-options/<did>/approve")
@portal
def portal_approve(did):
    dsn, p = portal_design(did)
    d = request.get_json(force=True) or {}
    opt = next((o for o in dsn["options"] if o["id"] == d.get("option_id")), None) or abort(400, "Choose one of the options")
    comment = (d.get("comment") or "").strip()[:1000] or None
    ch = {"status": "approved", "approved_option_id": opt["id"], "approved_label": opt["label"], "approved_name": opt["name"],
          "client_comment": comment, "decided_at": t.now(), "decided_by": g.user["name"]}
    pid = str(p["_id"])
    if dsn.get("selection_id") and opt.get("selection_option_id"):  # the linked selection records the choice
        from .selections import choose_option
        s = db.selections.find_one({"_id": oid(dsn["selection_id"]), "company_id": g.cid})
        sopt = s and next((o for o in s.get("options", []) if o["id"] == opt["selection_option_id"]), None)
        if s and sopt and s["status"] in ("open", "options_sent"):
            choose_option(s, p, sopt, {"name": g.user["name"], "method": "Portal", "date": sales.today(), "note": f"Design option {opt['label']}"})
            ch["selection_chosen"] = True
    if opt["price"]:  # the extra becomes a draft change order for the PM to check and send
        from .change_orders import new_co
        from .insights import open_stage
        st = open_stage(p)
        co = new_co(p, {"stage_id": st["id"], "title": f"{dsn['title']}: option {opt['label']} — {opt['name']}", "reason": "client_request",
                        "description": f"Client approved design option {opt['label']} ({opt['name']})" + (f": {comment}" if comment else ""),
                        "lines": [{"description": f"Design option {opt['label']}: {opt['name']}", "qty": 1, "unit": "lot",
                                   "price_rate": opt["price"], "credit": opt["price"] < 0}]},
                    {"requested": {"kind": "client", "name": g.user["name"], "at": t.now(), "contact_id": g.contact_id}})
        ch.update(co_id=str(co["_id"]), co_number=co["number"])
    upd = t.update("design_options", did, ch)
    text = f"{p['name']}: {g.user['name']} approved option {opt['label']} ({opt['name']}) for {dsn['title']}" + (f" — {ch['co_number']} drafted" if ch.get("co_number") else "")
    ev.log(pid, "file", text)
    notify.send("design_option", ev.managers(p), text, f"/app/projects/{pid}?tab=design", project_id=pid, skip_self=False)
    return jsonify(design_out(upd))


@bp.post("/portal/design-options/<did>/changes")
@portal
def portal_changes(did):
    dsn, p = portal_design(did)
    comment = ((request.get_json(force=True) or {}).get("comment") or "").strip()[:1000] or abort(400, "Say what you would like changed")
    upd = t.update("design_options", did, {"status": "changes_requested", "client_comment": comment, "decided_at": t.now(), "decided_by": g.user["name"]})
    notify.send("design_option", ev.managers(p), f"{p['name']}: {g.user['name']} asked for changes to {dsn['title']}: {comment[:140]}",
                f"/app/projects/{p['_id']}?tab=design", project_id=str(p["_id"]), skip_self=False)
    return jsonify(design_out(upd))
