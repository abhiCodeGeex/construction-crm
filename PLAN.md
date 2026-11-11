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
| 4 | Daily site reports: weather, manpower, work done, photos, issues → project issues, delays → delay log; portal read-only view; Documents, Selections, Site reports leave SOON | Planned |

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
