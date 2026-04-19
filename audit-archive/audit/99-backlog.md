# 99 — Backlog

> Deferred work from this audit. Does NOT fit the "one-line fix" ceiling OR requires product/architecture decisions.

## Backend bugs to investigate

### B-01 — `GET /api/v1/email-templates` returns 500
**Suspect:** `backend/app/services/email_template_service.py:160-193` in `list_templates()`. Returns `EmailTemplateResponse(id=uuid.UUID(...))` — if the schema's `id` field is typed `str`, Pydantic v2 will serialize-fail on dump. Likely quick fix: `str(uuid.uuid5(...))`.

### B-02 — `GET /api/v1/verfahrensdoku` returns 500
**Suspect:** service throws unhandled exception. Read `backend/app/services/verfahrensdoku_service.py` and correlate with logs.

### B-03 — `/api/v1/contracts/stats` ABORTED (net error, not HTTP error)
**Suspect:** endpoint exists but fails mid-request; frontend aborts. Investigate `backend/app/api/v1/contracts.py` for a path like `/stats`.

### B-04 — 42 pre-existing TypeScript errors
`npx tsc --noEmit` reports 42 errors BEFORE my fixes (none introduced by this audit). Biggest offender: `src/pages/QMPage.tsx` (~15 implicit-any, checklist-item type mismatch).
**Impact:** `npm run build` likely passes (Vite is more lenient than tsc), but strict CI would reject. CLAUDE.md states "0 errors always" — this is a regression baseline the team should clear before next release.
**Files:** mostly `pages/QMPage.tsx` lines 290-500.

## Architecture decisions (need a human)

### A-01 — Invoice KPI vs list inconsistency
The KPI on `/invoices` says "0€ fakturiert" while the list has 38 invoices worth ≥1k€ each and 57901.83€ "Überfällig". Owner decision: what invariants should hold?
- KPI's "fakturiert" = ?
  - all with `status != draft` → currently UI has all as Entwurf (draft)
  - OR sum of `total_gross` for invoices with status = sent/paid
- Either way the KPI query and the list query must share the same filter.

### A-02 — Accounting vs Invoicing reconciliation
Accounting EÜR shows 127k€ Einnahmen, with Konto 1200 = 57.901€ — **matches** the "Überfällig" invoice total. Strongly suggests: invoice → kontierung writes an income entry but the invoice is never moved out of draft. Needs an accountant's sign-off on the intended flow.

### A-03 — PATCH vs PUT vs DELETE method semantics
3 modules (cabinets, contacts, tasks) return 405 for PATCH/DELETE. Either:
1. Backend doesn't support those verbs and frontend is wrong
2. Or backend should support them
Decide once and align everywhere.

### A-04 — `/search` should accept GET
REST convention for idempotent queries. Adding GET is 10 lines.

### A-05 — Silent router imports
`router.py` wraps 36+ imports in `try/except: logger.debug(...)`. Startup failures become invisible 404s. Decide:
- Fail fast (crash on first import error) — typical for monoliths
- Expose failures via `/health` — already partial; just raise log level to WARNING

### A-06 — Temporal sidecars with no workflows
3 compose services (temporal, temporal-ui, temporal-worker). No workflow definitions. Either implement one or drop the services.

## Content / data decisions

### D-01 — i18n gap (7 languages × ~139 keys)
Keys on DE/EN that others lack. Need either:
- Translator resources
- Auto-translation pass (DeepL/Google) then human review
- OR scope-limit: "ship with DE+EN+TR for Turkish market; add others as customers request"

### D-02 — Demo data hygiene
VPS accumulated ~50 `Audit-Kontakt` contacts and ~10 duplicate `test_audit.txt` documents. One-off cleanup.

### D-03 — Richer demo seed
Current demo: one fake Max Mueller + 3 accounts + mostly identical test files. A richer seed would produce much better first impression.

## Feature gaps (known but not implemented)

### G-01 — Password reset backend
Frontend `ForgotPasswordPage.tsx` exists, no backend wiring.
Endpoints to add:
- `POST /auth/request-password-reset {email}` → sends email with token
- `POST /auth/reset-password {token, new_password}` → sets password
Needs SMTP configured (email already has broadcast infrastructure).

### G-02 — DATEV export completeness
Memory notes from prior audit: "DATEV export incomplete". Not re-verified this round.

### G-03 — MFA in login flow
Backend supports MFA; login screenshot doesn't surface it. Verify via e2e.

### G-04 — `/marketplace` has no backend
Either implement or hide the nav.

## Cosmetic / low-impact

- **P-01** FAB `+` overlaps short tables on some pages (safe-area fix).
- **P-02** Sidebar badges (1, 2) need `title`/`aria-label` for meaning.
- **P-03** Mixed primary/secondary button ordering across pages.
- **P-04** Invoice number column narrow (truncation).
- **P-05** Empty `components/stamps/` directory — delete.
- **P-06** 5 components >1000 LOC — refactor sprint.
- **P-07** 71 `any` type usages (mostly error handling) — strengthen types.
- **P-08** Nachtrag model file bundles `Serienbrief` and `PushSubscription` — split.
- **P-09** 3 AI hooks with overlap — consolidate.

## Known-good, NOT a bug

- Backend `redirect_slashes=False` is a deliberate choice (prevents 307 redirects, keeps routes exact). Fixed 8 callers to match; left the backend as-is.
- Dark mode is generally consistent; minor chart-recolor-on-reload artifacts aren't regressions.
- German-first language default + 10-language matrix works correctly (only content coverage is the issue).
