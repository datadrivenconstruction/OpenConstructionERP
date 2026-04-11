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
    version: '1.4.8',
    date: '2026-04-11',
    changes: [
      'Real-time collaboration L1 — soft locks + presence (issue #51). Maher00746 asked: "Does the platform support real-time collaboration when multiple users edit the same BOQ?". Full plan has 3 layers (L1 soft locks / L2 Yjs text / L3 full CRDT rows). v1.4.8 ships L1, which covers the 90% case ("two estimators editing the same position should not trample each other") without dragging in a CRDT runtime, Yjs, or Redis',
      'New backend module collaboration_locks (1,580 LOC, 10 files) at /api/v1/collaboration_locks. oe_collab_lock table with UniqueConstraint(entity_type, entity_id). Atomic acquire via read-then-insert-or-steal at the repository level — cross-dialect (SQLite dev + PG prod), races handled by catching IntegrityError and re-reading the winner. Expired rows are stolen in place via UPDATE. Heartbeat extends TTL in 30s steps. Background sweeper runs every 30s. Entity-type allowlist mirrors the existing collaboration module',
      'Presence WebSocket: WS /collaboration_locks/presence/?entity_type=...&entity_id=...&token=<jwt> broadcasts JSON frames {event, ts, ...} to every connected client subscribed to the same entity. Auth via token query param (browser WebSocket cannot set headers). Frame types: presence_snapshot, presence_join, presence_leave, lock_acquired, lock_heartbeat, lock_released, lock_expired, pong. Multi-tab dedup, presence_join excludes the joiner from its own broadcast, lock_acquired intentionally echoes to the holder for state confirmation',
      'Worker-local presence hub (no Redis, no LISTEN/NOTIFY in v1.4.8 — single presence_hub = PresenceHub() module-level instance). Multi-worker deployments still get correct locking via the DB but presence broadcasts are worker-scoped. Documented upgrade path to LISTEN/NOTIFY is a single internal swap with no caller changes',
      'Frontend useEntityLock hook (auto-acquire on mount, 15s heartbeat, cleanup-release on unmount, graceful network-error degradation), usePresenceWebSocket hook (JWT-via-query-param, roster state), PresenceIndicator component (green/amber/blue pill: "You are editing" / "Locked by Anna 3:42 remaining" / "N viewers"). 5 files, 636 LOC under frontend/src/features/collab_locks/',
      'BOQ wiring in BOQGrid.tsx: acquires on onCellEditingStarted (per ROW not per cell — tracks held locks in rowLockMapRef and reuses on subsequent cell edits within the same row), releases on onCellEditingStopped, releases all held row locks on unmount. 409 cancels the edit and shows a toast with holder name + remaining seconds. Network errors degrade silently',
      '17 / 17 integration tests passing — covering acquire-when-free, conflict-409, idempotent re-acquire, heartbeat-extends, heartbeat-rejects-non-holder, release, idempotent missing-id release, allowlist-400, GET /entity/ none-or-holder, GET /my/ list, expired-lock-can-be-stolen, sweeper, plus 3 WebSocket smoke tests (auth rejection, snapshot+broadcast delivery, presence_join across two clients)',
      'Deferred to v1.5/v2.0: L2 (Yjs Y.Text on description/notes — needs yjs + y-websocket deps + server CRDT state), L3 (full CRDT BOQ rows — 3x the surface for marginal gain), Postgres LISTEN/NOTIFY fan-out (only needed for multi-worker deployments), audit log of lock events, org-scoped RBAC, frontend wiring for non-BOQ entities (the hook + indicator are ready to drop into requirements / RFIs / tasks / BIM elements editors)',
      'Verification: backend ruff clean across the new module + tests, 17/17 integration tests in 65.7s, version sync at 1.4.8, frontend tsc --noEmit exit 0, Alembic migration a1b2c3d4e5f6 chains correctly on top of head b2f4e1a3c907',
    ],
  },
  {
    version: '1.4.7',
    date: '2026-04-11',
    changes: [
      'BIM viewer: determinate geometry-loading progress bar replaces the silent spinner. ColladaLoader onProgress is now wired through ElementManager.loadDAEGeometry → BIMViewer state, so users see streaming percentage + gradient fill + "Streaming geometry from server / Finalising scene" status text instead of staring at a spinning loader for 30+ seconds on big Revit models',
      'Sidebar BETA badges on /bim, /bim/rules, /chat — tiny lowercase neutral-grey badge so users know not to rely on those modules for production work yet, without visually competing with the rest of the sidebar',
      'Restored rich GitHub README. The d3d2319 rewrite stripped the README from 450 lines to 53 — dropping the Table of Contents menu, the comparison table, the feature gallery with screenshots, the workflow diagram, the 12 feature blocks, and the regional standards table. All restored, version bumped to 1.4.6 in badge + footer',
      'F1: BIMPage.tsx upload handler dropped two (res as any) casts. BIMCadUploadResponse now declares element_count + typed status union so the success toast no longer guesses fields',
      'F5: BIMFilterPanel resets every transient filter state slot (search / storey checkboxes / type checkboxes / expanded headers / active group highlight) when the user switches BIM models. Previously checkboxes for storeys / types from the old model lingered into the new one',
      'T2.3: Assembly.total_rate stays in sync when a CostItem.rate changes externally. New assemblies/events.py subscribes to costs.item.updated, finds every Component pointing at the updated item, refreshes the per-component unit_cost + total, and re-runs the parent assembly total math. BOQ positions created BEFORE the rate change are not touched (locked financial commitments)',
      'T3.5: requirements.list_by_bim_element uses the PostgreSQL JSONB @> containment operator at the SQL level on PG, doing the filtering in the database instead of loading every project requirement and filtering in Python. SQLite still uses the Python fallback. Mirrors tasks/service.py dialect-aware pattern',
      'T8 (deferred from v1.4.5): 12 broken integration tests now pass. Root cause was a mix of trailing-slash mismatch (10 tests — redirect_slashes=False is intentional, fix is on the test side), missing required query param (1 test — tendering needs project_id for cross-tenant safety), and missing auth header (2 tests). Audited and fixed every site',
      'Notifications subscriber dialect guard: the S3 framework added in v1.4.6 deadlocked under SQLite because it opened its own write session inside the upstream transaction (SQLite is single-writer per file). Handlers now probe the dialect at entry and bail out fast on SQLite — production uses PostgreSQL where this is a non-issue',
      'T2.1 Project Intelligence smart actions: run_validation, match_cwicr_prices, generate_schedule are now real implementations instead of redirect-stubs. run_validation runs the DIN 276 + boq_quality rule sets against the project BOQ and returns the new ValidationReport id with pass/warning/error counts. match_cwicr_prices walks every leaf BOQ position with a zero unit_rate, calls CostItemService.suggest_for_bim_element with the position description + classification, writes the top match back to unit_rate (qty × rate recomputed), and publishes boq.prices.matched. generate_schedule refuses if a schedule exists, else creates a draft and delegates to ScheduleService.generate_from_boq. 9 new unit tests',
      'T9 vector_routes factory: extracted ~291 lines of duplicated vector/status + vector/reindex boilerplate from 6 of 8 module routers (documents, tasks, risk, validation, requirements, erp_chat) into a new app/core/vector_routes.py:create_vector_routes() helper. Each module now does include_router(create_vector_routes(...)) in 4 lines instead of 50. Net -105 LOC in module routers. boq and bim_hub keep their hand-written endpoints because they accept extra optional query params the factory does not yet model. All 16 existing vector routes preserved exactly',
      'Costmodel honest schedule reporting: removed the hardcoded time_elapsed_pct = 50.0 fallback in calculate_evm that was making every unscheduled project look on_track / at_risk in the dashboard. evm_status is now schedule_unknown when date parsing fails. Bonus TCPI zero-denominator fix in full_evm/service.py (returns "inf" sentinel when remaining work exists but budget is exhausted). New DELETE /costmodel/projects/{pid}/5d/snapshots/{sid} endpoint for stale snapshot cleanup. 21 new unit tests, 963 total passing, zero regressions',
      'BIM frontend correctness wave (F2/F3/F4/F6): AddToBOQModal derives effectiveBOQId via useMemo so a BOQ removed mid-flow can not leave a stale id; all four BIM link modals reset internal state on element identity change; LinkActivityToBIMModal + LinkRequirementToBIMModal replaced the hardcoded "first 200 + N more" stub with real pagination (PAGE_SIZE 50 + Load more button); ElementManager now tracks every cloned THREE.Material and disposes them in resetColors / dispose, plugging a slow GPU memory leak that grew every status-color toggle',
      'Levels filter (replaces "Storeys"): Revit users overwhelmingly think in terms of Level (the actual Revit property), and the upload pipeline missed any element whose level was buried inside the properties JSONB blob (common for Revit Excel where Level is a Type Parameter not a column). Backend _rows_to_elements now calls a new _extract_storey helper that scans the properties blob for 20 case-insensitive keys (Level, Base Constraint, Reference Level, Schedule Level, IFCBuildingStorey, Geschoss, Etage…) and normalises literal "None" / "<None>" / "null" / "-" / "—" strings to None so the filter no longer shows a fake "None (586)" bucket. Frontend renamed STOREYS → LEVELS, "by Storey" → "by Level". Internal state keys unchanged so saved filter groups keep working',
      'BIM converter preflight + one-click auto-install: dropping a .rvt at /bim used to silently fail with a hardcoded English error after wasting an 18 MB upload. Backend now refuses .rvt/.dwg/.dgn upfront with status=converter_required when find_converter is None, returning converter_id + install_endpoint so the frontend can route the user straight into the install flow. Success-path response surfaces the real model.error_message instead of the hardcoded string',
      'BIM converter installer rewritten to use the real datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN repo (the old code pointed at a non-existent ddc-community-toolkit URL). Walks DDC_WINDOWS_Converters/DDC_CONVERTER_{FORMAT}/ via the GitHub Contents API, downloads files from raw.githubusercontent.com in parallel via ThreadPoolExecutor(8) — RVT goes from ~5 minutes sequential to ~30-60 seconds for the 175 files / 598 MB it ships. Per-format install dirs (~/.openestimator/converters/{ext}_windows/) so each Qt6 + Teigha bundle stays isolated. Path traversal defence runs BEFORE network IO. Atomic rmtree rollback on partial failure. Linux returns platform_unsupported with copy-paste apt commands (no silent sudo from a web handler). macOS gets a graceful "convert to IFC first" message',
      'find_converter now probes the new per-format Windows install dirs and Linux apt install paths (/usr/bin/ddc-{ext}converter) so installed converters are picked up instantly with no service restart',
      'New BIMConverterStatusBanner component: amber banner above /bim listing every missing converter with name, real size in MB, and one-click Install. Mutation runs through React Query, success toast, automatic refetch. Session-scoped dismiss. New InstallConverterPrompt modal pops up when the user drops a file whose converter is missing — pre-upload guard intercepts the drop so no megabytes wasted. On install success the original upload bytes are replayed automatically. The previously hardcoded "Could not extract elements" error is replaced with the backend error_message. 27 new i18n keys, all with English defaultValue',
      'Verification: backend ruff clean across every v1.4.7-touched file, 16/16 BIM converter preflight + cross-module + PI action tests passing, 963 unit tests in costmodel/finance/full_evm suites passing, version sync at 1.4.7, integrity check at 23 hits, frontend tsc --noEmit clean, live test of GitHub Contents API directory walk against the real cad2data-Revit-IFC-DWG-DGN repo confirms 175 files enumerate cleanly',
    ],
  },
  {
    version: '1.4.6',
    date: '2026-04-11',
    changes: [
      'Security: contacts module IDOR fix. List/search/by-company/stats endpoints used to return EVERY contact in the database to anyone with contacts.read — 3 TODO(v1.4-tenancy) markers acknowledged the gap. Now scoped via owner_id (created_by proxy) at the repository layer; admins still see the global view via _is_admin() bypass',
      'Security: collaboration module had ZERO permission checks. No RequirePermission on any of the 7 endpoints, no project access validation — any authenticated user could list/create/edit/delete comments and viewpoints across project boundaries. Now wired via new collaboration/permissions.py registering 4 perms (Viewer/Editor) plus an entity_type allowlist (16 entries) that rejects orphaned metadata at the router boundary',
      'Notifications subscriber framework: notifications was a ghost component since day one — service had create()/notify_users() but nothing in the platform called them. New notifications/events.py wires a declarative subscription map: boq.boq.created → creator notify, meeting.action_items_created → per-task-owner notifies, cde.container.state_transitioned → actor notify. Adding a new trigger is now a one-line entry',
      'Raw SQL → ORM in 3 remaining cross-link sites (punchlist/meetings/takeoff). v1.4.4 fixed bim_hub upload, but the same hand-rolled INSERT INTO oe_documents_document via text() pattern lived in punch photos, meeting transcripts, and takeoff PDFs. All replaced with clean Document(...) ORM inserts. Verified zero raw INSERTs remain across all 4 sites',
      'Meetings complete: stop publishing meeting.action_items_created event when task creation fails. The endpoint used to wrap task creation in try/except that swallowed all errors then published the event regardless — telling notifications + vector indexer "tasks created" even when zero made it to the DB. Now per-item isolation, separate created/failed lists, only publish when at least one task persisted, payload carries created_count + failed_count for "3 of 5" UI display',
      'project_intelligence collector now reads from requirements / bim_hub / tasks / assemblies. Previously blind to all 4 modules — score was a partial picture and the AI advisor could not surface gaps like "no requirements defined" or "BIM elements not linked to BOQ". Added 4 new state dataclasses + 4 parallel collectors via asyncio.gather. Smoke-tested against the live DB with the 5 most recent projects (collector now sees req=1 / bim=2 / tasks=1 etc on projects from the v1.4.5 cross-module integration tests)',
      'Verification: backend ruff clean across every v1.4.6-touched file, 174 unit+integration tests passing, version sync at 1.4.6, integrity check passes',
      'Deferred to v1.4.7+: project_intelligence actions implementation (3 dead-code endpoints), costmodel vs full_evm consolidation, costmodel PV approximation flaw, BIM frontend 14 findings (200-item modal caps, type-unsafe casts, modal pattern drift), assembly total_rate invalidation, create_vector_routes factory, trailing-slash test fixes, test coverage push for costmodel/finance/full_evm + 6 shared infra modules',
    ],
  },
  {
    version: '1.4.5',
    date: '2026-04-11',
    changes: [
      'Deep-audit cut driven by 3 parallel sub-agents that investigated requirements, project_intelligence, erp_chat, vector_index, bim_hub element groups, quantity maps, and assemblies for hacks, half-baked logic, and missing cross-module wiring. 40+ findings; this cut tackles the cross-module correctness ones plus the biggest test coverage holes',
      'Cross-module data integrity: orphaned BIM element ids cleaned up on element delete. 3 of 5 link types denormalise BIM ids into JSON arrays (Task / Activity / Requirement) instead of FK tables — they used to leak stale refs FOREVER. New _strip_orphaned_bim_links runs inline on the active session inside bulk_import_elements + delete_model so it shares the upstream transaction (no SQLite write-lock contention) and rolls back atomically on failure',
      'Requirement embeddings now include pinned bim_element_ids in to_text() so semantic search like "requirements linked to roof elements" actually works. The link event used to re-embed the row but the embedding was unchanged because to_text() never read metadata_["bim_element_ids"]',
      'Property filter _matches is now type-aware: handles strings via fnmatch, lists via membership/intersection, dicts via recursive containment, None via explicit "must not be set" semantics. Was exact equality before, silently broke on multi-valued IFC properties (materials=["steel"] vs filter "steel" returned False). 20 new unit tests pin every branch',
      'Quantity map applies now surface skipped (element, rule) pairs with structured reason ("missing_property" or "invalid_decimal") via new skipped_count + skipped[] fields on QuantityMapApplyResult. Estimators used to see empty populations with no clue why',
      'Per-collection asyncio.Lock on reindex_collection prevents two concurrent reindex requests against the same vector collection from interleaving purge+index ops and leaving the store with partial indexes / dup ids / ghost rows. Different collections still reindex in parallel',
      'Missing CRUD: PATCH /requirements/{set_id} (rename / edit / change status without delete-and-recreate) and POST /requirements/{set_id}/requirements/bulk-delete/ (up to 500 ids in a single transaction with skipped count surfaced). Routes mounted: 19 → 21',
      'Type discipline: GateResult.score migrated from String(10) to Float via Alembic migration b2f4e1a3c907 (idempotent batch-alter). Lexicographic sort meant "9.5" > "85.0" — every "top N gate runs" report was silently wrong',
      'Test coverage push: 113 new unit tests across 7 vector adapter files (BOQ, Documents, Tasks, Risks, BIM elements, Validation, Chat — previously only Requirements had coverage). 20 new tests for the property matcher. 1 new end-to-end integration test for orphan cleanup. Total ~135 new tests',
      'Frontend: BIMPage.tsx hardcoded English strings replaced with i18n keys (deferred from v1.4.4 audit). UploadPanel + NonReadyOverlay + empty-state now go through useTranslation(). New bim.upload_* / bim.overlay_* keys added to i18n-fallbacks.ts. The HARD rule from CLAUDE.md is now honoured',
      'Verification: 113 vector adapter tests + 20 property matcher tests + 3 integration tests all green, ruff clean across every v1.4.5-touched file, frontend tsc --noEmit clean, version sync at 1.4.5',
      'Deferred to v1.4.6: project_intelligence.collector wiring 4 missing modules, project_intelligence actions implementation (3 of 8 are dead code lying to users), assembly total_rate invalidation, create_vector_routes factory (~250 LOC dedup), 12 broken integration tests trailing-slash audit',
    ],
  },
  {
    version: '1.4.4',
    date: '2026-04-11',
    changes: [
      'Backend hardening cut driven by a multi-agent quality audit. No new user-visible features — focus is "everything that already exists works at scale and stays honest about which version it is"',
      'Memory hazard fix in vector auto-backfill: previously _auto_backfill_vector_collections did SELECT * on each indexed table at startup, materialised the full result set into a Python list, and only THEN sliced down to vector_backfill_max_rows — on a 2M-row deployment that allocated gigabytes of RAM before the cap could even kick in. Now issues a cheap COUNT(*) first to decide whether reindexing is needed, then pulls only the capped number of rows with LIMIT applied at the SQL level. Side benefit: 8 per-collection _load_X closures collapsed into a single declarative backfill_targets registry, ~80 LOC reduction in main.py',
      'Python 3.14 readiness: replaced datetime.utcnow() (deprecated since 3.12) with datetime.now(UTC) across 8 call sites — boq/router.py:2991, documents/service.py:475, tendering/router.py:378, project_intelligence/collector.py:680, punchlist/router.py:299, meetings/router.py:984, takeoff/router.py:1872, plus bim_hub/router.py:869 (rewritten as ORM insert, see below)',
      'Replaced raw SQL INSERT with ORM Document(...) in bim_hub/router.py upload_cad cross-link to Documents hub — the parameter binding was safe but the pattern was fragile (any future Document schema change would silently break the cross-link without test coverage) and shipped a stray utcnow(). Now uses the model directly with all defaults + timestamps inherited from Base',
      'Functional ruff cleanup: F401 unused imports removed from boq/events.py, project_intelligence/collector.py (uuid), project_intelligence/scorer.py (Callable), search/router.py (Depends). F541 f-string without placeholders fixed in project_intelligence/advisor.py:399. B905 zip() without strict= fixed in costs/router.py:1742 (the cost-database resource loader — without strict=True an array length drift would silently corrupt assembly composition mid-import). Plus auto-fixed UP037/UP041/I001 style issues',
      'Version-sync CI guard (NEW): backend/pyproject.toml silently drifted from frontend/package.json for FOUR minor versions (v1.3.32 → v1.4.2 all shipped with the Python package stuck on 1.3.31, so /api/health lied because Settings.app_version reads from importlib.metadata). v1.4.3 retro-fixed the literal but left the door open. New scripts/check_version_sync.py reads both files plus the top entries of CHANGELOG.md and Changelog.tsx and exits non-zero on mismatch. Wired into both .pre-commit-config.yaml as a local hook AND .github/workflows/ci.yml as a dedicated version-sync job that runs in parallel with backend+frontend lanes. Tested negatively (catches drift) and positively (passes at 1.4.4)',
      'Verification: Backend ruff check clean across every file touched in v1.4.4. Backend boots cleanly via app.router.lifespan_context smoke test (57 modules loaded, 217k vectors indexed, no startup errors). check_version_sync.py passes at 1.4.4',
      'Deferred to v1.4.5: BIMPage.tsx i18n compliance (11+ hardcoded strings), create_vector_routes() factory (~250 LOC duplication across 8 modules), trailing-slash audit of 12 broken integration tests (redirect_slashes=False is intentional — fixes CORS 307 issue), deep-dive audit of recently-added modules looking for hacks, half-baked logic, and missing cross-module wiring',
    ],
  },
  {
    version: '1.4.3',
    date: '2026-04-11',
    changes: [
      'Requirements ↔ BIM cross-module integration — Requirements (EAC triplets — Entity / Attribute / Constraint) are now the 5th cross-module link type on BIM elements, mirroring the existing BOQ / Documents / Tasks / Schedule activities pattern. Pin a constraint like "fire_rating = F90" to a wall element with one click and trace it back from either side',
      'New oe_requirements vector collection (8th total) — embeds the EAC triplet plus unit / category / priority / status / notes via a new RequirementVectorAdapter. Multilingual by default, works across English / German / Russian / Lithuanian / French / Spanish / Italian / Polish / Portuguese',
      'Requirements service event publishing — new _safe_publish helper plus standardised requirements.requirement.created/updated/deleted/linked_bim events on every CRUD and link operation. The vector indexer subscribes and refreshes the embedding automatically',
      'New service methods: link_to_bim_elements (additive by default; pass replace=true to overwrite) stored under metadata_["bim_element_ids"] so no schema migration needed; list_by_bim_element reverse query scoped to a project for performance',
      'New router endpoints: PATCH /requirements/{set_id}/requirements/{req_id}/bim-links/, GET /requirements/by-bim-element/?bim_element_id=&project_id=, GET /requirements/vector/status/, POST /requirements/vector/reindex/, GET /requirements/{set_id}/requirements/{req_id}/similar/',
      'New RequirementBrief in bim_hub schemas + linked_requirements field on BIMElementResponse. BIMHubService.list_elements_with_links() Step 6.5 loads every requirement in the project and filters in Python on the bim_element_ids array',
      'New LinkRequirementToBIMModal — mirrors LinkActivityToBIMModal exactly: loads every requirement set in the project, flattens into a searchable list, click → PATCH bim-links → invalidate the bim-elements query. Color-coded by priority (must / should / may) and status (verified / conflict / open)',
      '"Linked requirements" section in BIMViewer element details panel — violet themed, slots between "Schedule activities" and semantic similarity. Renders entity.attribute + constraint + priority badge + click-to-open',
      'BIMPage wiring — new linkRequirementFor state + handleLinkRequirement/handleOpenRequirement handlers, modal mount, props passed to BIMViewer',
      'RequirementsPage expanded row now shows a "Pinned BIM elements" cell with the count read from metadata.bim_element_ids. Click navigates to /bim?element= with the first pinned element preselected. Plus deep-link parsing for ?id=<requirement_id> that fans out detail fetches across every set to find the owning set, switches to it and expands the row',
      'GlobalSearchModal facet support — fuchsia color for the new Requirements pill, oe_requirements mapped to /requirements?id= in hitToHref. VectorStatusCard picks up the new collection via REINDEX_PATH so admins can trigger a reindex from Settings. Auto-backfill on startup now indexes requirements alongside the other 7 collections',
      'Also fixed (polish bundled into this cut): backend/pyproject.toml had silently drifted from the frontend version since v1.3.31 — every v1.4.x release reported "1.3.31" via /api/health because app_version reads from the Python package — bumped directly to 1.4.3. BIM CAD upload handler referenced ghost cad_path/cad_dir variables left over from the storage abstraction refactor, so IFC/RVT processing crashed with NameError on every upload attempt — replaced with a tempfile.TemporaryDirectory workspace that materialises the upload locally, runs the sync processor, uploads any geometry back through save_geometry, and stores the real storage key as canonical_file_path. SimilarItemsPanel no longer advertises requirements — the panel only knows the item id but the similar requirement route is nested under the parent set, so the placeholder URL would have 404-ed on every call',
      'Verification: 718 total routes mounted across 57 loaded modules (real count from module_loader.load_all + APIRoute inspection), 8 vector collections all with real adapters and reindex endpoints, frontend tsc --noEmit clean, backend ruff check clean across every v1.4.3-touched file, new unit coverage for RequirementVectorAdapter plus an integration test driving PATCH /bim-links/ → GET /by-bim-element/ → GET /models/{id}/elements/ (Step 6.5) end-to-end',
    ],
  },
  {
    version: '1.4.2',
    date: '2026-04-11',
    changes: [
      'Security: SQL injection guard in LanceDB id-quoting — every row id passed to vector_index_collection / vector_delete_collection / legacy cost-collection upsert is now re-parsed as a strict uuid.UUID before being interpolated into the id IN (...) filter. Defence-in-depth — the adapter layer always passes UUIDs from SQLAlchemy GUID() columns, so a parse failure now indicates a bug or attack and the row is silently dropped',
      'Security: Qdrant search payload mutation fix — vector_search_collection was using payload.pop() to extract reserved fields, mutating the qdrant client cached result objects. Replaced with non-mutating get() + dict comprehension',
      'Token-aware text clipping — _safe_text now uses the active SentenceTransformer tokenizer (when available) to clip at 510 tokens instead of the previous 4000-char cap. The character cap routinely exceeded the 512-token limit of small SBERT models, silently truncating tail content during embedding',
      'Frontend deep links now actually work — hitToHref was generating route formats that no destination page parsed. BOQ now uses /boq/<boqId>?highlight=<positionId>, DocumentsPage parses ?id= and auto-opens preview, TasksPage parses ?id= and scrolls + ring-highlights the matching card, RiskRegisterPage parses ?id= and opens detail view, BIMPage parses ?element= and selects after the elements list resolves. Each parser strips the param after one shot so refresh does not re-trigger',
      'New GET /api/v1/bim_hub/coverage-summary/?project_id=... — aggregates elements_total / elements_linked_to_boq / elements_costed / elements_validated / elements_with_documents / elements_with_tasks / elements_with_activities plus matching percentages. Documents/tasks/activities/validation lookups are wrapped defensively so a missing optional module does not 500 the call',
      'New BIMCoverageCard on the dashboard — 6 progress bars + headline percentage (avg of all metrics). Hides itself on projects with zero BIM elements so non-BIM workflows stay clean. Color-coded by completeness (green ≥75% / amber ≥40% / rose otherwise) with click-through to the BIM viewer',
      'BOQ position BIM badge is now clickable — the blue pill that shows the linked BIM element count was a read-only span; it is now a button that navigates to /bim?element=<first_id>. Estimators can finally jump from a BOQ row to the 3D model element it was created from in one click',
      'Schedule activity BIM badge — Gantt activity rows render a small amber pill with the count of pinned BIM elements when activity.bim_element_ids is non-empty. Click navigates to the BIM viewer with the first pinned element preselected. Closes the 4D-schedule reverse-nav gap',
      'BIM Quantity Rules page Suggest from CWICR — when a rule target is auto-create, the editor exposes a "Default unit rate" field plus a "Suggest from CWICR" button that calls /api/v1/costs/suggest-for-element/ with the rule filter context and prefills the top match. The rate persists into boq_target.unit_rate and is read by the apply path so the new BOQ position lands fully priced — no second pass in the BOQ editor',
      'Verification: 766 total routes mounted (up from 765 in v1.4.1). Frontend tsc --noEmit clean. Backend ruff check clean across every file touched in v1.4.2. _safe_quote_ids smoke-tested against literal SQL injection payloads and confirms attacker strings are dropped',
    ],
  },
  {
    version: '1.4.1',
    date: '2026-04-11',
    changes: [
      'Validation reports vector adapter — oe_validation collection now has a real adapter, event subscribers wired to validation.report.created/deleted publishes, and /api/v1/validation/vector/status/, /vector/reindex/, /{id}/similar/ endpoints. Semantic search across validation history (e.g. "find reports about missing classification codes") now works',
      'Chat messages vector adapter — oe_chat collection now has a real adapter. User and assistant messages with non-empty content are auto-indexed via a new erp_chat.message.created event publish in service.py. Long-term semantic memory for the AI advisor and per-message similarity search both now functional',
      'Auto-backfill on startup — new helper in main.py runs as a detached background task during lifespan startup. For each of the 7 collections it compares the live row count to the indexed count and backfills any missing rows (capped by vector_backfill_max_rows=5000 per pass). Disable with vector_auto_backfill=False. This closes the upgrade gap where existing v1.3.x BOQ / Document / Task / Risk / BIM / chat rows were unsearchable until the user manually called every per-module reindex endpoint',
      'Settings → Semantic Search Status panel — new VectorStatusCard renders a per-collection health table fetched from /api/v1/search/status/ with one-click reindex buttons, engine + model + dimension badges, connection indicator and a "purge first" toggle for embedding-model migrations',
      'BIM element update event subscription is now documented as a forward-compat hook (no current publisher — BIM elements are refreshed via bulk-import which already publishes created). The day a PATCH /elements/{id}/ endpoint lands, vector freshness will work without any wiring change',
      'Backend ruff check clean across every file touched in this sweep (auto-fixed import-order issues in two files)',
      'Verification: full app boot 765 routes, 34 vector/similar/search routes (up from 28 in v1.4.0). All 7 collections now have real adapters. multilingual-e5-small model loads from HuggingFace cache on first encode call. Frontend tsc --noEmit clean',
    ],
  },
  {
    version: '1.4.0',
    date: '2026-04-11',
    changes: [
      'Cross-module semantic memory layer — every business module now participates in a unified vector store via the new `EmbeddingAdapter` protocol. Six new collections live alongside the existing CWICR cost index: oe_boq_positions, oe_documents, oe_tasks, oe_risks, oe_bim_elements, oe_validation, oe_chat. All collections share one schema so the unified search layer writes to any of them through one code path',
      'Multilingual embedding model — switched the default from all-MiniLM-L6-v2 (English-only) to intfloat/multilingual-e5-small (50+ languages, same 384-dim). CWICR\'s 9-language cost database now ranks correctly across English, German, Russian, Lithuanian, French, Spanish, Italian, Polish and Portuguese. The legacy model is kept as a graceful fallback so existing LanceDB tables stay loadable',
      'Event-driven indexing — every Position / Document / Task / Risk / BIM Element create/update/delete event triggers an automatic upsert into the matching vector collection. No cron jobs, no Celery workers, no manual reindex needed for normal operation. Failures are logged and swallowed so vector indexing can never break a CRUD path',
      'Per-module reindex / status / similar endpoints — every participating module now exposes GET /vector/status/, POST /vector/reindex/?project_id=...&purge_first=false, and GET /{id}/similar/?limit=5&cross_project=true. Live for BOQ, Documents, Tasks, Risks and BIM elements',
      'Unified cross-collection search API — new oe_search module with GET /api/v1/search/?q=...&types=boq,documents,risks fans out to every selected collection in parallel and merges via Reciprocal Rank Fusion. Plus /search/status/ and /search/types/',
      'Cmd+Shift+K Global Search modal — frontend GlobalSearchModal with debounced input, facet pills (BOQ / Documents / Tasks / Risks / BIM / Validation / Chat) showing per-collection hit counts, current project scope toggle, grouped results and click-to-navigate routing. Works from any page including text fields',
      'Universal "Similar items" panel — drop-in <SimilarItemsPanel module="risks" id={...} /> component for any record card. Embedded in Risk Register detail (cross-project lessons learned reuse), BIM viewer element details, and Documents preview modal',
      'AI Chat semantic tools — six new tool definitions: search_boq_positions, search_documents, search_tasks, search_risks, search_bim_elements, search_anything. Each tool returns ranked hits with confidence scores. System prompt updated to prefer semantic tools for free-text questions and to quote provenance in responses',
      'AI Advisor RAG injection — project_intelligence/advisor.py answer_question() now retrieves the top-12 semantic hits from the unified search layer and injects them into the LLM prompt as a "Relevant context (semantic retrieval)" block. The advisor is now a proper RAG agent — answers stay anchored in real evidence instead of hallucinating',
      'Verification: 759 total routes mounted, 28 vector / similar / search routes wired end-to-end, 217 487 CWICR cost vectors auto-loaded on startup, frontend tsc --noEmit clean, backend imports clean across foundation + 5 modules + unified search + 6 new chat tools + advisor RAG',
    ],
  },
  {
    version: '1.3.32',
    date: '2026-04-10',
    changes: [
      'BIM viewer now shows a top-of-viewport health stats banner with multi-pill clickable chips: total elements, BOQ-linked count, validation errors, warnings, has-tasks and has-documents.  Each pill is a one-click smart filter that narrows the viewport to the matching element bucket — instant triage of model health without opening the filter sidebar',
      'BIMFilterPanel exposes the same five smart-filter chips at the top of the sidebar (errors / warnings / unlinked-to-BOQ / has tasks / has documents) with live counts derived from the cross-module link arrays on each element.  Chips only render when the bucket has matches so the panel stays clean on a healthy model',
      'Three new color-by modes for the BIM viewer grouped under "By compliance": 🛡️ Validation status (red error / amber warning / green pass / grey unchecked), 💰 BOQ link coverage (red unlinked / green linked), 📄 Document coverage.  Implemented via a new `ElementManager.colorByDirect()` helper that paints meshes from a fixed palette without rebuilding materials — keeps 60 fps even on 16k+ element models',
      'New `POST /api/v1/costs/suggest-for-element/` endpoint ranks CWICR cost items for a BIM element by classification overlap (DIN 276 / OmniClass), element-type / material / family keyword matches in description and code, and discipline tag overlap.  Each result returns a 0..1 confidence score plus human-readable match_reasons.  DB-agnostic (works on PostgreSQL AND SQLite), no pgvector required, candidate window capped at 200 with Python-side ranking',
      'AddToBOQModal "Create new position" tab now fetches the top-5 ranked rates for the clicked element on open and renders them as one-click chips with code, description, unit rate, unit, confidence dot (green ≥60% / amber ≥35% / grey otherwise) and a hover tooltip listing match reasons.  Clicking a chip populates description / unit / unit_rate from the matching CWICR item — no manual lookup needed.  Quantity is preserved (it comes from BIM geometry, not the cost database)',
      'Verification: tsc --noEmit clean, backend imports clean, both new endpoints and 13 existing routes mounted, smart filter chips + banner + colour modes wire end-to-end through BIMPage → BIMViewer → BIMFilterPanel without prop drilling spaghetti',
    ],
  },
  {
    version: '1.3.31',
    date: '2026-04-11',
    changes: [
      'BIM viewer cross-module panel is now READ-WRITE — three new inline modals let the user create new tasks, link existing documents, and link existing schedule activities to the selected BIM element WITHOUT leaving the BIM viewer.  No more navigating to /tasks → fill form → come back → reload to see the link.  Each section in the element details panel now has a "+ New" or "+ Link" button right next to its count badge',
      'New CreateTaskFromBIMModal — clicks "+ New" in the Linked Tasks section.  Pre-fills the title with element type ("Issue on Walls"), pins bim_element_ids on create so the new task instantly appears in the panel via React Query invalidation.  Type / priority / due date selectors built in.  Multi-element bulk-pin supported — when called with N elements the new task lands on all of them in one shot',
      'New LinkDocumentToBIMModal — clicks "+ Link" in the Linked Documents section.  Lists every document in the active project with searchable name / category / drawing-number / discipline filter.  Click a row → POST to /documents/bim-links/ → invalidates the bim-elements query → link badge appears in the panel without page reload',
      'New LinkActivityToBIMModal — clicks "+ Link" in the Schedule Activities section.  Loads every activity from every schedule in the project (parallel fetch, capped at 200 visible).  Click a row → PATCH /schedule/activities/{id}/bim-links additively (existing pinned elements are preserved, new ones appended) → invalidates the bim-elements query',
      'Cross-module sections always render — the four section blocks (BOQ / Documents / Tasks / Activities) used to be conditionally rendered only when the element had at least one link.  Now they always render with empty-state placeholders + the "+ Add" buttons so first-time users can discover the linking workflow without needing a pre-existing link to find the section',
      'Validation ↔ BIM per-element rules engine — new POST /api/v1/validation/check-bim-model endpoint runs universal BIM rules (wall has thickness, structural has material, fire-rating present, MEP has system, etc.) against every element in a model.  Live test on the demo: 33 962 rule checks → 22 610 passed / 10 497 warnings / 1 163 errors in one shot.  Per-element results are eager-loaded into BIMElementResponse.validation_results + the worst severity is rolled up into BIMElementResponse.validation_status (pass / warning / error / unchecked)',
      'BIM viewer renders per-element validation badge — new "Validation results" section appears in the element details panel when the element has at least one validation result, colour-coded by worst severity (rose for error, amber for warning, emerald for pass) with a ShieldX / ShieldAlert / ShieldCheck icon.  Lists up to 6 failed rules with rule_id + message preview',
      'Tasks page TaskCard renders a "Pinned to N BIM element(s)" badge in the source-indicator slot when the task has bim_element_ids populated.  Click the badge → /bim?element=… opens the BIM viewer with the first pinned element preselected.  Reverse-direction navigation symmetric with the existing Documents preview footer',
      'Bug fix — ValidationReportResponse pydantic schema was reading `report.metadata` from the SQLAlchemy ORM, which collides with the SQLAlchemy class-level `MetaData()` registry.  Switched to `validation_alias=AliasChoices("metadata_", "metadata")` so Pydantic reads the python attribute name first.  All validation routes (existing and the new check-bim-model) now serialise correctly',
      'Verification: 16 backend files compile clean, 5 new frontend files added (3 inline modals + extended types), tsc --noEmit clean, headless deep test 10/10 PASS at 60 fps, end-to-end curl tests pass for: validation run (33 962 checks), per-element validation embed, document link create + delete',
    ],
  },
  {
    version: '1.3.30',
    date: '2026-04-11',
    changes: [
      'BIM viewer is now deeply connected to Documents, Tasks, and Schedule (4D) — the BIM element details panel shows four cross-module link sections in one place: Linked BOQ Positions (existing), Linked Documents (drawings/RFIs/photos), Linked Tasks (defects/issues), and Schedule Activities (4D timeline).  Each section is collapsible, shows count badges, and clicking any row navigates to the matching detail page in the other module',
      'New `oe_documents_bim_link` table — joins Documents to BIM Elements with link_type (manual/auto), confidence, and a future-proof region_bbox column for PDF region markup.  Endpoints: GET/POST/DELETE under /api/v1/documents/bim-links/.  Bidirectional querying: filter by element_id OR document_id.  Eager-loaded into BIMElementResponse.linked_documents with document_name + document_category briefs in one round-trip',
      'New `Task.bim_element_ids` JSON column on `oe_tasks_task` — spatial defect management.  PATCH /api/v1/tasks/{id}/bim-links replaces the array, GET /api/v1/tasks/?bim_element_id=… is the reverse query.  Eager-loaded into BIMElementResponse.linked_tasks with title + status + task_type + due_date',
      'Schedule activity ↔ BIM linking — `Activity.bim_element_ids` field has existed since v1.x but was never wired up.  v1.3.30 adds: PATCH /api/v1/schedule/activities/{id}/bim-links, GET /api/v1/schedule/activities/by-bim-element/?element_id=…&project_id=…, and embedded brief in BIMElementResponse.linked_activities with name + start/end dates + percent_complete.  No migration needed (column was already there)',
      'Documents page preview modal — when previewing a drawing, a new "Linked BIM elements" footer strip lists every BIM element this document is linked to.  Click any element chip → navigates to /bim?element=… with the element preselected (reverse-direction navigation)',
      'Frontend API wrappers — added `listDocumentsForElement` / `listElementsForDocument` / `createDocumentBIMLink` / `deleteDocumentBIMLink` / `updateTaskBIMLinks` / `listTasksForElement` / `updateActivityBIMLinks` / `listActivitiesForElement` to features/bim/api.ts.  Type definitions for `BIMDocumentLinkBrief` / `BIMTaskBrief` / `BIMActivityBrief` added to ElementManager.ts',
      'Verification — three Alembic migrations applied (1f58eec86764 + ffe3f561e2c1), all backend files compile clean, frontend tsc clean, end-to-end curl test creates a document↔element link and the link instantly appears in the element response with full document_name + document_category populated, headless deep test still 10/10 PASS at 60 fps',
    ],
  },
  {
    version: '1.3.29',
    date: '2026-04-11',
    changes: [
      'Chat page (/chat) — removed the redundant "ERP AI Assistant" top bar.  The app\'s main layout already provides a header; the chat-specific bar duplicated UI and didn\'t match the rest of the site palette.  Clear chat now lives in the input bar (left panel)',
      'Release pipeline — synced root `CHANGELOG.md` with the in-app `Changelog.tsx` from v1.3.22 onwards.  The release workflow at `.github/workflows/release.yml` reads `## [VERSION]` patterns from CHANGELOG.md when a `v*` tag is pushed; without a matching section the GitHub release ships with a generic fallback message.  Now every v1.3.x release has a proper section in CHANGELOG.md with Added/Changed/Fixed bullets',
      'Update notification badge — investigation: the `UpdateNotification` widget polls https://api.github.com/repos/datadrivenconstruction/OpenConstructionERP/releases/latest every hour and shows a sidebar card when the latest GitHub release is newer than the running app version.  The widget is working — the gap was that GitHub\'s latest release was still v0.8.0 because **no version tags had been pushed since v1.0.0**.  All v1.3.x bumps lived in local commits only.  To restore the badge for old installations: tag the current commit (`git tag v1.3.29 && git push origin v1.3.29`), the release workflow auto-builds Docker + creates the GitHub release, and within an hour every running v1.3.x install pings the GitHub API and lights up the update card',
    ],
  },
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
