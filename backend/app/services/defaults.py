"""Default templates every new company starts with (editable per company)."""

STAGE_TEMPLATES = {
    "architecture": ["Concept", "Schematic design", "Design development", "Construction documents",
                     "Approvals", "Construction support"],
    "construction": ["Pre-construction", "Foundation", "Structure", "MEP", "Finishing", "Handover"],
    "interior": ["Brief", "Concept", "Design", "Selections", "Procurement", "Installation", "Handover"],
}

PIPELINE = ["Lead", "Site visit", "Proposal/Bid", "Negotiation"]

LEAD_SOURCES = ["Website form", "Referral", "Houzz/portals", "Ads", "Walk-in", "Repeat client"]

MESSAGE_TEMPLATES = [
    {"channel": "whatsapp", "name": "Morning work message",
     "body": "Good morning {{worker}}! Today: {{site}} · {{room}} · {{task}}. Drawing: {{drawing}}. Supervisor: {{supervisor}}."},
    {"channel": "whatsapp", "name": "Payment approved",
     "body": "Hi {{name}}, your payment of {{amount}} for {{project}} is approved and paid today."},
    {"channel": "email", "name": "Proposal follow-up",
     "body": "Dear {{client}},\n\nJust checking whether you had a chance to review our proposal {{number}} for {{project}}.\n\nRegards,\n{{company}}"},
    {"channel": "email", "name": "Invoice reminder",
     "body": "Dear {{client}},\n\nThis is a reminder that invoice {{number}} for {{amount}} is due on {{due_date}}.\n\nRegards,\n{{company}}"},
    {"channel": "sms", "name": "Site visit confirmation",
     "body": "Hi {{client}}, confirming our site visit for {{project}} on {{date}}. - {{company}}"},
]

# topic -> role the message is routed to (section 17)
ROUTING = {
    "material_needed": "procurement",
    "payment": "accounts",
    "need_clarification": "designer",
    "design": "designer",
    "need_help": "site",
    "work_done": "site",
    "general": "pm",
}
ROUTING_KEYWORDS = [
    (("payment", "paid", "salary", "money"), "payment"),
    (("material", "cement", "hinges", "tiles", "delivery", "sand", "plywood"), "material_needed"),
    (("drawing", "design", "size", "shade", "colour", "color", "dimension"), "design"),
]
URGENT_KEYWORDS = ("accident", "injury", "safety", "fire", "complaint", "urgent", "collapse")

COMPANY_TYPES = {"architect": "architecture", "contractor": "construction", "interior": "interior"}
