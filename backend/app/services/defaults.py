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

# ---------------- Phase C+ (leads in depth) ----------------
# a site visit is booked as an appointment; "site_visit" stays valid only for entries logged before Phase C+
LOGGABLE_ACTIVITIES = ["call", "email", "whatsapp", "meeting", "note"]
CALL_OUTCOMES = ["Reached", "No answer", "Busy", "Wrong number", "Call back later"]
TEMPERATURES = ["hot", "warm", "cold"]
CONTACT_CHANNELS = ["call", "whatsapp", "email", "sms"]
STAKEHOLDER_ROLES = {"Co-owner": "Client", "Family member": "Other", "Architect": "Architect", "Developer": "Developer",
                     "Consultant": "Consultant", "Other": "Other"}  # role on the lead -> role on the won project

# steps the system checks before a lead may leave a stage (Settings -> Sales -> Stage rules)
STAGE_REQUIREMENTS = {
    "first_contact": "First contact logged (call, email, WhatsApp or meeting)",
    "visit_done": "Site visit done and its report submitted",
    "measurements": "Measurements recorded",
    "brief_complete": "Brief marked complete",
    "estimate_approved": "An estimate approved",
    "proposal_sent": "A proposal sent to the client",
}
DEFAULT_STAGE_RULES = {
    "Lead": {"checklist": ["Budget confirmed", "Decision-maker identified", "Timeline confirmed",
                           "Site ready or possession date known", "Loan or approvals needed checked"],
             "requires": ["first_contact"], "max_days": 3, "probability": 10},
    "Site visit": {"checklist": ["Site condition checklist filled", "Photos taken", "Client drawings collected"],
                   "requires": ["visit_done", "measurements", "brief_complete"], "max_days": 10, "probability": 25},
    "Proposal/Bid": {"checklist": [], "requires": ["estimate_approved", "proposal_sent"], "max_days": 14,
                     "probability": 50},
    "Negotiation": {"checklist": [], "requires": [], "max_days": 21, "probability": 75},
}

VISIT_KINDS = ["site_visit", "meeting"]
VISIT_STATUSES = ["scheduled", "confirmed", "done", "no_show", "cancelled"]
SITE_CHECKLIST = ["Power supply available", "Water supply available", "Existing finishes to be removed",
                  "Demolition needed", "Lift or stair access for material", "Society / authority rules checked",
                  "Parking and unloading space", "Seepage or damp visible"]
OPENING_KINDS = ["door", "window", "opening"]
# quantity an estimate line can take from a room's measurements
MEASURE_SOURCES = {"floor_area": "Floor area", "ceiling_area": "Ceiling area", "wall_area": "Wall area",
                   "net_wall_area": "Wall area less doors and windows", "perimeter": "Perimeter"}
WORK_TYPES = ["Civil work", "False ceiling", "Flooring", "Modular kitchen", "Wardrobes", "Electrical", "Plumbing",
              "Painting", "Furniture", "Décor & furnishing", "Lighting", "HVAC", "Structure", "Facade", "Landscape"]
FILE_FOLDERS = ["photos", "client_drawings", "brief", "proposals", "other"]
RATE_KINDS = ["material", "labour", "product"]
EXPENSE_CATEGORIES = ["Site visit travel", "Staff time", "3D renders", "Samples", "Consultant", "Marketing", "Other"]
RECEIPT_KINDS = ["Token / booking advance", "Design fee advance"]
PAYMENT_MODES = ["Cash", "UPI", "Bank transfer", "Cheque", "Card"]
PROPOSAL_CHANNELS = ["email", "whatsapp", "in_person", "other"]
REJECT_REASONS = ["Price", "Scope", "Timing", "Chose a competitor", "Other"]

# public client questionnaire, per service (ids are stored with the answers)
QUESTIONNAIRE = {
    "interior": [
        {"id": "rooms", "label": "Which rooms should we design?", "type": "text"},
        {"id": "style", "label": "Style you like", "type": "choice",
         "options": ["Modern", "Contemporary", "Minimal", "Traditional", "Indo-modern", "Industrial", "Not sure"]},
        {"id": "colours_like", "label": "Colours you like", "type": "text"},
        {"id": "colours_avoid", "label": "Colours to avoid", "type": "text"},
        {"id": "materials", "label": "Materials or finishes you prefer (laminate, veneer, PU, stone…)", "type": "text"},
        {"id": "household", "label": "Who lives in the home (adults, children, elders, pets)?", "type": "text"},
        {"id": "storage", "label": "Storage needs", "type": "text"},
        {"id": "must_haves", "label": "Must-haves", "type": "text"},
        {"id": "budget_comfort", "label": "Budget you are comfortable with", "type": "text"},
        {"id": "move_in", "label": "When do you want to move in?", "type": "text"},
        {"id": "references", "label": "Links to pictures you like", "type": "text"},
    ],
    "architecture": [
        {"id": "site", "label": "About the plot or site (size, facing, road width)", "type": "text"},
        {"id": "spaces", "label": "Spaces you need (bedrooms, office, parking…)", "type": "text"},
        {"id": "floors", "label": "Number of floors", "type": "text"},
        {"id": "style", "label": "Architectural style you like", "type": "text"},
        {"id": "sustainability", "label": "Sustainability wishes (solar, rainwater, daylight…)", "type": "text"},
        {"id": "approvals", "label": "Approvals already obtained", "type": "text"},
        {"id": "timeline", "label": "When should construction start?", "type": "text"},
        {"id": "references", "label": "Links to buildings you like", "type": "text"},
    ],
    "construction": [
        {"id": "plot", "label": "Plot size and location", "type": "text"},
        {"id": "floors", "label": "Number of floors", "type": "text"},
        {"id": "drawings", "label": "Do you have approved drawings?", "type": "choice", "options": ["Yes", "No", "In progress"]},
        {"id": "structure", "label": "Structure type, if known (RCC frame, load-bearing…)", "type": "text"},
        {"id": "finish", "label": "Finish level", "type": "choice", "options": ["Basic", "Standard", "Premium", "Luxury"]},
        {"id": "start", "label": "When should work start?", "type": "text"},
        {"id": "must_haves", "label": "Anything else we must know", "type": "text"},
    ],
}

# notification events: label shown in the bell / preferences; critical ones cannot be switched off
NOTIFY_EVENTS = {
    "lead_assigned": ("New lead assigned to you", True),
    "lead_unassigned": ("New unassigned lead", True),
    "lead_reassigned": ("Lead reassigned", True),
    "response_late": ("Lead not contacted in time", False),
    "followup_assigned": ("Follow-up assigned to you", False),
    "followup_due": ("Follow-up due today", False),
    "followup_overdue": ("Follow-up overdue", False),
    "lead_stuck": ("Lead stuck in a stage", False),
    "hot_idle": ("Hot lead with no activity", False),
    "visit_assigned": ("Site visit assigned to you", True),
    "visit_changed": ("Site visit rescheduled or cancelled", True),
    "visit_reminder": ("Site visit reminder", False),
    "visit_missed": ("Site visit missed", False),
    "visit_report": ("Visit report submitted", False),
    "report_late": ("Visit report not submitted", False),
    "questionnaire": ("Client questionnaire submitted", False),
    "brief_ready": ("Brief ready for estimate", False),
    "approval_needed": ("Approval needed", True),
    "approval_decided": ("Approval decided", True),
    "proposal_response": ("Proposal accepted or rejected", True),
    "proposal_waiting": ("Proposal not accepted yet", False),
    "proposal_expiring": ("Proposal expiring", False),
    "proposal_expired": ("Proposal expired", False),
    "lead_won": ("Lead won", False),
    "lead_lost": ("Lead lost", False),
    "advance_received": ("Advance received", False),
    "project_pm": ("You are PM on a new project", True),
    "lead_resumed": ("On-hold lead back in the pipeline", False),
    "bid_due": ("Bid due soon", False),
    "lead_merged": ("Lead merged", False),
}
