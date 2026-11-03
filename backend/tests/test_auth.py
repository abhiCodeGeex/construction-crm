"""End-to-end auth/RBAC checks against a running API (demo seed required).

    docker compose exec backend python tests/test_auth.py
"""
import json
import time
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.security import AREAS, ROLE_PERMS, INTERNAL_ROLES, EXTERNAL_ROLES, SA_ROLES  # noqa: E402

BASE = os.getenv("API", "http://localhost:5000/api")
PW, SA_PW = "Demo@123", "Admin@12345"
failures, passed = [], 0


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name} {detail}")


def login(email):
    s, d = call("POST", "/auth/login", {"email": email, "password": PW})
    check(f"login {email}", s == 200, s)
    return d.get("token")


# 1. every staff role against every area (read + write)
for role in INTERNAL_ROLES:
    tok = login(f"{role}@skyline.test")
    for area in AREAS:
        level = ROLE_PERMS[role].get(area, "")
        s, _ = call("GET", f"/access/probe/{area}", token=tok)
        check(f"{role} read {area}", s == (200 if "r" in level else 403), s)
        s, d = call("POST", f"/access/probe/{area}", {}, token=tok)
        check(f"{role} write {area}", s == (200 if "w" in level else 403), s)
    s, d = call("GET", f"/access/probe/projects", token=tok)
    if s == 200:
        hidden = "trade_price" not in d["sample"]
        check(f"{role} cost hiding", hidden == (role == "site"), d["sample"])
    s, _ = call("GET", "/portal/me", token=tok)
    check(f"{role} blocked from portal", s == 403, s)

# 2. external portal roles: portal only
for role in EXTERNAL_ROLES:
    tok = login(f"{role}@skyline.test")
    s, d = call("GET", "/portal/me", token=tok)
    check(f"{role} portal/me", s == 200 and d.get("role") == role, s)
    for area in AREAS:
        s, _ = call("GET", f"/access/probe/{area}", token=tok)
        check(f"{role} blocked {area}", s == 403, s)

# 3. bad credentials / no token
check("wrong password", call("POST", "/auth/login", {"email": "owner@skyline.test", "password": "x"})[0] == 401)
check("no token", call("GET", "/auth/me")[0] == 401)
check("garbage token", call("GET", "/auth/me", token="abc")[0] == 401)

# 4. tenant isolation
nest = login("owner@nest.test")
s, users = call("GET", "/users", token=nest)
check("nest sees only own users", s == 200 and all(u["email"].endswith("@nest.test") for u in users), users)
owner = login("owner@skyline.test")
s, sky_users = call("GET", "/users", token=owner)
designer_id = next(u["id"] for u in sky_users if u["email"] == "designer@skyline.test")
check("cross-tenant update blocked", call("PUT", f"/users/{designer_id}", {"name": "hack"}, token=nest)[0] == 404)

# 5. user management rules
pm = login("pm@skyline.test")
check("pm cannot create users", call("POST", "/users", {"name": "x", "email": "x@x.test", "role": "sales",
                                                        "password": "secret1"}, token=pm)[0] == 403)
s, u = call("POST", "/users", {"name": "Temp Sales", "email": "temp.sales@skyline.test", "role": "sales",
                               "password": "secret1"}, token=owner)
if s == 409:
    u = next(x for x in call("GET", "/users", token=owner)[1] if x["email"] == "temp.sales@skyline.test")
    call("PUT", f"/users/{u['id']}", {"active": True, "role": "sales", "password": "secret1"}, token=owner)
    s = 201
check("owner creates user", s == 201, (s, u))
s, d = call("POST", "/auth/login", {"email": "temp.sales@skyline.test", "password": "secret1"})
temp = d.get("token")
check("new sales reads leads", call("GET", "/access/probe/leads", token=temp)[0] == 200)
call("PUT", f"/users/{u['id']}", {"role": "accounts"}, token=owner)
check("role change applies immediately", call("GET", "/access/probe/leads", token=temp)[0] == 403
      and call("GET", "/access/probe/finance", token=temp)[0] == 200)
call("PUT", f"/users/{u['id']}", {"active": False}, token=owner)
check("deactivated token rejected", call("GET", "/auth/me", token=temp)[0] == 401)
check("deactivated cannot login", call("POST", "/auth/login", {"email": "temp.sales@skyline.test",
                                                               "password": "secret1"})[0] == 403)
check("cannot deactivate self", call("PUT", f"/users/{call('GET', '/auth/me', token=owner)[1]['user']['id']}",
                                     {"active": False}, token=owner)[0] == 409)

# 6. plan limits (Basic = 5 users, 1 module)
created = 0
for i in range(6):
    s, _ = call("POST", "/users", {"name": f"N{i}", "email": f"n{i}.{int(time.time()*1000)}@nest.test", "role": "pm",
                                   "password": "secret1"}, token=nest)
    if s != 201:
        break
    created += 1
check("basic plan user limit -> 402", s == 402, (s, created))
check("basic plan module limit", call("PUT", "/company", {"modules": ["interior", "construction"]},
                                      token=nest)[0] == 402)

# 7. signup
s, d = call("POST", "/auth/signup", {"company_name": "Test Signup Co", "name": "Sign Up",
                                     "email": f"signup{int(time.time()*1000)}@test.test", "password": "secret1",
                                     "company_types": ["architect"]})
check("signup", s == 201 and d["user"]["role"] == "owner" and d["company"]["modules"] == ["architecture"], s)

# 8. super admin: 2FA, roles, separation
s, d = call("POST", "/sa/login", {"email": "superadmin@buildsuite.test", "password": SA_PW})
check("sa needs 2fa", s == 200 and d.get("two_factor_required"), d)
check("sa wrong 2fa", call("POST", "/sa/login", {"email": "superadmin@buildsuite.test", "password": SA_PW,
                                                  "code": "000000"})[0] == 401)
sa_tokens = {}
for role in SA_ROLES:
    email = "superadmin@buildsuite.test" if role == "owner" else f"sa-{role}@buildsuite.test"
    s, d = call("POST", "/sa/login", {"email": email, "password": SA_PW, "code": "123456"})
    check(f"sa login {role}", s == 200, s)
    sa_tokens[role] = d.get("token")
    from app.routes.superadmin import SA_AREAS, _sa_perms
    for area in SA_AREAS:
        lvl = _sa_perms(role).get(area, "")
        check(f"sa {role} read {area}", call("GET", f"/sa/probe/{area}", token=d["token"])[0] == (200 if "r" in lvl else 403))
        check(f"sa {role} write {area}", call("POST", f"/sa/probe/{area}", {}, token=d["token"])[0] == (200 if "w" in lvl else 403))
check("sa blocked from tenant data", call("GET", "/users", token=sa_tokens["owner"])[0] == 403)
check("tenant blocked from sa", call("GET", "/sa/dashboard", token=owner)[0] == 403)

# 9. suspended company
s, comps = call("GET", "/sa/companies", token=sa_tokens["owner"])
nest_id = next(c["id"] for c in comps if c["name"] == "Nest Interiors")
check("viewer cannot suspend", call("POST", f"/sa/companies/{nest_id}/action", {"action": "suspend"},
                                    token=sa_tokens["viewer"])[0] == 403)
call("POST", f"/sa/companies/{nest_id}/action", {"action": "suspend"}, token=sa_tokens["owner"])
check("suspended token blocked", call("GET", "/auth/me", token=nest)[0] == 403)
check("suspended login blocked", call("POST", "/auth/login", {"email": "owner@nest.test", "password": PW})[0] == 403)
call("POST", f"/sa/companies/{nest_id}/action", {"action": "reactivate"}, token=sa_tokens["owner"])
check("reactivated", call("GET", "/auth/me", token=nest)[0] == 200)

# cleanup extra nest users so the test can re-run
for x in call("GET", "/users", token=nest)[1]:
    if x["email"] not in ("owner@nest.test", "designer@nest.test") and x.get("active"):
        call("PUT", f"/users/{x['id']}", {"active": False}, token=nest)

# users and companies have no delete endpoint: remove this run's test logins and signed-up test companies directly
from pymongo import MongoClient
mdb = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]
nest_co = mdb.companies.find_one({"name": "Nest Interiors"})
mdb.users.delete_many({"company_id": str(nest_co["_id"]), "email": {"$regex": r"^n\d+\.\d+@nest\.test$"}})
for co in mdb.companies.find({"name": "Test Signup Co"}):
    for name in mdb.list_collection_names():
        if name not in ("companies", "plans", "schema_migrations"):
            mdb[name].delete_many({"company_id": str(co["_id"])})
    mdb.companies.delete_one({"_id": co["_id"]})
check("cleanup: no test logins left", not mdb.users.count_documents({"email": {"$regex": r"^(n\d+\.\d+@nest|signup\d+@test)\.test$"}}))

print(f"passed: {passed}  failed: {len(failures)}")
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
