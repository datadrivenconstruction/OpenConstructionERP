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
    version: '0.8.0',
    date: '2026-04-07',
    changes: [
      'New: Custom Columns dialog with 7 professional presets — Procurement, Notes, Quality Control, Sustainability, German Tender Style (Lohn/Material/Geräte/Sonstiges-EP + Wagnis%), Austrian Tender Style, BIM Integration (IFC GUID, Element ID, Storey, Phase)',
      'New: Renumber positions with gap-of-10 scheme (01, 01.10, 01.20, 02, 02.10) — matches the professional German/Austrian tender output convention, lets you insert 01.15 later without renumbering everything',
      'New: Excel round-trip with custom columns — supplier, notes and procurement fields are now exported to .xlsx and survive a full import → edit → export cycle',
      'New: Project Health bar on Project Detail — circular progress with 5 checkpoints (BOQ created → positions added → all priced → validation run → no errors) and a single "Next step" button that always points at the first incomplete item',
      'New: Strong password policy on registration and reset — 8+ chars, ≥1 letter, ≥1 digit, blacklist of 24 common passwords; rejects "password", "12345678" and friends',
      'New: Login rate limit (10/min per IP) with 429 + Retry-After header to slow credential stuffing',
      'New: JWT freshness check — old tokens are invalidated automatically when the user changes password',
      'New: Security headers middleware — X-Frame-Options, X-Content-Type-Options, CSP, HSTS, Referrer-Policy, Permissions-Policy on every API response',
      'New: Schedule date validation — start_date > end_date is now rejected with a clear 422',
      'New: Role-aware UI — ChangeOrders Approve button is hidden for editors, who see an "Awaiting approval" badge instead of a 403 error',
      'New: Soft-deleted projects properly disappear — GET, list and BOQ list now return 404 for archived projects (was leaking stale data)',
      'New: User-friendly API error messages — ApiError now extracts the actual FastAPI detail string instead of "API 500"; covers network, timeout, 422 validation arrays, and status fallbacks across 21 locales',
      'New: PDF upload magic-byte check — rejects JPG/HTML/etc. renamed to .pdf',
      'Fix: ChangeOrders POST /items returned 500 for every payload — MissingGreenlet on order.code after recalc; now captures fields before expire_all',
      'Fix: 5D generate-budget returned 500 on missing boq_id — now validates 422 + auto-picks the most recently updated BOQ when omitted',
      'Fix: Custom Columns SQLAlchemy JSON persistence — only the FIRST added column was being saved due to in-place dict mutation; now uses flag_modified() with a fresh dict',
      'Fix: Editing a custom column on a resource-priced position rewrote total/unit_rate — service.update_position now only re-derives pricing when quantity or resources actually changed',
      'Fix: Requirements module tables were never created on fresh installs — module models are now imported in main.py + alembic env.py',
      'Fix: Cross-user permission boundary verified end-to-end — User B gets 403 on every attempt to read/modify/delete User A\'s data',
      'Fix: Single source-of-truth for app version — bumping package.json now updates Sidebar, About, error reports and update checker automatically',
      'Polish: a11y — added h1 (sr-only) on /login and /register, name and id attributes on all auth inputs, aria-label on password show/hide buttons',
      'Polish: highlight unpriced positions in BOQ grid with a subtle amber background and left border',
      'Polish: warn before creating a project with a duplicate name (two-click confirmation)',
      'Polish: keyboard shortcuts dialog now lists only shortcuts that actually work; added g r → Reports and g t → Tendering navigation sequences',
    ],
  },
  {
    version: '0.7.0',
    date: '2026-04-07',
    changes: [
      'New: Custom Columns in BOQ — define your own dynamic fields (text, number, date, select), stored per BOQ',
      'New: Hierarchical BOQ — multi-level sections with recursive tree builder and depth-aware indentation',
      'New: Excel Round-Trip foundation — original column metadata preserved on import for faithful re-export',
      'New: Parametric Assembly formula engine — variables, conditionals, lookup tables, math functions',
      'New: "Continue your work" card on Dashboard — jump straight back to your most recent BOQ',
      'New: Quick Start Estimate button — one-click project + BOQ creation with sensible defaults',
      'New: Simplified sidebar mode — beginner view shows only the 7 essential modules',
      'New: User-friendly error messages — toasts now show actionable text instead of "API 500"',
      'New: Keyboard shortcuts dialog (press ?) cleaned up to only list shortcuts that actually work',
      'Fix: BOQ drag-and-drop 500 errors — session corruption from activity logging removed',
      'Fix: BOQGrid runtime crash — customColumns prop now properly destructured',
      'Fix: 4D Schedule + 5D Cost Model — 27/27 endpoints pass after MissingGreenlet and Monte Carlo fixes',
      'Fix: Mobile sidebar now locks body scroll when open',
      'Fix: New BOQ position highlight + auto-scroll for instant visual feedback',
    ],
  },
  {
    version: '0.6.0',
    date: '2026-04-07',
    changes: [
      'New: Resource quantities scale proportionally when position quantity changes',
      'New: Professional resource-position pricing logic — unit rate auto-derived from resources',
      'New: BOQ drag-drop now updates parent_id when moving positions between sections',
      'New: Settings page two-column layout on wide screens for better space usage',
      'New: Data Explorer heatmap visualization + pivot CSV/Excel export',
      'Fix: Critical business logic — project validation, total exclusion of section rows, bulk import safety',
      'Fix: Resource total uses pre-computed values for accuracy across edge cases',
      'Fix: BOQ qty/rate cells switched to single-click numeric editors',
      'Fix: TypeScript build — zero errors on tsc --noEmit',
      'Polish: i18n consistency, dynamic column alignment, quality polish across the app',
    ],
  },
  {
    version: '0.5.0',
    date: '2026-04-06',
    changes: [
      'New: PDF Takeoff — server sync, Documents integration, professional measurement workflow',
      'New: Professional export formatting — Excel header block + PDF cover page with signature lines',
      'New: CAD/BIM module — Create BOQ from Pivot, exports include resources',
      'New: Deep UX improvements across 7 pages — search bars, empty states, redesigned reports & modules',
      'New: Privacy Policy + Terms of Service pages',
      'New: Modal dialogs for creating BOQ, Projects, and Assemblies — no more separate creation pages',
      'New: BOQ list auto-filters by the active project from the header context',
      'New: Data Explorer landing — dashed dropzone, compact 12-card recent models grid, delete from landing',
      'Fix: Pivot/Charts smart column selection — quantity keywords prioritized for sums',
      'Fix: New BOQ now appears in the list immediately (cache invalidation)',
      'Cleanup: Removed 76 test/smoke projects from the seed database',
    ],
  },
  {
    version: '0.4.0',
    date: '2026-04-06',
    changes: [
      'New: Modal dialogs for creating BOQ, Projects, and Assemblies — no more separate pages',
      'New: BOQ list auto-filters by active project from header context',
      'New: Data Explorer landing redesign — dashed dropzone, compact session list',
      'New: Table of contents navigation in GitHub README',
      'New: Privacy Policy and Terms of Service pages',
      'Fix: New BOQ not appearing in list after creation (cache invalidation)',
      'Fix: CostBreakdownPanel styling — consistent rounded borders and shadows',
      'Fix: Data Explorer landing — professional compact layout for recent models',
      'Cleanup: Removed 76 test/smoke projects from seed database',
    ],
  },
  {
    version: '0.3.0',
    date: '2026-04-05',
    changes: [
      'New: Data Explorer — global search, column picker, CSV export, data quality indicators',
      'New: Persistent CAD analyses — save to project, list, reopen, delete',
      'New: Global upload queue with background CAD conversion and header indicator',
      'New: Field Reports module — daily logs, weather, workforce tracking, PDF export',
      'New: Photo Gallery module — upload, EXIF metadata, GPS, categories, lightbox',
      'New: Markups & Annotations module + Punch List module (20 modules total)',
      'New: Requirements export (CSV/Excel/JSON) and import (CSV/JSON) with regex validation',
      'New: PDF Takeoff split into two sidebar menus — Measurements + Documents & AI',
      'New: 60+ missing translation keys added across all 21 languages',
      'Fix: Pivot/Charts — smart column selection, quantity keywords prioritized',
      'Fix: BOQ editor — hide tips when positions exist, compact header spacing',
      'Fix: Markups, Punch List, and Requirements pages — API paths, types, and validation',
      'Refactor: Complete markups page redesign — compact, professional, functional',
    ],
  },
  {
    version: '0.2.1',
    date: '2026-04-04',
    changes: [
      'Security: Path traversal protection on document downloads, CORS hardening, login enumeration fix',
      'Fix: BOQ duplication crash (MissingGreenlet) — now works correctly',
      'Fix: CWICR cost database import 500 error on Windows (ProcessPoolExecutor → asyncio.to_thread)',
      'Fix: pip install -e ./backend broken (pyproject.toml structure)',
      'Fix: Docker quickstart — Dockerfile, migration, asyncpg, APP_ENV',
      'New: Comparison table in README (vs commercial estimating suites)',
      'New: Free DDC book section on About page',
      'New: Setup Wizard link in welcome modal for re-onboarding',
      'New: Version number displayed in sidebar (v0.2.1)',
      'New: Nginx CSP, HSTS, Permissions-Policy security headers',
      'Updated: 9 vulnerable dependencies (aiohttp, cryptography, pillow, etc.)',
      'Removed: streamlit and dev screenshot artifacts from repository',
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
