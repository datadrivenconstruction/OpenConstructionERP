/**
 * Changelog — Displays version history as a timeline with version badges.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { APP_VERSION } from '@/shared/lib/version';

interface ChangelogEntry {
  version: string;
  date: string;
  changes: string[];
}

const CHANGELOG: ChangelogEntry[] = [
  {
    version: '1.3.28',
    date: '2026-04-11',
    changes: [
      'BIM filter — universal "Building elements" + "Annotations & analytical" split.  User report: the wrong elements showed up under each category, the grouping was unclear, and different projects need different rules.  Replaced the manually-curated noise list with a universal split driven by `bucketOf()` — every category lands in either a real building bucket (Structure / Envelope / Openings / MEP / Furniture / …) OR a noise bucket (Annotations / Analytical).  The Category panel now renders building chips at the top in normal style and a collapsible "Annotations & analytical" section underneath that\'s closed by default but always present.  Works zero-curation for any project',
      'BIM filter — pretty category names.  Real DDC RvtExporter output stores normalised lowercase concatenated category names like "Curtainwallmullions" / "Structuralcolumns" / "Doortags".  New `prettifyCategoryName()` looks each one up in a curated table of ~150 well-known Revit categories and renders the natural English form ("Curtain Wall Mullions" / "Structural Columns" / "Door Tags").  Anything not in the table gets first-letter capitalised but is otherwise un-touched — never algorithmically guessing word boundaries (the wrong split "Stair Srailingbaluster" is worse than the ugly-but-correct "Stairsrailingbaluster")',
      'BIM filter — "None" element_type (the 6 048 Revit-ingest junk rows in the demo) now classified as noise so the buildings-only view doesn\'t pollute the panel with thousands of uncategorised rows.  Real building-element baseline drops from "everything" to "everything except None + annotations + analytical" automatically',
      'Headless test verdict logic — clear-all assertion now compares against the buildings-only baseline instead of the raw mesh count, since buildings-only is sticky and doesn\'t reset.  All 10 verdicts now PASS deterministically: storey filter, clear storey, buildings-only toggle, Walls type filter (5440 → 205), clear all (back to 2294 baseline), multi-chip OR (Doors=108, +Walls=313), group save → list, group apply (2294 → 205), group delete, 60 fps stable',
    ],
  },
  {
    version: '1.3.27',
    date: '2026-04-11',
    changes: [
      'BIM filter panel — three professional grouping modes via a new segmented control: **By Category** (flat list of every Revit category / IFC entity, default — works for both formats with zero curation), **By Type Name** (hierarchical Category → Family/Type Name like the Revit Browser, with chevron-collapsible category headers), and **Buckets** (existing semantic Structure / Envelope / MEP / … grouping kept as a third option).  Fixes the user complaint that the bucket-only view felt incomplete and unclear about how filters were structured',
      'New `getTypeNameKey()` helper resolves the second-level Type Name from `el.name` first, then `properties.family`, `properties["family and type"]`, or `properties.type`.  Real Revit data has 100% `name` coverage and 75% `properties.family` coverage, so the type-name view always populates',
      'Added explicit "Clear types" link in the type-filter section header (matches the existing "All levels" link in the storey section) so users have a one-click way to drop type selections without re-clicking each chip',
      'Headless test extended (TEST 7d) — verifies all three grouping modes by clicking the segmented control buttons and counting category headers: 127 category headers rendered in Type Name mode on the demo (every distinct element_type gets its own collapsible header).  Screenshots saved at 14-typename-grouping.png and 15-buckets-grouping.png',
      'Headless test fix — TEST 7b\'s modal-close button selector was matching the close button on the BIM filter panel itself (both are X-icon lucide buttons), accidentally closing the panel between tests and breaking TEST 7c.  Scoped the close-button query to elements inside the `.fixed.inset-0.z-50` modal overlay only.  All 10 verdicts now PASS deterministically',
    ],
  },
  {
    version: '1.3.26',
    date: '2026-04-11',
    changes: [
      'Fix: "Add to BOQ" link create returned 500 Internal Server Error on every click. Root cause: the v1.3.22 backend agent\'s ownership check `_verify_boq_position_access()` referenced `position.project_id` directly, but `Position` has no `project_id` column — the project lives on the parent `BOQ` row reached via `position.boq_id`. Fix: rewrote the helper as a single-row SELECT that joins Position → BOQ and pulls `BOQ.project_id` in one round-trip. Verified end-to-end via curl (link created, cad_element_ids synced, boq_links embedded in element response, delete works) and via the headless deep test',
      'Fix: headless test for Save-as-group lifecycle was flaky — the assertion ran 2 s after the POST, but the React Query refetch + panel re-render chain sometimes took longer. Replaced the fixed timeout with a 6-s polling loop that breaks as soon as the saved-groups section appears, eliminating false-negative FAILs',
    ],
  },
  {
    version: '1.3.25',
    date: '2026-04-11',
    changes: [
      'BIM saved groups — full lifecycle UI completed.  v1.3.24 added the SaveGroupModal, but the saved groups had nowhere to live afterwards.  v1.3.25 adds a "Saved groups" section at the top of the BIMFilterPanel scroll area listing every group for the current model with one-click apply, link-to-BOQ, and delete actions.  Each row shows the group\'s color dot, name, and cached member count.  Clicking a group converts its `filter_criteria` back into the panel\'s Set-based filter state and highlights the row as the active group.  Manual filter changes drop the highlight automatically because the filter is no longer 1:1 with the group',
      'BIM saved groups — fetched via `useQuery(["bim-element-groups", projectId, modelId])` from the new `/api/v1/bim_hub/element-groups/` endpoint, with React Query auto-refetch on save / delete via `invalidateQueries`.  Delete uses a confirmation dialog and the new `deleteElementGroup` API wrapper.  Link-to-BOQ resolves the group\'s `member_element_ids` against the loaded element list and opens AddToBOQModal with the resolved subset',
      'Headless deep test (debug-bim.cjs TEST 7c) now exercises the FULL lifecycle: filter Walls → click "Save as group" → type a unique group name → click "Save group" → verify the new SAVED GROUPS section lists it → click Clear all → click the saved group row → verify mesh visibility re-narrows to the original 205 walls → click the trash icon → confirm bypassed → verify the group disappears.  All five sub-assertions PASS — group save → list, group apply, group delete',
      'Test verdict logic — clear-storey now compares against the buildings-only baseline (5168) instead of the raw mesh count (5440), so the previous WARN flips to PASS.  The buildings-only toggle hides 272 noise meshes by default, which is the expected baseline for every filter test',
    ],
  },
  {
    version: '1.3.24',
    date: '2026-04-11',
    changes: [
      'BIM storage architecture — three layers landed end-to-end. (1) Pluggable storage backend abstraction in `app/core/storage.py` with LocalStorageBackend (default, byte-for-byte identical to v1.3.23) and S3StorageBackend (opt-in via `pip install openconstructionerp[s3]`, supports MinIO / AWS / Backblaze / DigitalOcean Spaces). (2) New `oe_bim_element_group` table for saved selections — dynamic groups recompute members from a filter predicate, static groups freeze the snapshot. (3) Full design captured in `docs/BIM-STORAGE-ARCHITECTURE.md` covering the three layers, the cross-module link unification roadmap, and the migration path for existing deployments',
      'BIM Element Groups (saved selections) — backend complete: new `BIMElementGroup` SQLAlchemy model + Pydantic schemas + service methods (list/create/update/delete + resolve_element_group_members) + 4 endpoints under /api/v1/bim_hub/element-groups/ + Alembic migration `f22fa2934807_add_bim_element_group_table`. The resolve method handles all filter_criteria keys (element_type, category, discipline, storey, name_contains, property_filter) with PostgreSQL JSON containment for property matching and a Python-side fallback for SQLite',
      'Frontend element groups UX — new `SaveGroupModal` (~210 lines) opens from a "Save as group" button next to the Quick Takeoff button in the filter panel. Captures the current filter criteria + visible element ids, lets the user pick dynamic vs static, set a name + description + colour, then POSTs to the new endpoint. Verified end-to-end via headless test: button shows when filter is active, click opens modal with header + name input + radio toggles, both screenshot inspection and DOM assertions pass',
      'Storage backend tests — new `backend/tests/unit/test_storage.py` covers LocalStorageBackend round-trip (write → read → verify → delete → verify gone) and the storage factory (settings → correct backend instance). Both tests pass cleanly with `pytest tests/unit/test_storage.py -v`',
      'Storage migration helper — new `backend/scripts/migrate_bim_to_s3.py` walks `data/bim/` and uploads every existing file to the configured S3 bucket via the new abstraction. One-time runner for deployments switching from local to cloud storage',
      'New optional dependency — `aioboto3>=12.0.0` added under `[project.optional-dependencies] s3` in `backend/pyproject.toml`. `pip install openconstructionerp` continues to work without it; users only install `[s3]` extras when they actually want cloud storage. Importing S3StorageBackend without aioboto3 raises a clear ImportError instead of crashing at startup',
      'BIM viewer filter panel re-tested end-to-end after the SaveGroup wiring: storey filter (5440→317), buildings-only toggle (5440↔5168), Walls type filter (→205), clear all (→5168), multi-chip OR (Doors=108, Doors+Walls=313), all 5 camera presets, grid toggle, element click → AddToBOQ modal with real BOQ positions, Save as group → SaveGroupModal renders. 60 fps stable on the 5 440-mesh demo model',
    ],
  },
  {
    version: '1.3.23',
    date: '2026-04-11',
    changes: [
      'BIM viewer is verified end-to-end via headless deep test (debug-bim.cjs): all camera presets (Top/Front/Side/Iso/Fit) move the camera to the correct position, grid toggle flips visibility, element click opens the properties panel with "Linked BOQ positions" section, "Add to BOQ" button opens the modal with both tabs populated by real BOQ positions from the demo project, /bim/rules page renders the empty state, and the storey + buildings-only + Walls type filter + clear all + multi-chip OR all pass with 60 fps on real GPU',
      'BIM viewer headless test (frontend/debug-bim.cjs) was extended with 4 new test groups: camera preset verification (TEST 6), grid toggle (TEST 7), element click → AddToBOQ modal (TEST 7b), navigation to /bim/rules (TEST 8), and a synthetic stress test that clones the demo scene 4× to ~21 760 meshes (TEST 9). The stress test confirms the per-mesh path holds 60 fps up to ~5 000 meshes and degrades to ~2 fps at 21 000 — informing the BatchedMesh follow-up below',
      'Fix: sidebar now shows "BIM Rules" instead of the raw `nav.bim_rules` translation key — added the missing English fallback in i18n-fallbacks.ts',
      'Internal: ElementManager now contains a `batchMeshesByMaterial()` method that uses Three.js BatchedMesh to collapse same-material meshes into one draw call per material (groups with ≥10 instances).  Currently gated behind a 50 000-mesh threshold so it never triggers on real-world models — Three.js BatchedMesh.setVisibleAt has subtle GPU-sync issues that cause partial renders when filters change rapidly, so the per-mesh path is the default for everything below 50 k meshes (which is comfortably 60 fps).  The proper fix is to pre-bake batched meshes on the BACKEND side as part of the canonical-format conversion, which is the storage architecture work in progress',
    ],
  },
  {
    version: '1.3.22',
    date: '2026-04-11',
    changes: [
      'BIM ↔ BOQ linking — the headline feature. The backend link infrastructure was fully built but had zero UI until now. Closing the gap end-to-end: (1) BIMElementResponse now embeds a boq_links array of BOQElementLinkBrief objects so the viewer knows per-element link state on first fetch, (2) the element details panel in the viewer renders a "Linked BOQ positions" section on every selected element with ordinal/description/link-type badge and an unlink button per link, (3) a new "Add to BOQ" modal (features/bim/AddToBOQModal.tsx, ~550 lines) offers two tabs — "Link to existing position" (searchable list of BOQ positions for the project) and "Create new position" (pre-filled form with aggregated quantities, unit, description, classification from the element) — both single-element and bulk-element paths in one shot',
      'Quick takeoff: a new "Link N visible elements to BOQ" button in the filter panel runs AddToBOQ on the current filtered subset, so clicking Walls + 01 Entry Level + Quick Takeoff creates one BOQ position linked to all 211 walls on the ground floor in three clicks',
      'BIM Quantity Rules page at /bim/rules — dedicated UI for rule-based bulk linking (the professional Vico/iTWO/Solibri approach). Define patterns like "IFC WALL + material=Concrete + thickness≥0.24 → DIN 276 330", preview matches via dry-run, then apply to create BOQElementLink rows + auto-created BOQ positions in bulk. Integrates with the existing BIMQuantityMap backend model and the /quantity-maps/ endpoints',
      'apply_quantity_maps now actually persists — previously it returned a preview and never wrote anything. It now honours the dry_run flag (default True for safety), wraps each rule in a savepoint, skips duplicate (position, element) pairs, supports auto-creating BOQ positions when the rule has auto_create:true, and returns new links_created + positions_created counters',
      'Position.cad_element_ids is auto-synced on link CRUD — every create_link / delete_link now updates the JSON array on the corresponding BOQ position so the existing "is linked" checks everywhere in the codebase stay consistent. Added a sync_cad_element_ids(project_id) back-fill service method for legacy rows',
      'Bi-directional selection sync — new useBIMLinkSelectionStore (Zustand) publishes "BOQ row selected → highlight linked BIM elements in orange" and "BIM element selected → scroll BOQ row into view". Cross-highlighting works even when both pages are open in split-view',
      'Linked-count badge — a green "N linked" chip in the viewer top-right shows at-a-glance how many elements already have BOQ links, so the user can see takeoff progress without opening the BOQ editor',
      'Viewer toolbar rework — removed the broken 4D/5D view-mode stubs (visual-only, never wired to cost or schedule data), added a camera preset group (Fit / Isometric / Top / Front / Side) via SceneManager.setCameraPreset, wired the existing toggleGrid() to a Grid button, and consolidated every button into a single bordered row with function-group dividers (Camera | Selection | Visibility). Professional toolbar taxonomy per the Vico / Forge / BIMcollab research brief',
      'New BIMElement.highlight(elementIds) method on ElementManager — colours matching meshes orange WITHOUT hiding the rest, so the user sees the spatial distribution of whichever BOQ position they clicked. Driven by the new highlightedIds prop on BIMViewer',
      'Per-project link count visible in the BOQ grid — positions with cad_element_ids.length > 0 now render a small blue pill showing the link count in their row, so estimators see takeoff coverage at a glance while scrolling through the BOQ',
    ],
  },
  {
    version: '1.3.21',
    date: '2026-04-10',
    changes: [
      'BIM viewer Storeys filter is now actually usable. The DDC RVT export ships ~10 000 annotation/analytical rows with `storey: null` which dominated the storey list and showed up as a useless "—" entry. The Storeys section now (1) is scoped by the "Building elements only" toggle so the noise rows are excluded entirely, (2) parses the leading level number from each name ("01 - Entry Level" → level 1, label "Entry Level"), (3) renders a small numeric badge in front of each chip ("01", "02", "03", "G" for ground, "B1" for basement), (4) sorts ground-up by parsed level number instead of alphabetical, (5) adds an "All levels" link when any storey is selected. Verified end-to-end via headless Playwright: clicking the Entry Level chip drops viewport visibility from 5 168 → 317 meshes and zooms to that floor only',
      'BIM filter panel verified by deep test: Walls chip = 205 visible meshes, Doors chip = 108, Walls + Doors together = 313 (perfect OR-set semantics across selected types). Buildings-only toggle proven to hide 272 noise meshes on the demo. Real-GPU FPS measured at 60 on the 5 440-mesh model after the v1.3.20 perf pass',
    ],
  },
  {
    version: '1.3.20',
    date: '2026-04-10',
    changes: [
      'BIM viewer is much faster on real-world models — measured live in headless Playwright. Three causes: (1) DDC RvtExporter ships ~40 spotlights inside its DAE which ColladaLoader silently added to the scene, turning a 4-light setup into a 46-light shadow disaster; (2) every COLLADA mesh inherited castShadow=true so the renderer rebuilt a shadow map for 5 000+ casters per frame; (3) the directional light itself was a shadow caster with a 2048×2048 map. Fix: strip every Light/Camera at COLLADA-load time, force castShadow=false on every BIM mesh, disable shadow casting on the directional light, and turn off the renderer-level shadowMap. The 5 440-mesh demo went from 1 fps → 30+ fps in headless software-render',
      'BIM viewer grid is now sized to the loaded model (1 m cells, extent ≈ 1.6 × the model footprint) instead of the fixed 100 × 100 m default — small Revit exports were sitting inside an enormous grid that dwarfed the geometry',
      'BIM viewer now caps renderer pixel ratio at 1 (was capped at 2) — high-DPI rendering on a 5 000-mesh scene quadruples fragment cost for marginal visual gain',
      'BIM viewer locks matrixAutoUpdate=false on every COLLADA mesh after the initial transform — Three.js no longer recomputes 5 000+ world matrices every frame',
      'BIM viewer camera fits the model tighter (multiplier 1.4 → 1.05) so the geometry actually fills the viewport instead of sitting in the middle with ~40 % empty margin',
      'BIM filter panel reorganised into semantic buckets (Structure / Envelope / Doors & Windows / MEP / Furniture / Annotations / Analytical) — DDC RVT exports were dumping 50+ raw Revit categories like "Analytical Nodes", "Weak Dims" and "Area Scheme Lines" as flat chips, drowning the categories that estimators actually care about',
      'BIM filter panel adds a "Building elements only" toggle (default ON) that hides annotation/analytical noise from the viewport — verified hides ~1 500 noise meshes on the demo model',
      'BIM filter panel: clicking a category chip now zooms the camera to the visible subset, giving immediate spatial feedback — applies on every filter/isolate change and zooms back out when the filter is cleared',
      'BIM viewer now uses a positional fallback to wire DAE meshes to elements when the converter (looking at you, DDC RvtExporter) drops node names. Approximate but lets filters actually do something on the viewport instead of being a no-op',
    ],
  },
  {
    version: '1.3.19',
    date: '2026-04-10',
    changes: [
      'Fix: BIM viewer camera now correctly frames the model on first load — diagnosed via headless Playwright (model was 1 m wide but camera was 1840 m away, off by 1000×). Three root causes: (1) placeholder boxes from element bounding_box created an early bbox in source-CAD units that the first zoomToFit framed; (2) SceneManager.zoomToFit did not force updateMatrixWorld so it read stale identity matrices on the first call; (3) BIMViewer only fired one post-DAE zoomToFit which often beat ColladaLoader\'s microtask flush. Fix: skip placeholders when a real DAE URL is queued, force updateMatrixWorld at the top of zoomToFit, and schedule the post-DAE fit at 0/50/250 ms',
    ],
  },
  {
    version: '1.3.18',
    date: '2026-04-10',
    changes: [
      'Fix: BIM viewer now shows COLLADA materials and colours from the source file — was overwriting every mesh with a flat default discipline material, making everything look uniformly white',
      'Fix: BIM viewer camera fit now ignores the grid helper and lights — model is no longer dwarfed by the 100×100 grid bbox and visible immediately on load',
      'Fix: BIM viewer colour-by reset now restores the original COLLADA material instead of falling back to the flat discipline colour',
      'Cleanup: tighter inner padding on every page — main content area now uses px-2 sm:px-3 (was px-3 sm:px-4 lg:px-6) and the artificial max-w-content cap is gone, so dashboards, lists and editors fill the available width',
      'Security: BIM model delete now removes the original RVT/IFC + COLLADA + Excel files from disk (was a leak — files accumulated indefinitely)',
      'Security: new POST /api/v1/bim_hub/cleanup-orphans/ admin endpoint scans data/bim/ for files whose model row no longer exists and removes them',
      'Fix: markups now save points in PDF user units (not canvas pixels), so an annotation drawn at 100% zoom renders correctly at 200% zoom or any other scale. Legacy pixel-coordinate markups still render via a backwards-compat flag',
      'Fix: PDF.js memory leak in the markups inline annotator — pdfDoc is now destroyed and the in-flight RenderTask is cancelled on unmount / page change',
      'Security: takeoff converter ZIP install now validates every member path against zip-slip — refuses absolute paths and `..` parent traversal that could write outside the install directory',
    ],
  },
  {
    version: '1.3.17',
    date: '2026-04-10',
    changes: [
      'Fix: EVM SPI no longer returns impossible values like 33 — clamped to [0, 5] when the time-phased PV proxy degenerates (set `spi_capped: true` in the response when the cap fired)',
      'Fix: schedule CPM now sorts activities topologically before forward and backward passes — out-of-order DB rows used to silently produce wrong ES/EF dates',
      'Fix: schedule CPM now detects dependency cycles and raises HTTP 400 with the affected activity names — used to silently produce nonsense',
      'Fix: risk matrix is now a real 5×5 grid (very_low / low / medium / high / critical) — was effectively 5×4 because the impact map skipped level 3, shifting tier boundaries',
      'Fix: costmodel.calculate_evm N+1 — budget_lines lookup hoisted out of the per-schedule loop',
    ],
  },
  {
    version: '1.3.16',
    date: '2026-04-10',
    changes: [
      'Security: validation reports — list/get/delete now verify project ownership (was IDOR)',
      'Security: tendering — bid PATCH now verifies ownership; package list now requires project_id (no more cross-tenant enumeration)',
      'Security: project_intelligence — all 8 endpoints behind RequirePermission + ownership check; cache key now includes user_id (was leaking cached state across users)',
      'Security: full_evm — all 3 endpoints behind RequirePermission + ownership check',
      'Security: catalog/region delete now requires catalog.delete (was catalog.create — wrong perm); same for costs/clear-region (was costs.update)',
      'Security: AI provider API keys now encrypted at rest with Fernet (was plaintext in oe_ai_settings). Existing rows transparently fall through to plaintext on first read, get re-encrypted on next save',
      'Security: erp_chat /stream/ now rate-limited (was unlimited); tool results capped at 8000 chars / 50 list items before re-injection into the LLM context (was unbounded — a 16k-element BOQ tool call would burn ~500k tokens per agent round)',
    ],
  },
  {
    version: '1.3.15',
    date: '2026-04-10',
    changes: [
      'Security: bim_hub now has permission checks on all 21 endpoints (previously 0/22 — every model/element/geometry was readable across tenants)',
      'Security: finance now has permission checks on all 17 endpoints (was 0/17)',
      'Security: contacts now has permission checks on all 11 endpoints (was 0/11)',
      'Security: rfq_bidding now has permission checks on all 11 endpoints (was 0/11)',
      'Security: assemblies endpoints verify ownership — closes a cross-tenant data injection through apply-to-boq',
      'Security: BOQ position update/delete/reorder now verify BOQ ownership',
      'Security: /api/v1/projects/analytics/overview/ now scoped by owner (was leaking every project to every authenticated user). Also fixed an N+1 — analytics overview is now 3 queries instead of 3+N',
      'Cleanup: 213 MB of orphan RVT files and pip cache removed from the public hosted demo',
    ],
  },
  {
    version: '1.3.14',
    date: '2026-04-10',
    changes: [
      'Fix #42 (round 2): login 404 on quickstart — `/api/v1/users/auth/login` now works with and without trailing slash. Same for /register and /refresh',
      'Fix #42: PostgreSQL demo seed crash "expected str, got int" — `Activity.progress_pct` is `String(10)` in the schema, demo seeder was passing `int`. Wrapped in `str()`',
      'Cleanup: `[ai]` extra renamed to `[semantic]` (just qdrant + sentence-transformers). Old `[ai]` kept as alias. Vendor LLM SDKs (anthropic, openai) removed — they were ~800 MB of dead wheels (we use httpx directly)',
      '`openestimate doctor` now checks pandas + pyarrow as ERROR-level (was silent), and checks for any LLM provider API key',
      '`openestimate init-db` now reports per-module import failures loudly and exits non-zero if any module fails',
    ],
  },
  {
    version: '1.3.13',
    date: '2026-04-10',
    changes: [
      'Fix: pandas + pyarrow are now in base dependencies — fresh `pip install openconstructionerp` no longer breaks `load-cwicr` with HTTP 500',
      'Fix: BIM viewer geometry now visible on first load — reverted to a simple `setFromObject(scene)` fit, removed the broken Mesh-only filter that missed COLLADA Group nodes',
      'Fix: BIM viewer wide camera near/far range (0.01–1,000,000) so models in any unit (mm/cm/m/ft) fit without manual zoom',
      'New: persistent demo-mode warning banner + one-time modal on the public hosted demo (driven by `OE_DEMO_MODE=true` env var)',
      'New: `/api/v1/users/` strips PII (names blanked, email local part hashed) when `OE_DEMO_MODE=true` — only the email domain remains visible',
      'Cleanup: removed `pyarrow` from `[vector]` extra (now in base)',
      'Credit: @migfrazao2003 + @maher00746 added to README contributors',
    ],
  },
  {
    version: '1.3.12',
    date: '2026-04-10',
    changes: [
      'Fix #42: PostgreSQL quickstart now creates tables on first start (was missing schema, login broken)',
      'Fix: BIM viewer fits the camera to the model on load — no more mousewheel hunting',
      'Fix: BIM filters and isolate now work for Revit/RVT exports',
      'Fix: BIM ingest fills in mesh_ref, level and bounding box on every element',
      'New: 6-step progress bar after BIM upload (uploading → converting → parsing → indexing → linking → ready)',
      'New: `openestimate doctor` command — runs 8 pre-flight checks before serve',
      'New: `openestimate init-db` creates the full schema for all 43 modules',
      'New: friendlier CLI startup banner with version, URL and demo login',
      'Cleanup: removed duplicate project selector from chat top bar, tighter top spacing',
      'Cleanup: rewritten README quickstart (3 commands) + troubleshooting table',
      'Cleanup: install.ps1 is now a 5-step progress flow with check marks',
    ],
  },
  {
    version: '1.3.11',
    date: '2026-04-10',
    changes: [
      'Feature: BIM viewer full-width layout — removed the outer page padding, added a thin left divider against the sidebar, so the 3D viewport and filter panel use the full available width on every screen size',
      'Feature: BIM filter panel is now format-aware — detects whether the loaded model is a Revit (RVT) or IFC file and shows the right categorisation. Revit models show Levels + Revit Categories (Walls, Floors, Ceilings, Doors, Windows, Columns, Structural Framing, Furniture, Mechanical Equipment, Plumbing, Electrical, Generic Models). IFC models show IfcBuildingStorey + IfcEntity types (IfcWall, IfcSlab, IfcRoof, IfcDoor, IfcWindow, IfcColumn, IfcBeam, IfcFlowTerminal). A small RVT/IFC badge in the panel header confirms the detected format',
      'Fix: removed the Discipline filter from the BIM viewer — disciplines were an artificial grouping that did not map cleanly to either Revit or IFC data models. All discipline UI, group-by option, and colour-by-discipline mode are gone; colour-by now exposes Category / Storey / Type instead',
      'Feature: AI Chat page now matches the site theme — the dedicated GitHub-dark "keynote" colour palette has been replaced with the global OpenEstimate design tokens. Chat now follows the app light/dark mode toggle, uses the same background, surface, border and text colours as the rest of the product, and keeps the amber (#f0883e) only for genuine AI accent moments (streaming cursor, live indicator, highlighted tokens, tool name chips)',
      'Feature: AI Chat page uses the full available width — removed the old max-width wrapper, added a thin left divider against the sidebar, same pattern as BIM and BOQ pages',
    ],
  },
  {
    version: '1.3.10',
    date: '2026-04-10',
    changes: [
      'Fix: backend no longer silently exits on Windows + Anaconda Python during startup — root cause was an MKL/OpenMP DLL conflict (libiomp5md.dll loaded twice from both Anaconda and torch), which triggered a native TerminateProcess call with no Python traceback. Fixed by setting KMP_DUPLICATE_LIB_OK=TRUE + OMP_NUM_THREADS=1 + MKL_NUM_THREADS=1 as the very first thing in app/main.py, before any import that can pull in numpy or torch',
      'Fix: vector DB status check no longer eagerly loads the sentence-transformers model (which pulled in torch and ~400 MB of weights just to return a boolean can_generate_locally). Now uses importlib.util.find_spec() as a lazy availability check — startup is ~30 seconds faster and avoids the torch import path entirely when the embedder is not actually needed',
      'Fix: vector DB status check no longer eagerly opens a Qdrant connection during startup just to populate can_restore_snapshots. Same lazy-check approach — if qdrant-client is installed, we assume snapshot restore is possible',
      'Feature: _init_vector_db() now logs actionable hints when vector backend is not reachable — e.g. "Start a local Qdrant with: docker run -p 6333:6333 qdrant/qdrant" or "Install the embedded vector backend with: pip install openconstructionerp[vector]"',
      'Feature: Qdrant is still the recommended production vector backend (supports snapshots, scales to millions of vectors). The app simply degrades gracefully to LanceDB or disables semantic search if Qdrant is unreachable, instead of crashing',
      'Fix: https://openconstructionerp.com/demo/ now correctly serves the SPA index.html instead of returning {"detail":"Not Found"}. Root cause was a Starlette lifecycle trap — mount_frontend() registered its SPA 404 exception handler INSIDE the startup event handler, but by then Starlette had already built the ExceptionMiddleware with a snapshot of app.exception_handlers, so the new handler never became active. Moved mount_frontend() into create_app() (before the app is returned), so the handler is in place before the first lifespan message is processed',
    ],
  },
  {
    version: '1.3.9',
    date: '2026-04-10',
    changes: [
      'Fix: Cost database load no longer hangs at 30% — vectorized resource aggregation + single-commit SQLite insert. Full 55,719-item CWICR region now loads in ~19s (was 346s, ~18× speedup)',
      'Fix: Non-admin roles can now install cost databases — changed /load-cwicr permission from costs.create (EDITOR+) to costs.read (VIEWER+), so viewers finish onboarding without the "Missing permission" 403',
      'Fix: Legacy "estimator" role now resolves correctly in the permission system — added ROLE_ALIASES map (estimator → editor, qs → editor, superuser → admin, guest → viewer), so industry-specific role names work without DB migration',
      'Feature: BIM viewer color-by mode — recolor elements by discipline, storey, or type using golden-angle hue palette; one-click reset to discipline colors',
      'Feature: BIM viewer isolate mode — hide everything except the selected element group; works alongside filter predicates',
      'Feature: ElementManager.colorBy() / resetColors() / isolate() — non-destructive material cloning so discipline base materials stay intact',
      'Feature: ERP Chat tool authorization + argument validation — every project-touching tool (get_project_summary, get_boq_items, compare_projects, etc.) now verifies the caller owns the project before fetching data; admin bypass preserved',
      'Feature: Tool argument helpers (_parse_uuid, _parse_str, _require_project_access) + structured _auth_error responses so the AI gets actionable error messages instead of silent failures',
    ],
  },
  {
    version: '1.3.8',
    date: '2026-04-10',
    changes: [
      'Feature: BIM viewer filter + group panel — free-text search, discipline toggles, storey filter, element type filter',
      'Feature: BIM element explorer — groups by discipline/storey/type, click to select in viewer, expandable tree',
      'Feature: ElementManager.applyFilter() — fast mesh visibility toggle for 16k+ elements (no re-render)',
      'Feature: Filter button in BIM header with live visible count badge',
    ],
  },
  {
    version: '1.3.7',
    date: '2026-04-10',
    changes: [
      'Fix: BIM viewer now shows REAL Revit geometry (33 MB COLLADA) instead of 500 placeholder boxes — two-pass DDC converter (Excel + native .dae)',
      'Fix: BIM element fetch limit raised from 1000 → 50000 — viewer now loads all 16k+ elements at once',
      'Fix: ERP Chat tables missing in dev DB — added erp_chat models import to main.py so create_all picks them up',
      'Feature: AI Config Banner on /chat — shown when no API key, includes "Open Settings" link with i18n',
      'Feature: "AI Chat" sidebar label translated to all 21 languages (en, de, fr, es, pt, ru, zh, ar, hi, tr, it, nl, pl, cs, ja, ko, sv, no, da, fi, bg)',
    ],
  },
  {
    version: '1.3.6',
    date: '2026-04-10',
    changes: [
      'Fix: BIM 3D viewer geometry now loads — endpoint accepts ?token= query param so Three.js ColladaLoader (which can\'t set Authorization header) can authenticate',
      'Fix: /chat page no longer returns 404 — removed duplicate prefix from erp_chat router (was being mounted at /api/v1/erp_chat/erp_chat/)',
      'Fix: Cost database installation from onboarding now works — added trailing slash to load-cwicr endpoint',
      'Feature: Big floating AI Chat button (bottom-right) on every page — gradient pill with pulse indicator, hidden on /chat itself',
      'Feature: Floating Recent button moved up to make room for the AI Chat FAB',
    ],
  },
  {
    version: '1.3.5',
    date: '2026-04-10',
    changes: [
      'Feature: /chat page now respects site theme — light/dark mode switches automatically when user toggles the theme',
      'Feature: Rich empty state on /chat — 3-step explanation, 6 tool category cards with examples, hero icon',
      'Feature: All /chat UI strings now use i18next — translates automatically to all 21 supported languages',
      'Feature: New light theme tokens in chat-tokens.css with warm whites and proper contrast',
      'Fix: Send button text color works in both light and dark themes',
    ],
  },
  {
    version: '1.3.4',
    date: '2026-04-10',
    changes: [
      'Fix: BIM RVT file upload now actually works — was failing because relative input paths broke when DDC converter ran from its own DLL directory',
      'Fix: BIM Excel parser now filters out non-element rows (Materials/SunStudy/ViewPorts/None) — extracts 8200+ real elements from Revit files',
      'Fix: BIM elements now use Revit OST_ category names + Revit uniqueid as stable_id + correct quantity column mapping',
      'Test: Added 17 unit tests for BIM processor (discipline classification, IFC text parser, Excel mapping, edge cases)',
      'Docs: openconstructionerp.com/docs.html updated with latest content + screenshots',
    ],
  },
  {
    version: '1.3.3',
    date: '2026-04-10',
    changes: [
      'Feature: Bulk operations — POST /batch/delete/, PATCH /batch/status/, POST /batch/assign/ on Tasks/RFI/Documents/Risks',
      'Feature: Reusable bulk_ops core helper with BulkDeleteRequest/BulkStatusRequest/BulkAssignRequest schemas',
      'Feature: Backend search on Tasks (title/description/result), RFI (subject/question/response/number), Meetings (title/agenda/minutes/number) — case-insensitive ILIKE',
      'Feature: Task dependencies — depends_on FK field, complete_task blocks until predecessor done, cycle detection on update',
      'Feature: TaskService.list_blockers() helper for dependency graph queries',
    ],
  },
  {
    version: '1.3.2',
    date: '2026-04-10',
    changes: [
      'Feature: Finance EVM — added EAC/VAC/ETC/TCPI forecast metrics (PMBOK standard)',
      'Feature: Schedule CPM — persists ES/EF/LS/LF/float in activity metadata + supports all 4 dep types (FS/SS/FF/SF)',
      'Feature: BOQ section delete — cascade option + scrubs dangling Activity.boq_position_ids refs',
      'Feature: Tasks — completed tasks can now be reopened for rework scenarios',
      'Feature: Tasks — new list_upcoming_tasks() for reminder/notification workflows',
      'Feature: RFI — publishes rfi.responded + rfi.closed events for notification chains',
      'Feature: Meetings — delete_meeting scrubs meeting_id from auto-created tasks',
      'Feature: Submittals — publishes submitted/reviewed/approved events + first-submit sets revision=1',
      'Feature: Documents — publishes document.uploaded event for CDE workflows',
      'Security: Documents download/photo — path traversal hardening via Path.relative_to() + symlink rejection',
      'Fix: Project Intelligence scorer — optional domains no longer unfairly penalize overall score',
    ],
  },
  {
    version: '1.3.1',
    date: '2026-04-10',
    changes: [
      'Security: Procurement module — added RequirePermission to all POST/PATCH endpoints (was unprotected)',
      'Security: BOQ module — added ownership verification to position, section, and markup CRUD (prevents cross-tenant writes)',
      'Security: RFI module — added RequirePermission to read endpoints (list, stats, get, export, close)',
      'Fix: BOQEditorPage — deferred delete errors now logged instead of silently swallowed',
      'Fix: CostsPage — clipboard copy toast only shows on actual success, error toast on failure',
      'Fix: ProjectsPage — BOQ stats loading errors now surfaced per-project with hasError flag',
      'Fix: FinancePage — invoice total handles NaN inputs gracefully',
      'Fix: RiskRegisterPage — matrix color handles unknown impact values instead of defaulting to low-risk',
      'Fix: TakeoffPage — previous upload error toast cleared when new files are selected',
      'Fix: BOQ classify_position — returns 503 error instead of empty suggestions on AI failures',
      'Fix: ChangeOrders — lazy-loading errors now debug-logged with context',
      'Perf: Costs module — added indexes on source, region, and (source, region) composite',
    ],
  },
  {
    version: '1.3.0',
    date: '2026-04-10',
    changes: [
      'New: AI Chat — full-page split-screen AI workspace (/chat) with tool-calling agent, 11 ERP tools, 9 live data renderers',
      'New: BIM Viewer redesign — premium light UI, edge-to-edge viewport, model filmstrip, slide-in upload panel',
      'New: BIM processing now uses DDC Community Converter pipeline (same as Data Explorer)',
      'New: Floating Recent button — bottom-right FAB with last 5 visited items',
      'New: About page links to openconstructionerp.com with UTM tracking',
      'Fix: BIM RVT files no longer stuck in "processing" — shows clear "Needs Converter" status',
      'Fix: BIM geometry URL now works for all ready models',
      'Move: Project Intelligence → AI Tools sidebar group',
      'Move: Recent section from sidebar to floating popover',
    ],
  },
  {
    version: '1.0.0',
    date: '2026-04-08',
    changes: [
      'New: Interconnected module ecosystems — Documents↔CDE↔Transmittals, Safety↔Inspections↔NCR↔Punchlist, BIM↔Takeoff↔Schedule',
      'New: Visual create forms with card selectors, section headers, smart defaults across all modules',
      'New: Cross-module navigation links on every page',
      'New: 14 integrations — Teams, Slack, Telegram, Discord, Email, Webhooks, Calendar, n8n, Zapier, Make, Google Sheets, Power BI, REST API',
      'New: DokuFluss-style onboarding with 5 company profiles and module toggle switches',
      'New: AI Meeting Summary import — 3-step flow with preview (Teams, Google Meet, Zoom, Webex)',
      'New: Project Dashboard with unified KPIs from all modules',
      'New: Global Search across 9 entity types',
      'New: 5 comprehensive demo projects with data across 12 modules each',
      'New: Quality dashboard summary (incidents, inspections, NCRs, defects)',
      'New: SVG Gantt chart with BIM element badges on linked activities',
      'New: Three.js BIM Viewer with processing status tracking',
      'Fix: 90+ bugs from deep QA audit across all modules',
      'Fix: 15 critical security and crash fixes from QA test reports',
      'Fix: CPM engine now correctly processes schedule relationships',
      'Polish: Consistent UI across all pages — animations, badges, forms, mobile responsive',
    ],
  },
  {
    version: '0.9.1',
    date: '2026-04-07',
    changes: [
      'New: Discord webhook integration — send project notifications to Discord channels',
      'New: WhatsApp Business integration (Coming Soon) — template messages via Meta Cloud API',
      'New: Integration Hub now has 14 cards grouped by category: Notifications, Automation, Data',
      'New: n8n, Zapier, and Make cards with setup instructions for workflow automation',
      'New: Google Sheets export card — open your BOQ exports directly in Sheets',
      'New: Power BI / Tableau card — connect BI tools to our REST API',
      'New: REST API card with link to interactive OpenAPI docs',
      'Fix: Cross-module event flow audit and corrections',
    ],
  },
  {
    version: '0.9.0',
    date: '2026-04-07',
    changes: [
      'New: 30 backend modules — contacts, finance, procurement, safety, inspections, tasks, RFI, submittals, NCR, meetings, CDE, transmittals, BIM Hub, reporting, and more',
      'New: Internationalization foundation — multi-currency with 35 currencies, 198 countries, 30 work calendars, 70 tax configs, ECB exchange rates',
      'New: Module System v2 — enable/disable modules at runtime with dependency checking',
      'New: 13 frontend pages — Contacts, Tasks (Kanban), RFI, Finance, Procurement, Safety, Meetings, Inspections, NCR, Submittals, Correspondence, CDE, Transmittals',
      'New: SVG Gantt chart — day/week/month zoom, dependency arrows, critical path highlighting, drag-to-reschedule',
      'New: Three.js BIM Viewer — discipline coloring, raycaster selection, properties panel',
      'New: Notification bell — API-backed with 30s polling, dropdown, mark-all-read',
      'New: Threaded comments component — works on any entity, @mentions, nested replies',
      'New: MoneyDisplay, DateDisplay, QuantityDisplay — locale-aware formatting components',
      'New: Regional Settings — timezone, measurement system, paper size, date/number format, currency',
      'New: CPM engine — forward/backward pass, float calculation, calendar-aware critical path',
      'New: 8 regional packs (US, DACH, UK, Russia, Middle East, Asia-Pacific, India, LatAm)',
      'New: 3 enterprise packs (approval workflows, deep EVM, RFQ bidding)',
      'New: 568 translation keys across 20 languages with professional construction terminology',
      'New: 50 integration tests for critical API flows',
      'Fix: All pages now have consistent layout, modals, and spacing',
    ],
  },
  {
    version: '0.8.0',
    date: '2026-04-07',
    changes: [
      'New: Add custom columns to your BOQ — pick from 7 ready-made presets (procurement, notes, quality, sustainability, BIM) or build your own',
      'New: One-click renumber positions with multiple schemes — choose how you want them numbered, see a live preview before applying',
      'New: Project Health bar shows how complete each project is and what to do next',
      'New: "Continue your work" card on Dashboard jumps you straight back to the BOQ you were editing',
      'New: Stronger account security — strong-password policy, login rate limit, automatic token refresh after password change',
      'New: Friendlier error messages — instead of "API 500" you now see the real reason something failed',
      'New: Update notification card shows in the sidebar, About page and Settings whenever a new version is out',
      'Fix: Adding items to Change Orders no longer crashes',
      'Fix: Custom columns now persist correctly when you add several',
      'Fix: Editing a custom column no longer overwrites the position price',
      'Fix: Archived projects truly disappear from lists',
      'Polish: Unpriced BOQ rows are now subtly highlighted so they\'re easier to spot',
      'Polish: Better accessibility on the login and register pages',
      'Polish: Brand-blue update card with grouped highlights and a single "How to update" button',
    ],
  },
  {
    version: '0.7.0',
    date: '2026-04-07',
    changes: [
      'New: Add your own columns to the BOQ',
      'New: Multi-level sections so you can structure big estimates the way you think',
      'New: Excel import keeps your original columns so re-exports look the same',
      'New: Formula engine for assemblies — variables, conditions, math functions',
      'New: Quick Start button creates a project + BOQ in one click',
      'New: Beginner sidebar mode hides advanced modules until you need them',
      'New: Friendlier error messages everywhere',
      'Fix: Drag-and-drop in the BOQ no longer crashes',
      'Fix: 4D schedule and 5D cost model fully working again',
      'Fix: Mobile sidebar locks the page background',
    ],
  },
  {
    version: '0.6.0',
    date: '2026-04-07',
    changes: [
      'New: Resource quantities scale automatically when you change a position quantity',
      'New: Unit rate is auto-calculated from the resources you add to a position',
      'New: Move positions between sections by drag-and-drop',
      'New: Wide-screen layout for the Settings page',
      'New: Data Explorer heatmap + pivot export to CSV/Excel',
      'Fix: Single-click number editors for quantity and rate',
      'Polish: Quality and consistency improvements across the app',
    ],
  },
  {
    version: '0.5.0',
    date: '2026-04-06',
    changes: [
      'New: PDF Takeoff — measure and tag drawings right inside the app',
      'New: Professional Excel + PDF export with cover pages and signature lines',
      'New: CAD/BIM module — turn a 3D model pivot straight into a BOQ',
      'New: Privacy Policy and Terms of Service pages',
      'New: Modal dialogs for creating projects, BOQs and assemblies',
      'Polish: Data Explorer redesigned with a clean dropzone + recent files grid',
    ],
  },
  {
    version: '0.4.0',
    date: '2026-04-06',
    changes: [
      'New: Create projects, BOQs and assemblies from quick modal dialogs',
      'New: BOQ list filters by the active project from the header',
      'New: Privacy Policy and Terms of Service pages',
      'Fix: New BOQ now appears in the list right after you create it',
    ],
  },
  {
    version: '0.3.0',
    date: '2026-04-05',
    changes: [
      'New: Data Explorer with search, column picker and CSV export',
      'New: Save and reopen CAD analyses inside a project',
      'New: Background upload queue for CAD files',
      'New: Field Reports — daily logs, weather, workforce, PDF export',
      'New: Photo Gallery — uploads with EXIF + GPS metadata',
      'New: Markups & Annotations and Punch List modules',
      'New: Requirements export and import (CSV / Excel / JSON)',
      'New: 60+ missing translation keys added across all 21 languages',
    ],
  },
  {
    version: '0.2.1',
    date: '2026-04-04',
    changes: [
      'Security: stronger document download checks, CORS hardening, login enumeration fix',
      'Fix: BOQ duplication crash',
      'Fix: cost database import error on Windows',
      'Fix: pip install of the backend works again',
      'Fix: Docker quickstart',
      'New: Comparison table in the README',
      'New: Setup Wizard link in the welcome modal',
      'New: Version number shown in the sidebar',
      'Updated: 9 dependencies bumped to address security advisories',
    ],
  },
  {
    version: '0.1.1',
    date: '2026-04-01',
    changes: [
      'Fix: Settings page freeze resolved + missing "Regional Standards" EN translation',
      'Fix: DELETE project 500 error + XSS sanitization in project names',
      'Fix: Removed duplicate "#1" on login page',
      'Build: Added requirements.txt for easier pip install',
      'Build: Cleaned repository for GitHub release (removed 159 dev artifacts)',
    ],
  },
  {
    version: '0.1.0',
    date: '2026-03-27',
    changes: [
      'Initial release',
      '18 validation rules (DIN 276, GAEB, BOQ Quality)',
      'AI-powered estimation (Text, Photo, PDF, Excel, CAD/BIM)',
      '55,000+ cost items across 11 regional databases',
      '20 languages supported',
      'BOQ Editor with AG Grid, markups, and exports',
      '4D Schedule with Gantt and CPM',
      '5D Cost Model with EVM',
      'Tendering with bid comparison',
    ],
  },
];

export function Changelog() {
  const { t } = useTranslation();

  return (
    <div id="changelog">
      <h2 className="text-lg font-semibold text-content-primary mb-4">
        {t('about.changelog_title', { defaultValue: 'Changelog' })}
      </h2>

      <div className="relative">
        {/* Timeline line */}
        <div className="absolute left-[18px] top-3 bottom-3 w-px bg-border-light" />

        <div className="space-y-6">
          {CHANGELOG.map((entry) => {
            const isCurrent = entry.version === APP_VERSION;
            return (
            <div key={entry.version} className="relative flex gap-4">
              {/* Timeline dot — emerald + pulse for the current release, blue for older */}
              <div className={`relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 ${isCurrent ? 'bg-emerald-50 border-emerald-500 dark:bg-emerald-900/20' : 'bg-oe-blue/10 border-oe-blue'}`}>
                {isCurrent && (
                  <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-30 animate-ping" />
                )}
                <div className={`h-2.5 w-2.5 rounded-full ${isCurrent ? 'bg-emerald-500' : 'bg-oe-blue'}`} />
              </div>

              {/* Content */}
              <div className="flex-1 pt-0.5">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant={isCurrent ? 'success' : 'blue'} size="sm">v{entry.version}</Badge>
                  {isCurrent && (
                    <span className="text-2xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                      {t('about.current_version', { defaultValue: 'Current' })}
                    </span>
                  )}
                  <span className="text-xs text-content-tertiary ml-auto">{entry.date}</span>
                </div>

                <ul className="space-y-1.5">
                  {entry.changes.map((change, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm text-content-secondary">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-content-tertiary/50" />
                      <span>{change}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
