"""Phase I block 4 — the interior product catalogue, markup rules and the selection margin report (§7).

* Products are the rate library's *product* items with catalogue fields: supplier, SKU, dimensions, finish, photos,
  trade price (the rate — our cost), client price, lead time, the supplier's web page.
* *Add from a link* (§7 "web clipper"): the server reads a supplier's product page and suggests the name, photo, price
  and brand from its Open Graph / schema.org tags. Only public web addresses are fetched (no private or local
  networks, every redirect checked), with a short timeout and a size cap; nothing is saved until the user saves it.
* Markup rules (§7 "markup rules per category or client"): a company default, a % per product category and a % per
  client; the client's rule wins, then the category's, then the default. A selection option with a cost and no
  price takes its price from the rule.
* Margin report per project (§7 "margin report per project"): chosen options' cost, price and margin by room — cost
  fields, so only roles that see costs.
"""
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

from flask import Blueprint, request, jsonify, abort, g

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, can
from .lead_steps import num

bp = Blueprint("catalogue", __name__)

MARKUP_DEFAULTS = {"default_pct": 25, "by_category": {}, "by_client": {}}


def r2(v):
    return round((v or 0) + 1e-9, 2)


# ---------------- markup rules ----------------
def markup_rules(company=None):
    return {**MARKUP_DEFAULTS, **((company or g.company).get("markup_rules") or {})}


def markup_for(category=None, client_id=None):
    """The % added to our cost: the client's rule, else the category's, else the company default."""
    m = markup_rules()
    if client_id and client_id in m["by_client"]:
        return float(m["by_client"][client_id]), "client"
    if category and category in m["by_category"]:
        return float(m["by_category"][category]), "category"
    return float(m["default_pct"]), "default"


@bp.get("/settings/markup")
@api(None)
def get_markup():
    if g.hide_costs:
        abort(403, "Your role cannot see markups")
    m = markup_rules()
    names = {str(c["_id"]): c["name"] for c in db.contacts.find({"company_id": g.cid, "_id": {"$in": [oid(x) for x in m["by_client"]]}}, {"name": 1})}
    return jsonify({**m, "client_names": names})


@bp.put("/settings/markup")
@api("settings")
def put_markup():
    d = request.get_json(force=True) or {}

    def pct(v, label):
        v = num(v, label, required=True)
        if not 0 <= v <= 500:
            abort(400, f"{label} is 0 to 500%")
        return v

    m = markup_rules()
    if "default_pct" in d:
        m["default_pct"] = pct(d["default_pct"], "Default markup")
    if "by_category" in d:
        m["by_category"] = {str(k)[:60]: pct(v, f"Markup for {k}") for k, v in (d["by_category"] or {}).items() if str(k).strip()}
    if "by_client" in d:
        out = {}
        for k, v in (d["by_client"] or {}).items():
            if not db.contacts.find_one({"_id": oid(k), "company_id": g.cid}, {"_id": 1}):
                abort(400, "Client not found")
            out[k] = pct(v, "Client markup")
        m["by_client"] = out
    db.companies.update_one({"_id": g.company["_id"]}, {"$set": {"markup_rules": m}})
    return jsonify(m)


# ---------------- product catalogue ----------------
def product_fields(d, kind):
    """Catalogue fields kept on a rate-library item of kind *product* (Phase I)."""
    if kind != "product":
        return {}
    out = {}
    for k, n in (("sku", 60), ("dimensions", 120), ("finish", 120), ("url", 500), ("image_url", 500)):
        if k in d:
            v = (d.get(k) or "").strip()[:n] or None
            if k in ("url", "image_url") and v and not re.match(r"^https?://", v):
                abort(400, "Links start with http:// or https://")
            out[k] = v
    if "lead_days" in d:
        v = int(num(d.get("lead_days"), "Lead time") or 0)
        if not 0 <= v <= 365:
            abort(400, "Lead time is 0 to 365 days")
        out["lead_days"] = v
    if "client_price" in d:
        out["client_price"] = r2(num(d.get("client_price"), "Client price") or 0) or None
    if "supplier_id" in d:
        if d["supplier_id"]:
            c = db.contacts.find_one({"_id": oid(d["supplier_id"]), "company_id": g.cid}) or abort(400, "Supplier not found")
            out.update(supplier_id=d["supplier_id"], supplier_name=c["name"])
        else:
            out.update(supplier_id=None, supplier_name=None)
    if "photos" in d:
        keys = []
        for key in dict.fromkeys(d.get("photos") or []):
            db.files.find_one({"company_id": g.cid, "key": key}) or abort(400, "Upload the photo first")
            keys.append(key)
        out["photos"] = keys[:8]
    return out


def product_view(r):
    data = serialize(r)
    pct, src = markup_for(r.get("category"))
    data["suggested_price"] = r2(r["rate"] * (1 + pct / 100))
    data["markup_source"] = src
    data["price"] = r.get("client_price") or data["suggested_price"]
    data["photo_urls"] = [f"/api/files/{k}" for k in r.get("photos") or []]
    if g.hide_costs:
        for k in ("rate", "suggested_price", "markup_source", "actuals", "last_actual", "suggested_rate"):
            data.pop(k, None)
    return data


@bp.get("/products")
@api(None)
def list_products():
    if not (can("proposals") or can("selections") or can("procurement")):
        abort(403, "Your role cannot view the product catalogue")
    q = {"kind": "product", "active": True}
    if request.args.get("category"):
        q["category"] = request.args["category"]
    rows = [product_view(r) for r in t.find("rate_library", q, sort=[("category", 1), ("name", 1)])]
    s = (request.args.get("q") or "").strip().lower()
    if s:
        rows = [r for r in rows if s in " ".join(str(r.get(k) or "") for k in ("name", "brand", "sku", "finish", "supplier_name")).lower()]
    return jsonify({"products": rows, "can_write": can("proposals", True) or can("selections", True)})


# ---------------- add from a link ----------------
class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_url(url):
    """Only http(s) to hosts that resolve to public addresses (no local, private, link-local or reserved ones)."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        abort(400, "Paste the product's web address (http or https)")
    if u.port not in (None, 80, 443):
        abort(400, "Only standard web ports are read")
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(u.hostname, None)}
    except socket.gaierror:
        abort(400, "That web address cannot be found")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            abort(400, "That address is not a public web page")
    return url


def fetch_page(url, max_bytes=1_500_000):
    public_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BuildSuite product clipper)",
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with opener.open(req, timeout=6) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                abort(400, "That link is not a web page")
            raw = r.read(max_bytes + 1)
            final = r.geturl()
    except urllib.error.HTTPError as e:
        abort(400, f"The page answered {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError):
        abort(400, "The page could not be read")
    return raw[:max_bytes].decode("utf-8", "replace"), final


def _meta(page, *names):
    for n in names:
        m = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']+)', page, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name|itemprop)=["\']' + re.escape(n) + r'["\']', page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _jsonld_product(page):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if "@graph" in x:
                    stack += x["@graph"] if isinstance(x["@graph"], list) else [x["@graph"]]
                typ = x.get("@type")
                if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                    return x
    return None


def parse_product(page, url):
    """Name, photo, price, currency, brand and SKU from the page's Open Graph / schema.org data."""
    out = {"url": url, "name": None, "image_url": None, "price": None, "currency": None, "brand": None, "sku": None, "description": None}
    p = _jsonld_product(page)
    if p:
        out["name"] = p.get("name")
        img = p.get("image")
        out["image_url"] = img[0] if isinstance(img, list) and img else (img.get("url") if isinstance(img, dict) else img)
        brand = p.get("brand")
        out["brand"] = brand.get("name") if isinstance(brand, dict) else brand
        out["sku"] = p.get("sku")
        offers = p.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict):
            out["price"] = offer.get("price") or offer.get("lowPrice")
            out["currency"] = offer.get("priceCurrency")
        out["description"] = p.get("description")
    out["name"] = out["name"] or _meta(page, "og:title", "twitter:title") or \
        (lambda m: html.unescape(m.group(1)).strip() if m else None)(re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I))
    out["image_url"] = out["image_url"] or _meta(page, "og:image", "twitter:image")
    out["price"] = out["price"] or _meta(page, "product:price:amount", "og:price:amount", "price")
    out["currency"] = out["currency"] or _meta(page, "product:price:currency", "og:price:currency", "priceCurrency")
    out["brand"] = out["brand"] or _meta(page, "product:brand", "og:brand", "brand")
    out["description"] = out["description"] or _meta(page, "og:description", "description")
    try:
        out["price"] = float(str(out["price"]).replace(",", "")) if out["price"] not in (None, "") else None
    except ValueError:
        out["price"] = None
    if out["image_url"]:
        out["image_url"] = urllib.parse.urljoin(url, out["image_url"])
        if not out["image_url"].startswith(("http://", "https://")):
            out["image_url"] = None
    for k in ("name", "brand", "sku"):
        out[k] = (str(out[k]).strip()[:120] or None) if out[k] else None
    out["description"] = (out["description"] or "")[:300] or None
    return out


@bp.post("/products/clip")
@api(None)
def clip():
    if not (can("proposals", True) or can("selections", True)):
        abort(403, "Your role cannot add products")
    url = ((request.get_json(force=True) or {}).get("url") or "").strip()
    page, final = fetch_page(url)
    data = parse_product(page, final)
    if not data["name"]:
        abort(422, "No product details were found on that page; fill them in by hand")
    return jsonify(data)


# ---------------- selection margin report ----------------
@bp.get("/projects/<pid>/selections/margin")
@api(None)
def selection_margin(pid):
    from .selections import access, chosen
    access(pid)
    if g.hide_costs or not (can("finance") or can("selections", True)):
        abort(403, "Your role cannot see selection margins")
    rooms, total = {}, {"cost": 0.0, "price": 0.0, "allowance": 0.0}
    for s in db.selections.find({"company_id": g.cid, "project_id": pid}).sort([("room", 1), ("item", 1)]):
        ch = chosen(s)
        if not ch:
            continue
        rm = rooms.setdefault(s.get("room") or "—", {"room": s.get("room") or "—", "items": [], "cost": 0.0, "price": 0.0})
        margin = r2(ch["price"] - ch["cost"])
        rm["items"].append({"item": s["item"], "option": ch["name"], "status": s["status"], "cost": ch["cost"], "price": ch["price"],
                            "margin": margin, "margin_pct": round(margin / ch["price"] * 100, 1) if ch["price"] else None,
                            "allowance": s.get("allowance") or 0})
        rm["cost"] = r2(rm["cost"] + ch["cost"])
        rm["price"] = r2(rm["price"] + ch["price"])
        for k, v in (("cost", ch["cost"]), ("price", ch["price"]), ("allowance", s.get("allowance") or 0)):
            total[k] = r2(total[k] + v)
    for rm in rooms.values():
        rm["margin"] = r2(rm["price"] - rm["cost"])
        rm["margin_pct"] = round(rm["margin"] / rm["price"] * 100, 1) if rm["price"] else None
    total["margin"] = r2(total["price"] - total["cost"])
    total["margin_pct"] = round(total["margin"] / total["price"] * 100, 1) if total["price"] else None
    return jsonify({"rooms": list(rooms.values()), "total": total})
