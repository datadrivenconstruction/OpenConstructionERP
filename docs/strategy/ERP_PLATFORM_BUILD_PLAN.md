# ERP Platform Depth - Build Plan

> STATUS: PLANNING (mature cloud-ERP benchmark merged; construction project-controls benchmark merged)
> LAST UPDATED: 2026-06-08
> OWNER: DataDrivenConstruction
> SCOPE: adopt the highest-value, globally-needed ERP modules/functions and wire them into our
> existing modules. Plan-driven, dependency-ordered, built to perfect quality (no stubs, no crutches).

## How to resume (read this first)

This is the single source of truth for the ERP-depth initiative. It survives reboots and is meant
to be picked up by any agent that enters the repo.

1. Read this whole file. Section "Quality bar" is non-negotiable. Section "Hard conditions" lists
   guardrails that gate coding - satisfy them before/inside each feature.
2. Build in dependency order. `oe_saved_views` and the finance Chart of Accounts are the roots;
   most later features depend on them. Do not start a dependent before its dependency is complete.
3. A feature is "done" only when the FULL vertical slice exists: models -> schemas -> repository ->
   service -> router -> validators -> migration (single alembic head) -> backend tests -> 26-locale
   i18n -> frontend feature + tests -> IN-PRODUCT GUIDANCE (see "In-product guidance & UX") ->
   tsc/eslint/ruff clean. No placeholders, no TODO stubs, no "wire later". If you cannot finish a
   slice, do not start it.
4. Parallelize only INDEPENDENT features (different modules, no shared-file contention). Use a
   Workflow with one agent per independent feature; serialize anything that shares a dependency.
5. Tick the checkbox in "Roadmap & progress" and append a dated note to the "Progress log".
6. Respect every hard constraint: lightweight 2GB core, PostgreSQL-only, AGPL-only, modules=plugins,
   i18n 27 locales, AI proposes/human confirms.

### TRADEMARK RULE (strict, founder)
The benchmarked competitors' brand/product names must NEVER appear in any commit, PR, changelog,
code, UI string, comment, or build artifact. Every feature here already uses a neutral generic name.
Phase 1 ships a CI/pre-commit gate that fails the build if a competitor brand token is found.

## Quality bar (no stubs, no crutches)

- Money math is correctness-critical: tests-FIRST for percentage-of-completion %, WIP over/under,
  trial-balance = 0, period-lock rejection, currency-honesty (never blend currencies).
- Every new query surface enforces tenant/project scoping server-side, on top of the existing
  key-scope. A registration without a scoper is rejected at startup.
- Every importer commits THROUGH the owning module's service (invariants, events, audit), never a
  raw INSERT.
- Streaming/chunked reads with row/cell/byte caps for any file ingest (no unbounded load on 2GB).
- No new datastore, no non-AGPL dependency, no PostGIS-requiring column on the embedded default.
- CLARITY IS A FEATURE: every new function must be obvious to a non-expert user. No screen ships
  without in-product guidance (see the dedicated section). A finance term a construction estimator
  may not know (percentage-of-completion, WIP, retainage, trial balance, accrual) MUST carry an
  inline plain-language explanation. If a user has to read external docs to use a screen, it is not done.
- TRANSLATED EVERYWHERE: every user-facing string lands in all 27 locales in the same change, never
  English-only. Verify each locale with `frontend/scripts/i18n-diff.cjs` - zero missing and zero
  English-equal for every new key before merge.
- TESTED FOR REAL: green unit tests are necessary but not sufficient. No feature is done until it
  passes the multi-pass visual acceptance gate (real clicks + screenshots + screenshot review, 3 to
  4 deep passes) - see "Verification & testing gate".

## In-product guidance & UX (mandatory for every feature)

These ERP features are powerful but can intimidate non-accountants. Every feature ships with the
following, all i18n'd in all 27 locales (zero hardcoded strings), reusing existing design-system and
help components where they exist (tooltips, ProductTour, WhatsNewCard, empty states):

1. Module intro / empty state: the first time a screen is opened (or when empty), a short plain-
   language panel: what this is for, the one first action to take, and a 1-line example. Never a
   blank screen with no guidance.
2. Field-level "what's this?" help: an info affordance next to every non-obvious field/term with a
   one or two sentence plain-language explanation and, for finance terms, a tiny worked example
   (e.g. "Percentage of complete = cost incurred / total expected cost. 60k spent of 100k budget = 60%.").
   Maintain a shared finance/construction glossary so the same term reads identically everywhere.
2b. Plain language first: label things the way a site QS/estimator speaks, with the accounting term
   in parentheses, not the other way round (e.g. "Money earned but not yet billed (under-billing)").
3. Guided first run: extend ProductTour (or an inline coach-marks pass) for each new module's core
   flow, launchable again from a Help affordance. Auto-start once, never nag.
4. Helpful, explanatory errors/validation: every block states WHY and the fix in plain language
   (e.g. "This period is closed, so it can't accept new entries. Post to the current open period, or
   ask an admin to reopen it."). Never a bare code or a silent failure.
5. AI suggestions explain themselves: every AI proposal shows a plain-language reason and a confidence
   score, with an obvious accept/edit/reject, and never auto-applies.
6. Sensible defaults + presets/examples so a user is never staring at an empty form; show a worked
   example or a "start from a template" path.
7. Progressive disclosure: show the simple path by default, tuck advanced options behind "Advanced"
   so the basic flow stays uncluttered.
8. Consistency: same term, same icon, same layout for the same concept across modules, so learning
   one screen teaches the others.

Definition-of-done check per feature: open it as a brand-new user with no docs - can they understand
what it does and complete the primary task from on-screen guidance alone? If not, it is not done.

## Verification & testing gate (the founder's top bar - mandatory)

"The main thing is very thorough testing through real clicks, screenshots, and screenshot analysis -
3 to 4 genuinely deep passes." This is not optional and not replaced by unit tests. The reusable
harness is `frontend/qa-tests/ux-acceptance.mjs` (logs in through the REAL demo UI - token injection
is rejected by the API - then runs the passes below, writing screenshots to
`qa-tests/ux-acceptance/<module>/` and a machine report to `report.json`).

Every feature/module is signed off only after 3 to 4 deep passes, each ending in screenshots that are
actually looked at, not just diffed:

1. SMOKE: open every route, screenshot, collect console + page errors, assert no redirect to /login
   and no error-boundary crash, assert the page is not empty.
2. INTERACT: real, non-destructive clicks through the core flow (open help/"what's this", empty-state
   CTA, primary panel/drawer, tabs); screenshot each resulting state; zero new console errors.
3. I18N (all-languages gate): reload under a representative locale spread covering Latin, Cyrillic,
   CJK and RTL plus the lowest-coverage locales; screenshot; scan for raw-key leaks and English-equal
   leaks; the RTL pass must show a correctly mirrored layout. Confirms the 27-locale gate visually,
   not just by key count.
4. GUIDANCE: detect which of the 8 in-product-guidance items are present; screenshot the help/tour
   open state.

Sign-off rule: a human (or the agent on the founder's behalf) reads the screenshots from all passes
and confirms the screen is clear, correct, and fully translated. No green-checkmark-only sign-off.
Run order per change: `tsc -b` -> unit/component tests -> this visual gate -> commit.

## Strategy (from the mature-ERP benchmark)

Our gap vs a mature cloud ERP is NOT construction (we lead there) but FINANCIAL DEPTH plus four
reusable platform primitives the incumbent reuses everywhere: a record-level saved-search engine,
role-based home dashboards, no-code workflow automation, and a unified import framework. We already
own most building blocks (append-only double-entry `LedgerEntry` with `is_reversal`/`reversal_of_id`,
`ControlAccount`/`CostLine`/`BudgetLine`, `EVMSnapshot`, `Contract`/`ProgressClaim`/`RetentionSchedule`,
KPI registry, vector+SQL search, validation pipeline, pandas/openpyxl in base deps). So the strategy
is mostly EXTEND, not rebuild. Build the keystone primitive first, then financial depth, then the
asymmetric edge (percentage-of-completion + WIP), then the convenience UX layer. Defer multi-entity
consolidation and FP&A (demand-gated, XL).

## Hard conditions (guardrails - satisfy before/inside each feature)

1. No-code automation is a THIN layer over `oe_approval_routes` (core, auto_install). Do NOT fork
   `oe_enterprise_workflows`.
2. OCR bill capture is an OPTIONAL module on the `[cv]` extra with graceful fallback to manual entry.
3. `oe_saved_views`: scoper MANDATORY at registration, filterable/sortable columns whitelisted per
   entity, hard row/time budget (or EXPLAIN-cost guard).
4. CI/pre-commit gate on the competitor brand token - automated, not "the reviewer will remember".
5. Scheduler default = the existing in-process task path with graceful degradation without Redis.
6. `finance` Chart of Accounts: backfill migration for the existing live `LedgerEntry.account_code`
   (`String(100)`) into the COA, FK added via data-migration (map or quarantine orphan codes);
   `server_default` on new columns (create_all ignores Python defaults on existing dev DBs).
7. Tests-FIRST for money math.

## Top features (globally-needed, mapped to our modules)

Effort: S=days, M=weeks, L=month+, XL=multi-quarter. Phase = build order.

| Pri | Capability (neutral) | Connects to our modules | Effort | Build/Extend | Phase |
|-----|----------------------|-------------------------|--------|--------------|-------|
| P0 | record-level saved-search / saved-views engine | feeds dashboards, bi_dashboards, reminders, automation, exports; unifies smart_views + file_saved_views + snapshot filters + KPI sources | L | build `oe_saved_views` | 1 |
| P0 | GL: chart of accounts + financial statements + period close | finance ledger, costmodel, contracts, reporting | M | extend `finance` | 1 |
| P0 | global command palette + recent records | search fan-out, all modules | S | extend `search` | 1 |
| P0 | CI/pre-commit trademark gate | repo-wide guardrail | S | build (CI) | 1 |
| P1 | percentage-of-completion rev-rec + WIP schedule (our flagship) | contracts, finance, costmodel, projects, EVM | M | build `oe_revrec` | 2 |
| P1 | change-order-to-budget + dual-sided retainage | contracts, change-orders, variations, finance | S | extend `contracts` | 2 |
| P2 | role-based home dashboard + reminders portlet | dashboards, bi_dashboards, oe_saved_views | M | extend `dashboards` | 3 |
| P2 | no-code workflow automation (trigger-condition-action) | thin layer over `oe_approval_routes`; all records | M | build over `oe_approval_routes` | 3 |
| P2 | unified mapped CSV import + validation dry-run | validation engine, costs/boq/vendors/equipment, all modules | M | build `oe_import` | 3 |
| P2 | policy-driven procurement routing + vendor scorecards | procurement, governance, subcontractors | S | extend `procurement` | 3 |
| P3 | 3-way PO/GRN match + batch payment runs | finance, procurement | M | extend `finance`+`procurement` | 4 |
| P3 | OCR bill capture (optional `[cv]`) | finance/procurement; graceful manual fallback | M | optional module | 4 |
| P3 | rule-based bank reconciliation | finance ledger | M | extend `finance` | 4 |
| P3 | natural-language analytics + AI writing assist | ai_agents + oe_saved_views; rfi/claims | M | extend `ai_agents` | 4 |
| P3 | recurring/scheduled billing | finance + scheduler; service/equipment/accommodation | S | extend `finance` | 4 |
| P4 | fixed-asset depreciation journals | equipment + finance | M | extend `equipment`+`finance` | 5 |
| P4 (defer) | multi-entity/multi-currency consolidation | finance, projects | XL | build `oe_consolidation`, demand-gated | 5 |
| P4 (defer) | FP&A: driver budgets, scenarios, rolling forecast | finance, costmodel, boq; map vs existing eac/full_evm | XL | build `oe_fpa`, demand-gated | 5 |
| P4 (defer) | per-record activity timeline | claims/disputes accountability | M | build `oe_activity`, opt-in | 5 |

## New module specs

### `oe_saved_views` (P0, Phase 1) - keystone
- Depends: `oe_users`, `oe_projects`.
- Purpose: record-level no-code query engine over a registry of queryable entities; one saved view
  (filters/columns/grouping/sort) reused as list, dashboard tile, reminder count, export, automation
  trigger. Unifies smart_views, file_saved_views, snapshot filters, KPI sources.
- Functions: `register_queryable_entity(entity_type, field_registry, scoper)` (scoper MANDATORY;
  registration without one is rejected), `run_view(view_id, ctx) -> Page[record]` (with drill refs),
  `save_view(owner, entity_type, spec, share_scope)`, `count_for_reminder(view_id, ctx)`,
  `to_export(view_id, fmt)`.
- Guardrails: column whitelist per entity; hard page-size cap; no grouping on non-indexed columns;
  hard row/time budget; scoper enforced server-side always. Shared core engine; file_saved_views and
  smart_views keep their specialized UIs but share the engine.

### `oe_revrec` (P1, Phase 2) - flagship (generic ERP lacks this natively)
- Depends: `oe_contracts`, `oe_finance`, `oe_costmodel`, `oe_projects`.
- Purpose: cost-to-cost percentage-of-completion + WIP (over/under-billing) schedule. Reads existing
  inputs (contract value, budget cost-to-complete, EVM, certified claims as billings); posts
  revenue/deferred-revenue journals to the append-only ledger. Methods: cost-to-cost POC,
  completed-contract, fixed-amount.
- Functions: `compute_percent_complete(project_id, contract_id, method)`, `build_wip_schedule(
  project_id, period) -> WipRow[]` (earned_revenue, cost_incurred, billed_to_date, over_under),
  `post_revrec_journals(project_id, period) -> LedgerEntry[]` (append-only), `suggest_cost_to_complete
  (project_id) -> Forecast(value, confidence)` (human-confirmed).
- Guardrails: single-currency-per-recognition-run (refuse to compute POC across blended currencies);
  no silent auto-post even at period close (explicit "confirm WIP & post" action); forecasts always
  confidence-scored.

### `oe_import` (P2, Phase 3) - unified import
- Depends: `oe_validation`, `oe_users`.
- Purpose: one CSV/spreadsheet import for any entity: upload -> map columns -> saved reusable
  mappings -> dry-run through validation -> commit with per-row error report + audit note. AI
  suggests mapping with confidence; human confirms.
- Functions: `register_importable(entity_type, field_schema, committer)` (committer MANDATORY; commit
  goes THROUGH the module service, never raw INSERT), `infer_mapping(file_sample, entity_type) ->
  Mapping(confidence)`, `dry_run(import_id) -> RowResult[]`, `commit(import_id) -> ImportReport`,
  `save_mapping(name, entity_type, mapping)`.
- Guardrails: streaming/chunk read with row/cell caps and max upload size; never load the whole sheet
  into RAM.

### Deferred (demand-gated, do NOT build speculatively)
- `oe_consolidation` (XL): legal-entity hierarchy; entity-dimension must be nullable so single-entity
  installs pay zero complexity.
- `oe_fpa` (XL): map against existing `eac` (simpleeval) / `full_evm` / `project_controls` first to
  EXTEND not create a 4th forecast store; reuse the existing simpleeval evaluator.
- `oe_activity` (M, opt-in): per-record activity timeline.

## Extend-existing specs

### `finance` (Phase 1-4)
- `ChartOfAccount` (hierarchical account_code, account_type, parent) + `AccountingPeriod` (open/closed
  lock). Backfill migration: COA + AccountingPeriod first, backfill/validate existing
  `LedgerEntry.account_code` into COA, then FK via data-migration (map or quarantine orphans);
  `server_default` on new columns.
- Statement service: trial balance, income statement, balance sheet, cash-flow with comparative
  periods + budget-vs-actual; drill from statement line to source.
- Period-close lock in the posting service (single writer), not a DB trigger.
- Later: bank reconciliation, 3-way PO/GRN match, batch payment runs, depreciation journals,
  recurring billing templates.

### automation -> over `oe_approval_routes` (Phase 3)
Build the no-code trigger-condition-action layer on top of `oe_approval_routes` (core, auto_install,
already consumed by markup/submittal/change-order/RFI/contract). Do NOT fork `oe_enterprise_workflows`.

### `search` (Phase 1)
Global command palette + recent records over the existing search fan-out.

### `dashboards` (Phase 3)
Role-based home dashboard + reminders portlet, tiles driven by `oe_saved_views`.

## Roadmap & progress

Tick `[x]` as each FULL vertical slice lands; append a dated note to the Progress log.

### Phase 1 - Keystone + financial spine
- [ ] CI/pre-commit trademark gate (fail build on competitor brand token) + docs
- [ ] `oe_saved_views` module (engine, registry, mandatory scoper, column whitelist, budget) + tests + i18n
- [ ] Adapt `smart_views` + `file_saved_views` + snapshot filters + KPI sources onto the shared engine
- [ ] `finance` ChartOfAccount + AccountingPeriod models + backfill migration (account_code -> COA, FK) + tests-first
- [ ] `finance` statement service (trial balance, P&L, balance sheet, cash-flow, drill-down) + tests + i18n
- [ ] `finance` period-close lock in posting service + rejection tests
- [ ] global command palette + recent records (extend `search`) + frontend + tests
- [ ] C1 schedule-quality check pack (logic/float/constraint metrics + health score) over validation + tests + i18n
- [ ] C9 signature-authority routing (amount-band -> approver tier) on `oe_approval_routes` + tests

### Phase 2 - Flagship: revenue recognition + contract billing
- [ ] `oe_revrec` module (POC %, WIP schedule, append-only journals, confidence forecast) - tests-FIRST for money math
- [ ] `oe_revrec` frontend: WIP report + "confirm WIP & post" flow (no silent auto-post) + i18n
- [ ] `contracts` change-order-to-budget + dual-sided retainage (AR+AP) + tests
- [ ] C4 lien-waiver state machine (conditional -> unconditional on confirmed disbursement) + coverage gate + tests
- [ ] C5 compliance-document register -> auto pay-application HOLD + expiry alerts + tests
- [ ] C7 schedule-of-values sheet (auto from signed commitment, drawn by pay-apps, certified-to-date) + tests + i18n

### Phase 3 - Convenience UX layer
- [ ] role-based home dashboard + reminders portlet (extend `dashboards`, driven by saved_views) + i18n
- [ ] no-code workflow automation (trigger-condition-action over `oe_approval_routes`) + tests
- [ ] `oe_import` unified mapped CSV import + validation dry-run + streaming caps + tests + i18n
- [ ] procurement policy-driven routing + vendor scorecards (extend `procurement`) + tests
- [ ] C3 schedule revision compare over snapshots (activities/links/assignments diff + impact) + tests + i18n
- [ ] C6 cost-control spreadsheet (CBS x source columns + formula columns + worksheets) + tests + i18n
- [ ] C10 CDE attribute-driven distribution matrix + configurable auto-numbering + tests + i18n

### Phase 4 - AP depth + analytics
- [ ] 3-way PO/GRN match + batch payment runs (finance+procurement) + tests
- [ ] OCR bill capture (optional `[cv]` module, graceful manual fallback)
- [ ] rule-based bank reconciliation (finance) + tests
- [ ] natural-language analytics + AI writing assist (ai_agents + saved_views)
- [ ] recurring/scheduled billing (finance + scheduler)
- [ ] C2 network Monte Carlo (QSRA) over `cpm.py` (P50/P80/P90 finish+cost, criticality) + tests
- [ ] C8 multi-curve cash flow + reusable distribution-curve templates + curve-accurate planned value + tests
- [ ] C11 subcontractor self-service portal (line-level pay-app + GC certification) + tests + i18n
- [ ] C12 schedule leveling depth (SS/FF/SF + resource calendars + leveling priorities) + tests

### Phase 5 - Enterprise (demand-gated, deferred)
- [ ] fixed-asset depreciation journals (equipment+finance)
- [ ] `oe_consolidation` (only on paying enterprise/JV demand; nullable entity dimension)
- [ ] `oe_fpa` (only after mapping vs eac/full_evm/project_controls)
- [ ] `oe_activity` per-record timeline (opt-in)
- [ ] C13 funding manager (sources -> appropriation -> commitment consumption) - greenfield, demand-gated
- [ ] C14 capital portfolio planning (scenarios, weighted scoring, stage-gates) - greenfield, demand-gated
- [ ] C15 configurable business-process record engine (no-code form + workflow designer) - shares Phase-3 automation designer

## MERGED - construction project-controls benchmark (neutral-named adopt list)

Source: internal benchmark of a major vendor's construction + project-controls + cloud-ERP portfolio
(7-agent workflow + adversarial critique, landed 2026-06-08). Brand rule applies - everything below is
neutral-named only. Verdict was GO-conditional; the first blocking condition is the brand-denylist CI
gate (already Phase 1 item 1). Code-verified reuse: our `cpm.py` handles all four PDM link types
(FS/SS/FF/SF) with lag on the standard library (no scipy/networkx); `risk/service.py.simulate` already
runs PERT Monte Carlo (random.triangular) up to 100k iterations without numpy; costmodel/finance/
contracts/subcontractors entities exist. So most of the incumbent's visible edge is presentation and
orchestration over data we already hold, plus three genuinely greenfield bets (funding manager,
capital portfolio planning, configurable record engine).

Top adopt list, sorted by leverage (cheap reuse over what we already own first):

| # | Feature (neutral name) | Construction value | Effort | Build/Extend |
|---|---|---|---|---|
| C1 | Schedule-quality check pack (logic/float/constraint metrics + 0-1 health score) | Clean, defensible schedule is a standard owner/audit gate on public work | S | EXTEND core/validation + schedule |
| C2 | Network Monte Carlo (QSRA) over `cpm.py` (P50/P80/P90 finish+cost, criticality index) | Defensible contingency for bids and delay claims | M | EXTEND risk + schedule_advanced |
| C3 | Schedule revision compare over snapshots (added/edited/deleted activities, links, assignments) | Planners' most-requested feature: what changed between revisions + impact | M | EXTEND schedule (snapshot_data exists) |
| C4 | Lien-waiver state machine (conditional -> unconditional on confirmed disbursement) + coverage gate | Solves lien-law chicken-and-egg, legally load-bearing | S | EXTEND subcontractors + finance |
| C5 | Compliance-document register -> auto pay-application HOLD + expiry alerts | GC must verify compliance before paying (esp. public jobs) | S | EXTEND subcontractors |
| C6 | Cost-control spreadsheet (CBS rows x source columns: original/changes/current budget, committed, actual, forecast + formula columns + worksheets) | Our largest presentation gap vs the incumbent | M | EXTEND costmodel/project-controls |
| C7 | Schedule-of-values sheet (auto-built from signed commitment, drawn down by pay-apps, certified-to-date) | Backbone of subcontractor billing | M | EXTEND contracts/subcontractors |
| C8 | Multi-curve cash flow (baseline/spend/forecast/custom) + reusable distribution-curve templates + curve-accurate planned value | Replaces today's naive straight-line EVM with real S-curves | M | EXTEND costmodel + finance |
| C9 | Signature-authority routing (amount-band -> approver tier) | Real delegation-of-authority on commitments/changes | S | EXTEND oe_approval_routes (add amount_min/max/condition) |
| C10 | Attribute-driven distribution matrix + configurable auto-numbering for the CDE | Routes documents by type/discipline/role; governed numbering | M | EXTEND cde/transmittals/file_distribution |
| C11 | Subcontractor self-service portal (line-level pay-application + GC certification) | Removes email/spreadsheet pay cycles | M | EXTEND subcontractors + portal |
| C12 | Schedule leveling depth (SS/FF/SF + resource calendars + leveling priorities) | Today leveling is FS-only (SS/FF/SF are TODO) | M | EXTEND schedule_advanced/leveling |
| C13 | Funding manager (sources -> appropriation -> commitment consumption) | Fund accounting on top of the GL (greenfield) | L | NEW oe_funding (defer, demand-gated) |
| C14 | Capital portfolio planning (scenarios, weighted scoring, constrained mix, stage-gates) | Owner/program-level planning above projects (greenfield) | XL | NEW (defer, demand-gated) |
| C15 | Configurable business-process record engine (no-code form + workflow designer) | Long tail of owner-specific documents; pairs with no-code automation | XL | NEW oe_records (defer; share designer with Phase-3 automation) |

Slotting into the existing phases (cheap reuse banked before any XL bet):
- Phase 1 (alongside finance spine): C1 schedule-quality check pack, C9 signature-authority routing.
- Phase 2 (alongside revrec/billing): C4 lien-waiver FSM, C5 compliance register holds, C7 SOV sheet.
- Phase 3 (alongside convenience UX): C3 revision compare, C6 cost-control spreadsheet, C10 CDE
  distribution + numbering.
- Phase 4 (analytics/depth): C2 network Monte Carlo, C8 multi-curve cash flow, C11 sub portal, C12
  leveling depth.
- Phase 5 (enterprise, demand-gated): C13 funding manager, C14 capital portfolio, C15 record engine.

Incident to clean up separately: `cde/models.py` docstrings contain zero-width unicode that can break
i18n extraction/grep. Build (not reuse) work flagged by the benchmark: tamper-evident hash-chain for
correspondence/transmittal (our LedgerEntry is append-only by convention + reversal-link but has no
hash columns).

## Progress log (append-only)
- 2026-06-08: Plan created from the mature-ERP benchmark (7-agent workflow + adversarial critique).
  Decisions and guardrails locked. Construction-suite benchmark pending merge. No code written yet.
  Next: Phase 1 - CI trademark gate, then `oe_saved_views`, then finance COA/statements.
- 2026-06-08: Founder directive - clarity/usability is mandatory. Added "In-product guidance & UX"
  as a first-class definition-of-done item for every feature (intro/empty states, field-level
  plain-language help + finance glossary, guided first run, explanatory errors, self-explaining AI).
  Same standard mirrored into POINTCLOUD_AND_SPATIAL_PLAN.md.
- 2026-06-08: Founder directives - (a) translate every new string into all 27 locales in the same
  change (verify via i18n-diff.cjs, zero needfix); (b) the main quality bar is thorough testing
  through real clicks + screenshots + screenshot analysis, 3 to 4 deep passes. Added the "TRANSLATED
  EVERYWHERE" and "TESTED FOR REAL" bars and a dedicated "Verification & testing gate" section. Built
  the reusable harness `frontend/qa-tests/ux-acceptance.mjs` (real demo-UI login -> smoke / interact /
  i18n / guidance passes -> per-module screenshots + report.json).
- 2026-06-08: Construction project-controls benchmark (workflow wnqsr6e1y) landed. Merged its
  neutral-named adopt list (C1-C15) into the phases above; cheap reuse (schedule-quality, lien-waiver
  FSM, compliance holds, SOV, signature-authority) banked before the three greenfield XL bets.
- 2026-06-08: First deep acceptance pass on boq/finance/ai-estimator (4 locales incl. RTL+CJK).
  Visual finding: i18n is genuinely complete (Arabic fully RTL-mirrored, Japanese fully translated
  incl. intro banners), module intro banners + empty-states already shipped platform-wide. The real
  platform gap is field-level "what's this" help on jargon (finance: COA/committed/forecast/EVM/WIP),
  a shared glossary, and re-launchable guided tours - not intros/i18n/empty-states. This sharpens the
  platform-UX audit (workflow wxbd9vv0w).
