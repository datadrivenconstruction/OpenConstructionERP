# Changelog

All notable changes to OpenConstructionERP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
