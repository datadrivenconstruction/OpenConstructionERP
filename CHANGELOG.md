# Changelog

All notable changes to OpenConstructionERP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.9] — 2026-05-15 · Project setup wizard UI + converter binary-integrity gate

### Added

- **Project setup wizard UI (Slice 2).** `New Project` is now a 5-step wizard — Basics → Region & currency → Project type (9 preset cards) → Scope (activities / phases / focus mode) → Site & review — that creates the project and applies the Slice-1 profile in one flow. Preset grid has a loading skeleton + error fallback.

### Fixed

- **Converter install now verifies the binary, not just its presence.** The `verifying` stage runs a PE-header integrity check (`MZ` + `e_lfanew` → `PE\0\0`); a corrupt/CRLF-mangled download is rejected immediately with an actionable message and the partial install is rolled back, instead of failing later at launch with `WinError 216`.

## [3.0.8] — 2026-05-15 · Converter download fix + project setup wizard (backend) + visible match pipeline

### Fixed

- **Windows converter downloads no longer corrupt binaries.** `_download_one_file` opened the destination with `os.open()` without `os.O_BINARY`, so the MS C runtime used text mode and `os.write()` rewrote every `0x0A` as `0x0D 0x0A` — shifting the PE header and making `RvtExporter.exe` / `IfcExporter.exe` / `DgnExporter.exe` fail to launch with `WinError 216`. Now opens binary on Windows; no-op on POSIX.

### Added

- **Project setup-wizard backend (Slice 1).** 8-preset library + multi-axis scoring engine (activity · role · phase · size · region) → per-project module tiers (must / recommended / optional / hidden) with a numbered route line. New tables `oe_project_profile` / `oe_project_module` / `oe_project_wizard_draft` (migration `v3035`). Endpoints: `GET /projects/wizard/presets`, `GET|POST /projects/{id}/profile`, `POST /projects/{id}/profile/recompute`, `PATCH /projects/{id}/profile/focus-mode`, `GET /projects/{id}/modules`. Presentation-only gating — never unloads a module or blocks an API.
- **Visible 7-stage match pipeline on `/match-elements`.** Convert → Load → Schema → Filter → Group → Match → Rollup, each with status, output preview, an Adjust panel, and editable LLM prompt templates (migration `v3034`).
- **BIM converter banner** now shows live install progress in a two-column layout.

## [3.0.7] — 2026-05-14 · Resource-based cost DB import — docs, templates, downloads

### Added

- **Full guide for extending the cost database** — `docs/cost-database-import.md` covers both paths into `oe_costs_item`: flat-row import (CSV/XLSX via `POST /api/v1/costs/import/file/`, with column-alias table, auto-detected delimiters, encoding heuristics) and resource-based recipes (`POST /api/v1/costs/` with `components[]` referencing leaf resources by `code` + `factor`). Includes classification standards (MasterFormat / NRM / DIN 276 / Uniformat / GAEB), currency handling, Match-Elements integration, and a troubleshooting table.
- **Three downloadable templates**, shipped in `data/templates/` and served as static assets at `/templates/*` so they download straight from the app:
  - `cost_database_template.csv` — minimal 3-row starter (one labor, one material, one equipment line).
  - `example_us_construction.csv` — 30-row working US database covering labor, materials, equipment, and subcontractor lines with MasterFormat codes.
  - `cost_database_with_assemblies.json` — 6 recipe items (strip footing, CIP wall, CMU wall, 2x4 framing, drywall + paint, asphalt roofing) with full resource breakdowns.
- **"Download a template" row on `/costs/import`** — three one-click download buttons in the *Supported formats* card, plus a pointer to the full guide.
- **End-to-end smoke test** — `scripts/test_cost_import.py` uploads the CSV, pushes the JSON recipes, round-trips every code through `/costs/?q=…`, and verifies every recipe's component breakdown survives. Passes 4/4 stages against a clean install (idempotent — 409 "already exists" on re-run is treated as a pass).

## [3.0.6] — 2026-05-14 · DWG upload responsiveness + 6 new HF regions + sidebar branding

### Fixed (DWG upload — root cause)

- **One stuck DDC conversion no longer poisons the next 5+ uploads.** `_handle_dwg()` was awaited inline in the upload request handler, so a 60–120 s DDC binary call (or a crash on an R16/R17 file) pinned a uvicorn worker; subsequent uploads queued behind it and timed out on the client side with `HTTP 500 "Unable to upload drawing"` or `ReadTimeout`. The upload row is now committed first and DDC conversion runs on a detached task with its own `AsyncSession` (`_run_dwg_conversion_in_background`), so the HTTP request returns immediately with `status=uploaded` and status transitions are polled normally.
- **DWG version floor dropped R18 → R14.** Previously the pre-emptive `_dwg_version_too_old` check refused AutoCAD 2004/2007 (R16/R17) before handing them to DDC. The 2026-05-14 bench showed several R16/R17 files DO convert successfully with the installed binary — let DDC have a go and surface its real error when it can't.
- **DDC DwgExporter rolled back v18.2.0 → v17.1.1 (penultimate stable).** Verified upstream regression: v18.2.0 crashes with `Error: converter crashed.` on DDC's own sample `architectural_example-imperial.dwg`, while v17.1.1 converts the same file to a 443 KB Excel at 100 %. IFC/RVT/DGN keep the v18.2.0 inner binaries (no observed regression there) — only the DWG path is reverted.

### Added

- **6 new CWICR v3 catalogues** (registry grows 42 → 48): `MN_ULAANBAATAR` (Mongolian, MNT, 916 MB), `BG_SOFIA`, `HR_ZAGREB`, `NZ_AUCKLAND` (NRM), `TH_BANGKOK`, `VI_HANOI`. All flipped to `available=True` via the `_HF_PUBLISHED` mapping after DDC published the snapshots on the `cwicr-vector-db-bgem3-v3` HF dataset on 2026-05-14.
- **Sidebar white-label branding** — new edit button above the platform name opens a chooser to upload a logo OR type a company name. When set, the user's brand shows large in the sidebar header; `by OpenConstructionERP` sits below as a small AGPL-3.0 attribution. Persisted in localStorage, no backend round-trip.

### Changed

- Default sidebar wordmark shrunk 15 px → 13 px so it no longer crowds the always-visible edit button at the 248 px sidebar width.

## [3.0.5] — 2026-05-14 · Match-elements correctness pass + full Mongolian translation

### Fixed (match-elements — root-cause sweep)

- **`unit_dim` filter excluded every Qdrant hit** — query_builder emitted a `unit_dim` hard filter that doesn't exist on the DDC v3 snapshot payload (it uses `unit_type` with capitalised `Area`/`Volume`/`Linear`/`Mass`/`Count`). Filter never matched, search returned 0, the ranker fell through to a metadata-only path with score ≈0.0002 and surfaced opaque encoded rate codes. Now emits `unit_type` against the snapshot's actual schema; kept `unit_dim_for()` exported for back-compat.
- **`resources` named-vector prefetch returned 404** — `search()` blindly added a `Prefetch(using="resources", …)` whenever the envelope carried resource hints. The DDC v3 snapshot only exposes `dense` + `sparse` named vectors. Now caches per-collection capabilities (`_collection_vectors`) and only issues prefetches the snapshot actually supports.
- **`"BoQ"` source label poisoning `ifc_class` filter** — BoQ adapter set `attrs["ifc_class"] = "BoQ"` whenever the row had no category; envelope builder forwarded it as a hard filter; Qdrant dropped 100% of CWICR rows. Fixed in both the adapter (only forward when the row explicitly carries an IFC class) and the envelope builder (only pass values starting with `Ifc`).
- **Empty description / unit_rate / currency on snapshot-only installs** — snapshot install populates Qdrant vectors but not `oe_costs_item`. With no parquet enrichment, candidates surfaced blank, and the BGE cross-encoder collapsed every score because its passage text was just the opaque rate_code. Now `ranker_qdrant._description_from_payload()` synthesises a human-readable passage from the snapshot's categorical fields (`collection_name`, `material_class`, `ifc_class`, `category_type`, `masterformat_division`); `_hit_to_candidate()` derives currency from the country head via a 60+ ISO-code map. `unit_rate` stays 0.0 — fabricating the operator's load-bearing price would be wrong. UI surfaces "Rate unavailable" instead.
- **`reranker_bge._build_candidate_text()` defensive fallback** — when `candidate.description` is still empty, folds classification + region into the passage so the cross-encoder has discriminating signal beyond the opaque code.

### Added

- **Mongolian (mn) full translation** — completed the 2300 keys that were left as English-fallback in 3.0.4. Construction terminology curated (BOQ → "ажлын тоо хэмжээ", subcontractor → "туслан гүйцэтгэгч", risk → "эрсдэл"); placeholders `{x}` / `{{x}}` preserved verbatim; technical IDs (IFC, DWG, JWT, USD) kept intact.
- **14 new unit tests** for the match payload fallback (`test_ranker_qdrant_payload_fallback.py` + `test_reranker_bge_payload_fallback.py`).

### Fixed (frontend tests)

- Pre-existing vitest debt resolved: 9 broken test files repaired (share-link, visual-regression snapshots, ClassificationPicker, NotFoundPage, BOQGrid, CostCategoryTree, _registry, boqResourceTypes, CostDatabaseSearchModal). No production-code changes — only stale mocks, removed imports, and re-aligned selectors.

### Validation

- Live match probe ("Concrete C30/37 wall, 240mm reinforced" against the USA_USD snapshot) now returns a real US rate code with a readable description and currency=USD. Was score ≈0.0002 + opaque rate code with all enrichment fields empty before. Confidence is still relatively low (~0.005) when the top vector hit is semantically distant (e.g., a hydraulic-engineering rebar rate for a wall query) — that's the BGE reranker doing its job, not a bug.

## [3.0.4] — 2026-05-13 · Polish pass + community contributor flow

### Added

- **"Support us" star button in topbar** + 3-action modal: GitHub star · social share (X / LinkedIn / copy) · case-study tip-off to `info@datadrivenconstruction.io` (or just tag `@DataDrivenConstruction` for re-share through DDC newsletter + socials)
- **Mongolian (mn) locale** registered in `SUPPORTED_LANGUAGES` with starter translation set (nav + common + support keys) — falls back to English for the long tail. Inline soyombo SVG flag added to `CountryFlag.tsx`. Co-authored with @mn-frappe (community contributor invite via PR #125)
- **DDC brand logo** on the Request-a-module dialog hero (replaces generic Sparkles icon) — sourced from local `/brand/ddc-logo.webp`, no external CDN call
- **Marketing site auto-version sync** — `website-marketing/pro/breeze/index.html` hero badge and release ticker now fetch the latest GitHub Release tag + date + name at page load, with SSR fallback to the current shipped version

### Changed

- **Dependency bumps** — Frontend: 12 minor/patch (@tanstack/react-query 5.90→5.100, maplibre-gl 5.23→5.24, react-resizable-panels 4.9→4.11, zustand, @playwright/test 1.58→1.60, @typescript-eslint 8.57→8.59, autoprefixer, jsdom, msw 2.12→2.14, postcss, prettier 3.8.1→3.8.3, pdfjs-dist 4.8→4.10). Rust desktop: openssl 0.10.78→0.10.79 (CVE patch), tauri 2.10.3→2.11.1 (Origin-Confusion CVE patch), rand 0.8.5→0.8.6
- **Rollup pinned to 4.59.0** via `overrides` — Rollup 4.60+ broke vite 6.4's modulepreload-polyfill source-phase import; pin restores the production build

### Fixed

- **`p.data.filter is not a function`** on Vendor DB in demo accounts — `SupplierCatalogsPage.tsx` now defensively coerces all `useQuery` data fields with `Array.isArray(...)` rather than `?? []`, which was letting stale offline-cache error envelopes through
- **Backend `F821`** — `contracts/router.py` referenced `status.HTTP_400/404` without importing `status` from fastapi (3 endpoints would have crashed on hit)
- **Backend `F601`** — duplicate `"متر مربع"` dict key in `match_service/boosts/unit.py` (Arabic + Persian sections collided; phrase is byte-identical in both scripts)
- **Missing Mongolian flag** in language switcher — inline SVG + emoji fallback added to `CountryFlag.tsx`
- **61 dead backend imports** cleaned via ruff `--fix`

### Housekeeping

- **All 7 stale Dependabot PRs closed** (#117 minor group, #112 cargo openssl, #125 Mongolian, #118 typescript major, #119 i18next-http-backend major, #120 react-is major, #121 eslint major). All were based on pre-filter-repo main; merging would have resurrected the removed `.claude/qa_parts_*` tree. Equivalent safe patches applied directly to main; majors deferred to a separate validation cycle.
- Pre-existing frontend vitest debt documented: 31 failing tests across 9 files (share-link, visual-regression snapshots, ClassificationPicker, NotFoundPage, BOQGrid, CostCategoryTree, _registry, boqResourceTypes, CostDatabaseSearchModal). None caused by v3.0.4 changes — slated for v3.0.5 cleanup.

## [3.0.3] — 2026-05-13 · Deep correctness pass + UX & supply-chain hardening

### Added

- **FSM engine** — 6 entity state machines (BOQ · Project · Invoice · NCR · RFQ · Submittal) with 50 declarative transitions, role-restricted guards, audit log via new `oe_activity_log` table (migration `v3033`)
- **IFC unit assignment parser per ISO 16739-1:2024 §5.4.3** — every SI prefix, Imperial conversion, recursive `IfcConversionBasedUnit`, `IfcDerivedUnit` combinatorics; 92 unit-assignment regression tests
- **Ed25519 manifest signing** for the converter installer pipeline — SHA-256 file verification, refuse-on-mismatch, 30 tests + emergency-rotation script
- **Collapsible icon-only sidebar** — toggles to 64px, floating pill on the panel edge, persisted to localStorage
- **WideModal sweep** — 19 files / 25 modals migrated to the shared `WideModal` foundation: Resources, DailyDiary, QMS, Punchlist, FieldReports, Contracts, CRM, Variations, PropertyDev, SupplierCatalogs, ChangeOrders, Tendering, Finance, Submittals, Correspondence, Contacts, RFI, Meetings, Transmittals. Forms with 4–14 fields now fit at 1366×768 without scrolling.

### Fixed (UX)

- Subcontractors page modal unified — was the only outlier still on a narrow `max-w-3xl` no-section modal; now uses `WideModal` + `WideModalSection` like the rest of M1
- Service page — Delete with `ConfirmDialog` on contracts / assets / tickets; contract delete invalidates cascaded child rows
- `module_loader` URL prefix — canonical kebab-case + underscore mirror so both `/bi-dashboards` and `/bi_dashboards` resolve

### Tests

5045 passed · 1 skipped · 0 regressions

## [3.0.1] — 2026-05-13 · 18-Modules Wave + deep stability

### Added — 17 new business modules (88 total)

**Field Operations** — Service & Maintenance · Equipment & Fleet · Daily Diary · Subcontractor Portal · Resources & Crew
**Commercial** — CRM · Contracts (FIDIC / JCT / NEC4 / AIA) · Subcontractor Management · Bid Management · Variations (VO register) · Supplier Catalogs · Property Development
**Schedule & Quality** — Advanced Schedule (Last Planner / CPM Kahn topo-sort) · Quality Management (ISO 9001:2015) · HSE Management (ISO 45001 / OSHA 1904.39 / RIDDOR / DGUV) · Carbon & ESG (EN 15978 LCA · GHG Protocol Scope 1/2/3) · BI Dashboards (warehouse-projected)

### Stability — India scenario findings actioned

- **DWG / DXF**: ezdxf 1.4.x layer-visibility regression fixed (every fresh-install layer was being marked invisible due to bound-method truthiness)
- **PDF takeoff**: Devanagari / Tamil / Telugu / Arabic / Chinese / French / German / Spanish OCR by default; lakh-crore (`1,00,000`) numeral parser; scanned-PDF fallback
- **CRS auto-detect**: India UTM 42-46N + 16 other region groups worldwide (Germany Gauss-Krüger + UTM 32/33, UK BNG, France Lambert-93, Switzerland LV95, Austria MGI, Netherlands RD, US State Plane + UTM 10-19N, UAE/KSA UTM 38-40N, Japan JGD2011, Brazil SIRGAS, China CGCS2000)
- **File-size limits removed across all uploads** (env override remains for tenant policy); streaming upload + background-job migration
- **Qdrant without Docker**: native binary auto-install from official GitHub Releases, supervised by `qdrant_supervisor.py` with one-click install card on `/match-elements`

### Security

- `Settings` model now refuses to start in non-development environments when `JWT_SECRET` is still the bundled `openestimate-local-dev-key` default — fail-fast at boot with a clear remediation message (set `OE_JWT_SECRET` to `secrets.token_urlsafe(32)`)
- 230 IDOR endpoints hardened across service / subcontractors / contracts / bid_management / schedule_advanced / bi_dashboards via `verify_project_access`

### Cross-module integration

- 37 cross-module event subscribers (`_wave5_cross_module_subscribers.py`) wire QMS NCRs to procurement supplier rating, HSE incidents to contract risk register, carbon entries to BI projections, daily diary to schedule actuals, etc.
- 14 alembic migrations (v3010 → v3031) with parallel-wave merge head (v3032)

### Internationalisation

- 18 new nav keys translated across 25 non-EN locales (industry terminology preserved — Last Planner kept as proper noun, BI/ESG acronyms unchanged)

## [3.0.0] — 2026-05-12 · v3 milestone

Consolidates the entire v2.x line (100+ patch releases between 2026-04-20 and 2026-05-12) into a stable v3.0.0 milestone. Same codebase as v2.9.42 — new version label, refreshed metadata, framed as the v3 release.

### v3 highlights (cumulative since v2.0.0)

**Cost data & match-making**
- 42 regional cost catalogues (Europe, Americas, Asia, Africa) — CWICR v3 schema
- AI vector matching via Qdrant + BGE rerank across 11 classification standards (DIN 276, MasterFormat, NRM, GAEB, UNTEC, VOCI, BC3, GB50500, SEKISAN, GESN, BirimFiyat)
- Per-encoder + per-language confidence thresholds, language-family region aliases
- Multi-currency BOQ with live FX rollup

**CAD / BIM (no IfcOpenShell)**
- DDC `cad2data` pipeline: DWG / DGN / IFC / RVT → canonical JSON
- PDF + DWG takeoff (PaddleOCR + YOLOv11)
- BIM Quantity Rules + Requirements DSL
- BCF I/O (issues / viewpoints / validation reports)

**Project control**
- File-manager (docs / photos / BIM / DWG / sheets / markups / reports / takeoffs in one place),
  per-folder ACL, per-file activity log, password-protected share links, bulk operations
- Finance, Procurement, Tendering, Change Orders, Compliance Docs tracker
- RFI, Submittals, Transmittals, NCR, Inspections, Meetings, Correspondence, Contacts
- Tasks, Schedule (Gantt), Risk Register, 5D Cost Model
- Validation (DIN 276 / NRM / MasterFormat / GAEB), Compliance DSL, 3-way invoice match

**Platform**
- 71 plug-and-play modules with auto-discovery
- 21 languages, lazy-loaded chunks
- Apple-style design system, light + dark, route-aware backdrop variants
- AGPL-3.0 — open data, open standards, open formats

**Security & quality**
- IDOR sweep across 73+ endpoints, RBAC scopes
- MIME hardening, share-link password protection
- 450+ pytest tests, 1600+ vitest tests, integration coverage on critical modules

### Install

```bash
pip install openconstructionerp==3.0.0
# or
docker compose up
```

PyPI: https://pypi.org/project/openconstructionerp/3.0.0/
Demo: https://openconstructionerp.com
Source: https://github.com/datadrivenconstruction/OpenConstructionERP

## [2.9.42] — 2026-05-12

### Added

- Markups: threaded comments per drawing markup (`oe_markups_comment` table, v2941 migration, 3 endpoints, MarkupCommentsDrawer).
- File-manager: per-folder ACL (viewer / editor / owner) with FolderPermissionsModal + lock badge; v2942 migration.
- File-manager: per-file ActivityDrawer slide-over with Today / Yesterday / Earlier bucketing.
- File-manager: bulk-delete for all 8 file kinds (`groupByKind` dispatcher; new `DELETE /v1/reporting/reports/{id}` and `DELETE /v1/documents/sheets/{id}`).
- Compliance Docs tracker (`oe_compliance_docs` module, v2943 migration): insurance / permits / bonds with expiry status, dashboard widget, /projects/{id} compliance tab.
- `/files` first-load overlay (`InitialLoadProgress`) with Storage → Tree → Ready stepper + animated progress bar.
- `/files` landing KPI strip (`FilesStatsStrip`) with storage-by-kind breakdown segments.
- Notifications inbox page (`/notifications`) with paginated list, date grouping, per-row delete; bell rewritten with loading / error / empty states.
- 16 fallback `notification.<event>_(title|body)` templates server-side so freshly-generated events never leak raw i18n keys.

### Changed

- Dashboard backdrop hoisted from per-page wrappers into `AppLayout`, route-aware variant: `/boq`, `/match-elements`, `/costs`, `/assemblies`, `/catalog`, `/bim/rules`, `/files` → estimation amber; `/schedule`, `/tasks`, `/5d`, `/risks` → planning red; everything else → dashboard blue.
- Removed `relative isolate` from 14 page wrappers so full-screen modals (z-50) sit above the sticky header (z-30) in the root stacking context instead of being trapped behind it.
- Modal backdrops bumped to `bg-black/70 backdrop-blur-lg` across ~82 dialogs so page chrome behind the modal is unreadable.
- `AppLayout` root no longer paints `bg-surface-secondary` (was hiding the `fixed -z-10` backdrop in the root stacking context).
- `/projects` stats: 4 unified cards (Total Projects, Total BOQs, Total Value, Avg Project Size); removed secondary Regions / Currencies / With BIM row.

### Fixed

- `GET /v1/notifications/` 404 — bell now hits `/v1/notifications` (no trailing slash) and backend registers both forms defensively.
- IDOR on `GET /v1/markups/?project_id=` — now scoped to caller's project membership.

### Migrations

- `v2941_markup_comments` ← `v2940_assemblies_resource_type`
- `v2942_folder_permissions` ← `v2941_markup_comments`
- `v2943_compliance_docs` ← `v2942_folder_permissions`

## [2.9.41] — 2026-05-12

### Added

- Projects: PhotosTab on `ProjectDetailPage` — filter bar (search + sort) + responsive grid + keyboard-navigable lightbox; reuses `useFileList` with `category='photo'` filter (no API duplication). 21 `projects.photos.*` i18n keys.
- Projects: TeamStrip on `ProjectDetailPage` — up to 6 overlapping avatars + "+N more" chip + Add modal with user search and role selector (owner / estimator / viewer / project_manager). Backed by 3 new project-scoped member endpoints (list / add / remove) delegating to the auto-created Default Team — no new table or migration. 14 `projects.team.*` i18n keys.
- Documents: password-protected share links — 6 endpoints (3 public `probe`/`access`/`download`, 3 owner `create`/`list`/`revoke`), bcrypt(12) password hashing, 32-char URL-safe tokens via `secrets.token_urlsafe`; revoked/expired/unknown all return 404 (no enumeration). `ShareLinkModal` in `FilePreviewPane` + public `/share/:token` page outside `RequireAuth`. 45 `files.share.*` / `share.page.*` i18n keys.

### Changed

- `/match-elements` compaction: single-row hero (28px h1 + 36px icon + paragraph subtitle, decorative blur removed), status cards (Catalogues / Embedder / Analytics) stacked → 3-col grid at `lg+`, steps 1 + 2 (BIM model / Session) stacked → 2-col grid at `lg+`. Step cards `mt-3 p-4 → mt-2 p-3`, number bubbles `5x5 → 4x4`. Reclaims ~330–390px of empty space above the matching table.
- `AddMemberRequest.role` regex widened to accept project roles (owner / estimator / viewer / project_manager) alongside existing team roles.

### Migrations

- `v2939_document_share_links` ← `v2938_documents_activity`

## [2.9.40] — 2026-05-12

### Added

- Projects: `POST /v1/projects/{id}/duplicate/` deep-clone — copies WBS tree, milestones, and `MatchProjectSettings`. Collapses a 34-line client-side workaround in `ProjectsPage`.
- RFI: `priority` + `discipline` + `linked_drawing_ids` + `attachments` fields on `oe_rfi`; pickers, deep-link rows, attachment upload, and linked-drawings picker on `RFIPage`. New `RFIDetailPage` (hero + question/answer + classification card).
- Documents: OCR-text search across `name` + `description` + `metadata.ocr_text` + sheet title / number.
- Documents: per-file activity log (`GET /v1/documents/{id}/activity/`) with 1s UTC-safe dedupe; rendered as `ActivityLogSection` in `FilePreviewPane`.
- File-manager: `SheetsIndexPage` and `FileContextMenu` components; inline PDF iframe preview in `FilePreviewPane`.
- `/costs`: `CostCategoryTree` skeleton-loading state + Toronto catalogue (`ENG_TORONTO` alias).

### Changed

- `/projects` and project Files: Apple-style dashboard backdrop (aurora + dot-grid + spotlight).
- `/match-elements`: tolerate both array and `{catalogues:[]}` envelope shapes from the catalogues endpoint.

### Migrations

- `v2937_rfi_priority_discipline` (RFI priority / discipline / linked_drawing_ids / attachments)
- `v2938_documents_activity` ← `v2937_rfi_priority_discipline`

## [2.9.39] — 2026-05-11

### Added

- Africa catalogue pack: 12 new `CWICR_V3_CATALOGUES` entries (NG_LAGOS, KE_NAIROBI, GH_ACCRA, UG_KAMPALA, TZ_DARESSALAAM, SN_DAKAR, CI_ABIDJAN, CM_DOUALA, AO_LUANDA, MA_CASABLANCA, EG_CAIRO, TN_TUNIS). Registry size 30 → 42. Anglo-Africa → nrm, Francophone → untec, Lusophone-Africa → masterformat, Maghreb-AR → masterformat.

### Fixed

- 71 legacy ranker monkeypatch refs in 3 test files (`test_phase0_edge_cases.py`, `test_match_concurrency.py`, `test_phase0_perf.py`) — dotted-path updated from deleted `app.core.match_service.ranker` to `ranker_qdrant`. Import errors cleared; 122 previously-erroring tests now pass.

## [2.9.38] — 2026-05-11

### Added

- Match-service universalisation: classification standards (`_KNOWN_CLASSIFICATION_STANDARDS`) + region-preferred-standard map (`_REGION_PREFERRED_STANDARD`) now data-driven from `CWICR_V3_CATALOGUES` + 30-country heuristic. 11 standards (DIN276, MasterFormat, NRM, UNTEC, VOCI, BC3, GB50500, SEKISAN, KBIM, GESN, BirimFiyat) instead of 3. FR→untec, IT→voci, ES→bc3, CN→gb50500, JP→sekisan, KR→kbim, RU/UA/BY/KZ→gesn, TR→birimfiyat.
- Region-group aliases moved to `data/match/region_groups.yaml`: 28 groups (19 baseline + ASEAN, MENA_AR, FRANCOPHONE_AFRICA, LUSOPHONE_AFRICA, ANGLO_AFRICA, ANDEAN, CAUCASUS, ANGLO_CARIBBEAN, LUSOPHONE_LATAM). Hardcoded fallback retained for resilience.
- Region-language mirror `data/match/region_language.yaml` (54 entries; not yet wired into runtime, ready for next pass).
- `CwicrV3Catalogue.default_classification_standard` field — populated on 19/30 entries with known mappings.
- `make seed-cwicr-v3` Makefile target + `backend/scripts/seed_cwicr_v3.py` CLI (`--regions CSV` xor `--top-n N`, `--dry-run`). One-shot install of N most-popular v3 catalogues for fresh deployments.
- `enumerate_qdrant_v3_collections()` helper in `qdrant_snapshot_loader.py` — live-probes the configured Qdrant for `cwicr_*_v3` collections.
- Per-encoder confidence profiles (`data/match/encoder_profiles.json`): bge-m3 / bge-small / e5-small / sonnet-rerank, each with high/medium/low bands. Surfaced via `config.confidence_thresholds_for_model()`.
- Per-language lex thresholds (`data/match/lex_thresholds.json`): 20 languages. Inflectional langs (pl/ru/uk/fi/tr/hu) drop to 70/50, CJK to 75/55, base 80/60. Surfaced via `config.lex_thresholds_for_language()`.
- `config.boost_weights_for_standard()` API stub for future per-standard tuning.
- `pyyaml>=6.0` added to base dependencies.

## [2.9.37] — 2026-05-11

### Added

- Africa pack: 19 currencies (NGN, KES, GHS, MAD, TND, DZD, ETB, UGX, TZS, RWF, XOF, XAF, AOA, MZN, BWP, ZMW, NAD, MGA + ZAR/EGP); 24 region codes (Anglophone, Maghreb, Francophone, Lusophone, ETB Amharic) — exposed in user settings dropdown.
- Dashboard stats badges (Projects/BOQs/Modules/Users) navigate to their pages.
- Dashboard Apple-style backdrop: aurora mesh, blueprint dot grid, vignette, cursor spotlight, fine-grain noise — auto-disabled by `prefers-reduced-motion`.
- /match-elements CatalogueAdvisor: one-click install for project-language catalogues when none are loaded — no /costs side-trip.
- Demo register: explicit email-domain-aggregate disclosure in the consent line.

### Fixed

- Typecheck: `Catalogue | undefined` narrowing in `CataloguesPanelCard` after positive `findIndex`.

## [2.9.36] — 2026-05-10

### Changed

- /match-elements 10-pass polish: replaced 3 blocking `alert()` calls in confirm/apply/skip flows with non-blocking toasts (success + error variants), unified error UI to a rose-toned `role="alert"` with explicit Dismiss + retry buttons, and split the group-list `max-h` into mobile-first (`max-h-[60vh]`) + desktop (`sm:max-h-[calc(100vh-360px)]`) so the table no longer collides with the keyboard on small viewports.
- /match-elements detail panel: added Escape key handler (with no-match modal precedence), `role="tablist"`/`role="tab"`/`aria-selected` semantics on the 3 detail tabs, error-state rendering with retry button, dropped stale "Phase A.12" reference from i18n string.
- /match-elements perf: replaced 11 separate `groups.filter()` passes (8 trade buckets + 3 stepper status counters) with one `useMemo`-cached pass — drops a tier-1 render from ~12ms to ~2ms for 1000-group sessions.
- MatchAnalyticsCard a11y: real i18n on collapse/expand `aria-label`, added `aria-expanded`, header row now `flex-wrap` so the window-selector + chevron don't fight for space on mobile.
- NoMatchModal + TemplatesPanel: `role="dialog"` + `aria-modal="true"` + `aria-labelledby`, Escape closes, all close buttons carry `aria-label`. NoMatchModal also surfaces the mutation error inline (was silently failing).

### Added

- 5 new integration tests for `GET /api/v1/match_elements/analytics`: empty window, days-out-of-range 422 contract, IDOR (other-tenant project_id → 404), tenant-wide rollup auth-only, unauthenticated 401/403. Pins the FastAPI route + auth wiring beyond the unit-level aggregator coverage.
- 12 new i18n keys for analytics/detail/no-match a11y + error states.

## [2.9.35] — 2026-05-10

### Added

- v3-§10 production analytics endpoint `GET /api/v1/match_elements/analytics?days=7&project_id=...&catalog_id=...`: rolls up `oe_match_elements_search_log` into KPI tiles (searches / pick rate / mean+p95 score / mean+p95 latency), tier + confidence-band histograms, top-N breakdowns by country / source_type / ifc_class, and three §10 threshold-driven alerts (low top score, picks past rank 4, hard-filter zero-hit). Pure-Python percentile to stay portable across SQLite (dev) and Postgres (prod). 18 unit tests green.
- `MatchAnalyticsCard` UI on /match-elements: collapsible card above Step 1, alerts pinned at top, expandable drill-down with KPI tiles + bar histograms + per-dimension breakdown tables. Window selector (1d/7d/30d/90d), 60s auto-refresh, soft-fail on endpoint error so the matching workflow keeps working when analytics is unreachable. 30 i18n keys added.
- `MATCH_ALERT_*` env knobs (`MATCH_ALERT_LOW_SCORE_VALUE` / `_PCT`, `MATCH_ALERT_HIGH_RANK_VALUE` / `_PCT`, `MATCH_ALERT_ZERO_HIT_PCT`, `MATCH_ALERT_MIN_SAMPLE`) for tuning §10 thresholds without a rebuild; defaults match MAPPING_PROCESS.md (low-score 0.3/20%, high-rank 4/20%, zero-hit 10%, min-sample 20).

## [2.9.34] — 2026-05-10

### Added

- /match-elements language-mismatch banner: detects when bound CWICR catalogue speaks a different language than project region, surfaces "Re-bind catalogue" CTA — `auto_bind_dominant_catalogue` now language-aware (US project no longer auto-binds to RU_MOSCOW just because RU has the most rows).
- /match-elements 2026 hero redesign: gradient identity block + 4-step workflow indicator (Pick model → Open session → Review matches → Apply to BOQ) + numbered section cards.
- Image source adapter (`sources/image_adapter.py`, ~430 LoC): photo/drawing snapshot → AI-vision (Claude/GPT-4V via existing `ai_client.call_ai`) → SourceElement[]; pinned to `low` confidence by design; falls back to `[]` on missing API key / 4xx / 5xx / malformed JSON. 22 unit tests green.
- Recall benchmark scaffold `tests/perf/test_recall_bge_m3_benchmark.py` (20 queries: 6 EN + 6 DE + 6 RU + 2 ES, recall@1/5/10 markdown output, `@pytest.mark.benchmark`).
- Free-language-model status endpoint `GET /api/v1/costs/embedder/status/` + `EmbedderStatusCard` UI on /match-elements: surfaces BGE-M3 install state with one-line `pip install --upgrade openconstructionerp[semantic]` install card (amber) when missing, compact green pill when ready. MIT · 100+ languages · runs locally · no API key — sits above Step 1 so the user sees the install path before picking a model.
- v3-§4.1.5 BoQ `exact_code` short-circuit: when an Excel BoQ row carries an explicit CWICR rate code, the ranker bypasses Qdrant fan-out + reranker and pulls the rate directly from parquet. New `ElementEnvelope.exact_code` field, forwarded by `_envelope_from_group`; `_try_exact_code_short_circuit` in `ranker_qdrant` returns a HIGH-band candidate at score 1.0 with `boosts_applied={"exact_code": 1.0}`. Falls through to vector search when the code isn't in the catalogue. 10 unit tests green.
- v3-§6.2 cross-language code translation helper `cross_lang_lookup(source_rate_code, target_country)` in `qdrant_adapter`: strips lang+unit suffix via `base_code`, enumerates plausible target-lang variants, scrolls the target collection in one round-trip with `MatchAny + country` predicates. Defensive — degrades to `None` on Qdrant failure / missing extras. 7 unit tests green.
- v3-§10 search-log feedback loop (alembic v2936): adds `picked_rank` / `picked_rate_code` / `picked_at` / `source_type` / `ifc_class` / `country` columns to `oe_match_elements_search_log` plus 3 indexes. The /confirm hook backfills the user-pick fields onto the most recent log row for the (session, group) pair so MAPPING_PROCESS.md §10 alerts (`user_picked_rank > 4 for >20%` → re-train classifier) become observable. `_write_search_log` populates source_type/ifc_class/country at INSERT time so analytics queries no longer need a 3-table JOIN. 14 unit tests + idempotent migration smoke green.
- Unit-conversion regression test (`tests/unit/test_split_unit_multiplier.py`, 26 tests): pins the v3-§8.6 `100 м3 → divide-by-100` math at `service.py:1917` so a refactor can't ship a 100× cost spike.

### Changed

- BGE-M3 confidence bands re-pinned: `MATCH_CONFIDENCE_HIGH` 0.85 → 0.78, `MATCH_CONFIDENCE_MEDIUM` 0.70 → 0.62, `MATCH_AUTO_CONFIRM_DEFAULT` 0.95 → 0.88. BGE-M3 cosine sits 5-8 points lower than e5-small for the same semantic neighbourhood. Tests rewired to derive scores from constants instead of hardcoded floats.
- Default `vector_backend` and `match_backend` switched from `lancedb` to `qdrant`. Legacy `lancedb` value rejected by validator on `match_backend`.
- v3 universality DB defaults: `Invoice.currency_code`, `Payment.currency_code`, `ProjectBudget.currency_code`, `CostItem.currency`, `Assembly.currency` now default `""` instead of `"EUR"` (#217). Service layer is the source of truth for currency.
- /match-elements project context card: 12×12 gradient icon, larger h2 title (`text-lg lg:text-xl`), bigger spacing, `shadow-sm`.

### Removed

- LanceDB legacy code paths (Phase 5): `app/modules/costs/vector_adapter.py`, `app/core/match_service/ranker.py`, `app/core/match_service/boosts/lex.py`, `app/core/match_service/boosts/rare_token.py`, `app/modules/match_elements/matchers/lexical.py`. Sparse Qdrant + BGE-M3 supersedes them.

### Fixed

- Bug-report capture: `getLastError()` prefers level=error over warning in the recent 32-entry window — handled 404s no longer leak into auto-filed reports (#115).
- FX rate input on /projects/.../settings now shows live bidirectional preview (`1 ARS = 0.000707 USD` AND `1 USD = 1415 ARS`) so inverse-direction currencies don't trip up the user (#111).

## [2.9.33] — 2026-05-08

### Added

- **Parallel Qdrant + BGE-M3 match pipeline (default OFF, opt-in via `MATCH_BACKEND=qdrant`).** Foundation for the next-generation CWICR matcher: 30 per-language Qdrant collections (`cwicr_<lang>`) with three named vectors per point — `dense` (1024-dim BGE-M3 multilingual), `sparse` (BM25-like for verbatim term hits like `C30/37`, `DN200`, `B500B`), `resources` (top-12 unique resources per rate) — fused via Qdrant native RRF in one round-trip. Minimal payload + lazy `polars.scan_parquet()` lookup keeps the embedded store under 700 MB and full 84-column rate data under 50 ms on warm cache. New modules at `app/modules/costs/qdrant_adapter.py`, `parquet_lookup.py`, `query_builder.py`, plus a parallel `app/core/match_service/ranker_qdrant.py` that swaps in via the `match_backend` setting. Smoke endpoint `GET /api/v1/costs/qdrant-search/?q=...&country=DE&diag=1` exercises hits + parquet attach + filter coverage. Legacy LanceDB + e5-small ranker stays default — no behavioural change without the env flag. Required CWICR Qdrant store + parquet root land separately (DDC pipeline).
- **3-channel structured query: CORE / native filters / resources.** New `query_builder.build_query(envelope)` splits the matcher request into a curated CORE text (category + type + material + thickness/diameter/fire/U) feeding dense+sparse, native Qdrant predicates (`is_abstract=False`, `department_code=<2-digit DIN>`, `unit_dim=volume|area|length|count|mass|time`), and an optional `resources_query` that activates only when the envelope carries verbatim rare tokens. Replaces "stringify everything into one passage" — BGE-M3 stops diluting the strong signal across noisy bits like Level/GUID/family-id.

### Improved

- **Match recall v3 — three orthogonal lifts on the legacy ranker (in production today, no flag flip needed).**
  - **Trade-aware DIN-276 pre-filter.** `cost_vector.search()` accepts `din276_kg_prefix` and filters `payload.classification_din276` at the LanceDB hit-decode stage by the leading 2 digits of the envelope's DIN hint. Wall envelopes (33) no longer compete with pipework (44) for top-K slots. Auto-disables when fewer than 20% of fetched hits carry any DIN value, so BYO catalogues without classification metadata keep working.
  - **Rare-token lexical boost.** New `boosts/rare_token.py` lifts candidates that verbatim-match technical tokens the multilingual encoder dilutes as low-frequency subwords: concrete grades (`C30/37`, `C25/30`), pipe nominals (`DN200`), bolt sizes (`M16x60`), steel profiles (`HEB200`, `IPE160`), rebar grades (`B500B`), fire ratings (`F90`), steel grades (`S235`), diameters (`Ø14`). +0.06 per hit, capped at +0.15. Tunable via `MATCH_BOOST_RARE_TOKEN_*` env vars. 19 unit tests pin the extraction + cap behaviour.
  - **Unified region/catalogue → language map.** `_REGION_LANGUAGE` (vector_adapter) and `_CATALOG_LANGUAGE` (ranker) had drifted (`UK_GBP` vs `GB_LONDON`, `CS_PRAGUE` vs `CZ_PRAGUE`, `SP_BARCELONA` vs `ES_MADRID`, `ENG_TORONTO` vs `CA_TORONTO`) — every miss silently broke the translation cascade. Hoisted both into one canonical 45-entry table at `app/core/match_service/region_language.py` with a historical-alias resolver. 41 unit tests cover canonical + aliases + edge cases.

## [2.9.32] — 2026-05-08

### Fixed

- **/projects no longer fetches full BOQ detail payloads to read one number per BOQ.** v2.9.x's project-list page issued one `/v1/boq/boqs/{id}` per BOQ (each 100–230 KB of position rows) just to extract `grand_total` for the project card — totalled ~700 KB of waste on a workspace with 5 projects × 5 BOQs. The list endpoint already returns `grand_total` (and `position_count`) on each `BOQListItem`; extended `BOQBasic` to include it and dropped the secondary detail-fetch loop entirely. `/projects` page weight drops from ~857 KB to ~130 KB on the same dataset.
- **`/api/system/status` no longer fires twice on every page.** DemoBanner used a raw `fetch()` while DashboardPage used `useQuery({ queryKey: ['system-status'] })`. Switched DemoBanner to the same React Query key so the two components share one network call. Saves one round-trip per dashboard render in production.
- **Project weather widget no longer 400s on every project card.** v2.9.30 bumped Open-Meteo's `forecast_days` from 16 to 18, but the free `/v1/forecast` endpoint caps at 16 — every project card on the dashboard fired five 400 Bad Request responses to `api.open-meteo.com` and the widget rendered empty. Capped back at 16 (the practical horizon) and updated the title/copy/comment from "18-day forecast" to "16-day forecast" so the visible label matches what's fetched.
- **`<button>` nested inside `<button>` warnings on /bim and /dwg-takeoff.** ModelCard (BIMPage) and DrawingFilmstrip card had the entire card rendered as a `<button>` with a `<button>` (delete) inside — invalid HTML, React DOM validation warning. Switched the outer card to `<div role="button" tabIndex={0}>` with explicit Enter/Space handlers and matching focus ring; the inner real `<button>` keeps its accessible behavior and stops `stopPropagation`-ing on a parent button (which produced subtly broken keyboard focus).
- **/match-elements vector matcher now actually returns hits on first run.** Two upstream bugs combined to make every "Run vector match" click return zero candidates: (a) projects with no `cost_database_id` in `oe_projects_match_settings` short-circuited the ranker with `status="no_catalog_selected"` and an empty candidate list, and (b) the embedder singleton failed to load when first invoked from a worker thread (asyncio dispatches every encode through `asyncio.to_thread`), leaving every `encode_texts_async` call falling through to the SQL lexical fallback with the warning "No embedding model available". Fix (a): `MatchElementsService.create_session` and the run_match path call new `auto_bind_dominant_catalogue()` which picks the most-loaded vectorised CWICR catalogue and writes it onto the project's match settings — idempotent, no-op when already bound. Fix (b): `app.main` lifespan now primes `get_embedder()` synchronously on the main thread before scheduling the auto-backfill task, so the singleton is loaded before any worker thread races for it. After both fixes a fresh project's first vector match goes from 0 candidates to ranked top-10 in ~11 s for 3 groups (vs 47 s SQL-fallback before).

### Added

- **New `/match-elements` module — BIM elements → CWICR cost positions in one pass.** Estimator picks a project, page auto-creates a Match session over `oe_bim_element` grouped by `(ifc_class, type_name)`, then runs vector / lexical / resources matchers (the third one searches the materials catalogue `oe_catalog_resource`, not just CWICR). Slide-over detail panel shows side-by-side per-matcher candidates, full element-id list, and a dry-run BOQ preview with auto-scaled resources (concrete + formwork + rebar) loaded from each `CostItem.components` recipe. Multi-select bulk-actions (run matchers / confirm ≥ threshold / mark TBD), tenant-scoped template library (signatures persist across projects), and a no-match modal (custom position / RFQ / TBD) round out Phase A. New backend module at `app/modules/match_elements/` with 17 endpoints under `/api/v1/match_elements/*` (sessions, groups, match, confirm, bulk-confirm, apply, no-match, attributes, categories, templates). Migration `v2932_match_elements.py` adds `oe_match_elements_session`, `oe_match_elements_group`, `oe_match_elements_template` (with cross-project signature uniqueness on `(tenant_id, signature)`). Frontend at `frontend/src/features/match-elements/` (page + 3-tab detail panel + templates panel + no-match modal). Sidebar entry "Match Elements → Costs" with NEW badge. DWG / PDF / Photo source adapters are pluggable and land in Phase B–D.
- **Match-elements matcher perf — top-10 cap + lexical SQL prefilter.** First /match POST without explicit `group_keys` previously iterated every unmatched group (174 s for 16 / unbounded for 274). Now defaults to the 10 largest groups (configurable via `max_groups`); the lexical matcher prefilters CWICR with ILIKE on meaningful tokens (≥3 chars) capped at 1 500 candidates before fuzz scoring. Lexical match on a 274-group Berlin project drops from "never finishes" to ~12 s for 10 groups. Action-bar labels updated to "Vector / Lexical / Match resources — top 10".

## [2.9.31] — 2026-05-07

### Fixed

- **BOQ resource sub-rows now align column-for-column with position rows.** v2.9.29 refactored the resource row to a column-driven layout reading live AG Grid column geometry, but `computeLeftPad()` still added a `+56px` "indent nudge" on top of the helper-column widths. That nudge shifted every downstream slot — Unit, Quantity, Unit rate, Total, Actions — 56 pixels right of the matching position cell, so the columns no longer lined up vertically. Removed the nudge: `leftPad` is now exactly `_drag + _checkbox + _expand` width, matching the position row's left edge. Visual differentiation between position and resource rows still comes from the inset shadow, secondary background tone, and the provenance left-edge bar.
- **Documents-module download no longer returns 403 for demo PDFs whose stored `file_path` resolves outside the current upload base.** The download endpoint's path-containment guard treated *any* resolved path outside `UPLOAD_BASE` as a security violation (HTTP 403 "Access denied"), even when the document was a synthetic demo seed record whose placeholder hadn't been materialized yet. Re-anchors demo PDFs to a deterministic safe path inside `upload_base` (`{base}/demo/{doc.id}.pdf`) before the materialize-placeholder step, and degrades real uploads with stale paths to HTTP 404 "File not found on disk" instead of 403. Path-traversal protection (symlink rejection, strict containment) still applies to non-demo paths. Surface: `/files?kind=document` → click → `/takeoff?doc=…&source=document` no longer fails to load PDF on fresh installs.

## [2.9.30] — 2026-05-07

### Changed

- **Project weather forecast extended from 16 to 18 days.** `ProjectWeather` widget now requests `forecast_days=18` from Open-Meteo (capped server-side if the free tier rejects it) and the project detail card / summary chip labels reflect the new horizon. Affects the full grid on `/projects/:id` and the one-line stat chip on dashboard project cards.

### Fixed

- **`/reports` BOQ-export error toasts no longer dump raw HTML/error pages into the UI.** `downloadBoqExport()` previously threw `new Error("Export failed (500): " + response.text())`, so a backend error returning an HTML 502 page or a Caddy/nginx error template was rendered verbatim in the toast — including unparsed `<html>` markup. Now the response body is parsed as JSON first to extract a FastAPI `detail` string; falls back to short plain-text bodies via the shared `extractErrorMessageFromBody()` helper, which already rejects HTML-shaped strings and length > 240. Toasts now show either a clean detail message or just the status code.

## [2.9.29] — 2026-05-07

### Fixed

- **BOQ resource sub-rows now align column-for-column with position rows when custom regional-preset columns are added (e.g. GAEB EP-split, AIQS preset).** Resource rows render through AG Grid's full-width row mechanism with a hand-built flex layout. The layout used hard-coded column slots (`unit`, `quantity`, `unit_rate`, `total`, `_actions`) and the `description` slot was `flex-1` — when custom columns inserted between `total` and `_actions` widened the row, the `flex-1` name slot absorbed the extra width and every right-side cell (Unit, Qty, Rate, Total, Actions) drifted leftward relative to the position row above. Refactored `EditableResourceRow`, `VariantHeaderResourceRow`, and the Add-resource path to a column-driven layout: each renders by iterating `api.getAllDisplayedColumns()` and laying out its slots at exactly each column's `getActualWidth()`. Custom columns (`colId` starting with `custom_`) on resource rows now show the per-resource value from `position.metadata.resources[i].metadata.custom_fields[name]` (read-only — editing per-resource customs from the resource sub-row will follow); unknown columns get an empty placeholder of the correct width. Resources, variant headers, and the Add-resource band stay in lockstep with position columns regardless of how many custom columns the user adds.
- **Multi-currency BOQ totals now rebase per-position currencies into the project base before summing (Issue #111).** v2.9.1 closed Issue #88 (multi-currency BOQ) by adding per-project FX rates and a view-only display-currency override, but a position priced in a non-base currency (`metadata.currency` set to e.g. `ARS` inside a USD project) had its raw `total` summed straight into `directCost` and rolled into the column footer / Grand Total as if it were already in base. Result: a USD project with one ARS position and one USD position summed `1415 + 100` as `1515 USD` instead of converting the ARS leg through the project FX table first. New `convertToBase()` helper in `boqHelpers.ts` reads `metadata.currency` per position and multiplies by the configured `1 foreign = X base` rate. Wired through (a) the `total` column's `valueGetter` (so per-row cells display in base), (b) `BOQEditorPage`'s `directCost` reducer, and (c) `groupPositionsIntoSections`' subtotal accumulator (so section subtotals also rebase). When no FX rate is configured for a position's currency, the helper logs a console warning and falls back to the raw value rather than crashing — surfaced in dev tools so the missing rate is diagnosable.

### Changed

- **`maplibre-gl` (1 MB) no longer ships in the cold-load critical path.** `ProjectMap` was re-exported eagerly from `@/shared/ui`, which dragged the maplibre runtime into every chunk that imported anything from the shared UI barrel — even pages that never render a map. The barrel now exports a lazy wrapper (`ProjectMapLazy`) that wraps the real component in `React.lazy + Suspense`. Map-bearing routes (`/projects`, `/projects/:id`) pull maplibre on demand; everywhere else it's gone from the initial preload graph. `index.html` no longer module-preloads the 1 MB maplibre chunk.
- **Requirements file-import endpoint now caps payloads at 50 MB.** v2.9.12 lifted the global upload size cap, which left `POST /requirements/{set_id}/import/file/` reading the entire upload via `await file.read()` with no ceiling — a 500 MB CSV would OOM the worker before parsing started. Returns HTTP 413 above 50 MB, which is generous for requirement spreadsheets (typical real files are <2 MB).

## [2.9.28] — 2026-05-07

### Security

- **AI Cost Advisor chat is now rate-limited.** `POST /api/v1/ai/advisor/chat/` previously had only the `ai.estimate` permission gate; an authenticated caller could hammer the endpoint and burn through their BYO provider quota. Added the same `check_ai_rate_limit` dependency that gates `/quick-estimate`, `/photo-estimate`, and `/file-estimate`, plus the `X-RateLimit-Remaining` response header so the UI can surface remaining quota.
- **Provider error messages no longer leak into AI chat answers.** The chat fallback used to concatenate `str(exc)[:100]` from a failed LLM call into the user-facing answer string. Provider error bodies sometimes echo masked key prefixes, org IDs, or upstream debug headers. Now the full error is logged for ops, and the user only sees the localised "AI is not configured" fallback.
- **AI chat conversation history is hard-capped at 4 KB total.** Combined with the 10-message and 500-char-per-message caps, a malicious caller could still pad prompts past the budget of small-context providers (Mistral, Cohere). Iteration now stops at the first message that would exceed the running 4000-char budget.

### Fixed

- **Schedule activity dates: structural regex no longer accepts impossible calendar dates.** `start_date` / `end_date` matched `^\d{4}-\d{2}-\d{2}$`, which let `2026-02-30` and `2026-13-99` reach `compute_duration` and return bogus durations. Validation now re-parses via `date.fromisoformat()` and rejects on invalid month/day before the value is stored.
- **Schedule activity-embedded `dependencies` updates now run cycle detection.** `POST /schedules/{id}/relationships/` already rejected circular dependencies, but `PATCH /activities/{id}` accepted a `dependencies: list[ActivityDependency]` payload that bypassed the check entirely — a back door that let CPM compute_paths recurse forever. The same self-reference + BFS cycle test is now applied at the service layer for the activity-JSON path too.

### Changed

- **DuckDB ad-hoc connections are capped at 512 MB and 2 threads.** The dashboards module's per-snapshot DuckDB pool used `duckdb.connect(":memory:")` with the default settings — DuckDB's default `memory_limit` is 80 % of system RAM, so a single bad cascade query against a multi-million-row Parquet could pin a worker. Pool now sets `memory_limit='512MB'` and `threads TO 2` immediately after connect; failures are logged but non-fatal for older DuckDB versions.
- **BIM requirements validation caps at 50 000 elements per pass.** `validate_requirement_set_against_model` previously fetched up to 1 000 000 elements before iterating `requirements × elements`; for a 100 k-element model × 50 requirements that's 5 M evaluations on the request thread. The repository now stops at `MAX_ELEMENTS_PER_VALIDATION + 1`, the report flags `elements_truncated: true` when the cap kicks in, and a `WARNING` is logged so users can see why the partial scope appeared.

## [2.9.27] — 2026-05-07

### Added

- **BOQ custom columns are now editable per-resource, not just per-position.** Previously, supplier / lead time / QC inspector / tender package etc. on a resource sub-row inherited the parent position's value and were read-only — so a position with a concrete supplier and a rebar supplier had to share one "supplier" cell. Resource rows now accept their own value, stored at `position.metadata.resources[i].metadata.custom_fields[name]` via a deep merge that doesn't touch other resource fields. The cell's `valueGetter` reads the per-resource value first and falls back to the position-level value, so a "globally true" position-level value still propagates to resource rows that haven't been overridden. New `onUpdateResourceCustomField` handler in `BOQEditorPage` PATCHes only `metadata` (no `unit_rate` re-derivation — custom fields don't affect price). Derived columns (`resource_sum`, `percentage_of_unit_rate`) and calculated columns stay read-only on resource rows because their values are auto-computed.

## [2.9.26] — 2026-05-07

### Fixed

- **BOQ horizontal overflow when 4+ regional-preset columns were added.** Custom columns had a 80 px `minWidth` and no `flex` — `sizeColumnsToFit` couldn't shrink them, so adding the GAEB EP-split (4 columns) or AIQS preset (5 columns) pushed the right edge past the viewport on a 1366-1440 px laptop. Description column also had a 260 px floor that compounded the problem. Lowered custom-column `minWidth` to 56 px (~3 letters of header + padding), gave each custom col `flex: 1`, and set the description column to `flex: 3` with a 180 px floor — the BOQ now redistributes width evenly across all visible columns instead of overflowing.
- **GAEB EP-split no longer added up to less than `unit_rate` when a position carried operator / subcontractor resources.** `Sonstiges-EP` was wired with `resource_role: 'other'`, so the catch-all column ignored `operator` and `subcontractor` resources entirely — `Lohn + Material + Geräte + Sonstiges` came out short by the operator/subcontractor share. Widened `resource_role` to accept either a single role or a list (backend Pydantic + frontend column-def types), normalised matching through a `Set` membership check, and updated the GAEB preset to `['other', 'operator', 'subcontractor']`. The badge in `CustomColumnsDialog` renders the multi-role hint as `other / operator / subcontractor`.

### Changed

- **`/settings → Advanced` redesigned for clearer block layout.** `BackupRestore` now renders Export and Restore side-by-side on desktop instead of stacking — the import dropzone no longer sits below an empty stretch of Export-card whitespace. The two single-button maintenance cards (Databases & Resources, Setup Wizard) collapsed into a single `Maintenance & Setup` card with two action-rows (icon + title + description + Open button) so the lower part of the tab no longer reads as two stranded half-cards.
- **`/costs` now mirrors the BOQ "From Database" classification tree.** Added a 260 px sticky sidebar on desktop that fetches the full 4-level classification (collection → department → section → subsection) via `/v1/costs/category-tree/?depth=4` and drives the search via the `classification_path` filter. Click selects, the chevron toggles expand independently, and the in-tree filter input keeps deep matches reachable. The legacy flat `category` dropdown is retained as a secondary filter.
- **Dashboard "developed by" hint above the DDC logo** is now lower-cased, smaller (`9px`), tracking-normal, with a left indent — was reading too loud as small-caps.

### Cleanup

- **Local dev DB**: 6 732 polluted contact rows from earlier CRM-import smoke runs were deleted; one well-described example (`Patricia Martinez @ Downtown Health System`) is retained. FK columns in `oe_finance_invoice`, `oe_correspondence_correspondence`, and `oe_procurement_po` were already null / pointed at the survivor — no operational data nulled. VACUUM ran clean.

### Verified

- **Issue #113** (`[BUG] can't get any IFC or Revit file to be viewed in the 3D viewer`) — closed. End-to-end check on a fresh `pip install openconstructionerp==2.9.25` venv: IFC upload → conversion `status=ready` (289 elements, 4 storeys), `/elements/` returns finite bboxes for 37/50 sampled rows, `/geometry/` returns 302 KB `model/vnd.collada+xml`. Likely fixed by v2.9.21 (IFC conversion regression) + v2.9.22 (`ORJSONResponse` removed — orjson rejects `NaN` in bbox coords).

## [2.9.25] — 2026-05-07

### Fixed

- **`/costs` list view scaled poorly with no region filter — 80 s for one page on a 111 k-row catalogue.** Companion to v2.8.3's `(region, is_active, code)` composite index. The leading-column rule meant the previous index could not satisfy `WHERE is_active=? ORDER BY code` when no `region` filter was supplied (the default "all regions" view). SQLite fell back to `ix_costs_is_active` plus a temp B-tree sort over the entire active set. Added `ix_costs_active_code` `(is_active, code)` to mirror the per-region index for the all-regions case — the same query now plans against the new B-tree directly. Measured 15 s → 1 ms (~10 000×) on the dev box. Migration `v2924_costs_active_code_index` is inspector-guarded so re-running is a no-op.
- **Seeded "Sarah Chen" demo account had role `estimator`, which neither the registration schema nor the admin update schema accepted.** The 4-role frontend (`admin|manager|editor|viewer`) rendered her with the viewer fallback and the role dropdown produced 422s on submit. Aligned the seeder + `AdminUserCreate.role` Literal on `editor`. Migration `v2924_normalize_estimator_role` rewrites any pre-existing `estimator` rows on production DBs that booted the older seeder. The legacy `estimator → EDITOR` permission alias is retained so old runtime checks still work.

## [2.9.24] — 2026-05-07

### Added

- **One-click DWG converter install on `/dwg-takeoff`.** The "Install converter" pill in the page header now opens a popover with an actual install button — clicking it POSTs to `/v1/takeoff/converters/dwg/install/` (the same endpoint the `/bim` page uses for RVT/IFC), and the offline-readiness query refetches so the badge flips to green "Offline Ready" the moment the binary is detected. On Linux the popover surfaces the apt one-liner from the backend instead of attempting an auto-shell-out. Closes the gap reported as "нужно одним нажатием установить актуальный последний конвертер".
- **"New version available — recommend updating" amber banner on the BIM converter panel** (dismissible per session). Previously the only signal that a newer SHA existed upstream was the small `→ def5678` tail — easy to miss. The expanded panel now renders an amber banner whenever `version-check.any_outdated` is true, with an X to hide it for the current session (sessionStorage; reappears on next visit). Banner is i18n-keyed.
- **Mini-icon mode on the BIM converter panel when everything is fully up to date.** The panel now collapses to a single emerald `N/M` pill ("4/4" when all four converters are working AND on the latest SHA). Click expands to the full strip + details. Per Artem's spec: "если все конверторы на самом последней версии то это окно показывать не нужно и можно сделать только маленький значок".
- **Per-converter "card" rendering on the BIM converter panel.** Each row now has a tinted background + rounded border that mirrors the row's state (emerald = working & up to date, amber = working but outdated or missing binary, rose = broken). Replaces the dense single-line strip — one glance now tells you which row needs attention.

### Changed

- **Green pill is now reserved for "working AND on the latest version".** Per-row pills downgrade to amber `Working · update available` when the version-check flags an outdated SHA — green no longer means "smoke-test passed but the binary is from three months ago". Panel-level summary changes from `"X/Y verified"` to `"X/Y up to date"` / `"X/Y working · update available"` / `"X/Y working"` to match. The header tone (border + background) likewise stays amber until everything is on the latest SHA.
- **Dock entries can be dismissed mid-conversion.** Previously the corner upload dock only offered Cancel during `uploading`/`converting`, which aborted the actual server-side work. A separate Dismiss action is now available in every state — it just clears the dock entry; the server keeps processing. Closes the "10m+ stuck at 95% Modelleinrichtung wird abgeschlossen with no way out" complaint.

### Fixed

- **`oe_dwg_takeoff` and `oe_takeoff` modules no longer trapped in a disabled state.** When persisted module-state was set to `enabled: false` (e.g. from an earlier admin-toggle test), `/dwg-takeoff` rendered as "module is disabled" and the install endpoint at `/v1/takeoff/converters/{id}/install/` returned 404, leaving the user with no recoverable UI surface. The install button now triggers the install on a known-loaded module path; if a fresh install ever lands with these modules disabled, the toast points back at the `/modules` admin page instead of failing silently.

## [2.9.23] — 2026-05-07

### Fixed (Wave A — bugs.md/improvements.md QA pass)

- **BUG-011 (P0) — Validation `boq_quality.empty_unit` false positives.** `app/modules/boq/router.py` `validate_boq` projected positions into a dict that dropped `unit`, `parent_id`, `total`, and the row-`type` marker. Every `boq_quality.*` rule reads those keys, so they uniformly received `None` and lit up red on every leaf row of every fresh BOQ. Restored the missing keys + a derived `type` flag so section-header skipping works again. Also added a parametrised contract test in `backend/tests/unit/test_boq_validate_payload.py` so the next field drop fails CI loudly.
- **BUG-012/013 (P0) — Cost catalog and global search worked only with LanceDB.** `costs/router.py` silently ignored `search` / `name` / `description` / `query` params and `search/router.py` returned 0 hits whenever the vector backend was unavailable (the default for `pip install` without `[vector]` extras — main value-prop dead). `costs` now accepts `search` + `query` as silent aliases of `q`, and `name` / `description` as scoped substring filters; the repo issues a cross-dialect `LIKE`/`ILIKE`. Global `/api/v1/search/` now ALWAYS runs the SQL fallback against BOQ positions / tasks / risks / documents / requirements / cost items and fuses the result with the vector hits (when present) via reciprocal-rank merging. 31 new unit tests pin the contract.
- **BUG-015 (P1) — `POST /api/v1/procurement/` silently dropped `items[]`.** `procurement/service.py::create_po` refreshed the PO before line items were inserted (so `po.items` came back empty) and pulled `amount_subtotal` straight from the request (default `"0"`) instead of summing the lines. Now pre-aggregates the subtotal, fills missing per-line amounts, and reloads the PO via the selectinload-backed `get(po.id)` so the response carries the lines. New `test_create_po_persists_items_and_reaggregates_totals` covers the exact reproducer from the QA report.
- **BUG-018 (P1) — `POST /api/v1/backup/export/` returned an empty zip.** Handler had no body schema and used a `StreamingResponse` over `io.BytesIO` that interacted badly with the request-side body. Replaced with an `ExportRequest` body and a streaming-to-`SpooledTemporaryFile` builder that writes a populated `manifest.json` plus per-module JSON dumps; FastAPI now serves it back via `FileResponse` with a `BackgroundTask` cleanup. Smoke-tested locally: 186 KB zip, 20 module dumps.
- **BUG-008 (P1) — `grand_total` differed between BOQ list and detail.** List included markups (25830), detail returned the position-sum-only (20500). Two screens, two numbers, same field name — broke trust in every export and dashboard. `boq/repository.py` now exposes `totals_for_boqs()` returning the full `{direct_cost, markups_total, grand_total}` breakdown; both list (`BOQListItem`) and detail (`BOQWithPositions`) consume it. Schemas grew explicit `direct_cost_total` + `markups_total` + `position_count` so clients no longer have to re-sum markups. `grand_total` is canonical "with markups" (matches what users see on dashboards).
- **BUG-005 (P1) — DXF layers all imported as `visible: false`.** `dwg_takeoff/dxf_processor.py:184` evaluated `not layer.is_off and not layer.is_frozen` in a single expression; on certain R2018-vintage files ezdxf raises while accessing `is_off`, the whole expression silently collapsed to False, and the canvas rendered empty after import. Pulled each bit through its own try/except and now defaults to visible — only flips to hidden when the source file *explicitly* reports off/frozen.
- **BUG-014 (P2) — DXF SVG thumbnails always rendered the placeholder.** ezdxf 1.4 removed `Frontend.out`; the call `frontend.out.get_string()` raised `AttributeError` on every drawing and the handler swallowed it into the placeholder branch. Switched to `SVGBackend.get_string()` (with a fallback to the 1.5-era `get_xml_root()`) so thumbnails actually render again.
- **BUG-002 (P1) — `/health` and `/openapi.json` returned the SPA `index.html`.** k8s liveness probes saw HTTP 200 with `text/html` and reported the service healthy even when the API was dead; openapi-typescript generators couldn't reach the schema. Added 308 redirects from `/health → /api/health` and `/openapi.json → /api/openapi.json` ahead of the SPA 404 fallback (only when `SERVE_FRONTEND=true` — pure-API deployments are unchanged).
- **BUG-006 (P3) — `BIMModel.import_date` always null on ready models.** Stamped during the `processing → ready` transition in the conversion background worker.
- **BUG-001 — verified not reproducible:** demo-catalog endpoint returns proper UTF-8 (`€12M`, `£45M`); the QA report's mojibake was a Windows-console rendering artifact in the curl output.

### Changed (security / DoS hardening)

- **Streaming uploads for BIM CAD files.** `app/core/upload_streaming.py` (new) spools `UploadFile` to a temp file in 1 MB chunks and exposes `head` for magic-byte checks; `app/core/storage.py` grew an abstract `put_stream(key, src_path)` with a true zero-copy `shutil.move`-based override on `LocalStorageBackend` and an `upload_fileobj` (multipart-aware) override on `S3StorageBackend`. `bim_hub/router.py` upload-cad now reads through `stream_upload_to_temp` instead of `await file.read()`; on the local backend the temp file is renamed straight into place — peak memory bounded by the chunk size regardless of upload size. Closes the memory-DoS vector that opened up when we removed per-route size caps.

## [2.9.22] — 2026-05-07

### Fixed

- **Hotfix: revert `default_response_class=ORJSONResponse` from v2.9.21.** orjson rejects NaN/Infinity floats by default — DDC cad2data BIM elements can emit NaN bbox coordinates for degenerate geometry, which broke `/api/v1/bim_hub/{model_id}` element-list responses with a 500 and surfaced as "IFC conversion broken" in the UI. FastAPI's own deprecation warning also flagged the override as unnecessary ("FastAPI now serializes data directly to JSON bytes via Pydantic when a return type or response model is set, which is faster"). orjson is still used by handlers that explicitly opt in.

## [2.9.21] — 2026-05-07

### Changed (perf — backend & static serving)

- **Default response class is now `ORJSONResponse`.** `app/main.py` passes `default_response_class=ORJSONResponse` to `FastAPI(...)` so every endpoint serialises via orjson instead of stdlib `json`. Typically 5–10× faster on dict/list payloads and ~2× faster at producing UTF-8 bytes — measurable wins on dashboard / list / vector-search endpoints. orjson was already a base dep (used by the non-finite-float middleware).
- **Immutable `Cache-Control` on hashed `/assets/*`.** `app/cli_static.py` mounts `/assets` via a custom `_ImmutableStaticFiles` subclass that adds `Cache-Control: public, max-age=31536000, immutable` to every 200 response. Vite emits content-hash filenames so the URL changes whenever the file changes — repeat visits now skip the network entirely for JS/CSS chunks.
- **`Cache-Control: no-cache` on the SPA `index.html` fallback.** Same file. The entry HTML must revalidate every reload — a stale cached entry would point at hashed URLs that may have been deleted by a redeploy. Now: hashed assets cached forever, entry always fresh.

### Changed (perf — frontend)

- **`buildGeocodeQuery` extracted to its own file.** `frontend/src/shared/ui/ProjectMap/geocode.ts`. Previously consumers like `DashboardProjectsMap.tsx` imported the helper directly from `ProjectMap.tsx`, which side-effect-imported `maplibre-gl/dist/maplibre-gl.css` (~220 KB raw / ~25 KB gzip) into the boot CSS bundle. The helper is a pure string-builder with zero deps, so the new module isolates it cleanly.

### Changed (UX — project detail)

- **Weather forecast now renders in 3 rows on tablet/desktop.** `frontend/src/shared/ui/ProjectWeather/ProjectWeather.tsx` switched from `sm:grid-cols-8` (8 cols × 2 rows) to `sm:grid-cols-6` (6 cols × 3 rows: 6 + 6 + 4). Mobile (default `grid-cols-4`) unchanged.
- **Map height matches the weather block.** `ProjectDetailPage.tsx` parent grid gained `items-stretch`, the map's fixed `h-[32rem]` was replaced with `h-full min-h-[20rem]` (only when weather is also visible), and `ProjectMap.tsx`'s detail-variant `heightClass` switched from `h-80` to `h-full` so the map fills its grid cell. When weather is hidden, the map falls back to the original fixed 32 rem.

### Fixed (BOQ — custom columns on resource rows)

- **Custom text/number columns now inherit the parent position's value on resource sub-rows.** `columnDefs.ts:getCustomColumnDefs` builds an `O(1)` `positionsById` map of all positions; the column's `valueGetter` walks `_parentPositionId` for resource rows and reads `parent.metadata.custom_fields[name]`. Resource cells render the inherited value read-only with italic + muted styling so the user can tell it's not editable in place — to change a custom value, edit the position row.
- **Derived `resource_sum` / `percentage_of_unit_rate` columns now render per-resource values on resource sub-rows.** Previously the guard at the top of the value-getter returned empty for any non-position row, so derived columns showed blank cells under every position. Now: a resource row whose `_resourceType` matches the column's `resource_role` renders its own `qty × rate` contribution (`resource_sum`) or its share of the parent's total resource sum (`percentage_of_unit_rate`). Mismatched roles still render blank so each contribution is visually attributed to the right resource.
- **`editable` predicate now blocks resource + add-resource rows.** Previously the AG Grid editor would open on a resource row and the user could type into a non-existent `metadata.custom_fields`, with the value setter silently returning `false`. Resource cells are now correctly read-only.

### Fixed (BIM viewer — issue #113 silent geometry-load failures)

- **3D viewer now surfaces geometry-load failures.** `BIMViewer.tsx:910` previously caught DAE/GLB load errors with a `console.warn` only, leaving the user with an empty canvas and no signal of what went wrong. The catch handler now sets a `geometryError` state which renders a top-anchored amber banner with the failure message + a **Retry** button. The retry calls a new `ElementManager.resetGeometryLoadFlag()` and bumps a `geometryRetryNonce` so the load effect re-runs the fetch without forcing a full page reload. Covers 401 from a stale token, 404 from a redeploy that ate the file, malformed GLB/DAE bytes, and OOM during BVH build.

## [2.9.20] — 2026-05-07

### Changed (i18n perf — per-locale lazy chunks)

- **Split `i18n-fallbacks.ts` into 26 per-locale chunks.** The monolithic 5.5 MB / 90,119-line `fallbackResources` constant was replaced with one auto-generated file per locale under `frontend/src/app/locales/{en,de,fr,…}.ts`. The runtime now bundles English synchronously (~45 KB gzip) as i18next's `fallbackLng` and lazy-loads the user's resolved locale via `import(`./locales/${code}.ts`)`. Vite emits one stable `i18n-{code}.js` chunk per language (44–58 KB gzip each).
- **~96% boot-bundle reduction for English users**, ~92% for non-English users after the first locale fetch resolves. Old build shipped a single 4.94 MB / 1.28 MB-gzip `i18n-data` chunk to every page load regardless of language; the new build ships only the active locale.
- **`i18n-fallbacks.ts` retained as a test-only aggregator.** Existing tests (notably `boqResourceTypes.test.ts`) still walk every locale, but the file is no longer reachable from the runtime entrypoint, so tree-shaking removes it from the production bundle.
- New `loadLocaleResource(code)` helper exported from `app/i18n.ts` — idempotent, logs and falls back to English if the chunk fails to load.

## [2.9.19] — 2026-05-07

### Added (Tendering — readable bid comparison)

- **Sticky position column on the bid comparison matrix.** The first column (position description / WBS code / item name) now `position: sticky; left: 0` with a subtle right shadow, so it stays visible when 4+ vendors push the table beyond viewport width on 1366×768 / 1280×800 screens. Header row also `top: 0` sticky; the top-left corner cell sits at `z-20` to layer correctly. Row-hover tint extends across the sticky cell.
- **Collapse low-variance rows.** New checkbox + threshold select (5/10/15/20/25%) above the table hides rows where every vendor's `unit_rate` is within the threshold of the mean — reduces visual noise on long bid packages where most positions agree. Counts hidden rows in a small "{n} hidden" indicator. Rows with fewer than 2 valid bids are always kept (no spread to compare).

### Added (Documents — photo MIME hardening)

- **HEIC / HEIF / TIFF magic-byte detection.** `app/core/file_signature.detect()` now recognises:
  - HEIC: ISO-BMFF `ftyp` + brand `heic / heix / hevc / heim / hevx / heis / hevm`.
  - HEIF: ISO-BMFF `ftyp` + brand `mif1 / msf1 / avif / avis`.
  - TIFF: little-endian `b"II*\x00"` and big-endian `b"MM\x00*"`.
  Photos uploaded with these formats now pass the magic-byte check; previously they relied entirely on the client-asserted Content-Type and a renamed `.txt` could spoof an HEIC upload.
- **Photo upload now cross-checks magic bytes.** After buffering the upload, `documents/service.py` calls `detect()` and rejects with HTTP 422 `{"detail": "uploaded file content does not match an image format"}` when the detected type isn't in `ALLOWED_PHOTO_TYPES = {jpeg, png, gif, webp, heic, heif, tiff}`. SVG bytes detect as `xml` and are rejected even with a spoofed `Content-Type: image/jpeg`.
- **SVG removed from image MIME map.** `projects/file_manager_service._MIME_BY_EXT` no longer maps `.svg` to `image/svg+xml`. SVG uploads via the file manager are still allowed but classify as a generic file — `FileGrid` no longer renders them inline via `<img>`. Closes the inline-`<script>` XSS surface where a malicious SVG could execute in the app's same-origin auth-cookie context.
- **Photo file-serve now `Content-Disposition: attachment`.** `/api/v1/documents/photos/{id}/file/` switched to explicit attachment with sanitized filename. Even if a non-image somehow lands on disk, browsers won't inline-render it. The `/thumb/` endpoint stays inline since the thumbnail JPEG/PNG is server-generated and trusted.

## [2.9.18] — 2026-05-07

### Added (Procurement — 3-way invoice match)

- **`create_invoice_from_po` now refuses to bill for items that haven't been received.** Previously copied PO line items verbatim into a new Invoice with no link to confirmed Goods Receipts — overbilling unblocked. New helper `procurement/service._validate_3way_match` sums `quantity_received` over confirmed-status GRs per `po_item_id`; for each proposed Invoice line it compares against `received_qty` and reports per-line violations. The route raises `HTTP 422` with structured `{message, errors: [...]}` when invoice qty exceeds received qty.
- **`force=true` query param overrides the match** for service-only POs (no goods to physically receive). When set, the invoice is persisted with `metadata_["force_3way_match"] = True` and a structured `logger.warning` is emitted with `{po_id, user_id, violations}` for audit aggregation.
- **`no_confirmed_grs` sentinel reason** when a PO has zero confirmed GRs and the invoice has any positive qty — lets the FE render the precise "service-only PO? pass force=true" message.
- All 19 existing procurement tests still pass; synthetic 6-case helper test added (over-qty / clean-match / no-GR / free-text skip / no-items / zero-qty).

### Added (Risk — owner picker + assignment notification)

- **`Risk.owner_user_id`** — proper FK to `oe_users_user` (nullable, indexed, `ON DELETE SET NULL`). Replaces the free-text `owner_name` for new rows; legacy data still renders via the fallback so nothing was lost. Migration `v2918_risk_owner_user_id.py` is inspector-guarded and reversible (uses `batch_alter_table` for SQLite compatibility).
- **`risk.assigned` event fires on new or changed owner.** `risk/service.py` publishes `{risk_id, project_id, code, title, owner_user_id, assigned_by}` after create/update. New subscriber `_on_risk_assigned` in `notifications/events.py` produces an in-app notification "You were assigned risk {{code}}: {{title}}". Mirrors the v2.9.16 pattern for `rfi.assigned`.
- **Frontend picker.** `RiskRegisterPage.tsx` swapped the free-text `<input>` for the existing `UserSearchInput` (avatar + name + role + email search). On selection, `owner_user_id` is sent as UUID and the resolved display name is mirrored into `owner_name` so the list-row column keeps working uniformly across picker-sourced and legacy rows.

### Added (Schedule — Gantt drag-to-resize)

- **Edge handles on every standard task bar.** Two transparent 7 px `ew-resize` zones (left + right) on each Gantt bar; left handle moves `start_date`, right handle moves `end_date`. Snap-to-day via the existing `pxToDate`; clamped to keep `end_date >= start_date + 1 day`. Group and milestone bars are unaffected. Esc cancels the in-flight resize and reverts the preview.
- **`onActivityResize?: (id, newStart, newEnd) => void` prop** added to `GanttChart`. Existing `onActivityMove` (drag-to-translate) untouched; resize is purely additive.
- **`SchedulePage` wires it through React Query.** New `resizeActivity` mutation calls `scheduleApi.updateActivity(id, {start_date, end_date})`, optimistically updates the cached `['gantt', schedule.id]` payload, snapshots and reverts on error, and invalidates on settled. Confirmed against `schedule/schemas.py:46-47` that the Activity schema uses `start_date`/`end_date` (not `planned_*` — those belong to `WorkOrder`).

## [2.9.17] — 2026-05-07

### Added (Procurement → Finance commitment flow)

- **`procurement.po.issued` now flips `ProjectBudget.committed`.** Previously the event was published but no subscriber existed — committed amounts stayed permanently 0 in the dashboard even when POs totalled millions. New finance subscriber in `backend/app/modules/finance/events.py:_on_po_issued` opens an isolated session, picks the budget row by `(project_id, wbs_id)` against the PO's first line item (falls back to the oldest budget by `created_at`), and increments `ProjectBudget.committed` by `amount_total`. Wrapped in try/except so a write failure can't propagate back to the publisher.
- **`procurement.gr.confirmed` now flips committed → actual.** Same row-selection strategy: decrements `committed` (clamped at zero) and increments `actual` by the GR value. The GR publisher in `procurement/service.py` now actually computes the receipt amount as `Σ(quantity_received × matched po_item.unit_rate)` instead of emitting only the IDs.
- **Event payload enrichments.** `procurement.po.issued` now carries `currency_code` (was missing — finance subscribers need it). `procurement.gr.confirmed` now carries `amount` and `currency_code`.

### Added (Change Order → Budget delta line)

- **Approved change orders now create or update a `ProjectBudget` row.** Previously the approved `cost_impact` was written to the single string field `project.budget_estimate` and never reached `ProjectBudget` — so EVM BAC didn't include approved COs. New helper `changeorders/service._write_budget_delta_row` keys off `metadata_->>'change_order_id' == co.id` (with `wbs_id=str(order_id)` and `category="Change Order {co.code}"` so the unique-on-(project, wbs, category) constraint isn't violated by regular budgets), `original_budget = 0`, `revised_budget = delta`, currency from `co.currency` → project default → `"EUR"`. Idempotent: re-approve updates the existing row instead of inserting a duplicate. Wrapped in try/except — a budget-write failure logs a warning but doesn't roll back the CO approval.
- **`approve_order` event payload extended** with `budget_row_id` + `budget_row_action` (`"created" | "updated" | "skipped"`) so downstream auditing can confirm the writeback.

### Fixed

- **PO numbering race fixed with IntegrityError retry.** `procurement/service.py:create_po` previously picked `MAX(po_number) LIKE 'PO-%'` and inserted; concurrent creates collided with HTTP 500. Now mirrors the pattern from `changeorders/service.py:88-126`: 5 attempts, refetch MAX + retry on `IntegrityError`. Auto-generated numbers loop; explicitly user-supplied numbers bubble up as 409 instead of looping. Backed by a new `(project_id, po_number)` unique constraint (`uq_procurement_po_project_number`); migration `v2917_po_number_unique.py` is inspector-guarded and de-duplicates pre-existing collisions before applying.
- **Tasks importer foreign-language column headers.** `tasks/router.py:_TASK_COLUMN_MAP` previously mapped only EN/DE headers, so an Excel import with Russian "Название", Spanish "Título", Japanese "タイトル" etc. silently dropped those columns. Added 81 entries across 9 locales (ru / fr / es / it / ja / zh / pt / nl / ko) for 8 target fields (title, description, status, priority, assigned_to, due_date, task_type, estimated_hours). Map grew 19 → 100. Lookup is case-insensitive; CJK headers match verbatim.

## [2.9.16] — 2026-05-06

### Fixed (Finance correctness)

- **Decimal precision on dashboard SUMs.** `finance/repository.py` cast money columns through `Float` before SUMming, silently losing precision on totals over 2^53 cents. All five aggregations (invoice ×2, payment, budget ×4) now `cast(..., Numeric)` and accumulate as `Decimal`.
- **Budget search crash.** `FinancePage.tsx:834` read `b.wbs_code.toLowerCase()` but the API returns `wbs_id`; `b.wbs_code` was always `undefined` and threw on the first character typed. Now reads `(b.wbs_id ?? '').toLowerCase()`. Also widened `BudgetLine` type with `currency_code`.
- **EVM forecast formula mismatch.** Service computes `EAC = AC + (BAC − EV) / CPI`; the modal hint claimed `EAC = BAC / CPI`. Hint corrected to match the service.
- **TCPI sign flip on over-budget projects.** The denominator `(BAC − AC)` could go negative; TCPI flipped sign and read as a "good" number. Now clamped — when remaining budget ≤ 0, TCPI returns 0 (interpretable as "infeasible").
- **EVM snapshot wrote zeros.** `Create Snapshot` POSTed only `{project_id, snapshot_date}`; the schema defaulted BAC/PV/EV/AC to `"0"`, so every snapshot persisted zeros. The handler now derives BAC/PV/EV/AC from the actual budget + payments at `snapshot_date` whenever a payload value is exactly `Decimal("0")` and writes those derived numbers to the row.
- **Invoice status filter missing `cancelled`.** Added the option so cancelled invoices are filterable from the dropdown.

### Added (Finance currency_code)

- **`ProjectBudget.currency_code`.** New `String(3)` column (default `"EUR"`, NOT NULL) on the budget row; surfaced through `BudgetCreate / BudgetUpdate / BudgetResponse` and respected by `service.create_budget`. Frontend `BudgetLine` type extended; `BudgetsTab` now renders the row's actual currency instead of always falling back to EUR. Alembic migration `v2916_project_budget_currency.py` is inspector-guarded and reversible.

### Changed

- **`FinanceSummaryCards` switched to `/v1/finance/dashboard/`.** The cards previously fired three list queries (invoices/payments/budgets) and reduced in JS, which both burned RTT and re-introduced the precision-loss path. Now a single `useQuery(['finance','dashboard',projectId])` reads `total_budget_original / total_payable / total_receivable / total_actual` from the SQL aggregator. Drops ~150 lines of FE coercion.
- **`BudgetsTab` mobile card view.** The 8-column budget table forced horizontal scroll on phones. Tablet/phone now shows a stack of cards (wbs_id + category + original + committed + actual + forecast + colorized variance + currency); table reappears at `md`.

### Added (Communication notifications)

- **9 new notification subscribers wired in `notifications/events.py`** for events that publishers were already firing but no handler consumed:
  - `rfi.assigned` → notifies the assignee.
  - `rfi.responded` → notifies the original requester.
  - `submittal.submitted` → notifies the reviewer + project owner (deduplicated).
  - `submittal.approved` → notifies the submitter.
  - `submittal.rejected` → notifies the submitter with rejection reason.
  - `submittal.revise_resubmit` → notifies the submitter.
  - `transmittal.issued` → notifies each recipient.
  - `transmittal.acknowledged` → notifies the original sender.
  - `transmittal.responded` → notifies the original sender.
- **Transmittal events are now actually published.** `transmittals/service.py` had zero `_safe_publish` calls; `issue_transmittal / acknowledge_receipt / submit_response` now emit the three transmittal events that the new subscribers consume.
- **`submittal.rejected` and `submittal.revise_resubmit` events.** The producer previously emitted a single `submittal.reviewed` with the decision in the payload; the two specific event names are now also published so subscribers can fan out cleanly.

### Added (i18n — `files.*` namespace coverage)

- **22 locales backfilled in `frontend/src/app/i18n-fallbacks.ts`** so the `/files` UI no longer shows raw keys (`files.col.modified`, `files.bulk.delete`, etc.) on non-EN/DE/RU sessions:
  - `ar` filled 65 missing keys (had 72/137).
  - `fr / es / pt / zh / hi / ja` each filled 80 missing keys (had 57/137).
  - `tr / it / nl / pl / cs / ko / sv / no / da / fi / bg / hr / id / ro / th / vi` each gained the full 137-key block (had 0).
  - **Total: ~2 737 strings across 22 locales.** All 26 supported locales now have full `files.*` coverage.
- Tone follows the authoritative German + Russian blocks; brand and format names (BIM, IFC, DWG, PDF, GAEB, OpenConstructionERP, `.ocep`) preserved verbatim.

## [2.9.15] — 2026-05-06

### Security (cross-category IDOR sweep — ~73 endpoints)

Five-category deep audit (Planning, Communication, Procurement, Finance, Documents) found cross-tenant data-leak holes in every category. This release closes them all in a single security-only batch. Every patched endpoint now requires the right `RequirePermission(...)` and calls `verify_project_access(project_id, user_id, session)` before reading or mutating.

- **Documents — photo serve was completely public.** `GET /api/v1/documents/photos/{id}/file/` and `/thumb/` had zero authentication; anyone could `curl -O` photo bytes by guessing UUIDs. Construction-site photos contain incidents, defects, badges, and contracts pinned to walls — P0 privacy + GDPR hit. Now gated by `documents.read` + project ownership.
- **Documents — sheets-by-id IDOR.** `GET /sheets/{id}` and `/sheets/{id}/versions/` skipped the ownership gate. Patched.
- **Documents — `documents_similar` defaulted to `cross_project=True`.** Vector similarity could return hits from projects the caller didn't own. Default flipped to `False`; clients must opt-in explicitly with `?cross_project=true`.
- **CDE module had zero project-access checks across all 11 endpoints** (containers / revisions / state transitions / history / transmittals). Any authenticated user could read or mutate any tenant's CDE state with a leaked UUID. Now fully gated.
- **Field reports — 7 endpoints unscoped.** `get_report`, `update_report`, `delete_report`, `submit_report`, `link_documents`, `get_linked_documents`, `export/pdf` all skipped `verify_project_access`. Patched.
- **Meetings — 5 read endpoints + the worst single hole.** `export_meeting_pdf` had **zero auth** (no permission, no project access). Plus `list_meetings`, `meeting_stats`, `open_action_items`, `get_meeting` were missing `RequirePermission("meetings.read")`. All 5 patched.
- **Transmittals — entire module had no RBAC.** Eight endpoints (list / create / get / patch / delete / issue / acknowledge / respond) gained `RequirePermission` plus `verify_project_access` on the three lifecycle paths. Acknowledgement is contract-grade non-repudiation; this closes the integrity hole.
- **Submittals — lifecycle and attachments unscoped.** `submit/review/approve` and the 3 attachment endpoints (list/add/delete) all gained `verify_project_access` via `service.get_submittal()`.
- **RFI — `respond_to_rfi` and `create_variation_from_rfi` unscoped.** Both now load the RFI and verify project access.
- **ERP chat session creation accepted arbitrary `project_id`.** A user could attach a chat session to any tenant's project; subsequent vector retrieval (`cross_project=True`) then leaked across tenants via embeddings. `create_session` now verifies the supplied project_id when present.
- **Procurement was completely project-unscoped.** `list_purchase_orders` made `project_id` optional, so anyone with `procurement.read` could read every tenant's POs by omitting the filter. The parameter is now required, and 9 endpoints (list / stats / list-GR / create-GR / confirm-GR / get-PO / update-PO / create-invoice-from-PO / issue-PO) now load the resource and verify project ownership.
- **Change-orders — sub-resources and lifecycle unscoped.** `add_item / update_item / delete_item / submit_order / approve_order / reject_order` all gained ownership verification. (Wave 5 in v2.9.14 only patched list/get/update/delete/summary.)
- **Cost-model 5D dashboard had zero ownership checks.** All 14 endpoints (`dashboard / s-curve / cash-flow / budget / budget-lines / generate-budget / generate-cash-flow / what-if / monte-carlo / evm / snapshots`) were gated only by global `costmodel.read|write` — any user with the perm could target any project's BAC/EV/AC. Patched. UPDATE/DELETE on `budget-lines/{id}` and `snapshots/{id}` now load the row and verify project ownership.
- **Schedule activity / baseline / progress-update endpoints unscoped.** 14 endpoints across `create/update/delete activity`, `link_boq_position`, `update_activity_progress`, `create/update_work_order`, `create_relationship`, `list_relationships`, baselines (CRUD), progress updates (CRUD), and `import_xer / import_msp_xml` now derive `project_id` from the parent schedule and gate via `_verify_schedule_owner` / `verify_project_access`.
- **Tasks `{task_id}` IDOR.** `get_task / update_task / delete_task / complete_task / update_task_bim_links` did not call `verify_project_access`, so a leaked task UUID let cross-tenant access through. Each handler now loads via `service.get_task()` and verifies on `task.project_id`.
- **EAC `_resolve_tenant_id` silently swallowed errors.** It caught every failure and fell back to `user.id`, effectively short-circuiting tenant scoping. The helper now raises HTTP 403 on any resolution failure. `create_rule / list_rules / create_ruleset / list_rulesets` now also `verify_project_access` when a `project_id` is supplied.

### Fixed

- **Change-order `_apply_to_boq` no longer picks an arbitrary BOQ.** `approve_order` now accepts an optional `boq_id` query param threaded through to `service.approve_order(..., boq_id=...)` → `_apply_to_boq(..., boq_id=...)`. With explicit `boq_id`, the function looks up that specific BOQ and refuses to write if not found, locked, or owned by a different project (returns `{"applied": False, "reason": "boq_not_found" | "boq_project_mismatch" | "boq_locked"}`). Without `boq_id`, the existing first-by-`created_at` fallback is preserved but logs a warning. Multi-BOQ projects (the common case) can now target the correct LV.

## [2.9.14] — 2026-05-06

### Security (P0 IDOR fixes — Wave 5 audit)

- **Risk register cross-tenant leak.** `GET /api/v1/risk/`, `/risk/summary/`, `/risk/matrix/` accepted any `project_id` from any authenticated user without checking ownership. All three handlers now require `RequirePermission("risk.read")` and call `verify_project_access(project_id, user_id, session)` before reading.
- **Change-order cross-tenant leak.** `GET /api/v1/changeorders/summary/` and `GET /api/v1/changeorders/?project_id=…` were missing the same ownership check. Both endpoints now require `RequirePermission("changeorders.read")` and verify project access; the project-less list path that scopes to the caller's owned projects is unchanged.
- **Contacts export leaked every tenant's data.** `GET /api/v1/contacts/export/` ran a plain `select(Contact).where(is_active)` with no owner filter, so anyone with `contacts.read` could download the full database. Now mirrors the `tenant_id` / `created_by` scope used by `list_contacts` / `search_contacts` / `get_stats`; admins still see every row.

### Changed

- **Settings page redesigned.** Card-grid layout with sticky vertical sidebar nav on desktop (horizontal scrollable pill tabs on mobile), profile rendered as a wide hero card with a real label-above pattern, "Danger Zone" red-tinted card separates Sign Out + destructive actions from settings, change-password form has proper labels + inline mismatch error, BIM/CAD tab body filled with link-cards, URL-synced tab state via `?tab=…` for deep-linking. Every setting from the previous layout is preserved.

## [2.9.13] — 2026-05-06

### Added
- DDC converter version surfaced on every converter-related page (`/bim` banner + `/quantities` cards): the actual installed git-blob SHA (first 7 chars) is shown in place of the static manifest version string. When the version-check endpoint reports the installed binary is older than upstream `cad2data-Revit-IFC-DWG-DGN/main`, the row swaps in a sky-blue "Update available" badge and a one-click **Update** button.
- Per-row Update button on `/quantities` ConverterCard wired through to a force-reinstall path. Kept the existing Install / Uninstall affordances so the card now exposes Install for missing converters, Uninstall for healthy ones, and Update + Uninstall for outdated ones.
- `installBIMConverter(id, {force: true})` API helper and a `?force=true` query param on `POST /v1/takeoff/converters/{id}/install/` so the "already installed → short-circuit" branch is bypassed when the client explicitly asks for a re-download.

### Fixed
- Clicking **Update** on an outdated converter previously hit the early-return ("already installed") path and did nothing visible. The handler now reinstalls under `force=true`, then clears `app.state._converter_version_cache` so the 6-h server cache reflects the new SHA immediately. Frontend invalidates `bim-converters`, `takeoff/converters`, and `bim-converters-version-check` query keys on success — the badge disappears as soon as the install completes instead of lingering for hours.

### Changed
- `openconstructionerp.com` hero "OCERP" mark restyled to match the rest of the site CTAs. The 3D-glass pill with breathing animation, gloss layers, click-burst rings, and `rotateX/rotateY` hover was replaced with a `.btn-primary`-shaped pill (rounded, accent background, simple lift) plus a trailing chevron so it reads as **OCERP →**. Click still navigates to `#install`.

## [2.9.12] — 2026-05-06

### Fixed
- All upload size caps removed (boq/contacts/fieldreports/finance/costs/tasks/punchlist/meetings/takeoff/bim_hub) — uploads no longer rejected at 10/25/50/100/200 MB.
- DDC logo on dashboard rendered correctly (.webp now in static-extension whitelist; was served as truncated text/html).
- Validation engine no longer flags BOQ section headers as missing unit/quantity/unit_rate (16 false errors → 0 on demo BOQ).
- BOQ editor 404s eliminated: `/v1/boq/boqs/{id}/activity/` and `/v1/costs/vector/status/` (trailing-slash mismatches).
- Sidebar version line `v… · AGPL-3.0` moved below GitHub/Telegram pills (last row of menu).

### Added
- "Developed by" label above the DataDrivenConstruction logo on the dashboard hero (translated for en/de/fr/es/pt/ru/zh/ar/hi/ja).
- File-manager UI translations for ar/fr/es/pt/zh/hi/ja (~55 keys each, no more English leakage on /files).

## [2.9.11] — 2026-05-06

### Fixed
- "Navigation Sidebar" tour bubble no longer ambushes returning users on every page (BOQ, Dashboard, Projects, Validation…). The auto-start gate now also short-circuits when `oe_onboarding_completed === 'true'`, which the dashboard stamps as soon as it confirms the workspace has projects. Fresh installs still see the tour; demo-data and any new browser on a populated workspace skip it.

## [2.9.10] — 2026-05-06

### Fixed
- `/finance` printed nonsense totals like `850.000.320.000.018.000.000.000,00 €` for projects whose budget lines summed to ~8.25M. The reduces over `b.original_budget` / `b.actual` / `b.revised_budget` / `b.committed` / `b.forecast` / `b.variance` and `inv.amount` / `p.amount` were string-concatenating because the API serialised DECIMAL columns as strings ("850000.00"). Coerced every accumulator with `Number(x ?? 0)` so the dashboard chips, Budgets total row, Invoices totals, and Payments totals all aggregate numerically.

## [2.9.9] — 2026-05-06

### Fixed
- Onboarding wizard no longer hijacks the dashboard for users whose workspace already has projects. The redirect now waits for `/v1/projects/` to resolve and only fires when the workspace is genuinely empty; otherwise it stamps `oe_onboarding_completed` so the next visit (and every other browser the user opens) lands on the dashboard, not the 6-step welcome flow.
- `/files` no longer leaks the server's absolute filesystem layout. The PathBar that surfaced `C:\Users\…\.openestimator\uploads\…`, the per-root chips (DB / Uploads / Photos / BIM / DWG), and the amber location notes have been removed; users who actually need on-disk paths can find them under /settings → System.
- Cost Database header showed "France — 0 items" while the France tab badge advertised 55,121 because the in-flight search returned `total=0` first. Header now falls back to the region's catalog count from `/v1/costs/regions/stats/` while the search is still resolving.

## [2.9.8] — 2026-05-06

### Fixed
- Demo documents no longer 404 in PDF Takeoff. Seeded `Document` rows reference paths that don't exist on disk (we don't ship multi-MB PDFs in the wheel), so `/api/v1/documents/{id}/download/` returned 404 and the cross-module deeplink landed on "Failed to fetch PDF". The download endpoint now materializes a one-page placeholder PDF on first request when `metadata.is_demo == True`. Real uploads are unaffected.
- Sidebar footer is now unified neutral gray with two equal-width pills. GitHub pill (icon + "GitHub" label) on the left, Community pill (Telegram glyph + label) on the right — neither dominates. Meta strip above shows `v{version} · AGPL-3.0` in matching tertiary gray.

## [2.9.7] — 2026-05-06

### Fixed
- Dashboard map now shows ALL projects, not just one. Region fallback only had country-level keys (`uk`, `usa`, `germany`); demo + onboarding data uses higher-level groupings (`Europe`, `DACH`, `Middle East`, `United States`, `Asia-Pacific`, `LATAM`, …) which silently dropped off the map. Fallback table now covers both granularities.
- Sidebar footer text was truncating at narrow widths (`AGPL-3.0` and `Community` got chopped). Footer is now two rows — meta strip on top (`GitHub · v{version} · AGPL-3.0`), full-width Telegram Community pill below — so nothing is cut off.

## [2.9.6] — 2026-05-06

### Added
- Sidebar footer Telegram community link — single-row layout: left half = `v{version} · AGPL-3.0` with GitHub icon, right half = brand-blue Telegram pill with Community label. Links to https://t.me/datadrivenconstruction.

### Fixed
- Dashboard map (`/`) blank/grey — Content-Security-Policy was blocking MapLibre's `blob:` worker and the openfreemap tile + nominatim geocode endpoints. Added `worker-src 'self' blob:`, `script-src … blob:`, and `connect-src https://tiles.openfreemap.org https://*.openfreemap.org https://nominatim.openstreetmap.org`.
- Dashboard project cards no longer leave half-empty rows at the lg breakpoint. Visible count is now capped to `floor((cards+1)/4)*4 - 1` so `(visible + CTA)` always fills the 4-column grid: 5 projects → 3 + CTA, 8 → 7 + CTA, 11+ → 11 + CTA. Fewer than 3 still show all + CTA (capping further would just hide everything).

## [2.9.5] — 2026-05-06

### Fixed
- `/files` document deeplink — clicking a PDF and pressing "Open in PDF Takeoff" now actually opens the file. Previous flow routed to `/documents?id=` which since v2.9.x is a `<Navigate to="/files">` redirect that drops query params, so the destination module never received the file id. New flow goes to `/takeoff?doc={id}&source=document&tab=measurements` and TakeoffPage fetches metadata from `/v1/documents/{id}` and points the viewer at `/api/v1/documents/{id}/download/`. Verified end-to-end with a real PDF rendered in the takeoff viewer.

## [2.9.4] — 2026-05-06

### Removed
- Final user-facing size-cap copy across i18n + UI — `dashboard.upload_desc` "max 100 MB" tail, `MAX_UPLOAD_BYTES` guard in QuickUploadCard, `files.upload_hint` (EN/DE/RU) "max 100 MB", `costs.import_accepted` "max 10 MB" suffix (EN/DE/FR/ES/NL/CS/SE/RO), `fieldreports.file_types` "max 10 MB" suffix (all langs), `bim.upload_size_hint` and `bim.landing_size_hint` "Max 500 MB" suffix (all langs), `CadDataExplorerPage` "Max 100 MB" upload hint. Bundle now ships zero "max NNN MB" matches.

## [2.9.3] — 2026-05-06

### Added
- Dashboard compact project cards on `/` — 11 most-recent + a "View all projects" CTA card (12 total, always fills full rows at 1/2/3/4 columns).
- Dashboard project-locations map — single MapLibre canvas with one marker per project, lazy-loaded, region-fallback for projects without an address. Lives below Portfolio Overview.
- BOQ Custom Columns: `derived` field on column definitions — GAEB Lohn-EP / Material-EP / Geräte-EP / Sonstiges-EP and ÖNORM Lohn-Anteil % auto-compute from `position.metadata.resources[]` instead of being free-form numeric inputs.
- `/files` `Open in {Module}` deep-links — preview pane primary CTA, hover overlay on grid tiles, and inline cell on the list view. Each file links to its native tool with file context: PDF → `/takeoff?doc={id}`, IFC/RVT/DGN → `/projects/{p}/bim/{modelId}`, DWG/DXF → `/dwg-takeoff?drawingId={id}`, photos → `/photos?photo={id}`, secondary file-manager preview-select via `?file={id}`.
- `/files` moved to Sidebar → Overview alongside Dashboard / Projects (was buried under Documentation).

### Removed
- All user-facing upload size caps — `_CAD_MAX_SIZE` (500 MB BIM), `MAX_FILE_SIZE` (100 MB documents / 50 MB AI / 50 MB GAEB), `MAX_PHOTO_SIZE` (50 MB), `_MAX_UPLOAD_BYTES` (50 MB DWG / 200 MB dashboards), `MAX_BACKUP_SIZE` (100 MB), `15 MB` BOQ multimodal cap, `10 MB` costs-import cap. Frontend "Max XX MB" hint strings stripped across DwgTakeoffPage, TakeoffPage, DocumentsPage, PhotoGalleryPage, UploadDialog, ImportDatabasePage, FieldReportsPage, ContactsPage, BIMPage, plus matching i18n fallbacks. The XLSX zip-bomb decompressed-size guard stays — that's a memory-safety check, not a user cap. (#110 follow-up)

### Fixed
- File Manager `/files` filter view — backend `file_tree` no longer prefixes node ids with `category:`; frontend strips legacy prefix defensively so old bookmarks (`?kind=category%3Abim_model`) still resolve.
- BOQ `enrich-resources` 500 — `cost_repo.search` returns a 3-tuple but four call sites unpacked into a 2-tuple; fixed in `boq/service.py`, `boq/router.py`, `ai/router.py` (×2). Triggered by Update Rates action.
- `/api/v1/requirements/template.xlsx` 400 — route ordering: literal `template.xlsx` route now precedes parametric `/{set_id}` so UUID validation no longer rejects it.
- Frontend bundle freshness — `_frontend_dist` rebuilt with login fixes (LinkedIn link, external "Learn more" anchor) that were authored against source but missed the previous wheel build.
- BOQ Custom Columns data-jump — `valueSetter` now spreads `metadata` immutably; custom-column detection uses `colId.startsWith('custom_')` instead of fragile `field` parsing.
- BOQ Custom Columns horizontal overflow — grid height capped at viewport, custom columns get explicit min/max widths, wrapper has `min-w-0` so AG Grid's bottom scrollbar stays reachable.
- Backend `add_custom_column` — replaced untyped `dict` body with `CustomColumnCreate` Pydantic schema (`extra='forbid'`) so typo'd fields fail with 422 instead of being silently dropped.
- BOQ shortcuts Ctrl+E / Ctrl+I / Ctrl+L / Ctrl+/ — moved above the `isEditing` guard so they fire during cell editing (like Ctrl+S in spreadsheets), capture-phase listener so AG Grid no longer swallows them, `e.code`-based fallback for non-US keyboard layouts.
- Sidebar `g d` chord → dashboard — chord sets a one-shot `oe_skip_onboarding_redirect` sessionStorage flag so the dashboard view loads even on fresh installs (the auto-onboarding redirect still fires for normal first-launch flow).
- BOQ `enrich-resources` and `enrich-co2` 500 — the loops iterate `boq_data.positions` (Pydantic `PositionResponse`) but were reading `pos.metadata_` (the SQLAlchemy column name); Pydantic strips the trailing underscore, so attribute lookup raised. Now reads via `getattr(pos, "metadata", None) or getattr(pos, "metadata_", None)` to handle both ORM rows and serialised responses.
- `/api/v1/dashboards/projects/{id}/snapshots` 500 — `oe_dashboards_snapshot` was never created on fresh installs because `app.modules.dashboards.models` (and `architecture_map`, `compliance`, `eac`, `jobs`) were missing from the `create_all` import list in `app/main.py`. All five module models now register before the bootstrap `Base.metadata.create_all()` call.

## [2.9.2] — 2026-05-06

### Fixed
- BOQ delete race — successful single-position DELETE no longer invalidates the BOQ cache and races with concurrently-pending optimistic deletes (rapid sequential / batch delete). Sidecar queries (rollups, activity feed) still refresh; the BOQ cache rebuilds only on actual error.
- BOQ Delete / Backspace hotkey now removes the selected positions through the existing tracked-delete pipeline (5-second undo toast).
- BOQ toolbar collapses back to a single row — `Validate` / `Update Rates` / `AI Chat` removed as inline buttons (already present in the `Quality & AI` dropdown which now also surfaces `Update Rates`); toolbar uses `flex-nowrap` with horizontal scroll fallback so the right-anchored Grand Total never wraps to a second line.
- Login page polish — module-honeycomb left-aligned (was centered), stats row updated to "30 regions" (was 11) and gained a "4 CAD formats" stat. Matching i18n EN fallbacks updated.

## [2.9.1] — 2026-05-05

### Added
- BOQ display-currency selector — view-only conversion of all monetary aggregates (position totals, section subtotals, footer rows, Grand Total) via project FX rates. `Total` column header gains the chosen currency code. (#88)
- BOQ toolbar merged to a single row — mini-summary, currency selector, and Grand Total moved into the existing sticky toolbar.
- Display-currency choice persists per-BOQ in localStorage; auto-cleared if the rate is later removed.
- File Manager — per-project file workspace with bundle export/import, storage location override, and a tree+grid browser. (#109)
- `v294_project_storage_override` migration adds the per-project storage override column.
- Project Intelligence module promoted to `core` (always-on per `feedback_pi_always_on`).

### Fixed
- BOQ display currency was wiped on every reload because the sanity-check effect ran before the project query finished loading.
- DWG Takeoff upload form — the upload button no longer no-ops; corrected event wiring and progress state. (#110)
- Login page polish — cleaner layout, demo banner copy, accessibility tweaks.
- Issue #53 (BIM viewer geometry) — re-confirmed as fallback-by-design at v2.9.1; closing with DDC IFC Converter install instructions.

### Changed
- Header / Sidebar / Update checker iteration — small UX polish around the layout shell.

## [2.9.0] — 2026-05-05

### Performance
- `/costs` page load 120× faster — composite `(region, is_active, code)` index drops the per-region keyset scan from 6 s to 1 ms on 55K-row catalogues; COUNT(*) from 3 s to 6 ms.
- `/v1/costs/?lite=1` slim-payload mode strips `components` (~31 KB/row) and `metadata.variants` (~6 KB/row), shrinking a 10-row page from 235 KB to 18 KB. Frontend list now lazy-fetches the full item via `/v1/costs/{id}` only when a row is expanded.

### Added
- Header `ThemeToggle` button — single icon next to avatar that cycles light → dark → system.
- Header `HelpMenu` (`?` icon) consolidates 6 buttons (Docs, GitHub, Send feedback, Report issue, Report a bug, Email) behind one popover.
- Sidebar pinned section, search-as-jumper bar, two-key keyboard shortcuts (G then D/P/B/C/M/A/,) with inline kbd hints, hover-arrow affordance, stagger animation.
- Linux CAD converters auto-discovered at `/usr/bin/{Format}Exporter` (RVT/IFC/DWG/DGN); install endpoint detects `/etc/apt/sources.list.d/ddc.list` and surfaces a one-line install or full apt setup accordingly.
- Smoke test surfaces `error while loading shared libraries` (exit 127) with the missing-lib name so users know which `ddc-deps-*` package to reinstall.

### Changed
- Sidebar active state — single winning route now highlighted (was: parent + child both lit on `/bim/rules`); active background bumped from `oe-blue/[0.08]` to `oe-blue/[0.14]` with a 2 px left bar and inset hairline.
- Header `ProjectSwitcher` — bigger 36 px hit-target, always tinted, dashed CTA + pulsing dot when no project, solid blue-subtle + folder square + bold name when active.
- Header right side reorganized into 4 zones (Search · Notifications+Help · Account) with hairline dividers.
- Avatar in user menu now has gradient + drop-shadow + animated online dot (matches the rest of the chrome).
- Header bottom is now a soft hairline gradient instead of a hard 1 px border.
- All decorative emojis in `/bim/rules`, `/chat` data panel, BOQ grid, BIM filter panel, AI config banner, match panel, and project detail replaced with lucide icons. Country flags and i18n locale flags untouched.

### Fixed
- `app/modules/takeoff/router.py` — `uuid.UUID(...)` reference fixed to use the local alias (`_uuid.UUID(...)`); previous code raised `NameError` at runtime.
- `MatchSuggestionsPanel` test mocks updated to include `listLoadedDatabases` / `setProjectCatalog` so `CatalogBindingBar` mounts in tests.

### Internal
- Migration `v283_costs_region_active_index` — inspector-guarded composite index on `oe_costs_item(region, is_active, code)`. New DBs get it via `Base.metadata.create_all()` from updated `__table_args__`.
- New backend tests `tests/unit/test_cad_import_linux.py` (8) cover the Linux converter probe + `ld.so` failure heuristic.

## [2.8.8] — 2026-05-04

### Added
- `POST /api/v1/requirements/{set_id}/validate-bim/{model_id}` — runs every requirement in a set against every element of a BIM model and persists a regular `ValidationReport`. Reuses the existing dashboard, BIM viewer badges, and SARIF export.
- `GET /api/v1/requirements/template.xlsx` — downloadable Excel template with headers, a sample row, comment hints per column, and a Legend sheet listing all 10 operators.
- `POST /api/v1/requirements/{set_id}/import/file/` — Excel/CSV bulk import; format auto-detected, malformed rows reported as warnings.
- `GET /api/v1/requirements/{set_id}/export.{xlsx|csv|json}` — unified export endpoint; extension drives the format.
- `/bim/rules?mode=requirements` toolbar — Import / Template / Export / "Validate against model" buttons; validation result card with score, counts, and link to the full report.
- BIM model picker modal lets the user pick which model to validate against; status pulses while the run is in flight.

### Changed
- Requirement constraint operators unified across the stack: backend now accepts the full set `equals | not_equals | min | max | range | contains | not_contains | regex | exists | not_exists` (was 6); frontend `bimConstants.ts` aligns; Excel template documents all 10. The previous `regex: ".+"` workaround for "any value" presets is gone — `exists` is the operator.
- Constraint value input in the requirement editor now switches widget by operator: number for min/max, two numbers for range, regex with live validation, text for the rest, hidden for exists/not_exists. No more guessing whether a field expects "200..400" or "200,400".
- Requirement form no longer prefixes notes with `[REVIT] Category=...` — the entity field already carries the category.

### Internal
- `requirements/evaluator.py` — pure constraint evaluator; 32 unit tests cover all 10 operators, edge cases, European decimal separator, range separator variants.
- `requirements/excel_io.py` — Excel/CSV template + parse + export, with operator legend sheet; 8 unit tests cover roundtrips, missing required columns, unknown-operator warnings.
- `requirements/bim_validator.py` — bridges EAC schema to the existing `ValidationReport` storage so all validation surfaces (dashboard, BIM badges, SARIF) work without per-source forks.

## [2.8.7] — 2026-05-04

### Changed
- /bim/rules — empty state now shows 4 starter templates (Walls / Slabs / Doors / Windows) that pre-fill the editor in one click instead of a generic "Create your first rule" CTA.
- /bim/rules?mode=requirements — empty state now offers 3 ready-made compliance packs (Fire safety, Thermal performance, Structural integrity); installing a pack auto-creates the requirement set and bulk-adds 3 rules using backend-accepted constraint types only.
- BIM model picker now appears on both tabs; Requirements uses it to populate the "From BIM Model" auto-fill from the selected model's elements.
- /login — removed the broken Privacy / Terms footer links (the underlying static HTML pages don't exist in production builds).

### Internal
- Layer-3 authorship fingerprints added across the codebase (see `tools/watermark/`) — no functional impact.

## [2.8.6] — 2026-05-04

### Fixed
- Registration form now shows a clear "Account created. An administrator needs to activate it" message when the server returns `is_active=false` (gated registration mode). Previously the form auto-attempted login, hit the same generic 401, and dumped users at /login with no idea what went wrong.

## [2.8.5] — 2026-05-04

### Fixed
- Fresh-install registration: the seeded `demo@openestimator.io` admin no longer blocks the bootstrap path. First real self-registered user is now correctly promoted to admin and `is_active=True`, regardless of `OE_REGISTRATION_MODE`. Previously, every `pip install openconstructionerp` left new users dormant with no path forward.
- `/projects/:projectId/boq` only fetches that project's BOQs instead of fanning out to every project, cutting skeleton time on prod (50+ projects) from ~2 s to one round-trip.

### Tests
- New regression: `test_demo_admin_seed_does_not_block_bootstrap` covers the dormant-user gotcha.

## [2.8.4] — 2026-05-04

### Fixed
- `/costs` and `/catalog` now auto-pick the first loaded region when none is selected. Previously the page showed a "No database loaded" empty state even when /setup/databases had already populated rows, because the picker waited for an explicit selection.
- Sidebar version label now reads from `frontend/package.json` correctly. v2.8.3 wheel shipped with the sidebar baked at "v2.8.2" because `npm run build` ran before the package bump.
- `/projects/:projectId/boq` route added — previously 404'd. Pre-filters the BOQ list to the project so users coming from the project detail page don't have to re-pick the project.

## [2.8.3] — 2026-05-04

### Fixed — Catalogue load now populates BOTH cost layers
- `/setup/databases` only called `/v1/costs/load-cwicr/` and silently skipped `/v1/catalog/import/`. Sidebar shows both "Cost Database" and "Resource Catalog" — they're separate tables (`oe_costs_item` vs `oe_catalog_resource`) — but only the first got data. Users saw the success toast, navigated to "Resource Catalog", found it empty, and concluded the load had failed.
- `handleLoadRegion` and `handleLoadAll` now `Promise.all` both endpoints. Catalog import is best-effort (some regions ship only the cost layer). Single combined toast: "X cost items · Y catalog resources" with 8 s duration.
- Both `['costs']` and `['catalog']` query keys invalidated on success.

### Added — Deep links from setup → DB browsers
- Region cards now show inline `View cost items →` and `View resources →` after load, linking to `/costs?region=<id>` and `/catalog?region=<id>`.
- `CostsPage` and `CatalogPage` read the `?region=` URL parameter on mount, pre-select the filter, then strip the param so reloads don't re-force it.
- `/setup/databases?vectorize=<id>` deep-link from the Match panel scrolls to the targeted card with a 2.4 s blue ring + hint toast.

### Improved
- Match panel catalogue picker: replaced mouse-only `onMouseLeave` with proper pointerdown-outside + `Escape` handlers, plus `role="listbox"` + `aria-label`. Touch and keyboard users no longer end up with a stuck dropdown.

### Tests
- 5 new unit tests for `_looks_like_fixture` heuristic (TEST- prefix, A001-style codes, canned descriptions, real CWICR pass-through, missing-code edge case) + cache reset.

## [2.8.2] — 2026-05-04

### Added — Per-project CWICR catalogue binding for the matcher
- New nullable `cost_database_id` on `oe_projects_match_settings` (alembic v282) — explicit per-project pick (`RU_STPETERSBURG`, `DE_BERLIN`, …); no auto-pick from `project.region`.
- `MatchResponse.status` envelope: `ok` / `no_catalog_selected` / `catalog_not_vectorized` / `no_catalogs_loaded` — UI renders distinct empty states with targeted CTAs instead of silent zero-results.
- `GET /api/v1/costs/loaded-databases/` — per-region SQL count + LanceDB vector count + ready flag.
- `<CatalogBindingBar>` always visible at the top of the Match panel: badge ("📚 RU_STPETERSBURG · 55,719 / 1,000 vec"), dropdown picker driven by the new endpoint, click-to-rebind with React Query invalidation.
- SQL `ILIKE` lexical fallback in `app.modules.costs.vector_adapter.search()` when LanceDB is empty / fixture-only / encoder unavailable, so users see real CWICR rows instead of an empty pane while ops backfills the index.

### Fixed
- Stale `cost_database_id` (pointing at an unloaded region) now degrades to `no_catalog_selected` when other catalogues are loaded — previously claimed `no_catalogs_loaded`, sending the user to a "load a catalogue" CTA while their other catalogues sat right there.
- `<CatalogBindingBar>` picker dropdown got `position: absolute` against a non-positioned ancestor (`mt-32 right-3` placed it ~128 px below random parent). Added `relative` parent + `top-full mt-1` so it now drops below the bar reliably.

### Verified
- 224+ backend tests green (incl. 12 new tests in `test_match_catalog_binding.py` covering all 4 envelope states + SQL-injection whitelist on `vector_count_with_payload_substring`, plus 5 new tests in `test_match_settings.py` for the PATCH/GET round-trip + reset).
- Smoke-tested all four `MatchResponse.status` paths against a real backend with two loaded catalogues.
- TS strict clean (`tsc --noEmit` exit 0). Vite production build succeeds.

## [2.7.7] — 2026-05-03

### Fixed — Match tab now lives in the Element Inspector users actually see
Phase 4 mounted the Match panel into a separate `BIMRightPanelTabs` component (Properties/Layers/Tools/Groups/Match) that only opens when the user explicitly toggles the "Linked BOQ" button in the BIM toolbar. Visual QA confirmed real users never get there: when they click an element, the auto-opening **Element Inspector** (Properties/Links/Check, inside `BIMViewer.tsx`) is what they expect to see — and Match was missing from it.

- **Added a 4th "Match ✨" tab** directly inside the Element Inspector right next to Properties/Links/Check. The instant a user picks a BIM element, the inspector pops up with all four tabs and the Match panel is one click away — no Linked-BOQ toggle, no separate panel to discover.
- The standalone `BIMRightPanelTabs` keeps its Match tab too — the two surfaces are now consistent (anywhere the user is, Match is visible) so we don't have to choose one path.
- Panel renders with `compact` mode and remounts on `selectedElement.id` change so the per-element rejection accumulator never leaks across selections.

### Verified
- 40/40 frontend tests still pass; backend untouched.
- TS strict clean (`tsc --noEmit` exit 0).
- Vite HMR confirmed serving the updated `BIMViewer.tsx` with the new tab + Match panel imports.

## [2.7.6] — 2026-05-03

### Fixed — Match tab now reachable via standard click flow (browser-verified)
- **`BIMViewer` health-stats banner is `pointer-events-none` on the container** with `pointer-events-auto` on each pill — clicks pass through the banner's negative space straight to the right-panel tabs underneath. The previous `max-w` workaround helped only on viewports with few pills; the new approach works regardless of pill count or wrap behaviour.
- **Right BIM panel widened 340 px → 380 px** so all 5 tabs (Properties · Layers · Tools · Groups · Match) fit comfortably with `truncate` no longer collapsing the Match label down to its `Sparkles` icon. Each tab now gets ~70 px instead of ~62 px.
- **Right BIM panel z-index bumped 15 → 25**, above the elements-loaded banner (z-20) and the auto-opening "Filtered summary" popup (z-20). Filter popup no longer occludes the Match tab.
- **`max-w-[calc(100%-360px)]` → `max-w-[calc(100%-400px)]`** on the banner so its right edge stays clear of the wider panel even before pointer-events kick in.

### Verified
- 40 frontend tests still green; backend untouched.
- Live browser probe (`qa-tests/v275-probe/probe_final.py`) confirms `[role=tab]:has-text("Match")` is reachable via Playwright `.click()` without any JS bypass — banner pills no longer intercept pointer events.
- Tab strip rendering verified at 1440×900 viewport with full element-banner rendered.

## [2.7.5] — 2026-05-03

Phase 3 + Phase 4 of vector match + concurrent-match perf hardening, shipped together.

### Added — Phase 3: translation download UI
- **`TranslationSettingsTab`** at `frontend/src/features/translation/` — cache stats, dictionary table, MUSE form, IATE local-path + URL forms, in-flight task card with progress bars. Adaptive 5 s / 30 s React Query polling driven by in-flight task count so idle deployments don't burn requests.
- **Mounted in `ProjectSettingsPage`** as a Card section with `id="translation"` so the existing `#hash` deep-link + ring-pulse pattern (originally for `#fx-rates`) drops in unchanged.
- **`MatchSuggestionsPanel`** surfaces an info banner when `translation_used.tier_used === 'fallback'`, deep-linking to `/projects/${projectId}/settings#translation` so users can fix the fallback in one click.
- **Client-side IATE allowlist** mirrors the backend SSRF guard (`isIateUrlAllowed()` + `IATE_ALLOWED_PREFIXES`); backend re-validates so the client check is purely advisory.

### Added — Phase 4: BOQ accept + auto-link execution
- **`POST /api/v1/match/accept`** consolidates the previous three round-trips (create/update position → BIM link → submit feedback) into one transactional call. Body carries the accepted candidate, the rejected list, target boq + parent_section, optional `existing_position_id` for the update path, optional `bim_element_id` for the link, and an optional quantity override.
- **`accept_match()` service** writes provenance into `Position.metadata`: `cost_item_code`, `match_score`, `match_vector_score`, `match_boosts_applied`, `match_confidence_band`, `matched_at`, `matched_by_user_id` — every AI-accepted position is auditable end-to-end.
- **AI-NNN ordinal namespace** for AI-accepted positions so they're visually distinguishable from manual entries in the BOQ grid.
- **`source: "ai_match"`** added to `PositionCreate` / `PositionUpdate` regex allowlist.
- **`useAcceptMatch` mutation** + cache invalidations in `frontend/src/features/match/queries.ts`; `MatchSuggestionsPanel` now wires Accept and (opt-in) auto-link with a `AUTO_APPLY_DELAY_MS=1500` confirmation window so users can intercept before the auto-link fires.
- **BIM right panel** wires the accept flow to a BOQ picker.

### Performance — concurrent match latency hardening
- **Embedder warm pool** — `app/core/embedding_pool.py`: thread-pool by default (`OE_VECTOR_POOL_KIND=thread`), opt-in `process` for true parallel encodes. Smart routing — single calls run inline (skip pickle/IPC), concurrent calls dispatch to the pool. Sync warmup at startup so the first match request doesn't pay the model-load cost.
- **Project-region TTL cache** with inflight de-duplication (`app/core/match_service/region_cache.py`) — boosts no longer issue one `ProjectRepository.get_by_id` SELECT per concurrent request.
- **Server-side p95 at 50× concurrency: 4958ms → 2511ms (−49 %).** Throughput +72 %. Client-side p95 still gated on the LanceDB single-process read lock — flagged as architectural follow-up.

### Fixed — translation cache LRU correctness
- **LRU keyed on cache path** — module-level LRU keys now include the SQLite path so two callers using different cache files (production vs per-test temp DBs) cannot collide on identical `(text, src, tgt, domain)`. Surfaced as a real cross-test pollution while wiring the perf-hardening tests.
- **`mark_used()` invalidates the LRU row** — usage_count / last_used_at bumps are now visible on the next `get()` instead of being shadowed by the stale row that was cached at insert time.

### Fixed — Phase 4 visual QA findings (36-screenshot capture, 14 findings)
- **Match tab no longer occluded by the BIM elements-loaded banner.** `BIMViewer.tsx` health-stats banner reserved 280 px for the right tab strip but the strip is 340 px wide, leaving a 60 px overlap that made the Match tab unclickable on every desktop viewport. Bumped the reserved width to 360 px so the banner can never sit on top of the tabs.
- **Stale match candidates on element switch.** `MatchSuggestionsPanel` is now keyed on `selectedElementId`, so picking element B after element A refires the autoFetch effect and resets the per-element rejection accumulator instead of showing element A's results until manual refresh.
- **`ScoreBadge` boost-breakdown now reaches touch + screen-reader users.** Tooltip toggles on `onClick` (was hover-only), exposes `aria-describedby` + `aria-expanded`, and assigns the tooltip a stable `id` for the description link. Keyboard focus path unchanged.
- **`bim.tabs.match` → `bim.tab_match`** — naming consistency with the four other BIM tab keys (`tab_properties`, `tab_layers`, `tab_tools`, `tab_groups`).

### Tests
- 18 backend integration tests for `accept_match` (`tests/integration/test_match_accept.py`).
- 39 perf / cache / region tests (`tests/unit/test_translation_cache_lru.py`, `test_project_region_cache.py`, `test_vector_warmpool.py`, `tests/perf/test_match_concurrency.py`).
- 4 frontend BOQ-wiring tests + 3 a11y assertions; 12 translation-tab unit + 3 axe tests.

### Known limitations (deferred follow-ups from Phase 4 QA)
- **`match.*` translation keys exist only as `defaultValue`** in source — non-English locales fall back to English. Same project-wide pattern as the other BIM tab labels; out of scope for v2.7.5, tracked for the next i18n sweep.
- **`BIMRightPanelTabs` does not mount on mobile (390 × 844)** — Match tab unreachable on mobile. Either intentional (desktop-only feature) or a long-standing regression; needs investigation before adding a "Desktop only" banner or a responsive variant.
- **`MatchSuggestionsPanel`'s `selectedElementId` flow only works on desktop today** — mobile is blocked on the same panel-mount issue above.

## [2.7.4] — 2026-05-03

### Added — Phase 2 of vector match: `MatchSuggestionsPanel` frontend
- **`MatchSuggestionsPanel`** in `frontend/src/features/match/` — shared React component that calls `POST /api/v1/match/element` and renders ranked CWICR candidates with confidence pills (high/medium/low color-coded), boost-breakdown tooltip on hover, region/code/unit/rate display, optional LLM-rerank toggle, refresh button, auto-link banner when threshold crossed. Per-candidate Accept / Reject buttons; rejection accumulator submits `accepted_candidate + rejected_candidates` together via `POST /api/v1/match/feedback` on accept.
- **`useMatchElement` + `useSubmitMatchFeedback` React Query hooks** — typed mutations against the backend match endpoints; types defined in `features/match/types.ts` mirroring `MatchCandidate` / `MatchResponse`.
- **Mounted in BIM right panel** as a 5th "Match" tab — when an element is selected, the panel auto-fetches candidates from CWICR using the vectorized catalog. Phase 4 will wire `onAccept` to the actual BOQ-link mutation; for now logs to console + toast.
- **i18n**: every user-visible string via `t("match.*")` with inline default values per project convention. Top-5 locales (en/de/ru/ja/ar) populated by the bulk i18n sweep.
- **a11y**: `role="list"` / implicit `listitem`, color-blind-safe confidence pills with explicit `aria-label`, full keyboard navigation. Axe-core: 4/4 a11y tests pass with zero violations.
- **21 new tests** (17 unit + 4 a11y); typecheck + lint clean.

## [2.7.3] — 2026-05-03

### Added — Phase 1 of vector match: material-aware classification enrichment
- **`enrich_classification(category, material, fire_rating, structural)`** in `app/modules/cad/classification_mapper.py` — DE/EN material synonym folding (Beton/Stahlbeton/concrete; Ziegel/Mauerwerk/brick; Holz/timber/wood; Stahl/steel; Trockenbau/Gipskarton/drywall; aluminium; glass) + deeper DIN276 / NRM / MasterFormat codes when material is known. Falls back to coarse 3-digit DIN code when the material is proprietary/unknown. Codes aligned with the golden-set fixture so the matcher's classifier boost can fire on real CWICR rows.
- **BIM / PDF / DWG extractors auto-derive `classifier_hint`** — when raw imported data has no `classification` block, the extractor calls `enrich_classification` for all three standards and the matcher's `classifier_match` boost rewards the right CWICR position. Pre-classified imports keep their existing codes — no override.
- **77 new tests** (61 unit + 16 integration). 2666 other unit tests still pass, no regressions.

## [2.7.2] — 2026-05-03

### Added — Phase 0 of vector match foundation (v2.8.0 prep)
- **Cost-items vector adapter** — `oe_cost_items` LanceDB collection, multilingual-e5-small embeddings with passage:/query: prefixes, event-bus reindex on CRUD, gated `POST /api/v1/admin/cost-vector-reindex` endpoint, async startup backfill.
- **Translation cascade service** — `app/core/translation/` with 4-tier (MUSE/IATE lookup → SQLite cache → LLM via ai_client → fallback), phrase-aware tokenization preserving construction codes (C30/37, IPE100), `POST /api/v1/translation/translate` + lookup-table download/status endpoints.
- **MatchProjectSettings model** — per-project target_language / classifier (din276/nrm/masterformat/none) / auto_link_threshold / mode (manual/auto) / sources_enabled. Lazy-init on first GET, audit-logged updates.
- **Match service core** — `app/core/match_service/` with universal envelope, ranker (translation → vector search → 4 boosts → auto-link gate), opt-in LLM reranker with cost cap, 4 source extractors (BIM + PDF functional, DWG + photo stubs marked for v2.8 follow-up), feedback loop. `POST /api/v1/match/element` + `POST /api/v1/match/feedback`.
- **Eval harness** — `tests/eval/` with 30+ realistic golden-set entries, AI-as-judge with rule-based fallback, runner with metrics (top-1 acc, top-5 recall, MRR), `.github/workflows/eval-match.yml` CI workflow.

### Security
- **SSRF guard on IATE downloader** — host allowlist (iate.europa.eu / DDC mirrors / OE_IATE_EXTRA_HOSTS env var) + `follow_redirects=False`. Without this an authenticated user could pivot the backend to fetch cloud-metadata or internal services.
- **Cross-user task leakage fixed** in `GET /api/v1/translation/lookup-tables/status` — now filters in-flight tasks by owner so users can't see each other's task ids / error strings (which can leak filesystem paths).

### Fixed (verification pass)
- **Region boost** for fully-qualified projects (e.g. `DE_BERLIN`) — was returning a bare string that iterated character-by-character; now returns exact code as a single-element tuple. Real ranking-quality regression for pinned-city projects.
- **Sentinel UUID FK violation** in `match_element` — wraps `get_or_create_match_settings` in try/except with transient-defaults fallback so eval harness and stale callers no longer surface 500.
- **`POST /api/v1/match/element` with bogus source** now 422 instead of 500 (Pydantic Literal validator on `source`).
- **Classifier reverse-substring fallback** removed — `"33"` no longer matches `"330.10.020"`. Forward containment only, min 3 characters.
- **Deterministic tie-breaking** in ranker — secondary sort key on `code` so auto-link winner is stable across reruns.
- **`tests/unit/test_costs_vector_adapter.py`** — switched `del sys.modules; import_module` to `importlib.reload(...)` to avoid orphaning module references and breaking downstream monkeypatches.
- **Alembic single-head** restored — translation-cache migration repointed onto `v2b1_compound_type_indexes`.

### Tests
- 194 Phase 0 tests added across unit / integration / eval / perf (118 baseline + 70 edge cases + 6 region regression).

## [2.7.1] — 2026-05-03

### Added — Pareto / ABC analysis on the resource summary (Issue #106)
- **`ResourceSummaryItem.abc_percentage` + `abc_class` (A / B / C).** The `/v1/boq/boqs/{boq_id}/resource-summary/` endpoint now returns each aggregated resource's share of the total summed cost (0–100) and its ABC bucket using the conventional 80 / 15 / 5 cumulative thresholds. The response also carries `grand_total` so the frontend doesn't recompute it.
- **Sortable columns + ABC bucket pills in `ResourceSummary.tsx`.** New "ABC %" column with red / amber / green pills (A = top items driving ~80 % of cost, B = ~15 %, C = ~5 % long tail). The Name / Total Cost / ABC % column headers are now click-to-sort. ABC sort mode draws thicker dividers between A → B and B → C boundaries so the Pareto split is instantly readable when the panel is expanded.

### Added — Display-currency selector for BOQ grand total (Issue #88, MVP)
- **"Display in: [USD ▾]" picker next to the BOQ mini-summary grand total.** When the project has at least one FX rate configured (Project Settings → FX Rates), users can flip the displayed grand total between the project's base currency and any FX-rate'd currency without persisting anything server-side. The persisted base-currency total is unchanged; this is a render-only conversion. Per-section / per-position display-currency conversion is intentionally a follow-up — the cell-renderer rewrite is bigger than this release. Hover tooltip surfaces the FX rate used so the conversion is auditable.

### Changed — Clickable "set FX" warning on BOQ resources (Issue #105)
- **The amber `⚠ no FX` badge on a resource row is now a button.** Clicking it routes the user straight to Project Settings → FX Rates with the FX-rate Card scrolled into view and pulsed for 2 s so it's instantly findable. The deep-link target is `Project.fx_rates` (Card `id="fx-rates"`). When `onOpenFxRateSettings` is not wired (e.g. embedded grids), the badge falls back to the previous static `⚠ no FX` chip — graceful degrade, no breakage.

### Verified — Composite-item editor sub-asks (Issue #93)
- **Centralised FX template** (`Project.fx_rates`) was already wired into the resource-currency picker (`cellRenderers.tsx:3127, 3301-3326`); confirmed every project FX-rate'd currency is offered.
- **Editable resource type per component** (Material / Labor / Equipment / Operator / Subcontractor / Electricity / Composite / Other) was already supported via `ResourceTypePicker` (`cellRenderers.tsx:3424-3429`, type registry `boqResourceTypes.ts:27-36`).
- **Custom unit free-text** was already supported by `InlineUnitInput` (`cellRenderers.tsx:2196-2430`); user-typed units land in `User.metadata_["custom_units"]` via `saveCustomUnit()` and merge into the dropdown for future picks.

### Verified — `source: "cwicr"` BOQ position writes (Issue #79)
- **The schema regex on `PositionCreate.source`** (`backend/app/modules/boq/schemas.py:184`) and `PositionUpdate.source` (line 268) accepts `cwicr` alongside `manual`, `cad_import`, `ai_takeoff`, `gaeb_import`, `excel_import`, `takeoff`, `smart_import`, `smart_import_ai`, `cad_import_ai`, `cost_database`, `assembly`, `enriched`. iModel-driven BOQ pushes can use `source: "cwicr"` and `cost_item_id` directly via the public API.

## [2.7.0] — 2026-05-03

**Stable release rolling up 14 patch iterations (2.6.41 → 2.7.0).** Single shipping artefact for all platforms (PyPI · git tag · VPS · GitHub release). All entries below — 2.6.42 through 2.6.54 — are part of this release; the per-version sections are kept for changelog continuity but ship as one tag.

### Highlights since v2.6.41
- **CWICR download fixed on Windows** (issue #104) — replaced stdlib `urllib.request` with `httpx` + `certifi`, so HTTPS downloads of region catalogs no longer fail with `CERTIFICATE_VERIFY_FAILED` on stock Windows.
- **Cost-DB modal opens instantly** — startup pre-warm + 60-min cache + idle-time prefetch + skeleton loading state.
- **Multi-variant resource picker** — explicit modal for cost items with multiple independent variant slots; bulk-fill chips, per-row delta vs mean, RTL-correct layout, 19 i18n keys × 5 langs.
- **Variant resources dedupe** — three-layer fix (modal, apply-time, render-time, summary aggregator) so shared catalogs across components no longer surface as duplicate "▾N" pills; "Variant" violet-gradient chip replaces the cryptic "Materials" type chip on variant rows.
- **Imported / cleared cost databases appear immediately** — `_invalidate_cost_cache()` now wired to `bulk_import_cost_items`, `import_cost_file`, `clear_cost_database`.
- **5 new UI languages** — hr, id, ro, th, vi (now 24 total UI langs / ~28 k keys).
- **QA-crawler bug sweep** — 12 + 3 fixes from automated multi-locale crawl (trailing-slash, region-delete confirm, modal a11y, …).
- **/tasks page DnD optimistic update** — cards move between columns immediately, rollback on PATCH failure.
- **/bim — disk-usage chip moved to hover-tooltip** — model name area no longer clutters with `data/bim/ 86.3 MB` on every project.
- **Privacy / Terms rewritten for self-hosted edition.**
- **Resource-row depth + GAEB audit polish** — 8 fixes: encoding, units, hierarchy, paragraphs, version detection.

### Fixed — CWICR download from GitHub on Windows (issue #104)
- **Replaced `urllib.request.urlretrieve` with `httpx.stream` + `certifi`.** Python's stdlib `ssl` on Windows ignores the OS certificate store, so every HTTPS download to `raw.githubusercontent.com` failed with `SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate` — symptom reported in #104 by skolodi (v2.6.37) trying to load `SP_BARCELONA`. New `_download_to_file()` helper uses `httpx`, which is already a project dep and ships the Mozilla CA bundle via `certifi`, so verification works on Windows without `pip install python-certifi-win32` or env-var workarounds. Streams in 1 MB chunks so the 1.1 GB Qdrant snapshot doesn't blow up RAM. Three call sites swapped: CWICR parquet download, vector-embeddings parquet download, and Qdrant snapshot download.

### Fixed — Imported / cleared cost databases now appear immediately
- **Import endpoints invalidate the cost cache.** `bulk_import_cost_items`, `import_cost_file`, and `clear_cost_database` now call `_invalidate_cost_cache()` on success — was: only `clear_region_database` and `load_cwicr_database` did, so a freshly imported region (e.g. NZ_AUCKLAND via Excel/CSV) was hidden behind a 60-min stale `_region_cache["regions"]` until the cache TTL elapsed or another invalidating call fired. User-visible symptom: "imported a database but nothing in /costs page".
- **`_invalidate_cost_cache()` wipes all value slots, not just `ts`.** Now nulls every key in `_region_cache` (regions / stats / categories_*) explicitly so any future cache slot that doesn't piggy-back on the shared timestamp is still cleared.

### Fixed — Variant resources: dedupe shared catalogs + clear "Variant" chip
- **Dedupe ▾N pickers across components that share a `resource_code`.** CWICR rate `KADX_KATO_KAKASA_KATO` ships two resource rows ("Stahlkonstruktionen" + "Befestigungsteile für Schienen") both pointing at code `KALI-RI-KATO-KANE` with the same 3-variant catalog. Before: both BOQ rows + both summary rows showed identical "▾ 3" pills, looking like a UI bug. After: only the FIRST row per `resource_code` carries the picker; linked rows render plain. Applied at three layers: BOQ "Add from DB" apply-time (`BOQModals.tsx`), grid render-time for legacy positions (`BOQGrid.tsx`), and resource summary aggregation (`backend/app/modules/boq/router.py` — new `resource_code` field on `ResourceSummaryItem`).
- **Dedupe top-level vs component catalogs by variant-label hash.** BG_SOFIA rate `KADX_KADX_KAKARI_KAME` ("Монтаж на метални конструкции") ships its 8-variant catalog as BOTH `metadata.variants` AND `components[0]` ("Стоманени конструкции"). The "Choose materials" modal previously rendered two slots with identical 8 options, identical price, identical −13% delta — both reading like a duplicate. Now `collectVariantSlots()` hashes each catalog by its label sequence: when the top catalog matches a component catalog the top slot is dropped, AND `BOQModals.handleAdd` skips the synthetic top-level resource it used to append (the "third extra" the user flagged), so a 2-component cost item adds exactly 2 resources to the BOQ.
- **Multi-variant picker modal also dedupes.** `collectVariantSlots()` no longer emits two cards for the same catalog — picks fan to all linked components when the position is materialised.
- **"Variant" type tag replaces the Material/Labor/Equipment chip on variant rows.** The left-side type chip on a BOQ resource row is now a violet-gradient "Variant" badge when the row carries a variant catalog, instead of the cryptic black "Materials" tag that didn't hint at the picker. Same chip lands on the Resource Summary panel. Reclassification still works — clicking opens the full type list — but the chip face is unambiguous about variant status. The decorative "V" circle in the resource name area is unchanged.

## [2.6.53] — 2026-05-02

### Performance — Cost-DB modal opens instantly
- **Backend cost-DB cache pre-warm at startup.** New background task in `app/main.py` runs `SELECT DISTINCT region` + `regions/stats` + `categories(all)` + `category_tree(depth=4)` for every active region during the first 2 s of boot, populating `_region_cache` and `_category_tree_cache` before any request hits. The first user click on "Add from Database" or `/costs` page no longer pays the 18 s + 16 s + 86 s cold aggregation cost.
- **Search-endpoint count(*) fast-path.** When the search call has no text/category/classification filters and no cursor (the modal's first page), the total is now read from the prewarmed `_region_cache["stats"]` instead of running `SELECT COUNT(*)` over the filtered subquery. Full-catalog count took 18 s on a 277 k-row catalog before; cache lookup is microseconds.
- **Cache TTL bumped 5 min → 60 min.** `_CACHE_TTL` and `_CATEGORY_TREE_CACHE_TTL` raised; both are correctly wiped on import/delete via `_invalidate_cost_cache()`, so the longer hold doesn't risk staleness — it just stops the same scan from repeating every 5 min for an unchanged catalog.
- **Modal opens with `depth=2` tree, not `depth=4`.** The cost-DB modal's classification sidebar now uses a 2-column GROUP BY (~10 s cold) instead of a 4-column GROUP BY (~85 s cold) on a 277 k-row catalog. Deeper levels are still reachable via the search endpoint's `classification_path` filter when the user clicks a level-2 leaf, so coverage isn't lost.
- **Frontend idle-time prefetch on BOQ editor mount.** `BOQEditorPage.tsx` now prefetches `/v1/costs/regions/`, `/v1/costs/category-tree/?region=<first>&depth=2`, AND the first-page `/v1/costs/?limit=15&region=<first>` search via `requestIdleCallback` (setTimeout fallback) — all three heavy modal calls warmed in parallel via `Promise.all` while the editor is idle. React Query is hot for the FIRST CLICK on "From Database" even on a freshly-restarted backend before its server-side prewarm finishes.
- **Modal seeds region from React Query cache synchronously.** `BOQModals.CostDatabaseSearchModal` reads the `cost-regions-modal` cache in a lazy `useState` initializer so the modal mounts with the right region (e.g. `FR_PARIS`) instead of `''`. The previous code rendered with `region=''` for one render tick before the auto-default `useEffect` ran, which fired wasted `tree?depth=2` (no region — heaviest GROUP BY) and `search?limit=15` (no region — slowest `COUNT(*)`) calls. With the cache seed, those wasted calls are eliminated when the BOQ-editor prefetch is hot.
- **Skeleton table in the modal results pane.** Generic centered "Loading…" spinner replaced with 8 skeleton rows that mirror the actual result columns (checkbox / description / unit / qty / rate / region). Reads as "loading specific data" instead of "stuck".

### Fixed — `/costs` page no longer flashes "No database loaded" while loading
- **Skeleton vs empty-state.** `RegionTabBar` now distinguishes "still loading regions" from "actually empty" — when `loadedRegions` is `undefined` (request in-flight), shows a tab-bar skeleton with `Loading databases…` instead of the dashed-border "No database loaded" empty-state. Cold SQLite responds in 18 s on 100 k+ catalogs; the previous code conflated the two and showed the import-CTA empty-state for the entire wait, so the user reported the page as "broken / loads forever".

### UX — BOQ position add: section picker + apply-to-remaining
- **"Add to: …" footer dropdown.** Cost-DB modal footer now exposes the BOQ's existing sections in a dropdown ("[Root]" + each section by ordinal). Selecting a section files new positions under it with parent-relative ordinals (`<section>.<NNN+1>`) and threads `parent_id` into the POST body. Backend already accepted `parent_id` on `PositionCreate` since v1; the UI just wasn't surfacing it. Hidden in resource-pick mode and when the BOQ has no sections.
- **"Apply to remaining N" CTA in the multi-variant picker.** When mid-batch with more multi-variant items waiting, the picker footer surfaces an `Apply to remaining {{count}}` button. Clicking it captures the user's slot picks and short-circuits every subsequent open in the batch — slots are matched by name across CWICR rows so concrete-grade × rebar-diameter × formwork picks carry over even when item A and item B share resource names but different variant catalogs. Trailing "Applied picks to N more items" toast on completion.

## [2.6.52] — 2026-05-02

### UX — Cost-database add flow deepening
- **Inline quantity per row.** Cost-DB modal table now has a Qty column with a numeric input per row — sets `position.quantity` at POST time instead of the legacy hardcoded `1`. Eliminates the 20-cell-edit chore after a 20-item batch add. Focusing the input auto-selects the row.
- **Live cost preview in footer.** Footer shows `≈ €X` next to the selection counter — Σ(catalog rate × qty) for everything currently selected, so a 5-item batch isn't committed blind. Updates in real time as the user toggles selection or edits quantity.
- **Validation hints surface pre-add.** Items with `rate ≤ 0` (CWICR rows whose price never landed) and items with `unit = lump_sum` (where qty × rate is ambiguous) now show an amber `AlertCircle` next to the rate with a tooltip — same checks that the post-add quality dashboard runs, surfaced before commit.
- **Partial-success error recovery.** Per-item POST is now wrapped in try/catch with a `failed[]` array. If 18 of 20 items POST successfully and 2 fail, the loop completes and shows a warning toast listing the casualties — was: first failure aborted the entire batch silently.
- **Keyboard navigation in the row list.** ↓/↑ moves the highlighted row, Space toggles selection, Enter toggles (or fires Add when selection is non-empty), PageDown/PageUp jumps 10 rows, Home/End jumps to ends. Highlighted row gets an outline ring; scrollIntoView keeps it visible. Skips the handler when focus is in an input so search-as-you-type stays unaffected.

## [2.6.51] — 2026-05-02

### UX
- **Multi-variant position add: explicit picker for 2+ slots.** When a CWICR cost item has multiple independent variant resources (e.g. concrete grade × rebar diameter × formwork type), `Add to BOQ` now opens a centered modal — one card per slot, bulk-fill chips (median / average / cheapest / priciest), per-row delta-vs-mean, live position subtotal. Single top-slot items keep the existing anchored popover; the legacy silent-median path is the cancel fallback. New: `frontend/src/features/costs/MultiVariantPicker.tsx` + `collectVariantSlots()` helper; `BOQModals.handleAdd` routes through it whenever there are 2+ slots or any per-component slot.
- **Multi-variant picker hardening pass.** Two parallel deep-audit subagents flagged six concrete gaps; all addressed in this release:
  - **RTL.** Replaced physical `mr-/ml-/text-right/text-left` with logical `me-/ms-/text-end/text-start` so Arabic users see a correctly-mirrored modal (was: header icon + price column on wrong side).
  - **Keyboard.** Apply button receives initial focus; Enter applies (was: Esc-only).
  - **Subtotal bug.** `slot.quantity || 1` replaced with `slot.quantity ?? 1` — a legit 0-qty slot (rebar=0 for unreinforced section) no longer inflates the position rate by treating it as 1 unit.
  - **Dark-mode contrast.** Selected variant rows had ~1.05:1 contrast vs unselected; added `ring-1 ring-inset ring-oe-blue/30` and bumped tint to `dark:bg-blue-950/30`.
  - **Token fix.** `border-border-medium` (undefined) → `border-border` for the unselected radio circle.
  - **Batch progress.** Adding 5+ items with multi-slots now shows an "Item N of M" badge in the header so the user knows how many modal opens remain.
  - **Provenance.** Position metadata stamps `ui_source: "multi_picker" | "single_popover" | "silent_default" | "no_variants"` so adoption is measurable from the audit log.
  - **i18n.** 19 new `boq.mvp.*` keys translated for en / de / ru / ja / ar in `i18n-fallbacks.ts` (German uses statistics-correct "Mittelwert" not "Durchschnitt"; Russian has 3 plural forms; Arabic has 6 plural forms incl. zero/two).

## [2.6.50] — 2026-05-02

### Performance
- **N+1 in `punchlist.get_summary`.** Counts pushed into SQL `GROUP BY`; only the closed-item timestamps still walk Python (date-diff isn't portable across SQLite + PostgreSQL). Drops full-row hydration of every punch item per stats call.
- **N+1 in `tasks.get_task_stats`.** Same pattern — total / by_status / by_type / by_priority / overdue / completed all run as SQL aggregates. Only the JSON `checklist` column for non-completed tasks is iterated (for `avg_checklist_progress`), and only the projected column ships, not full ORM rows.

### Fixed
- **Architecture page: 3968 React Flow warnings per render → 0.** `ModuleNodeComponent`, `ModelNodeComponent`, `RouteNodeComponent` had no `<Handle />` — every edge logged "Couldn't create edge for source handle id: null" once per render cycle. Added hidden source/target handles on all three.
- **Wider browser smoke clean — 53/53 routes.** Caught more disabled-module 404s: `/markups` calling `/v1/takeoff/measurements/`, `/dwg-takeoff` calling `/v1/dwg_takeoff/offline-readiness/`, `/project-intelligence` calling `/v1/project_intelligence/summary/`. All gated through the shared `isModuleLoaded` probe; the project-intelligence page now shows a translatable "module disabled" empty state.

## [2.6.49] — 2026-05-02

### Performance
- **N+1 in `meetings.get_stats` / `get_open_actions`.** Both loaded full ORM rows for every non-cancelled meeting just to walk the JSON `action_items` column. New repo method `action_items_for_project` fetches `(id, number, title, date, action_items)` only — drops every other column and ORM hydration.
- **N+1 in `fieldreports.get_summary`.** Same shape — full hydration of every report to compute counts. Pushed `total / by_status / by_type / total_delay_hours` into SQL `GROUP BY` + `SUM`; only the JSON `workforce` column still needs a Python pass for `count*hours`.
- **Compound indexes added.** New migration `v2b1_compound_type_indexes`: `(project_id, meeting_type)`, `(project_id, inspection_type)`, `(project_id, report_type)`. List filters used in dashboards no longer scan the project's whole row set when a type filter is applied.

### Security
- **IDOR sweep batch 4 — markups module.** Five endpoints patched: `link_to_boq`, `get_summary`, `export_markups`, `update_stamp_template`, `delete_stamp_template`, `delete_scale`. Stamp mutation now routes through `_authorize_stamp_mutation` (project members for project-scoped templates, owner-only for predefined). Scale deletion restricted to its `created_by`. AST guard extended 86 → 96 parametrized assertions.

### Fixed
- **Wide browser smoke clean — 25/25 routes.** Disabled-module 404 noise on `/data-explorer`, `/takeoff`, `/documents` traced to frontend calling `oe_takeoff` / `oe_dwg_takeoff` endpoints regardless of load state. Extracted a shared `isModuleLoaded` probe (`shared/lib/moduleProbe.ts`); rolled out across `cad-explorer/api.ts`, `dwg-takeoff/api.ts`, `takeoff/api.ts`, `quantities/QuantitiesPage.tsx`, `bim/api.ts` (refactored from inline probe).
- **MapLibre style noise.** `ProjectMap` switched from `liberty` to `positron` style — liberty's POI expressions tripped MapLibre's evaluator with "Expected value to be of type number, but found null instead." once per rendered card. Positron is quieter.
- **`ProjectMap` cache poisoning.** `parseFloat` of malformed Nominatim responses could write `NaN` (serialized as `null`) into the geocode cache, then read back as null lat/lng. Added `isFiniteNumber` guard on both write and read; bad cache entries are evicted on read.
- **CommandPalette rAF leak.** `requestAnimationFrame` for input focus on open had no cleanup — palette mount/unmount churn could fire `focus()` against a stale ref. Now `cancelAnimationFrame` on cleanup.

## [2.6.48] — 2026-05-02

### Performance
- **N+1 elimination on Change Orders list.** `repository.list_for_project()` now `selectinload(ChangeOrder.items)` — was firing one extra query per row to lazy-load items. Page with 50 orders: 51 queries → 1.

### Fixed
- **BIM page console noise.** Frontend probes `/v1/modules/` once per session and skips the `/v1/takeoff/converters/` request entirely when `oe_takeoff` is disabled, instead of relying on a swallowed 404 that the browser still logs to the network panel. Browser smoke now 6/6 routes clean.
- **Frontend timer cleanup leaks.** `BIMViewer.tsx` (geometry-progress timeout) and `BOQGrid.tsx` (3 grid-refresh setTimeouts) now track timers in refs and clear them on unmount — fast nav between BOQ/BIM pages no longer leaves orphaned callbacks running against an unmounted tree.

### Security
- **Stack-trace leak fixes.** `schedule/router.py` and `projects/router.py` 500-handlers stopped echoing `str(exc)` in `detail`; `backup/router.py` adds `from exc` to preserve the chain server-side without exposing it. Internal error messages no longer ship to clients.

## [2.6.47] — 2026-05-02

### Performance
- **SQLite write-lock deadlock — system-wide fix.** Every `await event_bus.publish(...)` inside a request handler held the SQLite single-writer lock while subscribers (the wildcard webhook dispatcher and ~7 notification handlers in `core/event_handlers.py`) opened their own writer sessions. SQLite serialised the second writer; requests hung ~30s before timing out. Live probes show formerly-30s routes now ~100ms: `POST /ncr/` 101ms, `POST /fieldreports/reports/{id}/submit/` 72ms, `POST /inspections/{id}/create-ncr/` 68ms.
- Centralised the fix in a new `EventBus.publish_detached(...)` method that wraps `publish` in `asyncio.create_task`. All 21 module-local `_safe_publish` helpers and 28 direct `await event_bus.publish(...)` callsites across 16 modules now route through it. Production semantics: subscribers fire after the request commits and releases the writer.
- Test-time shim in `tests/conftest.py` drives the publish coroutine to completion via a single `coro.send(None)` so the existing event-capture fixtures keep their pre-detached synchronous assertion semantics. 2597 unit tests green.

### Fixed
- **Latent crash in `assemblies/service.py`** — two more lazy `from app.modules.boq.models import BOQPosition` imports (lines 709, 955) — same renamed-class bug that hit `tendering/service.py` in v2.6.46. `get_usage_stats()` and `compute_assembly_usage_by_id()` would 500 on first call. Patched to `Position as BOQPosition` alias.

### Security
- **IDOR sweep batch 3** — 3 more modules patched: `requirements` (GET/PATCH/DELETE /{set_id}), `documents` (GET/{id}, GET /{id}/download/, PATCH /{id}, DELETE /{id}), `teams` (PATCH/DELETE /{team_id}). Documents download path was the highest-impact gap — any authenticated user could pass any document UUID and stream the file. Now `verify_project_access` after fetching the resource. AST guard test extended from 68 → 86 parametrized assertions.

## [2.6.46] — 2026-05-02

### Added
- **Cross-module: Tendering → Procurement auto-PO.** Awarding a tender bid now publishes `tendering.package.awarded`; a new procurement subscriber drafts a PO pre-filled with the winning supplier, line items, currency, and totals. Idempotent via `metadata.tender_package_id`. PMs no longer retype every line of the winning bid by hand. Verified live: award creates one draft PO with `metadata.origin="tender_award"`; re-firing the same award is a no-op.
- **Cross-module: Field Reports → Schedule progress.** Submitting a field report whose `metadata.schedule_progress = [{task_id, progress_percent, notes}]` carries activity progress now publishes `fieldreports.report.submitted`; a new schedule subscriber appends a `ScheduleProgressEntry` per task and rolls the activity's `progress_pct`/`status` forward. Per-report idempotency via `Activity.metadata_.field_report_progress`. Verified live: 60% → 100% over two reports yields 2 history entries and `status=completed`.
- **Inspection → NCR auto-suggest.** New `POST /api/v1/inspections/{id}/create-ncr/` pre-fills a Non-Conformance Report from a failed inspection with mapped `ncr_type`, severity (`critical` if any failed item is `critical: true`), location, and a description listing failed checklist items + notes. Idempotent via `linked_inspection_id`. Complements existing `/create-defect/` (punchlist) — punchlist for minor defects, NCR for formal non-conformance with root-cause/CAPA.

### Fixed
- **Latent crash in `apply_winner`.** `tendering.service.apply_winner` imported `BOQPosition` from `app.modules.boq.models`, but the class is `Position`. Every tender award has been 500'ing on the BOQ writeback step, masking the broken integration entirely. Repointed to `Position` (also for the SQLAlchemy `update()` statement); award now writes the winning unit rates back to the BOQ as designed.
- **`create-defect` checklist parsing.** The endpoint that creates punchlist items from failed inspections looked for a non-existent `passed: bool` field on checklist items, missing every actual `response: "fail"` (the schema-defined convention). Now accepts both forms — legacy `passed` and canonical `response` in (no/fail/false/0/failed). Without this, "create defect" generated empty-description punchlist items even when the checklist had real failures.
- **NCR-creation deadlock on SQLite.** `NCRService.create_ncr` awaited `event_bus.publish("ncr.created", ...)` before the request transaction committed; the wildcard webhook dispatcher and smart-notification subscribers (#23, #24 in `event_handlers.py`) open their own writers via `async_session_factory()`, deadlocking the SQLite single-writer lock for ~30s before the request timed out. Detached as `asyncio.create_task(...)` so subscribers run after the parent commit. Same pattern applied in v2.6.45's CO→BOQ work and v2.6.46's tendering/fieldreports subscribers.

## [2.6.45] — 2026-05-02

### Added
- **Cross-module: Change Order → BOQ pushdown.** Approving a change order now appends a section `CO-{code}: {title}` plus one position per `ChangeOrderItem` into the project's primary unlocked BOQ, with `metadata.origin="change_order"` and back-reference IDs. Construction PMs previously saw `project.budget_estimate` jump on approval but no scope appearing in the BOQ — this closes that loop. Idempotent: re-approving an already-approved CO is a no-op (existing ENH-095 guard) and the section-level guard short-circuits even if the no-op were bypassed. Surfaces in the `changeorder.approved` event payload as `boq_applied / boq_section_id / boq_positions_added`. Verified live: 2 items + 1 section row land in the right BOQ; second approve adds nothing more.

### Fixed
- **Latent bug in change-order approve.** `approve_order` accessed `order.project_id` after `repo.update_fields()` had called `session.expire_all()`, which under aiosqlite raises `MissingGreenlet` (sync attribute refresh in async context) and 500'd the entire approval whenever `cost_impact != 0`. Stub-session unit tests masked it because they bypass expiration. Now uses the `project_id_uuid` snapshot captured before the update.

### Notes
- v2.7.0 backlog items previously marked open (EAC validator FK fixture, demo_credentials test failures, v260c migration idempotence) are already resolved on `main` — confirmed via direct test run; tracker stale.

## [2.6.44] — 2026-05-02

### Security
- IDOR sweep batch 2 — 6 more modules patched. RFI, Submittals, Correspondence, Transmittals, Markups, Change Orders single-resource handlers (`GET/PATCH/DELETE /{id}`) now `verify_project_access` after fetching the resource, returning 404 for non-owners. 18 handlers total. Live cross-user check: admin gets 200, estimator gets 404 across rfi/submittals/correspondence/changeorders. AST anti-regression test extended from 32 → 68 parametrized assertions.

### Verified (no code change)
- `/api/v1/dashboards/presets` previously returned 500 in dev — root cause was missing local migrations `v2a0_compliance_dsl_rules` + `v2b0_preset_sync_columns` (committed in repo for v2.10/2.11 but never applied to dev DB). After `alembic upgrade head`, endpoint returns 200. Live probe of all 28 unique frontend `apiGet` paths against running v2.6.43 returns 200. Bulk-resolved 99 more stale findings in `qa-tests/improvements.json` (50 NotificationBell medium-sev + 49 silent-HTTP) — open count down from 707 to 552, with the remaining 552 all `performance`-category LCP improvement candidates rather than bugs.

## [2.6.43] — 2026-05-02

### Security
- IDOR sweep across 6 modules — single-resource handlers (`GET/PATCH/DELETE /{id}`) now call `verify_project_access(resource.project_id, user_id, session)` after fetching, returning 404 (not the resource) for non-owner non-admin users. Affected: NCR (3 endpoints), Inspections (3), Meetings (3), Punchlist items (3), Risk (3), Takeoff document delete (1) — 16 handlers total. Verified live: legit owner gets 200, cross-user request gets 404 "Project not found" (matches finance/erp_chat pattern).

### Fixed
- Export functions across 7 features (`contacts`, `tasks`, `fieldreports`, `rfi`, `costs`, `costs/import`, `finance`) used `body.detail || 'Export failed'` to surface the error — but FastAPI 422 returns `detail` as an array of objects, which JS coerces to `[object Object]` in the toast. Now route through `extractErrorMessageFromBody()` which flattens 422 arrays, handles plain-string bodies, and falls back to a status-coded message (`Export failed (HTTP 500)` etc.).
- QA-crawler nav-shape heuristic produced 43 false positives ("Open menu", project picker, Radix dropdown triggers) flagged as "did not navigate". Engine now reads `aria-haspopup` / `aria-controls` / `data-radix-collection-item` BEFORE clicking and skips the nav-shape rule for popup-trigger elements — these legitimately open overlays without changing the URL, and our overlay-detect window can briefly miss them.

### Added
- `backend/tests/unit/test_idor_router_guards.py` — AST-level anti-regression test that walks each protected handler and asserts both `session: SessionDep` accepted and `verify_project_access` called. Catches silent regressions where a refactor drops the IDOR guard without breaking the legit-owner happy path.

### Verified (no code change)
- v2.6.40-42 backend 500 sweep was effective end-to-end. Live probe of 40 distinct URLs from older QA-crawler journey logs (Search, NotificationBell unread-count, Switch Project, custom-units, system/status, fieldreports/summary, contacts/search, projects/dashboard, etc.) — all return 200/2xx with the demo token. Stale "high severity" findings in `qa-tests/improvements.json` are residue from pre-fix runs and have been bulk-resolved (76 silent-HTTP + 43 discoverability-FP + 1 IDOR fix = 120 items).

## [2.6.42] — 2026-05-02

### Fixed
- 12 more trailing-slash 404/422 endpoints across `/v1/collaboration/comments`, takeoff `save-to-project`, tasks/meetings/finance/fieldreports/inspections/RFI imports & exports, BOQ project-activity, and documents upload.
- `Costs > Import database` per-region delete button bypassed confirmation — destructive single-click that wiped a whole region's pricing data; now `window.confirm`-gated.
- `ChangeOrders` row-level delete and `PunchList` item delete and `Photos` batch delete now require explicit user confirmation before mutating.
- `FinancePage` EVM panel rendered KPI cards as `NaN` — the `/v1/finance/evm/` endpoint returns an envelope `{items, total}`, but the React Query was typed as a single `EVMData`. Now extracts `items[0]` (the latest snapshot) and `parseFloat`s every Decimal-as-string metric (BAC/PV/EV/AC/SPI/CPI/EAC/VAC/ETC/TCPI).
- `ReportingPage` stale-data race when switching projects mid-fetch — six parallel stat fetches (finance/safety/tasks/RFI/schedule/procurement) could resolve out of order and overwrite the current project's data with the previous project's responses. Generation-counter ref now discards in-flight responses from stale generations.

### Changed
- 8 more modals given WCAG `role="dialog"` + `aria-modal="true"` + `aria-labelledby` for screen readers and QA-crawler modal-detect heuristic: BOQ Manual Resource, BOQ Recalc/GAEB-export/Add-section, Catalog Build-assembly/Adjust-prices, BOQ Variables, Asset Edit.
- QA-crawler engine: post-click modal-detect timeout 400ms → 1000ms (was missing slow modals like Three.js Snapshot creator), and locale-switcher 401 noise suppressed in silent-http-error heuristic (bootstrap re-auth retries make these false positives).

### Added
- Unit tests for v2.6.40 anti-regressions: `test_documents_relative_path` (path-traversal containment), `test_database_pool_config` (SQLite pool sizing applied), `test_fieldreports` JSONB string-coercion + malformed-workforce resilience.
- Unit test pinning the `EVMListResponse` envelope shape and Decimal-as-string serialization contract — prevents the EVM endpoint from drifting back to a bare list (root cause of the FinancePage NaN bug).

## [2.6.41] — 2026-05-01

### Fixed
- 3 more trailing-slash 404/422 endpoints surfaced after the v2.6.40 sweep: `/v1/procurement/goods-receipts`, `/v1/contacts/search`, `/v1/fieldreports/reports` — frontend now hits the slashed form so the lists actually populate.
- `Delete Region` on `/catalog` ran without confirmation — destructive action wiped the entire region's resources on a single click. Now gated by `window.confirm`, matching the BOQ section-delete pattern.

### Changed
- `CreateResourceModal` (catalog) given proper `role="dialog"` + `aria-modal="true"` + `aria-labelledby` — was a bare div, invisible to screen readers and to the QA-crawler heuristic.

## [2.6.40] — 2026-05-01

### Fixed
- `NotificationBell` crashed every route with `displayItems.map is not a function` — backend returns `{items, total, unread_count}` but the React Query was typed as `Notification[]`.
- `CommandPalette` global search 404 + envelope mismatch — frontend now hits `/v1/search/?q=…` and reads `.hits[]` instead of treating the envelope as an array.
- `GET /api/v1/fieldreports/reports/summary/` returned 500 — JSONB workforce entries with stringy `count`/`hours` now coerced to float before arithmetic.
- `GET /api/v1/documents/{id}/download/` returned 403 on demo seed records — `file_path` stored as relative now resolves against `UPLOAD_BASE` instead of CWD, so the security containment check passes (file-not-found still returns a clean 404).
- Trailing-slash 404s on five endpoints called without slash before `?`: punchlist items, takeoff measurements, safety incidents (× 2), safety observations (× 2), markups stamp templates, sustainability EPD materials.
- `fetchTeamMembers` hit a non-existent `/v1/projects/{id}/members` endpoint; now falls back to `/v1/users/?limit=100` so the punch-list assignment dropdown actually populates.
- Duplicate React keys in `Changelog` for two adjacent v1.9.6 entries — key now combines version + date + array index.
- SQLAlchemy connection-pool exhaustion under concurrent load — SQLite path was silently using SQLAlchemy default `pool_size=5/overflow=10` (the configured 24/10 was Postgres-only). Now applied for both backends; 50-concurrent stress test is clean.

## [2.6.38] — 2026-05-01

### Changed
- `privacy-policy.html` and `terms.html` shipped with the local self-hosted app rewritten — now state explicitly that data stays on the operator's server, that DataDrivenConstruction is not Controller / Processor of project data, and list every outbound network call (AI APIs you configure, GitHub releases for converters / CWICR, PyPI for upgrades). The marketing-site versions at openconstructionerp.com keep their SaaS-style copy because that one *is* operated by us. Self-hosted vs demo distinction made unambiguous.

## [2.6.37] — 2026-05-01

### Added
- `oe_admin` module with `POST /api/v1/admin/qa-reset` for QA-pipeline / crawler reset of the demo dataset. Triple-gated: `QA_RESET_ENABLED=1` env var + matching `QA_RESET_TOKEN` body + tenant must equal `"demo"`. Off by default; nothing fires in production unless an operator explicitly opts in.

### Fixed
- Variant resource prefix (`price_abstract_resource_common_start`) shown in From-Database modal results. Variant items now render the abstract base name as primary line and the rate-code description as a smaller subtitle, so estimators scan rows by material instead of CWICR codes.
- Resource row self-heals legacy stored names that lost the `common_start` prefix — when `composedVariantName` extends `storedName` with the abstract base, prefer the composed form. Catches rows the v2.6.30 backfill missed without a round-trip.

### Changed
- `/costs` page initial render sized for fast first paint: `PAGE_SIZE` 20 → 10, `staleTime` 5 min on regions / stats / categories so quick navigation away-and-back no longer re-fires aggregates.
- BOQ "From Database" modal first paint within ~150 ms: search query fetches 15 items (was 50) with IntersectionObserver auto-loading the rest as the user scrolls.
- Resource rows visually nest under their parent position — slightly deeper background + inset top-shadow makes sub-positions read as sub-positions, not standalone rows.
- Backend `/v1/costs/category-tree/` accepts `depth` (1..4) and `parent_path` for future lazy-tree expansion. Default behavior unchanged (depth=4, full tree).

### i18n
- 24 languages bulk-translated in `i18n-fallbacks.ts` via parallel-agent pipeline (`scripts/i18n_extract.py` + `scripts/i18n_apply.py`): ~28,000 keys across `ar/bg/cs/da/de/es/fi/fr/hi/hr/id/it/ja/ko/nl/no/pl/pt/ro/ru/sv/tr/vi/zh`. Missing-key + English-bleed detector finds rows that were silently English; agents fill them in chunks; merge step rewrites the file in one pass. `th` deferred to next release.
- Marketing site `id` / `th` gap-filled: same-as-EN strings reduced from 349/431 to 56/56 (only proper nouns / codes remain).
- Vietnamese backend + marketing translations completed in wave 2.

## [2.6.36] — 2026-04-30

### Added
- 5 new UI languages: Croatian (`hr`), Indonesian (`id`), Romanian (`ro`), Thai (`th`), Vietnamese (`vi`). Frontend `SUPPORTED_LANGUAGES` now 26. Backend + marketing locales aligned (`hi` was missing from backend, `bg`+`hi` from marketing — added).

### Fixed
- `backend/pyproject.toml` version was out of lockstep with `frontend/package.json` and `CHANGELOG.md` in v2.6.35 (committed at 2.6.34; PyPI build patched it). Lockstep restored at v2.6.36.
- `backend/locales/` removed from `.gitignore` — new UI-language stubs were silently dropped from git on v2.6.35. Tracked baselines so source-added langs ship in releases.

## [2.6.35] — 2026-04-30

### Fixed
- Quantity edit no longer snaps back to old value after ~1s. FormulaCellEditor passes `cancel=true` to `stopEditing` after `setDataValue`, suppressing AG Grid's secondary commit from a doubly-mounted StrictMode editor.
- Variant resource name no longer carries rate-code description as prefix bleed. Apply path uses `full_label → common_start + label → label → baseDescription`. `backend/scripts/backfill_variant_prefix.py` rewrites already-stamped names.
- Unit dropdown commits via mouse click again (third recurrence). Capture-phase document-mousedown shield was halting dispatch before React's `onMouseDown<li>`. Replaced with native `<ul>` listener reading `data-unit-value`.
- Resource rows use the same portaled-dropdown unit editor as position rows.
- Multi-variant per position: each variant component gets its own picker pill — `available_variants` forwarded for ALL components on apply, not just the first.
- `/costs/import` Installed Databases section reappears under empty/loading/error states; uninstall buttons restored.
- Quantity save instant: PATCH response splices into cache (no full BOQ refetch). Sibling rollups debounced 400ms.
- Revit `.rvt` upload no longer fails on `BIMHubService.create_model() got an unexpected keyword argument 'created_by'`.

### Added
- "Report a bug" entry in user menu — pre-filled GitHub issue with anonymized last error, app version, page, build hash.
- BOQ position description shows inline (i) icon when source cost item has `scope_of_work`; click opens portaled bullet-list popover.
- `/costs` variant detail compacted: inline stat strip + clamp top-8 with "Show all N" toggle (~1700px → ~250px).
- VariantPicker accordion when ≥2 groups, flat list for 1.

## [2.6.34] — 2026-04-30

### Added
- CWICR loader now imports per-component variant catalogs. Each abstract resource row inside a rate is preserved as its own resource with `available_variants` + `available_variant_stats` stamped on the component itself. Rates like `KANE_RINE_KAKARI_KARI` now arrive with all 3 variant resources (formwork / panels / boards), each with its own picker — previously only the first row survived and the other two were silently dropped.
- CWICR loader now imports `metadata.scope_of_work` — the ordered list of work steps (`Состав работ` / `Scope of work` / `Arbeitsumfang` / `Composition des travaux`). Verified universal across all 30 regions in the catalog.

### Fixed
- Variant builder falls back to `..._all_values_per_unit` when `..._all_values` is empty, recovering catalogs for rate rows that only populate per-unit pricing (~4,800 rates per region).
- Scope-of-work detector no longer relies on the `is_scope` flag (which is False in DE/FR exports) — uses `work_composition_text` non-empty + `resource_name` empty as the universal rule.

### Changed
- CWICR loader runs in no-cache mode: each `POST /load-cwicr/{db_id}` re-downloads the parquet from GitHub and deletes it in `finally` after processing. `~/.openestimator/cache/` is no longer consulted on lookup and stays empty between runs. Locally-installed DDC_Toolkit parquets (Priority 1) are still used and left untouched.

## [2.6.33] — 2026-04-30

### Fixed
- Variant resource qty / rate edits now contribute to the position's unit_rate sum. The synthetic VARIANT row materializes the variant as a real entry in `metadata.resources[]` on first edit, so it participates in `Σ(r.qty × r.rate)` like every other resource. After the first edit the row renders as a regular resource line with its own ▾ re-pick pill.
- Unit dropdown pick is no longer dropped by AG Grid 32's outside-click detector. The dropdown is portaled to `<body>`, so AG Grid's *native* document-level mousedown handler used to fire `stopEditing(true)` (cancel) before the React `onClick` could commit. Added `nativeEvent.stopImmediatePropagation()` on both UL and LI mouse events so the pick wins the race.

### Changed
- V-badge on positions with variant resources now toggles the resource panel (expand / collapse) instead of opening the variant picker. Picker access stays on the synthetic VARIANT row's "Variant" chip and on the per-resource ▾ pill in the expanded panel.

## [2.6.32] — 2026-04-30

### Fixed
- Variant resource header no longer mirrors `position.quantity` for legacy positions. The synthetic header now defaults to `1` (per-unit norm) when `metadata.variant.quantity` is unset, so editing position qty never touches the variant resource qty visually or in storage.

### Added
- Per-resource variant pickers when a position carries multiple variant resources. `available_variants` + `available_variant_stats` now persist on every variant resource at add-time, so each resource gets its own re-pick pill in the expanded panel; the position-level synthetic header is suppressed when one or more resources carry their own variant catalog.

## [2.6.31] — 2026-04-30

### Changed
- "All databases" tab removed from the cost-database picker. Only country-specific DB tabs render now.

### Fixed
- Unit cell editor: picking a unit from the dropdown now actually commits the value. AG Grid 32's outside-click detector was cancelling the edit before `pick()` could run because the dropdown is portaled to `<body>`. `stopPropagation` on the dropdown's `mouseDown`, plus a synchronous `mouseDown` commit on each list item, keeps the pick alive.

## [2.6.30] — 2026-04-29

### Changed
- Cost-database modal: country DBs lead the region tabs row, "All databases" pushed to the end.
- Variant resource quantity is now stored at `metadata.variant.quantity` and decoupled from `position.quantity` — editing one no longer changes the other.

### Added
- Paginated "From Database" search (cursor + 50/page) and a category tree sidebar backed by `GET /api/v1/costs/category-tree/` (5-min cache).
- Calculated custom-column type with formula textarea, Test button, and live re-eval (Phase E).
- Autocomplete tooltip for Description column (Phase F).

## [2.6.29] — 2026-04-29

### Added
- **BOQ formula engine — cross-position references, named variables, conditionals, unit conversions, cycle detection.** Phase C of `inherited-knitting-dahl` plan. The hand-written CSP-safe parser at `frontend/src/features/boq/grid/cellEditors.tsx` now accepts `pos("01.02.003").qty / .rate / .total`, `section("Concrete").total`, `col("MyCol")` (in calculated columns), `$GFA` style variables, comparison ops (`<`, `>`, `<=`, `>=`, `==`, `!=`), `if(cond, a, b)` short-circuit, 8 unit converters (`m_to_ft`, `ft_to_m`, `m2_to_ft2`, `ft2_to_m2`, `m3_to_yd3`, `yd3_to_m3`, `kg_to_lb`, `lb_to_kg`), and `round_up(x, n)` / `round_down(x, n)`. Cycle detection ports the visited-set DFS pattern from `service.py` to TypeScript via Tarjan's SCC; warn-and-allow policy — cycle participants render a yellow ⚠ marker, computed value 0, full cycle path in tooltip, save NOT blocked. Live re-eval orchestrator with 200ms debounce coalesces qty/rate/variable changes. Backwards-compat preserved: `evaluateFormula(input)` legacy single-arg signature unchanged. New `frontend/src/features/boq/grid/formula/` directory; 68/68 vitest cases (engine, cycle detection, cross-position).
- **BIM model persistence** — uploaded BIM models stay viewable after revisit. New `keep_original_cad: bool = False` setting in `backend/app/config.py`; conversion artefacts (canonical JSON, GLB, thumbnails) persist forever, originals are deleted after successful conversion when `keep_original_cad=False` (default) or kept when set to `True`. Failed conversions keep originals so user can retry. `GET /api/v1/bim_hub/models/` enriched with `conversion_artifact_size_mb`, `has_original`, `error_code`, plus aggregate `total_artifact_size_mb` / `total_original_size_mb` / `storage_root_label`. New `DiskUsageChip` in BIM page header surfaces data root + total artefact size with hover tooltip. 4 new pytest integration cases.
- **CWICR cost-database localisation across 16 locales.** New `backend/app/modules/costs/translations/` directory with locale dicts for de, en, ro, bg, sv, it, nl, pl, cs, hr, tr, id, ja, ko, th, vi. RO/BG/SV fully populated; rest cover units + common construction materials with high-confidence terms. `costs/router.py` accepts `?locale=ro` query param or `Accept-Language` header and emits `*_localized` mirror keys (`category_localized`, `unit_localized`, `group_localized`) — originals always preserved as fallback. `shared/lib/api.ts` auto-forwards `Accept-Language` from `i18next.language`. Backfill script at `backend/scripts/translate_cwicr_columns.py` writes localised mirrors into the SQLite cache idempotently. 42 backend + 7 frontend tests; verified RO_BUCHAREST / BG_SOFIA / SV_STOCKHOLM produce non-German values for `BAUARBEITEN` → `LUCRĂRI DE CONSTRUCȚII` / `СТРОИТЕЛНИ РАБОТИ` / `BYGGNADSARBETEN`.
- **Resource-row variant re-picker.** v2.6.25 added per-resource variant snapshots; v2.6.29 lets the user re-pick variants on already-added resource rows. New `PATCH /api/v1/boq/positions/{id}/resources/{idx}/variant/` endpoint re-uses `_stamp_resource_variant_snapshots` for idempotent sibling preservation; recomputes position-level `unit_rate` from the per-unit subtotal sum; emits `boq.position.updated` with `kind=resource_variant_repick`. Frontend `EditableResourceRow` shows a small `▾ N` pill on every resource with `available_variants` cached at add-time, opens the existing `VariantPicker` preselected on the current pick. 4px left-edge provenance bar (blue=explicit pick, amber=default-from-mean, none=plain). Backwards-compat: legacy resources without `available_variants` degrade gracefully. 13 unit + 5 integration + 9 vitest tests.
- **Resource type chips i18n across all 21 locales.** Resource-type labels (labor / material / equipment / operator / subcontractor / electricity / composite / other) now flow through `getResourceTypeLabel(type, t)` in three render sites (`CatalogPickerModal`, `ResourceSummary`, `CatalogPage`). 168 new translation entries (8 keys × 21 locales) with construction-industry vocabulary per locale (de: Bediener / Energie; ru: Машинист / Электроэнергия; fr: Opérateur / Électricité; ja: オペレーター / 電力; etc.). 217-assertion vitest spec covering canonical list shape, fallback when no `t` supplied, every-locale-has-every-key contract, integration with live i18next.

### Fixed
- **GAEB import / export — 8 concrete fixes uncovered by deep audit.**
  - Encoding sniff on import: `decodeXmlBuffer()` now reads the `<?xml encoding=...?>` prolog and uses the matching `TextDecoder`. Legacy DACH GAEB files in ISO-8859-1/Windows-1252 no longer corrupt ä/ö/ü/ß into `U+FFFD`.
  - Unit codes: `GAEB_UNIT_CODES` map translates internal canonical units (`m2`/`m3`/`pcs`/`lsum`/`hr`) to GAEB DA short codes (`m²`/`m³`/`Stk`/`psch`/`Std`) on export, with reverse map on import. RIB iTWO / Sirados / ORCA round-trip works.
  - Hierarchy: `buildSectionTree()` walks dotted ordinals and creates arbitrarily-deep section nodes with recursive `renderSection()`. Multi-level Los → Titel → Position structures no longer flatten on export.
  - Line breaks: import-side `normaliseRunWhitespace()` collapses only horizontal whitespace, preserves `\n`. Export emits one `<Text>` per paragraph instead of one blob.
  - Version & namespace: emits spec-compliant `<VersMajor>3</VersMajor><VersMinor>3</VersMinor>` (was non-standard `<Version>3.3</Version>`); namespace correctly uses `DA81` for X81, `DA83` for X83 etc.
  - ShortText: first paragraph only, no ellipsis (was multi-line + `...` which many AVA readers display verbatim).
  - Filename: `<projectName>-<boqName>.<ext>` (was `<boqName>.<ext>`).
  15 new regression tests; 45/45 GAEB tests pass (was 30/30); tsc clean. No new dependencies, no backend changes (GAEB I/O is client-side TypeScript).
- **VariantPicker currency falls back to region currency, not USD.** `BOQModals.tsx` chain was `item.currency || 'USD'`; for abstract-resource cost items with empty `item.currency` (despite real-currency variant prices in EUR/BGN/RON/SEK/JPY), this rendered `$ 1,200` on Bulgarian / Swedish / Japanese rows. Now extends with `REGION_MAP[item.region]?.currency` between the item value and USD-as-last-resort. So `BG_SOFIA` shows BGN, `RO_BUCHAREST` shows RON, `SV_STOCKHOLM` shows SEK.
- **BUG-LANG-AUTODETECT — wizard's Get Started button now writes `oe_lang_explicit=1`.** The auto-detect useEffect (added earlier in this version cycle) only re-detects from `navigator.language` when `oe_lang_explicit` is unset. Previously a US-Windows admin landed in Polish UI just because someone else had demoed the build in Polish on the same machine and left a stale `i18nextLng` value.
- **BUG-AUTO-PROJECT-SELECT — `/bim` cold open now pins resolved project into `useProjectContextStore`.** When `urlProjectId` and `contextProjectId` are both empty, `BIMPage` falls back to `projectsList[0]` for the models query, but never wrote that pick into the global store. Other pages (recents, breadcrumb, BOQ landing, upload dialogs) read `activeProjectId` from the store and decided "no active project" → dimmed CTA / kicked back to picker. Now we pin the resolved fallback into the store the first time we resolve one, only when nothing else has set it (never overrides explicit picks).
- **BUG-DUAL-UPLOAD-PDF — TakeoffPage no longer re-uploads the same PDF to `/api/v1/documents/upload`.** The `uploadMutation` `onSuccess` used to fire `createDocumentRecord(file)` for "cross-referencing", which doubled bytes-on-disk and produced two identical entries in the Documents module. Removed entirely. If a takeoff doc needs to surface in the Documents module, do it backend-side at upload time via FK, not by sending the file twice.

## [2.6.28] — 2026-04-29

### Fixed
- **BUG-RVT01 · CRITICAL — every native CAD upload crashed pre-flight with `ValueError: stdin and input arguments may not both be used`.** `backend/app/modules/boq/cad_import.py:275` passed both `stdin=subprocess.PIPE` and `input=b"\n"` to `subprocess.run`; Python forbids the combination because `input=` already implicitly sets `stdin=PIPE`. Pre-flight check fired on every RVT / IFC / DGN / DWG upload through `BIMHubService` and pinned models at `error_code=ddc_smoke_failed` even when the binary was correctly installed. Removed the explicit `stdin=PIPE`. Smoke test now runs: `smoke_test_converter('rvt')` → `{status: ok}`, `smoke_test_converter('ifc')` → `{status: ok}`.
- **BUG-RVT02 · log/response inconsistency on install-time smoke timeout.** When the install endpoint at `backend/app/modules/takeoff/router.py:614-623` hit the 15-second timeout (binary loaded fine and is sitting in a Qt message loop — the design-intent "healthy" path), the catch-all exception handler emitted `WARNING Smoke test for X converter failed: ...` while the response correctly reported `smoke_test_passed: true`. Split into an explicit `TimeoutExpired` branch (logs at INFO, "binary loaded but waiting for stdin; treating as healthy") and a real-failure branch that now correctly flips `smoke_ok = False` and surfaces a useful `message` instead of relying on the default-true initial value.
- **BUG-RVT03/04 · `converter_required` upload now persists the file and returns 202 Accepted.** Before: `POST /api/v1/bim_hub/upload-cad/` with no converter installed returned HTTP 201 with `model_id: null` and `file_size: 0` — the file was silently discarded and the user had to re-upload after install. Now: the file lands at `data/bim/{project_id}/{model_id}/original.{ext}` exactly like a normal upload, a `BIMModel` row is created with `status="needs_converter"` so the user can `Re-process` from the UI after installing, and the response is 202 Accepted with `Retry-After: 60` and a `Link` header pointing at both the install endpoint and the model's `/retry/` endpoint. HTTP semantic correctness restored: 201 means "resource created", 202 means "request accepted, will be processed".
- **Unit validator: sanitise, don't gate.** The strict 36-entry allowlist that 422'd anything outside the curated catalogue produced a steady stream of "unit 'X' is not in the approved BOQ unit catalogue" failures every time a regional CWICR import landed: Romanian `Bucat`, Bulgarian `бр`, Russian `шт`, German `Stück`, French `unité`, plus per-trade slang (`man-day`, `lin.m`, `MWh`, `kg/m`, `%`). Replaced with a permissive sanitiser at `backend/app/modules/boq/units.py`: any 1–30 character string starting with a letter (any Unicode script — Latin, Cyrillic, Greek, CJK, accented) or a digit (multi-prefix forms) or `%` (percentage) passes through, lowercased and stripped. Common synonyms (`ton`/`tonne`/`tonnes` → `t`, `hour`/`hours`/`h` → `hr`, `metre`/`metres` → `m`) still canonicalise via the alias map so unit-breakdown stats don't fragment. Genuinely unsafe shapes (HTML / SQL / shell / quote / control characters, > 30 chars, non-letter / non-digit / non-`%` leading char) still 422 with a clear message naming the actual constraint instead of dumping the full catalogue. Alias precedence flipped so synonyms collapse first, fixing the original BUG-MATH03 complaint that "hour" and "hr" produced separate buckets. 98 new pytest cases (canonical round-trip, alias canonicalisation, every locale spelling above, multi-prefix forms, malicious-input rejection). Existing integration test updated: "xyz" is now an accepted custom unit; HTML payloads remain rejected.

## [2.6.27] — 2026-04-28

### Fixed
- **Flags missing on Windows for 10 CWICR regions** — Australia, New Zealand, Croatia, Romania, Thailand, Vietnam, Indonesia, Mexico, South Africa, Nigeria all rendered as literal "AU"/"NZ"/etc. text on Windows because Win10/Win11 have no native flag-emoji glyphs in any system font. The emoji-only fallback added in v2.6.23 worked on Mac/Linux but not Windows. Replaced with real inline SVG flags for all 10 — guaranteed to render on every platform. SVG designs are simplified but recognisable at 14–32 px sizes.
- **CWICR download error message was useless** — "CWICR database 'RO_BUCHAREST' not found. Install DDC_Toolkit…or check your internet connection" gave the user no signal whether the issue was a stale backend (no mapping for the new 19 regions in v2.6.22-), a partial cached file stuck at <1 KB, a network failure, or an upstream 404. Loader now records the last download failure per `db_id` and surfaces it through the 404 response: "backend has no GitHub mapping" / "returned 0 bytes (likely 404)" / "{ExceptionType}: {message}. URL: …". Partial-cache leftovers are auto-discarded so the next attempt gets a clean slot.

## [2.6.26] — 2026-04-28

### Fixed
- **Unit "ton" rejected on CWICR add** — "Failed to add positions, unit 'ton' is not in the approved BOQ unit catalogue". Added a canonical alias map: `ton`/`tons`/`tonne`/`tonnes`/`mt` → `t`, `metre`/`metres`/`meter`/`meters` → `m`, `sqm`/`sq.m`/`cum`/`cu.m` → `m2`/`m3`, `each`/`piece(s)` → `ea`/`pcs`, `lump sum`/`lumpsum` → `lsum`, `hours`/`week`/`days`/`mo` → canonical forms. Aggregations stay coherent (everything buckets into the canonical unit) without rejecting common spellings.
- **Country flags missing on cost-database regions** — `<CountryFlag code="DE_BERLIN" />` returned null because the lookup used the full lowercased key. The component now extracts the country prefix from region keys (`DE_BERLIN` → `de`, `AU_SYDNEY` → `au`) and maps non-ISO prefixes (`USA_USD` → `us`, `ENG_TORONTO` → `ca`, `SP_BARCELONA` → `es`, `PT_SAOPAULO` → `br`, `AR_DUBAI` → `ae`, `ZH_SHANGHAI` → `cn`, `HI_MUMBAI` → `in`, `CS_PRAGUE` → `cz`, `JA_TOKYO` → `jp`, `KO_SEOUL` → `kr`, `SV_STOCKHOLM` → `se`, `VI_HANOI` → `vn`) so all 30 CWICR regions render with proper flags everywhere.
- **BIM converter status panel could not be dismissed on /bim** — `BIMPage` mounted the banner without `dismissible`, so the X button was never rendered. Now passed; banner can be closed and the dismissed flag persists in localStorage.
- **Re-check: "Operation failed Not Found"** — the verify endpoint (`POST /v1/takeoff/converters/{id}/verify/`) only landed in v2.6.23. When users on stale backends click Re-check, the 404 now surfaces a clear "Backend version too old, run `pip install --upgrade openconstructionerp`" toast instead of a bare error.

## [2.6.25] — 2026-04-28

### Added
- **Per-resource CWICR variants on multi-resource positions.** When a position is composed of more than one variant-bearing resource (e.g. concrete C30 + rebar 8mm), each resource entry now keeps its own immutable `variant_snapshot`. The "Add resource from cost database" flow opens the variant picker first, the picked rate lands on the resource entry, and the backend's new `_stamp_resource_variant_snapshots` walks `metadata.resources[]` independently so a later cost-DB re-import cannot silently rewrite any one of them. 4 new pytest cases (per-resource stamp, mixed variant + variant_default + plain, idempotent no-op patch, switch one resource without disturbing the other).

### Changed
- **VariantPicker UX redesign.** Width 360 → 520px so full descriptions are visible with `line-clamp-3` instead of single-line truncation. Stats banner now shows Min / Avg / Median / Max (Avg added). Search input visible at ≥6 variants. Sort dropdown: default / price asc / price desc / label A→Z. Per-row delta-vs-mean chip (`+N%` amber, `-N%` emerald, `≈ avg` gray) so price spread reads at a glance. Selected row highlighted with `ring-1 ring-inset`. Empty state on filter miss. All 8 existing contract tests still green.

## [2.6.24] — 2026-04-28

### Fixed
- **RBAC: viewers / demo users can now add BOQ positions.** `boq.update` lowered to VIEWER; `boq.create` was already at VIEWER, so the original gate was inconsistent (start a BOQ, can't fill it).
- 10 new CWICR cost-database regions (au, hr, id, mx, ng, nz, ro, th, vn, za) now show their flag in onboarding and `/costs/import`.
- Cost-database search modal: when no database is imported, surface a "Import a database" CTA pointing at `/costs/import` instead of a generic "no results" line.

### Added
- **BOQ preset library 8→14** with regional grouping. Universal: Procurement / Notes / Quality / Sustainability / Status & Scope / Tendering / Schedule. Regional (collapsible): GAEB-AVA, ÖNORM-BRZ, USA CSI MasterFormat, Australia AIQS, Brazil SINAPI, UK NRM2, BIM Integration. Plan: `inherited-knitting-dahl.md` Phase A.
- **Per-BOQ named variables** ($GFA, $LABOR_RATE …). Backend: `BOQVariable` schema + `GET/PUT /v1/boq/boqs/{id}/variables/`, capped at 50 vars, UPPER_SNAKE_CASE regex, type coercion. Frontend: `BOQVariablesDialog` mounted from Grid Settings dropdown with table editor (name/type/value/description). Plan Phase B; will feed into formula engine in Phase C.
- 16 new vitest cases for the preset registry (form + backwards-compat for legacy ids); 10 new pytest integration cases for the variables endpoint (round-trip, validation, cap, replace-semantics, type coercion).

## [2.6.23] — 2026-04-28

### Added
- **CWICR cost database expanded from 11 → 30 regions.** DDC repo grew with 19 new countries (AU, NZ, IT, NL, PL, CS, HR, BG, RO, SV, TR, JA, KO, TH, VI, ID, MX, ZA, NG); registry, REGION_MAP, DatabaseSetupPage, ImportDatabasePage, OnboardingWizard all updated. Onboarding region grid grouped by region (Anglosphere / Western Europe / CEE / MENA / APAC / Americas) with a search filter so 30 entries don't dominate the step. `LANG_TO_REGION` updated so `it`→`IT_ROME`, `ja`→`JA_TOKYO`, `ko`→`KO_SEOUL`, `nl`→`NL_AMSTERDAM`, `pl`→`PL_WARSAW`, etc. — previously these locales fell back to DE/SP/ZH approximations.
- **BIM converter health check + smoke test.** `GET /v1/takeoff/converters/?verify=true` now runs an 8s smoke test per installed converter (parallel via `asyncio.gather`) to catch DLL load failures, Mark-of-the-Web blocking, missing VC++ Redistributable, wrong-arch binaries. New `POST /v1/takeoff/converters/{id}/verify/` for on-demand re-check. Result cached 5 min server-side; cache invalidated on install/uninstall. Pre-flight smoke test added to RVT background processor so a broken-but-installed binary fails fast with a structured error instead of a 5-minute conversion that produces nothing.
- **BIM converter status panel rewrite.** Always visible on `/bim` (was hidden when all installed); shows `health` per converter with ✓ Working / ⚠ Broken / ⬇ Not installed pills, install path on hover, Re-check button on every installed row, action buttons mapped from backend's `suggested_actions` (Install / Reinstall / Install VC++ Redist / Manual install on GitHub / Unblock files / Run as Administrator). IFC now included (was previously omitted, which is why "Revit and IFC don't load" was reproducible). Dismissible mode added; mounted on `/projects` empty state so fresh-install users see converter status before creating their first project.
- **Abstract resource variants polished to ship-quality.** Default = mean rate when applying a CWICR cost item with multiple price variants (closest-to-mean entry chosen when no exact match). Inline variant picker (`▾ N options`) on every BOQ unit_rate cell; opens the same `VariantPicker` used at apply time. Position metadata stamps a `variant_snapshot = {code, rate, currency, captured_at}` so subsequent CWICR re-imports don't silently rewrite the position's rate. Visual markers: 4px left-edge bar (blue for explicit pick, amber for default = mean) plus an Abstract pill in the description cell. Excel export gains a "Variant" column. 6 backend tests + 8 frontend tests; all green.

### Fixed
- **VPS source-dir shadowed wheel for ALL modules, not just `_frontend_dist`.** The systemd `WorkingDirectory=/root/OpenConstructionERP/backend` puts the source `app/` tree ahead of the installed wheel on `sys.path`, so every Python module updated in a new wheel was silently shadowed by the old source. Caught when the v2.6.22 demo-login route returned 404 despite the wheel containing it. Deploy procedure now rsyncs the entire wheel `app/` over `backend/app/` after every `pip install`.
- **BOQ cell edits jumped back to old value before re-updating** (lag bug at `/boq/{id}`). The `updateMutation` in `BOQEditorPage.tsx` performed an optimistic `setQueryData` write but didn't `cancelQueries` on the in-flight refetch issued by sibling mutations (add/reorder/catalog/etc.) — so the GET landed AFTER the optimistic write, clobbered the cache with stale server data, and the new value reappeared only when the PATCH eventually returned. Added `await queryClient.cancelQueries({ queryKey: ['boq', boqId] })` in `onMutate`, snapshot+rollback in `onError`, invalidation moved from `onSuccess` to `onSettled` (fires once per mutation). Cell edits now feel instant.

## [2.6.22] — 2026-04-28

### Fixed
- **"Demo login failed. Please try again." on every fresh install.** The seeder in `app.main._seed_demo_account` generates a fresh `secrets.token_urlsafe(16)` per install (BUG-D01 — no hardcoded credential is shipped) and persists it to a 0600 credentials file, but the frontend's "Demo login" button hard-codes `DemoPass1234!`. So login → 401, auto-register → 409 "already registered", user → "Demo login failed". Added a dedicated `POST /api/v1/users/auth/demo-login/` endpoint that mints tokens for whitelisted seeded accounts without a password check (gated by `SEED_DEMO=true`, rate-limited per IP). Frontend now hits this endpoint; falls back to the legacy login+register pair against pre-v2.6.22 servers so deployments don't break the moment the new client ships.
- **3D viewer stuck silently when CAD conversion fails (Hans's report).** The non-ready overlay now renders the backend's `error_message` directly so users see *why* their model didn't render — "RVT converter not installed", "RVT version newer than the converter", "No elements extracted from this IFC file" — instead of a generic "Error" placeholder. Background processor populates a structured `metadata.error_code` (`ddc_not_found` / `ddc_failed` / `zero_elements` / `unexpected`) so the UI can dispatch on it.
- **DWG/DGN converter install showed "Internal server error"** instead of the actual reason. The `POST /api/v1/takeoff/converters/{id}/install/` endpoint only translated `RuntimeError` to a 502 — any other exception (rate-limited GitHub API, JSON decode error, OS permission denied) leaked as a generic 500. Wrapped the whole handler in a top-level `except` that returns 502 with `{exception_class}: {message}` so the install banner displays the real cause and a manual-install link.
- **Linux install attempts shown as failures.** When the backend returned the structured `platform_unsupported: true` body with apt-install instructions, the banner mutation treated `installed: false` as "success", flashing "Installed" toast text. Now the toast branches on `result.installed`: success, info+long-duration on Linux (with the apt commands), warning on smoke-test failure, error on network failure. `InstallConverterPrompt` mirrors the same logic and refuses to auto-retry the upload when the install didn't actually succeed.

### Added
- **Retry button on the BIM viewer error overlay** — re-runs background DDC conversion for a previously failed model via new `POST /api/v1/bim_hub/{model_id}/retry/` endpoint. Useful after the user installs a missing converter (the "Install converter" button on the overlay auto-retries on success), or when the original failure was transient (network blip, OOM during a parallel upload burst).
- **Pre-flight converter check before RVT processing.** `_process_cad_in_background` now verifies the RVT converter is installed up front and returns `status="needs_converter"` with a specific install link, instead of letting the pipeline run to the generic "no elements extracted" message.
- **Post-install smoke test for the Windows DDC converter.** After downloading binaries from GitHub, `POST /api/v1/takeoff/converters/{id}/install/` launches the binary once with a 15s timeout to catch missing-DLL errors (`STATUS_DLL_NOT_FOUND`, `STATUS_DLL_INIT_FAILED`). Failures surface immediately with re-install instructions instead of the user discovering the problem on their next CAD upload.

## [2.6.21] — 2026-04-28

### Added
- **Custom unit catalogue persists per-user across browsers and sessions.** Units typed into the BOQ Unit cell now sync to `User.metadata_["custom_units"]` via two new endpoints (`GET`/`PATCH /api/v1/users/me/custom-units/`). Previously the catalogue lived only in `localStorage`, so a unit added on one device was invisible everywhere else. App boot calls `syncCustomUnitsFromServer()` once after auth resolves; commits push to the server fire-and-forget. Anonymous / offline sessions fall back to localStorage cleanly.

### Fixed
- **Resource name reverts to old value on first edit.** Renaming a catalogued resource fired two sequential `onUpdateResource` calls (`name`, then `code: ''`). Both read the same React Query cache snapshot, and the second mutation overwrote the first — so the new name was visibly written and immediately reset to the original. Symptom: "name only saves on the second click." Fixed by collapsing the two writes into a single `onUpdateResourceFields(posId, idx, {name, code: ''})` mutation.
- **Resource name X-coordinate matches position description.** Removed the `pl-4` indent added in v2.6.20 — `InlineTextInput`'s built-in `px-1` already matches the position description column's `!pl-1`, so resource names and position names sit on the exact same vertical line.

## [2.6.20] — 2026-04-28

### Fixed
- **Issue #103 — Gemini API model out-of-date.** Default model bumped `gemini-2.0-flash` → `gemini-2.5-flash` so Test Connection in Settings → Configuration succeeds again.
- **IFC viewer rendered all-black.** When a converted IFC ships without `IfcSurfaceStyle`, DDC's DAE export writes `<color>0 0 0 1</color>`; trimesh preserves it into the GLB and the model was rendering as a flat black silhouette. Detect near-black albedo (Rec.601 luma < 0.04) per mesh and substitute the discipline-coloured `MeshStandardMaterial` instead. Original material is still cached on `userData.originalMaterial` so reset/colorBy modes are unchanged.
- **BOQ alignment — 28px shift between position values and resource values.** The position grid has a 28px-wide visible `_bim_qty` column between `unit` and `quantity`; the resource row jumped directly from unit to qty, pushing every resource numeric (qty / rate / total / actions) 28px LEFT of its position counterpart. Added an aria-hidden 28px spacer slot (and a classification spacer for the case where that hidden column is toggled on) so right edges line up exactly.

### Added
- **Formula support on resource quantities** (Issue #90 follow-up). Resource qty / rate inline inputs now recognise the same Excel-style syntax as the position quantity editor: `=2*PI()*3`, `12.5 x 4`, `=sqrt(144)`. Live `= …` preview pops below the input while typing; on commit the evaluated number is written, errors leave the value unchanged. Pure numeric input continues through the existing path with no behaviour change.

### Changed
- **Quantity formula popup editor — sized for readability.** Fixed dimensions 180px × 32px (was the cell's 110px × ~24px), text size lifted from xs to sm. The popup no longer balloons rightward into the Unit Rate column when a long expression is typed.

## [2.6.19] — 2026-04-28

### Fixed
- **Resource name vs position description X-alignment** — `InlineTextInput`'s display-mode span already adds `px-1` (4px) of horizontal padding internally. The resource name slot was *also* applying its own `pl-1`, double-padding to 8px while the position description column padding is only 4px (`!pl-1`). Removed the outer `pl-1` so the input span's own 4px is the single source of truth — resource names now start at the exact same X coordinate as position description text.
- **Resource quantity vs position quantity X-alignment** — same double-padding bug on numeric slots. `InlineNumberInput`'s display span adds `px-1` (4px), and the qty slot had `pr-2` (8px), totalling 12px from slot right-edge to text right-edge while the position quantity cell uses only 8px (`!pr-2`). Resource qty slot reduced to `pr-1 pl-1` (4px) so combined with the input's 4px it sums to 8px, matching the position cell exactly.

## [2.6.18] — 2026-04-28

### Fixed
- **BOQ resource calculation model — corrected to per-unit norms** (CostX / Candy / iTWO / ProEst convention). Resources are now stored as quantities-per-1-unit-of-position. Position `unit_rate = Σ(r.quantity × r.unit_rate)` (no division by qty). Position `total = quantity × unit_rate`. Changing position quantity no longer scales resource quantities or recomputes unit_rate — only the total scales. Three sites fixed:
  - `frontend/.../BOQGrid.tsx` `onCellValueChanged`: removed proportional resource scaling on qty edit.
  - `frontend/.../BOQEditorPage.tsx` `handleUpdateResource`: dropped `/ posQty` divisor.
  - `backend/.../service.py` `update_position`: only `triggered_by_resources` (not `triggered_by_qty`) recomputes unit_rate; formula is `sum`, no division.

### Changed
- **BOQ row alignment** — position cells and resource sub-rows now share an identical column grid:
  - Resource left section restructured to mirror AG Grid columns 1:1 (code slot = ordinal column width, tag slot = bim_link column width, name slot = description column).
  - `--ag-cell-horizontal-padding` 16px → 8px globally so AG Grid cells and resource slots use the same padding; right-edges of qty / unit_rate / total line up across positions and resources.
  - Resource font sizes 11px → 12px to match position `text-xs`.
  - Position ordinal made `text-right` so its right edge aligns with the resource code right edge.
  - Resource catalogue code: full code visible (no truncation), 8px font, fixed 100px right-aligned slot.
  - Expanded position rows now render ordinal / description / qty / unit_rate / total in `font-bold` so they stand out from the indented resource sub-rows.
- **Toolbar dedup** — removed duplicate "Update Rates" entry from the Quality & AI dropdown menu; the standalone toolbar button is the only entry point.
- **Checkbox column** trimmed 36px → 24px to reduce empty space between drag handle and expand chevron.

### Added
- "Update Rates" error toast now surfaces the actual exception message (instead of a generic "Recalculation failed") and writes a `[Update Rates]` line to the console for debugging.

## [2.6.17] — 2026-04-28

### Fixed
- **BOQ unit catalogue** — `'100 EA'`, `'1000 m'`, and other CWICR multi-prefix forms (rate-per-N units) were rejected by `PositionCreate` / `PositionUpdate`. New `normalise_unit()` helper accepts `<N> <approved_unit>` patterns with up to 6-digit multipliers and lowercases the trailing token. Bare units behave as before.

### Changed
- **Resource row UX** in BOQ inline editor:
  - Resource-type badge replaced with a fit-content portal-popover picker. Native `<select>` rendered every badge at "EQUIPMENT" width regardless of label; each badge now sizes to its own content (MATERIAL / LABOR / EQUIPMENT / SUBCONTRACTOR / OTHER).
  - Catalogue code chip moved from the right of the name to the **left**, so the article number is the first thing the eye lands on. Auto-clears when the user commits a different name — the row then represents a customised resource saveable to the user's personal catalogue via the existing BookmarkPlus action.
  - Currency dropdown grouped: project-FX-configured codes first, then a 33-currency global ISO 4217 list (USD/EUR/GBP/CHF/JPY/CNY/RUB/INR/CAD/AUD/NZD/SGD/HKD/KRW/BRL/MXN/ZAR/TRY/PLN/CZK/HUF/SEK/NOK/DKK/RON/AED/SAR/QAR/ILS/THB/IDR/MYR/PHP/VND). Picking a currency without a configured FX rate still flags the total cell with the existing "no FX" amber badge.

## [2.6.16] — 2026-04-28

### Added
- CWICR abstract-resource variants surfaced end-to-end. Importer preserves the 4 bullet-separated parquet columns (`variable_parts`, `est_price_all_values`, `position_count`, plus the per-unit sibling) into `CostItem.metadata_['variants']` + `['variant_stats']`. Cost DB grid shows a blue "N variants" badge next to the rate; clicking the row expands a detail panel with KvList stats, sorted variants table, and a "Median" chip on the median row. BOQ "From Database" → row pick triggers a portal popover (`VariantPicker`) for choosing a specific variant; chosen price overrides `unit_rate`, label is appended as `(Variant: …)` suffix in the description, and `metadata.variant` is written to the BOQ position. BOQ grid renders a marker badge next to variant-bearing rows.
- 8 new i18n keys per locale (EN + RU) under `costs.*` and `boq.*`.

### Changed
- Demo database trimmed from 75 mixed (Cycle/CostLink/Domain/Smoke probes) to 6 curated demo projects: Boylston Crossing, Wohnpark Friedrichshain, Residencial Salamanca, Residencial Vila Madalena, 上海徐汇职业学校扩建工程, Downtown Medical Center.
- Hoisted `KvList`, `Kv`, `QtyTile` from BIM drawer to `frontend/src/shared/ui/` so cost variant detail panel can reuse them.

### Fixed
- **Issue #101 — RBAC: BOQ create blocked for viewer-tier users.** `boq.create` lowered from EDITOR to VIEWER so any signed-in user (including freshly self-registered viewers) can start an estimate; project ownership / membership is still enforced by the service. `RequirePermission` now falls back to the live permission registry when the JWT's frozen permission list omits a lowered permission, so existing sessions don't have to re-login. Update / delete remain editor-gated.
- Several quality slices from prior sessions: punchlist photo upload now reads body before mkdir (413 fires even when storage is unwritable); AI photo/file estimate endpoints reject oversize Content-Length pre-emptively; assemblies formula-engine narrows the `except` ladder so type errors surface; erp_chat splits `ValueError` from generic `Exception` to stop flooding the journal with expected AI-key tracebacks; bim_hub forward-ref hoisted to module-level import; dwg_takeoff `l` → `layer` (E741); eac executor SIM103 collapsed; catalog `urlopen` offloaded to `asyncio.to_thread` to keep the event loop responsive.

## [2.6.15] — 2026-04-27

### Added
- Provenance markers across exporters and runtime artifacts so a forked deploy can be traced back. COBie/IDS/Excel/PDF/SARIF exports stamp `OpenConstructionERP · DDC-CWICR-OE-2026` in document metadata; SVG favicon carries an RDF authorship block; JWT tokens include `iss: openconstructionerp`; outbound catalog HTTP requests advertise the project User-Agent.

## [2.6.14] — 2026-04-27

### Fixed
- Alembic migrations `v260b` and `v260c` no longer raise on missing project / EAC tables — they skip with a warning so `Base.metadata.create_all()` at boot can handle the schema. Was bricking every prod `alembic upgrade head` while the running service was fine.

## [2.6.13] — 2026-04-27

### Fixed
- COBie XLSX export — `<a href>` clicks didn't carry the JWT, plus the URL had a trailing slash that 307-redirected. Replaced with `downloadCobieXlsx()` that fetches with Authorization header and triggers a synthetic download.
- `/assets` page contrast — text was hardcoded `text-neutral-100/200/300` so it disappeared in light theme and especially under hover. Switched to design tokens (`text-content-*`, `bg-surface-*`, `border-border-*`) so both themes are legible.
- Asset detail drawer uses the same theme tokens — backdrop, header, action bar, KvList, QtyTile, BIM properties rows all adapt to light/dark.

## [2.6.12] — 2026-04-27

### Fixed
- Frontend version sync — `frontend/package.json` was stuck at 2.6.10 through the v2.6.11 release, so the bundled UI kept reporting the old version. Both versions now move in lockstep (Issue #101 follow-up).
- Asset Register `/assets` route 422 — `GET /v1/bim_hub/assets` and `PATCH /v1/bim_hub/assets/{id}/asset-info` are now declared before `GET /v1/bim_hub/{model_id}` so FastAPI matches the literal path first.
- DWG annotation provenance preserved — backend `update_position` strip pass now also skips `dwg_annotation_source` when the caller includes it (mirrors the BIM/PDF carve-outs from v2.6.11).

### Added
- Asset detail drawer on `/assets` — click any asset row (or the new geometry icon) to open a side drawer with quantities, the full BIM properties (lazy-loaded from the same Parquet endpoint the 3D viewer uses), and an "Open in 3D Viewer" deep-link.
- BOQ "Quality & AI" dropdown — Validate / Update Rates / AI Chat are promoted inline; the rest (Price Check, Cost Finder, Smart AI) live behind a single dropdown to free up toolbar space.
- Per-measurement BOQ link in PDF Takeoff — link a single measurement to one BOQ position with a quantity-transfer preview and a unit-mismatch warning.
- Update banner shows installed → latest delta — `v{current} → v{latest}` and "X changes in v{latest}" instead of the ambiguous "X changes" count.
- `dwg_annotation_source` icon + short-label in the BOQ Quantity / Unit cells.

### Tests
- `test_boq_bim_qty_source_roundtrip.py` extended with PDF and DWG carve-out cases — all 4 pass.



### Fixed — Issue #96 (CLI / installer)
- **`openconstructionerp upgrade`** new command that pip-installs into the *same* Python env it's running in (uses `sys.executable -m pip`). The Windows installer creates a private venv at `%LOCALAPPDATA%\OpenConstructionERP\venv`; running `pip install --upgrade openconstructionerp` from any other shell upgraded the user's global Python instead, leaving the launcher's venv pinned to the old wheel — so the startup banner kept reporting the old version even though pip claimed success. The new command always lands in the right env. `version` now also prints `Site-packages: …` so users can see which interpreter the launcher is actually using.

### Fixed — BOQ editor
- **VAT row no longer hardcoded.** Removed the German-19% fallback in `boqHelpers.ts`. The Net→VAT→Gross footer is now driven from the `tax`-category row in Markups & Overheads (single source of truth, matches the backend PDF/Excel exporters). When no tax markup exists, the VAT and Gross Total rows are hidden; adding any tax markup re-introduces them with the correct rate.
- **Volume column edit lag fixed.** `updateMutation.onMutate` now writes the new value to the React Query cache immediately instead of only clearing badges, so a quantity edit no longer flickers through the old value for ~5 s while the server round-trips.
- **BIM picker provenance preserved.** Backend `update_position` was unconditionally stripping `metadata.bim_qty_source` / `pdf_measurement_source` on any quantity change — including the same request that the BIM Quantity Picker used to *set* them. Now the strip pass skips link keys that the caller explicitly included in incoming metadata; pure manual quantity edits still drop the badge as before. Added `tests/integration/test_boq_bim_qty_source_roundtrip.py` (2 cases) covering both branches.
- **BIM / PDF source icons in the Quantity cell.** `QuantityCellRenderer` now renders a small Cuboid icon for BIM-sourced cells and a Ruler icon for PDF-takeoff-sourced cells, so provenance is scannable without hovering for the tooltip.
- **Custom Columns accept any script.** `CustomColumnsDialog.normalizeColumnName` was stripping every non-ASCII character (`/[^a-z0-9_]/g`), which silently nuked Cyrillic / CJK / Arabic input and surfaced as "Column name is invalid". Now uses Unicode property escapes (`\p{L}\p{N}`), mirroring Python's `str.isidentifier()` so frontend and backend agree.

### Fixed — Country-specific defaults
- **Removed German / Euro fallbacks** flagged by the country-hardcode audit:
  - `getLocaleForRegion()` now falls back to the user's UI locale (resolved via `i18next`) instead of `'de-DE'`.
  - `getCurrencySymbol()` and `getCurrencyCode()` return empty strings when no currency is set (was `'€'` / `'EUR'`).
  - `createFormatter()` accepts an optional locale and falls back to `getIntlLocale()` instead of `'de-DE'`.
- The static `VAT_RATES` map is renamed to `SUGGESTED_VAT_RATES` and downgraded to a *suggestion* — used only to seed the placeholder in Project Settings; no longer applied as a render-time default.

### Tests
- 196 / 196 BOQ frontend tests, 1 132 / 1 132 full frontend sweep — all green.
- BOQ backend integration suite (44 tests) — all green, including the new `bim_qty_source` roundtrip cases.

## [2.6.10] — 2026-04-27

### Security
- **Demo password no longer hardcoded.** `_resolve_demo_password()` regression reintroduced the literal `DemoPass1234!` as the no-env-var fallback (BUG-D01). Restored to `secrets.token_urlsafe(16)` so every fresh install gets a unique random password persisted to `~/.openestimator/.demo_credentials.json`. Operators using `OE_DEMO_PASSWORD` env var are unaffected.

### Fixed — Tests
- `tests/conftest.py` now eagerly imports every module's ORM `models` so `Base.metadata` holds a coherent table set regardless of test-collection order. Eliminates 9 spurious `NoReferencedTableError` failures in `tests/unit/eac/test_validator_aliases.py` when run as part of the full sweep. Full unit-test pass: 2309 / 2309.

## [2.6.9] — 2026-04-27

### Fixed — Takeoff
- **Suppress "0 m²" / "0 m" labels for degenerate measurements.** `formatMeasurement(value, unit)` now returns the empty string when `value < 0.01`, so half-finished polygons and pre-calibration shapes no longer litter the side panel and on-canvas labels with misleading zero readouts.

## [2.6.8] — 2026-04-27

### Fixed — Takeoff
- **Page-jump popover** on the page indicator. Click the `X / Y` chip in the toolbar and the dropdown lists every page with a measurement-count badge per page, so users can jump directly to the page they need (especially useful on multi-page tender drawings).

## [2.6.7] — 2026-04-27

Annotation persistence — the last gap in PDF Takeoff durability.

### Fixed — Takeoff
- **Annotations now persist to the backend.** Cloud / arrow / text / rectangle / highlight types previously only saved to `localStorage`, so annotations vanished on a fresh device or browser. Schema regex extended (`takeoff/schemas.py`) and the frontend sync hook (`useMeasurementPersistence.ts`) no longer filters them out, so the existing 3-second debounce now covers the full set.
- Backwards compatible: existing measurements rows untouched; clients running v2.6.6 continue to work (annotations just stay localStorage-only on those clients).

## [2.6.6] — 2026-04-27

UX papercuts patch — Takeoff Tier 2 follow-up + Header surface fixes.

### Fixed — Takeoff
- **Active-tool hint banner** above the canvas — every measure / annotation tool now shows a one-line instruction (e.g. "Click on each item to count" + "Esc: switch tool · Del: undo last"). Replaces the silent state where users could not tell what the tool expected.
- **Annotation colour editing in the Notes panel** — small swatch next to each annotation row, native `<input type="color">` opens the OS palette so users can recolour after creation without re-drawing.
- **DWG Layers tab counter** now reflects the *visible* layer count instead of the static total, so toggling layers updates the badge live.

### Fixed — Header
- "Report Issue" button surfaced directly in the top header (was hidden behind a `…` More popover). The mailto fallback stays inside the popover.

## [2.6.5] — 2026-04-27

Hotfix bundle — security findings + deferred Auth/IDOR slice + Takeoff UX papercuts.

### Security
- Fix CodeQL `py/partial-ssrf` (critical) in `fieldreports/weather.py` — switch to `httpx.get(base_url, params=…)` so the host is fixed at compile time.
- Fix CodeQL `py/partial-ssrf` (critical) in `catalog/router.py` — URL-quote the static-map values and verify final netloc is `raw.githubusercontent.com` before download.
- Fix CodeQL `py/polynomial-redos` (high) in `dsl/nl_builder.py` — bound the German V2 reorder regex inner field to `{1,100}` characters so the lazy quantifier can't backtrack quadratically on adversarial input.

### Added — Auth/IDOR hardening (v2.4.0 slice A, deferred)
- `erp_chat/router.py`: project-scoped IDOR closed on `/{conversation_id}/messages` GET + DELETE.
- `reporting/router.py`: 3 IDOR fixes covering KPI history, dashboards, and audit trails.
- 17 new integration tests in `tests/integration/test_costs_idor.py`, `test_erp_chat_idor.py`, `test_reporting_idor.py`.

### Fixed — PDF Takeoff UX
- Mouse-wheel zoom on canvas (cursor-anchored, native listener with `passive: false` so `preventDefault` actually works).
- Annotation/measurement delete buttons now visible at 40-50% baseline opacity (no longer hover-only) and carry the `(Del)` shortcut hint.
- New "Not calibrated · click to fix" amber badge in toolbar — mirrors the existing purple "Calibrated · 1:N" badge.
- One-time toast warning when first real measurement is created on an uncalibrated drawing, gated by ref so it never spams.

## [2.6.4] — 2026-04-27

Wave-5 patch release — completes the T00–T13 dashboards/compliance backlog with two final feature deliverables.

### Added — Dashboards (T10 Multi-Source Project Federation)
- `dashboards/federation.py`: `build_federated_view(snapshot_ids, schema_align)` reads each snapshot's parquet into DuckDB and unions them with `__project_id` + `__snapshot_id` provenance columns. Three schema-align modes: `intersect` (common columns only), `union` (NULL-fill missing), `strict` (422 on mismatch).
- `federated_query()` runs whitelisted SELECT-only SQL on the view (rejects ATTACH/INSTALL/DROP/PRAGMA/SET, rejects multi-statement, rejects empty input)
- `federated_aggregate()` supports count/sum/avg/min/max with provenance group-by
- Endpoints: `POST /api/v1/dashboards/federation/build`, `POST /api/v1/dashboards/federation/aggregate`
- Frontend: `FederationPanel` (multi-select snapshot picker + schema-align mode + group-by/measure pickers), `FederatedResultsTable` (provenance chips first, project/snapshot labels)

### Added — Compliance (T13 Natural Language Rule Builder)
- `core/validation/dsl/nl_builder.py`: 8 deterministic patterns (must_have, must_not_have, value_equals, value_greater_than, value_less_than, value_at_least, count_at_least, count_zero) with EN / DE / RU lang aliases (incl. German V2 verb-final reordering)
- Optional injectable AI fallback: lazy `app.modules.ai.ai_client` import, low-confidence-only invocation, response round-tripped through the strict T08 parser before acceptance — never crashes if no API key
- Endpoints: `POST /api/v1/compliance/dsl/from-nl`, `GET /api/v1/compliance/dsl/nl-patterns`
- Frontend: `/compliance/builder` route with `NlRuleBuilderPanel` (3-pane: NL textarea / DSL preview / pattern hints, Ctrl+Enter to generate, AI checkbox, confidence badge), `DslPreview` (token-level YAML highlight, no codemirror), `NlPatternHints`

### Tests
- 30 + 6 (T10) + 29 + 7 + 11 (T13) = 83 new tests, all passing
- Full frontend `tsc --noEmit` clean across all dashboards + compliance + EAC canvas additions
- ruff + mypy clean on all new backend code

## [2.6.3] — 2026-04-27

Wave-4 patch release bundling three feature deliverables (T09 Model-Dashboard Sync Protocol, T11 Historical Snapshot Navigator, T12 CWICR Item Matcher).

### Added — Dashboards (T09 Sync Protocol)
- `sync_protocol.py` with `PresetSyncProbe`, `SyncReport`, `auto_heal()`, `diff_snapshot_meta()`. Detects column renames, drops, dtype changes, and dropped filter values; classifies severity and proposes auto-fixes.
- `oe_dashboards_preset.sync_status` + `last_sync_check_at` columns (alembic `v2b0_preset_sync_columns`)
- Subscribes to `snapshot.refreshed` event — flips matching presets to `stale` automatically
- Endpoints: `POST /api/v1/dashboards/presets/{id}/sync-check`, `POST /presets/{id}/sync-heal`
- Frontend: `PresetSyncBadge` (color-coded chip beside preset names), `SyncReportDrawer` (grouped issue list with Auto-heal CTA)

### Added — Dashboards (T11 Snapshot Navigator)
- `snapshot_navigator.py` with `list_snapshots_for_project()`, `diff_two_snapshots()`, schema-from-stats helper
- Endpoints: `GET /snapshots/timeline`, `GET /snapshots/diff` (cross-project diff returns 422)
- Frontend: `SnapshotTimeline` (vertical card list with multi-select + Compare), `SnapshotDiffView` (added/removed/dtype-changed columns + summary chips), `SnapshotPickerInline` (compact dropdown)

### Added — Costs (T12 CWICR Item Matcher)
- `costs/matcher.py` with `match_cwicr_items()` and `match_cwicr_for_position()`
- Lexical scoring via rapidfuzz `token_set_ratio` over description + localized descriptions, with additive unit/lang bonuses
- Optional semantic path tries `app.core.vector.encode_texts` then `sentence_transformers`; falls back to lexical-only if either is missing (logs once, never raises)
- Hybrid mode: `0.6 * lexical + 0.4 * semantic`
- Endpoints: `POST /api/v1/costs/match`, `POST /api/v1/costs/match-from-position`
- Frontend: `CwicrMatchPanel` with query input, mode selector, and per-row Apply CTA

### Tests
- 25 + 7 (T09) + 19 + 14 (T11) + 25 + 7 (T12) = 97 new tests, all passing
- ruff + mypy clean for backend; tsc + eslint clean for frontend

## [2.6.2] — 2026-04-27

Patch release bundling three wave-3 features (T07 Dataset Integrity, T08 Compliance DSL Engine, EAC §3.2 Block Editor canvas) and a downgrade-path migration fix.

### Fixed
- **Alembic v260b downgrade failed on SQLite** — `drop_column("idempotency_key")` raised "error in index … after drop column" because SQLAlchemy's `create_all()` lays down an auto-named `ix_oe_eac_run_idempotency_key` index that the migration didn't know about. Now walks `inspector.get_indexes()` and drops every index covering the column. Migration roundtrip test sweep: 11/11 + 1 xfail.

### Added — Dashboards (T07)
- **Dataset Integrity Overview** — `compute_integrity_report()` in `backend/app/modules/dashboards/integrity.py` produces per-column null/unique/dtype/sample/zero/outlier/issue-code stats plus a project-wide completeness score and stable schema hash. `POST /api/v1/dashboards/integrity-report` endpoint with project cross-check. `IntegrityOverview.tsx` table component with completeness chip, per-column issue badges, click-to-expand sample-values drawer, and `issuesOnly` filter.

### Added — Compliance (T08)
- **DSL Engine for ValidationRule** — `backend/app/core/validation/dsl/` package provides a typed AST (`RuleDefinition`, `ForEachAssert`, `Comparison`, `Aggregation`, `Logical`, `FieldRef`, `Literal`) parsed from YAML/JSON via `yaml.safe_load`, dunder-rejection, depth-cap 16, python-tag attack rejection. `compile_rule()` produces a registered ValidationRule subclass; supports `forEach`/`assert`, `count`/`sum`/`avg`/`min`/`max`, comparisons (`==`,`!=`,`<`,`<=`,`>`,`>=`,`in`), logical (`and`/`or`/`not`). New `oe_compliance_dsl_rule` table (alembic `v2a0_compliance_dsl_rules`), 5 endpoints under `/api/v1/compliance/dsl/` (validate-syntax, compile, list, get, delete) with tenant isolation and owner-only delete.

### Added — EAC (§3.2 Block Editor canvas)
- **Spatial block canvas with slot DnD** — `frontend/src/features/eac/canvas/` package built on `@xyflow/react`: `BlockCanvas` (zoom/pan/multi-select/keyboard), `BlockNode` (editable title + expandable params + typed slot handles), `SlotConnection` (typed bezier edges colored by data type), `CanvasToolbar` (undo/redo, fit-view, save, validate, compile), `useBlockCanvasStore` Zustand store with bounded undo/redo and clipboard, `dnd.ts` slot-type compatibility matrix. New page `EACBlockEditorPage.tsx` mounted at `/eac/blocks/:eacId`.

### Tests
- 19 + 5 (T07) + 19 + 12 + 8 (T08) + 15 + 10 + 4 + 5 (EAC canvas) = 97 new tests, all passing
- Migration roundtrip 11/11 (was 10 + 1 xfail before v260b downgrade fix)

## [2.6.1] — 2026-04-26

Patch release on top of v2.6.0 — bundles a prod-deploy migration fix and three Dashboards features (T04 Cascade Filter Engine, T05 Presets & Collections, T06 Tabular Data I/O) that were nearly complete at the v2.6.0 cut.

### Fixed
- **Alembic v270 migration crashed on empty DB** — `inspector.get_columns("oe_boq_position")` raised `NoSuchTableError` when the migration ran ahead of the ORM `create_all()` boot path. Now `get_table_names()`-guarded with a logged WARNING when the table is missing. Discovered during the v2.6.0 prod deploy: prod was actually missing `alembic_version` entirely (schema present but never stamped); fixed via `alembic stamp head` followed by `alembic upgrade head` clean no-op.

### Added — Dashboards (T04 + T05 + T06)
- **Cascade Filter Engine (T04)** — `POST /api/v1/dashboards/snapshots/{id}/cascade-values` returns distinct values of a target column whose row-set is consistent with the user's other-column selections, optional fuzzy `q`. `GET /api/v1/dashboards/snapshots/{id}/row-count` returns the live filtered row count. `CascadeFilterPanel.tsx` is a vertical stack of debounced per-column pickers with chip multi-select, per-column Clear, and a top-level Reset all.
- **Presets & Collections (T05)** — new `oe_dashboards_preset` table (alembic `v290_dashboards_presets`), service publishing `dashboard.saved` / `dashboard.deleted` events. Endpoints: `POST/GET/PATCH/DELETE /api/v1/dashboards/presets`, `POST /presets/{id}/share`. `PresetPicker.tsx` exposes "My presets" + "Shared collections" with a Save-current modal; `QuickInsightPanel.tsx`'s pin button now creates a real preset (was a no-op stub in v2.6.0).
- **Tabular Data I/O (T06)** — `rows_io.py` provides paginated DuckDB row reads + CSV/XLSX/Parquet exports + a two-step import staging area. Endpoints: `GET /snapshots/{id}/rows`, `GET /snapshots/{id}/export`, `POST /snapshots/{id}/import`, `POST /snapshots/{id}/import/commit`. `DataTable.tsx` renders the rows endpoint with click-to-sort headers; `ExportButton.tsx` triggers downloads with the auth token attached. Import UI deferred to a follow-up — the staging endpoints exist and are tested, but the snapshot-write path waits on T10 federation.

### Tests
- 16 + 16 + 10 + 7 + 6 + 5 + 12 = 72 new tests across the four agents, all passing. Backend ruff clean; frontend tsc + vitest clean.

## [2.6.0] — 2026-04-26

Major feature release. RFC 37 multi-currency / VAT / compound positions, BIM Viewer UX overhaul, IDS / SARIF interop, EAC engine API completeness, dashboards Quick-Insight + Smart-Autocomplete, security hardening, Linux install guide.

### Added — RFC 37 multi-currency, VAT, compound positions
- **Multi-currency BOQ resources (Issue #88)** — per-resource `currency` on compound-position rows. Project Settings page exposes a per-project FX rate table (code, label, rate-to-base) so foreign-priced labour, materials, equipment roll up cleanly into the project's base currency. Inline currency picker on every resource row in the BOQ grid; `⚠ no FX` pill renders when a resource currency has no rate configured. Resource total displayed in resource currency with base-currency tooltip (`qty × rate × fx`).
- **Per-project VAT override (Issue #89)** — `Project.default_vat_rate` column. When seeding a fresh BOQ's default markups, the project's VAT override (if set) replaces the regional default. Settings UI shows live "Effective: X%" badge with regional fallback.
- **Compound position editing (Issue #93)** — resource type / unit / currency are now first-class editable fields in the BOQ grid. Resource type rendered as a badge-styled `<select>` covering material / labour / equipment / subcontractor / other (i18n-keyed). Unit cell uses a project-aware datalist with free-form input persisted via `saveCustomUnit`. Project Settings exposes a chip list of custom units for the project.
- **CWICR cost link (Issue #79)** — `Position.cost_item_id` plumbed through `PositionCreate` / `PositionUpdate` / `PositionResponse`. Backend rejects unknown / inactive cost-item IDs with 422; metadata-preserving on PATCH. Bulk-positions endpoint forwards optional per-row `cost_item_id`.

### Added — BIM Viewer UX
- **Geometry session cache** — Zustand LRU keyed by `modelId` (4 entries / 200 MB cap). Returning to `/bim/{id}` from another route no longer re-downloads or re-parses the GLB / DAE — the parsed scene is restored from cache. ~5× faster on second visit.
- **Color-mode legend** — overlay listing each colour swatch + meaning across Storey / Type / Validation / BOQ-link coverage / Document coverage modes (gradient bar with min/max for the 5D-rate continuous mode). Capped at 12 swatches (+N more).
- **Persistent measurement list** — completed measurements now land in the Tools panel with focus / hide / rename / delete per row, plus a top-level "Clear all measurements" button. Stop measuring no longer wipes the user's work; Esc cancels the active mode without deleting completed entries.
- **Saved Views: rename + delete** — pencil + trash icons per row, inline edit with Enter / Esc.
- **Asset Card panel fix** — store wiring repaired (`assetCardEnabled` + setter were missing in `useBIMViewerStore`), glass effect dropped for solid surface, asset registration now resolves stub IDs through `ensureBIMElement` so PATCH always lands on a real DB UUID.
- **BIM volumetric quantity auto-suggest (Task #136)** — when linking BIM elements to a new BOQ position, the Quantity input pre-fills from the most relevant geometric parameter for the position's unit (volume / area / length / mass / count) with a confidence badge and partial-coverage warning.
- **Properties tab** is now a real local tab inside the right panel — no longer a disguised navigation to `/data-explorer`.
- **Rules button** opens in a new tab instead of unloading the viewer.
- **Saved Views Save button** no longer clipped past the panel edge.
- **4D Schedule placeholder** removed (was a no-op button).
- **Issue #53 — placeholder geometry banner**. When the IFC text fallback synthesizes generic boxes (DDC `cad2data` not installed), elements are tagged `is_placeholder: true` and the viewer shows an amber dismissable banner pointing to `docs/INSTALL_DDC.md`. No more silent placeholder-as-real-geometry.
- **Issue #53 — DAE double-rotation regression**. `ColladaLoader` already pre-rotates Z_UP DAEs; the unconditional `scene.rotation.x = -π/2` flipped models upside-down. Now branched on `_isGLB` with a Y-vs-Z bbox heuristic for un-rotated DAE inputs.

### Added — Validation interop
- **IDS importer (Task #224)** — `POST /api/v1/validation/import-ids` (multipart). Parses buildingSMART IDS XML via `defusedxml`, registers each `<specification>` as a `ValidationRule` under the `ids_custom` rule set. No IfcOpenShell dependency.
- **SARIF v2.1.0 exporter** — `GET /api/v1/validation/reports/{id}/sarif` returning `application/sarif+json`. Severity error / warning / info → SARIF error / warning / note. Element refs map to logical locations.

### Added — EAC §1.7 Engine API completeness
- New endpoints: `POST /rules:compile`, `GET /runs/{id}/status`, `POST /runs/{id}:cancel`, `POST /runs/{id}:rerun`, `GET /runs/{a}:diff/{b}`.
- Cooperative cancellation via in-process token registry + persisted `EacRun.status='cancelled'` for cross-worker visibility.
- New events: `eac.run.cancelled`, `eac.run.rerun_started`.

### Added — Dashboards (T02 + T03)
- **Quick-Insight Panel** — `GET /api/v1/dashboards/snapshots/{id}/quick-insights` runs rule-based heuristics over the snapshot (histograms, bars, lines, scatters, donuts) ranked by interestingness with chart-type diversity. `QuickInsightPanel.tsx` renders the result grid with refresh + per-card pin buttons.
- **Smart Value Autocomplete** — `GET /api/v1/dashboards/snapshots/{id}/values?column=...&q=...` powered by DuckDB + rapidfuzz fuzzy reranking. `SmartValueAutocomplete.tsx` is a debounced (250 ms) ARIA combobox with keyboard nav.

### Added — Event bus adoption (v2.4.0 slice E)
Five previously silent modules now emit events for downstream audit / analytics / notifications:
- `punchlist` — item created / updated / deleted / status_changed
- `procurement` — po created / updated / issued, gr created / confirmed
- `reporting` — kpi_snapshot / template / report_generated
- `notifications` — created / read / bulk_read / deleted
- `tendering` — package created / updated, bid created / updated (re-enabled commented-out publishes)

### Security
- **XML XXE pinning** — `backend/app/modules/schedule/router.py` now imports `defusedxml` exclusively for user-XML parsing; regression tests pin against billion-laughs and external-entity payloads.
- **Punchlist photo upload size cap** — 25 MB limit enforced via `Content-Length` pre-check then body-size fallback; HTTP 413 instead of OOM.
- **CSP source-of-truth** — duplicate `Content-Security-Policy` removed from `deploy/docker/nginx.conf`; backend middleware is now authoritative.
- **CodeQL noise reduction** — `.github/codeql/codeql-config.yml` adds `paths-ignore` for tests / dist / audit / alembic / demo seeds / marketing and `query-filters` for low-signal rules; expected ~80% alert reduction with zero behaviour change.

### Documentation
- **Linux install guide** — `docs/INSTALL_LINUX.md` covers PEP 668 externally-managed-environment trap on Ubuntu 23.04+ (incl. 26), Python 3.12 vs 3.13 wheel-coverage, system-deps for source build, port-collision recovery, optional systemd unit. README adds an Ubuntu/Debian pointer block.
- **CLAUDE.md** validation-rules-tree fixed to match disk reality (one colocated `rules/__init__.py`, no per-standard files).

### Test infrastructure
- **Backend `shared_auth` fixture cascade fix** — three-layer cascade resolved: (1) `conftest.py` redirects `DATABASE_URL` to a per-session temp SQLite *before* `from app...` imports so tests no longer compete with the production DB; (2) `_auth_helpers.promote_to_admin` flips `is_active=True` (BUG-RBAC03); (3) login / API rate limits bumped for whole-suite runs to avoid spurious 429s. The five originally-failing test files (`test_api_smoke`, `test_boq_regression`, `test_boq_import_safety`, `test_boq_cycle_detection`, `test_boq_cost_item_link`) plus three adjacent suites pass cleanly together: 57/57 in 246 s.
- `test_boq_cycle_detection` 400-vs-422 expectations aligned to the deliberate `service.py` BUG-CYCLE02 behaviour.

## [2.5.6] — 2026-04-26

Hotfix for Issue #92 (formula save broken on v2.5.5) plus a UX fix for Issue #91 (Enter-after-edit jumped to footer) and a toolbar polish.

### Fixed
- **BOQ Quantity save (Issue #92)** — three chained bugs caused every Quantity edit on v2.5.5 to come back as `0`:
  1. Backend `PATCH /v1/boq/positions/{id}` returned `500` whenever the row's `confidence` column held a legacy label (`'high'` / `'medium'` / `'low'`) — `_position_to_response` did `float(position.confidence)` and crashed. Added `_coerce_confidence` that maps known labels to `0.9 / 0.6 / 0.3` and falls back to `None` for unknowns.
  2. `onFormulaApplied` was destructured as `_onFormulaApplied` (unused) inside `BOQGrid`, so `metadata.formula` was never persisted even though the editor fired the callback. Wired through the AG Grid `gridContext`.
  3. The popup editor's tail blur (fired when `stopEditing` unmounted the input) re-entered the commit path and double-PATCHed — sometimes with the editor's raw text, which the value-parser fell back to `oldValue` for, so the cell appeared to "revert". Added a `committedRef` idempotency guard so commit fires exactly once per Enter / Tab / Blur.
- **BOQ Enter-after-edit (Issue #91)** — pressing Enter after editing Unit / Quantity / Unit-rate jumped focus down to the next row, and on the last data row landed on the footer ("Resumen") forcing the user to navigate back. Now Enter-after-edit advances right to the next column on the same row, matching how users actually fill BOQ data left-to-right (`enterNavigatesVerticallyAfterEdit={false}`).

### Changed
- BOQ toolbar AI section: removed the coloured `border-l-2` accent strips between the *Find Costs / AI Chat / Analyze* buttons.

## [2.5.5] — 2026-04-26

Issue #90: Excel-style formulas in BOQ Quantity cells. Plus the v2.5.4 Undo defensive wrapper, an "About" copy edit, and three small marketing-page text updates.

### Added — Issue #90 formulas in Qty
- New `formulaCellEditor` wired to the BOQ Quantity column. Type `=2*PI()^2*3`, `=sqrt(144) + 5`, `12.5 x 4`, etc. — the cell evaluates the expression and stores the resolved number, while the source formula is persisted in `metadata.formula` so you can re-edit it later.
- The parser is hand-written recursive-descent (CSP-safe; **no eval / no Function**) and supports:
  - Operators `+ − * / ^` (and `**` as exponent alias), parentheses
  - `x` / `×` as multiplication aliases (so "2 x 3" works)
  - `,` as decimal separator (es / de / ru locales) — only when the input has no parens, so it never collides with function-arg separators
  - Constants: `PI`, `E`
  - Functions: `sqrt`, `abs`, `round`, `floor`, `ceil`, `pow(x,y)`, `min(...)`, `max(...)`, `sin`, `cos`, `tan`, `log`, `exp`
  - Optional Excel-style leading `=`
- Editor UX: violet `ƒx` badge, live evaluation preview (`= 59.22` in green or `⚠ syntax error` in red as you type), inline `?` help popover with a cheat-sheet of operators / functions / examples.
- Cell display when a formula is stored: violet `ƒx` pill + violet number + AG Grid tooltip showing the source formula. Click the cell → editor pre-fills with the original formula, not the resolved number.
- 20 unit tests cover precedence, exponent associativity, locale decimals, multiplication aliases, function calls, identifier-injection guards (rejects `=window`, `=alert(1)`, etc.), and the user's reported example `=2xPI()^2x3`.

### Fixed — Undo defensive wrapper (was v2.5.4)
- `BOQService.update_position` wraps the DB write block (`update_fields` → `flush` → `refresh`) in a defensive try/except. Any unexpected SQLAlchemy/IntegrityError now surfaces as `422 Unprocessable Entity` with a helpful "row may have been deleted or modified concurrently — reload and retry" message instead of a bare 500. The full traceback + a type-only field summary is logged via `logger.exception` so the underlying cause is recoverable from server logs (Bug 1, partial).

### Changed — copy
- About / "Voices" founder bio: tightened the closing two paragraphs — drops the redundant "ten years" / "decade" repetition, ends with "an open-source modular ERP for the construction industry" + a single follow-up paragraph about the AI-tooling consolidation.

### Known issues (still tracking)
- Bug 1 root cause not yet identified — the defensive wrapper neutralises the user-facing impact (no more silent 500) but the trigger condition is still unknown. Server logs will now expose it on next occurrence.
- Bug 4 (description cell crash on newly-added position) — needs user-side repro with browser console screenshot.

## [2.5.3] — 2026-04-26

BOQ-editor stability + UX sweep. User reported 23 bugs on a single project's BOQ page (`/boq/{id}`); 21 fixed in this release, the remaining 2 (Undo replay 500 on stale parent_id; description-cell crash on newly-added rows) need a reproducible repro and are tracked separately.

### Fixed (data integrity)
- **Silent data loss on save failure** — Quantity edits whose server response 500'd were left in the grid as if accepted; the optimistic cache update is now rolled back via `invalidateAll()` in `updateMutation.onError` (Bug 5).
- **Apply Regional Template crash** — markup cascade calculation was unguarded against null/non-numeric `percentage` and `fixed_amount`; added `Number.isFinite` checks + array guard (Bug 3).
- **Import freeze (~30 s)** — XLSX/PDF/CAD imports could hang the UI with no signal. Added an immediate "Importing X… (up to 60 s)" toast and a 90 s `AbortController` timeout that surfaces a friendly message instead of an apparent hang (Bug 2).

### Fixed (UX)
- Lock Estimate now confirms before locking (it's irreversible without admin unlock) — Bug 8.
- Esc closes the AI Features Setup modal — standard modal behaviour (Bug 10).
- Right-click Actions menu flips when it would overflow the viewport (Bug 11).
- Grid Settings dropdown widened from `w-52` → `w-64` so "Manage Columns" / "Renumber Positions" no longer truncate (Bug 12).
- Footer rows (Direct Cost / Net Total / VAT / Gross Total) no longer show a stray `0` in the Quantity column — totals don't have a quantity (Bug 15).
- Paste-from-Excel button has a visible `Paste` label at xl breakpoints (Bug 16).
- BIM Quantity picker element names get a native browser tooltip with the full text + `IfcWallStandardCase` hint when truncated (Bug 21).
- Toolbar now sticks at `top-[52px]` (under the app header) instead of colliding with it (Bug 7).
- Right-side AI Smart / AI Cost Finder panels offset by `top-[52px]` so they no longer cover the toolbar's Import/Export/Lock buttons (Bug 13).
- "AI" group label in the toolbar is decorative — marked `pointer-events-none aria-hidden` (Bug 6).
- Unit column display now matches the editor (raw lowercase code: `m`, `m2`, `m3`) — `uppercase` CSS removed (Bug 9).
- Three AI buttons in the toolbar (Find Costs / AI Chat / Analyze) get coloured left borders + a visible label on the previously icon-only middle one (Bug 18).
- Adding an empty position toasts a one-line hint that Quality Score will dip until quantity/rate are filled (Bug 19).
- Version History empty state explicitly directs the user to the label-input + Save button instead of just saying "No snapshots yet" (Bug 20).
- AI Cost Finder demotes the CWICR `code` token to a small grey badge with a `title=` tooltip — internal IDs no longer dominate the row (Bug 22).
- Feedback URL no longer leaks `error_count=N` query param; the count is logged to console for self-debugging instead (Bug 23).
- Header's duplicate keyboard-shortcuts trigger removed; the BOQ toolbar's Keyboard icon is the single entry point (Bug 17).

## [2.5.2] — 2026-04-26

QA-report stability sweep. Triaged a 65-bug audit; ~70% were already-fixed or false-positive. Real fixes shipped:

### Security
- `docker-compose.quickstart.yml`: `JWT_SECRET` and `POSTGRES_PASSWORD` now required via env (or `.env`) — compose fails fast instead of shipping globally-shared defaults.
- `Dockerfile.unified`: removed baked-in `JWT_SECRET=change-me-in-production` ENV — must be supplied at `docker run` time.
- `registration_mode` default flipped `open` → `admin-approve`. First registrant still becomes admin (bootstrap path); subsequent self-registrations need approval. Self-hosters who want open registration set `OE_REGISTRATION_MODE=open` in `.env`.

### Fixed
- `_resolve_demo_password` default is now the documented `DemoPass1234!` instead of a random token — the CLI banner, README, and seed all advertised that string but the actual default was random, so demo logins silently failed on fresh installs.
- BOQ position parent_id validation returns 422 (FastAPI convention) instead of 400 across self-cycle / missing-parent / cross-BOQ cases.
- `smart_import` xlsx path now calls `reject_if_xlsx_bomb` — the bomb guard previously only ran in `import_boq_excel`, leaving a DoS vector via this endpoint.
- Reporting page no longer logs 50× console 404 — `/v1/reporting/kpi` → `/v1/reporting/kpi/`.
- Finance page no longer 422s on every load — `/v1/finance/budgets` → `/v1/finance/budgets/`.
- BIM Asset Register page no longer 404s — `/v1/bim_hub/assets/?` was hitting `/{model_id}` route, removed the trailing slash.
- Onboarding tour no longer blocks first-time project creation — auto-start is now skipped on `/projects/new`, `/onboarding`, `/setup`, `/login`, `/register`.
- Empty-dashboard for new users replaced with proper EmptyState (FolderPlus + Create-project CTA).
- `?lang=` URL parameter now honoured at i18n init (validated against supported locales, persisted to localStorage).

### Build / Install
- `backend/requirements.txt` reduced from 236-line freeze (torch, openai, anthropic, playwright, pyinstaller, etc.) to a 4-line `-e .[server]` shim. Saves GBs on `pip install -r`.
- `Makefile` `dev` target split: `dev-backend`, `dev-frontend` for two-terminal Windows workflow; `dev-unix` keeps the POSIX-only `&` form.
- `openestimate init-db --reset` flag added — deletes existing DB before init. Without it, prints a warning if a previous DB is present at the data dir.
- `pyproject.toml` upper version bounds added on pandas/pyarrow/pydantic/sqlalchemy/alembic/fastapi/uvicorn/duckdb/httpx — prevents pip from resolving breaking-major releases.
- `Dockerfile.unified` base image bumped `node:20-alpine` → `node:22-alpine` (rollup-plugin-visualizer 8.x requires node>=22).

### UI
- Header: dev-tool buttons "Report Issue" + "Email Issues" moved into a `⋯` "More" popover.

## [2.5.1] — 2026-04-26

Hotfix release for installer regression on Windows (issue #87).

### Fixed
- `install.ps1` aborted on `uv`'s stderr progress under `irm | iex` (PS 5.1 wrapped "Resolved 64 packages in 1.28s" as `NativeCommandError`). Switched to `Continue`-policy + `Invoke-Native` helper merging stderr→stdout.
- `install.sh` `curl` calls now use `-f` to fail-fast on HTTP 4xx/5xx (no more HTML error pages written to `docker-compose.yml`).
- `install.sh` Python detection picks the first interpreter actually ≥3.12 instead of falling back to whatever `python3` resolves to.
- `install.sh` and `install.ps1` honour `OE_VERSION` env var for pip/uv paths.
- Marketing site: replaced dead `get.openconstructionerp.com` install CTAs with raw GitHub install-script URL on hero + final CTA.

## [2.5.0] — 2026-04-25

Stability release. No migration needed for 2.4.0 upgrades.

### Fixed
- PDF takeoff page indicator no longer resets to `0/31` on Next click.
- Alembic multiple-head error on fresh clones (new `v232_merge_heads` no-op).
- PDF/DWG takeoff cross-page/layout state leaks.
- BIM viewer state leaks on model switch + stale prop callbacks.
- PDF drop-zone honesty: PDF-only with toast on rejection.
- Text-annotation Escape race (no more ghost annotations).
- Vite "Failed to fetch dynamically imported module" (14 deps pre-bundled).
- `make seed` / `db-reset` Makefile target.
- `win32_setctime` marker for non-Windows pip installs.

### Added
- Delete/Backspace shortcut in PDF takeoff.

## [Unreleased]

### Dashboards Phase 0 (T00 scaffolding)

- New modules: `oe_dashboards`, `oe_compliance_ai`, `oe_cost_match` (auto-discovered).
- `snapshot_storage.py` + `duckdb_pool.py` core primitives.
- `duckdb>=1.2.0` + `rapidfuzz>=3.0.0` promoted to base deps.
- ADR-001 (snapshot storage model) + `CLAUDE-DASHBOARDS.md` 13-task plan.
- 25 new unit tests. Full suite: 1470/1470 green.

## [2.4.0] — 2026-04-22

Audit-driven hardening — observability + i18n.

### Slice C — Structured error logging
- `reporting.kpi_recalc`: 7 sub-module failure paths logged at WARNING with op + project_id.
- `takeoff/service`: pdfplumber/PyMuPDF errors logged with input fingerprint, double-fail returns generic 400.
- `boq/events`: wildcard activity-log gated on PostgreSQL; vector-index failures rate-limited.
- `StorageBackend.open_stream`: safe default chunked read instead of `NotImplementedError`.

### Slice D — Validation i18n + GAEB
- New `core/validation/messages/` bundle (en/de/ru, 87 keys each).
- All 42 rules now flow through `translate()`, locale via `ValidationContext.metadata['locale']`.
- GAEB ruleset: 1→5 rules (`lv_structure`, `einheitspreis_sanity`, `trade_section_code`, `quantity_decimals`).
- Total rules 42→46.

### Tests
- +72 unit tests (28 slice C + 44 slice D). Full suite: 1445/1445 green.

### Deferred
- IDOR hotfixes (erp_chat, costs autocomplete/search, reporting), pagination (schedule, bim_hub), event bus in 5 silent modules.

## [2.3.1] — 2026-04-22

Post-v2.3.0 audit hardening.

### Added
- Pluggable `EmailBackend` (console/smtp/noop/memory) + `send_password_reset()` typed helper.
- `Contact.tenant_id` column + IDOR guard via tenant scoping (migration `v231`).
- `openestimate welcome` CLI + first-run interactive browser prompt.

### Fixed
- `RedisCache.get/set/delete` errors now logged via rate-limited `_RateLimitedLogger`.
- `bim_hub/ifc_processor` silent ValueError handlers replaced with DEBUG logs.

### Tests
- +49 unit tests. Full suite: 1373/1373 green.

### Migrations
- `v231_contact_tenant_id` (idempotent).

## [2.3.0] — 2026-04-22

ISO 19650 Phase A — Asset Register, COBie export, Scheduled reports.

### Added
- **Asset Register** (`/assets`) — list of tracked BIM assets with manufacturer/model/serial/warranty/status, searchable, URL-shareable filter, edit modal, in-viewer card.
- **COBie UK 2.4 export** (`/v1/bim_hub/models/{id}/export/cobie.xlsx`) — 7-sheet workbook, deterministic `frozen_now` option.
- **Scheduled reports** — POSIX cron + recipient list, custom parser (no croniter dep), `POST /schedule` / `/run-now` / `GET /scheduled`, minute-tick async scheduler in FastAPI lifespan.
- API: `GET /v1/bim_hub/assets`, `PATCH .../asset-info/`.

### Tests
- +43 backend (cron, schedule, asset, COBie). Full suite: 1324/1324 green.
- +4 Vitest + Playwright `assets-register.spec.ts`.

### Migrations
- `v230_bim_element_asset_info` (asset_info JSONB + is_tracked_asset bool + index).
- `v230_reporting_schedule` (6 schedule columns + 2 indexes).

## [2.2.0] — 2026-04-21

Q2 UX deep improvements — pivot viz, wider Charts, markup hub, calibration, 4D scrubber.

### Added
- **Pivot viz modes**: Table / Heatmap / Bar / Treemap / Matrix. URL persisted via `?piv_viz=`.
- **Charts**: all text columns surface (high-cardinality flagged with ⚠︎), no 20-column cap, new Aggregation picker (`?chart_agg=`).
- **Unified Markups hub** (`/markups`) — aggregates general markup / DWG / PDF measurements.
- **Threshold rules** (R/A/G bands per pivot column, `?tr=`).
- **BIM 4D timeline scrubber** when phase data present.
- **DWG calibration + sheet strip**, **PDF calibration + measurement ledger**.

### Fixed
- DWG annotations render on canvas (backend shape normalised at API boundary).
- PDF annotation click-through past legend overlay.
- BIM properties panel: per-row translucent cards, "Dimensions" → "BBox Dimensions".
- Frontend `APP_VERSION` reports v2.2.0.

### Tests
- +135 frontend (Pivot/Charts/aggregation/urlState). Total: 923 vitest, 1272 backend.
- Playwright `_data-explorer-viz-modes.spec.ts` — 9,512-element RVT.

## [2.1.0] — 2026-04-20

Q1 UX deep improvements — keyboard shortcuts, undo/redo, 5D cost viz, URL deep-links, RBAC fixes.

### Added
- **DWG Takeoff**: per-tool shortcuts (V/H/D/L/P/A/R/C/T/Esc), 50-entry undo/redo, Shift ortho lock, endpoint/midpoint snap.
- **PDF Takeoff**: 11-tool shortcuts, redo stack, measurement properties panel, color-coded group legend.
- **BIM Viewer**: screenshot to PNG, 5D cost gradient mode, camera+selection URL state (`?cx,cy,cz,tx,ty,tz,sel=`).
- **CAD-BIM BI Explorer**: full URL state (tabs/slicers/pivot/chart), Power-BI-style data bars.

### Fixed
- Notification navigation no longer flashes screen black (Suspense moved inside layout).
- `useModuleStore` GET path unified with PATCH to `/me/module-preferences/`.
- Dashboard team-count gated on admin/editor role (no more 403 in viewer console).
- RBAC bootstrap uses `has_admin()` check; demo user seeded as `viewer`.

### Tests
- 220/220 frontend (138 new), 6/6 Q1 Playwright, 0 TS errors.
- New `viewer-errors-audit.spec.ts` (zero-error console as a viewer).

## [2.0.0] — 2026-04-20

Second stable release. Supersedes the 1.x line.

### Fixed
- **AI Chat**: SSE streams crashing mid-flush — endpoint now opens own session, writes `asyncio.shield()`-wrapped.
- **AI key encryption**: `pydantic-settings` resolved by absolute path; rotated-key ciphertexts surface as "not configured" instead of 401.
- **DWG scale**: DXF `$INSUNITS` routed through `unitFactorToMetres()`; 3.58 m no longer shows 3580.200 m.
- **48 integration tests**: trailing-slash drift, `promote_to_admin()` after register fix.
- CDE container POST trailing slash; BOQ create trailing slash; AI Estimate save-as-BOQ trailing slash.

### Added
- BIM aggregate `/boq-links/` endpoint (3 897 real links render instead of blank).
- CAD-BIM BI Explorer: KPI strip (6 totals) + pivot data bars.
- Modules: `MODULES.md`, in-app `/modules/developer-guide`, sidebar "+ Add module" CTA.
- Dashboard: Quick Start navigation, explicit "New Estimate" button, clickable Quality Score tile.
- About/branding: Artem photo, DDC logo, book banner, community tiles.
- Provenance markers (`shared/lib/ddc-integrity.ts` + `middleware/fingerprint.py`).
- BOQ: PDF-origin icons, `FileTypeChips` per row, MarkupPanel overflow fix.
- Project Intelligence: safe-markdown renderer (no more raw asterisks).

### Cleanup
- 5 duplicate demo projects removed (6 regional demos remain).
- Diagnostic specs / test artifacts / one-off seed scripts removed; `.gitignore` extended.
- `ruff --fix`: 29 fixes across 29 files.

### Quality gates
- Frontend typecheck clean; backend cold-start clean (60 modules).

## [1.9.7] — 2026-04-19

### Workflow polish — reload persistence, onboarding, vector UX, BIM labels

- **DWG / BIM reload persistence** — both `DwgTakeoffPage` and `BIMPage` only read `projectId` from `useProjectContextStore.activeProjectId`. When the Header's stale-project cleanup wiped the store on reload, queries fired with an empty `projectId` and the pages rendered as "no documents". Both pages now fall back to `projects[0]?.id` and write the pick back to the context store so the state survives a full reload.
- **CWICR Vector Database progress UX** — `/costs/import` Vector DB loader was a bare spinner for 45+ s while the embedding model downloaded. New 4-phase progress panel in `ImportDatabasePage`: Fetch (0–3 s) → Model (3–15 s) → Embed (15–45 s) → Index (45+ s) with a purple-blue gradient shimmer bar, elapsed timer, and phase dots so users don't assume it froze.
- **BIM "BBox dimensions" label** — the right-panel block title read "Dimensions" which collided with element real-world dimensions. Renamed to "BBox dimensions" (axis-aligned bounding box) so users can tell apart the model frame from the selected element's size. `bim.dimensions_title` i18n key lands with the new default.
- **CDE optimistic container insert** — creating a container was silently succeeding (container appeared 15 s later after refetch) because `stateFilter` often did not match the new container's state. `CDEPage` onSuccess now (1) resets the state filter to "All" and (2) writes the created container into the React-Query cache so it shows up instantly.
- **Header stale-project cleanup** — `activeProjectId` persisted through localStorage outlived the project it pointed at (deleted / demo reset). Header now auto-clears `activeProjectId` when the server's project list does not contain it, so switchers never show a ghost "Project [deleted]" entry.
- **DWG upload store janitor** — `useDwgUploadStore` entries could hang in `uploading` / `converting` forever if the tab was closed mid-upload. Module-level patrol flips any job stuck >45 min to `error`, so the dock no longer shows a perpetual spinner on reopen.
- **Onboarding language cards bigger + compact shell** — welcome step cards were fighting for visibility against a padded shell. Cards resized to `grid-cols-3 sm:grid-cols-4 gap-2.5` with `size={24}` flags + `text-sm`, while the shell trimmed to `pt-4 pb-8` / `py-5 sm:py-7` so everything fits on a 13" laptop without scrolling.

### Quality gates

- `tsc --noEmit`: 0 errors

## [1.9.6] — 2026-04-19

### Reliability hotfixes — import pipeline, validators, reindex

- **CWICR region load 404** — `POST /api/v1/costs/load-cwicr/{db_id}/` had a trailing slash on the backend route; frontend called without it and got 404 on every region (France, Germany, US, etc.). Sibling routes `/vector/load-github/{db_id}` and `/import/{db_id}` use no trailing slash — `load-cwicr` now matches the pattern (`backend/app/modules/costs/router.py:1472`). Onboarding "Load database" step now works end-to-end.
- **LanceDB Qdrant false positive** — `GET /v1/vector/status` reported `can_restore_snapshots: true` whenever the `qdrant_client` pip package was importable, even on the LanceDB backend where snapshot restore requires a running Qdrant server. Settings page then tried to use the Qdrant restore path on a LanceDB deploy and showed "Qdrant not available". Now hardcoded to `False` on LanceDB (`backend/app/core/vector.py:301`) — Qdrant restore path is only surfaced when the Qdrant backend is actually selected.
- **Projects `/v1/projects/?limit=500` 422** — Header bulk-fetches the full project list to drive the Switch Project dropdown (`?limit=500`) but the backend `limit` Query had `le=100` so the request 422'd and the dropdown returned empty. Raised to `le=500` (`backend/app/modules/projects/router.py:109`). Resolves the "Could not load projects" banner in the switcher.
- **Contacts `/v1/contacts/?limit=200` 422** — same root cause: `ContactSearchInput` (Procurement, Transmittals, RFQ, etc.) fetched `?limit=200` for browse; backend was capped at 100. Raised to `le=500` (`backend/app/modules/contacts/router.py:128`). Resolves the "Select from contacts" empty state in Procurement.
- **Settings reindex double-prefix 404** — `VectorStatusCard.tsx` REINDEX_PATH map included `/api/` at the start of every entry, but `apiPost` also prepends `/api`, producing `/api/api/v1/...` — every reindex call 404'd. All 8 entries now use `/v1/...`; reindex works for every backend module.
- **DWG `/dwg-takeoff` upload dock persistence** — backend `dwg_takeoff/service.py` already created `Document` rows on every DWG upload (verified at `service.py:240-267`); the missing piece was the frontend fallback that surfaced them on reload — shipped in v1.9.7 above. Together they close the "documents disappear on reload" bug the user reported.

### Quality gates

- `tsc --noEmit`: 0 errors
- Fast smoke against local backend: projects list / contacts list / load-cwicr / reindex endpoints all 2xx

## [1.9.5] — 2026-04-18

### Deep audit pass — security + API contract + i18n + mobile

- **API contract normalisers (5 modules)** — Submittals, Meetings, Safety, Inspections and NCR all had field drift between backend (`submittal_type`, `incident_date`, `inspection_date`, `location_description`, `created_by`) and frontend (`type`, `date`, `location`, `reported_by`). Each feature's `api.ts` (or inline `select`) now runs the fetched row through a `normalise*()` function — same pattern as the v1.9.4 Transmittals fix. Resolves `type_undefined` / `status_undefined` i18n key leaks on all five list pages.
- **Procurement + Finance defensive fallbacks** — backend doesn't yet emit `vendor_name` / `counterparty_name` (resolved from `vendor_contact_id` / `contact_id`). Frontend now falls back to the raw id so the PO / Invoice tables render instead of crashing on `.toLowerCase()` of undefined. Proper backend enrichment tracked as follow-up #45.
- **NCR type hardening** — `ncr_number` and `linked_inspection_number` are numeric on the UI but strings on the wire ("NCR-001"). Normaliser now extracts the numeric suffix so `.toString().padStart()` calls behave. `cost_impact` string → number conversion on the same path.
- **Schedule `t()` API cleanup** — 5 call sites (`status_*`, `zoom_*`, `type_*`, `boq.*`) were passing a plain string as the second argument. Modernised to the `{ defaultValue }` object form so i18next never renders a raw key when the dictionary misses.
- **Security — external links** — `Sidebar.tsx:373` (`/api/source`) was missing `rel="noopener noreferrer"` on its `target="_blank"`. MeetingsPage attachment chips carried only `rel="noreferrer"` (noopener implied by modern browsers but not best practice). Both now use the full `noopener noreferrer` pair. Full audit of 20 files confirmed no other tabnabbing surfaces remain.
- **Header tablet overlap** — at 768 px the title, ProjectSwitcher, GitHub button, Report Issue button and 192 px Search box all fought for space and physically overlapped. GitHub and Report Issue now hide until `lg` (≥1024); the `<h1>` route title also stays hidden until `lg`; search shrinks to `w-40 md:w-44 lg:w-56`. iPad portrait users get a clean header.
- **Tasks action bar mobile** — the 375-px mobile view had the action bar overflow (Project select + Export + Import + New Task = 457 px). Row now wraps (`flex-wrap`) so actions reflow onto a second line instead of pushing off-screen.
- **ProjectMap i18n** — new component shipped without `useTranslation`, so "Locating…" and "No location set" were hardcoded English. Both now flow through `t('projects.map_locating', ...)` / `t('projects.map_no_location', ...)`.

### Quality gates

- `tsc --noEmit`: 0 errors
- R5 verification suite: 9/9 pass

## [1.9.4] — 2026-04-18

### v1.9 completion pass — finishes 6 items the earlier rounds left unshipped

- **#31 Transmittals Edit + Delete** — inline `EditTransmittalModal` (subject / purpose / response-due / cover-note, unlocked-only), new backend `PATCH /v1/transmittals/{id}` was already wired + new `DELETE /v1/transmittals/{id}` with 409 on issued transmittals. Frontend Row grows Edit + Delete buttons next to Issue in draft state; audit-safe delete via service/repo.
- **#13 DWG drawing scale 1:N** — `drawingScale` state in DwgTakeoffPage + floating "Scale 1:N" input under the ToolPalette. Applied as a linear multiplier to all rubber-band length labels, polyline segment pills / perimeter / area labels, and the `measurement_value` persisted with every distance/area/line/polyline/circle annotation. Persisted per-drawing in `localStorage` so the estimator doesn't re-enter it on reopen. Text-pin popup was already landed in v1.9.1.
- **#9 DWG Offline Ready badge** — verified already shipped. The component `OfflineReadyBadge` was added alongside the backend `/v1/dwg_takeoff/offline-readiness/` probe; earlier audit missed it because the grep pattern didn't match the hyphenated class name.
- **#12 DWG Summary measurements panel redesign** — verified already shipped. The `SummaryTab` component with KPI cards + per-layer + per-type breakdowns was landed alongside the v1.9.3 PDF export work.
- **#10 DWG UploadDock UI** — new `DwgUploadIndicator` component (bottom-right, above the BIM indicator) reads from `useDwgUploadStore`: minimised pill + expandable job list, per-job cancel / retry / dismiss, `beforeunload` guard while transferring. DwgTakeoffPage upload button now dispatches via the store (`startUpload`) and closes the modal immediately; a subscription invalidates `['dwg-drawings']` + `['documents']` queries and auto-selects the new drawing when the job flips to `ready`. Uploads now genuinely survive navigation.
- **#15 DWG drawing primitives** — ToolPalette now exposes `line`, `polyline`, `circle` alongside existing `rectangle` / `arrow` / `text_pin` / `area`. Two-click circle tool emits πr² × scale² as the measurement value; open polyline finishes on double-click with Σ segment length; line and distance share the same renderer path. Backend annotation-type pattern widened to accept the new `circle|polyline|line` kinds.
- **#22 Split BIM Rules / Quantity Rules navigation (v2)** — single page `BIMQuantityRulesPage` now drives two distinct user-facing entries: Takeoff section "BIM Rules" opens `/bim/rules?mode=requirements` (Requirements tab locked, tab switcher hidden, page title + subtitle swap to the compliance framing, BIM Requirements Import/Export drawer moves into this mode only); Estimation section "Quantity Rules" opens `/bim/rules` (original tab switcher, Quantity Rules + Requirements both visible). Replaces the earlier nav-only split that had pointed Takeoff at `/validation`.

### Post-release polish

- **Tasks create error fix** — Assignee free-text input was sending names like "John Doe" as `responsible_id` into a UUID-typed column, blowing up task creation. `handleCreateSubmit` now UUID-checks the assignee: real UUIDs go to `responsible_id`, typed names fall into `metadata.assignee_name` so the label survives without corrupting the FK column.
- **Project Intelligence layout** — Section 2 restructured: readiness ring now sits in a fixed 3-col card next to a full-height Critical-Gaps card (9-col), gaps render in a 2-col grid at wide widths, and the analytics grid takes the full container width below instead of being squeezed into an 8-of-12 column. Eliminates the big empty gutter the left column used to leave under the ring.
- **BIM measure-miss feedback** — `MeasureManager` now surfaces an `onMiss` callback when the raycast returns no geometry; the viewer shows a toast so users know the click registered but did not land on an element (the tool previously silently ignored these clicks, reading as "broken").
- **About page Changelog** — catch-up entries for v1.9.1 / v1.9.2 / v1.9.3 (previously stopped at v1.9.0).
- **Security** — `MessageBubble` markdown link renderer now allow-lists URL schemes (http/https/internal/mailto); rejects `javascript:`/`data:`/`vbscript:` injection.
- **Screenshot timing** — `round4-screenshots.spec.ts` snap helper waits for `networkidle` + the `Analyzing project…` spinner to disappear before capturing. Fixes the empty Estimation Dashboard capture (6 KB → 151 KB).

### Post-sweep polish (R5 full end-to-end verification)

- **E2E infra** — new `e2e/v1.9/global-setup.ts` logs in once per run, caches the JWT to `.auth-token.txt`, every spec reuses it. Avoids the 5/min rate limit on `/login/` when many parallel workers fan out. Helpers also fixed for ESM (`"type": "module"` → `fileURLToPath(import.meta.url)` replaces raw `__dirname`).
- **Tasks assignee display** — the free-text assignee name saved in `metadata.assignee_name` (when the user typed "John Doe" rather than a UUID) was never rendered on the Kanban card. `TasksPage` now falls back to `metadata.assignee_name` so typed names show up like any resolved user name. Edit form pre-fill reads the same fallback.
- **Tasks edit UUID safety** — the edit-submit path was passing free-text assignee names straight into the backend's UUID-typed `assigned_to` column, which would 422 on any edit that touched a legitimate real UUID after a name round-trip. `editMut` now applies the same UUID regex guard as the create path.
- **Transmittals purpose display** — the grid was rendering the raw i18n key `transmittals.purpose_undefined` because the backend serialises the enum as `purpose_code` while the UI models expected `purpose`. New `normaliseTransmittal` in `features/transmittals/api.ts` maps `purpose_code → purpose`, `response_due_date → response_due`, `is_locked → locked` at the API boundary; fetch/create/patch/issue all go through it.
- **CAD Explorer missingness 404** — `/v1/takeoff/cad-data/missingness/` returned 404 against a running backend because uvicorn was started before the endpoint was added and `--reload` missed the module addition. Restarted; endpoint now returns the 7-key shape (`total_rows`, `sampled_rows`, `columns`, `row_completeness`, `presence_matrix`, `applied_filters`, `sampled`) as expected.

### Quality gates

- `tsc --noEmit`: 0 errors
- Vitest: 609 passed, 24 skipped
- Playwright R5 sweep: cluster A (Tasks, 3/3), cluster B (CAD/BIM, 3/3 after backend restart), cluster C (Rules + Dashboard + 45-route nav, 5/5), cluster D (broad nav, 27/27), r5-verification (9/9)
- Backend pytest (transmittals slice): 7/7 passing

## [1.9.3] — 2026-04-18

### R4 new features

- **#10 DWG progress bar + background upload** — new `useDwgUploadStore` (Zustand, mirrors `useBIMUploadStore`): jobs carry progress + stage + error, AbortController per job, simulated stage timer with phases `uploading → converting → extracting → finalizing`. Uploads survive navigation away from `/dwg-takeoff`. Store is free-standing for now; integration into an "Upload Dock" UI component is tracked as v1.9.4 polish.
- **#14 DWG element link-to-other-modules** — extended the right-click context menu (`DwgContextMenu`) with four cross-module actions: Create task, Link to schedule, Link to document, Link to requirement. Each opens the target module page in a new tab with `drawing_id` + `entity_ids` query params so the receiving page can pre-populate forms / filters. No new backend endpoints — uses the existing URL-parameter pattern shared across modules.
- **#15 DWG PDF export** — "Export PDF" button in the Summary tab beside "Export CSV". Generates a multi-page A4 report via jsPDF: totals (count, Σ area, Σ perimeter, Σ length) + per-layer breakdown (up to 40 rows) + per-type breakdown. Rasterised viewport snapshot is deferred; the tabular report is the primary user ask.
- **#22 Split BIM Rules module** — deferred to v1.9.4. The redesigned RuleEditorModal from v1.9.1 (RFC 24) already handles the Quantity Rules concern cleanly; splitting into a separate BIM data-quality page needs a new rule schema + endpoints + migration. Explicitly tracked on the roadmap; does not block v1.9.3.

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- All prior v1.9.1 + v1.9.2 tests still passing

## [1.9.2] — 2026-04-18

### R3 UX polish — remaining items

- **#20 BIM top Link-to-BOQ removed** — the top-toolbar button was a duplicate of the entry point in the selection toolbar / context menu. Selection-toolbar entry remains intact.
- **#21 4D Schedule button disabled** — visually grayed with `aria-disabled` + "coming soon" tooltip. Feature wiring tracked as R5.

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- All prior v1.9.1 tests still passing

## [1.9.1] — 2026-04-18

### R2 deep-research items (8 items with RFCs)

- **#11 DWG polyline selection rework** (RFC 11): ranked area/proximity hit-test fixes outer-polyline bias; `Set<string>` multi-select with Shift+Click + Escape; cycle-through within 6 px / 300 ms; new `aggregateEntities` helper (Σ area / Σ perimeter / Σ length by type); new backend `POST/GET/DELETE /v1/dwg_takeoff/groups/` with `DwgEntityGroup` model; 6 backend tests + 25 frontend unit tests.
- **#16 Data Explorer analytics** (RFC 16): `useAnalysisStateStore` (slicers + chart config + saved views, localStorage-persisted); `numberFormat` lib (currency / percent / number with Intl caching); `aggregation.ts` (Top-N + slicer composition); Recharts lazy-loaded (Bar / Line / Pie / Scatter + ResponsiveContainer); SlicerBanner + TopNToggle + DrillDownModal + ViewsDrawer; 39 unit tests + 5 E2E cases.
- **#19 BIM viewer controls** (RFC 19): `SavedViewsStore` (100-view localStorage cap, ordered eviction); per-category transparency via `ElementManager.setCategoryOpacity` (cloned materials, leak-free dispose); `THREE.BoxHelper` on selection; `MeasureManager` with state-machine + `M` shortcut + `Escape` cancel; 4-tab right panel (Properties / Layers / Tools / Groups); unit tests for all three managers.
- **#24 Quantity Rules redesign** (RFC 24): new `GET /v1/bim_hub/models/{id}/schema/` with 1000-value cap per property; RuleEditorModal with Seed-from-model + datalist comboboxes (element type, property key/value, quantity source); required-field asterisks; Advanced mode toggle (AND/OR/NOT + regex hint + raw JSON editor); BETA badge on page header; 6 backend tests.
- **#25 Project Intelligence → Estimation Dashboard** (RFC 25): `ProjectKPIHero` (Budget variance / Schedule health / Risk-adjusted cost with traffic-light thresholds); `ProjectAnalyticsGrid` (Pareto cost drivers, price volatility, vendor concentration, scope coverage, live validation); 5 new backend endpoints (`/v1/costmodel/variance`, `/v1/boq/line-items`, `/v1/boq/cost-rollup`, `/v1/tendering/bid-analysis`, `/v1/boq/anomalies`); dropped Achievements card + hero onboarding; cache TTL 5 min → 60 s; rename "Estimation Dashboard" (URL unchanged); 14 backend tests.
- **#29 Meetings edit + attachments + description** (RFC 29): new `document_ids: JSON` column with migration + server default `[]`; `EditMeetingModal` mirroring Create (pre-fill + diff-PATCH); delete with `useConfirm`; attachment dropzone with `DocumentService` cross-link; minutes textarea (50 000 char cap); Playwright spec.
- **#33 CDE deep audit (ISO 19650)** (RFC 33): `suitability.py` lookup (S0 / S1–S7 / A1–A5 / AR with state-cross-check validator); new `StateTransition` table + inline audit writes (pre-commit, same-session); revision→Document cross-link on upload; Gate B requires `approver_signature` (400 otherwise); history + transmittals endpoints; `TransmittalItem.revision_id` cross-link; CDEHistoryDrawer + CDETransmittalsBadge; 21 backend tests (17 unit + 4 integration).

### R3 UX polish items bundled

- **#1 Local DDC logo** — Dashboard logo swapped to `/brand/ddc-logo.webp` (no external image fetches on page load).
- **#3 Offline banner removed** — redundant with offline-first pattern from v1.9.0.
- **#4 Header issue menu order** — Report Issue (bug download) now before Email Issues.
- **#7 Takeoff measurements row density** — tighter row height in `TakeoffViewerModule` for both measurement and annotation rows.
- **#17 cad-explorer "Columns" label** — renamed to "Parameter columns" / "Parameter-Spalten" / "Колонки параметров" for clarity.
- **#26 Schedule Create button** — bigger, `Plus`-iconed, size `lg`.
- **#28 5D EVM scope indicator** — banner shows "Viewing all projects (N)" or "Project: {name}" with switch link.
- **#30 Submittals Edit dialog** — row-level Edit button + `EditSubmittalModal` + `updateSubmittal` API wrapper.
- **#32 Documents filters** — client-side file-type dropdown (PDF / DWG / IFC / RVT / Other) + revision filter (All / Latest / Has versions).

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- Backend `tests/unit/v1_9/` + `tests/integration/v1_9/`: **49/49 passing**
- Frontend unit tests: 600/633 passing (9 pre-existing failures in jsPDF stub + visual-regression snapshots — documented in release notes)
- 7 new RFCs committed in `docs/rfc/` before implementation
- See `docs/ROADMAP_v1.9.md` for per-item detail

### Upgrade notes

- Alembic migrations: three new heads chained — `v191_meetings_document_ids`, `v191_dwg_entity_groups`, `v191_cde_audit`. Run `alembic upgrade head`.
- DWG viewer: `selectedEntityId: string | null` prop is now `selectedEntityIds: Set<string>` (breaking). Two internal call-sites updated; no external consumers affected.
- CDE: `suitability_code` is now state-validated — existing rows with free-text codes continue to work (nullable column + validator only runs on create / update payloads).

## [1.9.0] — 2026-04-17

### R1 critical bug fixes (8 items from the 33-item v1.9 roadmap)

- **BOQ resource add** (#2): optimistic cache write in `handleCatalogSelect` + `networkMode: 'offlineFirst'` + retry guard on the BOQ query. Resources appear instantly; reload no longer hangs.
- **BOQ list offline** (#5): global QueryClient hardened with `navigator.onLine` retry guard and 4xx no-retry — no more `AbortError: signal is aborted without reason` when the network drops.
- **Project not-found vs network error** (#6): `ApiError.status === 404` distinction; new Offline / Can't-reach-server / Retry UI branch; auto-clear-recents gated on true 404 only.
- **Takeoff persistence** (#8): `activeDocId` synced to URL param on upload / click / remove so reload restores the open document.
- **BIM Type Name grouping** (#18): `BIMFilterPanel` condition relaxed to show Link-to-BOQ and Save-Group whenever any elements are visible.
- **BIM Rules** (#23): `mutationKey` + awaited invalidate + filter fix (no-project-context leakage).
- **Tasks category tab** (#27): create modal defaults `task_type` to the active `typeFilter` instead of hard-coded `'task'`.
- **CDE New Container** (#33): `mutationKey`, awaited invalidate, concrete error fallback with dev `console.error` — silent failures are now visible.

### Quality gates

- `tsc --noEmit`: 0 errors
- Playwright `e2e/v1.9/`: 5/5 runnable tests green (2 skipped — pending BIM-model seed data)
- See `docs/ROADMAP_v1.9.md` for per-item detail, rationale, and CTO review checklist

### Scope changes from the original 10-item R1 target

- `#9` (DWG offline) → moved to R3 (UX badge only; backend already offline-capable)
- `#13` (DWG scale + annotation text) → moved to R2 (needs RFC for scale semantics + live repro for text)

## [1.8.3] — 2026-04-17

### BOQ quantity CTA, BIM filmstrip fix, Dashboard upload, cross-link

- **BOQ Linked Geometry → "Apply to BOQ" CTA refresh.** The "Set as
  quantity" buttons are now prominent — a green gradient CTA with arrow
  on every SUM row, and hover-reveal chips with an arrow indicator for
  DISTINCT values. `CheckCircle2` badge replaces the plain "current" tag.
- **BIM filmstrip no longer disappears.** Removed the
  `landingModels.length > 0` conditional that hid the "Your Models" bar
  between LandingPage unmount and main-view mount; the filmstrip is now
  always rendered with a "No models yet" empty state so users keep a
  consistent anchor to switch or upload models.
- **Dashboard upload dropzone.** New `QuickUploadCard` component drops
  files straight into the Documents module with client-side 100 MB limit,
  toasts, live document count, and a `→ Documents` jump link.
- **Cross-link module uploads into Documents.** BIM (`upload_cad_file`),
  DWG Takeoff (`DwgTakeoffService.upload_drawing`), and PDF Takeoff
  (`takeoff/router.py upload_document`) now best-effort create a Document
  row pointing at the same physical file (no duplication) with
  `metadata.source_module` + `source_id` so every file a user uploads —
  in any module — is visible in `/documents`.
- **DocumentsPage routing prefers metadata.** `routeForDocument` and
  `isCardClickable` read `metadata.source_module` first and fall back to
  filename extension, so cross-linked files always jump back to the
  correct module.

## [1.8.2] — 2026-04-17

### Documents routing, BOQ link fixes, DWG filmstrip

- **Documents → correct module by file type** — PDFs open in preview or
  `/takeoff`, DWG/DXF/DGN open in `/dwg-takeoff`, RVT/IFC/NWD/NWC open in
  `/bim`. All with deep-link params so the right file is loaded on arrival.
- **Documents — "Module Files" section** — new compact grid showing BIM
  models, DWG drawings, and Takeoff PDFs uploaded via their native modules,
  each clickable straight into that module.
- **BOQ link icons — deep-link fix** — the red PDF and amber DWG icons next
  to BOQ positions now pass the correct URL params (`drawingId` for DWG,
  `name` for PDF) so clicking them opens the specific linked file instead
  of bouncing to the module landing page.
- **BIM ?docName= / ?docId= deep-link** — `/bim?docName=xxx.rvt` auto-selects
  the matching model if it exists, otherwise opens the upload dialog with
  the filename pre-filled.
- **DWG Takeoff filmstrip** — taller (108-px cards, 150-px max-height) for
  clearer per-drawing metadata.
- **Header** — "Report Issues" → "Email Issues" with mail icon linking
  directly to `mailto:info@datadrivenconstruction.io`.

## [1.8.1] — 2026-04-17

### DWG Takeoff depth pass + Takeoff decorative background

- **DWG ↔ BOQ deep linking** — full picker mirrors the PDF-takeoff flow:
  project + BOQ dropdowns, pick-existing-or-create-and-link, search filter,
  already-linked badge. On link, a `text_pin` annotation is auto-created at
  the selected entity's centroid (if none exists), `linkAnnotationToBoq`
  ties it to the position, and the position's `quantity` + `unit` +
  `metadata.{dwg_drawing_id, dwg_entity_id, linked_annotation_id}` are
  updated — matching the PDF linking model end-to-end.
- **DWG summary bar** in the right panel: total entities, Σ area, Σ distance,
  plus a one-click CSV export of all measurements (type, text, value, unit,
  linked position id).
- **DWG right panel refinement** — back to light theme, width bumped to 72px,
  elevated shadow for separation from the dark canvas.
- **DWG toolbar palette** — white-glass on dark `#3f3f3f` canvas so tool
  icons read clearly in both light and dark app themes.
- **Takeoff decorative background** — field-surveyor chalkmarks (rectangles,
  irregular polygons, distance dimension lines, vertex pins, scale ruler) at
  ~6% opacity, fixed to viewport so both Measurements and Documents tabs
  share the same bg.
- **Documents API** — frontend wrappers for general-document upload/list/
  delete (`uploadDocument`, `fetchDocuments`, `deleteDocument`). Foundation
  for the upcoming Dashboard ↔ Documents module integration.
- **Demo storyboard** — full 6-minute walkthrough script saved to
  `docs/VIDEO_DEMO_v1.8.md` (hook → CAD/BIM → takeoff → BOQ → validation
  → tender → 4D/5D).

## [1.8.0] — 2026-04-17

### BOQ ↔ Takeoff linking, UI polish sprint, decorative backgrounds

- **BOQ ↔ PDF Takeoff deep linking** — individual measurements can now be linked
  to specific BOQ positions. The measurement's quantity auto-transfers to the
  position and stays in sync. Bidirectional metadata: `measurement.linked_boq_position_id`
  + `position.metadata.pdf_document_id / pdf_page / pdf_measurement_id`.
- **BOQ grid link icons** — rose PDF icon + amber DWG icon next to positions
  that have linked documents. Click opens the document in the same tab so the
  auth session is preserved (no more login bounce).
- **BOQ Linked Geometry popover** — "Set as quantity" buttons next to each BIM
  parameter value; one click applies the value to the position's quantity field.
- **Takeoff UI refresh** — tab order swapped (Measurements first, Documents & AI
  second); tighter rounded corners; per-tool hover colours. Bottom filmstrip
  of previously uploaded documents with click-to-open.
- **Takeoff decorative background** — barely-visible polygons, distance lines,
  scale rulers behind the viewer, evoking field-surveyor chalkmarks.
- **BIM landing** — tileable isometric-cube SVG pattern at ~1% opacity; airy
  spacing; inner scroll hidden with `scrollbar-none`; content fits 1080p viewport.
- **BIM filmstrip** — no longer auto-collapses after 10s; always visible.
- **DWG Takeoff** — toolbar palette switched to white-glass for contrast on the
  dark `#3f3f3f` canvas; right-panel re-themed dark with readable slate-100
  text; drawings filmstrip already dark (1.7.2).
- **CAD Data Explorer** — subtle semi-transparent spreadsheet grid decoration;
  landing now fits without horizontal *or* vertical scroll on typical viewports.
- **Chat** — markdown links like `[Settings](/settings)` now render as proper
  clickable anchors; external links open in a new tab.
- **Projects** — self-healing bookmark URLs: navigating to a stale project ID
  (e.g. after a demo reseed) auto-clears it from `useProjectContextStore` and
  `useRecentStore` so the user isn't stuck on "Project not found".

## [1.7.0] — 2026-04-15

### BIM, DWG Takeoff, and cross-module UI improvements

- **BIM Viewer** — linked BOQ panel with quantities
- **DWG Takeoff** — polygon selection + measurements
- **Data Explorer** — BIM-style full-viewport layout
- **Dashboard** — DDC branding, subtitle i18n (21 langs)
- **Assemblies** — JSON import/export, tags, drag-reorder
- **5D Cost Model** — inline-editable budget lines
- **Finance** — summary cards with key metrics
- **Tasks** — custom categories, 4-column Kanban
- **Schedule** — user-selectable project start date
- **Chat** — AI config onboarding guide
- **Project Intelligence** — tag badges, compact cards
- **Bugfixes** — Contacts country_code, RFI field sync, 4 modals
- **UI** — unified padding across 37+ pages

## [1.4.8] — 2026-04-11

### Real-time collaboration L1 — soft locks + presence (issue #51)

Maher00746 asked: "Does the platform support real-time collaboration
when multiple users are working on the same BOQ?". The full collab
plan has 3 layers: L1 (soft locks + presence), L2 (Yjs Y.Text on text
fields), L3 (full CRDT BOQ rows). This release ships **L1**, which
covers the maher00746 90% case ("two estimators editing the same
position should not trample each other") without dragging in a CRDT
runtime, Yjs, or Redis. L2 / L3 remain on the v1.5 / v2.0 roadmap.

#### New module ``backend/app/modules/collaboration_locks/``
Self-contained module with manifest, models, schemas, repository,
service, router, presence hub, sweeper, and event bridge — 1,580
backend LOC across 10 files. Mounted at ``/api/v1/collaboration_locks``.
Named ``collaboration_locks`` (not ``collaboration``) so it does not
collide with the existing comments / viewpoints module.

- ``oe_collab_lock`` table (Alembic migration ``a1b2c3d4e5f6``) with
  ``UniqueConstraint(entity_type, entity_id)`` so only one user can
  hold a row at a time. Indexed on ``expires_at`` and ``user_id``.
- **Atomic acquire** via read-then-insert-or-steal at the repository
  level — cross-dialect (SQLite dev + PG prod), races handled by
  catching ``IntegrityError`` and re-reading the winner. Expired
  rows are stolen *in place* via UPDATE so the unique constraint
  never trips.
- **Heartbeat extends TTL** in 30s steps; rejected if the caller is
  not the holder.
- **Release** is idempotent and only honoured for the holder.
- **Background sweeper** runs every 30s, purges rows where
  ``expires_at < now()``. Uses its own session per iteration so a
  sweeper failure cannot roll back any in-flight request.
- **Entity-type allowlist** mirrors the existing ``collaboration``
  module — clients cannot lock arbitrary strings. Returns 400 on
  rejection.
- **409 conflict body** is a distinct ``CollabLockConflict`` schema
  with ``current_holder_user_id``, ``current_holder_name``,
  ``locked_at``, ``expires_at``, ``remaining_seconds`` so the
  frontend can render a useful toast without a follow-up GET.
- **Naive datetime normalisation** via ``_as_aware()`` helpers in
  repository + service — SQLite's ``DateTime(timezone=True)``
  returns naive Python datetimes, so every comparison gets coerced
  to UTC first. Same pattern already used in ``dependencies.py``
  for ``password_changed_at``.

#### Presence WebSocket
``WS /collaboration_locks/presence/?entity_type=...&entity_id=...&token=<jwt>``
broadcasts JSON frames to every connected client subscribed to the
same entity. Auth via the ``token`` query param because browser
WebSocket cannot set headers — same pattern as the BIM geometry
endpoint. The ``PresenceHub`` is worker-local in v1.4.8 (single
``presence_hub = PresenceHub()`` module-level instance, no Redis,
no Postgres LISTEN/NOTIFY) — multi-worker deployments still get
correct *locking* via the DB but presence broadcasts are
worker-scoped. Documented in the module docstring; the upgrade
path to LISTEN/NOTIFY is a single internal swap with no caller
changes.

Wire format (every frame is JSON ``{event, ts, ...}``):

| event | extras | when |
|---|---|---|
| ``presence_snapshot`` | ``users[]``, ``lock`` | first frame after upgrade |
| ``presence_join`` | ``user_id``, ``user_name`` | another user opened the entity |
| ``presence_leave`` | ``user_id`` | user closed all their tabs on the entity |
| ``lock_acquired`` | ``lock_id``, ``user_id``, ``user_name``, ``expires_at`` | any user claimed the lock |
| ``lock_heartbeat`` | ``lock_id``, ``user_id``, ``user_name``, ``expires_at`` | holder renewed TTL |
| ``lock_released`` | ``lock_id``, ``user_id``, ``user_name`` | holder voluntarily released |
| ``lock_expired`` | ``lock_id``, ``user_id`` | sweeper removed a stale lock |
| ``pong`` | — | response to client ``"ping"`` keepalive |

The ``presence_join`` broadcast uses ``exclude=websocket`` so the
joiner does not receive their own join event. ``lock_acquired``
intentionally does NOT exclude — the holder *should* see the echo
so the UI can confirm the state transition from the event stream
(useful for multi-tab consistency).

Multi-tab same user: the hub deduplicates by ``user_id`` in the
roster. ``leave()`` walks remaining sockets to check whether the
departing user still has another tab on this entity before
broadcasting ``presence_leave``. The lock itself is idempotent per
user (re-acquire refreshes TTL).

#### Frontend hook + indicator + BOQ wiring
``frontend/src/features/collab_locks/`` — 5 files, 636 LOC:
- ``api.ts`` — typed clients with a tagged-union return type so
  TypeScript narrows ``CollabLock`` vs ``CollabLockConflict``
- ``useEntityLock.ts`` — auto-acquire on mount, 15s heartbeat,
  cleanup-release on unmount. Catches every error and degrades
  gracefully — a network drop transitions to ``'released'`` and
  re-acquires on the next focus event. Worst case: user types
  for ~15s without a live lock (race window between expiry and
  next sweep at 60s TTL + 30s sweep interval).
- ``usePresenceWebSocket.ts`` — JWT-via-query-param connection,
  roster state, event stream
- ``PresenceIndicator.tsx`` — green / amber / blue pill badge
  ("You are editing" / "Locked by Anna 3:42 remaining" / "N viewers")
- ``index.ts`` — barrel re-exports

**BOQ wiring** in ``frontend/src/features/boq/BOQGrid.tsx``:
- Acquires on ``onCellEditingStarted`` (per ROW, not per cell —
  tracks held locks in a ``rowLockMapRef`` and re-uses on
  subsequent cell edits within the same row)
- Releases on new ``onCellEditingStopped`` callback
- Releases all held row locks on unmount
- 409 cancels the edit and shows a toast with the holder name +
  remaining seconds. Network errors degrade silently — the user
  can still edit, just without collab safety.

9 new i18n keys (``collab_locks.lock_held_by_you``,
``collab_locks.lock_held_by_other``, ``collab_locks.lock_conflict_toast``,
``collab_locks.viewers_label`` etc.) all via ``t(key, { defaultValue })``
so the UI works today without a translation pass.

#### Tests — 17 / 17 passing

``backend/tests/integration/test_collab_locks.py`` — 14 tests
covering: acquire when free / conflict, idempotent re-acquire,
heartbeat extends / rejects non-holder, release, idempotent
release of missing-id, allowlist 400, ``GET /entity/`` returns
none-or-holder, ``GET /my/`` lists my locks, expired-lock-can-be-
stolen via direct DB forge, sweeper removes expired rows.

``backend/tests/integration/test_collab_locks_ws.py`` — 3
WebSocket tests: rejects missing token (1008), delivers
``presence_snapshot`` + ``lock_acquired`` to subscribers, delivers
``presence_join`` across two clients.

#### What is deliberately NOT in v1.4.8

- **L2 — Yjs Y.Text on description / notes** → v1.5. Requires
  ``yjs`` + ``y-websocket`` deps + server-side CRDT state
  persistence. Not needed for the maher00746 case.
- **L3 — full CRDT BOQ rows** → v2.0. 3x the surface of L1 with
  marginal UX gain over soft locks for our user base.
- **Postgres LISTEN/NOTIFY fan-out** → only needed for multi-
  worker deployments wanting cross-worker presence. The hub
  interface stays stable; only ``_broadcast`` needs a second
  implementation gated on settings.
- **Audit log of lock events** → the event bus already publishes
  ``collab.lock.*``; an audit subscriber can be added in a
  follow-up without touching this module.
- **Org-scoped RBAC** → ``org_id`` column exists but is unused.
  Matches the current behaviour of the ``collaboration`` module.
- **Frontend wiring for non-BOQ entities** → only BOQ row editing
  is wired in this PR. Requirements / RFIs / tasks / BIM elements
  are already in the allowlist; the hook + indicator are ready
  to drop into any of those editors.

### Verification
- Backend ``ruff check`` clean across the new module + tests
- 17/17 collab_locks integration tests passing in 65.7s
- ``check_version_sync.py`` passes at 1.4.8
- Frontend ``tsc --noEmit`` exit 0
- Alembic migration chains correctly on top of head ``b2f4e1a3c907``

## [1.4.7] — 2026-04-11

### Added — UX polish + cross-module event hooks

#### BIM viewer geometry-loading progress bar
The BIM viewer used to show only a generic spinner while the COLLADA
geometry blob downloaded — a 100MB Revit model could take 30+ seconds
with no visible progress, so users assumed the page had hung.
``ElementManager.loadDAEGeometry`` now accepts an ``onProgress``
callback that surfaces the XHR ``loaded / total`` ratio, and
``BIMViewer`` renders a determinate progress bar with percentage
indicator, gradient fill, and "Streaming geometry from server…" /
"Finalising scene…" status text.

#### Sidebar BETA badges (subtle, modern)
``/bim``, ``/bim/rules``, and ``/chat`` are still under heavy
development.  Added a tiny lowercase ``beta`` badge to each of those
nav items so users know not to rely on those modules for production
work yet.  The badge style is intentionally understated — neutral
grey, 9px, lowercase — so it does not visually compete with the
sidebar's normal items.

#### Restored rich GitHub README
``README.md`` was rewritten to a 53-line minimal version in d3d2319
that dropped the Table of Contents menu, the comparison table, the
feature gallery, and the workflow diagram.  This release restores
the rich 450-line version (badges, ToC table, why-OpenConstructionERP
table, vendor comparison, complete-estimation-workflow diagram, 12
feature blocks with screenshots, regional standards table, tech
stack, architecture diagram) — bumped to v1.4.6 in the version
badge and footer.

### Fixed

#### Frontend correctness
- **F1**: ``BIMPage.tsx:602`` dropped two ``(res as any)`` casts on
  the upload response.  ``BIMCadUploadResponse`` now declares
  ``element_count: number`` and a typed ``status`` union, so the
  upload toast no longer guesses fields that may not exist.
- **F5**: ``BIMFilterPanel`` now resets every transient filter slot
  (search, storey checkboxes, type checkboxes, expanded headers,
  active group highlight) when the user switches to a different
  BIM model.  Previously the checkbox UI carried over Storey 5
  selections from the old model into the new one — confusing UX
  where the displayed filter did not match the applied predicate.

#### Cross-module wiring
- **T2.3**: ``Assembly.total_rate`` is no longer stale when a
  ``CostItem.rate`` changes externally.  New ``assemblies/events.py``
  subscribes to ``costs.item.updated``, finds every ``Component``
  pointing at the updated cost item, refreshes the per-component
  ``unit_cost`` + ``total``, and re-runs the parent assembly total
  math (sum of components × ``bid_factor``).  BOQ positions
  generated from an assembly BEFORE the rate change are intentionally
  NOT touched — they're locked financial commitments at create time;
  the next regenerate of the position picks up the new rate.
- **T3.5**: ``requirements.list_by_bim_element`` now uses the
  PostgreSQL JSONB ``@>`` containment operator at the SQL level when
  the dialect is PG, so the database does the filtering instead of
  loading every project requirement and filtering in Python.
  SQLite still uses the Python fallback (no portable JSONB
  operator).  Mirrors the dialect-aware pattern in
  ``tasks/service.py::get_tasks_for_bim_element``.

#### Test infrastructure
- **T8 (deferred from v1.4.5)**: 12 broken integration tests that
  failed since v1.3.x with 404 / 422 / 403 errors are now passing.
  Root cause was a mix of:
  - Trailing-slash mismatch (10 tests): tests called
    ``/boqs/{id}/positions`` without the slash but the route is
    ``/boqs/{id}/positions/``.  ``redirect_slashes=False`` is
    intentional in main.py to kill CORS 307 redirect issues with
    the frontend, so the FIX is to add the slash to the test
    paths.  Audited every parametric POST in
    ``test_cross_module_flows.py`` + ``test_api_smoke.py``.
  - Missing required query param (1 test):
    ``test_tendering_packages`` was hitting ``/tendering/packages/``
    without the mandatory ``project_id`` (security: prevents
    cross-tenant enumeration).  Fixed to create a throwaway project
    first.
  - Permission scope (1 test):
    ``test_cost_regions`` and ``test_vector_status`` had no
    auth header — the endpoints require ``contacts.read`` or
    similar.  Fixed to pass ``auth_headers``.

### Notifications subscriber dialect guard
The S3 subscriber framework added in v1.4.6 (boq.created /
meeting.action_items_created / cde.state_transitioned event hooks)
opened its own short-lived session via ``async_session_factory()``
to call ``NotificationService.create()``.  Under SQLite this
deadlocked against the upstream service's still-open transaction
because SQLite is single-writer per file.  The handlers now probe
the dialect at entry and bail out fast on SQLite — production uses
PostgreSQL where this is a non-issue, and the dev SQLite path
simply skips the in-app notification (the upstream mutation still
succeeds).  A v1.5 background-task refactor will move notification
create out of the upstream transaction altogether.

### Project Intelligence smart actions implementation (T2.1)
The three "smart action" tiles on ``/project-intelligence`` were
stub redirects that opened the validation / cost-catalog / scheduler
pages and let the user finish the action manually.  ``actions.py``
now actually performs the work:
- ``run_validation`` loads the project's oldest BOQ, runs
  ``ValidationModuleService.run_validation`` with
  ``rule_sets=["din276","boq_quality"]``, and returns the new
  ``ValidationReport`` id plus pass / warning / error counts.
- ``match_cwicr_prices`` walks every leaf BOQ position with a
  zero ``unit_rate``, calls ``CostItemService.suggest_for_bim_element``
  with the position description and classification, and writes the
  top match's rate back to ``unit_rate`` (with ``total = qty × rate``
  recomputed and the matched code/score saved into ``metadata_``).
  Publishes ``boq.prices.matched`` so vector re-indexing subscribers
  can react.
- ``generate_schedule`` refuses if a schedule already exists,
  otherwise creates a draft ``Schedule`` keyed off
  ``project.planned_start_date`` and delegates to
  ``ScheduleService.generate_from_boq``, returning ``schedule_id``
  + ``activity_count``.

Every action wraps its body in try/except so failures surface as
``ActionResult(success=False, message=...)`` rather than 500.
9 new unit tests cover happy path + no-BOQ guards + service-raises
branches.

### Vector routes factory (T9)
6 of 8 module routers were carrying ~50 lines each of copy-pasted
``vector/status`` + ``vector/reindex`` boilerplate (documents,
tasks, risk, validation, requirements, erp_chat).  Extracted the
common shape into ``app/core/vector_routes.py:create_vector_routes()``
which takes a model + project_id_attr (or a custom loader for
parent-scoped modules), the read/write permissions, and a vector
adapter.  Each module router now does ``include_router(create_vector_routes(...))``
in 4 lines instead of 50.  Net result: **-105 LOC** in module
routers, ~291 lines of duplicated boilerplate eliminated, all 16
existing vector routes preserved exactly.  ``boq`` and ``bim_hub``
keep their hand-written endpoints because they accept extra
optional query params (``boq_id`` / ``model_id``) that the
factory does not yet model.

### Costmodel honest schedule reporting + delete-snapshot
The 5D cost-model dashboard previously reported every project as
"on_track / at_risk" even when no schedule data was available,
because ``calculate_evm`` had a hard-coded ``time_elapsed_pct =
50.0`` fallback.  This skewed portfolio rollups and made unscheduled
projects look like they were silently 50 % done.

- The fallback is gone.  ``schedule_known: bool`` is set only when
  date parsing actually succeeds; otherwise ``evm_status`` is
  ``schedule_unknown`` and the dashboard renders "no schedule yet"
  instead of a fake percentage.
- Bonus fix in ``full_evm/service.py``: TCPI was crashing on
  ``Decimal(0)`` denominators.  Three-branch decision now yields
  ``"inf"`` sentinel when remaining work exists but the budget is
  exhausted, and ``Decimal(0)`` when both are zero.
- New ``DELETE /api/v1/costmodel/projects/{pid}/5d/snapshots/{sid}``
  endpoint (gated by ``costmodel.write``) for cleaning out stale
  snapshots without dropping into a SQL shell.  Emits
  ``costmodel.snapshot.deleted`` event.

21 new unit tests, total suite 963 passing, zero regressions.

### BIM frontend correctness wave (F2/F3/F4/F6)
- **F4** — ``AddToBOQModal`` derived ``effectiveBOQId`` via
  ``useMemo`` from ``(boqs, userSelectedBOQId)`` so a BOQ getting
  removed mid-flow can not leave the modal pointing at a stale id.
  Tightened the React Query ``enabled`` guard with
  ``!boqsQuery.isLoading`` for first-render correctness.
- **F2** — All four BIM link modals
  (``AddToBOQModal``/``LinkDocumentToBIMModal``/``LinkActivityToBIMModal``/``LinkRequirementToBIMModal``)
  reset their internal state when the parent's ``elements`` array
  identity changes, so reopening the modal after switching elements
  always starts clean.
- **F3** — ``LinkActivityToBIMModal`` and
  ``LinkRequirementToBIMModal`` replaced the hardcoded "showing
  first 200, +N more…" stub with proper pagination
  (``PAGE_SIZE = 50`` + "Load more (N remaining)" button), with
  the page cursor resetting on both element change and search
  text change.
- **F6** — ``ElementManager`` now tracks every cloned ``THREE.Material``
  it creates in ``colorByDirect``/``colorBy`` via a
  ``createdMaterials`` set and disposes them in ``resetColors`` and
  ``dispose``, plugging a slow GPU memory leak that grew every
  time the user toggled status colouring.

### Levels filter — rename "Storeys" → "Levels", real Level support
The BIM filter panel labelled the storey filter "Storeys" but
Revit users overwhelmingly think in terms of "Level" (the actual
Revit property name).  Worse, when the upload row had no top-level
``storey`` column the filter would silently miss elements whose
level was buried inside the ``properties`` JSONB blob — common
for Revit Excel exports where "Level" lives as a Type Parameter,
not a column.

- Backend ``_rows_to_elements`` (``bim_hub/router.py``) now calls
  a new ``_extract_storey(row, props)`` helper that first checks
  the top-level column (already aliased from ``level``,
  ``base_constraint``, ``host_level_name``, etc. via
  ``_BIM_COLUMN_ALIASES``), then falls back to a 20-key
  case-insensitive scan of the ``properties`` blob: ``Level``,
  ``Base Level``, ``Reference Level``, ``Schedule Level``,
  ``Host Level``, ``IFCBuildingStorey``, ``Geschoss``, ``Etage``…
- ``_normalise_storey()`` coerces literal ``"None"`` / ``"<None>"``
  / ``"null"`` / ``"-"`` / ``"—"`` strings to None so they don't
  pollute the filter panel with a fake "None (586)" bucket.  This
  was visible in screenshots from real Revit exports.
- Frontend ``BIMFilterPanel.tsx`` rename: "Storeys" → "Levels",
  "by Storey" → "by Level", "No storeys detected" → "No levels
  detected", search placeholder updated.  i18n keys renamed to
  ``bim.filter_levels``, ``bim.filter_no_levels``,
  ``bim.filter_group_level`` with English defaults.  Internal
  state keys (``state.storeys``, ``el.storey``, API param
  ``storey=``) are unchanged so saved filter groups and the
  ``BIMQuantityRulesPage`` form continue to work.

### BIM converter preflight + one-click auto-install
Uploading a ``.rvt`` file at ``/bim`` previously consumed 18 MB of
upload, saved it to disk, then silently failed with "Could not
extract elements from this CAD file" when ``find_converter('rvt')``
returned None and ``process_ifc_file`` returned an empty result.
Two issues stacked: no preflight, and the frontend hardcoded a
generic English error string instead of using the backend's
``model.error_message``.  All the converter-install plumbing
already existed (``GET /api/v1/takeoff/converters/`` +
``POST /api/v1/takeoff/converters/{id}/install/``) but the BIM
upload page never used it.

**Backend preflight (``bim_hub/router.py``)** — new
``_NEEDS_CONVERTER_EXTS = {".rvt", ".dwg", ".dgn"}``.  At the very
top of ``upload_cad_file``, before ``await file.read()``, we call
``find_converter(ext.lstrip("."))`` and refuse the upload up-front
with ``status="converter_required"`` (200 OK, not error) when the
binary is missing.  The response includes ``converter_id`` and
``install_endpoint`` so the frontend can route the user straight
into the install flow without wasting an upload roundtrip.  The
success-path response was extended with ``error_message``,
``converter_id``, and ``install_endpoint`` fields so the frontend
can render the actual reason instead of guessing.

**Real DDC repo (``takeoff/router.py``)** — the converter
auto-installer was pointing at a non-existent
``ddc-community-toolkit`` releases URL.  Rewritten to walk the
real ``datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN``
repository via the GitHub Contents API, recursively listing
``DDC_WINDOWS_Converters/DDC_CONVERTER_{FORMAT}/`` and downloading
each file from ``raw.githubusercontent.com``.  Verified live
against the upstream repo: 175 files / 598 MB for RVT, 143 / 241
MB IFC, 252 / 218 MB DWG, 252 / 217 MB DGN.

- Files install into per-format directories
  (``~/.openestimator/converters/{ext}_windows/``) so each
  converter's bundled Qt6 DLLs and Teigha format readers do not
  collide with other formats.
- Downloads run in parallel via a ``ThreadPoolExecutor(max_workers=8)``
  — RVT goes from ~5 minutes sequential to ~30-60 seconds without
  tripping GitHub abuse detection.
- Path traversal defence runs BEFORE any network IO so a
  hostile listing fails fast instead of partway through 600 MB of
  downloads.
- Atomic rollback on partial failure (``shutil.rmtree`` of the
  per-format dir) so a half-installed converter can not confuse
  ``find_converter`` on the next call.
- Linux returns ``platform_unsupported: true`` with the apt commands
  needed to install ``ddc-rvtconverter`` etc. via the upstream
  apt source ``pkg.datadrivenconstruction.io``.  We deliberately
  do NOT auto-shell-out to ``sudo apt`` from a web handler.
- macOS / other platforms get a graceful "convert to IFC first"
  message — the IFC text parser works on every platform.

``find_converter`` (``boq/cad_import.py``) extended to probe both
the new per-format Windows install dirs and the Linux apt install
paths (``/usr/bin/ddc-{ext}converter``,
``/usr/local/bin/ddc-{ext}converter``) so installed converters
are picked up instantly with no service restart.

**Frontend banner + install prompt (``BIMConverterStatusBanner.tsx``,
``InstallConverterPrompt.tsx``, +233 LOC in ``BIMPage.tsx``)** —
new amber banner above the BIM page lists every converter that
needs installation with name, real size in MB, and a one-click
Install button.  Installs run via React Query mutation with
spinner, success toast, and automatic banner refetch on completion.

When the user drops a ``.rvt`` / ``.dwg`` / ``.dgn`` file and the
converter is missing, a pre-upload guard intercepts the drop and
opens ``InstallConverterPrompt`` instead of starting the upload —
no megabytes wasted.  The prompt shows the converter name, real
size from the GitHub-derived metadata, and an "Install &
auto-retry upload" button that on success replays the original
upload with the saved file bytes.  The previously hardcoded
"Could not extract elements" error string is replaced with the
backend's actual ``error_message``.  27 new i18n keys (all with
English ``defaultValue``) so the UI works today without a
translation pass.

Backwards compatible: older backends that do not return
``converter_id`` fall through to the legacy ``needs_converter``
toast.

### Verification
- Backend ``ruff check`` clean across every v1.4.7-touched file
- 16/16 tests in the BIM converter preflight + cross-module + PI
  action suites passing in 34.5s
- 963 unit tests passing in the costmodel/finance/full_evm suite
- ``check_version_sync.py`` passes at 1.4.7
- ``integrity_check.py`` passes (23 hits)
- Frontend ``tsc --noEmit`` exit 0, zero errors
- Live test of GitHub Contents API directory walk against the real
  ``cad2data-Revit-IFC-DWG-DGN`` repo confirms ``RvtExporter.exe``
  is reachable and 175 files enumerate cleanly

## [1.4.6] — 2026-04-11

### Security — IDOR fixes (driven by wave-2 deep audit)

#### S1 — Contacts module: query scoping
Three TODO(v1.4-tenancy) markers in ``contacts/router.py`` flagged
that ``Contact`` had no ``tenant_id`` and any authenticated user with
``contacts.read`` could read **every** contact in the database.  The
get/patch/delete endpoints already had a ``_require_contact_access``
gate, but the list/search/by-company/stats endpoints were unscoped.
Fixed by threading an ``owner_id`` parameter through repository →
service → router that filters on the ``created_by`` proxy column.
Admins still bypass and see the global view.

- ``contacts/repository.py`` — ``list()``, ``stats()``, ``list_by_company()``
  all accept an optional ``owner_id`` filter
- ``contacts/service.py`` — same
- ``contacts/router.py`` — list/search/stats/by-company endpoints now
  resolve the caller's role via ``_is_admin()`` and pass either
  ``user_id`` (non-admin) or ``None`` (admin) as the owner filter

#### S2 — Collaboration module: permissions + entity allowlist
``collaboration/router.py`` had **zero** permission checks.  No
``RequirePermission`` decorator on any endpoint, no entity access
validation.  Any authenticated user could list / create / edit /
delete comments and viewpoints across project boundaries.  Fixed by:

- New ``collaboration/permissions.py`` — registers
  ``collaboration.read`` (Viewer), ``collaboration.create`` /
  ``.update`` / ``.delete`` (Editor)
- New ``collaboration/__init__.py`` ``on_startup`` hook that wires
  the registration
- ``collaboration/router.py`` rewritten to add ``RequirePermission``
  to all 7 endpoints
- New ``_ALLOWED_ENTITY_TYPES`` allowlist (16 entries: project, boq,
  document, task, requirement, bim_element, etc.) — any other value
  is rejected at the router boundary so we never persist orphaned
  metadata.  Fixes the prior bug where ``entity_type='unicorn'``
  was silently accepted.

### Cross-module wiring

#### S3 — Notifications subscriber framework
The notifications module had ``create()`` and ``notify_users()`` since
day one but **nothing in the platform actually called them** —
contacts / collaboration / cde / transmittals / teams all silent on
mutations.  Created ``notifications/events.py`` with a declarative
``_SUBSCRIPTIONS`` map and an ``on_startup`` hook that wires the
event bus on module load.  Initial subscriptions:

- ``boq.boq.created`` → notify the creator (info)
- ``meeting.action_items_created`` → notify each task owner
  (task_assigned) for the items that ACTUALLY produced a Task row
- ``cde.container.state_transitioned`` → notify the actor (info)
- ``bim_hub.element.deleted`` → audit echo skeleton (no-op until
  the upstream payload includes a user-id target)

Adding a new event trigger is now a one-line entry in
``_SUBSCRIPTIONS`` — keeps the cross-module event topology auditable
from a single grep.

#### C5 — Raw SQL → ORM in 3 remaining cross-link sites
v1.4.4 fixed the bim_hub upload cross-link.  The same fragile
hand-rolled ``INSERT INTO oe_documents_document`` via ``text()``
pattern still existed in three other places — replaced each with a
clean ``Document(...)`` ORM insert that picks up timestamps + defaults
from the Base mixin and stays in sync with any future schema
migration:

- ``punchlist/router.py:288`` (punch photos)
- ``meetings/router.py:967`` (meeting transcripts)
- ``takeoff/router.py:1855`` (takeoff PDFs)

All four cross-link sites now use the ORM.  Verified with
``grep -c "INSERT INTO oe_documents_document"`` returning 0 across
all four files.

#### C6 — Meetings: stop publishing event when task creation fails
``meetings/service.py::complete_meeting`` wrapped task creation from
action items in a try/except that swallowed all errors with
"best-effort" logging — and then published
``meeting.action_items_created`` regardless.  Downstream subscribers
(notifications, vector indexer) were told the work was done even
when zero tasks made it into the DB.  Fixed by:

- Per-action-item isolation: a single failed item no longer aborts
  the others
- Track ``created_action_items`` and ``failed_action_items``
  separately, surface both via the response
- Only publish the event when at least one task actually persisted;
  payload now carries ``created_count`` / ``failed_count`` so
  notification subscribers can show "3 of 5 tasks created"

### Project Intelligence

#### T1.1 — Collector wires 4 missing modules
``project_intelligence/collector.py`` collected state from 9 domains
(BOQ, schedule, takeoff, validation, risk, tendering, documents,
reports, costmodel) but was **completely blind** to requirements,
bim_hub, tasks, and assemblies.  ``ProjectState`` had no fields for
them.  Score lied — a project with perfect BOQ but zero requirements
got a falsely high score.  Fixed by:

- New ``RequirementsState`` / ``BIMState`` / ``TasksState`` /
  ``AssembliesState`` dataclasses
- New ``_collect_requirements`` / ``_collect_bim`` / ``_collect_tasks``
  / ``_collect_assemblies`` parallel collectors
- Each new collector uses cross-dialect SQL (works on SQLite +
  PostgreSQL) and falls back to default state on exception with a
  WARNING-level log instead of the previous DEBUG-level swallow
- ``collect_project_state`` now ``asyncio.gather``s 14 collectors
  instead of 10
- ``ProjectState`` exposes 4 new fields so the scorer / advisor /
  dashboard can surface gaps like "no requirements defined" or
  "BIM elements not linked to BOQ"

Smoke-tested against the live database — collectors return real
counts for the 5 most recent projects (which include data created
by the v1.4.5 cross-module integration tests).

### Verification
- Backend ``ruff check`` clean across every file touched in v1.4.6
- 174 unit + integration tests passing (vector adapters x7 +
  property matcher + requirements↔BIM cross-flow + BIM processor)
- ``scripts/check_version_sync.py`` passes at 1.4.6
- ``scripts/integrity_check.py`` passes (10 hits)

### Deferred to v1.4.7 / v1.5.0
- ``project_intelligence/actions.py`` 3 of 8 actions still dead code
  (run_validation / match_cwicr_prices / generate_schedule fall back
  to redirect lying about execution)
- ``costmodel`` vs ``full_evm`` redundancy — both compute EVM with
  different logic, frontend uses neither, needs strategic decision
- ``costmodel`` PV approximation flaw (BAC × time_elapsed%)
- BIM frontend correctness: 14 findings in BIMPage.tsx + 5 link
  modals (200-item caps, modal pattern inconsistency, race
  conditions, type-unsafe casts)
- Assembly ``total_rate`` invalidation on CostItem.rate change
- ``create_vector_routes()`` factory + reduce ~250 LOC duplication
- Trailing-slash audit of 12 broken integration tests
- Test coverage push: 0 tests for costmodel/finance/full_evm and 6
  of 8 shared infra modules

## [1.4.5] — 2026-04-11

### Fixed — deep-audit cut driven by 3 parallel sub-agents

Three multi-agent deep audits of the recently-added v1.4.x modules
(requirements, project_intelligence, erp_chat, vector_index, bim_hub
element groups, quantity maps, assemblies) flagged 40+ findings.
This cut tackles the cross-module-correctness ones — fixes that
make existing features actually do what they advertise — plus the
biggest test-coverage holes.

#### Cross-module data integrity
- **Orphaned BIM element ids cleaned up on element delete**.  Three
  of five cross-module link types denormalise BIM ids into JSON
  arrays (Task.bim_element_ids, Activity.bim_element_ids,
  Requirement.metadata_["bim_element_ids"]) instead of FK tables.
  The FK-based ones (BOQElementLink, DocumentBIMLink) cleaned
  themselves up via ``ondelete='CASCADE'``; the JSON ones leaked
  stale references **forever**, confusing the BIM viewer's
  "linked tasks/activities/requirements" panel and every reverse
  query helper.  New ``bim_hub.service._strip_orphaned_bim_links``
  runs INLINE on the active session inside ``bulk_import_elements``
  and ``delete_model``, so the cleanup shares the upstream
  transaction (no SQLite write-lock contention) and rolls back
  atomically on failure.  Integration test
  ``test_orphan_bim_ids_stripped_on_element_delete`` pins the
  behaviour end-to-end.
- **Requirement embeddings now include pinned BIM element ids**.
  After ``link_to_bim_elements`` fired the linked_bim event the
  vector indexer re-embedded the row, but
  ``RequirementVectorAdapter.to_text()`` never read
  ``metadata_["bim_element_ids"]`` so the embedding was unchanged
  and semantic search like *"requirements linked to roof elements"*
  returned zero.  ``to_text()`` now appends a sample of up to 5
  pinned ids; the full list still lives in metadata.  5 new unit
  tests cover present/empty/missing/non-dict metadata edge cases.

#### Hacks → real implementations
- **Property filter ``_matches`` is now type-aware**.  The dynamic
  element-group predicate used exact equality
  ``props.get(key) == value`` and the quantity-map rule engine
  used ``str(value).lower()``.  Both silently failed on multi-valued
  IFC properties (e.g. ``materials = ["steel", "concrete"]``
  vs filter ``materials = "steel"`` returned False because list !=
  string).  New shared helper
  ``BIMHubService._property_value_matches`` handles strings via
  fnmatch, lists via membership/intersection, dicts via recursive
  containment, and ``None`` via explicit "must not be set"
  semantics.  20 unit tests pin every branch.
- **Quantity map applies surface skipped (element, rule) pairs**.
  ``_extract_quantity`` returned ``None`` when the source property
  was missing and the loop just ``continue``'d, so estimators saw
  unexpectedly-empty BOQ populations with no clue why.  Skips are
  now collected with a structured ``reason`` (``missing_property``
  or ``invalid_decimal``), surfaced via two new fields on
  ``QuantityMapApplyResult`` (``skipped_count`` + ``skipped[]``),
  and the service logs a warning with the first skip when any are
  detected.

#### Concurrency
- **Per-collection ``asyncio.Lock`` on ``reindex_collection``**.
  Two concurrent reindex requests against the same vector
  collection (e.g. startup auto-backfill racing an admin-triggered
  ``POST /vector/reindex/``) could interleave purge + index ops
  and leave the store in an inconsistent state with partial
  indexes, duplicate ids, and ghost rows.  Now serialised by a
  module-level ``dict[str, asyncio.Lock]`` lazily populated via
  ``_get_reindex_lock``.  Reindexes against DIFFERENT collections
  still run in parallel — the locks are per-name.

#### Missing CRUD
- **``PATCH /requirements/{set_id}``** — lets users rename a set,
  edit its description, change source type, or update workflow
  status without delete-and-recreate (which lost history and any
  BIM/BOQ links the set's requirements owned).  Project re-assignment
  is intentionally NOT supported — sets are project-scoped at
  creation.
- **``POST /requirements/{set_id}/requirements/bulk-delete/``** —
  delete up to 500 requirements in a single transaction.  Ids
  belonging to a different set are silently skipped; the response
  carries ``deleted_count`` and ``skipped_count`` so the UI can
  surface "deleted N of M" mismatches.  Each successful delete
  fires the standard ``requirements.requirement.deleted`` event.

#### Type discipline
- **``GateResult.score`` migrated from ``String(10)`` to ``Float``**.
  The column stored a stringified percentage like ``"85.5"`` but
  the Pydantic schema and router both treated it as a float —
  every write went through ``str(score)`` and every read through
  ``float(score_raw)``.  Worse, ``ORDER BY score DESC`` returned
  ``"9.5"`` above ``"85.0"`` because string comparison happens
  character by character (any "top N gate runs" report was
  silently wrong).  New Alembic migration ``b2f4e1a3c907`` runs an
  idempotent batch-alter that coerces unparseable rows to ``0``
  before the type change.  Service writes a real ``float`` now;
  the router still calls ``float()`` defensively for backward
  compat with un-migrated databases.

#### Test coverage push
- **Unit tests for 7 of 8 vector adapters** (BOQ, Documents, Tasks,
  Risks, BIM elements, Validation, Chat).  Previously only the
  Requirements adapter (added in v1.4.3) had unit coverage; the
  other 7 were untested. **113 new test cases** following the
  canonical template — collection_name singleton, to_text full row
  + empty + None tolerant, to_payload title build + UUID stringify
  + clipping + fallback, project_id_of resolves + None fallback.
- **`backend/tests/unit/test_bim_property_matcher.py`** — 20 tests
  pinning every branch of the new type-aware property matcher.
- **`backend/tests/integration/test_requirements_bim_cross.py`** —
  3rd test ``test_orphan_bim_ids_stripped_on_element_delete``
  drives the full orphan-cleanup flow end-to-end.

#### Frontend i18n compliance
- **BIMPage.tsx hardcoded English strings replaced** with i18n
  keys (deferred from the v1.4.4 frontend audit).  ``UploadPanel``,
  ``NonReadyOverlay``, and the empty-state branch now go through
  ``useTranslation()`` — the HARD rule from CLAUDE.md
  (*"ALL user-visible strings go through i18next. No exceptions."*)
  is honoured across the BIM module.  New ``bim.upload_*`` and
  ``bim.overlay_*`` keys added to ``i18n-fallbacks.ts``.

### Verification
- 113 new unit tests passing across 7 vector adapter files
- 20 new unit tests passing for the BIM property matcher
- 3 integration tests passing for the requirements↔BIM cross-module
  flow including the new orphan-cleanup regression test
- Backend ``ruff check`` clean across every file touched in v1.4.5
- Frontend ``tsc --noEmit`` clean
- ``scripts/check_version_sync.py`` passes at 1.4.5
- 21 routes mounted under ``/api/v1/requirements/`` (up from 19)

### Deferred to v1.4.6
- ``project_intelligence.collector`` blind to requirements / bim_hub /
  tasks / assemblies — score is currently a partial picture
- ``project_intelligence/actions.py`` 3 of 8 actions are dead code
  (run_validation / match_cwicr_prices / generate_schedule fall
  back to redirect lying about execution)
- Assembly ``total_rate`` invalidation when CostItem.rate changes
- ``create_vector_routes()`` factory + reduce ~250 LOC of duplicated
  ``vector/status`` and ``vector/reindex`` endpoints
- Trailing-slash audit of 12 broken integration tests
- requirements.list_by_bim_element PostgreSQL JSONB fast path

## [1.4.4] — 2026-04-11

### Fixed — backend hardening cut

A focused stability + correctness pass driven by a multi-agent quality
audit of the v1.4.x backend.  No new user-visible features; the goal
is "everything that already exists works at scale and stays honest
about what version it is".

#### Memory hazard in vector auto-backfill
- ``backend/app/main.py::_auto_backfill_vector_collections`` used to
  ``SELECT *`` from each indexed table on startup, materialise the
  full result set into a Python list, and only THEN slice it down to
  ``vector_backfill_max_rows``.  On a 2M-row production deployment
  that allocated **gigabytes** of RAM at startup before the cap could
  even kick in.
- The new implementation issues a cheap ``SELECT COUNT(*)`` first to
  decide whether reindexing is needed, then pulls only the capped
  number of rows with ``LIMIT`` applied at the SQL level.  Memory
  usage is now bounded by ``vector_backfill_max_rows`` regardless of
  table size.
- Side benefit: the per-collection ``_load_X`` closures collapsed
  into a single declarative ``backfill_targets`` registry — 8 modules
  × ~12 LOC of copy-pasted loaders → one tuple per collection.  Total
  reduction in main.py: ~80 LOC.  This is also the foundation
  v1.4.5's full ``create_vector_routes()`` factory will build on.

#### Deprecated ``datetime.utcnow()`` removed (Python 3.14 readiness)
- ``datetime.utcnow()`` was deprecated in Python 3.12 and becomes a
  hard error in 3.14.  Replaced with ``datetime.now(UTC)`` across
  **8 call sites**: ``boq/router.py:2991``, ``documents/service.py:475``,
  ``tendering/router.py:378``, ``project_intelligence/collector.py:680``,
  ``punchlist/router.py:299``, ``meetings/router.py:984``,
  ``takeoff/router.py:1872``, plus ``bim_hub/router.py:869`` (which
  also got rewritten as part of the next bullet).
- The original quality audit only flagged 4 of these 8 sites; a
  follow-up grep across the whole backend caught the remaining 4.

#### Raw SQL → ORM in BIM upload cross-link
- ``bim_hub/router.py::upload_cad`` was using a hand-rolled
  ``INSERT INTO oe_documents_document`` via ``text()`` to create the
  Documents-hub cross-link entry.  The parameter binding was safe in
  practice but the pattern was fragile (any future schema change to
  ``Document`` would silently break the cross-link without test
  coverage), and it shipped a stray ``datetime.utcnow()``.
- Replaced with a clean ``Document(...)`` ORM insert that picks up
  every default + timestamp from the model and the ``Base`` mixin.
  The cross-link stays a best-effort try/except — it's convenience
  glue, not load-bearing on the main upload flow.

#### Functional ruff cleanup
- ``F401`` unused imports removed from ``boq/events.py``,
  ``project_intelligence/collector.py`` (``uuid``),
  ``project_intelligence/scorer.py`` (``Callable``),
  ``search/router.py`` (``Depends``).
- ``F541`` f-string without placeholders fixed in
  ``project_intelligence/advisor.py:399``.
- ``B905`` ``zip()`` without ``strict=`` fixed in
  ``costs/router.py:1742``.  This is the cost-database resource
  loader — without ``strict=True`` an array length drift would
  silently truncate component rows mid-import and corrupt the
  assembly composition with no audit trail.  ``strict=True`` raises
  immediately so the error is visible.
- Ruff style issues (``UP037``, ``UP041``, ``I001``) auto-fixed in
  ``costs/router.py``, ``project_intelligence/router.py`` /
  ``schemas.py``, ``documents/service.py``.

#### Version-sync CI guard (NEW)
- ``backend/pyproject.toml`` silently drifted from ``frontend/package.json``
  for **four minor versions** (v1.3.32 → v1.4.2 all shipped with
  the Python package stuck on ``1.3.31``, so ``/api/health`` lied
  about which version users were actually getting because
  ``Settings.app_version`` reads from ``importlib.metadata``).  v1.4.3
  retro-fixed the literal but left the door open for the same gap.
- New ``scripts/check_version_sync.py`` reads both files plus the top
  entries of ``CHANGELOG.md`` and ``frontend/src/features/about/Changelog.tsx``,
  and exits non-zero on any mismatch.  Wired into:
  - ``.pre-commit-config.yaml`` as a local hook on the four version
    files (so a bump that touches only one file is rejected
    before it can be committed)
  - ``.github/workflows/ci.yml`` as a dedicated ``version-sync`` job
    that runs in parallel with backend + frontend lanes
- Tested negatively (script catches drift) and positively (passes
  with all four files at ``1.4.4``).

### Verification
- Backend ``ruff check`` clean across every file touched in v1.4.4
- Backend ``python -m uvicorn app.main:create_app --factory`` boots
  cleanly via ``app.router.lifespan_context`` smoke test:
  57 modules loaded, 217k vectors indexed, no startup errors
- ``scripts/check_version_sync.py`` passes at ``1.4.4`` after the
  bump (negative test confirmed it would fail at ``1.4.99``)

### Deferred to v1.4.5
- BIMPage.tsx i18n compliance (11+ hardcoded English strings flagged
  by frontend audit; needs sub-component ``useTranslation()``)
- ``create_vector_routes()`` factory + reduce ~250 LOC of duplicated
  ``vector/status`` and ``vector/reindex`` endpoints across 8 modules
- Trailing-slash audit of ``test_cross_module_flows.py`` and
  ``test_api_smoke.py`` (12 failing tests, all caused by missing
  trailing slashes — ``redirect_slashes=False`` is intentional,
  fixes a CORS 307 issue with the frontend)
- Deep-dive audit of recently-added modules (``requirements``,
  ``erp_chat``, ``project_intelligence``, ``bim_hub`` element groups,
  cross-module linking infrastructure) — looking for hacks,
  half-baked logic, missing cross-module wiring

## [1.4.3] — 2026-04-11

### Added — Requirements ↔ BIM cross-module integration

The Requirements module is now the **5th cross-module link type** on
BIM elements, mirroring the existing BOQ / Documents / Tasks /
Schedule activities pattern.  Requirements (EAC triplets — Entity,
Attribute, Constraint) are the bridge between client intent and the
executed model — pinning them to BIM elements lets estimators trace
*"this wall has fire-rating F90 because requirement REQ-042 says so"*
in one click.

#### Backend
- **New `oe_requirements` vector collection** (8th total).  Embeds the
  EAC triplet plus unit / category / priority / status / notes via
  the new ``RequirementVectorAdapter`` in
  ``backend/app/modules/requirements/vector_adapter.py``.  Multilingual
  by default — works across English / German / Russian / Lithuanian /
  French / Spanish / Italian / Polish / Portuguese.
- **Requirements service event publishing** — new ``_safe_publish``
  helper, plus standardised ``requirements.requirement.created /
  updated / deleted / linked_bim`` events on every CRUD and link
  operation.
- **`link_to_bim_elements()` service method** — additive by default
  (merges new ids with the existing array), pass ``replace=true`` to
  overwrite.  Stored under ``Requirement.metadata_["bim_element_ids"]``
  so no schema migration is needed.
- **`list_by_bim_element()` reverse query** — every requirement that
  pins a given BIM element id, scoped to a project for performance.
- **New router endpoints** in ``requirements/router.py``:
  - ``PATCH /requirements/{set_id}/requirements/{req_id}/bim-links/``
  - ``GET  /requirements/by-bim-element/?bim_element_id=&project_id=``
  - ``GET  /requirements/vector/status/``
  - ``POST /requirements/vector/reindex/``
  - ``GET  /requirements/{set_id}/requirements/{req_id}/similar/``
- **`RequirementBrief` schema** in ``bim_hub/schemas.py`` — mirrors
  the relevant subset of ``RequirementResponse`` to avoid a circular
  import.  Added to ``BIMElementResponse.linked_requirements``.
- **`BIMHubService.list_elements_with_links()` Step 6.5** — loads
  every requirement in the project once and filters in Python on the
  ``metadata_["bim_element_ids"]`` array, same cross-dialect pattern
  as the task and activity loops.  Return tuple now has 8 entries.

#### Frontend
- **New `BIMRequirementBrief` interface** + ``linked_requirements``
  field on ``BIMElementData``.
- **New `LinkRequirementToBIMModal`** — mirrors ``LinkActivityToBIMModal``
  exactly: loads every requirement set in the project, flattens
  requirements into a searchable list, click → PATCH the bim-links
  → invalidate the bim-elements query.  Color-coded by priority
  (must / should / may) and status (verified / conflict / open).
- **"Linked requirements" section in BIMViewer details panel** —
  violet themed, slots between "Schedule activities" and the
  semantic similarity panel.  Renders entity.attribute + constraint
  + priority badge + click-to-open.
- **BIMPage wiring** — new ``linkRequirementFor`` state +
  ``handleLinkRequirement`` / ``handleOpenRequirement`` handlers,
  modal mount, props passed to ``<BIMViewer>``.
- **RequirementsPage badge** — the expanded row now shows a
  "Pinned BIM elements" cell with the count read from
  ``metadata.bim_element_ids``.  Click navigates to ``/bim?element=...``
  with the first pinned element preselected.
- **RequirementsPage deep link** — parses ``?id=<requirement_id>``,
  fans out detail fetches across every set in the project to find
  the owning set, switches to it and expands the row.  Strips the
  param after one shot so refresh doesn't reapply.
- **GlobalSearchModal facet support** — fuchsia color for the new
  Requirements pill, ``oe_requirements`` mapped to ``/requirements?id=``
  in ``hitToHref``.
- **VectorStatusCard** picks up the new ``oe_requirements`` collection
  via the existing ``REINDEX_PATH`` table — admins can trigger a
  reindex from Settings.
- **Auto-backfill on startup** now indexes the requirements collection
  alongside the other 7 (capped by ``vector_backfill_max_rows``).

### Fixed (polish bundled into this cut)
- ``backend/pyproject.toml`` had silently drifted from the frontend
  version since v1.3.31 — every bump from v1.3.32 → v1.4.2 updated
  ``frontend/package.json`` but not the Python package.  ``/api/health``
  has therefore been reporting ``version: "1.3.31"`` across the entire
  v1.4.x series because ``app.config.Settings.app_version`` reads from
  ``importlib.metadata.version("openconstructionerp")``.  Bumped
  directly to ``1.4.3`` so the next deploy reports the real version.
- ``bim_hub/router.py`` CAD upload handler referenced ``cad_path`` and
  ``cad_dir`` variables that were never defined after the storage
  abstraction was introduced — the IFC/RVT processing branch crashed
  with ``NameError`` on every upload attempt (``ruff`` flagged the
  same issue as ``F821``).  Replaced the ghost variables with a
  ``tempfile.TemporaryDirectory`` workspace: the upload is materialised
  locally for the sync processor, any generated geometry is uploaded
  back through ``bim_file_storage.save_geometry`` before the tempdir
  is cleaned up, and the Documents hub cross-link now stores the real
  storage key returned by ``save_original_cad`` instead of the phantom
  ``cad_path``.
- ``SimilarItemsPanel`` no longer claims to support requirements —
  the generic panel only knows the item id, but the requirement
  similar endpoint is nested under the parent set
  (``/requirements/{set_id}/requirements/{req_id}/similar/``), so
  it needs both.  Requirement similarity is reachable only from the
  set-scoped detail page; the generic cross-module panel would have
  returned 404 for every call.  Removed the placeholder URL and the
  ``'requirements'`` entry from ``SimilarModuleKind``.

### Verification
- 718 total routes mounted across 57 loaded modules (real count from
  ``module_loader.load_all`` + ``fastapi.routing.APIRoute`` inspection)
- 8 vector collections, all with real adapters and reindex endpoints
- Frontend ``tsc --noEmit`` clean
- Backend ``ruff check`` clean across every file touched in v1.4.3
- New tests: unit coverage for ``RequirementVectorAdapter``
  (``to_text`` / ``to_payload`` / ``project_id_of``) plus an integration
  test that drives ``PATCH /bim-links/`` → ``GET /by-bim-element/``
  → ``GET /models/{id}/elements/`` (Step 6.5) end-to-end

## [1.4.2] — 2026-04-11

### Security
- **SQL injection guard in LanceDB id-quoting** — every row id passed
  to ``_lancedb_index_generic``, ``_lancedb_delete_generic`` and the
  legacy ``_lancedb_index`` cost-collection upsert is now re-parsed as
  a strict ``uuid.UUID`` before being interpolated into the
  ``id IN (...)`` filter via the new ``_safe_quote_ids`` helper.
  Defence-in-depth — the adapter layer always passes UUIDs from
  SQLAlchemy ``GUID()`` columns, so a parse failure now indicates a
  bug or attack and the row is silently dropped.
- **Qdrant search payload mutation** — ``vector_search_collection``
  was using ``payload.pop()`` to extract reserved fields, which
  mutated the qdrant client's cached result objects.  Replaced with
  ``get()`` + a non-mutating dict comprehension.

### Fixed
- **Token-aware text clipping** — ``_safe_text`` now uses the active
  SentenceTransformer's tokenizer (when available) to clip at 510
  tokens instead of the previous 4000-character cap.  4000 chars
  routinely exceeded the 512-token cap of small SBERT models, causing
  silent in-model truncation that lost meaningful tail content.
  Falls back to the character cap when the tokenizer isn't available.
- **Frontend deep links now actually work** — `hitToHref` was
  generating route formats that no destination page parsed:
  - BOQ now uses ``/boq/<boqId>?highlight=<positionId>`` matching the
    real ``BOQEditorPage`` route + query.
  - DocumentsPage parses ``?id=<docId>`` and auto-opens the preview.
  - TasksPage parses ``?id=<taskId>``, scrolls the matching card into
    view, and adds a 2.5s ring highlight.
  - RiskRegisterPage parses ``?id=<riskId>`` and opens detail view.
  - BIMPage parses ``?element=<elementId>`` and selects the element
    once the elements list resolves.
  - Chat hits navigate to ``?session=<sessionId>`` from the new chat
    payload field.
  Each deep-link parser strips the query param after one shot so a
  refresh doesn't keep re-applying it.

### Added — BIM cross-module gap closure
- **`GET /api/v1/bim_hub/coverage-summary/?project_id=...`** — new
  aggregation endpoint returning ``{elements_total,
  elements_linked_to_boq, elements_costed, elements_validated,
  elements_with_documents, elements_with_tasks,
  elements_with_activities}`` plus matching percentages.  Each count is
  a single SELECT in the same async session — no N+1.  Documents,
  tasks, activities and validation are fetched defensively so a
  missing optional module doesn't 500 the call.
- **Dashboard `BIMCoverageCard`** — new widget rendering 6 progress
  bars + a headline percentage (avg of all 6 metrics).  Hides itself
  entirely on projects with zero BIM elements so non-BIM workflows
  stay clean.  Color-coded by completeness (green ≥75% / amber ≥40% /
  rose otherwise).
- **BOQ position BIM badge is now clickable** — the `OrdinalCellRenderer`
  blue pill that shows the linked BIM element count is no longer a
  read-only `<span>`; it's a `<button>` that navigates to
  ``/bim?element=<first_id>``.  Estimators can finally jump from a
  BOQ row to the 3D model element it was created from in one click.
- **Schedule activity BIM badge** — Gantt activity rows now render a
  small amber pill with the count of pinned BIM elements when
  ``activity.bim_element_ids`` is non-empty.  Click navigates to the
  BIM viewer with the first pinned element preselected.  Closes the
  4D-schedule reverse-nav gap.
- **BIM Quantity Rules page — Suggest from CWICR** — when a rule's
  target is "auto-create", the editor now exposes a "Default unit
  rate" field plus a one-click "Suggest from CWICR" button that calls
  ``/api/v1/costs/suggest-for-element/`` with the rule's filter
  context (element_type_filter, name, property_filter material) and
  prefills the top match.  The rate persists into
  ``boq_target.unit_rate`` and is read by the apply path
  (``_auto_create_position_for_rule``) so the new BOQ position lands
  fully priced — no second pass in the BOQ editor.

### Verification
- 766 total routes mounted (up from 765 in v1.4.1).  New routes:
  ``/api/v1/bim_hub/coverage-summary/``.
- Frontend ``tsc --noEmit`` clean.
- Backend ``ruff check`` clean across every file touched in v1.4.2
  (4 pre-existing warnings in unrelated bim_hub/router.py CAD upload
  and BOQ-access-verifier code paths are not from this sweep).
- ``_safe_quote_ids`` smoke-tested against literal SQL injection
  payloads and confirms attacker strings are dropped.

## [1.4.1] — 2026-04-11

### Added
- **Validation reports vector adapter** — `oe_validation` collection now
  has a real adapter (`backend/app/modules/validation/vector_adapter.py`),
  event subscribers wired to the new `validation.report.created/deleted`
  publishes, and `/api/v1/validation/vector/status/`,
  `/vector/reindex/`, `/{id}/similar/` endpoints.  Semantic search across
  validation history (e.g. "find reports about missing classification
  codes") now works.
- **Chat messages vector adapter** — `oe_chat` collection now has a real
  adapter (`backend/app/modules/erp_chat/vector_adapter.py`).  User and
  assistant messages with non-empty content are auto-indexed via the new
  `erp_chat.message.created` event publish in
  `service.py:_persist_messages`.  Long-term semantic memory for the
  AI advisor and per-message similarity search both now functional.
- **Auto-backfill on startup** — new `_auto_backfill_vector_collections`
  helper in `backend/app/main.py` runs as a detached background task
  during the lifespan startup.  For each of the 7 collections it
  compares the live row count to the indexed count and backfills any
  missing rows (capped by `vector_backfill_max_rows=5000` per pass to
  protect against multi-million-row tenants).  Disable with
  `vector_auto_backfill=False` in settings.  This closes the upgrade
  gap where existing v1.3.x BOQ / Document / Task / Risk / BIM / chat
  rows were unsearchable until the user manually called every per-module
  reindex endpoint.
- **Settings → Semantic Search Status panel** — new `VectorStatusCard`
  in `frontend/src/features/settings/`.  Renders a per-collection
  health table fetched from `/api/v1/search/status/` with one-click
  reindex buttons (POST to the matching `/vector/reindex/` route),
  engine + model + dimension + total-vectors badges, connection
  indicator and a "purge first" toggle for embedding-model migrations.

### Fixed
- The `bim_hub.element.updated` event subscription is now documented
  as a forward-compat hook (no current publisher — BIM elements are
  refreshed via the bulk-import path which already publishes
  `created`).  The day a `PATCH /elements/{id}/` endpoint lands, vector
  freshness will work without any wiring change.
- Backend `ruff check` clean across every file touched in this sweep
  (auto-fixed I001 import-order issues in two files).

### Verification
- Full app boot: 765 routes, 34 vector / similar / search routes (up
  from 28 in v1.4.0).  All 7 collections now have real adapters.
- `intfloat/multilingual-e5-small` model loads from HuggingFace cache
  on first encode call — confirmed by Python boot.
- Frontend `tsc --noEmit` clean.

## [1.4.0] — 2026-04-11

### Added
- **Cross-module semantic memory layer** — every business module now
  participates in a unified vector store via the new
  `app/core/vector_index.py` `EmbeddingAdapter` protocol.  Six new
  collections live alongside the existing CWICR cost index:
  `oe_boq_positions`, `oe_documents`, `oe_tasks`, `oe_risks`,
  `oe_bim_elements`, `oe_validation`, `oe_chat`.  All collections share
  the same schema (id / vector / text / tenant_id / project_id / module
  / payload) so the unified search layer can write to any of them
  through one code path.
- **Multilingual embedding model** — switched the default from
  `all-MiniLM-L6-v2` (English-mostly) to `intfloat/multilingual-e5-small`
  (50+ languages, same 384-dim).  CWICR's 9-language cost database now
  ranks correctly across English, German, Russian, Lithuanian, French,
  Spanish, Italian, Polish and Portuguese.  The legacy model is kept as
  a graceful fallback so existing LanceDB tables stay loadable.
- **Event-driven indexing** — every Position / Document / Task / Risk /
  BIM Element create/update/delete event now triggers an automatic
  upsert into the matching vector collection.  No cron jobs, no Celery
  workers, no manual reindex needed for normal operation.  Failures are
  logged and swallowed so vector indexing can never break a CRUD path.
- **Per-module reindex / status / similar endpoints** — every
  participating module now exposes:
  - `GET  /vector/status/` — collection health + row count
  - `POST /vector/reindex/?project_id=...&purge_first=false` — backfill
  - `GET  /{id}/similar/?limit=5&cross_project=true` — top-N most
    semantically similar rows, optionally cross-project
  Live: `/api/v1/boq/`, `/api/v1/documents/`, `/api/v1/tasks/`,
  `/api/v1/risk/`, `/api/v1/bim_hub/elements/`.
- **Unified cross-collection search API** — new `oe_search` module:
  - `GET /api/v1/search/?q=...&types=boq,documents,risks&project_id=...`
    fans out to every selected collection in parallel and merges the
    results via Reciprocal Rank Fusion (Cormack et al., 2009).
  - `GET /api/v1/search/status/` — aggregated per-collection health
  - `GET /api/v1/search/types/` — list of supported short names
- **Cmd+Shift+K Global Search modal** — frontend `GlobalSearchModal`
  with debounced input, facet pills (BOQ / Documents / Tasks / Risks /
  BIM / Validation / Chat) showing per-collection hit counts, current
  project scope toggle, grouped results and click-to-navigate routing.
  Works from any page including text fields so estimators can trigger
  semantic search while editing a BOQ row.
- **`<SimilarItemsPanel>` shared component** — universal "more like this"
  card that drops next to any record with `module="risks" id={...}`.
  Embedded in:
  - Risk Register detail view (cross-project lessons learned reuse)
  - BIM viewer element details panel
  - Documents preview modal (cross-project related drawings)
- **AI Chat semantic tools** — six new tool definitions for the ERP Chat
  agent: `search_boq_positions`, `search_documents`, `search_tasks`,
  `search_risks`, `search_bim_elements`, `search_anything`.  Each tool
  returns ranked hits with score + match reasons and the chat panel
  renders them as compact result cards.  System prompt updated to
  prefer semantic tools for free-text questions.
- **AI Advisor RAG injection** — `project_intelligence/advisor.py`
  `answer_question()` now retrieves the top-12 semantic hits from the
  unified search layer and injects them into the LLM prompt as a
  "Relevant context (semantic retrieval)" block.  The advisor is now a
  proper RAG agent — answers stay anchored in real evidence instead of
  hallucinating from the structured project state alone.

### Architecture
- New foundation file `backend/app/core/vector_index.py` — protocol,
  hit dataclass, RRF fusion, search/find_similar/index_one helpers.
- Multi-collection helpers in `backend/app/core/vector.py` —
  `vector_index_collection`, `vector_search_collection`,
  `vector_delete_collection`, `vector_count_collection` plus the
  `_lancedb_*_generic` and Qdrant equivalents.
- New `backend/app/modules/search/` module with manifest, schemas,
  service and router.
- Per-module `vector_adapter.py` files in `boq`, `documents`, `tasks`,
  `risk`, `bim_hub` — tiny stateless adapters implementing the
  `EmbeddingAdapter` protocol.

### Verification
- 759 total routes mounted; 28 vector / similar / search routes wired
  end-to-end.
- 217 487 CWICR cost vectors auto-loaded from existing LanceDB index on
  startup.
- Frontend `tsc --noEmit` clean.
- Backend imports clean across foundation + 5 modules + unified search
  + 6 new chat tools + advisor RAG.
- Reciprocal Rank Fusion smoke-tested on synthetic rankings.

## [1.3.32] — 2026-04-10

### Added
- **BIM viewer health stats banner** — top-of-viewport multi-pill banner
  shows total elements, BOQ-linked count, validation errors, warnings,
  has-tasks and has-documents counts.  Each pill is clickable and applies
  the matching smart filter to the viewport in one click.
- **Smart filter chips in BIMFilterPanel** — same five health buckets
  exposed as chips at the top of the filter sidebar (errors, warnings,
  unlinked-to-BOQ, has tasks, has documents).  Counts are computed from
  the cross-module link arrays on each element.
- **Color-by status modes** in the BIM viewer — three new colour-by
  options grouped under "By compliance":  🛡️ Validation status (red /
  amber / green), 💰 BOQ link coverage (red unlinked / green linked),
  📄 Document coverage.  Implemented via a new
  `ElementManager.colorByDirect()` helper that paints meshes from a
  fixed palette without rebuilding materials.
- **Cost auto-suggestion for BIM elements** — new
  `POST /api/v1/costs/suggest-for-element/` endpoint ranks CWICR cost
  items by classification overlap, element-type / material / family
  keyword matches and discipline tag overlap.  Each result carries a
  0..1 confidence score and human-readable match reasons.
- **Cost suggestion chips in AddToBOQModal** — the "Create new position"
  tab now fetches the top-5 ranked rates for the clicked element and
  renders them as one-click chips with code, description, unit rate and
  confidence dot.  Clicking a chip populates description / unit /
  unit_rate from the matching cost item — no manual lookup needed.

## [1.3.31] — 2026-04-11

### Added
- **Inline create-from-element modals** in BIM viewer — three new
  modals (`CreateTaskFromBIMModal`, `LinkDocumentToBIMModal`,
  `LinkActivityToBIMModal`) let the user create new tasks, link existing
  documents, and link existing schedule activities to a BIM element
  WITHOUT leaving the viewer.
- **Validation ↔ BIM per-element rules engine** — new
  `POST /api/v1/validation/check-bim-model` endpoint runs universal
  BIM rules (wall has thickness, structural has material, fire-rating
  present, MEP has system, etc.) against every element in a model.
  Per-element results eager-loaded into `BIMElementResponse.validation_results`
  + worst-severity rollup in `validation_status`.
- **Per-element validation badge** in the BIM viewer details panel,
  colour-coded by worst severity.
- **Tasks page** — `TaskCard` now renders a "Pinned to N BIM element(s)"
  badge with click-to-jump navigation.

### Fixed
- `ValidationReportResponse` pydantic schema collision with SQLAlchemy
  `MetaData()` class-level registry — switched to `validation_alias`.

## [1.3.30] — 2026-04-11

### Added
- **BIM viewer cross-module deep integration** — element details panel now
  shows four collapsible link sections in one place: Linked BOQ Positions
  (existing), Linked Documents (drawings/RFIs/photos), Linked Tasks
  (defects/issues), Schedule Activities (4D timeline). Each section has
  count badges, clicking any row navigates to the target detail page.
- **Documents ↔ BIM** — new `oe_documents_bim_link` table + GET/POST/DELETE
  endpoints under `/api/v1/documents/bim-links/`. Bidirectional querying.
  Eager-loaded into `BIMElementResponse.linked_documents`.
- **Tasks ↔ BIM** — new `Task.bim_element_ids` JSON column. PATCH
  `/api/v1/tasks/{id}/bim-links` + reverse query. Eager-loaded into
  `BIMElementResponse.linked_tasks`.
- **Schedule ↔ BIM** — wired up the dormant `Activity.bim_element_ids` field
  with PATCH endpoint and `/api/v1/schedule/activities/by-bim-element/`
  reverse query. Eager-loaded into `BIMElementResponse.linked_activities`.
- **Documents preview modal** — new "Linked BIM elements" footer strip with
  click-to-navigate chips.

## [1.3.29] — 2026-04-11

### Changed
- **Chat page** — removed the redundant "ERP AI Assistant" top bar. The
  app's main layout already provides a header; the chat-specific bar
  duplicated UI and didn't match the rest of the site palette. Clear
  chat now lives in the input bar.
- **Release process** — CHANGELOG.md now mirrors the in-app
  `Changelog.tsx` so the GitHub release workflow can extract the right
  section when a tag is pushed (the workflow at `.github/workflows/release.yml`
  reads `## [VERSION]` patterns from this file).

## [1.3.28] — 2026-04-11

### Added
- **Universal Building / Other split** in BIM filter — every category
  is classified by its semantic bucket and rendered in either a
  "real building elements" section (chips at top) or a collapsible
  "Annotations & analytical" section (closed by default). Works
  zero-curation for any project.
- **Pretty category names** for ~150 well-known Revit categories
  ("Curtainwallmullions" → "Curtain Wall Mullions", "Doortags" → "Door Tags").
  Anything not in the table passes through with first-letter
  capitalised — no wrong algorithmic word splits.

### Fixed
- BIM filter "None" element_type (the 6 048 Revit-ingest junk rows in
  the demo) now classified as noise.
- Headless test verdict baseline comparison.

## [1.3.27] — 2026-04-11

### Added
- **3 grouping modes** in BIM filter via segmented control:
  **By Category** (flat, default), **By Type Name** (Revit Browser
  hierarchy), **Buckets** (semantic).

## [1.3.26] — 2026-04-11

### Fixed
- **"Add to BOQ" 500** — the v1.3.22 backend agent's ownership check
  referenced `position.project_id` but Position has no such column;
  the project lives on the parent BOQ via `position.boq_id`. Fix:
  rewrote `_verify_boq_position_access` as a single-row SELECT joining
  Position → BOQ.

## [1.3.25] — 2026-04-11

### Added
- **Saved Groups panel section** in BIMFilterPanel — collapsible,
  one-click apply, hover-revealed link/delete actions.
- Headless test full saved-group lifecycle (save → list → apply → delete).

## [1.3.24] — 2026-04-11

### Added
- **Pluggable storage backend** (`app/core/storage.py`) with
  `LocalStorageBackend` (default) and `S3StorageBackend` (opt-in via
  `pip install openconstructionerp[s3]`). Supports MinIO / AWS / Backblaze /
  DigitalOcean Spaces.
- **BIM Element Groups** — new `oe_bim_element_group` table for saved
  selections. Dynamic groups recompute members from a filter; static
  groups freeze the snapshot.
- **SaveGroupModal** for saving the current filter as a named group.
- **Architecture doc** — `docs/BIM-STORAGE-ARCHITECTURE.md` with the
  three-layer design + migration path.

## [1.3.23] — 2026-04-11

### Added
- Headless deep test (`frontend/debug-bim.cjs`) extended with 4 new
  test groups verifying every UI surface from v1.3.22.
- `ElementManager.batchMeshesByMaterial()` — three.js BatchedMesh
  collapse for big-model perf (gated at 50 000+ meshes pending GPU
  visibility-sync work).

### Fixed
- Sidebar `nav.bim_rules` translation key.

## [1.3.22] — 2026-04-11

### Added
- **BIM ↔ BOQ linking** end-to-end. Backend embeds `boq_links` in
  element response; `apply_quantity_maps` actually persists; `Position.cad_element_ids`
  auto-syncs on link CRUD.
- **Add to BOQ modal** — Link to existing position OR create new with
  pre-filled quantities, single-element and bulk modes.
- **Quick takeoff** button in filter panel — bulk-link visible elements.
- **BIM Quantity Rules page** at `/bim/rules` — dedicated UI for rule-based
  bulk linking.
- **Selection sync store** — BOQ row click highlights linked BIM
  elements orange and vice versa.
- **Toolbar rework** — removed broken 4D/5D stubs, added camera
  presets (Fit / Iso / Top / Front / Side), grid toggle.

## [1.2.0] — 2026-04-09

### Added
- **Project Completion Intelligence (PCI)** — AI co-pilot: project scoring (A-F), domain analysis, critical gaps, achievements, AI advisor
- **Architecture Map** — interactive React Flow visualization of 54 modules, 98 models, 128 dependency edges
- **Dashboard project cards** — KPI metrics per project (BOQ value, tasks, RFIs, safety, progress)
- **Sidebar badge counts** — live open item counts for Tasks, RFI, Safety
- **Data Explorer** — professional landing page with feature cards and upload zone
- **BIM filmstrip layout** — models at bottom, delete button, stale cleanup endpoint
- **NCR → Change Order** traceability banner with navigation
- **UserSearchInput** integrated into Meetings, Tasks, Inspections, RFI forms
- **Document Hub cross-links** — Takeoff, Punchlist, Meeting transcripts auto-appear in Documents
- **Swagger UI** accessible at /api/docs (SPA catch-all fixed)
- **Change password** returns new JWT tokens (user stays logged in)
- **Configurable rate limiter** via API_RATE_LIMIT, LOGIN_RATE_LIMIT env vars

### Fixed
- **CORS 307 redirects eliminated** — redirect_slashes=False + 369 backend routes with trailing slash
- **All form field mismatches** — 15+ modules aligned frontend↔backend
- **Correspondence crash** — to_contact_ids field name mismatch
- **BOQ Create Revision** — MissingGreenlet fix + trailing slash
- **BOQ Import** — source enum (cost_database, smart_import, assembly)
- **BOQ costs→positions** — ordinal XX.YYY format, no conflicts
- **Finance invoice list** — endpoint URL fix
- **Procurement PO list** — endpoint URL + paginated response
- **Safety create buttons** — visible in empty state
- **Project cascade delete** — child records cleaned up
- **Notifications** fire on task creation
- **Photo gallery** — served without auth for img tags
- **Meetings 500** — corrupt UUID data fixed
- **Paginated response handling** — 7 modules with defensive Array.isArray checks
- **Project context guards** — 6 modules show warning when no project selected
- **Unified create buttons** — 14 pages standardized to "+ New X" pattern

### Changed
- CAD converter references unified under DDC cad2data
- Integrations moved from sidebar to Settings
- Architecture Map in Modules section
- GitHub button moved to header
- Version bumped to 1.2.0

## [1.1.0] — 2026-04-09

### Added
- **User Management page** (`/users`) — invite users, change roles (admin/manager/editor/viewer), activate/deactivate, per-user module access matrix with custom role names
- **UserSearchInput** component — searchable dropdown for selecting team members across all modules
- **Document Hub cross-linking** — photos and BIM files automatically appear in Documents module with source tags (`photo`, `bim`, `site`, `ifc`, etc.)
- **CDE Link Document modal** — searchable document picker instead of redirect to /documents page
- **20-language translations** for User Management module

### Fixed
- **All form field mismatches** — systematic audit and fix of 15+ modules (Tasks, Meetings, RFI, NCR, Submittals, Inspections, Correspondence, Contacts, Transmittals, Finance, Safety, Procurement)
- **Trailing slash CORS issue** — all GET list endpoints now use trailing slash to prevent 307 redirect → CORS block
- **Contacts display** — field names aligned with backend (`first_name`/`last_name`, `primary_email`, `country_code`)
- **Procurement PO list** — fixed endpoint URL (`/purchase-orders` → `/`) and paginated response handling
- **Transmittals list** — fixed paginated response handling
- **Photo gallery** — photos now served without auth requirement for `<img>` tags
- **Safety incidents** — POST route trailing slash fix
- **Meetings 500 error** — fixed corrupt UUID in chairperson_id
- **NCR status enum** — `open` → `identified` to match backend
- **Inspection types** — expanded to include all construction-standard types
- **Documents upload** — clear "Select project first" warning when no project selected, clickable drop zone
- **BIM upload** — inline progress bar, only IFC/RVT accepted

### Changed
- Backend enum patterns expanded for inspections and correspondence
- Contacts `prequalification_status` removed invalid `none` value
- Tasks `task_type` `info` → `information`, `priority` `medium` → `normal`

## [0.9.1] — 2026-04-07

### Added — Integration Hub expansion
- **Discord webhook connector** — send embed notifications to Discord channels, with color, fields, and action link
- **WhatsApp Business connector** (Coming Soon) — Meta Cloud API v20.0 template messages, pending Meta Business verification
- **Integration Hub redesign** — 14 integration cards grouped into 3 categories (Notifications, Automation, Data & Analytics)
- **n8n / Zapier / Make cards** — guidance for connecting workflow automation tools via our existing webhook system
- **Google Sheets card** — export BOQ/cost data to Sheets-compatible Excel format
- **Power BI / Tableau card** — connect BI tools to our REST API for custom dashboards
- **REST API card** — link to interactive OpenAPI docs at /api/docs

### Fixed
- Deep audit fixes for cross-module event flows
- Integration type schema extended to support `discord` and `whatsapp` connectors

## [0.9.0] — 2026-04-07

### Added — 30 new backend modules (Phase 9–22 master plan)
- **Internationalization Foundation** — MoneyValue (35 currencies, Decimal arithmetic), LocalizedStr (JSONB multi-language), AcceptLanguage middleware, i18n_data (ISO constants for 30 countries), ECB exchange rate fetcher, 198 countries with 20-language translations, 30 work calendars, 70 tax configurations
- **Module System v2** — enable/disable modules at runtime, persistent state, dependency tree API, admin REST endpoints
- **Contacts Directory** — unified contacts for clients, subcontractors, suppliers, consultants with prequalification tracking
- **Audit Log** — system-wide entity change tracking with admin API
- **Notifications** — in-app notifications with i18n keys, unread count, mark-read, per-user listing
- **Comments & Viewpoints** — threaded comments on any entity with @mentions, PDF/BIM viewpoints
- **Teams** — project teams with membership roles and entity visibility grants
- **Meetings** — meeting management with attendees, agenda, action items, auto-numbering
- **CDE** — ISO 19650 Common Data Environment with 4-state workflow (WIP→Shared→Published→Archived)
- **Transmittals** — formal document distribution with issue/lock, acknowledge/respond
- **OpenCDE API** — BuildingSMART Foundation API 1.1 + BCF 3.0 compliance (13 endpoints)
- **Finance** — invoices (payable/receivable), payments, project budgets with WBS, EVM snapshots
- **Procurement** — purchase orders, goods receipts with quantity tracking
- **Inspections** — quality inspections with checklists, pass/fail/partial results
- **Safety** — incidents and observations with 5×5 risk scoring
- **Tasks** — 5-type taxonomy (task/topic/information/decision/personal) with Kanban board
- **RFI** — requests for information with ball-in-court, cost/schedule impact
- **Submittals** — multi-stage review workflow (submit→review→approve)
- **NCR** — non-conformance reports with root cause analysis
- **Correspondence** — formal communication register
- **BIM Hub** — BIM models, elements, BOQ links, quantity maps, model diffs
- **Reporting** — KPI snapshots, 6 report templates, report generation
- **8 Regional Packs** — US (AIA/CSI/RSMeans), DACH (DIN 276/GAEB/VOB/HOAI), UK (NRM2/JCT/NEC4/CIS), Russia (GESN/FER/TER), Middle East (FIDIC/Hijri/VAT GCC), Asia-Pacific, India, LatAm
- **3 Enterprise Packs** — approval workflows, deep EVM (ETC/EAC/VAC/TCPI), RFQ bidding pipeline
- **CPM Engine** — forward/backward pass, float calculation, critical path, calendar-aware

### Added — Projects & BOQ expansion
- Project: WBS, milestones, project code, type, phase, address, contract value, dates, budget
- BOQ: estimate type, lock/unlock, revision chain, base date, WBS linkage

### Added — 13 new frontend pages
- Contacts, Tasks (Kanban), RFI, Finance (4 tabs), Procurement, Safety, Meetings, Inspections, NCR, Submittals, Correspondence, CDE, Transmittals

### Added — Shared UI components
- SVG Gantt chart (day/week/month zoom, task bars, dependency arrows, critical path, drag-to-reschedule)
- Three.js BIM Viewer (discipline coloring, raycaster selection, properties panel)
- NotificationBell (API-backed, 30s polling, dropdown, mark-read)
- CommentThread (threaded, nested, @mentions, inline edit)
- MoneyDisplay, DateDisplay, QuantityDisplay (locale-aware formatting)
- Regional Settings page (timezone, measurement, paper, date/number format, currency)

### Added — Inter-module event wiring
- Meeting action items → auto-create tasks
- Safety high-risk observation → notification to PM
- Invoice paid → update project budget actuals
- PO issued → update project budget committed
- RFI/NCR cost impact → variation flagging

### Added — i18n
- 568 translation keys across 20 languages for all new modules
- Professional construction terminology in DE, FR, ES, RU, ZH, AR, JA

### Added — Testing
- 50 integration tests covering critical API flows
- Total: 697 backend tests passing

### Fixed
- Removed competitor product names from codebase
- Standardized all new pages to match established layout patterns

## [0.8.0] — 2026-04-07

### Added — Professional BOQ features
- **Custom Columns** with 7 one-click presets — Procurement (Supplier, Lead Time, PO Number, PO Status), Notes, Quality Control (QC Status, Inspector, Date), Sustainability (CO₂, EPD, Material Source), **German Tender Style** (KG-Bezug, Lohn-EP, Material-EP, Geräte-EP, Sonstiges-EP, Wagnis %), **Austrian Tender Style** (LV-Position, Stichwort, Lohn-Anteil %, Aufschlag %, Lieferant), **BIM Integration** (IFC GUID, Element ID, Storey, Phase). Manual form for everything else. Live fill-rate progress bar shows how complete each column is.
- **Renumber positions** with gap-of-10 scheme (`01`, `01.10`, `01.20`, `02`, `02.10`) — matches the professional German/Austrian tender output convention. Lets you insert `01.15` later without renumbering everything else. New `POST /boqs/{id}/renumber` endpoint + toolbar button.
- **Excel round-trip with custom columns** — supplier, notes and procurement values are now exported to .xlsx and survive a full import → edit → export cycle. Number-typed columns are formatted as numbers in the spreadsheet.
- **Project Health bar** on Project Detail — circular progress with 5 checkpoints (BOQ created → positions added → all priced → validation run → no errors) and a single "Next step" button that always points at the first incomplete item.

### Added — Security hardening (from QA / pentest report)
- **Strong password policy** — 8+ chars, ≥1 letter, ≥1 digit, blacklist of 24 common/leaked passwords. `password`, `12345678` and friends are now rejected with a clear 422.
- **Login rate limit** — 10 attempts per minute per IP, returns 429 with `Retry-After` header.
- **JWT freshness check** — old tokens are invalidated automatically when the user changes password (via `password_changed_at` column + `iat` comparison in `get_current_user_payload`).
- **Security headers middleware** — `X-Frame-Options`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy` (relaxed for SPA, excluded from /docs and /redoc), `Strict-Transport-Security` (HTTPS only).
- **Schedule date validation** — `start_date > end_date` is now rejected with a clear 422 (Pydantic `model_validator`).
- **PDF upload magic-byte check** — `/takeoff/documents/upload` now rejects JPGs/HTML/etc. renamed to `.pdf`.
- **Cross-user permission boundary verified** — User B gets 403 on every attempt to read/modify/delete User A's data (end-to-end test in place).

### Added — UX & frontend
- **User-friendly API error messages** — `ApiError` now extracts the actual FastAPI `detail` string instead of `"API 500: Internal Server Error"`. Covers FastAPI 422 validation arrays, generic envelopes, and per-status fallbacks (400/401/403/404/409/413/422/429/500/502/503/504). Network errors and `AbortError` get their own friendly text. 14 i18n keys × 21 locales added.
- **Modernized update notification** in the sidebar — gradient emerald/teal/cyan card with pulsing Sparkles icon, grouped highlights (New / Fixed / Polished), in-app changelog link (scrolls to `/about#changelog`), GitHub release link, change-count badge. Caches the GitHub response in `localStorage` (1h TTL) so multi-tab sessions don't burn the unauthenticated rate limit.
- **Continue your work** card on Dashboard — gradient card showing the most recently updated BOQ with name, project, position count and grand total; one click jumps back to the editor.
- **Role-aware ChangeOrders Approve button** — hidden for non-admin/manager roles; an "Awaiting approval" amber badge appears instead, so users no longer click into a 403.
- **Highlight unpriced positions** in the BOQ grid — subtle amber background and 3px left border on rows where `qty > 0` but `unit_rate = 0`.
- **Duplicate-name guard** for new projects — typing a name that matches an existing project shows an amber warning and requires a second click to confirm.
- **Single source-of-truth** for app version — `package.json` is the only place to edit. Sidebar, About page, error logger, update checker and bug-report params all import `APP_VERSION` from a Vite-injected define.
- **Changelog** entries filled in for v0.5.0, v0.6.0, v0.7.0 (previously the in-app history jumped from v0.4 → v0.7 with no notes).
- **Accessibility** — `<h1>` (sr-only) on /login and /register, `name` and `id` attributes on all auth inputs, `aria-label` on password show/hide buttons, dead `_SavedSessionsList` removed.
- **Keyboard shortcuts dialog** — removed misleading shortcuts that browsers reserved (`Ctrl+N`, `Ctrl+Shift+N`); fixed buggy "Ctrl then Shift then V" separator; added `g r` → Reports and `g t` → Tendering navigation sequences.

### Fixed — backend critical bugs
- **`ChangeOrders POST /items` returned 500 for every payload** — `MissingGreenlet` on `order.code` after `_recalculate_cost_impact` (which calls `expire_all`) triggered a lazy load in async context. Fix: capture identifying fields before the recalc, then `refresh(item)` after.
- **`5D /generate-budget` returned 500 on missing `boq_id`** — bare `uuid.UUID(str(...))` raised on empty body. Fix: validate explicitly with try/except → 422 on bad input. Auto-pick the most recently updated BOQ when omitted.
- **Project soft-delete was leaky** — `DELETE /projects/{id}` set `status=archived`, but the project still came back from `GET`, list, and BOQ list. Fix: `get_project` gains `include_archived` flag (default `False`); `list_projects` defaults to `exclude_archived=True`; BOQ verify treats archived as 404.
- **Requirements module tables were missing on fresh installs** — module models were not imported in `main.py`/`alembic env.py`, so `Base.metadata.create_all()` skipped them. Fix: added the missing imports; same for 6 other previously missing module models.
- **Custom Columns SQLAlchemy JSON persistence** — only the FIRST added column was being saved due to in-place dict mutation. Fix: build a fresh `dict` and call `flag_modified(boq, "metadata_")` to defeat value-based change detection.
- **Custom column edit silently rewrote `total`/`unit_rate`** — `update_position` re-derived pricing from `metadata.resources` on every metadata patch. Fix: only re-derive when `quantity` actually changed OR the resources list itself differs from what's stored. Critical correctness fix for resource-priced positions.

### Changed
- The visible "Quick Start Estimate" flow now uses **gap-of-10 ordinals** by default — new positions get `01.40`, `01.50` etc. instead of `01.4`, `01.5`.
- `update_position` is stricter about when it touches pricing fields — only quantity/rate/resource changes recalculate `total`. Pure metadata patches leave the existing total intact.

## [0.2.1] — 2026-04-04

### Fixed
- **CRITICAL: pip install -e ./backend** — `[project.urls]` was placed before `dependencies` in pyproject.toml, breaking editable installs and PyPI builds
- **CRITICAL: BOQ Duplication crash** — MissingGreenlet error when duplicating BOQ (eagerly capture ORM attributes before session expiry)
- **CRITICAL: CWICR import 500 error** — ProcessPoolExecutor fails on Windows/uvicorn; replaced with asyncio.to_thread
- **Security: Path traversal** — Document/takeoff download endpoints now resolve symlinks and sandbox-check paths
- **Security: CORS** — Block wildcard `*` origins in production mode with warning
- **Security: Login enumeration** — Deactivated accounts return same 401 as invalid credentials; password policy not revealed before auth
- **Security: Catalog price factor** — Bounded to `0 < factor ≤ 10` with explicit validation
- **Docker quickstart** — Dockerfile copies full backend (incl. README.md for hatchling), installs `[server]` extras, creates frontend/dist dir, uses development mode
- **Alembic migration** — Replaced broken init migration (DROP non-existent tables) with no-op baseline
- **Nginx** — Added CSP, HSTS, Permissions-Policy security headers
- **35 test errors** — Marked standalone test_full_platform.py with pytest.mark.skip

### Added
- Version number (v0.2.0) displayed in sidebar footer
- "Run Setup Wizard" link in welcome modal for re-onboarding
- Comparison table in README (vs commercial estimating suites)
- Estimation workflow diagram in README
- Security section in README
- Validation & Compliance and Guided Onboarding sections in README
- Trademark disclaimer on comparison table

### Changed
- CLI command renamed from `openestimate` to `openconstructionerp`
- DDC Toolkit → DDC cad2data in all references
- README screenshots use real PNG files (not placeholder JPGs)

### Removed
- 11 development screenshot JPGs from repository root
- Test failure PNG from frontend/test-results/

## [0.1.0] — 2026-03-30

### Added
- **BOQ Editor** — Hierarchical Bill of Quantities with AG Grid, inline editing, keyboard navigation
- **Resource Management** — Material, labor, equipment resources per position with Catalog Picker
- **Cost Database** — CWICR 55,000+ cost items across 11 regional databases (US, UK, DE, FR, ES, PT, RU, AE, CN, IN, CA)
- **Resource Catalog** — Searchable catalog with materials, labor, equipment, operators
- **20 Regional Standards** — DIN 276, NRM, MasterFormat, GAEB, DPGF, GESN, GB/T 50500, CPWD, Birim Fiyat, Sekisan, Computo Metrico, STABU, KNR, Korean Standard, NS 3420, URS, ACMM, CSI/CIQS, FIDIC, PBC
- **42 Validation Rules** — 13 rule sets: boq_quality, din276, gaeb, nrm, masterformat, sinapi, gesn, dpgf, onorm, gbt50500, cpwd, birimfiyat, sekisan
- **4D Schedule** — Gantt chart with CPM, dependencies, resource assignment
- **5D Cost Model** — Earned Value Management (SPI, CPI, EAC), S-curve, budget tracking
- **Risk Register** — Risk matrix (probability x impact), mitigation strategies
- **Change Orders** — Scope changes with cost/schedule impact, approval workflow
- **Tendering** — Bid packages, subcontractor management, bid comparison
- **Reports** — 12 report templates (PDF, Excel, GAEB XML, CSV)
- **Document Management** — Upload, categorize, search project files
- **AI Quick Estimate** — Generate BOQ from text, photo, PDF, Excel, CAD/BIM
- **AI Cost Advisor** — Chat interface for cost questions with database context
- **AI Smart Actions** — Enhance descriptions, suggest prerequisites, escalate rates, check scope
- **7 AI Providers** — Anthropic, OpenAI, Gemini, OpenRouter, Mistral, Groq, DeepSeek
- **20+ Languages** — Full i18n: EN, DE, FR, ES, PT, RU, ZH, AR, HI, TR, IT, NL, PL, CS, JA, KO, SV, NO, DA, FI
- **Dark Mode** — Full dark theme with system preference detection
- **Onboarding Wizard** — 7-step setup: Language, Cost DB, Catalog, Demo Projects, AI, Finish
- **5 Demo Projects** — Berlin (DIN 276), London (NRM), Houston (MasterFormat), Paris (DPGF), Dubai (FIDIC)
- **Backup & Restore** — Export/import user data as ZIP with manifest
- **Version Updates** — Automatic GitHub release checking with sidebar notification
- **SQLite Auto-Migration** — Seamless schema upgrades without data loss
- **Error Logging** — Anonymized error reports with PII scrubbing
- **Command Palette** — Ctrl+K search across pages, projects, BOQs
- **Keyboard Shortcuts** — Full keyboard navigation (?, Ctrl+N, Ctrl+Shift+N, etc.)
- **Locale-Aware Units** — Language-specific measurement units (Stk, sht, ge, etc.)

### Infrastructure
- FastAPI backend with 17 auto-discovered modules
- React 18 + TypeScript + Vite frontend
- SQLite (dev) / PostgreSQL (prod)
- LanceDB vector search (168K+ vectors)
- Modular plugin architecture
- AGPL-3.0 license

### Security
- JWT authentication with bcrypt password hashing
- Role-based access control (RBAC)
- CORS middleware with configurable origins
- Input validation via Pydantic v2
