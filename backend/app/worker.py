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


def check_meetings(now):
    """Staff attendees: a reminder in the 2 hours before a planned meeting."""
    for m in db.project_meetings.find({"company_id": g.cid, "status": "planned", "at": {"$gt": now, "$lte": now + timedelta(hours=2)}}):
        p = db.projects.find_one({"_id": oid(m["project_id"])}, {"name": 1})
        if not p:
            continue
        notify.send("meeting_reminder", [s["user_id"] for s in m.get("staff", [])],
                    f"{m['title']} ({p['name']}) at {m['at'].strftime('%H:%M')} UTC" + (f", {m['place']}" if m.get("place") else ""),
                    f"/app/projects/{m['project_id']}", project_id=m["project_id"], key=f"meet-2h:{m['_id']}:{m['at'].isoformat()}")


def check_health(now):
    """When a running project's health turns red, its managers and the Owners are told (once per turn to red)."""
    from .services.project_health import health
    for p in db.projects.find({"company_id": g.cid, "status": {"$in": ["planning", "active"]}}):
        h = health(p, now.date().isoformat())
        if h["grade"] == p.get("health_grade"):
            continue
        db.projects.update_one({"_id": p["_id"]}, {"$set": {"health_grade": h["grade"], "health_since": now}})
        if h["grade"] == "red":
            worst = sorted(h["parts"], key=lambda x: x["points"] - x["max"])[:2]
            notify.send("project_at_risk", project_events.managers(p) + project_events.owners(),
                        f"{p['name']} is off track (health {h['score']}/100): " + "; ".join(x["why"] for x in worst),
                        project_events.link(p), project_id=str(p["_id"]), key=f"risk:{p['_id']}:{now.date().isoformat()}",
                        level="warn")


def check_invoices(now):
    """Unpaid invoices (Phase E): 3 days before the due date and on it -> Accounts; a day late -> Accounts and the
    project's managers; 7 days late -> the Owners. Keys carry the due date, so a re-dated invoice is chased again;
    paid and void invoices never are."""
    today = now.date()
    accounts = notify.role_users("accounts")
    for inv in db.invoices.find({"company_id": g.cid, "status": {"$in": ["sent", "part_paid"]}, "kind": {"$ne": "credit_note"},
                                 "due_date": {"$ne": None}}):
        due = inv["due_date"]
        days = (datetime.fromisoformat(due).date() - today).days
        left = round(inv["total"] - inv.get("credited", 0) - inv.get("paid", 0), 2)
        what = f"{inv['number']} ({inv.get('client_name') or 'client'}, {inv.get('project_name') or ''}): {left:,.0f} left to pay"
        link, iid = f"/app/invoices/{inv['_id']}", str(inv["_id"])
        if 0 < days <= 3:
            notify.send("invoice_due", accounts, f"Due {due}: {what}", link, project_id=inv.get("project_id"), key=f"inv-due3:{iid}:{due}")
        elif days == 0:
            notify.send("invoice_due", accounts, f"Due today: {what}", link, project_id=inv.get("project_id"), key=f"inv-due0:{iid}:{due}")
        if days < 0:
            p = db.projects.find_one({"_id": oid(inv["project_id"])}) if inv.get("project_id") else None
            notify.send("invoice_overdue", accounts + (project_events.managers(p) if p else []), f"Overdue since {due}: {what}",
                        link, project_id=inv.get("project_id"), key=f"inv-late:{iid}:{due}", level="warn")
        if days <= -7:
            notify.send("invoice_overdue", project_events.owners(), f"{-days} days overdue: {what}", link,
                        project_id=inv.get("project_id"), key=f"inv-late7:{iid}:{due}", level="warn")


def check_change_orders(now):
    """A change order sent to the client and not answered in 3 days -> the project's managers, once."""
    for co in db.change_orders.find({"company_id": g.cid, "status": "sent", "sent_at": {"$lt": now - timedelta(days=3)}}):
        p = db.projects.find_one({"_id": oid(co["project_id"])})
        if p:
            notify.send("co_waiting", project_events.managers(p), f"Change order {co['number']} ({co['title']}, {p['name']}) "
                        f"sent {co['sent_at'].date().isoformat()}: no answer from the client yet", f"/app/projects/{p['_id']}?tab=changes",
                        project_id=co["project_id"], key=f"co-wait:{co['_id']}", level="warn")


def check_transmittals(now):
    """Issued for comment or for approval and not acknowledged in 7 days -> the person who sent it, once."""
    for tr in db.transmittals.find({"company_id": g.cid, "acknowledged": None, "purpose": {"$in": ["for_comment", "for_approval"]},
                                    "created_at": {"$lt": now - timedelta(days=7)}}):
        notify.send("transmittal_waiting", [tr["sent_by"]], f"{tr['number']} ({tr['project_name']}) sent {tr['created_at'].date().isoformat()} "
                    f"to {', '.join(r['name'] for r in tr['to'])}: not acknowledged yet", f"/app/projects/{tr['project_id']}?tab=documents",
                    project_id=tr["project_id"], key=f"trn-wait:{tr['_id']}", level="warn")


def check_selections(now):
    """A client choice due in 3 days -> the project's managers; overdue -> managers again (it is also listed as waiting
    on the client). Keys carry the due date, so a new due date is reminded again."""
    today = now.date()
    for s in db.selections.find({"company_id": g.cid, "status": {"$in": ["open", "options_sent"]}, "due_date": {"$ne": None}}):
        days = (datetime.fromisoformat(s["due_date"]).date() - today).days
        if days > 3:
            continue
        p = db.projects.find_one({"_id": oid(s["project_id"])})
        if not p or p.get("status") not in ("planning", "active"):
            continue
        late = days < 0
        notify.send("selection_due", project_events.managers(p),
                    f"{p['name']}: the client's choice of {s['item']} " + (f"is {-days} day(s) late" if late else f"is due {s['due_date']}"),
                    f"/app/projects/{p['_id']}?tab=selections", project_id=s["project_id"],
                    key=f"sel-{'late' if late else 'due'}:{s['_id']}:{s['due_date']}", level="warn" if late else "info")


def check_site_reports(now):
    """Active projects with a site supervisor: no report by the company's cut-off on a working day -> the supervisor(s);
    still none the next day -> the project's managers. On-hold and finished projects are quiet."""
    from .routes.site_reports import site_settings, SUPERVISOR
    from .services import workdays
    st = site_settings()
    local = now + timedelta(minutes=st["tz_offset_min"])
    today, yday = local.date(), local.date() - timedelta(days=1)
    hh, mm = (int(x) for x in st["cutoff"].split(":"))
    after_cutoff = (local.hour, local.minute) >= (hh, mm)
    cal = workdays.calendar()
    for p in db.projects.find({"company_id": g.cid, "status": "active"}):
        sups = [m["user_id"] for m in p.get("team", []) if m.get("project_role") == SUPERVISOR and m.get("user_id")]
        if not sups:
            continue
        pid = str(p["_id"])
        if after_cutoff and workdays.is_working(today, cal) and not db.site_reports.find_one({"company_id": g.cid, "project_id": pid, "date": today.isoformat()}, {"_id": 1}):
            notify.send("site_report_missing", sups, f"{p['name']}: today's site report is not written yet", f"/app/projects/{pid}?tab=site",
                        project_id=pid, key=f"sr-miss:{pid}:{today.isoformat()}", level="warn")
        if workdays.is_working(yday, cal) and p.get("start", "") <= yday.isoformat() and \
                not db.site_reports.find_one({"company_id": g.cid, "project_id": pid, "date": yday.isoformat()}, {"_id": 1}):
            notify.send("site_report_missing", project_events.managers(p), f"{p['name']}: no site report for {yday.isoformat()}",
                        f"/app/projects/{pid}?tab=site", project_id=pid, key=f"sr-miss2:{pid}:{yday.isoformat()}", level="warn")


def check_client_reminders(now):
    """The client is reminded once: an invoice the day after its due date, a selection choice 3 days before it is due.
    By email, and by WhatsApp when they opted in. Keys carry the date, so a re-dated item is reminded again."""
    from .services import messaging
    from .routes.lead_money import money_text
    today = now.date()
    yday, in3 = (today - timedelta(days=1)).isoformat(), (today + timedelta(days=3)).isoformat()

    def remind(contact_id, key, subject, text, project_id):
        c = db.contacts.find_one({"_id": oid(contact_id), "company_id": g.cid}) if contact_id else None
        if not c or db.reminders.find_one({"company_id": g.cid, "key": key}):
            return
        mail = notify.deliver(g.company, c.get("email"), subject, text + f"\n\n{g.company['name']}") if c.get("email") else "no email"
        whats = messaging.notify_contact(c, f"{g.company['name']}: {text}", "reminder", key)
        db.reminders.insert_one({"company_id": g.cid, "key": key, "contact_id": contact_id, "project_id": project_id,
                                 "email": mail, "whatsapp": whats, "at": now})

    # Phase I: a series of client reminders around the due date (days before = negative), firmer as it gets later
    from .routes.finance import settings as fin_settings
    offsets = sorted(set(int(x) for x in fin_settings(g.company).get("client_reminder_days") or [1]))
    dates = {(today - timedelta(days=o)).isoformat(): o for o in offsets}
    for inv in db.invoices.find({"company_id": g.cid, "status": {"$in": ["sent", "part_paid"]}, "kind": {"$ne": "credit_note"},
                                 "due_date": {"$in": list(dates)}}):
        o = dates[inv["due_date"]]
        left = round(inv["total"] - inv.get("credited", 0) - inv.get("paid", 0), 2)
        what = f"Invoice {inv['number']} ({inv.get('project_name') or ''})"
        if o < 0:
            subject, text = f"Invoice {inv['number']} is due on {inv['due_date']}", f"{what} is due on {inv['due_date']}: {money_text(left)}."
        elif o == 0:
            subject, text = f"Invoice {inv['number']} is due today", f"{what} is due today: {money_text(left)}."
        else:
            final = o == offsets[-1] and o >= 14
            subject = f"{'Final reminder' if final else 'Reminder'}: invoice {inv['number']}"
            text = f"{what} was due on {inv['due_date']}; {money_text(left)} is left to pay ({o} day(s) late)." + \
                (" Please pay now or tell us when you will." if final else "")
        key = f"client-inv:{inv['_id']}:{inv['due_date']}" + ("" if o == 1 else f":{o}")
        remind(inv.get("client_id"), key, subject, text + " You can pay it from your portal.", inv.get("project_id"))
    for s in db.selections.find({"company_id": g.cid, "status": {"$in": ["open", "options_sent"]}, "due_date": in3}):
        p = db.projects.find_one({"_id": oid(s["project_id"])}) or {}
        remind(p.get("client_id"), f"client-sel:{s['_id']}:{s['due_date']}", f"Please choose: {s['item']}",
               f"Please choose your {s['item']} for {p.get('name', '')} by {s['due_date']} — the options are in your portal.", s["project_id"])


def check_procurement(now):
    """RFQ due tomorrow with suppliers not answered -> Procurement; PO waiting approval 1 day -> approvers, 3 days ->
    Owners; PO sent and not acknowledged in 2 days -> Procurement; delivery due tomorrow -> site supervisor and
    Procurement; delivery late -> Procurement and the PM, 3 days -> Owners; vendor bill due in 3 days / overdue ->
    Accounts. Each once per date."""
    today = now.date()
    iso = today.isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    proc = notify.role_users("procurement")
    for r in db.rfqs.find({"company_id": g.cid, "status": "sent", "due_date": tomorrow}):
        waiting = [s["name"] for s in r["suppliers"] if not any(q["supplier_id"] == s["contact_id"] for q in r["quotes"])]
        if waiting:
            notify.send("delivery_due", proc, f"{r['number']} quotes due tomorrow; not answered: {', '.join(waiting)}", "/app/procurement?tab=rfqs",
                        project_id=r["project_id"], key=f"rfq-due:{r['_id']}:{r['due_date']}")
    for po in db.purchase_orders.find({"company_id": g.cid, "status": {"$in": ["waiting_approval", "sent", "acknowledged", "part_received", "approved"]}}):
        p = db.projects.find_one({"_id": oid(po["project_id"])}) or {}
        link, pid, name = f"/app/purchase-orders/{po['_id']}", po["project_id"], po.get("number") or "PO"
        if po["status"] == "waiting_approval":
            since = (po.get("approval") or {}).get("requested_at")
            days = (now - since).days if since else 0
            if days >= 1:
                who = project_events.owners() if "owner" in po["approval"].get("needs", []) else project_events.managers(p)
                notify.send("po_approval", who, f"Still waiting for approval: PO for {po['vendor_name']} on {po['project_name']}", link,
                            project_id=pid, key=f"po-wait1:{po['_id']}")
            if days >= 3:
                notify.send("po_approval", project_events.owners(), f"3 days waiting: PO for {po['vendor_name']} on {po['project_name']}", link,
                            project_id=pid, key=f"po-wait3:{po['_id']}", level="warn")
            continue
        sent = po.get("sent_at")
        if po["status"] == "sent" and sent and (now - sent).days >= 2:
            notify.send("po_acknowledged", proc, f"{name} to {po['vendor_name']} not acknowledged yet", link, project_id=pid, key=f"po-noack:{po['_id']}")
        due = po.get("expected_date")
        if not due or po["status"] == "approved":
            continue
        sups = [m["user_id"] for m in p.get("team", []) if m.get("project_role") == "Site Supervisor" and m.get("user_id")]
        if due == tomorrow:
            notify.send("delivery_due", list(dict.fromkeys(sups + proc)), f"Delivery due tomorrow: {name} from {po['vendor_name']} ({po['project_name']})",
                        link, project_id=pid, key=f"po-due:{po['_id']}:{due}")
        elif due < iso:
            late = (today - datetime.fromisoformat(due).date()).days
            notify.send("delivery_due", list(dict.fromkeys(proc + project_events.managers(p))), f"Delivery late: {name} from {po['vendor_name']} "
                        f"was due {due}", link, project_id=pid, key=f"po-late:{po['_id']}:{due}", level="warn")
            if late >= 3:
                notify.send("delivery_due", project_events.owners(), f"{late} days late: {name} from {po['vendor_name']} ({po['project_name']})",
                            link, project_id=pid, key=f"po-late3:{po['_id']}:{due}", level="warn")
    acc = notify.role_users("accounts")
    in3 = (today + timedelta(days=3)).isoformat()
    for b in db.vendor_bills.find({"company_id": g.cid, "status": {"$in": ["approved", "part_paid"]}}):
        if b["due_date"] == in3:
            notify.send("bill_due", acc, f"Bill {b['bill_no']} from {b['vendor_name']} due {b['due_date']}", "/app/finance",
                        project_id=b.get("project_id"), key=f"bill-due:{b['_id']}:{b['due_date']}")
        elif b["due_date"] < iso:
            notify.send("bill_due", acc, f"Bill {b['bill_no']} from {b['vendor_name']} overdue since {b['due_date']}", "/app/finance",
                        project_id=b.get("project_id"), key=f"bill-late:{b['_id']}:{b['due_date']}", level="warn")


def check_retention(now):
    from .routes.claims import check_retention as run
    run(now)


def check_snags(now):
    from .routes.site_plus import check_snags as run
    run(now)


def check_usage(now):
    from .routes.platform import check_usage_alerts
    check_usage_alerts(now)


def check_permits(now):
    from .routes.permits import check_permits as run
    run(now)


def check_field(now):
    """Phase J: the morning work message to site workers, the PM digest, and escalation of urgent site messages."""
    from .routes.field import check_morning, check_escalations
    from .routes.digest import check_digest
    check_morning(now)
    check_escalations(now)
    check_digest(now)


def check_phase_k(now):
    """Phase K: overdue RFIs / submittals, automatic follow-up sequences, the daily accounting sync."""
    from .routes.rfis import check_rfis
    from .routes.sequences import check_sequences
    from .routes.accounting import check_accounting
    check_rfis(now)
    check_sequences(now)
    check_accounting(now)


def check_phase_l(now):
    """Phase L: overdue safety actions, scheduled report emails."""
    from .routes.safety import check_safety
    from .routes.report_builder import check_reports
    check_safety(now)
    check_reports(now)


def platform_daily(now):
    """Phase I: the subscription billing run, once a day (trial ends, renewals, reminders, read-only, purge)."""
    day = now.date().isoformat()
    if db.platform_settings.find_one({"_id": "billing_run", "day": day}):
        return
    from .routes.platform import billing_run
    res = billing_run(now)
    db.platform_settings.update_one({"_id": "billing_run"}, {"$set": {"day": day, "result": res, "at": now}}, upsert=True)


CHECKS = [check_leads, check_followups, check_visits, check_proposals, check_bids, check_projects,
          check_compliance, check_meetings, check_health, check_invoices, check_change_orders,
          check_transmittals, check_selections, check_site_reports,
          check_client_reminders, check_procurement, check_retention, check_snags, check_permits, check_usage, check_field, check_phase_k, check_phase_l]


def run_once(now=None):
    now = now or datetime.utcnow()
    platform_daily(now)
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
