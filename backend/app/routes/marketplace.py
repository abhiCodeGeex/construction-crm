"""Phase L block 4 — the marketplace of supplier catalogues (v4 §7, v4 Phase 3).

One catalogue for the whole platform, across companies:
* Sellers: a company that sells (a supplier, a showroom, a manufacturer using BuildSuite) turns on "Sell on the
  marketplace" (Settings) and publishes products from its own catalogue at a list price. The Super Admin can also list a
  supplier that is not on the platform and keep its price list (CSV-like rows). The Super Admin can hide any listing.
* Buyers: staff who see the product catalogue browse and search (category, brand, city, price), and
    - "add to my catalogue": a copy in their own catalogue at the list price as our cost, the supplier added to their
      contacts (or matched by email) — linked, so when the seller changes the price the buyer sees it and can update;
    - "ask for a quote": quantity, project city, needed by; the seller gets it (notification and email for a company
      on the platform; email for a listed supplier) and answers with a price and lead time, which the buyer sees.
Nothing private crosses companies: a listing shows the seller's name, city, contact for enquiries and the item's own
fields — never the seller's cost, margin, clients or other data. Photos are served from the listing only while it is
published.
"""
import os
import re

from flask import Blueprint, request, jsonify, abort, g, send_from_directory

from .. import tenancy as t
from ..config import Config
from ..db import db, oid, serialize
from ..security import api, can, superadmin
from ..services import notify
from ..services.defaults import WORK_TYPES
from .lead_steps import num

bp = Blueprint("marketplace", __name__)


def r2(v):
    return round((v or 0) + 1e-9, 2)


def market_view(it, buyer_links=None):
    d = {k: it.get(k) for k in ("name", "brand", "sku", "category", "unit", "dimensions", "finish", "description", "lead_days",
                                 "min_order", "price", "currency", "seller_name", "seller_city", "seller_kind", "url")}
    d["id"] = str(it["_id"])
    d["image_urls"] = ([it["image_url"]] if it.get("image_url") else []) + [f"/api/public/market/img/{it['_id']}/{i}" for i in range(len(it.get("photos") or []))]
    d["updated_at"] = serialize(it.get("price_at") or it.get("updated_at"))
    if buyer_links is not None:
        link = buyer_links.get(str(it["_id"]))
        d["in_my_catalogue"] = bool(link)
        d["price_changed"] = bool(link) and r2(link.get("market_price")) != r2(it.get("price"))
    return d


def buyer():
    """Estimators, designers, sales (proposals), procurement and the Owner — not site or accounts (read-only procurement)."""
    if not (can("proposals") or can("selections") or can("procurement", True)):
        abort(403, "Your role cannot use the marketplace")


# ============================== buyers ==============================
@bp.get("/marketplace")
@api(None)
def browse():
    buyer()
    q = {"published": True, "hidden": {"$ne": True}}
    a = request.args
    if a.get("category"):
        q["category"] = a["category"]
    if a.get("city"):
        q["seller_city"] = {"$regex": f"^{re.escape(a['city'])}", "$options": "i"}
    if a.get("seller"):
        q["seller_key"] = a["seller"]
    s = (a.get("q") or "").strip()[:80]
    if s:
        rx = {"$regex": re.escape(s), "$options": "i"}
        q["$or"] = [{"name": rx}, {"brand": rx}, {"sku": rx}, {"finish": rx}, {"seller_name": rx}, {"description": rx}]
    price = {}
    for k, op in (("min", "$gte"), ("max", "$lte")):
        if a.get(k):
            price[op] = num(a[k], "Price")
    if price:
        q["price"] = price
    q["seller_company_id"] = {"$ne": g.cid}  # your own listings are in your catalogue already
    page = max(0, int(a.get("page") or 0))
    total = db.market_items.count_documents(q)
    rows = list(db.market_items.find(q).sort([("name", 1)]).skip(page * 48).limit(48))
    links = {r["market_item_id"]: r for r in db.rate_library.find({"company_id": g.cid, "market_item_id": {"$in": [str(x["_id"]) for x in rows]}},
                                                                   {"market_item_id": 1, "market_price": 1})}
    sellers = list(db.market_items.aggregate([{"$match": {"published": True, "hidden": {"$ne": True}}},
                                              {"$group": {"_id": "$seller_key", "name": {"$first": "$seller_name"}, "city": {"$first": "$seller_city"}, "items": {"$sum": 1}}},
                                              {"$sort": {"name": 1}}, {"$limit": 200}]))
    return jsonify({"items": [market_view(x, links) for x in rows], "total": total, "page": page, "categories": WORK_TYPES + ["Other"],
                    "sellers": [{"key": x["_id"], "name": x["name"], "city": x["city"], "items": x["items"]} for x in sellers]})


@bp.get("/marketplace/<iid>")
@api(None)
def item(iid):
    buyer()
    it = db.market_items.find_one({"_id": oid(iid), "published": True, "hidden": {"$ne": True}}) or abort(404, "Listing not found")
    links = {r["market_item_id"]: r for r in db.rate_library.find({"company_id": g.cid, "market_item_id": iid})}
    return jsonify(market_view(it, links))


def supplier_contact(it):
    """The seller in the buyer's contacts: matched by email (or name), else added as a supplier."""
    email = (it.get("seller_email") or "").lower() or None
    c = (db.contacts.find_one({"company_id": g.cid, "email": email}) if email else None) or \
        db.contacts.find_one({"company_id": g.cid, "name": it["seller_name"], "types": "supplier"})
    if c:
        if "supplier" not in (c.get("types") or []):
            db.contacts.update_one({"_id": c["_id"]}, {"$addToSet": {"types": "supplier"}})
        return c
    return t.insert("contacts", {"name": it["seller_name"], "kind": "company", "types": ["supplier"], "email": email,
                                 "phone": it.get("seller_phone"), "city": it.get("seller_city"), "source": "Marketplace", "notes": None})


@bp.post("/marketplace/<iid>/add")
@api(None)
def add_to_catalogue(iid):
    if not (can("proposals", True) or can("selections", True) or can("procurement", True)):
        abort(403, "Your role cannot change the catalogue")
    it = db.market_items.find_one({"_id": oid(iid), "published": True, "hidden": {"$ne": True}}) or abort(404, "Listing not found")
    if it.get("seller_company_id") == g.cid:
        abort(400, "This is your own listing")
    ex = db.rate_library.find_one({"company_id": g.cid, "market_item_id": iid})
    if ex:
        abort(409, "Already in your catalogue")
    c = supplier_contact(it)
    r = t.insert("rate_library", {"kind": "product", "name": it["name"], "unit": it.get("unit") or "nos", "rate": r2(it["price"]),
                                  "category": it.get("category") if it.get("category") in WORK_TYPES else None, "brand": it.get("brand"),
                                  "notes": f"From the marketplace ({it['seller_name']})", "active": True, "sku": it.get("sku"),
                                  "dimensions": it.get("dimensions"), "finish": it.get("finish"), "url": it.get("url"), "image_url": it.get("image_url"),
                                  "lead_days": it.get("lead_days"), "client_price": None, "supplier_id": str(c["_id"]), "supplier_name": c["name"],
                                  "photos": [], "market_item_id": iid, "market_price": r2(it["price"])})
    db.market_items.update_one({"_id": it["_id"]}, {"$inc": {"adds": 1}})
    return jsonify(serialize(r)), 201


@bp.post("/marketplace/<iid>/update-price")
@api(None)
def update_price(iid):
    if not (can("proposals", True) or can("selections", True) or can("procurement", True)):
        abort(403, "Your role cannot change the catalogue")
    it = db.market_items.find_one({"_id": oid(iid)}) or abort(404, "Listing not found")
    r = db.rate_library.find_one({"company_id": g.cid, "market_item_id": iid}) or abort(404, "Not in your catalogue")
    upd = t.update("rate_library", str(r["_id"]), {"rate": r2(it["price"]), "market_price": r2(it["price"]), "lead_days": it.get("lead_days")})
    return jsonify(serialize(upd))


@bp.post("/marketplace/<iid>/enquire")
@api(None)
def enquire(iid):
    buyer()
    it = db.market_items.find_one({"_id": oid(iid), "published": True, "hidden": {"$ne": True}}) or abort(404, "Listing not found")
    if it.get("seller_company_id") == g.cid:
        abort(400, "This is your own listing")
    d = request.get_json(force=True) or {}
    qty = num(d.get("qty"), "Quantity", required=True, positive=True)
    from .lead_money import a_date
    e = {"item_id": iid, "item_name": it["name"], "unit": it.get("unit"), "list_price": it.get("price"), "seller_key": it["seller_key"],
         "seller_name": it["seller_name"], "seller_company_id": it.get("seller_company_id"), "buyer_company_id": g.cid,
         "buyer_name": g.company["name"], "buyer_user_id": g.uid, "buyer_person": g.user.get("name"), "buyer_email": g.user.get("email"),
         "qty": qty, "city": (d.get("city") or g.company.get("city") or "").strip()[:60] or None,
         "needed_by": a_date(d.get("needed_by"), "Needed by", required=False), "note": (d.get("note") or "").strip()[:1000] or None,
         "status": "open", "reply": None, "created_at": t.now(), "number": None}
    e["number"] = f"MQ-{db.market_enquiries.count_documents({}) + 1:05d}"
    e["_id"] = db.market_enquiries.insert_one(e).inserted_id
    text = (f"Quote request {e['number']} from {g.company['name']} ({g.user.get('name')}): {qty:g} {it.get('unit') or ''} of {it['name']}"
            + (f", needed by {e['needed_by']}" if e["needed_by"] else "") + (f", {e['city']}" if e["city"] else "") + (f". {e['note']}" if e["note"] else ""))
    if it.get("seller_company_id"):
        seller = db.companies.find_one({"_id": oid(it["seller_company_id"])})
        if seller:
            users = [str(u["_id"]) for u in db.users.find({"company_id": it["seller_company_id"], "kind": "staff", "active": {"$ne": False},
                                                            "role": {"$in": ["owner", "sales", "procurement"]}}, {"_id": 1})]
            notify.send("market_enquiry", users, text, "/app/marketplace?tab=selling", company=seller, skip_self=False)
    elif it.get("seller_email"):
        notify.deliver(g.company, it["seller_email"], f"Quote request {e['number']}: {it['name']}",
                       text + f"\n\nReply to {g.user.get('email')} — {g.company['name']}")
    return jsonify(serialize(e)), 201


@bp.get("/marketplace-enquiries")
@api(None)
def my_enquiries():
    """Quote requests I sent (as a buyer) and the ones my company received (as a seller)."""
    buyer_rows = [serialize(x) for x in db.market_enquiries.find({"buyer_company_id": g.cid}).sort("created_at", -1).limit(100)]
    seller_rows = []
    if can("leads") or can("procurement") or g.role == "owner":
        seller_rows = [serialize({k: v for k, v in x.items() if k != "buyer_user_id"})
                       for x in db.market_enquiries.find({"seller_company_id": g.cid}).sort("created_at", -1).limit(100)]
    return jsonify({"sent": buyer_rows, "received": seller_rows})


@bp.post("/marketplace-enquiries/<eid>/reply")
@api(None)
def reply(eid):
    e = db.market_enquiries.find_one({"_id": oid(eid), "seller_company_id": g.cid}) or abort(404, "Enquiry not found")
    if not (g.role in ("owner", "sales", "procurement")):
        abort(403, "Your role cannot answer quote requests")
    d = request.get_json(force=True) or {}
    price = num(d.get("price"), "Price", required=True, positive=True)
    lead = d.get("lead_days")
    rep = {"price": r2(price), "lead_days": int(lead) if str(lead or "").isdigit() else None, "note": (d.get("note") or "").strip()[:1000] or None,
           "valid_until": (d.get("valid_until") or None), "by": g.user.get("name"), "at": t.now()}
    db.market_enquiries.update_one({"_id": e["_id"]}, {"$set": {"status": "quoted", "reply": rep}})
    buyer_co = db.companies.find_one({"_id": oid(e["buyer_company_id"])})
    if buyer_co:
        notify.send("market_enquiry", [e["buyer_user_id"]], f"{g.company['name']} quoted {rep['price']:g} per {e.get('unit') or 'unit'} for {e['item_name']} ({e['number']})",
                    "/app/marketplace?tab=quotes", company=buyer_co, skip_self=False)
    return jsonify(serialize(db.market_enquiries.find_one({"_id": e["_id"]})))


# ============================== sellers (a company on the platform) ==============================
def seller_key(company):
    return f"c:{company['_id']}"


@bp.get("/marketplace-selling")
@api("settings", write=False)
def selling():
    s = g.company.get("marketplace") or {}
    mine = {x["product_id"]: x for x in db.market_items.find({"seller_company_id": g.cid})}
    prods = t.find("rate_library", {"kind": "product", "active": True}, sort=[("name", 1)])
    return jsonify({"enabled": bool(s.get("enabled")), "contact_email": s.get("contact_email") or g.company.get("email"), "about": s.get("about"),
                    "products": [{"id": str(p["_id"]), "name": p["name"], "brand": p.get("brand"), "unit": p.get("unit"), "client_price": p.get("client_price"),
                                  "listed": bool(mine.get(str(p["_id"]), {}).get("published")), "list_price": mine.get(str(p["_id"]), {}).get("price"),
                                  "hidden": bool(mine.get(str(p["_id"]), {}).get("hidden")), "adds": mine.get(str(p["_id"]), {}).get("adds", 0)} for p in prods]})


@bp.put("/marketplace-selling")
@api("settings")
def put_selling():
    d = request.get_json(force=True) or {}
    s = {**(g.company.get("marketplace") or {})}
    if "enabled" in d:
        s["enabled"] = bool(d["enabled"])
    if "contact_email" in d:
        v = (d.get("contact_email") or "").strip()[:120] or None
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            abort(400, "Enquiry email is not valid")
        s["contact_email"] = v
    if "about" in d:
        s["about"] = (d.get("about") or "").strip()[:500] or None
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"marketplace": s}})
    g.company["marketplace"] = s
    if not s.get("enabled"):
        db.market_items.update_many({"seller_company_id": g.cid}, {"$set": {"published": False}})
    t.audit("update", "companies", g.company["_id"], note=f"Marketplace selling: {'on' if s.get('enabled') else 'off'}")
    return selling()


@bp.post("/marketplace-selling/<pid>")
@api("settings")
def publish(pid):
    """List (or update) one of our products at a list price; {"published": false} takes it off."""
    if not (g.company.get("marketplace") or {}).get("enabled"):
        abort(409, "Turn on selling on the marketplace first")
    p = t.get("rate_library", pid)
    if p["kind"] != "product":
        abort(400, "Only catalogue products are listed")
    d = request.get_json(force=True) or {}
    ex = db.market_items.find_one({"seller_company_id": g.cid, "product_id": pid})
    if d.get("published") is False:
        if ex:
            db.market_items.update_one({"_id": ex["_id"]}, {"$set": {"published": False}})
        return selling()
    price = r2(num(d.get("price") if d.get("price") is not None else p.get("client_price"), "List price", required=True, positive=True))
    s = g.company.get("marketplace") or {}
    doc = {"seller_company_id": g.cid, "seller_key": seller_key(g.company), "seller_kind": "company", "seller_name": g.company["name"],
           "seller_city": g.company.get("city"), "seller_email": s.get("contact_email") or g.company.get("email"), "seller_phone": g.company.get("phone"),
           "product_id": pid, "name": p["name"], "brand": p.get("brand"), "sku": p.get("sku"), "category": p.get("category") or "Other",
           "unit": p.get("unit"), "dimensions": p.get("dimensions"), "finish": p.get("finish"), "description": p.get("notes"),
           "lead_days": p.get("lead_days"), "min_order": num(d.get("min_order"), "Minimum order") if d.get("min_order") else None,
           "price": price, "currency": g.company.get("currency") or "INR", "url": p.get("url"), "image_url": p.get("image_url"),
           "photos": [{"company_id": g.cid, "key": k} for k in (p.get("photos") or [])[:6]], "published": True, "updated_at": t.now()}
    if ex:
        if r2(ex.get("price")) != price:
            doc["price_at"] = t.now()
        db.market_items.update_one({"_id": ex["_id"]}, {"$set": doc})
    else:
        db.market_items.insert_one({**doc, "hidden": False, "adds": 0, "created_at": t.now(), "price_at": t.now()})
    return selling()


@bp.get("/public/market/img/<iid>/<int:n>")
def market_img(iid, n):
    it = db.market_items.find_one({"_id": oid(iid), "published": True, "hidden": {"$ne": True}}) or abort(404)
    ph = (it.get("photos") or [])[n] if n < len(it.get("photos") or []) else abort(404)
    key = ph["key"]
    if not key.startswith(f"{ph['company_id']}_") or not os.path.exists(os.path.join(Config.UPLOAD_DIR, key)):
        abort(404)
    return send_from_directory(Config.UPLOAD_DIR, key)


# ============================== Super Admin ==============================
@bp.get("/sa/marketplace")
@superadmin("companies")
def sa_list():
    q = {}
    if request.args.get("q"):
        rx = {"$regex": re.escape(request.args["q"][:80]), "$options": "i"}
        q["$or"] = [{"name": rx}, {"seller_name": rx}]
    rows = list(db.market_items.find(q).sort("updated_at", -1).limit(300))
    return jsonify({"items": [{**market_view(x), "published": x.get("published"), "hidden": bool(x.get("hidden")), "adds": x.get("adds", 0),
                               "seller_kind": x.get("seller_kind")} for x in rows],
                    "enquiries": db.market_enquiries.count_documents({}), "sellers": len(db.market_items.distinct("seller_key"))})


@bp.post("/sa/marketplace/<iid>/hide")
@superadmin("companies")
def sa_hide(iid):
    from .platform import sa_audit
    hide = bool((request.get_json(force=True) or {}).get("hidden", True))
    r = db.market_items.update_one({"_id": oid(iid)}, {"$set": {"hidden": hide}})
    if not r.matched_count:
        abort(404, "Listing not found")
    sa_audit("marketplace_hide" if hide else "marketplace_show", iid)
    return jsonify({"hidden": hide})


@bp.post("/sa/marketplace/suppliers")
@superadmin("companies")
def sa_supplier():
    """A supplier that is not on the platform, with its price list: {name, city, email, phone, items: [{name, unit, price, …}]}.
    Sending the same supplier again replaces its list."""
    from .platform import sa_audit
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip()[:120] or abort(400, "Supplier name is required")
    email = (d.get("email") or "").strip().lower()[:120] or None
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        abort(400, "Email is not valid")
    key = "s:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    rows = []
    for x in (d.get("items") or [])[:2000]:
        n = (x.get("name") or "").strip()[:200]
        if not n:
            continue
        try:
            price = r2(float(x.get("price")))
            assert price > 0
        except (TypeError, ValueError, AssertionError):
            abort(400, f"{n}: price must be a positive number")
        rows.append({"seller_company_id": None, "seller_key": key, "seller_kind": "listed", "seller_name": name, "seller_city": (d.get("city") or "").strip()[:60] or None,
                     "seller_email": email, "seller_phone": (d.get("phone") or "").strip()[:20] or None, "product_id": None, "name": n,
                     "brand": (x.get("brand") or "").strip()[:80] or None, "sku": (x.get("sku") or "").strip()[:60] or None,
                     "category": x.get("category") if x.get("category") in WORK_TYPES else "Other", "unit": (x.get("unit") or "nos").strip()[:20],
                     "dimensions": (x.get("dimensions") or "").strip()[:120] or None, "finish": (x.get("finish") or "").strip()[:120] or None,
                     "description": (x.get("description") or "").strip()[:500] or None, "lead_days": int(x["lead_days"]) if str(x.get("lead_days") or "").isdigit() else None,
                     "min_order": None, "price": price, "currency": (d.get("currency") or "INR")[:3], "url": None,
                     "image_url": x.get("image_url") if re.match(r"^https://", x.get("image_url") or "") else None, "photos": [],
                     "published": True, "hidden": False, "adds": 0, "created_at": t.now(), "updated_at": t.now(), "price_at": t.now()})
    if not rows:
        abort(400, "Add the supplier's items")
    old = {x["name"].lower(): x for x in db.market_items.find({"seller_key": key})}
    keep_ids = []
    for r in rows:
        ex = old.get(r["name"].lower())
        if ex:
            ch = {k: v for k, v in r.items() if k not in ("created_at", "adds", "hidden")}
            if r2(ex.get("price")) == r["price"]:
                ch.pop("price_at")
            db.market_items.update_one({"_id": ex["_id"]}, {"$set": ch})
            keep_ids.append(ex["_id"])
        else:
            keep_ids.append(db.market_items.insert_one(r).inserted_id)
    db.market_items.update_many({"seller_key": key, "_id": {"$nin": keep_ids}}, {"$set": {"published": False}})
    sa_audit("marketplace_supplier", key, note=f"{name}: {len(rows)} item(s)")
    return jsonify({"seller_key": key, "items": len(rows)}), 201
