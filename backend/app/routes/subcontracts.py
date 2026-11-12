"""Phase K block 1 — subcontractor management (v4 §9).

* Work package: a scope of lines (typed, or taken from the project's accepted estimate) for one trade.
* Bidding: subcontractors (contacts of type subcontractor) are invited; they price each line in the portal (or the team
  enters a bid they sent). Bids are compared side by side against the estimate's cost rate (internal) and awarded.
* Award = the subcontract agreement: value, retention %, start / end, terms; a printable agreement.
* Measured progress: each payment certificate states the quantity done to date per line; the certificate is
  gross to date − previous certificates, minus retention held. Approving it books the cost (category Subcontract) on
  the project; paying it records the payment. At the end the held retention is released by a release certificate.
* Compliance (insurance, licences …) with expiry alerts already lives on the contact (Phase F); the award warns when the
  subcontractor has an expired document.
* After the job: a performance rating (quality, time, safety, communication 1-5) kept on the subcontractor.
Who: Owner, PM (on the project) and Procurement; costs and the estimate's rates are hidden from roles that do not see costs.
"""
from datetime import date

from flask import Blueprint, request, jsonify, abort, g, Response

from .. import tenancy as t
from ..db import db, oid, serialize
from ..security import api, portal, can
from ..services import notify, project_events as ev, budget
from .lead_money import a_date
from .lead_steps import num
from .projects import load, member

bp = Blueprint("subcontracts", __name__)
STATUSES = ["draft", "bidding", "awarded", "complete", "cancelled"]
RATING_KEYS = ("quality", "time", "safety", "communication")


def r2(v):
    return round((v or 0) + 1e-9, 2)


def writer(p):
    if not (can("procurement", True) or (can("projects", True) and (g.role == "owner" or member(p)))):
        abort(403, "Your role cannot manage subcontracts on this project")


def reader():
    if not (can("procurement") or can("projects")):
        abort(403, "Your role cannot view subcontracts")


def project_of(pid):
    return t.get("projects", pid) if can("procurement") and g.role in ("procurement", "owner") else load(pid)


def compliance_issues(contact):
    today = date.today().isoformat()
    return [c.get("name") or c.get("type") for c in (contact or {}).get("compliance", []) if c.get("expiry") and c["expiry"] < today]


def out(sc):
    d = serialize(sc)
    if g.hide_costs:
        for ln in d.get("lines", []):
            ln.pop("est_rate", None)
    d["certified"] = r2(sum(c["gross_this"] for c in db.sub_certificates.find({"company_id": g.cid, "subcontract_id": str(sc["_id"]), "kind": "progress",
                                                                                 "status": {"$in": ["approved", "paid"]}})))
    return d


def clean_lines(rows, estimate=None):
    est = {ln["id"]: ln for ln in (estimate or {}).get("lines", [])}
    out_ = []
    for r in (rows or [])[:100]:
        src = est.get(r.get("estimate_line_id")) if r.get("estimate_line_id") else None
        desc = (r.get("description") or (src or {}).get("description") or "").strip()[:200] or abort(400, "Each line needs a description")
        qty = num(r.get("qty", (src or {}).get("qty")), f"Quantity of {desc}", required=True, positive=True)
        est_rate = r.get("est_rate")
        if est_rate is None and src:
            est_rate = (src.get("labour_rate") or 0) + (src.get("material_rate") or 0) if r.get("with_material") else (src.get("labour_rate") or 0)
        out_.append({"id": r.get("id") or t.sid(), "description": desc, "qty": qty, "unit": (r.get("unit") or (src or {}).get("unit") or "").strip()[:20] or None,
                     "est_rate": r2(num(est_rate, f"Estimate rate of {desc}") or 0) if not g.hide_costs else 0,
                     "estimate_line_id": r.get("estimate_line_id") if src else None})
    if not out_:
        abort(400, "Add at least one line to the package")
    return out_


# ============================== packages ==============================
@bp.get("/projects/<pid>/estimate-lines")
@api(None)
def estimate_lines(pid):
    reader()
    p = project_of(pid)
    from .finance import estimate_for
    e = estimate_for(p)
    if not e:
        return jsonify({"estimate": None, "lines": []})
    rows = [{"id": ln["id"], "description": ln["description"], "qty": ln.get("qty"), "unit": ln.get("unit"), "room": ln.get("room"),
             "work_type": ln.get("work_type"), **({} if g.hide_costs else {"labour_rate": ln.get("labour_rate"), "material_rate": ln.get("material_rate")})}
            for ln in e.get("lines", [])]
    return jsonify({"estimate": e.get("number") or str(e["_id"]), "lines": rows})


@bp.get("/subcontracts")
@api(None)
def list_all():
    reader()
    q = {}
    if request.args.get("project_id"):
        project_of(request.args["project_id"])
        q["project_id"] = request.args["project_id"]
    elif g.role not in ("owner", "procurement"):
        q["project_id"] = {"$in": [str(x["_id"]) for x in db.projects.find({"company_id": g.cid, "team.user_id": g.uid}, {"_id": 1})]}
    if request.args.get("status"):
        q["status"] = request.args["status"]
    return jsonify([out(x) for x in t.find("subcontracts", q, sort=[("created_at", -1)], limit=300)])


@bp.post("/projects/<pid>/subcontracts")
@api(None)
def add(pid):
    p = project_of(pid)
    writer(p)
    d = request.get_json(force=True) or {}
    from .finance import estimate_for
    st = next((s for s in p.get("stages", []) if s["id"] == d.get("stage_id")), None) if d.get("stage_id") else None
    if d.get("stage_id") and not st:
        abort(400, "Stage not found")
    sc = t.insert("subcontracts", {
        "number": t.next_number("SC", "SC"), "project_id": pid, "project_name": p["name"],
        "title": (d.get("title") or "").strip()[:150] or abort(400, "Name the work package (e.g. Electrical works)"),
        "trade": (d.get("trade") or "").strip()[:40] or None, "scope": (d.get("scope") or "").strip()[:4000] or None,
        "stage_id": st and st["id"], "stage_name": st and st["name"], "due_date": a_date(d.get("due_date"), "Bids due", required=False),
        "lines": clean_lines(d.get("lines"), estimate_for(p)), "bidders": [], "bids": [], "status": "draft", "award": None, "rating": None})
    ev.log(pid, "cost", f"Work package {sc['number']}: {sc['title']}")
    return jsonify(out(sc)), 201


def load_sc(sid, write=True):
    sc = t.get("subcontracts", sid)
    p = project_of(sc["project_id"])
    if write:
        writer(p)
    return sc, p


@bp.get("/subcontracts/<sid>")
@api(None)
def get_one(sid):
    reader()
    sc, p = load_sc(sid, write=False)
    certs = serialize(t.find("sub_certificates", {"subcontract_id": sid}, sort=[("number", 1)]))
    return jsonify({**out(sc), "certificates": certs})


@bp.put("/subcontracts/<sid>")
@api(None)
def edit(sid):
    sc, p = load_sc(sid)
    if sc["status"] not in ("draft", "bidding"):
        abort(409, "An awarded package is changed by a variation, not edited")
    d = request.get_json(force=True) or {}
    ch = {}
    for k, n in (("title", 150), ("trade", 40), ("scope", 4000)):
        if k in d:
            ch[k] = (d.get(k) or "").strip()[:n] or (abort(400, "Title is required") if k == "title" else None)
    if "due_date" in d:
        ch["due_date"] = a_date(d.get("due_date"), "Bids due", required=False)
    if "lines" in d:
        if sc["bids"]:
            abort(409, "Bids are in; cancel the package and make a new one to change the lines")
        from .finance import estimate_for
        ch["lines"] = clean_lines(d["lines"], estimate_for(p))
    return jsonify(out(t.update("subcontracts", sid, ch)))


@bp.post("/subcontracts/<sid>/invite")
@api(None)
def invite(sid):
    sc, p = load_sc(sid)
    if sc["status"] not in ("draft", "bidding"):
        abort(409, "Bidding is closed")
    ids = (request.get_json(force=True) or {}).get("contact_ids") or abort(400, "Choose the subcontractors to invite")
    have = {b["contact_id"] for b in sc["bidders"]}
    bidders = list(sc["bidders"])
    for cid_ in dict.fromkeys(ids):
        c = db.contacts.find_one({"_id": oid(cid_), "company_id": g.cid}) if len(cid_) == 24 else None
        if not c:
            abort(400, "Subcontractor not found")
        if "subcontractor" not in (c.get("types") or []):
            abort(400, f"{c['name']} is not marked as a subcontractor")
        if cid_ in have:
            continue
        bidders.append({"contact_id": cid_, "name": c["name"], "invited_at": t.now(), "status": "invited", "expired_docs": compliance_issues(c)})
        body = (f"Dear {c['name']},\n\n{g.company['name']} invites you to price {sc['title']} on {p['name']}"
                + (f" by {sc['due_date']}" if sc.get("due_date") else "") + ".\nOpen your portal to see the scope and send your rates.\n")
        notify.deliver(g.company, c.get("email"), f"Invitation to bid: {sc['title']} — {p['name']}", body)
        from ..services import messaging
        messaging.notify_contact(c, f"{g.company['name']}: please price {sc['title']} ({p['name']}) in your portal.")
    upd = t.update("subcontracts", sid, {"bidders": bidders, "status": "bidding"})
    return jsonify(out(upd))


def clean_bid(sc, d, contact):
    rates = {r.get("line_id"): r.get("rate") for r in d.get("lines") or []}
    lines = []
    for ln in sc["lines"]:
        rate = num(rates.get(ln["id"]), f"Rate for {ln['description']}", required=True)
        if rate < 0:
            abort(400, f"Rate for {ln['description']} cannot be negative")
        lines.append({"line_id": ln["id"], "rate": r2(rate), "amount": r2(rate * ln["qty"])})
    days = d.get("days")
    if days is not None and (not isinstance(days, int) or not 0 < days <= 1000):
        abort(400, "Days to complete: a whole number")
    return {"contact_id": str(contact["_id"]), "name": contact["name"], "lines": lines, "total": r2(sum(x["amount"] for x in lines)),
            "days": days, "note": (d.get("note") or "").strip()[:1000] or None, "submitted_at": t.now(), "by": g.user.get("name")}


def store_bid(sc, bid):
    bids = [b for b in sc["bids"] if b["contact_id"] != bid["contact_id"]] + [bid]  # a new bid replaces the old one
    bidders = [{**b, "status": "bid"} if b["contact_id"] == bid["contact_id"] else b for b in sc["bidders"]]
    return t.update("subcontracts", str(sc["_id"]), {"bids": bids, "bidders": bidders})


@bp.post("/subcontracts/<sid>/bids")
@api(None)
def team_bid(sid):
    """A bid the subcontractor sent another way (email, paper), entered by the team."""
    sc, p = load_sc(sid)
    if sc["status"] != "bidding":
        abort(409, "Invite subcontractors first; bidding is not open")
    d = request.get_json(force=True) or {}
    if d.get("contact_id") not in {b["contact_id"] for b in sc["bidders"]}:
        abort(400, "Only an invited subcontractor can bid")
    c = db.contacts.find_one({"_id": oid(d["contact_id"])})
    return jsonify(out(store_bid(sc, clean_bid(sc, d, c)))), 201


@bp.get("/subcontracts/<sid>/compare")
@api(None)
def compare(sid):
    reader()
    sc, p = load_sc(sid, write=False)
    bids = sorted(sc["bids"], key=lambda b: b["total"])
    rows = []
    for ln in sc["lines"]:
        cells = {b["contact_id"]: next((x for x in b["lines"] if x["line_id"] == ln["id"]), None) for b in bids}
        low = min((c["rate"] for c in cells.values() if c), default=None)
        rows.append({"line": {k: v for k, v in ln.items() if not (g.hide_costs and k == "est_rate")},
                     "est_amount": None if g.hide_costs else r2(ln.get("est_rate", 0) * ln["qty"]),
                     "bids": {k: {**v, "lowest": v["rate"] == low} if v else None for k, v in cells.items()}})
    est_total = None if g.hide_costs else r2(sum(ln.get("est_rate", 0) * ln["qty"] for ln in sc["lines"]))
    return jsonify({"rows": rows, "bidders": [{"contact_id": b["contact_id"], "name": b["name"], "total": b["total"], "days": b["days"], "note": b["note"],
                                               "vs_estimate": None if est_total in (None, 0) else r2((b["total"] - est_total) / est_total * 100),
                                               "rating": (db.contacts.find_one({"_id": oid(b["contact_id"])}) or {}).get("sub_rating")} for b in bids],
                    "estimate_total": est_total, "lowest": bids[0]["contact_id"] if bids else None})


@bp.post("/subcontracts/<sid>/award")
@api(None)
def award(sid):
    sc, p = load_sc(sid)
    if sc["status"] != "bidding":
        abort(409, "Only a package out for bids can be awarded")
    d = request.get_json(force=True) or {}
    bid = next((b for b in sc["bids"] if b["contact_id"] == d.get("contact_id")), None) or abort(400, "Choose a subcontractor who bid")
    c = db.contacts.find_one({"_id": oid(bid["contact_id"])})
    expired = compliance_issues(c)
    if expired and not d.get("accept_expired"):
        abort(409, f"{c['name']} has expired documents: {', '.join(expired)}. Ask for new ones, or confirm to award anyway.")
    ret = num(d.get("retention_pct", 5), "Retention %")
    if not 0 <= ret <= 20:
        abort(400, "Retention 0-20 %")
    start, end = a_date(d.get("start"), "Start", required=False), a_date(d.get("end"), "End", required=False)
    if start and end and end < start:
        abort(400, "End is before start")
    awd = {"contact_id": bid["contact_id"], "name": bid["name"], "total": bid["total"], "lines": bid["lines"], "retention_pct": ret,
           "start": start, "end": end, "terms": (d.get("terms") or "").strip()[:4000] or None, "agreement_no": sc["number"].replace("SC", "SCA"),
           "awarded_at": t.now(), "by": g.user["name"], "accepted_expired": expired or None, "chose_lowest": bid["total"] == min(b["total"] for b in sc["bids"]),
           "reason": (d.get("reason") or "").strip()[:500] or None}
    if not awd["chose_lowest"] and not awd["reason"]:
        abort(400, "Say why you are not awarding the lowest bid")
    upd = t.update("subcontracts", sid, {"status": "awarded", "award": awd})
    ev.log(sc["project_id"], "cost", f"{sc['number']} {sc['title']} awarded to {bid['name']}" + ("" if g.hide_costs else f" ({bid['total']:,.2f})"))
    for b in sc["bidders"]:
        bc = db.contacts.find_one({"_id": oid(b["contact_id"])}) or {}
        won = b["contact_id"] == bid["contact_id"]
        notify.deliver(g.company, bc.get("email"), f"{sc['title']} — {p['name']}",
                       f"Dear {b['name']},\n\n" + ("Your bid is accepted. The agreement is in your portal." if won else
                                                   "Thank you for your bid. This package has been awarded to another subcontractor."))
    return jsonify(out(upd))


@bp.get("/subcontracts/<sid>/agreement")
@api(None)
def agreement(sid):
    """A printable subcontract agreement (HTML)."""
    reader()
    sc, p = load_sc(sid, write=False)
    a = sc.get("award") or abort(409, "Not awarded yet")
    esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;")
    rates = {x["line_id"]: x for x in a["lines"]}
    rows = "".join(f"<tr><td>{esc(ln['description'])}</td><td>{ln['qty']:g} {esc(ln['unit'])}</td><td>{rates[ln['id']]['rate']:,.2f}</td>"
                   f"<td>{rates[ln['id']]['amount']:,.2f}</td></tr>" for ln in sc["lines"])
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(a['agreement_no'])}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:2rem auto}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px}}</style></head>
<body><h2>Subcontract agreement {esc(a['agreement_no'])}</h2>
<p><b>{esc(g.company['name'])}</b> (the Contractor) and <b>{esc(a['name'])}</b> (the Subcontractor) agree that the Subcontractor carries out
<b>{esc(sc['title'])}</b> on <b>{esc(p['name'])}</b>{(' from ' + a['start']) if a.get('start') else ''}{(' to ' + a['end']) if a.get('end') else ''}.</p>
{f'<p>{esc(sc["scope"])}</p>' if sc.get('scope') else ''}
<table><tr><th>Item</th><th>Quantity</th><th>Rate</th><th>Amount</th></tr>{rows}
<tr><td colspan="3"><b>Contract value</b></td><td><b>{a['total']:,.2f}</b></td></tr></table>
<p>Payment against measured work, certified by the Contractor. Retention of {a['retention_pct']:g}% is held from each payment and released at completion.</p>
{f'<p>{esc(a["terms"])}</p>' if a.get('terms') else ''}
<p style="margin-top:4rem">For the Contractor ______________________ &nbsp;&nbsp; For the Subcontractor ______________________</p></body></html>"""
    return Response(html, mimetype="text/html")


# ============================== payment certificates ==============================
def certs_of(sid, kinds=("progress",), statuses=("draft", "approved", "paid")):
    return list(db.sub_certificates.find({"company_id": g.cid, "subcontract_id": sid, "kind": {"$in": list(kinds)}, "status": {"$in": list(statuses)}}).sort("number", 1))


@bp.post("/subcontracts/<sid>/certificates")
@api(None)
def add_certificate(sid):
    sc, p = load_sc(sid)
    if sc["status"] != "awarded":
        abort(409, "Certificates are for an awarded package that is not complete")
    if certs_of(sid, statuses=("draft",)):
        abort(409, "Approve or delete the draft certificate first")
    d = request.get_json(force=True) or {}
    a = sc["award"]
    rates = {x["line_id"]: x["rate"] for x in a["lines"]}
    prev = certs_of(sid, statuses=("approved", "paid"))
    last = {m["line_id"]: m["qty_to_date"] for m in (prev[-1]["measured"] if prev else [])}
    given = {m.get("line_id"): m.get("qty_to_date") for m in d.get("measured") or []}
    measured = []
    for ln in sc["lines"]:
        q = given.get(ln["id"], last.get(ln["id"], 0))
        q = num(q, f"Quantity done of {ln['description']}") or 0
        if q < last.get(ln["id"], 0):
            abort(400, f"{ln['description']}: quantity to date cannot go down ({last[ln['id']]:g} certified before)")
        if q > ln["qty"] * 1.1 + 1e-9:
            abort(400, f"{ln['description']}: more than 110% of the package quantity — make a variation")
        measured.append({"line_id": ln["id"], "description": ln["description"], "qty_to_date": q, "rate": rates[ln["id"]], "amount": r2(q * rates[ln["id"]])})
    gross_to_date = r2(sum(m["amount"] for m in measured))
    before = r2(sum(c["gross_this"] for c in prev))
    this = r2(gross_to_date - before)
    if this <= 0:
        abort(400, "Nothing new is measured since the last certificate")
    retention = r2(this * a["retention_pct"] / 100)
    c = t.insert("sub_certificates", {
        "subcontract_id": sid, "project_id": sc["project_id"], "project_name": sc["project_name"], "number": len(certs_of(sid, ("progress", "release"), ("approved", "paid", "draft"))) + 1,
        "kind": "progress", "contact_id": a["contact_id"], "name": a["name"], "date": a_date(d.get("date") or date.today().isoformat(), "Date"),
        "measured": measured, "gross_to_date": gross_to_date, "previous": before, "gross_this": this, "retention": retention, "net": r2(this - retention),
        "note": (d.get("note") or "").strip()[:500] or None, "status": "draft", "cost_id": None, "paid": 0, "payments": []})
    return jsonify(serialize(c)), 201


def load_cert(cid_, write=True):
    c = t.get("sub_certificates", cid_)
    sc, p = load_sc(c["subcontract_id"], write)
    return c, sc, p


@bp.delete("/sub-certificates/<cid_>")
@api(None)
def delete_certificate(cid_):
    c, sc, p = load_cert(cid_)
    if c["status"] != "draft":
        abort(409, "Only a draft certificate can be deleted")
    db.sub_certificates.delete_one({"_id": c["_id"]})
    return jsonify({"ok": True})


@bp.post("/sub-certificates/<cid_>/approve")
@api(None)
def approve_certificate(cid_):
    """Approving books the work certified as a cost on the project (category Subcontract)."""
    c, sc, p = load_cert(cid_)
    if c["status"] != "draft":
        abort(409, "Already approved")
    if c["kind"] == "progress":
        st_id = sc.get("stage_id") or next((s["id"] for s in p.get("stages", []) if s.get("status") != "done"), None) or (p.get("stages") or [{}])[0].get("id")
        st = next((s for s in p.get("stages", []) if s["id"] == st_id), {})
        cost = t.insert("costs", {"project_id": sc["project_id"], "project_name": p["name"], "project_code": p.get("code"), "stage_id": st_id,
                                  "stage_name": st.get("name"), "category": "Subcontract", "vendor_id": c["contact_id"], "vendor_name": c["name"],
                                  "date": c["date"], "description": f"{sc['number']} certificate {c['number']}: {sc['title']}", "amount": c["gross_this"],
                                  "tax": 0, "total": c["gross_this"], "qty": None, "unit": None, "rate_id": None, "rate_name": None, "bill_no": None,
                                  "files": [], "kind": "cost", "created_by": g.uid, "created_by_name": g.user.get("name"), "status": "approved",
                                  "approved_by": g.user.get("name"), "decided_at": t.now(), "submitted_at": t.now(), "over_budget": 0,
                                  "subcontract_id": str(sc["_id"]), "certificate_id": cid_})
        if st_id:
            budget.recalc_stage(t.get("projects", sc["project_id"]), st_id)
        ch = {"cost_id": str(cost["_id"])}
    else:
        ch = {}
    upd = t.update("sub_certificates", cid_, {"status": "approved", "approved_by": g.user["name"], "approved_at": t.now(), **ch})
    ev.log(sc["project_id"], "cost", f"{sc['number']} certificate {c['number']} approved ({c['name']})")
    return jsonify(serialize(upd))


@bp.post("/sub-certificates/<cid_>/pay")
@api(None)
def pay_certificate(cid_):
    c, sc, p = load_cert(cid_, write=False)
    if not (can("finance", True) or can("procurement", True) or g.role == "owner"):
        abort(403, "Your role cannot record payments")
    if c["status"] not in ("approved",):
        abort(409, "Approve the certificate first" if c["status"] == "draft" else "Already paid")
    d = request.get_json(force=True) or {}
    amount = num(d.get("amount", r2(c["net"] - c["paid"])), "Amount", required=True, positive=True)
    if amount > r2(c["net"] - c["paid"]) + 0.005:
        abort(400, f"More than the {r2(c['net'] - c['paid']):,.2f} still due on this certificate")
    pay = {"amount": r2(amount), "date": a_date(d.get("date") or date.today().isoformat(), "Date"), "ref": (d.get("ref") or "").strip()[:80] or None,
           "by": g.user["name"], "at": t.now()}
    paid = r2(c["paid"] + amount)
    upd = t.update("sub_certificates", cid_, {"paid": paid, "payments": c["payments"] + [pay], "status": "paid" if paid >= c["net"] - 0.005 else "approved"})
    return jsonify(serialize(upd))


@bp.post("/subcontracts/<sid>/complete")
@api(None)
def complete(sid):
    """Work finished: rate the subcontractor, and release the retention held (a release certificate)."""
    sc, p = load_sc(sid)
    if sc["status"] != "awarded":
        abort(409, "Only an awarded package can be completed")
    if certs_of(sid, statuses=("draft",)):
        abort(409, "Approve or delete the draft certificate first")
    d = request.get_json(force=True) or {}
    rating = {}
    for k in RATING_KEYS:
        v = (d.get("rating") or {}).get(k)
        if not isinstance(v, int) or not 1 <= v <= 5:
            abort(400, f"Rate {k} from 1 to 5")
        rating[k] = v
    rating.update(avg=round(sum(rating[k] for k in RATING_KEYS) / 4, 2), note=(d.get("note") or "").strip()[:500] or None, by=g.user["name"], at=t.now())
    held = r2(sum(c["retention"] for c in certs_of(sid, statuses=("approved", "paid"))))
    rel = None
    if held > 0:
        a = sc["award"]
        rel = t.insert("sub_certificates", {
            "subcontract_id": sid, "project_id": sc["project_id"], "project_name": sc["project_name"],
            "number": len(certs_of(sid, ("progress", "release"), ("approved", "paid", "draft"))) + 1, "kind": "release", "contact_id": a["contact_id"],
            "name": a["name"], "date": date.today().isoformat(), "measured": [], "gross_to_date": 0, "previous": 0, "gross_this": 0, "retention": -held,
            "net": held, "note": "Retention released at completion", "status": "draft", "cost_id": None, "paid": 0, "payments": []})
    upd = t.update("subcontracts", sid, {"status": "complete", "rating": rating, "completed_at": t.now()})
    # the subcontractor's running rating
    rated = [x["rating"]["avg"] for x in db.subcontracts.find({"company_id": g.cid, "award.contact_id": sc["award"]["contact_id"], "rating": {"$ne": None}})]
    db.contacts.update_one({"_id": oid(sc["award"]["contact_id"])}, {"$set": {"sub_rating": {"avg": round(sum(rated) / len(rated), 2), "jobs": len(rated)}}})
    ev.log(sc["project_id"], "cost", f"{sc['number']} complete — {sc['award']['name']} rated {rating['avg']:g}/5" + (f"; retention {held:,.2f} to release" if held and not g.hide_costs else ""))
    return jsonify({**out(upd), "release_certificate": serialize(rel) if rel else None})


@bp.post("/subcontracts/<sid>/cancel")
@api(None)
def cancel(sid):
    sc, p = load_sc(sid)
    if sc["status"] not in ("draft", "bidding"):
        abort(409, "An awarded package cannot be cancelled here")
    return jsonify(out(t.update("subcontracts", sid, {"status": "cancelled"})))


@bp.get("/subcontractors")
@api(None)
def subcontractors():
    """Subcontractors with their rating, jobs, current work and compliance."""
    reader()
    rows = []
    for c in db.contacts.find({"company_id": g.cid, "types": "subcontractor", "deleted_at": None}).sort("name", 1):
        cid_ = str(c["_id"])
        rows.append({"id": cid_, "name": c["name"], "phone": c.get("phone"), "email": c.get("email"), "rating": c.get("sub_rating"),
                     "expired_docs": compliance_issues(c), "invited": db.subcontracts.count_documents({"company_id": g.cid, "bidders.contact_id": cid_}),
                     "awarded": db.subcontracts.count_documents({"company_id": g.cid, "award.contact_id": cid_}),
                     "active": db.subcontracts.count_documents({"company_id": g.cid, "award.contact_id": cid_, "status": "awarded"})})
    return jsonify(rows)


# ============================== portal (the subcontractor) ==============================
def portal_sc(sid):
    sc = db.subcontracts.find_one({"_id": oid(sid), "company_id": g.cid, "bidders.contact_id": g.contact_id}) if len(sid) == 24 else None
    return sc or abort(404, "not found")


def portal_view(sc):
    me = g.contact_id
    mine = next((b for b in sc["bids"] if b["contact_id"] == me), None)
    a = sc.get("award")
    return {"id": str(sc["_id"]), "number": sc["number"], "title": sc["title"], "project_name": sc["project_name"], "trade": sc.get("trade"),
            "scope": sc.get("scope"), "due_date": sc.get("due_date"), "status": sc["status"] if sc["status"] != "awarded" or (a and a["contact_id"] == me) else "closed",
            "lines": [{"id": ln["id"], "description": ln["description"], "qty": ln["qty"], "unit": ln["unit"]} for ln in sc["lines"]],
            "my_bid": serialize(mine), "awarded_to_me": bool(a and a["contact_id"] == me),
            "award": {k: a[k] for k in ("total", "retention_pct", "start", "end", "terms", "agreement_no")} if a and a["contact_id"] == me else None,
            "certificates": serialize([{k: c[k] for k in ("number", "kind", "date", "gross_this", "retention", "net", "paid", "status")}
                                       for c in db.sub_certificates.find({"company_id": g.cid, "subcontract_id": str(sc["_id"]), "contact_id": me,
                                                                          "status": {"$in": ["approved", "paid"]}}).sort("number", 1)])}


@bp.get("/portal/subcontracts")
@portal
def portal_list():
    return jsonify([portal_view(sc) for sc in db.subcontracts.find({"company_id": g.cid, "bidders.contact_id": g.contact_id,
                                                                    "status": {"$in": ["bidding", "awarded", "complete"]}}).sort("created_at", -1)])


@bp.post("/portal/subcontracts/<sid>/bid")
@portal
def portal_bid(sid):
    sc = portal_sc(sid)
    if sc["status"] != "bidding":
        abort(409, "Bidding is closed")
    if sc.get("due_date") and sc["due_date"] < date.today().isoformat():
        abort(409, "The bid date has passed; ask the team")
    c = db.contacts.find_one({"_id": oid(g.contact_id)})
    upd = store_bid(sc, clean_bid(sc, request.get_json(force=True) or {}, c))
    p = db.projects.find_one({"_id": oid(sc["project_id"])})
    notify.send("sub_bid", list(dict.fromkeys(notify.role_users("procurement") + ev.managers(p))), f"Bid from {c['name']} for {sc['title']} ({sc['project_name']})",
                f"/app/procurement?tab=subcontracts&id={sid}", project_id=sc["project_id"], skip_self=False)
    return jsonify(portal_view(upd)), 201


@bp.post("/portal/subcontracts/<sid>/decline")
@portal
def portal_decline(sid):
    sc = portal_sc(sid)
    if sc["status"] != "bidding":
        abort(409, "Bidding is closed")
    bidders = [{**b, "status": "declined"} if b["contact_id"] == g.contact_id else b for b in sc["bidders"]]
    return jsonify(portal_view(t.update("subcontracts", sid, {"bidders": bidders})))
