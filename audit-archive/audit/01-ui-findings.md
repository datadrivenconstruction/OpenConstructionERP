# 01 — UI Findings (Phase 2)

> Source: Playwright sweep against `http://31.97.123.81:7777` on 2026-04-17.
> 50 routes × light+dark = 100 screenshots in `audit/screenshots/<group>/<name>--<theme>.png`.
> Sweep report JSON: `audit/screenshots/_sweep-report.json`.

## Sweep stats

- 50 routes reached, 0 runtime JS crashes (`pageErrors` empty everywhere — React doesn't crash).
- **34 × HTTP 404**, 5 × HTTP 422, **4 × HTTP 500**, 3 × HTTP 403 in console across pages.
- Every page fires 2 **CSP violations** (see F-01 below) — 100 routes × 2 violations.
- 2 pages have failed network requests (login assets, /contracts/stats).

---

## High-severity findings

### F-01 — [high] CSP misconfigured on every page
**Screenshot:** every file in `audit/screenshots/*`
**Observation (from sweep report):**
```
The Content Security Policy directive 'frame-ancestors' is ignored when delivered via a <meta> element.
Executing inline script violates 'script-src 'self' 'unsafe-eval''. …hash ('sha256-PyASMZ0Db8Gc2wAsChN9yXjnS8ElUvwAj2dJnPiaKz4=') or nonce required.
```
- `frame-ancestors` only works as an HTTP header; the `<meta>` CSP should drop it (or the header should be set separately).
- One inline script is emitting and being blocked — either remove it or whitelist via hash.
**Minimum fix:** drop `frame-ancestors` from the meta CSP and add the inline-script hash OR move the inline code to an external file.
**Files:** `frontend/index.html`, backend security middleware `backend/app/middleware/security.py` (if it sets CSP). Verify and align.

### F-02 — [critical] Workflows list doesn't load (trailing-slash 404)
**Screenshot:** `audit/screenshots/07-tasks/workflows--light.png` shows "Laden fehlgeschlagen · Erneut versuchen" where the list should be.
**Root cause:** `frontend/src/hooks/useWorkflows.ts:30,53` and `frontend/src/components/workflows/WorkflowDesigner.tsx:412` call `/workflows/` (trailing slash). Backend has `app = FastAPI(redirect_slashes=False)` → those return 404.
**Impact:** list is empty, creating a new workflow silently fails.
**Fix applied** (this audit): removed trailing slash in those 3 lines.

### F-03 — [critical] Forms list / creation broken by same trailing-slash issue
**Observation:** `frontend/src/hooks/useForms.ts:20,56` calls `/forms/`. 404 on VPS.
**Fix applied:** removed trailing slash.

### F-04 — [high] Email-templates list triggers HTTP 500
**Screenshot:** settings → (implicit usage)  **API:** `GET /api/v1/email-templates` → `{"detail":"error.internal_server_error"}`
**Root cause:** likely a type mismatch in `EmailTemplateService.list_templates()` — returns `EmailTemplateResponse(id=uuid.UUID, …)` while schema might expect `str`. Needs backend log to confirm.
**Plus:** `useEmailTemplates.ts:53` was calling `/email-templates/` (404 before the 500); trailing slash removed.
**Fix applied:** frontend slash bug. Backend 500 left in backlog (`99-backlog.md`).

### F-05 — [high] Verfahrensdokumentation endpoint 500
**Screenshot:** `audit/screenshots/10-compliance/compliance--light.png` — GoBD panel flags "Verfahrensdokumentation" red.
**API:** `GET /api/v1/verfahrensdoku` → 500.
**Plus:** frontend called `/verfahrensdoku/` (404 before 500).
**Fix applied:** frontend slash bug. Backend 500 left in backlog.

### F-06 — [high] Contracts stats endpoint not reachable
**Screenshot:** `audit/screenshots/05-crm/contracts--light.png`
**Sweep report:** `GET /api/v1/contracts/stats — net::ERR_ABORTED` while loading the Contracts page.
**Minimum fix:** verify route exists on backend (likely `/contracts/statistics` or `/contracts/summary`). Align frontend caller.

### F-07 — [high] Every page loads Google Fonts cross-origin — aborted by CSP
**Screenshot:** login page font rendering falls back to system font.
**Sweep report (login):**
```
GET https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap — net::ERR_ABORTED
GET https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:… — net::ERR_ABORTED
```
**Minimum fix:** either self-host the fonts under `/frontend/public/fonts/` OR add `https://fonts.googleapis.com` / `https://fonts.gstatic.com` to CSP `style-src` / `font-src` (and drop the unused Inter — CLAUDE.md specifies Plus Jakarta Sans as body).

### F-08 — [high] Login page fails to load one of the JS chunks
**Sweep report (login):**
```
GET /assets/ui-CdZgSvgs.js — net::ERR_ABORTED
```
Not user-visible (chunk is loaded again later in bundle), but indicates a bad preload hint or abandoned dynamic import. **Minimum fix:** inspect `frontend/index.html` `<link rel="modulepreload">` tags and Vite `manifest.json` — the referenced chunk name is stale.

---

## Medium findings

### F-09 — [medium] Sidebar "Verträge" shows red "1" badge with no context
**Screenshot:** every auth page, left sidebar.
The red badge on `Verträge` implies "1 pending / needs attention" but:
- The Contracts page loads empty (see F-06).
- Aufträge has `2`, Rechnungen has `1`. No hover tooltip explains what these mean.
**Minimum fix:** add `title` / `aria-label` describing the badge ("1 expiring soon", "1 overdue invoice", etc.).
**Files:** `frontend/src/components/layout/AppLayout.tsx` (sidebar render).

### F-10 — [medium] Too-many-demo-test-contact-rows from prior audits
**Screenshot:** `audit/screenshots/05-crm/contacts--light.png`
Rows like `Audit Kontakt GmbH / audit-AUDIT-20260414-...@example.de`. This is **test pollution** on demo VPS from prior probe runs.
**Minimum fix:** one-off cleanup SQL (outside the product). Out of scope for code change.

### F-11 — [medium] Documents list monotonous: 10+ identical `test_audit.txt 46 B` rows
**Screenshot:** `audit/screenshots/02-documents/list--light.png`
Again test data pollution. Should seed or curate a richer demo fixture (invoices, contracts, a letter, a payslip). **Product quality signal for demo visitors.**

### F-12 — [medium] FAB "+" blue circle overlaps data on short pages
**Screenshot:** `audit/screenshots/01-dashboard/dashboard--light.png`
The bottom-right floating `+` button sits near "Bitte noch etwas geduldig sein…" notification strip. On shorter viewports it covers the last row of tables.
**Minimum fix:** `bottom: calc(1.5rem + env(safe-area-inset-bottom))` and check z-index/padding below.
**Files:** `AppLayout.tsx` (FAB position) OR per-page component.

### F-13 — [medium] Dark-mode screenshots miss a hard visual regression check
All 49 authenticated pages captured in dark mode. Spot-checks show mostly correct dark tokens. **But** `_sweep-report.json` records a sharp remount (`page.reload()` between light→dark) — some charts render stale light-mode fills on first paint. Not tracked as individual findings — sample in Phase 5 QA.

---

## Low findings

### F-14 — [low] Logo label `DokuFluss KI` (blue pill) next to logo
The "KI" pill adds noise to the logo lockup. Consider moving it to the topbar for dev/beta tags only.

### F-15 — [low] `?` help icon in sidebar is unreachable keyboard-wise
The small `?` above the user card requires mouse. No tabindex verified — out of audit scope to fix fully, note for a11y pass.

### F-16 — [low] Invoice number formatting in "Rechnungen" list shows e.g. `RE-2026-000…` truncated on some rows
Column width likely too narrow.
**Files:** `frontend/src/components/invoicing/InvoiceTable.tsx`.

### F-17 — [low] Mixed button ordering: primary+secondary reversed on some pages
E.g. Workflows has `[Mit KI erstellen] [+ Neuen Workflow erstellen]` (secondary first, then primary). Settings has primary-right. **Minimum fix:** align across pages on Apple HIG (primary on right for forms, left for toolbars).

---

## Noteworthy non-findings

- **No runtime JS crashes** — `pageErrors` empty across all 50 routes. Huge positive; error boundaries are working.
- **German i18n consistent** — every page is fully DE. No mixed languages or "TODO" placeholders observed.
- **Responsive design not tested** — only 1440×900 captured. Mobile + tablet remain a Phase 5 follow-up. 
- **Light/dark tokens** — consistent across main UI. Some chart colors could be audited individually.

---

## Pages NOT captured (and why)

- `/documents/:id` — needs a real document ID; skipped to avoid fixture-dependency in the sweep
- `/invoices/:id`, `/invoices/:id/edit` — same reason
- `/workflows/:id/designer` — depends on an existing workflow (which currently doesn't list — F-02)
- `/forms/:id/designer` — same
- `/portal/:token`, `/f/:token` — public token-based views; out of scope
- `/reset-password` — needs a reset token; skipped
- `/accept-invitation` — needs invite token; skipped
- `/ai-settings` redirects vary — captured as `ai-settings--light/dark.png`

Sample per group is already sufficient for Phase 2 scoring.

---

## Findings summary

| severity | count |
|:--------:|:----:|
| critical | 3 (F-02, F-03, F-04/05 bundle) |
| high | 5 (F-01, F-06, F-07, F-08, and backend 500 group) |
| medium | 5 |
| low | 4 |
| **total** | **17** |

Critical fixes applied in this audit: trailing-slash bugs in Workflows, Forms, Email-templates, Verfahrensdoku (see `99-changes-log.md`).
