# BuildSuite CRM — Phase A: Authentication & Authorization

Source: *Construction & Interior CRM – Requirements (v4)*, sections 1 (roles), 13 (portal users) and 18 (Super Admin roles, plan limits).
Stack: **Angular 19 + PrimeNG 19 (Aura theme)** · **Python 3.12 / Flask** · **MongoDB 7** · **Docker Compose**.

Scope is deliberately limited to this phase. Later phases (leads, projects, finance, …) are planned only after this one is approved.

---

## 1. What this phase delivers

| # | Capability | Done when |
|---|---|---|
| A1 | Company signup (company type → modules, plan, 14-day trial) | New owner lands in the app with the right modules |
| A2 | Login / logout for staff and portal users | Staff → `/app`, portal → `/portal` |
| A3 | 12 company roles (8 staff + 4 portal) with per-area read / write | API returns 403 exactly where the matrix says |
| A4 | Cost hiding for Site Supervisor and all portal roles | Cost fields never leave the server for those roles |
| A5 | User management (add, edit role, reset password, deactivate) | Owner-only; changes apply on the next request |
| A6 | Plan limits (Basic 5 users / 1 module, Pro 15, Enterprise 50) | 6th staff user on Basic → 402 |
| A7 | Tenant isolation | A company can never read or change another's records |
| A8 | Company status: trial / active / read-only / suspended | Suspended → all its users blocked; read-only → GET only |
| A9 | Super Admin login with two-factor + 5 platform roles | Owner / Billing / Support / Sales / Viewer gated per area |
| A10 | Audit log (company + Super Admin) | Every write records who / what / when / diff |

Out of scope now: real TOTP app pairing (demo code `123456`), password-reset email, SSO, business modules.

---

## 2. Roles

**Company staff** (counted against the plan, except WhatsApp-only site workers)

| Role | Areas (rw = edit, r = view) |
|---|---|
| Owner / Admin | everything |
| Sales / BD | leads, contacts, proposals, follow-ups, messages (rw) · projects, documents, reports (r) |
| Project Manager | projects, change orders, site, documents, contacts, procurement, finance, selections, follow-ups, messages (rw) · proposals, reports, leads (r) |
| Architect / Designer | documents, selections, change orders, follow-ups, messages (rw) · projects, contacts, finance, proposals (r) |
| Estimator / QS | proposals, follow-ups (rw) · projects, contacts, procurement, leads (r) |
| Site Supervisor | site, messages, follow-ups (rw) · projects, documents, change orders, procurement (r) · **costs hidden** |
| Procurement | procurement, contacts, messages, follow-ups (rw) · selections, projects, finance (r) |
| Accounts | finance, follow-ups, messages (rw) · projects, contacts, reports, procurement, change orders, proposals (r) |

**Portal users** (free): Client, Subcontractor, Vendor / Supplier, Consultant — portal only, costs always hidden.

**Super Admin**: Owner (everything) · Billing (billing, reports) · Support (support, read companies) · Sales (companies, coupons) · Viewer (dashboard, reports, read companies). Super Admins can never call company-data endpoints.

The single source of truth is `ROLE_PERMS` / `SA_ROLES` in [backend/app/security.py](backend/app/security.py).

---

## 3. How it works

```
Browser ─► nginx :8080 ─┬─ /        Angular SPA (PrimeNG)
                        └─ /api/* ─► Flask (gunicorn) ─► MongoDB
```

* **Tokens** — JWT (HS256, 12 h). Payload carries only ids; **role, active flag and company status are re-read from MongoDB on every request**, so a role change, deactivation or suspension takes effect immediately.
* **Decorators** — `@api(area)` (staff + permission, read/write inferred from HTTP method), `@portal` (external users), `@superadmin(area)`.
* **Tenancy** — every tenant document carries `company_id`; `app/tenancy.py` injects it into every query/insert/update.
* **Passwords** — bcrypt. Super Admin passwords ≥ 8 chars + second factor.
* **Frontend** — `AuthService` (signals) holds the session; `authInterceptor` adds the bearer token and signs out on 401; route guards (`staffGuard`, `portalGuard`, `saGuard`) mirror the API's checks. The UI only hides what the API already blocks — the API is the authority.

---

## 4. Extension rules (so later phases plug in without conflicts)

1. **Permission areas are a registry.** A new module adds its area key to `AREAS` and the role levels to `ROLE_PERMS`; the frontend adds one entry to `NAV` in [frontend/src/app/core/nav.ts](frontend/src/app/core/nav.ts) and its route with `data: { area }`. Nothing else changes.
2. **Defaults in code, customisations in data.** Effective permissions = code defaults merged with optional `company.role_overrides[role][area]`. New areas appear for every company automatically and a company's customisations are never overwritten.
3. **Versioned, idempotent migrations.** Data changes go into a new numbered function in [backend/app/migrations.py](backend/app/migrations.py) (`003_…`, `004_…`); applied keys are stored in `schema_migrations`. Never edit a shipped migration. Every environment converges to the same state.
4. **One blueprint per module**, registered in `create_app()` under `/api`. Endpoint names are prefixed by the module, so routes cannot collide.
5. **Tenant data only through `app/tenancy.py`** (`find/get/insert/update/delete`) — isolation and audit come for free.
6. **Parked code**: earlier drafts of the business modules live in `backend/later/` and are *not* registered. Each will be reviewed and moved in during its own phase.
7. **Tests per phase.** [backend/tests/test_auth.py](backend/tests/test_auth.py) runs every role against every area; later phases add their own test files and keep this one green.

---

## 5. Run & test

```bash
docker compose up -d --build
docker compose exec backend python tests/test_auth.py
```

* App: http://localhost:8080 · Super Admin: http://localhost:8080/sa/login
* Demo staff/portal password `Demo@123` (e.g. `owner@skyline.test`, `site@skyline.test`, `client@skyline.test`, `owner@nest.test`)
* Super Admin `superadmin@buildsuite.test` / `Admin@12345`, 2FA `123456` (also `sa-billing@…`, `sa-support@…`, `sa-sales@…`, `sa-viewer@…`)

### Manual test checklist
- [ ] Sign in as each staff role → menu shows only readable areas; **My access → Test all areas** reports 0 mismatches
- [ ] Site Supervisor: cost-hiding sample has no trade price / margin / budget
- [ ] Portal roles land on `/portal`; typing `/app` redirects back
- [ ] Owner adds a user, changes their role → the other user's next request reflects it; deactivate → they are signed out
- [ ] Nest (Basic): adding a 4th extra staff user shows the upgrade message; enabling a 2nd module is refused
- [ ] Super Admin: wrong 2FA code refused; Viewer cannot suspend; suspending Nest blocks `owner@nest.test` immediately
- [ ] Signup creates a trial company with the chosen modules

---

## 6. Next phase (proposed, awaiting approval)
Phase B — Contacts & Leads pipeline on top of this auth layer.
