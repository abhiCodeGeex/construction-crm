"""Project notifications (B+1). Every change to stages, tasks and milestones goes through `save_stages`, which
calls `stage_changes(old, new)`: the differences decide who is told. The scheduled checks (due tomorrow, overdue,
late milestones, compliance expiry) live in the worker and use the helpers here.

Who is told
* task assigned            -> the new assignee
* task blocked             -> the project's managers
* stage complete           -> the project's managers and the Owner(s)
* milestone achieved       -> the project's managers and the Owner(s)
* added to a project       -> that staff user
* issue raised             -> the issue owner; high severity also the project's managers
"""
from flask import g

from ..db import db, oid
from . import notify

PM_ROLE = "Project Manager"


def link(p):
    return f"/app/projects/{p['_id']}"


def managers(p):
    """Staff on the team with the Project Manager role; when there is none, every Owner."""
    ids = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("project_role") == PM_ROLE]
    active = {str(u["_id"]) for u in db.users.find({"_id": {"$in": [oid(i) for i in ids]}, "active": {"$ne": False}}, {"_id": 1})}
    return [i for i in ids if i in active] or owners()  # a deactivated PM falls back to the Owners


def owners():
    return [str(u["_id"]) for u in db.users.find({"company_id": g.cid, "role": "owner", "kind": "staff",
                                                  "active": {"$ne": False}}, {"_id": 1})]


def _tasks(p):
    return {tk["id"]: (s, tk) for s in p.get("stages", []) for tk in s.get("tasks", [])}


def _milestones(p):
    return {ms["id"]: (s, ms) for s in p.get("stages", []) for ms in s.get("milestones", [])}


def stage_changes(old, new):
    """Compare the project before and after a write: timeline entries, then who is told."""
    log_stage_changes(old, new)
    pid, name, url = str(new["_id"]), new["name"], link(new)
    before = _tasks(old)
    for tid, (stage, tk) in _tasks(new).items():
        prev = before.get(tid, (None, {}))[1]
        if tk.get("assignee_id") and tk["assignee_id"] != prev.get("assignee_id"):
            notify.send("task_assigned", [tk["assignee_id"]],
                        f"{tk['title']} ({stage['name']}, {name}) — {tk.get('start')} to {tk.get('end')}",
                        url, project_id=pid)
        if tk["status"] == "blocked" and prev.get("status") != "blocked":
            notify.send("task_blocked", managers(new),
                        f"{tk['title']} is blocked ({stage['name']}, {name})"
                        + (f" — {tk['notes']}" if tk.get("notes") else ""), url, project_id=pid)
    old_stages = {s["id"]: s for s in old.get("stages", [])}
    for s in new.get("stages", []):
        was = old_stages.get(s["id"], {})
        if s.get("status") == "done" and was.get("status") != "done" and s.get("tasks"):
            notify.send("stage_done", managers(new) + owners(), f"{s['name']} is complete on {name}", url,
                        project_id=pid)
    old_ms = _milestones(old)
    for mid, (stage, ms) in _milestones(new).items():
        if ms["status"] == "achieved" and old_ms.get(mid, (None, {}))[1].get("status") != "achieved":
            notify.send("milestone_achieved", managers(new) + owners(), f"{ms['name']} achieved on {name}", url,
                        project_id=pid)


def added_to_team(p, entry):
    log(p["_id"], "team", f"{entry['name']} added as {entry['project_role']} ({entry['access']} access)")
    if entry.get("user_id"):
        notify.send("project_added", [entry["user_id"]],
                    f"You were added to {p['name']} as {entry['project_role']} ({entry['access']} access)",
                    link(p), project_id=str(p["_id"]))


def issue_raised(p, issue):
    log(p["_id"], "issue", f"{issue['severity'].capitalize()} issue raised: {issue['title']}"
        + (f" (owner {issue['owner_name']})" if issue.get("owner_name") else ""), issue_id=str(issue["_id"]))
    who = [issue.get("owner_id")] + (managers(p) if issue["severity"] == "high" else [])
    notify.send("issue_raised", who, f"{issue['severity'].capitalize()} issue on {p['name']}: {issue['title']}",
                link(p), project_id=str(p["_id"]), level="warn" if issue["severity"] == "high" else "info")


# ---------------- activity log (B+2 / B+3) ----------------
# kinds group the project timeline's filters
ACTIVITY_GROUPS = {
    "Tasks": ["task"],
    "Stages & milestones": ["stage", "milestone", "checklist", "signoff"],
    "Schedule & delays": ["schedule", "baseline", "delay"],
    "Team": ["team"],
    "Issues": ["issue"],
    "Comments & files": ["comment", "file"],
    "Meetings": ["meeting"],
    "Edits": ["edit"],
}


def log(pid, kind, text, **extra):
    db.project_activity.insert_one({"company_id": g.cid, "project_id": str(pid), "kind": kind, "text": text,
                                    "at": _now(), "by": (getattr(g, "user", None) or {}).get("name"),
                                    "by_id": getattr(g, "uid", None), **extra})


def _now():
    from ..tenancy import now
    return now()


def log_stage_changes(old, new):
    """Timeline entries for what changed in stages, tasks and milestones (one write can change several)."""
    pid = str(new["_id"])
    before, after = _tasks(old), _tasks(new)
    for tid, (stage, tk) in after.items():
        prev = before.get(tid, (None, None))[1]
        if prev is None:
            log(pid, "task", f"Task added: {tk['title']} ({stage['name']}, {tk.get('start')} → {tk.get('end')})"
                + (f", assigned to {tk['assignee_name']}" if tk.get("assignee_name") else ""), task_id=tid)
            continue
        if tk["status"] != prev["status"]:
            log(pid, "task", f"{tk['title']}: {prev['status'].replace('_', ' ')} → {tk['status'].replace('_', ' ')}"
                + (f" ({tk['notes']})" if tk["status"] == "blocked" and tk.get("notes") else ""), task_id=tid)
        if tk.get("assignee_id") != prev.get("assignee_id"):
            log(pid, "task", f"{tk['title']}: assigned to {tk.get('assignee_name') or 'nobody'}"
                + (f" (was {prev.get('assignee_name')})" if prev.get("assignee_name") else ""), task_id=tid)
        if (tk.get("start"), tk.get("end")) != (prev.get("start"), prev.get("end")):
            log(pid, "schedule", f"{tk['title']}: {prev.get('start')} → {prev.get('end')} moved to "
                f"{tk.get('start')} → {tk.get('end')}", task_id=tid)
        if tk.get("title") != prev.get("title"):
            log(pid, "task", f"Task renamed: {prev.get('title')} → {tk['title']}", task_id=tid)
    for tid, (stage, tk) in before.items():
        if tid not in after:
            log(pid, "task", f"Task deleted: {tk['title']} ({stage['name']})", task_id=tid)
    old_stages = {s["id"]: s for s in old.get("stages", [])}
    new_ids = set()
    for s in new.get("stages", []):
        new_ids.add(s["id"])
        was = old_stages.get(s["id"])
        if not was:
            log(pid, "stage", f"Stage added: {s['name']} ({s.get('start')} → {s.get('end')})", stage_id=s["id"])
            continue
        if s.get("status") != was.get("status") and s.get("status") in ("done", "on_hold") \
                or was.get("status") == "on_hold" and s.get("status") != "on_hold":
            log(pid, "stage", f"{s['name']}: {was.get('status', '').replace('_', ' ')} → {s.get('status', '').replace('_', ' ')}",
                stage_id=s["id"])
        if s.get("name") != was.get("name"):
            log(pid, "stage", f"Stage renamed: {was.get('name')} → {s['name']}", stage_id=s["id"])
    for sid, s in old_stages.items():
        if sid not in new_ids:
            log(pid, "stage", f"Stage deleted: {s['name']}", stage_id=sid)
    old_ms = _milestones(old)
    for mid, (stage, ms) in _milestones(new).items():
        was = old_ms.get(mid, (None, None))[1]
        if was is None:
            if old.get("stages"):  # not when the project is created
                log(pid, "milestone", f"Milestone added: {ms['name']} (due {ms.get('due')})", milestone_id=mid)
        elif ms["status"] != was["status"]:
            log(pid, "milestone", f"{ms['name']}: {'achieved' if ms['status'] == 'achieved' else 'reopened'}"
                + (f" — owner override: {ms['override_reason']}" if ms["status"] == "achieved" and ms.get("override_reason") else ""),
                milestone_id=mid)
        elif ms.get("due") != was.get("due"):
            log(pid, "schedule", f"{ms['name']}: due {was.get('due')} → {ms.get('due')}", milestone_id=mid)
