"""Phase F block 3 — selections (finishes, fittings, products the client chooses).

open -> options sent -> chosen -> confirmed -> ordered -> installed.
* Each item has an allowance and options (name, brand, code, supplier, photo, qty, our cost, the client's price, lead
  time). Options can come from the rate library's *product* items.
* Staff send the options to the client (email with prices, never cost) and record the client's choice: who, how, when.
  A choice not made by its due date shows as *Waiting on client* and reminds the PM. Changing a confirmed choice needs
  a reason and reopens the item.
* Allowance vs chosen price: over the allowance, *Create change order* fills a Phase E change order for the difference.
* Ordering creates the Phase E cost (submitted, so the stage budget sees it) — decision F-2 in PLAN.md.
* When every selection of a stage is installed, the stage's "Items installed as per the selection" check is offered.
Who: selections rw (Owner, PM, Designer) on projects they are on; Procurement reads. Site and clients never see cost.
"""
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from ..services import notify, project_events as ev, sales
from ..services.defaults import SIGNOFF_METHODS
from .lead_money import a_date, money_text
from .lead_steps import num
from .projects import load, member

bp = Blueprint("selections", __name__)

STATUSES = ["open", "options_sent", "chosen", "confirmed", "ordered", "installed"]
LABELS = {"open": "Open", "options_sent": "Options sent", "chosen": "Chosen", "confirmed": "Confirmed", "ordered": "Ordered",
          "installed": "Installed"}


def r2(v):
    return round((v or 0) + 1e-9, 2)


def access(pid, write=False):
    if not can("selections"):
        abort(403, "Your role cannot view selections")
    p = load(pid)
    if write and not (can("selections", True) and (g.role == "owner" or member(p))):
        abort(403, "Your role cannot change selections")
    return p


def load_sel(sid):
    s = t.get("selections", sid)
    return s, access(s["project_id"], write=request.method != "GET")


def chosen(s):
    return next((o for o in s.get("options", []) if o["id"] == s.get("chosen_option_id")), None)


def present(s):
    data = t.out(serialize(s))
    ch = chosen(s)
    data["chosen"] = ch and t.out(serialize(ch))
    data["difference"] = r2(ch["price"] - (s.get("allowance") or 0)) if ch else None
    data["overdue"] = s["status"] in ("open", "options_sent") and bool(s.get("due_date")) and s["due_date"] < sales.today()
    return data


def clean_options(rows):
    out = []
    for r in (rows or [])[:12]:
        name = (r.get("name") or "").strip()[:120] or abort(400, "Each option needs a name")
        opt = {"id": r.get("id") or t.sid(), "name": name, "brand": (r.get("brand") or "").strip()[:60] or None,
               "code": (r.get("code") or "").strip()[:40] or None, "qty": num(r.get("qty"), f"Quantity of {name}") or 1,
               "unit": (r.get("unit") or "").strip()[:20] or None, "lead_days": int(r.get("lead_days") or 0),
               "supplier_id": None, "supplier_name": None, "rate_id": None, "file_key": None}
        if r.get("rate_id"):
            rate = db.rate_library.find_one({"_id": oid(r["rate_id"]), "company_id": g.cid, "kind": "product"}) or abort(400, "Choose a product of the rate library")
            opt.update(rate_id=r["rate_id"], unit=opt["unit"] or rate["unit"], brand=opt["brand"] or rate.get("brand"))
        unit_cost = num(r.get("unit_cost"), f"Cost of {name}") or 0
        unit_price = num(r.get("unit_price"), f"Price of {name}") or 0
        opt.update(unit_cost=unit_cost, unit_price=unit_price, cost=r2(opt["qty"] * unit_cost), price=r2(opt["qty"] * unit_price))
        if r.get("supplier_id"):
            c = db.contacts.find_one({"_id": oid(r["supplier_id"]), "company_id": g.cid}) or abort(400, "Supplier not found")
            opt.update(supplier_id=r["supplier_id"], supplier_name=c["name"])
        if r.get("file_key"):
            if not db.files.find_one({"company_id": g.cid, "key": r["file_key"]}):
                abort(400, "Upload the photo first")
            opt["file_key"] = r["file_key"]
        if not 0 <= opt["lead_days"] <= 365:
            abort(400, "Lead time is 0 to 365 days")
        out.append(opt)
    return out


def clean(d, p, s=None):
    ch = {}
    if "stage_id" in d or s is None:
        st = next((x for x in p.get("stages", []) if x["id"] == d.get("stage_id")), None) or abort(400, "Choose a stage of this project")
        ch.update(stage_id=st["id"], stage_name=st["name"], stage_start=st.get("start"))
    if "item" in d or s is None:
        ch["item"] = (d.get("item") or "").strip()[:120] or abort(400, "What is being selected? (e.g. Kitchen countertop)")
    if "room" in d:
        ch["room"] = (d.get("room") or "").strip()[:80] or None
    if "allowance" in d:
        ch["allowance"] = r2(num(d.get("allowance"), "Allowance") or 0)
    if "notes" in d:
        ch["notes"] = (d.get("notes") or "").strip()[:1000] or None
    if "options" in d:
        ch["options"] = clean_options(d["options"])
    if "due_date" in d:
        ch["due_date"] = a_date(d["due_date"], "Choice due", required=False)
    merged = {**(s or {}), **ch}
    if not merged.get("due_date") and merged.get("stage_start") and merged.get("options"):
        lead = max(o["lead_days"] for o in merged["options"])
        ch["due_date"] = (date.fromisoformat(merged["stage_start"]) - timedelta(days=lead)).isoformat()  # in time to order it
    return ch


@bp.get("/projects/<pid>/selections")
@api(None)
def list_selections(pid):
    p = access(pid)
    rows = [present(s) for s in t.find("selections", {"project_id": pid}, sort=[("stage_start", 1), ("room", 1), ("item", 1)])]
    with_choice = [r for r in rows if r["chosen"]]
    return jsonify({"selections": rows, "statuses": LABELS, "methods": SIGNOFF_METHODS,
                    "stages": [{"id": s["id"], "name": s["name"]} for s in p.get("stages", [])],
                    "summary": {"allowance": r2(sum(r.get("allowance") or 0 for r in rows)),
                                "chosen": r2(sum(r["chosen"]["price"] for r in with_choice)),
                                "difference": r2(sum(r["difference"] for r in with_choice)),
                                "waiting": sum(1 for r in rows if r["overdue"])},
                    "can_write": can("selections", True) and (g.role == "owner" or member(p) is not None),
                    "can_order_cost": can("finance", True)})


@bp.get("/selections")
@api("selections", write=False)
def all_selections():
    """Selections page: items across your projects, the ones waiting on the client first."""
    q = {}
    if g.role != "owner":
        q["project_id"] = {"$in": [str(p["_id"]) for p in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]}
    if request.args.get("status"):
        q["status"] = {"$in": request.args["status"].split(",")}
    rows = [present(s) for s in t.find("selections", q, sort=[("due_date", 1)], limit=500)]
    return jsonify({"selections": rows, "statuses": LABELS})


@bp.post("/projects/<pid>/selections")
@api(None)
def add_selection(pid):
    p = access(pid, write=True)
    d = request.get_json(force=True) or {}
    s = t.insert("selections", {"project_id": pid, "project_name": p["name"], "room": None, "allowance": 0, "notes": None, "options": [],
                                "due_date": None, "status": "open", "chosen_option_id": None, "choice": None, "history": [],
                                **clean(d, p)})
    return jsonify(present(s)), 201


@bp.put("/selections/<sid>")
@api(None)
def edit_selection(sid):
    s, p = load_sel(sid)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "A chosen item is changed by reopening it (with a reason)")
    return jsonify(present(t.update("selections", sid, clean(request.get_json(force=True) or {}, p, s))))


@bp.delete("/selections/<sid>")
@api(None)
def delete_selection(sid):
    s, _ = load_sel(sid)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "Only an item not chosen yet can be deleted")
    t.delete("selections", sid)
    return jsonify({"ok": True})


@bp.post("/selections/<sid>/send")
@api(None)
def send_options(sid):
    s, p = load_sel(sid)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "Already chosen")
    if not s["options"]:
        abort(400, "Add the options first")
    client = db.contacts.find_one({"_id": oid(p["client_id"]), "company_id": g.cid}) if p.get("client_id") else None
    result = None
    if (request.get_json(force=True) or {}).get("email", True):
        body = "\n".join([f"{s['item']}" + (f" — {s['room']}" if s.get("room") else "") + f" ({p['name']})", "",
                          "Options:"] + [f"• {o['name']}" + (f" ({o['brand']})" if o.get("brand") else "") + f": {money_text(o['price'])}"
                                         for o in s["options"]]
                         + ([f"\nAllowance in your contract: {money_text(s['allowance'])}"] if s.get("allowance") else [])
                         + ([f"Please choose by {s['due_date']}."] if s.get("due_date") else []) + [f"\nRegards,\n{g.company['name']}"])
        result = notify.deliver(g.company, (client or {}).get("email"), f"Please choose: {s['item']} — {p['name']}", body)
    upd = t.update("selections", sid, {"status": "options_sent", "sent_at": t.now(), "emailed": result})
    ev.log(s["project_id"], "file", f"Selection options sent: {s['item']} ({len(s['options'])} options)" + (f" — email {result}" if result else ""))
    return jsonify(present(upd))


@bp.post("/selections/<sid>/choice")
@api(None)
def record_choice(sid):
    s, p = load_sel(sid)
    if s["status"] not in ("open", "options_sent"):
        abort(409, "A choice is already recorded; reopen the item to change it")
    d = request.get_json(force=True) or {}
    opt = next((o for o in s["options"] if o["id"] == d.get("option_id")), None) or abort(400, "Choose one of the options")
    if d.get("method") not in SIGNOFF_METHODS:
        abort(400, f"How did the client choose? {', '.join(SIGNOFF_METHODS)}")
    name = (d.get("name") or "").strip() or abort(400, "Who chose it for the client?")
    day = a_date(d.get("date") or sales.today(), "Date")
    if day > sales.today():
        abort(400, "The date cannot be in the future")
    choice = {"name": name[:120], "method": d["method"], "date": day, "note": (d.get("note") or "").strip()[:300] or None}
    return jsonify(present(choose_option(s, p, opt, choice)))


def choose_option(s, p, opt, choice):
    """Record the client's choice — by staff, or by the client in the portal (Phase G, method Portal)."""
    sid = str(s["_id"])
    choice = {**choice, "recorded_by": g.user.get("name"), "recorded_at": t.now()}
    upd = t.update("selections", sid, {"status": "chosen", "chosen_option_id": opt["id"], "choice": choice})
    diff = r2(opt["price"] - (s.get("allowance") or 0))
    text = f"{s['item']}: client chose {opt['name']} ({money_text(opt['price'])})" + (
        f", {money_text(diff)} over the allowance" if s.get("allowance") and diff > 0 else "")
    ev.log(s["project_id"], "file", f"Selection — {text}")
    notify.send("selection_chosen", ev.managers(p), f"{p['name']}: {text}", f"/app/projects/{p['_id']}?tab=selections", project_id=s["project_id"])
    return upd


@bp.post("/selections/<sid>/status")
@api(None)
def move_status(sid):
    """Forward only: chosen -> confirmed -> ordered -> installed. Ordering records the cost in Finance."""
    s, p = load_sel(sid)
    st = (request.get_json(force=True) or {}).get("status")
    order = ["chosen", "confirmed", "ordered", "installed"]
    if st not in order[1:] or s["status"] not in order or order.index(st) != order.index(s["status"]) + 1:
        abort(409, f"From {LABELS[s['status']]} the next step is {LABELS.get(order[order.index(s['status']) + 1], '—') if s['status'] in order[:-1] else 'none'}")
    ch = {"status": st, f"{st}_at": t.now(), "history": s.get("history", []) + [{"status": st, "by": g.user.get("name"), "at": t.now()}]}
    if st == "ordered":
        opt = chosen(s)
        if opt["cost"] and can("finance", True):
            from .finance import submit
            cost = t.insert("costs", {"project_id": s["project_id"], "project_name": p["name"], "project_code": p.get("code"),
                                      "stage_id": s["stage_id"], "stage_name": s["stage_name"], "category": "Material",
                                      "vendor_id": opt.get("supplier_id"), "vendor_name": opt.get("supplier_name"), "date": sales.today(),
                                      "description": f"{s['item']}: {opt['name']}"[:300], "amount": opt["cost"], "tax": 0, "total": opt["cost"],
                                      "qty": opt.get("qty"), "unit": opt.get("unit"), "rate_id": opt.get("rate_id"), "rate_name": None,
                                      "bill_no": None, "files": [], "status": "draft", "kind": "cost", "created_by": g.uid,
                                      "created_by_name": g.user.get("name"), "selection_id": sid})
            cost = submit(cost, p)
            ch.update(cost_id=str(cost["_id"]), cost_status=cost["status"])
    upd = t.update("selections", sid, ch)
    ev.log(s["project_id"], "file", f"Selection {s['item']}: {LABELS[st].lower()}")
    if st == "installed":
        offer_installed_check(p, s["stage_id"])
    return jsonify(present(upd))


def offer_installed_check(p, stage_id):
    items = list(db.selections.find({"company_id": g.cid, "project_id": str(p["_id"]), "stage_id": stage_id}, {"status": 1}))
    if not items or any(x["status"] != "installed" for x in items):
        return
    fresh = db.projects.find_one({"_id": p["_id"]})
    changed = False
    for st in fresh.get("stages", []):
        if st["id"] == stage_id:
            for c in st.get("checklist", []):
                if "selection" in c["text"].lower() and not c.get("done"):
                    c["suggested"] = {"by": "selections", "number": "all selections installed", "at": t.now().isoformat()}
                    changed = True
    if changed:
        db.projects.update_one({"_id": p["_id"]}, {"$set": {"stages": fresh["stages"]}})


@bp.post("/selections/<sid>/reopen")
@api(None)
def reopen(sid):
    s, p = load_sel(sid)
    if s["status"] not in ("chosen", "confirmed"):
        abort(409, "Only a chosen or confirmed item is reopened (an ordered one is a change order)")
    reason = ((request.get_json(force=True) or {}).get("reason") or "").strip() or abort(400, "Say why the choice changes")
    upd = t.update("selections", sid, {"status": "options_sent", "chosen_option_id": None, "choice": None,
                                       "history": s.get("history", []) + [{"status": "reopened", "reason": reason[:300], "by": g.user.get("name"),
                                                                            "at": t.now(), "was": (chosen(s) or {}).get("name")}]})
    ev.log(s["project_id"], "file", f"Selection {s['item']} reopened: {reason}")
    return jsonify(present(upd))


@bp.post("/selections/<sid>/change-order")
@api(None)
def to_change_order(sid):
    """The client's choice costs more than the allowance: a draft change order for the difference."""
    from .change_orders import new_co
    s, p = load_sel(sid)
    if not can("change_orders", True):
        abort(403, "Your role cannot raise change orders")
    opt = chosen(s) or abort(409, "Record the client's choice first")
    diff = r2(opt["price"] - (s.get("allowance") or 0))
    if diff <= 0:
        abort(409, "The choice is within the allowance")
    if s.get("co_id"):
        abort(409, "A change order is already raised for this item")
    ratio = opt["cost"] / opt["price"] if opt["price"] else 0
    co = new_co(p, {"stage_id": s["stage_id"], "title": f"Upgrade: {s['item']}"[:150], "reason": "client_request",
                    "description": f"The client chose {opt['name']} ({money_text(opt['price'])}) against an allowance of "
                                   f"{money_text(s.get('allowance') or 0)}.",
                    "lines": [{"description": f"{s['item']}: {opt['name']} over the allowance", "qty": 1,
                               "cost_rate": r2(diff * ratio), "price_rate": diff}]}, {"selection_id": sid})
    upd = t.update("selections", sid, {"co_id": str(co["_id"]), "co_number": co["number"]})
    return jsonify({"selection": present(upd), "change_order": t.out(serialize(co))}), 201
