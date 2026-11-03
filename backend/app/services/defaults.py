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
    {"channel": "email", "name": "Thank you for your enquiry", "subject": "Your enquiry with {{company}}",
     "body": "Dear {{client}},\n\nThank you for contacting {{company}} about {{project}}. {{salesperson}} will call you "
             "within one working day to understand your requirements.\n\nRegards,\n{{salesperson}}\n{{company}}"},
    {"channel": "whatsapp", "name": "Site visit confirmation",
     "body": "Hi {{client}}, confirming our site visit for {{project}} on {{date}}. – {{salesperson}}, {{company}}"},
    {"channel": "sms", "name": "Follow-up after enquiry",
     "body": "Hi {{client}}, following up on {{project}}. When is a good time to talk? - {{salesperson}}, {{company}}"},
    {"channel": "email", "name": "Budget discussion", "subject": "{{project}} – budget",
     "body": "Dear {{client}},\n\nAs discussed, the indicative budget for {{project}} is {{amount}}. We will share a "
             "detailed proposal next.\n\nRegards,\n{{salesperson}}\n{{company}}"},
    {"channel": "whatsapp", "name": "Re-engage cold lead",
     "body": "Hi {{client}}, it has been a while since we spoke about {{project}}. Are you still planning it? We would be glad to help. – {{company}}"},
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

# ---------------- Phase B ----------------
DEFAULT_STAGE_DAYS = 14

# optional templates a company can add (Â§4: "RIBA or AIA stages can be added")
TEMPLATE_PRESETS = {
    "riba": {"name": "RIBA Plan of Work 2020", "service": "architecture", "stages": [
        "0 Strategic Definition", "1 Preparation and Briefing", "2 Concept Design", "3 Spatial Coordination",
        "4 Technical Design", "5 Manufacturing and Construction", "6 Handover", "7 Use"]},
    "aia": {"name": "AIA phases", "service": "architecture", "stages": [
        "Schematic Design", "Design Development", "Construction Documents", "Bidding / Negotiation",
        "Construction Administration"]},
}

SERVICES = ("architecture", "construction", "interior")

# Â§3: contact types
CONTACT_TYPES = ["client", "developer", "architect", "contractor", "subcontractor", "supplier", "consultant",
                 "authority"]

# role a contact or staff member plays on one project (Â§3 "roles per project", Â§4 "project team")
PROJECT_ROLES = ["Client", "Developer", "Project Manager", "Architect", "Interior Designer", "Structural Consultant",
                 "MEP Consultant", "Consultant", "Main Contractor", "Subcontractor", "Supplier",
                 "Authority / Inspector", "Site Supervisor", "Estimator / QS", "Procurement", "Accounts", "Sales",
                 "Other"]

PROJECT_STATUSES = ["planning", "active", "on_hold", "completed", "cancelled"]
PROJECT_TYPES = ["New build", "Renovation", "Fit-out", "Interior"]
TASK_STATUSES = ["todo", "in_progress", "blocked", "done"]
COMPLIANCE_TYPES = ["insurance", "licence", "certificate", "other"]
DESIGN_SERVICES = ("architecture", "interior")


def template_stages(names):
    return [{"name": n, "duration_days": DEFAULT_STAGE_DAYS} for n in names]

# ---------------- Phase C ----------------
LOSS_REASONS = ["Price too high", "Chose a competitor", "Project postponed or cancelled", "No response from client",
                "Budget not available", "Outside our services or area", "Other"]
LEAD_TIMELINES = ["Immediately", "1–3 months", "3–6 months", "6–12 months", "12+ months"]
ACTIVITY_TYPES = ["call", "email", "whatsapp", "meeting", "site_visit", "note"]
FOLLOWUP_CHANNELS = ["call", "email", "whatsapp", "sms", "meeting", "site_visit", "other"]
