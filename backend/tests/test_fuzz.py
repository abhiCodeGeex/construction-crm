"""Hard negative testing: every API route x every role x bad input. Nothing may ever answer 500.

Run against a throwaway database (it creates junk records):
    docker compose exec -e API=http://localhost:5001/api -e MONGO_DB=buildsuite_rt backend python tests/test_fuzz.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pymongo import MongoClient  # noqa: E402

BASE = os.getenv("API", "http://localhost:5001/api")
DB = os.getenv("MONGO_DB", "buildsuite_rt")
assert DB != "buildsuite", "run the fuzz test on a throwaway database"
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[DB]


def call(method, path, body=None, token=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, method=method, data=data)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:2000]
    except Exception as e:  # connection reset etc. counts as a failure too
        return 599, str(e).encode()


def login(email, pw="Demo@123"):
    s, d = call("POST", "/auth/login", {"email": email, "password": pw})
    return json.loads(d)["token"] if s == 200 else None


ROLES = ["owner", "sales", "pm", "designer", "estimator", "site", "procurement", "accounts", "client", "subcontractor", "vendor", "consultant"]
TOK = {r: login(f"{r}@skyline.test") for r in ROLES}
TOK["nest_owner"] = login("owner@nest.test")
TOK["none"] = None
TOK["bad"] = "not.a.token"

cid = mongo.users.find_one({"email": "owner@skyline.test"})["company_id"]
real = {
    "project": str(mongo.projects.find_one({"company_id": cid})["_id"]),
    "lead": str(mongo.leads.find_one({"company_id": cid})["_id"]),
    "contact": str(mongo.contacts.find_one({"company_id": cid})["_id"]),
}

HUGE = "x" * 200_000
WRONG = {"name": 123, "title": [], "start": "not-a-date", "end": 5, "due": {"a": 1}, "date": "2026-13-45", "status": {}, "amount": "abc",
         "value": -5, "email": 7, "text": None, "items": "x", "links": "x", "depends_on": "x", "stages": "x", "checklist": "x",
         "waiting_on": "x", "staff": "x", "contacts": 5, "actions": [1], "decisions": 5, "code": 5, "password": 5, "key": [],
         "at": "yesterday", "owner_id": ["x"], "assignee_id": {"x": 1}, "progress": "half", "lag": "a", "priority": 9,
         "events": "x", "working_days": "x", "holidays": [{"date": 5}], "rows": "x", "service": 7, "stage": [], "folder": 3,
         "type": [], "party": 4, "reason": [], "lines": "x", "phone": [], "budget": "lots", "area": "big", "pct": "x",
         "payment_schedule": "x", "fee": "x", "competitors": "x", "rate": "x", "qty": "x", "quantity": "x", "stage_id": 5,
         "user_id": 5, "contact_id": [], "role": 5, "access": [], "kind": 5, "types": "x", "compliance": "x", "bank": "x"}
ODD = {k: "'; DROP TABLE x; -- <script>alert(1)</script> ‮ 😀 \x00" for k in ("name", "title", "text", "note", "notes", "email", "q")}
BODIES = {"none": None, "empty": {}, "list": [1, 2], "wrong_types": WRONG, "odd_text": ODD, "huge": {"name": HUGE, "title": HUGE, "text": HUGE},
          "not_json": "raw"}


def routes():
    from app import create_app
    app = create_app()
    out = []
    for r in app.url_map.iter_rules():
        if not r.rule.startswith("/api/"):
            continue
        for m in r.methods - {"HEAD", "OPTIONS"}:
            out.append((m, r.rule[4:], list(r.arguments)))
    return sorted(out)


def fill(rule, args, mode):
    path = rule
    for a in args:
        if mode == "invalid":
            v = "zzz"
        elif mode == "missing":
            v = "0" * 24
        else:
            v = real["project"] if "/projects/" in rule or rule.startswith("/projects") else \
                real["lead"] if "/leads/" in rule else real["contact"] if "/contacts/" in rule else "0" * 24
        path = re.sub(r"<(?:[^:>]+:)?" + a + ">", v, path)
    return path


fails = {}
closed = set()
count = 0
jobs = []
for method, rule, args in routes():
    modes = ["invalid", "missing"] + (["real"] if args and method != "DELETE" else []) if args else ["plain"]
    if "superadmin" in rule or rule.startswith("/sa/"):
        tokens = ["none", "bad", "owner"]
    else:
        tokens = list(TOK)
    for mode in modes:
        path = fill(rule, args, mode if mode != "plain" else "missing")
        for tk in tokens:  # every role: no body / empty body; three roles: every kind of bad body
            bodies = ["none"] if method == "GET" else (["empty"] if tk not in ("owner", "pm", "client") else list(BODIES))
            for b in bodies:
                jobs.append((method, rule, mode, b, tk, path))


def run(job):
    method, rule, mode, b, tk, path = job
    st, d = call(method, path, BODIES[b] if b != "not_json" else None, TOK[tk], raw=b"{not json" if b == "not_json" else None)
    return job, st, d


from concurrent.futures import ThreadPoolExecutor  # noqa: E402
with ThreadPoolExecutor(12) as ex:
    for (method, rule, mode, b, tk, path), st, d in ex.map(run, jobs):
        count += 1
        if st == 599 and b == "huge":
            closed.add((method, rule))  # the server answered before reading a 600 KB body; checked in the log below
        elif st >= 500:
            fails.setdefault((method, rule, mode, b), (st, tk, d.decode(errors="replace")[:160]))

print(f"requests: {count}  crashes (5xx): {len(fails)}  huge bodies answered early: {len(closed)} routes")
for (m, r, mode, b), (st, tk, d) in sorted(fails.items()):
    print(f"  {st} {m} {r}  ids={mode} body={b} as={tk}  {d}")
sys.exit(1 if fails else 0)
