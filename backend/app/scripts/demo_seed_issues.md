# Demo Seed Issues Log

Tracks bugs / blockers / quirks discovered while seeding 5 demo projects
(US, DE, ES, BR, CN). Each entry = one problem worth fixing later in a
post-seed audit pass. Severity tags: `BLOCKER` (seeder cannot continue),
`BUG` (seeder works around it but UI/data is wrong), `POLISH` (cosmetic).

Format per entry:

```
## [SEVERITY] short title
- **Found**: phase/step where the issue surfaced
- **Symptom**: what we observed
- **Workaround**: what the seeder does to keep moving
- **Fix later**: what needs to change in the product code
```

---

## [POLISH] `pt-BR` not registered as locale; only bare `pt` exists
- **Found**: i18n audit (Phase 0)
- **Symptom**: `SUPPORTED_LANGUAGES` and `i18n-fallbacks.ts` only define `pt` (labelled "Português" with BR flag). Pushing `locale: 'pt-BR'` would silently fall back to `en`.
- **Workaround**: Brazilian demo project uses `locale: 'pt'`; `formatters.ts` already maps `pt` → `pt-BR` for Intl formatting (currency, dates).
- **Fix later**: Decide if Brazilian Portuguese should be a separate registered locale (true `pt-BR` strings vs European `pt`) — if yes, add to `SUPPORTED_LANGUAGES` and either alias the bundle or author a distinct one.

## [BUG] Opening a project doesn't switch UI language
- **Found**: i18n audit (Phase 0)
- **Symptom**: `Project.locale` is stored but the UI language is driven entirely by `localStorage['i18nextLng']`. Opening a German demo project shows the chrome in whatever the user last picked.
- **Workaround**: none (data fields like project name and BOQ descriptions still render in the project locale because they're free text).
- **Fix later**: On project open, call `i18n.changeLanguage(project.locale)` (and ideally remember to restore on logout / project switch). Make sure to handle the user-explicit-pick case (don't override if user manually changed locale this session).

## [POLISH] Validation rule sets `masterformat` and `nrm` not registered
- **Found**: Phase 5 — validation, US project planning
- **Symptom**: `app/core/validation/rules/__init__.py` only registers prefixes `boq_quality`, `din276`, `gaeb`. US (MasterFormat) and UK (NRM) projects can only run universal `boq_quality` checks.
- **Workaround**: US demo project's `validation_rule_sets` is `["boq_quality"]` only — the `masterformat` standard is set on the project but never validated against.
- **Fix later**: Author rule set `app/core/validation/rules/masterformat.py` (Division code format, 6-digit CSI codes, division coverage). Same for `nrm.py` if UK localization is on the roadmap.

## [BUG] GET /api/v1/bim_hub/models/{id}/elements/ crashes on specific rows
- **Found**: Phase 3 — CAD-driven BOQ, US project (rstadvancedsampleproject.rvt, 2196 elements)
- **Symptom**: Paging the elements endpoint with `limit=500&offset=1000` returns HTTP 500 (`{"detail":"Internal server error"}`). Narrowing it down, individual rows at offsets 1147 and 1149 (Structural Framing / Beam Analytical) serialize fine individually with `limit=1` sometimes but not always; rows 1140-1166 consistently break at any page size > 1 that covers them. Element records look well-formed in SQLite (properties/quantities are valid JSON).
- **Workaround**: seeder switched `_fetch_elements_tolerant` to recursive subdivision — on 500, halve the window down to `limit=1`; rows that still 500 at 1 get skipped and logged, the rest ingest. US BOQ therefore covers ~2170/2196 elements rather than all 2196.
- **Fix later**: Inspect backend `/elements/` handler and `BIMElementResponse` Pydantic model — a specific property shape (maybe a nested dict with non-string keys, or a very long value) breaks `.model_validate()` when multiple rows are batched. Reproduce with the specific model+offset combo and trace the serialization error in uvicorn logs.

<!-- Demo-session UX findings (browser audit) -->

## [BUG] Switching project in header keeps user on stale deep-link routes
- **Found**: Phase 5 — browser audit, ProjectSwitcher
- **Symptom**: User opens `/boq/:oldBoqId` (or any entity-scoped detail route) and switches project in the header dropdown. `setActiveProject()` only updates the Zustand store — the URL stays pointing at the previous project's BOQ, so the page shows stale data or 404.
- **Workaround**: Fixed in header — added `resolveRouteAfterProjectSwitch(pathname, newId)` that swaps `projectId` in `/projects/:id/*` routes and redirects entity-scoped routes (`/boq/:id`, `/bim/:id`, `/assemblies/:id`, `/takeoff/:id`, `/documents/:id`, …) back to the list route.
- **Fix later**: audit any new entity-detail route added after this — the regex list must be kept in sync.

## [BUG] DWG Takeoff — create annotation sends wrong field names
- **Found**: Phase 5 — browser audit, `/dwg-takeoff`
- **Symptom**: Click any measurement tool on the top toolbar → creating the resulting annotation fails with `HTTP 422: project_id: Field required; annotation_type: Field required`. Frontend was sending `{drawing_id, type, points, …}` but the backend `DwgAnnotationCreate` schema expects `{project_id, drawing_id, annotation_type, geometry: {points, …}, …}`.
- **Workaround**: Fixed in `features/dwg-takeoff/api.ts` (renamed payload fields) and `DwgTakeoffPage.tsx` (pass active `projectId`, wrap points into `geometry`).
- **Fix later**: none — schema is now aligned. Consider a shared OpenAPI-generated type so the drift doesn't recur.

## [BUG] DWG Takeoff — "Link to BOQ" popover button does nothing visible
- **Found**: Phase 5 — browser audit, `/dwg-takeoff` entity click → popover
- **Symptom**: User clicks an entity in the DXF viewer, the `ElementInfoPopover` shows a "Link to BOQ" button. Clicking it only closes the popover and switches the right panel to the Properties tab — which has no BOQ-picker UI. User gets zero confirmation that the link action is wired up.
- **Workaround**: Added an info toast explaining the feature is WIP and pointing at the BOQ editor for now.
- **Fix later**: Implement a BOQ position picker modal. On select, create a `text_pin` annotation at the entity centroid with `linked_boq_position_id=<picked>`. Backend already accepts `linked_boq_position_id` in `DwgAnnotationCreate`; payload type in `api.ts` needs that field too.

## [BUG] GET /api/v1/bim_hub/<project_id>/markups/ → 404
- **Found**: Phase 5 — API audit script spot check across 5 projects
- **Symptom**: Calling `/api/v1/boq/markups/?project_id=<id>` returns 404 on every project, even though the seeder creates 4 markups per BOQ and `oe_boq_markup` holds 44 rows total.
- **Workaround**: none — we look up markups by BOQ, not by project, so UI already works.
- **Fix later**: either add the list-by-project endpoint or document clearly that markups are BOQ-scoped so API consumers know where to look.

<!-- Entries appended below by seeder during runs -->
