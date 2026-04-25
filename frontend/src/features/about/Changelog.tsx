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
    version: '2.5.0',
    date: '2026-04-25',
    changes: [
      'Fix: PDF takeoff page indicator no longer resets to 0/31 on Next click — stale useCallback closure over totalPages',
      'Fix: alembic multiple-head error blocking fresh-clone backend startup — v232 merge migration unifies money + contact-tenant chains',
      'Fix: PDF takeoff cross-page state leaks — in-progress drawing, calibration pick, and selected-measurement state now reset on page navigation (no more polygons that span pages)',
      'Fix: DWG takeoff cross-state leaks — half-drawn measurements no longer carry over between drawings or Model/Paper Space layouts; calibration pick state now resets on layout switch',
      'Fix: BIM viewer model-switch leaks — selection cleared on auto-pick / deep-link paths; geometry reload now keyed on modelId (not element count) so two same-count models no longer overlay',
      'Fix: BIM viewer prop callbacks (onElementSelect / onElementHover / onSelectionChange) now reach the parent — were captured-at-mount in stale closures',
      'Fix: PDF takeoff drop-zone advertised PDF/PNG/JPG/TIFF but silently rejected non-PDF files — now PDF-only with a warning toast on rejection',
      'Fix: Text-annotation Escape no longer creates a "ghost" annotation (onBlur race that fired confirm with the typed value despite cancel)',
      'Fix: Vite "Failed to fetch dynamically imported module" — pre-bundle 14 heavy lazy deps (ag-grid, recharts, jspdf, maplibre-gl, xlsx, yjs, dnd-kit, @xyflow/react) like pdf.js to keep chunk hashes stable across HMR',
      'Add: Delete / Backspace keyboard shortcut to remove the selected measurement (matches CAD/design tool convention)',
      'Fix: Makefile `make seed` and `make db-reset` no longer fail with ModuleNotFoundError — pointed at the actual seed_demo_showcase script',
      'Fix: requirements.txt win32_setctime now has sys_platform marker — pip install on Linux/macOS no longer aborts',
      'Verified: prod E2E confirms Next button advances 1/31 → 2/31 → 7/31 (no 0/31 regression) on https://openconstructionerp.com',
    ],
  },
  {
    version: '2.4.0',
    date: '2026-04-22',
    changes: [
      'Observability: reporting.auto_recalculate_kpis — 7 silent fallbacks now log at WARNING with project_id and full stack; fallback values (null / 0) preserved exactly',
      'Observability: takeoff PDF parsing — real pdfplumber/PyMuPDF exceptions surface in logs with size/magic-byte fingerprint (never absolute paths); double-failure returns a generic 400, keeps diagnostics server-side',
      'Observability: boq wildcard activity-log handler re-enabled behind a SQLite/PostgreSQL dialect guard; vector-index failures funneled through the 60 s rate-limited logger instead of thousand-line DEBUG spam',
      'Observability: StorageBackend.open_stream — safe default yields read_bytes() as a single chunk instead of raising NotImplementedError unconditionally',
      'i18n: all 42 built-in validation rules extract user-facing message / suggestion text to locale JSON bundles (en / de / ru, 87 keys each); locale read from ValidationContext.metadata["locale"], omission keeps pre-refactor English output',
      'Validation: GAEB rule set expanded from 1 → 5 — lv_structure, einheitspreis_sanity (ERROR), trade_section_code, quantity_decimals. Total built-in rules: 42 → 46',
      'Tests: +72 new unit tests (28 observability + 44 i18n/GAEB). Full backend suite: 1445 / 1445 green',
    ],
  },
  {
    version: '2.3.1',
    date: '2026-04-22',
    changes: [
      'Email: pluggable EmailBackend abstraction — backends: console / smtp / noop / memory; POST /auth/forgot-password now actually delivers the reset link',
      'Security: Contact.tenant_id column + idempotent backfill from created_by; list / stats / list_by_company scope via tenant_id with legacy-row fallback',
      'Observability: cache error logging — removed four except: pass blocks in RedisCache get/set/delete; rate-limited dedup (60 s window)',
      'Onboarding: `openestimate welcome` command + first-run detection + interactive "Open in browser now? [O/n]" prompt',
      'Tests: +49 new unit tests (email / contacts / cache); 1373 / 1373 green',
    ],
  },
  {
    version: '2.1.0',
    date: '2026-04-20',
    changes: [
      'DWG Takeoff — per-tool keyboard shortcuts (V/H/D/L/P/A/R/C/T + Esc) with letter shown in tooltips',
      'DWG Takeoff — undo/redo stack (50 entries) + toolbar buttons + Ctrl+Z/Ctrl+Y/Ctrl+Shift+Z',
      'DWG Takeoff — Shift-to-lock ortho/angle ghost ray during line/polyline drawing',
      'DWG Takeoff — snap modes (endpoint + midpoint) with on-canvas crosshair marker',
      'PDF Takeoff — per-tool keyboard shortcuts for 11 tools (V/D/P/A/O/C/R/T/H/W/X + Esc)',
      'PDF Takeoff — redo stack (alongside existing undo) with Ctrl+Y/Ctrl+Shift+Z',
      'PDF Takeoff — measurement properties panel (Group/Color/Annotation/Notes/Delete)',
      'PDF Takeoff — color-coded group legend overlay, click-to-hide per group',
      'BIM Viewer — toolbar screenshot button (PNG download + clipboard best-effort)',
      'BIM Viewer — 5D cost colour mode with blue→amber→red gradient by unit rate + legend strip',
      'BIM Viewer — URL deep-link state for camera + selection (?cx=...&cy=...&sel=a,b,c)',
      'CAD-BIM BI Explorer — URL-driven state for tab/slicers/pivot/chart (reload keeps view)',
      'CAD-BIM BI Explorer — Power-BI-style data bars across flat, tree-parent, tree-child rows',
      'Fix: clicking notifications no longer flashes the whole screen to black — Suspense boundary moved inside the layout so sidebar + header stay mounted during lazy chunk loads',
      'Fix: module preferences GET was calling the wrong URL (/v1/users/module-preferences instead of /v1/users/me/module-preferences/) — preferences now survive reload',
      'Fix: Dashboard team-count query no longer fires for viewer role users — was producing a red 403 in DevTools because /v1/users/ requires users.list permission',
      'Fix: RBAC bootstrap — first person to register via /auth/register is now correctly promoted to admin. Previously failed because the seeded demo user claimed the admin slot',
      'Tests: 220/220 frontend unit tests + 6/6 Q1 Playwright specs + 0 TypeScript errors',
    ],
  },
  {
    version: '2.0.0',
    date: '2026-04-20',
    changes: [
      'Fix: AI Chat SSE streams now complete reliably (asyncio.shield on DB flush under cancellation)',
      'Fix: AI settings encryption — .env JWT_SECRET is loaded by absolute path, keys survive backend restarts',
      'Fix: AI Settings UI only marks a provider as "configured" when the stored key actually decrypts',
      'Fix: DWG Takeoff scale — perimeter/area respect DXF $INSUNITS and current drawing scale on both canvas and ElementInfoPopover',
      'Fix: BIM Linked BOQ panel populates (new aggregate endpoint fetches joins by model)',
      'Fix: BIM Rules button now deep-links to ?mode=requirements',
      'Fix: CDE container create — correct trailing-slash route, no more 307 auth drop',
      'Fix: AI Estimate "Save as BOQ" — correct trailing-slash route',
      'Fix: Markups & Overheads dropdown no longer clipped by parent overflow',
      'Fix: Cost Intelligence Advisor renders markdown (bold/italic/headings/lists) instead of raw asterisks',
      'Fix: Modal backdrops now cover the top header (z-index rebalance)',
      'UX: AI Estimate — BETA badge in sidebar',
      'UX: /projects — file-type badges right-aligned in same row, larger professional md size',
      'UX: Floating AI Chat button removed app-wide',
      'UX: BOQ list — file-type chips shown on each row',
      'UX: PDF-origin icon on BOQ positions sourced from PDF takeoff',
      'UX: CAD-BIM Explorer renamed to CAD-BIM BI Explorer with a new KPI dashboard strip (Elements / Volume / Area / Length / Weight / Categories / Levels)',
      'UX: CAD-BIM BI Explorer — Power-BI-style data bars in Pivot cells, scaled to each column\'s visible max',
      'UX: Dashboard — Quick Start Estimate is pure-navigation now (opens last BOQ / new BOQ / new project); explicit New Estimate button added',
      'UX: Dashboard — Quality Score KPI replaces "N/A" text with a dashed-circle icon + clickable "run validation" CTA',
      'UX: Sidebar — prominent "+ Add module" CTA at the bottom of the nav, routes to the in-app developer guide',
      'UX: About — Artem Boiko avatar, DDC logo, GitHub repo cards, full-width clickable book banner, Community block (LinkedIn / Telegram / X)',
      'Docs: new MODULES.md at repo root + in-app /modules/developer-guide page + "Build a module" link on the Modules page',
      'Security: layered DDC provenance markers (meta tags, CSS custom props, localStorage key, response headers, console banner) for copyright-enforcement forensics',
      'Tests: fixed 48 backend integration failures (admin promotion in fixtures + trailing-slash drift); 61/61 green',
      'Cleanup: removed 5 archived duplicate demo projects; 6 regional demos remain',
      'Cleanup: removed debug scripts, playwright video output, diagnostic specs; tightened .gitignore',
    ],
  },
  {
    version: '1.9.6',
    date: '2026-04-19',
    changes: [
      'Fix: CWICR region load 404 (trailing-slash route drift)',
      'Fix: LanceDB restore path no longer leaks onto Qdrant UI',
      'Fix: Projects/Contacts list 422 when fetching >100 rows',
      'Fix: Settings reindex 404 (duplicate /api prefix)',
      'DWG: Document rows now persist across reload',
    ],
  },
  {
    version: '1.9.5',
    date: '2026-04-18',
    changes: [
      'Normalise API drift: Submittals, Meetings, Safety, Inspections, NCR',
      'Procurement + Finance: fallback to contact id when name missing',
      'NCR: numeric suffix extraction for badge padding',
      'Schedule: i18next call sites modernised (no raw keys)',
      'External links: full rel="noopener noreferrer" across 20 files',
      'Header layout: GitHub/Report hidden < lg, search shrinks',
      'Tasks action bar: wraps at 375px instead of overflowing',
      'ProjectMap: i18n ("Locating…" / "No location set")',
    ],
  },
  {
    version: '1.9.4',
    date: '2026-04-18',
    changes: [
      'Transmittals: Edit + Delete on drafts (issued stay locked)',
      'DWG: Scale 1:N multiplies every measurement, persisted',
      'DWG: new Line / Polyline / Circle tools',
      'DWG: floating upload dock survives navigation',
      'Split BIM Rules (compliance) from Quantity Rules',
      'Tasks: free-text assignee stored in metadata, renders on card',
      'Project Intelligence: readiness + gaps on one row',
      'BIM distance measure: toast when click misses geometry',
      'Transmittals grid: API normaliser (no raw i18n keys)',
      'CAD Explorer: missingness panel back online',
      'E2E: shared login token across workers',
      'Security: markdown link renderer rejects js:/data:/vbs: URIs',
    ],
  },
  {
    version: '1.9.3',
    date: '2026-04-18',
    changes: [
      'DWG: background uploads with staged progress',
      'DWG: right-click → Create task / Link to schedule/doc/req',
      'DWG: Export PDF from Summary tab (multi-page jsPDF)',
    ],
  },
  {
    version: '1.9.2',
    date: '2026-04-18',
    changes: [
      'BIM: removed duplicate top-bar "Link to BOQ" button',
      'BIM: 4D Schedule disabled with "coming soon" tooltip',
    ],
  },
  {
    version: '1.9.1',
    date: '2026-04-18',
    changes: [
      'DWG polyline selection: ranked hit-test fixes outer bias',
      'Data Explorer: Power-BI-style slicers + Recharts',
      'BIM: SavedViews, category transparency, measure M-key, 4-tab panel',
      'Quantity Rules: Seed-from-model picker + Advanced AND/OR/NOT',
      'Estimation Dashboard: KPI hero + 5 analytics cards',
      'Meetings: edit, attachments, 50k-char minutes',
      'CDE deep audit ISO 19650: suitability lookup, audit log, Gate B',
      'Polish: DDC logo, tighter rows, Schedule bigger CTA, file filters',
    ],
  },
  {
    version: '1.9.0',
    date: '2026-04-17',
    changes: [
      'BOQ: add resource updates grid instantly (optimistic)',
      'Global: React Query offline-first with online-guard retry',
      'Project detail: Offline/Retry UI (no false 404)',
      'Takeoff: documents persist via activeDocId URL sync',
      'BIM: Link + Save-as-Group buttons always visible',
      'Quantity Rules: create reliably lands in list',
      'Tasks: create dialog pre-fills task_type from tab',
      'CDE: concrete error messages on New Container',
    ],
  },
  {
    version: '1.9.7',
    date: '2026-04-19',
    changes: [
      'Security emergency sprint — closed 10 critical authentication / input-validation holes flagged by the Part 7–8 audit',
      'Auth: JWT `type` claim enforced — reset + refresh tokens no longer accepted on protected endpoints (BUG-321 / BUG-331)',
      'Auth: JWT user existence verified on every entry point (HTTP, WebSocket, optional-auth, collab locks) — forged tokens with fake UUIDs blocked (BUG-323)',
      'Auth: dev mode auto-rotates JWT_SECRET to a random per-process value if the hardcoded default is in use — the open-source default-secret forgery path no longer works even locally (BUG-320)',
      'Auth: self-registration defaults to `viewer` role (was `editor` with 119 permissions); configurable via OE_DEFAULT_REGISTRATION_ROLE (BUG-386 / BUG-327)',
      'Auth: `settings.debug` typo fix eliminates user-enumeration oracle on forgot-password (BUG-345)',
      'API: /api/openapi.json returns 404 in production — schema enumeration no longer gifted to attackers (BUG-394)',
      'Costs: /actions/clear-region/{region} upgraded from `costs.delete` to admin-only, matching /actions/clear-database (BUG-395 parity)',
      'Deps: python-multipart 0.0.22 → 0.0.26 — patches CVE-2026-40347 (request smuggling on file-upload endpoints) (BUG-387)',
      'Sanitize: new app.core.sanitize strips XSS payloads (script/iframe/onerror/javascript:) from Project, BOQ, RFI and Feedback free-text while preserving literal angle brackets like "beam <200mm" (BUG-326 / BUG-389 / BUG-330)',
    ],
  },
  {
    version: '1.9.6',
    date: '2026-04-19',
    changes: [
      'Security: GAEB XML import now uses defusedxml — blocks XXE, billion-laughs, and external-entity attacks on user-uploaded tender files',
      'Security: new magic-byte file signature validator — BIM upload and Documents upload now reject files whose content does not match the extension (e.g. renamed executables)',
      'Correctness: BOQ money arithmetic now goes through Decimal end-to-end — the prior str → float → str round-trip silently dropped precision on large currency totals',
      'Excel exports (BOQ + Invoices) emit real numeric cells (Decimal) instead of strings — Excel can now SUM/sort, no more "Number stored as text" triangles',
      'CSV / GAEB exports: _fmt_number / _fmt_price / _fmt_qty rewritten with Decimal — preserves full precision and rejects NaN/Infinity at the edge',
      'Rate limiting: new client_identifier helper reads X-Forwarded-For so one reverse-proxy IP no longer fills the whole login bucket',
      'BIM processor: per-element property cap of 30 entries restored — huge Revit exports no longer blow up response payloads',
      'Global copy: removed country-specific standard names (DIN 276 / NRM / MasterFormat) from default UI text — kept only where they are structural (picker options, rule IDs)',
    ],
  },
  {
    version: '1.8.3',
    date: '2026-04-17',
    changes: [
      'BOQ Linked Geometry "Apply to BOQ" column: redesigned "Set as quantity" buttons — gradient CTA for SUM rows, hover-to-apply chips with arrow indicators for DISTINCT values',
      'BIM filmstrip always-visible: removed conditional that made "Your Models" bar vanish when models were empty or during LandingPage↔main-view transitions; shows "No models yet" empty state instead',
      'Dashboard: new compact file-upload drop zone that writes into the Documents module — toast + live count with link to /documents',
      'Cross-link module uploads → Documents: every BIM model, DWG drawing, and Takeoff PDF uploaded via its native module now also appears in /documents with source_module/source_id metadata (no file duplication)',
      'DocumentsPage routing: prefers metadata.source_module over filename extension — routes straight back to the source module (bim_hub / dwg_takeoff / takeoff)',
    ],
  },
  {
    version: '1.8.2',
    date: '2026-04-17',
    changes: [
      'Documents page: file-type routing — PDF opens preview / takeoff, DWG/DXF/DGN opens DWG Takeoff, RVT/IFC/NWD/NWC opens BIM Viewer (all with deep-link)',
      'Documents page: new "Module Files" section showing BIM models, DWG drawings, Takeoff PDFs with one-click navigation to their native module',
      'BOQ link icons: fixed PDF + DWG deep-link params — clicking the red PDF or amber DWG icon now opens the exact file that was linked (not the landing page)',
      'BIM page: supports ?docName= / ?docId= deep-link from Documents — auto-selects matching model or opens upload dialog',
      'DWG Takeoff: filmstrip taller (108px cards, 150px max-height) for clearer thumbnails + metadata',
      'Header: "Report Issues" → "Email Issues" with mail icon and direct mailto:info@datadrivenconstruction.io link',
    ],
  },
  {
    version: '1.8.1',
    date: '2026-04-17',
    changes: [
      'DWG Takeoff: full "Link to BOQ" picker — select existing position or create-and-link, quantity auto-transfers, centroid annotation created automatically',
      'DWG Takeoff: summary bar in right panel with total entities, Σ area, Σ distance + one-click CSV export of all measurements',
      'DWG Takeoff: right panel switched back to light theme with compact 72-col width and elevated shadow',
      'DWG Takeoff: toolbar palette white-glass for contrast on dark #3f3f3f canvas (visible in both themes)',
      'Takeoff: barely-visible field-surveyor decorative background (polygons, polylines, distance lines, scale ruler, vertex pins) spanning the full page',
      'Documents API: frontend wrappers for general-document upload/list/delete (foundation for upcoming Dashboard ↔ Documents integration)',
      'Demo storyboard: 6-minute walkthrough script saved to docs/VIDEO_DEMO_v1.8.md',
    ],
  },
  {
    version: '1.8.0',
    date: '2026-04-17',
    changes: [
      'BOQ ↔ PDF Takeoff deep linking: individual measurements now link to positions; quantity auto-transfers bidirectionally (measurement ↔ position metadata)',
      'BOQ grid: red PDF + amber DWG link icons next to positions; click opens document in same tab (auth preserved)',
      'BOQ Linked Geometry popover: "Set as quantity" buttons next to BIM parameter values for one-click apply',
      'Takeoff: tab order swapped (Measurements first, AI/Documents second); reduced rounded corners; cleaner tool buttons',
      'Takeoff: bottom filmstrip of previously uploaded project documents with click-to-open',
      'Takeoff: barely-visible decorative geometry behind viewer (rectangles, polylines, scale rulers) like field-surveyor markings',
      'BIM landing: tileable isometric-cube pattern background (airy, near-invisible, no scrollbar)',
      'BIM filmstrip: no longer auto-collapses — always visible for quick model switching',
      'DWG Takeoff: toolbar palette now white-glass for visibility on dark #3f3f3f canvas',
      'DWG Takeoff: right-side panel re-themed to match dark canvas (readable contrast)',
      'DWG Takeoff: drawings filmstrip re-themed dark to match page background',
      'CAD Data Explorer: decorative semi-transparent spreadsheet grid background; no horizontal or vertical scroll on landing',
      'Chat: markdown links like [Settings](/settings) now render as proper clickable anchors',
      'Projects: self-healing stale project IDs — auto-cleanup of context and recent stores on 404',
    ],
  },
  {
    version: '1.7.2',
    date: '2026-04-16',
    changes: [
      'BIM Viewer: top-left toolbar (camera + visibility) shifts right when filter panel is open',
      'BIM Model Summary: reactive to active scope — all / filtered / selection with live "shown of total" count',
      'BIM Viewer: skeleton loading bars replace "Unmatched" flash when clicking elements',
      'BIM ↔ BOQ linking: fixed UUID validation error for stub elements — backend lazy-creates missing BIMElement rows from Parquet',
      'BOQ Linked Geometry popover: new 3-column layout (preview / properties / Apply to BOQ) so Apply never scrolls off-screen',
      'BOQ Linked Geometry: aggregation semantics — Σ for area/volume/length (summed), = for thickness/width/material (distinct values listed)',
      'BOQ Linked Geometry: Parquet fallback fills "No numeric" gap for tapered roofs and other DDC-filtered categories',
      'Cleanup: removed orphaned BIMProcessingProgress component, deduplicated upload indicators',
      'DWG Takeoff: AutoCAD-style grid background with scoped CSS variables + vignette',
      'Documents: unified dropzone + card grid matching BIM pattern',
      'Header: GitHub Issues button added next to repo link; ProjectSwitcher shows loading/error states properly',
      'CAD Data Explorer: removed duplicate top bar, trust-line restyled',
    ],
  },
  {
    version: '1.7.1',
    date: '2026-04-16',
    changes: [
      'BIM: redesigned landing layout, version badges',
      'Tasks: type filter fix, Kanban column reorder',
      'BOQ: FAB shifts when AI panel open, template removed',
      'DWG: light-theme filmstrip and right panel',
      'Takeoff: BIM-style upload card redesign',
      'Procurement: contact picker from contacts module',
      'Assemblies: resource display + type badges',
      'Schedule: month label overlap prevention',
      'Design: 56 hardcoded colors → semantic tokens',
      'i18n: 20+ hardcoded strings wrapped in t()',
      'a11y: aria-labels across all modules',
    ],
  },
  {
    version: '1.7.0',
    date: '2026-04-15',
    changes: [
      'BIM Viewer: linked BOQ panel with quantities',
      'DWG Takeoff: polygon selection + measurements',
      'Data Explorer: BIM-style full-viewport layout',
      'Dashboard: DDC branding, subtitle i18n (21 langs)',
      'Assemblies: JSON import/export, tags, drag-reorder',
      '5D Cost Model: inline-editable budget lines',
      'Finance: summary cards with key metrics',
      'Tasks: custom categories, 4-column Kanban',
      'Schedule: user-selectable project start date',
      'Chat: AI config onboarding guide',
      'Project Intelligence: tag badges, compact cards',
      'Bugfixes: Contacts country_code, RFI field sync, 4 modals',
      'UI: unified padding across 37+ pages',
    ],
  },
  {
    version: '1.6.0',
    date: '2026-04-15',
    changes: [
      'BIM Linked Geometry Preview in BOQ grid',
      'BIM Quantity Picker with element-level fetch',
      'BIM source parameter shown on BOQ quantities',
      'DWG Takeoff: polyline area/perimeter measurements',
      'DWG viewport: CSS-pixel fit, resize refit, Fit button',
      'Fix: BOQ section collapse header dispatch',
      'Smart quantity formatting for very small values',
      'Dashboard: DDC branding update',
      'AI Chat: compact icon-only button layout',
    ],
  },
  {
    version: '1.5.2',
    date: '2026-04-14',
    changes: [
      'Fix: unit dropdown selection in BOQ editor',
      'Fix: ezdxf compatibility in Docker builds',
      'Audit fixes across multiple modules',
    ],
  },
  {
    version: '1.5.1',
    date: '2026-04-14',
    changes: [
      'Fix: Tendering deadline/submitted_at column truncation',
      'Fix: BOQ description editing — replaced broken autocomplete',
      'Fix: live total computation for positions without resources',
    ],
  },
  {
    version: '1.5.0',
    date: '2026-04-13',
    changes: [
      'Security: fixed 4 vulnerabilities, 2 concurrency bugs',
      'IFC4x3 civil infrastructure: 30+ new entity types',
      'BIM Viewer: Delete key hides, collapsible filmstrip',
      'Properties panel: clean key-value layout redesign',
      'Replaced 17 window.confirm() with styled ConfirmDialog',
      'i18n: wrapped 25+ hardcoded strings across 4 pages',
      'Performance: staleTime on 37 useQuery calls',
      'Code quality: stable keys, normalizeListResponse utility',
      'Tests: 185 backend + 55 E2E + 59 IFC civil tests',
    ],
  },
  {
    version: '1.4.8',
    date: '2026-04-11',
    changes: [
      'Real-time collaboration L1: soft locks + presence',
      'Backend collaboration_locks module with WebSocket presence',
      'useEntityLock hook + PresenceIndicator component',
      'BOQ row-level locking during cell editing',
      '17 integration tests for lock lifecycle',
    ],
  },
  {
    version: '1.4.7',
    date: '2026-04-11',
    changes: [
      'BIM: determinate geometry-loading progress bar',
      'Sidebar: BETA badges on BIM and Chat modules',
      'Restored rich GitHub README after accidental rewrite',
      'BIM filter panel resets on model switch',
      'Assembly total_rate syncs on cost item rate change',
      'Project Intelligence: real validation/pricing/schedule actions',
      'Vector routes factory: -105 LOC across 6 modules',
      'Fix: EVM honest schedule_unknown status fallback',
      'BIM: Levels filter replaces Storeys, 20-key extraction',
      'BIM converter: preflight check + one-click auto-install',
      'BIM converter: parallel download from cad2data repo',
      '12 broken integration tests fixed',
    ],
  },
  {
    version: '1.4.6',
    date: '2026-04-11',
    changes: [
      'Security: contacts module IDOR fix (owner scoping)',
      'Security: collaboration module permission checks added',
      'Notifications subscriber framework wired to events',
      'Raw SQL replaced with ORM in 3 cross-link sites',
      'Fix: meetings event only published on task success',
      'Project Intelligence: 4 new module collectors added',
    ],
  },
  {
    version: '1.4.5',
    date: '2026-04-11',
    changes: [
      'Deep audit: cross-module integrity + test coverage',
      'Fix: orphaned BIM element ids cleaned on delete',
      'Fix: property filter type-aware matching (lists, dicts)',
      'Quantity map: skipped elements now show reasons',
      'Per-collection reindex lock prevents data races',
      'Requirements: PATCH + bulk-delete endpoints added',
      'Fix: GateResult.score migrated from String to Float',
      'Tests: 135 new tests across 7 vector adapters',
      'BIMPage i18n: hardcoded English strings wrapped',
    ],
  },
  {
    version: '1.4.4',
    date: '2026-04-11',
    changes: [
      'Fix: vector auto-backfill memory hazard (COUNT before SELECT)',
      'Python 3.14: replaced datetime.utcnow() across 8 sites',
      'Raw SQL replaced with ORM in BIM upload cross-link',
      'Ruff cleanup: unused imports, f-strings, zip(strict=True)',
      'New: version-sync CI guard for pyproject/package.json',
    ],
  },
  {
    version: '1.4.3',
    date: '2026-04-11',
    changes: [
      'Requirements to BIM cross-module linking (5th link type)',
      'New oe_requirements vector collection (8th total)',
      'Requirements event publishing + vector auto-indexing',
      'LinkRequirementToBIMModal in BIM viewer',
      'RequirementsPage: pinned BIM elements + deep linking',
      'Global Search: Requirements facet support added',
      'Fix: BIM CAD upload crash from storage refactor',
      'Fix: pyproject.toml version drift synced to 1.4.3',
    ],
  },
  {
    version: '1.4.2',
    date: '2026-04-11',
    changes: [
      'Security: SQL injection guard in LanceDB id-quoting',
      'Security: Qdrant search payload mutation fix',
      'Token-aware text clipping at 510 SBERT tokens',
      'Frontend deep links: BOQ/Docs/Tasks/Risk/BIM working',
      'New: BIM coverage summary endpoint + dashboard card',
      'BOQ BIM badge clickable: jump to 3D viewer',
      'Schedule: BIM element badge on Gantt activities',
      'BIM Rules: CWICR rate suggestion on auto-create',
    ],
  },
  {
    version: '1.4.1',
    date: '2026-04-11',
    changes: [
      'Validation vector adapter with semantic search',
      'Chat messages vector adapter + auto-indexing',
      'Auto-backfill vector collections on startup',
      'Settings: Semantic Search Status panel added',
    ],
  },
  {
    version: '1.4.0',
    date: '2026-04-11',
    changes: [
      'Semantic memory: 7 vector collections across all modules',
      'Multilingual embedding model (50+ languages)',
      'Event-driven vector indexing on every CRUD operation',
      'Per-module reindex/status/similar endpoints',
      'Unified cross-collection search API with rank fusion',
      'Global Search modal (Cmd+Shift+K) with facet pills',
      'Similar Items panel for any entity type',
      'AI Chat: 6 semantic search tools added',
      'AI Advisor: RAG injection from semantic search',
    ],
  },
  {
    version: '1.3.32',
    date: '2026-04-10',
    changes: [
      'BIM: health stats banner with clickable filter chips',
      'BIM: smart-filter chips in sidebar (errors/warnings/links)',
      'BIM: 3 new color-by compliance modes at 60 fps',
      'New: CWICR cost suggestion endpoint for BIM elements',
      'AddToBOQ: one-click CWICR rate chips with confidence',
    ],
  },
  {
    version: '1.3.31',
    date: '2026-04-11',
    changes: [
      'BIM: read-write cross-module panel (create/link inline)',
      'New: CreateTaskFromBIM, LinkDocument, LinkActivity modals',
      'Cross-module sections always render with empty states',
      'BIM validation rules engine: per-element compliance check',
      'BIM: per-element validation badges in details panel',
      'Tasks: BIM element badge with reverse navigation',
      'Fix: ValidationReportResponse metadata alias collision',
    ],
  },
  {
    version: '1.3.30',
    date: '2026-04-11',
    changes: [
      'BIM: Documents, Tasks, Schedule (4D) cross-linking',
      'New: oe_documents_bim_link table + endpoints',
      'New: Task.bim_element_ids for spatial defect management',
      'Schedule activity BIM linking endpoints wired',
      'Documents preview: linked BIM elements footer',
    ],
  },
  {
    version: '1.3.29',
    date: '2026-04-11',
    changes: [
      'Chat: removed redundant top bar, clear chat in input',
      'Release pipeline: synced CHANGELOG.md with in-app log',
      'Update badge: fix — push version tags for GitHub releases',
    ],
  },
  {
    version: '1.3.28',
    date: '2026-04-11',
    changes: [
      'BIM filter: universal building vs annotation split',
      'BIM filter: pretty category names for 150+ Revit types',
      'BIM filter: "None" element_type classified as noise',
    ],
  },
  {
    version: '1.3.27',
    date: '2026-04-11',
    changes: [
      'BIM filter: 3 grouping modes (Category/TypeName/Buckets)',
      'New: getTypeNameKey() for hierarchical type resolution',
      'BIM filter: explicit "Clear types" link added',
    ],
  },
  {
    version: '1.3.26',
    date: '2026-04-11',
    changes: [
      'Fix: "Add to BOQ" link 500 error (position ownership check)',
      'Fix: flaky headless test for saved group lifecycle',
    ],
  },
  {
    version: '1.3.25',
    date: '2026-04-11',
    changes: [
      'BIM saved groups: full lifecycle UI (apply/delete/link)',
      'BIM groups: React Query auto-refetch on save/delete',
    ],
  },
  {
    version: '1.3.24',
    date: '2026-04-11',
    changes: [
      'BIM: pluggable storage backend (Local + S3/MinIO)',
      'BIM element groups: backend CRUD + Alembic migration',
      'Frontend: SaveGroupModal for dynamic/static groups',
      'New: S3 storage migration helper script',
    ],
  },
  {
    version: '1.3.23',
    date: '2026-04-11',
    changes: [
      'BIM viewer verified end-to-end via headless deep test',
      'Fix: "BIM Rules" i18n key fallback added to sidebar',
      'Internal: BatchedMesh method for 50k+ mesh scenes',
    ],
  },
  {
    version: '1.3.22',
    date: '2026-04-11',
    changes: [
      'BIM to BOQ linking: full end-to-end UI',
      'AddToBOQ modal: link existing or create new position',
      'Quick Takeoff: bulk-link visible elements to BOQ',
      'BIM Quantity Rules page at /bim/rules',
      'Bi-directional BIM/BOQ selection highlighting',
      'Viewer toolbar rework: camera presets + grid toggle',
      'BOQ grid: per-position BIM link count badge',
    ],
  },
  {
    version: '1.3.21',
    date: '2026-04-10',
    changes: [
      'BIM: usable Storeys filter with level parsing + sorting',
      'BIM filter: verified end-to-end (60 fps, correct counts)',
    ],
  },
  {
    version: '1.3.20',
    date: '2026-04-10',
    changes: [
      'BIM: 30x faster rendering (shadow/light/pixel fixes)',
      'BIM: model-sized grid, tighter camera fit',
      'BIM filter: semantic buckets, buildings-only toggle',
      'BIM filter: category chip click zooms to subset',
      'BIM: positional fallback for unnamed DAE meshes',
    ],
  },
  {
    version: '1.3.19',
    date: '2026-04-10',
    changes: [
      'Fix: BIM camera correctly frames model on first load',
    ],
  },
  {
    version: '1.3.18',
    date: '2026-04-10',
    changes: [
      'Fix: BIM shows COLLADA materials (not flat white)',
      'Fix: BIM camera fit ignores grid/lights',
      'Cleanup: tighter page padding, full-width layouts',
      'Security: BIM delete removes files from disk',
      'Fix: markups save in PDF units (not canvas pixels)',
      'Fix: PDF.js memory leak in markups annotator',
      'Security: zip-slip validation on converter install',
    ],
  },
  {
    version: '1.3.17',
    date: '2026-04-10',
    changes: [
      'Fix: EVM SPI clamped to valid range [0, 5]',
      'Fix: CPM topological sort + cycle detection',
      'Fix: risk matrix 5x5 grid (was 5x4)',
      'Fix: costmodel EVM N+1 query optimized',
    ],
  },
  {
    version: '1.3.16',
    date: '2026-04-10',
    changes: [
      'Security: validation/tendering/PI ownership checks (IDOR)',
      'Security: full_evm + catalog permission fixes',
      'Security: AI API keys encrypted at rest with Fernet',
      'Security: chat rate-limited, tool results size-capped',
    ],
  },
  {
    version: '1.3.15',
    date: '2026-04-10',
    changes: [
      'Security: permission checks on BIM/finance/contacts/RFQ',
      'Security: assemblies + BOQ ownership verification',
      'Security: project analytics scoped by owner',
      'Cleanup: 213 MB orphan files removed from demo',
    ],
  },
  {
    version: '1.3.14',
    date: '2026-04-10',
    changes: [
      'Fix: login trailing-slash 404 + demo seed str/int crash',
      'Cleanup: [ai] extra renamed to [semantic], -800 MB',
      'Doctor checks pandas/pyarrow; init-db reports failures',
    ],
  },
  {
    version: '1.3.13',
    date: '2026-04-10',
    changes: [
      'Fix: pandas/pyarrow in base deps (pip install works)',
      'Fix: BIM geometry visible on first load, wide near/far',
      'New: demo mode banner + PII stripping in user API',
    ],
  },
  {
    version: '1.3.12',
    date: '2026-04-10',
    changes: [
      'Fix: PostgreSQL quickstart creates tables on first start',
      'Fix: BIM camera fit, filters work for RVT exports',
      'New: BIM 6-step upload progress bar',
      'New: openestimate doctor + init-db CLI commands',
    ],
  },
  {
    version: '1.3.11',
    date: '2026-04-10',
    changes: [
      'BIM: full-width layout, format-aware filter (RVT/IFC)',
      'BIM: removed discipline filter, added Category/Storey/Type',
      'Chat: matches site theme, full-width layout',
    ],
  },
  {
    version: '1.3.10',
    date: '2026-04-10',
    changes: [
      'Fix: Windows Anaconda startup crash (MKL/OpenMP DLL)',
      'Fix: lazy vector DB model loading (-30s startup)',
      'Fix: SPA routing for production demo deployment',
      'Vector DB: actionable hints on connection failure',
    ],
  },
  {
    version: '1.3.9',
    date: '2026-04-10',
    changes: [
      'Fix: cost database load 18x faster (vectorized aggregation)',
      'Fix: non-admin roles can install cost databases',
      'Fix: legacy role aliases (estimator/qs/superuser/guest)',
      'BIM: color-by mode + isolate mode',
      'Chat: tool authorization + argument validation',
    ],
  },
  {
    version: '1.3.8',
    date: '2026-04-10',
    changes: [
      'BIM: filter panel (search, discipline, storey, type)',
      'BIM: element explorer with expandable tree grouping',
      'BIM: fast mesh visibility toggle for 16k+ elements',
    ],
  },
  {
    version: '1.3.7',
    date: '2026-04-10',
    changes: [
      'Fix: BIM shows real COLLADA geometry (not placeholders)',
      'Fix: BIM element fetch raised to 50,000 limit',
      'Chat: AI config banner when no API key set',
      'Chat: sidebar label translated to 21 languages',
    ],
  },
  {
    version: '1.3.6',
    date: '2026-04-10',
    changes: [
      'Fix: BIM geometry loads (token auth for ColladaLoader)',
      'Fix: /chat 404 (duplicate router prefix removed)',
      'Fix: cost database install from onboarding',
      'New: floating AI Chat button on every page',
    ],
  },
  {
    version: '1.3.5',
    date: '2026-04-10',
    changes: [
      'Chat: respects site theme (light/dark)',
      'Chat: rich empty state with tool category cards',
      'Chat: full i18n support (21 languages)',
    ],
  },
  {
    version: '1.3.4',
    date: '2026-04-10',
    changes: [
      'Fix: BIM RVT upload, Excel parser, element mapping',
      'Test: 17 unit tests for BIM processor',
    ],
  },
  {
    version: '1.3.3',
    date: '2026-04-10',
    changes: [
      'Bulk operations on Tasks/RFI/Documents/Risks',
      'Backend search on Tasks, RFI, Meetings (ILIKE)',
      'Task dependencies with cycle detection',
    ],
  },
  {
    version: '1.3.2',
    date: '2026-04-10',
    changes: [
      'Finance EVM: EAC/VAC/ETC/TCPI forecast metrics',
      'Schedule CPM: all 4 dependency types supported',
      'BOQ section delete with cascade option',
      'Tasks: reopen + upcoming tasks, RFI event publishing',
      'Security: document download path traversal hardening',
    ],
  },
  {
    version: '1.3.1',
    date: '2026-04-10',
    changes: [
      'Security: Procurement/BOQ/RFI permission checks added',
      'Fix: BOQ delete errors logged, not silently swallowed',
      'Fix: 6 error handling improvements across pages',
      'Fix: ChangeOrders — lazy-loading errors now debug-logged with context',
      'Perf: Costs module — added indexes on source, region, and (source, region) composite',
    ],
  },
  {
    version: '1.3.0',
    date: '2026-04-10',
    changes: [
      'AI Chat: full-page workspace with 11 ERP tools',
      'BIM Viewer redesign: premium UI, model filmstrip',
      'BIM: DDC Community Converter pipeline integrated',
      'Floating Recent button (bottom-right FAB)',
      'Fix: BIM RVT "Needs Converter" status, geometry URL',
    ],
  },
  {
    version: '1.0.0',
    date: '2026-04-08',
    changes: [
      'Interconnected module ecosystems across 30+ modules',
      '14 integrations (Teams, Slack, Telegram, Discord, etc.)',
      'Onboarding wizard with 5 company profile presets',
      'Project Dashboard with unified KPIs',
      'Global Search across 9 entity types',
      '5 demo projects with 12-module data each',
      'SVG Gantt chart + Three.js BIM Viewer',
      'Fix: 90+ bugs, 15 critical security fixes',
    ],
  },
  {
    version: '0.9.1',
    date: '2026-04-07',
    changes: [
      'Discord webhook integration + WhatsApp (planned)',
      'Integration Hub: 14 cards by category',
      'n8n, Zapier, Make, Google Sheets, Power BI cards',
      'Fix: cross-module event flow corrections',
    ],
  },
  {
    version: '0.9.0',
    date: '2026-04-07',
    changes: [
      '30 backend modules + 13 frontend pages',
      'i18n foundation: 35 currencies, 198 countries, 20 languages',
      'Module System v2 with runtime enable/disable',
      'SVG Gantt chart, Three.js BIM Viewer, notifications',
      'CPM engine, regional packs, enterprise packs',
      '568 translation keys, 50 integration tests',
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
