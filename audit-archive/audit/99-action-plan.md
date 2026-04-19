# 99 — Action Plan (Phase 5)

> Sorted by severity, then by benefit/cost ratio. Fixes are applied in the `audit/99-changes-log.md` order.

## The list

| # | module | severity | problem | proposed fix | est. min | file:line |
|---|--------|:---:|---------|-------------|:-------:|-----------|
| 1 | workflows | **critical** | Workflows list & create 404 (trailing slash) | drop slash in `/workflows/` callers | 5 | `hooks/useWorkflows.ts:30,53`, `components/workflows/WorkflowDesigner.tsx:412` |
| 2 | forms | **critical** | Forms list & create 404 | drop slash | 5 | `hooks/useForms.ts:20,56` |
| 3 | email-templates | **critical** | Endpoint 500s on list; front also called wrong path | front slash fix + backend service fix (UUID coercion) | 30 | `hooks/useEmailTemplates.ts:53`; `services/email_template_service.py:160` |
| 4 | verfahrensdoku | **critical** | Endpoint 500s; front also called wrong path | front slash fix + backend exception | 30 | `components/compliance/VerfahrensdokuPanel.tsx:63,72`; `services/verfahrensdoku_service.py` |
| 5 | invoicing | **critical** | KPI vs list inconsistency (0€ fakturiert / 57k€ überfällig) | audit kpi query; match filters with list query | 90 | `services/invoice_service.py` KPI computation |
| 6 | security | **high** | CSP: `frame-ancestors` in `<meta>` ignored; inline script blocked | drop `frame-ancestors` from meta or move to header; hash/remove inline script | 45 | `frontend/index.html`, `backend/app/middleware/security.py` |
| 7 | auth | **high** | Password reset backend missing — frontend has page | implement `POST /auth/request-password-reset` + `POST /auth/reset-password` (token → email) | 180 | `backend/app/api/v1/auth.py` |
| 8 | api-shape | **high** | useWorkflows (and others) typed as `T[]` but backend returns `{items,total}` | change to `PaginatedResponse<T>` and use `data.items` | 30 | `hooks/useWorkflows.ts`, similar ones |
| 9 | banking | **high** | Gesamtsaldo ≠ single account balance | align computations; document Kontostand vs Verfügbar | 45 | `services/banking_service.py` |
| 10 | accounting-integrity | **high** | Einnahmen/Ausgaben correlate with invoice status inconsistently | trace Konto 1200 entries; verify invoice→kontierung sync | 120 | `services/accounting_service.py`, `services/kontierung_service.py` |
| 11 | fonts / css | **high** | Google Fonts blocked by CSP | self-host fonts under `/public/fonts/` | 45 | `frontend/index.html`, `frontend/src/styles/tokens.css` |
| 12 | login | **high** | `/assets/ui-CdZgSvgs.js` 404 (stale modulepreload) | rebuild client; verify `vite build` manifest | 15 | `frontend/dist/` redeploy |
| 13 | router | **high** | Silent router imports in `router.py` hide startup failures | log WARNING + expose via /health | 30 | `backend/app/api/v1/router.py` |
| 14 | contracts | **high** | `/contracts/stats` ABORTED on Contracts page | verify route exists; align frontend caller path | 20 | `hooks/useContracts.ts`, `backend/app/api/v1/contracts.py` |
| 15 | sidebar-badges | **medium** | Red/orange/blue badges with no tooltip | add `title`/`aria-label` | 20 | `components/layout/AppLayout.tsx` (sidebar nav items) |
| 16 | REST | **medium** | `/search` rejects GET (405) | add GET handler with querystring | 15 | `backend/app/api/v1/search.py` |
| 17 | tasks | **medium** | `DELETE /tasks/{id}` 405 while UI likely calls DELETE | confirm verb; switch to PATCH status=archived OR add DELETE | 30 | `api/v1/tasks.py` + `hooks/useTasks.ts` |
| 18 | cabinets, contacts | **medium** | PATCH 405 | add PATCH aliases in routers | 20 | cabinets.py, contacts.py |
| 19 | compose | **medium** | Temporal sidecars run without workflows | either remove services OR implement one workflow | 10 | `docker-compose.yml` |
| 20 | i18n | **medium** | 7 languages missing ~139 keys | extract + translate backlog | 300 | `frontend/public/locales/*/translation.json` |
| 21 | contacts data hygiene | **medium** | ~50 test Audit-Kontakt rows on demo VPS | one-off cleanup SQL | 10 | N/A (db-only) |
| 22 | documents data hygiene | **medium** | ~10+ identical `test_audit.txt` in demo | seed richer fixture | 30 | `backend/app/seed.py` |
| 23 | fab-position | **low** | FAB `+` overlaps short tables | `bottom: calc(1.5rem + env(safe-area-inset-bottom))` | 5 | FAB component |
| 24 | marketplace | **low** | Page with no backend | hide nav or implement | 10 | nav entry in AppLayout |
| 25 | stamps folder | **low** | Empty dir | delete | 1 | `frontend/src/components/stamps/` |
| 26 | button ordering | **low** | Mixed primary/secondary ordering | align to Apple HIG | 30 | various toolbars |
| 27 | redundant ai hooks | **low** | `useAI`, `useAICopilot`, `useAIEmail` fragmented | consolidate into `useAIAction` | 60 | `hooks/useAI*.ts` |
| 28 | giant files | **low** | UploadModal 1727 LOC, DashboardPage 2702 LOC | split refactor sprint | 4 h+ | multiple |

## Batch 1 — Critical (applied in this audit)

- #1, #2 — trailing slashes for workflows + forms → **applied**
- #3, #4 — trailing slash parts only → **applied**. Backend 500s left for backlog.
- #5 — **deferred** (needs fixture + accountant sign-off).

## Batch 2 — High (deferred; require product owner / accountant decisions)

- #5, #9, #10 (financial integrity) — architectural decisions.
- #6 (CSP) — need to verify browser parity before rolling out.
- #7 (password reset) — net-new feature, separate PR.
- #12 — needs `vite build` + redeploy.

## Backlog

See `99-backlog.md`.

## Coverage

Total findings: **~50** (17 UI + ~17 functional + 16 cross-module).
Critical fixed in this audit: **4** (trailing-slash bugs for workflows × 2 + forms × 2 + email-templates call + verfahrensdoku call).
Remaining: tracked above.
