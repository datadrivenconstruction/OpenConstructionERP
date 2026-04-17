# OpenConstructionERP v1.9 Roadmap

**Source:** `~/Downloads/openconstructionerp-17-04-2026.md` (33 items)
**Started:** 2026-04-17
**Principles:** offline-first, max test depth, incremental releases per round, self-directed RFCs
**Policy reference:** `.claude/projects/.../memory/feedback_v19_workflow.md`

---

## 1. Round status

| Round | Version | Status | Items | Done |
|-------|---------|--------|-------|------|
| R0 — Setup | — | 🟢 Done | — | — |
| R1 — Critical bugs | v1.9.0 | 🟡 Ready for release | 8 | 8/8 |
| R2 — Deep research | v1.9.1 | 🔲 Pending | 7 | 0/7 |
| R3 — UX polish | v1.9.2 | 🔲 Pending | 14 | 0/14 |
| R4 — New features | v1.9.3 | 🔲 Pending | 4 | 0/4 |
| R5 — Final VPS deploy | — | 🔲 Pending | — | — |

**R1 progress detail (2026-04-17):**
- 🟢 #2 BOQ resource add — optimistic cache write in `handleCatalogSelect` + `networkMode: 'offlineFirst'` + retry guard on the BOQ query
- 🟢 #5 BOQ list AbortError offline — global QueryClient hardened: `networkMode: 'offlineFirst'`, `navigator.onLine` retry guard, 4xx no-retry (E2E ✓)
- 🟢 #6 Project not-found vs network error — `ApiError.status === 404` distinction, new "Offline / Can't reach server / Retry" UI branch, auto-clear-recents gated on true 404 only (E2E ✓ 2 tests)
- 🟢 #8 Takeoff persistence — URL sync for `activeDocId` on upload / click / remove (backend was already persisting + cross-linking to Documents)
- 🟢 #18 BIM Type Name grouping — filter-panel condition relaxed to always show Link-to-BOQ and Save-Group when any elements visible
- 🟢 #23 BIM Rules — `mutationKey: ['bim-quantity-maps','create']`, awaited invalidate before close, filter now hides project-scoped rules when no active project (E2E smoke ✓)
- 🟢 #27 Tasks category tab — create modal now defaults `task_type` to the active `typeFilter` instead of hard-coded `'task'` (E2E written)
- 🟢 #33 CDE New Container — mutationKey, awaited invalidate, better error surfacing with concrete fallback message + dev `console.error` (E2E repro probe written; fix may also depend on live server logs if user still reports)

**Scope changes from original 10-item R1 target:**
- 🔄 **#9 DWG offline** → moved to **R3 UX polish**. Rationale: backend converter (`backend/app/modules/dwg_takeoff/service.py`) has zero external network dependency per agent audit. The reported "doesn't work offline" is a perception issue best fixed with an "Offline Ready" badge; not a critical bug.
- 🔄 **#13 DWG scale + annotation text** → moved to **R2 deep-research**. Rationale: (a) "scale" in the current UI means zoom %, but the user is asking for drawing-scale (1:50 / 1:100) — a design-level change requiring an RFC. (b) Text-annotation code (`DxfViewer.tsx:547-626` and `AnnotationOverlay.tsx:45-115`) appears correct on read; needs live Playwright repro before patching blindly.

**Branching:** direct to `main` (pre-authorized for v1.9). **PyPI publish per round.** **VPS deploy only after R5.**

---

## 2. Testing infrastructure

- **Unit:** Vitest — `frontend/src/**/__tests__/*.test.ts(x)` and co-located `*.test.ts(x)`
- **E2E:** Playwright — `frontend/e2e/v1.9/NN-slug.spec.ts` (one spec per item)
- **Visual regression:** Playwright screenshots → `frontend/test-results/v1.9/`
- **Accessibility:** `@axe-core/playwright` inline in E2E specs for new UI
- **Backend:** pytest — `backend/tests/unit/v1_9/` + `backend/tests/integration/v1_9/`
- **Offline test harness:** Playwright `context.setOffline(true)` for items #3/#5/#6/#9/#10

## 3. Quality gates (per commit — all must pass)

1. `cd frontend && npx tsc --noEmit` → 0 errors
2. `npx eslint --max-warnings 0` on touched files
3. `npm run test` (Vitest) green
4. Item-scoped Playwright spec passes offline+online
5. Visual regression clean (or baseline intentionally updated)
6. `axe-core` scan clean on new UI
7. No `console.log` outside `import.meta.env.DEV` guards
8. No hardcoded user-visible strings (all through `useTranslation`)
9. ROADMAP_v1.9.md updated (item row + commit hash)

## 4. CTO / Codex review checklist (before tag push)

- [ ] Diff reviewed via `/security-review` (items touching auth, uploads, RBAC, file paths)
- [ ] Diff reviewed via `/simplify` (items over ~200 LOC)
- [ ] i18n keys added to EN/DE/RU (baseline) with fallback chain
- [ ] Changelog entry prepended in `frontend/src/features/about/Changelog.tsx` + `CHANGELOG.md`
- [ ] Version bumped in `frontend/package.json`, `backend/pyproject.toml`, README badge

---

## 5. Round 1 — Critical bugs → v1.9.0

### #2 — BOQ: resource add hangs + doesn't show immediately
- **URL:** `/boq/324f990f-1e27-4358-8d5a-2e6ce07be754`
- **Root causes:**
  1. `frontend/src/features/boq/BOQEditorPage.tsx:273-290` — `onMutate` skips optimistic update when `data.quantity === undefined`; resource changes never get immediate UI feedback.
  2. `BOQEditorPage.tsx:1037-1042` (query config) — no `networkMode`, staleTime 5min, retry `false`; BOQ query hangs on reload.
- **Fix:**
  - Add optimistic cache write in `handleCatalogSelect` (L1696-1738) via `queryClient.setQueryData(['boq', boqId], ...)`.
  - BOQ `useQuery`: `networkMode: 'always'`, `retry: (f,e) => f<2 && navigator.onLine`, clear error state after 3s.
- **Tests:** E2E add-resource-<500ms, E2E reload-no-hang-<2s, unit test on optimistic helper.
- **Files:** `frontend/src/features/boq/BOQEditorPage.tsx`
- **Status:** 🔲

### #5 — BOQ list AbortError offline
- **URL:** `/boq`
- **Root cause:** `frontend/src/main.tsx:10-43` QueryClient has no `navigator.onLine` guard; 300s AbortController in `api.ts:210` throws `AbortError: signal is aborted without reason` when network drops mid-request.
- **Fix:**
  - QueryClient: `queries.networkMode: 'offlineFirst'`, `retry: (count,err) => navigator.onLine && count<2`.
  - In `api.ts` — detect `!navigator.onLine` before fetch → immediately read `offlineStore.getCachedResponse(path)` (already exists at `frontend/src/shared/lib/offlineStore.ts`).
  - Silence `AbortError` in global error handler when `!navigator.onLine`.
- **Tests:** E2E with `context.setOffline(true)` → verify BOQ list renders cached, no error toast.
- **Files:** `frontend/src/main.tsx`, `frontend/src/shared/lib/api.ts`, `frontend/src/features/boq/BOQListPage.tsx`
- **Status:** 🔲

### #6 — Project-not-found vs network error conflation
- **URL:** `/projects/:id`
- **Root cause:** `frontend/src/features/projects/ProjectDetailPage.tsx:1037-1042` has `retry: false` → any error (404 or offline timeout) becomes `!project` → misleading "Project not found" UI.
- **Fix:** Distinguish in error path:
  - `error.status === 404` → "Project deleted" UI
  - Network error + cached data exists → render cached data with "offline" banner
  - Network error + no cache → "Can't load while offline" UI with retry button
- **Tests:** E2E online-404 (delete project, navigate) / E2E offline-cached (seed cache, go offline, navigate).
- **Files:** `frontend/src/features/projects/ProjectDetailPage.tsx`, `frontend/src/shared/lib/api.ts`
- **Status:** 🔲

### #8 — Takeoff uploaded project disappears on reload
- **URL:** `/takeoff?tab=measurements`
- **Finding:** Backend **already** persists (`backend/app/modules/takeoff/service.py:98-135`) **and** cross-links to Documents (`takeoff/router.py:2067-2097`). Bug is frontend-only.
- **Root cause:** `frontend/src/features/takeoff/TakeoffPage.tsx:942` — query `enabled: !!selectedProjectId`. If no project selected, list is empty.
- **Fix:**
  - Drop `!!selectedProjectId` guard when tab is `measurements` — fetch all user's takeoff docs by owner_id.
  - On upload success, invalidate both `['takeoff-documents', projectId]` AND `['documents', projectId]`.
- **Tests:** E2E upload-then-reload persists; E2E upload-then-check-/documents shows file.
- **Files:** `frontend/src/features/takeoff/TakeoffPage.tsx`
- **Status:** 🔲

### #9 — DWG offline conversion
- **URL:** `/dwg-takeoff`
- **Finding:** Backend has **no network dependency** (`backend/app/modules/dwg_takeoff/service.py:329-437` calls local DDC binary subprocess). DWG converter is already offline-capable.
- **Root cause:** Frontend DWG upload uses **raw fetch** bypassing offline layer — `frontend/src/features/dwg-takeoff/api.ts:141-170`. Also: no "offline ready" indicator, converter install prompt may be online-only.
- **Fix:**
  - Wrap upload in `apiPost()` (inherits offline fallback + AbortSignal).
  - Add "Offline Ready" badge on DWG page when `find_converter('dwg')` succeeds.
  - Converter download flow: pre-bundle fallback or show clear offline-install instructions.
- **Tests:** E2E offline DWG upload shows progress + completes if converter installed.
- **Files:** `frontend/src/features/dwg-takeoff/api.ts`, `frontend/src/features/dwg-takeoff/DwgTakeoffPage.tsx`
- **Status:** 🔲

### #13 — DWG scale + annotation text
- **URL:** `/dwg-takeoff`
- **Sub-bug 13a (scale):** `frontend/src/features/dwg-takeoff/components/DxfViewer.tsx:173` auto-fits only, no manual override. Units from backend (`service.py:416`) ignored.
  - **Fix:** Add "Drawing Scale 1:N" numeric input next to zoom control (L671 region). Apply as `vpRef.current.scale` multiplier. Suggest default from parsed DXF units header.
- **Sub-bug 13b (annotation text):** `DwgTakeoffPage.tsx:550-560` — `text_pin` tool fires but `textPinPopup` modal markup is missing in `AnnotationOverlay.tsx`.
  - **Fix:** Render text input popover when `textPinPopup` is set; include font size picker from `FONT_SIZES` (L43); submit via `handleAnnotationCreated({ type: 'text_pin', text, ... })`.
- **Tests:** E2E set scale 1:50 → dimension label shows correct meters; E2E add text annotation → visible on canvas.
- **Files:** `DxfViewer.tsx`, `DwgTakeoffPage.tsx`, `AnnotationOverlay.tsx`, `ToolPalette.tsx`
- **Status:** 🔲

### #18 — BIM Type Name grouping hides Link-to-BOQ
- **URL:** `/bim/b0f604f1-3c84-48f4-a077-c56702a77153`
- **Root cause:** `frontend/src/features/bim/BIMFilterPanel.tsx:864` — condition `visibleElements.length > 0 && visibleElements.length < elements.length` hides buttons when grouping is active but no filter reduces count.
- **Fix:** Change condition to show when `visibleElements.length > 0 && (groupingMode !== 'none' || visibleElements.length < elements.length)`.
- **Tests:** E2E group by Type Name → Link to BOQ + Save Group buttons visible.
- **Files:** `frontend/src/features/bim/BIMFilterPanel.tsx`
- **Status:** 🔲

### #23 — BIM New Requirement Rule broken + UX gaps
- **URL:** `/bim/rules`
- **Root cause (bug):** `frontend/src/features/bim/BIMQuantityRulesPage.tsx:1910` — `createMutation` invalidates `['bim-quantity-maps']`, but list query key likely includes projectId → key mismatch → list doesn't refresh.
- **Root cause (UX):** Fields are dropdown-only (no free-text), no required markers, no project seeding.
- **Fix (R1 scope — just the bug):**
  - Match invalidation key exactly: `queryClient.invalidateQueries({ queryKey: ['bim-quantity-maps', { projectId }] })`.
  - Or: use `exact: false` on invalidate. Or unify to simple `['bim-quantity-maps']` key.
- **(UX gaps → moved to R2 #24 Quantity Rules redesign RFC.)**
- **Tests:** E2E create rule → appears in list within 1s.
- **Files:** `frontend/src/features/bim/BIMQuantityRulesPage.tsx`
- **Status:** 🔲

### #27 — /tasks category filter broken
- **URL:** `/tasks`
- **Partial finding from agent:** Frontend at `frontend/src/features/tasks/api.ts:84` sends `type` param correctly; backend `tasks/router.py:120` accepts as `type_filter`. Agent could not pinpoint — needs live repro.
- **Investigation plan (first action of R1):**
  - Open `/tasks` with backend logs, click each category tab, capture actual HTTP payloads.
  - Create task via modal while on a non-"All" tab — inspect 400/422 response body.
- **Likely fix:** filter state not persisted across create; or new-task default `task_type` doesn't match active filter.
- **Tests:** E2E click each tab filter, verify URL and shown rows; E2E create task on "Topic" tab → task has type=topic and appears.
- **Files:** `frontend/src/features/tasks/TasksPage.tsx`, `frontend/src/features/tasks/api.ts`
- **Status:** 🔲

### #33 — CDE New Container doesn't work
- **URL:** `/cde`
- **Finding from agent:** Both frontend (`frontend/src/features/cde/CDEPage.tsx:839-846`) and backend (`backend/app/modules/cde/service.py:44-118`) implemented. Suspected 400/422 on schema mismatch — `cde_state` required with pattern validation.
- **Fix (R1 — just the create bug):**
  - Live repro, capture network payload, align form payload with `backend/app/modules/cde/schemas.py:34-37`.
  - Ensure default `cde_state: 'wip'` sent if unspecified.
- **(Deep audit of CDE module → R2 RFC covering: revision auto-numbering, transmittal integration, ISO-19650 naming parts, state-machine approval gates.)**
- **Tests:** E2E click New Container → form submit → container appears in list.
- **Files:** `frontend/src/features/cde/CDEPage.tsx`, `backend/app/modules/cde/schemas.py`
- **Status:** 🔲

**Release steps when R1 done:**
1. Verify all 10 E2E specs pass in `frontend/e2e/v1.9/`
2. `npx tsc --noEmit` clean
3. Bump version → 1.9.0 in package.json, pyproject.toml, README, Changelog.tsx, CHANGELOG.md
4. Commit: `feat: v1.9.0 — critical bug fixes (10 items)` + push main + tag v1.9.0
5. PyPI publish wheel (see `memory/pypi_token.md`)

---

## 6. Round 2 — Deep research → v1.9.1

Each item gets an RFC at `docs/rfc/NN-slug.md` written **before** implementation. RFC is committed alongside the code change for CTO review.

### #13 — DWG scale + annotation text (moved from R1)
- **RFC:** `docs/rfc/13-dwg-scale-and-text.md`
- **Scope:** (a) Distinguish zoom % from drawing scale (1:50 / 1:100) — add a drawing-scale state that multiplies measurement output. (b) Live repro the "text annotation invisible" claim via Playwright; the code looks correct on read so the bug may be environmental.
- **Status:** 🔲

### #11 — DWG polyline/layer selection rework
- **RFC:** `docs/rfc/11-dwg-selection.md`
- **Scope:** outer-polyline bias, click-to-hide, multi-select (box + layer), group linking, group aggregate (perimeter/length/area).
- **Research needed:** current hit-testing code in `DxfViewer.tsx`, z-order, layer model.
- **Status:** 🔲

### #16 — Data Explorer Power BI / Tableau features
- **RFC:** `docs/rfc/16-data-explorer-analytics.md`
- **Scope:** pivot, cross-filter, chart types, measure creation, drill-down, save view.
- **Research needed:** current feature inventory, what libs available (AG Grid charts? ECharts?).
- **Status:** 🔲

### #19 — BIM viewer control panel expansion
- **RFC:** `docs/rfc/19-bim-viewer-controls.md`
- **Scope:** sectioning, exploded view, measurement, markup, saved views, walk-through, layer isolate.
- **Status:** 🔲

### #24 — Quantity Rules redesign (BETA)
- **RFC:** `docs/rfc/24-quantity-rules-redesign.md`
- **Scope:** rule builder UX (picker + code), RVT/IFC seed UI, required-field markers, test-run preview, mark module as BETA.
- **Depends on:** #23 bug fix from R1.
- **Status:** 🔲

### #25 — Project Intelligence audit
- **RFC:** `docs/rfc/25-project-intelligence-audit.md`
- **Scope:** full read of `/project-intelligence`, identify outdated widgets, propose v2 layout with current data signals.
- **Status:** 🔲

### #29 — Meetings: edit + attachments + description
- **RFC:** `docs/rfc/29-meetings-overhaul.md`
- **Scope:** edit dialog (currently missing), file attachment upload+download (reuse DocumentService), rich-text description, minutes field.
- **Status:** 🔲

**Release:** `feat: v1.9.1 — deep-research items (6 RFCs)` + tag.

---

## 7. Round 3 — UX polish → v1.9.2

Each item: screenshot-before → patch → screenshot-after. Visual regression in Playwright.

| # | Item | Files | Status |
|---|------|-------|--------|
| 1 | Local DDC logo (`frontend/public/brand/ddc-logo.webp` downloaded ✓) — replace all `https://datadrivenconstruction.io/...png.webp` refs across 23 files | Header.tsx, Dashboard, etc. (grep list) | 🔲 |
| 9 | DWG "Offline Ready" badge (moved from R1) — backend `find_converter('dwg')` succeeds → badge. Plus `navigator.onLine` precheck on upload for clean error. | DwgTakeoffPage.tsx, dwg-takeoff/api.ts | 🔲 |
| 3 | Remove "No network connection. All data stored locally" banner — redundant with offline-first | global banner component | 🔲 |
| 4 | Swap menu Email Issues ↔ Report Issues | Header.tsx user menu | 🔲 |
| 7 | Takeoff measurements row height smaller | TakeoffMeasurementsTab | 🔲 |
| 12 | DWG Summary Measurements panel redesign | DwgTakeoffPage.tsx Summary tab | 🔲 |
| 17 | i18n "Columns 729" → "Колонок параметров ХХХ" | cad-explorer | 🔲 |
| 20 | Remove top "Link to BOQ" button in BIM viewer (duplicate) | BIMPage.tsx toolbar | 🔲 |
| 21 | Gray-out "4D Schedule" button in BIM toolbar | BIMPage.tsx toolbar | 🔲 |
| 26 | Schedule page — bigger/modern Create button | SchedulePage.tsx | 🔲 |
| 28 | 5D EVM — indicate "all projects" vs single project filter | FiveDPage.tsx | 🔲 |
| 30 | Submittals — add Edit dialog | SubmittalsPage.tsx | 🔲 |
| 31 | Transmittals — Edit + Delete | TransmittalsPage.tsx | 🔲 |
| 32 | Documents — filters by type (PDF, DWG, IFC, RVT) + revision | DocumentsPage.tsx | 🔲 |

**Release:** `feat: v1.9.2 — UX polish (13 items)` + tag.

---

## 8. Round 4 — New features → v1.9.3

### #10 — DWG progress bar + background upload
- Extend `useBIMUploadStore` pattern (`frontend/src/stores/useBIMUploadStore.ts`) for DWG.
- Global upload dock component shows all in-flight uploads across modules; survives navigation.
- **Status:** 🔲

### #14 — DWG element link-to-other-modules
- Mirror BIM's link flow (`BIMViewer.tsx` quick-action buttons: +BOQ, +Task, +Document, +Schedule, +Requirement).
- **Status:** 🔲

### #15 — DWG primitives + PDF export
- Primitives: line, polyline, rectangle, circle, polygon, text, arrow. Each with layer + color + thickness.
- PDF export of visible viewport including annotations + primitives.
- **Status:** 🔲

### #22 — Split BIM Rules module
- BIM Rules (data quality) → stays under Takeoff section
- Quantity Rules (estimate compliance) → moves under Estimation section
- **Depends on:** #24 redesign
- **Status:** 🔲

**Release:** `feat: v1.9.3 — new features (4 items)` + tag.

---

## 9. Round 5 — VPS deploy

After user approves all 4 rounds locally:
1. `ssh root@openconstructionerp.com`
2. `cd /root/OpenConstructionERP && git pull origin main`
3. `source venv/bin/activate && pip install -r requirements.txt`
4. `cd frontend && npm install --legacy-peer-deps && npx vite build`
5. `systemctl restart openconstructionerp`
6. Health check + smoke test all 33 items on prod URL.

---

## 10. Open research queue (dispatched to parallel agents in R0)

| Topic | Agent status | Summary |
|-------|--------------|---------|
| Offline-first audit | ✅ Returned | 60% ready, offlineStore exists; P1 kill externals + guards, P2 Service Worker, P3 persist-client |
| BOQ #2 | ✅ Returned | Missing optimistic update; reload staleness |
| Takeoff #8 | ✅ Returned | Backend cross-linking already done; frontend guard bug |
| Tasks #27 + CDE #33 | ✅ Returned | Both need live repro; suspected schema mismatch for CDE |
| BIM/DWG bugs | ✅ Returned | #18 condition bug, #23 invalidation bug, #9 actually offline-OK, #13 missing UI |

All findings folded into sections above.
