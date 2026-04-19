# OpenConstructionERP — Deep Audit

Started: 2026-04-18. Based on v1.9.5.

## Method

- **Non-destructive** — read-only inventory first, fixes only after findings are verified
- **Verified** — every claim tied to a file path + line number; no hand-waving
- **Staged** — each phase in its own file; `09-changes-log.md` records what was applied

## Phases

| # | File | Scope | Status |
|---|------|-------|:------:|
| 0 | `00-backend-inventory.md` | 762 endpoints / 60 modules / 10 anomalies | **done** |
| 0 | `00-frontend-inventory.md` | 63 pages / 86 routes / 17 stores / 5k LOC dead | **done** |
| 0 | `00-db-inventory.md` | 86 tables / 89 FK / 220 String(50) money cols | **done** |
| 1 | `01-sweeps.md` | Responsive / a11y / performance / console errors | pending |
| 2 | `02-domain.md` | BIM/CAD pipeline, BOQ math, Validation engine, Takeoff, CWICR search | pending (needs running app) |
| 3 | `03-cross-module.md` | BOQ totals, project cost rollups, validation scores, dashboard KPIs | **done** |
| 4 | `04-contract.md` | API wire-shape drift for ~20 modules not yet covered | **done** |
| 5 | `05-security.md` | CSP, XSS surfaces, RBAC, upload validation, rate limiting, token storage | **done** |
| 6 | `06-i18n.md` | 21 locales (EN 100% / DE 92.6% / RU 91.3% / 18×~70%) | **done** |
| 7 | `07-data.md` | Decimal precision, currency rounding, timezone, JSONB schema drift | **done** |
| 8 | `08-hygiene.md` | Dead code, duplicates, giant files, CLAUDE.md freshness, test coverage | **done** |
| 9 | `09-changes-log.md` | What got applied in which batch | **running** (Batch 1 + Batch 2 landed) |

## Progress snapshot (live)

**Phase 0 complete.** 3 inventories landed. Headline numbers:

- Backend: 762 endpoints, 60 modules with manifests, 59 with working routers (`cad` is a stub).
- Frontend: 63 pages, 86 routes, 17 Zustand stores, 18 files >2k LOC, ~5k LOC confirmed dead.
- DB: 86 tables in 37 modules, **every money/quantity/rate column is `String(50)`** (~220 cols), 98% of tables have no `org_id`, no AuditMixin/OrgMixin/TimestampMixin despite CLAUDE.md.
- i18n: 21 locales bundled in a single 50k-line TypeScript constant (not per-language JSON as CLAUDE.md implies). EN/DE/RU near parity, all others ~70%. No pluralization.

**2 critical findings** (C-01 money stored as strings, C-02 create_all-as-migration) and **several HIGH-severity architecture gaps** already confirmed — see `ERRORS.md`.

**Batch 1 + Batch 2 fixes landed (2026-04-18, uncommitted)**: 17 items total.
- **HIGH (2)**: H-06 XSS fix in pdfBOQExport, H-07 Nginx CSP sync with backend.
- **MEDIUM (8)**: M-01 feedback rate limit, M-02 partial auth gate, M-03 search prefix collision, M-04 vendor_name / counterparty_name enrichment, M-06 defusedxml, M-07 xlsx zip-bomb guard, M-08 photo size cap, M-09 upload rate limiter.
- **LOW (6)**: L-01 regional pack auth, L-02 architecture_map auth, L-03 audit_router type-ignore, L-05 dead files, L-06 brace-junk dirs, L-07 unused tenacity. L-04 reclassified as intentional (N-04).

Phase 3, 4, 7 audit reports added (21 new findings logged in their respective files). Phase 1 (UI sweeps) and Phase 2 (domain fire-test) require the app running and are deferred. Remaining ERRORS.md items: 3 CRITICAL + 6 HIGH + 3 MEDIUM + 5 LOW — all need design decisions, not mechanical fixes. See `09-changes-log.md` for detail + verification.

## Ground rules (from user)

- "аккуратно и тщательно, выверяя каждый пункт" — every finding is verified before it's logged
- No IfcOpenShell — all CAD through DDC cad2data pipeline (per CLAUDE.md)
- Don't commit until asked (user memory: `feedback_no_commit`)

## Deliverables

1. 9 phase reports (as above)
2. A consolidated `ERRORS.md` (confirmed bugs, with severity + fix hint)
3. A consolidated `IMPROVEMENTS.md` (polish opportunities, priority-banded)
4. A `backlog.md` (items that need a human decision, not a blind fix)
5. Fix batches applied per user request with version bump

## Context going in

v1.9.5 already landed (shipped 2026-04-18):
- API contract normalisers in 7 modules (Submittals / Meetings / Safety / Inspections / NCR / Procurement / Finance)
- Schedule `t(key, {defaultValue})` fix
- Sidebar + Meetings `rel="noopener noreferrer"`
- Header tablet overlap
- Tasks action-bar wrap on mobile
- ProjectMap `useTranslation`
- R5 verification suite 9/9 green, cluster tests 44/44 green
