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

Out of scope at the time: real TOTP app pairing, password-reset email, SSO, business modules. **The first two are done in Phase B+ block 1** (see the end of this file).

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
* Super Admin `superadmin@buildsuite.test` / `Admin@12345`, then a code from an authenticator app set up at the first sign-in (also `sa-billing@…`, `sa-support@…`, `sa-sales@…`, `sa-viewer@…`)

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

## C3. Next phase
Phase C+ (below), then Phase D — Proposals & estimates → contract with payment schedule.

---

# Phase C+ — Leads in depth

Source: the leads review (sections A–E agreed with the owner), built on requirements §2, §3, §5 (estimate inputs), §15 (notifications) and §16 (follow-ups). The proposal *builder*, client e-signature, the public proposal link and "viewed" tracking stay in Phase D; WhatsApp / SMS sending stays in Phase G. Everything else about a lead is here. Covered by [backend/tests/test_leads_deep.py](backend/tests/test_leads_deep.py).

### Build status (delivered block by block, each tested and committed)
| Block | Scope | Status |
|---|---|---|
| 1 | Notifications + bell + email, preferences, stage checklists / exit rules / day limits / override, call & meeting outcome + next step, old→new edit log, temperature / probability / close date / score / value, on hold & resume, lost with competitor + re-engage, sales settings, visibility, worker (response time, stuck, hot idle, follow-ups, resume) | **Done** |
| 2 | Site visits (appointments, reminders, report, cost), measurements, site checklist, lead files | **Done** |
| 3 | Brief + client questionnaire, decision-makers, ballpark from package rates | **Done** |
| 4 | Rate library, estimates + approval, expenses, receipts, proposals tracking, negotiation, competitors, won carry-over to the project | **Done** |
| 5 | Assignment rules, merge, import, bulk, export, saved views, calendar, Needs attention, bid additions, reports | **Done** |

## C+1. Rules for every step
| Rule | Implementation | Test |
|---|---|---|
| Every action is logged | Every lead change pushes a timeline entry `{type, text, at, by, changes?}`; edits record **old → new** per field | edit shows old→new; each action below adds an entry |
| Stage checklist + exit rules | Settings → Sales → *Stage rules* per service and stage: checklist items, required steps (`first_contact`, `visit_done`, `measurements`, `brief_complete`, `estimate_approved`, `proposal_sent`), day limit, win probability. Moving **forward** needs every stage passed to meet its rules (no skipping); moving back is free. The Owner may override with a reason (logged) | forward move refused with the missing items; override logged |
| Calls / meetings need outcome + next step | `call` needs an outcome from *Reached, No answer, Busy, Wrong number, Call back later*; `meeting` needs an outcome; both need a next follow-up date (not for *Wrong number*), which creates the follow-up. A site visit is no longer typed as a note — it is booked as an appointment | 400 without outcome / next date; follow-up created |
| Day limit per stage | `stage_entered_at` → days in stage on every card; past the limit the salesperson is notified, past twice the limit the sales manager | worker notifications |
| One notification matrix | `services/notify.py`: in-app bell for every staff user + email when the company has set up email (SMTP). Each user can switch off non-critical events (critical: assigned, approvals, visit assigned). A key per event prevents duplicate reminders | prefs respected; no duplicate |
| Sales manager | Settings → Sales: a chosen staff user, else every Owner. Receives escalations and approvals | recipients |

## C+2. The journey
| Step | Captured / actions | Logged | Notified |
|---|---|---|---|
| 1 New enquiry | Language, best time to call, preferred channel, branch, tags. **Assignment rules** (first rule matching service / branch → round-robin in its pool; no match → unassigned, to the manager). **Merge** two leads. **Import** CSV / Excel with a dry run. One-tap call / WhatsApp / email links | created, assigned, merged, imported | salesperson: *New lead assigned*; manager: *Unassigned lead*, *Not contacted within N min* (again after 24 h) |
| 2 Qualification | Stage checklist; **decision-makers** (contacts with a role, one marked main); temperature hot / warm / cold; expected close date; probability (stage default, overridable); **ballpark** = area × package rate (Settings) with a **budget-gap warning** | call with outcome, checklist ticks, temperature / probability / close date (old→new), ballpark | salesperson: follow-up reminders; manager: *Hot lead idle N days* |
| 3 Site visit & measurement | **Appointment** (date/time, duration, staff, address): scheduled → confirmed → done / no-show / cancelled; reschedule keeps old→new time and reason. **Measurements** room by room (L×W×H, doors / windows → floor, wall, net wall area, perimeter) and plot (size, setbacks, floors, soil, access). **Site condition checklist** (yes / no / n.a. + note). **Photos & files** per room. **Visit report** (findings, risks, recommendations). **Visit cost** (travel, staff hours × rate, other) → pre-sales spend | every status change, report, measurement add / edit / delete, file | staff: *Visit assigned*, day-before and 2-hour reminders; client: email reminder; salesperson: *Report submitted*; manager: *Visit missed*, *Report not submitted in 24 h* |
| 4 Brief | Scope per room × work types, style, materials, brands, must-haves, nice-to-haves, reference files, architecture programme and approvals. **Client questionnaire** link (public, one submission). Brief versions; client confirmation | each version (what changed), questionnaire sent / submitted, confirmed | salesperson: *Questionnaire submitted*; estimators: *Brief ready for estimate* |
| 5a Estimate (internal) | **Rate library** (material, labour, product; unit, rate). Estimate lines by room: quantity typed or taken from a measurement (floor / wall / net wall / ceiling area, perimeter), material + labour rate, overheads %, markup %, discount %, tax → cost, price and margin. Versions. **Approval** when margin < the minimum or discount > the limit. Hidden from site staff and clients | created, edited, submitted, approved / refused | approver: *Estimate needs approval*; author: *approved / refused* |
| 5b Proposal (tracking) | Proposal versions from an estimate or a typed value, validity date, file; sent (channel, date); accepted / rejected (reason + comment) / revision requested → next version; expired; **only one accepted** per lead | each status change | salesperson: *Accepted / Rejected*, *Not accepted in 3 days* (+ follow-up), *Expires in 2 days*; manager: *Rejected*, *Expired* |
| 6 Negotiation | Rounds: asked, offered, discount %, note; a discount above the limit needs approval. Competitors (name, price, notes) | every round, approval | approver / salesperson |
| 7 Won | Value defaults to the accepted proposal. Optional **advance received** (amount, date, mode, reference → receipt number). The project gets the brief, measurements, decision-makers (added to the team, view), accepted proposal, files and receipts — shown on the project as **From the lead**. A hand-off meeting follow-up is created for the PM | won, advance, files moved | PM: *You are PM*; Accounts: *Advance / contract value*; Owner + manager: *Lead won*; client: welcome email |
| 8 Lost / On hold / Reopen | Lost: reason, competitor, their price, re-engage date (creates a follow-up for that day). **On hold**: reason + resume date; leaves the active pipeline, not counted as lost, returns on that date. Reopen returns to the stage it left | each with its reason | manager: *Lead lost*; salesperson: *Resumes today*, *Re-engage today* |
| 9 Any time | Reassign, edit, change service, delete (Owner; refused once money was received), merge | old→new | old and new salesperson on reassignment |

## C+3. Across the module
| Area | Implementation |
|---|---|
| Timeline | One feed with filters (calls & messages, visits, brief, money, proposals, stage & status, edits) |
| Files | Lead files with a folder (photos, client drawings, brief, proposals, other) and room; they move to the project on win |
| Calendar | Visits, follow-ups, bid due dates and proposal expiry, per user or team (Follow-ups → Calendar) |
| Pre-sales money | Expenses (site visit, staff time, 3D renders, samples, consultant, marketing, other) and receipts (token / booking advance, design-fee advance) on the lead |
| Value, probability, score | Value = accepted or latest sent proposal → approved estimate → ballpark → budget. Weighted = value × probability. Score 0–100 = source (20) + budget fit (25) + temperature (25) + last contact (15) + first response within target (15) |
| Board cards | Temperature, days in stage (red over the limit), value, score, next follow-up |
| Needs attention | Not contacted, stuck, missed visits, late reports, proposals expiring / not accepted, approvals waiting, overdue follow-ups, hot & idle, unassigned |
| Bulk / views | Select leads → reassign, move stage (rules apply), tag, temperature; export CSV; saved filters per user |
| Visibility | Optional *salespeople see only their own leads* |
| Bids | Owner, site-walk date, Q&A deadline, documents & addenda, competitor + price on a loss; reminders 7 / 2 / 0 days before due; win rate per owner |
| Reports | Funnel with drop-off, time in stage, visit→win, proposal→win, average discount, losses per competitor, cost to acquire + ROI per source, monthly weighted forecast, response target met %, salesperson leaderboard |
| Settings | Stage rules, package rates, rate library, response target, approval limits, assignment rules, sales manager, visibility, email (SMTP) |
| Scheduled checks | A `worker` service runs every minute: reminders, escalations, expiry, on-hold resume, re-engage, bid due dates |

## C+4. Not in C+ (and where it goes)
| Item | Where |
|---|---|
| Proposal document builder, the client's proposal link, "viewed" tracking, e-signature, contract + payment schedule | Phase D (C+ tracks every proposal version, its answer and expiry) |
| Sending WhatsApp / SMS (email already works through the company's SMTP) | Phase G |
| Call recording and automatic logging of WhatsApp chats | Needs a telephony / WhatsApp Business provider (requirements §17, Phase 2) |
| Automatic follow-up sequences (day 1, 3, 7) | Requirements §16 puts them in Phase 2; C+ creates the follow-ups each step needs |
| Google / Outlook calendar sync | Integration (§15); the in-app calendar is in C+ |
| Real costs updating the rate library | Phase E (§12 "learn from it") |
| AI follow-up drafts | Phase 3 |

---

# Phase D — Proposals & estimates → contract with payment schedule

Source: requirements §5 (proposal types, templates, versions, optional items, discounts, taxes, online acceptance with e-signature, contract with a payment schedule tied to milestones, rate library), §1 (branding on proposals), §16 (alert when a proposal is viewed but not accepted). Builds on the C+ proposal tracking and estimates. Invoicing against the schedule is Phase E. Covered by [backend/tests/test_phase_d.py](backend/tests/test_phase_d.py).

## D1. Requirement → implementation → test
| Req | Requirement line | Implementation | Test |
|---|---|---|---|
| §5 | Fee proposal: fixed fee, hourly, % of project cost, per sq ft/m² | Type *fee*: basis fixed / hourly (hours × rate) / percent (% × project cost) / per area (area × rate); optional split of the fee across stages (% each, totals 100) | each basis; split must total 100 |
| §5 | Construction estimate: BOQ with quantities, material + labour rates, overheads, markup | Type *construction* from an **approved** C+ estimate: every estimate line becomes a client line priced at its share of the estimate's price (cost × overheads × markup), so the client never sees cost, overheads or markup and the proposal total equals the estimate total | totals equal; no cost fields in the client view |
| §5 | Interior quote: design fee + product list with markup | Type *interior*: design fee (fixed or per area) + products (room, name, brand, qty, unit, trade price, markup %) → client price; trade price and margin internal only | client price = trade × (1 + markup) |
| §5 | Templates | Settings → Proposals: templates per type (intro, scope, terms, default lines, payment schedule). Each company starts with one per enabled service, editable | create from template copies content |
| §5 | Versions (v1, v2…) | Every proposal of a lead is a version; *Revise* copies the content into a new draft version | revision copies content |
| §5 | Optional items | Lines can be optional; the client ticks the ones they want before accepting; the total follows | accepted total includes chosen items only |
| §5 | Discounts, taxes | Discount % and tax % (company tax rate by default, its label shown); a discount above the limit, or a margin below the minimum where cost is known, needs the owner / sales manager's approval before sending | send refused until approved |
| §5 | Online acceptance with e-signature | Sending creates a private client link. The client sees the branded proposal, picks optional items, types their name, draws their signature and accepts; time, IP address and browser are recorded with the signature. They can also decline or ask for changes (with a reason). Accepting on paper can still be recorded by staff | sign; decline; expired / used link refused |
| §16 | Alert when a proposal is viewed but not accepted | Every opening of the client link is logged (time, count); the salesperson is told at the first view; the worker reminds them when it was viewed 2 days ago and is still not answered | first view notifies once; reminder once |
| §1 | Branding on proposals | Settings → Company: logo, brand colour, address / phone / email / website footer — on the client page and the printout | logo served publicly only for the company's own logo |
| §5 | Converts to a contract with a payment schedule tied to milestones | Accepting creates the contract (number, value, signed lines, signature, payment schedule). Schedule rows: % of value due **on signing**, **on a stage's completion** (stage of the service's default template) or **on a date**; rows total 100 %. When the lead is won the contract joins the project: the project value is the contract value and each stage row links to that stage's "complete" milestone; a row is *due* once its trigger happens | schedule must total 100; milestone links; due follows the milestone |
| §5 | Rate library reused across estimates | Done in C+ (estimates); product lines can be picked from it | — |
| — | Print / PDF | A print layout of the proposal and of the contract (browser "Save as PDF") | — |

## D2. Rules fixed in this phase
* A proposal can only be edited as a draft. Editing after an approval clears the approval.
* One accepted proposal per lead; accepting supersedes the other open versions.
* The client link works only while the proposal is *sent* and within its validity; after acceptance it shows the signed copy.
* A contract is not edited; changes to scope and value arrive through change orders (Phase E, §11).

---

# Phase B+ — Projects in depth (and the open ends of A and B)

Source: the projects comparison (Procore, Buildertrend, Houzz Pro, Powerplay / Onsite) agreed with the owner, requirements §1, §3.4, §4, §15 and §18. Delivered in blocks, each tested, checked in the browser and committed. Covered by [backend/tests/test_projects_plus.py](backend/tests/test_projects_plus.py) (block 1) and [backend/tests/test_projects_depth.py](backend/tests/test_projects_depth.py) (blocks 2–4).

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Project notifications, scheduled project reminders, compliance expiry alerts, forgot password by email, change my own password, sessions signed out after a password change, real two-factor for Super Admin | **Done** |
| 2 | Stage closing rules (checklist, client sign-off, Owner override), task checklists, comments with @mention, task files and photos, priority | **Done** |
| 3 | Project timeline with filters, baseline vs actual with a reason for each delay, start-to-start / finish-to-finish / lag, working days and holidays, moving dependent tasks, drag-to-edit Gantt | **Done** |
| 4 | Meetings and minutes (action items become tasks, minutes emailed), project health score, finish forecast, "waiting on whom" (also in the client portal) | **Done** |

## B+1. Notifications, password and two-factor
| Area | Implementation | Test |
|---|---|---|
| Who is told (projects) | Every stage / task / milestone write goes through `save_stages`, which compares before and after (`services/project_events.py`). **Task assigned** → the new assignee (not again when the same task is edited). **Task blocked** → the project's managers (team members with the Project Manager role; none → the Owners), with the reason. **Stage complete** (its last task done) → managers + Owners, once. **Milestone achieved** → managers + Owners. **Added to a project** → that staff user, with role and access. **Issue raised** → the issue's owner; high severity also the managers. Nobody is told about their own action | each rule; not twice; not the actor |
| Scheduled (worker) | Planning / active projects only. **Due tomorrow** → assignee. **Overdue** → assignee; **3+ days overdue** → managers too, naming the assignee. **Milestone past its date** → managers. Keys carry the date, so a rescheduled task or milestone is reminded again for its new date; done tasks are never chased | each; no duplicates; reschedule; on-hold project quiet |
| Compliance expiry | Contacts' insurance, licences, certificates: **30 days** and **7 days** before expiry and **once expired** → Owners + Procurement, linking to the contact. A renewed document (new expiry) starts again. (Also fixed: a contact with one document without an expiry date was skipped by the check and by the Home count) | each mark; renewal; no duplicates |
| Settings | Notification settings grouped under *Leads & sales*, *Projects*, *Contacts*. Critical (always on): added to a project, task assigned, compliance expired | groups; critical cannot be switched off |
| Forgot password | Sign-in → *Forgot password?* → email. Always the same answer (nobody can find out which emails have an account) and the email is sent in the background (same reply time). The link works **60 minutes, once**; only a hash of it is stored; at most **3 links per user per hour**; using one cancels the others. No company email set up → the answer says to ask the Owner (Users → reset). Deactivated users get no link | each case |
| Change my own password | User menu (staff) / top bar (portal) → *Change password*: current + new twice (≥ 6, not the same as now). Returns a new session for this device | wrong current, short, same, ok |
| Sessions after a password change | Tokens carry the time they were issued (ms). Any session issued before the last password change (reset link, own change, Owner reset) is refused with "Your password was changed. Sign in again", shown on the sign-in page | other devices signed out; this one carries on |
| Audit | Password changes are logged as *changed* — never the value or its hash (25 older rows masked by migration 009) | no hash anywhere |
| Super Admin two-factor | Real authenticator codes (RFC 6238: Google / Microsoft Authenticator, Authy, 1Password). First sign-in (and after a reset): the password step returns a key + QR code; the first code confirms it. Codes are 6 digits / 30 s, one step of clock drift allowed, a code cannot be used twice. **5 wrong passwords or codes → locked 15 minutes** (logged). The platform Owner can *Reset two-factor* for a member (lost phone); nobody can change their own access. Secrets are never returned by any endpoint. The demo code `123456` is gone (migration 009) | set-up, confirm, replay refused, lock, reset, no secret in /sa/me or /sa/team |
| nginx | `/api` is resolved through Docker's DNS every 10 s, so a restarted backend is found without restarting nginx (before: 502s until nginx restarted, which also left forms blank). `index.html` is never cached | — |

## B+2. Closing a stage, task depth
| Area | Implementation | Test |
|---|---|---|
| Stage gate | Every stage closes through its **“<stage> complete” milestone** (the gate; contract payment rows hang on it). It closes only when every task is done (no tasks → progress 100 %), every **closing check** is ticked, the **client’s sign-off** is recorded (when the stage needs it) and no **high-severity issue** on that stage is open. The refusal lists exactly what is missing. The **Owner** may close anyway with a reason (kept on the timeline); nobody else can. A closed stage’s checklist and sign-off are locked until it is reopened | each rule; override owner-only; lock |
| Closing checklist | Defaults per service — Architecture: drawings issued, client comments addressed (+ client sign-off). Construction: quality inspection passed, site photos uploaded, snags closed. Interior: items installed as selected, client walk-through, snags closed (+ client sign-off). Editable per template stage (Settings → Stage templates: one check per line + “needs the client’s sign-off”) and per stage on the project. Open stages of existing projects got the defaults (migration 010) | defaults; template → new project; duplicates refused |
| Client sign-off | Recorded by staff: who, how (in person / email / WhatsApp / phone / signed document), date, note; managers are told. Removable while the stage is open | method required; notified |
| Task checklist | Steps inside a task, ticked by editors or the assignee (who may also add steps). Progress follows the ticks; a task is done only when every step is ticked; a new open step reopens a done task | each |
| Priority | Low / normal / high / urgent, shown on the task row | invalid refused |
| Comments & @mentions | Any staff member on the project comments on a task. **@Name** of a team member (the “@ Mention” button inserts it) notifies them; the assignee is told about every comment; nobody about their own. Delete: author or Owner | mention, assignee, author, outsider 404 |
| Task files & photos | Upload and attach with a caption (editors and the assignee); remove: uploader or editor (the stored file is deleted too) | each |
| Timeline entries | Every change above, plus task / stage / milestone changes, team and issues, is written to the project timeline | — |

## B+3. Plan, delays, timeline
| Area | Implementation | Test |
|---|---|---|
| Working days & holidays | Settings → Branches, tax & numbering → *Working days & holidays* (default Monday–Saturday). Lags, moving dependent tasks, delay days and the forecast count working days only | weekends and holidays skipped |
| Dependency types | Finish → start (FS), start → start (SS), finish → finish (FF), each with a lag in working days. FS: cannot start until the other finishes; SS: cannot start until the other started; FF: cannot finish until the other finished. Dates that break a link are flagged. Older tasks keep working as FS | each type; lag; refusals |
| Baseline | *Set baseline* freezes today’s dates as the agreed plan (later baselines are kept too). Every task and stage shows its slip in working days; the project shows how far its planned finish is from the baseline | slip values |
| Delay reasons | Once a baseline exists, moving a task, stage or milestone **later** asks *why* (client change / decision / payment, authority, consultant, material, subcontractor, labour, our planning, rework, weather, site condition, other). Each is kept as a delay with **who caused it** and the working days; the overview totals the days lost per party | refused without a reason; recorded; totals |
| Move dependents | When a task moves, the tasks that depend on it (and theirs) can move by the same number of working days — asked after a drag | dates shifted |
| Drag-to-edit Gantt | Timeline tab: drag a task bar to move it, drag its right edge to change the end; a live label shows the new dates; the baseline is a grey line under each bar | browser |
| Project timeline | *Activity* tab: every change newest first; filters Tasks · Stages & milestones · Schedule & delays · Team · Issues · Comments & files · Meetings · Edits. The field-level audit stays under *Audit log* | filters; unknown filter 400 |

## B+4. Meetings, health, waiting on whom
| Area | Implementation | Test |
|---|---|---|
| Meetings | Plan (title, date/time, place, staff from the team, contacts, agenda) → staff attendees told; moved → told again; reminder in the last 2 hours. Minutes: notes, decisions, actions (text, owner on the team, stage, due date). **Publish**: each action becomes a task (assigned, dated, “From the meeting …”), the minutes are emailed to every attendee with an email (result kept per address), staff are told. Published minutes are locked; only the Owner deletes them | each |
| Waiting on whom | Blocking a task asks who it waits on (client, architect / consultant, vendor, subcontractor, authority, our team + optional contact and note). Issues can wait on a party too. A stage whose work is done but lacks the client’s sign-off waits on the client. Per project (overview) with days waiting and totals per party; across projects `GET /waiting?party=`; the **client portal shows “Waiting on you”** (client items only) | each source; portal |
| Health score | Six parts out of 100, each with its reason: work on time (25), forecast finish (15), open issues (15), blocked / waiting (15), kept up to date (15), budget (15, full until costs are recorded in Phase E). Green ≥ 75 on track, amber 50–74 at risk, red < 50 off track. On the overview, the projects list and Home (*Projects at risk*). The managers and Owners are told once when a project turns red | parts sum; red; list; home; notified once |
| Finish forecast | Per stage, at the pace kept so far (progress per working day since it started): forecast finish and working days late; a stage that should have started with 0 % needs its full length from today. The project forecast is the latest stage forecast, said in plain words (“At the current pace Foundation finishes 9 working days late”) | late stage |
| Times | Meeting times go to the server in UTC and show in the viewer’s local time, like site visits; emailed and notified times are labelled UTC | browser |

---

# Phase E — Costs, invoices & change orders

Source: requirements §12 (finance: costs per stage with budget control, invoices, payments, "learn from it"), §11 (change orders), §4.7 (budget vs actual on the project dashboard), §5 (contract with a payment schedule tied to milestones — invoicing against it), §16 (payment reminders), §1 (tax, numbering, cost hiding). No separate requirements file is in the repository; section numbers follow the ones this plan and the parked drafts already use, and lines marked *(to confirm)* need the owner's word. Builds on the signed contract and payment schedule (Phase D), stage budgets and the dashboard (Phase B), the health score (B+4), lead receipts and the rate library (C+). Covered by `backend/tests/test_phase_e.py`.

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Cost entries (stage, category, vendor, bill files, approval), stage spent and 80 % / 100 % alerts, dashboard budget vs actual, health budget part, rate library actuals | **Done** |
| 2 | Invoices from payment-schedule rows (milestone achieved → due), manual invoices, tax, numbering, print, send by email | **Done** |
| 3 | Receipts against invoices, lead advances applied, overdue reminders and escalation, receivables | **Done** |
| 4 | Change orders (request → price → client approval → contract, schedule, stage budget and dates), finance reports, Finance + Change orders screens leave SOON | **Done** |

## E1. Requirement → implementation → test
| § | Requirement | Implementation | Test |
|---|---|---|---|
| §12 | Record every cost against the project and stage | `costs` {project, stage, category (material, labour, subcontract, equipment, transport, consultant, site expense, other), vendor contact (types supplier / subcontractor / contractor / consultant), date, amount, tax, description, qty + unit, rate-library item, bill number, files (via `/uploads`, kept in `files` and counted in the storage quota)}. Written by roles with `finance: rw`; a project editor without finance (Site Supervisor) may log a **site expense** up to a company limit, which always waits for approval | unknown stage / vendor 400; site over the limit 403; file listed in the quota |
| §12 | Cost approval | Status draft → submitted → approved / rejected (reason). Only **approved** costs count as actual. Approver: a Project Manager on the project or an Owner (same `MANAGER_ROLES`). A cost that takes a stage over its budget needs approval even from Accounts, with *why* (client change, our mistake, price rise) | over-budget cost waits; reason required; rejected not counted |
| §12 | Budget control per stage | Stage `spent` is recalculated from approved costs on every approve / void (reuse `later/services/budget.py` `stage_spent`, `recalc_stage`, `usage_level`). First crossing of **80 %** → project managers; **100 %** → managers + Owners (`notify.send`, keys per stage and level, so no repeats) | each level once; void drops the level back |
| §12 | Over budget because the client changed something → client pays | Approving such a cost with reason *client change* offers a **draft change order** for the overspend plus the company's overspend markup (draft `_overspend_change_order`), never sent automatically | draft CO created, status draft |
| §4.7 | Dashboard: budget vs actual | `GET /projects/<id>/dashboard` already sums approved `costs`; it now also returns per-stage budget / spent / % / level and committed (submitted) costs. Hidden for `HIDE_COST_ROLES` exactly as today | numbers per stage; site response has none |
| B+4 | Health score — budget part | `project_health.health` part 6 starts counting as soon as the first approved cost exists (today it says "recorded from the Finance phase"); the wording changes to *No costs recorded yet* | 0 / 7 / 15 points cases |
| §12 | "Learn from it": real costs update the rate library | A cost with a rate item and qty stores the actual unit rate on that `rate_library` item (`actuals` last 10, `last_actual`, `suggested_rate` = average). The rate is **not** overwritten; Settings → Rate library shows the suggestion and *Use suggested rate* (estimator / owner) | suggestion after 3 costs; rate unchanged until accepted |
| §5 / §12 | Invoice from a payment-schedule row | The contract view (`present_contract`) already marks a row *due* on signing, on its date or when its milestone is achieved. **Raise invoice** on a due row creates the invoice for that row's amount; the row gets `status: invoiced` + `invoice_id`, then `paid` when settled. A row can be invoiced only once; *upcoming* rows need an Owner override with a reason | not-due row refused; second invoice 409; row status follows |
| §12 | Other invoices | Manual invoice (lines, qty, rate) for extras; **change-order invoice** from an approved CO; credit note against an invoice. No progress-% claims in this phase *(to confirm)* | credit note cannot exceed the invoice |
| §1 | Tax | Invoice lines are taxable at the company tax rate and label (Settings) unless set per line. A schedule-row invoice splits the row amount into taxable and tax in the contract's own ratio (`contract.totals`, the contract value includes tax), so the row amounts still add up to the contract | row invoice taxable + tax = row amount |
| §1 | Numbering | `t.next_number("INV", "INV")`, credit notes `CRN`, change orders `CO`, receipts reuse `RCT` (same counter as lead receipts); formats editable in Settings → Branches, tax & numbering alongside `PRJ` | format applied; counters per company |
| §12 | Receipts against invoices | `receipts` {invoice allocations[], amount, date, mode, reference — same rules as `check_receipt` in `lead_money.py`}. One receipt may settle several invoices; an invoice may take several receipts; status sent → part paid → paid. Lead receipts moved on a win (`lead_receipts.project_id`) show as **advance received** and can be applied to the first invoice (normally *Advance on signing*) | over-allocation 400; part paid; advance applied once |
| §16 | Overdue invoices: reminders | Worker `check_invoices`: 3 days before due → Accounts; due today; 1 day overdue → Accounts + the project's managers; 7 days → Owners. Keys carry the due date, so a re-dated invoice is chased again; paid / void invoices never. Optional client email reminder through the company SMTP | each mark once; paid quiet |
| §11 | Change order request | `change_orders` {project, stage, task(s), title, description, reason (client request, design change, site condition, authority, our error), raised by, files}. Status draft → priced → sent to client → approved / rejected / withdrawn | flow order enforced |
| §11 | Price the change | Lines from the rate library or typed: cost (internal) and price (client), markup, tax; time impact in **working days** (`services/workdays.py`). Cost lines hidden for `HIDE_COST_ROLES` | site sees price, not cost |
| §11 | Client approval | Recorded by staff for now: who, how (in person / email / WhatsApp / signed document), date, file — same shape as the stage sign-off. Portal approval is Phase G. *Our error* changes are approved internally by an Owner (no client price, cost only) | method required; our-error needs Owner |
| §11 | Approved change updates the contract and plan | Contract gets `change_orders[]` and `revised_value` (the signed `value` and signature are never edited — D2 rule). A new payment-schedule row is added (*on approval* or *on a stage's completion*, chosen when pricing). Stage budget + cost impact. Time impact moves the stage's tasks and their dependents by working days through `save_stages`, recorded as a **delay** with reason *client change* when a baseline exists. Optional new tasks on the stage. Project value = revised value | contract revised; dates moved; delay logged; signed copy unchanged |
| §12 | Reports | Per project: contract → revised value, budget, committed, actual, invoiced, received, receivable, margin. Company: receivables ageing (0–30, 31–60, 61–90, 90+), cost by category / vendor, change orders by reason, budget overruns by stage. Reports area (`reports: r`) shows totals; cost and margin only to roles that can see costs | ageing buckets; margin hidden |

## E2. Rules fixed in this phase
* Only approved costs are *actual*; submitted ones are *committed*. Deleting an approved cost is replaced by **void** with a reason (Owner / Accounts), so the audit trail stays.
* An invoice is edited only as a draft. Once sent, changes go through a credit note. Void needs a reason and no receipts allocated.
* A payment-schedule row is invoiced once; its amount is fixed by the contract (or the change order that added it).
* The signed contract is never edited; change orders add to `revised_value` and the schedule.
* Cost fields added in this phase (`cost`, `spent`, `budget`, `margin`, `markup_pct`, vendor bill amounts) are added to `COST_FIELDS` and stripped for `HIDE_COST_ROLES`; invoices and receipts are never shown to Site Supervisor.
* Permissions use the existing areas: `finance` (costs, invoices, receipts — Owner, PM, Accounts rw; Designer, Procurement r) and `change_orders` (Owner, PM, Designer rw; Site, Accounts r). The NAV entries *Finance* and *Change orders* get `ready: true` and their routes.

## E3. What is added
| Kind | Items |
|---|---|
| Collections | `costs`, `invoices`, `receipts`, `change_orders` (+ `rate_library.actuals`, `contracts.change_orders` / `revised_value`, `payment_schedule[].status / invoice_id`). Migration `0xx_finance_indexes` (company + project + status / due date) |
| Endpoints | `GET/POST /projects/<id>/costs` · `PUT/POST /costs/<id>` (edit draft, `/submit`, `/approve`, `/reject`, `/void`) · `GET /finance/costs` (company list, filters) |
| | `POST /contracts/<id>/schedule/<row>/invoice` · `GET/POST /invoices` · `PUT /invoices/<id>` · `POST /invoices/<id>/send` · `/void` · `/credit-note` · `GET /invoices/<id>/print` |
| | `GET/POST /receipts` · `POST /receipts/<id>/void` · `POST /lead_receipts/<id>/apply` (advance → invoice) |
| | `GET/POST /projects/<id>/change_orders` · `PUT /change_orders/<id>` · `POST /change_orders/<id>/price` · `/send` · `/approve` · `/reject` · `/withdraw` · `POST /change_orders/<id>/invoice` |
| | `GET /projects/<id>/finance` (summary) · `GET /reports/finance` (ageing, categories, overruns) · `POST /rates/<id>/use-suggested` |
| Screens | Finance (Costs · Invoices · Receipts · Receivables tabs); project **Money** tab (budget vs actual per stage, costs, invoices, schedule with *Raise invoice*); Change orders list + editor; invoice print page; rate library suggestion column; Settings numbering for INV / CRN / CO |
| Worker | `check_invoices` (due / overdue / escalation), `check_change_orders` (sent and not answered in 3 days → PM). Both in `run_once` |
| Notifications | New `NOTIFY_EVENTS` under a *Finance* group: cost needs approval (critical), cost approved / rejected, stage 80 % / 100 % budget, invoice due / overdue, receipt recorded, CO needs approval, CO approved / rejected |
| Test file | `backend/tests/test_phase_e.py` (keeps `test_auth.py`, `test_phase_d.py`, `test_projects_depth.py` green) |

### What the parked drafts give (`backend/later/`)
| Draft | Reuse | Change needed |
|---|---|---|
| `services/budget.py` | `stage_spent`, `usage_level`, `recalc_stage`, `variance`, `project_financials` almost as they are | contracts are `status: "signed"` (draft looks for `"active"`); notify through `services/notify.send`, not `t.notify(role=…)` |
| `routes/finance.py` | Cost approval flow, over-budget reason, rate-library learning, `record_payment`, schedule invoicing idea | Uses `register_crud` / `..crud` and `services/pricing.py`, which are not in `app/` — rewrite as plain routes; schedule rows are `name / pct / amount`, not `label / percent`; reminders become worker notifications, not auto follow-ups |
| `routes/delivery.py` change orders | `apply_change_order` (contract + stage budget + date shift) | Shift dates with working days and `save_stages`, log delays, never overwrite `contract.value` |
| `services/pricing.py` `invoice_totals` | Totals / paid / status math | Check against the proposal `compute` tax rounding |
| Retention, progress claims, pay links, timesheets | Not in this phase (below) | — |

## E4. Not in this phase (and where it goes)
| Item | Where |
|---|---|
| Procurement: purchase requests, quotes, purchase orders, deliveries, three-way match (`later/routes/delivery.py`) | **Recommend its own phase after F** (Procurement area, NAV *Procurement*). In E a vendor bill is entered as a cost with the vendor and bill number; E keeps `costs.po_id` empty so POs can link later |
| Online payment links (Razorpay / Stripe) and paying from the portal | Phase G (portal) with a payment-provider integration |
| Client approves change orders in the portal | Phase G (E records the client's approval by staff) |
| Retention and its release, progress-% claims | *(to confirm)* — common in construction contracts; parked draft has both; add after E if the owner wants them |
| Accounting export (Tally / QuickBooks / Zoho Books) | Integrations *(to confirm §15)*; E gives CSV exports of invoices, receipts and costs |
| Timesheets / labour cost from hours | *(to confirm)*; labour is entered as a cost in E |
| Product deposits before ordering | Phase F selections + procurement phase |

Decisions taken to start building (the owner can change any of them; each is one setting or one rule):
1. **Pre-sales lead expenses** stay the cost of winning the lead; they are not project cost.
2. **Retention and progress-% claims** are not in Phase E.
3. **Site expenses**: limit 5,000 per entry (Settings → Branches, tax & numbering → Costs); every one waits for the PM; the Site Supervisor sees only their own entries and never the stage budgets.
4. **Upcoming schedule rows** can be invoiced early only by the Owner, with a reason.
5. **Tax**: one company tax rate and label, as on proposals.

Block 1 notes: a cost is recorded on the project's **Money** tab (Owner, PM, Accounts; Site Supervisor for site expenses); the company list is **Finance**. A project with approved costs cannot be deleted until they are voided. Cost entries appear in the project timeline under *Money* only for roles that can see finance.

Block 2 notes: a draft invoice has no number; **sending** issues the next INV number (formats for INV and CRN sit next to PRJ in Settings), so deleted drafts leave no gaps. The contract's payment schedule and *Raise invoice* are on the project's Money tab; an advance invoiced before the win joins the project when the lead is won. Printing is the invoice page (`/app/invoices/<id>`) with the browser's print, not a separate print endpoint. A project with sent invoices cannot be deleted.

Block 3 notes: a receipt must be allocated in full to open invoices of its project (no unallocated money on account yet). A lead advance is applied whole to one invoice and then cannot be voided on the lead. Voiding a receipt takes the money back off its invoices and the contract payment returns to *invoiced*. Receivables (Finance) age the unpaid balance by days past due. The optional client email reminder is not built yet.

Block 4 notes: a change order is numbered CO on creation (format in Settings with PRJ / INV / CRN). Editing a priced order sends it back to draft. With a signed contract an approved change becomes a payment-schedule row (due on approval, or when its stage's gate milestone is achieved) and is invoiced from the schedule with its own tax; without a contract it is invoiced directly. The time impact moves the stage's open tasks and everything that depends on them; once a baseline exists it is logged as a *client change* delay. Adding new tasks from a change order is not built (add them on the stage). Reports: project money on Reports (totals for anyone with Reports; budget, actual and margin only for roles that see finance) and a money summary on the project's Money tab.

**Phase E is complete.**

---

# Phase F — Documents, selections & site reports

Source: requirements for documents & drawings, selections and site reports *(section numbers to confirm — the parked draft `later/routes/delivery.py` cites "sections 6–11")*, §4.1 / B+2 (stage closing checks such as *Drawings issued to the client* and *Site photos uploaded*, client sign-off), §13 (portal users see their projects), §12 (selections cost ties to Phase E). Builds on the `files` collection, `/uploads` and the storage quota (`admin.py`), lead files handed over on a win (*From the lead*), project issues and the delay log (B+3). Client choices and approvals in the portal are Phase G; here staff record them. Covered by `backend/tests/test_phase_f.py`.

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Document library: folders, upload, versions / revisions, lead files shown in the library, permissions, quota | **Done** |
| 2 | Drawing register, revision status, transmittals (issue to client / consultant, by email), stage checks ticked from issued drawings | **Done** |
| 3 | Selections: rooms, options, allowance vs chosen cost, client choice recorded by staff, link to Phase E cost and change orders | **Done** |
| 4 | Daily site reports: weather, manpower, work done, photos, issues → project issues, delays → delay log; portal read-only view; Documents, Selections, Site reports leave SOON | **Done** |

## F1. Requirement → implementation → test
| § | Requirement | Implementation | Test |
|---|---|---|---|
| (to confirm) | Document library per project with folders | `documents` {project, folder, name, kind (drawing, specification, contract, approval / permit, report, photo, other), stage, room, tags, current version}. Default folders per service (Architecture: Concept, Drawings, Approvals; Construction: Structural, MEP, Site photos; Interior: Layouts, 3D views, Selections; all: Contract, Client documents, From the lead), editable in Settings. Files through `/uploads` (same type list, 20 MB / 100 MB video limits and the storage quota) | unknown folder 400; quota 402 |
| (to confirm) | Versions / revisions | Uploading over a document adds a version {rev (R0, R1… or company format), file key, note, by, at}; the latest is current, older ones stay downloadable. Removing a version deletes its stored file (as task files do) | revisions kept; old file served; delete frees quota |
| C+3 | Lead files and task files appear in one place | The library lists `lead_files` with `project_id` (folder *From the lead*, read-only there) and task files from B+2 (folder *Task files*) without copying them, so nothing is stored twice | lead file listed once; quota unchanged |
| (to confirm) | Drawing register | Documents of kind *drawing* carry a number (e.g. `A-101`), title, discipline, scale, and a status per revision: work in progress → for comment → for approval → approved / for construction → superseded. The register lists every drawing with its current revision and status and the date last issued | status flow; superseded on a new rev |
| (to confirm) | Transmittals | `transmittals` {number via `t.next_number("TRN", "TRN")`, project, to (contacts on the project team), purpose (for information, for comment, for approval, for construction), documents + revisions, note, sent by email (result per address, like meeting minutes), acknowledged (date, by — recorded by staff)}. The document shows where each revision was sent | number; email result kept; rev locked once sent |
| B+2 | Stage checks *Drawings issued to the client* / *Site photos uploaded* | When a transmittal to the client contains drawings of a stage, that stage's *Drawings issued to the client* check is offered as ticked (with a link to the transmittal); a site report or photo document on a construction stage offers *Site photos uploaded*. Still a tick by an editor, never automatic, so the Owner override rules of B+2 stay the same | offered after transmittal; not ticked without an editor |
| (to confirm) | Selections: options per item | `selections` {project, room, item (e.g. *Kitchen countertop*), stage, allowance, options[] {name, brand, code, supplier contact, photo / file, qty, unit, cost (internal), price (client), lead time}, chosen option, status open → options sent → chosen → confirmed → ordered → installed, due date (from the stage start minus lead time)}. Options may be picked from the rate library (`kind: product`) | status order; option from rate item |
| §12 | Allowance vs chosen cost | Each item shows allowance, chosen price and the difference; the project total of differences is shown on the Selections tab. When the confirmed choice is over the allowance, *Create change order* fills a Phase E change order with the difference (and under allowance a credit line). Confirming a choice can create a submitted cost in Phase E when the item is bought *(to confirm: on confirm or on order)* | difference math; CO prefilled; cost hidden for site / portal |
| (to confirm) | Client choice workflow | Staff send the options to the client (email with a summary, logged), then record the client's choice: who, how (in person / email / WhatsApp / phone / signed document), date, note — the same shape as the stage sign-off. A choice not made by its due date notifies the PM and shows as *Waiting on client* in the B+4 waiting list (and in the portal's *Waiting on you*). Changing a confirmed choice needs a reason and reopens the item | method required; overdue → waiting; reopen needs reason |
| B+2 | Interior check *Items installed as per the selection* | Offered as ticked when every selection of that stage is *installed* | offered; not forced |
| (to confirm) | Daily site report | `site_reports` {project, date (one per project per day; edit until the next day, then locked except for the Owner), weather (clear / cloudy / rain / heavy rain / extreme heat + note), manpower rows (trade, own / subcontractor contact, count), equipment, work done per stage / task with progress note, materials received, visitors, photos (via `/uploads`), issues, delays, safety incidents, author}. Written by roles with `site: rw` on projects they are on | second report same day 409; locked after a day; outsider 404 |
| B+1 / B+4 | Issues raised in the report → project issues | Each issue line can become a project issue (severity, stage, owner, waiting on whom) through the existing `/projects/<id>/issues` logic, so the B+1 notifications and the stage gate's high-severity rule apply | issue created + notified; stage gate blocked |
| B+3 | Delays in the report → delay log | A delay line {reason from `DELAY_REASONS`, stage / task, working days, note} is written to `project_delays` with the report as source; it does not move dates by itself (moving stays in the plan, B+3) — the PM is told to review the plan | delay row with source; dates unchanged |
| B+1 | Missing reports | Worker: no report by the company's cut-off time on a working day (`services/workdays.py`) for an active project with a site supervisor → that supervisor; next day → the project's managers | working days only; on-hold quiet |
| §13 | Portal (read only in F) | `GET /portal/projects/<id>` adds documents shared with the client (only revisions sent by transmittal or marked *shared*), selections with options and prices (never cost), and site report photos the PM marks as shareable. Approving and commenting stays for Phase G | client sees shared only; no cost fields |

## F2. Rules fixed in this phase
* Every file still goes through `/uploads` and the `files` collection; the storage quota counts each stored file once, wherever it is listed.
* A revision that was sent in a transmittal cannot be deleted; a new revision supersedes it.
* Selection cost and supplier price are cost fields (added to `COST_FIELDS`); clients and site staff see only the client price and the difference against the allowance.
* A site report records issues and delays; it never changes the plan dates or closes a stage by itself.
* Permissions use the existing areas: `documents` (Owner, PM, Designer rw; Sales, Site r), `selections` (Owner, PM, Designer rw; Procurement r) and `site` (Owner, PM, Site rw). Project membership rules of Phase B still apply (only projects you are on). The NAV entries *Documents & drawings*, *Selections* and *Site reports* get `ready: true` and their routes; each also appears as a project tab.

## F3. What is added
| Kind | Items |
|---|---|
| Collections | `documents` (with `versions[]`), `document_folders` (company defaults), `transmittals`, `selections`, `site_reports`. Migration `0xx_documents_site` (indexes; default folders per company) |
| Endpoints | `GET/POST /projects/<id>/documents` · `PUT/DELETE /documents/<id>` · `POST /documents/<id>/versions` · `DELETE /documents/<id>/versions/<rev>` · `PUT /documents/<id>/status` |
| | `GET /projects/<id>/drawing-register` · `GET/POST /projects/<id>/transmittals` · `POST /transmittals/<id>/acknowledge` |
| | `GET/POST /projects/<id>/selections` · `PUT/DELETE /selections/<id>` · `POST /selections/<id>/send` · `/choice` · `/reopen` · `/status` · `/change-order` |
| | `GET/POST /projects/<id>/site-reports` · `GET/PUT /site-reports/<id>` · `POST /site-reports/<id>/issues` · `/delays` · `GET /site-reports` (company, by date) |
| | `GET /portal/projects/<id>/documents` · `/selections` · `/photos` (read only) |
| Screens | Documents & drawings (folder tree, versions, drawing register, transmittals); project tabs Documents · Selections · Site reports; selection item editor with options side by side; daily report form usable on a phone (photos from the camera); Settings → document folders, report cut-off time; portal project page sections |
| Worker | `check_site_reports` (missing report), `check_selections` (choice due in 3 days, overdue → waiting on client), `check_transmittals` (for approval / for comment not acknowledged in 7 days → sender) |
| Notifications | *Documents & site* group: transmittal sent, drawing approved, selection choice due / overdue, client choice recorded, site report missing, issue / delay from a site report |
| Test file | `backend/tests/test_phase_f.py` |

### What the parked drafts give (`backend/later/`)
| Draft | Reuse | Change needed |
|---|---|---|
| `routes/delivery.py` documents | Revision list R0, R1…; a new revision clears the approval; transmit idea; comment thread | Rewrite without `register_crud`; transmittal becomes its own record; approvals move to Phase G |
| `routes/delivery.py` selections | Allowance / over-allowance math, status flow, product swap resets the choice, margin report | Options per item instead of one product; use the rate library instead of a separate `products` collection *(to confirm)*; ordering moves to the procurement phase |
| `routes/delivery.py` site reports / snags | Field list (date, labour count, photos, author) | Manpower per trade, weather, issues / delays links, one per day |
| `routes/portal.py` selection / document decisions | Shape of the portal endpoints | Phase G |

## F4. Not in this phase (and where it goes)
| Item | Where |
|---|---|
| Client approves drawings, comments on documents, picks a selection in the portal | Phase G (F records it by staff and shows read-only in the portal) |
| Sending transmittals / reports by WhatsApp | Phase G (F emails through the company SMTP) |
| Ordering selections, purchase orders, deliveries | Procurement phase (recommended after F) |
| Drawing markup / viewer for DWG and PDF annotations | Later *(to confirm)*; F stores and serves files as today |
| Snag / punch list as its own module | *(to confirm)* — recommend project issues with `kind: snag` so the stage check *Snags for this stage closed* can be offered from it |
| 360° renders and design options (parked draft) | *(to confirm)* — Interior design phase, after G |
| Product library separate from the rate library | *(to confirm)*; F uses the rate library `product` kind |

Decisions taken to start building (the owner can change any of them):
1. **Revisions** are named R0, R1, R2… (a company format can come later).
2. **A selection becomes a Phase E cost when it is ordered** (submitted, so the stage budget sees it), not when the client confirms.
3. **Site reports** are due every working day by 19:00 on active projects that have a site supervisor (cut-off editable in Settings).
4. **Clients see only photos marked shareable** (and documents marked shared or issued to them).
5. **Selection options use the rate library's *product* items**; no separate product library.

Block 1–2 notes: the library lists lead files and task files in two automatic folders without copying them. Drawings need a number unique on the project; a new revision supersedes the older ones. A transmittal emails the current revisions as attachments to people on the project team and keeps the email result per person; issued revisions can never be deleted. Issuing drawings of a stage to the client marks that stage's *Drawings issued to the client* check as ready to tick (an editor still ticks it).

Block 3 notes: when no due date is given, a choice is due on the stage start minus the longest option lead time. Options can be picked from the rate library's *product* items. Ordering a selection records a submitted Phase E cost (only roles with finance write create it). Over the allowance, *Change order* drafts a Phase E change order for the difference (cost in the chosen option's ratio); within the allowance there is no credit line yet. A late choice is listed as waiting on the client and reminds the PM; when every selection of a stage is installed, its *Items installed as per the selection* check is offered.

Block 4 notes: a site report can be written for today or yesterday (older only by an Owner) and changed until the end of the next day. The cut-off is checked in the company's local time (UTC+5:30 by default). In the portal a document marked *shared* shows its current revision; otherwise the client sees the latest revision issued to them by transmittal. Photos appear in the portal only when marked for the client.

**Phase F is complete.**

---

# Phase G — Client portal approvals, messaging & online payments

Source: requirements §13 (client portal: portal users see their projects and approve; never costs), §11 (client approval of change orders), §12 (invoices and payments), §16 (email / SMS / WhatsApp templates with merge fields; today only *log as sent*), the inbox and WhatsApp drafts *(§17 — to confirm; the parked `later/routes/engage.py` cites "section 17")*, and every item earlier phases parked here: C (sending through a provider), C+ (WhatsApp / SMS sending), E (portal approval of change orders, online payment links), F (client approves drawings, comments on documents, picks a selection; transmittals by WhatsApp). Builds on what staff record today with one shape — who, how (`SIGNOFF_METHODS`), date, note, file — for the stage sign-off (`routes/project_work.py` `record_signoff`), change-order approval (`routes/change_orders.py` `approve_co` / `reject_co`), selection choice (`routes/selections.py` `record_choice`) and drawing status (`routes/documents.py` `drawing_status`, `acknowledge`); on the online signature of a proposal (Phase D, `routes/proposals.py` `public_accept` / `visitor()`); on the read-only portal of Phase F (`routes/projects.py` `portal_query` / `portal_project`, `routes/site_reports.py` portal endpoints); and on receipts (`routes/invoices.py` `apply_payment`). Covered by `backend/tests/test_phase_g.py`.

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Portal approvals: stage sign-off, change orders, selection choice, drawing approval, transmittal acknowledgement, consultant and client comments on documents; "Waiting on you" becomes actionable; PM notified | **Done** |
| 2 | Invoices and receipts in the portal; payment-provider interface; Razorpay (test mode first) pay links; webhook → receipt; provider keys in Settings | **Done** |
| 3 | Project message threads between each portal user and the team; staff **Inbox** (area `messages`) leaves SOON | **Done** |
| 4 | WhatsApp / SMS gateway: provider settings, opt-in, sending templates, transmittals, invoices and reminders; delivery status webhook; *log only* when not set up | **Done** |

## G1. Requirement → implementation → test
| § | Requirement | Implementation | Test |
|---|---|---|---|
| §13 | One approval path for staff and portal | The body of each staff action moves into a function that both routes call: `signoff_stage(p, stage, approval)` (from `record_signoff`), `decide_change_order(co, p, approval, approve)` (from `approve_co` / `reject_co`, still calling `apply_change`), `choose_option(s, p, opt, choice)` (from `record_choice`), `set_drawing_status(doc, p, st, by)` (from `drawing_status`). A portal approval records `method: "Portal"`, the portal user's name, contact id, time, IP and user agent (reuse `proposals.visitor()`). *Portal* is not offered to staff (`SIGNOFF_METHODS` unchanged for them) | same record either way; staff cannot pick *Portal*; IP and time kept |
| §13 | Who may do what in the portal | The project is found with `portal_query()` (team `contact_id`). The **project role** on the team decides: *Client* — sign-off, change orders, selections, drawings sent to them *for approval*, invoices, payments, messages. *Architect / Structural / MEP Consultant / Consultant* — comment on and return drawings sent to them *for comment* or *for approval*, acknowledge transmittals, messages. *Subcontractor / Supplier / Main Contractor* — acknowledge transmittals, see their own "waiting on you", messages; no money, no approvals. Every portal response keeps `HIDE_COST_ROLES` (`security.py`): prices only, never cost or margin | each role allowed / 403; other project 404; no cost fields |
| B+2 | Client signs off a stage | `POST /portal/projects/<id>/stages/<sid>/signoff`: only when the stage is open and the sign-off is the last thing missing or asked for (`signoff_required`); typed full name + "I approve" tick (+ optional note / file). Same notification as today (`signoff_recorded` → `ev.managers`) and timeline entry. Staff may still remove it while the stage is open | method Portal; closed stage 409; notified |
| §11 | Client approves or rejects a change order | Portal lists change orders with status *sent* (price, time impact in working days, files; never cost lines). **Approve** needs typed name + drawn signature (same check as `public_accept`: PNG data URL, `MAX_SIGNATURE`) because it changes the contract value; then `apply_change` runs exactly as for a staff approval (revised value, schedule row, dates, *client change* delay). **Reject** needs a reason. Both → `co_decided` to the raiser + managers. *Our error* orders never appear in the portal | signature required; contract revised once; reject reason; our-error hidden |
| §13 / F | Client picks a selection | Portal shows options with client price, photo and lead time (already read-only in `portal_selections`); **Choose** calls `choose_option` with method Portal; status open / options sent only (a recorded choice needs staff *reopen*, as today). Over the allowance the difference is shown before confirming; the change order is still drafted by staff (F rule) | over-allowance shown; second choice 409; `selection_chosen` sent |
| F | Client approves a drawing; consultants comment | Only on a revision sent by transmittal **to this contact** with purpose *for approval* (approve or *return with comments*) or *for comment* (comments only). Approve → `set_drawing_status(approved)` → `drawing_approved` notification. Comments: `document_comments` {document, rev, contact / user, side (client, consultant, team), text, file (marked-up PDF via `/uploads`), status open → answered → closed}. The team replies on the Documents tab; a comment can become a task (B+2 task comment pattern). A new revision lists the open comments of the previous one | not sent to you 404; superseded rev 409; comment → task |
| F | Acknowledge a transmittal | `POST /portal/transmittals/<id>/acknowledge` fills the same `acknowledged` record as staff (`documents.acknowledge`) with method Portal; stops the `check_transmittals` reminder | ack once; reminder quiet |
| B+4 | "Waiting on you" becomes actionable | `project_health.waiting` rows already carry `kind` (task, signoff, selection, issue), `ref` and `contact`. Add kinds *change_order* (sent), *drawing* (for approval / comment to this contact), *transmittal* (not acknowledged), *invoice* (due). The portal filters rows by the user's contact (clients also get party *client*) and each row opens its action; information-only rows (blocked task, issue) open a message to the team | rows per contact; action link per kind |
| §12 | Invoices and receipts visible to the client | `GET /portal/projects/<id>/invoices`: sent / part paid / paid invoices and credit notes of the project (never drafts or void), balance, due date, the invoice page (same layout as `/app/invoices/<id>`) and receipts against them. Client role only | draft hidden; other client 404 |
| §12 | Pay online | `services/payments.py`: `create_link(company, invoice, amount)` → {provider, ref, url, expires}, `verify(company, headers, body)` → event, `fetch(company, ref)`. **Razorpay first** (INR, UPI / cards / net banking; Payment Links in test mode), Stripe behind the same interface later. `payment_links` {invoice, amount, provider, ref, url, status created → paid / expired / cancelled, events[]}. Portal **Pay** and the invoice email (`send_invoice`) carry the link. Amount = balance by default *(part payment — to confirm)* | link created; expired link refused; second link cancels the first |
| §12 | Payment → receipt | `POST /webhooks/payments/<provider>/<company>`: no login, provider signature checked (Razorpay HMAC of the body with the webhook secret), idempotent on the provider payment id. A *paid* event creates a receipt through `record_receipt(...)` (the body of `add_receipt`, so numbering `RCT`, allocation and `apply_payment` are the same) with mode *Online* (added to `PAYMENT_MODES`) and the provider reference; `receipt_recorded` → managers + Accounts; the client gets the receipt email | bad signature 400; replay no second receipt; invoice paid; schedule row paid |
| §12 | Provider keys per company | Settings → *Online payments*: provider, key id, key secret, webhook secret, test / live. Secrets masked on read like the SMTP password (`notifications.email_out`); audit row without values. Not set up → no Pay button | secret never returned; off → no link |
| §17 *(to confirm)* | Messages between client and team | `messages` (the collection `services/subscription.py` already counts) with `channel: portal`, one thread per project per portal contact, so a client never sees a subcontractor's thread {project, contact, side, author, text, files, at, read_by}. Portal: *Messages* on the project page. Staff: project **Messages** tab and **Inbox** (all threads of projects you are on, unread first), area `messages` from `ROLE_PERMS`; `nav.ts` Inbox gets `ready: true` | thread per contact; outsider 404; unread count |
| §15 | Who is told about portal actions | A portal message → the project's managers and the team members who already wrote in that thread; staff reply → the portal user by email (and WhatsApp when opted in, block 4). Every portal approval → managers (existing events), nobody about their own action | each; not the author |
| §16 | Send templates by WhatsApp / SMS | `services/messaging.py` gateway: `send(company, channel, to, text, template=None, params=None)` → {status, provider_id, error}. **One provider first: WhatsApp Cloud API (Meta)** *(Gupshup / Twilio as alternatives — to confirm)*; SMS second (India needs DLT-registered templates). `message_templates` (`routes/followups.py`) gain the provider template name and the order of merge fields; `render` stays the preview; **Send** replaces *log as sent* when a provider is set. Not set up → **log only**: the message is stored with status *logged (not sent)*, exactly today's behaviour | sent / logged; unknown field blocks sending |
| §16 | Opt-in | Contacts get `whatsapp_opt_in` {at, how (portal tick, written, verbal), by}; no opt-in → no WhatsApp (email still works). An inbound *STOP* records opt-out | refused without opt-in; STOP → out |
| F / E | Transmittals, invoices and reminders by WhatsApp | Transmittal send offers *also by WhatsApp* (template with a portal link, not the file); invoice send carries the pay link; worker reminders that today email the client (invoice due / overdue — the client reminder not built in E —, selection choice due, stage waiting for sign-off) go by WhatsApp when the contact opted in, once per key | link not attachment; reminder once |
| §16 | Delivery status | `POST /webhooks/messages/<provider>/<company>` (signature checked, e.g. Meta `X-Hub-Signature-256`) moves a message sent → delivered → read / failed with the error; a failed message to a client tells its sender | status flow; failed notified |
| — | Limits | WhatsApp messages per month from the plan (`subscription.limits()["whatsapp"]` + add-ons); over → 402 with the add-on hint (as the parked `_check_whatsapp_quota`). Logged-only messages do not count | 402 over limit |

## G2. Rules fixed in this phase
* A portal approval and a staff-recorded approval are the same record and run the same code; the only differences are `method: "Portal"`, the IP / user agent and who recorded it. Staff never record *Portal*.
* A portal user acts only on what was sent to them: their project (team contact), their transmittal, their thread. Anything else is 404, not 403.
* Approvals that change money or the contract (change orders) need a drawn signature; sign-off, selection choice and drawing approval need a typed name and a tick.
* An online payment becomes money only through the provider's signed webhook, never from the browser's return page. One provider payment makes one receipt.
* Secrets (payment keys, webhook secrets, messaging tokens) are written but never read back, as the SMTP password today.
* Nothing is sent by WhatsApp without opt-in; without a provider every send is *logged only*, so nothing breaks for companies that have not set one up.
* Cost fields stay hidden for every portal role (`HIDE_COST_ROLES`).

## G3. What is added
| Kind | Items |
|---|---|
| Collections | `document_comments`, `payment_links`, `messages` (portal, whatsapp, sms, email log; `thread_id`, `status`, `provider_id`), `webhook_events` (raw provider events, kept 90 days). Company `payment_settings`, `messaging_settings`; contact `whatsapp_opt_in`. Migration `020_portal_messaging` (indexes: messages company + thread + at, payment_links provider ref unique, webhook_events provider id unique) |
| Endpoints | `POST /portal/projects/<id>/stages/<sid>/signoff` · `GET /portal/projects/<id>/change_orders` · `POST /portal/change_orders/<id>/approve` · `/reject` |
| | `POST /portal/selections/<id>/choice` · `POST /portal/documents/<id>/approve` · `/return` · `GET/POST /portal/documents/<id>/comments` · `POST /portal/transmittals/<id>/acknowledge` · `GET /portal/waiting` |
| | `GET /portal/projects/<id>/invoices` · `GET /portal/invoices/<id>` · `POST /portal/invoices/<id>/pay` · `POST /webhooks/payments/<provider>/<company>` · `GET/PUT /settings/payments` |
| | `GET/POST /portal/projects/<id>/messages` · `GET /inbox` · `GET/POST /projects/<id>/messages` · `POST /messages/<thread>/read` · `GET/POST /documents/<id>/comments` (staff) |
| | `POST /message_templates/<id>/send` · `POST /transmittals/<id>/whatsapp` · `POST /invoices/<id>/whatsapp` · `PUT /contacts/<id>/opt-in` · `POST /webhooks/messages/<provider>/<company>` · `GET/PUT /settings/messaging` |
| Screens | Portal project page: *Waiting on you* with buttons, Approvals (sign-off, change orders with signature pad, selections side by side, drawings), Documents with comments, Invoices & payments, Messages. Staff: Inbox; project Messages tab; comments on the Documents tab; Settings → Online payments and Messaging (provider, keys, test button); opt-in on the contact; *Send* next to *Copy / Log as sent* on templates |
| Worker | `check_payment_links` (expire old links, re-check *created* links with `fetch` in case a webhook was missed), `check_portal_reminders` (client reminders by WhatsApp / email for sign-off, selection and invoice), `check_messages` (unanswered client message after 1 working day → managers). All in `run_once` |
| Notifications | *Portal & messages* group: client approved / rejected in the portal (reuse `signoff_recorded`, `co_decided`, `selection_chosen`, `drawing_approved`), document comment, transmittal acknowledged, new portal message (critical), online payment received (`receipt_recorded`), message failed |
| Test file | `backend/tests/test_phase_g.py` (provider calls faked; keeps `test_phase_e.py`, `test_phase_f.py` green) |

### What the parked drafts give (`backend/later/`)
| Draft | Reuse | Change needed |
|---|---|---|
| `routes/portal.py` decisions (`selection_decision`, `co_decision`, `doc_decision`, `doc_comment`) | Endpoint shape, `_stop_sequences` idea (a decision cancels its reminders) | Call the shared functions above instead of writing status directly; access by team contact (`portal_query`), not `client_id`; `notify.send`, not `t.notify(role=…)`; statuses are the F ones (*sent*, *for approval*) |
| `routes/portal.py` `pay` | Endpoint name | Simulated: becomes a provider link; money only via webhook and `record_receipt`, not `record_payment` |
| `routes/portal.py` `message` and `routes/engage.py` `log_message`, `inbox`, `inbound`, `_check_whatsapp_quota` | `messages` field list, inbox query, quota check, inbound webhook shape (Meta Cloud API) | Threads per project + contact; drop topic routing and the per-message cost guess *(routing — to confirm)*; real signature check |
| `routes/engage.py` morning messages, PM digest, trade handoff | Not in this phase (below) | — |
| `routes/portal.py` vendor purchase orders, design options | Not in this phase (below) | — |

## G4. Not in this phase (and where it goes)
| Item | Where |
|---|---|
| Vendor portal for purchase orders and delivery updates (`later/routes/portal.py` `vendor_pos`) | Procurement phase |
| WhatsApp for site workers (morning work messages, buttons, *work done*), PM digest (`later/routes/engage.py`) | *(to confirm)* — after G, on the same gateway |
| Inbound WhatsApp / SMS turned into threads or records | *(to confirm)* — G stores inbound messages from known numbers in the contact's thread only; topic routing later |
| Refunds and payment disputes | Staff void the receipt and refund outside the CRM; later *(to confirm)* |
| Stripe, second WhatsApp provider, email-to-thread replies | Behind the same interfaces when asked |
| Design options / 360° renders chosen in the portal | Interior design phase (F4) |
| Retention, progress-% claims paid online | With retention *(E4, to confirm)* |

Block 1–2 notes: portal approvals reuse the staff code (`signoff_stage`, `decide_change_order`, `choose_option`, `set_drawing_status`, `ack_transmittal`, `record_receipt`) and record method *Portal* with the IP. The portal's *For you to act on* lists what the person may do; a stage's sign-off is asked for only when it is the last thing missing. Consultants comment on or return drawings (returned → work in progress); the team replies on the Documents tab's Comments view, closes a comment or turns it into a task. Payments: Razorpay Payment Links, plus a **sandbox** provider (no network, no real money) for demos and tests whose checkout page calls the same signed webhook. A sent invoice email carries the pay link when payments are on; staff can copy a link from the Money tab.

Block 3–4 notes: threads are private per portal contact per project; the Inbox and the project's Messages tab show them unread first; a staff reply is emailed and, once the contact opted in, sent on WhatsApp. WhatsApp: Meta Cloud API plus a **sandbox** provider for demos and tests; not set up → messages are stored as *logged* and do not count against the plan. Opt-in is recorded per contact (staff, or the person in the portal); an inbound STOP opts out. Templates can be sent from a contact; transmittals and invoice sends can also go on WhatsApp (a portal or pay link, never the file). The worker reminds the client once of an overdue invoice and of a selection due in 3 days (decision 6). Inbound messages other than STOP are stored against the contact; routing them into a project thread is later.

**Phase G is complete.**

Decisions taken to start building (the owner can change any of them):
1. **Payments:** Razorpay first (test mode until live keys are entered), Stripe later behind the same interface. A client may pay part of an invoice online (any amount up to the balance). The company absorbs the gateway fee; nothing is added to the invoice.
2. **WhatsApp:** the Meta WhatsApp Cloud API directly; Gupshup / Twilio can be added behind the gateway. **SMS is not built in G** (India needs DLT-registered templates first); it stays *log only*.
3. **Signatures:** a drawn signature for change orders only; stage sign-off, selection choice and drawing approval take a typed full name and a tick.
4. **Consultants** comment on and return drawings; only the client approves.
5. **Threads:** one private thread per portal contact per project.
6. **Automatic client reminders** (email, and WhatsApp when opted in): invoice overdue (once, the day after the due date) and selection choice due (once, 3 days before). Others stay manual.

---

# Phase H — Procurement

Source: requirements for procurement *(section number to confirm — the parked `later/routes/delivery.py` and `later/routes/reports.py` `procurement()` are the only written source)*, §12 (budget control per stage, "learn from it"), §3.5 (vendors: tax IDs, bank details, compliance), and every item earlier phases parked here: E4 *Procurement: purchase requests, quotes, purchase orders, deliveries, three-way match (`later/routes/delivery.py`) — recommend its own phase after F*, with `costs.po_id` left empty so POs can link later (no code writes `po_id` today); E4 *Product deposits before ordering*; F4 *Ordering selections, purchase orders, deliveries — Procurement phase* and the F parked-draft note *ordering moves to the procurement phase*; F decision 2, which today makes a selection's *ordered* status record a submitted Phase E cost directly (`routes/selections.py` `move_status`); G4 *Vendor portal for purchase orders and delivery updates (`later/routes/portal.py` `vendor_pos`)*. Builds on the permission area `procurement` that exists since Phase A (`security.py` `ROLE_PERMS`: Owner, PM, Procurement rw; Estimator, Site, Accounts r) and the NAV entry *Procurement* (`core/nav.ts`, section Money, still SOON); vendor contacts (`defaults.py` `VENDOR_TYPES` supplier / subcontractor / contractor / consultant, bank details masked unless finance or procurement can edit — B, compliance documents checked by `worker.py` `check_compliance`); the rate library (`routes/lead_money.py` `/rates`, `RATE_KINDS` material / labour / product, actual rates stored by `routes/finance.py` `learn`); Phase E costs and stage budgets (`finance.py` `submit` / `approve_cost`, `services/budget.py` `over_budget`, `recalc_stage`, `stage_totals` committed vs spent); site reports (`routes/site_reports.py`, `materials` free text today); the Phase G portal pattern (`routes/portal_actions.py`, `site_reports.portal_project`, `projects.portal_query`) and gateway (`services/messaging.py` `notify_contact`). Covered by `backend/tests/test_phase_h.py`.

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Purchase requests (site, PM, selections), RFQs to several suppliers, quotes compared side by side, award → draft PO; PR / RFQ / PO / GRN numbering in Settings | **Done** |
| 2 | Purchase orders (from a quote or direct), commitment against the stage budget, approval above a limit or over budget, send by email (print page) and WhatsApp, amendments, cancel; selections *ordered* creates a PO instead of a cost | **Done** |
| 3 | Goods receipts (partial, photos, rejected / returned qty, link to the day's site report), vendor bills with three-way match and tolerance, bill → approved cost with `po_id`, payable status and vendor payments recorded | **Done** |
| 4 | Vendor portal (acknowledge PO, update delivery date, upload invoice), worker reminders, procurement reports, Procurement leaves SOON | **Done** |


Block 1–2 notes: Owner, Procurement and Accounts reach every project's procurement; others only projects they are on (404 otherwise). A Site Supervisor raises requests on their projects and never sees prices. The PO number is issued on approval. The approval limit is compared on the PO value **before tax**; above it an Owner approves, and a PO that takes a stage over budget (spent + committed + ordered) needs a project approver with an `OVERSPEND_REASONS` reason. A direct PO above the limit needs a reason. Sending carries the email and, when asked, WhatsApp in one call (no separate `/whatsapp`). An amendment that raises the total puts the PO back to draft for a new approval. Ordering a selection adds the chosen option to the supplier's open draft PO (or opens a request when it has no supplier) and records no cost. Suppliers with an expired compliance document are warned, not blocked. Editing a request or an RFQ after creating it (`PUT`) is not built: cancel and raise again.

Block 3–4 notes: returns are kept on the GRN (`returns[]`) rather than in a `supplier_returns` collection; reversing a whole GRN is not built (return the goods instead). Bills are matched against accepted, not yet billed qty and the rate and amount tolerances; a mismatch goes *on hold* and an Owner or Accounts accepts it with a reason, and its cost then goes through the usual cost approval. A supplier's portal invoice arrives as a *draft* bill that staff check. The supplier portal is one call (`GET /portal/purchase-orders` returns POs, bills and open RFQs); portal users upload through `POST /portal/uploads` (PDF or image only), since `/uploads` is staff only. Reminders count calendar days, not working days, and each fires once per date. The day's site report lists that day's deliveries (read only).

**Phase H is complete.**

## H1. Requirement → implementation → test
| § | Requirement | Implementation | Test |
|---|---|---|---|
| (to confirm) | Ask for material | `purchase_requests` {number `t.next_number("PR", "PR")`, project, stage, lines[] {rate-library item (`kind` material / product) or typed description, qty, unit, needed by}, delivery location (site / office), note, source (site, PM, selection), requested by, status open → quoting → ordered (all lines on POs) → closed / cancelled}. Raised by `procurement: rw` roles and by a **Site Supervisor on the project** (same exception as the site expense in `finance.py` `site_only`; never sees prices). New request → `pr_raised` to Procurement users (`notify.role_users("procurement")`) and the project's managers | site on another project 404; site sees no rates; notified |
| (to confirm) | Ask several suppliers for prices | `rfqs` {number `RFQ`, request(s), lines, suppliers[] (contacts of a `VENDOR_TYPES` type), due date, quotes[] {supplier, per-line rate, tax, delivery days, validity, terms, file via `/uploads`}}. Sent by email through the company SMTP (`notify.deliver`) and, when opted in, WhatsApp (`messaging.notify_contact`) with a portal link (block 4); a supplier with an expired compliance document is warned, not blocked *(to confirm)*. Quotes are typed in by staff (or by the supplier in the portal, block 4) | sent result per supplier; quote after due date allowed with a flag |
| (to confirm) | Compare quotes side by side | `GET /rfqs/<id>/compare`: one column per supplier, per-line rate, line and total amounts, tax, delivery days, and the **rate-library rate and last actual** (`rate_library.rate`, `last_actual`) so a high quote stands out. Lowest per line and lowest total marked. **Award** a whole quote or per line (split award) → one draft PO per awarded supplier; the reason is required when the lowest total is not chosen | split award makes two POs; reason required when not lowest |
| (to confirm) | Purchase order | `purchase_orders` {number `PO` (issued on approval, like INV on sending — no gaps from deleted drafts), project, supplier, lines[] {description, rate item, stage, qty, unit, `unit_cost`, tax, `cost`, selection id, request line}, delivery address and date, terms, source (rfq / direct / selection), status draft → waiting approval → approved → sent → acknowledged → part received → received → closed; cancelled}. A direct PO (no RFQ) needs a reason *(to confirm: below a value no reason)* | number on approval; status order enforced |
| §12 | A PO commits money against the stage budget | `budget.stage_totals` gains a third figure, **ordered**: approved PO line value not yet billed. `over_budget(p, stage, amount)` is called with the PO's stage totals (spent + committed + ordered) so a PO is checked before the money is spent. The project Money tab and dashboard show budget / ordered / committed / spent per stage; all of it stays a cost field for `HIDE_COST_ROLES` | ordered appears on approve, drops as bills are approved |
| §12 | PO approval | Company setting `po_approval_limit` in `finance.settings()` (default 50,000 *(to confirm)*, Settings → Finance next to `site_expense_limit`). At or below the limit and within the stage budget → approved on submit by Procurement / PM / Owner. Above the limit → Owner. Over a stage budget → a manager on the project (`finance.is_approver`) with a reason from `OVERSPEND_REASONS`, same notice as `cost_approval`. Reject needs a reason | each path; over budget needs reason; self-approval above limit 403 |
| (to confirm) | Send the PO | `GET /app/purchase-orders/<id>` print page (browser print, as invoices); **Send** emails it to the supplier contact (HTML body + the page as attachment if the PDF route exists, else a link) and, when opted in, WhatsApp via `messaging.notify_contact` with the portal link (never the file — G rule). Supplier acknowledgement recorded by staff (who, how `SIGNOFF_METHODS`, date) or in the portal | email result kept; WhatsApp logged when not set up |
| (to confirm) | Change a sent PO | Lines of a sent PO are changed only through an **amendment** (`revisions[]` rev 1, 2… with what changed and why); an increase goes through approval again; the supplier is sent the new revision. Cancel needs a reason and nothing received | amendment re-approves increase; cancel after receipt 409 |
| F | Selections ordered through a PO | `selections.move_status` to *ordered* no longer inserts a cost: it adds the chosen option (supplier, qty, `unit_cost`) to a draft PO for that supplier on the project (one open draft per supplier, like `later` `order_selections`), or opens a purchase request when the option has no supplier. The selection is *ordered* when its PO is sent and shows the PO number and expected date; a full receipt shows *received*. Costs already created by F stay as they are | no cost on order; PO line carries selection id; old costs untouched |
| E4 | Deposit before ordering | Not enforced in H; the PO shows the client's receipts on the project as a hint *(to confirm)* | — |
| (to confirm) | Goods received (GRN) | `goods_receipts` {number `GRN`, PO, date, lines[] {PO line, received qty, accepted qty, rejected qty + reason (damaged, wrong item, short, quality)}, photos (via `/uploads`, quota), delivery note / challan no., received by, site report id}. Recorded by Procurement, PM, Owner and **Site Supervisor on the project** (no prices shown). Received more than ordered is refused beyond a tolerance *(to confirm, default 5 %)*; PO moves to part received / received | over-receipt 400; partial status; site sees qty only |
| F | Deliveries in the site report | The day's site report lists that day's GRNs under *Materials received* (read only, linked) next to today's `materials` text; a GRN made from the report form is linked by `site_report_id` | GRN listed on the report; free text kept |
| (to confirm) | Returns and rejections | Rejected qty is never billable. **Return to supplier** {GRN lines, qty, reason, date, note} reduces accepted qty; the PO line is open again for a replacement or is short-closed by Procurement with a reason. Supplier told by email / WhatsApp | billable qty drops; short-close needs reason |
| E | Vendor bill and three-way match | `vendor_bills` {supplier, bill no. (unique per supplier), date, due date, PO, GRNs, lines {PO line, qty, rate, tax}, total, file, status draft → matched / on hold (mismatch) → approved → part paid → paid; void}. Match per line: billed qty ≤ accepted qty not yet billed; billed rate within `match_rate_tolerance_pct` of the PO rate; total within `match_amount_tolerance` *(defaults 1 % and 100 — to confirm)*. A mismatch shows the three columns (ordered / received / billed) and needs an Owner or Accounts override with a reason. Entered by roles with `finance: rw` or Procurement | over-billed qty held; within tolerance matched; override needs reason |
| §12 | Bill becomes the actual cost | Approving a matched bill writes one `costs` row per stage of its lines (category Material, or Subcontract for subcontractor / contractor vendors; vendor, `bill_no`, `po_id`, `bill_id`, files) and runs `finance.submit`: because the PO was already approved against the budget, a matched bill is approved straight away (no second budget question); an overridden mismatch stays *submitted* for the usual approver. `recalc_stage` and `learn` (actual rate per rate item) run as for any cost. A bill without a PO (small purchases) is still a plain Phase E cost | cost with `po_id`; stage spent up, ordered down; learn called |
| §12 | Payable and payments to vendors | Bill balance and due date give **payables** (Finance → Payables, ageing like receivables). `vendor_payments` {supplier, bills allocated, amount, date, mode (`PAYMENT_MODES`), reference, by} recorded by Accounts — the money moves outside the CRM. Bank details shown from the contact (masked rule of B) | over-allocation 400; bill paid; void returns balance |
| G4 | Vendor portal | A supplier portal user (`users.py` external role *vendor* → contact type supplier) sees only POs sent to their contact (`vendor_id == g.contact_id`; anything else 404, G rule): **Acknowledge**, **Update delivery date** (with note; a later date → `po_delivery_changed` to Procurement and the PM), **Upload invoice** (file + bill no., amount → a *draft* vendor bill for staff to match), RFQ **quote** entry, and their bills' payment status. Prices shown are **their own PO / quote prices only**; the portal presenter builds its own fields (`rate`, `amount`) from the PO lines and never returns `budget`, `spent`, stage totals, other suppliers' quotes or margin (`HIDE_COST_ROLES` still applied to the rest) | other supplier 404; own price visible; no budget fields |
| §16 | Reminders | Worker `check_procurement`: RFQ due tomorrow with suppliers not answered → Procurement; PO waiting approval > 1 working day → approver again, 3 → Owners; PO sent and not acknowledged in 2 working days → Procurement (+ supplier WhatsApp when opted in); delivery due tomorrow → site supervisor and Procurement; delivery late (expected date passed, not fully received) → Procurement + PM, 3 days → Owners; bill due in 3 days / overdue → Accounts. Keys carry the date, so a new date is chased again (`services/workdays.py` for working days) | each once; re-dated starts again; received quiet |
| §12 | Reports | Procurement area: spend by supplier (approved bills), PO status (open value by status / project), late deliveries (days late per supplier, on-time %), **price variance** (PO and bill rate vs rate-library rate per item, per supplier), open requests, payables ageing. Cost figures only to roles that see finance (`HIDE_COST_ROLES` for site) | variance math; late list; site sees no money |

## H2. Rules fixed in this phase
* A PO is a **commitment** (*ordered*), not actual cost. Only an approved vendor bill is actual; the cost row carries `po_id` and `bill_id`, so nothing is counted twice. A cost already linked to a bill cannot be edited on the Money tab; voiding the bill voids its cost.
* Budget is checked when money is committed (PO approval), not again when a matched bill arrives. A mismatch or a bill over the PO goes back through cost approval.
* An approved PO's lines change only by amendment; a sent PO, a GRN and an approved bill are never deleted, only cancelled / reversed / voided with a reason.
* Rejected and returned qty is never billable; billed qty never exceeds accepted qty beyond the tolerance without an override.
* Stock is **not** kept: everything received is booked to the PO's project and stage. A site store or transfers between projects are not in this phase.
* Paying a vendor happens outside the CRM; the CRM records the payment and the payable status only.
* Prices on PO lines are cost fields (`unit_cost`, `cost` are already in `COST_FIELDS`): the Site Supervisor sees items and quantities only. A supplier sees their own prices through the vendor portal presenter and never our budget, other quotes or margin.
* Permissions use the existing area `procurement` (Owner, PM, Procurement rw; Estimator, Site, Accounts r). Site may raise requests and record receipts on projects they are on; bills and payments also need `finance: rw` (Owner, PM, Accounts) or Procurement for bill entry. The NAV entry *Procurement* gets `ready: true` and a route; requests, POs and deliveries also appear on the project's Money tab (or a *Purchases* tab).

## H3. What is added
| Kind | Items |
|---|---|
| Collections | `purchase_requests`, `rfqs`, `purchase_orders` (`revisions[]`, `acknowledged`, `vendor_updates[]`), `goods_receipts`, `supplier_returns`, `vendor_bills`, `vendor_payments`; `costs.po_id` / `bill_id`; company `finance.po_approval_limit`, `match_rate_tolerance_pct`, `match_amount_tolerance`, `over_receipt_pct`. Migration `023_procurement` (indexes: company + project + status, POs supplier + status + expected date, bills supplier + bill no. unique, costs `po_id`) |
| Endpoints | `GET/POST /projects/<id>/purchase-requests` · `GET /purchase-requests` · `PUT /purchase-requests/<id>` · `POST /purchase-requests/<id>/cancel` |
| | `GET/POST /rfqs` · `PUT /rfqs/<id>` · `POST /rfqs/<id>/send` · `/quotes` · `GET /rfqs/<id>/compare` · `POST /rfqs/<id>/award` |
| | `GET/POST /purchase-orders` · `PUT /purchase-orders/<id>` · `POST /purchase-orders/<id>/submit` · `/approve` · `/reject` · `/send` · `/whatsapp` · `/acknowledge` · `/amend` · `/cancel` · `/short-close` |
| | `GET/POST /purchase-orders/<id>/receipts` · `POST /goods-receipts/<id>/reverse` · `POST /goods-receipts/<id>/return` |
| | `GET/POST /vendor-bills` · `PUT /vendor-bills/<id>` · `POST /vendor-bills/<id>/approve` · `/override` · `/void` · `GET/POST /vendor-payments` · `POST /vendor-payments/<id>/void` · `GET /finance/payables` |
| | `GET /portal/purchase-orders` · `POST /portal/purchase-orders/<id>/acknowledge` · `/delivery-date` · `/invoice` · `GET /portal/rfqs` · `POST /portal/rfqs/<id>/quote` · `GET /reports/procurement` · `GET/PUT /finance/settings` (new fields) |
| Screens | Procurement (Requests · RFQs · Purchase orders · Deliveries · Bills tabs); quote comparison side by side with rate-library column; PO editor and print page; GRN form usable on a phone (photos from the camera) from the PO and the site report; bill entry with the three-column match; Finance → Payables; project Money tab ordered column; Settings → Finance (PO limit, tolerances) and numbering for PR / RFQ / PO / GRN (`admin.py` `NUMBERED`); vendor portal page |
| Worker | `check_procurement` (RFQ due, PO waiting approval, not acknowledged, delivery due / late, bill due / overdue). In `run_once` |
| Notifications | New *Procurement* group in `routes/notifications.py` `GROUPS` / `notify_group` (a `PROCUREMENT_EVENTS` set): purchase request raised, PO needs approval (critical), PO approved / rejected, PO acknowledged, delivery date changed, delivery due / late, goods received with rejections, bill on hold (mismatch, critical), bill due / overdue, vendor invoice uploaded. Added to `NOTIFY_EVENTS` in `defaults.py` |
| Test file | `backend/tests/test_phase_h.py` (keeps `test_phase_e.py`, `test_phase_f.py`, `test_phase_g.py` green; F's selection-ordering test changes to expect a PO) |

### What the parked drafts give (`backend/later/`)
| Draft | Reuse | Change needed |
|---|---|---|
| `routes/delivery.py` `_po_totals`, `create_po` | Line amount / subtotal / tax / total math, supplier name copy | Lines carry stage and `unit_cost` (cost field); number on approval, not on draft; plain routes instead of `register_crud` (`later/services/crud.py` is not in `app/`) |
| `routes/delivery.py` `_prep_pr`, `award_quote` | Request with quotes, award → PO | Quotes move to `rfqs` with per-line rates and several suppliers; split award; reason when not lowest; drop the proportional rate scaling |
| `routes/delivery.py` `issue_po`, `services/budget.py` `needs_manager_approval` | Over-budget PO waits for a manager | Use `app/services/budget.over_budget` with the ordered figure, `finance.is_approver`, the value limit and `notify.send`, not `t.notify(role=…)`; status names as H1 |
| `routes/delivery.py` `receive_delivery` | Partial receipts, damaged qty, photos, selection updated on full receipt | Own `goods_receipts` record with number, accepted / rejected, tolerance, site report link; site may record on projects they are on only; F selection statuses (no *delivered* status) |
| `routes/delivery.py` `match_vendor_invoice` | Match idea (received value vs invoice, 1 % tolerance, matched / over / under billed) | Per-line qty and rate match, tolerances in settings, own `vendor_bills` record, cost through `finance.submit` (not `post_cost` / `pre_approved`), override with reason |
| `routes/delivery.py` `damage_claim`, `order_selections` | Claim on a PO; one PO per supplier from selections | Claims become supplier returns; ordering hooks into `selections.move_status`; the deposit check is not ported *(to confirm)* |
| `routes/portal.py` `vendor_pos`, `vendor_update` | Vendor sees their POs except draft / waiting approval; delivery date update | Explicit price fields only; acknowledge and invoice upload; `notify.send` to Procurement + PM, not `t.notify` |
| `routes/reports.py` `procurement` | Pending, late, spend by supplier | Spend from approved bills, not PO totals; add price variance and on-time % |
| `routes/engage.py` WhatsApp *material needed* → purchase request | Shape of a request from site | Not in this phase (inbound WhatsApp routing is parked in G4) |

## H4. Not in this phase (and where it goes)
| Item | Where |
|---|---|
| Stock / store, issues to site, transfers between projects, stock valuation | *(to confirm)* — later; H books everything to the project and stage |
| Paying vendors from the CRM (bank file, UPI payouts) | Later with an accounting / banking integration; H records payments made outside |
| Accounting export of bills and payments (Tally / QuickBooks / Zoho Books) | Integrations *(E4, to confirm §15)*; H gives CSV of bills and payments |
| Subcontract work orders with measured progress bills and retention | *(to confirm)* — with retention (E4); H handles subcontractors as POs with lump-sum lines |
| Rate contracts / price agreements with a supplier for a period | *(to confirm)* — later; H uses quotes and the rate library |
| Client deposit enforced before ordering selections | *(to confirm)* — H shows receipts as a hint only |
| Purchase requests from WhatsApp buttons (`later/routes/engage.py`) | With inbound WhatsApp routing (G4) |
| Supplier rating beyond on-time % and price variance | Later |

Decisions taken to start building (the owner can change any of them; the amounts are company settings):
1. **PO approval:** above 50,000 an Owner approves; below it the PM or Procurement user who raised the PO may approve it.
2. **Three-way match tolerance:** 1 % on the rate, 100 on the bill total, and up to 5 % more received than ordered.
3. **Vendor bills** are entered by Procurement or Accounts; the Phase E cost approval (PM / Owner, Accounts within budget) decides them.
4. **RFQs are optional.** A direct PO above the approval limit needs a reason.
5. **Selections are ordered through a PO** from now on; the costs Phase F already recorded for ordered selections stay as they are.
6. **No stock:** everything is booked straight to the project and stage.
7. **Vendor portal:** suppliers see and acknowledge their POs, update delivery dates and upload their invoices; staff enter RFQ quotes in this phase.
8. **Expired compliance documents warn**; they do not block a new PO.
9. **Client deposit before ordering a selection** is shown, not enforced.
---

# Phase I — Closing the gaps in the built modules

Source: a line-by-line check of *Construction & Interior CRM – Requirements (v4)* against Phases A–H (12 Nov 2026). Only gaps in modules that exist are in this phase; what v4 itself places in Phase 2 / 3 (RFIs, submittals, subcontractor management, timesheets, automatic sequences, accounting integrations, offline, safety, AI, full 3D viewer) and the MVP items with no module yet (§17 worker WhatsApp, §19 360° / renders) are not. Covered by `backend/tests/test_phase_i.py` (one section per block); all earlier suites stay green.

### Build status
| Block | Scope | Status |
|---|---|---|
| 1 | Stage budgets from the accepted estimate (§12), GST split CGST / SGST / IGST with HSN / SAC (§1, §15), receipts held on account, client invoice reminder series (§16), petty cash floats (§12) | **Done** |
| 2 | Progress claims by stage % (§12), retention held and released with the defects period (§12, §16), client deposits for selections (§7, §12) | **Done** |
| 3 | Photos with time + GPS tagged to stage / room (§10), attendance (§10), snag / punch list (§10, §14, §16), stock at site: receiving location, consumption, balance (§8, §10), installation checklist (§10) | **Done** |
| 4 | Authority / planning approvals register (§6), mood boards (§6), product catalogue fields + add from a link (§7), selection *Delivered* status, markup rules per category / client and selection margin report (§7), allowance credit, editing requests / RFQs and reversing a GRN (§8) | **Done** |
| 5 | Client raises a change request in the portal, site raises one (§11), new tasks from a change order, portal photo timeline and proposals (§13), reports: projects (delayed, milestones, snags), cash flow, team workload, waiting longest (§14, §16), inbound WhatsApp routed to the project and the right person (§17) | **Done** |
| 6 | Super Admin (§18): company approve / create / delete / trial / plan / modules / notes; plans, add-ons, coupons; subscription billing with GST invoices, retries, grace → read-only; self-service plan change; usage alerts; support tickets and login-as-company with permission; announcements; platform settings; data export; revenue / churn / conversion reports | **Done** |
| 7 | Calendar feed for Google / Outlook (§15), daily backups with status (§15), SMS provider with DLT template ids (§15), Hindi for the portal, site screens and menus (§15) | **Done** |

Decisions taken to start building (the owner can change any of them; amounts are settings):
1. **Stage budget = estimate cost** (direct + overheads, not the client price) per stage. Estimate lines get an optional stage; untagged lines are spread over the tagged stages pro rata. Budgets are filled on the win only where a stage budget is still 0; the Money tab can re-apply them.
2. **GST** is a company setting (*single rate* stays the default). With GST on: same state as the client → CGST + SGST, otherwise IGST; state from the GSTIN (first two digits) or the state field.
3. **Retention** default 5 % with a 12-month defects period, set per contract; half released at handover, half at the end of the defects period.
4. **Progress claims**: a contract is billed either by its milestone schedule or by progress, never both; the basis is fixed once the first invoice exists.
5. **Selection deposit** default 50 %; ordering without it warns (a setting can make it block).
6. **Stock** is kept per location (each project site, plus company warehouses); valued at the PO rate.
7. **Languages**: English and Hindi; other strings fall back to English.

Block 1 notes: an estimate line names its stage (the lead's service template); on the win each stage still at 0 takes the cost of its lines plus overheads, untagged lines spread over the tagged stages (or evenly when none is tagged); *Budgets from estimate* on the Money tab re-applies chosen stages (Owner, Accounts, the project's PM). GST is switched on in Settings → Currency, tax & numbering with the company state (or GSTIN); a draft shows the split live, sending fixes it on the invoice, and a credit note follows its invoice's place of supply. Invoice lines take an optional HSN / SAC code; Finance → GST lists a month's output tax by type and code. A receipt may keep part (or all) of the money on account and apply it to invoices later; voiding it takes back every part. Client reminders follow `client_reminder_days` (default −3, 1, 7, 14; the last one, 14+ days late, is the final reminder). Petty cash: Owner / Accounts give and take back cash; a cost marked *paid from petty cash* comes off the recorder's float (drafts too; rejected and void ones go back) and cannot exceed it.

Block 2 notes: Billing terms sit on the Money tab under the payment schedule. With progress billing the schedule's own rows are not invoiced (change-order rows still are); the schedule of values defaults to the stage budgets' proportions (else even) and the claimed % comes from the claims themselves, so deleting a draft claim frees it; one draft claim at a time. Retention is held on every contract invoice (schedule, change order, progress) and its balance leaves it out; *Release retention* drafts a *retention* invoice (no tax, kept out of the GST summary) and the project's money shows the retention held. The worker tells Accounts and the PM once when the defects period (handover date + days) ends with retention still held. *Ask for deposit* on a chosen selection drafts a deposit invoice (company %); ordering warns when it is unpaid, or refuses when *Do not order until the deposit is paid* is set.

Block 3 notes: photos keep the phone's time and place (asked once per upload) plus a stage and room; the place is kept as first sent, and the portal timeline groups shared photos by day. The project's Site tab has Daily reports · Attendance · Snags · Stock. Attendance is one sheet per project per day (today or yesterday; older by an Owner) for staff on the team and named site workers (Settings-free list on the tab); the month summary gives days (half days count ½), overtime and, for roles that see costs, labour cost at the worker's daily rate. Snags go open → fixed → closed; the fixer cannot close their own fix (an Owner can); reopen needs a reason; past-due snags are chased once per due date; closing the last snag of a stage offers any checklist item that mentions snags. Stock is computed from GRNs (accepted − returned) at their receiving location (the site, or a warehouse from Settings → Warehouses) plus moves (used on site by stage, moved between sites and warehouses, counted); value at the PO rate is a cost field. A warehouse holding stock cannot be removed. Installation: an ordered or delivered selection is installed by ticking the checklist (default six checks) with photos.

Block 4 notes: products are rate-library items of kind *product* with SKU, size, finish, supplier, lead time, photos, supplier link and an optional client price; Selections → Product catalogue lists them (trade price hidden from roles that do not see costs). *Add from a link* fetches only public http(s) pages (every address and redirect checked, 6 s, 1.5 MB) and reads schema.org Product or Open Graph tags; nothing is saved until the user saves. Markup: Settings → Product markup (default, per category, per client); an option with a cost and no price is priced by it (client, then category, then default) and keeps the % used. Selection → *Margin* shows cost, price and margin by room. A selection goes ordered → delivered when its PO line is fully received (or straight to installed). A choice under the allowance drafts a credit change order (negative price); approving it lowers the contract's revised value and records the credit due (given by a credit note). Open purchase requests can be changed (by Procurement or the requester) until priced; RFQs take a new due date and suppliers (a supplier who quoted stays). A delivery can be reversed whole when none of it is billed, returned or used. Documents tab: Documents & drawings · Approvals · Mood boards. Approvals move preparing → submitted (reference required) → query / approved (validity, conditions) / rejected; the worker chases 30 days without an answer and approvals running out within 30 days. Mood boards are images (uploaded or linked) per room; once shared, the client likes and comments in the portal and the managers are told of comments.

Block 5 notes: a change request (client in the portal, or anyone on the project from the Site tab's *Ask for a change*) is a draft change order marked *asked by the client / site*; the PM is told and prices it as usual; the client follows their requests in the portal (the price shows once it is sent). A change order can list new tasks (title, working days); on approval they are added to its stage one after the other from today (or the stage start) and the stage end grows to fit. The portal lists the client's proposals with their signing link. Reports: *Projects, cash flow and team* on the Reports page — delayed projects (late stages / tasks, forecast days late), milestones late or due in 14 days, open snags / issues / approvals / change orders per project, cash flow (three months back as received and paid, this month and two ahead as due from invoices, supplier bills and open POs; late items count as due now) for Owner / Accounts / finance roles that see costs, team workload over four weeks (working days of assigned open tasks against working days available), and client approvals and payments waiting longest. Inbound WhatsApp from a contact on a live project joins that project's thread with them (most recently updated project when several), goes to Accounts / Procurement / the designer by its words (payment, material, design) and always to the PM; urgent words are flagged. The *Milestones* card counts late ones too.

Block 6 notes: built on the parked `later/routes/superadmin.py` (now `routes/platform.py`; login, two-factor, team and the role matrix stay in `routes/superadmin.py`). Super Admin menu: Dashboard (companies by status, MRR, revenue this / last month / year, signups, conversions, cancellations, overdue list, database / storage / errors / last backup), Companies (search by name, status, plan, city, signup date; profile with owner, plan, usage, payment history, tickets, support sessions and notes; create a company with a temporary owner password; approve, suspend, reactivate, delete — kept 30 days then purged — restore, extend trial, free months, change plan, modules, features, add-ons, notes, reset the owner's password, log in as the company, download its export), Plans and coupons (a new price is for new signups; a company keeps `price_locked` until it renews; yearly = 10 months; coupons by % for N invoices, optional use limit and expiry), Billing (invoice list, *Run billing now*, mark paid by transfer / cheque / UPI / cash, refund as a credit note, void, GST by month with CGST / SGST / IGST from the company's GSTIN state against the platform's), Support and news (tickets, replies notify the raiser; announcements to all or chosen plans, optionally emailed to the owners), Reports and usage (revenue by plan, month and city, churn with reasons, trial conversion, most / least used features; usage against plan limits, WhatsApp cost against what the company pays), Platform settings (name, logo, login message, signup approval, gateway / WhatsApp / SMTP / SMS keys masked on read, terms and privacy served at `/api/public/legal/terms|privacy`). The worker runs the billing once a day: a trial that ended gets its first invoice; an active company due for renewal gets the next; an open invoice is reminded once a day; seven days past due the company turns read-only (writes refused with 402, billing and support still open); deleted companies are purged after 30 days. Companies near a limit (80 % of users, projects, WhatsApp or storage) are told once a month. Support log-in needs the company's *Allow support login* setting and a reason, lasts one hour, is recorded in the Super Admin audit and the company's audit log, and the company sees a banner while it is on. Company side: Settings → *Subscription & support* (plan, usage, change plan or cycle with a prorated invoice, coupon, pay an invoice — sandbox gateway pays at once —, ask for an export, cancel with a reason; tickets for everyone); announcements show as a dismissible banner. With *New companies wait for approval* on, a signup is *pending* until approved and cannot work meanwhile.

Block 7 notes: every staff user has a private calendar link (user menu → *Calendar feed*; `/api/calendar/<token>.ics`) to subscribe to in Google Calendar or Outlook — open tasks assigned to them, milestones of their projects, their follow-ups, site visits and project meetings, 30 days back to a year ahead; *Make a new link* stops the old one; the token never appears in API answers. SMS: Settings → Company → *SMS* (MSG91 or sandbox; sender id, DLT entity id, auth key masked); SMS templates carry their DLT template id (Settings → Sales & templates) and a live provider refuses a template without one; sent or logged messages are stored like WhatsApp ones. Backups: the `backup` service writes a gzipped JSON copy of every collection plus the uploaded files to the `backups` volume daily at 02:00 (BACKUP_HOUR), keeps 14 (BACKUP_KEEP), records the result for the Super Admin dashboard; Super Admin → Platform settings lists them and can back up now; restore with `docker compose exec backup python -m app.backup restore <folder> --yes`. Language: English or हिन्दी per user (staff user menu, portal top bar), saved on the user; the menus, the client portal and the site screens (reports, attendance, snags, stock, change requests) are translated, everything else stays in English.

**Phase I is complete.**

Phase I follow-up (second check against v4): the client can now answer *None of these* to a selection's options in the portal (the item goes back to open with their reason, the PM is told) — §7 "approves or rejects each item"; cost head *Products* added (§12 job costing by labour, material, subcontractor, products); the client portal shows the company's logo and colour (§1); the login page shows the platform's message and links to the terms of service and privacy policy (`/legal/terms`, `/legal/privacy`) (§18); the Owner buys add-ons in Settings → Subscription — extra users, storage packs and WhatsApp message packs, billed with the next invoice (§18); the plan's WhatsApp allowance is counted per calendar month (it counted every message ever); the web app installs to a phone's home screen (manifest + icon) for site staff and clients (§15 mobile — the offline app stays in Phase L).

---

# Roadmap — what v4 asks for that is not built yet

Everything in the modules built so far is covered (Phases A–I). What remains is whole areas, in the order v4's own phases put them. Each phase is planned in detail (requirement → implementation → test, blocks) before it is built, as before.

## Phase J — the rest of the MVP (v4 "Phase 1 — MVP") — **Done**
| Block | Scope (v4 §) | Status |
|---|---|---|
| 1 | **WhatsApp for site workers** (§17): worker list with WhatsApp numbers (free users, not counted), the **morning work message** built from the schedule (site, room, task, drawing link, supervisor) at a set time; messages in Hindi or the local language | Done |
| 2 | **One-tap buttons and voice notes** (§17): *Material needed*, *Work done*, *Need help / clarification* (with photo or voice note) arriving on WhatsApp become CRM records — a purchase request, a task update for the supervisor to approve, a question (RFI-lite) — with the answer sent back; **routing rules** per topic and **escalation** of urgent words to the PM | Done |
| 3 | **Trade sequence** (§17): when one trade marks work done, the next trade on the room is told it is ready; **QR code at site** per room opening its latest drawings and specs; **job card** (drawing, measurements, photo) per task | Done |
| 4 | **PM daily digest** (§17) by app and WhatsApp; **call / message reports**; **email in the shared inbox** | Done |
| 5 | **360° room views and renders with comments** (§19 MVP) | Done |
| 6 | **Design options** (§19 MVP) | Done |
| 7 | **Subscription charged automatically** (§18) | Done |

How it was built (tests: `backend/tests/test_phase_j.py`, 204 checks):
- **1** `routes/field.py`. Site workers get a WhatsApp opt-in (asked on site, needs a mobile) and a language (en / hi). A **job card** per task holds the room, trade, workers, drawings (current revision), measurements, reference photos and instructions. It has a public link `/j/<token>` that works without sign-in; it serves only the files listed on the card. The **morning message** is sent at Settings → Field & WhatsApp → time, once a day per company, in the company's time zone (minutes from UTC, India 330). Each opted-in worker gets the sites, rooms and tasks they have today, the job-card links, and the supervisor's name and phone, with three reply buttons (WhatsApp interactive message). A preview and "Send now" are on the project → Site → Workers on WhatsApp.
- **2** Webhook: a number that is not a contact but a site worker becomes a **field update**. A button press with no text asks for the detail (text, voice note or photo within 30 min).
  - *Material* becomes a purchase request (source `whatsapp`).
  - *Work done* waits for the supervisor; approving it marks the task done (checklist and predecessors are enforced), and sending it back gives the worker the reason.
  - *Help* becomes a question routed by the company's **routing rules** (topic → role, editable); the answer goes back on WhatsApp.
  - **Urgent words** (built-in list plus the company's own) notify the PM at once. They escalate to the Owners after N minutes if nobody presses "I'm on it". STOP opts a worker out.
  - Voice notes and photos keep the WhatsApp media id; with the Cloud API the file is also fetched into the company's uploads.
  - Client WhatsApp routing (Phase I) now uses the same company rules.
- **3** **Trade sequence**: when a task is marked done (in the app, or by approving a worker's update), the next trade hears that the room is ready (app notification and WhatsApp to that card's workers). The next trade is found from the tasks linked to this one, otherwise from the company's trade order within the same room. **Rooms & QR**: rooms are collected from job cards, documents and selections; one QR code per room (SVG from `/api/qr.svg`, made with `segno`) opens `/r/<token>`, which shows the room's current drawings, the chosen finishes (no prices) and the jobs. The QR can be printed.
- **4** `routes/digest.py`.
  - `/app/digest` is the morning screen: per project, what was done since yesterday, late tasks (with days late), stuck items (blocked tasks, worker updates not settled, urgent messages), budget stages at 80 % or more (only for roles that see costs), and whether there was no site report yesterday.
  - At the digest time the worker sends it to Owners and PMs as a notification, and on WhatsApp to those who opted in (`PUT /me/whatsapp`).
  - **Message report**: messages in by person, topic and channel, the median first reply, unread messages, and calls logged on leads.
  - **Inbound email**: a secret webhook for the mail provider's inbound parse. An email from a known contact goes into their project thread (`via: email`, quoted reply cut, duplicates by Message-Id ignored); an unknown sender waits in the "unmatched" list. Replies from the inbox already go back by email.
- **5** `routes/design.py`.
  - A **view** is a 360° panorama (shown with Pannellum 2.5.6 from the CDN, loaded only when opened) or a render; shared with the client or internal.
  - A comment is pinned with yaw/pitch (360°) or x/y % (render), by the team or by the client in the portal.
  - A comment becomes a task on a chosen stage, or a change request (a Phase I draft change order; when the client wrote it, it counts as the client's request), or is resolved.
  - A view with a comment that became a task or change request cannot be deleted.
  - File links in `<img>` tags and the viewer now load through a SameSite=Strict, path-scoped cookie that the API reads only for `GET /api/files/…`. This also fixes images on mood boards and product photos.
- **6** **Design options**: a decision with 2–4 options (A–D: images, description, extra price, which may be negative).
  - It can be linked to a selection, each option matching one of that selection's options.
  - "Send" emails or WhatsApps the client, who sees the options side by side in the portal and approves one or asks for changes.
  - Approving: the linked selection records the choice (method Portal), and an option with an extra price becomes a draft change order. The decision is then locked.
  - Editing the options of a sent decision puts it back to draft.
- **7** `routes/autopay.py`. The Owner sets up autopay (card or UPI) under Settings → Subscription, using the gateway chosen in Super Admin settings:
  - Sandbox: active at once; a test card makes every charge fail.
  - Razorpay: customer plus a recurring-token order; active on `token.confirmed`.
  - Stripe: customer plus an off-session SetupIntent; active on `setup_intent.succeeded`.

  Charging: an open invoice is charged when autopay is set up, when it is issued, and by the daily billing run once a day, up to 3 tries. Each failure is emailed to the Owner; after the third the read-only rule applies as before. Live charges are settled by the signed webhook `/api/webhooks/billing/<gateway>`: HMAC-SHA256 of the body with the new `gateway_webhook_secret` (masked in SA settings), or Stripe's `t=…,v1=…` signature with a 10-minute window. A repeated webhook does no harm.

Not verified: live WhatsApp Cloud, Razorpay and Stripe calls (built to their documented APIs; tested only in sandbox mode). The 360° viewer, digest, Field tab and public job card were clicked through in the browser.

## Phase K — v4 "Phase 2" — **Done**
| Block | Scope (v4 §) |
|---|---|
| 1 | **Subcontractor management** (§9): work packages from the BOQ, invite subcontractors to bid (portal), compare bids side by side and award, subcontract agreement, measured progress and payment certificates with **retention held**, compliance with expiry alerts (exists for contacts), **performance rating** after each job |
| 2 | **RFIs** (§6): question from site / consultant to the designer with photo, due date, answer, distribution; open RFIs in reports and the waiting list; **submittals** (shop drawings, samples) with review status |
| 3 | **Timesheets and resource planning** (§12, §14): hours per project and stage (architects and designers bill hours), approval, hourly-fee invoicing, hours per project and utilisation reports, resource calendar |
| 4 | **Automatic follow-up sequences and rules** (§16): trigger → wait → action (message, task, notify manager), sequences after enquiry / site visit / proposal (day 1, 3, 7), re-engage lost and cold leads, chasing approvals, after-handover warranty and maintenance check-ins, review and referral requests, anniversary messages; sequences stop when the client replies, approves or pays |
| 5 | **Accounting integration** (§12, §15): Tally (XML), Zoho Books, QuickBooks, Xero — invoices, receipts, bills, payments, GST |
| 6 | **AI WhatsApp assistant** for common questions and a **phone system (IVR)** with call logging (§16 / v4 Phase 2) |
| 7 | **Full 3D model viewer** (§19 Phase 2): GLB / IFC / OBJ in the browser (Three.js, IFC.js), comments pinned on the model, before / after comparison |

**Phase K — Done.** Tests: `backend/tests/test_phase_k.py`, 187 checks.
- **1** `routes/subcontracts.py`, Money → Subcontracts, and the subcontractor's portal.
  - **Packages and bids:** a work package's lines are typed in or taken from the accepted estimate (the labour rate becomes the internal estimate rate, hidden from roles that do not see costs). Only contacts typed *subcontractor* can be invited, by email and WhatsApp. They price every line in the portal, or the team enters a bid that came another way; a new bid replaces the old one.
  - **Comparison:** line by line against the estimate, lowest marked, % over or under the estimate, days, and the bidder's rating.
  - **Award:** awarding a bid that is not the lowest needs a reason; an expired compliance document warns, and awarding anyway is recorded. The agreement is printable (HTML).
  - **Certificates:** quantity done to date per line, which never goes down and is capped at 110%. Each certificate is gross to date − previous, minus retention. Approving it books the cost (category Subcontract, stage budget recalculated); paying it records part or full payments.
  - **Completion:** rates quality, time, safety and communication (1–5), kept as a running average on the subcontractor, and makes a retention-release certificate for the retention held.
- **2** `routes/rfis.py`, project → RFIs & submittals, and the portal.
  - **RFIs** go to a named staff member or an external consultant on the team, by default the architect or designer. The due date is 3 working days (1 if urgent). An RFI can carry photos and the drawing it is about.
  - **Answers** go to the asker and are emailed to the distribution list; an answer with a cost or time impact drafts a change request. An answered RFI can be closed, or reopened with a reason (history kept).
  - **From the portal:** subcontractors and consultants raise RFIs; an external consultant answers in the portal.
  - **Submittals** (shop drawing, sample, data sheet, method statement, test certificate) go to a reviewer for approved / approved as noted / revise and resubmit / rejected; anything but approved needs comments. Revise-and-resubmit needs a new revision.
  - **Reminders and reports:** the worker reminds about overdue RFIs and reviews once a day, the digest lists overdue RFIs as stuck, and `/reports/rfis` gives open, overdue and average days to answer, with submittals by status.
- **3** `routes/timesheets.py`, Team → Timesheets.
  - **Logging:** hours per day, project, stage and task, in quarter hours. No future days, at most 24 h a day, and only on projects the person is on.
  - **Approval:** the week is submitted; the project's PM or an Owner approves or returns it with a reason, and nobody approves their own hours.
  - **Rates:** per person (Settings → Integrations): the hourly cost gives each entry's cost, the bill rate is used for invoicing.
  - **Invoicing:** approved billable hours become a draft invoice, one line per person (hours × bill rate). Deleting or voiding that invoice frees the hours again.
  - **Report and plan:** the report shows hours by project and stage and by person (billable % and utilisation against hours per day × Monday–Saturday). The resource plan shows, per person and day, the tasks assigned (overbooked when two overlap) and the hours logged.
- **4** `routes/sequences.py`, Team → Automation & calls.
  - **Triggers:** new enquiry, site visit done, proposal sent, lead lost, lead gone cold (N days), client approval pending (selection or change order), invoice overdue, handed over, and handover anniversary.
  - **Steps:** wait N days → send a message template (WhatsApp when opted in, email or SMS; logged on the lead), make a follow-up task, or notify a role or the record's owner.
  - **Which records:** only records after the sequence was switched on, one run per record (per year for anniversaries).
  - **Stopping:** a run stops when the client replies, or when the record moves on (won or lost, accepted, chosen, paid). Runs are listed and can be stopped by hand.
  - **Who:** Owner, PM or sales manager. Presets cover the enquiry day 1/3/7 chase, the proposal chase, re-engaging after 90 days, and the after-handover review / 1-month / warranty check.
- **5** `routes/accounting.py`, Settings → Integrations → Accounting.
  - **Tally:** an XML file to import into Tally Prime / ERP 9. It holds party ledgers (Sundry Debtors / Creditors) and Sales (CGST/SGST/IGST ledgers), Receipt, Purchase (input GST) and Payment vouchers for a date range, with the company's own ledger names.
  - **Zoho Books, QuickBooks, Xero:** connected with OAuth (client id, secret and refresh token; tokens are refreshed and rotated). "Sync" pushes invoices, receipts and (Xero) bills. Each record keeps the provider's id so it is never sent twice; failures are listed with the provider's reason. An optional nightly sync is available, and a sandbox provider for trying it out.
- **6** `routes/assistant.py`, Settings → Integrations.
  - **Assistant:** a client's WhatsApp, after routing to the project thread, is answered from the company's FAQs and the project's facts: progress, current stage, next milestone, amount due, PM, last site report — never internal costs.
  - **Modes:** *FAQ* uses keyword matching only. *Claude* uses the company's own Anthropic API key, model `claude-opus-5-5`, low effort, a JSON answer-and-handoff reply, and the server-side refusal fallback. If the API is unavailable it falls back to the FAQ answers.
  - **Handing over:** urgent words, complaints, discount or change requests and unknown questions get the holding reply and go to the team. The answer is kept in the thread.
  - **Phone (IVR):** Twilio, Exotel (connect applet), or sandbox. The greeting and menu are set by the company (digit → role); the call is put through to that role on the caller's own project (else anyone in the role, else an Owner) and recorded if wanted.
  - **Call log and missed calls:** every call is logged, and calls by hand too. Calls with a known contact go on their open lead's timeline, so they count in the message report. A missed call alerts the person and makes a "Call back" follow-up.
- **7** `routes/models3d.py`, project → Documents → 3D models, and the portal.
  - **Files:** GLB / glTF, OBJ and IFC up to 100 MB. Three.js 0.160 and web-ifc 0.0.57 load from the CDN through an import map, only when a model is opened.
  - **Viewing:** orbit and zoom. A click on the model pins a numbered comment (point plus camera); a comment becomes a task or a change request, or is resolved.
  - **Versions:** a new upload can replace an earlier version; before / after shows both side by side with linked cameras.
  - **Sharing:** shared models appear in the portal, where the client comments.

Not verified: live Zoho, QuickBooks, Xero, Anthropic API, Twilio and Exotel calls. They are built to the providers' documented APIs and tested only in sandbox or fallback mode; the Claude path was exercised with an invalid key, which falls back to the FAQ answers. IFC rendering depends on web-ifc's API (checked against its documented calls, not with a real IFC file).

## Phase L — v4 "Phase 3" — **Done**
| Block | Scope (v4 §) |
|---|---|
| 1 | **Offline mobile app** (§10, §15): site report, attendance, snags and photos captured offline and synced; Android / iOS packaging |
| 2 | **Safety incidents, inspections and checklists** (§10) |
| 3 | **AI**: follow-up drafts, BOQ from drawings, progress summaries from site photos (§15) |
| 4 | **Marketplace of supplier catalogues** (§7, v4 Phase 3) |
| 5 | **AR on the phone** and the **3D model linked to site progress** (§19 Phase 3) |
| 6 | **Advanced reports and dashboards** (v4 Phase 3) |
| 7 | **More languages** beyond English and Hindi; per-project currency (§15) |

**Phase L — Done.** Tests: `backend/tests/test_phase_l.py`, 194 checks.
- **1** `routes/mobile.py`, the field app at `/field` (Delivery → Field app), `core/offline-store.ts`, `public/sw.js`.
  - **On the phone:** `GET /mobile/bootstrap` gives the person's live projects (stages and tasks, the attendance list, open snags, today's report and sheet) and the inspection checklists. It is kept in IndexedDB; a service worker keeps the app shell, so the page opens with no signal.
  - **Offline:** the daily report, attendance, new snags, snag fixes, safety incidents and inspections are queued. Photos are shrunk to 1600 px and kept as blobs with GPS and time.
  - **Sync:** when the signal is back, photos are uploaded first, then the queue goes to `POST /mobile/sync`. Each operation has an id made on the phone, so a queue sent twice is applied once (`sync_ops`, unique index). Each operation runs through the web app's own endpoint, so rules and permissions are the same.
  - **Merging:** the day's report on the server gets the phone's work lines, photos and notes, and its manpower per trade; attendance merges per person. A refused operation (locked report, no permission) stays on the phone with the reason, to fix or discard; the rest of the queue goes on.
  - **Who:** roles with site access (Owner, PM, Site Supervisor).
  - **Android / iOS:** `frontend/capacitor.config.json` packages the same build with Capacitor (`npx cap add android|ios`). The app must load the hosted site: set `server.url` to the deployment's https address before building, because the API is same-origin. The web app also installs to the home screen (manifest).
- **2** `routes/safety.py`, project → Safety, Delivery → Safety (report).
  - **Incidents:** near miss, first aid, injury, lost time, property damage, environmental, fire. People involved, what was done at once, witnesses and photos. A serious one (injury, lost time, fire, or high / critical) alerts the project's managers and the Owners at once.
  - **Investigation and close:** a manager records the root cause (from a list) and findings, and adds corrective actions with an owner and a due date. The owner marks an action done; the worker reminds daily once it is overdue. A serious incident is investigated before it is closed, and every action must be done first. A closed incident can be reopened with a reason.
  - **Inspections:** checklists from Settings → Integrations → Safety checklists (three ready-made: weekly site safety, working at height, electrical). Each item passes, fails or does not apply, and a fail needs a note. The score is passed / (passed + failed). A failed item becomes a snag (high and due tomorrow if critical, else 3 days); a failed critical item alerts the PM.
  - **Toolbox talks:** topic and attendees from the attendance list.
  - **Report:** incidents by kind and month, days lost, days without a lost-time injury per project, open and overdue actions, average inspection score, the items that fail most, and talks.
- **3** `routes/ai.py`, Settings → Integrations → AI.
  - **Modes:** off, Claude (the company's key; the assistant's key is used if none is set), or sandbox (fixed sample answers). Model `claude-opus-5-5`, structured JSON output, the server-side refusal fallback, adaptive thinking for drawings and photos. Every call is logged with its tokens, and the month's use is shown.
  - **Follow-up draft** on a lead: a WhatsApp or email message for one of five purposes from the lead's facts; with AI off, a plain template. Shown to copy and edit, never sent by itself.
  - **BOQ from drawings** on a draft estimate: up to 5 drawings (image or PDF) give lines with qty, unit, room, work type and how the quantity was read. Each line is matched to the rate library by name; the estimator ticks, corrects and adds them. The screen says to check every quantity.
  - **Progress summary** of a site report (its photos and notes) or of a project's last N days: a summary, what the photos show, safety concerns, a client update, and suggested stage progress. It never moves the plan.
- **4** `routes/marketplace.py`, Money → Marketplace, Super Admin → Marketplace.
  - **Sellers:** a company turns on selling and lists products from its catalogue at a list price. The Super Admin can list a supplier that is not on the platform from a pasted price list, and hide any listing.
  - **Buyers:** search and filter by category, supplier, city and price. *Add to my catalogue* copies the item at the list price as our cost and adds the supplier to contacts (matched by email). It stays linked: a price change shows, and *update* takes it.
  - **Quotes:** *Ask for a quote* (qty, needed by, city) reaches the seller (notification for a company on the platform, email for a listed supplier); the seller's price and lead time come back to the buyer.
  - **Privacy:** a listing never shows the seller's cost, internal ids or email. Photos are served only while the listing is published, and turning selling off unlists everything.
- **5** `routes/models3d.py` (added), project → Documents → 3D models, `/ar/:token`.
  - **Model linked to progress:** *Link parts to work*: click a part (a GLB / OBJ node name, or an IFC element as `ifc:<express id>`) and choose its stage or task. *Colour by site progress* paints each linked part done, in progress, late, blocked or not started, from the plan, with the % built. The client sees the same colours in the portal (no task ids).
  - **AR:** a GLB / glTF model gets a tokened link that opens Google's `<model-viewer>` (3.5.0, from the CDN). It shows the model at real size in the room through WebXR / Scene Viewer (Android) or Quick Look (iPhone). The file is served to the phone's AR app with CORS; withdrawing the link stops it.
- **6** `routes/report_builder.py`, Money → Report builder and Dashboards.
  - **Builder:** 9 datasets (leads, projects, invoices, payments, costs, follow-ups, site reports, safety incidents, timesheet hours), up to two group-bys, up to four measures, value filters, a period, a chart (table, bar, line, pie, number) and CSV export. Each dataset needs its guarding area; costs need a cost-seeing role. Rows are the ones the person sees elsewhere.
  - **Saved reports:** private or shared (Owner / PM). Weekly or monthly email with the CSV attached, run as the report's owner so it never shows more than they see.
  - **Dashboards:** per person (an Owner can share one); widgets from saved reports or nine quick reports. A widget a viewer's role cannot see says so instead of showing data. Charts are plain SVG.
- **7** `services/languages.py`, `core/i18n.ts`, project currency.
  - **Languages:** Marathi, Gujarati, Tamil, Telugu, Kannada and Bengali added to English and Hindi, for the menus, the portal, the site and field screens. The most-used phrases are translated; the rest stay in English. Site workers' morning WhatsApp message and its buttons go in all eight.
  - **Per-project currency:** a project has its own currency (INR, USD, EUR, GBP, AED, SGD, AUD; default the company's), locked once it has an invoice. Its invoices and payment links use it.
  - **Reports:** the report builder adds money up in the company's currency at the rates in Settings → Integrations → Currencies, with a currency group-by.
- **Security fix:** `GET /company` no longer returns saved keys or passwords (the AI and assistant API keys, accounting, phone and SMTP credentials); they show as •••.

Not verified live: the Anthropic API (sandbox and an invalid key only), the Android / iOS builds (configured, not built here: no Android SDK or Xcode), AR on real phones, and the offline flow on a real phone with no signal.
