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

---

# Phase B — Contacts, Projects & access control

Source: requirements §1 (company setup, per-project permissions, cost hiding, audit), §3 (contacts), §4 (projects), §13 (portal users see only their projects).
Out of scope (later phases): leads (C), proposals/budgets from estimates (D), costs/invoices/change orders (E), documents/selections/site (F), portal approvals & WhatsApp (G).

## B1. Requirement → implementation → test

| Req | Requirement line | Implementation | Test |
|---|---|---|---|
| §3.1 | Types: client, developer, architect, contractor, subcontractor, supplier, consultant, authority/inspector | `contacts.types[]` (multi-select, validated against this list); `kind` = company \| person; people link to their company (`org_id`) | create with invalid type → 400; filter by type |
| §3.2 | Roles per project — same firm client on one job, partner on another | Role lives on the **project team entry** (`team[].project_role`), never on the contact; contact page lists every project with its role there | same contact = Client on P1 and Architect on P2 |
| §3.3 | Trade category, rating, notes, past projects together | `trade_category`, `rating` (1–5), `notes`; "Projects together" tab from team membership | rating 6 → 400; history lists both projects |
| §3.4 | Compliance: insurance, licences, certificates, expiry alerts | `compliance[]` {type, name, number, issuer, issue/expiry date, file}; expiry status *expired / ≤30 days / valid*; alerts list on Home + Contacts | expired & expiring docs returned; valid not |
| §3.5 | Tax IDs, bank details (vendor payments), trade account numbers, discounts | `gstin`, `pan` (format-validated), `bank{account_name, account_no, ifsc, bank}` (IFSC validated), `trade_account_no`, `discount_pct` 0–100. **Bank details are masked** unless the role can edit finance or procurement | sales sees `••••1234`; accounts sees full |
| §3.6 | Relationship history: who referred what, what was won | `referred_by` on contacts and projects; history shows contacts & projects this contact referred, with total value of referred projects (won leads join in Phase C) | referral appears on referrer's history |
| §4.1 | Project → Phases/Stages → Tasks → Milestones | `projects.stages[]` → `tasks[]` and `milestones[]` | create/edit/delete each level |
| §4.2 | Default stage templates per service (Architecture, Construction, Interior) | Seeded per company exactly as in the doc, each stage with a default duration | new project gets the template stages |
| §4.3 | Templates editable per company; RIBA or AIA stages can be added | Settings → Stage templates: edit, reorder, add; one-click add *RIBA Plan of Work 2020* and *AIA phases*; choose default per service | edit template → next project uses it |
| §4.4 | One project can run all three services (design-and-build) | `services[]` limited to the company's enabled modules; stages built per service; adding a service later appends its stages | disabled module → 400 |
| §4.5 | Project team: internal staff + external parties with roles | `team[]` {user_id \| contact_id, project_role, access: edit\|view} | add staff & external |
| §4.6 | Gantt timeline with task dependencies and milestones | Gantt view: stage & task bars, milestone diamonds, finish-to-start arrows, today line; dependency cycle → 400; task can't start until predecessors are done → 409; date conflicts flagged | cycle, blocked start, conflict flag |
| §4.7 | Dashboard: progress %, budget vs actual, open issues, next milestones | Progress = duration-weighted stage progress (stage = % tasks done); budget = sum of stage budgets vs actual (cost entries arrive in Phase E, shown as 0 until then); project issue log; next 5 pending milestones with late flag | progress math; late flag |
| §4.8 | Site address with map, area, value | Address fields + map pin (OpenStreetMap / Leaflet, click to place); area with sq ft / m²; value | geo validated (lat/lng ranges) |
| §1 | Branches, currency, tax, numbering formats | Settings: branches list, currency, tax rate, project number format (e.g. `PRJ-{year}-{n:03d}`); project picks a branch | numbering format applied |
| §1 | Permissions per module and per project | **Module**: services must be enabled modules. **Project**: Owner sees all projects; everyone else sees only projects they are on. Edit needs role `projects:rw` **and** team access *edit*. Assignees may update their own tasks. Architect/Designer may edit **design stages** (Architecture & Interior services) on their projects | 403/404 matrix per role |
| §1 | Role permission editor | Owner adjusts any role's read/write per area (stored as overrides on top of code defaults); reset to default; owner role locked | override applies immediately; reset |
| §1 | Hide cost and margin from clients and site staff | Project `budget`/stage `budget`/`spent` stripped for Site Supervisor and portal | site response lacks budget |
| §1 | Audit log of who changed what | Every write via tenancy layer; project History tab | audit rows on project |
| §13 | Portal users see their projects | Client = project's client or external team member; read-only progress, stages, milestones; no money | client sees own only |

## B2. Rules fixed in this phase (no guessing later)
* **Task status**: todo → in_progress → done (or blocked). Moving to in_progress/done requires all predecessor tasks done.
* **Stage progress** = done tasks ÷ tasks; a stage without tasks uses its manual progress. Stage status follows (0 % not started, 100 % done, else in progress); *on hold* is manual.
* **Stage window** grows automatically to contain its tasks.
* **Milestones** auto-created at the end of each template stage ("<Stage> complete"); more can be added; achieved/pending.
* **Project status**: planning, active, on_hold, completed, cancelled. Active-project count is what the plan limit counts (planning + active).
* **Visibility**: creator is added to the team as Project Manager with edit access.

---

# Phase C — Leads, pipeline, bids & follow-ups

Source: requirements §2 (leads & sales pipeline) and the MVP line of §16: *"Follow-up tasks, reminders and message templates (automatic sequences in Phase 2)"*.
Out of scope: automatic sequences / automation rules and "proposal viewed" alerts (§16 Phase 2 and Phase D), sending email/SMS/WhatsApp through a provider (Phase G), approvals/payments waiting longest (Phases D–E).

## C1. Requirement → implementation → test

| Req | Requirement line | Implementation | Test |
|---|---|---|---|
| §2.0 | Every enquiry captured **once**, tracked until won project or recorded loss | Lead linked to a contact (existing, or created from the lead's name/phone/email). Creating a lead whose phone/email matches an **open** lead returns 409 with that lead unless "save anyway". Status: open → won (project created) or lost (reason required) | duplicate 409; force; won → project; lost needs reason |
| §2.1 | Sources: website form, referral, Houzz/portals, ads, walk-in, repeat client | `source` limited to these six (+ `source_detail`, e.g. portal or campaign). Referral requires *referred by* contact. Repeat client requires an existing contact. **Website form**: public, per-company form link + embeddable HTML; honeypot + rate limit | invalid source 400; referral w/o referrer 400; public form creates lead |
| §2.2 | Details: project type (new build, renovation, fit-out, interior), location, area (sq ft / m²), budget, timeline | `project_type` (4 values), `location`, `area` + `area_unit`, `budget`, `timeline` (Immediately, 1–3, 3–6, 6–12, 12+ months) | validation of each |
| §2.3 | Separate pipelines per service, e.g. Lead → Site visit → Proposal/Bid → Negotiation → Won / Lost | Each lead has one `service` (enabled modules only). Company keeps a stage list **per service** (default from the doc), editable in Settings; Won/Lost are fixed end states. Kanban board per service with drag-and-drop; every stage change recorded with time and user | board per service; stage not in that pipeline 400; history |
| §2.4 | Follow-up reminders, call / email / WhatsApp log, meeting notes | Activity log on the lead: call, email, WhatsApp, meeting, site visit, note (with outcome). Follow-ups (below) linked to the lead; next follow-up shown on the card; leads with no open follow-up flagged | log each type; next-follow-up |
| §2.5 | Win/loss reasons, conversion reports by source, service, salesperson | Win: choose project manager → Phase B project created with client, service, area, value, referral; lead locked. Loss: reason from an editable list + note. Sales report: pipeline value per stage, conversion % (won ÷ closed) by source / service / salesperson, loss reasons, first-response time | conversion math; report numbers |
| §2.6 | Bid/tender register: due dates, bid/no-bid decision, hit rate | Bids: title, client, lead, service, due date, value, decision (pending / bid / no-bid + reason), status (preparing → submitted → won / lost). Overdue flag. Hit rate = won ÷ (won + lost) of submitted bids | decision rules; hit rate |
| §16 | Follow-up tasks with owner, due date and priority | Follow-ups: title, notes, due date, priority (low / normal / high), owner (staff), channel, related lead / contact / project; done (with outcome) or cancelled | CRUD + rules |
| §16 | "Today's follow-ups" for every user; overdue highlighted | Today page: overdue, today, next 7 days; Owner/PM can view everyone's; count on Home | overdue/today buckets |
| §16 | Templates for email, SMS and WhatsApp with merge fields (client name, project, amount) | Templates per channel with `{{client}}`, `{{project}}`, `{{amount}}`, `{{company}}`, `{{name}}`, `{{date}}`; render against a lead/contact/project, copy, and *log as sent* (activity) — actual sending arrives with Phase G | merge render; unknown field kept visible |
| §16 | Every follow-up logged on the contact and project timeline | Contact page Activity tab and project page Follow-ups tab list linked follow-ups and lead activities | appears on both |
| §16 | Reports: overdue follow-ups per user, response time | Follow-up report: open / overdue / done per user; sales report: average first-response time per salesperson | numbers |
| §2/§3 | Relationship history: who referred what, and what was won | Contact history now also lists leads the contact referred and the won value | referral leads + won value |

## C2. Rules fixed in this phase
* **Visibility**: the pipeline is shared — every role with leads access sees all company leads. Changing leads needs `leads: rw` (Owner, Sales by default). Leads are assigned to a salesperson (`owner_id`); unassigned web-form leads show in an *Unassigned* filter.
* **Win**: needs a project manager (a staff user whose role can edit projects). The project is created even when the salesperson's own role cannot create projects; the PM gets edit access and the salesperson is added as *Sales* (view). The active-project plan limit still applies.
* **Locked**: won and lost leads are read-only except *reopen* (lost only, back to the stage it was lost from). Only the Owner deletes leads; a won lead cannot be deleted while its project exists.
* **Follow-ups**: everyone sees follow-ups they own or created; Owner and PM see all. Owner / creator / assignee can edit.
* **Templates**: managed in Settings (Owner); used by anyone with follow-ups access.
* **Pipeline edits**: a stage that still has open leads cannot be removed.

## C2b. Flow hand-offs between modules (audit, closes every open end)
Each module now hands its record on to the next, and nothing is left pointing at a deleted record or an inactive user. Covered by [backend/tests/test_flow_gaps.py](backend/tests/test_flow_gaps.py).

| Flow | Rule |
|---|---|
| Bid result | The result is recorded with **Won / Lost** on a *submitted* bid, never by editing (edit only moves *preparing → submitted*). Won and lost bids are read-only. |
| Bid won, no lead | A project is created straight from the bid: client, service and value, with a chosen PM (same PM rule as a lead win). Client and service are required. The project keeps `bid_id`. |
| Bid won, linked lead | The lead is won through the same path as *Mark as won* (project valued at the bid). If the lead was already won, the bid links that project and no second project is created. A lost linked lead must be reopened or unlinked first. |
| Bid lost | Needs a loss reason from the company list. A linked open lead is lost with the same reason (its follow-ups are cancelled). |
| Lead won / lost directly | Its *submitted* bids take the same result (won → linked to the project). Preparing bids are left alone. |
| Bid ↔ lead link | Optional, to an open lead only. The bid takes the lead's client and service. The lead page lists its bids; the register links to the lead and to the won project. A no-bid shows *Not bidding — reason*, a pending one *Awaiting decision*. |
| Project origin | The project page links back to the lead (or notes the won bid) it came from. |
| Project deleted | Its open follow-ups are cancelled; the won lead and bid keep their result but drop the link (lead activity notes the deletion), so the lead can then be deleted. |
| Lead deleted | Linked bids are unlinked. |
| Bid deleted | Not while it is won and its project exists. |
| Won bid without a project | (Won before this rule, or its project was deleted.) **Start project** on the bid creates the project from its service and value with a chosen PM, asking for the client if the bid has none; a won linked lead without a project is re-linked to it. Refused if the bid already has a project. |
| Contact deleted | Refused while the contact is the enquirer on a lead, the client on a bid, or the referrer of a contact, lead or project (relationship history, §3). Its open follow-ups are cancelled. |
| Project client | A contact set as a project's client gets the *client* type, so it is listed under Clients. |
| Lead reassigned | The previous salesperson's open follow-ups on that lead move to the new salesperson. |
| New lead refused | Nothing is saved: the enquirer's contact is created only after the whole lead is valid. |
| New enquirer | Can be marked as a company (not a person) on New lead. |
| User deactivated | If the user has open leads, follow-ups or tasks, an active colleague must be chosen: leads and follow-ups move to them; tasks move to them where they are on the project team, otherwise the task is unassigned for the PM. Logged in the audit. |
| Website form | Closed (404) when the company is read-only or cancelled, like every other write. |
| Choice buttons | Single-choice button groups (decision, status, unit, priority, access…) cannot be clicked back to empty, so a form never sends a blank required value. |

## C3. Next phase (proposed, awaiting approval)
Phase D — Proposals & estimates → contract with payment schedule.
