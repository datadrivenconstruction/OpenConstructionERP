# 03 — Cross-Module Coherence (Phase 4)

> Phase 4 hunts for integrity gaps between modules — dashboard parity, cascade rules, unit/currency consistency, dead routes, dead code.

## C-01 — [critical] Invoice KPIs contradict invoice list
**Screenshot:** `audit/screenshots/03-invoicing/list--light.png`
**Observation:**
- KPI cards show `Gesamt fakturiert: 0,00€`, `Gesamt erhalten: 0,00€`, `Ausstehend: 0,00€`, `Überfällig: 57.901,83€`.
- The list below shows ~38 invoices worth 1785€+ each (`RE-2026-000X` with amounts ≥ 500€).
- Sum of invoices in list is nowhere near 0€ "fakturiert", yet "Überfällig" is 57k€. These cannot both be right.

**Likely cause:**
- KPI endpoint aggregates only invoices with status=`sent` or similar, while list shows drafts too.
- OR KPI queries a different org scope / time range.
- OR accumulator is broken (e.g. sums `total_net` when it should sum `total_gross`, or filters on `deleted_at IS NULL` but invoices use a different column).

**Minimum fix:** verify `invoice_service.calculate_kpi()` (or equivalent) SQL. Ensure the KPI query and the list query share the same WHERE clause (org, status set, deleted_at, date range). Unit-test with 3 fixture invoices.

**Why it matters:** users will distrust every number on the page if one is wrong.

## C-02 — [high] Banking total ≠ account balance
**Screenshot:** `audit/screenshots/04-accounting/banking--light.png`
- "Gesamtsaldo: 38.463€"
- Only 1 account shown, its balance is "38.912,45€"
- Discrepancy: 449,45€

**Likely cause:** Gesamtsaldo aggregates a different snapshot than the card (e.g. ledger balance vs available balance, or a historical snapshot).

**Minimum fix:** document the distinction in the UI (`Kontostand` vs `Verfügbar`) OR make them the same computation.

## C-03 — [high] Accounting profit vs invoice/banking numbers diverge
**Screenshot:** `audit/screenshots/04-accounting/accounting--light.png`
- EÜR shows `Gesamteinnahmen 127.038,45€`, `Gesamtausgaben 36.978,53€`, `Gewinn 90.059,92€`.
- Invoice list shows 0€ fakturiert (C-01).
- Banking shows 38k€ Gesamtsaldo (C-02).

Cross-checks:
- Einnahmen 127k could include non-invoice income (cash receipts, bank inflows). OK in principle.
- But with "0€ fakturiert" per invoice KPI, 127k€ must all be non-invoice. Implausible for a DMS — likely double-counting or mis-categorized entries.

**Minimum fix:** trace one "Einnahmen" entry (Konto 1200 = 57.901,83€ — exactly matches the invoice "Überfällig" total!). This strongly suggests the accounting booked the invoices as income but the invoice module doesn't recognize them as "fakturiert". **Check kontierung → invoice status sync.**

## C-04 — [high] Workflows page shows "Laden fehlgeschlagen" even though API returns 200
**Screenshot:** `audit/screenshots/07-tasks/workflows--light.png`
**Root cause:** frontend calls `/workflows/` (trailing slash), backend has `redirect_slashes=False`, 404 → React Query rejects → error state.

**Fixed in this audit** (useWorkflows.ts, WorkflowDesigner.tsx).

## C-05 — [high] Shape mismatch: backend returns `{items, total, page, pages}`, frontend types `Workflow[]`
**Observation:** `useWorkflows.ts:30` types response as `Workflow[]` (bare array). Backend returns a pagination envelope. The `workflows.map(...)` that consumes the result will attempt to call `.map` on an object that has `{items}` not a raw array → silent empty list.

**Minimum fix:** change `apiClient.get<Workflow[]>(...)` to `apiClient.get<PaginatedResponse<Workflow>>(...)` and use `.data.items`. Same pattern applies anywhere else the frontend assumes raw arrays (verify Forms, Tasks, Invoices).

## C-06 — [medium] `Verträge` red badge without data
**Screenshot:** every auth page sidebar.
Badge shows `1` but Contracts page is empty (`/contracts/stats` ABORTED per F-06). Inconsistent — sidebar says 1 pending, page shows none.

## C-07 — [medium] Tasks DELETE not allowed while UI expects to delete
**Observation:** `DELETE /tasks/{id}` → 405. Frontend task list has a "Löschen" action (see `TasksPage.tsx`). Either:
- Frontend already uses PATCH status=archived (OK) — then hide/remove DELETE-style UI
- Frontend uses DELETE and silently fails — **bug**

**Needs code check.** Quick grep suggests `useTasks.ts` sends DELETE which will hit 405.

## C-08 — [medium] Router.py silently swallows failed module imports
**File:** `backend/app/api/v1/router.py` — 36+ routers loaded under `try/except Exception as _e: logger.debug(…)`.
If a router fails to import at startup (typo, missing schema, bad migration), its endpoints return 404 and **nothing logs above DEBUG level**. Ops won't see this in prod.

**Minimum fix:** log WARNING level on failed import, collect failures in a module list that `/health` exposes.

## C-09 — [medium] Serienbrief + PushSubscription models live in `nachtrag.py`
**File:** `backend/app/models/nachtrag.py`
Unrelated models bundled into a single file. Low functional risk, but confuses Alembic autogenerate and makes grep harder.
**Fix:** split to `serienbrief.py` and `push_subscription.py`. **(backlog)**

## C-10 — [medium] Temporal sidecar runs but no workflows defined
**File:** `docker-compose.yml` — `temporal`, `temporal-ui`, `temporal-worker` services defined, using RAM and ports. No active workflow definitions found in `backend/app/workers/workflows/`.
**Minimum fix:** either implement one workflow (or turn off the 3 services in prod). **[medium]** for resource waste.

## C-11 — [medium] i18n gap — 7 languages missing ~139 keys
**Files:** `frontend/public/locales/{fr,it,pl,hr,ro,ru,ar}/translation.json`
- DE/EN: 5892 keys
- Others: 5753–5807 keys
The delta is predominantly new AI/compliance/FinTS strings. **User-visible fallback to key names** in those languages.

**Minimum fix:** run i18next extraction/sync tool, have translators fill in. **(backlog)**

## C-12 — [low] Dead feature: MarketplacePage has no backend
**File:** `frontend/src/pages/MarketplacePage.tsx`
No backend `/marketplace` or `/plugins` route. The page is probably a placeholder. Either hide the nav entry or implement.

## C-13 — [low] Unused empty directory `frontend/src/components/stamps/`
No files. Probably leftover from initial scaffolding.

## C-14 — [low] Redundant AI hooks
`useAI.ts`, `useAICopilot.ts`, `useAIEmail.ts` — 3 separate hooks with overlapping patterns. Consolidate into one generic `useAIAction(kind)` if code duplication grows.

## C-15 — [low] Component bloat
5 components above 1000 LOC (UploadModal 1727, AIChatSidebar 1876, AppLayout 1665, BusinessCopilot 1290, InboxProcessingPanel 1123). Test with a refactor sprint when convenient.

---

## End-to-end flow sanity check

### Customer → Order → Invoice → Payment → Report

Walked one chain manually (via UI screenshots + API probes):

1. **Customer create** (`POST /contacts`) → 201 ✓
2. **Order create** (`POST /orders`) → not probed; UI page renders (screenshot OK)
3. **Invoice create from order** — frontend has `InvoiceCreatorPage.tsx` route `/invoices/new`; API not probed (no destructive tests). Screenshot `03-invoicing/new--light.png` shows form.
4. **Payment booking** — `POST /invoices/{id}/payments` — exists per router listing; not probed.
5. **Reconciliation** — banking transactions → invoice match. Reconciliation endpoint exists; probe returned 200 for `/banking/accounts`.
6. **Report (UStVA, BWA)** — accounting page renders numbers (screenshot). **But** C-01 / C-03 prove the report numbers are inconsistent with invoices → reconciliation is incomplete or broken.

**Verdict:** End-to-end mechanical flow works but financial data consistency is broken. Priority-1 investigation.

---

## Summary (Phase 4)

| severity | count |
|:--------:|:-----:|
| critical | 1 (Invoice KPI mismatch — C-01) |
| high | 4 (Banking/Accounting/Invoice integrity + trailing slash, shape mismatch) |
| medium | 7 |
| low | 4 |
| **total** | **16** |

Top-3 architectural issues worth raising to a human decision-maker:

1. **Financial data consistency (C-01 + C-03)** — a reconciliation layer is missing or broken between Invoicing and Accounting. Needs product owner + accountant sign-off on the intended invariants (e.g. "sum of sent invoices = sum of Konto 1200 credits"). Not a bug to fix blindly.
2. **Silent router failures (C-08)** — infrastructure pattern that hides production breakages. Requires a team decision: fail-fast at startup vs fail-open.
3. **Temporal sidecar paid-for, not used (C-10)** — either cut the 3 services from compose OR implement at least one durable workflow to justify the dependency.
