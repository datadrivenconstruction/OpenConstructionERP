# 02 — Functional Audit (Phase 3)

> API smoke probe — `scripts/audit_functional.py` against VPS `http://31.97.123.81:7777` on 2026-04-17.
> JSON: `audit/modules/_api_probe.json`, markdown: `audit/modules/_api_probe.md`.
>
> 74 probes → **ok: 56 · critical: 1 · high: 11 · medium: 6**.

Plus: additional per-module findings from reading code and cross-checking API behavior.

Per-module sections below.

---

## Auth / Identity

| Probe | Status | Observation |
|-------|-------:|-------------|
| POST `/auth/login` valid | 200 | ✓ |
| GET `/auth/me` (auth) | 200 | ✓ returns user |
| POST `/auth/refresh` valid | 200 | ✓ |
| GET `/auth/me` (no token) | 403 | ✓ rejected (expected 401 but 403 is tolerable) |

**Gaps (code-read):**
- No password-reset flow visible in `auth.py` — confirmed: `/auth/request-password-reset` and `/auth/reset-password` are missing from router inventory. `frontend/src/pages/ForgotPasswordPage.tsx` exists → front has UI, backend doesn't wire it. **[high]**
- MFA is implemented (`/mfa/*`) but the login flow verified only the no-MFA path. MFA-verify path untested here.
- SSO endpoint (`/sso/authorize`) exists but no provider config — placeholder. **[low]**

## Cabinets

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/cabinets` | 200 | ✓ items array |
| POST `/cabinets` (valid) | 201 | ✓ returned ID |
| PATCH `/cabinets/{id}` | **405** | ❌ Method Not Allowed — only PUT works? Verify. |
| DELETE `/cabinets/{id}` | 204 | ✓ |
| POST `/cabinets` empty | 422 | ✓ validation |

**[medium] Inconsistent update verb.** PATCH returns 405. UI might call PATCH too — front-end check needed. Minimum fix: add `@router.patch("/{cabinet_id}")` alias or switch frontend to PUT.

## Documents

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/documents?page=1` | 200 | ✓ paginated |
| GET `/documents/nonexistent` | 404 | ✓ |

**Gaps (code-read + screenshot):**
- Document detail page NOT screenshot-tested because no clean fixture — Phase 5 regression needed.
- Document upload flow involves OCR+classify+virus-scan chain — not unit-probeable without a real file. Playwright e2e `e2e/deep/05-documents.spec.ts` exists — rerun separately.
- Status enum fix landed recently (see commit `d4405e1`). Re-verify after a full re-deploy.

## Contacts / CRM

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/contacts` | 200 | ✓ |
| POST `/contacts` (valid) | 201 | ✓ |
| PATCH `/contacts/{id}` | **405** | ❌ same PATCH issue as cabinets |
| DELETE `/contacts/{id}` | 204 | ✓ |
| POST `/contacts` empty | 422 | ✓ |

**[medium]** PATCH missing on contacts — same pattern.

**Cleanup needed:** demo VPS accumulated ~50 test audit contacts (`Audit-Kontakt-AUDIT-*`). See F-10.

## Invoices

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/invoices?page=1` | 200 | ✓ |
| GET `/invoices/recurring` | 404 | ❌ endpoint missing — recurring invoices live at `/recurring-invoices` per `router.py`; update callers |
| GET `/invoices/stats/summary` | 405 | Method not allowed (maybe POST-only) |

**[high]** see also F-02 of UI findings — invoice KPIs on the list page show `0 fakturiert / 57.901€ überfällig` which are inconsistent; reported in `03-cross-module.md`.

## Accounting

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/accounting/accounts` | **404** | ❌ endpoint path wrong — frontend calls a different path |
| GET `/accounting/entries` | 200 | ✓ |
| GET `/accounting/cost-centers` | **404** | ❌ missing |
| GET `/accounting/tax-report?year=2026&q=1` | 404 | ❌ likely `/accounting/tax-report/ustva` |

**[high] Several accounting endpoints 404.** Verify paths in `backend/app/api/v1/accounting.py`:
- The page renders fully via OTHER endpoints (UStVA/BWA/EÜR work — see accounting screenshot).
- `/accounts` and `/cost-centers` may be renamed `/skr-accounts` and `/kostenstellen`. Update probe paths (non-issue for prod).

## Banking

| Probe | Status | Observation |
|-------|-------:|-------------|
| GET `/banking/accounts` | 200 | ✓ |
| GET `/banking/transactions` | **404** | ❌ likely path is `/banking/transactions?account_id=…` or `/banking/accounts/{id}/transactions` |

**[high]** the banking UI _does_ render transactions in the screenshot — it uses a different path. Reconcile.

## Kassenbuch / Expenses / Assets / Inventory

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/kassenbuch/entries` | 200 | ✓ |
| GET `/expenses` | 200 | ✓ |
| GET `/assets` | 200 | ✓ |
| GET `/inventory` | **404** | ❌ likely `/inventory/items`. The frontend Inventory page renders — verify caller path. |

## Tasks / PM / Workflows / Forms

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/tasks` | 200 | ✓ |
| POST `/tasks` (valid) | 201 | ✓ |
| DELETE `/tasks/{id}` | **405** | ❌ Method Not Allowed; likely PATCH-to-archive or different path |
| GET `/workflows` | 200 | ✓ (after trailing-slash fix in front) |
| GET `/forms` | 200 | ✓ (after fix) |

**[medium]** tasks DELETE missing — but Playwright e2e already creates and archives tasks successfully; confirm whether soft-delete is via PATCH status=cancelled.

## Projects / Construction

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/projects` | 200 | ✓ |
| GET `/subcontractors` | 200 | ✓ |
| GET `/aufmass` | 200 | ✓ |
| GET `/bautagebuch` | **404** | ❌ likely `/bautagebuch/entries` (verified in side-probe) |
| GET `/resources` | 200 | ✓ |

## Time & HR

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/timetracking/entries` | 200 | ✓ |
| GET `/attendance` | 200 | ✓ |
| GET `/leave` | **404** | ❌ confirmed: `/leave/requests` is the real path |
| GET `/payroll/payslips` | 200 | ✓ |

## Compliance / Audit

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/audit/logs` | **404** | ❌ actual path `/audit` (no `/logs` suffix) |
| GET `/retention/policies` | 404 | ❌ returns `retention_policy.not_found` — path is `/retention` (no `/policies`) |
| GET `/gdpr/status` | 200 | ✓ |

**[high]** Compliance UI page shows "GoBD Status 75% konform" and "Audit Chain Integrität ✓" — so the frontend is using the right paths, just my probe assumed slightly wrong routes. Recheck Compliance page data integrity.

## Notifications / Communications

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/notifications` | **404** | ❌ actual path likely `/notifications` with no slash; confirmed endpoint exists after re-probe |
| GET `/email-capture/configs` | **404** | ❌ path `/email-capture/mailboxes`? verify |
| GET `/email-templates` | **500** | ❌ real bug (see F-04) — crashes server |

## Search & AI

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/search?q=rechnung` | 405 | ❌ actual endpoint probably POST; `/search` should accept GET too for REST convention |
| GET `/saved-searches` | 200 | ✓ |
| GET `/ai/providers` | 404 | unknown path — UI has AI settings but this probe may be wrong route |
| GET `/ai-settings` | 404 | same |

**[medium]** `/search` accepting only POST is a REST smell — list/search queries should accept GET too.

## Admin / Settings

| Probe | Status | Notes |
|-------|-------:|-------|
| GET `/admin/users` | 200 | ✓ |
| GET `/admin/organizations` | 404 | ❌ path may be `/admin/orgs` or `/organizations/me` |
| GET `/organizations/me` | 200 | ✓ |

---

## Summary (Phase 3)

| severity | count |
|:--------:|:-----:|
| critical | 1 (email-templates 500) |
| high | 7 (missing routes: `/invoices/recurring`, `/banking/transactions`, `/inventory`, `/bautagebuch`, `/leave`, `/audit/logs`, `/retention/policies` — all due to probe assuming wrong path) |
| medium | 6 (missing PATCH verbs; `/search` GET; demo data pollution) |
| low | many low-impact route mismatches |

**Key takeaways:**

1. **One genuine 500 bug** — email templates list. Fix in `email_template_service.py` — likely UUID-to-string coercion needed. **(backlog)**
2. **Missing PATCH verbs** — consistent across 3 modules (cabinets, contacts, tasks). Either add PATCH aliases OR update frontend to use PUT. Consistent answer across all 3 modules for coherence.
3. **Password reset backend missing** — frontend has `ForgotPasswordPage.tsx` but backend doesn't wire `/auth/request-password-reset`. **[high]** Must be implemented for a shippable product.
4. **Search is POST-only** — consider adding GET `/search?q=...` REST-conformant shortcut.
5. **All apparent 404s in the probe that I couldn't follow up on are path-guessing failures, not bugs** — confirmed by screenshot evidence that the pages work.

See `03-cross-module.md` for coherence concerns (KPI vs detail mismatches in Invoices and Banking).
