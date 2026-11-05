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

from ..db import db
from . import notify

PM_ROLE = "Project Manager"


def link(p):
    return f"/app/projects/{p['_id']}"


def managers(p):
    """Staff on the team with the Project Manager role; when there is none, every Owner."""
    ids = [m["user_id"] for m in p.get("team", []) if m.get("user_id") and m.get("project_role") == PM_ROLE]
    return ids or owners()


def owners():
    return [str(u["_id"]) for u in db.users.find({"company_id": g.cid, "role": "owner", "kind": "staff",
                                                  "active": {"$ne": False}}, {"_id": 1})]


def _tasks(p):
    return {tk["id"]: (s, tk) for s in p.get("stages", []) for tk in s.get("tasks", [])}


def _milestones(p):
    return {ms["id"]: (s, ms) for s in p.get("stages", []) for ms in s.get("milestones", [])}


def stage_changes(old, new):
    """Compare the project before and after a write and notify what changed."""
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
    if entry.get("user_id"):
        notify.send("project_added", [entry["user_id"]],
                    f"You were added to {p['name']} as {entry['project_role']} ({entry['access']} access)",
                    link(p), project_id=str(p["_id"]))


def issue_raised(p, issue):
    who = [issue.get("owner_id")] + (managers(p) if issue["severity"] == "high" else [])
    notify.send("issue_raised", who, f"{issue['severity'].capitalize()} issue on {p['name']}: {issue['title']}",
                link(p), project_id=str(p["_id"]), level="warn" if issue["severity"] == "high" else "info")
