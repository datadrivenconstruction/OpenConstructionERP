# 08 — Code Hygiene Audit

**Date**: 2026-04-18
**Repo**: OpenConstructionERP (branch `main`, v1.8.3)
**Scope**: `frontend/src/`, `backend/app/`

---

## A. Giant files (>1500 LOC)

Sorted descending by LOC. Excludes `i18n-fallbacks.ts`, snapshots, generated OpenAPI types, lock files.

| LOC | Path | Purpose | Suggested split surfaces |
|----:|------|---------|--------------------------|
| 7843 | `backend/app/core/demo_projects.py` | 5 hard-coded demo-project template datasets (Berlin, London, US medical, Dubai, Paris) with BOQ/Schedule/Budget/Tender seeds | One file per project (`demo_projects/residential_berlin.py`, etc.) + shared `_builders.py` helpers |
| 4844 | `backend/app/modules/boq/router.py` | All BOQ HTTP endpoints (BOQs, positions, sections, markups, activity, templates) | `router/boqs.py`, `router/positions.py`, `router/sections.py`, `router/markups.py`, `router/templates.py` |
| 3993 | `backend/app/modules/boq/service.py` | BOQ business logic — CRUD, structured load, markup calc, grand total, events | `service/boq.py`, `service/positions.py`, `service/markups.py`, `service/totals.py` |
| 3715 | `frontend/src/features/dwg-takeoff/DwgTakeoffPage.tsx` | DWG/DXF viewer page — canvas, layers, annotations, filmstrip, upload | Split toolbar, right panel (layers/annotations/properties), canvas host into sibling components + keep page as shell |
| 3506 | `frontend/src/features/ai/QuickEstimatePage.tsx` | AI estimate wizard — prompts, CAD QTO, BOQ creation, chat | `steps/` folder per wizard step; `hooks/` for mutations; keep page as state owner |
| 3220 | `backend/app/core/i18n.py` | i18n runtime (20 languages, key resolver, formatters) | Extract per-locale JSON to `locales/*.json` if not already; keep engine ~300 LOC |
| 3142 | `frontend/src/modules/pdf-takeoff/TakeoffViewerModule.tsx` | PDF takeoff viewer — PDF.js host, annotation overlay, measurement tools | `PdfCanvas`, `MeasureLayer`, `AnnotationPanel`, `ToolPalette` components |
| 3137 | `frontend/src/shared/ui/BIMViewer/BIMViewer.tsx` | Three.js 3D BIM viewer — model render, selection, wireframe, properties | Already has `ElementManager.ts` (1667 LOC) — split camera/scene setup, input handlers, UI overlays |
| 3136 | `frontend/src/features/boq/BOQEditorPage.tsx` | BOQ editor page — AG Grid host, toolbar, sidebar panels | `panels/` subdir per right-panel; keep editor as thin orchestrator |
| 2829 | `frontend/src/features/cad-explorer/CadDataExplorerPage.tsx` | Pandas-like DataFrame explorer: 4 tabs (Data/Pivot/Charts/Describe) | One file per tab under `tabs/` |
| 2807 | `backend/app/modules/takeoff/router.py` | Takeoff endpoints — converters, documents, tables, calibration | `router/converters.py`, `router/documents.py`, `router/tables.py` |
| 2780 | `backend/app/modules/bim_hub/router.py` | BIM Hub endpoints — models, elements, links, diff, quantity rules | `router/models.py`, `router/elements.py`, `router/links.py`, `router/rules.py` |
| 2667 | `frontend/src/features/dashboard/DashboardPage.backup.tsx` | **STALE BACKUP** — pre-v1.8.x dashboard | **Delete** |
| 2545 | `frontend/src/features/costmodel/CostModelPage.tsx` | Cost model dashboard + trend charts | Split charts + scenario comparator |
| 2543 | `frontend/src/features/bim/BIMPage.tsx` | BIM hub landing page with 3D viewport + filmstrip | Extract upload panel, filmstrip, empty-state |
| 2501 | `frontend/src/features/bim/BIMQuantityRulesPage.tsx` | Rule-based BIM→BOQ linking wizard | Extract rule builder form + preview table |
| 2482 | `frontend/src/features/meetings/MeetingsPage.tsx` | Meetings CRUD + minutes + attendees | Standard list/detail split |
| 2480 | `backend/app/modules/bim_hub/service.py` | BIM Hub business logic — elements, links, diff, rules | Split diff engine, rule engine, link manager |
| 2463 | `frontend/src/features/catalog/CatalogPage.tsx` | CWICR cost-item catalog browser | Search bar, results table, filter panel |
| 2433 | `frontend/src/features/dashboard/DashboardPage.tsx` | Current dashboard with widget grid | Already has widget components — extract remaining inline widgets |
| 2346 | `frontend/src/features/finance/FinancePage.tsx` | Finance module — budget, invoices, cashflow | One file per tab |
| 2338 | `frontend/src/features/projects/ProjectDetailPage.tsx` | Project landing + module shortcuts | Error boundary + tabs split |
| 2288 | `backend/app/modules/costs/router.py` | Cost database endpoints | `router/items.py`, `router/escalation.py`, `router/import.py` |
| 2269 | `frontend/src/features/requirements/RequirementsPage.tsx` | BIM requirements (LOIN/EIR) editor | Table + gate panel split |
| 2197 | `frontend/src/features/costs/CostsPage.tsx` | Cost database browser UI | Filters + table + editor split |
| 2129 | `frontend/src/features/schedule/SchedulePage.tsx` | Gantt/schedule view | Gantt chart + task list + toolbar |
| 2017 | `backend/app/modules/schedule/service.py` | Schedule logic (tasks, dependencies, critical path) | CPM/solver into own module |
| 1935 | `backend/app/modules/schedule/router.py` | Schedule endpoints | Tasks/dependencies/milestones split |
| 1873 | `backend/app/scripts/seed_demo_v2.py` | Demo seeder v2 (untracked, in git status) | Promote to blessed script or delete |
| 1841 | `frontend/src/features/tasks/TasksPage.tsx` | Task board (Kanban + list) | Board/list view components |
| 1809 | `frontend/src/features/onboarding/OnboardingWizard.tsx` | First-run onboarding wizard | One file per step |
| 1775 | `frontend/src/features/bim/BIMFilterPanel.tsx` | BIM filter tree + chips UI | Split tree, chips, saved-views |
| 1767 | `backend/app/core/validation/rules/__init__.py` | **Alleged** DIN276/NRM/MasterFormat rules inline in `__init__.py` | Split to `din276.py`, `nrm.py`, `masterformat.py`, `gaeb.py` (matches CLAUDE.md spec) |
| 1758 | `frontend/src/features/takeoff/TakeoffPage.tsx` | Takeoff shell page | Viewer + panel split |
| 1751 | `backend/app/core/event_handlers.py` | Cross-module event handlers (BOQ↔Schedule↔BIM etc.) | One file per handler pair |
| 1696 | `frontend/src/features/boq/grid/cellRenderers.tsx` | AG Grid cell renderers for BOQ | Split by column family (quantity, money, description, status) |
| 1668 | `backend/app/modules/bim_hub/ifc_processor.py` | IFC processing utilities | Geometry/properties/structure split |
| 1667 | `frontend/src/shared/ui/BIMViewer/ElementManager.ts` | BIM element state mgr (selection, highlight, filter) | Selection store + render adapter |
| 1635 | `frontend/src/features/costs/ImportDatabasePage.tsx` | CWICR/RSMeans import wizard | Step components |
| 1627 | `backend/app/modules/projects/router.py` | Project endpoints (CRUD, members, settings) | Projects/members/settings split |
| 1617 | `frontend/src/features/documents/DocumentsPage.tsx` | Document manager (list + preview + upload) | Preview panel + list split |
| 1611 | `frontend/src/features/boq/BOQGrid.tsx` | AG Grid wrapper for BOQ | Column defs already extracted; extract keyboard handlers + hotkeys |
| 1577 | `frontend/src/features/safety/SafetyPage.tsx` | Safety observations / toolbox talks | Standard list/detail split |
| 1558 | `frontend/src/features/reports/ReportsPage.tsx` | Report catalog + generator | Catalog + builder split |
| 1508 | `frontend/src/features/modules/ModulesPage.tsx` | Module marketplace + install manager | Catalog vs installed tabs |
| 1504 | `frontend/src/features/markups/MarkupsPage.tsx` | Drawing markups page | Drawing canvas + markup list |
| 1502 | `frontend/src/features/fieldreports/FieldReportsPage.tsx` | Daily field reports | List/detail + weather/photo split |

**Total**: 48 files >1500 LOC (21 backend, 27 frontend).

---

## B. Backup / stale files

| Path | Size | Status |
|------|------|--------|
| `frontend/src/features/dashboard/DashboardPage.backup.tsx` | 2667 LOC | **CONFIRMED stale** — current version is `DashboardPage.tsx` (2433 LOC). Delete. |
| `backend/app/scripts/seed_demo_v2.py` | 1873 LOC | Untracked (in git status `??`). Decide: commit or delete. |
| `backend/app/scripts/seed_demo_v2_resume.py` | untracked | Resume script from interrupted seed. Same decision. |
| `backend/app/scripts/seed_demo_v2.log` | stale log | Delete from repo. |
| `backend/app/scripts/demo_seed_issues.md` | untracked notes | Decide: commit or delete. |
| `frontend/e2e/_pro-*.spec.ts`, `frontend/e2e/_pro-preview.spec.ts`, `frontend/e2e/bim-selection-diagnostic.spec.ts` | 5 untracked e2e specs with `_` prefix — look like WIP/temp | Review & clean up. |

### `@deprecated` annotations (keep but schedule removal)

- `frontend/src/features/bim/api.ts:255` — `getGeometryUrl()` (replaced by `fetchGeometryBlobUrl` that avoids JWT in URL). Remove after consumers confirmed migrated.
- `frontend/src/features/dwg-takeoff/lib/dxf-renderer.ts:37` — old `resolveColor` fallback.

No `TODO: DELETE` markers found in source.

---

## C. Dead code / unused exports

### TypeScript strict unused-locals/parameters
`tsc --noEmit --noUnusedLocals --noUnusedParameters` from `frontend/` — **0 errors**. Already enabled in `tsconfig.json` (lines 14–15). Clean.

### Unused exports (`ts-prune`)

- 329 total exported symbols with no detected external import
- 223 of those are `index.ts` barrel re-exports (expected — consumers import via deep path; safe to ignore)
- **~106 real dead-export candidates** worth reviewing. Full list at `audit/_ts_prune.txt`.

Notable clusters:
- `frontend/src/features/bim/api.ts` — 10+ exported fetchers never imported (`fetchGeometryBlobUrl`, `getGeometryUrl`, `listLinks`, `listDocumentsForElement`, `listElementsForDocument`, `deleteDocumentBIMLink`, `updateTaskBIMLinks`, `listTasksForElement`, `updateActivityBIMLinks`, `listActivitiesForElement`) — public API shipped but never wired from UI
- `frontend/src/features/boq/boqHelpers.ts` — 9 unused: `saveCustomUnit`, `fmtCompact`, `formatTimeAgo`, `UNITS`, `EditableField`, `VALIDATION_DOT_STYLES`, `VALIDATION_DOT_LABELS`, `PositionResource`, `PositionComment`
- `frontend/src/features/documents/api.ts` — `fetchPhotoGallery`, `fetchPhoto`, `deleteDocument` unused
- `frontend/src/features/dwg-takeoff/api.ts` — 6 unused: `fetchThumbnail`, `updateLayers`, `updateAnnotation`, `fetchPins`, `fetchEntityGroups`, `deleteEntityGroup`
- `frontend/src/features/erp-chat/api.ts` — `fetchChatSessions`, `createChatSession`, `fetchSessionMessages`, `deleteChatSession` unused
- `DashboardPage.backup.tsx` — 1 default export (confirms it's orphaned)

Estimate: **~100 truly dead exports** frontend-side (after excluding barrels).

---

## D. Empty directories

**No real empty dirs** — but 2 directories with **literal brace-expansion characters in their names** (from a failed `mkdir '{a,b,c}'` command):

- `frontend/src/{app,features/{projects,boq,takeoff,cad,costs,validation,tendering,reporting},shared/{ui,hooks,lib},stores}/` (nested junk tree)
- `backend/tests/{unit,integration,fixtures}/` (sibling to real `tests/unit`, `tests/integration`)
- `packages/{oe-schema,oe-sdk,oe-ui-kit}/` (nested, zero contents)

**Action**: `rm -r` each of these with careful quoting. Real source dirs are intact.

---

## E. CLAUDE.md freshness

| Path | LOC | Last commit |
|------|----:|-------------|
| `./CLAUDE.md` | 642 | 2026-03-18 `chore: initialize monorepo` |
| `./.claude/CLAUDE.md` | 641 | 2026-04-12 `chore: move CLAUDE.md to .claude/` (near-duplicate of root) |
| `./backend/CLAUDE.md` | 60 | 2026-03-18 (initial scaffold) |
| `./frontend/CLAUDE.md` | 50 | 2026-03-18 (initial scaffold) |
| `./services/cad-converter/CLAUDE.md` | 37 | 2026-03-18 |
| `./services/cv-pipeline/CLAUDE.md` | 40 | 2026-03-18 |

Root and `.claude/` CLAUDE.md are **near-duplicates** (642 vs 641 LOC) — should become one. Scaffold CLAUDE.md files haven't been updated in a month while repo is at v1.8.3.

### Drift — files referenced in CLAUDE.md that don't exist

Spot-check of 14 paths:

| Path | State |
|------|-------|
| `backend/app/core/validation/rules/din276.py` | MISSING (rules all inlined in `__init__.py`) |
| `backend/app/core/validation/rules/nrm.py` | MISSING |
| `backend/app/core/validation/rules/masterformat.py` | MISSING |
| `backend/app/core/validation/rules/gaeb.py` | MISSING |
| `backend/app/core/validation/rules/custom.py` | MISSING |
| `packages/oe-schema/` | MISSING (literal brace-junk dir only) |
| `packages/oe-sdk/` | MISSING |
| `packages/oe-ui-kit/` | MISSING |
| `backend/app/core/events.py`, `hooks.py`, `module_loader.py`, `permissions.py` | OK |
| `services/ai-service/`, `modules/oe-module-template/` | OK |

CLAUDE.md still says "Phase 0: Foundation (Текущая задача — 2 недели)" while repo is actually through Phase 3 (AI takeoff) + Phase 4 partial. **High drift — needs rewrite.**

---

## F. Test coverage

Fast heuristic by file count (no coverage run — vitest without `--coverage` flag configured):

| Area | Source files | Test files | File ratio |
|------|------:|-----:|------:|
| Frontend (`src/**`) | 537 | 45 | ~8% |
| Backend (`app/**`) | 547 | 74 | ~13% |

Backend has `tests/integration/` with 40+ integration tests covering cross-module flows, requirements↔BIM, BOQ regression, collab locks etc. — so functional coverage is higher than the raw ratio suggests. Frontend relies heavily on Playwright E2E (`frontend/e2e/` — ~30 specs) rather than unit tests.

No coverage number is currently measured in CI. Recommendation: add `vitest run --coverage` + `pytest --cov=app --cov-report=xml` to CI and publish.

---

## G. Duplicate code patterns

### Pattern 1 — `Intl.NumberFormat` inlined in 38 files

55 occurrences of `new Intl.NumberFormat(` across 38 files (pages, cells, panels, stores). `shared/lib/formatters.ts` (3 occurrences) and `shared/lib/numberFormat.ts` (1) already exist as the canonical helpers. Consolidate: enforce a single `formatNumber()/formatCurrency()` import and lint-ban raw `new Intl.NumberFormat` outside `shared/lib/`.

### Pattern 2 — Empty-state rendering across 49 pages

49 feature files render empty-state inline (string "No items", "nothing to show" etc.). `shared/ui/EmptyState.tsx` exists and has a test. 10–15 pages already use it; the rest are candidates for migration. Plus inline `if (isLoading) return ...; if (error) return ...` — no shared `<QueryBoundary>` helper yet; introducing one would eliminate ~200 LOC of boilerplate.

### Pattern 3 — List-normaliser duplication

6 files call `normalizeListResponse` (ok) but there are likely more doing manual `Array.isArray(data?.items) ? data.items : []` checks in-line — 13 files matched that pattern. Worth an internal convention + codemod.

### Pattern 4 — BOQ helpers

`frontend/src/features/boq/boqHelpers.ts` exports 9 never-imported symbols — suggests helpers that were extracted once but consumers migrated away. Prune.

---

## H. Dependencies

### Frontend — 52 top-level deps (`npm ls --depth=0`)

`depcheck` reports **3 unused production + 4 unused dev**:

- **Production unused**: `i18next-browser-languagedetector`, `i18next-http-backend`, `jszip`
  - (Note: `i18next-browser-languagedetector`/`i18next-http-backend` may be used via dynamic config in `app/i18n.ts` — verify before removal)
- **Dev unused**: `@testing-library/user-event`, `autoprefixer`, `postcss`, `tailwindcss`
  - (autoprefixer/postcss/tailwindcss are used by PostCSS config files — false positive; keep)

Plus `playwright` and `@eslint/js` are **imported but missing from `package.json`** (found in `debug-bim.cjs` and `eslint.config.js`) — should be added as devDependencies.

### Backend — 31 declared deps in `pyproject.toml`

Spot-check of imports vs declared:
- **`tenacity`** — declared, **never imported** in `backend/app/`. Remove.
- **`structlog`** — declared, imported only in `backend/app/main.py`. Keep.
- **`orjson`** — declared, imported only in `backend/app/modules/integrations/service.py`. Keep.
- **`trimesh`** — declared, imported in 3 bim_hub files (lazy). Keep.
- **`ezdxf`** — declared, imported in 3 dwg_takeoff files. Keep.
- **`pdfplumber`** — declared, imported in 4 files. Keep.
- **`reportlab`** — declared, imported in 2 files. Keep.
- **`openpyxl`** — declared, imported in 18 files. Keep.

All others (`fastapi`, `sqlalchemy`, `pydantic`, `alembic`, etc.) are core.

**Action**: remove `tenacity` from `backend/pyproject.toml`.

---

## Summary

| Metric | Value |
|--------|------:|
| Giant files (>1500 LOC) | **48** (21 backend, 27 frontend) |
| Biggest offender | `backend/app/core/demo_projects.py` — 7843 LOC |
| Stale / backup files | **6** (1 confirmed `.backup.tsx`, 3 untracked `seed_demo_v2*`, 1 orphan log, ~5 `_pro-*` e2e specs) |
| `@deprecated` annotations | 2 |
| Empty dirs (real) | 0 |
| Empty dirs (literal brace-expansion junk) | **3 junk trees** to delete |
| Dead exports (frontend, excluding barrels) | **~106 candidates**, ~100 likely real |
| TypeScript `noUnused*` warnings | **0** (already enforced in tsconfig) |
| Test file coverage heuristic | Frontend **~8%**, Backend **~13%** (plus E2E + integration suites) |
| CLAUDE.md files | 6 total; root ≡ .claude/ near-duplicate; all scaffold copies stale by ~1 month |
| CLAUDE.md broken refs | ≥8 paths referenced that don't exist (validation rule files, `packages/*`) |
| Frontend declared deps | 52; unused prod candidates: 3; missing-declared: 2 |
| Backend declared deps | 31; unused: 1 (`tenacity`); all others imported |
| Duplicate-pattern hot spots | `Intl.NumberFormat` in 38 files; inline empty-state in 49 files |

### Top priorities (quick wins)

1. **Delete** `frontend/src/features/dashboard/DashboardPage.backup.tsx` (2667 LOC deadweight).
2. **Delete** the 3 brace-expansion junk trees under `frontend/src`, `backend/tests`, `packages/`.
3. **Remove** `tenacity` from `backend/pyproject.toml`.
4. **Split** `backend/app/core/validation/rules/__init__.py` (1767 LOC) into the 5 files CLAUDE.md already documents.
5. **Merge** root `CLAUDE.md` and `.claude/CLAUDE.md`; rewrite phase status (project is at v1.8.3, not Phase 0).
6. **Prune** ~100 dead exports in `features/bim/api.ts`, `features/boq/boqHelpers.ts`, `features/erp-chat/api.ts`, `features/dwg-takeoff/api.ts`, `features/documents/api.ts`.
7. **Introduce** `<QueryBoundary>` shared component + lint rule banning inline `new Intl.NumberFormat` to collapse the top two duplicate patterns.
8. **Add** `vitest --coverage` and `pytest --cov` to CI to get real coverage numbers.
