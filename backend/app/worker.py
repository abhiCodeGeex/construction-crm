"""Scheduled checks (C+3), run every minute by the `worker` service:  python -m app.worker

Every reminder carries a key, so running the checks again never notifies twice. `run_once(now)` takes the
time as a parameter so the tests can step the clock."""
import time
from datetime import datetime, timedelta

from flask import g

from .db import db, oid
from .services import notify, project_events, sales

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


def check_visits(now):
    """Day-before and 2-hour reminders (staff in app, client by email); missed visits; reports not written."""
    from .routes.lead_steps import fmt
    for v in db.lead_visits.find({"company_id": g.cid, "status": {"$in": ["scheduled", "confirmed", "done"]}}):
        vid, lid = str(v["_id"]), v["lead_id"]
        lead = db.leads.find_one({"_id": oid(lid), "company_id": g.cid}) or {}
        if lead.get("status") != "open":
            continue
        link, staff = f"/app/leads/{lid}", [s["id"] for s in v["staff"]]
        what = f"{'Site visit' if v['kind'] == 'site_visit' else 'Meeting'} for {v['lead_title']} at {v['address']}"
        if v["status"] in ("scheduled", "confirmed"):
            left = (v["at"] - now).total_seconds() / 3600
            stamp = v["at"].isoformat()
            if 2 < left <= 24:
                notify.send("visit_reminder", staff, f"Tomorrow: {what}, {fmt(v['at'])}", link, lid, key=f"visit-24:{vid}:{stamp}")
                if not db.notifications.find_one({"company_id": g.cid, "key": f"client-24:{vid}:{stamp}"}):
                    c = db.contacts.find_one({"_id": oid(lead.get("contact_id"))}, {"email": 1})
                    result = notify.deliver(g.company, (c or {}).get("email"), f"Reminder: our visit on {fmt(v['at'])}",
                                            f"Dear {lead.get('contact_name')},\n\nA reminder of our visit for {v['lead_title']} on "
                                            f"{fmt(v['at'])} at {v['address']}.\n\nRegards,\n{g.company['name']}")
                    # a marker row so the client is reminded once, and the result is on the lead's timeline
                    db.notifications.insert_one({"company_id": g.cid, "user_id": None, "key": f"client-24:{vid}:{stamp}",
                                                 "event": "visit_reminder", "lead_id": lid, "read_at": now, "created_at": now,
                                                 "text": f"Client reminder: {result}"})
                    sales.log(lid, "email", f"Visit reminder emailed to the client: {result}", outcome=result, auto=True)
            if 0 < left <= 2:
                notify.send("visit_reminder", staff, f"In under 2 hours: {what}", link, lid, key=f"visit-2:{vid}:{stamp}")
            if (now - v["at"]).total_seconds() / 60 > (v.get("duration_min") or 60) + 120:
                notify.send("visit_missed", staff + [lead.get("owner_id")] + notify.managers(),
                            f"{what} was due {fmt(v['at'])} and is not marked done", link, lid, key=f"missed:{vid}:{stamp}")
        elif not (v.get("report") or {}).get("submitted_at") and v.get("done_at") and now - v["done_at"] > timedelta(hours=24):
            notify.send("report_late", notify.managers() + [lead.get("owner_id")] + staff,
                        f"No report yet for the visit of {fmt(v['at'])} ({v['lead_title']})", link, lid, key=f"report:{vid}")


def check_proposals(now):
    """Sent and not answered in 3 days -> salesperson + a follow-up; expiring in 2 days; expired -> manager too.
    Approvals waiting more than a day remind the approver."""
    from . import tenancy as t
    today = now.date().isoformat()
    soon = (now.date() + timedelta(days=2)).isoformat()
    for p in db.proposals.find({"company_id": g.cid, "status": "sent"}):
        pid, lid = str(p["_id"]), p["lead_id"]
        lead = db.leads.find_one({"_id": oid(lid), "company_id": g.cid}) or {}
        if lead.get("status") != "open":
            continue
        owner = [lead["owner_id"]] if lead.get("owner_id") else notify.managers()
        link = f"/app/leads/{lid}"
        if p["valid_until"] < today:
            db.proposals.update_one({"_id": p["_id"]}, {"$set": {"status": "expired", "updated_at": now}})
            sales.log(lid, "proposal", f"Proposal {p['number']} expired (valid until {p['valid_until']})")
            notify.send("proposal_expired", owner + notify.managers(), f"Proposal {p['number']} for {p['lead_title']} expired",
                        link, lid, key=f"expired:{pid}")
            continue
        if p["valid_until"] <= soon:
            notify.send("proposal_expiring", owner, f"Proposal {p['number']} for {p['lead_title']} expires on {p['valid_until']}",
                        link, lid, key=f"expiring:{pid}")
        if p.get("first_viewed_at") and now - p["first_viewed_at"] > timedelta(days=2):  # §16 viewed but not accepted
            notify.send("proposal_waiting", owner, f"{p['lead_title']}: proposal {p['number']} was opened "
                        f"{(now - p['first_viewed_at']).days} days ago ({p.get('view_count', 0)} views) and is not answered",
                        link, lid, key=f"viewed-wait:{pid}")
        if p.get("sent_at") and now - p["sent_at"] > timedelta(days=3):
            sent = notify.send("proposal_waiting", owner, f"Proposal {p['number']} for {p['lead_title']} sent "
                               f"{(now - p['sent_at']).days} days ago and not answered", link, lid, key=f"waiting:{pid}")
            if sent and not db.followups.find_one({"company_id": g.cid, "kind": "proposal_chase", "proposal_id": pid}):
                u = db.users.find_one({"_id": oid(owner[0])}, {"name": 1}) if owner else None
                t.insert("followups", {"title": f"Chase proposal {p['number']}: {p['lead_title']}", "due": today, "priority": "high",
                                       "channel": "call", "owner_id": owner[0] if owner else None, "owner_name": u and u["name"],
                                       "status": "open", "kind": "proposal_chase", "proposal_id": pid,
                                       "related": {"type": "lead", "id": lid, "label": p["lead_title"], "contact_id": lead.get("contact_id")}})
    for e in db.estimates.find({"company_id": g.cid, "status": "pending_approval"}):
        if now - e["approval"]["requested_at"] > timedelta(days=1):
            notify.send("approval_needed", notify.managers(), f"Estimate {e['number']} for {e['lead_title']} is still waiting for approval",
                        f"/app/leads/{e['lead_id']}", e["lead_id"], key=f"appr-wait:{e['_id']}")


def check_bids(now):
    """Bids we are preparing: 7 days, 2 days and on the due date, to the bid owner and the sales manager."""
    for b in db.bids.find({"company_id": g.cid, "status": "preparing", "decision": {"$ne": "no_bid"}}):
        left = (datetime.fromisoformat(b["due_date"]).date() - now.date()).days
        for mark in (7, 2, 0):
            if left == mark:
                who = [b.get("owner_id") or b.get("created_by")] + notify.managers()
                text = f"Bid {b['title']} is due {'today' if mark == 0 else f'in {mark} days'} ({b['due_date']})"
                notify.send("bid_due", who, text, "/app/leads", b.get("lead_id"), key=f"bid{mark}:{b['_id']}:{b['due_date']}")


def check_projects(now):
    """Open projects (planning / active): task due tomorrow -> assignee; task overdue -> assignee, and the
    project's managers once it is 3 days late; milestone past its date and not achieved -> managers.
    Keys carry the date, so a task or milestone that is rescheduled is reminded again for its new date."""
    today = now.date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    for p in db.projects.find({"company_id": g.cid, "status": {"$in": ["planning", "active"]}}):
        pid, url, name = str(p["_id"]), project_events.link(p), p["name"]
        for s in p.get("stages", []):
            for tk in s.get("tasks", []):
                end = tk.get("end")
                if tk["status"] == "done" or not end:
                    continue
                who = [tk.get("assignee_id")]
                what = f"{tk['title']} ({s['name']}, {name})"
                if end == tomorrow:
                    notify.send("task_due", who, f"Due tomorrow: {what}", url, project_id=pid,
                                key=f"task-due:{tk['id']}:{end}")
                elif end < today.isoformat():
                    late = (today - datetime.fromisoformat(end).date()).days
                    notify.send("task_overdue", who, f"Overdue by {late} day(s): {what}", url, project_id=pid,
                                key=f"task-late:{tk['id']}:{end}")
                    if late >= 3:
                        notify.send("task_overdue", project_events.managers(p),
                                    f"{tk.get('assignee_name') or 'Unassigned'} — {late} days overdue: {what}", url,
                                    project_id=pid, key=f"task-esc:{tk['id']}:{end}", level="warn")
            for ms in s.get("milestones", []):
                if ms["status"] == "pending" and ms.get("due") and ms["due"] < today.isoformat():
                    late = (today - datetime.fromisoformat(ms["due"]).date()).days
                    notify.send("milestone_late", project_events.managers(p),
                                f"{ms['name']} on {name} is {late} day(s) late (due {ms['due']})", url,
                                project_id=pid, key=f"ms-late:{ms['id']}:{ms['due']}", level="warn")


COMPLIANCE_MARKS = (30, 7)  # days before expiry; plus one alert on the day after it expires


def check_compliance(now):
    """Insurance, licences and certificates on contacts: 30 days and 7 days before expiry, and once expired,
    to the Owner(s) and Procurement. Keys carry the expiry date, so a renewed document starts again."""
    today = now.date()
    who = project_events.owners() + notify.role_users("procurement")
    for c in db.contacts.find({"company_id": g.cid, "active": {"$ne": False},
                               "compliance": {"$elemMatch": {"expiry": {"$type": "string"}}}}):
        for doc in c.get("compliance", []):
            if not doc.get("expiry"):
                continue
            left = (datetime.fromisoformat(doc["expiry"]).date() - today).days
            label = f"{doc['name']} of {c['name']}"
            url = f"/app/contacts/{c['_id']}"
            key = f"comp:{c['_id']}:{doc['id']}:{doc['expiry']}"
            if left < 0:
                notify.send("compliance_expired", who, f"{label} expired on {doc['expiry']}", url,
                            key=f"{key}:expired", level="warn")
            else:
                mark = next((m for m in sorted(COMPLIANCE_MARKS) if left <= m), None)
                if mark is not None:
                    notify.send("compliance_expiring", who, f"{label} expires on {doc['expiry']} "
                                f"({'today' if left == 0 else f'in {left} day(s)'})", url, key=f"{key}:{mark}")


CHECKS = [check_leads, check_followups, check_visits, check_proposals, check_bids, check_projects,
          check_compliance]


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
