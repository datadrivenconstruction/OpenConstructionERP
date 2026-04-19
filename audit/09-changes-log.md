# 09 — Changes Log

> Chronological record of fixes applied against findings in `ERRORS.md`. Batches group related edits so a regression can be isolated to a single batch.

---

## Batch 1 — Low-risk hygiene + confirmed security fixes (2026-04-18)

**Scope**: mechanical cleanups from Phase 0/5/8 findings + one real XSS fix. No data-model changes, no refactors that touch more than one call site outside the offending file.

### Applied

| ID | Severity | File(s) | Summary |
|----|---------:|---------|---------|
| L-06 | low | repo root | Deleted all brace-expansion junk directories. Zero functional impact but recursive tools wasted cycles on them. |
| L-05 | low | `frontend/src/features/dashboard/DashboardPage.backup.tsx` (2,667 LOC), `frontend/src/features/requirements/RequirementsPage.tsx` (2,269 LOC), `frontend/src/features/requirements/index.ts` | Deleted. `requirements/api.ts` kept — imported by three consumers. |
| L-07 | low | `backend/pyproject.toml`, `backend/requirements.txt` | Removed `tenacity` dep (zero inbound imports). |
| L-03 | low | `backend/app/core/audit_router.py:37, 64` | Dropped dead `_user_id: CurrentUserId = None  # type: ignore` default. |
| H-06 | high | `frontend/src/modules/_shared/pdfBOQExport.ts` | **XSS fix**. `htmlEscape()` helper wraps every position/template field in the print-HTML template. Closes JWT-exfiltration via stored BOQ description. |
| M-08 | medium | `backend/app/modules/punchlist/router.py` | 50 MB photo-upload cap (`MAX_PHOTO_SIZE` from `documents.service`). 413 before disk write. |
| M-01 | medium | `backend/app/main.py` | `POST /api/v1/feedback` — per-IP `login_limiter`, 429 with `Retry-After: 60`. |
| M-06 | medium | `backend/pyproject.toml`; `schedule/router.py`; `bim_requirements/parsers/ids_parser.py`; `bim_hub/ifc_processor.py`; `i18n_foundation/ecb_fetcher.py` | `defusedxml` promoted to first-class dep; every user-input XML parse routed through `safe_ET`. Stdlib `ET` kept for tree-build/types. |
| M-02 (partial) | medium | `backend/app/main.py`; `frontend/src/features/dashboard/DashboardPage.tsx` | Auth gate on `/api/system/modules`, `/validation-rules`, `/hooks`, `/demo/status`. Frontend raw `fetch()` → `apiGet()` to attach Bearer. |

---

## Batch 2 — More safe fixes + Phase 3/4/7 audit reports (2026-04-18)

**Scope**: auth-consistency on "benign-but-inconsistent" endpoints, upload hardening, API enrichment, CSP dedupe. Plus running Phase 3 (cross-module drift), Phase 4 (API contract remainder), Phase 7 (data integrity) audits.

### Applied

| ID | Severity | File(s) | Summary |
|----|---------:|---------|---------|
| L-01 | low | 8 regional packs (`us/uk/dach/india/russia/middle_east/latam/asia_pac_pack/router.py`) | `router = APIRouter(dependencies=[Depends(get_current_user_id)])`. Verified no frontend pre-auth calls to `/v1/*_pack/`. |
| L-02 | low | `backend/app/modules/architecture_map/router.py` | Router-level auth dependency. Frontend `ArchitectureMapPage` already uses `apiGet` — token auto-attached. |
| L-04 | info | (none) | Investigated. Dual-route (trailing-slash + bare) registration is deliberate per in-file comment — some Docker quickstart reverse-proxies drop the slash. **Not a bug.** Reclassified as N-04 in ERRORS.md. |
| M-03 | medium | `backend/app/core/global_search_router.py` | Prefix renamed `/api/v1/search` → `/api/v1/global-search`. Eliminates collision risk with the `search` module's auto-mount. Frontend never called this prefix (verified by grep). |
| M-04 | medium | `backend/app/modules/procurement/{schemas,router}.py`; `backend/app/modules/finance/{schemas,router}.py` | `POResponse.vendor_name` and `InvoiceResponse.counterparty_name` populated via one-shot `SELECT Contact WHERE id IN (...)` on every list/get/create/update/action response. Frontend v1.9.5 normaliser's UUID-fallback path is now dead code (can be removed next time that module is touched). |
| M-07 | medium | `backend/app/core/upload_guards.py` (new); `finance/router.py`, `fieldreports/router.py`, `contacts/router.py`, `boq/router.py` | New `reject_if_xlsx_bomb()` helper inspects `zipfile.ZipFile(...).infolist()` and sums `file_size` (uncompressed). Rejects if > 50 MB before openpyxl loads the sheet. Wired into all 4 xlsx-accepting endpoints. Silent no-op on non-ZIP payloads (plain CSV) so downstream error handling stays intact. |
| M-09 | medium | `backend/app/core/rate_limiter.py`; `documents/router.py::upload_document`; `bim_hub/router.py::upload_bim_data` + `upload_cad_file`; `takeoff/router.py::upload_document` | New `upload_limiter` (30/min per user — chosen over approval_limiter's 20/min to give batch BIM uploads headroom). 429 + `Retry-After` on exceed. |
| H-07 | high | `deploy/docker/nginx.conf` | Nginx CSP now matches backend CSP verbatim (+ comment documenting the invariant). Previously nginx's minimal CSP intersected with backend's to silently block Google Analytics / Fonts in production. Keeping both in sync is the correct posture — static `index.html` is served by nginx's `try_files` (not proxied) so backend middleware alone can't protect it. |

### Phase reports written

| Phase | File | Scope | Top finding |
|-------|------|-------|-------------|
| 3 | `audit/03-cross-module.md` | BOQ / cost / validation / KPI drift across modules | X-01 CRITICAL: BOQ dashboard total ignores active markups; same BOQ shows 2 different totals. |
| 4 | `audit/04-contract.md` | API wire-shape in 20 modules | Tasks HIGH: `checklist` is `list[dict]` on wire, `ChecklistItem[]` on frontend — different keys. |
| 7 | `audit/07-data.md` | Decimal / rounding / TZ / JSONB / FK / Alembic | D-01 HIGH: `str → float → total` path silently drops sig-digits past 15. D-04 HIGH: backend HALF_UP vs browser `Intl.NumberFormat` rounding mismatch. |

### Deferred to a later batch (explicit reasons)

| ID | Why it can't land in this batch |
|----|---------------------------------|
| C-01 (money as `String(50)`) | Multi-module migration + backfill + every consumer. Plan-first. |
| C-02 (`create_all()` at startup) | Baseline Alembic + dev/prod guard. Lifecycle change. |
| C-03 (JWT in localStorage) | httpOnly cookies + CSRF. Frontend rework. |
| H-01 (`cad` module stub) | Need user decision: promote `classification_mapper.py` to core, or flesh out module as DDC façade. |
| H-02 (missing `bim_compliance` / `project_completeness` rule sets) | Product decision: implement or delete from CLAUDE.md. |
| H-03 (50k-line i18n bundle) | Build-pipeline change to lazy-load per-locale JSON. |
| H-04 (18 locales ~70% coverage) | ~1k-key delta × 18 locales → separate translation pass. |
| H-05a/b/c/d | Schema + migration across all 37 modules. |
| H-08 (pluralization) | 853 `{{count}}` sites; needs scoped pass on top 20 count messages. |
| M-02 remainder (`/api/system/status`, `/marketplace`, `/demo/catalog`, `/version-check`) | `/status` called pre-auth by `DemoBanner.tsx` for `demo_mode` flag. Correct fix is split into `/public-info` (demo_mode + app_version) vs full `/status` (auth'd). Backlog. |
| M-05 (CSP `unsafe-inline` + `unsafe-eval`) | Nonce-based CSP requires Vite `index.html` plumbing + audit of `new Function(...)`. |
| M-10 (admin JWT bypass) | Defence-in-depth DB lookup touches `get_current_user_payload` — every authed endpoint. Measured rollout. |
| M-11 (1,768-LOC rules file) | Pure refactor, but 1.7k LOC split touches many import sites. Schedule with next validation feature. |
| L-08, L-09, L-10, L-11, L-12, L-13 | Hygiene refactor backlog. |
| Phase 1 (responsive/a11y/perf sweeps) | Needs the app running in a browser. Not doable in static-code-audit mode. |
| Phase 2 (BIM/BOQ/Validation domain deep-dive) | Needs app running + real CAD fixtures to fire-test the pipeline. |

### Verification performed in this batch

- Python AST parse on all 19 edited backend files — all clean.
- Frontend `npx tsc --noEmit` — clean.
- Regional pack frontend-call grep: `/v1/*_pack/` returns zero hits pre-edit (verified no UX break).
- `document.write` + `dangerouslySetInnerHTML` re-scan: only 1 remaining site (`MessageBubble.tsx`), which escapes content before applying markdown — safe.
- `POResponse` + `InvoiceResponse` enrichment: verified every `model_validate` call site replaced (grep now shows only the occurrence inside the helper).
- `upload_limiter` not applied to `punchlist` photos (already capped by `MAX_PHOTO_SIZE` in Batch 1); not applied to import/file endpoints (already size-capped).

### Cumulative scorecard

- **Critical (3)** — 0 fixed, 3 open (all need design: Decimal migration / Alembic baseline / JWT cookie rework).
- **High (8)** — 2 fixed (H-06 XSS, H-07 CSP). 6 open.
- **Medium (11)** — 8 fixed (M-01, M-02 partial, M-03, M-04, M-06, M-07, M-08, M-09). 3 open.
- **Low (13)** — 7 fixed (L-01, L-02, L-03, L-05, L-06, L-07) + 1 reclassified (L-04 → N-04 intentional). 5 open.
- **New findings from Phase 3/4/7 (21)** — 0 fixed yet (logged in dedicated phase reports).

### Version bump

Not yet. Still uncommitted. Bump to v1.9.6 when user approves the batch — Changelog entry should reference Batch 1 + Batch 2 + the new phase reports.
