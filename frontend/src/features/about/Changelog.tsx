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
