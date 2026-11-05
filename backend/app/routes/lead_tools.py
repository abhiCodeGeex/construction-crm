"""Working with many leads (C+3): assignment rules, merge, import (CSV / Excel), bulk actions, export, saved
views, the Needs-attention list and the sales calendar."""
import csv
import io
from datetime import datetime, timedelta, date

from flask import Blueprint, request, jsonify, abort, g, Response
from werkzeug.exceptions import HTTPException

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api
from ..services import notify, sales
from ..services.defaults import SERVICES, TEMPERATURES
from ..services.sales import load_lead, log, visible_q

bp = Blueprint("lead_tools", __name__)


# ---------------- assignment rules ----------------
def auto_owner(service, branch, company=None):
    """First rule matching the lead's service and branch, then round-robin among its active users.
    Returns (user_id, name) or (None, None) when no rule matches (the lead stays unassigned for the manager)."""
    company = company or g.company
    rules = (sales.settings(company).get("assignment") or {}).get("rules") or []
    for i, r in enumerate(rules):
        if r.get("service") and r["service"] != service:
            continue
        if r.get("branch") and r["branch"] != branch:
            continue
        users = [u for u in db.users.find({"_id": {"$in": [oid(x) for x in r.get("user_ids") or []]}, "company_id": str(company["_id"]),
                                            "kind": "staff", "active": {"$ne": False}}, {"name": 1})]
        users.sort(key=lambda u: (r["user_ids"].index(str(u["_id"]))))
        if not users:
            continue
        c = db.companies.find_one_and_update({"_id": company["_id"]}, {"$inc": {f"counters.assign_{i}": 1}}, return_document=True)
        u = users[(c["counters"][f"assign_{i}"] - 1) % len(users)]
        return str(u["_id"]), u["name"]
    return None, None


@bp.put("/leads/assignment")
@api("settings")
def set_assignment():
    d = request.get_json(force=True) or {}
    branches = [b.get("name") for b in g.company.get("branches", [])]
    rules = []
    for r in d.get("rules") or []:
        if r.get("service") and r["service"] not in SERVICES:
            abort(400, "Unknown service")
        if r.get("branch") and r["branch"] not in branches:
            abort(400, "Unknown branch")
        ids = list(dict.fromkeys(r.get("user_ids") or []))
        if not ids:
            abort(400, "Each rule needs at least one salesperson")
        for uid in ids:
            if not db.users.find_one({"_id": oid(uid), "company_id": g.cid, "kind": "staff", "active": {"$ne": False}}):
                abort(400, "Assignment users must be active staff")
        rules.append({"service": r.get("service") or None, "branch": r.get("branch") or None, "user_ids": ids})
    s = dict(g.company.get("sales") or {})
    s["assignment"] = {"rules": rules}
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"sales": s}})
    t.audit("update", "assignment_rules", g.company["_id"], note=f"{len(rules)} rule(s)")
    return jsonify(s["assignment"])


@bp.get("/leads/assignment")
@api("leads", write=False)
def get_assignment():
    return jsonify(sales.settings().get("assignment") or {"rules": []})


# ---------------- merge ----------------
@bp.post("/leads/<_id>/merge")
@api("leads")
def merge(_id):
    """Keep this lead; the other one's history, follow-ups, visits, files, money, estimates, proposals and bids
    move here. Empty fields are filled from the other lead. The other lead is marked merged (hidden)."""
    from .leads import editable, FIELDS, FIELD_LABELS
    keep = load_lead(_id)
    editable(keep) if keep["status"] != "on_hold" else None
    other_id = (request.get_json(force=True) or {}).get("other_id")
    if not other_id or other_id == _id:
        abort(400, "Choose the other lead to merge into this one")
    other = load_lead(other_id)
    if other["status"] not in ("open", "on_hold"):
        abort(409, f"{other['title']} is {other['status']}; only open leads can be merged")
    filled = {}
    for k in FIELDS:
        if k in ("title", "contact_id"):
            continue
        if keep.get(k) in (None, "", []) and other.get(k) not in (None, "", []):
            filled[k] = other[k]
    moved_acts = [{**a, "text": f"[from {other['title']}] {a['text']}"} for a in other.get("activities") or []]
    people = list(keep.get("stakeholders") or [])
    for p in other.get("stakeholders") or []:
        if p["contact_id"] != keep.get("contact_id") and not any(x["contact_id"] == p["contact_id"] for x in people):
            people.append({**p, "main": False})
    if other.get("contact_id") != keep.get("contact_id") and not any(x["contact_id"] == other.get("contact_id") for x in people):
        c = db.contacts.find_one({"_id": oid(other.get("contact_id"))}) or {}
        people.append({"id": t.sid(), "contact_id": other.get("contact_id"), "name": other.get("contact_name"), "role": "Other",
                       "main": False, "phone": c.get("phone"), "email": c.get("email")})
    comps = list(keep.get("competitors") or []) + [c for c in other.get("competitors") or []
                                                    if not any(x["name"].lower() == c["name"].lower() for x in keep.get("competitors") or [])]
    q = {"company_id": g.cid, "lead_id": other_id}
    for coll in ("lead_visits", "lead_files", "lead_expenses", "lead_receipts", "estimates", "proposals"):
        db[coll].update_many(q, {"$set": {"lead_id": _id, "lead_title": keep["title"]}})
    db.bids.update_many(q, {"$set": {"lead_id": _id, "lead_title": keep["title"]}})
    db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": other_id},
                             {"$set": {"related.id": _id, "related.label": keep["title"]}})
    db.notifications.update_many({"company_id": g.cid, "lead_id": other_id}, {"$set": {"lead_id": _id, "link": f"/app/leads/{_id}"}})
    db.leads.update_one({"_id": keep["_id"]}, {"$set": {**filled, "stakeholders": people, "competitors": comps,
                                                         "negotiation": (keep.get("negotiation") or []) + (other.get("negotiation") or [])},
                                               "$push": {"activities": {"$each": moved_acts}}})
    db.leads.update_one({"_id": other["_id"]}, {"$set": {"status": "merged", "merged_into": _id, "merged_at": t.now()}})
    t.audit("update", "leads", other["_id"], note=f"Merged into {keep['title']}")
    log(_id, "merged", f"Merged {other['title']} into this lead" + (f"; filled: {', '.join(FIELD_LABELS[k] for k in filled)}" if filled else ""))
    if other.get("owner_id") and other["owner_id"] != keep.get("owner_id"):
        notify.send("lead_merged", [other["owner_id"]], f"Your lead {other['title']} was merged into {keep['title']}",
                    f"/app/leads/{_id}", _id)
    from .leads import present
    return jsonify(present(load_lead(_id)))


# ---------------- import ----------------
IMPORT_COLUMNS = ["title", "name", "phone", "email", "company", "service", "source", "source_detail", "project_type",
                  "location", "area", "area_unit", "budget", "timeline", "notes", "owner_email", "temperature"]


def read_rows(f):
    name = (f.filename or "").lower()
    if name.endswith(".csv"):
        text = f.read().decode("utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(text)))
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h or "").strip().lower() for h in rows[0]]
        return [{head[i]: ("" if v is None else v) for i, v in enumerate(r) if i < len(head)} for r in rows[1:] if any(v not in (None, "") for v in r)]
    abort(400, "Import a .csv or .xlsx file (save an .xls sheet as .xlsx first)")


def number(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        raise ValueError(f"'{v}' is not a number")


@bp.get("/leads/import/template")
@api("leads", write=False)
def import_template():
    return Response(",".join(IMPORT_COLUMNS) + "\n", mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=lead-import-template.csv"})


@bp.post("/leads/import")
@api("leads")
def import_leads():
    """Dry run first (?dry_run=1) to see every row's result; then import. Rows that match an open lead's phone
    or email are skipped as duplicates. A row with no owner_email follows the assignment rules."""
    from .leads import clean, contact_from_payload, pipeline, history_entry, notify_assignment
    f = request.files.get("file") or abort(400, "Choose the file to import")
    rows = read_rows(f)
    if not rows:
        abort(400, "The file has no rows")
    if len(rows) > 2000:
        abort(400, "Import at most 2,000 rows at a time")
    dry = request.args.get("dry_run") == "1"
    out = []
    for i, raw in enumerate(rows, start=2):
        r = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in raw.items() if k}
        try:
            d = {"title": r.get("title") or f"{r.get('name')} – {r.get('project_type') or r.get('service')} enquiry",
                 "contact_name": r.get("name"), "contact_phone": r.get("phone") or None, "contact_email": r.get("email") or None,
                 "contact_is_company": bool(r.get("company")), "service": (r.get("service") or "").lower(),
                 "source": r.get("source") or "Ads", "source_detail": r.get("source_detail") or None,
                 "project_type": r.get("project_type") or None, "location": r.get("location") or None,
                 "area": number(r.get("area")), "area_unit": r.get("area_unit") or "sqft", "budget": number(r.get("budget")),
                 "timeline": r.get("timeline") or None, "notes": r.get("notes") or None,
                 "temperature": (r.get("temperature") or "").lower() or None}
            if d["temperature"] and d["temperature"] not in TEMPERATURES:
                raise ValueError("temperature must be hot, warm or cold")
            if r.get("owner_email"):
                u = db.users.find_one({"company_id": g.cid, "email": r["owner_email"].lower(), "kind": "staff", "active": {"$ne": False}})
                if not u:
                    raise ValueError(f"no active staff user {r['owner_email']}")
                d["owner_id"] = str(u["_id"])
            contact = contact_from_payload(d)  # 409 for a duplicate of an open lead
            data = clean(d, new_contact=contact)
            if dry:
                out.append({"row": i, "ok": True, "title": data["title"]})
                continue
            if not data.get("owner_id"):
                data["owner_id"], data["owner_name"] = auto_owner(data["service"], data.get("branch"))
            stage = pipeline(data["service"])[0]
            data.update(status="open", stage=stage, stage_entered_at=t.now(), first_response_at=None,
                        activities=[history_entry("created", f"Lead imported from {f.filename} (row {i})")],
                        stage_history=[{"stage": stage, "at": t.now(), "by": g.user.get("name")}])
            data["contact_id"] = str(t.insert("contacts", contact)["_id"])
            lead = t.insert("leads", data)
            notify_assignment(lead)
            out.append({"row": i, "ok": True, "title": data["title"], "id": str(lead["_id"]), "owner": data.get("owner_name")})
        except HTTPException as e:
            msg = e.description.split("|")[0]
            out.append({"row": i, "ok": False, "error": "duplicate — " + msg if e.code == 409 else msg})
        except ValueError as e:
            out.append({"row": i, "ok": False, "error": str(e)})
    if not dry:
        t.audit("create", "leads", None, note=f"Imported {sum(1 for x in out if x['ok'])} of {len(out)} rows from {f.filename}")
    return jsonify({"dry_run": dry, "rows": out, "ok": sum(1 for x in out if x["ok"]), "failed": sum(1 for x in out if not x["ok"])})


# ---------------- bulk actions ----------------
@bp.post("/leads/bulk")
@api("leads")
def bulk():
    """Reassign, move stage (exit rules apply to each lead), add / remove a tag or set the temperature."""
    from .leads import change_stage, notify_assignment, editable, staff, history_entry
    d = request.get_json(force=True) or {}
    ids, action, value = d.get("ids") or [], d.get("action"), d.get("value")
    if not ids or len(ids) > 500:
        abort(400, "Choose between 1 and 500 leads")
    if action not in ("assign", "stage", "tag_add", "tag_remove", "temperature"):
        abort(400, "Unknown bulk action")
    owner = staff(value) if action == "assign" else None
    if action == "temperature" and value not in TEMPERATURES:
        abort(400, "Temperature must be hot, warm or cold")
    if action in ("tag_add", "tag_remove") and not (value or "").strip():
        abort(400, "Enter the tag")
    done, failed = [], []
    for lid in ids:
        try:
            lead = load_lead(lid)
            editable(lead)
            if action == "assign":
                if lead.get("owner_id") == str(owner["_id"]):
                    done.append(lid)
                    continue
                prev = lead.get("owner_id")
                db.followups.update_many({"company_id": g.cid, "related.type": "lead", "related.id": lid, "status": "open", "owner_id": prev},
                                         {"$set": {"owner_id": str(owner["_id"]), "owner_name": owner["name"]}}) if prev else None
                upd = t.update("leads", lid, {"owner_id": str(owner["_id"]), "owner_name": owner["name"]},
                               raw={"$push": {"activities": history_entry("edit", f"Edited (bulk): Salesperson {lead.get('owner_name') or '—'} → {owner['name']}",
                                                                          changes=[{"field": "Salesperson", "from": lead.get("owner_name") or "—", "to": owner["name"]}])}})
                notify_assignment(upd, prev)
            elif action == "stage":
                change_stage(lead, value, (d.get("override_reason") or "").strip() or None)
            elif action == "temperature":
                if lead.get("temperature") != value:
                    t.update("leads", lid, {"temperature": value}, raw={"$push": {"activities": history_entry(
                        "edit", f"Edited (bulk): Temperature {lead.get('temperature') or '—'} → {value}",
                        changes=[{"field": "Temperature", "from": lead.get("temperature") or "—", "to": value}])}})
            else:
                tag = value.strip()
                op = "$addToSet" if action == "tag_add" else "$pull"
                db.leads.update_one({"_id": lead["_id"]}, {op: {"tags": tag}})
                log(lid, "edit", f"Tag {'added' if action == 'tag_add' else 'removed'} (bulk): {tag}")
            done.append(lid)
        except HTTPException as e:
            failed.append({"id": lid, "title": (db.leads.find_one({"_id": oid(lid)}, {"title": 1}) or {}).get("title"), "error": e.description})
    return jsonify({"done": done, "failed": failed})


# ---------------- export ----------------
@bp.get("/leads/export")
@api("leads", write=False)
def export():
    from .leads import present
    q = {"status": {"$ne": "merged"}, **visible_q()}
    for k in ("status", "service", "stage", "source", "temperature"):
        if request.args.get(k):
            q[k] = request.args[k]
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["title", "contact_name", "service", "status", "stage", "days_in_stage", "source", "source_detail", "owner_name", "temperature",
            "score", "value", "probability_effective", "weighted_value", "budget", "area", "area_unit", "location", "expected_close",
            "tags", "created_at", "first_response_at", "loss_reason", "competitor"]
    w.writerow(cols)
    for lead in t.find("leads", q, sort=[("created_at", -1)]):
        p = present(lead)
        w.writerow([", ".join(p.get(c) or []) if c == "tags" else ("" if p.get(c) is None else p.get(c)) for c in cols])
    t.audit("export", "leads", None, note=f"{buf.getvalue().count(chr(10)) - 1} lead(s) exported")
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})


# ---------------- saved views ----------------
@bp.get("/leads/views")
@api("leads", write=False)
def views():
    return jsonify((db.users.find_one({"_id": oid(g.uid)}, {"lead_views": 1}) or {}).get("lead_views") or [])


@bp.put("/leads/views")
@api("leads", write=False)
def save_views():
    rows = (request.get_json(force=True) or {}).get("views") or []
    clean = []
    for v in rows[:30]:
        name = (v.get("name") or "").strip()
        if not name:
            abort(400, "Name the view")
        clean.append({"name": name[:60], "filters": {k: v.get("filters", {}).get(k) for k in
                                                     ("service", "owner_id", "source", "temperature", "q", "tag", "status")}})
    db.users.update_one({"_id": oid(g.uid)}, {"$set": {"lead_views": clean}})
    return jsonify(clean)


# ---------------- needs attention ----------------
@bp.get("/leads/attention")
@api("leads", write=False)
def attention():
    """Everything that is late or waiting, live (not from notifications). The owner and the sales manager see
    the whole team; everyone else sees their own leads."""
    from .leads import present
    now = t.now()
    s = sales.settings()
    mine = not sales.is_manager()
    lq = {"status": "open", **({"owner_id": g.uid} if mine else {})}
    leads = t.find("leads", lq)
    by_id = {str(x["_id"]): x for x in leads}
    row = lambda lead, why: {"id": str(lead["_id"]), "title": lead["title"], "owner_name": lead.get("owner_name"), "why": why}
    out = {k: [] for k in ("not_contacted", "stuck", "missed_visits", "late_reports", "proposals", "approvals", "overdue_followups",
                           "hot_idle", "unassigned")}
    for lead in leads:
        if not lead.get("first_response_at") and (now - lead["created_at"]).total_seconds() / 60 >= s["response_minutes"]:
            out["not_contacted"].append(row(lead, f"{int((now - lead['created_at']).total_seconds() // 3600)} h since the enquiry"))
        limit = sales.stage_rules(lead["service"], lead["stage"]).get("max_days")
        days = sales.days_in_stage(lead, now)
        if limit and days > limit:
            out["stuck"].append(row(lead, f"{days} days in {lead['stage']} (limit {limit})"))
        if lead.get("temperature") == "hot" and (now - (lead.get("last_activity_at") or lead["created_at"])).days >= s["hot_idle_days"]:
            out["hot_idle"].append(row(lead, f"no activity for {(now - (lead.get('last_activity_at') or lead['created_at'])).days} days"))
    if not mine:
        out["unassigned"] = [row(x, x.get("source") or "") for x in t.find("leads", {"status": "open", "owner_id": None})]
    ids = list(by_id)
    for v in t.find("lead_visits", {"lead_id": {"$in": ids}, "status": {"$in": ["scheduled", "confirmed", "done"]}}):
        lead = by_id[v["lead_id"]]
        if v["status"] != "done" and v["at"] + timedelta(minutes=(v.get("duration_min") or 60) + 120) < now:
            out["missed_visits"].append(row(lead, f"visit {v['at']:%d %b %H:%M} UTC not marked done"))
        elif v["status"] == "done" and not (v.get("report") or {}).get("submitted_at") and v.get("done_at") and now - v["done_at"] > timedelta(hours=24):
            out["late_reports"].append(row(lead, f"visit {v['at']:%d %b} has no report"))
    soon = (now.date() + timedelta(days=2)).isoformat()
    for p in t.find("proposals", {"lead_id": {"$in": ids}, "status": "sent"}):
        lead = by_id[p["lead_id"]]
        if p["valid_until"] <= soon:
            out["proposals"].append(row(lead, f"{p['number']} expires {p['valid_until']}"))
        elif p.get("sent_at") and now - p["sent_at"] > timedelta(days=3):
            out["proposals"].append(row(lead, f"{p['number']} sent {(now - p['sent_at']).days} days ago, no answer"))
    if not mine:
        for e in t.find("estimates", {"status": "pending_approval"}):
            out["approvals"].append({"id": e["lead_id"], "title": e["lead_title"], "why": f"estimate {e['number']}: {'; '.join(e['approval']['reasons'])}"})
        for lead in t.find("leads", {"status": "open", "negotiation.approval.status": "pending"}):
            for r in lead["negotiation"]:
                if r["approval"]["status"] == "pending":
                    out["approvals"].append(row(lead, f"discount {r['discount_pct']:g}% asked by {r['by']}"))
    today = date.today().isoformat()
    fq = {"status": "open", "due": {"$lt": today}, "related.type": "lead", **({"owner_id": g.uid} if mine else {})}
    for f in t.find("followups", fq, sort=[("due", 1)]):
        out["overdue_followups"].append({"id": f["related"]["id"], "title": f["related"].get("label"), "owner_name": f.get("owner_name"),
                                         "why": f"{f['title']} — due {f['due']}"})
    return jsonify({"scope": "mine" if mine else "team", **out})


# ---------------- calendar ----------------
@bp.get("/calendar")
@api(None)
def calendar():
    """Visits, follow-ups, bid due dates and proposal expiry between ?from and ?to, mine or (managers) the team's."""
    try:
        start = date.fromisoformat(request.args.get("from") or date.today().replace(day=1).isoformat())
        end = date.fromisoformat(request.args.get("to") or (start + timedelta(days=42)).isoformat())
    except ValueError:
        abort(400, "from / to must be dates")
    if (end - start).days > 100:
        abort(400, "Show at most 100 days at a time")
    team = request.args.get("scope") == "team"
    if team and not (sales.is_manager() or g.role == "pm"):
        abort(403, "Only the owner, the sales manager and project managers see the team calendar")
    uid = request.args.get("user_id") if team and request.args.get("user_id") else (None if team else g.uid)
    events = []
    t0, t1 = datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
    vq = {"at": {"$gte": t0, "$lt": t1}, "status": {"$in": ["scheduled", "confirmed", "done"]}}
    if uid:
        vq["staff.id"] = uid
    from .leads import can
    if can("leads"):
        for v in t.find("lead_visits", vq):
            events.append({"kind": "visit", "at": v["at"], "title": f"{'Site visit' if v['kind'] == 'site_visit' else 'Meeting'}: {v['lead_title']}",
                           "detail": f"{v['address']} · {', '.join(s['name'] for s in v['staff'])}", "status": v["status"],
                           "link": f"/app/leads/{v['lead_id']}", "duration_min": v.get("duration_min")})
    fq = {"status": "open", "due": {"$gte": start.isoformat(), "$lte": end.isoformat()}}
    if uid:
        fq["owner_id"] = uid
    for f in t.find("followups", fq):
        rel = f.get("related") or {}
        events.append({"kind": "followup", "date": f["due"], "title": f["title"], "detail": f"{f.get('owner_name')} · {rel.get('label') or ''}",
                       "priority": f.get("priority"), "link": f"/app/leads/{rel['id']}" if rel.get("type") == "lead" else
                       (f"/app/projects/{rel['id']}" if rel.get("type") == "project" else "/app/followups")})
    if can("leads"):
        bq = {"due_date": {"$gte": start.isoformat(), "$lte": end.isoformat()}, "status": {"$in": ["preparing", "submitted"]}}
        if uid:
            bq["$or"] = [{"owner_id": uid}, {"owner_id": None, "created_by": uid}]
        for b in t.find("bids", bq):
            events.append({"kind": "bid", "date": b["due_date"], "title": f"Bid due: {b['title']}", "detail": b.get("client_name") or "",
                           "link": "/app/leads"})
        lids = [str(x["_id"]) for x in t.find("leads", {"status": "open", **({"owner_id": uid} if uid else {})})]
        for p in t.find("proposals", {"lead_id": {"$in": lids}, "status": "sent", "valid_until": {"$gte": start.isoformat(), "$lte": end.isoformat()}}):
            events.append({"kind": "proposal", "date": p["valid_until"], "title": f"Proposal {p['number']} expires", "detail": p["lead_title"],
                           "link": f"/app/leads/{p['lead_id']}"})
    events.sort(key=lambda e: (e.get("date") or e["at"].date().isoformat(), e.get("at") or datetime.min))
    return jsonify({"from": start.isoformat(), "to": end.isoformat(), "scope": "team" if team else "mine", "events": serialize(events)})
