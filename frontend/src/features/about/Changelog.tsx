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
      'New: 53 modules — full construction lifecycle from estimation to handover',
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
