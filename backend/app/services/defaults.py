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


def template_stages(names, service=None):
    """Template stages from plain names; each gets the service's default closing checklist and sign-off rule."""
    gate = gate_defaults(service)
    return [{"name": n, "duration_days": DEFAULT_STAGE_DAYS, **gate} for n in names]


def gate_defaults(service):
    g_ = STAGE_GATE_DEFAULTS.get(service) or {"checklist": [], "client_signoff": False}
    return {"checklist": list(g_["checklist"]), "client_signoff": g_["client_signoff"]}

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
    "proposal_viewed": ("Client opened a proposal", False),
    "contract_signed": ("Contract signed", True),
    # projects (B+1)
    "project_added": ("Added to a project", True),
    "task_assigned": ("Task assigned to you", True),
    "task_due": ("Task due tomorrow", False),
    "task_overdue": ("Task overdue", False),
    "task_blocked": ("Task blocked", False),
    "stage_done": ("Stage complete", False),
    "milestone_achieved": ("Milestone achieved", False),
    "milestone_late": ("Milestone late", False),
    "issue_raised": ("Issue raised on a project", False),
    # contacts (B+1)
    "compliance_expiring": ("Compliance document expiring", False),
    "compliance_expired": ("Compliance document expired", True),
}

# ---------------- Phase D ----------------
PROPOSAL_TYPES = {"fee": "Fee proposal", "construction": "Construction estimate", "interior": "Interior quote",
                  "simple": "Proposal with a typed value"}
FEE_BASES = {"fixed": "Fixed fee", "hourly": "Hourly", "percent": "% of project cost", "per_area": "Per sq ft / m²"}
SCHEDULE_TRIGGERS = {"signing": "On signing", "stage": "When a stage is complete", "date": "On a date"}
SERVICE_PROPOSAL_TYPE = {"architecture": "fee", "construction": "construction", "interior": "interior"}
TEMPLATE_TEXT = {
    "fee": {"intro": "Thank you for the opportunity to design your project. This proposal sets out our scope, fee and terms.",
            "terms": "Fees exclude statutory approval charges and third-party consultants unless listed. Additional services "
                     "beyond the scope are charged separately after your written approval."},
    "construction": {"intro": "Thank you for inviting us to quote. This estimate is based on the drawings and site visit "
                              "made with you.",
                     "terms": "Rates are valid for the period shown. Changes to the scope are priced and approved as change "
                              "orders before the work is done."},
    "interior": {"intro": "Thank you for choosing us for your interiors. This quote covers our design fee and the "
                          "products selected for each room.",
                 "terms": "Products are ordered after your approval and deposit. Lead times are as advised by the suppliers."},
}

# ---------------- Phase B+ (projects in depth) ----------------
# what must be true before a stage can be closed (its "<stage> complete" milestone achieved); editable per
# template stage in Settings -> Stage templates and per stage on the project
STAGE_GATE_DEFAULTS = {
    "architecture": {"checklist": ["Drawings issued to the client", "Client comments addressed"], "client_signoff": True},
    "construction": {"checklist": ["Quality inspection passed", "Site photos uploaded", "Snags for this stage closed"],
                     "client_signoff": False},
    "interior": {"checklist": ["Items installed as per the selection", "Client walkthrough done",
                               "Snags for this stage closed"], "client_signoff": True},
}
SIGNOFF_METHODS = ["In person", "Email", "WhatsApp", "Phone", "Signed document"]
TASK_PRIORITIES = ["low", "normal", "high", "urgent"]

# why a planned date moved later (required once a baseline is set); `party` = who caused it (waiting-on-whom)
DELAY_REASONS = {
    "client_change": ("Client changed something", "client"),
    "client_decision": ("Waiting for a client decision", "client"),
    "client_payment": ("Client payment late", "client"),
    "authority": ("Authority approval pending", "authority"),
    "consultant": ("Consultant drawings / input late", "consultant"),
    "material": ("Material not delivered", "vendor"),
    "subcontractor": ("Subcontractor delay", "subcontractor"),
    "labour": ("Labour shortage", "us"),
    "planning": ("Our planning or estimate", "us"),
    "rework": ("Rework / quality issue", "us"),
    "weather": ("Weather", "none"),
    "site": ("Site condition found", "none"),
    "other": ("Other", "other"),
}
# who a blocked task or open item is waiting on
WAITING_PARTIES = {"client": "Client", "consultant": "Architect / consultant", "vendor": "Vendor / supplier",
                   "subcontractor": "Subcontractor", "authority": "Authority / inspector", "us": "Our team"}
LINK_TYPES = {"FS": "Finish → start", "SS": "Start → start", "FF": "Finish → finish"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_WORKING_DAYS = [0, 1, 2, 3, 4, 5]  # Monday-Saturday (common on Indian sites); editable in Settings

NOTIFY_EVENTS.update({
    "mentioned": ("You were mentioned in a comment", True),
    "task_comment": ("New comment on your task", False),
    "meeting_scheduled": ("Meeting scheduled", False),
    "meeting_reminder": ("Meeting in 2 hours", False),
    "meeting_minutes": ("Meeting minutes published", False),
    "project_at_risk": ("Project health turned red", False),
    "signoff_recorded": ("Client sign-off recorded", False),
})

# ---------------- Phase E: costs, invoices, change orders ----------------
COST_CATEGORIES = ["Material", "Labour", "Subcontract", "Equipment", "Transport", "Consultant", "Site expense", "Other"]
VENDOR_TYPES = ["supplier", "subcontractor", "contractor", "consultant"]
COST_STATUSES = ["draft", "submitted", "approved", "rejected", "void"]
# why a cost takes a stage over its budget; "client_change" is the one the client pays for (change order)
OVERSPEND_REASONS = {"client_change": "Client changed something", "our_mistake": "Our mistake", "price_rise": "Price rise"}
FINANCE_DEFAULTS = {"site_expense_limit": 5000, "overspend_markup_pct": 10, "invoice_due_days": 7}
INVOICE_STATUSES = ["draft", "sent", "part_paid", "paid", "void"]

NOTIFY_EVENTS.update({
    "cost_approval": ("Cost waiting for your approval", True),
    "cost_decided": ("Your cost approved or rejected", False),
    "budget_alert": ("Stage budget 80% / 100% spent", False),
    "receipt_recorded": ("Payment received", False),
    "invoice_due": ("Invoice due soon", False),
    "invoice_overdue": ("Invoice overdue", False),
    "co_decided": ("Change order approved or rejected", False),
    "co_waiting": ("Change order not answered by the client", False),
})

# ---------------- Phase F: documents, selections, site reports ----------------
# default document folders: "all" for every project, then per service (Settings -> document folders)
DOC_FOLDERS = {
    "all": ["Contract", "Client documents"],
    "architecture": ["Concept", "Drawings", "Approvals"],
    "construction": ["Structural", "MEP", "Site photos"],
    "interior": ["Layouts", "3D views", "Selections"],
}
DOC_KINDS = ["drawing", "specification", "contract", "approval", "report", "photo", "other"]
DRAWING_STATUSES = {"wip": "Work in progress", "for_comment": "For comment", "for_approval": "For approval",
                    "approved": "Approved", "for_construction": "For construction", "superseded": "Superseded"}
TRANSMITTAL_PURPOSES = {"for_information": "For information", "for_comment": "For comment", "for_approval": "For approval",
                        "for_construction": "For construction"}
DISCIPLINES = ["Architecture", "Structure", "MEP", "Interior", "Landscape", "Other"]

NOTIFY_EVENTS.update({
    "transmittal_sent": ("Drawings or documents issued", False),
    "transmittal_waiting": ("Transmittal not acknowledged", False),
    "drawing_approved": ("Drawing approved", False),
    "selection_chosen": ("Client choice recorded", False),
    "selection_due": ("Client choice due or overdue", False),
    "site_report_missing": ("Daily site report missing", False),
    "site_delay": ("Delay reported on site", False),
})
