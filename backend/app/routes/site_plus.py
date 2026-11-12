"""Phase I block 3 — site and field (§10, §8, §14, §16).

* Stock (§8 "receiving location (site or warehouse) and stock at site", §10 "material stock and consumption at site"):
  goods are received at the project's site or into a company warehouse (the GRN says where). Stock per location =
  accepted − returned on its GRNs, plus the moves kept here: consumption on site (by stage), transfers between sites and
  warehouses, and counted adjustments. Value at the PO rate — a cost field, never shown to the Site Supervisor.
* Attendance (§10 "staff and labour attendance"): one sheet per project per day for staff on the team and named site
  workers (a company list, with the subcontractor they come from); present / half day / absent / leave, in and out,
  overtime. A month's summary gives days per person and, for roles that see costs, the labour cost at the daily rate.
* Snags (§10 "snag / punch list with photo, assignee and close-out", §14 "open snags", §16 "open snag / punch items past
  due"): open → fixed → closed (checked by someone other than the fixer, or an Owner); reopen with a reason. Closing the
  last snag of a stage offers its "snags closed" check. The worker chases snags past their due date.
* Installation checklist (§10 "installation checklist for interior projects"): a selection that is ordered (or
  delivered) is installed by ticking the checklist, with photos; all ticked → installed.
Who: the site area (Owner, PM, Site Supervisor) on projects they are on; stock moves also Procurement.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales
from ..services.defaults import SNAG_STATUSES, SNAG_PRIORITIES, ATTENDANCE_STATUSES, INSTALL_CHECKS
from .lead_money import a_date, money_text
from .lead_steps import num
from .projects import load, member

bp = Blueprint("site_plus", __name__)


def r2(v):
    return round((v or 0) + 1e-9, 2)


def site_access(pid, write=False):
    """Read: anyone with site, procurement or projects access on the project; write: site rw on the project."""
    if not (can("site") or can("procurement") or can("projects")):
        abort(403, "Your role cannot view site records")
    # Procurement reaches every project's stock (the Phase H rule); everyone else only projects they are on
    p = t.get("projects", pid) if can("procurement") and g.role in ("procurement", "owner") else load(pid)
    if write and not (can("site", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot write site records on this project")
    return p


def files_of(keys, limit=10):
    out = []
    for key in dict.fromkeys(keys or []):
        f = db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the photo first")
        out.append({"key": key, "name": f["name"]})
    return out[:limit]


def recent_day(d, label="Date"):
    """Today or yesterday; older only by an Owner (the site report rule)."""
    day = a_date(d or sales.today(), label)
    if day > sales.today():
        abort(400, f"{label} cannot be in the future")
    if day < (date.fromisoformat(sales.today()) - timedelta(days=1)).isoformat() and g.role != "owner":
        abort(409, "Site records are written on the day (or the next day); ask an Owner for an older one")
    return day


# ============================== warehouses and stock ==============================
def warehouses(company=None):
    return (company or g.company).get("warehouses") or []


def receiving_location(v):
    """Where a GRN's goods arrive: the project's site (default) or a company warehouse."""
    if v in (None, "", "site") or (isinstance(v, dict) and v.get("kind") == "site"):
        return {"kind": "site"}
    wid = v.get("id") if isinstance(v, dict) else v
    w = next((x for x in warehouses() if x["id"] == wid), None) or abort(400, "Choose the site or one of the company's warehouses")
    return {"kind": "warehouse", "id": w["id"], "name": w["name"]}


def loc_key(grn_or_move):
    loc = grn_or_move.get("location") or {"kind": "site"}
    return f"w:{loc['id']}" if loc.get("kind") == "warehouse" else f"p:{grn_or_move['project_id']}"


def item_key(row):
    return row.get("rate_id") or f"{(row.get('description') or '').strip().lower()}|{(row.get('unit') or '').strip().lower()}"


def stock_rows(where):
    """Balances at one location ("p:<project>" or "w:<warehouse>")."""
    items = {}

    def bump(key, desc, unit, field, qty, rate=None):
        it = items.setdefault(key, {"key": key, "description": desc, "unit": unit, "received": 0.0, "consumed": 0.0,
                                    "transfer_in": 0.0, "transfer_out": 0.0, "adjusted": 0.0, "rate": None})
        it[field] = r2(it[field] + qty)
        if rate:
            it["rate"] = rate

    q = {"company_id": g.cid}
    if where.startswith("p:"):
        q["project_id"] = where[2:]
    else:
        q["location.id"] = where[2:]
    for grn in db.goods_receipts.find(q):
        if loc_key(grn) != where:
            continue
        for ln in grn["lines"]:
            bump(item_key(ln), ln["description"], ln.get("unit"), "received", ln["accepted"] - ln.get("returned", 0), ln.get("unit_cost"))
    for m in db.stock_moves.find({"company_id": g.cid, "loc": where}):
        bump(m["key"], m["description"], m.get("unit"), m["kind"], abs(m["qty"]) if m["kind"] != "adjusted" else m["qty"], m.get("rate"))
    rows = []
    for it in items.values():
        it["balance"] = r2(it["received"] + it["transfer_in"] + it["adjusted"] - it["consumed"] - it["transfer_out"])
        it["value"] = r2(it["balance"] * (it["rate"] or 0))
        if g.hide_costs:
            it.pop("rate")
            it.pop("value")
        rows.append(it)
    return sorted(rows, key=lambda x: x["description"].lower())


def balance_of(where, key):
    return next((r for r in stock_rows(where) if r["key"] == key), None)


def stock_writer(p=None):
    if can("procurement", True) or g.role == "owner":
        return
    if p is not None and can("site", True) and member(p):
        return
    abort(403, "Your role cannot move stock on this project")


def location_of(code):
    """Check a location code the user named and say what it is."""
    if code.startswith("p:"):
        p = site_access(code[2:])
        return p, f"{p.get('code') or ''} {p['name']}".strip()
    if code.startswith("w:"):
        w = next((x for x in warehouses() if x["id"] == code[2:]), None) or abort(400, "Warehouse not found")
        if g.role not in ("owner", "procurement"):
            abort(403, "Only Procurement and the Owner see warehouse stock")
        return None, w["name"]
    abort(400, "A location is a project site or a warehouse")


def move(where, row, kind, qty, day, extra=None):
    return t.insert("stock_moves", {"loc": where, "key": row["key"], "description": row["description"], "unit": row.get("unit"),
                                    "kind": kind, "qty": qty, "date": day, "rate": row.get("rate"), "by": g.user.get("name"),
                                    "project_id": where[2:] if where.startswith("p:") else None, **(extra or {})})


@bp.get("/settings/warehouses")
@api(None)
def get_warehouses():
    return jsonify(warehouses())


@bp.put("/settings/warehouses")
@api("settings")
def put_warehouses():
    rows, seen = [], set()
    for w in (request.get_json(force=True) or {}).get("warehouses") or []:
        name = (w.get("name") or "").strip()[:80] or abort(400, "Every warehouse needs a name")
        if name.lower() in seen:
            abort(400, "Warehouse names must be unique")
        seen.add(name.lower())
        rows.append({"id": w.get("id") or t.sid(), "name": name, "address": (w.get("address") or "").strip()[:200] or None})
    kept = {w["id"] for w in rows}
    for w in warehouses():
        if w["id"] not in kept and any(r["balance"] for r in stock_rows(f"w:{w['id']}")):
            abort(409, f"{w['name']} still holds stock; move it out first")
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"warehouses": rows}})
    return jsonify(rows)


@bp.get("/projects/<pid>/stock")
@api(None)
def project_stock(pid):
    p = site_access(pid)
    moves = serialize(t.find("stock_moves", {"loc": f"p:{pid}"}, sort=[("date", -1), ("created_at", -1)], limit=200))
    if g.hide_costs:
        for m in moves:
            m.pop("rate", None)
    return jsonify({"rows": stock_rows(f"p:{pid}"), "moves": moves, "warehouses": warehouses(),
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "can_consume": can("site", True) and (g.role == "owner" or member(p) is not None) or can("procurement", True),
                    "can_transfer": can("procurement", True) or g.role == "owner"})


@bp.get("/warehouses/<wid>/stock")
@api(None)
def warehouse_stock(wid):
    location_of(f"w:{wid}")
    return jsonify({"rows": stock_rows(f"w:{wid}"),
                    "moves": serialize(t.find("stock_moves", {"loc": f"w:{wid}"}, sort=[("date", -1)], limit=200))})


@bp.post("/projects/<pid>/stock/consume")
@api(None)
def consume(pid):
    """Material used on site, by stage — from the site report or the stock page."""
    p = site_access(pid)
    stock_writer(p)
    d = request.get_json(force=True) or {}
    day = recent_day(d.get("date"))
    stages = {s["id"]: s for s in p.get("stages", [])}
    out = []
    for ln in d.get("lines") or []:
        have = balance_of(f"p:{pid}", ln.get("key")) or abort(400, "Choose material that is in stock on this site")
        qty = num(ln.get("qty"), f"Quantity of {have['description']}", required=True, positive=True)
        if qty > have["balance"] + 1e-9:
            abort(400, f"Only {have['balance']:g} {have.get('unit') or ''} of {have['description']} is on site")
        st = stages.get(ln.get("stage_id")) if ln.get("stage_id") else None
        if ln.get("stage_id") and not st:
            abort(400, "Stage not found")
        out.append(move(f"p:{pid}", have, "consumed", qty, day, {"stage_id": st and st["id"], "stage_name": st and st["name"],
                                                                  "note": (ln.get("note") or "").strip()[:200] or None,
                                                                  "site_report_id": d.get("site_report_id")}))
    if not out:
        abort(400, "Enter what was used")
    ev.log(pid, "file", "Material used on site: " + ", ".join(f"{m['qty']:g} {m.get('unit') or ''} {m['description']}" for m in out))
    return jsonify(serialize(out)), 201


@bp.post("/stock/transfer")
@api(None)
def transfer():
    """Move stock between project sites and warehouses (Procurement or the Owner)."""
    if not (can("procurement", True) or g.role == "owner"):
        abort(403, "Only Procurement or the Owner moves stock between locations")
    d = request.get_json(force=True) or {}
    src, dst = d.get("from") or "", d.get("to") or ""
    if src == dst:
        abort(400, "Choose two different locations")
    _, src_name = location_of(src)
    _, dst_name = location_of(dst)
    day = a_date(d.get("date") or sales.today(), "Date")
    ref = t.sid()
    done = []
    for ln in d.get("lines") or []:
        have = balance_of(src, ln.get("key")) or abort(400, f"Not in stock at {src_name}")
        qty = num(ln.get("qty"), f"Quantity of {have['description']}", required=True, positive=True)
        if qty > have["balance"] + 1e-9:
            abort(400, f"Only {have['balance']:g} {have.get('unit') or ''} of {have['description']} at {src_name}")
        move(src, have, "transfer_out", qty, day, {"ref": ref, "other": dst_name})
        move(dst, have, "transfer_in", qty, day, {"ref": ref, "other": src_name})
        done.append(f"{qty:g} {have.get('unit') or ''} {have['description']}")
    if not done:
        abort(400, "Choose what to move")
    for code in (src, dst):
        if code.startswith("p:"):
            ev.log(code[2:], "file", f"Stock moved {src_name} → {dst_name}: {', '.join(done)}")
    return jsonify({"ok": True, "moved": done}), 201


@bp.post("/projects/<pid>/stock/adjust")
@api(None)
def adjust(pid):
    """A stock count that differs: Procurement or the Owner, with a reason."""
    site_access(pid)
    if not (can("procurement", True) or g.role == "owner"):
        abort(403, "Only Procurement or the Owner adjusts stock")
    d = request.get_json(force=True) or {}
    have = balance_of(f"p:{pid}", d.get("key")) or abort(400, "Choose material of this site")
    counted = num(d.get("counted"), "Counted quantity", required=True)
    reason = (d.get("reason") or "").strip()[:200] or abort(400, "Say why the count differs")
    diff = r2(counted - have["balance"])
    if not diff:
        abort(400, "The count matches the stock")
    m = move(f"p:{pid}", have, "adjusted", diff, sales.today(), {"note": reason})
    return jsonify(serialize(m)), 201


# ============================== attendance ==============================
@bp.get("/site-workers")
@api(None)
def list_workers():
    if not (can("site") or can("projects")):
        abort(403, "Your role cannot view site workers")
    rows = t.out(serialize(t.find("site_workers", {}, sort=[("name", 1)])))
    return jsonify(rows)


def clean_worker(d, w=None):
    ch = {}
    if "name" in d or w is None:
        ch["name"] = (d.get("name") or "").strip()[:80] or abort(400, "Name is required")
    for k, n in (("phone", 20), ("trade", 40)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or None
    if "contact_id" in d:
        if d["contact_id"]:
            c = db.contacts.find_one({"_id": oid(d["contact_id"]), "company_id": g.cid}) or abort(400, "Subcontractor not found")
            ch.update(contact_id=d["contact_id"], contact_name=c["name"])
        else:
            ch.update(contact_id=None, contact_name=None)
    if "daily_rate" in d and not g.hide_costs:
        ch["daily_rate"] = r2(num(d.get("daily_rate"), "Daily rate") or 0) or None
    if "active" in d:
        ch["active"] = bool(d["active"])
    return ch


@bp.post("/site-workers")
@api("site")
def add_worker():
    d = request.get_json(force=True) or {}
    return jsonify(serialize(t.insert("site_workers", {"phone": None, "trade": None, "contact_id": None, "contact_name": None,
                                                       "daily_rate": None, "active": True, **clean_worker(d)}))), 201


@bp.put("/site-workers/<wid>")
@api("site")
def edit_worker(wid):
    w = t.get("site_workers", wid)
    return jsonify(serialize(t.update("site_workers", wid, clean_worker(request.get_json(force=True) or {}, w))))


def people(p):
    staff = [{"person": f"u:{m['user_id']}", "name": m["name"], "trade": m.get("project_role"), "kind": "staff"}
             for m in p.get("team", []) if m.get("user_id") and m.get("kind") != "external"]
    workers = [{"person": f"w:{w['_id']}", "name": w["name"], "trade": w.get("trade"), "kind": "worker", "party": w.get("contact_name")}
               for w in db.site_workers.find({"company_id": g.cid, "active": {"$ne": False}}).sort("name", 1)]
    return staff + workers


def hhmm(v, label):
    if v in (None, ""):
        return None
    try:
        hh, mm = (int(x) for x in str(v).split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except (ValueError, AssertionError):
        abort(400, f"{label} is a time like 09:00")
    return f"{hh:02d}:{mm:02d}"


@bp.get("/projects/<pid>/attendance")
@api(None)
def get_attendance(pid):
    p = site_access(pid)
    day = a_date(request.args.get("date") or sales.today(), "Date")
    sheet = db.attendance.find_one({"company_id": g.cid, "project_id": pid, "date": day})
    return jsonify({"date": day, "sheet": serialize(sheet) if sheet else None, "people": people(p), "statuses": list(ATTENDANCE_STATUSES),
                    "can_write": can("site", True) and (g.role == "owner" or member(p) is not None)})


@bp.put("/projects/<pid>/attendance")
@api(None)
def put_attendance(pid):
    p = site_access(pid, write=True)
    d = request.get_json(force=True) or {}
    day = recent_day(d.get("date"))
    known = {x["person"]: x for x in people(p)}
    rows, seen = [], set()
    for r in d.get("rows") or []:
        who = known.get(r.get("person")) or abort(400, "Mark attendance for people on this project or the site worker list")
        if r["person"] in seen:
            abort(400, f"{who['name']} is twice on the sheet")
        seen.add(r["person"])
        if r.get("status") not in ATTENDANCE_STATUSES:
            abort(400, f"Status: {', '.join(ATTENDANCE_STATUSES)}")
        t_in, t_out = hhmm(r.get("in"), "In"), hhmm(r.get("out"), "Out")
        if t_in and t_out and t_out < t_in:
            abort(400, f"{who['name']}: out is before in")
        ot = num(r.get("ot_hours"), "Overtime hours") or 0
        if not 0 <= ot <= 12:
            abort(400, "Overtime is 0 to 12 hours")
        rows.append({"person": r["person"], "name": who["name"], "trade": who.get("trade"), "kind": who["kind"], "status": r["status"],
                     "in": t_in, "out": t_out, "ot_hours": ot})
    doc = {"rows": rows, "present": sum(ATTENDANCE_STATUSES[x["status"]] for x in rows), "by": g.user.get("name"), "by_id": g.uid}
    old = db.attendance.find_one({"company_id": g.cid, "project_id": pid, "date": day})
    sheet = t.update("attendance", str(old["_id"]), doc) if old else \
        t.insert("attendance", {"project_id": pid, "project_name": p["name"], "date": day, **doc})
    return jsonify(serialize(sheet))


@bp.get("/projects/<pid>/attendance/summary")
@api(None)
def attendance_summary(pid):
    site_access(pid)
    month = request.args.get("month") or sales.today()[:7]
    if len(month) != 7 or month[4] != "-":
        abort(400, "Month must be YYYY-MM")
    rates = {f"w:{w['_id']}": w.get("daily_rate") for w in db.site_workers.find({"company_id": g.cid}, {"daily_rate": 1})}
    per = {}
    for sh in db.attendance.find({"company_id": g.cid, "project_id": pid, "date": {"$regex": f"^{month}"}}):
        for r in sh["rows"]:
            x = per.setdefault(r["person"], {"person": r["person"], "name": r["name"], "trade": r.get("trade"), "kind": r["kind"],
                                             "days": 0.0, "absent": 0, "ot_hours": 0.0})
            x["days"] += ATTENDANCE_STATUSES[r["status"]]
            x["absent"] += 1 if r["status"] == "absent" else 0
            x["ot_hours"] += r.get("ot_hours") or 0
    rows = sorted(per.values(), key=lambda x: (x["kind"], x["name"]))
    if not g.hide_costs and can("finance"):
        for x in rows:
            rate = rates.get(x["person"])
            x["cost"] = r2(x["days"] * rate) if rate else None
    return jsonify({"month": month, "rows": rows, "days": len(list(db.attendance.find({"company_id": g.cid, "project_id": pid,
                                                                                       "date": {"$regex": f"^{month}"}}, {"_id": 1})))})


# ============================== snags ==============================
def snag_present(s):
    data = serialize(s)
    data["overdue"] = s["status"] != "closed" and bool(s.get("due")) and s["due"] < sales.today()
    for ph in data.get("photos", []) + data.get("fix_photos", []):
        ph["url"] = f"/api/files/{ph['key']}"
    return data


def load_snag(sid, write=True):
    s = t.get("snags", sid)
    p = site_access(s["project_id"])
    if write and not (can("site", True) and (g.role == "owner" or member(p))) and s.get("assignee_id") != g.uid:
        abort(403, "Your role cannot change snags on this project")
    return s, p


def clean_snag(d, p, s=None):
    ch = {}
    if "title" in d or s is None:
        ch["title"] = (d.get("title") or "").strip()[:200] or abort(400, "What is wrong?")
    for k, n in (("location", 120), ("room", 80), ("description", 1000)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or None
    if "stage_id" in d:
        st = next((x for x in p.get("stages", []) if x["id"] == d["stage_id"]), None) if d["stage_id"] else None
        if d["stage_id"] and not st:
            abort(400, "Stage not found")
        ch.update(stage_id=st and st["id"], stage_name=st and st["name"])
    if "priority" in d:
        if d["priority"] not in SNAG_PRIORITIES:
            abort(400, f"Priority: {', '.join(SNAG_PRIORITIES)}")
        ch["priority"] = d["priority"]
    if "due" in d:
        ch["due"] = a_date(d["due"], "Due date", required=False)
    if "assignee_id" in d:
        if d["assignee_id"]:
            m = next((x for x in p.get("team", []) if x.get("user_id") == d["assignee_id"]), None) or abort(400, "Assign someone on the project team")
            ch.update(assignee_id=d["assignee_id"], assignee_name=m["name"])
        else:
            ch.update(assignee_id=None, assignee_name=None)
    if "party_id" in d:  # the subcontractor / supplier who must fix it
        if d["party_id"]:
            c = db.contacts.find_one({"_id": oid(d["party_id"]), "company_id": g.cid}) or abort(400, "Contact not found")
            ch.update(party_id=d["party_id"], party_name=c["name"])
        else:
            ch.update(party_id=None, party_name=None)
    if "photos" in d:
        ch["photos"] = files_of(d["photos"])
    return ch


@bp.get("/projects/<pid>/snags")
@api(None)
def list_snags(pid):
    p = site_access(pid)
    rows = [snag_present(s) for s in t.find("snags", {"project_id": pid}, sort=[("status", 1), ("due", 1), ("created_at", -1)])]
    return jsonify({"snags": rows, "statuses": SNAG_STATUSES, "priorities": SNAG_PRIORITIES,
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "team": [{"id": m["user_id"], "name": m["name"]} for m in p.get("team", []) if m.get("user_id")],
                    "counts": {k: sum(1 for r in rows if r["status"] == k) for k in SNAG_STATUSES},
                    "can_write": can("site", True) and (g.role == "owner" or member(p) is not None)})


@bp.post("/projects/<pid>/snags")
@api(None)
def add_snag(pid):
    p = site_access(pid, write=True)
    d = request.get_json(force=True) or {}
    s = t.insert("snags", {"project_id": pid, "project_name": p["name"], "number": t.next_number("SNG", "SNG"), "status": "open",
                           "location": None, "room": None, "description": None, "stage_id": None, "stage_name": None,
                           "priority": "normal", "due": None, "assignee_id": None, "assignee_name": None, "party_id": None,
                           "party_name": None, "photos": [], "fix_photos": [], "raised_by": g.user.get("name"), "raised_by_id": g.uid,
                           "history": [{"status": "open", "by": g.user.get("name"), "at": t.now()}], **clean_snag(d, p)})
    ev.log(pid, "issue", f"Snag {s['number']}: {s['title']}" + (f" ({s['location']})" if s.get("location") else ""))
    if s.get("assignee_id") and s["assignee_id"] != g.uid:
        notify.send("snag_assigned", [s["assignee_id"]], f"{p['name']}: snag {s['number']} — {s['title']}" + (f", due {s['due']}" if s.get("due") else ""),
                    f"/app/projects/{pid}?tab=site", project_id=pid)
    return jsonify(snag_present(s)), 201


@bp.put("/snags/<sid>")
@api(None)
def edit_snag(sid):
    s, p = load_snag(sid)
    if s["status"] != "open":
        abort(409, "Only an open snag is edited")
    ch = clean_snag(request.get_json(force=True) or {}, p, s)
    upd = t.update("snags", sid, ch)
    if ch.get("assignee_id") and ch["assignee_id"] != s.get("assignee_id") and ch["assignee_id"] != g.uid:
        notify.send("snag_assigned", [ch["assignee_id"]], f"{p['name']}: snag {s['number']} — {upd['title']}", f"/app/projects/{p['_id']}?tab=site",
                    project_id=s["project_id"])
    return jsonify(snag_present(upd))


def snag_step(s, status, extra):
    return {"status": status, **extra, "history": s.get("history", []) + [{"status": status, "by": g.user.get("name"), "at": t.now(),
                                                                            "note": extra.get("fix_note") or extra.get("reopen_reason")}]}


@bp.post("/snags/<sid>/fixed")
@api(None)
def snag_fixed(sid):
    s, p = load_snag(sid)
    if s["status"] != "open":
        abort(409, "Only an open snag is marked fixed")
    d = request.get_json(force=True) or {}
    upd = t.update("snags", sid, snag_step(s, "fixed", {"fix_note": (d.get("note") or "").strip()[:500] or None,
                                                        "fix_photos": files_of(d.get("photos")), "fixed_by": g.user.get("name"),
                                                        "fixed_by_id": g.uid, "fixed_at": t.now()}))
    if s.get("raised_by_id") and s["raised_by_id"] != g.uid:
        notify.send("snag_assigned", [s["raised_by_id"]], f"{p['name']}: snag {s['number']} fixed — check and close it",
                    f"/app/projects/{p['_id']}?tab=site", project_id=s["project_id"])
    return jsonify(snag_present(upd))


@bp.post("/snags/<sid>/close")
@api(None)
def snag_close(sid):
    s, p = load_snag(sid)
    if not (can("site", True) and (g.role == "owner" or member(p))):
        abort(403, "Only the site team closes snags")
    if s["status"] != "fixed":
        abort(409, "A snag is closed after it is marked fixed")
    if s.get("fixed_by_id") == g.uid and g.role != "owner":
        abort(409, "Someone other than the person who fixed it checks and closes it")
    upd = t.update("snags", sid, snag_step(s, "closed", {"closed_by": g.user.get("name"), "closed_at": t.now()}))
    if s.get("stage_id") and not db.snags.find_one({"company_id": g.cid, "project_id": s["project_id"], "stage_id": s["stage_id"],
                                                    "status": {"$ne": "closed"}}, {"_id": 1}):
        offer_check(p, s["stage_id"], "snag", "all snags closed")
    return jsonify(snag_present(upd))


@bp.post("/snags/<sid>/reopen")
@api(None)
def snag_reopen(sid):
    s, p = load_snag(sid)
    if s["status"] == "open":
        abort(409, "The snag is open")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip()[:300] or abort(400, "Say why it is reopened")
    upd = t.update("snags", sid, snag_step(s, "open", {"reopen_reason": reason, "fixed_by_id": None}))
    if s.get("assignee_id"):
        notify.send("snag_assigned", [s["assignee_id"]], f"{p['name']}: snag {s['number']} reopened — {reason}",
                    f"/app/projects/{p['_id']}?tab=site", project_id=s["project_id"])
    return jsonify(snag_present(upd))


def offer_check(p, stage_id, word, why):
    """Offer (never tick) a stage checklist item whose text mentions `word` — the B+2 rule: an editor still ticks it."""
    fresh = db.projects.find_one({"_id": p["_id"]})
    changed = False
    for st in fresh.get("stages", []):
        if st["id"] == stage_id:
            for c in st.get("checklist", []):
                if word in c["text"].lower() and not c.get("done"):
                    c["suggested"] = {"by": "site", "number": why, "at": t.now().isoformat()}
                    changed = True
    if changed:
        db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": fresh["stages"]}})


def check_snags(now):
    """Worker: an open or fixed snag past its due date -> its assignee and the project's managers, once per due date."""
    today = now.date().isoformat()
    for s in db.snags.find({"company_id": g.cid, "status": {"$ne": "closed"}, "due": {"$lt": today, "$ne": None}}):
        p = db.projects.find_one({"_id": oid(s["project_id"])})
        if not p or p.get("status") not in ("planning", "active"):
            continue
        who = list(dict.fromkeys(([s["assignee_id"]] if s.get("assignee_id") else []) + ev.managers(p)))
        notify.send("snag_due", who, f"{p['name']}: snag {s['number']} ({s['title']}) was due {s['due']}", f"/app/projects/{p['_id']}?tab=site",
                    project_id=s["project_id"], key=f"snag-due:{s['_id']}:{s['due']}", level="warn")


# ============================== installation checklist ==============================
@bp.post("/selections/<sid>/install")
@api(None)
def install(sid):
    """Tick the installation checklist (with photos); when every check is ticked the item is installed."""
    s = t.get("selections", sid)
    p = load(s["project_id"])
    if not ((can("site", True) or can("selections", True)) and (g.role == "owner" or member(p))):
        abort(403, "Only the site team or the designer on the project records installation")
    if s["status"] not in ("ordered", "delivered"):
        abort(409, "An item is installed after it is ordered")
    d = request.get_json(force=True) or {}
    prev = {c["text"]: c for c in (s.get("installation") or {}).get("checks", [])}
    checks = []
    for c in d.get("checks") or [{"text": x, "done": False} for x in INSTALL_CHECKS]:
        text = (c.get("text") or "").strip()[:120] or abort(400, "Each check needs its text")
        done = bool(c.get("done"))
        old = prev.get(text) or {}
        checks.append({"text": text, "done": done, "by": (old.get("by") if old.get("done") else g.user.get("name")) if done else None})
    inst = {"checks": checks, "photos": files_of(d.get("photos"), 12) if "photos" in d else (s.get("installation") or {}).get("photos", []),
            "note": (d.get("note") or "").strip()[:500] or (s.get("installation") or {}).get("note"), "updated_by": g.user.get("name"), "at": t.now()}
    ch = {"installation": inst}
    complete = bool(checks) and all(c["done"] for c in checks)
    if complete:
        ch.update(status="installed", installed_at=t.now(), history=s.get("history", []) + [{"status": "installed", "by": g.user.get("name"), "at": t.now()}])
    upd = t.update("selections", sid, ch)
    if complete:
        from .selections import offer_installed_check
        ev.log(s["project_id"], "file", f"Selection {s['item']}: installed ({len(checks)} checks ticked)")
        offer_installed_check(p, s["stage_id"])
    from .selections import present
    return jsonify(present(upd))


@bp.get("/install-checks")
@api(None)
def install_checks():
    return jsonify(INSTALL_CHECKS)
