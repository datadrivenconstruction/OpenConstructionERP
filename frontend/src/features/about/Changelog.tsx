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
  /**
   * One short summary in plain language. Proper-noun-heavy strings stay in English.
   * Each changelog description must be 1 to 2 sentences.
   */
  summary: string;
  tag?: Tag;
}

// Sorted newest to oldest. Sort is enforced at runtime below (semver-aware) so
// out-of-order entries here still display correctly.
//
// RULE: each changelog description must be 1 to 2 sentences. Keep the version,
// date, title and meaning intact; trim the prose, not the facts.
const CHANGELOG: ChangelogEntry[] = [
  { version: '8.8.2', date: '2026-06-21', tag: 'NEW', summary: 'BIM and CAD converters now install themselves the first time you upload a model, with no Settings trip and no manual steps: the install tries a system package install, a rootless unpack, and a built-in pure-Python reader in turn, so it works on minimal containers and non-Debian hosts too, resuming slow downloads and self-testing the binary afterwards. Bill-of-quantities exports and the compare view also convert foreign-currency amounts into the project base currency before totalling, at both the position and resource level, so mixed-currency exports add up correctly.' },
  { version: '8.8.1', date: '2026-06-21', tag: 'FIX', summary: 'A quick follow-up fix: a PDF uploaded for quantity takeoff now stays attached to the active project, so it remains in the document list after you reload the page. Previously the upload was saved without a project and the project-filtered list dropped it on refresh.' },
  { version: '8.8.0', date: '2026-06-21', tag: 'NEW', summary: 'Monte-Carlo cost-risk analysis turns a bill of quantities into a full cost distribution - P5 to P95 bands, a probability S-curve, a recommended contingency at your confidence level, and a tornado chart of the biggest variance drivers - and a new in-app "How it works" hub explains every module in all 27 languages. This release also adds lightweight 2D project maps in the Geo Hub, a DIN 276 element breakdown in cost benchmarks, count-by-example symbol counting in takeoff, quantity-weighted progress rollups, and a background converter install that no longer times out on slow servers.' },
  { version: '8.7.1', date: '2026-06-20', tag: 'FIX', summary: 'A maintenance release: the repeated "request timed out" message no longer floods the screen on a busy server, a CAD drawing whose conversion was interrupted by a restart now shows a clear, recoverable error instead of spinning forever, and the AI Estimator no longer analyses the source twice when you start a new estimate. It also confines the AI agent reading tools to projects the user can access, aligns the transmittals statuses with the backend, and polishes the guided AI estimate, point cloud and Geo Hub screens.' },
  { version: '8.7.0', date: '2026-06-20', tag: 'SECURITY', summary: 'A broad security release: cross-tenant access gaps were closed across requirements, contacts, project controls and other modules, monetary inputs now reject not-a-number, infinity and absurd magnitudes, currency roll-ups no longer blend different currencies, and partial edits no longer drop the fields they did not mention. It also adds methodology-aware country and industry packs, PDF and Excel export for methodology estimates, LAS, LAZ and COPC point cloud reading, and a clear no-geometry notice for BIM models that have no 3D mesh.' },
  { version: '8.6.1', date: '2026-06-19', tag: 'FIX', summary: '3D BIM models, DWG drawings and takeoff PDFs that had been uploaded and marked ready could fail to open with a file-not-found error on standalone-PostgreSQL, Docker and macOS deployments, because the files were written to one location and read from another. Storage now resolves a single consistent data directory across every launch mode, with a fallback that still finds files saved by earlier versions, so existing uploads keep working.' },
  { version: '8.6.0', date: '2026-06-18', tag: 'NEW', summary: 'A data-driven estimating methodology engine: instead of one fixed markup chain, a project can follow a named methodology you build in the app, with a typed bill-of-quantities hierarchy, analytical dimensions, funding sources and a cascade of markups that build on one another. Country and industry templates ship ready to install, the cascade editor shows a live preview reconciled against the server, and construction machinery is now costed separately from installed equipment.' },
  { version: '8.5.0', date: '2026-06-18', tag: 'NEW', summary: 'DWG and DXF takeoff is now a full vector takeoff: one click produces a per-layer quantity table with the right unit for each layer, plus a count-by-block tool, drawing-text search and one-click Excel export. The PDF takeoff viewer gains a page-thumbnail sidebar, find-on-sheet, scale detection and fit and zoom controls, steel can be priced by mass, and the 3D viewer now degrades gracefully on marginal GPUs.' },
  { version: '8.4.0', date: '2026-06-17', tag: 'FIX', summary: 'PDF takeoff measurements are now scoped to the project and the specific document they were drawn on rather than keyed by file name, so two files that share a name no longer show the same measurements. The resources under a bill-of-quantities position now expand on the first click, and the public hosted demo keeps its bundled cost databases read-only.' },
  { version: '8.3.3', date: '2026-06-15', tag: 'FIX', summary: 'Totals that summed money values arriving from the server as text were concatenating instead of adding, producing wrong figures. This is fixed across the Excel and PDF bill-of-quantities exports, the assembly rate rollups, the BOQ tree and resource subtotals, the cost model planned, committed, actual, forecast and variance columns, the bid analysis breakdown, and the chat and AI estimate totals.' },
  { version: '8.3.2', date: '2026-06-15', tag: 'SECURITY', summary: 'Money figures that the server sends as text no longer break the screens that show them, so tender and bill-of-quantities exports, the reports and analytics totals, the cost benchmark, the 5D cost model, the regional rate adjustment and the cost-match panels all render their amounts reliably. Access checks were also tightened so an account only opens and changes records in projects it can reach, covering bill-of-quantities locking, the safety toolbox-talk and corrective-action endpoints, timecard import and shared saved views.' },
  { version: '8.3.1', date: '2026-06-15', tag: 'FIX', summary: 'Sample projects are now clearly labelled and easy to remove so a fresh install can start from an empty workspace, a new project takes its currency from your regional preference, and the AI estimate builder, the match-to-cost wizard and the assembly template dialog now follow the project chosen in the top bar. Regional cost-database downloads explain a blocked connection and offer a retry, and the new wording is translated across all 26 other languages.' },
  { version: '8.3.0', date: '2026-06-15', tag: 'NEW', summary: 'A new South Africa construction pack, the first in our African coverage, pre-configured with SANS 1200 and ASAQS measurement, CIDB contractor grading, the PPPFA 80/20 and 90/10 procurement scoring, the nine provinces and the rand with 15 percent VAT, and Johannesburg cost data on demand. This release also translates the most recent feature screens across all 26 other languages.' },
  { version: '8.2.2', date: '2026-06-15', tag: 'FIX', summary: 'The macOS desktop app no longer opens with a "damaged" warning. The build is now ad-hoc signed across the app and its bundled local server so the code signature is valid, and the install guide explains the one-time command to clear the download quarantine.' },
  { version: '8.2.1', date: '2026-06-15', tag: 'SECURITY', summary: 'A hardening release. Editing one part of a record no longer clears the other details saved on it, fixed across more than two dozen modules where a partial edit used to overwrite the whole stored details field. Paying an invoice now updates budget actuals correctly when some of the spend was already received, cost breakdowns convert mixed currencies before totalling, and reversing a ledger entry writes back every leg. Access checks were tightened so an account only reads and changes records in projects it can reach, and high-value variations, awarded bids and permit activation now require the matching permission.' },
  { version: '8.2.0', date: '2026-06-14', tag: 'NEW', summary: 'A new project journey map in the top bar names the phase you are in and opens the whole project lifecycle, from winning the work to handover, with every major module placed on its phase as a link, translated in every language. This release also warns when a project exchange rate looks entered upside down, validates BIM models imported from spreadsheets or bulk files, and flags scanned PDF pages in takeoff that need OCR.' },
  { version: '8.1.0', date: '2026-06-14', tag: 'SECURITY', summary: 'A broad access-control pass makes sure every account only sees and changes data in the projects it can reach, across finance, business intelligence, jobs, approval workflows, the cost catalogue, lead webhooks, property development and the chat assistant; a request that omits a project filter is now scoped to your own projects. A new top-bar news button opens the latest release news, the takeoff CSV export subtracts openings the way Excel does, and DIN 276 cost groups validate across the full code hierarchy.' },
  { version: '8.0.0', date: '2026-06-13', tag: 'MILESTONE', summary: 'Every major module now has a built-in guide: a help button opens a short panel that explains what the module does, the main steps and a few tips, in your language. This release also fixes DWG takeoff drawings on a fresh install, clears links to deleted bill of quantities positions, hardens cross-tenant access on the BOQ and AI estimator endpoints, and finishes the interface translation in every language.' },
  { version: '7.10.0', date: '2026-06-13', tag: 'NEW',       summary: 'ERP Chat now renders Markdown tables as real tables, and the quick create and project setup windows are fully translated in all 27 languages. Regional cost catalogues download on demand instead of shipping inside the install, so it is about 15 MB lighter while all thirty regions stay available.' },
  { version: '7.9.0', date: '2026-06-13', tag: 'NEW',       summary: 'You can now keep your own company price books in the cost database, import them from Excel or CSV, filter by catalogue and export back to Excel, with thirty regional catalogues working offline. The 5D cost model gains an earned value column, estimate-based schedules get realistic durations, and an audit pass fixes European decimal rates, budget duplication, blended foreign-currency change orders and the project switcher.' },
  { version: '7.8.0', date: '2026-06-12', tag: 'NEW',       summary: 'The bill of quantities gains optional Material, Labor and Equipment columns that show how each unit rate splits across the three, plus three worked retail example projects for German cities. Consolidated ledger statements are now admin-only, imported rules stay per project, the BOQ Excel export reconciles again, and fixes land for AI estimate numbers, empty validation passes, the 3D viewer and translated messages.' },
  { version: '7.7.0', date: '2026-06-11', tag: 'NEW',       summary: 'BOQ descriptions can now hold a full multi-line specification like a German LV Langtext, row height cycles between three sizes, and the New BOQ window imports GAEB, BC3, Excel, CSV, PDF or CAD on the spot. Partner, country and industry packs sit under one Packs tab, a worked discount-store example project ships, GAEB X84 import no longer loses money and exports valid 3.3, and large point-cloud uploads finish reliably.' },
  { version: '7.6.0', date: '2026-06-11', tag: 'NEW',       summary: 'A new finance general ledger keeps a chart of accounts and produces a trial balance, income statement, balance sheet and cash flow, you can erase your own account from Settings, and takeoff can read a PDF plan with a vision model. Large uploads resume after a dropped connection, limits are much higher, a saved-views module remembers filtered lists, and tenant isolation and money math were hardened across twelve modules.' },
  { version: '7.5.0', date: '2026-06-10', tag: 'NEW',       summary: 'Takeoff Recognize now reads scanned drawings with no vector layer, you can drag a placed measurement directly on the drawing with the quantity updating live, and a Save PDF button exports the marked-up drawing. Cost Benchmarks compare a project against your own portfolio by currency, file downloads are fixed for every file including DWG and IFC, and the dashboard quick-upload gains a project picker.' },
  { version: '7.4.0', date: '2026-06-10', tag: 'NEW',       summary: 'Takeoff measurements and markups now open the real drawing with the item in view, example projects start with real site photos, and a new Point Cloud beta registers laser scan, photogrammetry and LIDAR clouds. Many modules now arrive filled with example data, and the AI Estimate Builder no longer crashes when you confirm the parameter sheet.' },
  { version: '7.3.0', date: '2026-06-08', tag: 'NEW',       summary: 'BIM viewer grouping and filtering on IFC models line up with the geometry again and stay on the selection, the upload picker accepts RVT, IFC and DWG only, and a new schedule-quality pack adds seven checks. Self-explaining modules arrive across the platform with confidence badges, suggestion chips, plain-language errors and an inline glossary in every language.' },
  { version: '7.2.0', date: '2026-06-08', tag: 'FIX',       summary: 'Fixes the Windows app that could get stuck on "Recovering the local database" under the Turkish regional format, and heals a machine already stuck. The AI Estimate Builder no longer shows a fake $0.00, reads parameters in plain words and shows live progress, the BIM filter panel is translated in all 26 languages, and module switching, the RVT converter and IFC filters work correctly again.' },
  { version: '7.1.0', date: '2026-06-07', tag: 'NEW',       summary: 'Related records are now one click away everywhere, with over 80 new two-way links across variations, change orders, contracts, clashes and inspections, and the AI Estimate Builder talks you through scope with editable work packages and explained rates. The desktop app sets itself up on first launch, and about a thousand interface strings per language were brought to native copy in all 26 languages.' },
  { version: '7.0.1', date: '2026-06-06', tag: 'FIX',       summary: 'Fixes the Windows desktop app that could close on its own right after opening. It now shows a clear error if it cannot start, reuses a running backend only when versions match, and installs without needing a download.' },
  { version: '7.0.0', date: '2026-06-06', tag: 'MILESTONE', summary: 'A new AI Estimate Builder turns a typed scope, a BIM model or uploaded files into a priced bill of quantities, with prices always from the cost catalogue, and every module now has one clean title and a short explainer card in all 27 languages. The collaboration hub is a real workspace, and many modules got fixes so dashboards, validation and matching just work.' },
  { version: '6.10.0', date: '2026-06-05', tag: 'NEW',      summary: 'Field time tracking with real payroll, where a crew lead logs hours that flow into a payroll batch and post to the ledger exactly once, plus a project-controls dashboard for cost, schedule, quality, safety and risk health. Owner billing forms for US, Canada and Australia, a subcontractor payment portal, and a client progress-reports tab round out the release.' },
  { version: '6.9.0', date: '2026-06-05', tag: 'NEW',       summary: 'A new Management of Change register screen, with cost matching working again for projects outside the US and backup restore limited to your own data so it cannot wipe another user. Plus broad backend hardening and the desktop fixes from the 6.8 builds.' },
  { version: '6.8.2', date: '2026-06-05', tag: 'FIX',       summary: 'The Windows, macOS and Linux desktop installers build again, carrying the 6.8.1 database fix that had shipped on pip and Docker but not as an installer.' },
  { version: '6.8.1', date: '2026-06-05', tag: 'FIX',       summary: 'The desktop app now launches reliably after install. It connects to its own local database correctly and shows a clear message plus a startup log if anything goes wrong, instead of failing silently.' },
  { version: '6.8.0', date: '2026-06-04', tag: 'NEW',       summary: 'Quantity takeoff on DWG drawings now reports correct real-world metres, and a wave of features links the modules together, from subcontractor scorecards and progress claims to resource leveling and offline field work. Interface translation gaps were cleared across all 26 non-English languages.' },
  { version: '6.7.0', date: '2026-06-03', tag: 'NEW',       summary: 'All 27 interface languages are now fully translated, the AI Agents page adds ready-made agents and a no-code builder, partner packs install cleanly with their catalogue and demo data, and example projects come filled out with real Revit, IFC and DWG models. Generated PDFs now render correctly in Cyrillic and other alphabets, and the desktop installers bundle the database engine so the app starts on a fresh machine.' },
  { version: '6.6.0', date: '2026-06-02', tag: 'NEW',       summary: 'PostgreSQL is now the only database, started for you on first run or pointed at an external one. This release also fixes 3D models on the project map so geometry shows as soon as a model is placed.' },
  { version: '6.5.0', date: '2026-06-02', tag: 'NEW',       summary: 'A redesigned AI Agents page with five new working agents (estimate review, cost classification, document search, cost summary and rate benchmarking), plus WhatsApp notifications. Placing a file on the project map works end to end with fast map tiles, and the bill of quantities shows multiple currencies again, never blended.' },
  { version: '6.4.2', date: '2026-06-02', tag: 'FIX',       summary: 'Geometry fixes so BIM and 3D models sit at ground level, and Partner Packs you can build and install by dropping a folder or uploading a zip with no restart. Plus security dependency updates.' },
  { version: '6.4.1', date: '2026-06-02', tag: 'FIX',       summary: 'Build cleanup only. No change to how the app runs.' },
  { version: '6.4.0', date: '2026-06-02', tag: 'NEW',       summary: 'Estimate, BOQ, budget, purchase orders, contracts and bid packages now share one cost line, with a rollup that shows estimate, budget, committed, contracted and actual figures next to every linked record, grouped by currency and never blended. The project map now flies to a 3D model once it has loaded.' },
  { version: '6.3.1', date: '2026-06-01', tag: 'FIX',       summary: 'Fixes the project map page crash and restores 3D geometry, with the dashboard schedule and AI-insights widgets now on real data, coming-soon teasers gone, and the Daily Diary PDF plus PDF and AI quantity matching made real. Partner Pack activation installs the bundled cost catalogue with a live progress bar.' },
  { version: '6.3.0', date: '2026-06-01', tag: 'NEW',       summary: 'Nine role-based company profiles: pick one and the sidebar shows just the modules that role needs. The Partner Packs banner now opens the in-app packs page, plus a place-on-map picker on the project map page.' },
  { version: '6.0.0', date: '2026-05-30', tag: 'MILESTONE', summary: 'PostgreSQL is now the default database with zero setup, starting on first run with no Docker and migrating any old data for you. Plus 15 database bugs fixed.' },
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

/**
 * Top N changelog entries, newest version first. Single source of truth for
 * the /about header's "Recent releases" list so it never drifts from the
 * changelog below. Reuses the semver-aware {@link compareVersionsDesc}.
 */
export function getRecentReleases(count = 3): ChangelogEntry[] {
  return [...CHANGELOG].sort(compareVersionsDesc).slice(0, Math.max(0, count));
}

// Older releases (> 6 months ago relative to the real current date) fade
// slightly so the recent ones pop. Computed at render time against the
// actual "now" so the newest releases never get muted.
const FRESH_WINDOW_DAYS = 30 * 6;
function isStale(date: string): boolean {
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return false;
  const ageDays = (new Date().getTime() - d.getTime()) / 86_400_000;
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
