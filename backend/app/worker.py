"""Scheduled checks (C+3), run every minute by the `worker` service:  python -m app.worker

Every reminder carries a key, so running the checks again never notifies twice. `run_once(now)` takes the
time as a parameter so the tests can step the clock."""
import time
from datetime import datetime

from flask import g

from .db import db
from .services import notify, sales

ACTIVE = {"$nin": ["suspended", "cancelled"]}


def _company_context(company):
    g.cid, g.company, g.uid, g.role = str(company["_id"]), company, None, None
    g.user = {"name": "System"}


def check_leads(now):
    s = sales.settings()
    target = s["response_minutes"]
    today = now.date().isoformat()
    for lead in db.leads.find({"company_id": g.cid, "status": "open"}):
        lid, link, title = str(lead["_id"]), f"/app/leads/{lead['_id']}", lead["title"]
        owner = [lead["owner_id"]] if lead.get("owner_id") else []
        # response time target
        if not lead.get("first_response_at"):
            age = (now - lead["created_at"]).total_seconds() / 60
            if age >= target:
                notify.send("response_late", owner + notify.managers(), f"{title} has not been contacted "
                            f"({int(age)} min since the enquiry, target {target} min)", link, lid, key=f"resp:{lid}")
            if age >= 24 * 60:
                notify.send("response_late", owner + notify.managers(), f"{title} still not contacted after 24 hours",
                            link, lid, key=f"resp24:{lid}")
        # day limit per stage: the salesperson first, the sales manager at twice the limit
        limit = sales.stage_rules(lead["service"], lead["stage"]).get("max_days")
        days = sales.days_in_stage(lead, now)
        if limit and days > limit:
            entered = (lead.get("stage_entered_at") or lead["created_at"]).isoformat()
            notify.send("lead_stuck", owner or notify.managers(), f"{title} has been in {lead['stage']} for {days} days "
                        f"(limit {limit})", link, lid, key=f"stuck:{lid}:{lead['stage']}:{entered}")
            if days > 2 * limit:
                notify.send("lead_stuck", notify.managers(), f"{title} ({lead.get('owner_name') or 'unassigned'}) is "
                            f"stuck in {lead['stage']} for {days} days", link, lid,
                            key=f"stuck2:{lid}:{lead['stage']}:{entered}")
        # hot lead with no activity
        if lead.get("temperature") == "hot":
            last = lead.get("last_activity_at") or lead["created_at"]
            idle = (now - last).days
            if idle >= s["hot_idle_days"]:
                notify.send("hot_idle", notify.managers() + owner, f"Hot lead {title} has had no activity for {idle} days",
                            link, lid, key=f"hot:{lid}:{last.isoformat()}")
    # on hold until today: back into the pipeline
    for lead in db.leads.find({"company_id": g.cid, "status": "on_hold", "resume_on": {"$lte": today}}):
        from .routes.leads import resume_lead
        resume_lead(lead, f"Back in the pipeline at {lead['stage']} — resume date {lead['resume_on']} reached")
        notify.send("lead_resumed", [lead.get("owner_id")] if lead.get("owner_id") else notify.managers(),
                    f"{lead['title']} is back in the pipeline (was on hold: {lead.get('hold_reason')})",
                    f"/app/leads/{lead['_id']}", str(lead["_id"]), key=f"resume:{lead['_id']}:{lead['resume_on']}")


def check_followups(now):
    today = now.date().isoformat()
    esc = sales.settings()["followup_escalate_days"]
    for f in db.followups.find({"company_id": g.cid, "status": "open", "due": {"$lte": today}}):
        fid = str(f["_id"])
        rel = f.get("related") or {}
        link = f"/app/leads/{rel['id']}" if rel.get("type") == "lead" else "/app/followups"
        lead_id = rel.get("id") if rel.get("type") == "lead" else None
        what = f"{f['title']}" + (f" ({rel.get('label')})" if rel.get("label") else "")
        if f["due"] == today:
            notify.send("followup_due", [f.get("owner_id")], f"Due today: {what}", link, lead_id, key=f"fu-due:{fid}:{today}")
        else:
            late = (now.date() - datetime.fromisoformat(f["due"]).date()).days
            notify.send("followup_overdue", [f.get("owner_id")], f"Overdue by {late} day(s): {what}", link, lead_id,
                        key=f"fu-late:{fid}")
            if late > esc:
                notify.send("followup_overdue", notify.managers(), f"{f.get('owner_name')}'s follow-up is {late} days "
                            f"overdue: {what}", link, lead_id, key=f"fu-esc:{fid}")


CHECKS = [check_leads, check_followups]


def run_once(now=None):
    now = now or datetime.utcnow()
    for company in db.companies.find({"deleted_at": None, "status": ACTIVE}):
        _company_context(company)
        for check in CHECKS:
            check(now)


def main():
    from . import create_app
    app = create_app()
    while True:
        started = time.time()
        with app.app_context():
            try:
                run_once()
            except Exception as e:  # one bad record must not stop the reminders for everyone
                app.logger.exception(e)
        time.sleep(max(5, 60 - (time.time() - started)))


if __name__ == "__main__":
    main()
