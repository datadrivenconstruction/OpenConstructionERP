/**
 * Changelog: compact two-column release log on the /about page.
 *
 * Each entry is a single glass-style card with version, date, a short summary
 * line, and an optional tag badge. The card list is rendered as CSS columns
 * (`columns-1 md:columns-2`) so entries of variable height pack into the
 * shorter column automatically. There is no need to manually balance the
 * two columns, and a single tall summary doesn't leave the other side blank.
 *
 * Source-of-truth: a single hard-coded `CHANGELOG` array (see below). Entries
 * are kept short and plain per the user's request. The full prose lives in
 * repo-root CHANGELOG.md.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { APP_VERSION } from '@/shared/lib/version';

type Tag = 'NEW' | 'FIX' | 'BETA' | 'SECURITY' | 'MILESTONE';

interface ChangelogEntry {
  version: string;
  date: string;
  /** One short line in plain language. Proper-noun-heavy strings stay in English. */
  summary: string;
  tag?: Tag;
}

// Sorted newest to oldest. Sort is enforced at runtime below (semver-aware) so
// out-of-order entries here still display correctly.
const CHANGELOG: ChangelogEntry[] = [
  { version: '7.1.0', date: '2026-06-06', tag: 'NEW',       summary: 'The desktop app now sets itself up on first launch and drops you straight into a step-by-step setup wizard. The AI Estimate Builder asks a few quick questions, then builds a priced work-package list. Clash results turn into a single tracked task. Adding a cost item now brings all its resources into the estimate. Pages respond right away with a loading bar while they open.' },
  { version: '7.0.1', date: '2026-06-06', tag: 'FIX',       summary: 'Fixes the Windows desktop app that could close on its own right after opening. It now shows a clear error if it cannot start, reuses a running backend only when versions match, and installs without needing a download.' },
  { version: '7.0.0', date: '2026-06-06', tag: 'MILESTONE', summary: 'New AI Estimate Builder turns a typed scope, a BIM model or uploaded files into a priced bill of quantities, with prices always from the cost catalogue. Every module now has one clean title in the top bar and a short card explaining what it does, in all 27 languages. The collaboration hub is a real workspace, and many modules got fixes so dashboards, validation and matching just work.' },
  { version: '6.10.0', date: '2026-06-05', tag: 'NEW',      summary: 'Field time tracking with real payroll: a crew lead logs hours, those hours flow into a payroll batch and post to the ledger exactly once. A new project-controls dashboard shows cost, schedule, quality, safety and risk health in one view. Owner billing forms for US, Canada and Australia. New subcontractor payment portal and client progress-reports tab.' },
  { version: '6.9.0', date: '2026-06-05', tag: 'NEW',       summary: 'New screen for the Management of Change register. Cost matching works again for projects outside the US. Backup restore is now limited to your own data so it cannot wipe another user. Plus broad backend hardening and the desktop fixes from the 6.8 builds.' },
  { version: '6.8.2', date: '2026-06-05', tag: 'FIX',       summary: 'The Windows, macOS and Linux desktop installers build again, carrying the 6.8.1 database fix that had shipped on pip and Docker but not as an installer.' },
  { version: '6.8.1', date: '2026-06-05', tag: 'FIX',       summary: 'The desktop app now launches reliably after install. It connects to its own local database correctly and shows a clear message plus a startup log if anything goes wrong, instead of failing silently.' },
  { version: '6.8.0', date: '2026-06-04', tag: 'NEW',       summary: 'Quantity takeoff on DWG drawings now reports correct real-world metres. A wave of features links the modules together, from subcontractor scorecards and progress claims to resource leveling and offline field work. Interface translation gaps cleared across all 26 non-English languages.' },
  { version: '6.7.0', date: '2026-06-03', tag: 'NEW',       summary: 'All 27 interface languages are now fully translated. The AI Agents page adds ready-made agents and a no-code builder. Partner packs install cleanly with their catalogue and demo data. Example projects come filled out with real Revit, IFC and DWG models. Generated PDFs now render correctly in Cyrillic and other alphabets, and the desktop installers bundle the database engine so the app starts on a fresh machine.' },
  { version: '6.6.0', date: '2026-06-02', tag: 'NEW',       summary: 'PostgreSQL is now the only database. The app still starts its own database on first run, or you can point it at an external one. Also fixes 3D models on the project map so geometry shows as soon as a model is placed.' },
  { version: '6.5.0', date: '2026-06-02', tag: 'NEW',       summary: 'A redesigned AI Agents page with five new working agents: estimate review, cost classification, document search, cost summary and rate benchmarking. WhatsApp notifications. Placing a file on the project map works end to end with fast map tiles. The bill of quantities shows multiple currencies again, never blended.' },
  { version: '6.4.2', date: '2026-06-02', tag: 'FIX',       summary: 'Geometry fixes so BIM and 3D models sit at ground level. Partner Packs you can build and install by dropping a folder or uploading a zip, with no restart needed. Plus security dependency updates.' },
  { version: '6.4.1', date: '2026-06-02', tag: 'FIX',       summary: 'Build cleanup only. No change to how the app runs.' },
  { version: '6.4.0', date: '2026-06-02', tag: 'NEW',       summary: 'Estimate, BOQ, budget, purchase orders, contracts and bid packages now share one cost line, with a rollup that shows estimate, budget, committed, contracted and actual figures next to every linked record. Amounts are grouped by currency and never blended. The project map now flies to a 3D model once it has loaded.' },
  { version: '6.3.1', date: '2026-06-01', tag: 'FIX',       summary: 'Fixes the project map page crash and restores 3D geometry. The dashboard schedule and AI-insights widgets now use real data, coming-soon teasers are gone, and the Daily Diary PDF plus PDF and AI quantity matching are real. Partner Pack activation installs the bundled cost catalogue with a live progress bar.' },
  { version: '6.3.0', date: '2026-06-01', tag: 'NEW',       summary: 'Nine role-based company profiles: pick one and the sidebar shows just the modules that role needs. The Partner Packs banner now opens the in-app packs page, plus a place-on-map picker on the project map page.' },
  { version: '6.0.0', date: '2026-05-30', tag: 'MILESTONE', summary: 'PostgreSQL is now the default database with zero setup. It starts on first run with no Docker, and any old data is migrated for you. Plus 15 database bugs fixed.' },
  { version: '5.9.2', date: '2026-05-30', tag: 'NEW',       summary: 'Optional PostgreSQL scale foundation: faster JSON storage, automatic performance indexes, and a migration script. The simple single-command install is unchanged.' },
  // v5.x: second stable major
  { version: '5.5.1', date: '2026-05-28', tag: 'FIX',       summary: 'Re-ships the 5.5.0 build so the listing shows the correct command name. No runtime changes.' },
  { version: '5.5.0', date: '2026-05-28', tag: 'NEW',       summary: 'Stability wave: 8 user-reported bug fixes across takeoff, DWG, BIM and the data explorer, a login session fix, and a strong translation pass on 26 languages.' },
  { version: '5.4.3', date: '2026-05-28', tag: 'FIX',       summary: 'The map mode picker no longer kicks you back to the projects list, and address search now shows a Searching row while it looks up the address.' },
  { version: '5.4.2', date: '2026-05-28', tag: 'FIX',       summary: 'Converter cleanup: one-click DWG install when a conversion fails, and a clean human message when a BIM file is out of date, with technical details tucked behind a toggle.' },
  { version: '5.4.1', date: '2026-05-28', tag: 'SECURITY',  summary: 'Deep audit landings: 13 security fixes, 5 quiet calculation bugs, more data-privacy scrubbing, and a fix for the map view collapsing to a tiny square.' },
  { version: '5.4.0', date: '2026-05-27', tag: 'NEW',       summary: 'Quality wave: better cost matching, a second round of accessibility contrast fixes, and dark-mode button cleanup.' },
  { version: '5.3.0', date: '2026-05-27', tag: 'NEW',       summary: 'Map hub round 2, Brazil support (currency, standards and tax PDF), dark-mode login, a real reporting renderer, Daily Diary delete, and an accessibility contrast pass across 51 screens.' },
  { version: '5.2.8', date: '2026-05-27', tag: 'FIX',       summary: 'More reliable map tabs, a markups-to-takeoff deep link, and inline editing on resources.' },
  { version: '5.2.7', date: '2026-05-27', tag: 'NEW',       summary: 'A responsive widget grid on the project detail page, plus one-click in-app upgrade with a captured install log.' },
  { version: '5.2.0', date: '2026-05-26', tag: 'NEW',       summary: 'International BOQ exchange: import and export GAEB, BC3, NRM Excel and MasterFormat Excel.' },
  { version: '5.1.1', date: '2026-05-26', tag: 'NEW',       summary: 'File versioning, a notifications dispatcher, and a universal audit trail.' },
  { version: '5.0.0', date: '2026-05-26', tag: 'MILESTONE', summary: 'Second stable major: more AI providers, a viewable status for partial BIM files, and community contributions landed.' },

  // v4.x: stable major
  { version: '4.1.0', date: '2026-05-21', tag: 'NEW',       summary: 'Rollup wave: better BIM diagnostics, first critical-path schedule slice, an assembly library, an installable app, and a fully translated marketing site.' },
  { version: '4.0.1', date: '2026-05-20', tag: 'FIX',       summary: 'BIM view-cube orbit fix, marketing forms moved to a new provider, and denser module cards.' },
  { version: '4.0.0', date: '2026-05-20', tag: 'MILESTONE', summary: 'Stable 4.0: production-ready, 103 modules, and a passed legal and licensing audit.' },

  // v3.x: pro-grade waves, BOQ and BIM rebuild, element matching
  { version: '3.12.1', date: '2026-05-20', tag: 'FIX', summary: 'BIM upload safety checks, a catalogue picker for element matching, and a business-intelligence starter pack.' },
  { version: '3.12.0', date: '2026-05-20',             summary: 'Pro-grade wave: BOQ, cost intelligence, clash reports, BIM viewpoints, a files area, and PDF or Excel takeoff.' },
  { version: '3.11.0', date: '2026-05-20',             summary: 'More modules, validation on GAEB and Excel import, a GAEB writer, RVT diagnostics, and an /about page redesign.' },
  { version: '3.10.1', date: '2026-05-19',             summary: 'The element-matching "how it works" panel is now collapsed by default.' },
  { version: '3.10.0', date: '2026-05-19',             summary: 'A files area wave with clash collaboration and element-matching polish.' },
  { version: '3.9.1',  date: '2026-05-19', tag: 'FIX', summary: 'Clash model labels now read as models, not projects.' },
  { version: '3.9.0',  date: '2026-05-19',             summary: 'Add BOQ rows scoped to a section, automatic AI model recovery, a customizable dashboard, and PDF compare.' },
  { version: '3.8.0',  date: '2026-05-19',             summary: 'Deeper clash coordination, element-matching polish, and more consistent matching results.' },
  { version: '3.7.0',  date: '2026-05-19',             summary: 'New Clash Detection module, file-manager polish, and a batch of correctness fixes.' },
  { version: '3.6.1',  date: '2026-05-18', tag: 'FIX', summary: 'Nested BOQ levels now show correctly, with clean numbering and a PDF export fix.' },
  { version: '3.6.0',  date: '2026-05-18',             summary: 'Multi-level BOQ up to 8 levels deep, clean resource codes, and the full matching pipeline restored.' },
  { version: '3.5.0',  date: '2026-05-18',             summary: 'A pipeline builder, currency-correct CSV and Excel exports, a currency column, and a frozen exchange-rate appendix.' },
  { version: '3.4.1',  date: '2026-05-17', tag: 'FIX', summary: 'Project photos and file thumbnails load reliably, and demo projects include Revit and IFC models.' },
  { version: '3.4.0',  date: '2026-05-17',             summary: 'Polished showcase BOQs, a colored real-IFC hero model, and a viewer flicker fix.' },
  { version: '3.3.1',  date: '2026-05-17',             summary: 'A 7-project localized showcase, auto-loaded on a fresh install.' },
  { version: '3.3.0',  date: '2026-05-16',             summary: 'Reusable BOQ codes: link positions together, see master and instance badges, and unlink in one click.' },
  { version: '3.2.0',  date: '2026-05-16', tag: 'FIX', summary: 'Clean-install fix so all modules set up correctly, plus a 10-module planning and field-ops audit.' },
  { version: '3.1.0',  date: '2026-05-15',             summary: 'A deep correctness sweep across 23 modules.' },
  { version: '3.0.9',  date: '2026-05-15',             summary: 'New project setup wizard and a converter download integrity check.' },
  { version: '3.0.8',  date: '2026-05-15', tag: 'FIX', summary: 'Fixes a converter download failure on Windows and adds the project setup wizard backend.' },
  { version: '3.0.7',  date: '2026-05-14',             summary: 'Resource-based cost-database import with docs, templates and downloads.' },
  { version: '3.0.6',  date: '2026-05-14',             summary: 'Faster DWG uploads, 6 new cost regions, and sidebar branding.' },
  { version: '3.0.5',  date: '2026-05-14', tag: 'FIX', summary: 'Element-matching correctness fixes and full Mongolian translation.' },
  { version: '3.0.4',  date: '2026-05-13',             summary: 'Polish pass and a community contributor flow.' },
  { version: '3.0.3',  date: '2026-05-13',             summary: 'A workflow engine, an updated IFC parser, signed module manifests, and a collapsible sidebar.' },
  { version: '3.0.1',  date: '2026-05-13',             summary: 'An 18-module wave plus India support: Devanagari reading, local number formats and 16 regions.' },
  { version: '3.0.0',  date: '2026-05-12', tag: 'MILESTONE', summary: 'v3 milestone: rolled up the 2.x line, validated deploy, and 71 modules loaded.' },

  // v2.9.x: pre-v3 rapid iteration
  { version: '2.9.42', date: '2026-05-12',             summary: 'Dashboard pop-up layering fix and style polish.' },
  { version: '2.9.39', date: '2026-05-11',             summary: '12 new African cost catalogues and matching fixes.' },
  { version: '2.9.38', date: '2026-05-11',             summary: '11 classification standards now data-driven, up from 3.' },
  { version: '2.9.37', date: '2026-05-11',             summary: 'Africa pack with 19 currencies and 24 regions, plus one-click English install for element matching.' },
  { version: '2.9.36', date: '2026-05-10',             summary: 'A 10-pass polish of element matching: accessibility, speed and clearer messages.' },
  { version: '2.9.35', date: '2026-05-10',             summary: 'New analytics endpoint and dashboard.' },
  { version: '2.9.34', date: '2026-05-10',             summary: 'Version bump and build, a mid-session save.' },
  { version: '2.9.32', date: '2026-05-08',             summary: 'First phase of element matching: BIM plus several matchers and the UX around them.' },
  { version: '2.9.26', date: '2026-05-07',             summary: 'Search backend rework with many filters and a recall benchmark.' },
  { version: '2.9.25', date: '2026-05-07', tag: 'FIX', summary: 'Faster cost search without a region and an estimator role fix.' },
  { version: '2.9.24', date: '2026-05-07',             summary: 'Correctness fixes, one-click DWG install, and BIM panel polish.' },
  { version: '2.9.20', date: '2026-05-07',             summary: 'Faster startup: translations now load on demand instead of all at once.' },
  { version: '2.9.19', date: '2026-05-07',             summary: 'A sticky column in bid comparison and stronger photo upload checks.' },
  { version: '2.9.18', date: '2026-05-07',             summary: 'Three-way invoice match, a risk owner picker, and Gantt resize.' },
  { version: '2.9.17', date: '2026-05-07',             summary: 'Procurement now feeds finance, change orders update the budget, and tasks import in 9 languages.' },
  { version: '2.9.16', date: '2026-05-06',             summary: 'Finance correctness fixes and a 22-language files translation backfill.' },
  { version: '2.9.15', date: '2026-05-06', tag: 'SECURITY', summary: 'Access-control sweep across roughly 73 endpoints in planning, communication, procurement and documents.' },
  { version: '2.9.14', date: '2026-05-06', tag: 'SECURITY', summary: 'Access-control fixes on risk, change orders and contact export, plus a settings UI redesign.' },
  { version: '2.9.13', date: '2026-05-06',             summary: 'Shows the converter version on the BIM and quantities pages, with a force-reinstall option.' },
  { version: '2.9.12', date: '2026-05-06', tag: 'FIX', summary: 'Removed upload size caps, a photo format fix, BOQ load fixes, and files translated in 9 languages.' },
  { version: '2.9.1',  date: '2026-05-05',             summary: 'Multi-currency BOQ, a file manager, a DWG button, and a BIM viewer fix.' },
  { version: '2.9.0',  date: '2026-05-05',             summary: 'A deep files-area audit with ISO 19650 support, suitability codes and an audit log.' },

  // v2.8.x: per-project catalogue binding
  { version: '2.8.3', date: '2026-05-04', tag: 'FIX', summary: 'Clean-install fixes: version label, project BOQ load, and automatic cost region.' },
  { version: '2.8.2', date: '2026-05-04',             summary: 'Each project can now bind its own cost catalogue.' },

  // v2.7.x: stable rollup
  { version: '2.7.0', date: '2026-05-03', tag: 'SECURITY', summary: 'Access-control fixes on markups and speed fixes across meetings, field reports, punch list and tasks.' },

  // v2.6.x: access-control sweep, dashboards, compliance
  { version: '2.6.50', date: '2026-05-02', tag: 'SECURITY', summary: 'Access-control fixes on markups, speed fixes, and a workflow-builder handle fix.' },
  { version: '2.6.7',  date: '2026-04-27',             summary: 'Takeoff annotations now save to the backend, with all annotation types supported.' },
  { version: '2.6.4',  date: '2026-04-27',             summary: 'Completed the dashboards and compliance backlog across five patches.' },
  { version: '2.6.0',  date: '2026-04-26',             summary: 'BCF import and export is allowed again for issues, viewpoints and validation reports.' },

  // v2.5.x: observability plus DWG and PDF takeoff hardening
  { version: '2.5.0', date: '2026-04-25', tag: 'FIX', summary: 'PDF takeoff page indicator fix and viewer state hardening.' },

  // v2.4.x down to 2.0.x
  { version: '2.4.0', date: '2026-04-22',             summary: 'Better reporting and takeoff, more GAEB rule sets, and translation for 42 validation rules.' },
  { version: '2.3.1', date: '2026-04-22',             summary: 'A pluggable email backend and better cache error logging.' },
  { version: '2.3.0', date: '2026-04-22',             summary: 'Forgot-password reset links now work end to end.' },
  { version: '2.2.0', date: '2026-04-21',             summary: 'A mid-cycle release between 2.1 and 2.3.' },
  { version: '2.1.0', date: '2026-04-20',             summary: 'Per-tool shortcuts, undo and redo, and snap modes on DWG and PDF takeoff, plus a BIM cost colour mode.' },
  { version: '2.0.0', date: '2026-04-20', tag: 'MILESTONE', summary: 'More reliable AI chat, encrypted AI settings, and all tests green.' },

  // v1.9.x: security sprint plus DWG
  { version: '1.9.7', date: '2026-04-19', tag: 'SECURITY', summary: 'Security sprint: 10 critical login and input-validation holes closed.' },
  { version: '1.9.6', date: '2026-04-19', tag: 'SECURITY', summary: 'Safer GAEB import, file-type validation, and exact decimal money math throughout.' },
  { version: '1.9.5', date: '2026-04-18',             summary: 'Aligned several module APIs and modernised translations.' },
  { version: '1.9.4', date: '2026-04-18',             summary: 'Transmittals edit and delete, DWG scale, line, polyline and circle tools, and safer links.' },
  { version: '1.9.3', date: '2026-04-18',             summary: 'Background DWG uploads, right-click to create a task or link, and PDF export from the summary tab.' },
  { version: '1.9.2', date: '2026-04-18',             summary: 'Removed a duplicate BIM link button and disabled the unfinished 4D schedule with a tooltip.' },
  { version: '1.9.1', date: '2026-04-18',             summary: 'Better DWG click targeting, dashboard slicers and charts, saved views, and longer meeting minutes.' },
  { version: '1.9.0', date: '2026-04-17',             summary: 'Instant BOQ add, offline-first data loading, and a reliable quantity-rules list.' },

  // v1.8.x: BOQ to PDF and DWG deep linking
  { version: '1.8.3', date: '2026-04-17',             summary: 'Redesigned Apply to BOQ for linked geometry, and module uploads now flow into Documents.' },
  { version: '1.8.2', date: '2026-04-17',             summary: 'Documents now route files by type (PDF, DWG, RVT, IFC) with deep links and taller preview cards.' },
  { version: '1.8.1', date: '2026-04-17',             summary: 'DWG takeoff gains a full Link to BOQ picker, a summary bar, and CSV export of measurements.' },
  { version: '1.8.0', date: '2026-04-17',             summary: 'BOQ and PDF takeoff deep linking, with quantities that transfer automatically and clear link icons.' },

  // v1.7.x: BIM, DWG and cross-module
  { version: '1.7.2', date: '2026-04-16',             summary: 'BIM viewer toolbar tidy-up and a 3-column linked-geometry popover.' },
  { version: '1.7.1', date: '2026-04-16',             summary: 'A redesigned BIM landing page, a tasks filter fix, and consistent colour tokens.' },
  { version: '1.7.0', date: '2026-04-15',             summary: 'BIM linked-BOQ panel, DWG polygon measurements, assembly import and export, and a tasks Kanban.' },

  // v1.6.x down to v1.0
  { version: '1.6.0', date: '2026-04-15',             summary: 'A BIM linked-geometry preview in the BOQ grid, a quantity picker, and DWG area and perimeter.' },
  { version: '1.5.2', date: '2026-04-14', tag: 'FIX', summary: 'Unit dropdown fix in the BOQ editor and a DWG compatibility fix in Docker builds.' },
  { version: '1.5.1', date: '2026-04-14', tag: 'FIX', summary: 'Tendering deadline column fix and reliable BOQ description editing.' },
  { version: '1.5.0', date: '2026-04-13', tag: 'SECURITY', summary: '4 vulnerabilities and 2 concurrency bugs fixed, plus broader IFC civil support.' },
  { version: '1.4.8', date: '2026-04-11',             summary: 'Real-time collaboration: soft locks, presence, and row locking while you edit a BOQ cell.' },
  { version: '1.4.7', date: '2026-04-11',             summary: 'Determinate BIM progress and a converter pre-check with auto-install.' },
  { version: '1.4.6', date: '2026-04-11', tag: 'SECURITY', summary: 'Contacts access-control fix, collaboration permission checks, and a notifications framework.' },
  { version: '1.4.5', date: '2026-04-11',             summary: 'A cross-module integrity audit plus bulk-delete on requirements.' },
  { version: '1.4.4', date: '2026-04-11', tag: 'FIX', summary: 'Fixed a memory hazard in vector backfill and updated for newer Python.' },
  { version: '1.4.3', date: '2026-04-11',             summary: 'Link requirements to BIM, an 8th vector collection, and a global-search facet.' },
  { version: '1.4.2', date: '2026-04-11', tag: 'SECURITY', summary: 'A SQL injection guard, a vector payload fix, and frontend deep links.' },
  { version: '1.4.1', date: '2026-04-11',             summary: 'Validation and chat search adapters, startup backfill, and a semantic-search status panel.' },
  { version: '1.4.0', date: '2026-04-11',             summary: 'Semantic memory: 7 vector collections, multilingual search, and a global search shortcut.' },
  { version: '1.3.32', date: '2026-04-10',            summary: 'A BIM health banner, smart-filter chips, and 3 new compliance colour modes at 60 fps.' },
  { version: '1.3.22', date: '2026-04-11',            summary: 'Full BIM-to-BOQ linking in the UI, bulk quick takeoff, and a BIM quantity-rules page.' },
  { version: '1.3.18', date: '2026-04-10', tag: 'FIX', summary: 'BIM material and camera fixes, markups in PDF units, and safer zip handling.' },
  { version: '1.3.16', date: '2026-04-10', tag: 'SECURITY', summary: 'Ownership checks on validation, tendering and project intelligence, plus encrypted AI keys.' },
  { version: '1.3.15', date: '2026-04-10', tag: 'SECURITY', summary: 'Permission checks on BIM, finance, contacts and RFQ, with analytics scoped by owner.' },
  { version: '1.3.13', date: '2026-04-10',            summary: 'BIM geometry now shows on first load, plus a demo-mode banner.' },
  { version: '1.3.10', date: '2026-04-10', tag: 'FIX', summary: 'Fixed a Windows startup crash and made startup about 30 seconds faster.' },
  { version: '1.3.8',  date: '2026-04-10',            summary: 'A BIM filter panel and element explorer that stays fast on very large models.' },
  { version: '1.3.6',  date: '2026-04-10', tag: 'FIX', summary: 'BIM geometry now loads, and the chat page no longer 404s.' },
  { version: '1.3.0',  date: '2026-04-10',            summary: 'A full-page AI chat workspace with 11 tools and a redesigned BIM viewer.' },
  { version: '1.2.0',  date: '2026-04-09',            summary: 'A project completion AI co-pilot, an architecture map, and dashboard KPI cards.' },
  { version: '1.1.0',  date: '2026-04-09',            summary: 'A bridge release between the 1.0 milestone and the 1.2 features.' },
  { version: '1.0.0',  date: '2026-04-08', tag: 'MILESTONE', summary: 'Connected modules across 30+ packages, 14 integrations, 5 demo projects, and a 3D BIM viewer.' },

  // v0.x: early development
  { version: '0.9.1', date: '2026-04-07',             summary: 'A Discord webhook and an integration hub for n8n, Zapier, Make, Google Sheets and Power BI.' },
  { version: '0.9.0', date: '2026-04-07',             summary: '30 backend modules and 13 pages, with 35 currencies, 198 countries and 20 languages.' },
  { version: '0.8.0', date: '2026-04-07',             summary: 'Custom BOQ columns, one-click renumber, a project health bar, and a strong-password policy.' },
  { version: '0.7.0', date: '2026-04-07',             summary: 'Multi-level BOQ sections, Excel import that keeps columns, and a formula engine for assemblies.' },
  { version: '0.6.0', date: '2026-04-07',             summary: 'Resource quantities scale with positions, automatic unit rates, and drag-and-drop between sections.' },
  { version: '0.5.0', date: '2026-04-06',             summary: 'PDF takeoff, professional Excel and PDF export, and a CAD or BIM pivot into a BOQ.' },
  { version: '0.4.0', date: '2026-04-06',             summary: 'Quick dialogs for projects, BOQs and assemblies, plus filters on the BOQ list.' },
  { version: '0.3.0', date: '2026-04-05',             summary: 'A data explorer with CSV export, field reports, a photo gallery, markups and a punch list.' },
  { version: '0.2.1', date: '2026-04-04', tag: 'FIX', summary: 'Stronger download checks, a login fix, and dependency updates.' },
  { version: '0.1.1', date: '2026-04-01', tag: 'FIX', summary: 'Fixed a settings page freeze and a project delete error, with safer project names.' },
  { version: '0.1.0', date: '2026-03-27', tag: 'NEW', summary: 'First release: 18 validation rules, AI estimation, 55K cost items, 20 languages, and a BOQ grid.' },
];

/**
 * Parse a semver-ish version string into a comparable tuple. Falls back to
 * lexical compare for malformed input, which keeps a typo from blowing up
 * the whole list render.
 */
function parseVersion(v: string): number[] {
  return v.split('.').map(part => {
    const n = parseInt(part, 10);
    return Number.isFinite(n) ? n : 0;
  });
}

function compareVersionsDesc(a: ChangelogEntry, b: ChangelogEntry): number {
  const av = parseVersion(a.version);
  const bv = parseVersion(b.version);
  for (let i = 0; i < Math.max(av.length, bv.length); i += 1) {
    const ai = av[i] ?? 0;
    const bi = bv[i] ?? 0;
    if (ai !== bi) return bi - ai;
  }
  return 0;
}

// Older releases (> 6 months ago relative to "today") fade slightly so the
// recent ones pop. We use a stable date constant, not Date.now(), so the
// muted band doesn't silently drift between builds.
const TODAY = new Date('2026-05-21T00:00:00Z');
const FRESH_WINDOW_DAYS = 30 * 6;
function isStale(date: string): boolean {
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return false;
  const ageDays = (TODAY.getTime() - d.getTime()) / 86_400_000;
  return ageDays > FRESH_WINDOW_DAYS;
}

const TAG_VARIANT: Record<Tag, 'success' | 'blue' | 'warning' | 'error' | 'neutral'> = {
  NEW: 'success',
  FIX: 'warning',
  BETA: 'blue',
  SECURITY: 'error',
  MILESTONE: 'blue',
};

export function Changelog() {
  const { t } = useTranslation();

  const entries = [...CHANGELOG].sort(compareVersionsDesc);
  // Latest 7 versions get visible tag chips; older ones drop the tag to keep
  // the card list calm. The tag is still encoded in the data, just not shown.
  const FRESH_TAG_COUNT = 7;

  const tagLabel = (tag: Tag): string => {
    switch (tag) {
      case 'NEW':       return t('about.changelog_tag_new', { defaultValue: 'NEW' });
      case 'FIX':       return t('about.changelog_tag_fix', { defaultValue: 'FIX' });
      case 'BETA':      return t('about.changelog_tag_beta', { defaultValue: 'BETA' });
      case 'SECURITY':  return t('about.changelog_tag_security', { defaultValue: 'SECURITY' });
      case 'MILESTONE': return t('about.changelog_tag_milestone', { defaultValue: 'MILESTONE' });
    }
  };

  return (
    <div id="changelog">
      <div className="flex items-baseline justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-content-primary">
          {t('about.changelog_title', { defaultValue: 'Changelog' })}
        </h2>
        <span className="text-2xs text-content-tertiary tabular-nums">
          {t('about.changelog_count', {
            defaultValue: '{{count}} releases',
            count: entries.length,
          })}
        </span>
      </div>

      {/*
        CSS columns layout packs variable-height cards into the shorter
        column automatically without the gymnastics of a manual two-list
        split. `break-inside-avoid` on each card keeps a single entry from
        being torn across the column boundary.
      */}
      <div className="columns-1 md:columns-2 gap-4 [column-fill:_balance]">
        {entries.map((entry, idx) => {
          const isCurrent = entry.version === APP_VERSION;
          const stale = !isCurrent && isStale(entry.date);
          const showTag = entry.tag && idx < FRESH_TAG_COUNT;
          return (
            <article
              key={`${entry.version}-${entry.date}`}
              className={[
                'mb-3 break-inside-avoid rounded-xl border px-3.5 py-2.5',
                'bg-white/60 backdrop-blur-xl border-white/40',
                'dark:bg-slate-900/40 dark:border-white/[0.05]',
                'transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md hover:bg-white/80 dark:hover:bg-slate-900/60',
                isCurrent ? 'ring-1 ring-emerald-500/50 bg-emerald-50/60 dark:bg-emerald-900/15 dark:ring-emerald-400/40' : '',
                stale ? 'opacity-70' : '',
              ].join(' ')}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant={isCurrent ? 'success' : 'blue'} size="sm">
                  v{entry.version}
                </Badge>
                <span className={`font-mono text-2xs tabular-nums ${stale ? 'text-content-quaternary' : 'text-content-tertiary'}`}>
                  {entry.date}
                </span>
                {isCurrent && (
                  <span className="text-2xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                    {t('about.current_version', { defaultValue: 'Current' })}
                  </span>
                )}
                {showTag && entry.tag && (
                  <Badge variant={TAG_VARIANT[entry.tag]} size="sm">
                    {tagLabel(entry.tag)}
                  </Badge>
                )}
              </div>
              <p className={`mt-1.5 text-xs leading-snug ${stale ? 'text-content-tertiary' : 'text-content-secondary'}`}>
                {entry.summary}
              </p>
            </article>
          );
        })}
      </div>
    </div>
  );
}
