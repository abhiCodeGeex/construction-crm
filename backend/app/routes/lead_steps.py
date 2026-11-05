"""Lead journey step 3 (C+2): site-visit appointments with reminders, report and cost; room-by-room and plot
measurements; lead files (photos, client drawings, brief, proposals)."""
import os
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..config import Config
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, sales
from ..services.defaults import VISIT_KINDS, SITE_CHECKLIST, OPENING_KINDS, FILE_FOLDERS
from ..services.sales import load_lead, log

bp = Blueprint("lead_steps", __name__)


def open_lead(_id):
    from .leads import editable
    lead = load_lead(_id)
    editable(lead)
    return lead


def num(v, field, required=False, positive=False):
    if v in (None, ""):
        if required:
            abort(400, f"{field} is required")
        return None
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or (positive and v == 0):
        abort(400, f"{field} must be a {'positive ' if positive else ''}number")
    return float(v)


def when(v):
    """Appointment time from the browser (ISO, in UTC)."""
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        abort(400, "Choose the date and time of the visit")
    return dt.replace(tzinfo=None) - (dt.utcoffset() or timedelta(0)) if dt.tzinfo else dt


def staff_list(ids):
    if not ids:
        abort(400, "Choose who goes on the visit")
    out = []
    for uid in dict.fromkeys(ids):
        u = db.users.find_one({"_id": oid(uid), "company_id": g.cid, "kind": "staff", "active": {"$ne": False}})
        if not u:
            abort(400, "Visit staff must be active staff users")
        out.append({"id": str(u["_id"]), "name": u["name"]})
    return out


def fmt(dt):
    return dt.strftime("%d %b %Y, %H:%M UTC")


def client_email(lead, subject, body):
    """Email the enquirer when email is set up; the result is logged on the lead either way."""
    c = db.contacts.find_one({"_id": oid(lead.get("contact_id")), "company_id": g.cid}, {"email": 1, "name": 1})
    result = notify.deliver(g.company, (c or {}).get("email"), subject, body)
    log(str(lead["_id"]), "email", f"Email to client “{subject}”: {result}", outcome=result, auto=True)
    return result


# ---------------- appointments ----------------
def present_visit(v):
    data = serialize(v)
    data["missed"] = v["status"] in ("scheduled", "confirmed") and v["at"] + timedelta(minutes=v.get("duration_min") or 60) < t.now()
    data["report_late"] = v["status"] == "done" and not (v.get("report") or {}).get("submitted_at") and \
        v.get("done_at") and v["done_at"] < t.now() - timedelta(hours=24)
    return data


@bp.get("/leads/<_id>/visits")
@api("leads")
def list_visits(_id):
    load_lead(_id)
    return jsonify({"visits": [present_visit(v) for v in t.find("lead_visits", {"lead_id": _id}, sort=[("at", -1)])],
                    "site_checklist": SITE_CHECKLIST, "kinds": VISIT_KINDS})


@bp.post("/leads/<_id>/visits")
@api("leads")
def book_visit(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    kind = d.get("kind", "site_visit")
    if kind not in VISIT_KINDS:
        abort(400, "Kind must be a site visit or a meeting")
    at = when(d.get("at"))
    duration = int(num(d.get("duration_min"), "Duration", positive=True) or 60)
    staff = staff_list(d.get("staff_ids") or [])
    address = (d.get("address") or lead.get("location") or "").strip()
    if not address:
        abort(400, "Enter the address of the visit")
    v = t.insert("lead_visits", {"lead_id": _id, "lead_title": lead["title"], "kind": kind, "at": at, "duration_min": duration,
                                 "staff": staff, "address": address, "notes": (d.get("notes") or "").strip() or None,
                                 "status": "scheduled", "history": [], "report": None, "site_checklist": [], "cost": None})
    what = "Site visit" if kind == "site_visit" else "Meeting"
    log(_id, "visit", f"{what} booked for {fmt(at)} at {address} — {', '.join(s['name'] for s in staff)}", visit_id=str(v["_id"]))
    notify.send("visit_assigned", [s["id"] for s in staff], f"{what} for {lead['title']} on {fmt(at)} at {address}",
                f"/app/leads/{_id}", _id)
    if d.get("email_client"):
        client_email(lead, f"{what} confirmed — {fmt(at)}",
                     f"Dear {lead.get('contact_name')},\n\nThis confirms our {what.lower()} for {lead['title']} on {fmt(at)} at "
                     f"{address}. Our team: {', '.join(s['name'] for s in staff)}.\n\nRegards,\n{g.company['name']}")
    return jsonify(present_visit(v)), 201


def load_visit(vid):
    v = t.get("lead_visits", vid)
    load_lead(v["lead_id"])
    return v


@bp.put("/visits/<vid>")
@api("leads")
def edit_visit(vid):
    """Staff, address, duration, notes. Changing the time is a reschedule (needs a reason)."""
    v = load_visit(vid)
    lead = open_lead(v["lead_id"])
    if v["status"] not in ("scheduled", "confirmed"):
        abort(409, f"This visit is {v['status'].replace('_', ' ')}; it can no longer be changed")
    d = request.get_json(force=True) or {}
    changes, notes = {}, []
    if "staff_ids" in d:
        staff = staff_list(d["staff_ids"])
        if [s["id"] for s in staff] != [s["id"] for s in v["staff"]]:
            changes["staff"] = staff
            notes.append(f"staff {', '.join(s['name'] for s in v['staff'])} → {', '.join(s['name'] for s in staff)}")
            added = [s["id"] for s in staff if s["id"] not in {x["id"] for x in v["staff"]}]
            notify.send("visit_assigned", added, f"Visit for {lead['title']} on {fmt(v['at'])} at {v['address']}",
                        f"/app/leads/{v['lead_id']}", v["lead_id"])
    if d.get("address") and d["address"].strip() != v["address"]:
        changes["address"] = d["address"].strip()
        notes.append(f"address {v['address']} → {changes['address']}")
    if "duration_min" in d:
        dur = int(num(d["duration_min"], "Duration", required=True, positive=True))
        if dur != v["duration_min"]:
            changes["duration_min"] = dur
            notes.append(f"duration {v['duration_min']} → {dur} min")
    if "notes" in d:
        changes["notes"] = (d["notes"] or "").strip() or None
    if not changes:
        return jsonify(present_visit(v))
    if notes:
        log(v["lead_id"], "visit", "Visit changed: " + "; ".join(notes), visit_id=vid)
    return jsonify(present_visit(t.update("lead_visits", vid, changes)))


@bp.post("/visits/<vid>/reschedule")
@api("leads")
def reschedule(vid):
    v = load_visit(vid)
    lead = open_lead(v["lead_id"])
    if v["status"] not in ("scheduled", "confirmed"):
        abort(409, f"This visit is {v['status'].replace('_', ' ')}")
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    if not reason:
        abort(400, "Say why the visit is rescheduled")
    at = when(d.get("at"))
    if at == v["at"]:
        abort(400, "Choose a different time")
    hist = {"at": t.now(), "by": g.user.get("name"), "from": v["at"], "to": at, "reason": reason, "action": "rescheduled"}
    upd = t.update("lead_visits", vid, {"at": at, "status": "scheduled"}, raw={"$push": {"history": hist}})
    log(v["lead_id"], "visit", f"Visit rescheduled {fmt(v['at'])} → {fmt(at)} — {reason}", visit_id=vid)
    notify.send("visit_changed", [s["id"] for s in v["staff"]] + [lead.get("owner_id")],
                f"Visit for {lead['title']} moved to {fmt(at)} ({reason})", f"/app/leads/{v['lead_id']}", v["lead_id"])
    if d.get("email_client"):
        client_email(lead, f"Visit rescheduled — {fmt(at)}", f"Dear {lead.get('contact_name')},\n\nOur visit for {lead['title']} "
                     f"has moved to {fmt(at)} at {v['address']}.\n\nRegards,\n{g.company['name']}")
    return jsonify(present_visit(upd))


@bp.post("/visits/<vid>/status")
@api("leads")
def visit_status(vid):
    """scheduled -> confirmed (client confirmed) -> done / no_show / cancelled (with a reason)."""
    v = load_visit(vid)
    lead = open_lead(v["lead_id"])
    d = request.get_json(force=True) or {}
    status, reason = d.get("status"), (d.get("reason") or "").strip()
    allowed = {"scheduled": ("confirmed", "done", "no_show", "cancelled"), "confirmed": ("done", "no_show", "cancelled")}
    if status not in allowed.get(v["status"], ()):
        abort(409, f"A {v['status'].replace('_', ' ')} visit cannot become {str(status).replace('_', ' ')}")
    if status in ("no_show", "cancelled") and not reason:
        abort(400, "Give the reason")
    if status == "done" and v["at"] > t.now():
        abort(400, "The visit has not happened yet")
    changes = {"status": status}
    if status == "done":
        changes["done_at"] = t.now()
    hist = {"at": t.now(), "by": g.user.get("name"), "action": status, "reason": reason or None}
    upd = t.update("lead_visits", vid, changes, raw={"$push": {"history": hist}})
    label = {"confirmed": "confirmed by the client", "done": "done", "no_show": "missed (no-show)", "cancelled": "cancelled"}[status]
    log(v["lead_id"], "visit", f"Visit of {fmt(v['at'])} {label}" + (f" — {reason}" if reason else ""), visit_id=vid)
    if status == "done":
        db.leads.update_one({"_id": lead["_id"]}, {"$set": {"last_activity_at": t.now(),
                                                            **({} if lead.get("first_response_at") else {"first_response_at": t.now()})}})
    if status in ("no_show", "cancelled"):
        notify.send("visit_changed" if status == "cancelled" else "visit_missed",
                    [s["id"] for s in v["staff"]] + [lead.get("owner_id")] + (notify.managers() if status == "no_show" else []),
                    f"Visit for {lead['title']} on {fmt(v['at'])} {label}: {reason}", f"/app/leads/{v['lead_id']}", v["lead_id"])
    return jsonify(present_visit(upd))


@bp.put("/visits/<vid>/report")
@api("leads")
def visit_report(vid):
    """Findings, risks, recommendations, the site condition checklist and what the visit cost."""
    v = load_visit(vid)
    lead = open_lead(v["lead_id"])
    if v["status"] != "done":
        abort(409, "Mark the visit as done before writing its report")
    d = request.get_json(force=True) or {}
    findings = (d.get("findings") or "").strip()
    if not findings:
        abort(400, "Write what you found on site")
    checklist = []
    for row in d.get("site_checklist") or []:
        if row.get("item") not in SITE_CHECKLIST:
            abort(400, f"Unknown checklist item: {row.get('item')}")
        if row.get("value") not in ("yes", "no", "na"):
            abort(400, f"Answer yes, no or n/a for: {row['item']}")
        checklist.append({"item": row["item"], "value": row["value"], "note": (row.get("note") or "").strip() or None})
    c = d.get("cost") or {}
    cost = {"travel": num(c.get("travel"), "Travel") or 0, "staff_hours": num(c.get("staff_hours"), "Staff hours") or 0,
            "hourly_rate": num(c.get("hourly_rate"), "Hourly rate") or 0, "other": num(c.get("other"), "Other cost") or 0}
    cost["total"] = round(cost["travel"] + cost["staff_hours"] * cost["hourly_rate"] + cost["other"], 2)
    first = not (v.get("report") or {}).get("submitted_at")
    report = {"findings": findings, "risks": (d.get("risks") or "").strip() or None,
              "recommendations": (d.get("recommendations") or "").strip() or None,
              "submitted_at": (v.get("report") or {}).get("submitted_at") or t.now(), "by": g.user.get("name"),
              "updated_at": t.now()}
    upd = t.update("lead_visits", vid, {"report": report, "site_checklist": checklist, "cost": cost})
    sync_visit_expense(lead, upd)
    log(v["lead_id"], "visit", f"Visit report {'submitted' if first else 'updated'}: {findings[:140]}"
        + (f" · cost {cost['total']:,.0f}" if cost["total"] else ""), visit_id=vid)
    if first:
        notify.send("visit_report", [lead.get("owner_id")], f"Visit report for {lead['title']}: {findings[:100]}",
                    f"/app/leads/{v['lead_id']}", v["lead_id"])
    return jsonify(present_visit(upd))


def sync_visit_expense(lead, v):
    """The visit's cost is pre-sales spend on the lead (one expense row per visit, kept in step)."""
    total = (v.get("cost") or {}).get("total") or 0
    q = {"company_id": g.cid, "lead_id": str(lead["_id"]), "visit_id": str(v["_id"])}
    if total:
        db.lead_expenses.update_one(q, {"$set": {"category": "Site visit travel", "amount": total, "date": v["at"].date().isoformat(),
                                                 "note": f"Site visit {fmt(v['at'])}", "updated_at": t.now()},
                                        "$setOnInsert": {"created_at": t.now(), "created_by": g.uid}}, upsert=True)
    else:
        db.lead_expenses.delete_one(q)


# ---------------- measurements ----------------
def room_calc(r, unit):
    """Floor, ceiling, wall and net wall area (less doors and windows) and perimeter, in the lead's unit."""
    L, W, H = r["length"], r["width"], r.get("height") or 0
    openings = sum((o["width"] * o["height"] * o["count"]) for o in r.get("openings") or [])
    wall = 2 * (L + W) * H
    return {"floor_area": round(L * W, 2), "ceiling_area": round(L * W, 2), "perimeter": round(2 * (L + W), 2),
            "wall_area": round(wall, 2), "net_wall_area": round(max(0.0, wall - openings), 2),
            "openings_area": round(openings, 2), "area_unit": "sqft" if unit == "ft" else "sqm"}


def clean_room(d):
    name = (d.get("name") or "").strip()
    if not name:
        abort(400, "Name the room (e.g. Living, Kitchen, Bedroom 1)")
    room = {"name": name, "length": num(d.get("length"), "Length", required=True, positive=True),
            "width": num(d.get("width"), "Width", required=True, positive=True),
            "height": num(d.get("height"), "Height"), "notes": (d.get("notes") or "").strip() or None, "openings": []}
    for o in d.get("openings") or []:
        if o.get("kind") not in OPENING_KINDS:
            abort(400, "An opening is a door, window or opening")
        room["openings"].append({"kind": o["kind"], "width": num(o.get("width"), "Opening width", required=True, positive=True),
                                 "height": num(o.get("height"), "Opening height", required=True, positive=True),
                                 "count": int(num(o.get("count"), "Count", positive=True) or 1)})
    return room


def measurements(lead):
    m = dict(lead.get("measurements") or {})
    m.setdefault("unit", "ft")
    m.setdefault("rooms", [])
    m.setdefault("plot", {})
    return m


def present_measurements(m):
    rooms = [{**r, **room_calc(r, m["unit"])} for r in m["rooms"]]
    totals = {k: round(sum(r[k] for r in rooms), 2) for k in ("floor_area", "wall_area", "net_wall_area", "perimeter")}
    return serialize({**m, "rooms": rooms, "totals": totals})


def save_measurements(lead, m, text):
    m["updated_at"], m["updated_by"] = t.now(), g.user.get("name")
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"measurements": m, "updated_at": t.now()}})
    log(str(lead["_id"]), "measurement", text)
    return jsonify(present_measurements(m))


@bp.get("/leads/<_id>/measurements")
@api("leads")
def get_measurements(_id):
    return jsonify(present_measurements(measurements(load_lead(_id))))


@bp.put("/leads/<_id>/measurements/unit")
@api("leads")
def set_unit(_id):
    lead = open_lead(_id)
    unit = (request.get_json(force=True) or {}).get("unit")
    if unit not in ("ft", "m"):
        abort(400, "Unit must be feet or metres")
    m = measurements(lead)
    if m["rooms"] and unit != m["unit"]:
        abort(409, "Rooms are already measured in another unit; change them one by one or remove them first")
    m["unit"] = unit
    return save_measurements(lead, m, f"Measurement unit set to {'feet' if unit == 'ft' else 'metres'}")


@bp.post("/leads/<_id>/rooms")
@api("leads")
def add_room(_id):
    lead = open_lead(_id)
    m = measurements(lead)
    room = {"id": t.sid(), **clean_room(request.get_json(force=True) or {})}
    if any(r["name"].lower() == room["name"].lower() for r in m["rooms"]):
        abort(409, f"A room called {room['name']} is already measured")
    m["rooms"].append(room)
    c = room_calc(room, m["unit"])
    size = f"{room['length']:g} × {room['width']:g}" + (f" × {room['height']:g}" if room.get("height") else "")
    return save_measurements(lead, m, f"Measured {room['name']}: {size} {m['unit']} = {c['floor_area']:g} {c['area_unit']} floor")


@bp.put("/leads/<_id>/rooms/<rid>")
@api("leads")
def edit_room(_id, rid):
    lead = open_lead(_id)
    m = measurements(lead)
    i = next((i for i, r in enumerate(m["rooms"]) if r["id"] == rid), None)
    if i is None:
        abort(404, "room not found")
    old, new = m["rooms"][i], {"id": rid, **clean_room(request.get_json(force=True) or {})}
    if any(r["name"].lower() == new["name"].lower() and r["id"] != rid for r in m["rooms"]):
        abort(409, f"A room called {new['name']} is already measured")
    diff = [f"{k} {old.get(k) if old.get(k) is not None else '—'} → {new.get(k) if new.get(k) is not None else '—'}"
            for k in ("name", "length", "width", "height") if old.get(k) != new.get(k)]
    if old.get("openings") != new["openings"]:
        diff.append(f"openings {len(old.get('openings') or [])} → {len(new['openings'])}")
    if old.get("notes") != new.get("notes"):
        diff.append("notes")
    if not diff:
        return jsonify(present_measurements(m))
    m["rooms"][i] = new
    return save_measurements(lead, m, f"Changed {old['name']}: " + "; ".join(diff))


@bp.delete("/leads/<_id>/rooms/<rid>")
@api("leads")
def delete_room(_id, rid):
    lead = open_lead(_id)
    m = measurements(lead)
    room = next((r for r in m["rooms"] if r["id"] == rid), None)
    if not room:
        abort(404, "room not found")
    used = db.estimates.count_documents({"company_id": g.cid, "lead_id": _id, "lines.room_id": rid,
                                         "status": {"$in": ["draft", "pending_approval", "approved"]}})
    if used:
        abort(409, f"{room['name']} is used by an estimate; remove it from the estimate first")
    m["rooms"] = [r for r in m["rooms"] if r["id"] != rid]
    db.lead_files.update_many({"company_id": g.cid, "lead_id": _id, "room_id": rid}, {"$set": {"room_id": None, "room": None}})
    return save_measurements(lead, m, f"Removed room {room['name']}")


PLOT_FIELDS = {"area": "Plot area", "frontage": "Frontage", "depth": "Depth", "setback_front": "Front setback",
               "setback_rear": "Rear setback", "setback_sides": "Side setbacks", "floors": "Floors allowed"}


@bp.put("/leads/<_id>/plot")
@api("leads")
def set_plot(_id):
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    m = measurements(lead)
    old = m.get("plot") or {}
    plot = {k: num(d.get(k), label) for k, label in PLOT_FIELDS.items()}
    for k in ("soil", "access", "notes"):
        plot[k] = (d.get(k) or "").strip() or None
    diff = [f"{PLOT_FIELDS.get(k, k)} {old.get(k) if old.get(k) is not None else '—'} → {v if v is not None else '—'}"
            for k, v in plot.items() if old.get(k) != v]
    if not diff:
        return jsonify(present_measurements(m))
    m["plot"] = plot
    return save_measurements(lead, m, "Plot: " + "; ".join(diff))


# ---------------- lead files ----------------
def present_file(f):
    return {**serialize(f), "url": f"/api/files/{f['key']}"}


@bp.get("/leads/<_id>/files")
@api("leads")
def list_files(_id):
    load_lead(_id)
    return jsonify({"files": [present_file(f) for f in t.find("lead_files", {"lead_id": _id}, sort=[("created_at", -1)])],
                    "folders": FILE_FOLDERS})


@bp.post("/leads/<_id>/files")
@api("leads")
def attach_file(_id):
    """Attach an uploaded file (POST /uploads first) to the lead, in a folder and optionally a room or visit."""
    lead = open_lead(_id)
    d = request.get_json(force=True) or {}
    up = db.files.find_one({"company_id": g.cid, "key": d.get("key")})
    if not up:
        abort(400, "Upload the file first")
    if db.lead_files.find_one({"company_id": g.cid, "key": up["key"]}):
        abort(409, "This file is already attached")
    folder = d.get("folder")
    if folder not in FILE_FOLDERS:
        abort(400, f"Folder must be one of: {', '.join(FILE_FOLDERS)}")
    room = None
    if d.get("room_id"):
        room = next((r for r in measurements(lead)["rooms"] if r["id"] == d["room_id"]), None) or abort(400, "Room not found")
    if d.get("visit_id") and not db.lead_visits.find_one({"_id": oid(d["visit_id"]), "company_id": g.cid, "lead_id": _id}):
        abort(400, "Visit not found")
    f = t.insert("lead_files", {"lead_id": _id, "key": up["key"], "name": up["name"], "size": up["size"], "folder": folder,
                                "room_id": room and room["id"], "room": room and room["name"], "visit_id": d.get("visit_id"),
                                "caption": (d.get("caption") or "").strip() or None, "project_id": None})
    log(_id, "file", f"File added to {folder.replace('_', ' ')}: {up['name']}" + (f" ({room['name']})" if room else ""),
        file_id=str(f["_id"]))
    return jsonify(present_file(f)), 201


@bp.delete("/lead_files/<fid>")
@api("leads")
def remove_file(fid):
    f = t.get("lead_files", fid)
    open_lead(f["lead_id"])
    if f.get("created_by") != g.uid and g.role != "owner":
        abort(403, "Only the person who added the file (or the owner) can remove it")
    t.delete("lead_files", fid)
    delete_stored(f["key"])
    log(f["lead_id"], "file", f"File removed: {f['name']}")
    return jsonify({"ok": True})


def delete_stored(key):
    db.files.delete_one({"company_id": g.cid, "key": key})
    try:
        os.remove(os.path.join(Config.UPLOAD_DIR, key))
    except OSError:
        pass
