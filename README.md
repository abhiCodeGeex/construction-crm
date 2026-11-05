# BuildSuite CRM

Construction & interior CRM — Angular 19 + PrimeNG (Aura) · Flask · MongoDB · Docker.

**Current phase: C+ — leads in depth** (Phases A, B and C are done). See [PLAN.md](PLAN.md).

## Run

```bash
docker compose up -d --build
```

- App: http://localhost:8080
- Super Admin: http://localhost:8080/sa/login
- API health: http://localhost:8080/api/health
- The `worker` service runs the scheduled checks every minute (reminders, escalations, on-hold resume) — see `backend/app/worker.py`.

## Demo accounts

| Who | Email | Password |
|---|---|---|
| Staff (Skyline, Pro) | `owner`, `sales`, `pm`, `designer`, `estimator`, `site`, `procurement`, `accounts` `@skyline.test` | `Demo@123` |
| Portal (Skyline) | `client`, `subcontractor`, `vendor`, `consultant` `@skyline.test` | `Demo@123` |
| Second tenant (Nest, Basic) | `owner@nest.test`, `designer@nest.test` | `Demo@123` |
| Super Admin | `superadmin@buildsuite.test`, `sa-billing@…`, `sa-support@…`, `sa-sales@…`, `sa-viewer@…` | `Admin@12345`, 2FA `123456` |

## Tests

```bash
docker compose exec backend python tests/test_auth.py
docker compose exec backend python tests/test_phase_b.py
docker compose exec backend python tests/test_phase_c.py
docker compose exec backend python tests/test_e2e_flow.py
docker compose exec backend python tests/test_flow_gaps.py
docker compose exec backend python tests/test_leads_deep.py
```

`test_auth.py` runs every role against every permission area plus isolation, limits, deactivation, suspension and Super Admin checks. `test_phase_b.py` covers every Phase B requirement row in PLAN.md (B1). `test_phase_c.py` covers every Phase C row (C1). `test_e2e_flow.py` walks one enquiry through to a delivered project. `test_flow_gaps.py` covers the hand-offs between modules (PLAN.md C2b). `test_leads_deep.py` covers Phase C+ (leads in depth: notifications, stage rules, scheduled checks, email). Every suite removes the records it creates (test logins and signed-up test companies included), so the demo data stays clean between runs.

## Layout

```
backend/   Flask API (app/), migrations, seed, tests; backend/later/ = parked drafts of future modules (not loaded)
frontend/  Angular app (core/ = auth, guards, nav registry; pages/; superadmin/)
```

Set `SECRET_KEY` in the environment before any non-local deployment. `SEED_DEMO=0` skips demo users.
