"""Phase I block 1 — GST split (§1 tax rules, §15 regional tax).

A company keeps the single tax rate and label of Phase E unless it switches `tax_mode` to "gst". Then each invoice
splits its tax by the place of supply: the client's state (from their GSTIN, else the contact's state) against the
company's state (from its GSTIN, else its `state` setting). Same state -> CGST + SGST (half each); another state -> IGST.
No client state known -> treated as within the state (the common case for a local firm), and the invoice says so.
"""
from flask import g

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
}
_BY_NAME = {v.lower(): k for k, v in STATES.items()}


def r2(v):
    return round(v + 1e-9, 2)


def state_code(gstin=None, state=None):
    """Two-digit state code from a GSTIN or a state name / code; None when unknown."""
    if gstin and len(gstin) >= 2 and gstin[:2] in STATES:
        return gstin[:2]
    s = (state or "").strip()
    if s in STATES:
        return s
    return _BY_NAME.get(s.lower())


def enabled(company=None):
    return ((company or g.company).get("tax_mode") or "single") == "gst"


def company_state(company=None):
    c = company or g.company
    return state_code(c.get("gstin"), c.get("state"))


def split(tax, client_gstin=None, client_state=None, company=None):
    """The GST block of an invoice, or None when the company is not on GST."""
    if not enabled(company):
        return None
    ours = company_state(company)
    theirs = state_code(client_gstin, client_state)
    known = theirs is not None
    theirs = theirs or ours
    inter = bool(ours and theirs and ours != theirs)
    tax = r2(tax)
    cgst = 0 if inter else r2(tax / 2)
    return {"mode": "inter" if inter else "intra", "supplier_state": ours and f"{ours}-{STATES[ours]}",
            "place_of_supply": theirs and f"{theirs}-{STATES[theirs]}", "place_known": known,
            "cgst": cgst, "sgst": 0 if inter else r2(tax - cgst), "igst": tax if inter else 0}
