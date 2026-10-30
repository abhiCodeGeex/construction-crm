"""Proposal / estimate / quote totals for the three pricing styles (section 5)."""
from ..crud import num


def compute_proposal(p):
    kind = p.get("type", "estimate")
    items = p.get("items", []) or []
    subtotal_cost = 0.0
    net_items = 0.0
    for it in items:
        qty = num(it.get("qty"), 1)
        if kind == "estimate":
            cost = qty * (num(it.get("material_rate")) + num(it.get("labour_rate")))
            it["line_cost"] = round(cost, 2)
            it["amount"] = round(cost, 2)
        elif kind == "interior":
            trade = num(it.get("trade_price"))
            markup = num(it.get("markup_pct"), num(p.get("markup_pct")))
            it["line_cost"] = round(qty * trade, 2)
            it["rate"] = round(trade * (1 + markup / 100), 2)
            it["amount"] = round(qty * it["rate"], 2)
        else:  # fee proposal: fixed / hourly / percent / per_area handled by qty * rate
            mode = it.get("mode", "fixed")
            if mode == "percent":
                it["amount"] = round(num(it.get("base")) * num(it.get("rate")) / 100, 2)
            else:
                it["amount"] = round(qty * num(it.get("rate")), 2)
            it["line_cost"] = 0
        included = not it.get("optional") or it.get("included")
        if included:
            subtotal_cost += it["line_cost"]
            net_items += it["amount"]

    if kind == "estimate":
        overheads = subtotal_cost * num(p.get("overheads_pct")) / 100
        markup_amount = (subtotal_cost + overheads) * num(p.get("markup_pct")) / 100
        subtotal = subtotal_cost + overheads + markup_amount
        p["overheads"] = round(overheads, 2)
        p["markup_amount"] = round(markup_amount, 2)
    elif kind == "interior":
        subtotal = net_items + num(p.get("design_fee"))
        p["markup_amount"] = round(net_items - subtotal_cost, 2)
    else:
        subtotal = net_items
    discount = num(p.get("discount"))
    if p.get("discount_type") == "percent":
        discount = subtotal * discount / 100
    taxable = max(subtotal - discount, 0)
    tax = taxable * num(p.get("tax_pct"), 18) / 100
    p["subtotal_cost"] = round(subtotal_cost, 2)
    p["subtotal"] = round(subtotal, 2)
    p["discount_amount"] = round(discount, 2)
    p["tax"] = round(tax, 2)
    p["total"] = round(taxable + tax, 2)
    p["margin"] = round(taxable - subtotal_cost, 2) if subtotal_cost else None
    p["items"] = items
    return p


def invoice_totals(inv):
    items = inv.get("items", []) or []
    sub = 0.0
    for it in items:
        it["amount"] = round(num(it.get("qty"), 1) * num(it.get("rate")), 2)
        sub += it["amount"]
    tax = sub * num(inv.get("tax_pct"), 18) / 100
    total = sub + tax
    retention = sub * num(inv.get("retention_pct")) / 100
    inv["subtotal"] = round(sub, 2)
    inv["tax"] = round(tax, 2)
    inv["total"] = round(total, 2)
    inv["retention"] = round(retention, 2)
    inv["amount_due"] = round(total - retention, 2)
    paid = round(sum(num(p.get("amount")) for p in inv.get("payments", []) or []), 2)
    inv["paid"] = paid
    if inv.get("status") not in ("draft", "void"):
        inv["status"] = "paid" if paid >= inv["amount_due"] - 0.01 else ("partial" if paid > 0 else "sent")
    return inv
