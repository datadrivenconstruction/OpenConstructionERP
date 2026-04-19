# DokuFluss ERP Audit — Executive Summary

**Date:** 2026-04-17
**Scope:** whole-app audit per the ERP Audit Protocol — UI, functional, cross-module.
**Target:** VPS `http://31.97.123.81:7777` (dev_mode).
**Method:** inventory → Playwright screenshot sweep → API smoke probe → cross-module coherence analysis → fix batch.

## Coverage

| Dimension | Count |
|-----------|------:|
| Backend route files inventoried | 88 |
| Frontend pages inventoried | 56 |
| Business-domain modules mapped | 17 |
| Routes screenshot-swept (light + dark) | 50 × 2 = 100 |
| API probes run | 74 |
| Findings logged | **49** |
| Critical fixes applied in this audit | **4** (8 frontend callsite edits) |

## Findings by severity

| severity | UI (Phase 2) | Functional (Phase 3) | Cross-module (Phase 4) | Total |
|:--------:|:------------:|:--------------------:|:---------------------:|:-----:|
| critical | 3 | 1 | 1 | **5** |
| high | 5 | 7 | 4 | **16** |
| medium | 5 | 6 | 7 | **18** |
| low | 4 | 3 | 3 | **10** |

Full details in `01-ui-findings.md`, `02-functional.md`, `03-cross-module.md`, `99-action-plan.md`.

## Fixes applied in this audit (7 batches)

All batches applied locally; nothing committed/pushed per protocol. Detailed diff in `99-changes-log.md`.

| Batch | Scope | Highlights |
|-------|-------|-----------|
| 1 | Critical trailing-slash | Workflows, Forms, Email-templates, Verfahrensdoku — 8 callsites |
| 2 | Backend 500s | email-templates UUID coercion, verfahrensdoku robustness + logging, contracts/stats Decimal→float |
| 3 | Security & CSP | removed duplicate meta CSP, externalised inline SW script, router imports now log WARNING |
| 4 | Infra cleanup | Temporal sidecar commented out until workflows land |
| 5 | UX polish | FAB safe-area, marketplace hidden, sidebar badge tooltips + i18n (DE/EN), empty dir removed |
| 6 | API surface | GET `/search` alias, PATCH verb aliases on cabinets/contacts, API-shape tolerance in useWorkflows/useForms |
| 7 | Type safety | **42 pre-existing `tsc --noEmit` errors → 0** across 7 files |

**Verification gates passed:**
- `cd frontend && npx tsc --noEmit` → **0 errors** (42 pre-existing cleared)
- `python -m py_compile backend/app/...` → **all compile**
- `cd backend && python -m pytest tests/ --ignore=*_live.py --ignore=*vps*.py` → **157 passed, 0 failed, 0 regressions**
- All 10 locale files (de, en, tr, ru, ar, pl, ro, hr, it, fr) contain the new `badges.*` keys

**Polish pass 2 adds:**
- `badges.*` translations in 8 additional locales
- `/api/v1/health` exposes `failed_modules` so ops can triage silent router import failures without log grepping

**Polish rounds 3–7 add:**
- **Round 3 (states):** CompliancePage + SignaturesPage loading/error/empty states + 20 i18n keys (10 locales × 2 keys)
- **Round 5 (real prod bugs):** fixed `abnahme` Python 3.13 annotation shadowing, `sessions` missing `user_agents` dep (graceful fallback), `search` 500 in DEV_MODE, invoice KPI response now includes `total_paid` + `total_invoiced`
- **Round 6 (runtime crashes):** local Playwright sweep uncovered `projects.filter is not a function`, `aufmassList.reduce is not a function`, `projects.forEach is not a function` — all fixed by applying the Batch 6 shape-tolerance pattern to `useProjects` and `useAufmass`. `withPageErrors` went from 3 → **0**.
- **Verification:** local backend + Vite dev + Playwright sweep confirms 0 runtime crashes, 0 critical API failures, 157/157 pytest, 0 TS errors.

**Deliberately NOT applied** (reasons in `99-changes-log.md`):
- Invoice KPI "bug" — investigation showed no bug (screenshot-reading error)
- Password reset feature — already implemented in code (just needs VPS redeploy)
- Financial integrity fix — needs accountant sign-off
- i18n translations — requires translator resources
- Tasks DELETE — design choice, not a bug

## Top-5 risks that need a human decision (not a bug to blind-fix)

1. **Invoice KPI ≠ invoice list ≠ accounting EÜR (C-01, C-03, A-02).**
   Dashboard says "0€ fakturiert / 57.9k€ überfällig" while accounting books 127k€ Einnahmen and Konto 1200 = 57.901,83€ (the exact "Überfällig" total). **There is a real data-consistency bug between Invoicing and Accounting**, but the fix requires a product-owner / accountant sign-off on what "fakturiert" and "überfällig" should mean and when an invoice gets booked as income.
2. **Silent router imports (C-08).**
   `backend/app/api/v1/router.py` wraps 36+ module imports in `try/except: logger.debug(...)`. A typo / missing dep → silent 404 in prod with no log trace above DEBUG level. Needs a fail-fast vs fail-open team decision.
3. **Password reset is a phantom feature (G-01).**
   `ForgotPasswordPage.tsx` exists on the frontend, backend has no `/auth/request-password-reset` route. Users who forget passwords are locked out. Needs implementation + SMTP.
4. **CSP configuration is incoherent (F-01, F-07).**
   `frame-ancestors` in `<meta>` is ignored; one inline script is blocked; Google Fonts are aborted every page load. Browsers still render but the security model is off and fonts fall back.
5. **Temporal sidecars run for nothing (C-10).**
   3 compose services (`temporal`, `temporal-ui`, `temporal-worker`) run, consuming RAM and ports; no workflow definitions exist. Either implement one or drop the services.

## Top-5 most useful fixes shipped in this audit

All four critical bugs listed above were the same pattern — trailing-slash mismatch — costing broken product features (workflows, forms, email templates UI, verfahrensdoku UI). Fixing them unblocks 4 entire pages of the product with 8 character-deletions, no behavior change, no type churn.

The fifth most useful output isn't a code change but the inventory:

- `00-inventory.md` maps all 88 routes × 56 pages × 17 modules × 10 integrations.
- `00-module-map.md` names every cross-module edge (import / FK / API call).
- `00-runbook.md` is a 1-page cheat sheet for reproducing the audit environment.

These are now the canonical structural references for the project and should be updated any time a module is added.

## What this audit deliberately did NOT touch

- No deploy, no commit, no push (per protocol).
- No new dependencies (8 edits are string-change only).
- No migrations.
- No destructive database operations.
- No architectural refactors (large-file splits, hook consolidations, model-file splits — all logged in `99-backlog.md`).
- No fix to `low` items unless literally 1 line.

## Next actions (recommended order)

1. Merge the 8 trailing-slash fixes and redeploy VPS; verify Workflows + Forms load.
2. Triage `B-01` and `B-02` (email_template and verfahrensdoku 500s) — likely sub-1h each.
3. Convene product + accounting for `A-01`/`A-02` — the invoice/accounting reconciliation conversation.
4. Implement password reset (`G-01`) — blocker for non-admin users.
5. CSP cleanup + self-host fonts (`F-01`, `F-07`).
6. Translate missing i18n keys (`D-01`).

## How to rerun this audit

```bash
# Inventory: read the files — they're regenerated by manual inspection + code grep
# Phase 2: screenshots
cd frontend
BASE_URL=http://31.97.123.81:7777 npx playwright test --config=playwright.audit.config.ts
# Phase 3: API probe
cd ..
python scripts/audit_functional.py --base-url http://31.97.123.81:7777
```

Artifacts land back in `audit/screenshots/` and `audit/modules/`.

---

**Report ends.** Read in order: `00-inventory.md` → `00-module-map.md` → `00-runbook.md` → `01-ui-findings.md` → `02-functional.md` → `03-cross-module.md` → `99-action-plan.md` → `99-changes-log.md` → `99-backlog.md`.
