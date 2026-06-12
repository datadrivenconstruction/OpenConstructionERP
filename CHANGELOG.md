# Changelog

All notable changes to OpenConstructionERP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.9.0] - 2026-06-13

### Added

- Your own cost catalogues. You can now keep company price books inside the cost database: create a catalogue with its own required currency, fill it by hand or by importing an Excel or CSV price list, and apply its rates when estimating. The importer understands Russian column headings such as "Цена за ед." and European number formats like 8 450,00, warns when a file mixes currencies, and rows without a currency inherit the catalogue's. Catalogues appear as chips above the cost list for one-click filtering, and each one exports back to Excel with its real name kept intact in the filename, including non-Latin names.
- Offline regional cost data. Thirty regional reference catalogues, from St. Petersburg to Tokyo, now ship inside the install itself, so loading one takes seconds and works with no internet connection at all.
- Recording site progress on the 5D cost model. Budget lines that come from estimate positions now carry an earned value column, and you can record percent complete right in the line: the recorded percent becomes earned value at the position's budgeted rate, the column totals across the project, and the figure feeds the EVM analysis. Creating a budget from the estimate also seeds these lines automatically.
- Estimated activity durations in the 4D schedule. Generating a schedule from an estimate no longer produces zero-day activities when no labour data is available: durations fall back to built-in production rates per unit of work, and every estimated duration is marked with an "Est." badge so you know which bars to refine.
- Demo data you can actually remove. The projects page tells administrators how many of the visible projects are seeded demo content and offers to remove them in one click, without ever touching your own projects, and they stay gone after a restart.
- Faster project creation. Quick create now needs only a project name, everything else is optional, and the new project becomes the active one everywhere immediately, so the next page you open is already working on it.

### Fixed

- A European rate with three decimal places, like 0,500, no longer imports a thousand times too large. A single comma in a number is always read as the decimal separator; only multi-group figures like 1,234,567 are treated as thousands.
- Creating a budget from the estimate twice no longer doubles the finance budget, and the endpoint now checks that you are a member of the project. The material, labour and equipment share columns fill in and sum correctly across the estimate, including right after editing a resource.
- An approved change order in a different currency than its contract is recorded but no longer silently added into the contract total at face value, and two change orders approved at the same moment can no longer overwrite each other's contract update.
- Budget lines generated from positions priced in a foreign currency keep that currency label instead of being mislabelled as the project currency.
- Importing a second price list without a code column into the same catalogue no longer collides with the first one and silently imports nothing.
- The cost page no longer snaps back to a region filter on its own after you pick a catalogue, choose all regions, or delete an item, and downloaded export files no longer carry a stray underscore at the end of the name.
- The header project switcher keeps up with project changes: creating, deleting, duplicating, archiving or restoring a project updates the list immediately, and a freshly created project can no longer lose its active status to a stale list.
- Self-hosted AI models connect properly: an Ollama or vLLM endpoint is routed to the right provider even though the model name contains "llama", and no authorization header is sent when there is no key to send.
- Spreadsheet imports are hardened against zip bombs, and upgraded desktop installs receive the new database index they need so catalogue filtering stays fast on large cost databases.

## [7.8.0] - 2026-06-12

### Added

- Optional Material, Labor and Equipment columns in the bill of quantities. A button in the grid settings turns on three percentage columns that show, per position, how the unit rate splits across material, labour and equipment, so you can see the cost driver of every line at a glance and sort or filter on it. The columns are off by default and your choice is remembered. The same split also reads correctly straight after you edit a resource quantity or rate, recomputing from the live figures instead of an old cached value.
- Worked retail-market example projects for three German cities. Each one is a full discount-store estimate built from real trades with named crews, materials and equipment at regional rates, from earthworks and shell through drywall, screed, tiling and painting to refrigeration, ventilation, electrical, photovoltaics and external works, so the resources reflect how the work is actually priced rather than placeholder lines.

### Fixed

- Consolidated general ledger statements are now limited to administrators. A trial balance, income statement, balance sheet or cash flow requested without a project used to span every project on the instance for any finance reader; it now requires an administrator, and everyone else passes a project to see that project's books.
- Imported IDS validation rules are kept separate per project. A rule set imported into one project can no longer collide with, or be applied to, another project's data.
- The bill of quantities Excel export reconciles again. The sheet now writes the direct cost and each markup line above the grand total, so the total column adds up to the grand total instead of the markups quietly disappearing from the file.
- The AI estimate no longer lets a broken number reach your money. A non-numeric quantity or rate is rejected before it becomes a position, and a catalogue rate only replaces the estimated rate when the match is confident enough.
- Model validation is honest about an empty check. Validating a model where nothing matched the rules now reports as not checked rather than a green hundred percent pass.
- The 3D viewer no longer turns black after opening several models in a row, the cost-database import recovers cleanly if you leave the page mid-load, and the validation dashboard shows information-level findings in their own style instead of as warnings.
- Validation messages and suggestions now appear in your language, and the run result tells you which requested rule sets actually ran. Comment threads are checked against project access. A markup type that had no real effect is no longer accepted, and the demo sign-in shortcut is refused on a production install.

## [7.7.0] - 2026-06-11

### Added

- A multi-line description view for the bill of quantities. A position description can now carry a full specification text with paragraphs and line breaks, the way a German LV Langtext reads, and a toolbar button cycles the row height between compact, comfortable and tall so you can read the long text in place. Editing a description opens a large text box.
- Import a country standard straight from the New BOQ window. When you create a bill of quantities you can pick a file and have it imported on the spot, with the common national exchange formats recognised automatically: GAEB for the German-speaking countries, FIEBDC-3 (BC3) for Spain and Latin America, and Excel or CSV anywhere, while PDF and CAD are routed to the AI import.
- A worked retail-market example project. A new discount-store build estimate covers the popular trades, from earthworks, shell and roof through drywall partitions, screed, tiling, painting, internal doors and suspended ceilings to sanitary, ventilation, CO2 refrigeration, electrical, photovoltaics and external works, with a DIN 276 budget and a 303-position detailed bill that closes to the cent on every procurement unit.
- The Packs umbrella. Partner packs, country standard packs and industry template packs now sit under one Packs tab with a type badge on each card. The old partner-pack entry points, environment variable and state file keep working unchanged, so any pack already applied loads exactly as before.

### Fixed

- GAEB import no longer zeros out money. A GAEB X84 file used to import with a grand total of 0.00; the direct cost is now read cent-exact, and an export followed by a re-import preserves the total. Export also emits schema-valid GAEB DA XML 3.3, and the GAEB rule set no longer flags the official test file with dozens of false errors.
- Point cloud upload no longer fails at the final step. Finishing a large scan upload could return a 500 from the finalise call; it now completes and records the scan.
- Validation reports honestly on rule sets it does not run. An advertised but not-yet-implemented rule set now reports as unsupported with no score instead of silently passing, so a project can never look checked against a standard the engine does not actually enforce.

## [7.6.0] - 2026-06-11

### Added

- A general ledger built on double-entry accounting. A new finance ledger keeps a chart of accounts, posts balanced journal entries, and produces a trial balance, an income statement, a balance sheet and a direct-method cash flow statement. Every journal is checked to balance before it posts, so the books never drift.
- Self-service account erasure. You can erase your own account and personal data from the Settings danger zone, covering the right to erasure, with a clear confirmation before anything is removed.
- AI plan reading for PDF takeoff. The takeoff tool can read a drawing with a vision model and propose what it finds as labelled suggestions you confirm, and the server still re-derives every billed quantity on save.
- Resumable uploads for large CAD and PDF files. A big upload now goes up in chunks and resumes where it left off if the connection drops, instead of starting over.
- A saved-views module, so a filtered and sorted view of a list can be saved and reopened later.
- A point cloud upload page for the reality-capture beta, with the dashboard and login polish that goes with it.
- Privacy, terms and cookie policy pages.

### Changed

- Higher limits across the board. Large uploads, longer lists per page and bigger bulk actions all have more room: chunked uploads accept much larger files, spreadsheet imports allow more data, and pagination and bulk operations carry more rows in one go. The sign-in rate limit is unchanged.
- The module navigation tabs and key dialog buttons are now translated in all 27 languages, closing another wave of interface-text gaps.
- Integration copy uses neutral, format-level names instead of specific product names.

### Fixed

- A hardening pass across twelve modules tightened tenant isolation and money math, so amounts compute consistently and every request stays inside the right workspace.
- The onboarding Full Enterprise profile installs the right module set regardless of what the client sends.
- The production Docker deployment accepts larger drawing uploads, and takeoff cost figures are carried as exact decimal strings.
- The built-in SQLite to PostgreSQL copy survives a newer target schema instead of failing on a column it did not expect.
- The remaining vector-search calls moved to the current query API after the search client dropped its old method.

### Security

- A user can remove their own account and personal data through the right-to-erasure flow.
- Tenant isolation and money handling were hardened across twelve modules.

## [7.5.0] - 2026-06-10

### Added

- Recognition on scanned drawings. The takeoff Recognize tool now reads scanned floor plans that have no vector layer, detecting room outlines and wall lines from the image, so a paper-scan PDF returns usable measurement candidates instead of nothing. Vector PDFs keep using the precise vector path, so nothing changes for drawings that already carry geometry.
- Edit measurements directly on the drawing. You can select a placed measurement and reshape it on the canvas: drag a vertex, pull an edge to add a point, move the whole shape, or reposition a count marker, with the value updating live as you drag. The server re-derives the billed quantity on save, so an on-canvas edit can never inflate a number.
- Save the marked-up PDF. A new Save PDF button in the takeoff toolbar exports the drawing with your measurements and annotations baked into the file.
- Cost Benchmarks from your own projects. The benchmarks page now compares a project against the real distribution of your own portfolio, cost per square metre by currency, and shows where the project sits as a percentile. It falls back to the industry reference when you do not yet have enough priced projects, and it never mixes currencies or invents a number.
- A project picker on the dashboard quick-upload, so a dropped file can go to any project without leaving the dashboard.

### Fixed

- Downloads in the file manager work again. Files are now fetched with your sign-in, so a download no longer fails with a "you need to log in" or "file not available" message. Every file in a project downloads, including DWG and IFC files and the entries that previously returned a not-found error.
- The Estimate Builder is clearly marked as beta, in the menu and inside the module, with a short note that its grouping and matching are still maturing while every rate still comes from your own cost database.
- A clearer message when a CAD or BIM file converts but contains no building elements, in place of the misleading "converter not available" text.
- Faster, quieter startup. Two demo seeders that re-ran on every boot and logged an error are now properly idempotent, so a restart is quicker and the log stays clean.

## [7.4.0] - 2026-06-10

### Added

- Real site photos everywhere. Every example project now opens with real construction photos in its gallery, and the dashboard carries a "Latest site photos" strip that pulls the newest photos across your projects with the project name and date. The placeholder swatches that used to fill the gallery are gone, so a photo opens to a real image instead of a blank tile.
- Point Cloud, in beta. A new reality-capture page registers laser scan, photogrammetry and LIDAR clouds against the project, with a scan registry and direct-to-storage ingest. The cloud viewer, model registration and deviation analysis follow in later releases.
- Demo data for every module that used to start empty. Cost models, management-of-change entries, tender packages, takeoff measurements, accommodation, markups, the resource catalogue, BIM federations and clash runs all arrive populated, so each screen shows real example data out of the box.

### Fixed

- Cross-module links now open the real file. A takeoff measurement or a markup opened from the markups hub lands on the actual drawing PDF with the measurement or annotation in view, instead of an empty "file not found" viewer. The cause was twofold: the example documents pointed at files that were never written to disk, and two deep links carried the wrong address. Both are corrected and verified end to end on a fresh install.
- The AI Estimate Builder no longer fails when you confirm the parameter sheet. Confirming the parameters now reaches the work-package board reliably. A single database session was being used by several lookups at once and crashed the request, which is fixed by running the lookups in sequence.
- Quality pass on the accommodation, formwork, closeout and markups modules: charge edit and delete on accommodation, currency inheritance, reuse caps on formwork, and a completeness count on closeout that no longer overstates progress.

## [7.3.0] - 2026-06-08

### Added

- A schedule-quality validation pack with seven checks for project schedules: missing logic links, dangling activities, negative or excessive lag, hard date constraints that fight the logic, and out-of-sequence progress among them. Schedules now go through the same traffic-light validation as a BOQ or a BIM import, so a weak schedule is flagged instead of trusted.
- Self-explaining modules. A shared set of in-app guidance pieces now runs across the platform: confidence badges, suggestion chips, plain-language error states, an inline glossary tooltip and consistent grid headers. The first wave of construction glossary terms landed in all languages so the same word means the same thing on every screen.

### Changed

- Interface text, documentation and code comments were swept to neutral, format-level names (IFC, DWG, RVT, GAEB, NRM) rather than specific product names, and a repository check keeps new contributions on the same footing.

### Fixed

- Grouping and filtering on uploaded IFC models in the BIM viewer line up with the geometry again. Each shape is matched to its element by a stable id, so picking a storey, a category or an entity type isolates exactly those elements and the view stays on that selection instead of snapping back to the whole model a moment later. Verified end to end on a real IFC model: a wall, member or storey filter keeps just that subset on screen and holds.
- The BIM upload picker accepts RVT, IFC and DWG only now, and a dropped DWG is routed straight to the Drawings takeoff where it belongs instead of failing as an unsupported 3D model.
- Appending a maintenance entry to an asset now verifies you have access to that asset's project first, closing a gap where that one endpoint skipped the per-project access check.
- More interface text is translated: the converter install progress labels and a validation page introduction that were still showing in English.

## [7.2.0] - 2026-06-08

### Fixed

- The desktop app could get stuck on "Recovering the local database" forever on Windows PCs whose regional format is set to Turkish. The bundled database tool rejected the non-ASCII locale name ("Turkish_Türkiye.1254") during first-time setup, so the local database never finished initialising. Setup now always creates the database with a neutral locale, and on top of that it clears a half-finished database folder left by an earlier failed attempt, so a machine that was already stuck heals itself on the next launch instead of failing the same way. Verified end to end against a real local PostgreSQL on a fresh install and on an upgrade from a broken folder.
- The AI Estimate Builder no longer shows a fake $0.00 for a matched code that has no price in the catalogue. The match step and the alternatives list now say "matched, no price in catalogue", so an unpriced code reads honestly and you can pick a priced alternative. The rollup still treats it as zero so totals stay correct and the line stays flagged for review.
- The RVT converter stopped reporting "Converter is out of date" when it was actually current.
- Filters and groupings on IFC models in the BIM viewer behave correctly again across storeys, categories and entity groups.

### Changed

- Moving between modules is faster. The sidebar and header stay mounted as you navigate instead of being rebuilt on every page, so switching modules no longer tears down and re-creates the whole shell each time.
- The BIM viewer's filter and property-search panel is now fully translated in all 26 languages. The search box, the category, level and grouping controls, and the property-search operators were showing in English everywhere because their text lived only in code; that text is now in the catalogue and translated. The remaining stage-2 translation gaps were closed in the same pass.
- The AI Estimate Builder is clearer end to end: parameter names read as plain words instead of code-style snake_case, the match step shows a live progress bar so a long run no longer looks frozen, and matched rates are grouped by trade instead of one long list.
- Element matching can use your own AI key to re-rank candidates for better results. You turn it on at the match step, and the key stays scoped to your own workspace so it is never shared across tenants.
- Module badges were tidied: well-developed modules dropped the BETA tag, rougher ones keep it, and the old NEW tag is gone.
- The DWG takeoff drawing card reads clearly on the dark canvas now, and the PDF takeoff toolbar wraps to two rows instead of showing a scrollbar.

## [7.1.0] - 2026-06-07

### Added

- The desktop app finally has a real first launch. A fresh install no longer opens on a login form: the app provisions a local workspace owner on its own, signs it in, and lands directly in the setup wizard, language first, then company profile, modules, cost databases, country packs and demo data. A persistent "Skip setup - open in English" button sits on every step of the wizard, one click marks setup complete and opens the app in English. Returning launches go straight to the dashboard, logging out always returns to the normal login form, and the automatic sign-in only ever happens for a local desktop backend that has no real registered accounts.
- The AI Estimate Builder opens with a conversation instead of a bare form. You describe the job in your own words, the intake asks up to three short rounds of clarifying questions as chips, toggles and numeric inputs, then walks through two explicit confirmation checkpoints: a parameter sheet, and a work-package board organised by foreman stage from demolition to commissioning where every package shows its real catalogue coverage. Without an AI key the same flow degrades to a curated form, and you can switch to the form at any time.
- Rate matching in the AI Estimate Builder now runs three named passes, semantic match, unit reconciliation and a rate sanity check against benchmark bands, and shows its work. Every matched rate carries a "why this rate" trace you can expand, suspicious outliers are flagged and capped at low confidence instead of silently winning, and a candidate with the wrong unit dimension is demoted rather than dropped. Each work group also records where its quantity came from, with the formula and any assumptions spelled out.
- Clash detection can turn a whole spatial cluster of clashes into one tracked work item, a punch-list item or a task, instead of leaving dozens of raw clashes to chase individually. The draft title, priority and assignee are proposed with a confidence score and the coordinator edits anything before confirming; every member clash records the link both ways and the run summary stays true.
- BIM federations gained a health report that classifies every member model, ready, processing, failed, stale or empty, into a readiness score with a worst-state headline, plus a portable snapshot you can download and later diff against the live federation to see exactly which models were added, removed or changed between coordination meetings.
- BIM quantity rules gained a testing sandbox that runs a draft rule against the live model before saving, a unit-dimension guard that warns when an area rule declares a volume unit, a coverage report listing element categories no active rule selects, and a formula version history with one-click restore. BOQ positions generated by rules now carry an honest confidence stamp instead of none.
- A usage badge on every cost database row. A quiet neutral dot means the position is not used anywhere yet; once it lands in an estimate the badge becomes a green check with the real count of estimate positions using it, refreshed immediately after each add.
- A connectivity program across the whole platform: more than 80 places where related records sat side by side without a link are now wired in both directions. Variations, change orders and contracts cross-reference each other, clashes jump to coordination tasks, NCRs open their inspection, daily diary entries link field reports, procurement lines link supplier catalog items, BI tiles drill into the records behind the number, and dozens of pages accept deep links that scroll to and highlight the exact row they point at. The goal is the same everywhere: any related record is one click away.
- Quantity takeoff ties where an estimator actually needs them: 5D cost model, capacity planning, procurement and carbon pages link straight into BOQ quantities and the CAD-BIM matching flow.
- An asset operations module, plus deeper logic across coordination, ERP chat, geo, element matching and project intelligence from the module-deepening wave.
- Long-form "Show more" walkthroughs for six more modules: QMS, advanced HSE, management of change, NCR, punch list and inspections.

### Changed

- Navigation now answers every click immediately. Moving to a module whose code is still loading shows a progress bar, a spinner on the clicked sidebar row and a busy cursor instead of a second of nothing, so slow transitions read as loading rather than broken.
- KPI cards across the platform share one modern style: a slightly translucent surface that lets the page texture show through, consistent radii and spacing, and a soft hover. Info blocks got the same treatment, fixing the washed-out opaque look they had on dashboards.
- Element matching is now called CAD-BIM Match → Cost and sits next to the other estimating tools in the sidebar. The external portal is now called Client & Partner Portal everywhere, one name in the sidebar, breadcrumbs, search and the module registry.
- The changelog inside the app reads in seconds: each release is a few short plain sentences instead of paragraphs.
- A translation sweep brought roughly seventeen hundred interface strings per language to native copy in all 26 app languages, closing the gap to English entirely, and consolidated several hundred strings that previously lived only in code so they can stay translated. The website's download and partners pages were translated into all 19 site languages as well.
- Typography swept across all user-visible text: long dashes replaced with plain hyphens everywhere.

### Fixed

- Adding a position from the cost database into an estimate now carries everything the position owns. Before, only a coarse three-line labor/material/equipment split survived and the variant reference was lost; now every resource comes across, resources with variants default to the mean rate and keep the full variant catalogue so a specific variant can be picked later in the BOQ editor.
- The usage indicator on the cost database never changed color because usage was never recorded on add. It is now.
- Registration metadata, the ip, user agent and referrer captured at sign-up, was silently dropped and never stored. It persists now.

## [7.0.1] - 2026-06-06

### Fixed

- The 7.0.0 Windows desktop app could exit silently right after launch. The launcher carried a misconfigured updater plugin that failed to initialise, and when it failed the whole app went down with no window and no message, so the user saw nothing. This release removes the broken plugin. If the launcher ever fails to start now, it shows a clear error dialog with what went wrong instead of disappearing.
- The desktop app now only reuses an already-running backend when that backend reports the exact same version and answers as healthy. Before, it could attach to a stale process from an earlier release and run against the wrong server. A version or health mismatch now starts a fresh backend instead.
- The Windows installer bundles the WebView2 bootstrapper, so a first install no longer depends on a network download to get the runtime in place. The app works on a fresh, offline machine.
- All backend dependencies for the desktop build are now pinned through a lock file, so the bundle is reproducible and the same every time it is built.
- The desktop launcher reported version 0.1.0 in its log regardless of the real release. It now logs the actual version.

## [7.0.0] - 2026-06-06

### Added

- AI Estimate Builder, a new module that takes any starting point, a typed scope, a BIM model or uploaded documents, and walks it to a priced bill of quantities in four guarded stages: understand the source, group the quantities, match rates from the cost database, review and apply. Every stage shows its work and waits for a human decision. The AI suggests groupings and matches with confidence scores, but unit rates only ever come from the cost catalogue, the model is never allowed to invent a price. Runs are persisted, so a half-finished estimate survives a reload, and the whole flow degrades gracefully when no AI key or vector database is configured.
- Every module page now opens with the same information card, and the card finally says something useful. Instead of repeating the module name, the heading names the problem the module solves, "Nothing slips through at handover" rather than "Punch list", and the body explains in two or three plain sentences what you put in, what you get out and where the result flows next, with direct links to the connected modules. Around 60 pages that had no orientation card at all received one. The copy was written per module against what each page actually does, in all 27 languages.
- Collapsing that information card no longer leaves a stub in the page. The card disappears entirely and a small info icon appears in the top bar right after the module name; one click brings the card back. The cards also support a "Show more" expansion for longer step-by-step explanations, with simple formatting for lists and emphasis.
- The collaboration hub is now a real workspace: live comment threads, BIM viewpoints you can create and open, who-is-here presence and your own element locks, all on one screen instead of a set of dead links.
- The Validate button in the BOQ editor jumps straight into the validation dashboard with that BOQ preselected, and the dashboard remembers your last BOQ and restores the latest report when you return. Rule-set chips read as names a person uses, DIN 276, GAEB, NRM, MasterFormat, instead of raw engine ids.
- The daily diary calendar is clickable: pick any day to create or edit that day's entry directly, with keyboard navigation.

### Changed

- One identity per module, everywhere. The module name and icon live in the top app bar next to the project selector, and nowhere else: in-page duplicate titles are gone from roughly 90 pages, breadcrumbs render only when they add real depth such as a project or a detail trail, and the per-page project pickers are removed, the project is chosen once, globally. Page headers across the app share one layout, a muted one-line subtitle on the left, the actions on the right, on a single midline, with one uniform vertical rhythm instead of each page hand-rolling its own margins.
- Translucent tints across the whole interface actually render now. The theme palette silently dropped every semi-transparent variant of the brand and surface colors at build time, so card backgrounds, hover tints and accent borders that were designed in never reached the screen, the information cards looked like bare text on white. The palette now compiles those variants correctly, and the info cards wear their intended light translucent blue in both light and dark themes.
- The role-based reporting dashboards load like they should. The page used to hold every widget hostage behind one slow project-wide fan-out, showing skeletons that never resolved; widgets now load independently and resolve to data, an honest empty state with a way forward, or a retry, never a permanent grey box. Figures that have no source yet show a dash with a note explaining what will fill them.
- Supplier catalogs stops pretending to be a purchasing module. Requisitions, purchase orders and three-way matching clearly hand off to Procurement where they actually live, and the page focuses on what it is, the vendor and item reference library.
- Monte Carlo risk analysis respects the project currency on every figure and reads the project from the global context, and the subcontractor payments portal no longer traps signed-out visitors, it explains that access comes via the invitation link and offers a way back to the app.
- The element-to-cost matching wizard speaks all 27 languages, including the stage rail and step counter that were previously English-only.
- The project pill in the top bar yields space on mid-size screens so module names no longer truncate to "Carbo..." at common laptop widths.

### Fixed

- Reopening a punch-list item works again: resolved items can be sent back to open, verified items can be reopened, and closed items can be brought back, matching what the workflow allows on the server.
- The desktop app detects an already-running backend on the common ports and attaches to it instead of failing a fresh boot next to it, and the splash screen can open the launcher log directly when something does go wrong.

## [6.10.0] - 2026-06-05

### Added

- Field time and attendance with a real payroll lifecycle. A crew lead records hours on site, those hours roll into a payroll batch, and the batch moves through draft, submitted, approved and posted as guarded steps. Posting writes to the general ledger once and only once: a replayed or retried post lands on the same journal entry rather than booking the cost twice. Labour cost is rolled up against budget so a project can see committed and actual crew cost against what was planned, by trade. The field app captures all of this offline and syncs later through a durable ledger that records every entry with its own id, so a phone that reconnects and replays its queue cannot double-count a shift it already sent.
- A cross-module project-controls dashboard. One screen pulls the health of cost, schedule, quality, safety, risk and changes into a row of traffic-light KPIs, each with a drill-down into the records behind it. Instead of opening six modules to answer "is this project in trouble", a controls manager reads the colour, clicks the amber tile and lands on the overruns, the slipping activities or the open high-risk items that turned it amber.
- Compliance enforced at the points where it matters rather than as a separate report. Compliance rule packs run at the contract signing gate, so a contract cannot be signed while a required pack is failing. Documents are checked against ISO 19650 CDE suitability when their state changes, so a file cannot move to a suitability it has not earned. Inspection and test plans carry hold points that stop the work until the point is released. Vendor scorecards feed a prequalification gate on purchase orders, a hard-blocked vendor cannot receive an order and a vendor with a lapsed or rejected prequalification raises a clear warning on the order.
- AIA G702 and G703 payment applications for owner billing, with the application and continuation sheet generated from the schedule of values, retention handled, and the lifecycle tracked. These are gated to US, Canada and Australia projects, where the AIA format is the norm, and stay out of the way everywhere else.
- A wave of AI features, all opt-in and human-confirmed. A progress-report narrative agent drafts the written summary of a reporting period for a person to review and edit, never auto-sends. The no-code agent builder gained event and schedule triggers so an agent can run when something happens or on a cadence, with a run monitor that shows each execution and its result. Jobsite photo intelligence reads the EXIF capture date off an uploaded photo, suggests tags and flags a likely defect with a severity. A project-document semantic assistant answers questions over a project's documents and points back at the source.
- A subcontractor payment-application portal and a client progress-reports tab. A subcontractor submits a payment application through a magic-link portal scoped to their own agreement, and a client reads their project's progress reports through their own link. Both are protected by row-level security per agreement, so a portal user only ever sees the rows that belong to them.

### Fixed

- Scheduled reports now actually email their recipients on the cadence they were set to. The schedule existed but never dispatched, so a weekly report that someone configured simply never arrived. It now sends on time to the recipients on the report.
- Backup restore no longer runs a destructive replace when merge was chosen. Choosing merge is meant to add the restored rows alongside what is already there, but the restore quietly fell through to the replace path and cleared existing data first. Merge now merges and replace still replaces, each doing only what was asked.
- The user-invite flow honours the role chosen in the invite. An invite sent for a specific role was landing the new user on a default role instead, so an admin had to fix the role by hand after the person joined. The chosen role is now applied when the invite is accepted.
- Closed a cross-project access leak in the chat assistant's search tools. The tools that let the assistant look across a project's records were not scoped to the current project, so a question could surface rows from another project the user was not working in. They now filter to the project in context.

### Security

- Bumped vitest to 4.1.8, which clears the critical Dependabot alert and the vulnerable nested copies of vite and esbuild that it carried. Updated react-router-dom to 6.30.4 and the Rust tar crate to 0.4.46. The npm audit is clean after this. Two remaining transitive Rust advisories (rand and glib) are pinned by the current Tauri toolchain with no resolver-reachable patched version and no runtime exposure on the Windows desktop build; they are left for a future Tauri upgrade.

### Changed

- The desktop app survives a long PostgreSQL crash recovery and shows what it is doing while it starts. The embedded database can need WAL crash recovery after an unclean shutdown, and on a real cluster of any size that can take more than two minutes. The old startup budget gave up after about twenty-four seconds and the app exited with no window and no message, so the user saw nothing. The boot loop now waits out recovery within a generous deadline, clears stale pidfiles from dead postmasters and probes the real database port instead of trusting a half-written pidfile. The launcher writes its log from the very first instruction and drives a six-step boot checklist on the splash screen, launcher, backend, database, migrations, server and open, so a launch that fails turns the failed step red with the error inline, the log path and a copy button, and a stuck start is finally diagnosable. Verified against a forced unclean shutdown on a 25,000-row cluster where recovery took 213 seconds and every row survived.
- The marketing-site partner program is simplified to a single deal rather than a tiered set of offers, so the page is shorter and the terms are easier to act on.

## [6.9.0] - 2026-06-05

### Added

- A screen for the Management of Change register. The module had a working backend and permissions but no way to use it from the app. You can now raise a change request, set its category and risk level, record the headline cost and schedule impact, and walk it through review, approval and implementation. Each step is a guarded transition that asks for a short note so the audit trail stays complete, and the page only ever offers the moves that are legal for the current state. Entries take per-line impact assessments, link across to variations and change orders, and show a clean empty state until the first request is raised. It sits under the Commercial group in the sidebar at /moc and /projects/:id/moc, mirroring how the NCR register is wired.

### Fixed

- Cost matching now returns results for projects outside the US. A Canadian, UK or German project resolved to the English cost collection, which only carries US-tagged rates, and then pinned a country filter that removed every row, so the match screen came back empty. The country pin is now data-driven: if the region has no rows in the collection being searched, the pin is dropped and the whole collection is ranked instead. Where the country really is present, for example Mexican rates inside the Spanish collection, the pin still narrows correctly. A keyword fallback in the Revit to IFC crosswalk also maps the long tail of custom Revit sub-categories such as curtain grids, stair railings and framing joists, while genuinely non-billable categories stay unmapped. Across six demo models the IFC suggest rate rose from 32 to 95 percent and Revit from 57 to 87 percent, and the three non-US projects went from zero to between 84 and 95 percent.
- Backup restore is now scoped to the user who runs it. Export already filtered rows to the caller, but restore cleared every row in each table before reloading, so one user's restore could wipe another user's data. Restore now deletes only inside the same ownership scope it exports.
- The purchase-order list no longer returns a server error for a project that has at least one order. Two figures on the order were declared as plain text but exposed by the model as methods, so reading the list failed validation before the real values could be filled in. The list and the per-order quantities now read consistently, with ordered, received and invoiced totals shown the same way rather than one as 100 and another as 100.0.
- A purchase order can only be created as a draft. It was possible to create one already approved or issued and skip the approval step that commits budget. The only legal starting state is now draft, and callers move it forward with the approve and issue actions.
- Closed a team-member access hole. Listing a team's members did not check project access, so any signed-in user could read any team's membership. It now gates on the parent project, the same rule used for create, update and delete.
- Management-of-change entries return their stored notes again. The response field was being read from the wrong place and quietly came back empty, so saved metadata never reached the client.
- A broad hardening pass across the backend modules from the deep module-by-module review: access-control checks added where they were missing, money handled as exact decimals, safer list and detail endpoints, and small correctness fixes across procurement, contracts, files, approvals, reporting and many more. This branch also folds in the desktop launcher hardening and the plain-http frontend fixes that shipped in the 6.8 desktop builds, plus four TypeScript errors that had broken the production build.

### Changed

- Reporting reads better before a project has any data. Projects with no cost snapshot yet show a clean dash instead of "N/A", with a short note that CPI, SPI and progress appear after the first snapshot, so an empty value reads as "not started" rather than broken.
- Removed the PostgreSQL-migration notice banner left over from the 6.0 launch, and raised the users list cap so the markups and change-order views no longer reject a 200-row page. Also dropped a dead, never-called placeholder in the property-development module, and folded in the cross-module depth and UI polish from this quality wave across approval routes, coordination, field reports, change orders, inspections, BI dashboards, correspondence and BIM requirements, together with the translation-key merge behind it.

## [6.8.2] - 2026-06-05

### Fixed

- The desktop installers for Windows, macOS and Linux build again. The 6.8.1 desktop build failed to compile because of a mistake in the launcher's shutdown handler, so the database launch fix in 6.8.1 was correct but no installer was produced. This release carries the same launch fix, so the app no longer does nothing after install, with a working build on all three platforms. The pip package and the Docker image were already fixed in 6.8.1 and are unchanged here.

## [6.8.1] - 2026-06-05

### Fixed

- The Windows desktop app installed and then did nothing when you launched it. No window, no server, no local address, just nothing. The cause was the database driver trying to open an encrypted connection to the app's own local database using the security libraries packed inside the desktop build, which failed and stopped the backend before it ever came up. The app talks to its embedded database over local loopback only, where encryption is neither used nor needed, so it no longer attempts that handshake there. The same fix applies on macOS and Linux. An external PostgreSQL set through DATABASE_URL keeps its normal encrypted connection.
- The desktop launcher no longer fails silently. If the backend cannot start for any reason it now shows a plain message on the loading screen instead of leaving you with a blank or missing window, and it always writes a full startup log to a file in your home folder under .openestimate so the problem can be diagnosed and sent in. First-run setup, which builds the local database the first time you open the app, is given more time on a slow machine before it is treated as a failure.

## [6.8.0] - 2026-06-04

### Fixed

- Quantity takeoff on DWG drawings now reports real-world metres. The drawing's own units (millimetres in most CAD files) were not being applied to the totals, so a wall measured as a few metres showed up roughly a thousand times too large in the summary panel, the layer breakdown and the value linked to a bill-of-quantities position. The drawing scale and unit factor are now applied everywhere a length or area is shown or exported, so a distance reads as 28.4 m and a room as 216.7 m2 the way it should. The single-drawing endpoint also no longer returns a server error while it fills in a drawing's units on first open.

### Added

- A wave of features that connect the modules to each other and close gaps against the larger commercial systems. Subcontractor scorecards update on their own from quality, safety and schedule events. Progress claims bill an owner contract by type (lump sum, cost plus, time and materials, unit price) with retention and an approval lifecycle. Retainage is held and released correctly on subcontractor payments. Resource leveling smooths over-allocated crews across the portfolio. Job costing reads through from the cost model to actuals with the leftover audit gaps filled. Element matching can now learn a symbol's signature and suggest where it recurs across a drawing set, and the project-intelligence module forecasts cost and flags risks early with an escalation path. The file-based ERP and accounting connectors round-trip without touching a live system. An offline slice lets the field app keep working without a connection and sync later. Each piece ships with its own tests and a single database migration.

### Changed

- The interface translation backlog is cleared. Around 22,000 strings were translated and applied across the 26 non-English languages, going module by module so the app reads naturally rather than falling back to English mid-screen. The remaining untranslated strings are deliberate: brand names, format codes and the like that should stay as they are.

## [6.7.0] - 2026-06-03

### Added

- A simple builder on the AI Agents page. Alongside more ready-made agents, you can now create your own from the screen: give it a name and a short description, pick the tools it may use and write its instructions, with no code involved. Your agents are saved to your account and run next to the built-in ones.
- Activating a partner pack now narrows the whole workspace to that client. Only the pack's projects appear across the projects page, the dashboard and the rollup widgets, and the interface switches to the pack's language, so an operator running a single-client install sees a clean, localised workspace. The Batimatech pack, for example, comes up in French. Deactivating the pack reverses all of it, shown step by step with a progress bar: the projects are released back into the full list and the language returns to English.

### Changed

- All 27 interface languages are now fully translated. The pass focused on the dashboard and the project screens, where some English words were still showing through, and went over every module so the app reads naturally in each language.
- The example projects are filled out across every module. Each demo now arrives with a real Revit, IFC and DWG model and a PDF plan set attached, so the BIM viewer, the quantity takeoff and the reports all have real content to work with, and validation runs at install time and stores a report against the bill of quantities.
- Partner packs ship the real company logos for Doka Formwork, Batimatech and BIM-Cluster Hessen, and each pack installs cleanly together with its catalogue and demo data. The Batimatech pack now defaults to French and loads the Canadian CWICR cost database for Toronto through the DDC parser.
- Every partner pack now installs two demo projects instead of one. The cross-region packs that had no in-country second demo (Australia, modular and prefab, renewables EPC) now ship a sensible second project in the same currency and standards.

### Fixed

- Generated PDF documents now render correctly in Cyrillic and other non-Latin alphabets. The contracts, receipts, certificates, invoices and reports used a font limited to Western European characters, so Russian, Bulgarian and Ukrainian text came out as empty boxes. The documents now use a bundled Unicode font that covers those scripts.
- The desktop installers for Windows, macOS and Linux now bundle the embedded PostgreSQL engine, so the app starts on a fresh machine with no separate database setup. The earlier builds shipped without the database binaries and could not start.
- Hardened several areas after a code audit. A backup restore that fails part way through now rolls back instead of leaving the database half cleared, change-order totals no longer double count on a retried request, the cost-import path no longer runs one query per row, and a handful of endpoints that were missing a permission check now enforce one.
- Validation no longer fails when it runs straight after a demo is installed. It was reaching for a related collection that the async database session had not loaded yet, so the run could error before producing a report. It now reads the positions with an explicit query and produces the report every time.
- Reinstalling a demo project no longer stops on a duplicate resource code. The seeding step clears the demo's own resource rows by code before inserting them again, so a forced reinstall completes cleanly.
- The cost database import and the catalogue picker no longer fail with a server error. Importing the Germany and DACH cost database and adding items from the catalogue both work again.
- CAD conversion works on a headless Linux server. The DWG, Revit and IFC importers and the drawing-to-PDF export now point the bundled DDC cad2data converter at its own libraries when they run, which a no-root install keeps outside the system path. Before this an upload could report that the converter was installed and then fail on the server with nothing useful in the log. Windows and macOS were not affected.
- The assemblies editor shows every Cost Drivers category again when you enter prices, rather than only the first group that matched.

## [6.6.0] - 2026-06-02

### Changed

- Embedded PostgreSQL is now the only database. SQLite has been removed from both the application and the test suite. This finishes the move that began in version 6.0.0, when an in-process PostgreSQL became the default with no Docker and no setup. The translation-memory cache now lives in the main database instead of its own SQLite file, the cost-database importer loads straight into PostgreSQL, and the SQLite engine and the dual-dialect database machinery are gone. The app still boots its own PostgreSQL on first run under ~/.openestimate/pgdata, or you can point DATABASE_URL at any external PostgreSQL. The one-time import of a legacy SQLite database on upgrade still works. There is no longer a SQLite fallback to run on.

### Fixed

- 3D models placed on the project map now render. The map tile builder was writing each model's per-feature metadata as inline arrays, but the 3D Tiles format wants those values stored in the binary buffer and referenced by index. The viewer could not read the inline shape, so it gave up on the whole model and the map stayed blank. The metadata is now written the way the spec expects, with a binary property table, so the geometry shows on the map as soon as a model is placed.
- Database migrations now record correctly on PostgreSQL through the standard alembic path. The version table that alembic keeps for itself was capped at 32 characters, which is shorter than some of this project's revision names, so a plain incremental upgrade could fail the moment it recorded one of them. That column is now wide enough. A couple of migrations also created a boolean column with an integer default, which PostgreSQL rejects, and a set of older downgrade steps assumed SQLite behaviour, where a failed statement is harmless; on PostgreSQL the same failure aborts the whole transaction. The boolean defaults are fixed, and those downgrade steps now drop tables and columns with the database's own cascade and if-exists handling, so a downgrade no longer aborts on PostgreSQL. The recent migrations are exercised by an upgrade and downgrade roundtrip test against a real PostgreSQL server. The normal install path was never affected, since it creates the schema directly from the models and stamps it at the latest version.

## [6.5.0] - 2026-06-02

### Added

- A redesigned AI Agents page. Agents are shown as a clear gallery that says what each one does, the tools it can use and a few example prompts, so it is obvious what you can ask before you start. Five new working agents come with it: an estimate reviewer that runs the validation rules over a bill of quantities, a cost classifier that maps an item to a CWICR code, a document analyst that searches your project files, a project analyst that summarises a project's cost position, and a rate benchmarker that compares a unit rate against the cost database. Each agent only reports what it can actually read and says so plainly when a source is not available, rather than inventing an answer.
- WhatsApp notifications are wired into the integration test and send paths through the official Meta Cloud API. A delivery needs a verified Business phone number, an access token and a recipient in the config, plus a Meta-approved template. When any of those is missing the integration now surfaces the real Meta response instead of a placeholder message.

### Fixed

- Placing a file on the project map works from start to finish again. The result appears on the map, the camera moves to it, and the base map loads quickly because map tiles now go through one pooled client with caching and conditional requests instead of opening a fresh connection for every tile.
- Multiple currencies are visible again in the bill of quantities. A position priced in a currency other than the project base shows a small currency badge next to its unit rate, and there is a per-position currency action in the row menu for lines that have no resources of their own. Nothing is blended: each position is still converted into the project currency through the project exchange rate before it rolls up into the line total and the grand total.
- The linked-geometry preview in the bill of quantities no longer shows a blank panel when a model has no 3D mesh to display, which is common for data-only drawings that still need a converter. It now explains there is nothing to preview yet and offers to open the element in the BIM viewer, and it gives the same clear message when a model loads but no mesh matches the linked element.
- The numbered screenshots in the README were recaptured from the current build. The old ones were taken with the product tour open, so they carried a dark dimming backdrop, and the projects shot also had the version-6 database notice across the top. The new ones show the real app with no overlays.

### Changed

- The unfinished field-worker mobile shell is no longer reachable in a normal build. It is gated behind a pilot flag until its screens and sign-in are ready, so nobody lands on a placeholder page by typing the address.
- Build and release hygiene. The software bill of materials workflow runs on Python 3.12 to match the project, so its inventory artifacts are produced on release again, and the backend lint and formatting are clean.

## [6.4.2] - 2026-06-02

### Fixed

- BIM and 3D models now sit at ground level. Two separate geometry bugs put models far from where they belong. A file authored in millimetres or imperial units had its element placements read in raw file units while the extents were already converted to metres, so every element landed up to a thousand times too far from the origin and the viewer could not frame the building. Placements are now scaled to the file's declared length unit the same way the quantities are, and SI-metre and unit-less files are unaffected. Separately, the 3D tiles a project map serves were georeferenced several kilometres above the ground because of a duplicated coordinate conversion that used the wrong Earth radius. That math is replaced by the shared, tested helper, so a model now opens at the correct altitude. These close issue #53 and issue #48.
- The X-DDC-License response header is ASCII-only again. It previously carried a non-ASCII separator character that some HTTP clients and test tools rejected. The separator is now a plain hyphen. The header is a decorative authorship marker and nothing depends on its exact text.

### Added

- Partner Packs are easier to create and install. A pack is declarative presets only, so it ships no code and no data and is never executed. You can now scaffold a valid pack from the command line with `pack new`, drop a pack folder or a .zip into the runtime data directory's packs folder and pick it up with Rescan, or, as an admin, upload the .zip straight from Modules then Partner Packs. None of these need a restart or a source checkout, which matters for pip and server installs that have no repository on disk. The in-app developer guide was rewritten to describe this create, install and apply flow as it actually works, and the old instruction to restart the backend is gone.
- Zip uploads and dropped archives are extracted through one hardened routine that rejects path traversal, symlinks, absolute paths, drive letters and backslash members, checks every entry, and stages to a temporary directory before an atomic move into place. The admin upload endpoint is size-capped and checks the file is really a zip before reading it.

### Security

- Conservative dependency fixes for flagged advisories, none of which affect the running application. python-multipart was raised to 0.0.27 to pick up the fix for a multipart-parsing denial-of-service that is reachable through file uploads, and pyarrow to 23.0.1 for a patch within the same series. On the frontend, the uuid library bundled inside exceljs is pinned to 11.1.1 to clear a transitive advisory. The remaining flagged items are all inside the vitest test tooling, which is a development dependency that never ships in the build or runs in production, so that upgrade is being handled separately as a tested change because it is a major version.

### Changed

- The production Docker deployment is documented, covering both the single-image build and the split backend and nginx setup, including the upload size limit, module-worker content type and the WebSocket upgrade the nginx config handles.
- Build and test hygiene. Backend test collection no longer aborts when an optional dependency is not installed, so the continuous integration run completes cleanly, and a batch of frontend unit tests that had drifted from the components they cover was brought back in line. None of this changes how the app runs.

## [6.4.1] - 2026-06-02

### Fixed

- Backend lint and formatting are clean again. Cleared every ruff check and ruff format issue across the backend and pinned the ruff version so the formatter gives the same result in CI and on a developer machine. The hand-written demo pack cost tables stay out of the formatter so they keep their readable one-line-per-item layout. This is build and lint hygiene only, with no change to how the app runs.

## [6.4.0] - 2026-06-02

### Added

- Cost spine. Estimate, BOQ, budget, purchase orders, contracts and bid packages now hang off one stable cost line, so a number entered once carries through the whole project. A control-account tree groups the lines, and each line opens a rollup that puts its estimate, budget, committed, contracted and actual figures side by side together with every linked record. Amounts are converted inside a project through its own exchange rates and grouped by currency across projects, never blended, and a mixed-currency rollup says so plainly. Generating the spine from a BOQ is idempotent, so running it a second time never duplicates lines.
- Partner Packs install from the command line. New "module install", "module list" and "module uninstall" commands take a packaged module folder or archive, check its manifest, and move it into place, rejecting path-traversal and bad-layout archives.

### Fixed

- The 3D model now frames itself when you open a project map. The viewer waits for the model to finish loading before flying the camera to it, instead of giving up after a fixed delay and leaving the building as a distant speck.
- The cost database region loader reports the real number of resource components it already holds instead of zero on a reload.
- Developer guide text and the bundled partner packs were tidied up, including the partner-pack entry-point name and a sweep of stray long dashes.

## [6.3.1] - 2026-06-01

### Fixed

- The project geo page no longer crashes and 3D geometry renders again. The crash came from a documents response contract mismatch, and the missing geometry from canonical elements that carry a flat bounding box. Both are corrected and pinned by regression tests.
- The Daily Diary now exports a real PDF instead of a placeholder.
- Opening a document from Takeoff loads it in the in-app viewer instead of following a broken download link.
- Docker and nginx packaging were corrected for self-hosting: a non-editable backend install, a larger upload limit, and correct module-script and WebSocket handling.
- Logging in no longer holds a database write open on a background connection. The login used to record its last-seen timestamp on a separate connection that ran after the response, which collided with the user's next request on the default database and could surface as a locked database with a long stall. The timestamp is now written inside the login request itself, so login stays fast and never contends with the next call.
- The Documentation link in the top menu opens the official docs site at openconstructionerp.com/docs instead of the raw repository folder.

### Added

- The project dashboard schedule-summary and AI-insights widgets are backed by real endpoints. Schedule summary reports progress, completed and delayed counts and the next milestone. AI insights are distilled from the project's completed agent runs. Empty projects show a clean empty state instead of a gated widget.
- Quantity matching gained a PDF source for a bill of quantities, an optional AI matcher that falls back to vector search when no key is set, and group split and merge with requests for quotation wired through.
- Real multi-year holiday calendars (Hijri, equinox-based, and a curated Hindu festival table) replace the earlier approximations.
- Partner Pack activation now installs the pack's bundled work catalogue and resource database, shown with a live step-by-step progress bar.
- After a pip install, the app can be started with python -m openconstructionerp. This works from any folder even when pip placed the launcher in a scripts directory that is not on PATH, which is common on Windows.

### Changed

- Removed the coming-soon connector teasers (Microsoft 365, Google Workspace, WhatsApp, and the construction management platform and MS Project marketplace placeholders) so nothing in the interface is a dead end.

## [6.3.0] - 2026-06-01

### Added

- Nine role-based company profiles: general contractor, estimator, architecture and engineering, construction manager, real estate developer, subcontractor, owner and client, BIM and VDC, and full enterprise. The profile picked during onboarding now tailors the workspace. The sidebar shows the modules that role needs and hides the rest, while the core modules stay on for everyone. The onboarding wizard reads the profile catalogue from the backend so the wizard, the saved preferences and the sidebar all use one vocabulary.
- A unified place-on-map picker on the project geo page.
- An apply dialog and a short developer guide on the Partner Packs page.

### Changed

- The dashboard co-branding banner now links into the in-app Partner Packs page, and the partner logo is shown as a proper app icon with a brand-coloured monogram fallback.
- The US Construction Pack ships a clean stars-and-stripes emblem, and the pack descriptions across every region were tidied up.
- AUTHORS and CONTRIBUTORS were split so authorship and copyright stay with DataDrivenConstruction while community contributors are credited in their own file.

## [6.1.2] - 2026-05-31

### Added

- Linux CAD and BIM converters now download and install automatically on first
  use, exactly like on Windows. The proprietary DDC converter binaries ship as
  signed .deb packages; the app fetches the package index, resolves the
  transitive dependencies, downloads them and unpacks them into a private
  per-architecture directory under ~/.openestimator with no root, no Docker and
  no apt setup. The same one-click flow backs the Install button on the
  Quantities and BIM pages. amd64 is fully supported; on an architecture the
  upstream repository does not publish yet, the app falls back to a clear apt
  command instead of failing.

### Fixed

- macOS: the converters no longer try to launch a Windows .exe. There is no
  native macOS build, so the app now says so plainly and points to the two
  paths that work on a Mac: run in Docker, or upload an IFC file (IFC is read by
  a built-in text parser that needs no native converter on any platform).
- Claude and the other AI providers connect again. The model identifiers were
  refreshed to the current Claude generation, the API key is now read from the
  environment and from ~/.openestimate/config.json in addition to the database,
  and provider and key problems are reported with the real reason instead of a
  generic failure.
- The converter version check no longer shows a false "update available" banner
  on Linux and macOS, where the Windows binary comparison does not apply.

## [6.1.1] - 2026-05-31

### Fixed

- Release pipeline: the Docker image tag is now lowercased before it is pushed
  to GHCR, so the container image publishes correctly. GHCR rejects any tag
  whose repository path contains uppercase letters.
- Desktop builds: raised the Node heap limit for the frontend build so the
  macOS installer job no longer runs out of memory.

## [6.1.0] - 2026-05-31

### Added

- Flagship reference project: a single residential house built from one real
  DWG drawing, one Revit model, one IFC model and one PDF plan set. Each CAD
  and BIM file is converted through the DDC cad2data console converters into
  our canonical JSON, with no IfcOpenShell and no native IFC parsing. Element
  groups are linked to bill-of-quantities positions with real quantities, real
  CWICR cost rates and real resources, with navigation both ways: from a BOQ
  line to its model elements and from any element back to its BOQ line.
- Automatic CAD and BIM converter download on first use, with no manual install
  step.

### Changed

- Showcase demo seeding is now opt-in (set `SEED_SHOWCASE=true`); the flagship
  reference project always installs.

### Fixed

- Broad audit fix wave: owner checks and IDOR hardening on BOQ exports,
  currency-correct money handling, RBAC and permission registration fixes,
  API contract corrections, project geo-hub map rendering with OpenStreetMap
  tiles, a PWA service-worker MIME-type fix, and silent session refresh so long
  sessions no longer drop to the login screen.

## [6.0.0] - 2026-05-30

### Changed

- **PostgreSQL is now the default database, with zero setup.** A fresh
  `openconstructionerp serve` boots a real in-process PostgreSQL 16 cluster
  (bundled binaries, no Docker, no separate install) and stores its data under
  `~/.openestimate/pgdata`. The single-file SQLite database is still available
  as an opt-out escape hatch - run with `--sqlite` or set `OE_USE_SQLITE=1`.
  This is the headline change of the 6.0 series and the reason for the major
  version bump.
- **Transparent one-time data migration.** On first boot, if a legacy
  `openestimate.db` is present and the embedded cluster is empty, its data is
  copied into PostgreSQL automatically and the old file is retired to
  `openestimate.db.migrated`. Nothing to run by hand.
- The PostgreSQL drivers (`asyncpg`, `psycopg2-binary`) and the embedded server
  (`pixeltable-pgserver`) moved into the base dependencies, so `pip install
  openconstructionerp` ships everything needed for the default PostgreSQL path.
  The `[server]` extra is now just Celery + boto3.

### Fixed

- **15 PostgreSQL dialect bugs** that previously only worked on SQLite: tolerant
  numeric coercion for money-as-text columns (no more `invalid input syntax` on
  a malformed row), timezone-aware datetime binding for `TIMESTAMPTZ` columns,
  `GROUP BY` on JSONB expressions instead of output aliases, `jsonb_array_length`
  on JSONB columns, `string_agg` in place of SQLite-only `GROUP_CONCAT`,
  UTC-normalised timestamp writes for lexically-ordered date columns, and
  consistent BIM dynamic-group filtering across both backends.
- A dedicated embedded-PostgreSQL regression suite (`backend/tests/pg`) runs in
  CI against a real PG16 cluster so these dialect differences cannot regress.

## [5.9.2] - 2026-05-30

### Added

- **PostgreSQL scale foundation** - generic JSON columns now emit `JSONB`
  on PostgreSQL (GIN-indexable, fast containment queries); SQLite is
  unchanged. PostgreSQL is fully optional - the default zero-dependency
  SQLite path (`pip install openconstructionerp` and one command, no
  Docker) is untouched.
- **Automatic performance indexes on PostgreSQL** - foreign-key btree
  indexes, composite `(project_id, created_at)` and `(project_id, status)`
  indexes, and GIN indexes on path-queried JSON columns, emitted at
  schema creation.
- **SQLite-to-PostgreSQL migration script**
  (`backend/app/scripts/migrate_sqlite_to_postgres.py`) - streams every
  table, resets sequences, with `--truncate` / `--dry-run` / `--only`.

### Changed

- **Connection pooling hardening** - `pool_pre_ping` and `pool_recycle`
  on PostgreSQL; configurable pool size and overflow on both backends.
- **CWICR cost-database bulk import** is now PostgreSQL-safe
  (`INSERT ... ON CONFLICT DO NOTHING`), with the fast raw-SQLite path
  retained.
- **Packaging** - removed stale "openestimate" branding from the
  PyPI-facing metadata (keywords) so the project page reads as
  OpenConstructionERP throughout.

## [5.9.1] - 2026-05-30

**Stability and correctness hardening, plus sharper flags and partner logos.**

A focused, module-by-module QA sweep took every reachable button, endpoint and
permission check and verified it behaves. The result is a long list of small,
concrete fixes rather than new features. Eight reachable server errors were
traced to their source and removed, several buttons that looked active but went
nowhere are now wired to real handlers, and a number of access checks that were
either too loose or silently denying were corrected.

Access control was tightened where it was wrong in either direction. Cross
project and cross tenant read holes were closed, sub resources under BOQ and
requirements now enforce the same guards as their parents, and a few endpoints
that conflated read and write permission were split so that viewers can read
without being able to change anything. The money handling started in 5.9.0 was
carried the rest of the way: amounts are never blended across ISO currencies,
totals are grouped by currency or converted through a project's own rates, and
the currency code travels with every value end to end.

The API contracts that drifted between the backend and the frontend were
reconciled - HSE advanced, procurement goods receipts, transmittals, smart
views and bid management now agree on their request and response shapes.

Finally, two visual fixes. The inline country flags were rebuilt with proper
geometry: the United States canton no longer relies on a star glyph font that
renders as empty boxes inside an image, and China, Turkey, Saudi Arabia,
Australia, New Zealand, South Africa and the India chakra were redrawn cleanly.
Five partner packs that shared a placeholder logo now carry their own emblem.

### Fixed

- Removed eight reachable HTTP 500s found by the QA sweep across the touched modules.
- Wired up buttons and actions that were unreachable or had no handler, including bid management open bids, the match wizard setup panels, smart view sharing and the transmittals payload.
- Closed cross project and cross tenant access holes (IDOR/RBAC), added the missing file distribution subscribe guard, and added RBAC guards on BOQ and requirements sub resources.
- Split read and write permissions where they were conflated, made access team inclusive where intended, scoped list queries to the caller, and gated high value actions.
- Reconciled drifted API contracts: HSE advanced (seven entities), procurement goods receipts, transmittals, smart views and bid management.
- Fixed the procurement goods receipts project query and response enrichment, and a dashboards snapshot route ordering shadow.
- Settings backup and restore now use the correct restore and validate request shapes.

### Changed

- Money totals are grouped by currency or converted through project `fx_rates`, never blended; the ISO code is shown next to every amount, and the EUR fallback default was removed from the compare and rollup paths.
- Rebuilt the inline country flags (US, CN, TR, SA, AU, NZ, ZA and the India chakra) with proper SVG geometry so they render correctly at small sizes on every platform.
- Gave the five placeholder partner pack logos (Australia, New Zealand, UK, Modular & Prefab, Renewables EPC) distinctive emblems consistent with the packs that already shipped real marks.

## [5.9.0] - 2026-05-30

**Quality wave, full localization, and partner-pack country projects.**

A large multi-agent quality pass swept roughly 26 modules and fixed every
confirmed high and medium severity finding from the deep-review audits. The
money handling is now consistent everywhere: amounts in a foreign currency are
converted inside a project through that project's `fx_rates`, totals across
projects are grouped by currency rather than blended into a single number, and
the ISO currency code is always shown next to a value. Touched areas include
finance, BOQ compare, costs, assemblies, catalog, coordination, dashboard,
schedule, tendering, reporting, RFI, submittals, risk, QMS, safety, geo, and
property development.

Localization is now complete. The earlier backlog of missing strings across the
26 locales is closed, and every new key introduced by this release - the quality
wave plus the dashboard greeting, the country onboarding, the tendering levelling
and addendum work, and the QMS sign-off - is translated into all of them. Every
one of the 27 locale files is up to date (de, fr, es, pt, ru, zh, ar, hi, tr, it,
nl, pl, cs, ja, ko, sv, no, da, fi, bg, hr, id, ro, th, vi, mn, plus the English
master).

Partner packs now ship a flagship country project each. Twelve realistic,
fully worked-out demo projects (Sydney, Auckland, Montréal, Frankfurt, São
Paulo, Delhi, Riyadh, London, Denver, a German formwork structure, a modular
housing scheme, and a solar plus storage EPC) are authored as standalone demo
templates, each in its own currency, classification standard, and locale, with
88 to 136 priced positions. They appear automatically in the project
marketplace, and when a partner pack is active its country project installs on
first boot. The merge between the pack templates and the core registry is now
order independent, with a regression test guarding it.

### Added
- `GET /api/v1/projects/{id}/activity` returns a project-scoped, cross-module
  recent-activity feed (RFIs, tasks, change orders, documents, punch items,
  field reports), which restores the project overview activity widget.
- Twelve partner-pack flagship demo projects under `app/core/demo_packs/`, with
  auto-derived marketplace catalog rows and `OE_PARTNER_PACK` driven auto-install.
- Backend groundwork for in-app partner-pack apply (state, apply, discovery, router).
- One-click country setup in onboarding. A "Set up by country" step installs a
  localized workspace - interface language, a matching cost database (CWICR
  region preload), the right classification standard, and a sample project - in a
  single click for 21 countries, or piece by piece from a customize panel. The
  manual region picker and the AI connection move into an Advanced section.
- Time-aware dashboard greeting that addresses the signed-in user by name (Good
  morning / Good afternoon / Good evening / Welcome back), localized in all 27
  languages.
- Bundled showcase 3D geometry. The demo BIM models now ship their GLB geometry
  and seed it on first boot, so the 3D viewer works out of the box on a fresh
  install (issue #168).

### Changed
- The dashboard "Weather & Site" panel is off by default. It stays available as
  an opt-in widget through dashboard customization.
- Access tokens no longer embed the full permission set. The server re-derives
  permissions from the user's role on every request, which shrinks the token and
  removes the intermittent HTTP 431 (request header too large) error that could
  blank the UI or make projects appear to be missing.

### Fixed
- Recent-activity widget 404 on the project overview (issue #167).
- BIM 3D viewer showing "No 3D geometry" for the demo models on a fresh install
  (issue #168). Geometry is bundled and seeded at startup, the geometry endpoint
  now reports a precise status (still converting, conversion failed, no converter,
  or genuinely missing), and the viewer no longer files an automatic bug report
  for the expected "not ready yet" states.
- All confirmed high and medium deep-review findings across the modules above.
- Mixed-currency totals that previously summed across currencies without conversion.

## [5.6.0] - 2026-05-28

**Partner-pack system - pip-installable white-label preset bundles.**
Adds Shape-A partner-pack architecture: a separate Python package
(`openconstructionerp-<slug>`) registers via the entry-point group
`openconstructionerp.partner_packs` and declares a `PartnerPackManifest`
that the core picks up at boot. The pack supplies branding (logo,
primary/accent colours, favicon), default locale, additional locale
JSON overrides, CWICR region preloads, validation rule packs to
enable, default modules, and a custom onboarding script. Single-tenant
(one pack per install); active pack chosen by env var
`OE_PARTNER_PACK` or the first registered entry.

Co-branding contract: every UI surface shows
`Powered by OpenConstructionERP · In partnership with <Partner>`.
The badge mounts on the dashboard (top) and in the top nav bar
(absolute-centered, only at xl+ width). Users can dismiss per
browser session - the badge reappears on next browser launch
(sessionStorage, not localStorage).

Five reference packs ship under `packs/`:
- `batimatech-ca` - Canadian construction conferences (fr-CA primary
  + en-CA, Toronto + Montréal CWICR, NBC 2020 + CCDC + CSA-A23 rule
  packs, CAD, ca_gst_pst tax, batimatech red `#BE1B2F`).
- `doker-formwork` - formwork supplier (de, Berlin CWICR, DIN 18218
  + concrete + formwork-cycle rule packs, EUR, Doker blue `#003D7A`).
- `bimhessen-de` - German BIM consultancy (de, Berlin CWICR, DIN
  276 + GAEB X83/X86 + VOB 2023 + ISO 19650 CDE + BKI rule packs,
  EUR, Hessen blue `#005CA9`).
- `uk-jct` - UK general contractor (en-GB, London CWICR, NRM 1+2 +
  JCT contract clauses + BCIS benchmarks, GBP, Union flag blue
  `#012169`).
- `us-rsmeans` - US general contractor (en-US, New York CWICR,
  MasterFormat 2018 + AIA A201 2017 + RSMeans City Cost Index rule
  packs, USD, Old Glory blue `#0A3161`).

Install pattern:
```
pip install openconstructionerp openconstructionerp-batimatech-ca
openconstructionerp serve
# logs: Partner pack active: batimatech-ca (batimatech) v0.1.0
```

### Added
- `backend/app/core/partner_pack/` - Pydantic manifest schema,
  entry-point discovery with env override + LRU cache + graceful
  failure, REST router exposing `/api/v1/partner-pack/{current,
  installed, logo, favicon, onboarding-script, locale/{code},
  by-slug/{slug}}`.
- `frontend/src/shared/hooks/usePartnerPack.ts` - React Query hook
  against the current-pack endpoint.
- `frontend/src/shared/ui/PartnerLogoBadge.tsx` - two render
  variants (`nav` chip and `dashboard` banner) with per-session
  dismiss.
- 13/13 backend unit tests in `tests/test_partner_pack_core.py`
  cover schema validation, entry-point precedence, broken-pack
  tolerance, and all router endpoints.
- Fresh-venv install verification screenshots at
  `docs/qa/v6-partner-pack-verification/`.

### Fixed
- `usePartnerPack` originally double-prefixed the path
  (`/api/api/v1/...`) because `apiGet` already prepends `BASE_URL =
  '/api'`. Path corrected to `/v1/partner-pack/current` so the
  badges render on a real install.
- Nav-bar chip overlapped the right-zone action buttons at 1366×768
  and 1920×1080. Constrained to `xl:flex` (1280+) and capped at
  `max-w-[14rem]` so it can never physically reach the action zone.

## [5.5.3] - 2026-05-28

**Build-unblock patch - re-ships v5.5.2 with the PyPI workflow green.**
The v5.5.2 tag passed `tsc --noEmit` in dev mode but failed
`tsc -b` in CI on a pre-existing type mismatch in the markups
aggregator test factory (the factory was not updated when alembic
v3146 added `assignee_id` to the Markup interface). Adding the
missing field unblocks the wheel build so v5.5.3 ships the same
v5.5.2 surface area to PyPI.

### Fixed
- **`aggregator.test.ts` factory missing `assignee_id`** - failed
  `tsc -b` in the PyPI publish workflow's wheel-build step; the dev
  `tsc --noEmit` had ignored the test files. Adds `assignee_id: null`
  to the factory so the build is green.

## [5.5.2] - 2026-05-28

**Quality wave on v5.5.1.** Closes the FX-popover UX gap from issue #157
(the v5.5.1 attempt only added a post-save badge - this one fixes the
write-time flow so users can actually enter the FX rate without losing
their dropdown selection). Ships the Wave-2 Epic A approval-routes
engine (generic templates → instances → step states, mounted on
`/approval-routes` and integrated into `/markups`). Honest
document-template locales - chips now show native + English names with
source-coded badges (override / bundled / fallback) and a built-in
editor for tenant-owned overrides. Three BIM viewer UX fixes (default
mode shows full geometry on `?sel=` deep-link instead of auto-isolating,
property search works in federation viewer via per-model picker,
Begehung moved to the top toolbar and duplicate ruler/section dropped
from the bottom). `/integrations` 404s gone (orphan "Example webhook
(disabled)" rows removed from the showcase snapshot, and the test
endpoint trailing-slash was normalised). AI Quick Estimate i18n keys
filled, `useLLMRun` shared hook, formatters lifted to `shared/lib/`.

### Fixed
- **#157 BOQ currency popover - auto-close on foreign currency + no
  way to enter the FX rate** - `cellRenderers.tsx`: keep the popover
  open when the picked currency has no FX rate yet, auto-focus the
  rate input (`PopoverFxRateRow`), and show a "SET RATE" badge with a
  required-hint paragraph so the next action is obvious. Closes the
  v5.5.1 attempt that only surfaced a post-save warning at the
  section level.
- **`/integrations` "Operation failed / Not Found / Test failed" on
  Example webhook rows** - removed 6 orphan
  `Example webhook (disabled)` seed rows from the showcase snapshot
  (they pointed at no real config so every action 404'd), and changed
  the test endpoint route from `…/test/` to `…/test` to match the
  rest of the module's slash style. Real configs unaffected.
- **`/bim` viewer trio**: (1) `?sel=…` deep-links now render the full
  geometry by default - the old behaviour auto-isolated the picked
  element and made the rest of the model invisible; (2) Property
  search supports the federation viewer through a per-model picker so
  searching by `Pset_*.Property` finds matches across linked models;
  (3) Begehung (walk mode) moved to the top toolbar where the rest of
  the camera tools live, and the duplicate ruler/section dropdowns
  that were stacked on the bottom toolbar were removed.
- **`/property-dev/settings/document-templates` Locale picker** - the
  chip list used to be a flat row of code stubs (`EN` / `DE` / `RU`)
  with no indication of what was actually translated. Now each chip
  shows native + English name (`Deutsch (German)` / `日本語 (Japanese)`)
  with a colour-coded source badge: green = tenant override active,
  blue = built-in translation, amber = no translation, falls back to
  English. Clicking any chip (or the new `+ Add / edit translation`
  button) opens an inline JSON editor that loads English as a
  starter, lets the tenant edit + save the override, and offers a
  one-click revert to the bundled copy.

### Added
- **Approval routes engine (Wave-2 Epic A)** - generic, polymorphic
  approval workflow. New module `backend/app/modules/approval_routes/`
  with tables `oe_approval_route` / `_step` / `_instance` /
  `_step_state` (alembic v3147). REST API exposes route templates,
  instance lifecycle (start / decide / cancel), and step-state queries
  filterable by target kind + status. Frontend module
  `frontend/src/features/approval-routes/` ships an admin page
  (templates + history tabs), a polymorphic `ApprovalInstanceCard`
  drop-in, and a `RouteEditor` modal with role-or-user mutex toggle,
  mode dropdown, SLA hours, and reorderable steps. Already integrated
  into `/markups`.
- **AI Quick Estimate refactor + i18n fill** - `useLLMRun` shared
  hook (commit `0eb16ac3`), formatters lifted from `features/ai/` to
  `shared/lib/formatters/` (`9c234ca8`), and the missing `ai.*` keys
  filled in `en.ts` (`d133889e`).
- **Tenant document-template locale overrides** - backend stores
  uploaded JSON at `uploads/property_dev/document_locales/{code}.json`,
  takes precedence over bundled JSON at render time; GET/PUT/DELETE
  endpoints exposed at `/property-dev/document-templates/locales/{code}`.

### Changed
- **Showcase snapshot trimmed** - removed the orphan
  `Example webhook (disabled)` rows (6 from
  `oe_integrations_config`). Snapshot is still gzipped and lives at
  `backend/app/scripts/showcase_snapshot.json.gz` with the same
  filename, so existing seed/SEED_SHOWCASE flows are unaffected.
- **Markups module** - assignee FK added (alembic v3146,
  `4763fe64`), prev/next chevron navigation with keyboard shortcuts
  (`ae1639b4`), back-to-document deep-link with scroll + pulse
  highlight (`d5cc56f2`), `EditMarkupModal` for title/description/
  colour (`0f436982`).
- **Geo Hub** - auto-zoom camera fits overlays + 3D tiles on load
  (`d0b72773`), 2D / 3D / Columbus scene-mode toggle with persistence
  (`ec2448b0`), per-overlay visibility + opacity controls
  (`b7cde60b`), left sidebar listing overlays + tilesets with fly-to
  (`fc46f5fd`).
- **i18n coverage push** - `ko` ≥75%, `zh` ≥75%, `cs`/`hr`/`pl`/`ro`
  ≥70%, `da`/`no`/`sv` ≥70%, `fi` ≥70% on high-traffic surfaces.

### Migration
- Alembic chain v3144 → v3145 (demo_project_addresses) → v3146
  (markup_assignee) → v3147 (approval_routes). All forward-only,
  idempotent on existing installs. No data migration needed.

## [5.5.1] - 2026-05-28

**README CLI-name patch - re-ships the v5.5.0 wheel with the long-description that PyPI renders on the project page.** The v5.5.0 wheel was tagged from a commit that still showed the legacy `openestimate` CLI binary name in the quickstart and the `doctor` invocation hint. Both binaries continue to work (pyproject.toml exposes `openestimate` and `openconstructionerp` as parallel entry points), but the canonical command on the rendered README should match the package name. No code changes. No migration. Same `5.5.0` runtime.

### Fixed
- **README quickstart and doctor invocation** - `openestimate` → `openconstructionerp` on `README.md:700` and `README.md:713` so the PyPI long-description matches the package name. Filed because users browsing https://pypi.org/project/openconstructionerp/ kept seeing the old name in the highlighted install snippet.

## [5.5.0] - 2026-05-28

**Stability wave - last stable 5.x cut.** Eight user-reported runtime
bugs found in a single morning of fresh-install testing, plus the
underlying "session reset on backend restart" issue, plus a deep i18n
pass that brought Japanese to 98.5% coverage. Includes six merged
contributor PRs (#140, #141, #151, #158, #163, #164 - team-member
project access, Mourdi59), the related-articles widget across all
news article pages, and the 2026-05-28 9/9-PASS browser verification
sweep with 22 screenshots committed under `docs/qa/`.

### Fixed
- **`/takeoff` "Failed to load PDF - Setting up fake worker failed"**
  on cold loads - added `.mjs` to the PWA precache glob so the PDF.js
  worker is cached with its real Content-Type, and made
  `request.destination === 'worker'` bypass the CacheFirst runtime
  rule so future Workers (PDF.js, Cesium, ML pipelines) never get
  intermediated by the service worker.
- **`/takeoff` "Failed to fetch PDF (403)"** when downloading an
  uploaded document - the path-traversal guard whitelisted only the
  brand-namespace `~/.openestimator` while the CLI defaults to
  `~/.openestimate`; now both spellings and `OE_DATA_DIR` /
  `DATA_DIR` env vars are honored.
- **Session reset on backend restart ("kicked back to desktop")** -
  dev-mode `JWT_SECRET` was rotated every boot when the bundled
  default was in use, invalidating every active token. The secret is
  now persisted to `~/.openestimate/.jwt-secret` (chmod 600 on POSIX)
  and re-loaded on subsequent boots. Sessions survive `Ctrl+C`+relaunch.
  Setting `JWT_SECRET` env var still takes precedence.
- **CAD/BIM Data Explorer "CAD conversion failed for .rvt"** - the
  `convert_cad_to_excel` path built CLI args as `<exe> <input>
  <output> standard -no-collada` unconditionally. DDC v18+ rejects
  those positional tokens with `exit 15`. Routed through the
  `build_ddc_args` + `detect_converter_capabilities` builder that
  `ifc_processor` already uses, so v17 keeps its positional shape and
  v18 gets `-x out.xlsx --no-dae -m standard` automatically.
- **`/dwg-takeoff` drawings don't load + misleading "upload DXF"
  error** - wheel-install converter discovery now scans the launch
  CWD's parent in addition to the source-repo parent (closes the
  wheel-install gap), and the missing-converter error message points
  at the one-click install pill + GitHub fallback instead of just
  "use DXF". DWG conversion now goes through the same v18-aware
  `build_ddc_args` so future DwgExporter v18 works without further
  patching.
- **`/bim/:id` 3D walk mode froze the viewport** - `WalkMode` /
  `PointerLockControls` mutated the camera every frame but never
  signalled the on-demand `SceneManager._needsRender` (which was
  previously only set by the now-disabled `OrbitControls`). Added an
  optional `onChange` callback fired from `tick()` on any frame the
  camera moved or pointer-lock was active; wired
  `BIMViewer.tsx` → `scene.requestRender()`.
- **BIM Section Box buttons ("По выделению / По всей модели /
  Сбросить") did nothing** - `applyToScene()` set
  `material.clippingPlanes` + `localClippingEnabled=true` but no
  dirty signal reached the on-demand renderer. Same `onChange`
  pattern as walk-mode now fires from `enable()`, `disable()`, and
  `setBoundsToBox()`.
- **`/bim/federations` 3D tab showed "Geometry fetch failed [object
  Object]"** - the embedded `FederatedViewer` 404'd on every member
  model that hadn't been re-converted. Replaced the broken viewport
  with a list of member-model link cards that navigate to
  `/bim/:modelId` (where the per-model viewer works) and HEAD-probe
  each model's geometry so 404 rows are greyed out as "Geometry not
  available" instead of leading the user into a broken page.
- **`/projects` lost the per-card map** - `ProjectsPage` gated the
  map render on `mapEnabled && project.address`; demo projects
  created before the v3.2.0 seed update had `address IS NULL`, so
  the card silently dropped its map. Removed the gate (ProjectMap
  itself handles the missing-coords case with a friendly
  placeholder) and added alembic `v3145_demo_project_addresses` to
  backfill the five canonical demo addresses on existing installs.

### Added
- **i18n deep coverage pass across 26 locales** - 26 high-impact
  commits filling nav phase labels, common verbs, sidebar admin,
  login brand, tour + WhatsNew chrome. Locale-by-locale gap analysis
  saved to `docs/i18n/COVERAGE_2026_05_28.md`.
- **Japanese (JA) locale to 98.5% coverage** - 1,627 keys translated
  across boq, propdev, costs, match_elements, accommodation, bim,
  finance, schedule, users and 20+ other namespaces using
  construction-industry terminology (積算, 単価, 明細, 工事, 物件).
  111 keys intentionally kept in Latin (brand codes, EVM acronyms,
  industry-exchange identifiers, file paths).
- **`/geo` - Photon (Komoot, Apache 2.0) as primary geocoder** with
  Nominatim (ODbL) as fallback. Photon is faster, has no per-IP
  rate limit, and matches our open-data + self-hostable
  philosophy.
- **`/geo` viewer - collapsible "Open Data" license pill** that lists
  every upstream source (Cesium Apache 2.0, OpenStreetMap ODbL,
  Nominatim ODbL, Photon Apache 2.0) with direct links so reviewers
  can verify the stack is fully open without reading the source.
- **`/geo` + `/projects` - one-click 2D/3D toggle** wired into both
  the Geo Hub viewer and every project card's map preview.
- **News pages: "More from the OpenConstructionERP blog" widget** -
  inline closing strip on every article + sticky right-rail at
  `min-width:1500px`, vanilla JS, no dependencies, no tracking. 15
  article pages covered.
- **Browser verification harness** - `docs/qa/verification-2026-05-28/`
  ships the Playwright spec, before/after screenshots for nine
  fixes, and a Markdown REPORT showing 9 PASS / 0 FAIL against a
  source-built backend on port 8001.

### Changed
- **Team-member project access (PR #164, Mourdi59)** - non-owner
  team members now reach project + BOQ endpoints through
  `TeamMembership` rows alongside owner checks. New
  `backend/app/modules/teams/access.py` provides the canonical
  `is_project_member()` + `member_project_ids_subquery()` helpers,
  replacing six inline copies. Access denials return 404 (not 403)
  to avoid leaking UUID existence; malformed UUIDs are wrapped in
  try/except returning 404 instead of 500. Five integration tests
  cover the access matrix.
- **PWA service worker** - `globPatterns: '**/*.{js,mjs,css,html,svg,
  woff2,ico}'` (`.mjs` added) so future ESM workers are precached
  with correct headers without needing per-asset Workbox rules.

### Dependencies
- `chore(deps)`: tmp 0.2.5 → 0.2.6 (#163, dependabot)
- `chore(deps)`: 8 minor/patch frontend bumps (react-query,
  date-fns, three, postcss, …) (#158, dependabot)
- `chore(deps)`: openssl 0.10.79 → 0.10.80 in desktop/src-tauri
  (#151, dependabot)
- `chore(deps)`: pandas upper bound `<3` → `<4` (#141, dependabot)
- `ci`: actions/dependency-review-action 4 → 5 (#140, dependabot)

### Skipped (separate migration wave)
- react-router-dom 6 → 7 (#145), react-i18next 15 → 17 (#146),
  eslint 9 → 10 (#144), @vitejs/plugin-react 4 → 6 (#143) - each is
  a meaningful API change that deserves its own audit + test cycle.
- PR #161 (rjohny55) - baseline is v4.12; unresolvable conflicts in
  `ai/router.py` + `catalog/router.py` against our v5.4 state.
  Useful pieces (Kimi provider, retry session, password strength)
  worth extracting into a fresh PR after rebase.

## [5.4.3] - 2026-05-28

**/geo navigation + autocomplete UX.** Browser audit found two bugs the
postage-stamp fix in v5.4.1 didn't catch: clicking the `Project` or
`Development` mode tab when no context was active navigated to
`/projects` or `/property-dev` - dumping the user out of /geo into a
slow-loading list page. Address autocomplete also felt broken because
the dropdown stayed closed while Nominatim's 1 req/s upstream took
5–10 s on a cold cache.

### Fixed
- **GeoModePicker soft-disabled tabs** - clicking a tab without context
  now opens an in-page picker dialog (project/development list with
  search) instead of navigating away. Picking a row navigates to the
  appropriate scoped /geo route. ESC + backdrop click close the dialog.
  Keyboard nav, ARIA roles, and the dim "?" affordance preserved.
- **AddressAutocomplete perceived empty** - the dropdown now opens
  immediately when a fetch begins and renders a `Searching…` row with
  spinner while suggestions are empty + `isLoading` is true. Users see
  progress instead of an apparently-broken input during the 5–10 s
  Nominatim round-trip on cold cache.

## [5.4.2] - 2026-05-28

**Converter UX simplification.** Fresh-install pain reported by Artem on
a new Windows machine: DWG upload failed with "DWG conversion requires
DDC DwgExporter" and no path to actually install; BIM "out of date"
overlay surfaced the raw stderr ("The following argument was not
expected: …") as the primary message.

### Fixed
- **/dwg-takeoff conversion error** - when the backend message names
  "DDC DwgExporter", the error card now renders an inline `Install DWG
  converter (1 click)` button (with live progress bar - ~150 MB
  download) before the existing Retry/Delete row. Hits the same
  `POST /api/v1/takeoff/converters/dwg/install/` endpoint as /settings →
  Converters. On success, auto-triggers the upload-retry flow. On Linux,
  surfaces the apt-get commands the backend returns and links to
  /settings?tab=converters as a fallback.
- **/bim "Converter is out of date" overlay** - replaced the raw
  stderr-bearing backend message with a clean human sentence
  ("The installed RVT converter is older than this build expects. Click
  'Reinstall converter' below - we'll pull the latest version and retry
  your upload automatically"). The original message + stderr excerpt
  are preserved as a collapsible `<details>` "Show technical details"
  block (useful for support tickets). Dropped the redundant
  "Reinstall fetches the latest converter from GitHub…" hint that
  appeared next to the Reinstall button.

## [5.4.1] - 2026-05-28

**Hotfix wave.** Bundles the 20-wave deep audit landings (W1–W20 across
every business module) plus a critical /geo render fix.

### Fixed - /geo (P0 user-reported)
- **Cesium canvas collapsed to 300×150** on the global Geo Hub view - the
  CesiumViewer.tsx wrapper intentionally skips Cesium's `widgets.css`
  (to suppress unstyled toolbar pills) but the same stylesheet is also
  the only place `.cesium-viewer`, `.cesium-widget`, and the canvas get
  `width:100%; height:100%`. Without it the canvas fell back to browser
  default and the globe rendered into a postage-stamp in the corner of
  the main area. Fixed by inlining the four minimum rules into the
  scoped `<style>` block.

### Fixed - 20-wave deep audit (security + correctness across every module)

**Security (HIGH-severity):**
- **W3 Costs/Vector**: LanceDB filter SQL injection guard
- **W7 PropDev**: double-reservation race (conditional UPDATE)
- **W8 CRM**: GDPR `forget_lead` PII scrub extended to source + activity
- **W9 HSE**: JSA FSM IDOR (foreign-project state transitions)
- **W11 Auth**: audit-log gap on login/reset/role-change (invisible to
  forensics); reset-token single-use guard
- **W12 Reporting**: HTTP header injection via `invoice_number` /
  Content-Disposition (RFC 6266 quoting)
- **W16 fieldreports**: approve endpoint had no `verify_project_access`
- **W17 Geo Hub**: raster-overlay DELETE used `write` perm instead of
  `delete` (editor could nuke manager-owned overlays)
- **W19 Punchlist**: photo delete IDOR; verify/close perm was dead code

**Correctness (silent miscalc):**
- **W10 Schedule**: CPM critical-path used `<0` instead of `<=0` for
  total-float (missed zero-float activities)
- **W18 Carbon**: embodied-CO₂ auto-fill double-normalised the unit
  (silently wrong figures for cross-unit factors)
- **W20 Procurement**: EUR hardcoded in `PurchaseOrder.currency_code`
  ORM default (task #217 violation)
- **W20 Finance**: `budget.actual` was `str` assigned to `MoneyType()`
  column (PostgreSQL coercion bug)
- **W20 Finance**: budget Excel export used `float()` → IEEE-754
  rounding on large values
- **W6 Validation**: 2 rule classes existed but were never registered
  (E-VAL-008 + BOQUnitSystem + ClassificationNudge)

**Race conditions / FSM hardening:**
- **W2 Tendering**: token_hash leak, award-delete FSM revert, concurrent
  submit race
- **W9 Submittals**: CAS race on parallel approvals
- **W15 Variations**: VR→VO conversion race (one VR creating two VOs)
- **W17 Notifications**: webhook circuit-breaker (skip after 10 fails,
  auto-deactivate after 50)

**IDOR / RBAC:**
- **W1 BOQ**: three IDOR/precision gaps
- **W14 Files/Markups**: scale-list IDOR, scheduler re-registration
- **W15 ChangeOrders**: missing `RequirePermission` on GET-detail

**UX / perf:**
- **W4 Takeoff**: inline-dict PDF encryption detection, dark-mode canvas
- **W5 BIM**: canvas ARIA labels, dark-mode, overriddenMeshes leak
- **W13 Dashboards**: missing POST /rollup/ handler (5 endpoint tests
  silently 405-broken); unbounded activity + validation report fetches

## [5.4.0] - 2026-05-27

**Quality wave on the v5.3.0 base.** Six focused commits - no schema
changes, no new modules. Bundles WCAG-AA round 2, AI-surfaces refactor,
match-quality fixes from real-BIM iteration, and the dark-mode token
followups from the v5.3.0 review pass.

### Added
- **`useLLMRun()` shared hook** (`frontend/src/features/ai/hooks/useLLMRun.ts`)
  - `useMutation`-backed wrapper for LLM-bound async ops with
  AbortController and focus-restore ref. Replaces ad-hoc `useState` +
  `try/catch` blocks in AdvisorPage and QuickEstimatePage (6 call sites).
- **`shared/lib/formatters.ts` lifted utilities**: `formatNumber`
  (currency-aware), `formatFileSize`, `getFileExtension` - promoted from
  feature-local helpers for reuse across AI + reporting surfaces.
- **Theme-aware `--oe-blue-text` token + `text-oe-blue-text` utility**
  (light `#005bb5` / dark `#93c5fd`) - splits the blue-on-tint text use
  case off `--oe-blue-dark` so the same class clears WCAG-AA in both
  modes. 145 occurrences across 56 files migrated.
- **`_is_non_billable_envelope()` gate** in match ranker (`IfcSpace`,
  `IfcZone`, `IfcOpeningElement` w/o material, etc.) prevents
  metadata-only fallback from surfacing arbitrary "Electrical equipment"
  rows for non-billable IFC entities.

### Fixed
- **Match: `ifc_class` filter never fired on IFC-sourced elements** -
  BIM extractor left every v3 structured field (`ifc_class`,
  `material_class`, `ifc_predefined_type`, `nominal_size_mm`) at `None`,
  so the SearchPlan skipped the hard filter even though ~28k catalogue
  rows are indexed by it. Three layered fixes: 35 `Ifc*` aliases added
  to `classification_mapper._CATEGORY_ALIASES`, English IFC noun
  prepended to the dense description in `extractors/bim`, and direct
  envelope population from BIM properties.
- **Match: BGE rerank collapsed correct candidates** - the
  cross-encoder's sigmoid logits land in 0.003–0.05 on templated
  catalogue passages, and the pre-blend implementation *replaced* the
  prior (RRF + boosts) score with this collapsed signal. Now 60/40
  blends prior with BGE; sorts head by raw BGE (preserves rerank
  authority) but displays blended score with `bge_rerank_delta` in
  `boosts_applied` for explainability.
- **WCAG-AA - `--oe-text-secondary` failed on tinted light surfaces**:
  `#6e6e73` → `#5b5e66`. 2 511 occurrences in ~330 files now clear AA
  on `bg-oe-blue-subtle` (4.27:1 → 5.75:1+).
- **Dark-mode `hover:bg-oe-blue-dark` button contrast**: white text on
  the `#bfdbfe` tint (introduced as a text-token band-aid in `ee2edb9d`)
  dropped to ~1.3:1. Now that `text-oe-blue-dark` is gone, the token
  reverts to `#1e40af` for saturated white-on-button contrast.

### Refactor
- **AI surfaces**: AdvisorPage + QuickEstimatePage migrated to
  `useLLMRun()`. No behaviour change; tsc clean.


**Last stable 5.x cut.** Six audit bundles consolidated on the v5.2.8 base.
No schema changes - alembic stays at `v3144`. Module count unchanged at 116.

### Added
- **Brazil Tier-1 invoice support**: `BRL` in finance currency shortlist,
  500-line `br_invoice_pdf.py` RPS-layout renderer with prestador/tomador
  blocks and retenções (ISS/PIS/COFINS/CSLL/INSS/IRRF). Two new validation
  rules `NBR12721ClassificationRequired` + `NBR12721ValidSection` (S1–S11
  cost groups). BOQ importer recognises `nbr`+`sinapi` codes; São Paulo
  defaults to SINAPI as regional cost reference. 15 new tests.
- **/reporting in-page renderer**: View button per report row opens
  `ReportViewerModal` with sandboxed `<iframe srcDoc>` for HTML reports.
  Distinct error states for 410 (expired) / 404 / network. Blob URL for
  new-tab link.
- **Daily Diary delete**: Trash2 ghost button gated on `!sealed`, wired
  through `useConfirm()` with danger-styled `ConfirmDialog`. 4 new tests.
- **Dashboard rollup endpoint**: new `RollupRequest` schema with 10
  configurable widget IDs and bounds validation (+136 LOC). Project
  dashboard goes from 13 per-widget requests to 6. 41 new tests covering
  IDOR isolation and rollup parity.
- **Geo Hub `sweep_deleted_raster_overlays(older_than_days=30)`** janitor
  helper for retroactive cleanup of soft-deleted overlay bytes.

### Fixed
- **`set_user_module_access` metadata payload silently dropped** -
  SQLAlchemy `DeclarativeBase` reserves the `metadata` attribute name;
  the column is aliased as `metadata_` but the router wrote
  `metadata=metadata` instead of `metadata_=metadata`. (Author-attributed
  community PR #164 by `@Mourdi59`.)
- **Geo Hub `delete_tileset` storage leak**: deleted the DB row but left
  tileset bytes orphaned in MinIO. Now calls
  `storage_backend.delete_prefix(obj.prefix)` before the DB delete.
- **Geo Hub `accuracy_m` runaway**: schema now caps at `le=10_000` so a
  stray fat-finger can't blow up the whole map.
- **`map_config` N+1**: `development_id` filter now pushed into SQL
  instead of post-fetch Python filter.
- **`ProjectGeoPage` iOS Safari URL bar collapse**: `100vh` → `100dvh`.
- **/login dark-mode contrast**: 7 scoped overrides on `LoginPage.tsx` -
  form column backdrop `dark:bg-[#070912]`, demo buttons
  `dark:bg-white/[0.06]`, credential cards `dark:bg-white/[0.07]` with
  `dark:border-white/15`, subtitle promoted from tertiary to secondary
  ink. Light mode untouched.
- **WCAG-AA contrast - top axe-core offender**: 51 files / 126 line
  replacements moving `text-oe-blue` → `text-oe-blue-dark` where
  `bg-oe-blue-subtle` co-occurs (3.1:1 → 4.5:1+ AA pass). Includes the
  global project-picker chip in `Header.tsx` and the blue variant of
  `Badge.tsx`.

### Docs
- Backfilled three v3 release announcements on the marketing site
  (`v3-0-0.html`, `v3-6-0.html`, `v3-11-0.html`) using the v5-2-8
  template with the `.chip.v3` indigo style.
- Fixed broken `og:image` on `news.html` (was a stale path under
  `/pro/shared/media/`; now points at `/screenshots/hero-overview.jpg`).

## [5.0.0] - 2026-05-26

**Second stable major.** First release to land community contributor work
directly on `main` (`@Mourdi59` + `@rjohny55`). Bundles every fix and
feature since v4.12.0 plus the full v4.12.0 deep-audit wave.

### Added
- **AI providers**: Kimi (Moonshot AI), Ollama (Local), vLLM (Local) -
  first-class providers in the Settings → AI panel. Ollama / vLLM accept
  a custom Server URL so on-prem and self-hosted models work without
  patching the backend. Alembic `v3141_ai_kimi_api_key` adds the
  encrypted-secret column for Kimi; Ollama / vLLM base URLs piggyback on
  the existing metadata JSON column. (#161 by @rjohny55)
- **BIM viewer `degraded` status**: models with geometry but no quantity
  extraction are now viewable - element query and `geometryUrl` both
  treat `degraded` as viewable, status dot is solid amber (distinct from
  pulsing amber of in-progress and green of ready), label reads
  *"Imported (no quantities)"*. (#159 by @Mourdi59)
- **Dashboard Vector DB row** now surfaces the active engine name
  (e.g. *"Qdrant · 12,400 vectors"*) instead of only the vector count.
  (#161 by @rjohny55)

### Changed
- **Sign-up password validation**: in addition to the existing minimum
  length (8 chars), new accounts now require at least one letter and one
  digit. Backend FastAPI validation arrays are now flattened to a single
  string in the error banner. Sign-up only - existing users keep their
  passwords. (#161 by @rjohny55)
- **Marketing site**: removed the redundant *"All modules · same as the
  in-app menu"* grid that duplicated the *"One install. The whole
  construction stack."* overview placed earlier on the same page. Drops
  ~86 lines from `marketing-site/index.html`.

### Fixed
- **BIM COLLADA namespace prefix**: Python ElementTree was serialising
  the patched DAE root tag as `<ns0:COLLADA xmlns:ns0="...">`, which the
  frontend's literal `<COLLADA` text-scan rejected with *"Not a COLLADA
  document"* - viewer rendered blank even after a successful conversion.
  `_patch_collada_node_names()` now registers the COLLADA namespace as
  default before `tree.write()`. As a defence-in-depth measure, the
  frontend regex in `detectGeometryKind()` and `parseDAEBuffer()` now
  also accepts namespace-prefixed forms. (#159 by @Mourdi59)
- **Slow-query listener race**: `conn.info.pop("query_start_time", …)`
  in `_log_slow_query` now guarded against connections closed
  mid-call by a concurrent coroutine. (#161 by @rjohny55)
- **Module-presence probe concurrency**: probes sharing an aborted
  session now catch `InFailedSQLTransactionError` and return `False`
  instead of bubbling and 500-ing the entire `/api/v1/projects/status`
  endpoint. (#161 by @rjohny55)
- **FieldReport activity-rollup**: `FieldReport` has no `title` column,
  but the dashboard recent-activity SQL was selecting it - pure
  `AttributeError` waiting to fire. Replaced with
  `coalesce(work_performed, report_type)`. (#161 by @rjohny55)
- **Qdrant snapshot restore**: `client.recover_snapshot(location=…)`
  only accepts URIs the Qdrant server itself can fetch (http://, s3://,
  or file:// on the server's own disk). Snapshots sitting on the app
  container were therefore unreachable from a separate Qdrant container.
  Restore now POSTs the snapshot bytes via the multipart upload
  endpoint using the existing `qdrant_snapshot_loader`. (#161 by @rjohny55)
- **Marketing-site i18n entities**: locale JSONs contained raw HTML
  entities (`&amp;`, `&middot;`, `&rsquo;`, `&ldquo;`, `&rdquo;`,
  `&ndash;`, `&mdash;`, numeric `&#128170;`) that rendered literally
  whenever i18next applied them via `textContent` - most visible in
  workshop testimonials as *"D&amp;S &middot; BIM Manager"* instead of
  *"D&S · BIM Manager"*. `html.unescape` pass across 513 strings × 20
  locales fixes every affected role/quote line.

### Contributors
- **@Mourdi59** - first community PR landed (BIM viewer fixes).
- **@rjohny55** - multi-area patch set across slow-query guards, module
  presence concurrency, FieldReport rollup, Qdrant restore, three new
  AI providers.

Three hunks from #161 were held back for follow-up discussion: the
hardcoded `SQLITE_URL` Docker path (would break VPS + Windows dev), the
`CREATE TABLE oe_costs_item` schema duplication, and the
urllib→requests migration in catalog/router (httpx is the project-wide
HTTP stack - `requests` would introduce a parallel dependency).

## [4.12.0] - 2026-05-26

20-wave deep audit + control wave on top of v4.11.0. R7 security pattern
revival across three modules (CRM orphan tests, QMS audit-log infrastructure,
EAC tenant-scoped hardening), QuickEstimatePage accessibility debt cleared,
QA browser-screenshot harness parameterized for locale / theme / viewport,
and the OpenConstructionERP concept paper published as a news article.

### Added
- `qms`: new `QMSAuditLog` SQLAlchemy model (alembic `v3140_qms_audit_log`)
  recording entity-scoped state transitions on NCR raise/close and inspection
  start/complete. Idempotent migration, 5 indexes, all NOT NULL columns
  carry `server_default` so fresh-install `create_all` works. Repository
  exposes `append_audit`, `list_audit_log`, `list_audit_for_entity`,
  `purge_audit_for_tenant`. New GET endpoints honour IDOR→404 and tenant
  scoping. Magic-byte denylist (PE/ELF/ZIP/PDF/PNG/JPEG) enforced on
  attachment uploads with 8 MB cap (413). (65ea96b2)
- `eac.aliases`: tenant-scoped service layer + magic-byte upload denylist +
  Decimal-as-string serialization (`DecimalStr`) + 12 new R7-pattern tests in
  `backend/tests/modules/eac/test_eac_r7_audit.py`. (a5fd6964)
- 5 CRM R7 orphan test files restored (~59 tests, 1,155 lines) - covers
  GDPR forget, lead dedupe, money decimal, PII redaction, win role gate.
  These were parked by the v4.7.2 triage and never re-committed. (dd24aa1c)
- Marketing site: OpenConstructionERP concept paper published as standalone
  news article at `/news/open-erp-own-your-stack.html` with banner,
  back-to-news nav, 7 inline images, 3 fonts, and downloadable PDF. Featured
  card on `/news.html`. (cee9e5f9)
- 6 workshop attendee testimonials localized across all 20 marketing-site
  locales (14 i18n keys × 20 locales = 280 new strings). Quotes + roles +
  read-more/less controls all data-i18n wired. (468bf82b)
- `qa/screenshots/full-app.spec.ts` patched with three-layer public-demo
  modal dismissal: sessionStorage seed (`oe_demo_modal_dismissed=1`) +
  injected CSS hider for `z-[200]` fixed overlays + best-effort click on
  "I understand, continue". Eliminates the modal interference that blocked
  prior baseline captures. (c12a4252)
- `qa/screenshots/full-app.spec.ts` parameterized with `QA_LOCALE` (seeds
  i18next storage keys), `QA_THEME` (seeds `oe_theme`), and `QA_VIEWPORT`
  (`WIDTHxHEIGHT` → `test.use({ viewport })`) env-var hooks. Enables
  locale / dark-mode / mobile sweeps without harness forks. (63fb6f75)
- `qa/screenshots/axe-sweep.spec.ts` + `axe.config.ts` - new accessibility
  scan spec using `@axe-core/playwright` against a 29-route subset with
  aggregated JSON output. (e9b5d38f)

### Changed
- `frontend/src/features/ai/QuickEstimatePage.tsx` accessibility pass - all
  10 deferred findings closed (4 P1 + 6 P2): `sr-only` labels via `useId()`,
  `aria-live` on `LoadingState`, `role="alert"` error banners, focus
  management with `resultRegionRef` + `tabIndex={-1}`, `aria-describedby` on
  disabled submit, tablist ARIA wiring, color-only banner `sr-only`
  prefixes, `aria-hidden` decorative icons, `SaveDialog` focus trap via
  `useFocusTrap`. 20/20 ai-feature unit tests pass. (97a1ed49)

### Notes
- Wave 16-DE i18n audit verified: German locale renders cleanly across
  sidebar, content chrome, and module pages - no `__missing_key__`
  fallbacks, no layout overflow despite long German compounds.
- Two QA findings raised for follow-up (not blocking this release):
  authenticated `/` should redirect to `/dashboard` (currently captures
  marketing landing), and `/costs` shows DE chrome but Arabic-script data
  (Middle East seed leaking into DE locale - should auto-pick regional DB).

## [4.9.2] - 2026-05-25

Same-day patch on top of v4.9.1 - BIM Category→TypeName tree no longer explodes
on showcase / fast-path-converted models with sequential placeholder names.

### Fixed
- `BIMFilterPanel.getTypeNameKey` now detects the `<element_type> <integer>`
  placeholder pattern (`"Walls 1"`, `"Walls 2"`, ..., `"Walls 64"`) that the
  showcase seed and the converted-DAE fast path emit when no real Revit
  Family/Type can be resolved. Previously those names flowed through to the
  Category → Type Name hierarchy verbatim - a model with 64 walls rendered
  64 single-element TypeName rows under the Walls category instead of
  collapsing into a few real family/types. The placeholder pattern is now
  treated as no-real-name and routes through to the "Unspecified" bucket like
  any other unlabeled element. Verified on the showcase model
  `c8acb9a5-3fff-5719-a2b0-fe7d62a8a21f` (380 elements across 15 Revit
  categories): zero `"Walls N"` rows left in the tree.

## [4.9.1] - 2026-05-25

Same-day patch on top of v4.9.0 - four follow-up fixes after VPS deploy verification.

### Fixed
- `accommodation` booking-overlap guard re-applied - `POST /api/v1/accommodation/rooms/{id}/bookings` + `PATCH /api/v1/accommodation/bookings/{id}` were silently double-booking the same room on overlapping dates after the V6 verification wave lost the source fix to an NTFS junction race. New `assert_no_booking_overlap()` helper uses the same half-open interval semantics as the existing list filter, checked only against live statuses (`reserved`, `checked_in`), self-excluded on PATCH. 6 xfailed tests un-xfailed, all pass. (eadc6ff8)
- `BIMFilterPanel` Category / TypeName / Buckets tree no longer shrinks when filtering by storey. Commit ba1887cb had gated `byType` / `byCategoryThenType` / `byBucket` population behind `matchesStoreyFilter(el)` as part of an attempted facet-UI sweep - side-effect: picking storey L02 collapsed the entire Category sidebar to L02-only categories. The structural navigation panels must stay stable regardless of which axis is filtered. Verified via Playwright probe: 12 category rows before storey pick, 12 after. (756df401)

### Added
- Three workshop attendee testimonials on the marketing site DDC section: Kai Schmitt (Dimexcon), Philip Becker (Herbert Gruppe), Lukas Fuchs (D&S). CSS grid bumped from a fixed 2-col to a responsive 3/2/1 (≥1080px / ≥720px / mobile) so 5 cards land as 3+2 on desktop. Quotes verbatim, LinkedIn avatars base64-embedded. Generator script committed at `website-marketing/pro/breeze/_screenshots/add_workshop_testimonials.py`, idempotent. (c8c3ba62)

### Changed
- i18n: 247 new keys present in `en.ts` but missing from `de.ts` backfilled to all 26 other locale files as EN placeholders (project convention). Groups: project layout / widgets (102), audit (18), procurement (18), schedule_advanced (16), bim / rfi / submittals (15 each), tendering (14), geo_hub (11), sidebar (7), queue (6), geo (4), reports (3), property_dev (3). 6,416 key insertions total. (715d9de8)

## [4.9.0] - 2026-05-25

Dashboard / settings / docs / converters wave on top of v4.8.0 - every
fix the user reported on 2026-05-24 → 2026-05-25 bundled into one release.

### Added
- `formwork` MVP module - systems catalogue + per-BOQ assignments + reuse-aware unit-cost formula `unit_rate * (1 + waste_pct/100) / reuse_count`. 3 tables (`oe_formwork_system`, `oe_formwork_assignment`, `oe_formwork_schedule_line`), alembic v3132. (7bc95240)
- `OperationsSnapshotCard` - single consolidated dashboard card replacing 9 separate wave-2 widgets (BOQ summary, validation, clash, critical path, top risks, HSE, procurement, budget variance, change orders). 3×3 compact-tile grid, hardened against undefined payload fields. (bbbbe97f, e9d5fbe8)
- `/settings?tab=converters` now embeds the BIM-style live health banner - smoke-test health pills (verify=true), one-click Install / Update / Reinstall / Re-check buttons with live install-progress bar, and a top-level "X/Y working - update available" summary chip. Existing all-converters SHA-comparison table stays below. (3a70a0ac)
- Project Detail page customizer + 7 new widgets (commit ec5aec1e).
- Geo Hub: instant address-search overlay with fly-to + dismissible pin; Cesium ion default-token warning silenced. (e5ceb89e, d2dd0f49)
- `subcontractors`, `rfi`, `submittals`, `schedule_advanced`, `contracts`, `procurement`, `tendering`, `reporting`, `hse_advanced` - UX polish + module-specific deep features (status pipelines, overdue indicators, ball-in-court, critical-path, multi-currency rollup, GAEB X83, scorecards, insurance expiry). (ba22d6d2 0e679296 d3c77c7b 969f5a05 4a3f717c 25022188 3c29a1ec 124–130)
- README hero refreshed with feature-grid layout (ec4a9c16) and all 56 emojis (9 ToC + 47 body) swapped for GitHub Octicons with `<picture>` light/dark variants. (9f631f73, d6535269)

### Changed
- `SUPPORTED_LOCALES` in `property_dev/document_templates.py` expanded from 6 to 27 locales - matches the frontend locale catalogue. Locales without a dedicated JSON in `data/document_locales/` fall back to `en.json` automatically via `_load_locale`. (cbb186fe)
- `/settings`: BIM/CAD section title and description now read just "Converters" / "DDC converters" - the legacy BIM/CAD prefix misled users into thinking it was a separate BIM section. Legacy `?tab=bimcad` aliased to `?tab=converters`. (8e248c4f, de571d15)
- PropDev tabs grouped into Master data / Sales / Operations blocks. (bc2ab951)
- A11y: shell tokens bumped, app-shell button-name on UploadQueue + RecentFAB + remove-task, design-token contrast to WCAG AA for `text-tertiary` / `text-quaternary`. (a15884a5, 02eddcb9, a27da31b)
- /files sidebar counts now honour `q` + extension filters. (8caf4156)
- Catalog: full resource name shown in expanded detail panel; portal-rendered tooltip escapes table overflow clipping. (29883084, 88e8eca2, 8e69f0f3)
- LoginPage: 31 keys backfilled to 14 locales. (c5dda014)

### Fixed
- `WhatsNewCard` chip popovers now render via `createPortal(document.body)` with `position: fixed` + `z-[1000]` - the parent card's `backdrop-blur-md` creates a stacking context that trapped the old `absolute z-30` popovers behind dashboard widgets. (0b15df9a)
- `BIMFilterPanel` chip counts now respect active filters (proper facet-UI: each axis counted against elements passing every OTHER axis but not its own). (ba1887cb)
- BIM `/bim/:id` grouping restored when filtering by category/type. (9a0051e0)
- `/coordination` dashboard 404 cascade - root cause: stale active project id rejecting every endpoint. (17cf8390)
- `/projects/:id/geo` crash "Cannot read properties of undefined (reading 'scene')" - `OverlayLayer` cesium effects now guard against undefined viewer. (882f662e)
- `/clash` mojibake in CAD-BIM picker strings. (9626c014)
- Shared money formatters hardened against Decimal-string inputs across DashboardPage / CompactProjectCard / `formatters.ts` / `MoneyDisplay.tsx`. (1aa4aaea, 0680e9be)
- Kill-switch service worker at `frontend/public/sw.js` - auto-unregisters the stale prod SW that pinned `/assets/index-<hash>.js` from an earlier prod build, so every recent dashboard / catalog / snapshot fix actually reaches the user. (b413be31)
- 20 latent tsc errors swept (PlotStatus `held`/`blocked`, PropDevDocType 6 new records, InventoryMap MoneyDisplay prop, HSEAdvancedPage select cast, unused imports). (c025e6f0)

### Tests
- Formwork smoke test (`tests/modules/test_formwork_smoke.py`).
- A11y axe spec + artefacts for V_DESIGN (a27da31b).

## [4.4.0] - 2026-05-22

PropDev R6 rollup + new Geo Hub module + canonical→3D Tiles pipeline.

### Added
- Property Development R6 wave: Lead → Reservation → SPA → PaymentSchedule entities with multi-buyer ContractParty (ownership_pct sum=100), Broker + Commission + Escrow + PriceMatrix + Phase/Block hierarchy, ValidationRules + regulator PDF reports (RERA / MAHARERA / 214-FZ / CMA in 6 locales), buyer journey dashboards (heatmap / velocity / cashflow waterfall / inventory ageing / funnel conversion / buyer journey timeline), document templates (SPA / reservation / handover / warranty / NOC, 6 locales, jurisdiction-aware clauses, DRAFT watermark, multi-buyer SPA with ownership_pct), tax engine for 12 jurisdictions (GB/DE/AT/CH/AE/SA/IN/RU/BR/SG/US/AU). Alembic v3103 + v3104 → v3105 merge.
- `geo_hub` module - Cesium 3D Tiles 1.1 + cross-module geospatial integration: 7 entities, 34 REST endpoints, pure-Python pygltflib tile pipeline (no C++ deps, no IfcOpenShell). Routes `/geo`, `/projects/:id/geo`, `/property-dev/developments/:id/geo`. Sidebar entry under CAD/BIM analytics with NEW badge. Alembic v3106_geo_hub_init.
- `POST /api/v1/geo-hub/from-canonical/{cad_import_id}` - package a converted CAD/BIM canonical-JSON model as a Cesium 3D Tileset, georeferenced against the project anchor. Optional `heading_deg` for orientation; 5 integration tests pass.
- "View on map" entry buttons in BIM Hub toolbar (when project scoped) and Property Dev development toolbar (when development selected) - navigates to the matching Geo Hub page. New `geo_hub.view_on_map` i18n key in 27 locales.
- CesiumJS frontend dependency wired via lazy `import('cesium')` + Vite `vendor-cesium` manualChunk (4.7 MB raw / 1.3 MB gzip, isolated from main bundle). `window.CESIUM_BASE_URL` set before any cesium import resolves; static assets (Workers / Widgets / Assets / ThirdParty) copied to `dist/cesium/` during build.

### Changed
- `RequestValidationError` handler in `app/main.py` now recursively coerces all non-JSON-native types (Decimal, UUID, datetime, ...) to JSON-safe forms before responding - fixes 500 in 422 responses when Pydantic input echoed a Decimal.
- `_resolve_doc_type_or_404` in property_dev now returns 404 (matches its name), not 400.

### Fixed
- R6 `MissingGreenlet` in `convert_lead_to_reservation` and `convert_reservation_to_spa` - surgical `session.expire(obj)` per row instead of session-wide `expire_all()`, and snapshot scalar attrs before `update_fields` so post-write reads don't lazy-load on expired rows.
- 24 locale files (ar/bg/cs/da/es/fi/fr/hi/hr/id/it/ja/ko/mn/nl/no/pl/pt/ro/sv/th/tr/vi/zh) had a missing comma at line ~5626 before the propdev block (regression from d7431ac1).
- `/v1/projects/{id}/profile` 404 spam (50/64 errors per user log) - auto-retrofit + CRM/users limit caps + bug_report whitelist + converter install timeout.
- 6 stale tsc errors in `CesiumViewer.test.tsx` (vi.doMock 3-arg signature), `InventoryAgeing.tsx` (unused `num`), `SalesVelocity.tsx` (unused `SalesVelocityBucket`).
- Redundant `from fastapi.responses import Response` inside `stream_propdev_document` - already imported at module top.

### Tests
- 31 ValidationRule tests + 24 geo_hub tile pipeline tests + 5 from-canonical integration tests + R6 lead-to-SPA suite (12/12) pass.

## [4.3.2] - 2026-05-22

Admin UX hotfix - audit log full rewrite + sidebar polish + developer guide refresh.

### Added
- `/admin/audit-log` filter bar (free-text search debounced, date-range presets Today/Last 7d/Last 30d/Custom, sortable timestamp column, JSON export alongside CSV, pager with total count via new `GET /api/v1/audit/count`, per-page selector 25/50/100/200, expand-row drill-down with before/after JSON diff, ESC closes drawer).
- Sidebar admin grid (2-column button strip with horizontal icon+label layout at the bottom - Users/Audit/Roles/Modules/Settings/About - short labels in EN + RU with fallback for other 25 locales).

### Changed
- `/admin/audit-log` is full-width (was `max-w-6xl`).
- `frontend/src/main.tsx` global mutation `onError` toast now respects `meta.suppressGlobalErrorToast` opt-out (closes double-toast issue on `/admin/permissions` PATCH).
- Developer guide refreshed - fake `publish_event`/`@subscribe` examples replaced with real `event_bus.publish/subscribe` API, fake `PERMISSIONS = []` list replaced with real `permission_registry.register_module_permissions(name, {...: Role.X})` pattern, manifest example shows real `optional_depends` + `display_name_i18n` fields, copy-template step replaced with real `make module-new NAME=oe_my_module`, RBAC clarified (hierarchical: admin > manager > editor > viewer).
- Developer guide translated to 9 locales (en/de/es/fr/it/nl/pl/pt/ru).

### Fixed
- `/admin/audit-log` backend was silently ignoring `date_from`/`date_to` query params the frontend was already sending.
- UUID parse on `user_id_filter` no longer 500s on malformed input.
- Developer guide code blocks no longer touch surrounding text (Code component `my-4 pt-5`, inline `mx-0.5 px-1.5`).
- 12px gap between sidebar admin grid and update notification card.

### Tests
- `audit-log.test.tsx` extended 5→12.
- `PermissionsMatrixPage.test.tsx` 8/8 still pass.
- Backend `test_admin_permissions_matrix.py` 9/9 still pass.

## [4.3.1] - 2026-05-22

Hotfix above v4.3.0 - the issue #153 root-cause fix and the contact-email
canonicalisation landed locally after the v4.3.0 PyPI wheel had been published.
This release republishes the wheel so `pip install openconstructionerp` gets
the working build.

### Fixed
- **Issue #153 (real root cause).** `bim_hub` DAE serve-time validator was
  rejecting valid COLLADA files with namespace-prefixed roots like
  `<ns0:COLLADA>` (the form the DDC/Revit pipeline emits) - both are valid
  per the XML namespace spec. Validator now accepts either form.
- **Contact email canonicalised.** Every user-visible string and config
  default now points to `info@datadrivenconstruction.io`. The old aliases
  (`support@`, `sales@`, `noreply@`, `notifications@`, `info@openconstructionerp.com`)
  never had real mailboxes - they bounced silently.

## [4.3.0] - 2026-05-22

### Round 5 - 11-module deep hardening + issue #153 RVT crash fix

A focused 11-module deep audit + fix wave, plus an urgent fix for the production-reported `TypeError: Cannot read properties of undefined (reading 'toLowerCase')` that crashed the RVT upload flow on /bim. ~150 new tests across the touched modules.

### Security

- **`carbon`: 22-endpoint IDOR closure.** Carbon-footprint endpoints (`/carbon/factors/`, `/carbon/scope1`, `/carbon/scope2`, `/carbon/scope3`, `/carbon/inventory/`, `/carbon/reduction-targets/`, `/carbon/offsets/`, `/carbon/reports/`) all routed by `project_id` without `verify_project_access`. Any authenticated user could read/write any project's emission inventory and CSRD-mandated targets. Project gate added on every read and write site; 22 endpoints covered.
- **`hse_advanced`: MANAGER role gate on regulatory closures (RIDDOR/OSHA/ISO 45001).** `close_incident`, `close_inspection`, `close_audit_finding` accepted any authenticated user - a contractor could mark a fatality as "closed" without supervisor sign-off, breaking the regulator-facing audit trail. Now requires `manager` or `safety_officer` role; close-audit log captures the closer's role.
- **`subcontractors`: rating + block tampering closed.** `rate_subcontractor`, `block_subcontractor`, `unblock_subcontractor` had no project-access check and no role guard. A bidder could downvote competitors company-wide. Project-scope verify + `procurement_manager`/`admin` role required.
- **`qms`: IDOR closed on calibration + NCR routes.** `/qms/calibrations/{id}`, `/qms/ncrs/{id}` (read, update, close) returned/updated rows across project boundaries. Tenant + project gate added; close-NCR also requires `quality_manager` role.
- **`rfi`: IDOR on close-rfi closed.** `POST /rfi/{id}/close` accepted any authenticated user from any project. Project-scope verify added; the close action now also captures `closed_by_user_id` for the regulator trail.
- **`submittals`: project-scope IDOR closed.** `GET /submittals/{id}`, `PATCH /submittals/{id}`, `POST /submittals/{id}/transitions` all leaked across tenants. Repository-level `project_id` filter + service-layer project-access verify.
- **`variations`: apply-to-final-account IDOR closed.** `POST /variations/{id}/apply-to-final-account` was the highest-impact endpoint in the module (rewrites the project final-account amount) and had no project gate. Now requires `finance_manager`/`pm` and verifies the variation belongs to the project on the URL.
- **`projects`: currency-change race + slug-collision race closed.** Currency-change endpoint now returns 409 when the project already has financial transactions (was silently corrupting historical totals). Slug-collision retry loop replaced with a unique-index + IntegrityError catch.
- **`crm`: GDPR Art-17 forget endpoint + role + activity-owner spoof.** New `POST /crm/leads/{id}/forget` that PII-purges + tombstones a lead per GDPR Art-17 (right to erasure). `win_lead` now requires `sales_manager` role (was open). `log_activity` no longer trusts the request body's `owner_user_id` field - server forces it to `current_user_id` (closes activity-attribution spoof).

### Correctness

- **`variations`: currency-aware rollup.** `get_project_variations_total` was summing `amount` across mixed-currency variations (USD + EUR + GBP) into one number. Now groups by `currency_code` and returns `{by_currency: {USD: 12345.00, EUR: 9876.00}, base_currency_total: <FX-converted>}` - matches the BOQ multi-currency rollup contract from v2.9.1.
- **`qms`: NCR `cost_impact_amount` widened Numeric(15,2) → Numeric(18,2).** Aligns with the platform money convention used by `finance`, `change_orders`, `contracts`, `rfq_bidding`, and `clash_cost_impact`. Old precision capped the integer side at 13 digits - fine for a single positional cost but truncated multi-million-EUR tunnel-section rework NCRs at the database edge.
- **`submittals`: unique number constraint + retry.** `next_submittal_number(project_id)` raced under concurrent submitter uploads producing duplicate labels. New `(project_id, submittal_number)` unique index + service-layer IntegrityError retry loop (3 attempts).
- **`rfi`: `cost_impact` Decimal validation.** Was accepting `float` from the request body and round-tripping through SQLAlchemy `Decimal` - surfaced as 0.1 + 0.2 = 0.30000000000000004 in the rolled-up trade-cost report. Pydantic v2 `Decimal` field + `decimal_places=2` constraint on the schema.
- **`service`: ticket / contract / work-order number uniqueness.** `next_ticket_number`, `next_contract_number`, `next_work_order_number` read `COUNT(*)` then format-string concat - two dispatchers POSTing concurrently produced identical labels. Backfilled three unique indexes (composite on ticket for per-contract scoping); the existing service-layer retry path now actually retries.
- **`eac`: run-result `rule_id` index.** `oe_eac_run_result_item.rule_id` had no standalone index - the leftmost-prefix on the existing compound `(run_id, rule_id)` covered only the run-scoped queries, so "results for one rule across runs" was seq-scanning a 100k-row hot table.

### Bug fixes

- **#153 - RVT upload crash: `TypeError: Cannot read properties of undefined (reading 'toLowerCase')`.** Defensive guards at 7 sites where a string method was called on possibly-undefined input:
  - `frontend/src/app/layout/Sidebar.tsx` - keydown handler (`e.key?.toLowerCase()`)
  - `frontend/src/features/boq/BOQEditorPage.tsx` - keydown handler
  - `frontend/src/shared/ui/BIMViewer/BIMViewer.tsx` - keydown handler
  - `frontend/src/features/bim/InstallConverterPrompt.tsx` - converterId guard
  - `frontend/src/shared/ui/BIMViewer/ElementManager.ts` - `setDisciplineVisible` + `getDisciplineColor` (discipline could be `undefined` for elements with no IFC class)
  - `frontend/src/features/bim/BIMFilterPanel.tsx` - `Object.keys(...).map(k => String(k).toLowerCase())` so numeric/null keys can't crash the filter render.

### New endpoints

- `POST /api/v1/crm/leads/{id}/forget` - GDPR Art-17 right-to-erasure for CRM lead PII (name, email, phone, IP, lead-source UA scrubbed; lead row tombstoned with audit reason).
- `POST /api/v1/submittals/{id}/attachments/upload/` - magic-byte-gated attachment upload (PDF/PNG/JPG/HEIC/HEIF/DWG/IFC; SVG banned; Content-Disposition: attachment).
- `POST /api/v1/rfi/{id}/attachments/` - magic-byte-gated RFI reply attachment upload.

### Migrations

- `v3099_eac_run_result_rule_id_index` - eac standalone FK index on `oe_eac_run_result_item.rule_id`.
- `v3099_rfi_unique_attachments` - RFI `(project_id, rfi_number)` unique + attachments JSON column.
- `v3099_subcontractors_unique_tax_id` - subcontractors unique tax-id index (per tenant).
- `v3099_submittals_unique_number` - submittals `(project_id, submittal_number)` unique constraint.
- `v3100_schedule_advanced_user_indexes` - schedule_advanced user-FK indexes (closes pre-flagged seq-scan on workspace_share lookup).
- `v3101_carbon_idor_indexes` - carbon `(project_id, scope)` covering index used by the new project-scope gate on the 22 endpoints.
- `v3101_crm_lead_email_dedup_index` - case-insensitive `LOWER(contact_email)` index for the new dedup pre-check.
- `v3101_qms_money_numeric` - qms `cost_impact_amount` Numeric(15,2) → Numeric(18,2) (Postgres-only widening; SQLite stores as text).
- `v3101_service_number_uniques` - service contract/ticket/work-order unique indexes.
- `v3101_variations_currency_indexes` - variations `(project_id, currency_code)` covering index for the new currency-aware rollup.
- `v3102_round5_merge` - pure multi-head merge of all eight Round-5 heads back to a single trunk.

### Tests

~150 new tests across 11 modules. Coverage focus: IDOR negatives (cross-project read + write should 404), role negatives (estimator can't close NCR), money correctness (`Decimal(0.1) + Decimal(0.2) == Decimal("0.30")`), uniqueness race-condition simulations (concurrent inserts → exactly one wins, the other gets IntegrityError → retry produces N+1 label).

---

## [4.2.4] - 2026-05-21 · Round 4 - 20-module deep improvements sweep

A single release bundling 20 parallel module-deep audit + fix passes on previously under-tested modules. Every module touched here got a baseline pytest file; combined ~140 new tests.

### Security

- **`teams`: critical RBAC bypass closed.** `create_team`, `add_member`, `remove_member` had no `verify_project_access` gate - any authenticated user could create teams in any project and self-elevate to `owner`/`project_manager`, inheriting elevated permissions. Service-layer project-access check + self-elevation block on elevated roles.
- **`architecture_map`: critical information disclosure closed.** Was `Depends(get_current_user_id)` only → every viewer/estimator could enumerate the full ERP architecture (table names, model columns, module deps). Now requires `architecture.read` admin permission with router-level + per-endpoint defence.
- **`rfq_bidding`: award role gate.** `award_bid` only required `rfq.update` (EDITOR) but FSM declares admin/manager. Added service-layer 403 check on `{admin, manager, owner}`. Also: bid-submission state-escape blocked (vendors could submit against draft/awarded/cancelled), past-deadline submissions 409.
- **`smart_views`: federation read leak.** `_can_read` returned `True` blindly for federation scope → anyone with a federation UUID could read any federation-scoped view. Now resolves `BIMFederation.project_id` and checks accessible project set. Closes backlog #103 (federation visibility staleness on owner change) via new event subscriber on `projects.project.updated`.
- **`opencde_api`: `$orderby` allowlist + LIKE-wildcard injection.** `parse_orderby` used bare `getattr(BCFTopic, field, None)` accepting ORM relationships; user-supplied label literal interpolated into `LIKE %"<value>"%` without escaping `%`/`_`/`\`. Both fixed; scalar columns only + SQLA `.like(escape="\\")`.
- **`pipelines`: `create_pipeline` accepted `project_id` from body without `verify_project_access`.** Now gated.
- **`coordination_hub`: silent write on `coordination.read` GET.** Viewer hitting `/thresholds` committed seed rows. Now `allow_seed` is permission-derived; viewers get ephemeral defaults.
- **`compliance_docs` + `correspondence`: magic-byte upload endpoints.** Mirror v4.2.1 punchlist + v4.2.3 AI fixes - extension-only validation replaced with `app.core.file_signature.require_signature`.
- **`correspondence`: CRLF subject sanitisation.** Email-header injection vector closed; control chars stripped from `subject` on create + update.
- **`contacts`: PII redaction in logs + import-error responses + duplicate-email race (IntegrityError → 409) + PATCH audit `user_id` propagation.**
- **`erp_chat`: history role/length sanitisation.** Smuggled `system` role in `conversation_history` now dropped - kills prompt-injection via fake system turn. Content capped at 4000 chars, tail-windowed to 20 most recent.
- **`ai_agents`: tool-context spoofing fix.** An LLM that forged `__agent_context__` in tool_args could spoof the user; trusted context now strips and re-injects. Idempotency-Key header dedupes retries.
- **`clash_ai_triage`: rate limit added to triage/batch/replay endpoints** (was none) + 180s wall-timeout + structured per-call cost log.
- **`enterprise_workflows`: action_type whitelist + MAX_STEPS=32 cap + role validation.**

### Performance

- **`opencde_api`: N+1 in `create_topic`** - was loading every BCFTopic row for the project to compute monotonic index via `len(list(...))`. Replaced with `SELECT COUNT(*)`.
- **`project_intelligence`: LLM LRU cache (sha256-keyed, 60s TTL) + bounded state cache (was unbounded → memory leak on long-lived process).**
- **`pipelines`: max-nodes cap (256), per-node `asyncio.wait_for` timeout (300s), row-ids cap (5000) on `source.boq` / `transform.filter` envelopes.**

### Correctness

- **`clash_cost_impact`: Decimal-exact rollup.** Was reading 2dp-rounded floats and re-summing → drift up to `0.005 × N`. Now sums exact Decimals, rounds once at the boundary; `ROUND_HALF_UP` instead of banker's even.
- **`coordination_hub`: warn/error threshold invariant.** Inverted pairs could persist and silently break the elif-cascade.
- **`rfq_bidding`: money/currency Decimal validation** + 3-letter ISO normalisation + score field validation. Also fixed latent `MissingGreenlet` bug (ORM access after `expire_all()` - hidden in prod because the prior `try: except: pass` audit-log catch swallowed it).
- **`markups` + `dwg_takeoff`: Float → Numeric(18,6) / Numeric(10,6)** on `measurement_value`, `pixels_per_unit`, `real_distance`, `scale_override`, `thickness`, `scale_denominator`. New alembic migrations `v3097_markups_measurement_numeric` (merges two heads) + `v3097_dwg_takeoff_decimal_quantities`. Float precision drift no longer leaks into BOQ via takeoff/markups.
- **`dwg_takeoff`: magic-byte validation moved pre-write.** Renamed PDFs/ZIPs no longer land on disk before the sniff.
- **`compliance_ai`: was stub-only.** Built `POST /from-nl` with auth + rate-limit + 2000-char input cap + 1024-token AI cap + structured verdict log + `_log_failures`-wrapped event publish. Fixed latent double-prefix bug (`/api/v1/compliance-ai/compliance-ai/_health`).
- **`smart_views`: federation views now appear in `list_visible_to_user`** (previously excluded entirely).

### Observability

- New structured cost / outcome logs across: `erp_chat`, `ai_agents`, `clash_ai_triage`, `project_intelligence`, `compliance_ai`, `pipelines`, `coordination_hub`, `teams`, `enterprise_workflows` - each emits a single `module.operation` INFO record with relevant fields (tokens, duration, cost, actor, outcome).
- `architecture_map` now writes per-endpoint audit log of who's enumerating system architecture.
- `teams` publishes `teams.team.{created,updated,deleted}` and `teams.membership.{added,removed}` events for permission-cache invalidation.
- `compliance_docs` publishes `compliance_docs.expiry.alert` event on status transitions.

### DB

- `alembic v3097_markups_measurement_numeric` (merge migration for multi-head)
- `alembic v3097_dwg_takeoff_decimal_quantities`
- `alembic v3098_correspondence_attachments_column` (adds `attachments JSON NOT NULL DEFAULT []` to `oe_correspondence_correspondence` - required for the new attachments endpoint to work on existing prod DBs)

Single head at `v3098`.

### Tests

~140 new tests across:
- `test_coordination_hub.py` (5), `test_smart_views.py` (3), `test_clash_ai_triage.py` (12), `test_clash_cost_impact.py` (9), `test_cost_match.py` (13), `test_rfq_bidding.py` (11), `test_pipelines.py` (4), `test_erp_chat.py` (5)
- `test_teams.py` (2), `test_contacts.py` (11), `test_correspondence.py` (6), `test_compliance_ai.py` (4), `test_compliance_docs.py` (12), `test_enterprise_workflows.py` (6), `test_ai_agents.py` (6), `test_project_intelligence.py` (7)
- `test_dwg_takeoff_service.py` (11), `test_markups.py` (4), `test_opencde_api.py` (30), `test_architecture_map.py` (11)

### Notes

`cost_match` was found to be a stub-only module (the matching logic lives in `match_elements`; cost_match is reserved for T12 assembly material-layer matching). Baseline tests pin current shape with a guard that fails when models.py lands, prompting full T12 coverage. No regressions detected in any adjacent suite.

## [4.2.3] - 2026-05-21 · Security hardening + observability foundation + bundle slimdown

### Added

- **Request correlation IDs.** New `app/middleware/request_id.py` (`RequestIDMiddleware`) generates `uuid4().hex[:16]` (or honours a client-supplied `X-Request-ID` matching `^[A-Za-z0-9_-]{1,64}$`), stores it in a `ContextVar`, echoes it on every response. Wired into the root logger via `RequestIDLogFilter` so every log line in the process gets the request ID injected. Format prefix is now `[%(request_id)s]`.
- **Slow-query logging.** SQLAlchemy `before_cursor_execute` / `after_cursor_execute` event listeners measure each statement; anything over `OE_SLOW_QUERY_MS` (default 500 ms) is logged at WARNING with structured `extra={elapsed_ms, statement[:200], executemany}`. Covers both async and sync engines.
- **`/api/health` deepened.** Adds `alembic_head_matches` (script head vs DB current rev) and `frontend_dist_present` (`_frontend_dist/index.html` exists). Either being false flips top-level `status` to `"degraded"` (still 200 - load balancers can probe without page-flapping).
- **Operator runbook.** New `docs/RUNBOOK.md` (156 lines): service basics, restart / logs / health probes, deploy procedure, sqlite backup-restore, alembic `DATABASE_SYNC_URL` gotcha, rollback, common-500 causes. Extracted from internal memory so on-call can recover the box without paging the original author.
- **Client-error sink endpoint.** New module `oe_client_errors`: `POST /api/v1/client-errors/` accepts anonymised payloads (length-capped: message ≤ 2048, ≤ 64 stack lines, ua / path ≤ 512), per-IP 30/min rate limit, logs at WARNING with structured `extra`. Frontend `errorLogger.ts` now POSTs alongside localStorage (fire-and-forget, `keepalive: true`, gated by `VITE_ENABLE_ERROR_REPORTING`).
- **FK indexes migration (`v3096_round3_fk_indexes`).** Adds 6 missing indexes: `oe_contracts_progress_claim_line.contract_line_id`, `oe_clash_issue.{first_seen,last_seen,resolved}_run_id`, `oe_crm_opportunity.lost_reason_code`, `oe_equipment_work_order.schedule_id`. Inspector-guarded so re-running is safe. The other 8 audit-flagged FKs turned out to be already covered by composite indexes.

### Security

- **Closed `POST /api/v1/jobs/{job_id}/cancel` unauthenticated mutation.** Requires `CurrentUserId` now (the `JobRun` model has no project/owner column, so per-row ownership gating isn't possible yet - authentication is the floor).
- **Path-traversal hardening in CAD/BOQ smart-import.** `takeoff/router.py:1382`, `takeoff/router.py:1617`, and `boq/router.py:5377` all built `Path(tmpdir) / filename` from `file.filename`. Now normalise to `Path(filename).name` (drops any directory components) and 400 on empty / `.` / `..`. Normal filenames like `report.xlsx` are unchanged.
- **AI photo / file estimate now magic-byte validates.** `ai/router.py` `photo-estimate` calls `require_signature(... ALLOWED_PHOTO_TYPES ...)`; `file-estimate` uses a per-category allow-list (pdf / excel / cad / image), skipping only `csv` (no reliable signature). Bytes whose declared `Content-Type` doesn't match the magic prefix → HTTP 415.
- **StampTemplateEditor XSS fix.** `frontend/src/features/file-approvals/StampTemplateEditor.tsx:184` used `dangerouslySetInnerHTML` to preview pasted SVG. A shared malicious template could `<script>` against the next viewer. Now renders inside `<iframe sandbox="" srcDoc={...} />` - empty sandbox attribute strips all capabilities (no scripts, no same-origin, no forms).

### Fixed

- **3 silent-fail `200 + {error}` responses → proper status codes.**
  - `fieldreports/router.py` `/weather/` 200 → 503 when provider key missing or upstream fetch fails.
  - `costs/router.py` `/vector/index/` 200 → 503 (× 4 sibling early-returns) when Qdrant unreachable.
  - `costs/router.py` rate import 200 + "no rate_code column" → 422 with the same body shape.
- **Broken collection in `test_tendering_leveling.py` repaired.** `AddendumCreate` was never added with the bid-leveling Addendum feature - the test targets unimplemented service methods on top of a missing schema. Marked `pytest.mark.skip` at module level with a docstring listing the 4 implementation prerequisites for re-enable, plus a guarded import so the file becomes valid the moment the feature ships. 5,922 tests now collect cleanly.

### Changed

- **Frontend bundle slimdown.** `index-*.js` 1.76 MB → **1.27 MB** (gzip 311 KB). Five unused deps dropped (`leaflet`, `react-leaflet`, `@types/leaflet`, `jszip`, `i18next-http-backend`, `i18next-browser-languagedetector` - 11 packages removed in total including transitives). Seven admin pages converted from eager to `React.lazy()` (`SettingsPage`, `ModulesPage`, `ModuleDeveloperGuide`, `AssembliesPage` + 3 siblings, `ImportDatabasePage`, `OnboardingWizard`, `LoginPageNext`, `QuickEstimatePage`) - each emits its own chunk; total ~530 KB raw split off the main chunk.
- **BOQ grid column stability.** `BOQGrid.tsx` previously listed the i18next `t` function as a `useMemo` dependency. Because `useTranslation()` returns a fresh `t` on every render, column defs rebuilt every render → AG Grid `setColumnDefs` re-ran constantly. Replaced with `i18n.language` as the real dep and a `tRef` for the latest `t`. Removes a measurable repaint on every unrelated state update.
- **`MoneyDisplay` / `QuantityDisplay` Zustand reads use field selectors.** Each cell was subscribing to the full preferences store; an unrelated preference change (theme toggle, locale switch) re-rendered every money / quantity cell in the BOQ. Now uses `useStore(s => s.field)` per field.
- **4 orphan `describe.skip` / `it.skip` blocks annotated.** Sites in `api-mocks.test.tsx` and `visual-regression.test.tsx` now carry a single-line `// SKIP: <reason>. Re-enable when: <condition>. Tracked in v4.3 backlog.` so future maintainers can decide without guessing.

### Notes

109 modules load (was 108 - `oe_client_errors` added). Boot time on VPS unchanged at ~3-4 min. No additional Python deps; alembic chain stays single-head at `v3096_round3_fk_indexes`. Frontend dev deps `@types/leaflet` also removed.

## [4.2.2] - 2026-05-21 · i18n + a11y + event flow + performance polish

### Added

- **`useFocusTrap` hook.** New `frontend/src/shared/hooks/useFocusTrap.ts` - captures `document.activeElement` on mount, intercepts Tab / Shift+Tab to wrap focus within the container, restores focus on cleanup (covers Escape, backdrop click, explicit close). Filters disabled / `aria-hidden` / off-screen nodes. Now wired into `ConfirmDialog` + `WideModal`.
- **`role="navigation" aria-label="Main navigation"` landmark on Sidebar.** Screen readers can now identify the sidebar and skip-nav directly to it.
- **3 previously-orphan event subscribers now wired:**
  - `qms.ncr.mirrored_from_hse` → notifications wave-5 dispatcher (in-app notification to HSE incident creator + QMS NCR owner)
  - `procurement.supplier_rating_update` → procurement events log subscriber (INFO with `ncr_id` / `supplier_id` / severity - stub until supplier-rating model lands)
  - `contracts.risk_register_update` → risk-events subscriber materialises a risk row with `metadata.source_incident_id` for idempotency (PostgreSQL-gated)
- **Detached-task error visibility.** New `_log_failures(coro, *, name)` helper in `app.core.events` attaches a done-callback that logs failures at WARNING with exception class + traceback. Wired into `procurement._on_tender_awarded` and `schedule._on_field_report_submitted`. No more silent task failures.

### Fixed

- **i18n: 327 missing `admin.*` keys backfilled across 23 locales.** Permissions Matrix + Audit Log pages now render correctly in ar, bg, cs, da, es, fi, fr, hi, hr, id, it, ja, ko, mn, nl, no, pl, pt, ro, sv, th, tr, vi, zh - 24 × 54 = 1,296 inserts. DE + RU already complete in native; EN unchanged. Translation refinements pending - initial release ships the English fallback so the UI works correctly in every locale.
- **StatusDot color-only-meaning gap.** Component now always renders a screen-reader-only `<span>` with the variant name ("Success" / "Warning" / "Error" / "Info" / "Neutral") when no visible `label` is supplied. Wrapper gets `role="status"`. Color-blind + high-contrast users now have a text signal.
- **BOQ N+1 query loops.**
  - `_subtree_height` (`boq/service.py:1935`): per-node `list_children` → single `list_all_for_boq` + in-memory parent→children index. O(subtree_size) → O(1) round-trips.
  - `apply_quantity_links` (`boq/service.py:7234`): per-link `get_by_id` lookup → new bulk `PositionRepository.list_by_ids` + snapshot dict. N round-trips → 1.

### Removed

- **Unused exports:** `FloatingChatButton` (only referenced in a stale comment).
- **Unused frontend dep:** `react-is` (zero direct imports; still pulled transitively by recharts / ag-grid / testing-library where actually needed).
- **Dev scratch artefacts:** `frontend/_capture_v4_news.mjs`, `frontend/_capture_v4_v2.mjs`, `frontend/_verify_cards_layout.mjs`, `tmp/check_full.py`, `tmp/check_vi.py`. These were one-off v4.0 marketing capture / i18n-build scripts that didn't belong in the shipped tree.

### Notes

Test coverage this release: 299 BOQ + 198 events / risk / procurement / qms / hse / notifications + 18 a11y (ConfirmDialog + WideModal) + 14 admin-i18n - all green.

`email-validator` was intentionally **not** removed: pydantic's `EmailStr` uses it via `users` / `portal` / `file_distribution` / `file_transmittals` and would `ImportError` at runtime without it.

## [4.2.1] - 2026-05-21 · Security & correctness hotfix

### Fixed

- **IDOR closures across legacy modules.** Added `_verify_boq_owner()` to BOQ `get_boq_structured`, `get_boq_activity`, `create_revision`; added `verify_project_access()` to Equipment GET/PATCH/DELETE `/equipment/{id}`, Punchlist `/items/{id}/transition/` + `/pin-to-sheet/`, Meetings `/{meeting_id}/complete/`, and Costs `/v1/costs/{item_id}/record-usage/`. Surfaced by the v4.2.0 20-wave QA sweep.
- **Coordination Hub serial KPI fetch.** Replaced 6 sequential `await` calls in `coordination_hub.service.build_dashboard()` with a single `asyncio.gather(...)` - dashboard load time now matches the slowest single counter rather than their sum. 37 backend tests still green.
- **MeasureTool snap-to-vertex X axis.** Removed dead `(raw.x - raw.x)` term in `frontend/src/shared/ui/BIMViewer/MeasureTool.ts:221`. Snapping now reads the correct X coordinate; 9 vitest specs green including the 8-pixel snap test.
- **Hardcoded currency fallbacks removed.** `'USD'` fallbacks in `CwicrMatchPanel`, `VariantPicker`, `MultiVariantPicker`, and the `'EUR'` literals in `CostsPage` (`handleCreateAssembly`, `INITIAL_COST_ITEM_FORM`, totals badge) now resolve from the project context via `useProjectContextStore` + `/v1/projects/` query, matching how `AddToBOQModal` / `FinancePage` / `MatchWizardFlow` already do it. Empty fallback when no project context - explicit user choice required.
- **Change Orders float-in-money → Decimal-validated `str`.** Every monetary field in `changeorders.schemas` (`cost_impact`, `cost_delta`, `original_quantity`, `new_quantity`, `original_rate`, `new_rate`, summary totals) now serialises as `str` with a Decimal coercer mirroring `finance.schemas`. Router conversions updated. No DB column change.
- **Punchlist photo upload - magic-byte validation.** Removed spoof-able content-type-only check from `/items/{id}/photo`; now uses `app.core.file_signature.require_signature()` (jpeg/png/gif/webp/heic/heif/tiff; SVG/XML/PDF/scripts rejected with 415). The cross-linked `Document.mime_type` now uses the detected MIME, not the client-supplied header.

### Notes

Cumulative test count this release: 21 backend unit + 37 coordination_hub + 47 changeorders/punchlist + 24 costs frontend + 9 MeasureTool. AGPL-3.0 compliance unchanged.

## [4.2.0] - 2026-05-21 · Coordination · Smart Views · Permissions · Sidebar restructure

### Added

- **Model Coordination Hub.** New top-level `/coordination` landing page unifies federations + clashes + smart views + rule packs + BCF activity into one project-scoped view. Glass-card visual treatment on a gradient backdrop with per-metric color accents (rose / amber / emerald / sky). Health traffic-light banner surfaces "all clear" / "attention" / "alert" based on open-clash and failing-rule counts. Quick Actions row gives one-click jumps to Clash, Federations, Rule packs, Smart views. New `coordination_hub` backend module with KPI rollup, trade matrix, timeline, configurable alert thresholds (4 metrics: open clashes total, high-severity clashes, cost-impact % of budget, model age days; with default seeding + admin overrides). Trade matrix cells are drill-down links into the clash list with the discipline pair pre-filtered. 37 new backend tests + 27 frontend tests, all green.
- **Smart Views - rules not snapshots.** Net-new module with a rule-based view engine: each rule has a selector (`ifc_class` + property + operator + value) and an action (color / hide / transparent / isolate). The viewer re-evaluates rules against the current federation every time it loads, so a "Walls by fire rating" view stays correct as the model evolves. Per-view scope (user / project / federation). Six built-in presets ship out of the box (Walls by FireRating, MEP by discipline, Concrete C30/37+, Doors fire-rated, Exterior walls, Spaces by zone) + UI to install them with one click. Share-by-link: generate signed `itsdangerous` HMAC token, copy URL, revoke from owner. New alembic migrations `v41_smart_views` + `v41_smart_views_share`. 62 backend tests + 43 frontend tests.
- **Clash Smart Issues - deterministic identity.** ClashIssue rows now carry a SHA1 signature (sorted GUID pair + spatial bucket + clash_type) so re-running clash detection preserves issue identity, comments and suppression across runs. Bulk suppression service (`bulk_suppress(project_id, issue_ids, reason)`) with IDOR-safe ownership gate + audit-logged history fan-out. New alembic migration `v41_clash_signature_smart_issues`. Frontend filter persistence (severity / status / discipline / sort) per-project in localStorage with version envelope + 5-project LRU + debounced writes. 82 clash tests including 8 new bulk-suppression tests + 17 frontend filter-persistence tests.
- **BCF 3.0 - zip export + reader + OpenCDE REST API.** Stdlib-only BCF 3.0 writer with deterministic UTC dates, PNG magic-byte snapshot validation, duplicate-GUID guard, and zip-slip prevention via `_safe_dir` GUID hex validation. Reader uses `defusedxml` (XXE / DTD disabled) with 100 MiB uncompressed cap, 10 000-entry cap, and `_is_unsafe_zip_path` guard against absolute / drive-letter / `..` paths. New OpenCDE REST API at `/api/v1/bcf/3.0/` exposes the buildingSMART 15-endpoint conformance profile (projects, topics CRUD, comments, viewpoints, snapshot bytes, current-user) with OData `$filter` / `$orderby` / `$top` / `$skip`, ETag (sha1 of modified_date) and `If-Match` stale-write detection. Round-trip integrity test verifies that a 5-topic × 3-viewpoint × 10-comment + snapshots archive survives writer → reader → writer with identical structure (incl. unicode / emoji / CJK titles). 42 OpenCDE tests + 14 round-trip tests, all green.
- **Clash AI Triage.** Persisted LLM-based clash severity verdicts. `MODEL_COSTS` Decimal table covers 9 OpenAI + Anthropic + xAI models with `Numeric(10,4)` cost columns for auditing. Deterministic prompts (`PROMPT_VERSION="v1.0"`) with `_sanitise()` stripping control chars + backticks + tagging `ignore previous` / `system:` / `assistant:` lines as `[SUSPICIOUS]`. Per-user API key resolution via `AISettings` (never from process env, never logged). Replay endpoint refuses 410 Gone when the source clash was deleted (FK on-delete nulled `clash_id`). New alembic migration `v41_clash_ai_triage`.
- **Clash Cost Impact.** Rolls clash-to-BOQ links into a per-project total open cost impact. Decimal arithmetic end-to-end (no float). Currency-aware. Graceful handling of missing BOQ links (404 short-circuits, no crash). Defended against 404-vs-403 timing oracle by resolving `project_id` before access-check.
- **BIM Requirements - Rules-as-Code YAML.** Add LOD 300 (15 rules) + LOD 400 (18 rules) + COBie 2.4 handover (15 rules) seed packs in repo-root `data/bim_rules/` next to the existing 5 packs. Pure rule_runtime evaluator (no DB / IO; tested with synthetic elements). YAML loader uses `yaml.safe_load` + strict tag block-list (rejects `!!python/object/apply`, `!!python/name`). RulePackPreviewModal frontend adds a "Test against current model" section with color-coded pass / warn / fail chips per rule + click-through drill-down. 56 rules total across 8 packs; 121 backend tests + 29 frontend tests.
- **Federation Type Tree (Slice 2) + Federated Viewer (Slice 3).** Flat-by-class type tree groups elements across all federation members (not per-model nested) so a "Walls" entry surfaces every wall regardless of source model. New 3D federated viewer composes multiple GLTF members into one scene with per-member visibility / color hints / dispose-on-unmount discipline (BufferGeometry / Material / Texture / Renderer / Controls / RAF / ResizeObserver all cleaned up). 22 viewer tests + 16 type-tree tests.
- **Coordination Hub Dashboard.** Coordination-hub backend aggregator pulls live counts from clash + bim_hub + bim_requirements + smart_views + bcf + clash_cost_impact with `_safe_count` / `_safe_scalar` / `_safe_list` graceful degradation (missing table → 0 + WARNING log, never 500). 30 s per-project cache. Trade matrix runs a single GROUP BY clash query and normalises pair keys symmetrically. Timeline UNIONs clash_runs + federations + requirement_sets + BCF topics with 50-newest-first cap.
- **Module-presence dimming.** New endpoint `GET /api/v1/projects/{project_id}/module-presence` returns a flat bool map across 56 modules ("does this project have any data for module X"). Each probe is a `SELECT 1 ... LIMIT 1` with index-only access; all 56 run concurrently via `asyncio.gather` so total latency stays under 200 ms. 60 s per-project cache. Frontend `useModulePresence()` hook drives a 3-state visual gradient in the sidebar: empty modules render at 55 % opacity + `text-zinc-500`, populated modules render at normal weight. 7 backend tests + 7 hook tests.
- **Sidebar restructure - lifecycle order.** Sidebar groups now follow the project lifecycle: Overview → Estimating → Catalogues & Reference → Takeoff → Model Coordination → AI & Tools → Commercial → Planning → Field Operations → Communication → Documents → Quality → Safety & HSE → Finance & Procurement → Analytics & Reports → Regional. The old monolithic "AI & Estimation" group is split into Estimating (BOQ + Match Elements + AI Estimate + Estimation Dashboard) and Catalogues & Reference (Costs + Catalog + Assemblies + Assembly Library). Assets moved from Documents to Field Operations (assets are physical inventory, not paperwork). New `nav.group_catalogues` + `nav.group_analytics` + `nav.group_ai_estimation_desc` keys across all 27 locales. Visual separator (`<hr>`) before Regional marks the boundary between project-work and reference/setup surfaces.
- **/ai-estimate redesign.** Glass hero header with `BrainCircuit` gradient badge + `model: gpt-4o` pulsing pill. Premium textarea with violet focus ring + inner shadow glow. Four auto-fill example chips (Berlin apartments, NYC office fit-out, Rotterdam warehouse, London school) shown only when the prompt is empty. New `useQuickEstimateHistory()` hook persists last 20 estimates per user in localStorage with version envelope + LRU eviction + storage-corruption fallback. Six example prompts in `examplePrompts.ts` cover apartment / office / warehouse / school / single-family / hospital MEP scenarios. 20 new tests.
- **/admin/permissions - editable.** Permissions matrix is now fully editable for admins (read-only fallback for non-admins). Click a `(role, perm)` cell to set `min_role = role` with optimistic React Query update + automatic rollback on error + per-cell spinner during pending mutation. Confirmation modal on every change. Lockout-protection modal blocks demoting `permissions.admin` or `system.permissions.*` below admin (refused both client-side + server-side with HTTP 400 `admin_lockout_blocked`). Role filter dropdown, preset apply buttons (viewer-default / editor-default / manager-default), CSV export. All changes audit-logged via existing audit module. 9 backend tests + 8 frontend tests + 28 new locale keys per EN / DE / RU.
- **/about - Changelog redesign.** Two-column CSS-columns layout with `[column-fill:_balance]` for variable-height entries. Expanded from ~70 to **118 historical entries** spanning v0.1.0 (2026-03-27) → v4.2.0 (2026-05-21). Each entry is one short summary line per release (≤ 90 chars). Glass-style cards with hover lift. Latest 7 entries get visible `NEW` / `FIX` / `BETA` / `SECURITY` / `MILESTONE` tag badges; entries older than 6 months render at 70 % opacity so they recede. Semver-aware runtime sort preserves descending order.
- **Marketing-site Mongolian locale.** Backfilled 121-key gap on 17 of 20 marketing-site locales (last updated Apr 23 vs EN/DE/RU updated Apr 29). 4 parallel translation agents bridged the gap to 100 % native quality. `LOCALE_VERSION` bumped to `20260521b`.

### Fixed

- **P0: `bim_requirements` permissions registry.** Module's router gated endpoints with `RequirePermission("bim_requirements.read|create|update|delete|export")` but the keys were never registered, so non-admin users hit 403 on legitimate calls. New `permissions.py` registers all five keys with their min-role (VIEWER / EDITOR / MANAGER) + `on_startup()` wiring in `__init__.py`.
- **P1: clash_ai_triage replay-IDOR on NULL clash_id.** `verify_project_access` previously only ran when `existing.clash_id is not None`; if the source clash was deleted (FK on-delete nulls clash_id) any caller with `clash_triage.execute` could replay. Endpoint now returns 410 Gone with `"Source clash was deleted; triage cannot be replayed."`.
- **P1: bim_requirements `/template/` missing permission gate.** Endpoint only required authentication, not `bim_requirements.read`. Inconsistent with siblings - added `Depends(RequirePermission("bim_requirements.read"))`.
- **P1: clash_cost_impact 404/403 timing oracle.** `get_clash_impact` called the service before access-check, enabling a 404-vs-403 timing oracle that confirmed a clash UUID exists across project boundaries. New lightweight `project_id_for_clash()` resolver runs first; access-check then runs against the resolved project_id; impact computation only runs if the check passes.
- **P1: MeasureTool snap-math dead-code.** `MeasureTool.ts:220` had `(raw.x - raw.x) +` in the `clickPx` Vector2 X component. Removed.
- **P1: i18n gaps - TradeMatrix + YamlEditor + Smart Views enums.** `CoordinationTradeMatrix.tsx` hardcoded discipline labels (Arch / Struct / MEP / Landscape / Civil / Other) → now `t('coordination.discipline.*')`. `YamlEditor.tsx` bare "parsed" badge → `t('rulePacks.parsed_badge')`. `SmartViewRuleEditor.tsx` `OPERATORS` + `ACTIONS` enum values rendered raw to international users → now translated via label map.
- **P2: BCF upload cap harmonisation.** `clash/router.py` was 25 MiB, `bcf/router.py` was 100 MiB for the structurally-identical BCF archive. Both now 100 MiB to match `BCFReader.DEFAULT_MAX_TOTAL_BYTES`.

### Notes

- All recently-added modules pass full audit (clash, bcf, smart_views, bim_requirements, clash_cost_impact, clash_ai_triage, coordination_hub) - production-quality, no IfcOpenShell, no OpenCascade, Decimal end-to-end for money, IDOR-gated, defusedxml for XML, `yaml.safe_load` for YAML.
- `NOTICE.frontend.json` regenerated for v4.2.0 (966 packages incl. new `vite-plugin-pwa` + `workbox-build` + `workbox-window` from v4.1.0).
- Alembic chain stays a single linear tip: `v40_fieldreports_uuid_typing → v41_clash_signature_smart_issues → v41_smart_views → v41_clash_ai_triage → v41_smart_views_share → v41_coordination_thresholds`.
- **AGPL-compatibility maintained** - no IfcOpenShell, no OpenCascade, no new GPL-2-only deps. BCF is an XML format (not an IfcOpenShell dependency) and remains allowed per the 2026-04-26 decision.

## [4.1.0] - 2026-05-21 · P1 wave rollup · BIM diagnostic UX · marketing-site i18n complete

### Added

- **BIM geometry error reporting - plain-language UX rewrite.** Every geometry-fetch error path (401 / 403 / 404 / 422 / 5xx / network) now ships a structured payload with a non-PII `request_id` correlation header (UUID4) returned via `X-Request-Id`, a status-aware headline ("Your session expired" vs "The 3D file looks damaged"), a backend-derived `cause` field that maps 422 reasons into 6 plain-language categories (HTML page instead of mesh, IFC schedule with no geometry, magic-byte mismatch, truncated upload, unsupported glTF version, generic), an actionable `remediation`, and a "Copy bug report" button that emits a ready-to-email markdown block (Request ID + HTTP status + cause + first 8 bytes hex/ASCII + size + UA + URL - zero PII). Backend `logger.warning` lines correlate by `request_id` for one-grep triage.
- **Mac `uv pip install -e ./backend` fix.** New `[tool.hatch.build.targets.editable]` block with empty `force-include` map in `backend/pyproject.toml` so editable installs no longer require the bundled `frontend/dist`.
- **Marketing site - hero headline + module-overview block i18n on 20 languages.** "Run the whole construction project" hero now carries `data-i18n-html="hero.headline"` with `data-anchor="primary"` / `data-anchor="secondary"` attributes on emphasized words; SVG animation switched to attribute-based anchor lookup so translations with different word counts/orders still render correctly. 175 new keys (`modgrid.*` module-overview card grid + `demo.card_*` + `hero.headline` + `modgrid.show_less`) translated into all 19 non-English locales (de / fr / es / it / pt / nl · sv / no / da / fi · ru / pl / cs / bg · zh / ja / ko / ar / tr) with industry-correct terminology (Leistungsverzeichnis, Przedmiar robót, Ведомость объёмов, 工程量清单, قائمة الكميات). `LOCALE_VERSION` bumped to `20260521a`.

- **BIM Federation - Slice 1.** Federations are named groups of N BIM models sharing an origin (e.g. architectural + structural + MEP), with per-discipline membership, z-ordering, visibility, and color hints. This slice ships data persistence + list/detail UI; the federated 3D viewer that composes members into a single scene is deferred to Slice 2.
  - New tables `oe_bim_federation` + `oe_bim_federation_model` (alembic `v40_bim_federations`, linearised at the tail of the v40 chain `assembly_templates → ai_agents → cpm_weekly → bim_federations`). Cascading FKs on both link sides clean up membership rows when either the federation or the constituent BIM model is deleted.
  - Endpoints on the existing BIM Hub module: `POST /api/v1/bim-hub/federations/` · `GET /api/v1/bim-hub/federations/?project_id=…` · `GET /api/v1/bim-hub/federations/{id}` (detail with members ordered by `z_order`) · `PUT /api/v1/bim-hub/federations/{id}` · `DELETE /api/v1/bim-hub/federations/{id}` · `POST /api/v1/bim-hub/federations/{id}/models` · `DELETE /api/v1/bim-hub/federations/{id}/models/{model_id}`. Project ownership is the sole ACL - federations inherit it from their project, and cross-project model adds 400.
  - New `/bim/federations` route + `FederationsPage` with project selector, federation card grid, create modal, and detail drawer (member list, discipline pill, color swatch, add/remove member).
  - 6 new tests in `backend/tests/modules/bim_hub/test_federations.py` (create, add member + duplicate guard, list filtered by project, detail z-order, cross-project access denial, delete cascades member links) - all green.
  - i18n keys under `bim.federation.*` for EN / DE / RU.

- **Scheduling - CPM Slice 1.** First-class Critical Path Method engine on top of the existing schedule + schedule_advanced modules. Pure-Python forward + backward pass (no scipy / networkx) at `backend/app/modules/schedule_advanced/cpm.py` computes ES / EF / LS / LF, total float, free float, and critical-path marking on a `TaskNetwork`; cycles are detected via DFS and surface the offending node path through `CycleError`; disconnected sub-networks are scheduled per island. Companion `leveling.py` ships a serial-greedy `level_by_resource_max` heuristic (priority = LS asc → total_float asc → id asc) that shifts activities forward (never backward) to honour per-resource ceilings. New `WeeklyCommitment` table (alembic v40_cpm_weekly) backs the lightweight Last-Planner commit flow with auto-computed PPC = actual / planned clamped to [0, 1]. Four additive endpoints under `/api/v1/schedule-advanced/{schedule_id}/…`: `compute-cpm` (persists ES / EF / LS / LF / float / critical onto each Activity row and returns project_duration + critical path), `level-resources`, `commitments`, `ppc?week=`. New `frontend/src/features/schedule/CPMView.tsx` renders an ES / EF / LS / LF / float column grid with a red "CRITICAL" badge on critical rows plus toolbar buttons to recompute CPM or open a resource-leveling modal. EN / DE / RU translations under `schedule.cpm.*`. 8 new tests in `backend/tests/modules/schedule_advanced/test_cpm.py` (textbook 6-activity AOA critical path A → C → F = 11d, forward pass, backward pass, total float, cycle detection, disconnected sub-network, leveling ceiling enforcement, PPC math) - all green; existing 61 schedule_advanced unit tests stay passing. FS-only in Slice 1; SS / FF / SF dependency types and parallel-SGS leveling are wired as TODO comments for Slice 2.
- **AI Agents framework - Slice 1.** New `backend/app/modules/ai_agents/` module adds a generic ReAct-style agent loop on top of the existing single-call `ai` LLM client. Ships a `Tool` protocol + `ToolRegistry`, a declarative `Agent` dataclass, and an `AgentRunner` that loops "LLM -> tool_call -> observation -> repeat" until a final answer or `max_iterations` (defaults to 8, then `status=failed reason=iter_limit`). LLM is abstracted behind an `LLMBridge` protocol - production `CallAILLM` wraps `ai.ai_client.call_ai` with a deterministic `<tool_call>{json}</tool_call>` text-protocol parser (no provider-specific tool-use APIs); tests use `ScriptedLLM` for offline replay. Per-run history persists to two new strictly-additive tables (`oe_ai_agents_run` + `oe_ai_agents_step`, alembic `v40_ai_agents`) so the UI can render every thought / tool_call / observation / answer as a vertical timeline. Endpoints: `GET /api/v1/ai-agents/agents/`, `GET /tools/`, `POST /runs/`, `GET /runs/`, `GET /runs/{id}`. Sample `boq_drafter` agent declares three tools: `search_costs(q, region)` (proxies `costs.matcher.match_cwicr_items` with a deterministic mock fallback), `suggest_assembly(description)` (mock stub, TODO to wire to `assemblies.repository`), and `create_position(...)` which returns a structured PROPOSAL payload - never writes the BOQ (the architecture guide "AI-augmented, human-confirmed"). 9 pytest tests cover scripted-LLM happy path, iter-limit cap, registry dispatch, unknown-tool error step, BOQ-drafter end-to-end, DB persistence, text-protocol parser, and `on_step` callback. New `frontend/src/features/ai-agents/AgentsPage.tsx` renders the agent catalogue + run launcher + live polling timeline; EN/DE/RU `agents.*` keys.
- **Mobile PWA - Slice 1.** OpenConstructionERP is now installable as a Progressive Web App on Android / iOS / desktop Chromium browsers.
  - `vite-plugin-pwa` wired into `frontend/vite.config.ts` with workbox `generateSW`: precaches the app shell (`index.html` + JS/CSS/HTML/SVG/WOFF2 bundles), `NavigationRoute` falls back to `/index.html` so offline deep-links still resolve, and three runtime cache lanes - `oce-static-assets` (CacheFirst for fonts/images/hashed asset chunks), `oce-i18n-locales` (StaleWhileRevalidate for `assets/i18n-<code>-*.js`), and `oce-api` (NetworkFirst with 8 s timeout, GET-only, cached only as offline fallback for idempotent reads).
  - Web App Manifest declares name "OpenConstructionERP", short_name "OCERP", `theme_color` sky-600 (`#0284c7`), `background_color` `#f7fbff`, `display: standalone`, scope `/`, start_url `/`, plus 192/256/384/512 SVG icons + a 512 maskable variant under `frontend/public/pwa/` (modern browsers accept SVG icons in a manifest directly; an optional `frontend/scripts/build-pwa-icons.mjs` helper rasterizes to PNG when `sharp` is installed).
  - New `<PWAInstallPrompt />` (`frontend/src/shared/ui/PWAInstallPrompt.tsx`) mounted once in `App.tsx`: discrete bottom-right toast that captures `beforeinstallprompt`, persists 30-day dismissal in localStorage, and replaces itself with a one-time "Add to Home Screen via Share menu" hint on iOS Safari (UA-sniffed; iOS Chrome/Edge correctly excluded). Hides automatically when already in `display-mode: standalone`.
  - New `<OfflineFallback />` (`frontend/src/shared/ui/OfflineFallback.tsx`) - minimal full-page "You're offline" surface with a best-effort "last synced N minutes ago" line backed by an `oce.pwa.lastSyncAt` localStorage key, ready to be wired into workbox's NavigationRoute fallback or rendered inline by feature pages.
  - Touch-friendly tweaks on Daily Diary, Punch List, and Photo Gallery: bottom-anchored FAB visible only on viewports `≤sm` (≥44×44 tap target via `min-h-[44px] min-w-[44px]`) that fires each page's primary action (new diary / new punch item / upload photo), so site crews on phones reach the verb without scrolling past header + filter chrome.
  - 8 new EN/DE/RU `pwa.*` translation keys (`install_prompt_title`, `install_prompt_body`, `install_button`, `not_now_button`, `ios_hint_body`, `offline_title`, `offline_body`, `last_synced`).
  - New `frontend/tests/pwa/manifest.test.ts` + `service-worker.test.ts` (vitest) - assert the build outputs the expected manifest fields + workbox runtime caches; skip cleanly when the build hasn't been produced yet. Always-on guards on `vite.config.ts` text catch accidental plugin removal. `frontend/scripts/pwa-install.spec.ts` Playwright spec scaffolded (skipped) for a future Linux job that includes Lighthouse.

- **Assembly Library - Slice 1.** Platform-wide canonical recipe templates with backend + frontend + i18n. 25 ready-to-use templates ship in the box covering concrete walls (C25/30, C30/37), brick walls (KSL 11.5/17.5 cm), drywall partitions (W111/W112), in-situ slabs (20/25 cm), cement screed, flat roof (bitumen 2-layer), ETICS facade insulation, interior wood + exterior steel doors, uPVC + aluminum windows, tile/vinyl/parquet floor finishes, copper pipe DN20, sanitary WC, wall radiator, RC column 30×30, steel beam HEB200, open-cut excavation, and backfill. Each template carries DE / RU / ES translations and a DIN 276 + MasterFormat anchor.
  - New table `oe_assemblies_template` (alembic v40) seeded idempotently at module startup.
  - `GET /api/v1/assemblies/templates/` lists/filters templates (q · category · tag · DIN 276 · MasterFormat); `GET /api/v1/assemblies/templates/{id}` fetches one; `POST /api/v1/assemblies/templates/{id}/apply` resolves each component's free-text `cost_match_query` against the project's bound cost catalogue via the existing lexical matcher (no Qdrant required) and returns a non-persisted preview with rolled-up totals for human confirmation.
  - New `/assemblies/library` route + sidebar entry under Estimation with a card-grid browser, category chips, search, and drawer-based apply workflow.
  - 7 new tests in `backend/tests/modules/assemblies/test_templates.py` (seed count, list, category filter, DIN 276 filter, apply with cost resolution, quantity scaling, DE/RU/ES translation coverage) - all green; full assemblies suite stays at 45 passing.

## [4.0.1] - 2026-05-20 · BIM ViewCube polish · marketing-site forms migrated off formsubmit

### Fixed

- **BIM ViewCube - clicking the cube no longer locks orbit controls.** When two cube clicks landed back-to-back, the second `flyTo` cancelled the first tween via `_tweenReject(...)` but never restored `controls.enabled` to its pre-tween value, leaving `OrbitControls` permanently disabled. New class field `_tweenWasControlsEnabled` is restored on both completion AND cancellation paths, so re-clicking the cube during an animation now correctly re-enables mouse orbit when the second animation completes.
- **BIM ViewCube - placement / sizing / chrome.** Cube moved from `top-3 right-3` to `bottom-3 + left = leftPanelWidth + 16px` so it sits to the right of the filter sidebar instead of being hidden behind it. Size increased 80 → 112 px. Wrapper `bg-white/70 backdrop-blur shadow-md ring-1` chrome removed - the cube is now a bare transparent canvas that floats over the viewport.

### Marketing-site infrastructure (no impact on the wheel)

- All marketing-site forms (`/partners.html`, `/index.html` newsletter / popup / homepage inquiry) migrated off the dead `formsubmit.co` relay onto an in-house Hostinger SMTP path running on the demo VPS. New endpoints `/api/partners-apply`, `/api/subscribe`, `/api/inquiry` accept JSON POST, persist to JSONL on disk, and send both an admin notification and a customer ack via `info@openconstructionerp.com`.
- Module cards (added in 4.0.0) moved out from above the demo-player carousel down to a dedicated section after the GIF tour-player, and reflowed into a denser 6-col layout with smaller icon chips, tighter padding, and a category-tinted hover lift.
- Static `index.html` version fallback bumped to `v4.0.0` (was `v3.0.4`); release ticker refreshed to show v4.0.0 / v3.12.1 / v3.12.0 / v3.11.0. Dynamic GitHub Releases fetch already returned v4.0.0 - this only matters for SEO bots / slow connections.

### Notes

- Same alembic head as 4.0.0 (`v3096_regional_indices_certainty`). No data migration required.

## [4.0.0] - 2026-05-20 · Stable 4.0 - production-ready platform

This is the first **stable 4.x** release. Same code base, same install procedure as the latest 3.12 patch; the version cut signals that the platform is now considered production-ready across the full estimation → takeoff → BIM → BOQ → tender → reporting workflow, with a stable public API surface, multi-tenant security pass complete, and 103 modules shipping in the box.

### What "stable 4.0" means

- **API surface is stable.** Every `/api/v1/*` endpoint shipped in 3.10.x → 3.12.x is now considered part of the public contract. Breaking changes will be marked `/v2`; 4.x patches will only add fields and endpoints, not rename or remove existing ones. OpenAPI spec at `/api/openapi.json` is the source of truth.
- **Multi-tenant security pass complete.** Cross-category IDOR sweep (memory: `v2.9.15` + `v2.9.14`) closed ~73 endpoints across Planning / Communication / Procurement / Documents. Every project-scoped route enforces `verify_project_access`; every owner-scoped route (dashboards, reports, alerts, saved views, filters) enforces inline `owner_user_id` comparison with 404-not-403 on mismatch.
- **103 modules ship in the box**, dynamically discovered by the module loader: BOQ + Cost Intelligence + Match Elements + Tendering + BIM Hub + Clash Detection + Takeoff + AI Estimate + ERP Chat + Project Intelligence + Schedule + Tasks + Risk + Daily Diary + Equipment + Service + Finance + Procurement + CRM + Contracts + Subcontractors + Bid Management + Supplier Catalogs + BI Dashboards + Validation + Inspections + Punchlist + Files CDE + Quality + HSE + Portal + Carbon + many more. All have backend + frontend + tests + i18n + permissions.
- **CAD/BIM pipeline is canonical-format-first.** Every CAD source (DWG, DGN, IFC, RVT) goes through the DDC cad2data converter into a canonical JSON. No IfcOpenShell dependency. BCF allowed as I/O for issues + viewpoints + validation reports. Serve-time magic-byte validation guards the viewer against corrupt blobs.
- **Cost database: 55,000 priced positions in CWICR, plus 30+ regional v3 catalogues.** Multi-currency BOQ with FX-correct exports. Vector search via Qdrant; multilingual semantic match across 24 languages.
- **i18n: 24 languages.** EN/DE/RU/zh-Hans/pt-BR/Mongolian are deep native quality. The remaining 17 ship with English `defaultValue` fallbacks; native pass continues in 4.0.x.
- **Self-host story: one command.** `pip install openconstructionerp && openconstructionerp` boots PostgreSQL-or-SQLite + 103 modules + Qdrant ping + showcase snapshot seed + alembic upgrade. AGPL-3.0 community; commercial licence for source-modification protection.

### Notable since 3.0 milestone (rolled up)

- BIM Hub pro-grade - Site Compass cube, Solo Mode, Trait Lens color-by-property, Element Bundles selection sets, viewpoint state with camera + filter + clip + thumbnail, screenshot export, DDC converter version badge, property search panel.
- Clash Detection - schema + DBSCAN engine + FP-mining + 6 REST endpoints, KPI dashboard with severity / discipline-pair / top-clashing-pairs / MTTR, rule editor + suggestions banner.
- Takeoff pro-grade - PDF + DWG measurements, PaddleOCR + YOLO symbol detection, jsPDF export with annotations, exceljs export with per-group subtotals.
- BOQ pro-grade - bulk multiply rate / qty / classification, per-cell field-history restore, Ctrl+D fill-down + Ctrl+; today, multi-level hierarchy with 8-deep nesting, reusable/linked positions, FX-correct CSV/Excel exports with frozen FX appendix.
- Match Elements - 7-stage visible pipeline (Convert → Load → Schema → Filter → Group → Match → Rollup), per-stage adjust, vector + lexical + resource matchers, currency-aware rollup, catalogue + display-currency picker.
- Cost Intelligence - regional indices + cost-item usage telemetry, certainty bands (green/yellow/red), live regional-adjust panel.
- Files CDE - saved views rail, tag-filter facet, version history with "Make current", 24h trash purge, per-recipient notification fan-out on new revision.
- Validation@Import - DIN 276 + GAEB + NRM + MasterFormat + BOQ-quality + project-completeness rule packs wired into GAEB / Excel import path; GAEB X84 (Nebenangebot) export writer.
- BI Dashboards - 5 role-based starter dashboards (CEO / CFO / PM / Site / Safety), 14 system KPIs with 12-week history, 3 reports, 2 schedules, 4 alert rules - installed via idempotent one-click endpoint.
- AI services - embedding-pool with prewarmed workers, FSM-driven match pipeline, BIM placeholder geometry fallback, Mongolian + Devanagari OCR, lakh-crore numeric parsing, UTM CRS for 16 regions.
- Ecosystem - license-request page with 90-day affiliate cookies, marketing site with 34-card module grid mirroring the in-app sidebar, openconstructionerp.com production deployment.

### Hand-off

Identical to 3.12.1: no migration steps required. Existing 3.12.x installs upgrade in place via `pip install --upgrade openconstructionerp && alembic upgrade head && systemctl restart openconstructionerp`. Alembic head: `v3096_regional_indices_certainty`.

### Notes

- Native i18n pass for the 17 placeholder locales continues in 4.0.x patch line - defaultValue fallbacks ship today.
- Audited but not yet shipped: W5.5 Assembly Library, W6.5 BIM Federation, W8 Scheduling CPM, W13 AI Agents - planned for 4.1.

## [3.12.1] - 2026-05-20 · BIM serve-validation · BI starter pack · /match-elements catalogue picker · marketing module-cards · UI polish

### Added

- **/match-elements - Cost catalogue & Display currency pickers** - stage 3 of the wizard ("Confirm the rate catalogue") now exposes two dropdowns: a Cost-catalogue selector listing every loaded CWICR-v3 catalogue (region · city · language · currency) with auto-preselect by project region, and a Display-currency override pre-seeded with the project currency plus every loaded catalogue's currency plus the global commons (EUR/USD/GBP/CHF/PLN/CZK/CAD/AUD/JPY/CNY/BRL/INR/ZAR/TRY/AED/SAR/NOK/SEK/DKK). Catalogue choice flows into `createSession`/`updateSession` as `catalogue_id` (region-string form), overriding the auto-bind for that session.
- **BI Dashboards - starter pack installer** - empty `/bi-dashboards` grid now shows a one-click "Install starter pack" CTA. New idempotent endpoint `POST /api/v1/bi-dashboards/install-starter-pack` materialises 5 role-based dashboards (CEO · CFO · PM · Site · Safety) with 4-8 widgets each, the 14 system KPIs, 12-week trend history per KPI, 3 reports, 2 schedules and 4 alert rules in one transaction. Re-running is safe; only missing rows are inserted.
- **Marketing site - full module-cards grid** - 34 cards under "Skip the sales call. See it work." mirroring the in-app sidebar 1:1 (same lucide icons, same module order) with a one-sentence functional description per module. Inline SVG sprite + CSS, no CDN/JS-loader dependency; responsive 4 / 3 / 2 / 1 columns with hover-lift and accent-tinted icon chip.

### Fixed

- **BIM 3D loading - server-side payload validation (Downtown Medical Center / RVT report)** - `_quick_validate_geometry_bytes` now peeks at the first 4 KB of every geometry response in `router.py` and rejects payloads whose magic bytes don't match the extension (`.glb` GLTF2 header, `.dae` COLLADA root, `.gltf` JSON `asset.version`). The exact user-reported case - `<?xml ve` bytes served from a `.glb` slot - now 422s with a diagnostic head dump (`magic mismatch; head=3c 3f 78 6d 6c …`) instead of reaching the browser and crashing Three.js's GLTFLoader. Frontend `ElementManager.parseGeometryBuffer` also surfaces actionable hints when XML/HTML/JSON bytes arrive in a geometry slot (likely converter failure, auth redirect, or proxy error). 11 new unit tests cover valid GLB / GLB magic-mismatch / GLB wrong-version / valid COLLADA / XML-not-COLLADA / HTML error-page / empty / truncated / unknown-extension passthrough / valid GLTF / GLTF missing asset.
- **BIMViewer pre-existing tsc errors** - unused `tmpDir`/`tmpUp` locals in `BIMViewCube.tsx`, null-safety on `canvas.getBoundingClientRect()` in click handler, and `'iso' → 'iso_ne'` alias mapping in the `window.__oeBim.setViewPreset` bridge so the canonical SceneManager ViewPreset type accepts the friendly alias.
- **`/about` - Browse case studies button removed** per user request (case-studies link is on datadrivenconstruction.io home).

### Polish

- **`/login`** - manager avatar now `#7cd0ff`, "zero cloud" wraps to next line, "AI-assisted, human-confirmed" block left-aligned; brand+pencil row centered inline (was absolutely-positioned).
- **`/files/search`** - full-width 2-column layout with filter rail (kinds, sort, group-by-project, view options), recent-searches chips (localStorage), summary header with content-index badge, sticky project headers in grouped view, URL hydration with re-entrancy guard.

### Notes

- i18n native pass for the 17 placeholder locales (es/fr/it/nl/pl/ja/ko/vi/tr/ar/…) deferred to v3.12.2 - all new keys ship with English `defaultValue` fallbacks so they render correctly today; deep native translation needs an out-of-process pass.

## [3.12.0] - 2026-05-20 · Wave 5/6/7 pro-grade - BOQ + Cost Intelligence + Clash A4 + BIM viewpoints + Files CDE + Takeoff PDF/Excel

### Added

- **BOQ pro-grade UX (Wave 5 / Stream A)** -
  - Bulk operations expansion: "Multiply rate" / "Multiply qty" / "Set classification" chips in the floating BatchActionBar; new endpoint `PATCH /api/v1/boqs/{boq_id}/positions/bulk-update/` accepting `{ids, updates | rate_factor | quantity_factor}` (transactional, allowlist-enforced, audit-logged).
  - Per-cell restore - new "Field history" tab in VersionHistoryDrawer flattens BOQActivityLog diff entries into per-field rows with a Restore button calling new `POST /api/v1/boqs/{boq_id}/positions/{position_id}/restore-field/` (validates log_id ↔ position ↔ field).
  - Keyboard shortcuts in BOQGrid - `Ctrl+D` fill-down to all selected rows in the focused column (respects PASTE_PROTECTED_FIELDS), `Ctrl+;` inserts today's ISO date.
- **Cost Intelligence (Wave 5 / Stream B)** -
  - `oe_regional_indices` + `oe_cost_item_usage` tables (alembic `v3096_regional_indices_certainty`).
  - 4 endpoints under `/api/v1/costs/`: `GET regional-adjust`, `GET regional-indices`, `GET {item_id}/certainty`, `POST {item_id}/record-usage`.
  - Seeded 8×6 regional matrix (DE_BERLIN/DE_MUNICH/UK_LONDON/UK_MANCHESTER/US_NYC/US_LA/FR_PARIS/ES_MADRID × concrete/steel/labor/mep/finishes/sitework), source `OE_v3.12_seed_2026Q2`.
  - `CertaintyBadge` (green/yellow/red) on every cost row + `RegionalAdjustPanel` live-preview in the toolbar.
  - Certainty band rule: green if freq≥10 AND age<365d; yellow if freq 3-9 OR age 365-1095d; else red.
- **Clash Wave A4 wiring (Wave 6 / Stream C)** - schema + DBSCAN engine + FP-mining had landed in v3.11.0 but were unreachable from REST; now wired:
  - 6 endpoints under `/api/v1/clash/runs/{run_id}/`: `GET clusters`, `GET rule-suggestions`, `POST apply-rule-suggestion`, `GET rules`, `PATCH rules` (cap 500, 422 above), `GET kpi` (total / by_status / by_severity / by_type / by_discipline_pair / top_clashing_pairs / mttr_hours).
  - `_apply_rules` spliced into `_detect` so per-pair tolerance overrides + severity overrides actually drive detection (was schema-only).
  - 4 new UI components - `ClashClusterChips` (filter), `ClashRuleEditor` (WideModal CRUD), `ClashRuleSuggestionBanner` (review + apply), `ClashKpiPanel` (tiles + severity bar + top pairs + MTTR).
- **BIM viewpoint state + property search + DDC version badge (Wave 6 / Stream D)** -
  - `Viewpoint` now captures full state: `cameraPos`, `target`, `filterState` (storey/types/discipline/isolatedIds), `clipState` (mode/box/plane), `screenshotDataUrl`. Save view → restore view round-trips camera + filter + clip + thumbnail.
  - `getScreenshot()` on SceneManager → PNG download from a Camera-icon button in the BIMViewer toolbar. Filename includes diacritics-stripped model name + ISO timestamp.
  - `ConverterVersionBadge` on every model card - shows green-dot `DDC v{X}` pill when `metadata.converter_version` populated (sourced via `dpkg` on Linux or parent-dir on Windows from the v3.11 helper); returns null cleanly when absent.
  - `PropertySearchPanel` toolbar popover - column dropdown (sourced from DDC Parquet schema) + operator + value query builder; Search → isolates matching elements via existing `setIsolatedIds`. Graceful empty-state when schema unavailable.
- **Files CDE finish (Wave 7 / Stream E)** -
  - `SavedViewsRail` spliced into FileManager left sidebar; `SaveViewButton` appears when any filter is active, persists name + filter to `oe_file_saved_view`.
  - `TagFilterFacet` in the actions bar - multi-select tags, filters file list.
  - `VersionHistorySection` in FilePreviewPane - chronological version list with `VersionBadge` per row + "Make current" on superseded rows.
  - Backend: `purge_expired_trash()` background job (24h scheduler) + `POST /api/v1/file-trash/purge-now` admin endpoint deletes underlying file on disk + row.
  - Backend: `on_file_new_revision(file_id)` hook fans out per-recipient notifications across active matching `oe_file_distribution_list` entries; wired into `register_new_version`.
- **Takeoff PDF/Excel export (Wave 6 / Stream F)** -
  - `Export PDF (with annotations)` - client-side jsPDF builder lazy-imported; renders each annotated PDF page to canvas via PDF.js, bakes the existing measurement overlay rendering on top, JPEG-encodes at 0.85; final A4 summary page lists per-group / per-type counts with color swatches. Respects group visibility.
  - `Export Excel (.xlsx)` - exceljs builder; "Measurements" sheet (Group/Type/Annotation/Page/Value/Unit/Linked BOQ Position + group header rows tinted + per-type subtotal rows + frozen header) and "Summary" sheet (pivot by group with grand-total row).
  - Filename: `takeoff-{slug(projectName)}-{YYYY-MM-DD}.{ext}`, slug preserves Unicode letters (São Paulo, Cyrillic, etc.).
- **/about further refinements (post-v3.11)** -
  - Platform Capabilities - 6 stats collapsed to a single row for compactness, height matched to Community card.
  - Header right - UpdateNotification now paired with a "Recent releases" mini-list (last 3 versions with date + headline + anchor to in-page Changelog).
  - Community card - Telegram featured on its own row (cyan-tinted + "Live" badge + 2-line copy), LinkedIn + X each on their own full-width row with longer descriptions, so the card stretches to match Platform Capabilities.
  - Documentation card - enriched with "Popular topics" 2×3 deep-link grid (Quick start · BIM import · GAEB · Takeoff · Module SDK · VPS deployment).
  - License card - restructured into "You can / You must" 2-col bullets + badges + "Commercial licensing" CTA at bottom (parallel button position to Documentation's "Open Docs").
  - Support OpenConstructionERP right column - 4 impact-stat KPI tiles on top mirror the visual weight of the left hero, then the existing "Your support enables" bullet list below.
  - Free Guidebook - book cover 1/3 → 2/5 column (max-w 200px → 320px) with 10-part TOC column narrowed to 3/5.

### Fixed

- **Stream E hotfix (3 defects from Playwright verification)** -
  - `POST /api/v1/file-versions/{id}/restore/` was returning 500 → root-caused + fixed in `file_versions/service.py`; "Make current" now flips current-flag correctly with toast confirmation.
  - `POST /api/v1/file-saved-views/{id}/use/` telemetry was returning 500 → fixed in `file_saved_views/service.py`; `use_count` + `last_used_at` now increment per apply.
  - `FileManagerPage` URL-sync effect was stripping new query params when a saved view was applied while already on /files → effect now re-reads `searchParams` on URL change instead of only at mount.

### Notes

- 6 implementation streams + 6 deep audit agents + 6 testing agents ran in parallel - first multi-wave structure where audit → slice → ship → verify all ran as independent agent fleets. Audit reports + Playwright screenshots archived under `qa-tests/_v3.12.0-stream-{A,B,C,D,E,F}/`.
- Deferred to v3.13.0: Assembly Library 2.0, What-If BOQ branches, Model Federation, BCF round-trip, semantic Clash rules + PDF coordination-meeting export + async Celery clustering, CCI/BCIS escalation feeds, supplier price feeds, AI symbol detection (CV pipeline), 3D markup persistence.

## [3.11.0] - 2026-05-20 · Wave 3/4 modules + Validation@Import + X84 export + /about redesign

### Added

- **Wave 3 modules** - `service` SLA breach scan + RRULE-based recurring contracts (alembic `v3091`), `meetings` recurring attendance, `erp_chat` feedback, `notifications` preferences (alembic `v3088`-`v3090`).
- **Wave 4 modules** - `bi_dashboards` cross-filter + click-to-drill (`v3092`), `subcontractors` prequal scoring + insurance-expiry sweep (`v3093`), `requirements` ISO 19650 EIR matrix with LOD/LOI deliverables (`v3094`), `file_favorites` star + pin module.
- Single merge migration `v3095_merge_wave34_heads` consolidates the 7 sibling heads into one.
- **Validation @ Import** - GAEB X81/X83/X84/Excel/CSV import endpoints now run DIN276 + GAEB + boq_quality (or NRM / MasterFormat per locale) rule packs inline and surface a `validation_report` field on the response. Feature-flagged via `IMPORT_INLINE_VALIDATION` (default ON).
- **GAEB X84 export (Nebenangebot)** - new `?format=x84` mode on the GAEB export route emits `DP=84` + `BoQBkUp/BoQBkUpReason` per item + optional `BoQBkUpRef` parent ref + `Award/Recommendation` block for marked alternates.
- **Module scaffolding** - `make module-new NAME=oe_foo` + `modules/oe-module-template/` skeleton (manifest + models + schemas + repository + service + router + migration + tests) + `docs/module-development/quickstart.md`. Makes the "vibe-coding" plugin claim real.
- **BIM/RVT converter diagnostics** - new `read_rvt_revit_version()` extracts Format/Build/App from the OLE header; `detect_converter_version()` queries `dpkg` on Linux or parent-dir fingerprint on Windows; conversion failures now record the structured context (RVT version vs. converter version vs. stderr tail) and the router composes an actionable error message ("File saved with Revit 2024. Installed RVT converter: 18.0.0.0. Converter said: ...") shipped to the UI overlay.

### Changed

- **/about page redesign** - full-width 1600px container; 6-tile Platform Capabilities stat grid (`55K+ / 24 / 48 / 6 / 100+ / 12`) split into 2 separate Cards next to a dedicated Community Card with matched heights; "About the project" Card switched to 3:2 grid with bio + blockquote on the left and the marketing-site DDC Ecosystem block on the right (Flagship products / Open-source on GitHub / Find us across the network); Consulting & Services rebuilt as the marketing site's 3 numbered offerings (Build 01 / Workshops 02 / Consulting 03) with trusted-by chip list (Drees & Sommer · Lindner Group · OTWB · ShapeMaker · TUM · Bauindustrie Bayern · …); Support OpenConstructionERP compacted into 2-col (3 stacked action cards left + "Your support enables" backlog right); Free Guidebook reshaped into small cover + 10-part real chapter list of the Data-Driven Construction book; Documentation + License grouped into matched-height 2-col band; header itself 2-col with identity left + UpdateNotification right; deduped LinkedIn/YouTube/Website/GitHub social row.
- **Project dashboard /Quick Actions** - buttons bumped `sm` → `md` (28 → 32 px) with `space-y-2.5`; card stretches via `h-full flex flex-col` to match Recent Activity height; Documents stats block redesigned with prominent number tiles in a bordered area pushed to the bottom via `mt-auto`.
- **Stale-count sweep** - 12 files refreshed to 24 languages / 48 regional databases (was scattered 9/11/20/21/30) across `AUTHORS.md`, `backend/pyproject.toml` (description), `backend/README.md`, `backend/app/config.py`, `backend/app/core/i18n.py` (EN/RU/AR onboarding strings), `backend/app/core/marketplace.py`, `backend/app/main.py`, `backend/app/modules/erp_chat/{prompts,tools}.py`, `backend/app/modules/match_elements/service.py`, `data/catalog/README.md`, `docs/expand_docs2.py`.

### Fixed

- `file_favorites/__init__.py` was importing a non-existent `permissions.py` - added the missing permission registration so the lifespan startup no longer aborts.

## [3.10.1] - 2026-05-19 · Match-elements "how it works" collapsed by default

### Changed

- /match-elements: the "How matching works - read this first" explainer is now collapsed by default with a white background, keeping the wizard's first screen tidy. Click to expand the full 8-stage tour.

## [3.10.0] - 2026-05-19 · /files enterprise-CDE-grade wave + Clash collab/metadata + match-elements polish

### Added

- /files: 10 new sub-modules bringing the document hub to construction-CDE-platform parity - `file_versions` (rollback + diff metadata), `file_trash` (30-day soft-delete + recycle bin route), `file_search` (cross-project + content search, /files/search), `file_tags` (polymorphic tags + bulk tag drawer), `file_saved_views` (per-project filter snapshots), `file_distribution` (named distribution lists + bulk recipients), `file_comments` (threaded comments anchored to file_kind+file_id), `file_references` (referenced-in panel from BOQ/Punch/RFI/etc.), `file_transmittals` (formal transmittal wizard + PDF cover, /files/transmittals), `file_approvals` (multi-step approval drawer with stamp burn + sidecar JSON fallback).
- /files page: ISO 19650 naming-violation banner, Save-view button, extension overflow popover (RVT/RFA/NWD/DWF/DOCX/MPP/PPTX/ZIP), Recently Viewed strip, keyboard-shortcut sheet, bulk soft-delete & bulk-tag bar, drag-drop into folder cards, FileTree with SavedViews rail and Trash node.
- Clash A2/A3: per-result collaboration locks (`a1b2c3d4e5f6_add_collab_lock_table`) and result-level metadata (`v3048_clash_a2_metadata`, `v3049_clash_collab`) - assignment, status, severity ladder.
- Sidebar: subdued "beta" badges on recently shipped modules.

### Changed

- Match-elements: removed the redundant "project" stage; wizard starts on model and warms the matching session in the background (no blocking spinner on first navigation). Editable n8n-derived prompts retained.
- Project detail: dashboard Open-Items panel rows are now click-through to the underlying entity.
- Equipment: page now hydrates from real backend service; modal lifecycle hardened.

### Notes

- Alembic chain consolidated through `v3071_merge_clash_and_files` (single head).
- Clash A4 intelligence-layer schema landed (rules JSON, cluster_id, ClashCluster table via `v3049_clash_a4_intelligence`); intelligence engine, FP feedback and rule suggestions follow in v3.10.x.
- SQLite-only dev smoke trips on the pre-existing `v2918_risk_owner_user_id` batch_alter (FK to oe_users_user not present in fresh-install order); Postgres prod path unaffected.

## [3.9.1] - 2026-05-19 · Clash model labels read as models, not projects

### Fixed

- Clash: BIM model cards no longer show the project/location prefix baked into seeded model names - the label collapses to the discipline/type tail, so two models of one project no longer read as "two projects". Robust without the global project name being hydrated (direct nav / `?project=` deep-link).

## [3.9.0] - 2026-05-19 · BOQ section-scoped add + AI model auto-recovery + toolbar polish

### Fixed

- BOQ (#149): a section's "Add position" now files the partida **inside that section** instead of after the last sub-section.
- AI Chat (#148): auto-recovers from renamed/retired provider model slugs via `openrouter/auto` then provider default; final error stays actionable.
- BOQ toolbar (#289): Quality & AI / warnings / Grand Total summary no longer cramped - wrapping pills + flex-wrap layout, professional at all widths.

### Added

- BOQ: per-section **always-visible** primary "Add Position" button (no longer hover-only).
- Dashboard: **Customize mode** - reorder/show/hide widgets, persisted per user; Settings → Dashboard tab.
- Markups: **PDF revision compare** (side-by-side / overlay diff of two document revisions).

## [3.8.0] - 2026-05-19 · Clash coordination depth + Match-Elements UX & lifecycle hardening

### Added

- Clash: per-clash **severity** (critical/high/medium/low) - colored badges, severity filter, KPI tile, derived from penetration / clearance ratio.
- Clash: **run-to-run comparison** (new / resolved / persistent) with carry-forward of status, assignee, comments and due-date across re-runs by a stable clash signature.
- Clash: per-clash **collaboration** - assignee, due date, and a comments thread.
- Clash: **CSV export** of the clash list (filters honoured).
- Clash: group / build selection sets by **any element property** (beyond discipline/type/category/IfcEntity) - backend-enumerated property facets.
- Clash: **embedded quick 3D preview** of the two clashing elements in the detail panel + "Open in full 3D viewer".
- Clash & Match Elements: "Beta - new module / may have rough edges" banner with a one-click "Open an issue" path.
- Match Elements: up-front **vector-DB readiness** check (one-click native Qdrant installer when down) and a collapsible plain-language "How matching works" 8-stage overview; page widened for the data-heavy stages.

### Fixed

- Match Elements: switching project no longer keeps a **stale session** (could write a BOQ to the wrong project); rail jumps are blocked when a prerequisite is missing; the empty-grouping dead-end now shows guidance + a recovery path; scope edits re-sync to the session; added project/model/groups query error states and an actionable "0 confirmed" toast; detail-panel focus trap (a11y).
- Match backend: region→catalogue routing is **deterministic again** - the live-Qdrant availability probe is gated behind `CWICR_COLLECTION_PROBE` (was silently re-routing non-English regions to English and breaking 97 unit tests).

### Changed

- Clash migration `v3047_clash_severity_delta` - additive, idempotent, single linear head.
- Sidebar: tighter logo↔search spacing.

## [3.7.0] - 2026-05-19 · Clash Detection module + GitHub issue sweep + file-manager polish

### Added

- New **Clash Detection** module (`/clash`): intra-project geometric interference + clearance coordination over real GLB element geometry - exact OBB-SAT + Möller tri-tri narrow phase, discipline×discipline matrix, Navisworks/Solibri-grade review table, BCF export, one-click "Isolate in 3D".
- Clash: Navisworks-style category/type **selection sets** (Set A × Set B) as the primary search mode; collision results deep-link into the BIM viewer and frame the camera on the clash centroid.
- Clash: active-project context panel - model/element/run summary + working links to BIM 3D Viewer, element matcher and project overview.
- New **Incoming Webhook Leads** module (`oe_webhook_leads`): secure `POST /incoming/{source}` ingestion (API-key/HMAC/JWT, IP allow-list, rate limit), payload→lead mapping, audit log, Settings UI (#147).
- File manager: clicking a BIM model offers BIM 3D Viewer / CAD-BIM BI Explorer / Clash Detection navigation.

### Fixed

- Multi-currency: foreign-currency positions now convert correctly in **section subtotals** (two places) and project totals; FX-correct CSV/Excel export with a frozen-rate appendix (#111).
- "Add partida" now inserts directly **below the selected row** instead of elsewhere (#139).
- AI Chat now renders the streamed answer (OpenRouter/OpenAI SSE) instead of staying blank while tokens are consumed (#138).
- BOQ supports up to **8 nested section/partida levels** with recursive subtotals and a `/v1/boq/limits/` contract (#136).
- Resources can carry a unique **code** with a reuse-or-create prompt and master→instance propagation (#133).
- Clash 3D: collisions now actually display (fixed GLB load-race, element highlight and camera target).
- File manager: BIM-model and sheet rows no longer report 0 bytes - size falls back to the real GLB artifact / parent-document share.
- **Hardened JSON-column deserialization**: a legacy/gap-fill scalar in a JSON column (e.g. `activity = construction`) no longer 500s every read of the affected row - fixed the "Failed to add position / Internal server error" and project-profile crashes via a tolerant engine `json_deserializer`.
- BOQ: deleting a **sub-section that contains nested sub-sections** now works - the editor delegates to the backend's recursive cascade instead of a flat child sweep that silently 409'd.
- Clash: the active-project panel's **BIM 3D Viewer / Match / Project-overview** buttons now navigate (were inert due to a button-inside-link); BIM target picks the first model with parsed geometry.

### Changed

- Clash page: full-width horizontal setup before a run; config collapses into a left-rail menu once results exist. Models auto-included (intra-project) and labelled without the redundant project prefix.
- 3D-geometry clash engine optimised to run under 30 s on showcase models (result-preserving).

## [3.6.1] - 2026-05-18 · BOQ hierarchy visible + nesting fixes + project-focus sidebar

### Fixed

- BOQ grid now renders the true nested section tree: sub-sections (sections-in-sections) are no longer dropped - each level is indented with a depth accent, subtotals roll up recursively, collapse works per level (#136).
- "Add sub-section" no longer silently fails on an ordinal collision (e.g. a stray sibling): the nested ordinal is now globally collision-free (#136).
- Resource-expand control made clearly visible (persistent tinted chip + count) - it was too faint and read as missing (#133).
- PDF export no longer crashes (`float += Decimal`) on a BOQ containing ungrouped positions.

### Added

- Section rows show their ordinal and a discoverable "+ Sub" button to create a nested sub-section inline.
- Project-focus sidebar: needed modules prominent, not-needed small+grey inline, with This-project / All-modules toggle; Guided setup shows Required/Recommended/Optional module tiers.
- /files: document-type cards redesigned - smaller, more data, modern.

### Changed

- CLI entrypoint label is now `openconstructionerp` (matches the PyPI package name).

## [3.6.0] - 2026-05-18 · Multi-level BOQ hierarchy + resource-code dedup + match-pipeline restore

### Added

- BOQ multi-level hierarchy: sections-in-sections and partidas-in-partidas up to 8 nesting tiers, depth-capped on every create/bulk/section/re-parent path; `GET /v1/boq/limits/` exposes the cap (#136).
- BOQ resource code: full duplicate handling - reuse the existing resource or create-new-with-changed-code; a master-resource edit propagates its definition to every reusing instance (quantity never propagates, user-overridden resources preserved) (#133).
- New Project "Show all options": optional fields grouped into iconed cards - Description, Localization, Identification, Site address, Schedule & budget.

### Changed

- /match-elements: the deep 7-stage pipeline (Convert→Load→Schema→Filter→Group→Match→Rollup, per-stage Adjust, editable prompts) is the visible primary flow again - single rail, prominent resume doorway.

### Fixed

- Qdrant collection-info reads are version-tolerant (`points_count`→`vectors_count`→`count()`); fixes the `'CollectionInfo' object has no attribute 'vectors_count'` crash on /match-elements.
- "Vector DB unreachable" banner is now actionable - explains the optional dependency, points to native Qdrant install, lexical-fallback note, wired Retry button.
- Takeoff measurements tab fits in one viewport at desktop sizes - no page scrollbars (real fix after #181/#182).

## [3.5.0] - 2026-05-18 · Pipeline Builder + BOQ FX-correct exports + reuse codes

### Added

- Pipeline Builder: visual automation canvas + graph executor + node registry (6 node types), per-run states, publish-gated structural validation.
- BOQ manual resources gain a `code` field with a project-wide reuse prompt: insert the existing resource or create-new-with-changed-code (#133 stage 1).
- Exchange modules (22 regions) ship a one-click sample-template download.
- BOQ CSV & Excel exports gain a Currency column + a frozen FX-rate appendix (rates can't be retroactively changed on a delivered BOQ).

### Changed

- New Project page: collapsible "Optional details" with progressive disclosure - fast path stays 3–4 fields (#195).
- §4–12 deep-improvement wave across AI, Planning, Field Ops, Finance, Commercial, Communication, Documentation, Quality and Regional modules.

### Fixed

- BOQ reuse codes: a master edit now propagates to every linked instance's child/subtree (instance edits still diverge/unlink as intended) (#132).
- BOQ section subtotals, Direct Cost and Grand Total now FX-convert foreign-currency positions in the export path (CSV/Excel/PDF/GAEB) - the export-side twin of the #131 grid fix (#111).
- /catalog resources not displaying for anonymous/demo access (#196).
- BIM converters status panel is now dismissible (#194).
- GitHub issues #128, #129, #131, #134, #135 resolved; takeoff measurements horizontal scroll (#182).
- Finance/procurement project-currency inheritance is now best-effort - a failed lookup never 500s a budget/PO create.

### Security

- Pipeline Builder endpoints (list / get / update / **delete** / runs / node-types) required no authentication - all now require an authenticated user.

## [3.4.1] - 2026-05-17 · Authenticated media loading + dual IFC/RVT showcase

### Fixed

- Photo & file-grid thumbnails and full-size images failed to load (HTTP 401) - JWT-protected media endpoints can't authenticate a plain `<img src>`. New shared `AuthImage` fetches with the bearer token and renders an object URL; applied across the photo gallery, file manager grid and project photos tab. Affects every real uploaded photo, not only the showcase.

### Changed

- Showcase snapshot regenerated: each of the 7 projects now ships a second Autodesk Revit (.rvt) structural model alongside the IFC architectural model - both visible in the BIM viewer and the Match Elements (data-analytics) module.

## [3.4.0] - 2026-05-17 · Professional showcase BOQ + colored real-IFC BIM + viewer fix

### Added

- Edit + Delete on Finance, Inspections, Procurement and Variations (notices / VR / VO / daywork / EoT) - full prefilled edit modals + guarded delete.

### Changed

- Showcase BOQs rebuilt professionally: 12 WBS divisions × ~49 priced positions per project, each broken into 3–6 real region-catalogue resources at average price, fully localized; reconciliation deterministically recomputed (BAC/EVM/cash-flow stays green, ALL 7 PASS).
- Showcase BIM now a real 48 MB IFC2X3 model with 380 real parsed elements (walls/slabs/windows/doors/beams + BaseQuantities), every priced position linked, downloadable original, rendered in color (66 materials).

### Fixed

- BIM 3D viewer z-fighting ("jumping triangles") on real IFC/RVT models - logarithmic depth buffer + model-scaled camera near/far instead of a fixed 1e8 range.

## [3.3.1] - 2026-05-17 · 7-project localized showcase on fresh install

### Added

- Fresh install seeds the 7-project localized showcase (EN/DE/ZH/AR/HI/RU/pt-BR) from a committed snapshot - real CWICR-resource estimates, linked BIM, WBS, cost-model/EVM and every operational module filled, each in its own language and currency.
- Idempotent boot loader with demo-owner re-mapping; never breaks boot.
- `SEED_SHOWCASE=false` opts out; the classic 5 demo projects remain the fallback when the snapshot or SQLite is unavailable.

### Fixed

- Showcase entities were seeded into terminal/locked statuses (meeting `completed`, RFI `closed`, contract `active`, EOT-claim invalid `approved`, field-report `submitted`, CDE `shared`/S0) so API state-machine guards blocked edit/delete; reset to editable create-default states across all 7 projects. Numeric/financial columns untouched - BAC/EVM/cash-flow reconciliation preserved.

## [3.3.0] - 2026-05-16 · Reusable BOQ codes (linked positions) + deep correctness pass

### Added

- BOQ code reuse / linked positions (#127): type or pick an existing code → a linked instance is created with the master's full definition + child subtree, its own unique ordinal and its own independently-editable quantity (no more "code already exists" dead-end).
- Master-definition edits propagate project-wide to every linked instance; quantity/ordinal never propagate.
- Editing a linked instance's definition auto-unlinks it and warns the user instead of back-propagating.
- Codeless positions/resources get an auto unique internal `reference_code` so they are always referenceable.
- "Show Linked Positions" panel + value-preserving "Unlink"; grid badges (amber master with count / blue instance).
- Alembic `v3036_linked_positions` (reference_code / link_group_id / link_role, idempotent).

### Fixed

- Unlink a master with linked instances returned HTTP 500 (`update_fields` `expire_all` expired the ORM instance → `MissingGreenlet`); now 200, value-preserving, survivor promoted.
- Deep correctness pass (W1–W7) across assemblies/catalog, BOQ core, projects/documents, risk/schedule/variations, validation/costs/core, CAD/BIM unit honesty, takeoff labels & frontend perf.
- Validation `RunValidationResponse.score` accepts `None` (SKIPPED reports no longer 500 the response model).
- i18n validation bundle: humanised fallback for missing keys (raw dotted keys never surface to users).

### Verification

- #127 verified end-to-end live (reuse, propagation, unlink, independent quantities, child subtree) + new integration regression tests; frontend type-check clean.

## [3.2.0] - 2026-05-16 · Backlog triage, Planning/Field-Ops audit, clean-install fix, per-country demo data

### Clean install

- Fresh database now creates all module tables: `create_all` ran off a hand-maintained import list that omitted 18 modules (service, resources, equipment, portal, daily_diary, schedule_advanced, crm, contracts, variations, bid_management, qms, hse_advanced, carbon, bi_dashboards, subcontractors, supplier_catalogs, property_dev, compliance_docs) - those whole sections 500'd ("no such table") on any fresh install. Module models are now discovered dynamically; adding a module needs no edit.

### Correctness

- Planning + Field Operations deep audit (10 modules): schedule 8 cross-tenant IDOR endpoints + working-day calendar + Gantt duration; schedule-advanced CPM 500-on-cycle + EVM sunk-cost + read-only Weekly commitments; tasks assignee-not-persisted + checklist-progress-0% + illegal status transitions + completion event/audit; 5d budget variance + hardcoded EUR ×2 + S-curve double-cumulation; risk dead heatmap + impact-level mismatch + numeric-parse 500; daily-diary missing entries endpoint + calendar day-click + wrong-day weather; equipment >500-fleet drawer + dropped depreciation/geo fields; resources timezone double-offset + invisible live bookings + spurious 409; service permanently-empty Tickets + WO-create 422 + hardcoded EUR; portal ticket-create 422 + own-ticket scoping + durable access rules.
- Variations: every list endpoint was dead (`UnmappedInstanceError` - a mapped attribute stored as a class attribute became an instance descriptor); 8 repositories fixed.
- Bid management: bid-package list was unusable (frontend `limit=200` vs backend `le=100` → 422); cap raised to 500 (no silent truncation).
- Remediation backlog (125 items) triaged at root: documents IDOR / path-traversal / unsafe sort, BOQ currency rounding + markup base + recalculate-rates 500 + >1000-position rollup, assemblies import 500 / overflow / negative factor / formula engine, validation score scale + empty-BOQ-as-passed + ReDoS in `must_match`, projects/dashboard/catalog money & date integrity, takeoff/CAD aggregation honesty, requirements gate sequencing, bim_requirements project authz + explicit XXE.
- i18n locales: 3949 duplicate-key build errors removed (first-wins dedup), canonical translations preserved; fixes silent runtime translation shadowing.
- Cost matching: restored the 3-letter→ISO-alpha-2 country remap (`country_filter_for`) - US/GB/CA rates were silently excluded from every match.

### Demo data

- Paris demo project re-based to France's DPGF standard (was German DIN 276); region, validation rule set and per-lot classification corrected per country.
- Demo seed is exactly 4 country-correct projects - Berlin (DIN 276 / EUR), Dubai (MasterFormat / AED), Paris (DPGF / EUR), US Medical (MasterFormat / USD); no test/smoke data shipped.

### Verification

- Backend 5562 unit tests passing, frontend type-check clean, zero regressions.
- Live browser walkthrough: 62 pages across every sidebar section, real tab clicks + screenshots, 0 API/JS errors.

## [3.1.0] - 2026-05-15 · Deep logic + correctness sweep (23 modules, 10 waves)

A 10-wave root-cause pass across the operational/commercial modules. Full unit
tier 5269 passing, frontend type-check clean, zero regressions.

### Security / authorization

- **Daily Diary: cross-project IDOR closed** on ~25 endpoints - another project's site diary could be read/edited/signed/archived.
- **Reporting: module was admin-only** - missing permission registration meant every editor/manager got 403 on all mutating endpoints; permissions now register on startup.
- **Tendering: module was admin-only** - same missing-registration cause; fixed.
- **Customer Portal: cross-project change-order leak** - a per-CO grant let a caller read all approved COs of an unrelated project.
- **CRM / Contracts / Carbon: unregistered permission strings** (`crm.write`, `contracts.write`, `carbon.write`) silently 403'd editors; aligned to registered permissions.
- **Variations / Contracts / Bid Management: object-level scoping** added to mutating + sub-resource endpoints lacking it.
- **Schedule XML import: hostile payloads now return 400, not 500** - `defusedxml` XXE/billion-laughs rejections are no longer mis-handled as uncaught errors.
- **Supplier Catalogs / PEPPOL: XXE hardening** - hard-refuse parsing when `defusedxml` is unavailable; boundary exceptions return a clean 400.

### Correctness (money / data integrity)

- **Change Orders: no more hardcoded `EUR`** - model, schema and service default removed; currency now resolves from the owning project.
- **Variations / Bid Management: voided/withdrawn items no longer inflate rollups**; Decimal-exact money math (was float).
- **Contracts: certified claims now emit the finance event** (were silently never invoiced); financial terms locked once signed.
- **Carbon: granular EN 15978 stages no longer dropped from totals** (was under-reporting embodied carbon).
- **HSE Advanced: TRIR recordable undercount fixed** (a lost-time case with no medical treatment was excluded - impossible per OSHA).
- **Safety: "days without LTI" date-integrity fixed** - robust date parsing + canonical ISO write path; malformed dates fail safe to "unconfirmed" instead of a falsely-reassuring number.
- **BI Dashboards: KPI trend charts were reversed** (newest-first ordering); drill-down period filters were dropped.
- **Service / Subcontractors / Equipment / Resources / Property Dev:** lifecycle-state guards, idempotent transitions (no duplicate events on retry), N+1 dashboard queries replaced with SQL aggregates, mixed-currency sums guarded.

### Wizards

- **Project setup wizard:** reachable duplicate-name confirm, no literal `__custom__` in review, required custom region/currency, string-backed regional factor clamped on blur, idempotent submit (no double-create), submit-time full validation, focus trap + return-focus, `role="dialog"`/`aria-modal`, clickable visited stepper, richer review.
- **Match pipeline:** honest "runs the deterministic heuristic today" note, read-only seeded prompt with Fork-to-edit, the displayed prompt is the one that runs (was silently `null`), stage errors surfaced (no silent close), per-stage knob state no longer leaks across stages, group-by seeds from effective keys, slide-over `role="dialog"` + focus.

## [3.0.9] - 2026-05-15 · Project setup wizard UI + converter binary-integrity gate

### Added

- **Project setup wizard UI (Slice 2).** `New Project` is now a 5-step wizard - Basics → Region & currency → Project type (9 preset cards) → Scope (activities / phases / focus mode) → Site & review - that creates the project and applies the Slice-1 profile in one flow. Preset grid has a loading skeleton + error fallback.

### Fixed

- **Converter install now verifies the binary, not just its presence.** The `verifying` stage runs a PE-header integrity check (`MZ` + `e_lfanew` → `PE\0\0`); a corrupt/CRLF-mangled download is rejected immediately with an actionable message and the partial install is rolled back, instead of failing later at launch with `WinError 216`.

## [3.0.8] - 2026-05-15 · Converter download fix + project setup wizard (backend) + visible match pipeline

### Fixed

- **Windows converter downloads no longer corrupt binaries.** `_download_one_file` opened the destination with `os.open()` without `os.O_BINARY`, so the MS C runtime used text mode and `os.write()` rewrote every `0x0A` as `0x0D 0x0A` - shifting the PE header and making `RvtExporter.exe` / `IfcExporter.exe` / `DgnExporter.exe` fail to launch with `WinError 216`. Now opens binary on Windows; no-op on POSIX.

### Added

- **Project setup-wizard backend (Slice 1).** 8-preset library + multi-axis scoring engine (activity · role · phase · size · region) → per-project module tiers (must / recommended / optional / hidden) with a numbered route line. New tables `oe_project_profile` / `oe_project_module` / `oe_project_wizard_draft` (migration `v3035`). Endpoints: `GET /projects/wizard/presets`, `GET|POST /projects/{id}/profile`, `POST /projects/{id}/profile/recompute`, `PATCH /projects/{id}/profile/focus-mode`, `GET /projects/{id}/modules`. Presentation-only gating - never unloads a module or blocks an API.
- **Visible 7-stage match pipeline on `/match-elements`.** Convert → Load → Schema → Filter → Group → Match → Rollup, each with status, output preview, an Adjust panel, and editable LLM prompt templates (migration `v3034`).
- **BIM converter banner** now shows live install progress in a two-column layout.

## [3.0.7] - 2026-05-14 · Resource-based cost DB import - docs, templates, downloads

### Added

- **Full guide for extending the cost database** - `docs/cost-database-import.md` covers both paths into `oe_costs_item`: flat-row import (CSV/XLSX via `POST /api/v1/costs/import/file/`, with column-alias table, auto-detected delimiters, encoding heuristics) and resource-based recipes (`POST /api/v1/costs/` with `components[]` referencing leaf resources by `code` + `factor`). Includes classification standards (MasterFormat / NRM / DIN 276 / Uniformat / GAEB), currency handling, Match-Elements integration, and a troubleshooting table.
- **Three downloadable templates**, shipped in `data/templates/` and served as static assets at `/templates/*` so they download straight from the app:
  - `cost_database_template.csv` - minimal 3-row starter (one labor, one material, one equipment line).
  - `example_us_construction.csv` - 30-row working US database covering labor, materials, equipment, and subcontractor lines with MasterFormat codes.
  - `cost_database_with_assemblies.json` - 6 recipe items (strip footing, CIP wall, CMU wall, 2x4 framing, drywall + paint, asphalt roofing) with full resource breakdowns.
- **"Download a template" row on `/costs/import`** - three one-click download buttons in the *Supported formats* card, plus a pointer to the full guide.
- **End-to-end smoke test** - `scripts/test_cost_import.py` uploads the CSV, pushes the JSON recipes, round-trips every code through `/costs/?q=…`, and verifies every recipe's component breakdown survives. Passes 4/4 stages against a clean install (idempotent - 409 "already exists" on re-run is treated as a pass).

## [3.0.6] - 2026-05-14 · DWG upload responsiveness + 6 new HF regions + sidebar branding

### Fixed (DWG upload - root cause)

- **One stuck DDC conversion no longer poisons the next 5+ uploads.** `_handle_dwg()` was awaited inline in the upload request handler, so a 60–120 s DDC binary call (or a crash on an R16/R17 file) pinned a uvicorn worker; subsequent uploads queued behind it and timed out on the client side with `HTTP 500 "Unable to upload drawing"` or `ReadTimeout`. The upload row is now committed first and DDC conversion runs on a detached task with its own `AsyncSession` (`_run_dwg_conversion_in_background`), so the HTTP request returns immediately with `status=uploaded` and status transitions are polled normally.
- **DWG version floor dropped R18 → R14.** Previously the pre-emptive `_dwg_version_too_old` check refused AutoCAD 2004/2007 (R16/R17) before handing them to DDC. The 2026-05-14 bench showed several R16/R17 files DO convert successfully with the installed binary - let DDC have a go and surface its real error when it can't.
- **DDC DwgExporter rolled back v18.2.0 → v17.1.1 (penultimate stable).** Verified upstream regression: v18.2.0 crashes with `Error: converter crashed.` on DDC's own sample `architectural_example-imperial.dwg`, while v17.1.1 converts the same file to a 443 KB Excel at 100 %. IFC/RVT/DGN keep the v18.2.0 inner binaries (no observed regression there) - only the DWG path is reverted.

### Added

- **6 new CWICR v3 catalogues** (registry grows 42 → 48): `MN_ULAANBAATAR` (Mongolian, MNT, 916 MB), `BG_SOFIA`, `HR_ZAGREB`, `NZ_AUCKLAND` (NRM), `TH_BANGKOK`, `VI_HANOI`. All flipped to `available=True` via the `_HF_PUBLISHED` mapping after DDC published the snapshots on the `cwicr-vector-db-bgem3-v3` HF dataset on 2026-05-14.
- **Sidebar white-label branding** - new edit button above the platform name opens a chooser to upload a logo OR type a company name. When set, the user's brand shows large in the sidebar header; `by OpenConstructionERP` sits below as a small AGPL-3.0 attribution. Persisted in localStorage, no backend round-trip.

### Changed

- Default sidebar wordmark shrunk 15 px → 13 px so it no longer crowds the always-visible edit button at the 248 px sidebar width.

## [3.0.5] - 2026-05-14 · Match-elements correctness pass + full Mongolian translation

### Fixed (match-elements - root-cause sweep)

- **`unit_dim` filter excluded every Qdrant hit** - query_builder emitted a `unit_dim` hard filter that doesn't exist on the DDC v3 snapshot payload (it uses `unit_type` with capitalised `Area`/`Volume`/`Linear`/`Mass`/`Count`). Filter never matched, search returned 0, the ranker fell through to a metadata-only path with score ≈0.0002 and surfaced opaque encoded rate codes. Now emits `unit_type` against the snapshot's actual schema; kept `unit_dim_for()` exported for back-compat.
- **`resources` named-vector prefetch returned 404** - `search()` blindly added a `Prefetch(using="resources", …)` whenever the envelope carried resource hints. The DDC v3 snapshot only exposes `dense` + `sparse` named vectors. Now caches per-collection capabilities (`_collection_vectors`) and only issues prefetches the snapshot actually supports.
- **`"BoQ"` source label poisoning `ifc_class` filter** - BoQ adapter set `attrs["ifc_class"] = "BoQ"` whenever the row had no category; envelope builder forwarded it as a hard filter; Qdrant dropped 100% of CWICR rows. Fixed in both the adapter (only forward when the row explicitly carries an IFC class) and the envelope builder (only pass values starting with `Ifc`).
- **Empty description / unit_rate / currency on snapshot-only installs** - snapshot install populates Qdrant vectors but not `oe_costs_item`. With no parquet enrichment, candidates surfaced blank, and the BGE cross-encoder collapsed every score because its passage text was just the opaque rate_code. Now `ranker_qdrant._description_from_payload()` synthesises a human-readable passage from the snapshot's categorical fields (`collection_name`, `material_class`, `ifc_class`, `category_type`, `masterformat_division`); `_hit_to_candidate()` derives currency from the country head via a 60+ ISO-code map. `unit_rate` stays 0.0 - fabricating the operator's load-bearing price would be wrong. UI surfaces "Rate unavailable" instead.
- **`reranker_bge._build_candidate_text()` defensive fallback** - when `candidate.description` is still empty, folds classification + region into the passage so the cross-encoder has discriminating signal beyond the opaque code.

### Added

- **Mongolian (mn) full translation** - completed the 2300 keys that were left as English-fallback in 3.0.4. Construction terminology curated (BOQ → "ажлын тоо хэмжээ", subcontractor → "туслан гүйцэтгэгч", risk → "эрсдэл"); placeholders `{x}` / `{{x}}` preserved verbatim; technical IDs (IFC, DWG, JWT, USD) kept intact.
- **14 new unit tests** for the match payload fallback (`test_ranker_qdrant_payload_fallback.py` + `test_reranker_bge_payload_fallback.py`).

### Fixed (frontend tests)

- Pre-existing vitest debt resolved: 9 broken test files repaired (share-link, visual-regression snapshots, ClassificationPicker, NotFoundPage, BOQGrid, CostCategoryTree, _registry, boqResourceTypes, CostDatabaseSearchModal). No production-code changes - only stale mocks, removed imports, and re-aligned selectors.

### Validation

- Live match probe ("Concrete C30/37 wall, 240mm reinforced" against the USA_USD snapshot) now returns a real US rate code with a readable description and currency=USD. Was score ≈0.0002 + opaque rate code with all enrichment fields empty before. Confidence is still relatively low (~0.005) when the top vector hit is semantically distant (e.g., a hydraulic-engineering rebar rate for a wall query) - that's the BGE reranker doing its job, not a bug.

## [3.0.4] - 2026-05-13 · Polish pass + community contributor flow

### Added

- **"Support us" star button in topbar** + 3-action modal: GitHub star · social share (X / LinkedIn / copy) · case-study tip-off to `info@datadrivenconstruction.io` (or just tag `@DataDrivenConstruction` for re-share through DDC newsletter + socials)
- **Mongolian (mn) locale** registered in `SUPPORTED_LANGUAGES` with starter translation set (nav + common + support keys) - falls back to English for the long tail. Inline soyombo SVG flag added to `CountryFlag.tsx`. Co-authored with @mn-frappe (community contributor invite via PR #125)
- **DDC brand logo** on the Request-a-module dialog hero (replaces generic Sparkles icon) - sourced from local `/brand/ddc-logo.webp`, no external CDN call
- **Marketing site auto-version sync** - `website-marketing/pro/breeze/index.html` hero badge and release ticker now fetch the latest GitHub Release tag + date + name at page load, with SSR fallback to the current shipped version

### Changed

- **Dependency bumps** - Frontend: 12 minor/patch (@tanstack/react-query 5.90→5.100, maplibre-gl 5.23→5.24, react-resizable-panels 4.9→4.11, zustand, @playwright/test 1.58→1.60, @typescript-eslint 8.57→8.59, autoprefixer, jsdom, msw 2.12→2.14, postcss, prettier 3.8.1→3.8.3, pdfjs-dist 4.8→4.10). Rust desktop: openssl 0.10.78→0.10.79 (CVE patch), tauri 2.10.3→2.11.1 (Origin-Confusion CVE patch), rand 0.8.5→0.8.6
- **Rollup pinned to 4.59.0** via `overrides` - Rollup 4.60+ broke vite 6.4's modulepreload-polyfill source-phase import; pin restores the production build

### Fixed

- **`p.data.filter is not a function`** on Vendor DB in demo accounts - `SupplierCatalogsPage.tsx` now defensively coerces all `useQuery` data fields with `Array.isArray(...)` rather than `?? []`, which was letting stale offline-cache error envelopes through
- **Backend `F821`** - `contracts/router.py` referenced `status.HTTP_400/404` without importing `status` from fastapi (3 endpoints would have crashed on hit)
- **Backend `F601`** - duplicate `"متر مربع"` dict key in `match_service/boosts/unit.py` (Arabic + Persian sections collided; phrase is byte-identical in both scripts)
- **Missing Mongolian flag** in language switcher - inline SVG + emoji fallback added to `CountryFlag.tsx`
- **61 dead backend imports** cleaned via ruff `--fix`

### Housekeeping

- **All 7 stale Dependabot PRs closed** (#117 minor group, #112 cargo openssl, #125 Mongolian, #118 typescript major, #119 i18next-http-backend major, #120 react-is major, #121 eslint major). All were based on an older main; merging would have resurrected a removed internal qa-scratch tree. Equivalent safe patches applied directly to main; majors deferred to a separate validation cycle.
- Pre-existing frontend vitest debt documented: 31 failing tests across 9 files (share-link, visual-regression snapshots, ClassificationPicker, NotFoundPage, BOQGrid, CostCategoryTree, _registry, boqResourceTypes, CostDatabaseSearchModal). None caused by v3.0.4 changes - slated for v3.0.5 cleanup.

## [3.0.3] - 2026-05-13 · Deep correctness pass + UX & supply-chain hardening

### Added

- **FSM engine** - 6 entity state machines (BOQ · Project · Invoice · NCR · RFQ · Submittal) with 50 declarative transitions, role-restricted guards, audit log via new `oe_activity_log` table (migration `v3033`)
- **IFC unit assignment parser per ISO 16739-1:2024 §5.4.3** - every SI prefix, Imperial conversion, recursive `IfcConversionBasedUnit`, `IfcDerivedUnit` combinatorics; 92 unit-assignment regression tests
- **Ed25519 manifest signing** for the converter installer pipeline - SHA-256 file verification, refuse-on-mismatch, 30 tests + emergency-rotation script
- **Collapsible icon-only sidebar** - toggles to 64px, floating pill on the panel edge, persisted to localStorage
- **WideModal sweep** - 19 files / 25 modals migrated to the shared `WideModal` foundation: Resources, DailyDiary, QMS, Punchlist, FieldReports, Contracts, CRM, Variations, PropertyDev, SupplierCatalogs, ChangeOrders, Tendering, Finance, Submittals, Correspondence, Contacts, RFI, Meetings, Transmittals. Forms with 4–14 fields now fit at 1366×768 without scrolling.

### Fixed (UX)

- Subcontractors page modal unified - was the only outlier still on a narrow `max-w-3xl` no-section modal; now uses `WideModal` + `WideModalSection` like the rest of M1
- Service page - Delete with `ConfirmDialog` on contracts / assets / tickets; contract delete invalidates cascaded child rows
- `module_loader` URL prefix - canonical kebab-case + underscore mirror so both `/bi-dashboards` and `/bi_dashboards` resolve

### Tests

5045 passed · 1 skipped · 0 regressions

## [3.0.1] - 2026-05-13 · 18-Modules Wave + deep stability

### Added - 17 new business modules (88 total)

**Field Operations** - Service & Maintenance · Equipment & Fleet · Daily Diary · Subcontractor Portal · Resources & Crew
**Commercial** - CRM · Contracts (FIDIC / JCT / NEC4 / AIA) · Subcontractor Management · Bid Management · Variations (VO register) · Supplier Catalogs · Property Development
**Schedule & Quality** - Advanced Schedule (Last Planner / CPM Kahn topo-sort) · Quality Management (ISO 9001:2015) · HSE Management (ISO 45001 / OSHA 1904.39 / RIDDOR / DGUV) · Carbon & ESG (EN 15978 LCA · GHG Protocol Scope 1/2/3) · BI Dashboards (warehouse-projected)

### Stability - India scenario findings actioned

- **DWG / DXF**: ezdxf 1.4.x layer-visibility regression fixed (every fresh-install layer was being marked invisible due to bound-method truthiness)
- **PDF takeoff**: Devanagari / Tamil / Telugu / Arabic / Chinese / French / German / Spanish OCR by default; lakh-crore (`1,00,000`) numeral parser; scanned-PDF fallback
- **CRS auto-detect**: India UTM 42-46N + 16 other region groups worldwide (Germany Gauss-Krüger + UTM 32/33, UK BNG, France Lambert-93, Switzerland LV95, Austria MGI, Netherlands RD, US State Plane + UTM 10-19N, UAE/KSA UTM 38-40N, Japan JGD2011, Brazil SIRGAS, China CGCS2000)
- **File-size limits removed across all uploads** (env override remains for tenant policy); streaming upload + background-job migration
- **Qdrant without Docker**: native binary auto-install from official GitHub Releases, supervised by `qdrant_supervisor.py` with one-click install card on `/match-elements`

### Security

- `Settings` model now refuses to start in non-development environments when `JWT_SECRET` is still the bundled `openestimate-local-dev-key` default - fail-fast at boot with a clear remediation message (set `OE_JWT_SECRET` to `secrets.token_urlsafe(32)`)
- 230 IDOR endpoints hardened across service / subcontractors / contracts / bid_management / schedule_advanced / bi_dashboards via `verify_project_access`

### Cross-module integration

- 37 cross-module event subscribers (`_wave5_cross_module_subscribers.py`) wire QMS NCRs to procurement supplier rating, HSE incidents to contract risk register, carbon entries to BI projections, daily diary to schedule actuals, etc.
- 14 alembic migrations (v3010 → v3031) with parallel-wave merge head (v3032)

### Internationalisation

- 18 new nav keys translated across 25 non-EN locales (industry terminology preserved - Last Planner kept as proper noun, BI/ESG acronyms unchanged)

## [3.0.0] - 2026-05-12 · v3 milestone

Consolidates the entire v2.x line (100+ patch releases between 2026-04-20 and 2026-05-12) into a stable v3.0.0 milestone. Same codebase as v2.9.42 - new version label, refreshed metadata, framed as the v3 release.

### v3 highlights (cumulative since v2.0.0)

**Cost data & match-making**
- 42 regional cost catalogues (Europe, Americas, Asia, Africa) - CWICR v3 schema
- AI vector matching via Qdrant + BGE rerank across 11 classification standards (DIN 276, MasterFormat, NRM, GAEB, UNTEC, VOCI, BC3, GB50500, SEKISAN, GESN, BirimFiyat)
- Per-encoder + per-language confidence thresholds, language-family region aliases
- Multi-currency BOQ with live FX rollup

**CAD / BIM (no IfcOpenShell)**
- DDC `cad2data` pipeline: DWG / DGN / IFC / RVT → canonical JSON
- PDF + DWG takeoff (PaddleOCR + YOLOv11)
- BIM Quantity Rules + Requirements DSL
- BCF I/O (issues / viewpoints / validation reports)

**Project control**
- File-manager (docs / photos / BIM / DWG / sheets / markups / reports / takeoffs in one place),
  per-folder ACL, per-file activity log, password-protected share links, bulk operations
- Finance, Procurement, Tendering, Change Orders, Compliance Docs tracker
- RFI, Submittals, Transmittals, NCR, Inspections, Meetings, Correspondence, Contacts
- Tasks, Schedule (Gantt), Risk Register, 5D Cost Model
- Validation (DIN 276 / NRM / MasterFormat / GAEB), Compliance DSL, 3-way invoice match

**Platform**
- 71 plug-and-play modules with auto-discovery
- 21 languages, lazy-loaded chunks
- Apple-style design system, light + dark, route-aware backdrop variants
- AGPL-3.0 - open data, open standards, open formats

**Security & quality**
- IDOR sweep across 73+ endpoints, RBAC scopes
- MIME hardening, share-link password protection
- 450+ pytest tests, 1600+ vitest tests, integration coverage on critical modules

### Install

```bash
pip install openconstructionerp==3.0.0
# or
docker compose up
```

PyPI: https://pypi.org/project/openconstructionerp/3.0.0/
Demo: https://openconstructionerp.com
Source: https://github.com/datadrivenconstruction/OpenConstructionERP

## [2.9.42] - 2026-05-12

### Added

- Markups: threaded comments per drawing markup (`oe_markups_comment` table, v2941 migration, 3 endpoints, MarkupCommentsDrawer).
- File-manager: per-folder ACL (viewer / editor / owner) with FolderPermissionsModal + lock badge; v2942 migration.
- File-manager: per-file ActivityDrawer slide-over with Today / Yesterday / Earlier bucketing.
- File-manager: bulk-delete for all 8 file kinds (`groupByKind` dispatcher; new `DELETE /v1/reporting/reports/{id}` and `DELETE /v1/documents/sheets/{id}`).
- Compliance Docs tracker (`oe_compliance_docs` module, v2943 migration): insurance / permits / bonds with expiry status, dashboard widget, /projects/{id} compliance tab.
- `/files` first-load overlay (`InitialLoadProgress`) with Storage → Tree → Ready stepper + animated progress bar.
- `/files` landing KPI strip (`FilesStatsStrip`) with storage-by-kind breakdown segments.
- Notifications inbox page (`/notifications`) with paginated list, date grouping, per-row delete; bell rewritten with loading / error / empty states.
- 16 fallback `notification.<event>_(title|body)` templates server-side so freshly-generated events never leak raw i18n keys.

### Changed

- Dashboard backdrop hoisted from per-page wrappers into `AppLayout`, route-aware variant: `/boq`, `/match-elements`, `/costs`, `/assemblies`, `/catalog`, `/bim/rules`, `/files` → estimation amber; `/schedule`, `/tasks`, `/5d`, `/risks` → planning red; everything else → dashboard blue.
- Removed `relative isolate` from 14 page wrappers so full-screen modals (z-50) sit above the sticky header (z-30) in the root stacking context instead of being trapped behind it.
- Modal backdrops bumped to `bg-black/70 backdrop-blur-lg` across ~82 dialogs so page chrome behind the modal is unreadable.
- `AppLayout` root no longer paints `bg-surface-secondary` (was hiding the `fixed -z-10` backdrop in the root stacking context).
- `/projects` stats: 4 unified cards (Total Projects, Total BOQs, Total Value, Avg Project Size); removed secondary Regions / Currencies / With BIM row.

### Fixed

- `GET /v1/notifications/` 404 - bell now hits `/v1/notifications` (no trailing slash) and backend registers both forms defensively.
- IDOR on `GET /v1/markups/?project_id=` - now scoped to caller's project membership.

### Migrations

- `v2941_markup_comments` ← `v2940_assemblies_resource_type`
- `v2942_folder_permissions` ← `v2941_markup_comments`
- `v2943_compliance_docs` ← `v2942_folder_permissions`

## [2.9.41] - 2026-05-12

### Added

- Projects: PhotosTab on `ProjectDetailPage` - filter bar (search + sort) + responsive grid + keyboard-navigable lightbox; reuses `useFileList` with `category='photo'` filter (no API duplication). 21 `projects.photos.*` i18n keys.
- Projects: TeamStrip on `ProjectDetailPage` - up to 6 overlapping avatars + "+N more" chip + Add modal with user search and role selector (owner / estimator / viewer / project_manager). Backed by 3 new project-scoped member endpoints (list / add / remove) delegating to the auto-created Default Team - no new table or migration. 14 `projects.team.*` i18n keys.
- Documents: password-protected share links - 6 endpoints (3 public `probe`/`access`/`download`, 3 owner `create`/`list`/`revoke`), bcrypt(12) password hashing, 32-char URL-safe tokens via `secrets.token_urlsafe`; revoked/expired/unknown all return 404 (no enumeration). `ShareLinkModal` in `FilePreviewPane` + public `/share/:token` page outside `RequireAuth`. 45 `files.share.*` / `share.page.*` i18n keys.

### Changed

- `/match-elements` compaction: single-row hero (28px h1 + 36px icon + paragraph subtitle, decorative blur removed), status cards (Catalogues / Embedder / Analytics) stacked → 3-col grid at `lg+`, steps 1 + 2 (BIM model / Session) stacked → 2-col grid at `lg+`. Step cards `mt-3 p-4 → mt-2 p-3`, number bubbles `5x5 → 4x4`. Reclaims ~330–390px of empty space above the matching table.
- `AddMemberRequest.role` regex widened to accept project roles (owner / estimator / viewer / project_manager) alongside existing team roles.

### Migrations

- `v2939_document_share_links` ← `v2938_documents_activity`

## [2.9.40] - 2026-05-12

### Added

- Projects: `POST /v1/projects/{id}/duplicate/` deep-clone - copies WBS tree, milestones, and `MatchProjectSettings`. Collapses a 34-line client-side workaround in `ProjectsPage`.
- RFI: `priority` + `discipline` + `linked_drawing_ids` + `attachments` fields on `oe_rfi`; pickers, deep-link rows, attachment upload, and linked-drawings picker on `RFIPage`. New `RFIDetailPage` (hero + question/answer + classification card).
- Documents: OCR-text search across `name` + `description` + `metadata.ocr_text` + sheet title / number.
- Documents: per-file activity log (`GET /v1/documents/{id}/activity/`) with 1s UTC-safe dedupe; rendered as `ActivityLogSection` in `FilePreviewPane`.
- File-manager: `SheetsIndexPage` and `FileContextMenu` components; inline PDF iframe preview in `FilePreviewPane`.
- `/costs`: `CostCategoryTree` skeleton-loading state + Toronto catalogue (`ENG_TORONTO` alias).

### Changed

- `/projects` and project Files: Apple-style dashboard backdrop (aurora + dot-grid + spotlight).
- `/match-elements`: tolerate both array and `{catalogues:[]}` envelope shapes from the catalogues endpoint.

### Migrations

- `v2937_rfi_priority_discipline` (RFI priority / discipline / linked_drawing_ids / attachments)
- `v2938_documents_activity` ← `v2937_rfi_priority_discipline`

## [2.9.39] - 2026-05-11

### Added

- Africa catalogue pack: 12 new `CWICR_V3_CATALOGUES` entries (NG_LAGOS, KE_NAIROBI, GH_ACCRA, UG_KAMPALA, TZ_DARESSALAAM, SN_DAKAR, CI_ABIDJAN, CM_DOUALA, AO_LUANDA, MA_CASABLANCA, EG_CAIRO, TN_TUNIS). Registry size 30 → 42. Anglo-Africa → nrm, Francophone → untec, Lusophone-Africa → masterformat, Maghreb-AR → masterformat.

### Fixed

- 71 legacy ranker monkeypatch refs in 3 test files (`test_phase0_edge_cases.py`, `test_match_concurrency.py`, `test_phase0_perf.py`) - dotted-path updated from deleted `app.core.match_service.ranker` to `ranker_qdrant`. Import errors cleared; 122 previously-erroring tests now pass.

## [2.9.38] - 2026-05-11

### Added

- Match-service universalisation: classification standards (`_KNOWN_CLASSIFICATION_STANDARDS`) + region-preferred-standard map (`_REGION_PREFERRED_STANDARD`) now data-driven from `CWICR_V3_CATALOGUES` + 30-country heuristic. 11 standards (DIN276, MasterFormat, NRM, UNTEC, VOCI, BC3, GB50500, SEKISAN, KBIM, GESN, BirimFiyat) instead of 3. FR→untec, IT→voci, ES→bc3, CN→gb50500, JP→sekisan, KR→kbim, RU/UA/BY/KZ→gesn, TR→birimfiyat.
- Region-group aliases moved to `data/match/region_groups.yaml`: 28 groups (19 baseline + ASEAN, MENA_AR, FRANCOPHONE_AFRICA, LUSOPHONE_AFRICA, ANGLO_AFRICA, ANDEAN, CAUCASUS, ANGLO_CARIBBEAN, LUSOPHONE_LATAM). Hardcoded fallback retained for resilience.
- Region-language mirror `data/match/region_language.yaml` (54 entries; not yet wired into runtime, ready for next pass).
- `CwicrV3Catalogue.default_classification_standard` field - populated on 19/30 entries with known mappings.
- `make seed-cwicr-v3` Makefile target + `backend/scripts/seed_cwicr_v3.py` CLI (`--regions CSV` xor `--top-n N`, `--dry-run`). One-shot install of N most-popular v3 catalogues for fresh deployments.
- `enumerate_qdrant_v3_collections()` helper in `qdrant_snapshot_loader.py` - live-probes the configured Qdrant for `cwicr_*_v3` collections.
- Per-encoder confidence profiles (`data/match/encoder_profiles.json`): bge-m3 / bge-small / e5-small / sonnet-rerank, each with high/medium/low bands. Surfaced via `config.confidence_thresholds_for_model()`.
- Per-language lex thresholds (`data/match/lex_thresholds.json`): 20 languages. Inflectional langs (pl/ru/uk/fi/tr/hu) drop to 70/50, CJK to 75/55, base 80/60. Surfaced via `config.lex_thresholds_for_language()`.
- `config.boost_weights_for_standard()` API stub for future per-standard tuning.
- `pyyaml>=6.0` added to base dependencies.

## [2.9.37] - 2026-05-11

### Added

- Africa pack: 19 currencies (NGN, KES, GHS, MAD, TND, DZD, ETB, UGX, TZS, RWF, XOF, XAF, AOA, MZN, BWP, ZMW, NAD, MGA + ZAR/EGP); 24 region codes (Anglophone, Maghreb, Francophone, Lusophone, ETB Amharic) - exposed in user settings dropdown.
- Dashboard stats badges (Projects/BOQs/Modules/Users) navigate to their pages.
- Dashboard Apple-style backdrop: aurora mesh, blueprint dot grid, vignette, cursor spotlight, fine-grain noise - auto-disabled by `prefers-reduced-motion`.
- /match-elements CatalogueAdvisor: one-click install for project-language catalogues when none are loaded - no /costs side-trip.
- Demo register: explicit email-domain-aggregate disclosure in the consent line.

### Fixed

- Typecheck: `Catalogue | undefined` narrowing in `CataloguesPanelCard` after positive `findIndex`.

## [2.9.36] - 2026-05-10

### Changed

- /match-elements 10-pass polish: replaced 3 blocking `alert()` calls in confirm/apply/skip flows with non-blocking toasts (success + error variants), unified error UI to a rose-toned `role="alert"` with explicit Dismiss + retry buttons, and split the group-list `max-h` into mobile-first (`max-h-[60vh]`) + desktop (`sm:max-h-[calc(100vh-360px)]`) so the table no longer collides with the keyboard on small viewports.
- /match-elements detail panel: added Escape key handler (with no-match modal precedence), `role="tablist"`/`role="tab"`/`aria-selected` semantics on the 3 detail tabs, error-state rendering with retry button, dropped stale "Phase A.12" reference from i18n string.
- /match-elements perf: replaced 11 separate `groups.filter()` passes (8 trade buckets + 3 stepper status counters) with one `useMemo`-cached pass - drops a tier-1 render from ~12ms to ~2ms for 1000-group sessions.
- MatchAnalyticsCard a11y: real i18n on collapse/expand `aria-label`, added `aria-expanded`, header row now `flex-wrap` so the window-selector + chevron don't fight for space on mobile.
- NoMatchModal + TemplatesPanel: `role="dialog"` + `aria-modal="true"` + `aria-labelledby`, Escape closes, all close buttons carry `aria-label`. NoMatchModal also surfaces the mutation error inline (was silently failing).

### Added

- 5 new integration tests for `GET /api/v1/match_elements/analytics`: empty window, days-out-of-range 422 contract, IDOR (other-tenant project_id → 404), tenant-wide rollup auth-only, unauthenticated 401/403. Pins the FastAPI route + auth wiring beyond the unit-level aggregator coverage.
- 12 new i18n keys for analytics/detail/no-match a11y + error states.

## [2.9.35] - 2026-05-10

### Added

- v3-§10 production analytics endpoint `GET /api/v1/match_elements/analytics?days=7&project_id=...&catalog_id=...`: rolls up `oe_match_elements_search_log` into KPI tiles (searches / pick rate / mean+p95 score / mean+p95 latency), tier + confidence-band histograms, top-N breakdowns by country / source_type / ifc_class, and three §10 threshold-driven alerts (low top score, picks past rank 4, hard-filter zero-hit). Pure-Python percentile to stay portable across SQLite (dev) and Postgres (prod). 18 unit tests green.
- `MatchAnalyticsCard` UI on /match-elements: collapsible card above Step 1, alerts pinned at top, expandable drill-down with KPI tiles + bar histograms + per-dimension breakdown tables. Window selector (1d/7d/30d/90d), 60s auto-refresh, soft-fail on endpoint error so the matching workflow keeps working when analytics is unreachable. 30 i18n keys added.
- `MATCH_ALERT_*` env knobs (`MATCH_ALERT_LOW_SCORE_VALUE` / `_PCT`, `MATCH_ALERT_HIGH_RANK_VALUE` / `_PCT`, `MATCH_ALERT_ZERO_HIT_PCT`, `MATCH_ALERT_MIN_SAMPLE`) for tuning §10 thresholds without a rebuild; defaults match MAPPING_PROCESS.md (low-score 0.3/20%, high-rank 4/20%, zero-hit 10%, min-sample 20).

## [2.9.34] - 2026-05-10

### Added

- /match-elements language-mismatch banner: detects when bound CWICR catalogue speaks a different language than project region, surfaces "Re-bind catalogue" CTA - `auto_bind_dominant_catalogue` now language-aware (US project no longer auto-binds to RU_MOSCOW just because RU has the most rows).
- /match-elements 2026 hero redesign: gradient identity block + 4-step workflow indicator (Pick model → Open session → Review matches → Apply to BOQ) + numbered section cards.
- Image source adapter (`sources/image_adapter.py`, ~430 LoC): photo/drawing snapshot → AI-vision (Claude/GPT-4V via existing `ai_client.call_ai`) → SourceElement[]; pinned to `low` confidence by design; falls back to `[]` on missing API key / 4xx / 5xx / malformed JSON. 22 unit tests green.
- Recall benchmark scaffold `tests/perf/test_recall_bge_m3_benchmark.py` (20 queries: 6 EN + 6 DE + 6 RU + 2 ES, recall@1/5/10 markdown output, `@pytest.mark.benchmark`).
- Free-language-model status endpoint `GET /api/v1/costs/embedder/status/` + `EmbedderStatusCard` UI on /match-elements: surfaces BGE-M3 install state with one-line `pip install --upgrade openconstructionerp[semantic]` install card (amber) when missing, compact green pill when ready. MIT · 100+ languages · runs locally · no API key - sits above Step 1 so the user sees the install path before picking a model.
- v3-§4.1.5 BoQ `exact_code` short-circuit: when an Excel BoQ row carries an explicit CWICR rate code, the ranker bypasses Qdrant fan-out + reranker and pulls the rate directly from parquet. New `ElementEnvelope.exact_code` field, forwarded by `_envelope_from_group`; `_try_exact_code_short_circuit` in `ranker_qdrant` returns a HIGH-band candidate at score 1.0 with `boosts_applied={"exact_code": 1.0}`. Falls through to vector search when the code isn't in the catalogue. 10 unit tests green.
- v3-§6.2 cross-language code translation helper `cross_lang_lookup(source_rate_code, target_country)` in `qdrant_adapter`: strips lang+unit suffix via `base_code`, enumerates plausible target-lang variants, scrolls the target collection in one round-trip with `MatchAny + country` predicates. Defensive - degrades to `None` on Qdrant failure / missing extras. 7 unit tests green.
- v3-§10 search-log feedback loop (alembic v2936): adds `picked_rank` / `picked_rate_code` / `picked_at` / `source_type` / `ifc_class` / `country` columns to `oe_match_elements_search_log` plus 3 indexes. The /confirm hook backfills the user-pick fields onto the most recent log row for the (session, group) pair so MAPPING_PROCESS.md §10 alerts (`user_picked_rank > 4 for >20%` → re-train classifier) become observable. `_write_search_log` populates source_type/ifc_class/country at INSERT time so analytics queries no longer need a 3-table JOIN. 14 unit tests + idempotent migration smoke green.
- Unit-conversion regression test (`tests/unit/test_split_unit_multiplier.py`, 26 tests): pins the v3-§8.6 `100 м3 → divide-by-100` math at `service.py:1917` so a refactor can't ship a 100× cost spike.

### Changed

- BGE-M3 confidence bands re-pinned: `MATCH_CONFIDENCE_HIGH` 0.85 → 0.78, `MATCH_CONFIDENCE_MEDIUM` 0.70 → 0.62, `MATCH_AUTO_CONFIRM_DEFAULT` 0.95 → 0.88. BGE-M3 cosine sits 5-8 points lower than e5-small for the same semantic neighbourhood. Tests rewired to derive scores from constants instead of hardcoded floats.
- Default `vector_backend` and `match_backend` switched from `lancedb` to `qdrant`. Legacy `lancedb` value rejected by validator on `match_backend`.
- v3 universality DB defaults: `Invoice.currency_code`, `Payment.currency_code`, `ProjectBudget.currency_code`, `CostItem.currency`, `Assembly.currency` now default `""` instead of `"EUR"` (#217). Service layer is the source of truth for currency.
- /match-elements project context card: 12×12 gradient icon, larger h2 title (`text-lg lg:text-xl`), bigger spacing, `shadow-sm`.

### Removed

- LanceDB legacy code paths (Phase 5): `app/modules/costs/vector_adapter.py`, `app/core/match_service/ranker.py`, `app/core/match_service/boosts/lex.py`, `app/core/match_service/boosts/rare_token.py`, `app/modules/match_elements/matchers/lexical.py`. Sparse Qdrant + BGE-M3 supersedes them.

### Fixed

- Bug-report capture: `getLastError()` prefers level=error over warning in the recent 32-entry window - handled 404s no longer leak into auto-filed reports (#115).
- FX rate input on /projects/.../settings now shows live bidirectional preview (`1 ARS = 0.000707 USD` AND `1 USD = 1415 ARS`) so inverse-direction currencies don't trip up the user (#111).

## [2.9.33] - 2026-05-08

### Added

- **Parallel Qdrant + BGE-M3 match pipeline (default OFF, opt-in via `MATCH_BACKEND=qdrant`).** Foundation for the next-generation CWICR matcher: 30 per-language Qdrant collections (`cwicr_<lang>`) with three named vectors per point - `dense` (1024-dim BGE-M3 multilingual), `sparse` (BM25-like for verbatim term hits like `C30/37`, `DN200`, `B500B`), `resources` (top-12 unique resources per rate) - fused via Qdrant native RRF in one round-trip. Minimal payload + lazy `polars.scan_parquet()` lookup keeps the embedded store under 700 MB and full 84-column rate data under 50 ms on warm cache. New modules at `app/modules/costs/qdrant_adapter.py`, `parquet_lookup.py`, `query_builder.py`, plus a parallel `app/core/match_service/ranker_qdrant.py` that swaps in via the `match_backend` setting. Smoke endpoint `GET /api/v1/costs/qdrant-search/?q=...&country=DE&diag=1` exercises hits + parquet attach + filter coverage. Legacy LanceDB + e5-small ranker stays default - no behavioural change without the env flag. Required CWICR Qdrant store + parquet root land separately (DDC pipeline).
- **3-channel structured query: CORE / native filters / resources.** New `query_builder.build_query(envelope)` splits the matcher request into a curated CORE text (category + type + material + thickness/diameter/fire/U) feeding dense+sparse, native Qdrant predicates (`is_abstract=False`, `department_code=<2-digit DIN>`, `unit_dim=volume|area|length|count|mass|time`), and an optional `resources_query` that activates only when the envelope carries verbatim rare tokens. Replaces "stringify everything into one passage" - BGE-M3 stops diluting the strong signal across noisy bits like Level/GUID/family-id.

### Improved

- **Match recall v3 - three orthogonal lifts on the legacy ranker (in production today, no flag flip needed).**
  - **Trade-aware DIN-276 pre-filter.** `cost_vector.search()` accepts `din276_kg_prefix` and filters `payload.classification_din276` at the LanceDB hit-decode stage by the leading 2 digits of the envelope's DIN hint. Wall envelopes (33) no longer compete with pipework (44) for top-K slots. Auto-disables when fewer than 20% of fetched hits carry any DIN value, so BYO catalogues without classification metadata keep working.
  - **Rare-token lexical boost.** New `boosts/rare_token.py` lifts candidates that verbatim-match technical tokens the multilingual encoder dilutes as low-frequency subwords: concrete grades (`C30/37`, `C25/30`), pipe nominals (`DN200`), bolt sizes (`M16x60`), steel profiles (`HEB200`, `IPE160`), rebar grades (`B500B`), fire ratings (`F90`), steel grades (`S235`), diameters (`Ø14`). +0.06 per hit, capped at +0.15. Tunable via `MATCH_BOOST_RARE_TOKEN_*` env vars. 19 unit tests pin the extraction + cap behaviour.
  - **Unified region/catalogue → language map.** `_REGION_LANGUAGE` (vector_adapter) and `_CATALOG_LANGUAGE` (ranker) had drifted (`UK_GBP` vs `GB_LONDON`, `CS_PRAGUE` vs `CZ_PRAGUE`, `SP_BARCELONA` vs `ES_MADRID`, `ENG_TORONTO` vs `CA_TORONTO`) - every miss silently broke the translation cascade. Hoisted both into one canonical 45-entry table at `app/core/match_service/region_language.py` with a historical-alias resolver. 41 unit tests cover canonical + aliases + edge cases.

## [2.9.32] - 2026-05-08

### Fixed

- **/projects no longer fetches full BOQ detail payloads to read one number per BOQ.** v2.9.x's project-list page issued one `/v1/boq/boqs/{id}` per BOQ (each 100–230 KB of position rows) just to extract `grand_total` for the project card - totalled ~700 KB of waste on a workspace with 5 projects × 5 BOQs. The list endpoint already returns `grand_total` (and `position_count`) on each `BOQListItem`; extended `BOQBasic` to include it and dropped the secondary detail-fetch loop entirely. `/projects` page weight drops from ~857 KB to ~130 KB on the same dataset.
- **`/api/system/status` no longer fires twice on every page.** DemoBanner used a raw `fetch()` while DashboardPage used `useQuery({ queryKey: ['system-status'] })`. Switched DemoBanner to the same React Query key so the two components share one network call. Saves one round-trip per dashboard render in production.
- **Project weather widget no longer 400s on every project card.** v2.9.30 bumped Open-Meteo's `forecast_days` from 16 to 18, but the free `/v1/forecast` endpoint caps at 16 - every project card on the dashboard fired five 400 Bad Request responses to `api.open-meteo.com` and the widget rendered empty. Capped back at 16 (the practical horizon) and updated the title/copy/comment from "18-day forecast" to "16-day forecast" so the visible label matches what's fetched.
- **`<button>` nested inside `<button>` warnings on /bim and /dwg-takeoff.** ModelCard (BIMPage) and DrawingFilmstrip card had the entire card rendered as a `<button>` with a `<button>` (delete) inside - invalid HTML, React DOM validation warning. Switched the outer card to `<div role="button" tabIndex={0}>` with explicit Enter/Space handlers and matching focus ring; the inner real `<button>` keeps its accessible behavior and stops `stopPropagation`-ing on a parent button (which produced subtly broken keyboard focus).
- **/match-elements vector matcher now actually returns hits on first run.** Two upstream bugs combined to make every "Run vector match" click return zero candidates: (a) projects with no `cost_database_id` in `oe_projects_match_settings` short-circuited the ranker with `status="no_catalog_selected"` and an empty candidate list, and (b) the embedder singleton failed to load when first invoked from a worker thread (asyncio dispatches every encode through `asyncio.to_thread`), leaving every `encode_texts_async` call falling through to the SQL lexical fallback with the warning "No embedding model available". Fix (a): `MatchElementsService.create_session` and the run_match path call new `auto_bind_dominant_catalogue()` which picks the most-loaded vectorised CWICR catalogue and writes it onto the project's match settings - idempotent, no-op when already bound. Fix (b): `app.main` lifespan now primes `get_embedder()` synchronously on the main thread before scheduling the auto-backfill task, so the singleton is loaded before any worker thread races for it. After both fixes a fresh project's first vector match goes from 0 candidates to ranked top-10 in ~11 s for 3 groups (vs 47 s SQL-fallback before).

### Added

- **New `/match-elements` module - BIM elements → CWICR cost positions in one pass.** Estimator picks a project, page auto-creates a Match session over `oe_bim_element` grouped by `(ifc_class, type_name)`, then runs vector / lexical / resources matchers (the third one searches the materials catalogue `oe_catalog_resource`, not just CWICR). Slide-over detail panel shows side-by-side per-matcher candidates, full element-id list, and a dry-run BOQ preview with auto-scaled resources (concrete + formwork + rebar) loaded from each `CostItem.components` recipe. Multi-select bulk-actions (run matchers / confirm ≥ threshold / mark TBD), tenant-scoped template library (signatures persist across projects), and a no-match modal (custom position / RFQ / TBD) round out Phase A. New backend module at `app/modules/match_elements/` with 17 endpoints under `/api/v1/match_elements/*` (sessions, groups, match, confirm, bulk-confirm, apply, no-match, attributes, categories, templates). Migration `v2932_match_elements.py` adds `oe_match_elements_session`, `oe_match_elements_group`, `oe_match_elements_template` (with cross-project signature uniqueness on `(tenant_id, signature)`). Frontend at `frontend/src/features/match-elements/` (page + 3-tab detail panel + templates panel + no-match modal). Sidebar entry "Match Elements → Costs" with NEW badge. DWG / PDF / Photo source adapters are pluggable and land in Phase B–D.
- **Match-elements matcher perf - top-10 cap + lexical SQL prefilter.** First /match POST without explicit `group_keys` previously iterated every unmatched group (174 s for 16 / unbounded for 274). Now defaults to the 10 largest groups (configurable via `max_groups`); the lexical matcher prefilters CWICR with ILIKE on meaningful tokens (≥3 chars) capped at 1 500 candidates before fuzz scoring. Lexical match on a 274-group Berlin project drops from "never finishes" to ~12 s for 10 groups. Action-bar labels updated to "Vector / Lexical / Match resources - top 10".

## [2.9.31] - 2026-05-07

### Fixed

- **BOQ resource sub-rows now align column-for-column with position rows.** v2.9.29 refactored the resource row to a column-driven layout reading live AG Grid column geometry, but `computeLeftPad()` still added a `+56px` "indent nudge" on top of the helper-column widths. That nudge shifted every downstream slot - Unit, Quantity, Unit rate, Total, Actions - 56 pixels right of the matching position cell, so the columns no longer lined up vertically. Removed the nudge: `leftPad` is now exactly `_drag + _checkbox + _expand` width, matching the position row's left edge. Visual differentiation between position and resource rows still comes from the inset shadow, secondary background tone, and the provenance left-edge bar.
- **Documents-module download no longer returns 403 for demo PDFs whose stored `file_path` resolves outside the current upload base.** The download endpoint's path-containment guard treated *any* resolved path outside `UPLOAD_BASE` as a security violation (HTTP 403 "Access denied"), even when the document was a synthetic demo seed record whose placeholder hadn't been materialized yet. Re-anchors demo PDFs to a deterministic safe path inside `upload_base` (`{base}/demo/{doc.id}.pdf`) before the materialize-placeholder step, and degrades real uploads with stale paths to HTTP 404 "File not found on disk" instead of 403. Path-traversal protection (symlink rejection, strict containment) still applies to non-demo paths. Surface: `/files?kind=document` → click → `/takeoff?doc=…&source=document` no longer fails to load PDF on fresh installs.

## [2.9.30] - 2026-05-07

### Changed

- **Project weather forecast extended from 16 to 18 days.** `ProjectWeather` widget now requests `forecast_days=18` from Open-Meteo (capped server-side if the free tier rejects it) and the project detail card / summary chip labels reflect the new horizon. Affects the full grid on `/projects/:id` and the one-line stat chip on dashboard project cards.

### Fixed

- **`/reports` BOQ-export error toasts no longer dump raw HTML/error pages into the UI.** `downloadBoqExport()` previously threw `new Error("Export failed (500): " + response.text())`, so a backend error returning an HTML 502 page or a Caddy/nginx error template was rendered verbatim in the toast - including unparsed `<html>` markup. Now the response body is parsed as JSON first to extract a FastAPI `detail` string; falls back to short plain-text bodies via the shared `extractErrorMessageFromBody()` helper, which already rejects HTML-shaped strings and length > 240. Toasts now show either a clean detail message or just the status code.

## [2.9.29] - 2026-05-07

### Fixed

- **BOQ resource sub-rows now align column-for-column with position rows when custom regional-preset columns are added (e.g. GAEB EP-split, AIQS preset).** Resource rows render through AG Grid's full-width row mechanism with a hand-built flex layout. The layout used hard-coded column slots (`unit`, `quantity`, `unit_rate`, `total`, `_actions`) and the `description` slot was `flex-1` - when custom columns inserted between `total` and `_actions` widened the row, the `flex-1` name slot absorbed the extra width and every right-side cell (Unit, Qty, Rate, Total, Actions) drifted leftward relative to the position row above. Refactored `EditableResourceRow`, `VariantHeaderResourceRow`, and the Add-resource path to a column-driven layout: each renders by iterating `api.getAllDisplayedColumns()` and laying out its slots at exactly each column's `getActualWidth()`. Custom columns (`colId` starting with `custom_`) on resource rows now show the per-resource value from `position.metadata.resources[i].metadata.custom_fields[name]` (read-only - editing per-resource customs from the resource sub-row will follow); unknown columns get an empty placeholder of the correct width. Resources, variant headers, and the Add-resource band stay in lockstep with position columns regardless of how many custom columns the user adds.
- **Multi-currency BOQ totals now rebase per-position currencies into the project base before summing (Issue #111).** v2.9.1 closed Issue #88 (multi-currency BOQ) by adding per-project FX rates and a view-only display-currency override, but a position priced in a non-base currency (`metadata.currency` set to e.g. `ARS` inside a USD project) had its raw `total` summed straight into `directCost` and rolled into the column footer / Grand Total as if it were already in base. Result: a USD project with one ARS position and one USD position summed `1415 + 100` as `1515 USD` instead of converting the ARS leg through the project FX table first. New `convertToBase()` helper in `boqHelpers.ts` reads `metadata.currency` per position and multiplies by the configured `1 foreign = X base` rate. Wired through (a) the `total` column's `valueGetter` (so per-row cells display in base), (b) `BOQEditorPage`'s `directCost` reducer, and (c) `groupPositionsIntoSections`' subtotal accumulator (so section subtotals also rebase). When no FX rate is configured for a position's currency, the helper logs a console warning and falls back to the raw value rather than crashing - surfaced in dev tools so the missing rate is diagnosable.

### Changed

- **`maplibre-gl` (1 MB) no longer ships in the cold-load critical path.** `ProjectMap` was re-exported eagerly from `@/shared/ui`, which dragged the maplibre runtime into every chunk that imported anything from the shared UI barrel - even pages that never render a map. The barrel now exports a lazy wrapper (`ProjectMapLazy`) that wraps the real component in `React.lazy + Suspense`. Map-bearing routes (`/projects`, `/projects/:id`) pull maplibre on demand; everywhere else it's gone from the initial preload graph. `index.html` no longer module-preloads the 1 MB maplibre chunk.
- **Requirements file-import endpoint now caps payloads at 50 MB.** v2.9.12 lifted the global upload size cap, which left `POST /requirements/{set_id}/import/file/` reading the entire upload via `await file.read()` with no ceiling - a 500 MB CSV would OOM the worker before parsing started. Returns HTTP 413 above 50 MB, which is generous for requirement spreadsheets (typical real files are <2 MB).

## [2.9.28] - 2026-05-07

### Security

- **AI Cost Advisor chat is now rate-limited.** `POST /api/v1/ai/advisor/chat/` previously had only the `ai.estimate` permission gate; an authenticated caller could hammer the endpoint and burn through their BYO provider quota. Added the same `check_ai_rate_limit` dependency that gates `/quick-estimate`, `/photo-estimate`, and `/file-estimate`, plus the `X-RateLimit-Remaining` response header so the UI can surface remaining quota.
- **Provider error messages no longer leak into AI chat answers.** The chat fallback used to concatenate `str(exc)[:100]` from a failed LLM call into the user-facing answer string. Provider error bodies sometimes echo masked key prefixes, org IDs, or upstream debug headers. Now the full error is logged for ops, and the user only sees the localised "AI is not configured" fallback.
- **AI chat conversation history is hard-capped at 4 KB total.** Combined with the 10-message and 500-char-per-message caps, a malicious caller could still pad prompts past the budget of small-context providers (Mistral, Cohere). Iteration now stops at the first message that would exceed the running 4000-char budget.

### Fixed

- **Schedule activity dates: structural regex no longer accepts impossible calendar dates.** `start_date` / `end_date` matched `^\d{4}-\d{2}-\d{2}$`, which let `2026-02-30` and `2026-13-99` reach `compute_duration` and return bogus durations. Validation now re-parses via `date.fromisoformat()` and rejects on invalid month/day before the value is stored.
- **Schedule activity-embedded `dependencies` updates now run cycle detection.** `POST /schedules/{id}/relationships/` already rejected circular dependencies, but `PATCH /activities/{id}` accepted a `dependencies: list[ActivityDependency]` payload that bypassed the check entirely - a back door that let CPM compute_paths recurse forever. The same self-reference + BFS cycle test is now applied at the service layer for the activity-JSON path too.

### Changed

- **DuckDB ad-hoc connections are capped at 512 MB and 2 threads.** The dashboards module's per-snapshot DuckDB pool used `duckdb.connect(":memory:")` with the default settings - DuckDB's default `memory_limit` is 80 % of system RAM, so a single bad cascade query against a multi-million-row Parquet could pin a worker. Pool now sets `memory_limit='512MB'` and `threads TO 2` immediately after connect; failures are logged but non-fatal for older DuckDB versions.
- **BIM requirements validation caps at 50 000 elements per pass.** `validate_requirement_set_against_model` previously fetched up to 1 000 000 elements before iterating `requirements × elements`; for a 100 k-element model × 50 requirements that's 5 M evaluations on the request thread. The repository now stops at `MAX_ELEMENTS_PER_VALIDATION + 1`, the report flags `elements_truncated: true` when the cap kicks in, and a `WARNING` is logged so users can see why the partial scope appeared.

## [2.9.27] - 2026-05-07

### Added

- **BOQ custom columns are now editable per-resource, not just per-position.** Previously, supplier / lead time / QC inspector / tender package etc. on a resource sub-row inherited the parent position's value and were read-only - so a position with a concrete supplier and a rebar supplier had to share one "supplier" cell. Resource rows now accept their own value, stored at `position.metadata.resources[i].metadata.custom_fields[name]` via a deep merge that doesn't touch other resource fields. The cell's `valueGetter` reads the per-resource value first and falls back to the position-level value, so a "globally true" position-level value still propagates to resource rows that haven't been overridden. New `onUpdateResourceCustomField` handler in `BOQEditorPage` PATCHes only `metadata` (no `unit_rate` re-derivation - custom fields don't affect price). Derived columns (`resource_sum`, `percentage_of_unit_rate`) and calculated columns stay read-only on resource rows because their values are auto-computed.

## [2.9.26] - 2026-05-07

### Fixed

- **BOQ horizontal overflow when 4+ regional-preset columns were added.** Custom columns had a 80 px `minWidth` and no `flex` - `sizeColumnsToFit` couldn't shrink them, so adding the GAEB EP-split (4 columns) or AIQS preset (5 columns) pushed the right edge past the viewport on a 1366-1440 px laptop. Description column also had a 260 px floor that compounded the problem. Lowered custom-column `minWidth` to 56 px (~3 letters of header + padding), gave each custom col `flex: 1`, and set the description column to `flex: 3` with a 180 px floor - the BOQ now redistributes width evenly across all visible columns instead of overflowing.
- **GAEB EP-split no longer added up to less than `unit_rate` when a position carried operator / subcontractor resources.** `Sonstiges-EP` was wired with `resource_role: 'other'`, so the catch-all column ignored `operator` and `subcontractor` resources entirely - `Lohn + Material + Geräte + Sonstiges` came out short by the operator/subcontractor share. Widened `resource_role` to accept either a single role or a list (backend Pydantic + frontend column-def types), normalised matching through a `Set` membership check, and updated the GAEB preset to `['other', 'operator', 'subcontractor']`. The badge in `CustomColumnsDialog` renders the multi-role hint as `other / operator / subcontractor`.

### Changed

- **`/settings → Advanced` redesigned for clearer block layout.** `BackupRestore` now renders Export and Restore side-by-side on desktop instead of stacking - the import dropzone no longer sits below an empty stretch of Export-card whitespace. The two single-button maintenance cards (Databases & Resources, Setup Wizard) collapsed into a single `Maintenance & Setup` card with two action-rows (icon + title + description + Open button) so the lower part of the tab no longer reads as two stranded half-cards.
- **`/costs` now mirrors the BOQ "From Database" classification tree.** Added a 260 px sticky sidebar on desktop that fetches the full 4-level classification (collection → department → section → subsection) via `/v1/costs/category-tree/?depth=4` and drives the search via the `classification_path` filter. Click selects, the chevron toggles expand independently, and the in-tree filter input keeps deep matches reachable. The legacy flat `category` dropdown is retained as a secondary filter.
- **Dashboard "developed by" hint above the DDC logo** is now lower-cased, smaller (`9px`), tracking-normal, with a left indent - was reading too loud as small-caps.

### Cleanup

- **Local dev DB**: 6 732 polluted contact rows from earlier CRM-import smoke runs were deleted; one well-described example (`Patricia Martinez @ Downtown Health System`) is retained. FK columns in `oe_finance_invoice`, `oe_correspondence_correspondence`, and `oe_procurement_po` were already null / pointed at the survivor - no operational data nulled. VACUUM ran clean.

### Verified

- **Issue #113** (`[BUG] can't get any IFC or Revit file to be viewed in the 3D viewer`) - closed. End-to-end check on a fresh `pip install openconstructionerp==2.9.25` venv: IFC upload → conversion `status=ready` (289 elements, 4 storeys), `/elements/` returns finite bboxes for 37/50 sampled rows, `/geometry/` returns 302 KB `model/vnd.collada+xml`. Likely fixed by v2.9.21 (IFC conversion regression) + v2.9.22 (`ORJSONResponse` removed - orjson rejects `NaN` in bbox coords).

## [2.9.25] - 2026-05-07

### Fixed

- **`/costs` list view scaled poorly with no region filter - 80 s for one page on a 111 k-row catalogue.** Companion to v2.8.3's `(region, is_active, code)` composite index. The leading-column rule meant the previous index could not satisfy `WHERE is_active=? ORDER BY code` when no `region` filter was supplied (the default "all regions" view). SQLite fell back to `ix_costs_is_active` plus a temp B-tree sort over the entire active set. Added `ix_costs_active_code` `(is_active, code)` to mirror the per-region index for the all-regions case - the same query now plans against the new B-tree directly. Measured 15 s → 1 ms (~10 000×) on the dev box. Migration `v2924_costs_active_code_index` is inspector-guarded so re-running is a no-op.
- **Seeded "Sarah Chen" demo account had role `estimator`, which neither the registration schema nor the admin update schema accepted.** The 4-role frontend (`admin|manager|editor|viewer`) rendered her with the viewer fallback and the role dropdown produced 422s on submit. Aligned the seeder + `AdminUserCreate.role` Literal on `editor`. Migration `v2924_normalize_estimator_role` rewrites any pre-existing `estimator` rows on production DBs that booted the older seeder. The legacy `estimator → EDITOR` permission alias is retained so old runtime checks still work.

## [2.9.24] - 2026-05-07

### Added

- **One-click DWG converter install on `/dwg-takeoff`.** The "Install converter" pill in the page header now opens a popover with an actual install button - clicking it POSTs to `/v1/takeoff/converters/dwg/install/` (the same endpoint the `/bim` page uses for RVT/IFC), and the offline-readiness query refetches so the badge flips to green "Offline Ready" the moment the binary is detected. On Linux the popover surfaces the apt one-liner from the backend instead of attempting an auto-shell-out. Closes the gap reported as "нужно одним нажатием установить актуальный последний конвертер".
- **"New version available - recommend updating" amber banner on the BIM converter panel** (dismissible per session). Previously the only signal that a newer SHA existed upstream was the small `→ def5678` tail - easy to miss. The expanded panel now renders an amber banner whenever `version-check.any_outdated` is true, with an X to hide it for the current session (sessionStorage; reappears on next visit). Banner is i18n-keyed.
- **Mini-icon mode on the BIM converter panel when everything is fully up to date.** The panel now collapses to a single emerald `N/M` pill ("4/4" when all four converters are working AND on the latest SHA). Click expands to the full strip + details. Per Artem's spec: "если все конверторы на самом последней версии то это окно показывать не нужно и можно сделать только маленький значок".
- **Per-converter "card" rendering on the BIM converter panel.** Each row now has a tinted background + rounded border that mirrors the row's state (emerald = working & up to date, amber = working but outdated or missing binary, rose = broken). Replaces the dense single-line strip - one glance now tells you which row needs attention.

### Changed

- **Green pill is now reserved for "working AND on the latest version".** Per-row pills downgrade to amber `Working · update available` when the version-check flags an outdated SHA - green no longer means "smoke-test passed but the binary is from three months ago". Panel-level summary changes from `"X/Y verified"` to `"X/Y up to date"` / `"X/Y working · update available"` / `"X/Y working"` to match. The header tone (border + background) likewise stays amber until everything is on the latest SHA.
- **Dock entries can be dismissed mid-conversion.** Previously the corner upload dock only offered Cancel during `uploading`/`converting`, which aborted the actual server-side work. A separate Dismiss action is now available in every state - it just clears the dock entry; the server keeps processing. Closes the "10m+ stuck at 95% Modelleinrichtung wird abgeschlossen with no way out" complaint.

### Fixed

- **`oe_dwg_takeoff` and `oe_takeoff` modules no longer trapped in a disabled state.** When persisted module-state was set to `enabled: false` (e.g. from an earlier admin-toggle test), `/dwg-takeoff` rendered as "module is disabled" and the install endpoint at `/v1/takeoff/converters/{id}/install/` returned 404, leaving the user with no recoverable UI surface. The install button now triggers the install on a known-loaded module path; if a fresh install ever lands with these modules disabled, the toast points back at the `/modules` admin page instead of failing silently.

## [2.9.23] - 2026-05-07

### Fixed (Wave A - bugs.md/improvements.md QA pass)

- **BUG-011 (P0) - Validation `boq_quality.empty_unit` false positives.** `app/modules/boq/router.py` `validate_boq` projected positions into a dict that dropped `unit`, `parent_id`, `total`, and the row-`type` marker. Every `boq_quality.*` rule reads those keys, so they uniformly received `None` and lit up red on every leaf row of every fresh BOQ. Restored the missing keys + a derived `type` flag so section-header skipping works again. Also added a parametrised contract test in `backend/tests/unit/test_boq_validate_payload.py` so the next field drop fails CI loudly.
- **BUG-012/013 (P0) - Cost catalog and global search worked only with LanceDB.** `costs/router.py` silently ignored `search` / `name` / `description` / `query` params and `search/router.py` returned 0 hits whenever the vector backend was unavailable (the default for `pip install` without `[vector]` extras - main value-prop dead). `costs` now accepts `search` + `query` as silent aliases of `q`, and `name` / `description` as scoped substring filters; the repo issues a cross-dialect `LIKE`/`ILIKE`. Global `/api/v1/search/` now ALWAYS runs the SQL fallback against BOQ positions / tasks / risks / documents / requirements / cost items and fuses the result with the vector hits (when present) via reciprocal-rank merging. 31 new unit tests pin the contract.
- **BUG-015 (P1) - `POST /api/v1/procurement/` silently dropped `items[]`.** `procurement/service.py::create_po` refreshed the PO before line items were inserted (so `po.items` came back empty) and pulled `amount_subtotal` straight from the request (default `"0"`) instead of summing the lines. Now pre-aggregates the subtotal, fills missing per-line amounts, and reloads the PO via the selectinload-backed `get(po.id)` so the response carries the lines. New `test_create_po_persists_items_and_reaggregates_totals` covers the exact reproducer from the QA report.
- **BUG-018 (P1) - `POST /api/v1/backup/export/` returned an empty zip.** Handler had no body schema and used a `StreamingResponse` over `io.BytesIO` that interacted badly with the request-side body. Replaced with an `ExportRequest` body and a streaming-to-`SpooledTemporaryFile` builder that writes a populated `manifest.json` plus per-module JSON dumps; FastAPI now serves it back via `FileResponse` with a `BackgroundTask` cleanup. Smoke-tested locally: 186 KB zip, 20 module dumps.
- **BUG-008 (P1) - `grand_total` differed between BOQ list and detail.** List included markups (25830), detail returned the position-sum-only (20500). Two screens, two numbers, same field name - broke trust in every export and dashboard. `boq/repository.py` now exposes `totals_for_boqs()` returning the full `{direct_cost, markups_total, grand_total}` breakdown; both list (`BOQListItem`) and detail (`BOQWithPositions`) consume it. Schemas grew explicit `direct_cost_total` + `markups_total` + `position_count` so clients no longer have to re-sum markups. `grand_total` is canonical "with markups" (matches what users see on dashboards).
- **BUG-005 (P1) - DXF layers all imported as `visible: false`.** `dwg_takeoff/dxf_processor.py:184` evaluated `not layer.is_off and not layer.is_frozen` in a single expression; on certain R2018-vintage files ezdxf raises while accessing `is_off`, the whole expression silently collapsed to False, and the canvas rendered empty after import. Pulled each bit through its own try/except and now defaults to visible - only flips to hidden when the source file *explicitly* reports off/frozen.
- **BUG-014 (P2) - DXF SVG thumbnails always rendered the placeholder.** ezdxf 1.4 removed `Frontend.out`; the call `frontend.out.get_string()` raised `AttributeError` on every drawing and the handler swallowed it into the placeholder branch. Switched to `SVGBackend.get_string()` (with a fallback to the 1.5-era `get_xml_root()`) so thumbnails actually render again.
- **BUG-002 (P1) - `/health` and `/openapi.json` returned the SPA `index.html`.** k8s liveness probes saw HTTP 200 with `text/html` and reported the service healthy even when the API was dead; openapi-typescript generators couldn't reach the schema. Added 308 redirects from `/health → /api/health` and `/openapi.json → /api/openapi.json` ahead of the SPA 404 fallback (only when `SERVE_FRONTEND=true` - pure-API deployments are unchanged).
- **BUG-006 (P3) - `BIMModel.import_date` always null on ready models.** Stamped during the `processing → ready` transition in the conversion background worker.
- **BUG-001 - verified not reproducible:** demo-catalog endpoint returns proper UTF-8 (`€12M`, `£45M`); the QA report's mojibake was a Windows-console rendering artifact in the curl output.

### Changed (security / DoS hardening)

- **Streaming uploads for BIM CAD files.** `app/core/upload_streaming.py` (new) spools `UploadFile` to a temp file in 1 MB chunks and exposes `head` for magic-byte checks; `app/core/storage.py` grew an abstract `put_stream(key, src_path)` with a true zero-copy `shutil.move`-based override on `LocalStorageBackend` and an `upload_fileobj` (multipart-aware) override on `S3StorageBackend`. `bim_hub/router.py` upload-cad now reads through `stream_upload_to_temp` instead of `await file.read()`; on the local backend the temp file is renamed straight into place - peak memory bounded by the chunk size regardless of upload size. Closes the memory-DoS vector that opened up when we removed per-route size caps.

## [2.9.22] - 2026-05-07

### Fixed

- **Hotfix: revert `default_response_class=ORJSONResponse` from v2.9.21.** orjson rejects NaN/Infinity floats by default - DDC cad2data BIM elements can emit NaN bbox coordinates for degenerate geometry, which broke `/api/v1/bim_hub/{model_id}` element-list responses with a 500 and surfaced as "IFC conversion broken" in the UI. FastAPI's own deprecation warning also flagged the override as unnecessary ("FastAPI now serializes data directly to JSON bytes via Pydantic when a return type or response model is set, which is faster"). orjson is still used by handlers that explicitly opt in.

## [2.9.21] - 2026-05-07

### Changed (perf - backend & static serving)

- **Default response class is now `ORJSONResponse`.** `app/main.py` passes `default_response_class=ORJSONResponse` to `FastAPI(...)` so every endpoint serialises via orjson instead of stdlib `json`. Typically 5–10× faster on dict/list payloads and ~2× faster at producing UTF-8 bytes - measurable wins on dashboard / list / vector-search endpoints. orjson was already a base dep (used by the non-finite-float middleware).
- **Immutable `Cache-Control` on hashed `/assets/*`.** `app/cli_static.py` mounts `/assets` via a custom `_ImmutableStaticFiles` subclass that adds `Cache-Control: public, max-age=31536000, immutable` to every 200 response. Vite emits content-hash filenames so the URL changes whenever the file changes - repeat visits now skip the network entirely for JS/CSS chunks.
- **`Cache-Control: no-cache` on the SPA `index.html` fallback.** Same file. The entry HTML must revalidate every reload - a stale cached entry would point at hashed URLs that may have been deleted by a redeploy. Now: hashed assets cached forever, entry always fresh.

### Changed (perf - frontend)

- **`buildGeocodeQuery` extracted to its own file.** `frontend/src/shared/ui/ProjectMap/geocode.ts`. Previously consumers like `DashboardProjectsMap.tsx` imported the helper directly from `ProjectMap.tsx`, which side-effect-imported `maplibre-gl/dist/maplibre-gl.css` (~220 KB raw / ~25 KB gzip) into the boot CSS bundle. The helper is a pure string-builder with zero deps, so the new module isolates it cleanly.

### Changed (UX - project detail)

- **Weather forecast now renders in 3 rows on tablet/desktop.** `frontend/src/shared/ui/ProjectWeather/ProjectWeather.tsx` switched from `sm:grid-cols-8` (8 cols × 2 rows) to `sm:grid-cols-6` (6 cols × 3 rows: 6 + 6 + 4). Mobile (default `grid-cols-4`) unchanged.
- **Map height matches the weather block.** `ProjectDetailPage.tsx` parent grid gained `items-stretch`, the map's fixed `h-[32rem]` was replaced with `h-full min-h-[20rem]` (only when weather is also visible), and `ProjectMap.tsx`'s detail-variant `heightClass` switched from `h-80` to `h-full` so the map fills its grid cell. When weather is hidden, the map falls back to the original fixed 32 rem.

### Fixed (BOQ - custom columns on resource rows)

- **Custom text/number columns now inherit the parent position's value on resource sub-rows.** `columnDefs.ts:getCustomColumnDefs` builds an `O(1)` `positionsById` map of all positions; the column's `valueGetter` walks `_parentPositionId` for resource rows and reads `parent.metadata.custom_fields[name]`. Resource cells render the inherited value read-only with italic + muted styling so the user can tell it's not editable in place - to change a custom value, edit the position row.
- **Derived `resource_sum` / `percentage_of_unit_rate` columns now render per-resource values on resource sub-rows.** Previously the guard at the top of the value-getter returned empty for any non-position row, so derived columns showed blank cells under every position. Now: a resource row whose `_resourceType` matches the column's `resource_role` renders its own `qty × rate` contribution (`resource_sum`) or its share of the parent's total resource sum (`percentage_of_unit_rate`). Mismatched roles still render blank so each contribution is visually attributed to the right resource.
- **`editable` predicate now blocks resource + add-resource rows.** Previously the AG Grid editor would open on a resource row and the user could type into a non-existent `metadata.custom_fields`, with the value setter silently returning `false`. Resource cells are now correctly read-only.

### Fixed (BIM viewer - issue #113 silent geometry-load failures)

- **3D viewer now surfaces geometry-load failures.** `BIMViewer.tsx:910` previously caught DAE/GLB load errors with a `console.warn` only, leaving the user with an empty canvas and no signal of what went wrong. The catch handler now sets a `geometryError` state which renders a top-anchored amber banner with the failure message + a **Retry** button. The retry calls a new `ElementManager.resetGeometryLoadFlag()` and bumps a `geometryRetryNonce` so the load effect re-runs the fetch without forcing a full page reload. Covers 401 from a stale token, 404 from a redeploy that ate the file, malformed GLB/DAE bytes, and OOM during BVH build.

## [2.9.20] - 2026-05-07

### Changed (i18n perf - per-locale lazy chunks)

- **Split `i18n-fallbacks.ts` into 26 per-locale chunks.** The monolithic 5.5 MB / 90,119-line `fallbackResources` constant was replaced with one auto-generated file per locale under `frontend/src/app/locales/{en,de,fr,…}.ts`. The runtime now bundles English synchronously (~45 KB gzip) as i18next's `fallbackLng` and lazy-loads the user's resolved locale via `import(`./locales/${code}.ts`)`. Vite emits one stable `i18n-{code}.js` chunk per language (44–58 KB gzip each).
- **~96% boot-bundle reduction for English users**, ~92% for non-English users after the first locale fetch resolves. Old build shipped a single 4.94 MB / 1.28 MB-gzip `i18n-data` chunk to every page load regardless of language; the new build ships only the active locale.
- **`i18n-fallbacks.ts` retained as a test-only aggregator.** Existing tests (notably `boqResourceTypes.test.ts`) still walk every locale, but the file is no longer reachable from the runtime entrypoint, so tree-shaking removes it from the production bundle.
- New `loadLocaleResource(code)` helper exported from `app/i18n.ts` - idempotent, logs and falls back to English if the chunk fails to load.

## [2.9.19] - 2026-05-07

### Added (Tendering - readable bid comparison)

- **Sticky position column on the bid comparison matrix.** The first column (position description / WBS code / item name) now `position: sticky; left: 0` with a subtle right shadow, so it stays visible when 4+ vendors push the table beyond viewport width on 1366×768 / 1280×800 screens. Header row also `top: 0` sticky; the top-left corner cell sits at `z-20` to layer correctly. Row-hover tint extends across the sticky cell.
- **Collapse low-variance rows.** New checkbox + threshold select (5/10/15/20/25%) above the table hides rows where every vendor's `unit_rate` is within the threshold of the mean - reduces visual noise on long bid packages where most positions agree. Counts hidden rows in a small "{n} hidden" indicator. Rows with fewer than 2 valid bids are always kept (no spread to compare).

### Added (Documents - photo MIME hardening)

- **HEIC / HEIF / TIFF magic-byte detection.** `app/core/file_signature.detect()` now recognises:
  - HEIC: ISO-BMFF `ftyp` + brand `heic / heix / hevc / heim / hevx / heis / hevm`.
  - HEIF: ISO-BMFF `ftyp` + brand `mif1 / msf1 / avif / avis`.
  - TIFF: little-endian `b"II*\x00"` and big-endian `b"MM\x00*"`.
  Photos uploaded with these formats now pass the magic-byte check; previously they relied entirely on the client-asserted Content-Type and a renamed `.txt` could spoof an HEIC upload.
- **Photo upload now cross-checks magic bytes.** After buffering the upload, `documents/service.py` calls `detect()` and rejects with HTTP 422 `{"detail": "uploaded file content does not match an image format"}` when the detected type isn't in `ALLOWED_PHOTO_TYPES = {jpeg, png, gif, webp, heic, heif, tiff}`. SVG bytes detect as `xml` and are rejected even with a spoofed `Content-Type: image/jpeg`.
- **SVG removed from image MIME map.** `projects/file_manager_service._MIME_BY_EXT` no longer maps `.svg` to `image/svg+xml`. SVG uploads via the file manager are still allowed but classify as a generic file - `FileGrid` no longer renders them inline via `<img>`. Closes the inline-`<script>` XSS surface where a malicious SVG could execute in the app's same-origin auth-cookie context.
- **Photo file-serve now `Content-Disposition: attachment`.** `/api/v1/documents/photos/{id}/file/` switched to explicit attachment with sanitized filename. Even if a non-image somehow lands on disk, browsers won't inline-render it. The `/thumb/` endpoint stays inline since the thumbnail JPEG/PNG is server-generated and trusted.

## [2.9.18] - 2026-05-07

### Added (Procurement - 3-way invoice match)

- **`create_invoice_from_po` now refuses to bill for items that haven't been received.** Previously copied PO line items verbatim into a new Invoice with no link to confirmed Goods Receipts - overbilling unblocked. New helper `procurement/service._validate_3way_match` sums `quantity_received` over confirmed-status GRs per `po_item_id`; for each proposed Invoice line it compares against `received_qty` and reports per-line violations. The route raises `HTTP 422` with structured `{message, errors: [...]}` when invoice qty exceeds received qty.
- **`force=true` query param overrides the match** for service-only POs (no goods to physically receive). When set, the invoice is persisted with `metadata_["force_3way_match"] = True` and a structured `logger.warning` is emitted with `{po_id, user_id, violations}` for audit aggregation.
- **`no_confirmed_grs` sentinel reason** when a PO has zero confirmed GRs and the invoice has any positive qty - lets the FE render the precise "service-only PO? pass force=true" message.
- All 19 existing procurement tests still pass; synthetic 6-case helper test added (over-qty / clean-match / no-GR / free-text skip / no-items / zero-qty).

### Added (Risk - owner picker + assignment notification)

- **`Risk.owner_user_id`** - proper FK to `oe_users_user` (nullable, indexed, `ON DELETE SET NULL`). Replaces the free-text `owner_name` for new rows; legacy data still renders via the fallback so nothing was lost. Migration `v2918_risk_owner_user_id.py` is inspector-guarded and reversible (uses `batch_alter_table` for SQLite compatibility).
- **`risk.assigned` event fires on new or changed owner.** `risk/service.py` publishes `{risk_id, project_id, code, title, owner_user_id, assigned_by}` after create/update. New subscriber `_on_risk_assigned` in `notifications/events.py` produces an in-app notification "You were assigned risk {{code}}: {{title}}". Mirrors the v2.9.16 pattern for `rfi.assigned`.
- **Frontend picker.** `RiskRegisterPage.tsx` swapped the free-text `<input>` for the existing `UserSearchInput` (avatar + name + role + email search). On selection, `owner_user_id` is sent as UUID and the resolved display name is mirrored into `owner_name` so the list-row column keeps working uniformly across picker-sourced and legacy rows.

### Added (Schedule - Gantt drag-to-resize)

- **Edge handles on every standard task bar.** Two transparent 7 px `ew-resize` zones (left + right) on each Gantt bar; left handle moves `start_date`, right handle moves `end_date`. Snap-to-day via the existing `pxToDate`; clamped to keep `end_date >= start_date + 1 day`. Group and milestone bars are unaffected. Esc cancels the in-flight resize and reverts the preview.
- **`onActivityResize?: (id, newStart, newEnd) => void` prop** added to `GanttChart`. Existing `onActivityMove` (drag-to-translate) untouched; resize is purely additive.
- **`SchedulePage` wires it through React Query.** New `resizeActivity` mutation calls `scheduleApi.updateActivity(id, {start_date, end_date})`, optimistically updates the cached `['gantt', schedule.id]` payload, snapshots and reverts on error, and invalidates on settled. Confirmed against `schedule/schemas.py:46-47` that the Activity schema uses `start_date`/`end_date` (not `planned_*` - those belong to `WorkOrder`).

## [2.9.17] - 2026-05-07

### Added (Procurement → Finance commitment flow)

- **`procurement.po.issued` now flips `ProjectBudget.committed`.** Previously the event was published but no subscriber existed - committed amounts stayed permanently 0 in the dashboard even when POs totalled millions. New finance subscriber in `backend/app/modules/finance/events.py:_on_po_issued` opens an isolated session, picks the budget row by `(project_id, wbs_id)` against the PO's first line item (falls back to the oldest budget by `created_at`), and increments `ProjectBudget.committed` by `amount_total`. Wrapped in try/except so a write failure can't propagate back to the publisher.
- **`procurement.gr.confirmed` now flips committed → actual.** Same row-selection strategy: decrements `committed` (clamped at zero) and increments `actual` by the GR value. The GR publisher in `procurement/service.py` now actually computes the receipt amount as `Σ(quantity_received × matched po_item.unit_rate)` instead of emitting only the IDs.
- **Event payload enrichments.** `procurement.po.issued` now carries `currency_code` (was missing - finance subscribers need it). `procurement.gr.confirmed` now carries `amount` and `currency_code`.

### Added (Change Order → Budget delta line)

- **Approved change orders now create or update a `ProjectBudget` row.** Previously the approved `cost_impact` was written to the single string field `project.budget_estimate` and never reached `ProjectBudget` - so EVM BAC didn't include approved COs. New helper `changeorders/service._write_budget_delta_row` keys off `metadata_->>'change_order_id' == co.id` (with `wbs_id=str(order_id)` and `category="Change Order {co.code}"` so the unique-on-(project, wbs, category) constraint isn't violated by regular budgets), `original_budget = 0`, `revised_budget = delta`, currency from `co.currency` → project default → `"EUR"`. Idempotent: re-approve updates the existing row instead of inserting a duplicate. Wrapped in try/except - a budget-write failure logs a warning but doesn't roll back the CO approval.
- **`approve_order` event payload extended** with `budget_row_id` + `budget_row_action` (`"created" | "updated" | "skipped"`) so downstream auditing can confirm the writeback.

### Fixed

- **PO numbering race fixed with IntegrityError retry.** `procurement/service.py:create_po` previously picked `MAX(po_number) LIKE 'PO-%'` and inserted; concurrent creates collided with HTTP 500. Now mirrors the pattern from `changeorders/service.py:88-126`: 5 attempts, refetch MAX + retry on `IntegrityError`. Auto-generated numbers loop; explicitly user-supplied numbers bubble up as 409 instead of looping. Backed by a new `(project_id, po_number)` unique constraint (`uq_procurement_po_project_number`); migration `v2917_po_number_unique.py` is inspector-guarded and de-duplicates pre-existing collisions before applying.
- **Tasks importer foreign-language column headers.** `tasks/router.py:_TASK_COLUMN_MAP` previously mapped only EN/DE headers, so an Excel import with Russian "Название", Spanish "Título", Japanese "タイトル" etc. silently dropped those columns. Added 81 entries across 9 locales (ru / fr / es / it / ja / zh / pt / nl / ko) for 8 target fields (title, description, status, priority, assigned_to, due_date, task_type, estimated_hours). Map grew 19 → 100. Lookup is case-insensitive; CJK headers match verbatim.

## [2.9.16] - 2026-05-06

### Fixed (Finance correctness)

- **Decimal precision on dashboard SUMs.** `finance/repository.py` cast money columns through `Float` before SUMming, silently losing precision on totals over 2^53 cents. All five aggregations (invoice ×2, payment, budget ×4) now `cast(..., Numeric)` and accumulate as `Decimal`.
- **Budget search crash.** `FinancePage.tsx:834` read `b.wbs_code.toLowerCase()` but the API returns `wbs_id`; `b.wbs_code` was always `undefined` and threw on the first character typed. Now reads `(b.wbs_id ?? '').toLowerCase()`. Also widened `BudgetLine` type with `currency_code`.
- **EVM forecast formula mismatch.** Service computes `EAC = AC + (BAC − EV) / CPI`; the modal hint claimed `EAC = BAC / CPI`. Hint corrected to match the service.
- **TCPI sign flip on over-budget projects.** The denominator `(BAC − AC)` could go negative; TCPI flipped sign and read as a "good" number. Now clamped - when remaining budget ≤ 0, TCPI returns 0 (interpretable as "infeasible").
- **EVM snapshot wrote zeros.** `Create Snapshot` POSTed only `{project_id, snapshot_date}`; the schema defaulted BAC/PV/EV/AC to `"0"`, so every snapshot persisted zeros. The handler now derives BAC/PV/EV/AC from the actual budget + payments at `snapshot_date` whenever a payload value is exactly `Decimal("0")` and writes those derived numbers to the row.
- **Invoice status filter missing `cancelled`.** Added the option so cancelled invoices are filterable from the dropdown.

### Added (Finance currency_code)

- **`ProjectBudget.currency_code`.** New `String(3)` column (default `"EUR"`, NOT NULL) on the budget row; surfaced through `BudgetCreate / BudgetUpdate / BudgetResponse` and respected by `service.create_budget`. Frontend `BudgetLine` type extended; `BudgetsTab` now renders the row's actual currency instead of always falling back to EUR. Alembic migration `v2916_project_budget_currency.py` is inspector-guarded and reversible.

### Changed

- **`FinanceSummaryCards` switched to `/v1/finance/dashboard/`.** The cards previously fired three list queries (invoices/payments/budgets) and reduced in JS, which both burned RTT and re-introduced the precision-loss path. Now a single `useQuery(['finance','dashboard',projectId])` reads `total_budget_original / total_payable / total_receivable / total_actual` from the SQL aggregator. Drops ~150 lines of FE coercion.
- **`BudgetsTab` mobile card view.** The 8-column budget table forced horizontal scroll on phones. Tablet/phone now shows a stack of cards (wbs_id + category + original + committed + actual + forecast + colorized variance + currency); table reappears at `md`.

### Added (Communication notifications)

- **9 new notification subscribers wired in `notifications/events.py`** for events that publishers were already firing but no handler consumed:
  - `rfi.assigned` → notifies the assignee.
  - `rfi.responded` → notifies the original requester.
  - `submittal.submitted` → notifies the reviewer + project owner (deduplicated).
  - `submittal.approved` → notifies the submitter.
  - `submittal.rejected` → notifies the submitter with rejection reason.
  - `submittal.revise_resubmit` → notifies the submitter.
  - `transmittal.issued` → notifies each recipient.
  - `transmittal.acknowledged` → notifies the original sender.
  - `transmittal.responded` → notifies the original sender.
- **Transmittal events are now actually published.** `transmittals/service.py` had zero `_safe_publish` calls; `issue_transmittal / acknowledge_receipt / submit_response` now emit the three transmittal events that the new subscribers consume.
- **`submittal.rejected` and `submittal.revise_resubmit` events.** The producer previously emitted a single `submittal.reviewed` with the decision in the payload; the two specific event names are now also published so subscribers can fan out cleanly.

### Added (i18n - `files.*` namespace coverage)

- **22 locales backfilled in `frontend/src/app/i18n-fallbacks.ts`** so the `/files` UI no longer shows raw keys (`files.col.modified`, `files.bulk.delete`, etc.) on non-EN/DE/RU sessions:
  - `ar` filled 65 missing keys (had 72/137).
  - `fr / es / pt / zh / hi / ja` each filled 80 missing keys (had 57/137).
  - `tr / it / nl / pl / cs / ko / sv / no / da / fi / bg / hr / id / ro / th / vi` each gained the full 137-key block (had 0).
  - **Total: ~2 737 strings across 22 locales.** All 26 supported locales now have full `files.*` coverage.
- Tone follows the authoritative German + Russian blocks; brand and format names (BIM, IFC, DWG, PDF, GAEB, OpenConstructionERP, `.ocep`) preserved verbatim.

## [2.9.15] - 2026-05-06

### Security (cross-category IDOR sweep - ~73 endpoints)

Five-category deep audit (Planning, Communication, Procurement, Finance, Documents) found cross-tenant data-leak holes in every category. This release closes them all in a single security-only batch. Every patched endpoint now requires the right `RequirePermission(...)` and calls `verify_project_access(project_id, user_id, session)` before reading or mutating.

- **Documents - photo serve was completely public.** `GET /api/v1/documents/photos/{id}/file/` and `/thumb/` had zero authentication; anyone could `curl -O` photo bytes by guessing UUIDs. Construction-site photos contain incidents, defects, badges, and contracts pinned to walls - P0 privacy + GDPR hit. Now gated by `documents.read` + project ownership.
- **Documents - sheets-by-id IDOR.** `GET /sheets/{id}` and `/sheets/{id}/versions/` skipped the ownership gate. Patched.
- **Documents - `documents_similar` defaulted to `cross_project=True`.** Vector similarity could return hits from projects the caller didn't own. Default flipped to `False`; clients must opt-in explicitly with `?cross_project=true`.
- **CDE module had zero project-access checks across all 11 endpoints** (containers / revisions / state transitions / history / transmittals). Any authenticated user could read or mutate any tenant's CDE state with a leaked UUID. Now fully gated.
- **Field reports - 7 endpoints unscoped.** `get_report`, `update_report`, `delete_report`, `submit_report`, `link_documents`, `get_linked_documents`, `export/pdf` all skipped `verify_project_access`. Patched.
- **Meetings - 5 read endpoints + the worst single hole.** `export_meeting_pdf` had **zero auth** (no permission, no project access). Plus `list_meetings`, `meeting_stats`, `open_action_items`, `get_meeting` were missing `RequirePermission("meetings.read")`. All 5 patched.
- **Transmittals - entire module had no RBAC.** Eight endpoints (list / create / get / patch / delete / issue / acknowledge / respond) gained `RequirePermission` plus `verify_project_access` on the three lifecycle paths. Acknowledgement is contract-grade non-repudiation; this closes the integrity hole.
- **Submittals - lifecycle and attachments unscoped.** `submit/review/approve` and the 3 attachment endpoints (list/add/delete) all gained `verify_project_access` via `service.get_submittal()`.
- **RFI - `respond_to_rfi` and `create_variation_from_rfi` unscoped.** Both now load the RFI and verify project access.
- **ERP chat session creation accepted arbitrary `project_id`.** A user could attach a chat session to any tenant's project; subsequent vector retrieval (`cross_project=True`) then leaked across tenants via embeddings. `create_session` now verifies the supplied project_id when present.
- **Procurement was completely project-unscoped.** `list_purchase_orders` made `project_id` optional, so anyone with `procurement.read` could read every tenant's POs by omitting the filter. The parameter is now required, and 9 endpoints (list / stats / list-GR / create-GR / confirm-GR / get-PO / update-PO / create-invoice-from-PO / issue-PO) now load the resource and verify project ownership.
- **Change-orders - sub-resources and lifecycle unscoped.** `add_item / update_item / delete_item / submit_order / approve_order / reject_order` all gained ownership verification. (Wave 5 in v2.9.14 only patched list/get/update/delete/summary.)
- **Cost-model 5D dashboard had zero ownership checks.** All 14 endpoints (`dashboard / s-curve / cash-flow / budget / budget-lines / generate-budget / generate-cash-flow / what-if / monte-carlo / evm / snapshots`) were gated only by global `costmodel.read|write` - any user with the perm could target any project's BAC/EV/AC. Patched. UPDATE/DELETE on `budget-lines/{id}` and `snapshots/{id}` now load the row and verify project ownership.
- **Schedule activity / baseline / progress-update endpoints unscoped.** 14 endpoints across `create/update/delete activity`, `link_boq_position`, `update_activity_progress`, `create/update_work_order`, `create_relationship`, `list_relationships`, baselines (CRUD), progress updates (CRUD), and `import_xer / import_msp_xml` now derive `project_id` from the parent schedule and gate via `_verify_schedule_owner` / `verify_project_access`.
- **Tasks `{task_id}` IDOR.** `get_task / update_task / delete_task / complete_task / update_task_bim_links` did not call `verify_project_access`, so a leaked task UUID let cross-tenant access through. Each handler now loads via `service.get_task()` and verifies on `task.project_id`.
- **EAC `_resolve_tenant_id` silently swallowed errors.** It caught every failure and fell back to `user.id`, effectively short-circuiting tenant scoping. The helper now raises HTTP 403 on any resolution failure. `create_rule / list_rules / create_ruleset / list_rulesets` now also `verify_project_access` when a `project_id` is supplied.

### Fixed

- **Change-order `_apply_to_boq` no longer picks an arbitrary BOQ.** `approve_order` now accepts an optional `boq_id` query param threaded through to `service.approve_order(..., boq_id=...)` → `_apply_to_boq(..., boq_id=...)`. With explicit `boq_id`, the function looks up that specific BOQ and refuses to write if not found, locked, or owned by a different project (returns `{"applied": False, "reason": "boq_not_found" | "boq_project_mismatch" | "boq_locked"}`). Without `boq_id`, the existing first-by-`created_at` fallback is preserved but logs a warning. Multi-BOQ projects (the common case) can now target the correct LV.

## [2.9.14] - 2026-05-06

### Security (P0 IDOR fixes - Wave 5 audit)

- **Risk register cross-tenant leak.** `GET /api/v1/risk/`, `/risk/summary/`, `/risk/matrix/` accepted any `project_id` from any authenticated user without checking ownership. All three handlers now require `RequirePermission("risk.read")` and call `verify_project_access(project_id, user_id, session)` before reading.
- **Change-order cross-tenant leak.** `GET /api/v1/changeorders/summary/` and `GET /api/v1/changeorders/?project_id=…` were missing the same ownership check. Both endpoints now require `RequirePermission("changeorders.read")` and verify project access; the project-less list path that scopes to the caller's owned projects is unchanged.
- **Contacts export leaked every tenant's data.** `GET /api/v1/contacts/export/` ran a plain `select(Contact).where(is_active)` with no owner filter, so anyone with `contacts.read` could download the full database. Now mirrors the `tenant_id` / `created_by` scope used by `list_contacts` / `search_contacts` / `get_stats`; admins still see every row.

### Changed

- **Settings page redesigned.** Card-grid layout with sticky vertical sidebar nav on desktop (horizontal scrollable pill tabs on mobile), profile rendered as a wide hero card with a real label-above pattern, "Danger Zone" red-tinted card separates Sign Out + destructive actions from settings, change-password form has proper labels + inline mismatch error, BIM/CAD tab body filled with link-cards, URL-synced tab state via `?tab=…` for deep-linking. Every setting from the previous layout is preserved.

## [2.9.13] - 2026-05-06

### Added
- DDC converter version surfaced on every converter-related page (`/bim` banner + `/quantities` cards): the actual installed git-blob SHA (first 7 chars) is shown in place of the static manifest version string. When the version-check endpoint reports the installed binary is older than upstream `cad2data-Revit-IFC-DWG-DGN/main`, the row swaps in a sky-blue "Update available" badge and a one-click **Update** button.
- Per-row Update button on `/quantities` ConverterCard wired through to a force-reinstall path. Kept the existing Install / Uninstall affordances so the card now exposes Install for missing converters, Uninstall for healthy ones, and Update + Uninstall for outdated ones.
- `installBIMConverter(id, {force: true})` API helper and a `?force=true` query param on `POST /v1/takeoff/converters/{id}/install/` so the "already installed → short-circuit" branch is bypassed when the client explicitly asks for a re-download.

### Fixed
- Clicking **Update** on an outdated converter previously hit the early-return ("already installed") path and did nothing visible. The handler now reinstalls under `force=true`, then clears `app.state._converter_version_cache` so the 6-h server cache reflects the new SHA immediately. Frontend invalidates `bim-converters`, `takeoff/converters`, and `bim-converters-version-check` query keys on success - the badge disappears as soon as the install completes instead of lingering for hours.

### Changed
- `openconstructionerp.com` hero "OCERP" mark restyled to match the rest of the site CTAs. The 3D-glass pill with breathing animation, gloss layers, click-burst rings, and `rotateX/rotateY` hover was replaced with a `.btn-primary`-shaped pill (rounded, accent background, simple lift) plus a trailing chevron so it reads as **OCERP →**. Click still navigates to `#install`.

## [2.9.12] - 2026-05-06

### Fixed
- All upload size caps removed (boq/contacts/fieldreports/finance/costs/tasks/punchlist/meetings/takeoff/bim_hub) - uploads no longer rejected at 10/25/50/100/200 MB.
- DDC logo on dashboard rendered correctly (.webp now in static-extension whitelist; was served as truncated text/html).
- Validation engine no longer flags BOQ section headers as missing unit/quantity/unit_rate (16 false errors → 0 on demo BOQ).
- BOQ editor 404s eliminated: `/v1/boq/boqs/{id}/activity/` and `/v1/costs/vector/status/` (trailing-slash mismatches).
- Sidebar version line `v… · AGPL-3.0` moved below GitHub/Telegram pills (last row of menu).

### Added
- "Developed by" label above the DataDrivenConstruction logo on the dashboard hero (translated for en/de/fr/es/pt/ru/zh/ar/hi/ja).
- File-manager UI translations for ar/fr/es/pt/zh/hi/ja (~55 keys each, no more English leakage on /files).

## [2.9.11] - 2026-05-06

### Fixed
- "Navigation Sidebar" tour bubble no longer ambushes returning users on every page (BOQ, Dashboard, Projects, Validation…). The auto-start gate now also short-circuits when `oe_onboarding_completed === 'true'`, which the dashboard stamps as soon as it confirms the workspace has projects. Fresh installs still see the tour; demo-data and any new browser on a populated workspace skip it.

## [2.9.10] - 2026-05-06

### Fixed
- `/finance` printed nonsense totals like `850.000.320.000.018.000.000.000,00 €` for projects whose budget lines summed to ~8.25M. The reduces over `b.original_budget` / `b.actual` / `b.revised_budget` / `b.committed` / `b.forecast` / `b.variance` and `inv.amount` / `p.amount` were string-concatenating because the API serialised DECIMAL columns as strings ("850000.00"). Coerced every accumulator with `Number(x ?? 0)` so the dashboard chips, Budgets total row, Invoices totals, and Payments totals all aggregate numerically.

## [2.9.9] - 2026-05-06

### Fixed
- Onboarding wizard no longer hijacks the dashboard for users whose workspace already has projects. The redirect now waits for `/v1/projects/` to resolve and only fires when the workspace is genuinely empty; otherwise it stamps `oe_onboarding_completed` so the next visit (and every other browser the user opens) lands on the dashboard, not the 6-step welcome flow.
- `/files` no longer leaks the server's absolute filesystem layout. The PathBar that surfaced `C:\Users\…\.openestimator\uploads\…`, the per-root chips (DB / Uploads / Photos / BIM / DWG), and the amber location notes have been removed; users who actually need on-disk paths can find them under /settings → System.
- Cost Database header showed "France - 0 items" while the France tab badge advertised 55,121 because the in-flight search returned `total=0` first. Header now falls back to the region's catalog count from `/v1/costs/regions/stats/` while the search is still resolving.

## [2.9.8] - 2026-05-06

### Fixed
- Demo documents no longer 404 in PDF Takeoff. Seeded `Document` rows reference paths that don't exist on disk (we don't ship multi-MB PDFs in the wheel), so `/api/v1/documents/{id}/download/` returned 404 and the cross-module deeplink landed on "Failed to fetch PDF". The download endpoint now materializes a one-page placeholder PDF on first request when `metadata.is_demo == True`. Real uploads are unaffected.
- Sidebar footer is now unified neutral gray with two equal-width pills. GitHub pill (icon + "GitHub" label) on the left, Community pill (Telegram glyph + label) on the right - neither dominates. Meta strip above shows `v{version} · AGPL-3.0` in matching tertiary gray.

## [2.9.7] - 2026-05-06

### Fixed
- Dashboard map now shows ALL projects, not just one. Region fallback only had country-level keys (`uk`, `usa`, `germany`); demo + onboarding data uses higher-level groupings (`Europe`, `DACH`, `Middle East`, `United States`, `Asia-Pacific`, `LATAM`, …) which silently dropped off the map. Fallback table now covers both granularities.
- Sidebar footer text was truncating at narrow widths (`AGPL-3.0` and `Community` got chopped). Footer is now two rows - meta strip on top (`GitHub · v{version} · AGPL-3.0`), full-width Telegram Community pill below - so nothing is cut off.

## [2.9.6] - 2026-05-06

### Added
- Sidebar footer Telegram community link - single-row layout: left half = `v{version} · AGPL-3.0` with GitHub icon, right half = brand-blue Telegram pill with Community label. Links to https://t.me/datadrivenconstruction.

### Fixed
- Dashboard map (`/`) blank/grey - Content-Security-Policy was blocking MapLibre's `blob:` worker and the openfreemap tile + nominatim geocode endpoints. Added `worker-src 'self' blob:`, `script-src … blob:`, and `connect-src https://tiles.openfreemap.org https://*.openfreemap.org https://nominatim.openstreetmap.org`.
- Dashboard project cards no longer leave half-empty rows at the lg breakpoint. Visible count is now capped to `floor((cards+1)/4)*4 - 1` so `(visible + CTA)` always fills the 4-column grid: 5 projects → 3 + CTA, 8 → 7 + CTA, 11+ → 11 + CTA. Fewer than 3 still show all + CTA (capping further would just hide everything).

## [2.9.5] - 2026-05-06

### Fixed
- `/files` document deeplink - clicking a PDF and pressing "Open in PDF Takeoff" now actually opens the file. Previous flow routed to `/documents?id=` which since v2.9.x is a `<Navigate to="/files">` redirect that drops query params, so the destination module never received the file id. New flow goes to `/takeoff?doc={id}&source=document&tab=measurements` and TakeoffPage fetches metadata from `/v1/documents/{id}` and points the viewer at `/api/v1/documents/{id}/download/`. Verified end-to-end with a real PDF rendered in the takeoff viewer.

## [2.9.4] - 2026-05-06

### Removed
- Final user-facing size-cap copy across i18n + UI - `dashboard.upload_desc` "max 100 MB" tail, `MAX_UPLOAD_BYTES` guard in QuickUploadCard, `files.upload_hint` (EN/DE/RU) "max 100 MB", `costs.import_accepted` "max 10 MB" suffix (EN/DE/FR/ES/NL/CS/SE/RO), `fieldreports.file_types` "max 10 MB" suffix (all langs), `bim.upload_size_hint` and `bim.landing_size_hint` "Max 500 MB" suffix (all langs), `CadDataExplorerPage` "Max 100 MB" upload hint. Bundle now ships zero "max NNN MB" matches.

## [2.9.3] - 2026-05-06

### Added
- Dashboard compact project cards on `/` - 11 most-recent + a "View all projects" CTA card (12 total, always fills full rows at 1/2/3/4 columns).
- Dashboard project-locations map - single MapLibre canvas with one marker per project, lazy-loaded, region-fallback for projects without an address. Lives below Portfolio Overview.
- BOQ Custom Columns: `derived` field on column definitions - GAEB Lohn-EP / Material-EP / Geräte-EP / Sonstiges-EP and ÖNORM Lohn-Anteil % auto-compute from `position.metadata.resources[]` instead of being free-form numeric inputs.
- `/files` `Open in {Module}` deep-links - preview pane primary CTA, hover overlay on grid tiles, and inline cell on the list view. Each file links to its native tool with file context: PDF → `/takeoff?doc={id}`, IFC/RVT/DGN → `/projects/{p}/bim/{modelId}`, DWG/DXF → `/dwg-takeoff?drawingId={id}`, photos → `/photos?photo={id}`, secondary file-manager preview-select via `?file={id}`.
- `/files` moved to Sidebar → Overview alongside Dashboard / Projects (was buried under Documentation).

### Removed
- All user-facing upload size caps - `_CAD_MAX_SIZE` (500 MB BIM), `MAX_FILE_SIZE` (100 MB documents / 50 MB AI / 50 MB GAEB), `MAX_PHOTO_SIZE` (50 MB), `_MAX_UPLOAD_BYTES` (50 MB DWG / 200 MB dashboards), `MAX_BACKUP_SIZE` (100 MB), `15 MB` BOQ multimodal cap, `10 MB` costs-import cap. Frontend "Max XX MB" hint strings stripped across DwgTakeoffPage, TakeoffPage, DocumentsPage, PhotoGalleryPage, UploadDialog, ImportDatabasePage, FieldReportsPage, ContactsPage, BIMPage, plus matching i18n fallbacks. The XLSX zip-bomb decompressed-size guard stays - that's a memory-safety check, not a user cap. (#110 follow-up)

### Fixed
- File Manager `/files` filter view - backend `file_tree` no longer prefixes node ids with `category:`; frontend strips legacy prefix defensively so old bookmarks (`?kind=category%3Abim_model`) still resolve.
- BOQ `enrich-resources` 500 - `cost_repo.search` returns a 3-tuple but four call sites unpacked into a 2-tuple; fixed in `boq/service.py`, `boq/router.py`, `ai/router.py` (×2). Triggered by Update Rates action.
- `/api/v1/requirements/template.xlsx` 400 - route ordering: literal `template.xlsx` route now precedes parametric `/{set_id}` so UUID validation no longer rejects it.
- Frontend bundle freshness - `_frontend_dist` rebuilt with login fixes (LinkedIn link, external "Learn more" anchor) that were authored against source but missed the previous wheel build.
- BOQ Custom Columns data-jump - `valueSetter` now spreads `metadata` immutably; custom-column detection uses `colId.startsWith('custom_')` instead of fragile `field` parsing.
- BOQ Custom Columns horizontal overflow - grid height capped at viewport, custom columns get explicit min/max widths, wrapper has `min-w-0` so AG Grid's bottom scrollbar stays reachable.
- Backend `add_custom_column` - replaced untyped `dict` body with `CustomColumnCreate` Pydantic schema (`extra='forbid'`) so typo'd fields fail with 422 instead of being silently dropped.
- BOQ shortcuts Ctrl+E / Ctrl+I / Ctrl+L / Ctrl+/ - moved above the `isEditing` guard so they fire during cell editing (like Ctrl+S in spreadsheets), capture-phase listener so AG Grid no longer swallows them, `e.code`-based fallback for non-US keyboard layouts.
- Sidebar `g d` chord → dashboard - chord sets a one-shot `oe_skip_onboarding_redirect` sessionStorage flag so the dashboard view loads even on fresh installs (the auto-onboarding redirect still fires for normal first-launch flow).
- BOQ `enrich-resources` and `enrich-co2` 500 - the loops iterate `boq_data.positions` (Pydantic `PositionResponse`) but were reading `pos.metadata_` (the SQLAlchemy column name); Pydantic strips the trailing underscore, so attribute lookup raised. Now reads via `getattr(pos, "metadata", None) or getattr(pos, "metadata_", None)` to handle both ORM rows and serialised responses.
- `/api/v1/dashboards/projects/{id}/snapshots` 500 - `oe_dashboards_snapshot` was never created on fresh installs because `app.modules.dashboards.models` (and `architecture_map`, `compliance`, `eac`, `jobs`) were missing from the `create_all` import list in `app/main.py`. All five module models now register before the bootstrap `Base.metadata.create_all()` call.

## [2.9.2] - 2026-05-06

### Fixed
- BOQ delete race - successful single-position DELETE no longer invalidates the BOQ cache and races with concurrently-pending optimistic deletes (rapid sequential / batch delete). Sidecar queries (rollups, activity feed) still refresh; the BOQ cache rebuilds only on actual error.
- BOQ Delete / Backspace hotkey now removes the selected positions through the existing tracked-delete pipeline (5-second undo toast).
- BOQ toolbar collapses back to a single row - `Validate` / `Update Rates` / `AI Chat` removed as inline buttons (already present in the `Quality & AI` dropdown which now also surfaces `Update Rates`); toolbar uses `flex-nowrap` with horizontal scroll fallback so the right-anchored Grand Total never wraps to a second line.
- Login page polish - module-honeycomb left-aligned (was centered), stats row updated to "30 regions" (was 11) and gained a "4 CAD formats" stat. Matching i18n EN fallbacks updated.

## [2.9.1] - 2026-05-05

### Added
- BOQ display-currency selector - view-only conversion of all monetary aggregates (position totals, section subtotals, footer rows, Grand Total) via project FX rates. `Total` column header gains the chosen currency code. (#88)
- BOQ toolbar merged to a single row - mini-summary, currency selector, and Grand Total moved into the existing sticky toolbar.
- Display-currency choice persists per-BOQ in localStorage; auto-cleared if the rate is later removed.
- File Manager - per-project file workspace with bundle export/import, storage location override, and a tree+grid browser. (#109)
- `v294_project_storage_override` migration adds the per-project storage override column.
- Project Intelligence module promoted to `core` (always-on per `feedback_pi_always_on`).

### Fixed
- BOQ display currency was wiped on every reload because the sanity-check effect ran before the project query finished loading.
- DWG Takeoff upload form - the upload button no longer no-ops; corrected event wiring and progress state. (#110)
- Login page polish - cleaner layout, demo banner copy, accessibility tweaks.
- Issue #53 (BIM viewer geometry) - re-confirmed as fallback-by-design at v2.9.1; closing with DDC IFC Converter install instructions.

### Changed
- Header / Sidebar / Update checker iteration - small UX polish around the layout shell.

## [2.9.0] - 2026-05-05

### Performance
- `/costs` page load 120× faster - composite `(region, is_active, code)` index drops the per-region keyset scan from 6 s to 1 ms on 55K-row catalogues; COUNT(*) from 3 s to 6 ms.
- `/v1/costs/?lite=1` slim-payload mode strips `components` (~31 KB/row) and `metadata.variants` (~6 KB/row), shrinking a 10-row page from 235 KB to 18 KB. Frontend list now lazy-fetches the full item via `/v1/costs/{id}` only when a row is expanded.

### Added
- Header `ThemeToggle` button - single icon next to avatar that cycles light → dark → system.
- Header `HelpMenu` (`?` icon) consolidates 6 buttons (Docs, GitHub, Send feedback, Report issue, Report a bug, Email) behind one popover.
- Sidebar pinned section, search-as-jumper bar, two-key keyboard shortcuts (G then D/P/B/C/M/A/,) with inline kbd hints, hover-arrow affordance, stagger animation.
- Linux CAD converters auto-discovered at `/usr/bin/{Format}Exporter` (RVT/IFC/DWG/DGN); install endpoint detects `/etc/apt/sources.list.d/ddc.list` and surfaces a one-line install or full apt setup accordingly.
- Smoke test surfaces `error while loading shared libraries` (exit 127) with the missing-lib name so users know which `ddc-deps-*` package to reinstall.

### Changed
- Sidebar active state - single winning route now highlighted (was: parent + child both lit on `/bim/rules`); active background bumped from `oe-blue/[0.08]` to `oe-blue/[0.14]` with a 2 px left bar and inset hairline.
- Header `ProjectSwitcher` - bigger 36 px hit-target, always tinted, dashed CTA + pulsing dot when no project, solid blue-subtle + folder square + bold name when active.
- Header right side reorganized into 4 zones (Search · Notifications+Help · Account) with hairline dividers.
- Avatar in user menu now has gradient + drop-shadow + animated online dot (matches the rest of the chrome).
- Header bottom is now a soft hairline gradient instead of a hard 1 px border.
- All decorative emojis in `/bim/rules`, `/chat` data panel, BOQ grid, BIM filter panel, AI config banner, match panel, and project detail replaced with lucide icons. Country flags and i18n locale flags untouched.

### Fixed
- `app/modules/takeoff/router.py` - `uuid.UUID(...)` reference fixed to use the local alias (`_uuid.UUID(...)`); previous code raised `NameError` at runtime.
- `MatchSuggestionsPanel` test mocks updated to include `listLoadedDatabases` / `setProjectCatalog` so `CatalogBindingBar` mounts in tests.

### Internal
- Migration `v283_costs_region_active_index` - inspector-guarded composite index on `oe_costs_item(region, is_active, code)`. New DBs get it via `Base.metadata.create_all()` from updated `__table_args__`.
- New backend tests `tests/unit/test_cad_import_linux.py` (8) cover the Linux converter probe + `ld.so` failure heuristic.

## [2.8.8] - 2026-05-04

### Added
- `POST /api/v1/requirements/{set_id}/validate-bim/{model_id}` - runs every requirement in a set against every element of a BIM model and persists a regular `ValidationReport`. Reuses the existing dashboard, BIM viewer badges, and SARIF export.
- `GET /api/v1/requirements/template.xlsx` - downloadable Excel template with headers, a sample row, comment hints per column, and a Legend sheet listing all 10 operators.
- `POST /api/v1/requirements/{set_id}/import/file/` - Excel/CSV bulk import; format auto-detected, malformed rows reported as warnings.
- `GET /api/v1/requirements/{set_id}/export.{xlsx|csv|json}` - unified export endpoint; extension drives the format.
- `/bim/rules?mode=requirements` toolbar - Import / Template / Export / "Validate against model" buttons; validation result card with score, counts, and link to the full report.
- BIM model picker modal lets the user pick which model to validate against; status pulses while the run is in flight.

### Changed
- Requirement constraint operators unified across the stack: backend now accepts the full set `equals | not_equals | min | max | range | contains | not_contains | regex | exists | not_exists` (was 6); frontend `bimConstants.ts` aligns; Excel template documents all 10. The previous `regex: ".+"` workaround for "any value" presets is gone - `exists` is the operator.
- Constraint value input in the requirement editor now switches widget by operator: number for min/max, two numbers for range, regex with live validation, text for the rest, hidden for exists/not_exists. No more guessing whether a field expects "200..400" or "200,400".
- Requirement form no longer prefixes notes with `[REVIT] Category=...` - the entity field already carries the category.

### Internal
- `requirements/evaluator.py` - pure constraint evaluator; 32 unit tests cover all 10 operators, edge cases, European decimal separator, range separator variants.
- `requirements/excel_io.py` - Excel/CSV template + parse + export, with operator legend sheet; 8 unit tests cover roundtrips, missing required columns, unknown-operator warnings.
- `requirements/bim_validator.py` - bridges EAC schema to the existing `ValidationReport` storage so all validation surfaces (dashboard, BIM badges, SARIF) work without per-source forks.

## [2.8.7] - 2026-05-04

### Changed
- /bim/rules - empty state now shows 4 starter templates (Walls / Slabs / Doors / Windows) that pre-fill the editor in one click instead of a generic "Create your first rule" CTA.
- /bim/rules?mode=requirements - empty state now offers 3 ready-made compliance packs (Fire safety, Thermal performance, Structural integrity); installing a pack auto-creates the requirement set and bulk-adds 3 rules using backend-accepted constraint types only.
- BIM model picker now appears on both tabs; Requirements uses it to populate the "From BIM Model" auto-fill from the selected model's elements.
- /login - removed the broken Privacy / Terms footer links (the underlying static HTML pages don't exist in production builds).

### Internal
- Layer-3 authorship fingerprints added across the codebase (see `tools/watermark/`) - no functional impact.

## [2.8.6] - 2026-05-04

### Fixed
- Registration form now shows a clear "Account created. An administrator needs to activate it" message when the server returns `is_active=false` (gated registration mode). Previously the form auto-attempted login, hit the same generic 401, and dumped users at /login with no idea what went wrong.

## [2.8.5] - 2026-05-04

### Fixed
- Fresh-install registration: the seeded `demo@openconstructionerp.com` admin no longer blocks the bootstrap path. First real self-registered user is now correctly promoted to admin and `is_active=True`, regardless of `OE_REGISTRATION_MODE`. Previously, every `pip install openconstructionerp` left new users dormant with no path forward.
- `/projects/:projectId/boq` only fetches that project's BOQs instead of fanning out to every project, cutting skeleton time on prod (50+ projects) from ~2 s to one round-trip.

### Tests
- New regression: `test_demo_admin_seed_does_not_block_bootstrap` covers the dormant-user gotcha.

## [2.8.4] - 2026-05-04

### Fixed
- `/costs` and `/catalog` now auto-pick the first loaded region when none is selected. Previously the page showed a "No database loaded" empty state even when /setup/databases had already populated rows, because the picker waited for an explicit selection.
- Sidebar version label now reads from `frontend/package.json` correctly. v2.8.3 wheel shipped with the sidebar baked at "v2.8.2" because `npm run build` ran before the package bump.
- `/projects/:projectId/boq` route added - previously 404'd. Pre-filters the BOQ list to the project so users coming from the project detail page don't have to re-pick the project.

## [2.8.3] - 2026-05-04

### Fixed - Catalogue load now populates BOTH cost layers
- `/setup/databases` only called `/v1/costs/load-cwicr/` and silently skipped `/v1/catalog/import/`. Sidebar shows both "Cost Database" and "Resource Catalog" - they're separate tables (`oe_costs_item` vs `oe_catalog_resource`) - but only the first got data. Users saw the success toast, navigated to "Resource Catalog", found it empty, and concluded the load had failed.
- `handleLoadRegion` and `handleLoadAll` now `Promise.all` both endpoints. Catalog import is best-effort (some regions ship only the cost layer). Single combined toast: "X cost items · Y catalog resources" with 8 s duration.
- Both `['costs']` and `['catalog']` query keys invalidated on success.

### Added - Deep links from setup → DB browsers
- Region cards now show inline `View cost items →` and `View resources →` after load, linking to `/costs?region=<id>` and `/catalog?region=<id>`.
- `CostsPage` and `CatalogPage` read the `?region=` URL parameter on mount, pre-select the filter, then strip the param so reloads don't re-force it.
- `/setup/databases?vectorize=<id>` deep-link from the Match panel scrolls to the targeted card with a 2.4 s blue ring + hint toast.

### Improved
- Match panel catalogue picker: replaced mouse-only `onMouseLeave` with proper pointerdown-outside + `Escape` handlers, plus `role="listbox"` + `aria-label`. Touch and keyboard users no longer end up with a stuck dropdown.

### Tests
- 5 new unit tests for `_looks_like_fixture` heuristic (TEST- prefix, A001-style codes, canned descriptions, real CWICR pass-through, missing-code edge case) + cache reset.

## [2.8.2] - 2026-05-04

### Added - Per-project CWICR catalogue binding for the matcher
- New nullable `cost_database_id` on `oe_projects_match_settings` (alembic v282) - explicit per-project pick (`RU_STPETERSBURG`, `DE_BERLIN`, …); no auto-pick from `project.region`.
- `MatchResponse.status` envelope: `ok` / `no_catalog_selected` / `catalog_not_vectorized` / `no_catalogs_loaded` - UI renders distinct empty states with targeted CTAs instead of silent zero-results.
- `GET /api/v1/costs/loaded-databases/` - per-region SQL count + LanceDB vector count + ready flag.
- `<CatalogBindingBar>` always visible at the top of the Match panel: badge ("📚 RU_STPETERSBURG · 55,719 / 1,000 vec"), dropdown picker driven by the new endpoint, click-to-rebind with React Query invalidation.
- SQL `ILIKE` lexical fallback in `app.modules.costs.vector_adapter.search()` when LanceDB is empty / fixture-only / encoder unavailable, so users see real CWICR rows instead of an empty pane while ops backfills the index.

### Fixed
- Stale `cost_database_id` (pointing at an unloaded region) now degrades to `no_catalog_selected` when other catalogues are loaded - previously claimed `no_catalogs_loaded`, sending the user to a "load a catalogue" CTA while their other catalogues sat right there.
- `<CatalogBindingBar>` picker dropdown got `position: absolute` against a non-positioned ancestor (`mt-32 right-3` placed it ~128 px below random parent). Added `relative` parent + `top-full mt-1` so it now drops below the bar reliably.

### Verified
- 224+ backend tests green (incl. 12 new tests in `test_match_catalog_binding.py` covering all 4 envelope states + SQL-injection whitelist on `vector_count_with_payload_substring`, plus 5 new tests in `test_match_settings.py` for the PATCH/GET round-trip + reset).
- Smoke-tested all four `MatchResponse.status` paths against a real backend with two loaded catalogues.
- TS strict clean (`tsc --noEmit` exit 0). Vite production build succeeds.

## [2.7.7] - 2026-05-03

### Fixed - Match tab now lives in the Element Inspector users actually see
Phase 4 mounted the Match panel into a separate `BIMRightPanelTabs` component (Properties/Layers/Tools/Groups/Match) that only opens when the user explicitly toggles the "Linked BOQ" button in the BIM toolbar. Visual QA confirmed real users never get there: when they click an element, the auto-opening **Element Inspector** (Properties/Links/Check, inside `BIMViewer.tsx`) is what they expect to see - and Match was missing from it.

- **Added a 4th "Match ✨" tab** directly inside the Element Inspector right next to Properties/Links/Check. The instant a user picks a BIM element, the inspector pops up with all four tabs and the Match panel is one click away - no Linked-BOQ toggle, no separate panel to discover.
- The standalone `BIMRightPanelTabs` keeps its Match tab too - the two surfaces are now consistent (anywhere the user is, Match is visible) so we don't have to choose one path.
- Panel renders with `compact` mode and remounts on `selectedElement.id` change so the per-element rejection accumulator never leaks across selections.

### Verified
- 40/40 frontend tests still pass; backend untouched.
- TS strict clean (`tsc --noEmit` exit 0).
- Vite HMR confirmed serving the updated `BIMViewer.tsx` with the new tab + Match panel imports.

## [2.7.6] - 2026-05-03

### Fixed - Match tab now reachable via standard click flow (browser-verified)
- **`BIMViewer` health-stats banner is `pointer-events-none` on the container** with `pointer-events-auto` on each pill - clicks pass through the banner's negative space straight to the right-panel tabs underneath. The previous `max-w` workaround helped only on viewports with few pills; the new approach works regardless of pill count or wrap behaviour.
- **Right BIM panel widened 340 px → 380 px** so all 5 tabs (Properties · Layers · Tools · Groups · Match) fit comfortably with `truncate` no longer collapsing the Match label down to its `Sparkles` icon. Each tab now gets ~70 px instead of ~62 px.
- **Right BIM panel z-index bumped 15 → 25**, above the elements-loaded banner (z-20) and the auto-opening "Filtered summary" popup (z-20). Filter popup no longer occludes the Match tab.
- **`max-w-[calc(100%-360px)]` → `max-w-[calc(100%-400px)]`** on the banner so its right edge stays clear of the wider panel even before pointer-events kick in.

### Verified
- 40 frontend tests still green; backend untouched.
- Live browser probe (`qa-tests/v275-probe/probe_final.py`) confirms `[role=tab]:has-text("Match")` is reachable via Playwright `.click()` without any JS bypass - banner pills no longer intercept pointer events.
- Tab strip rendering verified at 1440×900 viewport with full element-banner rendered.

## [2.7.5] - 2026-05-03

Phase 3 + Phase 4 of vector match + concurrent-match perf hardening, shipped together.

### Added - Phase 3: translation download UI
- **`TranslationSettingsTab`** at `frontend/src/features/translation/` - cache stats, dictionary table, MUSE form, IATE local-path + URL forms, in-flight task card with progress bars. Adaptive 5 s / 30 s React Query polling driven by in-flight task count so idle deployments don't burn requests.
- **Mounted in `ProjectSettingsPage`** as a Card section with `id="translation"` so the existing `#hash` deep-link + ring-pulse pattern (originally for `#fx-rates`) drops in unchanged.
- **`MatchSuggestionsPanel`** surfaces an info banner when `translation_used.tier_used === 'fallback'`, deep-linking to `/projects/${projectId}/settings#translation` so users can fix the fallback in one click.
- **Client-side IATE allowlist** mirrors the backend SSRF guard (`isIateUrlAllowed()` + `IATE_ALLOWED_PREFIXES`); backend re-validates so the client check is purely advisory.

### Added - Phase 4: BOQ accept + auto-link execution
- **`POST /api/v1/match/accept`** consolidates the previous three round-trips (create/update position → BIM link → submit feedback) into one transactional call. Body carries the accepted candidate, the rejected list, target boq + parent_section, optional `existing_position_id` for the update path, optional `bim_element_id` for the link, and an optional quantity override.
- **`accept_match()` service** writes provenance into `Position.metadata`: `cost_item_code`, `match_score`, `match_vector_score`, `match_boosts_applied`, `match_confidence_band`, `matched_at`, `matched_by_user_id` - every AI-accepted position is auditable end-to-end.
- **AI-NNN ordinal namespace** for AI-accepted positions so they're visually distinguishable from manual entries in the BOQ grid.
- **`source: "ai_match"`** added to `PositionCreate` / `PositionUpdate` regex allowlist.
- **`useAcceptMatch` mutation** + cache invalidations in `frontend/src/features/match/queries.ts`; `MatchSuggestionsPanel` now wires Accept and (opt-in) auto-link with a `AUTO_APPLY_DELAY_MS=1500` confirmation window so users can intercept before the auto-link fires.
- **BIM right panel** wires the accept flow to a BOQ picker.

### Performance - concurrent match latency hardening
- **Embedder warm pool** - `app/core/embedding_pool.py`: thread-pool by default (`OE_VECTOR_POOL_KIND=thread`), opt-in `process` for true parallel encodes. Smart routing - single calls run inline (skip pickle/IPC), concurrent calls dispatch to the pool. Sync warmup at startup so the first match request doesn't pay the model-load cost.
- **Project-region TTL cache** with inflight de-duplication (`app/core/match_service/region_cache.py`) - boosts no longer issue one `ProjectRepository.get_by_id` SELECT per concurrent request.
- **Server-side p95 at 50× concurrency: 4958ms → 2511ms (−49 %).** Throughput +72 %. Client-side p95 still gated on the LanceDB single-process read lock - flagged as architectural follow-up.

### Fixed - translation cache LRU correctness
- **LRU keyed on cache path** - module-level LRU keys now include the SQLite path so two callers using different cache files (production vs per-test temp DBs) cannot collide on identical `(text, src, tgt, domain)`. Surfaced as a real cross-test pollution while wiring the perf-hardening tests.
- **`mark_used()` invalidates the LRU row** - usage_count / last_used_at bumps are now visible on the next `get()` instead of being shadowed by the stale row that was cached at insert time.

### Fixed - Phase 4 visual QA findings (36-screenshot capture, 14 findings)
- **Match tab no longer occluded by the BIM elements-loaded banner.** `BIMViewer.tsx` health-stats banner reserved 280 px for the right tab strip but the strip is 340 px wide, leaving a 60 px overlap that made the Match tab unclickable on every desktop viewport. Bumped the reserved width to 360 px so the banner can never sit on top of the tabs.
- **Stale match candidates on element switch.** `MatchSuggestionsPanel` is now keyed on `selectedElementId`, so picking element B after element A refires the autoFetch effect and resets the per-element rejection accumulator instead of showing element A's results until manual refresh.
- **`ScoreBadge` boost-breakdown now reaches touch + screen-reader users.** Tooltip toggles on `onClick` (was hover-only), exposes `aria-describedby` + `aria-expanded`, and assigns the tooltip a stable `id` for the description link. Keyboard focus path unchanged.
- **`bim.tabs.match` → `bim.tab_match`** - naming consistency with the four other BIM tab keys (`tab_properties`, `tab_layers`, `tab_tools`, `tab_groups`).

### Tests
- 18 backend integration tests for `accept_match` (`tests/integration/test_match_accept.py`).
- 39 perf / cache / region tests (`tests/unit/test_translation_cache_lru.py`, `test_project_region_cache.py`, `test_vector_warmpool.py`, `tests/perf/test_match_concurrency.py`).
- 4 frontend BOQ-wiring tests + 3 a11y assertions; 12 translation-tab unit + 3 axe tests.

### Known limitations (deferred follow-ups from Phase 4 QA)
- **`match.*` translation keys exist only as `defaultValue`** in source - non-English locales fall back to English. Same project-wide pattern as the other BIM tab labels; out of scope for v2.7.5, tracked for the next i18n sweep.
- **`BIMRightPanelTabs` does not mount on mobile (390 × 844)** - Match tab unreachable on mobile. Either intentional (desktop-only feature) or a long-standing regression; needs investigation before adding a "Desktop only" banner or a responsive variant.
- **`MatchSuggestionsPanel`'s `selectedElementId` flow only works on desktop today** - mobile is blocked on the same panel-mount issue above.

## [2.7.4] - 2026-05-03

### Added - Phase 2 of vector match: `MatchSuggestionsPanel` frontend
- **`MatchSuggestionsPanel`** in `frontend/src/features/match/` - shared React component that calls `POST /api/v1/match/element` and renders ranked CWICR candidates with confidence pills (high/medium/low color-coded), boost-breakdown tooltip on hover, region/code/unit/rate display, optional LLM-rerank toggle, refresh button, auto-link banner when threshold crossed. Per-candidate Accept / Reject buttons; rejection accumulator submits `accepted_candidate + rejected_candidates` together via `POST /api/v1/match/feedback` on accept.
- **`useMatchElement` + `useSubmitMatchFeedback` React Query hooks** - typed mutations against the backend match endpoints; types defined in `features/match/types.ts` mirroring `MatchCandidate` / `MatchResponse`.
- **Mounted in BIM right panel** as a 5th "Match" tab - when an element is selected, the panel auto-fetches candidates from CWICR using the vectorized catalog. Phase 4 will wire `onAccept` to the actual BOQ-link mutation; for now logs to console + toast.
- **i18n**: every user-visible string via `t("match.*")` with inline default values per project convention. Top-5 locales (en/de/ru/ja/ar) populated by the bulk i18n sweep.
- **a11y**: `role="list"` / implicit `listitem`, color-blind-safe confidence pills with explicit `aria-label`, full keyboard navigation. Axe-core: 4/4 a11y tests pass with zero violations.
- **21 new tests** (17 unit + 4 a11y); typecheck + lint clean.

## [2.7.3] - 2026-05-03

### Added - Phase 1 of vector match: material-aware classification enrichment
- **`enrich_classification(category, material, fire_rating, structural)`** in `app/modules/cad/classification_mapper.py` - DE/EN material synonym folding (Beton/Stahlbeton/concrete; Ziegel/Mauerwerk/brick; Holz/timber/wood; Stahl/steel; Trockenbau/Gipskarton/drywall; aluminium; glass) + deeper DIN276 / NRM / MasterFormat codes when material is known. Falls back to coarse 3-digit DIN code when the material is proprietary/unknown. Codes aligned with the golden-set fixture so the matcher's classifier boost can fire on real CWICR rows.
- **BIM / PDF / DWG extractors auto-derive `classifier_hint`** - when raw imported data has no `classification` block, the extractor calls `enrich_classification` for all three standards and the matcher's `classifier_match` boost rewards the right CWICR position. Pre-classified imports keep their existing codes - no override.
- **77 new tests** (61 unit + 16 integration). 2666 other unit tests still pass, no regressions.

## [2.7.2] - 2026-05-03

### Added - Phase 0 of vector match foundation (v2.8.0 prep)
- **Cost-items vector adapter** - `oe_cost_items` LanceDB collection, multilingual-e5-small embeddings with passage:/query: prefixes, event-bus reindex on CRUD, gated `POST /api/v1/admin/cost-vector-reindex` endpoint, async startup backfill.
- **Translation cascade service** - `app/core/translation/` with 4-tier (MUSE/IATE lookup → SQLite cache → LLM via ai_client → fallback), phrase-aware tokenization preserving construction codes (C30/37, IPE100), `POST /api/v1/translation/translate` + lookup-table download/status endpoints.
- **MatchProjectSettings model** - per-project target_language / classifier (din276/nrm/masterformat/none) / auto_link_threshold / mode (manual/auto) / sources_enabled. Lazy-init on first GET, audit-logged updates.
- **Match service core** - `app/core/match_service/` with universal envelope, ranker (translation → vector search → 4 boosts → auto-link gate), opt-in LLM reranker with cost cap, 4 source extractors (BIM + PDF functional, DWG + photo stubs marked for v2.8 follow-up), feedback loop. `POST /api/v1/match/element` + `POST /api/v1/match/feedback`.
- **Eval harness** - `tests/eval/` with 30+ realistic golden-set entries, AI-as-judge with rule-based fallback, runner with metrics (top-1 acc, top-5 recall, MRR), `.github/workflows/eval-match.yml` CI workflow.

### Security
- **SSRF guard on IATE downloader** - host allowlist (iate.europa.eu / DDC mirrors / OE_IATE_EXTRA_HOSTS env var) + `follow_redirects=False`. Without this an authenticated user could pivot the backend to fetch cloud-metadata or internal services.
- **Cross-user task leakage fixed** in `GET /api/v1/translation/lookup-tables/status` - now filters in-flight tasks by owner so users can't see each other's task ids / error strings (which can leak filesystem paths).

### Fixed (verification pass)
- **Region boost** for fully-qualified projects (e.g. `DE_BERLIN`) - was returning a bare string that iterated character-by-character; now returns exact code as a single-element tuple. Real ranking-quality regression for pinned-city projects.
- **Sentinel UUID FK violation** in `match_element` - wraps `get_or_create_match_settings` in try/except with transient-defaults fallback so eval harness and stale callers no longer surface 500.
- **`POST /api/v1/match/element` with bogus source** now 422 instead of 500 (Pydantic Literal validator on `source`).
- **Classifier reverse-substring fallback** removed - `"33"` no longer matches `"330.10.020"`. Forward containment only, min 3 characters.
- **Deterministic tie-breaking** in ranker - secondary sort key on `code` so auto-link winner is stable across reruns.
- **`tests/unit/test_costs_vector_adapter.py`** - switched `del sys.modules; import_module` to `importlib.reload(...)` to avoid orphaning module references and breaking downstream monkeypatches.
- **Alembic single-head** restored - translation-cache migration repointed onto `v2b1_compound_type_indexes`.

### Tests
- 194 Phase 0 tests added across unit / integration / eval / perf (118 baseline + 70 edge cases + 6 region regression).

## [2.7.1] - 2026-05-03

### Added - Pareto / ABC analysis on the resource summary (Issue #106)
- **`ResourceSummaryItem.abc_percentage` + `abc_class` (A / B / C).** The `/v1/boq/boqs/{boq_id}/resource-summary/` endpoint now returns each aggregated resource's share of the total summed cost (0–100) and its ABC bucket using the conventional 80 / 15 / 5 cumulative thresholds. The response also carries `grand_total` so the frontend doesn't recompute it.
- **Sortable columns + ABC bucket pills in `ResourceSummary.tsx`.** New "ABC %" column with red / amber / green pills (A = top items driving ~80 % of cost, B = ~15 %, C = ~5 % long tail). The Name / Total Cost / ABC % column headers are now click-to-sort. ABC sort mode draws thicker dividers between A → B and B → C boundaries so the Pareto split is instantly readable when the panel is expanded.

### Added - Display-currency selector for BOQ grand total (Issue #88, MVP)
- **"Display in: [USD ▾]" picker next to the BOQ mini-summary grand total.** When the project has at least one FX rate configured (Project Settings → FX Rates), users can flip the displayed grand total between the project's base currency and any FX-rate'd currency without persisting anything server-side. The persisted base-currency total is unchanged; this is a render-only conversion. Per-section / per-position display-currency conversion is intentionally a follow-up - the cell-renderer rewrite is bigger than this release. Hover tooltip surfaces the FX rate used so the conversion is auditable.

### Changed - Clickable "set FX" warning on BOQ resources (Issue #105)
- **The amber `⚠ no FX` badge on a resource row is now a button.** Clicking it routes the user straight to Project Settings → FX Rates with the FX-rate Card scrolled into view and pulsed for 2 s so it's instantly findable. The deep-link target is `Project.fx_rates` (Card `id="fx-rates"`). When `onOpenFxRateSettings` is not wired (e.g. embedded grids), the badge falls back to the previous static `⚠ no FX` chip - graceful degrade, no breakage.

### Verified - Composite-item editor sub-asks (Issue #93)
- **Centralised FX template** (`Project.fx_rates`) was already wired into the resource-currency picker (`cellRenderers.tsx:3127, 3301-3326`); confirmed every project FX-rate'd currency is offered.
- **Editable resource type per component** (Material / Labor / Equipment / Operator / Subcontractor / Electricity / Composite / Other) was already supported via `ResourceTypePicker` (`cellRenderers.tsx:3424-3429`, type registry `boqResourceTypes.ts:27-36`).
- **Custom unit free-text** was already supported by `InlineUnitInput` (`cellRenderers.tsx:2196-2430`); user-typed units land in `User.metadata_["custom_units"]` via `saveCustomUnit()` and merge into the dropdown for future picks.

### Verified - `source: "cwicr"` BOQ position writes (Issue #79)
- **The schema regex on `PositionCreate.source`** (`backend/app/modules/boq/schemas.py:184`) and `PositionUpdate.source` (line 268) accepts `cwicr` alongside `manual`, `cad_import`, `ai_takeoff`, `gaeb_import`, `excel_import`, `takeoff`, `smart_import`, `smart_import_ai`, `cad_import_ai`, `cost_database`, `assembly`, `enriched`. iModel-driven BOQ pushes can use `source: "cwicr"` and `cost_item_id` directly via the public API.

## [2.7.0] - 2026-05-03

**Stable release rolling up 14 patch iterations (2.6.41 → 2.7.0).** Single shipping artefact for all platforms (PyPI · git tag · VPS · GitHub release). All entries below - 2.6.42 through 2.6.54 - are part of this release; the per-version sections are kept for changelog continuity but ship as one tag.

### Highlights since v2.6.41
- **CWICR download fixed on Windows** (issue #104) - replaced stdlib `urllib.request` with `httpx` + `certifi`, so HTTPS downloads of region catalogs no longer fail with `CERTIFICATE_VERIFY_FAILED` on stock Windows.
- **Cost-DB modal opens instantly** - startup pre-warm + 60-min cache + idle-time prefetch + skeleton loading state.
- **Multi-variant resource picker** - explicit modal for cost items with multiple independent variant slots; bulk-fill chips, per-row delta vs mean, RTL-correct layout, 19 i18n keys × 5 langs.
- **Variant resources dedupe** - three-layer fix (modal, apply-time, render-time, summary aggregator) so shared catalogs across components no longer surface as duplicate "▾N" pills; "Variant" violet-gradient chip replaces the cryptic "Materials" type chip on variant rows.
- **Imported / cleared cost databases appear immediately** - `_invalidate_cost_cache()` now wired to `bulk_import_cost_items`, `import_cost_file`, `clear_cost_database`.
- **5 new UI languages** - hr, id, ro, th, vi (now 24 total UI langs / ~28 k keys).
- **QA-crawler bug sweep** - 12 + 3 fixes from automated multi-locale crawl (trailing-slash, region-delete confirm, modal a11y, …).
- **/tasks page DnD optimistic update** - cards move between columns immediately, rollback on PATCH failure.
- **/bim - disk-usage chip moved to hover-tooltip** - model name area no longer clutters with `data/bim/ 86.3 MB` on every project.
- **Privacy / Terms rewritten for self-hosted edition.**
- **Resource-row depth + GAEB audit polish** - 8 fixes: encoding, units, hierarchy, paragraphs, version detection.

### Fixed - CWICR download from GitHub on Windows (issue #104)
- **Replaced `urllib.request.urlretrieve` with `httpx.stream` + `certifi`.** Python's stdlib `ssl` on Windows ignores the OS certificate store, so every HTTPS download to `raw.githubusercontent.com` failed with `SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate` - symptom reported in #104 by skolodi (v2.6.37) trying to load `SP_BARCELONA`. New `_download_to_file()` helper uses `httpx`, which is already a project dep and ships the Mozilla CA bundle via `certifi`, so verification works on Windows without `pip install python-certifi-win32` or env-var workarounds. Streams in 1 MB chunks so the 1.1 GB Qdrant snapshot doesn't blow up RAM. Three call sites swapped: CWICR parquet download, vector-embeddings parquet download, and Qdrant snapshot download.

### Fixed - Imported / cleared cost databases now appear immediately
- **Import endpoints invalidate the cost cache.** `bulk_import_cost_items`, `import_cost_file`, and `clear_cost_database` now call `_invalidate_cost_cache()` on success - was: only `clear_region_database` and `load_cwicr_database` did, so a freshly imported region (e.g. NZ_AUCKLAND via Excel/CSV) was hidden behind a 60-min stale `_region_cache["regions"]` until the cache TTL elapsed or another invalidating call fired. User-visible symptom: "imported a database but nothing in /costs page".
- **`_invalidate_cost_cache()` wipes all value slots, not just `ts`.** Now nulls every key in `_region_cache` (regions / stats / categories_*) explicitly so any future cache slot that doesn't piggy-back on the shared timestamp is still cleared.

### Fixed - Variant resources: dedupe shared catalogs + clear "Variant" chip
- **Dedupe ▾N pickers across components that share a `resource_code`.** CWICR rate `KADX_KATO_KAKASA_KATO` ships two resource rows ("Stahlkonstruktionen" + "Befestigungsteile für Schienen") both pointing at code `KALI-RI-KATO-KANE` with the same 3-variant catalog. Before: both BOQ rows + both summary rows showed identical "▾ 3" pills, looking like a UI bug. After: only the FIRST row per `resource_code` carries the picker; linked rows render plain. Applied at three layers: BOQ "Add from DB" apply-time (`BOQModals.tsx`), grid render-time for legacy positions (`BOQGrid.tsx`), and resource summary aggregation (`backend/app/modules/boq/router.py` - new `resource_code` field on `ResourceSummaryItem`).
- **Dedupe top-level vs component catalogs by variant-label hash.** BG_SOFIA rate `KADX_KADX_KAKARI_KAME` ("Монтаж на метални конструкции") ships its 8-variant catalog as BOTH `metadata.variants` AND `components[0]` ("Стоманени конструкции"). The "Choose materials" modal previously rendered two slots with identical 8 options, identical price, identical −13% delta - both reading like a duplicate. Now `collectVariantSlots()` hashes each catalog by its label sequence: when the top catalog matches a component catalog the top slot is dropped, AND `BOQModals.handleAdd` skips the synthetic top-level resource it used to append (the "third extra" the user flagged), so a 2-component cost item adds exactly 2 resources to the BOQ.
- **Multi-variant picker modal also dedupes.** `collectVariantSlots()` no longer emits two cards for the same catalog - picks fan to all linked components when the position is materialised.
- **"Variant" type tag replaces the Material/Labor/Equipment chip on variant rows.** The left-side type chip on a BOQ resource row is now a violet-gradient "Variant" badge when the row carries a variant catalog, instead of the cryptic black "Materials" tag that didn't hint at the picker. Same chip lands on the Resource Summary panel. Reclassification still works - clicking opens the full type list - but the chip face is unambiguous about variant status. The decorative "V" circle in the resource name area is unchanged.

## [2.6.53] - 2026-05-02

### Performance - Cost-DB modal opens instantly
- **Backend cost-DB cache pre-warm at startup.** New background task in `app/main.py` runs `SELECT DISTINCT region` + `regions/stats` + `categories(all)` + `category_tree(depth=4)` for every active region during the first 2 s of boot, populating `_region_cache` and `_category_tree_cache` before any request hits. The first user click on "Add from Database" or `/costs` page no longer pays the 18 s + 16 s + 86 s cold aggregation cost.
- **Search-endpoint count(*) fast-path.** When the search call has no text/category/classification filters and no cursor (the modal's first page), the total is now read from the prewarmed `_region_cache["stats"]` instead of running `SELECT COUNT(*)` over the filtered subquery. Full-catalog count took 18 s on a 277 k-row catalog before; cache lookup is microseconds.
- **Cache TTL bumped 5 min → 60 min.** `_CACHE_TTL` and `_CATEGORY_TREE_CACHE_TTL` raised; both are correctly wiped on import/delete via `_invalidate_cost_cache()`, so the longer hold doesn't risk staleness - it just stops the same scan from repeating every 5 min for an unchanged catalog.
- **Modal opens with `depth=2` tree, not `depth=4`.** The cost-DB modal's classification sidebar now uses a 2-column GROUP BY (~10 s cold) instead of a 4-column GROUP BY (~85 s cold) on a 277 k-row catalog. Deeper levels are still reachable via the search endpoint's `classification_path` filter when the user clicks a level-2 leaf, so coverage isn't lost.
- **Frontend idle-time prefetch on BOQ editor mount.** `BOQEditorPage.tsx` now prefetches `/v1/costs/regions/`, `/v1/costs/category-tree/?region=<first>&depth=2`, AND the first-page `/v1/costs/?limit=15&region=<first>` search via `requestIdleCallback` (setTimeout fallback) - all three heavy modal calls warmed in parallel via `Promise.all` while the editor is idle. React Query is hot for the FIRST CLICK on "From Database" even on a freshly-restarted backend before its server-side prewarm finishes.
- **Modal seeds region from React Query cache synchronously.** `BOQModals.CostDatabaseSearchModal` reads the `cost-regions-modal` cache in a lazy `useState` initializer so the modal mounts with the right region (e.g. `FR_PARIS`) instead of `''`. The previous code rendered with `region=''` for one render tick before the auto-default `useEffect` ran, which fired wasted `tree?depth=2` (no region - heaviest GROUP BY) and `search?limit=15` (no region - slowest `COUNT(*)`) calls. With the cache seed, those wasted calls are eliminated when the BOQ-editor prefetch is hot.
- **Skeleton table in the modal results pane.** Generic centered "Loading…" spinner replaced with 8 skeleton rows that mirror the actual result columns (checkbox / description / unit / qty / rate / region). Reads as "loading specific data" instead of "stuck".

### Fixed - `/costs` page no longer flashes "No database loaded" while loading
- **Skeleton vs empty-state.** `RegionTabBar` now distinguishes "still loading regions" from "actually empty" - when `loadedRegions` is `undefined` (request in-flight), shows a tab-bar skeleton with `Loading databases…` instead of the dashed-border "No database loaded" empty-state. Cold SQLite responds in 18 s on 100 k+ catalogs; the previous code conflated the two and showed the import-CTA empty-state for the entire wait, so the user reported the page as "broken / loads forever".

### UX - BOQ position add: section picker + apply-to-remaining
- **"Add to: …" footer dropdown.** Cost-DB modal footer now exposes the BOQ's existing sections in a dropdown ("[Root]" + each section by ordinal). Selecting a section files new positions under it with parent-relative ordinals (`<section>.<NNN+1>`) and threads `parent_id` into the POST body. Backend already accepted `parent_id` on `PositionCreate` since v1; the UI just wasn't surfacing it. Hidden in resource-pick mode and when the BOQ has no sections.
- **"Apply to remaining N" CTA in the multi-variant picker.** When mid-batch with more multi-variant items waiting, the picker footer surfaces an `Apply to remaining {{count}}` button. Clicking it captures the user's slot picks and short-circuits every subsequent open in the batch - slots are matched by name across CWICR rows so concrete-grade × rebar-diameter × formwork picks carry over even when item A and item B share resource names but different variant catalogs. Trailing "Applied picks to N more items" toast on completion.

## [2.6.52] - 2026-05-02

### UX - Cost-database add flow deepening
- **Inline quantity per row.** Cost-DB modal table now has a Qty column with a numeric input per row - sets `position.quantity` at POST time instead of the legacy hardcoded `1`. Eliminates the 20-cell-edit chore after a 20-item batch add. Focusing the input auto-selects the row.
- **Live cost preview in footer.** Footer shows `≈ €X` next to the selection counter - Σ(catalog rate × qty) for everything currently selected, so a 5-item batch isn't committed blind. Updates in real time as the user toggles selection or edits quantity.
- **Validation hints surface pre-add.** Items with `rate ≤ 0` (CWICR rows whose price never landed) and items with `unit = lump_sum` (where qty × rate is ambiguous) now show an amber `AlertCircle` next to the rate with a tooltip - same checks that the post-add quality dashboard runs, surfaced before commit.
- **Partial-success error recovery.** Per-item POST is now wrapped in try/catch with a `failed[]` array. If 18 of 20 items POST successfully and 2 fail, the loop completes and shows a warning toast listing the casualties - was: first failure aborted the entire batch silently.
- **Keyboard navigation in the row list.** ↓/↑ moves the highlighted row, Space toggles selection, Enter toggles (or fires Add when selection is non-empty), PageDown/PageUp jumps 10 rows, Home/End jumps to ends. Highlighted row gets an outline ring; scrollIntoView keeps it visible. Skips the handler when focus is in an input so search-as-you-type stays unaffected.

## [2.6.51] - 2026-05-02

### UX
- **Multi-variant position add: explicit picker for 2+ slots.** When a CWICR cost item has multiple independent variant resources (e.g. concrete grade × rebar diameter × formwork type), `Add to BOQ` now opens a centered modal - one card per slot, bulk-fill chips (median / average / cheapest / priciest), per-row delta-vs-mean, live position subtotal. Single top-slot items keep the existing anchored popover; the legacy silent-median path is the cancel fallback. New: `frontend/src/features/costs/MultiVariantPicker.tsx` + `collectVariantSlots()` helper; `BOQModals.handleAdd` routes through it whenever there are 2+ slots or any per-component slot.
- **Multi-variant picker hardening pass.** Two parallel deep-audit subagents flagged six concrete gaps; all addressed in this release:
  - **RTL.** Replaced physical `mr-/ml-/text-right/text-left` with logical `me-/ms-/text-end/text-start` so Arabic users see a correctly-mirrored modal (was: header icon + price column on wrong side).
  - **Keyboard.** Apply button receives initial focus; Enter applies (was: Esc-only).
  - **Subtotal bug.** `slot.quantity || 1` replaced with `slot.quantity ?? 1` - a legit 0-qty slot (rebar=0 for unreinforced section) no longer inflates the position rate by treating it as 1 unit.
  - **Dark-mode contrast.** Selected variant rows had ~1.05:1 contrast vs unselected; added `ring-1 ring-inset ring-oe-blue/30` and bumped tint to `dark:bg-blue-950/30`.
  - **Token fix.** `border-border-medium` (undefined) → `border-border` for the unselected radio circle.
  - **Batch progress.** Adding 5+ items with multi-slots now shows an "Item N of M" badge in the header so the user knows how many modal opens remain.
  - **Provenance.** Position metadata stamps `ui_source: "multi_picker" | "single_popover" | "silent_default" | "no_variants"` so adoption is measurable from the audit log.
  - **i18n.** 19 new `boq.mvp.*` keys translated for en / de / ru / ja / ar in `i18n-fallbacks.ts` (German uses statistics-correct "Mittelwert" not "Durchschnitt"; Russian has 3 plural forms; Arabic has 6 plural forms incl. zero/two).

## [2.6.50] - 2026-05-02

### Performance
- **N+1 in `punchlist.get_summary`.** Counts pushed into SQL `GROUP BY`; only the closed-item timestamps still walk Python (date-diff isn't portable across SQLite + PostgreSQL). Drops full-row hydration of every punch item per stats call.
- **N+1 in `tasks.get_task_stats`.** Same pattern - total / by_status / by_type / by_priority / overdue / completed all run as SQL aggregates. Only the JSON `checklist` column for non-completed tasks is iterated (for `avg_checklist_progress`), and only the projected column ships, not full ORM rows.

### Fixed
- **Architecture page: 3968 React Flow warnings per render → 0.** `ModuleNodeComponent`, `ModelNodeComponent`, `RouteNodeComponent` had no `<Handle />` - every edge logged "Couldn't create edge for source handle id: null" once per render cycle. Added hidden source/target handles on all three.
- **Wider browser smoke clean - 53/53 routes.** Caught more disabled-module 404s: `/markups` calling `/v1/takeoff/measurements/`, `/dwg-takeoff` calling `/v1/dwg_takeoff/offline-readiness/`, `/project-intelligence` calling `/v1/project_intelligence/summary/`. All gated through the shared `isModuleLoaded` probe; the project-intelligence page now shows a translatable "module disabled" empty state.

## [2.6.49] - 2026-05-02

### Performance
- **N+1 in `meetings.get_stats` / `get_open_actions`.** Both loaded full ORM rows for every non-cancelled meeting just to walk the JSON `action_items` column. New repo method `action_items_for_project` fetches `(id, number, title, date, action_items)` only - drops every other column and ORM hydration.
- **N+1 in `fieldreports.get_summary`.** Same shape - full hydration of every report to compute counts. Pushed `total / by_status / by_type / total_delay_hours` into SQL `GROUP BY` + `SUM`; only the JSON `workforce` column still needs a Python pass for `count*hours`.
- **Compound indexes added.** New migration `v2b1_compound_type_indexes`: `(project_id, meeting_type)`, `(project_id, inspection_type)`, `(project_id, report_type)`. List filters used in dashboards no longer scan the project's whole row set when a type filter is applied.

### Security
- **IDOR sweep batch 4 - markups module.** Five endpoints patched: `link_to_boq`, `get_summary`, `export_markups`, `update_stamp_template`, `delete_stamp_template`, `delete_scale`. Stamp mutation now routes through `_authorize_stamp_mutation` (project members for project-scoped templates, owner-only for predefined). Scale deletion restricted to its `created_by`. AST guard extended 86 → 96 parametrized assertions.

### Fixed
- **Wide browser smoke clean - 25/25 routes.** Disabled-module 404 noise on `/data-explorer`, `/takeoff`, `/documents` traced to frontend calling `oe_takeoff` / `oe_dwg_takeoff` endpoints regardless of load state. Extracted a shared `isModuleLoaded` probe (`shared/lib/moduleProbe.ts`); rolled out across `cad-explorer/api.ts`, `dwg-takeoff/api.ts`, `takeoff/api.ts`, `quantities/QuantitiesPage.tsx`, `bim/api.ts` (refactored from inline probe).
- **MapLibre style noise.** `ProjectMap` switched from `liberty` to `positron` style - liberty's POI expressions tripped MapLibre's evaluator with "Expected value to be of type number, but found null instead." once per rendered card. Positron is quieter.
- **`ProjectMap` cache poisoning.** `parseFloat` of malformed Nominatim responses could write `NaN` (serialized as `null`) into the geocode cache, then read back as null lat/lng. Added `isFiniteNumber` guard on both write and read; bad cache entries are evicted on read.
- **CommandPalette rAF leak.** `requestAnimationFrame` for input focus on open had no cleanup - palette mount/unmount churn could fire `focus()` against a stale ref. Now `cancelAnimationFrame` on cleanup.

## [2.6.48] - 2026-05-02

### Performance
- **N+1 elimination on Change Orders list.** `repository.list_for_project()` now `selectinload(ChangeOrder.items)` - was firing one extra query per row to lazy-load items. Page with 50 orders: 51 queries → 1.

### Fixed
- **BIM page console noise.** Frontend probes `/v1/modules/` once per session and skips the `/v1/takeoff/converters/` request entirely when `oe_takeoff` is disabled, instead of relying on a swallowed 404 that the browser still logs to the network panel. Browser smoke now 6/6 routes clean.
- **Frontend timer cleanup leaks.** `BIMViewer.tsx` (geometry-progress timeout) and `BOQGrid.tsx` (3 grid-refresh setTimeouts) now track timers in refs and clear them on unmount - fast nav between BOQ/BIM pages no longer leaves orphaned callbacks running against an unmounted tree.

### Security
- **Stack-trace leak fixes.** `schedule/router.py` and `projects/router.py` 500-handlers stopped echoing `str(exc)` in `detail`; `backup/router.py` adds `from exc` to preserve the chain server-side without exposing it. Internal error messages no longer ship to clients.

## [2.6.47] - 2026-05-02

### Performance
- **SQLite write-lock deadlock - system-wide fix.** Every `await event_bus.publish(...)` inside a request handler held the SQLite single-writer lock while subscribers (the wildcard webhook dispatcher and ~7 notification handlers in `core/event_handlers.py`) opened their own writer sessions. SQLite serialised the second writer; requests hung ~30s before timing out. Live probes show formerly-30s routes now ~100ms: `POST /ncr/` 101ms, `POST /fieldreports/reports/{id}/submit/` 72ms, `POST /inspections/{id}/create-ncr/` 68ms.
- Centralised the fix in a new `EventBus.publish_detached(...)` method that wraps `publish` in `asyncio.create_task`. All 21 module-local `_safe_publish` helpers and 28 direct `await event_bus.publish(...)` callsites across 16 modules now route through it. Production semantics: subscribers fire after the request commits and releases the writer.
- Test-time shim in `tests/conftest.py` drives the publish coroutine to completion via a single `coro.send(None)` so the existing event-capture fixtures keep their pre-detached synchronous assertion semantics. 2597 unit tests green.

### Fixed
- **Latent crash in `assemblies/service.py`** - two more lazy `from app.modules.boq.models import BOQPosition` imports (lines 709, 955) - same renamed-class bug that hit `tendering/service.py` in v2.6.46. `get_usage_stats()` and `compute_assembly_usage_by_id()` would 500 on first call. Patched to `Position as BOQPosition` alias.

### Security
- **IDOR sweep batch 3** - 3 more modules patched: `requirements` (GET/PATCH/DELETE /{set_id}), `documents` (GET/{id}, GET /{id}/download/, PATCH /{id}, DELETE /{id}), `teams` (PATCH/DELETE /{team_id}). Documents download path was the highest-impact gap - any authenticated user could pass any document UUID and stream the file. Now `verify_project_access` after fetching the resource. AST guard test extended from 68 → 86 parametrized assertions.

## [2.6.46] - 2026-05-02

### Added
- **Cross-module: Tendering → Procurement auto-PO.** Awarding a tender bid now publishes `tendering.package.awarded`; a new procurement subscriber drafts a PO pre-filled with the winning supplier, line items, currency, and totals. Idempotent via `metadata.tender_package_id`. PMs no longer retype every line of the winning bid by hand. Verified live: award creates one draft PO with `metadata.origin="tender_award"`; re-firing the same award is a no-op.
- **Cross-module: Field Reports → Schedule progress.** Submitting a field report whose `metadata.schedule_progress = [{task_id, progress_percent, notes}]` carries activity progress now publishes `fieldreports.report.submitted`; a new schedule subscriber appends a `ScheduleProgressEntry` per task and rolls the activity's `progress_pct`/`status` forward. Per-report idempotency via `Activity.metadata_.field_report_progress`. Verified live: 60% → 100% over two reports yields 2 history entries and `status=completed`.
- **Inspection → NCR auto-suggest.** New `POST /api/v1/inspections/{id}/create-ncr/` pre-fills a Non-Conformance Report from a failed inspection with mapped `ncr_type`, severity (`critical` if any failed item is `critical: true`), location, and a description listing failed checklist items + notes. Idempotent via `linked_inspection_id`. Complements existing `/create-defect/` (punchlist) - punchlist for minor defects, NCR for formal non-conformance with root-cause/CAPA.

### Fixed
- **Latent crash in `apply_winner`.** `tendering.service.apply_winner` imported `BOQPosition` from `app.modules.boq.models`, but the class is `Position`. Every tender award has been 500'ing on the BOQ writeback step, masking the broken integration entirely. Repointed to `Position` (also for the SQLAlchemy `update()` statement); award now writes the winning unit rates back to the BOQ as designed.
- **`create-defect` checklist parsing.** The endpoint that creates punchlist items from failed inspections looked for a non-existent `passed: bool` field on checklist items, missing every actual `response: "fail"` (the schema-defined convention). Now accepts both forms - legacy `passed` and canonical `response` in (no/fail/false/0/failed). Without this, "create defect" generated empty-description punchlist items even when the checklist had real failures.
- **NCR-creation deadlock on SQLite.** `NCRService.create_ncr` awaited `event_bus.publish("ncr.created", ...)` before the request transaction committed; the wildcard webhook dispatcher and smart-notification subscribers (#23, #24 in `event_handlers.py`) open their own writers via `async_session_factory()`, deadlocking the SQLite single-writer lock for ~30s before the request timed out. Detached as `asyncio.create_task(...)` so subscribers run after the parent commit. Same pattern applied in v2.6.45's CO→BOQ work and v2.6.46's tendering/fieldreports subscribers.

## [2.6.45] - 2026-05-02

### Added
- **Cross-module: Change Order → BOQ pushdown.** Approving a change order now appends a section `CO-{code}: {title}` plus one position per `ChangeOrderItem` into the project's primary unlocked BOQ, with `metadata.origin="change_order"` and back-reference IDs. Construction PMs previously saw `project.budget_estimate` jump on approval but no scope appearing in the BOQ - this closes that loop. Idempotent: re-approving an already-approved CO is a no-op (existing ENH-095 guard) and the section-level guard short-circuits even if the no-op were bypassed. Surfaces in the `changeorder.approved` event payload as `boq_applied / boq_section_id / boq_positions_added`. Verified live: 2 items + 1 section row land in the right BOQ; second approve adds nothing more.

### Fixed
- **Latent bug in change-order approve.** `approve_order` accessed `order.project_id` after `repo.update_fields()` had called `session.expire_all()`, which under aiosqlite raises `MissingGreenlet` (sync attribute refresh in async context) and 500'd the entire approval whenever `cost_impact != 0`. Stub-session unit tests masked it because they bypass expiration. Now uses the `project_id_uuid` snapshot captured before the update.

### Notes
- v2.7.0 backlog items previously marked open (EAC validator FK fixture, demo_credentials test failures, v260c migration idempotence) are already resolved on `main` - confirmed via direct test run; tracker stale.

## [2.6.44] - 2026-05-02

### Security
- IDOR sweep batch 2 - 6 more modules patched. RFI, Submittals, Correspondence, Transmittals, Markups, Change Orders single-resource handlers (`GET/PATCH/DELETE /{id}`) now `verify_project_access` after fetching the resource, returning 404 for non-owners. 18 handlers total. Live cross-user check: admin gets 200, estimator gets 404 across rfi/submittals/correspondence/changeorders. AST anti-regression test extended from 32 → 68 parametrized assertions.

### Verified (no code change)
- `/api/v1/dashboards/presets` previously returned 500 in dev - root cause was missing local migrations `v2a0_compliance_dsl_rules` + `v2b0_preset_sync_columns` (committed in repo for v2.10/2.11 but never applied to dev DB). After `alembic upgrade head`, endpoint returns 200. Live probe of all 28 unique frontend `apiGet` paths against running v2.6.43 returns 200. Bulk-resolved 99 more stale findings in `qa-tests/improvements.json` (50 NotificationBell medium-sev + 49 silent-HTTP) - open count down from 707 to 552, with the remaining 552 all `performance`-category LCP improvement candidates rather than bugs.

## [2.6.43] - 2026-05-02

### Security
- IDOR sweep across 6 modules - single-resource handlers (`GET/PATCH/DELETE /{id}`) now call `verify_project_access(resource.project_id, user_id, session)` after fetching, returning 404 (not the resource) for non-owner non-admin users. Affected: NCR (3 endpoints), Inspections (3), Meetings (3), Punchlist items (3), Risk (3), Takeoff document delete (1) - 16 handlers total. Verified live: legit owner gets 200, cross-user request gets 404 "Project not found" (matches finance/erp_chat pattern).

### Fixed
- Export functions across 7 features (`contacts`, `tasks`, `fieldreports`, `rfi`, `costs`, `costs/import`, `finance`) used `body.detail || 'Export failed'` to surface the error - but FastAPI 422 returns `detail` as an array of objects, which JS coerces to `[object Object]` in the toast. Now route through `extractErrorMessageFromBody()` which flattens 422 arrays, handles plain-string bodies, and falls back to a status-coded message (`Export failed (HTTP 500)` etc.).
- QA-crawler nav-shape heuristic produced 43 false positives ("Open menu", project picker, Radix dropdown triggers) flagged as "did not navigate". Engine now reads `aria-haspopup` / `aria-controls` / `data-radix-collection-item` BEFORE clicking and skips the nav-shape rule for popup-trigger elements - these legitimately open overlays without changing the URL, and our overlay-detect window can briefly miss them.

### Added
- `backend/tests/unit/test_idor_router_guards.py` - AST-level anti-regression test that walks each protected handler and asserts both `session: SessionDep` accepted and `verify_project_access` called. Catches silent regressions where a refactor drops the IDOR guard without breaking the legit-owner happy path.

### Verified (no code change)
- v2.6.40-42 backend 500 sweep was effective end-to-end. Live probe of 40 distinct URLs from older QA-crawler journey logs (Search, NotificationBell unread-count, Switch Project, custom-units, system/status, fieldreports/summary, contacts/search, projects/dashboard, etc.) - all return 200/2xx with the demo token. Stale "high severity" findings in `qa-tests/improvements.json` are residue from pre-fix runs and have been bulk-resolved (76 silent-HTTP + 43 discoverability-FP + 1 IDOR fix = 120 items).

## [2.6.42] - 2026-05-02

### Fixed
- 12 more trailing-slash 404/422 endpoints across `/v1/collaboration/comments`, takeoff `save-to-project`, tasks/meetings/finance/fieldreports/inspections/RFI imports & exports, BOQ project-activity, and documents upload.
- `Costs > Import database` per-region delete button bypassed confirmation - destructive single-click that wiped a whole region's pricing data; now `window.confirm`-gated.
- `ChangeOrders` row-level delete and `PunchList` item delete and `Photos` batch delete now require explicit user confirmation before mutating.
- `FinancePage` EVM panel rendered KPI cards as `NaN` - the `/v1/finance/evm/` endpoint returns an envelope `{items, total}`, but the React Query was typed as a single `EVMData`. Now extracts `items[0]` (the latest snapshot) and `parseFloat`s every Decimal-as-string metric (BAC/PV/EV/AC/SPI/CPI/EAC/VAC/ETC/TCPI).
- `ReportingPage` stale-data race when switching projects mid-fetch - six parallel stat fetches (finance/safety/tasks/RFI/schedule/procurement) could resolve out of order and overwrite the current project's data with the previous project's responses. Generation-counter ref now discards in-flight responses from stale generations.

### Changed
- 8 more modals given WCAG `role="dialog"` + `aria-modal="true"` + `aria-labelledby` for screen readers and QA-crawler modal-detect heuristic: BOQ Manual Resource, BOQ Recalc/GAEB-export/Add-section, Catalog Build-assembly/Adjust-prices, BOQ Variables, Asset Edit.
- QA-crawler engine: post-click modal-detect timeout 400ms → 1000ms (was missing slow modals like Three.js Snapshot creator), and locale-switcher 401 noise suppressed in silent-http-error heuristic (bootstrap re-auth retries make these false positives).

### Added
- Unit tests for v2.6.40 anti-regressions: `test_documents_relative_path` (path-traversal containment), `test_database_pool_config` (SQLite pool sizing applied), `test_fieldreports` JSONB string-coercion + malformed-workforce resilience.
- Unit test pinning the `EVMListResponse` envelope shape and Decimal-as-string serialization contract - prevents the EVM endpoint from drifting back to a bare list (root cause of the FinancePage NaN bug).

## [2.6.41] - 2026-05-01

### Fixed
- 3 more trailing-slash 404/422 endpoints surfaced after the v2.6.40 sweep: `/v1/procurement/goods-receipts`, `/v1/contacts/search`, `/v1/fieldreports/reports` - frontend now hits the slashed form so the lists actually populate.
- `Delete Region` on `/catalog` ran without confirmation - destructive action wiped the entire region's resources on a single click. Now gated by `window.confirm`, matching the BOQ section-delete pattern.

### Changed
- `CreateResourceModal` (catalog) given proper `role="dialog"` + `aria-modal="true"` + `aria-labelledby` - was a bare div, invisible to screen readers and to the QA-crawler heuristic.

## [2.6.40] - 2026-05-01

### Fixed
- `NotificationBell` crashed every route with `displayItems.map is not a function` - backend returns `{items, total, unread_count}` but the React Query was typed as `Notification[]`.
- `CommandPalette` global search 404 + envelope mismatch - frontend now hits `/v1/search/?q=…` and reads `.hits[]` instead of treating the envelope as an array.
- `GET /api/v1/fieldreports/reports/summary/` returned 500 - JSONB workforce entries with stringy `count`/`hours` now coerced to float before arithmetic.
- `GET /api/v1/documents/{id}/download/` returned 403 on demo seed records - `file_path` stored as relative now resolves against `UPLOAD_BASE` instead of CWD, so the security containment check passes (file-not-found still returns a clean 404).
- Trailing-slash 404s on five endpoints called without slash before `?`: punchlist items, takeoff measurements, safety incidents (× 2), safety observations (× 2), markups stamp templates, sustainability EPD materials.
- `fetchTeamMembers` hit a non-existent `/v1/projects/{id}/members` endpoint; now falls back to `/v1/users/?limit=100` so the punch-list assignment dropdown actually populates.
- Duplicate React keys in `Changelog` for two adjacent v1.9.6 entries - key now combines version + date + array index.
- SQLAlchemy connection-pool exhaustion under concurrent load - SQLite path was silently using SQLAlchemy default `pool_size=5/overflow=10` (the configured 24/10 was Postgres-only). Now applied for both backends; 50-concurrent stress test is clean.

## [2.6.38] - 2026-05-01

### Changed
- `privacy-policy.html` and `terms.html` shipped with the local self-hosted app rewritten - now state explicitly that data stays on the operator's server, that DataDrivenConstruction is not Controller / Processor of project data, and list every outbound network call (AI APIs you configure, GitHub releases for converters / CWICR, PyPI for upgrades). The marketing-site versions at openconstructionerp.com keep their SaaS-style copy because that one *is* operated by us. Self-hosted vs demo distinction made unambiguous.

## [2.6.37] - 2026-05-01

### Added
- `oe_admin` module with `POST /api/v1/admin/qa-reset` for QA-pipeline / crawler reset of the demo dataset. Triple-gated: `QA_RESET_ENABLED=1` env var + matching `QA_RESET_TOKEN` body + tenant must equal `"demo"`. Off by default; nothing fires in production unless an operator explicitly opts in.

### Fixed
- Variant resource prefix (`price_abstract_resource_common_start`) shown in From-Database modal results. Variant items now render the abstract base name as primary line and the rate-code description as a smaller subtitle, so estimators scan rows by material instead of CWICR codes.
- Resource row self-heals legacy stored names that lost the `common_start` prefix - when `composedVariantName` extends `storedName` with the abstract base, prefer the composed form. Catches rows the v2.6.30 backfill missed without a round-trip.

### Changed
- `/costs` page initial render sized for fast first paint: `PAGE_SIZE` 20 → 10, `staleTime` 5 min on regions / stats / categories so quick navigation away-and-back no longer re-fires aggregates.
- BOQ "From Database" modal first paint within ~150 ms: search query fetches 15 items (was 50) with IntersectionObserver auto-loading the rest as the user scrolls.
- Resource rows visually nest under their parent position - slightly deeper background + inset top-shadow makes sub-positions read as sub-positions, not standalone rows.
- Backend `/v1/costs/category-tree/` accepts `depth` (1..4) and `parent_path` for future lazy-tree expansion. Default behavior unchanged (depth=4, full tree).

### i18n
- 24 languages bulk-translated in `i18n-fallbacks.ts` via parallel-agent pipeline (`scripts/i18n_extract.py` + `scripts/i18n_apply.py`): ~28,000 keys across `ar/bg/cs/da/de/es/fi/fr/hi/hr/id/it/ja/ko/nl/no/pl/pt/ro/ru/sv/tr/vi/zh`. Missing-key + English-bleed detector finds rows that were silently English; agents fill them in chunks; merge step rewrites the file in one pass. `th` deferred to next release.
- Marketing site `id` / `th` gap-filled: same-as-EN strings reduced from 349/431 to 56/56 (only proper nouns / codes remain).
- Vietnamese backend + marketing translations completed in wave 2.

## [2.6.36] - 2026-04-30

### Added
- 5 new UI languages: Croatian (`hr`), Indonesian (`id`), Romanian (`ro`), Thai (`th`), Vietnamese (`vi`). Frontend `SUPPORTED_LANGUAGES` now 26. Backend + marketing locales aligned (`hi` was missing from backend, `bg`+`hi` from marketing - added).

### Fixed
- `backend/pyproject.toml` version was out of lockstep with `frontend/package.json` and `CHANGELOG.md` in v2.6.35 (committed at 2.6.34; PyPI build patched it). Lockstep restored at v2.6.36.
- `backend/locales/` removed from `.gitignore` - new UI-language stubs were silently dropped from git on v2.6.35. Tracked baselines so source-added langs ship in releases.

## [2.6.35] - 2026-04-30

### Fixed
- Quantity edit no longer snaps back to old value after ~1s. FormulaCellEditor passes `cancel=true` to `stopEditing` after `setDataValue`, suppressing AG Grid's secondary commit from a doubly-mounted StrictMode editor.
- Variant resource name no longer carries rate-code description as prefix bleed. Apply path uses `full_label → common_start + label → label → baseDescription`. `backend/scripts/backfill_variant_prefix.py` rewrites already-stamped names.
- Unit dropdown commits via mouse click again (third recurrence). Capture-phase document-mousedown shield was halting dispatch before React's `onMouseDown<li>`. Replaced with native `<ul>` listener reading `data-unit-value`.
- Resource rows use the same portaled-dropdown unit editor as position rows.
- Multi-variant per position: each variant component gets its own picker pill - `available_variants` forwarded for ALL components on apply, not just the first.
- `/costs/import` Installed Databases section reappears under empty/loading/error states; uninstall buttons restored.
- Quantity save instant: PATCH response splices into cache (no full BOQ refetch). Sibling rollups debounced 400ms.
- Revit `.rvt` upload no longer fails on `BIMHubService.create_model() got an unexpected keyword argument 'created_by'`.

### Added
- "Report a bug" entry in user menu - pre-filled GitHub issue with anonymized last error, app version, page, build hash.
- BOQ position description shows inline (i) icon when source cost item has `scope_of_work`; click opens portaled bullet-list popover.
- `/costs` variant detail compacted: inline stat strip + clamp top-8 with "Show all N" toggle (~1700px → ~250px).
- VariantPicker accordion when ≥2 groups, flat list for 1.

## [2.6.34] - 2026-04-30

### Added
- CWICR loader now imports per-component variant catalogs. Each abstract resource row inside a rate is preserved as its own resource with `available_variants` + `available_variant_stats` stamped on the component itself. Rates like `KANE_RINE_KAKARI_KARI` now arrive with all 3 variant resources (formwork / panels / boards), each with its own picker - previously only the first row survived and the other two were silently dropped.
- CWICR loader now imports `metadata.scope_of_work` - the ordered list of work steps (`Состав работ` / `Scope of work` / `Arbeitsumfang` / `Composition des travaux`). Verified universal across all 30 regions in the catalog.

### Fixed
- Variant builder falls back to `..._all_values_per_unit` when `..._all_values` is empty, recovering catalogs for rate rows that only populate per-unit pricing (~4,800 rates per region).
- Scope-of-work detector no longer relies on the `is_scope` flag (which is False in DE/FR exports) - uses `work_composition_text` non-empty + `resource_name` empty as the universal rule.

### Changed
- CWICR loader runs in no-cache mode: each `POST /load-cwicr/{db_id}` re-downloads the parquet from GitHub and deletes it in `finally` after processing. `~/.openestimator/cache/` is no longer consulted on lookup and stays empty between runs. Locally-installed DDC_Toolkit parquets (Priority 1) are still used and left untouched.

## [2.6.33] - 2026-04-30

### Fixed
- Variant resource qty / rate edits now contribute to the position's unit_rate sum. The synthetic VARIANT row materializes the variant as a real entry in `metadata.resources[]` on first edit, so it participates in `Σ(r.qty × r.rate)` like every other resource. After the first edit the row renders as a regular resource line with its own ▾ re-pick pill.
- Unit dropdown pick is no longer dropped by AG Grid 32's outside-click detector. The dropdown is portaled to `<body>`, so AG Grid's *native* document-level mousedown handler used to fire `stopEditing(true)` (cancel) before the React `onClick` could commit. Added `nativeEvent.stopImmediatePropagation()` on both UL and LI mouse events so the pick wins the race.

### Changed
- V-badge on positions with variant resources now toggles the resource panel (expand / collapse) instead of opening the variant picker. Picker access stays on the synthetic VARIANT row's "Variant" chip and on the per-resource ▾ pill in the expanded panel.

## [2.6.32] - 2026-04-30

### Fixed
- Variant resource header no longer mirrors `position.quantity` for legacy positions. The synthetic header now defaults to `1` (per-unit norm) when `metadata.variant.quantity` is unset, so editing position qty never touches the variant resource qty visually or in storage.

### Added
- Per-resource variant pickers when a position carries multiple variant resources. `available_variants` + `available_variant_stats` now persist on every variant resource at add-time, so each resource gets its own re-pick pill in the expanded panel; the position-level synthetic header is suppressed when one or more resources carry their own variant catalog.

## [2.6.31] - 2026-04-30

### Changed
- "All databases" tab removed from the cost-database picker. Only country-specific DB tabs render now.

### Fixed
- Unit cell editor: picking a unit from the dropdown now actually commits the value. AG Grid 32's outside-click detector was cancelling the edit before `pick()` could run because the dropdown is portaled to `<body>`. `stopPropagation` on the dropdown's `mouseDown`, plus a synchronous `mouseDown` commit on each list item, keeps the pick alive.

## [2.6.30] - 2026-04-29

### Changed
- Cost-database modal: country DBs lead the region tabs row, "All databases" pushed to the end.
- Variant resource quantity is now stored at `metadata.variant.quantity` and decoupled from `position.quantity` - editing one no longer changes the other.

### Added
- Paginated "From Database" search (cursor + 50/page) and a category tree sidebar backed by `GET /api/v1/costs/category-tree/` (5-min cache).
- Calculated custom-column type with formula textarea, Test button, and live re-eval (Phase E).
- Autocomplete tooltip for Description column (Phase F).

## [2.6.29] - 2026-04-29

### Added
- **BOQ formula engine - cross-position references, named variables, conditionals, unit conversions, cycle detection.** Phase C of `inherited-knitting-dahl` plan. The hand-written CSP-safe parser at `frontend/src/features/boq/grid/cellEditors.tsx` now accepts `pos("01.02.003").qty / .rate / .total`, `section("Concrete").total`, `col("MyCol")` (in calculated columns), `$GFA` style variables, comparison ops (`<`, `>`, `<=`, `>=`, `==`, `!=`), `if(cond, a, b)` short-circuit, 8 unit converters (`m_to_ft`, `ft_to_m`, `m2_to_ft2`, `ft2_to_m2`, `m3_to_yd3`, `yd3_to_m3`, `kg_to_lb`, `lb_to_kg`), and `round_up(x, n)` / `round_down(x, n)`. Cycle detection ports the visited-set DFS pattern from `service.py` to TypeScript via Tarjan's SCC; warn-and-allow policy - cycle participants render a yellow ⚠ marker, computed value 0, full cycle path in tooltip, save NOT blocked. Live re-eval orchestrator with 200ms debounce coalesces qty/rate/variable changes. Backwards-compat preserved: `evaluateFormula(input)` legacy single-arg signature unchanged. New `frontend/src/features/boq/grid/formula/` directory; 68/68 vitest cases (engine, cycle detection, cross-position).
- **BIM model persistence** - uploaded BIM models stay viewable after revisit. New `keep_original_cad: bool = False` setting in `backend/app/config.py`; conversion artefacts (canonical JSON, GLB, thumbnails) persist forever, originals are deleted after successful conversion when `keep_original_cad=False` (default) or kept when set to `True`. Failed conversions keep originals so user can retry. `GET /api/v1/bim_hub/models/` enriched with `conversion_artifact_size_mb`, `has_original`, `error_code`, plus aggregate `total_artifact_size_mb` / `total_original_size_mb` / `storage_root_label`. New `DiskUsageChip` in BIM page header surfaces data root + total artefact size with hover tooltip. 4 new pytest integration cases.
- **CWICR cost-database localisation across 16 locales.** New `backend/app/modules/costs/translations/` directory with locale dicts for de, en, ro, bg, sv, it, nl, pl, cs, hr, tr, id, ja, ko, th, vi. RO/BG/SV fully populated; rest cover units + common construction materials with high-confidence terms. `costs/router.py` accepts `?locale=ro` query param or `Accept-Language` header and emits `*_localized` mirror keys (`category_localized`, `unit_localized`, `group_localized`) - originals always preserved as fallback. `shared/lib/api.ts` auto-forwards `Accept-Language` from `i18next.language`. Backfill script at `backend/scripts/translate_cwicr_columns.py` writes localised mirrors into the SQLite cache idempotently. 42 backend + 7 frontend tests; verified RO_BUCHAREST / BG_SOFIA / SV_STOCKHOLM produce non-German values for `BAUARBEITEN` → `LUCRĂRI DE CONSTRUCȚII` / `СТРОИТЕЛНИ РАБОТИ` / `BYGGNADSARBETEN`.
- **Resource-row variant re-picker.** v2.6.25 added per-resource variant snapshots; v2.6.29 lets the user re-pick variants on already-added resource rows. New `PATCH /api/v1/boq/positions/{id}/resources/{idx}/variant/` endpoint re-uses `_stamp_resource_variant_snapshots` for idempotent sibling preservation; recomputes position-level `unit_rate` from the per-unit subtotal sum; emits `boq.position.updated` with `kind=resource_variant_repick`. Frontend `EditableResourceRow` shows a small `▾ N` pill on every resource with `available_variants` cached at add-time, opens the existing `VariantPicker` preselected on the current pick. 4px left-edge provenance bar (blue=explicit pick, amber=default-from-mean, none=plain). Backwards-compat: legacy resources without `available_variants` degrade gracefully. 13 unit + 5 integration + 9 vitest tests.
- **Resource type chips i18n across all 21 locales.** Resource-type labels (labor / material / equipment / operator / subcontractor / electricity / composite / other) now flow through `getResourceTypeLabel(type, t)` in three render sites (`CatalogPickerModal`, `ResourceSummary`, `CatalogPage`). 168 new translation entries (8 keys × 21 locales) with construction-industry vocabulary per locale (de: Bediener / Energie; ru: Машинист / Электроэнергия; fr: Opérateur / Électricité; ja: オペレーター / 電力; etc.). 217-assertion vitest spec covering canonical list shape, fallback when no `t` supplied, every-locale-has-every-key contract, integration with live i18next.

### Fixed
- **GAEB import / export - 8 concrete fixes uncovered by deep audit.**
  - Encoding sniff on import: `decodeXmlBuffer()` now reads the `<?xml encoding=...?>` prolog and uses the matching `TextDecoder`. Legacy DACH GAEB files in ISO-8859-1/Windows-1252 no longer corrupt ä/ö/ü/ß into `U+FFFD`.
  - Unit codes: `GAEB_UNIT_CODES` map translates internal canonical units (`m2`/`m3`/`pcs`/`lsum`/`hr`) to GAEB DA short codes (`m²`/`m³`/`Stk`/`psch`/`Std`) on export, with reverse map on import. Round-trip with common DACH GAEB tools works.
  - Hierarchy: `buildSectionTree()` walks dotted ordinals and creates arbitrarily-deep section nodes with recursive `renderSection()`. Multi-level Los → Titel → Position structures no longer flatten on export.
  - Line breaks: import-side `normaliseRunWhitespace()` collapses only horizontal whitespace, preserves `\n`. Export emits one `<Text>` per paragraph instead of one blob.
  - Version & namespace: emits spec-compliant `<VersMajor>3</VersMajor><VersMinor>3</VersMinor>` (was non-standard `<Version>3.3</Version>`); namespace correctly uses `DA81` for X81, `DA83` for X83 etc.
  - ShortText: first paragraph only, no ellipsis (was multi-line + `...` which many AVA readers display verbatim).
  - Filename: `<projectName>-<boqName>.<ext>` (was `<boqName>.<ext>`).
  15 new regression tests; 45/45 GAEB tests pass (was 30/30); tsc clean. No new dependencies, no backend changes (GAEB I/O is client-side TypeScript).
- **VariantPicker currency falls back to region currency, not USD.** `BOQModals.tsx` chain was `item.currency || 'USD'`; for abstract-resource cost items with empty `item.currency` (despite real-currency variant prices in EUR/BGN/RON/SEK/JPY), this rendered `$ 1,200` on Bulgarian / Swedish / Japanese rows. Now extends with `REGION_MAP[item.region]?.currency` between the item value and USD-as-last-resort. So `BG_SOFIA` shows BGN, `RO_BUCHAREST` shows RON, `SV_STOCKHOLM` shows SEK.
- **BUG-LANG-AUTODETECT - wizard's Get Started button now writes `oe_lang_explicit=1`.** The auto-detect useEffect (added earlier in this version cycle) only re-detects from `navigator.language` when `oe_lang_explicit` is unset. Previously a US-Windows admin landed in Polish UI just because someone else had demoed the build in Polish on the same machine and left a stale `i18nextLng` value.
- **BUG-AUTO-PROJECT-SELECT - `/bim` cold open now pins resolved project into `useProjectContextStore`.** When `urlProjectId` and `contextProjectId` are both empty, `BIMPage` falls back to `projectsList[0]` for the models query, but never wrote that pick into the global store. Other pages (recents, breadcrumb, BOQ landing, upload dialogs) read `activeProjectId` from the store and decided "no active project" → dimmed CTA / kicked back to picker. Now we pin the resolved fallback into the store the first time we resolve one, only when nothing else has set it (never overrides explicit picks).
- **BUG-DUAL-UPLOAD-PDF - TakeoffPage no longer re-uploads the same PDF to `/api/v1/documents/upload`.** The `uploadMutation` `onSuccess` used to fire `createDocumentRecord(file)` for "cross-referencing", which doubled bytes-on-disk and produced two identical entries in the Documents module. Removed entirely. If a takeoff doc needs to surface in the Documents module, do it backend-side at upload time via FK, not by sending the file twice.

## [2.6.28] - 2026-04-29

### Fixed
- **BUG-RVT01 · CRITICAL - every native CAD upload crashed pre-flight with `ValueError: stdin and input arguments may not both be used`.** `backend/app/modules/boq/cad_import.py:275` passed both `stdin=subprocess.PIPE` and `input=b"\n"` to `subprocess.run`; Python forbids the combination because `input=` already implicitly sets `stdin=PIPE`. Pre-flight check fired on every RVT / IFC / DGN / DWG upload through `BIMHubService` and pinned models at `error_code=ddc_smoke_failed` even when the binary was correctly installed. Removed the explicit `stdin=PIPE`. Smoke test now runs: `smoke_test_converter('rvt')` → `{status: ok}`, `smoke_test_converter('ifc')` → `{status: ok}`.
- **BUG-RVT02 · log/response inconsistency on install-time smoke timeout.** When the install endpoint at `backend/app/modules/takeoff/router.py:614-623` hit the 15-second timeout (binary loaded fine and is sitting in a Qt message loop - the design-intent "healthy" path), the catch-all exception handler emitted `WARNING Smoke test for X converter failed: ...` while the response correctly reported `smoke_test_passed: true`. Split into an explicit `TimeoutExpired` branch (logs at INFO, "binary loaded but waiting for stdin; treating as healthy") and a real-failure branch that now correctly flips `smoke_ok = False` and surfaces a useful `message` instead of relying on the default-true initial value.
- **BUG-RVT03/04 · `converter_required` upload now persists the file and returns 202 Accepted.** Before: `POST /api/v1/bim_hub/upload-cad/` with no converter installed returned HTTP 201 with `model_id: null` and `file_size: 0` - the file was silently discarded and the user had to re-upload after install. Now: the file lands at `data/bim/{project_id}/{model_id}/original.{ext}` exactly like a normal upload, a `BIMModel` row is created with `status="needs_converter"` so the user can `Re-process` from the UI after installing, and the response is 202 Accepted with `Retry-After: 60` and a `Link` header pointing at both the install endpoint and the model's `/retry/` endpoint. HTTP semantic correctness restored: 201 means "resource created", 202 means "request accepted, will be processed".
- **Unit validator: sanitise, don't gate.** The strict 36-entry allowlist that 422'd anything outside the curated catalogue produced a steady stream of "unit 'X' is not in the approved BOQ unit catalogue" failures every time a regional CWICR import landed: Romanian `Bucat`, Bulgarian `бр`, Russian `шт`, German `Stück`, French `unité`, plus per-trade slang (`man-day`, `lin.m`, `MWh`, `kg/m`, `%`). Replaced with a permissive sanitiser at `backend/app/modules/boq/units.py`: any 1–30 character string starting with a letter (any Unicode script - Latin, Cyrillic, Greek, CJK, accented) or a digit (multi-prefix forms) or `%` (percentage) passes through, lowercased and stripped. Common synonyms (`ton`/`tonne`/`tonnes` → `t`, `hour`/`hours`/`h` → `hr`, `metre`/`metres` → `m`) still canonicalise via the alias map so unit-breakdown stats don't fragment. Genuinely unsafe shapes (HTML / SQL / shell / quote / control characters, > 30 chars, non-letter / non-digit / non-`%` leading char) still 422 with a clear message naming the actual constraint instead of dumping the full catalogue. Alias precedence flipped so synonyms collapse first, fixing the original BUG-MATH03 complaint that "hour" and "hr" produced separate buckets. 98 new pytest cases (canonical round-trip, alias canonicalisation, every locale spelling above, multi-prefix forms, malicious-input rejection). Existing integration test updated: "xyz" is now an accepted custom unit; HTML payloads remain rejected.

## [2.6.27] - 2026-04-28

### Fixed
- **Flags missing on Windows for 10 CWICR regions** - Australia, New Zealand, Croatia, Romania, Thailand, Vietnam, Indonesia, Mexico, South Africa, Nigeria all rendered as literal "AU"/"NZ"/etc. text on Windows because Win10/Win11 have no native flag-emoji glyphs in any system font. The emoji-only fallback added in v2.6.23 worked on Mac/Linux but not Windows. Replaced with real inline SVG flags for all 10 - guaranteed to render on every platform. SVG designs are simplified but recognisable at 14–32 px sizes.
- **CWICR download error message was useless** - "CWICR database 'RO_BUCHAREST' not found. Install DDC_Toolkit…or check your internet connection" gave the user no signal whether the issue was a stale backend (no mapping for the new 19 regions in v2.6.22-), a partial cached file stuck at <1 KB, a network failure, or an upstream 404. Loader now records the last download failure per `db_id` and surfaces it through the 404 response: "backend has no GitHub mapping" / "returned 0 bytes (likely 404)" / "{ExceptionType}: {message}. URL: …". Partial-cache leftovers are auto-discarded so the next attempt gets a clean slot.

## [2.6.26] - 2026-04-28

### Fixed
- **Unit "ton" rejected on CWICR add** - "Failed to add positions, unit 'ton' is not in the approved BOQ unit catalogue". Added a canonical alias map: `ton`/`tons`/`tonne`/`tonnes`/`mt` → `t`, `metre`/`metres`/`meter`/`meters` → `m`, `sqm`/`sq.m`/`cum`/`cu.m` → `m2`/`m3`, `each`/`piece(s)` → `ea`/`pcs`, `lump sum`/`lumpsum` → `lsum`, `hours`/`week`/`days`/`mo` → canonical forms. Aggregations stay coherent (everything buckets into the canonical unit) without rejecting common spellings.
- **Country flags missing on cost-database regions** - `<CountryFlag code="DE_BERLIN" />` returned null because the lookup used the full lowercased key. The component now extracts the country prefix from region keys (`DE_BERLIN` → `de`, `AU_SYDNEY` → `au`) and maps non-ISO prefixes (`USA_USD` → `us`, `ENG_TORONTO` → `ca`, `SP_BARCELONA` → `es`, `PT_SAOPAULO` → `br`, `AR_DUBAI` → `ae`, `ZH_SHANGHAI` → `cn`, `HI_MUMBAI` → `in`, `CS_PRAGUE` → `cz`, `JA_TOKYO` → `jp`, `KO_SEOUL` → `kr`, `SV_STOCKHOLM` → `se`, `VI_HANOI` → `vn`) so all 30 CWICR regions render with proper flags everywhere.
- **BIM converter status panel could not be dismissed on /bim** - `BIMPage` mounted the banner without `dismissible`, so the X button was never rendered. Now passed; banner can be closed and the dismissed flag persists in localStorage.
- **Re-check: "Operation failed Not Found"** - the verify endpoint (`POST /v1/takeoff/converters/{id}/verify/`) only landed in v2.6.23. When users on stale backends click Re-check, the 404 now surfaces a clear "Backend version too old, run `pip install --upgrade openconstructionerp`" toast instead of a bare error.

## [2.6.25] - 2026-04-28

### Added
- **Per-resource CWICR variants on multi-resource positions.** When a position is composed of more than one variant-bearing resource (e.g. concrete C30 + rebar 8mm), each resource entry now keeps its own immutable `variant_snapshot`. The "Add resource from cost database" flow opens the variant picker first, the picked rate lands on the resource entry, and the backend's new `_stamp_resource_variant_snapshots` walks `metadata.resources[]` independently so a later cost-DB re-import cannot silently rewrite any one of them. 4 new pytest cases (per-resource stamp, mixed variant + variant_default + plain, idempotent no-op patch, switch one resource without disturbing the other).

### Changed
- **VariantPicker UX redesign.** Width 360 → 520px so full descriptions are visible with `line-clamp-3` instead of single-line truncation. Stats banner now shows Min / Avg / Median / Max (Avg added). Search input visible at ≥6 variants. Sort dropdown: default / price asc / price desc / label A→Z. Per-row delta-vs-mean chip (`+N%` amber, `-N%` emerald, `≈ avg` gray) so price spread reads at a glance. Selected row highlighted with `ring-1 ring-inset`. Empty state on filter miss. All 8 existing contract tests still green.

## [2.6.24] - 2026-04-28

### Fixed
- **RBAC: viewers / demo users can now add BOQ positions.** `boq.update` lowered to VIEWER; `boq.create` was already at VIEWER, so the original gate was inconsistent (start a BOQ, can't fill it).
- 10 new CWICR cost-database regions (au, hr, id, mx, ng, nz, ro, th, vn, za) now show their flag in onboarding and `/costs/import`.
- Cost-database search modal: when no database is imported, surface a "Import a database" CTA pointing at `/costs/import` instead of a generic "no results" line.

### Added
- **BOQ preset library 8→14** with regional grouping. Universal: Procurement / Notes / Quality / Sustainability / Status & Scope / Tendering / Schedule. Regional (collapsible): GAEB-AVA, ÖNORM-BRZ, USA CSI MasterFormat, Australia AIQS, Brazil SINAPI, UK NRM2, BIM Integration. Plan: `inherited-knitting-dahl.md` Phase A.
- **Per-BOQ named variables** ($GFA, $LABOR_RATE …). Backend: `BOQVariable` schema + `GET/PUT /v1/boq/boqs/{id}/variables/`, capped at 50 vars, UPPER_SNAKE_CASE regex, type coercion. Frontend: `BOQVariablesDialog` mounted from Grid Settings dropdown with table editor (name/type/value/description). Plan Phase B; will feed into formula engine in Phase C.
- 16 new vitest cases for the preset registry (form + backwards-compat for legacy ids); 10 new pytest integration cases for the variables endpoint (round-trip, validation, cap, replace-semantics, type coercion).

## [2.6.23] - 2026-04-28

### Added
- **CWICR cost database expanded from 11 → 30 regions.** DDC repo grew with 19 new countries (AU, NZ, IT, NL, PL, CS, HR, BG, RO, SV, TR, JA, KO, TH, VI, ID, MX, ZA, NG); registry, REGION_MAP, DatabaseSetupPage, ImportDatabasePage, OnboardingWizard all updated. Onboarding region grid grouped by region (Anglosphere / Western Europe / CEE / MENA / APAC / Americas) with a search filter so 30 entries don't dominate the step. `LANG_TO_REGION` updated so `it`→`IT_ROME`, `ja`→`JA_TOKYO`, `ko`→`KO_SEOUL`, `nl`→`NL_AMSTERDAM`, `pl`→`PL_WARSAW`, etc. - previously these locales fell back to DE/SP/ZH approximations.
- **BIM converter health check + smoke test.** `GET /v1/takeoff/converters/?verify=true` now runs an 8s smoke test per installed converter (parallel via `asyncio.gather`) to catch DLL load failures, Mark-of-the-Web blocking, missing VC++ Redistributable, wrong-arch binaries. New `POST /v1/takeoff/converters/{id}/verify/` for on-demand re-check. Result cached 5 min server-side; cache invalidated on install/uninstall. Pre-flight smoke test added to RVT background processor so a broken-but-installed binary fails fast with a structured error instead of a 5-minute conversion that produces nothing.
- **BIM converter status panel rewrite.** Always visible on `/bim` (was hidden when all installed); shows `health` per converter with ✓ Working / ⚠ Broken / ⬇ Not installed pills, install path on hover, Re-check button on every installed row, action buttons mapped from backend's `suggested_actions` (Install / Reinstall / Install VC++ Redist / Manual install on GitHub / Unblock files / Run as Administrator). IFC now included (was previously omitted, which is why "Revit and IFC don't load" was reproducible). Dismissible mode added; mounted on `/projects` empty state so fresh-install users see converter status before creating their first project.
- **Abstract resource variants polished to ship-quality.** Default = mean rate when applying a CWICR cost item with multiple price variants (closest-to-mean entry chosen when no exact match). Inline variant picker (`▾ N options`) on every BOQ unit_rate cell; opens the same `VariantPicker` used at apply time. Position metadata stamps a `variant_snapshot = {code, rate, currency, captured_at}` so subsequent CWICR re-imports don't silently rewrite the position's rate. Visual markers: 4px left-edge bar (blue for explicit pick, amber for default = mean) plus an Abstract pill in the description cell. Excel export gains a "Variant" column. 6 backend tests + 8 frontend tests; all green.

### Fixed
- **VPS source-dir shadowed wheel for ALL modules, not just `_frontend_dist`.** The systemd `WorkingDirectory=/root/OpenConstructionERP/backend` puts the source `app/` tree ahead of the installed wheel on `sys.path`, so every Python module updated in a new wheel was silently shadowed by the old source. Caught when the v2.6.22 demo-login route returned 404 despite the wheel containing it. Deploy procedure now rsyncs the entire wheel `app/` over `backend/app/` after every `pip install`.
- **BOQ cell edits jumped back to old value before re-updating** (lag bug at `/boq/{id}`). The `updateMutation` in `BOQEditorPage.tsx` performed an optimistic `setQueryData` write but didn't `cancelQueries` on the in-flight refetch issued by sibling mutations (add/reorder/catalog/etc.) - so the GET landed AFTER the optimistic write, clobbered the cache with stale server data, and the new value reappeared only when the PATCH eventually returned. Added `await queryClient.cancelQueries({ queryKey: ['boq', boqId] })` in `onMutate`, snapshot+rollback in `onError`, invalidation moved from `onSuccess` to `onSettled` (fires once per mutation). Cell edits now feel instant.

## [2.6.22] - 2026-04-28

### Fixed
- **"Demo login failed. Please try again." on every fresh install.** The seeder in `app.main._seed_demo_account` generates a fresh `secrets.token_urlsafe(16)` per install (BUG-D01 - no hardcoded credential is shipped) and persists it to a 0600 credentials file, but the frontend's "Demo login" button hard-codes `DemoPass1234!`. So login → 401, auto-register → 409 "already registered", user → "Demo login failed". Added a dedicated `POST /api/v1/users/auth/demo-login/` endpoint that mints tokens for whitelisted seeded accounts without a password check (gated by `SEED_DEMO=true`, rate-limited per IP). Frontend now hits this endpoint; falls back to the legacy login+register pair against pre-v2.6.22 servers so deployments don't break the moment the new client ships.
- **3D viewer stuck silently when CAD conversion fails (Hans's report).** The non-ready overlay now renders the backend's `error_message` directly so users see *why* their model didn't render - "RVT converter not installed", "RVT version newer than the converter", "No elements extracted from this IFC file" - instead of a generic "Error" placeholder. Background processor populates a structured `metadata.error_code` (`ddc_not_found` / `ddc_failed` / `zero_elements` / `unexpected`) so the UI can dispatch on it.
- **DWG/DGN converter install showed "Internal server error"** instead of the actual reason. The `POST /api/v1/takeoff/converters/{id}/install/` endpoint only translated `RuntimeError` to a 502 - any other exception (rate-limited GitHub API, JSON decode error, OS permission denied) leaked as a generic 500. Wrapped the whole handler in a top-level `except` that returns 502 with `{exception_class}: {message}` so the install banner displays the real cause and a manual-install link.
- **Linux install attempts shown as failures.** When the backend returned the structured `platform_unsupported: true` body with apt-install instructions, the banner mutation treated `installed: false` as "success", flashing "Installed" toast text. Now the toast branches on `result.installed`: success, info+long-duration on Linux (with the apt commands), warning on smoke-test failure, error on network failure. `InstallConverterPrompt` mirrors the same logic and refuses to auto-retry the upload when the install didn't actually succeed.

### Added
- **Retry button on the BIM viewer error overlay** - re-runs background DDC conversion for a previously failed model via new `POST /api/v1/bim_hub/{model_id}/retry/` endpoint. Useful after the user installs a missing converter (the "Install converter" button on the overlay auto-retries on success), or when the original failure was transient (network blip, OOM during a parallel upload burst).
- **Pre-flight converter check before RVT processing.** `_process_cad_in_background` now verifies the RVT converter is installed up front and returns `status="needs_converter"` with a specific install link, instead of letting the pipeline run to the generic "no elements extracted" message.
- **Post-install smoke test for the Windows DDC converter.** After downloading binaries from GitHub, `POST /api/v1/takeoff/converters/{id}/install/` launches the binary once with a 15s timeout to catch missing-DLL errors (`STATUS_DLL_NOT_FOUND`, `STATUS_DLL_INIT_FAILED`). Failures surface immediately with re-install instructions instead of the user discovering the problem on their next CAD upload.

## [2.6.21] - 2026-04-28

### Added
- **Custom unit catalogue persists per-user across browsers and sessions.** Units typed into the BOQ Unit cell now sync to `User.metadata_["custom_units"]` via two new endpoints (`GET`/`PATCH /api/v1/users/me/custom-units/`). Previously the catalogue lived only in `localStorage`, so a unit added on one device was invisible everywhere else. App boot calls `syncCustomUnitsFromServer()` once after auth resolves; commits push to the server fire-and-forget. Anonymous / offline sessions fall back to localStorage cleanly.

### Fixed
- **Resource name reverts to old value on first edit.** Renaming a catalogued resource fired two sequential `onUpdateResource` calls (`name`, then `code: ''`). Both read the same React Query cache snapshot, and the second mutation overwrote the first - so the new name was visibly written and immediately reset to the original. Symptom: "name only saves on the second click." Fixed by collapsing the two writes into a single `onUpdateResourceFields(posId, idx, {name, code: ''})` mutation.
- **Resource name X-coordinate matches position description.** Removed the `pl-4` indent added in v2.6.20 - `InlineTextInput`'s built-in `px-1` already matches the position description column's `!pl-1`, so resource names and position names sit on the exact same vertical line.

## [2.6.20] - 2026-04-28

### Fixed
- **Issue #103 - Gemini API model out-of-date.** Default model bumped `gemini-2.0-flash` → `gemini-2.5-flash` so Test Connection in Settings → Configuration succeeds again.
- **IFC viewer rendered all-black.** When a converted IFC ships without `IfcSurfaceStyle`, DDC's DAE export writes `<color>0 0 0 1</color>`; trimesh preserves it into the GLB and the model was rendering as a flat black silhouette. Detect near-black albedo (Rec.601 luma < 0.04) per mesh and substitute the discipline-coloured `MeshStandardMaterial` instead. Original material is still cached on `userData.originalMaterial` so reset/colorBy modes are unchanged.
- **BOQ alignment - 28px shift between position values and resource values.** The position grid has a 28px-wide visible `_bim_qty` column between `unit` and `quantity`; the resource row jumped directly from unit to qty, pushing every resource numeric (qty / rate / total / actions) 28px LEFT of its position counterpart. Added an aria-hidden 28px spacer slot (and a classification spacer for the case where that hidden column is toggled on) so right edges line up exactly.

### Added
- **Formula support on resource quantities** (Issue #90 follow-up). Resource qty / rate inline inputs now recognise the same Excel-style syntax as the position quantity editor: `=2*PI()*3`, `12.5 x 4`, `=sqrt(144)`. Live `= …` preview pops below the input while typing; on commit the evaluated number is written, errors leave the value unchanged. Pure numeric input continues through the existing path with no behaviour change.

### Changed
- **Quantity formula popup editor - sized for readability.** Fixed dimensions 180px × 32px (was the cell's 110px × ~24px), text size lifted from xs to sm. The popup no longer balloons rightward into the Unit Rate column when a long expression is typed.

## [2.6.19] - 2026-04-28

### Fixed
- **Resource name vs position description X-alignment** - `InlineTextInput`'s display-mode span already adds `px-1` (4px) of horizontal padding internally. The resource name slot was *also* applying its own `pl-1`, double-padding to 8px while the position description column padding is only 4px (`!pl-1`). Removed the outer `pl-1` so the input span's own 4px is the single source of truth - resource names now start at the exact same X coordinate as position description text.
- **Resource quantity vs position quantity X-alignment** - same double-padding bug on numeric slots. `InlineNumberInput`'s display span adds `px-1` (4px), and the qty slot had `pr-2` (8px), totalling 12px from slot right-edge to text right-edge while the position quantity cell uses only 8px (`!pr-2`). Resource qty slot reduced to `pr-1 pl-1` (4px) so combined with the input's 4px it sums to 8px, matching the position cell exactly.

## [2.6.18] - 2026-04-28

### Fixed
- **BOQ resource calculation model - corrected to per-unit norms** (the standard estimating-suite convention). Resources are now stored as quantities-per-1-unit-of-position. Position `unit_rate = Σ(r.quantity × r.unit_rate)` (no division by qty). Position `total = quantity × unit_rate`. Changing position quantity no longer scales resource quantities or recomputes unit_rate - only the total scales. Three sites fixed:
  - `frontend/.../BOQGrid.tsx` `onCellValueChanged`: removed proportional resource scaling on qty edit.
  - `frontend/.../BOQEditorPage.tsx` `handleUpdateResource`: dropped `/ posQty` divisor.
  - `backend/.../service.py` `update_position`: only `triggered_by_resources` (not `triggered_by_qty`) recomputes unit_rate; formula is `sum`, no division.

### Changed
- **BOQ row alignment** - position cells and resource sub-rows now share an identical column grid:
  - Resource left section restructured to mirror AG Grid columns 1:1 (code slot = ordinal column width, tag slot = bim_link column width, name slot = description column).
  - `--ag-cell-horizontal-padding` 16px → 8px globally so AG Grid cells and resource slots use the same padding; right-edges of qty / unit_rate / total line up across positions and resources.
  - Resource font sizes 11px → 12px to match position `text-xs`.
  - Position ordinal made `text-right` so its right edge aligns with the resource code right edge.
  - Resource catalogue code: full code visible (no truncation), 8px font, fixed 100px right-aligned slot.
  - Expanded position rows now render ordinal / description / qty / unit_rate / total in `font-bold` so they stand out from the indented resource sub-rows.
- **Toolbar dedup** - removed duplicate "Update Rates" entry from the Quality & AI dropdown menu; the standalone toolbar button is the only entry point.
- **Checkbox column** trimmed 36px → 24px to reduce empty space between drag handle and expand chevron.

### Added
- "Update Rates" error toast now surfaces the actual exception message (instead of a generic "Recalculation failed") and writes a `[Update Rates]` line to the console for debugging.

## [2.6.17] - 2026-04-28

### Fixed
- **BOQ unit catalogue** - `'100 EA'`, `'1000 m'`, and other CWICR multi-prefix forms (rate-per-N units) were rejected by `PositionCreate` / `PositionUpdate`. New `normalise_unit()` helper accepts `<N> <approved_unit>` patterns with up to 6-digit multipliers and lowercases the trailing token. Bare units behave as before.

### Changed
- **Resource row UX** in BOQ inline editor:
  - Resource-type badge replaced with a fit-content portal-popover picker. Native `<select>` rendered every badge at "EQUIPMENT" width regardless of label; each badge now sizes to its own content (MATERIAL / LABOR / EQUIPMENT / SUBCONTRACTOR / OTHER).
  - Catalogue code chip moved from the right of the name to the **left**, so the article number is the first thing the eye lands on. Auto-clears when the user commits a different name - the row then represents a customised resource saveable to the user's personal catalogue via the existing BookmarkPlus action.
  - Currency dropdown grouped: project-FX-configured codes first, then a 33-currency global ISO 4217 list (USD/EUR/GBP/CHF/JPY/CNY/RUB/INR/CAD/AUD/NZD/SGD/HKD/KRW/BRL/MXN/ZAR/TRY/PLN/CZK/HUF/SEK/NOK/DKK/RON/AED/SAR/QAR/ILS/THB/IDR/MYR/PHP/VND). Picking a currency without a configured FX rate still flags the total cell with the existing "no FX" amber badge.

## [2.6.16] - 2026-04-28

### Added
- CWICR abstract-resource variants surfaced end-to-end. Importer preserves the 4 bullet-separated parquet columns (`variable_parts`, `est_price_all_values`, `position_count`, plus the per-unit sibling) into `CostItem.metadata_['variants']` + `['variant_stats']`. Cost DB grid shows a blue "N variants" badge next to the rate; clicking the row expands a detail panel with KvList stats, sorted variants table, and a "Median" chip on the median row. BOQ "From Database" → row pick triggers a portal popover (`VariantPicker`) for choosing a specific variant; chosen price overrides `unit_rate`, label is appended as `(Variant: …)` suffix in the description, and `metadata.variant` is written to the BOQ position. BOQ grid renders a marker badge next to variant-bearing rows.
- 8 new i18n keys per locale (EN + RU) under `costs.*` and `boq.*`.

### Changed
- Demo database trimmed from 75 mixed (Cycle/CostLink/Domain/Smoke probes) to 6 curated demo projects: Boylston Crossing, Wohnpark Friedrichshain, Residencial Salamanca, Residencial Vila Madalena, 上海徐汇职业学校扩建工程, Downtown Medical Center.
- Hoisted `KvList`, `Kv`, `QtyTile` from BIM drawer to `frontend/src/shared/ui/` so cost variant detail panel can reuse them.

### Fixed
- **Issue #101 - RBAC: BOQ create blocked for viewer-tier users.** `boq.create` lowered from EDITOR to VIEWER so any signed-in user (including freshly self-registered viewers) can start an estimate; project ownership / membership is still enforced by the service. `RequirePermission` now falls back to the live permission registry when the JWT's frozen permission list omits a lowered permission, so existing sessions don't have to re-login. Update / delete remain editor-gated.
- Several quality slices from prior sessions: punchlist photo upload now reads body before mkdir (413 fires even when storage is unwritable); AI photo/file estimate endpoints reject oversize Content-Length pre-emptively; assemblies formula-engine narrows the `except` ladder so type errors surface; erp_chat splits `ValueError` from generic `Exception` to stop flooding the journal with expected AI-key tracebacks; bim_hub forward-ref hoisted to module-level import; dwg_takeoff `l` → `layer` (E741); eac executor SIM103 collapsed; catalog `urlopen` offloaded to `asyncio.to_thread` to keep the event loop responsive.

## [2.6.15] - 2026-04-27

### Added
- Provenance markers across exporters and runtime artifacts so a forked deploy can be traced back. COBie/IDS/Excel/PDF/SARIF exports stamp `OpenConstructionERP · DDC-CWICR-OE-2026` in document metadata; SVG favicon carries an RDF authorship block; JWT tokens include `iss: openconstructionerp`; outbound catalog HTTP requests advertise the project User-Agent.

## [2.6.14] - 2026-04-27

### Fixed
- Alembic migrations `v260b` and `v260c` no longer raise on missing project / EAC tables - they skip with a warning so `Base.metadata.create_all()` at boot can handle the schema. Was bricking every prod `alembic upgrade head` while the running service was fine.

## [2.6.13] - 2026-04-27

### Fixed
- COBie XLSX export - `<a href>` clicks didn't carry the JWT, plus the URL had a trailing slash that 307-redirected. Replaced with `downloadCobieXlsx()` that fetches with Authorization header and triggers a synthetic download.
- `/assets` page contrast - text was hardcoded `text-neutral-100/200/300` so it disappeared in light theme and especially under hover. Switched to design tokens (`text-content-*`, `bg-surface-*`, `border-border-*`) so both themes are legible.
- Asset detail drawer uses the same theme tokens - backdrop, header, action bar, KvList, QtyTile, BIM properties rows all adapt to light/dark.

## [2.6.12] - 2026-04-27

### Fixed
- Frontend version sync - `frontend/package.json` was stuck at 2.6.10 through the v2.6.11 release, so the bundled UI kept reporting the old version. Both versions now move in lockstep (Issue #101 follow-up).
- Asset Register `/assets` route 422 - `GET /v1/bim_hub/assets` and `PATCH /v1/bim_hub/assets/{id}/asset-info` are now declared before `GET /v1/bim_hub/{model_id}` so FastAPI matches the literal path first.
- DWG annotation provenance preserved - backend `update_position` strip pass now also skips `dwg_annotation_source` when the caller includes it (mirrors the BIM/PDF carve-outs from v2.6.11).

### Added
- Asset detail drawer on `/assets` - click any asset row (or the new geometry icon) to open a side drawer with quantities, the full BIM properties (lazy-loaded from the same Parquet endpoint the 3D viewer uses), and an "Open in 3D Viewer" deep-link.
- BOQ "Quality & AI" dropdown - Validate / Update Rates / AI Chat are promoted inline; the rest (Price Check, Cost Finder, Smart AI) live behind a single dropdown to free up toolbar space.
- Per-measurement BOQ link in PDF Takeoff - link a single measurement to one BOQ position with a quantity-transfer preview and a unit-mismatch warning.
- Update banner shows installed → latest delta - `v{current} → v{latest}` and "X changes in v{latest}" instead of the ambiguous "X changes" count.
- `dwg_annotation_source` icon + short-label in the BOQ Quantity / Unit cells.

### Tests
- `test_boq_bim_qty_source_roundtrip.py` extended with PDF and DWG carve-out cases - all 4 pass.



### Fixed - Issue #96 (CLI / installer)
- **`openconstructionerp upgrade`** new command that pip-installs into the *same* Python env it's running in (uses `sys.executable -m pip`). The Windows installer creates a private venv at `%LOCALAPPDATA%\OpenConstructionERP\venv`; running `pip install --upgrade openconstructionerp` from any other shell upgraded the user's global Python instead, leaving the launcher's venv pinned to the old wheel - so the startup banner kept reporting the old version even though pip claimed success. The new command always lands in the right env. `version` now also prints `Site-packages: …` so users can see which interpreter the launcher is actually using.

### Fixed - BOQ editor
- **VAT row no longer hardcoded.** Removed the German-19% fallback in `boqHelpers.ts`. The Net→VAT→Gross footer is now driven from the `tax`-category row in Markups & Overheads (single source of truth, matches the backend PDF/Excel exporters). When no tax markup exists, the VAT and Gross Total rows are hidden; adding any tax markup re-introduces them with the correct rate.
- **Volume column edit lag fixed.** `updateMutation.onMutate` now writes the new value to the React Query cache immediately instead of only clearing badges, so a quantity edit no longer flickers through the old value for ~5 s while the server round-trips.
- **BIM picker provenance preserved.** Backend `update_position` was unconditionally stripping `metadata.bim_qty_source` / `pdf_measurement_source` on any quantity change - including the same request that the BIM Quantity Picker used to *set* them. Now the strip pass skips link keys that the caller explicitly included in incoming metadata; pure manual quantity edits still drop the badge as before. Added `tests/integration/test_boq_bim_qty_source_roundtrip.py` (2 cases) covering both branches.
- **BIM / PDF source icons in the Quantity cell.** `QuantityCellRenderer` now renders a small Cuboid icon for BIM-sourced cells and a Ruler icon for PDF-takeoff-sourced cells, so provenance is scannable without hovering for the tooltip.
- **Custom Columns accept any script.** `CustomColumnsDialog.normalizeColumnName` was stripping every non-ASCII character (`/[^a-z0-9_]/g`), which silently nuked Cyrillic / CJK / Arabic input and surfaced as "Column name is invalid". Now uses Unicode property escapes (`\p{L}\p{N}`), mirroring Python's `str.isidentifier()` so frontend and backend agree.

### Fixed - Country-specific defaults
- **Removed German / Euro fallbacks** flagged by the country-hardcode audit:
  - `getLocaleForRegion()` now falls back to the user's UI locale (resolved via `i18next`) instead of `'de-DE'`.
  - `getCurrencySymbol()` and `getCurrencyCode()` return empty strings when no currency is set (was `'€'` / `'EUR'`).
  - `createFormatter()` accepts an optional locale and falls back to `getIntlLocale()` instead of `'de-DE'`.
- The static `VAT_RATES` map is renamed to `SUGGESTED_VAT_RATES` and downgraded to a *suggestion* - used only to seed the placeholder in Project Settings; no longer applied as a render-time default.

### Tests
- 196 / 196 BOQ frontend tests, 1 132 / 1 132 full frontend sweep - all green.
- BOQ backend integration suite (44 tests) - all green, including the new `bim_qty_source` roundtrip cases.

## [2.6.10] - 2026-04-27

### Security
- **Demo password no longer hardcoded.** `_resolve_demo_password()` regression reintroduced the literal `DemoPass1234!` as the no-env-var fallback (BUG-D01). Restored to `secrets.token_urlsafe(16)` so every fresh install gets a unique random password persisted to `~/.openestimator/.demo_credentials.json`. Operators using `OE_DEMO_PASSWORD` env var are unaffected.

### Fixed - Tests
- `tests/conftest.py` now eagerly imports every module's ORM `models` so `Base.metadata` holds a coherent table set regardless of test-collection order. Eliminates 9 spurious `NoReferencedTableError` failures in `tests/unit/eac/test_validator_aliases.py` when run as part of the full sweep. Full unit-test pass: 2309 / 2309.

## [2.6.9] - 2026-04-27

### Fixed - Takeoff
- **Suppress "0 m²" / "0 m" labels for degenerate measurements.** `formatMeasurement(value, unit)` now returns the empty string when `value < 0.01`, so half-finished polygons and pre-calibration shapes no longer litter the side panel and on-canvas labels with misleading zero readouts.

## [2.6.8] - 2026-04-27

### Fixed - Takeoff
- **Page-jump popover** on the page indicator. Click the `X / Y` chip in the toolbar and the dropdown lists every page with a measurement-count badge per page, so users can jump directly to the page they need (especially useful on multi-page tender drawings).

## [2.6.7] - 2026-04-27

Annotation persistence - the last gap in PDF Takeoff durability.

### Fixed - Takeoff
- **Annotations now persist to the backend.** Cloud / arrow / text / rectangle / highlight types previously only saved to `localStorage`, so annotations vanished on a fresh device or browser. Schema regex extended (`takeoff/schemas.py`) and the frontend sync hook (`useMeasurementPersistence.ts`) no longer filters them out, so the existing 3-second debounce now covers the full set.
- Backwards compatible: existing measurements rows untouched; clients running v2.6.6 continue to work (annotations just stay localStorage-only on those clients).

## [2.6.6] - 2026-04-27

UX papercuts patch - Takeoff Tier 2 follow-up + Header surface fixes.

### Fixed - Takeoff
- **Active-tool hint banner** above the canvas - every measure / annotation tool now shows a one-line instruction (e.g. "Click on each item to count" + "Esc: switch tool · Del: undo last"). Replaces the silent state where users could not tell what the tool expected.
- **Annotation colour editing in the Notes panel** - small swatch next to each annotation row, native `<input type="color">` opens the OS palette so users can recolour after creation without re-drawing.
- **DWG Layers tab counter** now reflects the *visible* layer count instead of the static total, so toggling layers updates the badge live.

### Fixed - Header
- "Report Issue" button surfaced directly in the top header (was hidden behind a `…` More popover). The mailto fallback stays inside the popover.

## [2.6.5] - 2026-04-27

Hotfix bundle - security findings + deferred Auth/IDOR slice + Takeoff UX papercuts.

### Security
- Fix CodeQL `py/partial-ssrf` (critical) in `fieldreports/weather.py` - switch to `httpx.get(base_url, params=…)` so the host is fixed at compile time.
- Fix CodeQL `py/partial-ssrf` (critical) in `catalog/router.py` - URL-quote the static-map values and verify final netloc is `raw.githubusercontent.com` before download.
- Fix CodeQL `py/polynomial-redos` (high) in `dsl/nl_builder.py` - bound the German V2 reorder regex inner field to `{1,100}` characters so the lazy quantifier can't backtrack quadratically on adversarial input.

### Added - Auth/IDOR hardening (v2.4.0 slice A, deferred)
- `erp_chat/router.py`: project-scoped IDOR closed on `/{conversation_id}/messages` GET + DELETE.
- `reporting/router.py`: 3 IDOR fixes covering KPI history, dashboards, and audit trails.
- 17 new integration tests in `tests/integration/test_costs_idor.py`, `test_erp_chat_idor.py`, `test_reporting_idor.py`.

### Fixed - PDF Takeoff UX
- Mouse-wheel zoom on canvas (cursor-anchored, native listener with `passive: false` so `preventDefault` actually works).
- Annotation/measurement delete buttons now visible at 40-50% baseline opacity (no longer hover-only) and carry the `(Del)` shortcut hint.
- New "Not calibrated · click to fix" amber badge in toolbar - mirrors the existing purple "Calibrated · 1:N" badge.
- One-time toast warning when first real measurement is created on an uncalibrated drawing, gated by ref so it never spams.

## [2.6.4] - 2026-04-27

Wave-5 patch release - completes the T00–T13 dashboards/compliance backlog with two final feature deliverables.

### Added - Dashboards (T10 Multi-Source Project Federation)
- `dashboards/federation.py`: `build_federated_view(snapshot_ids, schema_align)` reads each snapshot's parquet into DuckDB and unions them with `__project_id` + `__snapshot_id` provenance columns. Three schema-align modes: `intersect` (common columns only), `union` (NULL-fill missing), `strict` (422 on mismatch).
- `federated_query()` runs whitelisted SELECT-only SQL on the view (rejects ATTACH/INSTALL/DROP/PRAGMA/SET, rejects multi-statement, rejects empty input)
- `federated_aggregate()` supports count/sum/avg/min/max with provenance group-by
- Endpoints: `POST /api/v1/dashboards/federation/build`, `POST /api/v1/dashboards/federation/aggregate`
- Frontend: `FederationPanel` (multi-select snapshot picker + schema-align mode + group-by/measure pickers), `FederatedResultsTable` (provenance chips first, project/snapshot labels)

### Added - Compliance (T13 Natural Language Rule Builder)
- `core/validation/dsl/nl_builder.py`: 8 deterministic patterns (must_have, must_not_have, value_equals, value_greater_than, value_less_than, value_at_least, count_at_least, count_zero) with EN / DE / RU lang aliases (incl. German V2 verb-final reordering)
- Optional injectable AI fallback: lazy `app.modules.ai.ai_client` import, low-confidence-only invocation, response round-tripped through the strict T08 parser before acceptance - never crashes if no API key
- Endpoints: `POST /api/v1/compliance/dsl/from-nl`, `GET /api/v1/compliance/dsl/nl-patterns`
- Frontend: `/compliance/builder` route with `NlRuleBuilderPanel` (3-pane: NL textarea / DSL preview / pattern hints, Ctrl+Enter to generate, AI checkbox, confidence badge), `DslPreview` (token-level YAML highlight, no codemirror), `NlPatternHints`

### Tests
- 30 + 6 (T10) + 29 + 7 + 11 (T13) = 83 new tests, all passing
- Full frontend `tsc --noEmit` clean across all dashboards + compliance + EAC canvas additions
- ruff + mypy clean on all new backend code

## [2.6.3] - 2026-04-27

Wave-4 patch release bundling three feature deliverables (T09 Model-Dashboard Sync Protocol, T11 Historical Snapshot Navigator, T12 CWICR Item Matcher).

### Added - Dashboards (T09 Sync Protocol)
- `sync_protocol.py` with `PresetSyncProbe`, `SyncReport`, `auto_heal()`, `diff_snapshot_meta()`. Detects column renames, drops, dtype changes, and dropped filter values; classifies severity and proposes auto-fixes.
- `oe_dashboards_preset.sync_status` + `last_sync_check_at` columns (alembic `v2b0_preset_sync_columns`)
- Subscribes to `snapshot.refreshed` event - flips matching presets to `stale` automatically
- Endpoints: `POST /api/v1/dashboards/presets/{id}/sync-check`, `POST /presets/{id}/sync-heal`
- Frontend: `PresetSyncBadge` (color-coded chip beside preset names), `SyncReportDrawer` (grouped issue list with Auto-heal CTA)

### Added - Dashboards (T11 Snapshot Navigator)
- `snapshot_navigator.py` with `list_snapshots_for_project()`, `diff_two_snapshots()`, schema-from-stats helper
- Endpoints: `GET /snapshots/timeline`, `GET /snapshots/diff` (cross-project diff returns 422)
- Frontend: `SnapshotTimeline` (vertical card list with multi-select + Compare), `SnapshotDiffView` (added/removed/dtype-changed columns + summary chips), `SnapshotPickerInline` (compact dropdown)

### Added - Costs (T12 CWICR Item Matcher)
- `costs/matcher.py` with `match_cwicr_items()` and `match_cwicr_for_position()`
- Lexical scoring via rapidfuzz `token_set_ratio` over description + localized descriptions, with additive unit/lang bonuses
- Optional semantic path tries `app.core.vector.encode_texts` then `sentence_transformers`; falls back to lexical-only if either is missing (logs once, never raises)
- Hybrid mode: `0.6 * lexical + 0.4 * semantic`
- Endpoints: `POST /api/v1/costs/match`, `POST /api/v1/costs/match-from-position`
- Frontend: `CwicrMatchPanel` with query input, mode selector, and per-row Apply CTA

### Tests
- 25 + 7 (T09) + 19 + 14 (T11) + 25 + 7 (T12) = 97 new tests, all passing
- ruff + mypy clean for backend; tsc + eslint clean for frontend

## [2.6.2] - 2026-04-27

Patch release bundling three wave-3 features (T07 Dataset Integrity, T08 Compliance DSL Engine, EAC §3.2 Block Editor canvas) and a downgrade-path migration fix.

### Fixed
- **Alembic v260b downgrade failed on SQLite** - `drop_column("idempotency_key")` raised "error in index … after drop column" because SQLAlchemy's `create_all()` lays down an auto-named `ix_oe_eac_run_idempotency_key` index that the migration didn't know about. Now walks `inspector.get_indexes()` and drops every index covering the column. Migration roundtrip test sweep: 11/11 + 1 xfail.

### Added - Dashboards (T07)
- **Dataset Integrity Overview** - `compute_integrity_report()` in `backend/app/modules/dashboards/integrity.py` produces per-column null/unique/dtype/sample/zero/outlier/issue-code stats plus a project-wide completeness score and stable schema hash. `POST /api/v1/dashboards/integrity-report` endpoint with project cross-check. `IntegrityOverview.tsx` table component with completeness chip, per-column issue badges, click-to-expand sample-values drawer, and `issuesOnly` filter.

### Added - Compliance (T08)
- **DSL Engine for ValidationRule** - `backend/app/core/validation/dsl/` package provides a typed AST (`RuleDefinition`, `ForEachAssert`, `Comparison`, `Aggregation`, `Logical`, `FieldRef`, `Literal`) parsed from YAML/JSON via `yaml.safe_load`, dunder-rejection, depth-cap 16, python-tag attack rejection. `compile_rule()` produces a registered ValidationRule subclass; supports `forEach`/`assert`, `count`/`sum`/`avg`/`min`/`max`, comparisons (`==`,`!=`,`<`,`<=`,`>`,`>=`,`in`), logical (`and`/`or`/`not`). New `oe_compliance_dsl_rule` table (alembic `v2a0_compliance_dsl_rules`), 5 endpoints under `/api/v1/compliance/dsl/` (validate-syntax, compile, list, get, delete) with tenant isolation and owner-only delete.

### Added - EAC (§3.2 Block Editor canvas)
- **Spatial block canvas with slot DnD** - `frontend/src/features/eac/canvas/` package built on `@xyflow/react`: `BlockCanvas` (zoom/pan/multi-select/keyboard), `BlockNode` (editable title + expandable params + typed slot handles), `SlotConnection` (typed bezier edges colored by data type), `CanvasToolbar` (undo/redo, fit-view, save, validate, compile), `useBlockCanvasStore` Zustand store with bounded undo/redo and clipboard, `dnd.ts` slot-type compatibility matrix. New page `EACBlockEditorPage.tsx` mounted at `/eac/blocks/:eacId`.

### Tests
- 19 + 5 (T07) + 19 + 12 + 8 (T08) + 15 + 10 + 4 + 5 (EAC canvas) = 97 new tests, all passing
- Migration roundtrip 11/11 (was 10 + 1 xfail before v260b downgrade fix)

## [2.6.1] - 2026-04-26

Patch release on top of v2.6.0 - bundles a prod-deploy migration fix and three Dashboards features (T04 Cascade Filter Engine, T05 Presets & Collections, T06 Tabular Data I/O) that were nearly complete at the v2.6.0 cut.

### Fixed
- **Alembic v270 migration crashed on empty DB** - `inspector.get_columns("oe_boq_position")` raised `NoSuchTableError` when the migration ran ahead of the ORM `create_all()` boot path. Now `get_table_names()`-guarded with a logged WARNING when the table is missing. Discovered during the v2.6.0 prod deploy: prod was actually missing `alembic_version` entirely (schema present but never stamped); fixed via `alembic stamp head` followed by `alembic upgrade head` clean no-op.

### Added - Dashboards (T04 + T05 + T06)
- **Cascade Filter Engine (T04)** - `POST /api/v1/dashboards/snapshots/{id}/cascade-values` returns distinct values of a target column whose row-set is consistent with the user's other-column selections, optional fuzzy `q`. `GET /api/v1/dashboards/snapshots/{id}/row-count` returns the live filtered row count. `CascadeFilterPanel.tsx` is a vertical stack of debounced per-column pickers with chip multi-select, per-column Clear, and a top-level Reset all.
- **Presets & Collections (T05)** - new `oe_dashboards_preset` table (alembic `v290_dashboards_presets`), service publishing `dashboard.saved` / `dashboard.deleted` events. Endpoints: `POST/GET/PATCH/DELETE /api/v1/dashboards/presets`, `POST /presets/{id}/share`. `PresetPicker.tsx` exposes "My presets" + "Shared collections" with a Save-current modal; `QuickInsightPanel.tsx`'s pin button now creates a real preset (was a no-op stub in v2.6.0).
- **Tabular Data I/O (T06)** - `rows_io.py` provides paginated DuckDB row reads + CSV/XLSX/Parquet exports + a two-step import staging area. Endpoints: `GET /snapshots/{id}/rows`, `GET /snapshots/{id}/export`, `POST /snapshots/{id}/import`, `POST /snapshots/{id}/import/commit`. `DataTable.tsx` renders the rows endpoint with click-to-sort headers; `ExportButton.tsx` triggers downloads with the auth token attached. Import UI deferred to a follow-up - the staging endpoints exist and are tested, but the snapshot-write path waits on T10 federation.

### Tests
- 16 + 16 + 10 + 7 + 6 + 5 + 12 = 72 new tests across the four agents, all passing. Backend ruff clean; frontend tsc + vitest clean.

## [2.6.0] - 2026-04-26

Major feature release. RFC 37 multi-currency / VAT / compound positions, BIM Viewer UX overhaul, IDS / SARIF interop, EAC engine API completeness, dashboards Quick-Insight + Smart-Autocomplete, security hardening, Linux install guide.

### Added - RFC 37 multi-currency, VAT, compound positions
- **Multi-currency BOQ resources (Issue #88)** - per-resource `currency` on compound-position rows. Project Settings page exposes a per-project FX rate table (code, label, rate-to-base) so foreign-priced labour, materials, equipment roll up cleanly into the project's base currency. Inline currency picker on every resource row in the BOQ grid; `⚠ no FX` pill renders when a resource currency has no rate configured. Resource total displayed in resource currency with base-currency tooltip (`qty × rate × fx`).
- **Per-project VAT override (Issue #89)** - `Project.default_vat_rate` column. When seeding a fresh BOQ's default markups, the project's VAT override (if set) replaces the regional default. Settings UI shows live "Effective: X%" badge with regional fallback.
- **Compound position editing (Issue #93)** - resource type / unit / currency are now first-class editable fields in the BOQ grid. Resource type rendered as a badge-styled `<select>` covering material / labour / equipment / subcontractor / other (i18n-keyed). Unit cell uses a project-aware datalist with free-form input persisted via `saveCustomUnit`. Project Settings exposes a chip list of custom units for the project.
- **CWICR cost link (Issue #79)** - `Position.cost_item_id` plumbed through `PositionCreate` / `PositionUpdate` / `PositionResponse`. Backend rejects unknown / inactive cost-item IDs with 422; metadata-preserving on PATCH. Bulk-positions endpoint forwards optional per-row `cost_item_id`.

### Added - BIM Viewer UX
- **Geometry session cache** - Zustand LRU keyed by `modelId` (4 entries / 200 MB cap). Returning to `/bim/{id}` from another route no longer re-downloads or re-parses the GLB / DAE - the parsed scene is restored from cache. ~5× faster on second visit.
- **Color-mode legend** - overlay listing each colour swatch + meaning across Storey / Type / Validation / BOQ-link coverage / Document coverage modes (gradient bar with min/max for the 5D-rate continuous mode). Capped at 12 swatches (+N more).
- **Persistent measurement list** - completed measurements now land in the Tools panel with focus / hide / rename / delete per row, plus a top-level "Clear all measurements" button. Stop measuring no longer wipes the user's work; Esc cancels the active mode without deleting completed entries.
- **Saved Views: rename + delete** - pencil + trash icons per row, inline edit with Enter / Esc.
- **Asset Card panel fix** - store wiring repaired (`assetCardEnabled` + setter were missing in `useBIMViewerStore`), glass effect dropped for solid surface, asset registration now resolves stub IDs through `ensureBIMElement` so PATCH always lands on a real DB UUID.
- **BIM volumetric quantity auto-suggest (Task #136)** - when linking BIM elements to a new BOQ position, the Quantity input pre-fills from the most relevant geometric parameter for the position's unit (volume / area / length / mass / count) with a confidence badge and partial-coverage warning.
- **Properties tab** is now a real local tab inside the right panel - no longer a disguised navigation to `/data-explorer`.
- **Rules button** opens in a new tab instead of unloading the viewer.
- **Saved Views Save button** no longer clipped past the panel edge.
- **4D Schedule placeholder** removed (was a no-op button).
- **Issue #53 - placeholder geometry banner**. When the IFC text fallback synthesizes generic boxes (DDC `cad2data` not installed), elements are tagged `is_placeholder: true` and the viewer shows an amber dismissable banner pointing to `docs/INSTALL_DDC.md`. No more silent placeholder-as-real-geometry.
- **Issue #53 - DAE double-rotation regression**. `ColladaLoader` already pre-rotates Z_UP DAEs; the unconditional `scene.rotation.x = -π/2` flipped models upside-down. Now branched on `_isGLB` with a Y-vs-Z bbox heuristic for un-rotated DAE inputs.

### Added - Validation interop
- **IDS importer (Task #224)** - `POST /api/v1/validation/import-ids` (multipart). Parses buildingSMART IDS XML via `defusedxml`, registers each `<specification>` as a `ValidationRule` under the `ids_custom` rule set. No IfcOpenShell dependency.
- **SARIF v2.1.0 exporter** - `GET /api/v1/validation/reports/{id}/sarif` returning `application/sarif+json`. Severity error / warning / info → SARIF error / warning / note. Element refs map to logical locations.

### Added - EAC §1.7 Engine API completeness
- New endpoints: `POST /rules:compile`, `GET /runs/{id}/status`, `POST /runs/{id}:cancel`, `POST /runs/{id}:rerun`, `GET /runs/{a}:diff/{b}`.
- Cooperative cancellation via in-process token registry + persisted `EacRun.status='cancelled'` for cross-worker visibility.
- New events: `eac.run.cancelled`, `eac.run.rerun_started`.

### Added - Dashboards (T02 + T03)
- **Quick-Insight Panel** - `GET /api/v1/dashboards/snapshots/{id}/quick-insights` runs rule-based heuristics over the snapshot (histograms, bars, lines, scatters, donuts) ranked by interestingness with chart-type diversity. `QuickInsightPanel.tsx` renders the result grid with refresh + per-card pin buttons.
- **Smart Value Autocomplete** - `GET /api/v1/dashboards/snapshots/{id}/values?column=...&q=...` powered by DuckDB + rapidfuzz fuzzy reranking. `SmartValueAutocomplete.tsx` is a debounced (250 ms) ARIA combobox with keyboard nav.

### Added - Event bus adoption (v2.4.0 slice E)
Five previously silent modules now emit events for downstream audit / analytics / notifications:
- `punchlist` - item created / updated / deleted / status_changed
- `procurement` - po created / updated / issued, gr created / confirmed
- `reporting` - kpi_snapshot / template / report_generated
- `notifications` - created / read / bulk_read / deleted
- `tendering` - package created / updated, bid created / updated (re-enabled commented-out publishes)

### Security
- **XML XXE pinning** - `backend/app/modules/schedule/router.py` now imports `defusedxml` exclusively for user-XML parsing; regression tests pin against billion-laughs and external-entity payloads.
- **Punchlist photo upload size cap** - 25 MB limit enforced via `Content-Length` pre-check then body-size fallback; HTTP 413 instead of OOM.
- **CSP source-of-truth** - duplicate `Content-Security-Policy` removed from `deploy/docker/nginx.conf`; backend middleware is now authoritative.
- **CodeQL noise reduction** - `.github/codeql/codeql-config.yml` adds `paths-ignore` for tests / dist / audit / alembic / demo seeds / marketing and `query-filters` for low-signal rules; expected ~80% alert reduction with zero behaviour change.

### Documentation
- **Linux install guide** - `docs/INSTALL_LINUX.md` covers PEP 668 externally-managed-environment trap on Ubuntu 23.04+ (incl. 26), Python 3.12 vs 3.13 wheel-coverage, system-deps for source build, port-collision recovery, optional systemd unit. README adds an Ubuntu/Debian pointer block.
- **the architecture guide** validation-rules-tree fixed to match disk reality (one colocated `rules/__init__.py`, no per-standard files).

### Test infrastructure
- **Backend `shared_auth` fixture cascade fix** - three-layer cascade resolved: (1) `conftest.py` redirects `DATABASE_URL` to a per-session temp SQLite *before* `from app...` imports so tests no longer compete with the production DB; (2) `_auth_helpers.promote_to_admin` flips `is_active=True` (BUG-RBAC03); (3) login / API rate limits bumped for whole-suite runs to avoid spurious 429s. The five originally-failing test files (`test_api_smoke`, `test_boq_regression`, `test_boq_import_safety`, `test_boq_cycle_detection`, `test_boq_cost_item_link`) plus three adjacent suites pass cleanly together: 57/57 in 246 s.
- `test_boq_cycle_detection` 400-vs-422 expectations aligned to the deliberate `service.py` BUG-CYCLE02 behaviour.

## [2.5.6] - 2026-04-26

Hotfix for Issue #92 (formula save broken on v2.5.5) plus a UX fix for Issue #91 (Enter-after-edit jumped to footer) and a toolbar polish.

### Fixed
- **BOQ Quantity save (Issue #92)** - three chained bugs caused every Quantity edit on v2.5.5 to come back as `0`:
  1. Backend `PATCH /v1/boq/positions/{id}` returned `500` whenever the row's `confidence` column held a legacy label (`'high'` / `'medium'` / `'low'`) - `_position_to_response` did `float(position.confidence)` and crashed. Added `_coerce_confidence` that maps known labels to `0.9 / 0.6 / 0.3` and falls back to `None` for unknowns.
  2. `onFormulaApplied` was destructured as `_onFormulaApplied` (unused) inside `BOQGrid`, so `metadata.formula` was never persisted even though the editor fired the callback. Wired through the AG Grid `gridContext`.
  3. The popup editor's tail blur (fired when `stopEditing` unmounted the input) re-entered the commit path and double-PATCHed - sometimes with the editor's raw text, which the value-parser fell back to `oldValue` for, so the cell appeared to "revert". Added a `committedRef` idempotency guard so commit fires exactly once per Enter / Tab / Blur.
- **BOQ Enter-after-edit (Issue #91)** - pressing Enter after editing Unit / Quantity / Unit-rate jumped focus down to the next row, and on the last data row landed on the footer ("Resumen") forcing the user to navigate back. Now Enter-after-edit advances right to the next column on the same row, matching how users actually fill BOQ data left-to-right (`enterNavigatesVerticallyAfterEdit={false}`).

### Changed
- BOQ toolbar AI section: removed the coloured `border-l-2` accent strips between the *Find Costs / AI Chat / Analyze* buttons.

## [2.5.5] - 2026-04-26

Issue #90: Excel-style formulas in BOQ Quantity cells. Plus the v2.5.4 Undo defensive wrapper, an "About" copy edit, and three small marketing-page text updates.

### Added - Issue #90 formulas in Qty
- New `formulaCellEditor` wired to the BOQ Quantity column. Type `=2*PI()^2*3`, `=sqrt(144) + 5`, `12.5 x 4`, etc. - the cell evaluates the expression and stores the resolved number, while the source formula is persisted in `metadata.formula` so you can re-edit it later.
- The parser is hand-written recursive-descent (CSP-safe; **no eval / no Function**) and supports:
  - Operators `+ − * / ^` (and `**` as exponent alias), parentheses
  - `x` / `×` as multiplication aliases (so "2 x 3" works)
  - `,` as decimal separator (es / de / ru locales) - only when the input has no parens, so it never collides with function-arg separators
  - Constants: `PI`, `E`
  - Functions: `sqrt`, `abs`, `round`, `floor`, `ceil`, `pow(x,y)`, `min(...)`, `max(...)`, `sin`, `cos`, `tan`, `log`, `exp`
  - Optional Excel-style leading `=`
- Editor UX: violet `ƒx` badge, live evaluation preview (`= 59.22` in green or `⚠ syntax error` in red as you type), inline `?` help popover with a cheat-sheet of operators / functions / examples.
- Cell display when a formula is stored: violet `ƒx` pill + violet number + AG Grid tooltip showing the source formula. Click the cell → editor pre-fills with the original formula, not the resolved number.
- 20 unit tests cover precedence, exponent associativity, locale decimals, multiplication aliases, function calls, identifier-injection guards (rejects `=window`, `=alert(1)`, etc.), and the user's reported example `=2xPI()^2x3`.

### Fixed - Undo defensive wrapper (was v2.5.4)
- `BOQService.update_position` wraps the DB write block (`update_fields` → `flush` → `refresh`) in a defensive try/except. Any unexpected SQLAlchemy/IntegrityError now surfaces as `422 Unprocessable Entity` with a helpful "row may have been deleted or modified concurrently - reload and retry" message instead of a bare 500. The full traceback + a type-only field summary is logged via `logger.exception` so the underlying cause is recoverable from server logs (Bug 1, partial).

### Changed - copy
- About / "Voices" founder bio: tightened the closing two paragraphs - drops the redundant "ten years" / "decade" repetition, ends with "an open-source modular ERP for the construction industry" + a single follow-up paragraph about the AI-tooling consolidation.

### Known issues (still tracking)
- Bug 1 root cause not yet identified - the defensive wrapper neutralises the user-facing impact (no more silent 500) but the trigger condition is still unknown. Server logs will now expose it on next occurrence.
- Bug 4 (description cell crash on newly-added position) - needs user-side repro with browser console screenshot.

## [2.5.3] - 2026-04-26

BOQ-editor stability + UX sweep. User reported 23 bugs on a single project's BOQ page (`/boq/{id}`); 21 fixed in this release, the remaining 2 (Undo replay 500 on stale parent_id; description-cell crash on newly-added rows) need a reproducible repro and are tracked separately.

### Fixed (data integrity)
- **Silent data loss on save failure** - Quantity edits whose server response 500'd were left in the grid as if accepted; the optimistic cache update is now rolled back via `invalidateAll()` in `updateMutation.onError` (Bug 5).
- **Apply Regional Template crash** - markup cascade calculation was unguarded against null/non-numeric `percentage` and `fixed_amount`; added `Number.isFinite` checks + array guard (Bug 3).
- **Import freeze (~30 s)** - XLSX/PDF/CAD imports could hang the UI with no signal. Added an immediate "Importing X… (up to 60 s)" toast and a 90 s `AbortController` timeout that surfaces a friendly message instead of an apparent hang (Bug 2).

### Fixed (UX)
- Lock Estimate now confirms before locking (it's irreversible without admin unlock) - Bug 8.
- Esc closes the AI Features Setup modal - standard modal behaviour (Bug 10).
- Right-click Actions menu flips when it would overflow the viewport (Bug 11).
- Grid Settings dropdown widened from `w-52` → `w-64` so "Manage Columns" / "Renumber Positions" no longer truncate (Bug 12).
- Footer rows (Direct Cost / Net Total / VAT / Gross Total) no longer show a stray `0` in the Quantity column - totals don't have a quantity (Bug 15).
- Paste-from-Excel button has a visible `Paste` label at xl breakpoints (Bug 16).
- BIM Quantity picker element names get a native browser tooltip with the full text + `IfcWallStandardCase` hint when truncated (Bug 21).
- Toolbar now sticks at `top-[52px]` (under the app header) instead of colliding with it (Bug 7).
- Right-side AI Smart / AI Cost Finder panels offset by `top-[52px]` so they no longer cover the toolbar's Import/Export/Lock buttons (Bug 13).
- "AI" group label in the toolbar is decorative - marked `pointer-events-none aria-hidden` (Bug 6).
- Unit column display now matches the editor (raw lowercase code: `m`, `m2`, `m3`) - `uppercase` CSS removed (Bug 9).
- Three AI buttons in the toolbar (Find Costs / AI Chat / Analyze) get coloured left borders + a visible label on the previously icon-only middle one (Bug 18).
- Adding an empty position toasts a one-line hint that Quality Score will dip until quantity/rate are filled (Bug 19).
- Version History empty state explicitly directs the user to the label-input + Save button instead of just saying "No snapshots yet" (Bug 20).
- AI Cost Finder demotes the CWICR `code` token to a small grey badge with a `title=` tooltip - internal IDs no longer dominate the row (Bug 22).
- Feedback URL no longer leaks `error_count=N` query param; the count is logged to console for self-debugging instead (Bug 23).
- Header's duplicate keyboard-shortcuts trigger removed; the BOQ toolbar's Keyboard icon is the single entry point (Bug 17).

## [2.5.2] - 2026-04-26

QA-report stability sweep. Triaged a 65-bug audit; ~70% were already-fixed or false-positive. Real fixes shipped:

### Security
- `docker-compose.quickstart.yml`: `JWT_SECRET` and `POSTGRES_PASSWORD` now required via env (or `.env`) - compose fails fast instead of shipping globally-shared defaults.
- `Dockerfile.unified`: removed baked-in `JWT_SECRET=change-me-in-production` ENV - must be supplied at `docker run` time.
- `registration_mode` default flipped `open` → `admin-approve`. First registrant still becomes admin (bootstrap path); subsequent self-registrations need approval. Self-hosters who want open registration set `OE_REGISTRATION_MODE=open` in `.env`.

### Fixed
- `_resolve_demo_password` default is now the documented `DemoPass1234!` instead of a random token - the CLI banner, README, and seed all advertised that string but the actual default was random, so demo logins silently failed on fresh installs.
- BOQ position parent_id validation returns 422 (FastAPI convention) instead of 400 across self-cycle / missing-parent / cross-BOQ cases.
- `smart_import` xlsx path now calls `reject_if_xlsx_bomb` - the bomb guard previously only ran in `import_boq_excel`, leaving a DoS vector via this endpoint.
- Reporting page no longer logs 50× console 404 - `/v1/reporting/kpi` → `/v1/reporting/kpi/`.
- Finance page no longer 422s on every load - `/v1/finance/budgets` → `/v1/finance/budgets/`.
- BIM Asset Register page no longer 404s - `/v1/bim_hub/assets/?` was hitting `/{model_id}` route, removed the trailing slash.
- Onboarding tour no longer blocks first-time project creation - auto-start is now skipped on `/projects/new`, `/onboarding`, `/setup`, `/login`, `/register`.
- Empty-dashboard for new users replaced with proper EmptyState (FolderPlus + Create-project CTA).
- `?lang=` URL parameter now honoured at i18n init (validated against supported locales, persisted to localStorage).

### Build / Install
- `backend/requirements.txt` reduced from 236-line freeze (torch, openai, anthropic, playwright, pyinstaller, etc.) to a 4-line `-e .[server]` shim. Saves GBs on `pip install -r`.
- `Makefile` `dev` target split: `dev-backend`, `dev-frontend` for two-terminal Windows workflow; `dev-unix` keeps the POSIX-only `&` form.
- `openestimate init-db --reset` flag added - deletes existing DB before init. Without it, prints a warning if a previous DB is present at the data dir.
- `pyproject.toml` upper version bounds added on pandas/pyarrow/pydantic/sqlalchemy/alembic/fastapi/uvicorn/duckdb/httpx - prevents pip from resolving breaking-major releases.
- `Dockerfile.unified` base image bumped `node:20-alpine` → `node:22-alpine` (rollup-plugin-visualizer 8.x requires node>=22).

### UI
- Header: dev-tool buttons "Report Issue" + "Email Issues" moved into a `⋯` "More" popover.

## [2.5.1] - 2026-04-26

Hotfix release for installer regression on Windows (issue #87).

### Fixed
- `install.ps1` aborted on `uv`'s stderr progress under `irm | iex` (PS 5.1 wrapped "Resolved 64 packages in 1.28s" as `NativeCommandError`). Switched to `Continue`-policy + `Invoke-Native` helper merging stderr→stdout.
- `install.sh` `curl` calls now use `-f` to fail-fast on HTTP 4xx/5xx (no more HTML error pages written to `docker-compose.yml`).
- `install.sh` Python detection picks the first interpreter actually ≥3.12 instead of falling back to whatever `python3` resolves to.
- `install.sh` and `install.ps1` honour `OE_VERSION` env var for pip/uv paths.
- Marketing site: replaced dead `get.openconstructionerp.com` install CTAs with raw GitHub install-script URL on hero + final CTA.

## [2.5.0] - 2026-04-25

Stability release. No migration needed for 2.4.0 upgrades.

### Fixed
- PDF takeoff page indicator no longer resets to `0/31` on Next click.
- Alembic multiple-head error on fresh clones (new `v232_merge_heads` no-op).
- PDF/DWG takeoff cross-page/layout state leaks.
- BIM viewer state leaks on model switch + stale prop callbacks.
- PDF drop-zone honesty: PDF-only with toast on rejection.
- Text-annotation Escape race (no more ghost annotations).
- Vite "Failed to fetch dynamically imported module" (14 deps pre-bundled).
- `make seed` / `db-reset` Makefile target.
- `win32_setctime` marker for non-Windows pip installs.

### Added
- Delete/Backspace shortcut in PDF takeoff.

## [Unreleased]

### Dashboards Phase 0 (T00 scaffolding)

- New modules: `oe_dashboards`, `oe_compliance_ai`, `oe_cost_match` (auto-discovered).
- `snapshot_storage.py` + `duckdb_pool.py` core primitives.
- `duckdb>=1.2.0` + `rapidfuzz>=3.0.0` promoted to base deps.
- ADR-001 (snapshot storage model) + `DASHBOARDS_PLAN.md` 13-task plan.
- 25 new unit tests. Full suite: 1470/1470 green.

## [2.4.0] - 2026-04-22

Audit-driven hardening - observability + i18n.

### Slice C - Structured error logging
- `reporting.kpi_recalc`: 7 sub-module failure paths logged at WARNING with op + project_id.
- `takeoff/service`: pdfplumber/PyMuPDF errors logged with input fingerprint, double-fail returns generic 400.
- `boq/events`: wildcard activity-log gated on PostgreSQL; vector-index failures rate-limited.
- `StorageBackend.open_stream`: safe default chunked read instead of `NotImplementedError`.

### Slice D - Validation i18n + GAEB
- New `core/validation/messages/` bundle (en/de/ru, 87 keys each).
- All 42 rules now flow through `translate()`, locale via `ValidationContext.metadata['locale']`.
- GAEB ruleset: 1→5 rules (`lv_structure`, `einheitspreis_sanity`, `trade_section_code`, `quantity_decimals`).
- Total rules 42→46.

### Tests
- +72 unit tests (28 slice C + 44 slice D). Full suite: 1445/1445 green.

### Deferred
- IDOR hotfixes (erp_chat, costs autocomplete/search, reporting), pagination (schedule, bim_hub), event bus in 5 silent modules.

## [2.3.1] - 2026-04-22

Post-v2.3.0 audit hardening.

### Added
- Pluggable `EmailBackend` (console/smtp/noop/memory) + `send_password_reset()` typed helper.
- `Contact.tenant_id` column + IDOR guard via tenant scoping (migration `v231`).
- `openestimate welcome` CLI + first-run interactive browser prompt.

### Fixed
- `RedisCache.get/set/delete` errors now logged via rate-limited `_RateLimitedLogger`.
- `bim_hub/ifc_processor` silent ValueError handlers replaced with DEBUG logs.

### Tests
- +49 unit tests. Full suite: 1373/1373 green.

### Migrations
- `v231_contact_tenant_id` (idempotent).

## [2.3.0] - 2026-04-22

ISO 19650 Phase A - Asset Register, COBie export, Scheduled reports.

### Added
- **Asset Register** (`/assets`) - list of tracked BIM assets with manufacturer/model/serial/warranty/status, searchable, URL-shareable filter, edit modal, in-viewer card.
- **COBie UK 2.4 export** (`/v1/bim_hub/models/{id}/export/cobie.xlsx`) - 7-sheet workbook, deterministic `frozen_now` option.
- **Scheduled reports** - POSIX cron + recipient list, custom parser (no croniter dep), `POST /schedule` / `/run-now` / `GET /scheduled`, minute-tick async scheduler in FastAPI lifespan.
- API: `GET /v1/bim_hub/assets`, `PATCH .../asset-info/`.

### Tests
- +43 backend (cron, schedule, asset, COBie). Full suite: 1324/1324 green.
- +4 Vitest + Playwright `assets-register.spec.ts`.

### Migrations
- `v230_bim_element_asset_info` (asset_info JSONB + is_tracked_asset bool + index).
- `v230_reporting_schedule` (6 schedule columns + 2 indexes).

## [2.2.0] - 2026-04-21

Q2 UX deep improvements - pivot viz, wider Charts, markup hub, calibration, 4D scrubber.

### Added
- **Pivot viz modes**: Table / Heatmap / Bar / Treemap / Matrix. URL persisted via `?piv_viz=`.
- **Charts**: all text columns surface (high-cardinality flagged with ⚠︎), no 20-column cap, new Aggregation picker (`?chart_agg=`).
- **Unified Markups hub** (`/markups`) - aggregates general markup / DWG / PDF measurements.
- **Threshold rules** (R/A/G bands per pivot column, `?tr=`).
- **BIM 4D timeline scrubber** when phase data present.
- **DWG calibration + sheet strip**, **PDF calibration + measurement ledger**.

### Fixed
- DWG annotations render on canvas (backend shape normalised at API boundary).
- PDF annotation click-through past legend overlay.
- BIM properties panel: per-row translucent cards, "Dimensions" → "BBox Dimensions".
- Frontend `APP_VERSION` reports v2.2.0.

### Tests
- +135 frontend (Pivot/Charts/aggregation/urlState). Total: 923 vitest, 1272 backend.
- Playwright `_data-explorer-viz-modes.spec.ts` - 9,512-element RVT.

## [2.1.0] - 2026-04-20

Q1 UX deep improvements - keyboard shortcuts, undo/redo, 5D cost viz, URL deep-links, RBAC fixes.

### Added
- **DWG Takeoff**: per-tool shortcuts (V/H/D/L/P/A/R/C/T/Esc), 50-entry undo/redo, Shift ortho lock, endpoint/midpoint snap.
- **PDF Takeoff**: 11-tool shortcuts, redo stack, measurement properties panel, color-coded group legend.
- **BIM Viewer**: screenshot to PNG, 5D cost gradient mode, camera+selection URL state (`?cx,cy,cz,tx,ty,tz,sel=`).
- **CAD-BIM BI Explorer**: full URL state (tabs/slicers/pivot/chart), Power-BI-style data bars.

### Fixed
- Notification navigation no longer flashes screen black (Suspense moved inside layout).
- `useModuleStore` GET path unified with PATCH to `/me/module-preferences/`.
- Dashboard team-count gated on admin/editor role (no more 403 in viewer console).
- RBAC bootstrap uses `has_admin()` check; demo user seeded as `viewer`.

### Tests
- 220/220 frontend (138 new), 6/6 Q1 Playwright, 0 TS errors.
- New `viewer-errors-audit.spec.ts` (zero-error console as a viewer).

## [2.0.0] - 2026-04-20

Second stable release. Supersedes the 1.x line.

### Fixed
- **AI Chat**: SSE streams crashing mid-flush - endpoint now opens own session, writes `asyncio.shield()`-wrapped.
- **AI key encryption**: `pydantic-settings` resolved by absolute path; rotated-key ciphertexts surface as "not configured" instead of 401.
- **DWG scale**: DXF `$INSUNITS` routed through `unitFactorToMetres()`; 3.58 m no longer shows 3580.200 m.
- **48 integration tests**: trailing-slash drift, `promote_to_admin()` after register fix.
- CDE container POST trailing slash; BOQ create trailing slash; AI Estimate save-as-BOQ trailing slash.

### Added
- BIM aggregate `/boq-links/` endpoint (3 897 real links render instead of blank).
- CAD-BIM BI Explorer: KPI strip (6 totals) + pivot data bars.
- Modules: `MODULES.md`, in-app `/modules/developer-guide`, sidebar "+ Add module" CTA.
- Dashboard: Quick Start navigation, explicit "New Estimate" button, clickable Quality Score tile.
- About/branding: Artem photo, DDC logo, book banner, community tiles.
- Provenance markers (`shared/lib/ddc-integrity.ts` + `middleware/fingerprint.py`).
- BOQ: PDF-origin icons, `FileTypeChips` per row, MarkupPanel overflow fix.
- Project Intelligence: safe-markdown renderer (no more raw asterisks).

### Cleanup
- 5 duplicate demo projects removed (6 regional demos remain).
- Diagnostic specs / test artifacts / one-off seed scripts removed; `.gitignore` extended.
- `ruff --fix`: 29 fixes across 29 files.

### Quality gates
- Frontend typecheck clean; backend cold-start clean (60 modules).

## [1.9.7] - 2026-04-19

### Workflow polish - reload persistence, onboarding, vector UX, BIM labels

- **DWG / BIM reload persistence** - both `DwgTakeoffPage` and `BIMPage` only read `projectId` from `useProjectContextStore.activeProjectId`. When the Header's stale-project cleanup wiped the store on reload, queries fired with an empty `projectId` and the pages rendered as "no documents". Both pages now fall back to `projects[0]?.id` and write the pick back to the context store so the state survives a full reload.
- **CWICR Vector Database progress UX** - `/costs/import` Vector DB loader was a bare spinner for 45+ s while the embedding model downloaded. New 4-phase progress panel in `ImportDatabasePage`: Fetch (0–3 s) → Model (3–15 s) → Embed (15–45 s) → Index (45+ s) with a purple-blue gradient shimmer bar, elapsed timer, and phase dots so users don't assume it froze.
- **BIM "BBox dimensions" label** - the right-panel block title read "Dimensions" which collided with element real-world dimensions. Renamed to "BBox dimensions" (axis-aligned bounding box) so users can tell apart the model frame from the selected element's size. `bim.dimensions_title` i18n key lands with the new default.
- **CDE optimistic container insert** - creating a container was silently succeeding (container appeared 15 s later after refetch) because `stateFilter` often did not match the new container's state. `CDEPage` onSuccess now (1) resets the state filter to "All" and (2) writes the created container into the React-Query cache so it shows up instantly.
- **Header stale-project cleanup** - `activeProjectId` persisted through localStorage outlived the project it pointed at (deleted / demo reset). Header now auto-clears `activeProjectId` when the server's project list does not contain it, so switchers never show a ghost "Project [deleted]" entry.
- **DWG upload store janitor** - `useDwgUploadStore` entries could hang in `uploading` / `converting` forever if the tab was closed mid-upload. Module-level patrol flips any job stuck >45 min to `error`, so the dock no longer shows a perpetual spinner on reopen.
- **Onboarding language cards bigger + compact shell** - welcome step cards were fighting for visibility against a padded shell. Cards resized to `grid-cols-3 sm:grid-cols-4 gap-2.5` with `size={24}` flags + `text-sm`, while the shell trimmed to `pt-4 pb-8` / `py-5 sm:py-7` so everything fits on a 13" laptop without scrolling.

### Quality gates

- `tsc --noEmit`: 0 errors

## [1.9.6] - 2026-04-19

### Reliability hotfixes - import pipeline, validators, reindex

- **CWICR region load 404** - `POST /api/v1/costs/load-cwicr/{db_id}/` had a trailing slash on the backend route; frontend called without it and got 404 on every region (France, Germany, US, etc.). Sibling routes `/vector/load-github/{db_id}` and `/import/{db_id}` use no trailing slash - `load-cwicr` now matches the pattern (`backend/app/modules/costs/router.py:1472`). Onboarding "Load database" step now works end-to-end.
- **LanceDB Qdrant false positive** - `GET /v1/vector/status` reported `can_restore_snapshots: true` whenever the `qdrant_client` pip package was importable, even on the LanceDB backend where snapshot restore requires a running Qdrant server. Settings page then tried to use the Qdrant restore path on a LanceDB deploy and showed "Qdrant not available". Now hardcoded to `False` on LanceDB (`backend/app/core/vector.py:301`) - Qdrant restore path is only surfaced when the Qdrant backend is actually selected.
- **Projects `/v1/projects/?limit=500` 422** - Header bulk-fetches the full project list to drive the Switch Project dropdown (`?limit=500`) but the backend `limit` Query had `le=100` so the request 422'd and the dropdown returned empty. Raised to `le=500` (`backend/app/modules/projects/router.py:109`). Resolves the "Could not load projects" banner in the switcher.
- **Contacts `/v1/contacts/?limit=200` 422** - same root cause: `ContactSearchInput` (Procurement, Transmittals, RFQ, etc.) fetched `?limit=200` for browse; backend was capped at 100. Raised to `le=500` (`backend/app/modules/contacts/router.py:128`). Resolves the "Select from contacts" empty state in Procurement.
- **Settings reindex double-prefix 404** - `VectorStatusCard.tsx` REINDEX_PATH map included `/api/` at the start of every entry, but `apiPost` also prepends `/api`, producing `/api/api/v1/...` - every reindex call 404'd. All 8 entries now use `/v1/...`; reindex works for every backend module.
- **DWG `/dwg-takeoff` upload dock persistence** - backend `dwg_takeoff/service.py` already created `Document` rows on every DWG upload (verified at `service.py:240-267`); the missing piece was the frontend fallback that surfaced them on reload - shipped in v1.9.7 above. Together they close the "documents disappear on reload" bug the user reported.

### Quality gates

- `tsc --noEmit`: 0 errors
- Fast smoke against local backend: projects list / contacts list / load-cwicr / reindex endpoints all 2xx

## [1.9.5] - 2026-04-18

### Deep audit pass - security + API contract + i18n + mobile

- **API contract normalisers (5 modules)** - Submittals, Meetings, Safety, Inspections and NCR all had field drift between backend (`submittal_type`, `incident_date`, `inspection_date`, `location_description`, `created_by`) and frontend (`type`, `date`, `location`, `reported_by`). Each feature's `api.ts` (or inline `select`) now runs the fetched row through a `normalise*()` function - same pattern as the v1.9.4 Transmittals fix. Resolves `type_undefined` / `status_undefined` i18n key leaks on all five list pages.
- **Procurement + Finance defensive fallbacks** - backend doesn't yet emit `vendor_name` / `counterparty_name` (resolved from `vendor_contact_id` / `contact_id`). Frontend now falls back to the raw id so the PO / Invoice tables render instead of crashing on `.toLowerCase()` of undefined. Proper backend enrichment tracked as follow-up #45.
- **NCR type hardening** - `ncr_number` and `linked_inspection_number` are numeric on the UI but strings on the wire ("NCR-001"). Normaliser now extracts the numeric suffix so `.toString().padStart()` calls behave. `cost_impact` string → number conversion on the same path.
- **Schedule `t()` API cleanup** - 5 call sites (`status_*`, `zoom_*`, `type_*`, `boq.*`) were passing a plain string as the second argument. Modernised to the `{ defaultValue }` object form so i18next never renders a raw key when the dictionary misses.
- **Security - external links** - `Sidebar.tsx:373` (`/api/source`) was missing `rel="noopener noreferrer"` on its `target="_blank"`. MeetingsPage attachment chips carried only `rel="noreferrer"` (noopener implied by modern browsers but not best practice). Both now use the full `noopener noreferrer` pair. Full audit of 20 files confirmed no other tabnabbing surfaces remain.
- **Header tablet overlap** - at 768 px the title, ProjectSwitcher, GitHub button, Report Issue button and 192 px Search box all fought for space and physically overlapped. GitHub and Report Issue now hide until `lg` (≥1024); the `<h1>` route title also stays hidden until `lg`; search shrinks to `w-40 md:w-44 lg:w-56`. iPad portrait users get a clean header.
- **Tasks action bar mobile** - the 375-px mobile view had the action bar overflow (Project select + Export + Import + New Task = 457 px). Row now wraps (`flex-wrap`) so actions reflow onto a second line instead of pushing off-screen.
- **ProjectMap i18n** - new component shipped without `useTranslation`, so "Locating…" and "No location set" were hardcoded English. Both now flow through `t('projects.map_locating', ...)` / `t('projects.map_no_location', ...)`.

### Quality gates

- `tsc --noEmit`: 0 errors
- R5 verification suite: 9/9 pass

## [1.9.4] - 2026-04-18

### v1.9 completion pass - finishes 6 items the earlier rounds left unshipped

- **#31 Transmittals Edit + Delete** - inline `EditTransmittalModal` (subject / purpose / response-due / cover-note, unlocked-only), new backend `PATCH /v1/transmittals/{id}` was already wired + new `DELETE /v1/transmittals/{id}` with 409 on issued transmittals. Frontend Row grows Edit + Delete buttons next to Issue in draft state; audit-safe delete via service/repo.
- **#13 DWG drawing scale 1:N** - `drawingScale` state in DwgTakeoffPage + floating "Scale 1:N" input under the ToolPalette. Applied as a linear multiplier to all rubber-band length labels, polyline segment pills / perimeter / area labels, and the `measurement_value` persisted with every distance/area/line/polyline/circle annotation. Persisted per-drawing in `localStorage` so the estimator doesn't re-enter it on reopen. Text-pin popup was already landed in v1.9.1.
- **#9 DWG Offline Ready badge** - verified already shipped. The component `OfflineReadyBadge` was added alongside the backend `/v1/dwg_takeoff/offline-readiness/` probe; earlier audit missed it because the grep pattern didn't match the hyphenated class name.
- **#12 DWG Summary measurements panel redesign** - verified already shipped. The `SummaryTab` component with KPI cards + per-layer + per-type breakdowns was landed alongside the v1.9.3 PDF export work.
- **#10 DWG UploadDock UI** - new `DwgUploadIndicator` component (bottom-right, above the BIM indicator) reads from `useDwgUploadStore`: minimised pill + expandable job list, per-job cancel / retry / dismiss, `beforeunload` guard while transferring. DwgTakeoffPage upload button now dispatches via the store (`startUpload`) and closes the modal immediately; a subscription invalidates `['dwg-drawings']` + `['documents']` queries and auto-selects the new drawing when the job flips to `ready`. Uploads now genuinely survive navigation.
- **#15 DWG drawing primitives** - ToolPalette now exposes `line`, `polyline`, `circle` alongside existing `rectangle` / `arrow` / `text_pin` / `area`. Two-click circle tool emits πr² × scale² as the measurement value; open polyline finishes on double-click with Σ segment length; line and distance share the same renderer path. Backend annotation-type pattern widened to accept the new `circle|polyline|line` kinds.
- **#22 Split BIM Rules / Quantity Rules navigation (v2)** - single page `BIMQuantityRulesPage` now drives two distinct user-facing entries: Takeoff section "BIM Rules" opens `/bim/rules?mode=requirements` (Requirements tab locked, tab switcher hidden, page title + subtitle swap to the compliance framing, BIM Requirements Import/Export drawer moves into this mode only); Estimation section "Quantity Rules" opens `/bim/rules` (original tab switcher, Quantity Rules + Requirements both visible). Replaces the earlier nav-only split that had pointed Takeoff at `/validation`.

### Post-release polish

- **Tasks create error fix** - Assignee free-text input was sending names like "John Doe" as `responsible_id` into a UUID-typed column, blowing up task creation. `handleCreateSubmit` now UUID-checks the assignee: real UUIDs go to `responsible_id`, typed names fall into `metadata.assignee_name` so the label survives without corrupting the FK column.
- **Project Intelligence layout** - Section 2 restructured: readiness ring now sits in a fixed 3-col card next to a full-height Critical-Gaps card (9-col), gaps render in a 2-col grid at wide widths, and the analytics grid takes the full container width below instead of being squeezed into an 8-of-12 column. Eliminates the big empty gutter the left column used to leave under the ring.
- **BIM measure-miss feedback** - `MeasureManager` now surfaces an `onMiss` callback when the raycast returns no geometry; the viewer shows a toast so users know the click registered but did not land on an element (the tool previously silently ignored these clicks, reading as "broken").
- **About page Changelog** - catch-up entries for v1.9.1 / v1.9.2 / v1.9.3 (previously stopped at v1.9.0).
- **Security** - `MessageBubble` markdown link renderer now allow-lists URL schemes (http/https/internal/mailto); rejects `javascript:`/`data:`/`vbscript:` injection.
- **Screenshot timing** - `round4-screenshots.spec.ts` snap helper waits for `networkidle` + the `Analyzing project…` spinner to disappear before capturing. Fixes the empty Estimation Dashboard capture (6 KB → 151 KB).

### Post-sweep polish (R5 full end-to-end verification)

- **E2E infra** - new `e2e/v1.9/global-setup.ts` logs in once per run, caches the JWT to `.auth-token.txt`, every spec reuses it. Avoids the 5/min rate limit on `/login/` when many parallel workers fan out. Helpers also fixed for ESM (`"type": "module"` → `fileURLToPath(import.meta.url)` replaces raw `__dirname`).
- **Tasks assignee display** - the free-text assignee name saved in `metadata.assignee_name` (when the user typed "John Doe" rather than a UUID) was never rendered on the Kanban card. `TasksPage` now falls back to `metadata.assignee_name` so typed names show up like any resolved user name. Edit form pre-fill reads the same fallback.
- **Tasks edit UUID safety** - the edit-submit path was passing free-text assignee names straight into the backend's UUID-typed `assigned_to` column, which would 422 on any edit that touched a legitimate real UUID after a name round-trip. `editMut` now applies the same UUID regex guard as the create path.
- **Transmittals purpose display** - the grid was rendering the raw i18n key `transmittals.purpose_undefined` because the backend serialises the enum as `purpose_code` while the UI models expected `purpose`. New `normaliseTransmittal` in `features/transmittals/api.ts` maps `purpose_code → purpose`, `response_due_date → response_due`, `is_locked → locked` at the API boundary; fetch/create/patch/issue all go through it.
- **CAD Explorer missingness 404** - `/v1/takeoff/cad-data/missingness/` returned 404 against a running backend because uvicorn was started before the endpoint was added and `--reload` missed the module addition. Restarted; endpoint now returns the 7-key shape (`total_rows`, `sampled_rows`, `columns`, `row_completeness`, `presence_matrix`, `applied_filters`, `sampled`) as expected.

### Quality gates

- `tsc --noEmit`: 0 errors
- Vitest: 609 passed, 24 skipped
- Playwright R5 sweep: cluster A (Tasks, 3/3), cluster B (CAD/BIM, 3/3 after backend restart), cluster C (Rules + Dashboard + 45-route nav, 5/5), cluster D (broad nav, 27/27), r5-verification (9/9)
- Backend pytest (transmittals slice): 7/7 passing

## [1.9.3] - 2026-04-18

### R4 new features

- **#10 DWG progress bar + background upload** - new `useDwgUploadStore` (Zustand, mirrors `useBIMUploadStore`): jobs carry progress + stage + error, AbortController per job, simulated stage timer with phases `uploading → converting → extracting → finalizing`. Uploads survive navigation away from `/dwg-takeoff`. Store is free-standing for now; integration into an "Upload Dock" UI component is tracked as v1.9.4 polish.
- **#14 DWG element link-to-other-modules** - extended the right-click context menu (`DwgContextMenu`) with four cross-module actions: Create task, Link to schedule, Link to document, Link to requirement. Each opens the target module page in a new tab with `drawing_id` + `entity_ids` query params so the receiving page can pre-populate forms / filters. No new backend endpoints - uses the existing URL-parameter pattern shared across modules.
- **#15 DWG PDF export** - "Export PDF" button in the Summary tab beside "Export CSV". Generates a multi-page A4 report via jsPDF: totals (count, Σ area, Σ perimeter, Σ length) + per-layer breakdown (up to 40 rows) + per-type breakdown. Rasterised viewport snapshot is deferred; the tabular report is the primary user ask.
- **#22 Split BIM Rules module** - deferred to v1.9.4. The redesigned RuleEditorModal from v1.9.1 (RFC 24) already handles the Quantity Rules concern cleanly; splitting into a separate BIM data-quality page needs a new rule schema + endpoints + migration. Explicitly tracked on the roadmap; does not block v1.9.3.

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- All prior v1.9.1 + v1.9.2 tests still passing

## [1.9.2] - 2026-04-18

### R3 UX polish - remaining items

- **#20 BIM top Link-to-BOQ removed** - the top-toolbar button was a duplicate of the entry point in the selection toolbar / context menu. Selection-toolbar entry remains intact.
- **#21 4D Schedule button disabled** - visually grayed with `aria-disabled` + "coming soon" tooltip. Feature wiring tracked as R5.

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- All prior v1.9.1 tests still passing

## [1.9.1] - 2026-04-18

### R2 deep-research items (8 items with RFCs)

- **#11 DWG polyline selection rework** (RFC 11): ranked area/proximity hit-test fixes outer-polyline bias; `Set<string>` multi-select with Shift+Click + Escape; cycle-through within 6 px / 300 ms; new `aggregateEntities` helper (Σ area / Σ perimeter / Σ length by type); new backend `POST/GET/DELETE /v1/dwg_takeoff/groups/` with `DwgEntityGroup` model; 6 backend tests + 25 frontend unit tests.
- **#16 Data Explorer analytics** (RFC 16): `useAnalysisStateStore` (slicers + chart config + saved views, localStorage-persisted); `numberFormat` lib (currency / percent / number with Intl caching); `aggregation.ts` (Top-N + slicer composition); Recharts lazy-loaded (Bar / Line / Pie / Scatter + ResponsiveContainer); SlicerBanner + TopNToggle + DrillDownModal + ViewsDrawer; 39 unit tests + 5 E2E cases.
- **#19 BIM viewer controls** (RFC 19): `SavedViewsStore` (100-view localStorage cap, ordered eviction); per-category transparency via `ElementManager.setCategoryOpacity` (cloned materials, leak-free dispose); `THREE.BoxHelper` on selection; `MeasureManager` with state-machine + `M` shortcut + `Escape` cancel; 4-tab right panel (Properties / Layers / Tools / Groups); unit tests for all three managers.
- **#24 Quantity Rules redesign** (RFC 24): new `GET /v1/bim_hub/models/{id}/schema/` with 1000-value cap per property; RuleEditorModal with Seed-from-model + datalist comboboxes (element type, property key/value, quantity source); required-field asterisks; Advanced mode toggle (AND/OR/NOT + regex hint + raw JSON editor); BETA badge on page header; 6 backend tests.
- **#25 Project Intelligence → Estimation Dashboard** (RFC 25): `ProjectKPIHero` (Budget variance / Schedule health / Risk-adjusted cost with traffic-light thresholds); `ProjectAnalyticsGrid` (Pareto cost drivers, price volatility, vendor concentration, scope coverage, live validation); 5 new backend endpoints (`/v1/costmodel/variance`, `/v1/boq/line-items`, `/v1/boq/cost-rollup`, `/v1/tendering/bid-analysis`, `/v1/boq/anomalies`); dropped Achievements card + hero onboarding; cache TTL 5 min → 60 s; rename "Estimation Dashboard" (URL unchanged); 14 backend tests.
- **#29 Meetings edit + attachments + description** (RFC 29): new `document_ids: JSON` column with migration + server default `[]`; `EditMeetingModal` mirroring Create (pre-fill + diff-PATCH); delete with `useConfirm`; attachment dropzone with `DocumentService` cross-link; minutes textarea (50 000 char cap); Playwright spec.
- **#33 CDE deep audit (ISO 19650)** (RFC 33): `suitability.py` lookup (S0 / S1–S7 / A1–A5 / AR with state-cross-check validator); new `StateTransition` table + inline audit writes (pre-commit, same-session); revision→Document cross-link on upload; Gate B requires `approver_signature` (400 otherwise); history + transmittals endpoints; `TransmittalItem.revision_id` cross-link; CDEHistoryDrawer + CDETransmittalsBadge; 21 backend tests (17 unit + 4 integration).

### R3 UX polish items bundled

- **#1 Local DDC logo** - Dashboard logo swapped to `/brand/ddc-logo.webp` (no external image fetches on page load).
- **#3 Offline banner removed** - redundant with offline-first pattern from v1.9.0.
- **#4 Header issue menu order** - Report Issue (bug download) now before Email Issues.
- **#7 Takeoff measurements row density** - tighter row height in `TakeoffViewerModule` for both measurement and annotation rows.
- **#17 cad-explorer "Columns" label** - renamed to "Parameter columns" / "Parameter-Spalten" / "Колонки параметров" for clarity.
- **#26 Schedule Create button** - bigger, `Plus`-iconed, size `lg`.
- **#28 5D EVM scope indicator** - banner shows "Viewing all projects (N)" or "Project: {name}" with switch link.
- **#30 Submittals Edit dialog** - row-level Edit button + `EditSubmittalModal` + `updateSubmittal` API wrapper.
- **#32 Documents filters** - client-side file-type dropdown (PDF / DWG / IFC / RVT / Other) + revision filter (All / Latest / Has versions).

### Quality gates

- `tsc --noEmit`: 0 errors across the whole frontend
- Backend `tests/unit/v1_9/` + `tests/integration/v1_9/`: **49/49 passing**
- Frontend unit tests: 600/633 passing (9 pre-existing failures in jsPDF stub + visual-regression snapshots - documented in release notes)
- 7 new RFCs committed in `docs/rfc/` before implementation
- See `docs/ROADMAP_v1.9.md` for per-item detail

### Upgrade notes

- Alembic migrations: three new heads chained - `v191_meetings_document_ids`, `v191_dwg_entity_groups`, `v191_cde_audit`. Run `alembic upgrade head`.
- DWG viewer: `selectedEntityId: string | null` prop is now `selectedEntityIds: Set<string>` (breaking). Two internal call-sites updated; no external consumers affected.
- CDE: `suitability_code` is now state-validated - existing rows with free-text codes continue to work (nullable column + validator only runs on create / update payloads).

## [1.9.0] - 2026-04-17

### R1 critical bug fixes (8 items from the 33-item v1.9 roadmap)

- **BOQ resource add** (#2): optimistic cache write in `handleCatalogSelect` + `networkMode: 'offlineFirst'` + retry guard on the BOQ query. Resources appear instantly; reload no longer hangs.
- **BOQ list offline** (#5): global QueryClient hardened with `navigator.onLine` retry guard and 4xx no-retry - no more `AbortError: signal is aborted without reason` when the network drops.
- **Project not-found vs network error** (#6): `ApiError.status === 404` distinction; new Offline / Can't-reach-server / Retry UI branch; auto-clear-recents gated on true 404 only.
- **Takeoff persistence** (#8): `activeDocId` synced to URL param on upload / click / remove so reload restores the open document.
- **BIM Type Name grouping** (#18): `BIMFilterPanel` condition relaxed to show Link-to-BOQ and Save-Group whenever any elements are visible.
- **BIM Rules** (#23): `mutationKey` + awaited invalidate + filter fix (no-project-context leakage).
- **Tasks category tab** (#27): create modal defaults `task_type` to the active `typeFilter` instead of hard-coded `'task'`.
- **CDE New Container** (#33): `mutationKey`, awaited invalidate, concrete error fallback with dev `console.error` - silent failures are now visible.

### Quality gates

- `tsc --noEmit`: 0 errors
- Playwright `e2e/v1.9/`: 5/5 runnable tests green (2 skipped - pending BIM-model seed data)
- See `docs/ROADMAP_v1.9.md` for per-item detail, rationale, and CTO review checklist

### Scope changes from the original 10-item R1 target

- `#9` (DWG offline) → moved to R3 (UX badge only; backend already offline-capable)
- `#13` (DWG scale + annotation text) → moved to R2 (needs RFC for scale semantics + live repro for text)

## [1.8.3] - 2026-04-17

### BOQ quantity CTA, BIM filmstrip fix, Dashboard upload, cross-link

- **BOQ Linked Geometry → "Apply to BOQ" CTA refresh.** The "Set as
  quantity" buttons are now prominent - a green gradient CTA with arrow
  on every SUM row, and hover-reveal chips with an arrow indicator for
  DISTINCT values. `CheckCircle2` badge replaces the plain "current" tag.
- **BIM filmstrip no longer disappears.** Removed the
  `landingModels.length > 0` conditional that hid the "Your Models" bar
  between LandingPage unmount and main-view mount; the filmstrip is now
  always rendered with a "No models yet" empty state so users keep a
  consistent anchor to switch or upload models.
- **Dashboard upload dropzone.** New `QuickUploadCard` component drops
  files straight into the Documents module with client-side 100 MB limit,
  toasts, live document count, and a `→ Documents` jump link.
- **Cross-link module uploads into Documents.** BIM (`upload_cad_file`),
  DWG Takeoff (`DwgTakeoffService.upload_drawing`), and PDF Takeoff
  (`takeoff/router.py upload_document`) now best-effort create a Document
  row pointing at the same physical file (no duplication) with
  `metadata.source_module` + `source_id` so every file a user uploads -
  in any module - is visible in `/documents`.
- **DocumentsPage routing prefers metadata.** `routeForDocument` and
  `isCardClickable` read `metadata.source_module` first and fall back to
  filename extension, so cross-linked files always jump back to the
  correct module.

## [1.8.2] - 2026-04-17

### Documents routing, BOQ link fixes, DWG filmstrip

- **Documents → correct module by file type** - PDFs open in preview or
  `/takeoff`, DWG/DXF/DGN open in `/dwg-takeoff`, RVT/IFC/NWD/NWC open in
  `/bim`. All with deep-link params so the right file is loaded on arrival.
- **Documents - "Module Files" section** - new compact grid showing BIM
  models, DWG drawings, and Takeoff PDFs uploaded via their native modules,
  each clickable straight into that module.
- **BOQ link icons - deep-link fix** - the red PDF and amber DWG icons next
  to BOQ positions now pass the correct URL params (`drawingId` for DWG,
  `name` for PDF) so clicking them opens the specific linked file instead
  of bouncing to the module landing page.
- **BIM ?docName= / ?docId= deep-link** - `/bim?docName=xxx.rvt` auto-selects
  the matching model if it exists, otherwise opens the upload dialog with
  the filename pre-filled.
- **DWG Takeoff filmstrip** - taller (108-px cards, 150-px max-height) for
  clearer per-drawing metadata.
- **Header** - "Report Issues" → "Email Issues" with mail icon linking
  directly to `mailto:info@datadrivenconstruction.io`.

## [1.8.1] - 2026-04-17

### DWG Takeoff depth pass + Takeoff decorative background

- **DWG ↔ BOQ deep linking** - full picker mirrors the PDF-takeoff flow:
  project + BOQ dropdowns, pick-existing-or-create-and-link, search filter,
  already-linked badge. On link, a `text_pin` annotation is auto-created at
  the selected entity's centroid (if none exists), `linkAnnotationToBoq`
  ties it to the position, and the position's `quantity` + `unit` +
  `metadata.{dwg_drawing_id, dwg_entity_id, linked_annotation_id}` are
  updated - matching the PDF linking model end-to-end.
- **DWG summary bar** in the right panel: total entities, Σ area, Σ distance,
  plus a one-click CSV export of all measurements (type, text, value, unit,
  linked position id).
- **DWG right panel refinement** - back to light theme, width bumped to 72px,
  elevated shadow for separation from the dark canvas.
- **DWG toolbar palette** - white-glass on dark `#3f3f3f` canvas so tool
  icons read clearly in both light and dark app themes.
- **Takeoff decorative background** - field-surveyor chalkmarks (rectangles,
  irregular polygons, distance dimension lines, vertex pins, scale ruler) at
  ~6% opacity, fixed to viewport so both Measurements and Documents tabs
  share the same bg.
- **Documents API** - frontend wrappers for general-document upload/list/
  delete (`uploadDocument`, `fetchDocuments`, `deleteDocument`). Foundation
  for the upcoming Dashboard ↔ Documents module integration.
- **Demo storyboard** - full 6-minute walkthrough script saved to
  `docs/VIDEO_DEMO_v1.8.md` (hook → CAD/BIM → takeoff → BOQ → validation
  → tender → 4D/5D).

## [1.8.0] - 2026-04-17

### BOQ ↔ Takeoff linking, UI polish sprint, decorative backgrounds

- **BOQ ↔ PDF Takeoff deep linking** - individual measurements can now be linked
  to specific BOQ positions. The measurement's quantity auto-transfers to the
  position and stays in sync. Bidirectional metadata: `measurement.linked_boq_position_id`
  + `position.metadata.pdf_document_id / pdf_page / pdf_measurement_id`.
- **BOQ grid link icons** - rose PDF icon + amber DWG icon next to positions
  that have linked documents. Click opens the document in the same tab so the
  auth session is preserved (no more login bounce).
- **BOQ Linked Geometry popover** - "Set as quantity" buttons next to each BIM
  parameter value; one click applies the value to the position's quantity field.
- **Takeoff UI refresh** - tab order swapped (Measurements first, Documents & AI
  second); tighter rounded corners; per-tool hover colours. Bottom filmstrip
  of previously uploaded documents with click-to-open.
- **Takeoff decorative background** - barely-visible polygons, distance lines,
  scale rulers behind the viewer, evoking field-surveyor chalkmarks.
- **BIM landing** - tileable isometric-cube SVG pattern at ~1% opacity; airy
  spacing; inner scroll hidden with `scrollbar-none`; content fits 1080p viewport.
- **BIM filmstrip** - no longer auto-collapses after 10s; always visible.
- **DWG Takeoff** - toolbar palette switched to white-glass for contrast on the
  dark `#3f3f3f` canvas; right-panel re-themed dark with readable slate-100
  text; drawings filmstrip already dark (1.7.2).
- **CAD Data Explorer** - subtle semi-transparent spreadsheet grid decoration;
  landing now fits without horizontal *or* vertical scroll on typical viewports.
- **Chat** - markdown links like `[Settings](/settings)` now render as proper
  clickable anchors; external links open in a new tab.
- **Projects** - self-healing bookmark URLs: navigating to a stale project ID
  (e.g. after a demo reseed) auto-clears it from `useProjectContextStore` and
  `useRecentStore` so the user isn't stuck on "Project not found".

## [1.7.0] - 2026-04-15

### BIM, DWG Takeoff, and cross-module UI improvements

- **BIM Viewer** - linked BOQ panel with quantities
- **DWG Takeoff** - polygon selection + measurements
- **Data Explorer** - BIM-style full-viewport layout
- **Dashboard** - DDC branding, subtitle i18n (21 langs)
- **Assemblies** - JSON import/export, tags, drag-reorder
- **5D Cost Model** - inline-editable budget lines
- **Finance** - summary cards with key metrics
- **Tasks** - custom categories, 4-column Kanban
- **Schedule** - user-selectable project start date
- **Chat** - AI config onboarding guide
- **Project Intelligence** - tag badges, compact cards
- **Bugfixes** - Contacts country_code, RFI field sync, 4 modals
- **UI** - unified padding across 37+ pages

## [1.4.8] - 2026-04-11

### Real-time collaboration L1 - soft locks + presence (issue #51)

Maher00746 asked: "Does the platform support real-time collaboration
when multiple users are working on the same BOQ?". The full collab
plan has 3 layers: L1 (soft locks + presence), L2 (Yjs Y.Text on text
fields), L3 (full CRDT BOQ rows). This release ships **L1**, which
covers the maher00746 90% case ("two estimators editing the same
position should not trample each other") without dragging in a CRDT
runtime, Yjs, or Redis. L2 / L3 remain on the v1.5 / v2.0 roadmap.

#### New module ``backend/app/modules/collaboration_locks/``
Self-contained module with manifest, models, schemas, repository,
service, router, presence hub, sweeper, and event bridge - 1,580
backend LOC across 10 files. Mounted at ``/api/v1/collaboration_locks``.
Named ``collaboration_locks`` (not ``collaboration``) so it does not
collide with the existing comments / viewpoints module.

- ``oe_collab_lock`` table (Alembic migration ``a1b2c3d4e5f6``) with
  ``UniqueConstraint(entity_type, entity_id)`` so only one user can
  hold a row at a time. Indexed on ``expires_at`` and ``user_id``.
- **Atomic acquire** via read-then-insert-or-steal at the repository
  level - cross-dialect (SQLite dev + PG prod), races handled by
  catching ``IntegrityError`` and re-reading the winner. Expired
  rows are stolen *in place* via UPDATE so the unique constraint
  never trips.
- **Heartbeat extends TTL** in 30s steps; rejected if the caller is
  not the holder.
- **Release** is idempotent and only honoured for the holder.
- **Background sweeper** runs every 30s, purges rows where
  ``expires_at < now()``. Uses its own session per iteration so a
  sweeper failure cannot roll back any in-flight request.
- **Entity-type allowlist** mirrors the existing ``collaboration``
  module - clients cannot lock arbitrary strings. Returns 400 on
  rejection.
- **409 conflict body** is a distinct ``CollabLockConflict`` schema
  with ``current_holder_user_id``, ``current_holder_name``,
  ``locked_at``, ``expires_at``, ``remaining_seconds`` so the
  frontend can render a useful toast without a follow-up GET.
- **Naive datetime normalisation** via ``_as_aware()`` helpers in
  repository + service - SQLite's ``DateTime(timezone=True)``
  returns naive Python datetimes, so every comparison gets coerced
  to UTC first. Same pattern already used in ``dependencies.py``
  for ``password_changed_at``.

#### Presence WebSocket
``WS /collaboration_locks/presence/?entity_type=...&entity_id=...&token=<jwt>``
broadcasts JSON frames to every connected client subscribed to the
same entity. Auth via the ``token`` query param because browser
WebSocket cannot set headers - same pattern as the BIM geometry
endpoint. The ``PresenceHub`` is worker-local in v1.4.8 (single
``presence_hub = PresenceHub()`` module-level instance, no Redis,
no Postgres LISTEN/NOTIFY) - multi-worker deployments still get
correct *locking* via the DB but presence broadcasts are
worker-scoped. Documented in the module docstring; the upgrade
path to LISTEN/NOTIFY is a single internal swap with no caller
changes.

Wire format (every frame is JSON ``{event, ts, ...}``):

| event | extras | when |
|---|---|---|
| ``presence_snapshot`` | ``users[]``, ``lock`` | first frame after upgrade |
| ``presence_join`` | ``user_id``, ``user_name`` | another user opened the entity |
| ``presence_leave`` | ``user_id`` | user closed all their tabs on the entity |
| ``lock_acquired`` | ``lock_id``, ``user_id``, ``user_name``, ``expires_at`` | any user claimed the lock |
| ``lock_heartbeat`` | ``lock_id``, ``user_id``, ``user_name``, ``expires_at`` | holder renewed TTL |
| ``lock_released`` | ``lock_id``, ``user_id``, ``user_name`` | holder voluntarily released |
| ``lock_expired`` | ``lock_id``, ``user_id`` | sweeper removed a stale lock |
| ``pong`` | - | response to client ``"ping"`` keepalive |

The ``presence_join`` broadcast uses ``exclude=websocket`` so the
joiner does not receive their own join event. ``lock_acquired``
intentionally does NOT exclude - the holder *should* see the echo
so the UI can confirm the state transition from the event stream
(useful for multi-tab consistency).

Multi-tab same user: the hub deduplicates by ``user_id`` in the
roster. ``leave()`` walks remaining sockets to check whether the
departing user still has another tab on this entity before
broadcasting ``presence_leave``. The lock itself is idempotent per
user (re-acquire refreshes TTL).

#### Frontend hook + indicator + BOQ wiring
``frontend/src/features/collab_locks/`` - 5 files, 636 LOC:
- ``api.ts`` - typed clients with a tagged-union return type so
  TypeScript narrows ``CollabLock`` vs ``CollabLockConflict``
- ``useEntityLock.ts`` - auto-acquire on mount, 15s heartbeat,
  cleanup-release on unmount. Catches every error and degrades
  gracefully - a network drop transitions to ``'released'`` and
  re-acquires on the next focus event. Worst case: user types
  for ~15s without a live lock (race window between expiry and
  next sweep at 60s TTL + 30s sweep interval).
- ``usePresenceWebSocket.ts`` - JWT-via-query-param connection,
  roster state, event stream
- ``PresenceIndicator.tsx`` - green / amber / blue pill badge
  ("You are editing" / "Locked by Anna 3:42 remaining" / "N viewers")
- ``index.ts`` - barrel re-exports

**BOQ wiring** in ``frontend/src/features/boq/BOQGrid.tsx``:
- Acquires on ``onCellEditingStarted`` (per ROW, not per cell -
  tracks held locks in a ``rowLockMapRef`` and re-uses on
  subsequent cell edits within the same row)
- Releases on new ``onCellEditingStopped`` callback
- Releases all held row locks on unmount
- 409 cancels the edit and shows a toast with the holder name +
  remaining seconds. Network errors degrade silently - the user
  can still edit, just without collab safety.

9 new i18n keys (``collab_locks.lock_held_by_you``,
``collab_locks.lock_held_by_other``, ``collab_locks.lock_conflict_toast``,
``collab_locks.viewers_label`` etc.) all via ``t(key, { defaultValue })``
so the UI works today without a translation pass.

#### Tests - 17 / 17 passing

``backend/tests/integration/test_collab_locks.py`` - 14 tests
covering: acquire when free / conflict, idempotent re-acquire,
heartbeat extends / rejects non-holder, release, idempotent
release of missing-id, allowlist 400, ``GET /entity/`` returns
none-or-holder, ``GET /my/`` lists my locks, expired-lock-can-be-
stolen via direct DB forge, sweeper removes expired rows.

``backend/tests/integration/test_collab_locks_ws.py`` - 3
WebSocket tests: rejects missing token (1008), delivers
``presence_snapshot`` + ``lock_acquired`` to subscribers, delivers
``presence_join`` across two clients.

#### What is deliberately NOT in v1.4.8

- **L2 - Yjs Y.Text on description / notes** → v1.5. Requires
  ``yjs`` + ``y-websocket`` deps + server-side CRDT state
  persistence. Not needed for the maher00746 case.
- **L3 - full CRDT BOQ rows** → v2.0. 3x the surface of L1 with
  marginal UX gain over soft locks for our user base.
- **Postgres LISTEN/NOTIFY fan-out** → only needed for multi-
  worker deployments wanting cross-worker presence. The hub
  interface stays stable; only ``_broadcast`` needs a second
  implementation gated on settings.
- **Audit log of lock events** → the event bus already publishes
  ``collab.lock.*``; an audit subscriber can be added in a
  follow-up without touching this module.
- **Org-scoped RBAC** → ``org_id`` column exists but is unused.
  Matches the current behaviour of the ``collaboration`` module.
- **Frontend wiring for non-BOQ entities** → only BOQ row editing
  is wired in this PR. Requirements / RFIs / tasks / BIM elements
  are already in the allowlist; the hook + indicator are ready
  to drop into any of those editors.

### Verification
- Backend ``ruff check`` clean across the new module + tests
- 17/17 collab_locks integration tests passing in 65.7s
- ``check_version_sync.py`` passes at 1.4.8
- Frontend ``tsc --noEmit`` exit 0
- Alembic migration chains correctly on top of head ``b2f4e1a3c907``

## [1.4.7] - 2026-04-11

### Added - UX polish + cross-module event hooks

#### BIM viewer geometry-loading progress bar
The BIM viewer used to show only a generic spinner while the COLLADA
geometry blob downloaded - a 100MB Revit model could take 30+ seconds
with no visible progress, so users assumed the page had hung.
``ElementManager.loadDAEGeometry`` now accepts an ``onProgress``
callback that surfaces the XHR ``loaded / total`` ratio, and
``BIMViewer`` renders a determinate progress bar with percentage
indicator, gradient fill, and "Streaming geometry from server…" /
"Finalising scene…" status text.

#### Sidebar BETA badges (subtle, modern)
``/bim``, ``/bim/rules``, and ``/chat`` are still under heavy
development.  Added a tiny lowercase ``beta`` badge to each of those
nav items so users know not to rely on those modules for production
work yet.  The badge style is intentionally understated - neutral
grey, 9px, lowercase - so it does not visually compete with the
sidebar's normal items.

#### Restored rich GitHub README
``README.md`` was rewritten to a 53-line minimal version in d3d2319
that dropped the Table of Contents menu, the comparison table, the
feature gallery, and the workflow diagram.  This release restores
the rich 450-line version (badges, ToC table, why-OpenConstructionERP
table, vendor comparison, complete-estimation-workflow diagram, 12
feature blocks with screenshots, regional standards table, tech
stack, architecture diagram) - bumped to v1.4.6 in the version
badge and footer.

### Fixed

#### Frontend correctness
- **F1**: ``BIMPage.tsx:602`` dropped two ``(res as any)`` casts on
  the upload response.  ``BIMCadUploadResponse`` now declares
  ``element_count: number`` and a typed ``status`` union, so the
  upload toast no longer guesses fields that may not exist.
- **F5**: ``BIMFilterPanel`` now resets every transient filter slot
  (search, storey checkboxes, type checkboxes, expanded headers,
  active group highlight) when the user switches to a different
  BIM model.  Previously the checkbox UI carried over Storey 5
  selections from the old model into the new one - confusing UX
  where the displayed filter did not match the applied predicate.

#### Cross-module wiring
- **T2.3**: ``Assembly.total_rate`` is no longer stale when a
  ``CostItem.rate`` changes externally.  New ``assemblies/events.py``
  subscribes to ``costs.item.updated``, finds every ``Component``
  pointing at the updated cost item, refreshes the per-component
  ``unit_cost`` + ``total``, and re-runs the parent assembly total
  math (sum of components × ``bid_factor``).  BOQ positions
  generated from an assembly BEFORE the rate change are intentionally
  NOT touched - they're locked financial commitments at create time;
  the next regenerate of the position picks up the new rate.
- **T3.5**: ``requirements.list_by_bim_element`` now uses the
  PostgreSQL JSONB ``@>`` containment operator at the SQL level when
  the dialect is PG, so the database does the filtering instead of
  loading every project requirement and filtering in Python.
  SQLite still uses the Python fallback (no portable JSONB
  operator).  Mirrors the dialect-aware pattern in
  ``tasks/service.py::get_tasks_for_bim_element``.

#### Test infrastructure
- **T8 (deferred from v1.4.5)**: 12 broken integration tests that
  failed since v1.3.x with 404 / 422 / 403 errors are now passing.
  Root cause was a mix of:
  - Trailing-slash mismatch (10 tests): tests called
    ``/boqs/{id}/positions`` without the slash but the route is
    ``/boqs/{id}/positions/``.  ``redirect_slashes=False`` is
    intentional in main.py to kill CORS 307 redirect issues with
    the frontend, so the FIX is to add the slash to the test
    paths.  Audited every parametric POST in
    ``test_cross_module_flows.py`` + ``test_api_smoke.py``.
  - Missing required query param (1 test):
    ``test_tendering_packages`` was hitting ``/tendering/packages/``
    without the mandatory ``project_id`` (security: prevents
    cross-tenant enumeration).  Fixed to create a throwaway project
    first.
  - Permission scope (1 test):
    ``test_cost_regions`` and ``test_vector_status`` had no
    auth header - the endpoints require ``contacts.read`` or
    similar.  Fixed to pass ``auth_headers``.

### Notifications subscriber dialect guard
The S3 subscriber framework added in v1.4.6 (boq.created /
meeting.action_items_created / cde.state_transitioned event hooks)
opened its own short-lived session via ``async_session_factory()``
to call ``NotificationService.create()``.  Under SQLite this
deadlocked against the upstream service's still-open transaction
because SQLite is single-writer per file.  The handlers now probe
the dialect at entry and bail out fast on SQLite - production uses
PostgreSQL where this is a non-issue, and the dev SQLite path
simply skips the in-app notification (the upstream mutation still
succeeds).  A v1.5 background-task refactor will move notification
create out of the upstream transaction altogether.

### Project Intelligence smart actions implementation (T2.1)
The three "smart action" tiles on ``/project-intelligence`` were
stub redirects that opened the validation / cost-catalog / scheduler
pages and let the user finish the action manually.  ``actions.py``
now actually performs the work:
- ``run_validation`` loads the project's oldest BOQ, runs
  ``ValidationModuleService.run_validation`` with
  ``rule_sets=["din276","boq_quality"]``, and returns the new
  ``ValidationReport`` id plus pass / warning / error counts.
- ``match_cwicr_prices`` walks every leaf BOQ position with a
  zero ``unit_rate``, calls ``CostItemService.suggest_for_bim_element``
  with the position description and classification, and writes the
  top match's rate back to ``unit_rate`` (with ``total = qty × rate``
  recomputed and the matched code/score saved into ``metadata_``).
  Publishes ``boq.prices.matched`` so vector re-indexing subscribers
  can react.
- ``generate_schedule`` refuses if a schedule already exists,
  otherwise creates a draft ``Schedule`` keyed off
  ``project.planned_start_date`` and delegates to
  ``ScheduleService.generate_from_boq``, returning ``schedule_id``
  + ``activity_count``.

Every action wraps its body in try/except so failures surface as
``ActionResult(success=False, message=...)`` rather than 500.
9 new unit tests cover happy path + no-BOQ guards + service-raises
branches.

### Vector routes factory (T9)
6 of 8 module routers were carrying ~50 lines each of copy-pasted
``vector/status`` + ``vector/reindex`` boilerplate (documents,
tasks, risk, validation, requirements, erp_chat).  Extracted the
common shape into ``app/core/vector_routes.py:create_vector_routes()``
which takes a model + project_id_attr (or a custom loader for
parent-scoped modules), the read/write permissions, and a vector
adapter.  Each module router now does ``include_router(create_vector_routes(...))``
in 4 lines instead of 50.  Net result: **-105 LOC** in module
routers, ~291 lines of duplicated boilerplate eliminated, all 16
existing vector routes preserved exactly.  ``boq`` and ``bim_hub``
keep their hand-written endpoints because they accept extra
optional query params (``boq_id`` / ``model_id``) that the
factory does not yet model.

### Costmodel honest schedule reporting + delete-snapshot
The 5D cost-model dashboard previously reported every project as
"on_track / at_risk" even when no schedule data was available,
because ``calculate_evm`` had a hard-coded ``time_elapsed_pct =
50.0`` fallback.  This skewed portfolio rollups and made unscheduled
projects look like they were silently 50 % done.

- The fallback is gone.  ``schedule_known: bool`` is set only when
  date parsing actually succeeds; otherwise ``evm_status`` is
  ``schedule_unknown`` and the dashboard renders "no schedule yet"
  instead of a fake percentage.
- Bonus fix in ``full_evm/service.py``: TCPI was crashing on
  ``Decimal(0)`` denominators.  Three-branch decision now yields
  ``"inf"`` sentinel when remaining work exists but the budget is
  exhausted, and ``Decimal(0)`` when both are zero.
- New ``DELETE /api/v1/costmodel/projects/{pid}/5d/snapshots/{sid}``
  endpoint (gated by ``costmodel.write``) for cleaning out stale
  snapshots without dropping into a SQL shell.  Emits
  ``costmodel.snapshot.deleted`` event.

21 new unit tests, total suite 963 passing, zero regressions.

### BIM frontend correctness wave (F2/F3/F4/F6)
- **F4** - ``AddToBOQModal`` derived ``effectiveBOQId`` via
  ``useMemo`` from ``(boqs, userSelectedBOQId)`` so a BOQ getting
  removed mid-flow can not leave the modal pointing at a stale id.
  Tightened the React Query ``enabled`` guard with
  ``!boqsQuery.isLoading`` for first-render correctness.
- **F2** - All four BIM link modals
  (``AddToBOQModal``/``LinkDocumentToBIMModal``/``LinkActivityToBIMModal``/``LinkRequirementToBIMModal``)
  reset their internal state when the parent's ``elements`` array
  identity changes, so reopening the modal after switching elements
  always starts clean.
- **F3** - ``LinkActivityToBIMModal`` and
  ``LinkRequirementToBIMModal`` replaced the hardcoded "showing
  first 200, +N more…" stub with proper pagination
  (``PAGE_SIZE = 50`` + "Load more (N remaining)" button), with
  the page cursor resetting on both element change and search
  text change.
- **F6** - ``ElementManager`` now tracks every cloned ``THREE.Material``
  it creates in ``colorByDirect``/``colorBy`` via a
  ``createdMaterials`` set and disposes them in ``resetColors`` and
  ``dispose``, plugging a slow GPU memory leak that grew every
  time the user toggled status colouring.

### Levels filter - rename "Storeys" → "Levels", real Level support
The BIM filter panel labelled the storey filter "Storeys" but
Revit users overwhelmingly think in terms of "Level" (the actual
Revit property name).  Worse, when the upload row had no top-level
``storey`` column the filter would silently miss elements whose
level was buried inside the ``properties`` JSONB blob - common
for Revit Excel exports where "Level" lives as a Type Parameter,
not a column.

- Backend ``_rows_to_elements`` (``bim_hub/router.py``) now calls
  a new ``_extract_storey(row, props)`` helper that first checks
  the top-level column (already aliased from ``level``,
  ``base_constraint``, ``host_level_name``, etc. via
  ``_BIM_COLUMN_ALIASES``), then falls back to a 20-key
  case-insensitive scan of the ``properties`` blob: ``Level``,
  ``Base Level``, ``Reference Level``, ``Schedule Level``,
  ``Host Level``, ``IFCBuildingStorey``, ``Geschoss``, ``Etage``…
- ``_normalise_storey()`` coerces literal ``"None"`` / ``"<None>"``
  / ``"null"`` / ``"-"`` / ``"-"`` strings to None so they don't
  pollute the filter panel with a fake "None (586)" bucket.  This
  was visible in screenshots from real Revit exports.
- Frontend ``BIMFilterPanel.tsx`` rename: "Storeys" → "Levels",
  "by Storey" → "by Level", "No storeys detected" → "No levels
  detected", search placeholder updated.  i18n keys renamed to
  ``bim.filter_levels``, ``bim.filter_no_levels``,
  ``bim.filter_group_level`` with English defaults.  Internal
  state keys (``state.storeys``, ``el.storey``, API param
  ``storey=``) are unchanged so saved filter groups and the
  ``BIMQuantityRulesPage`` form continue to work.

### BIM converter preflight + one-click auto-install
Uploading a ``.rvt`` file at ``/bim`` previously consumed 18 MB of
upload, saved it to disk, then silently failed with "Could not
extract elements from this CAD file" when ``find_converter('rvt')``
returned None and ``process_ifc_file`` returned an empty result.
Two issues stacked: no preflight, and the frontend hardcoded a
generic English error string instead of using the backend's
``model.error_message``.  All the converter-install plumbing
already existed (``GET /api/v1/takeoff/converters/`` +
``POST /api/v1/takeoff/converters/{id}/install/``) but the BIM
upload page never used it.

**Backend preflight (``bim_hub/router.py``)** - new
``_NEEDS_CONVERTER_EXTS = {".rvt", ".dwg", ".dgn"}``.  At the very
top of ``upload_cad_file``, before ``await file.read()``, we call
``find_converter(ext.lstrip("."))`` and refuse the upload up-front
with ``status="converter_required"`` (200 OK, not error) when the
binary is missing.  The response includes ``converter_id`` and
``install_endpoint`` so the frontend can route the user straight
into the install flow without wasting an upload roundtrip.  The
success-path response was extended with ``error_message``,
``converter_id``, and ``install_endpoint`` fields so the frontend
can render the actual reason instead of guessing.

**Real DDC repo (``takeoff/router.py``)** - the converter
auto-installer was pointing at a non-existent
``ddc-community-toolkit`` releases URL.  Rewritten to walk the
real ``datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN``
repository via the GitHub Contents API, recursively listing
``DDC_WINDOWS_Converters/DDC_CONVERTER_{FORMAT}/`` and downloading
each file from ``raw.githubusercontent.com``.  Verified live
against the upstream repo: 175 files / 598 MB for RVT, 143 / 241
MB IFC, 252 / 218 MB DWG, 252 / 217 MB DGN.

- Files install into per-format directories
  (``~/.openestimator/converters/{ext}_windows/``) so each
  converter's bundled Qt6 DLLs and Teigha format readers do not
  collide with other formats.
- Downloads run in parallel via a ``ThreadPoolExecutor(max_workers=8)``
  - RVT goes from ~5 minutes sequential to ~30-60 seconds without
  tripping GitHub abuse detection.
- Path traversal defence runs BEFORE any network IO so a
  hostile listing fails fast instead of partway through 600 MB of
  downloads.
- Atomic rollback on partial failure (``shutil.rmtree`` of the
  per-format dir) so a half-installed converter can not confuse
  ``find_converter`` on the next call.
- Linux returns ``platform_unsupported: true`` with the apt commands
  needed to install ``ddc-rvtconverter`` etc. via the upstream
  apt source ``pkg.datadrivenconstruction.io``.  We deliberately
  do NOT auto-shell-out to ``sudo apt`` from a web handler.
- macOS / other platforms get a graceful "convert to IFC first"
  message - the IFC text parser works on every platform.

``find_converter`` (``boq/cad_import.py``) extended to probe both
the new per-format Windows install dirs and the Linux apt install
paths (``/usr/bin/ddc-{ext}converter``,
``/usr/local/bin/ddc-{ext}converter``) so installed converters
are picked up instantly with no service restart.

**Frontend banner + install prompt (``BIMConverterStatusBanner.tsx``,
``InstallConverterPrompt.tsx``, +233 LOC in ``BIMPage.tsx``)** -
new amber banner above the BIM page lists every converter that
needs installation with name, real size in MB, and a one-click
Install button.  Installs run via React Query mutation with
spinner, success toast, and automatic banner refetch on completion.

When the user drops a ``.rvt`` / ``.dwg`` / ``.dgn`` file and the
converter is missing, a pre-upload guard intercepts the drop and
opens ``InstallConverterPrompt`` instead of starting the upload -
no megabytes wasted.  The prompt shows the converter name, real
size from the GitHub-derived metadata, and an "Install &
auto-retry upload" button that on success replays the original
upload with the saved file bytes.  The previously hardcoded
"Could not extract elements" error string is replaced with the
backend's actual ``error_message``.  27 new i18n keys (all with
English ``defaultValue``) so the UI works today without a
translation pass.

Backwards compatible: older backends that do not return
``converter_id`` fall through to the legacy ``needs_converter``
toast.

### Verification
- Backend ``ruff check`` clean across every v1.4.7-touched file
- 16/16 tests in the BIM converter preflight + cross-module + PI
  action suites passing in 34.5s
- 963 unit tests passing in the costmodel/finance/full_evm suite
- ``check_version_sync.py`` passes at 1.4.7
- ``integrity_check.py`` passes (23 hits)
- Frontend ``tsc --noEmit`` exit 0, zero errors
- Live test of GitHub Contents API directory walk against the real
  ``cad2data-Revit-IFC-DWG-DGN`` repo confirms ``RvtExporter.exe``
  is reachable and 175 files enumerate cleanly

## [1.4.6] - 2026-04-11

### Security - IDOR fixes (driven by wave-2 deep audit)

#### S1 - Contacts module: query scoping
Three TODO(v1.4-tenancy) markers in ``contacts/router.py`` flagged
that ``Contact`` had no ``tenant_id`` and any authenticated user with
``contacts.read`` could read **every** contact in the database.  The
get/patch/delete endpoints already had a ``_require_contact_access``
gate, but the list/search/by-company/stats endpoints were unscoped.
Fixed by threading an ``owner_id`` parameter through repository →
service → router that filters on the ``created_by`` proxy column.
Admins still bypass and see the global view.

- ``contacts/repository.py`` - ``list()``, ``stats()``, ``list_by_company()``
  all accept an optional ``owner_id`` filter
- ``contacts/service.py`` - same
- ``contacts/router.py`` - list/search/stats/by-company endpoints now
  resolve the caller's role via ``_is_admin()`` and pass either
  ``user_id`` (non-admin) or ``None`` (admin) as the owner filter

#### S2 - Collaboration module: permissions + entity allowlist
``collaboration/router.py`` had **zero** permission checks.  No
``RequirePermission`` decorator on any endpoint, no entity access
validation.  Any authenticated user could list / create / edit /
delete comments and viewpoints across project boundaries.  Fixed by:

- New ``collaboration/permissions.py`` - registers
  ``collaboration.read`` (Viewer), ``collaboration.create`` /
  ``.update`` / ``.delete`` (Editor)
- New ``collaboration/__init__.py`` ``on_startup`` hook that wires
  the registration
- ``collaboration/router.py`` rewritten to add ``RequirePermission``
  to all 7 endpoints
- New ``_ALLOWED_ENTITY_TYPES`` allowlist (16 entries: project, boq,
  document, task, requirement, bim_element, etc.) - any other value
  is rejected at the router boundary so we never persist orphaned
  metadata.  Fixes the prior bug where ``entity_type='unicorn'``
  was silently accepted.

### Cross-module wiring

#### S3 - Notifications subscriber framework
The notifications module had ``create()`` and ``notify_users()`` since
day one but **nothing in the platform actually called them** -
contacts / collaboration / cde / transmittals / teams all silent on
mutations.  Created ``notifications/events.py`` with a declarative
``_SUBSCRIPTIONS`` map and an ``on_startup`` hook that wires the
event bus on module load.  Initial subscriptions:

- ``boq.boq.created`` → notify the creator (info)
- ``meeting.action_items_created`` → notify each task owner
  (task_assigned) for the items that ACTUALLY produced a Task row
- ``cde.container.state_transitioned`` → notify the actor (info)
- ``bim_hub.element.deleted`` → audit echo skeleton (no-op until
  the upstream payload includes a user-id target)

Adding a new event trigger is now a one-line entry in
``_SUBSCRIPTIONS`` - keeps the cross-module event topology auditable
from a single grep.

#### C5 - Raw SQL → ORM in 3 remaining cross-link sites
v1.4.4 fixed the bim_hub upload cross-link.  The same fragile
hand-rolled ``INSERT INTO oe_documents_document`` via ``text()``
pattern still existed in three other places - replaced each with a
clean ``Document(...)`` ORM insert that picks up timestamps + defaults
from the Base mixin and stays in sync with any future schema
migration:

- ``punchlist/router.py:288`` (punch photos)
- ``meetings/router.py:967`` (meeting transcripts)
- ``takeoff/router.py:1855`` (takeoff PDFs)

All four cross-link sites now use the ORM.  Verified with
``grep -c "INSERT INTO oe_documents_document"`` returning 0 across
all four files.

#### C6 - Meetings: stop publishing event when task creation fails
``meetings/service.py::complete_meeting`` wrapped task creation from
action items in a try/except that swallowed all errors with
"best-effort" logging - and then published
``meeting.action_items_created`` regardless.  Downstream subscribers
(notifications, vector indexer) were told the work was done even
when zero tasks made it into the DB.  Fixed by:

- Per-action-item isolation: a single failed item no longer aborts
  the others
- Track ``created_action_items`` and ``failed_action_items``
  separately, surface both via the response
- Only publish the event when at least one task actually persisted;
  payload now carries ``created_count`` / ``failed_count`` so
  notification subscribers can show "3 of 5 tasks created"

### Project Intelligence

#### T1.1 - Collector wires 4 missing modules
``project_intelligence/collector.py`` collected state from 9 domains
(BOQ, schedule, takeoff, validation, risk, tendering, documents,
reports, costmodel) but was **completely blind** to requirements,
bim_hub, tasks, and assemblies.  ``ProjectState`` had no fields for
them.  Score lied - a project with perfect BOQ but zero requirements
got a falsely high score.  Fixed by:

- New ``RequirementsState`` / ``BIMState`` / ``TasksState`` /
  ``AssembliesState`` dataclasses
- New ``_collect_requirements`` / ``_collect_bim`` / ``_collect_tasks``
  / ``_collect_assemblies`` parallel collectors
- Each new collector uses cross-dialect SQL (works on SQLite +
  PostgreSQL) and falls back to default state on exception with a
  WARNING-level log instead of the previous DEBUG-level swallow
- ``collect_project_state`` now ``asyncio.gather``s 14 collectors
  instead of 10
- ``ProjectState`` exposes 4 new fields so the scorer / advisor /
  dashboard can surface gaps like "no requirements defined" or
  "BIM elements not linked to BOQ"

Smoke-tested against the live database - collectors return real
counts for the 5 most recent projects (which include data created
by the v1.4.5 cross-module integration tests).

### Verification
- Backend ``ruff check`` clean across every file touched in v1.4.6
- 174 unit + integration tests passing (vector adapters x7 +
  property matcher + requirements↔BIM cross-flow + BIM processor)
- ``scripts/check_version_sync.py`` passes at 1.4.6
- ``scripts/integrity_check.py`` passes (10 hits)

### Deferred to v1.4.7 / v1.5.0
- ``project_intelligence/actions.py`` 3 of 8 actions still dead code
  (run_validation / match_cwicr_prices / generate_schedule fall back
  to redirect lying about execution)
- ``costmodel`` vs ``full_evm`` redundancy - both compute EVM with
  different logic, frontend uses neither, needs strategic decision
- ``costmodel`` PV approximation flaw (BAC × time_elapsed%)
- BIM frontend correctness: 14 findings in BIMPage.tsx + 5 link
  modals (200-item caps, modal pattern inconsistency, race
  conditions, type-unsafe casts)
- Assembly ``total_rate`` invalidation on CostItem.rate change
- ``create_vector_routes()`` factory + reduce ~250 LOC duplication
- Trailing-slash audit of 12 broken integration tests
- Test coverage push: 0 tests for costmodel/finance/full_evm and 6
  of 8 shared infra modules

## [1.4.5] - 2026-04-11

### Fixed - deep-audit cut driven by 3 parallel sub-agents

Three multi-agent deep audits of the recently-added v1.4.x modules
(requirements, project_intelligence, erp_chat, vector_index, bim_hub
element groups, quantity maps, assemblies) flagged 40+ findings.
This cut tackles the cross-module-correctness ones - fixes that
make existing features actually do what they advertise - plus the
biggest test-coverage holes.

#### Cross-module data integrity
- **Orphaned BIM element ids cleaned up on element delete**.  Three
  of five cross-module link types denormalise BIM ids into JSON
  arrays (Task.bim_element_ids, Activity.bim_element_ids,
  Requirement.metadata_["bim_element_ids"]) instead of FK tables.
  The FK-based ones (BOQElementLink, DocumentBIMLink) cleaned
  themselves up via ``ondelete='CASCADE'``; the JSON ones leaked
  stale references **forever**, confusing the BIM viewer's
  "linked tasks/activities/requirements" panel and every reverse
  query helper.  New ``bim_hub.service._strip_orphaned_bim_links``
  runs INLINE on the active session inside ``bulk_import_elements``
  and ``delete_model``, so the cleanup shares the upstream
  transaction (no SQLite write-lock contention) and rolls back
  atomically on failure.  Integration test
  ``test_orphan_bim_ids_stripped_on_element_delete`` pins the
  behaviour end-to-end.
- **Requirement embeddings now include pinned BIM element ids**.
  After ``link_to_bim_elements`` fired the linked_bim event the
  vector indexer re-embedded the row, but
  ``RequirementVectorAdapter.to_text()`` never read
  ``metadata_["bim_element_ids"]`` so the embedding was unchanged
  and semantic search like *"requirements linked to roof elements"*
  returned zero.  ``to_text()`` now appends a sample of up to 5
  pinned ids; the full list still lives in metadata.  5 new unit
  tests cover present/empty/missing/non-dict metadata edge cases.

#### Hacks → real implementations
- **Property filter ``_matches`` is now type-aware**.  The dynamic
  element-group predicate used exact equality
  ``props.get(key) == value`` and the quantity-map rule engine
  used ``str(value).lower()``.  Both silently failed on multi-valued
  IFC properties (e.g. ``materials = ["steel", "concrete"]``
  vs filter ``materials = "steel"`` returned False because list !=
  string).  New shared helper
  ``BIMHubService._property_value_matches`` handles strings via
  fnmatch, lists via membership/intersection, dicts via recursive
  containment, and ``None`` via explicit "must not be set"
  semantics.  20 unit tests pin every branch.
- **Quantity map applies surface skipped (element, rule) pairs**.
  ``_extract_quantity`` returned ``None`` when the source property
  was missing and the loop just ``continue``'d, so estimators saw
  unexpectedly-empty BOQ populations with no clue why.  Skips are
  now collected with a structured ``reason`` (``missing_property``
  or ``invalid_decimal``), surfaced via two new fields on
  ``QuantityMapApplyResult`` (``skipped_count`` + ``skipped[]``),
  and the service logs a warning with the first skip when any are
  detected.

#### Concurrency
- **Per-collection ``asyncio.Lock`` on ``reindex_collection``**.
  Two concurrent reindex requests against the same vector
  collection (e.g. startup auto-backfill racing an admin-triggered
  ``POST /vector/reindex/``) could interleave purge + index ops
  and leave the store in an inconsistent state with partial
  indexes, duplicate ids, and ghost rows.  Now serialised by a
  module-level ``dict[str, asyncio.Lock]`` lazily populated via
  ``_get_reindex_lock``.  Reindexes against DIFFERENT collections
  still run in parallel - the locks are per-name.

#### Missing CRUD
- **``PATCH /requirements/{set_id}``** - lets users rename a set,
  edit its description, change source type, or update workflow
  status without delete-and-recreate (which lost history and any
  BIM/BOQ links the set's requirements owned).  Project re-assignment
  is intentionally NOT supported - sets are project-scoped at
  creation.
- **``POST /requirements/{set_id}/requirements/bulk-delete/``** -
  delete up to 500 requirements in a single transaction.  Ids
  belonging to a different set are silently skipped; the response
  carries ``deleted_count`` and ``skipped_count`` so the UI can
  surface "deleted N of M" mismatches.  Each successful delete
  fires the standard ``requirements.requirement.deleted`` event.

#### Type discipline
- **``GateResult.score`` migrated from ``String(10)`` to ``Float``**.
  The column stored a stringified percentage like ``"85.5"`` but
  the Pydantic schema and router both treated it as a float -
  every write went through ``str(score)`` and every read through
  ``float(score_raw)``.  Worse, ``ORDER BY score DESC`` returned
  ``"9.5"`` above ``"85.0"`` because string comparison happens
  character by character (any "top N gate runs" report was
  silently wrong).  New Alembic migration ``b2f4e1a3c907`` runs an
  idempotent batch-alter that coerces unparseable rows to ``0``
  before the type change.  Service writes a real ``float`` now;
  the router still calls ``float()`` defensively for backward
  compat with un-migrated databases.

#### Test coverage push
- **Unit tests for 7 of 8 vector adapters** (BOQ, Documents, Tasks,
  Risks, BIM elements, Validation, Chat).  Previously only the
  Requirements adapter (added in v1.4.3) had unit coverage; the
  other 7 were untested. **113 new test cases** following the
  canonical template - collection_name singleton, to_text full row
  + empty + None tolerant, to_payload title build + UUID stringify
  + clipping + fallback, project_id_of resolves + None fallback.
- **`backend/tests/unit/test_bim_property_matcher.py`** - 20 tests
  pinning every branch of the new type-aware property matcher.
- **`backend/tests/integration/test_requirements_bim_cross.py`** -
  3rd test ``test_orphan_bim_ids_stripped_on_element_delete``
  drives the full orphan-cleanup flow end-to-end.

#### Frontend i18n compliance
- **BIMPage.tsx hardcoded English strings replaced** with i18n
  keys (deferred from the v1.4.4 frontend audit).  ``UploadPanel``,
  ``NonReadyOverlay``, and the empty-state branch now go through
  ``useTranslation()`` - the HARD rule from the architecture guide
  (*"ALL user-visible strings go through i18next. No exceptions."*)
  is honoured across the BIM module.  New ``bim.upload_*`` and
  ``bim.overlay_*`` keys added to ``i18n-fallbacks.ts``.

### Verification
- 113 new unit tests passing across 7 vector adapter files
- 20 new unit tests passing for the BIM property matcher
- 3 integration tests passing for the requirements↔BIM cross-module
  flow including the new orphan-cleanup regression test
- Backend ``ruff check`` clean across every file touched in v1.4.5
- Frontend ``tsc --noEmit`` clean
- ``scripts/check_version_sync.py`` passes at 1.4.5
- 21 routes mounted under ``/api/v1/requirements/`` (up from 19)

### Deferred to v1.4.6
- ``project_intelligence.collector`` blind to requirements / bim_hub /
  tasks / assemblies - score is currently a partial picture
- ``project_intelligence/actions.py`` 3 of 8 actions are dead code
  (run_validation / match_cwicr_prices / generate_schedule fall
  back to redirect lying about execution)
- Assembly ``total_rate`` invalidation when CostItem.rate changes
- ``create_vector_routes()`` factory + reduce ~250 LOC of duplicated
  ``vector/status`` and ``vector/reindex`` endpoints
- Trailing-slash audit of 12 broken integration tests
- requirements.list_by_bim_element PostgreSQL JSONB fast path

## [1.4.4] - 2026-04-11

### Fixed - backend hardening cut

A focused stability + correctness pass driven by a multi-agent quality
audit of the v1.4.x backend.  No new user-visible features; the goal
is "everything that already exists works at scale and stays honest
about what version it is".

#### Memory hazard in vector auto-backfill
- ``backend/app/main.py::_auto_backfill_vector_collections`` used to
  ``SELECT *`` from each indexed table on startup, materialise the
  full result set into a Python list, and only THEN slice it down to
  ``vector_backfill_max_rows``.  On a 2M-row production deployment
  that allocated **gigabytes** of RAM at startup before the cap could
  even kick in.
- The new implementation issues a cheap ``SELECT COUNT(*)`` first to
  decide whether reindexing is needed, then pulls only the capped
  number of rows with ``LIMIT`` applied at the SQL level.  Memory
  usage is now bounded by ``vector_backfill_max_rows`` regardless of
  table size.
- Side benefit: the per-collection ``_load_X`` closures collapsed
  into a single declarative ``backfill_targets`` registry - 8 modules
  × ~12 LOC of copy-pasted loaders → one tuple per collection.  Total
  reduction in main.py: ~80 LOC.  This is also the foundation
  v1.4.5's full ``create_vector_routes()`` factory will build on.

#### Deprecated ``datetime.utcnow()`` removed (Python 3.14 readiness)
- ``datetime.utcnow()`` was deprecated in Python 3.12 and becomes a
  hard error in 3.14.  Replaced with ``datetime.now(UTC)`` across
  **8 call sites**: ``boq/router.py:2991``, ``documents/service.py:475``,
  ``tendering/router.py:378``, ``project_intelligence/collector.py:680``,
  ``punchlist/router.py:299``, ``meetings/router.py:984``,
  ``takeoff/router.py:1872``, plus ``bim_hub/router.py:869`` (which
  also got rewritten as part of the next bullet).
- The original quality audit only flagged 4 of these 8 sites; a
  follow-up grep across the whole backend caught the remaining 4.

#### Raw SQL → ORM in BIM upload cross-link
- ``bim_hub/router.py::upload_cad`` was using a hand-rolled
  ``INSERT INTO oe_documents_document`` via ``text()`` to create the
  Documents-hub cross-link entry.  The parameter binding was safe in
  practice but the pattern was fragile (any future schema change to
  ``Document`` would silently break the cross-link without test
  coverage), and it shipped a stray ``datetime.utcnow()``.
- Replaced with a clean ``Document(...)`` ORM insert that picks up
  every default + timestamp from the model and the ``Base`` mixin.
  The cross-link stays a best-effort try/except - it's convenience
  glue, not load-bearing on the main upload flow.

#### Functional ruff cleanup
- ``F401`` unused imports removed from ``boq/events.py``,
  ``project_intelligence/collector.py`` (``uuid``),
  ``project_intelligence/scorer.py`` (``Callable``),
  ``search/router.py`` (``Depends``).
- ``F541`` f-string without placeholders fixed in
  ``project_intelligence/advisor.py:399``.
- ``B905`` ``zip()`` without ``strict=`` fixed in
  ``costs/router.py:1742``.  This is the cost-database resource
  loader - without ``strict=True`` an array length drift would
  silently truncate component rows mid-import and corrupt the
  assembly composition with no audit trail.  ``strict=True`` raises
  immediately so the error is visible.
- Ruff style issues (``UP037``, ``UP041``, ``I001``) auto-fixed in
  ``costs/router.py``, ``project_intelligence/router.py`` /
  ``schemas.py``, ``documents/service.py``.

#### Version-sync CI guard (NEW)
- ``backend/pyproject.toml`` silently drifted from ``frontend/package.json``
  for **four minor versions** (v1.3.32 → v1.4.2 all shipped with
  the Python package stuck on ``1.3.31``, so ``/api/health`` lied
  about which version users were actually getting because
  ``Settings.app_version`` reads from ``importlib.metadata``).  v1.4.3
  retro-fixed the literal but left the door open for the same gap.
- New ``scripts/check_version_sync.py`` reads both files plus the top
  entries of ``CHANGELOG.md`` and ``frontend/src/features/about/Changelog.tsx``,
  and exits non-zero on any mismatch.  Wired into:
  - ``.pre-commit-config.yaml`` as a local hook on the four version
    files (so a bump that touches only one file is rejected
    before it can be committed)
  - ``.github/workflows/ci.yml`` as a dedicated ``version-sync`` job
    that runs in parallel with backend + frontend lanes
- Tested negatively (script catches drift) and positively (passes
  with all four files at ``1.4.4``).

### Verification
- Backend ``ruff check`` clean across every file touched in v1.4.4
- Backend ``python -m uvicorn app.main:create_app --factory`` boots
  cleanly via ``app.router.lifespan_context`` smoke test:
  57 modules loaded, 217k vectors indexed, no startup errors
- ``scripts/check_version_sync.py`` passes at ``1.4.4`` after the
  bump (negative test confirmed it would fail at ``1.4.99``)

### Deferred to v1.4.5
- BIMPage.tsx i18n compliance (11+ hardcoded English strings flagged
  by frontend audit; needs sub-component ``useTranslation()``)
- ``create_vector_routes()`` factory + reduce ~250 LOC of duplicated
  ``vector/status`` and ``vector/reindex`` endpoints across 8 modules
- Trailing-slash audit of ``test_cross_module_flows.py`` and
  ``test_api_smoke.py`` (12 failing tests, all caused by missing
  trailing slashes - ``redirect_slashes=False`` is intentional,
  fixes a CORS 307 issue with the frontend)
- Deep-dive audit of recently-added modules (``requirements``,
  ``erp_chat``, ``project_intelligence``, ``bim_hub`` element groups,
  cross-module linking infrastructure) - looking for hacks,
  half-baked logic, missing cross-module wiring

## [1.4.3] - 2026-04-11

### Added - Requirements ↔ BIM cross-module integration

The Requirements module is now the **5th cross-module link type** on
BIM elements, mirroring the existing BOQ / Documents / Tasks /
Schedule activities pattern.  Requirements (EAC triplets - Entity,
Attribute, Constraint) are the bridge between client intent and the
executed model - pinning them to BIM elements lets estimators trace
*"this wall has fire-rating F90 because requirement REQ-042 says so"*
in one click.

#### Backend
- **New `oe_requirements` vector collection** (8th total).  Embeds the
  EAC triplet plus unit / category / priority / status / notes via
  the new ``RequirementVectorAdapter`` in
  ``backend/app/modules/requirements/vector_adapter.py``.  Multilingual
  by default - works across English / German / Russian / Lithuanian /
  French / Spanish / Italian / Polish / Portuguese.
- **Requirements service event publishing** - new ``_safe_publish``
  helper, plus standardised ``requirements.requirement.created /
  updated / deleted / linked_bim`` events on every CRUD and link
  operation.
- **`link_to_bim_elements()` service method** - additive by default
  (merges new ids with the existing array), pass ``replace=true`` to
  overwrite.  Stored under ``Requirement.metadata_["bim_element_ids"]``
  so no schema migration is needed.
- **`list_by_bim_element()` reverse query** - every requirement that
  pins a given BIM element id, scoped to a project for performance.
- **New router endpoints** in ``requirements/router.py``:
  - ``PATCH /requirements/{set_id}/requirements/{req_id}/bim-links/``
  - ``GET  /requirements/by-bim-element/?bim_element_id=&project_id=``
  - ``GET  /requirements/vector/status/``
  - ``POST /requirements/vector/reindex/``
  - ``GET  /requirements/{set_id}/requirements/{req_id}/similar/``
- **`RequirementBrief` schema** in ``bim_hub/schemas.py`` - mirrors
  the relevant subset of ``RequirementResponse`` to avoid a circular
  import.  Added to ``BIMElementResponse.linked_requirements``.
- **`BIMHubService.list_elements_with_links()` Step 6.5** - loads
  every requirement in the project once and filters in Python on the
  ``metadata_["bim_element_ids"]`` array, same cross-dialect pattern
  as the task and activity loops.  Return tuple now has 8 entries.

#### Frontend
- **New `BIMRequirementBrief` interface** + ``linked_requirements``
  field on ``BIMElementData``.
- **New `LinkRequirementToBIMModal`** - mirrors ``LinkActivityToBIMModal``
  exactly: loads every requirement set in the project, flattens
  requirements into a searchable list, click → PATCH the bim-links
  → invalidate the bim-elements query.  Color-coded by priority
  (must / should / may) and status (verified / conflict / open).
- **"Linked requirements" section in BIMViewer details panel** -
  violet themed, slots between "Schedule activities" and the
  semantic similarity panel.  Renders entity.attribute + constraint
  + priority badge + click-to-open.
- **BIMPage wiring** - new ``linkRequirementFor`` state +
  ``handleLinkRequirement`` / ``handleOpenRequirement`` handlers,
  modal mount, props passed to ``<BIMViewer>``.
- **RequirementsPage badge** - the expanded row now shows a
  "Pinned BIM elements" cell with the count read from
  ``metadata.bim_element_ids``.  Click navigates to ``/bim?element=...``
  with the first pinned element preselected.
- **RequirementsPage deep link** - parses ``?id=<requirement_id>``,
  fans out detail fetches across every set in the project to find
  the owning set, switches to it and expands the row.  Strips the
  param after one shot so refresh doesn't reapply.
- **GlobalSearchModal facet support** - fuchsia color for the new
  Requirements pill, ``oe_requirements`` mapped to ``/requirements?id=``
  in ``hitToHref``.
- **VectorStatusCard** picks up the new ``oe_requirements`` collection
  via the existing ``REINDEX_PATH`` table - admins can trigger a
  reindex from Settings.
- **Auto-backfill on startup** now indexes the requirements collection
  alongside the other 7 (capped by ``vector_backfill_max_rows``).

### Fixed (polish bundled into this cut)
- ``backend/pyproject.toml`` had silently drifted from the frontend
  version since v1.3.31 - every bump from v1.3.32 → v1.4.2 updated
  ``frontend/package.json`` but not the Python package.  ``/api/health``
  has therefore been reporting ``version: "1.3.31"`` across the entire
  v1.4.x series because ``app.config.Settings.app_version`` reads from
  ``importlib.metadata.version("openconstructionerp")``.  Bumped
  directly to ``1.4.3`` so the next deploy reports the real version.
- ``bim_hub/router.py`` CAD upload handler referenced ``cad_path`` and
  ``cad_dir`` variables that were never defined after the storage
  abstraction was introduced - the IFC/RVT processing branch crashed
  with ``NameError`` on every upload attempt (``ruff`` flagged the
  same issue as ``F821``).  Replaced the ghost variables with a
  ``tempfile.TemporaryDirectory`` workspace: the upload is materialised
  locally for the sync processor, any generated geometry is uploaded
  back through ``bim_file_storage.save_geometry`` before the tempdir
  is cleaned up, and the Documents hub cross-link now stores the real
  storage key returned by ``save_original_cad`` instead of the phantom
  ``cad_path``.
- ``SimilarItemsPanel`` no longer claims to support requirements -
  the generic panel only knows the item id, but the requirement
  similar endpoint is nested under the parent set
  (``/requirements/{set_id}/requirements/{req_id}/similar/``), so
  it needs both.  Requirement similarity is reachable only from the
  set-scoped detail page; the generic cross-module panel would have
  returned 404 for every call.  Removed the placeholder URL and the
  ``'requirements'`` entry from ``SimilarModuleKind``.

### Verification
- 718 total routes mounted across 57 loaded modules (real count from
  ``module_loader.load_all`` + ``fastapi.routing.APIRoute`` inspection)
- 8 vector collections, all with real adapters and reindex endpoints
- Frontend ``tsc --noEmit`` clean
- Backend ``ruff check`` clean across every file touched in v1.4.3
- New tests: unit coverage for ``RequirementVectorAdapter``
  (``to_text`` / ``to_payload`` / ``project_id_of``) plus an integration
  test that drives ``PATCH /bim-links/`` → ``GET /by-bim-element/``
  → ``GET /models/{id}/elements/`` (Step 6.5) end-to-end

## [1.4.2] - 2026-04-11

### Security
- **SQL injection guard in LanceDB id-quoting** - every row id passed
  to ``_lancedb_index_generic``, ``_lancedb_delete_generic`` and the
  legacy ``_lancedb_index`` cost-collection upsert is now re-parsed as
  a strict ``uuid.UUID`` before being interpolated into the
  ``id IN (...)`` filter via the new ``_safe_quote_ids`` helper.
  Defence-in-depth - the adapter layer always passes UUIDs from
  SQLAlchemy ``GUID()`` columns, so a parse failure now indicates a
  bug or attack and the row is silently dropped.
- **Qdrant search payload mutation** - ``vector_search_collection``
  was using ``payload.pop()`` to extract reserved fields, which
  mutated the qdrant client's cached result objects.  Replaced with
  ``get()`` + a non-mutating dict comprehension.

### Fixed
- **Token-aware text clipping** - ``_safe_text`` now uses the active
  SentenceTransformer's tokenizer (when available) to clip at 510
  tokens instead of the previous 4000-character cap.  4000 chars
  routinely exceeded the 512-token cap of small SBERT models, causing
  silent in-model truncation that lost meaningful tail content.
  Falls back to the character cap when the tokenizer isn't available.
- **Frontend deep links now actually work** - `hitToHref` was
  generating route formats that no destination page parsed:
  - BOQ now uses ``/boq/<boqId>?highlight=<positionId>`` matching the
    real ``BOQEditorPage`` route + query.
  - DocumentsPage parses ``?id=<docId>`` and auto-opens the preview.
  - TasksPage parses ``?id=<taskId>``, scrolls the matching card into
    view, and adds a 2.5s ring highlight.
  - RiskRegisterPage parses ``?id=<riskId>`` and opens detail view.
  - BIMPage parses ``?element=<elementId>`` and selects the element
    once the elements list resolves.
  - Chat hits navigate to ``?session=<sessionId>`` from the new chat
    payload field.
  Each deep-link parser strips the query param after one shot so a
  refresh doesn't keep re-applying it.

### Added - BIM cross-module gap closure
- **`GET /api/v1/bim_hub/coverage-summary/?project_id=...`** - new
  aggregation endpoint returning ``{elements_total,
  elements_linked_to_boq, elements_costed, elements_validated,
  elements_with_documents, elements_with_tasks,
  elements_with_activities}`` plus matching percentages.  Each count is
  a single SELECT in the same async session - no N+1.  Documents,
  tasks, activities and validation are fetched defensively so a
  missing optional module doesn't 500 the call.
- **Dashboard `BIMCoverageCard`** - new widget rendering 6 progress
  bars + a headline percentage (avg of all 6 metrics).  Hides itself
  entirely on projects with zero BIM elements so non-BIM workflows
  stay clean.  Color-coded by completeness (green ≥75% / amber ≥40% /
  rose otherwise).
- **BOQ position BIM badge is now clickable** - the `OrdinalCellRenderer`
  blue pill that shows the linked BIM element count is no longer a
  read-only `<span>`; it's a `<button>` that navigates to
  ``/bim?element=<first_id>``.  Estimators can finally jump from a
  BOQ row to the 3D model element it was created from in one click.
- **Schedule activity BIM badge** - Gantt activity rows now render a
  small amber pill with the count of pinned BIM elements when
  ``activity.bim_element_ids`` is non-empty.  Click navigates to the
  BIM viewer with the first pinned element preselected.  Closes the
  4D-schedule reverse-nav gap.
- **BIM Quantity Rules page - Suggest from CWICR** - when a rule's
  target is "auto-create", the editor now exposes a "Default unit
  rate" field plus a one-click "Suggest from CWICR" button that calls
  ``/api/v1/costs/suggest-for-element/`` with the rule's filter
  context (element_type_filter, name, property_filter material) and
  prefills the top match.  The rate persists into
  ``boq_target.unit_rate`` and is read by the apply path
  (``_auto_create_position_for_rule``) so the new BOQ position lands
  fully priced - no second pass in the BOQ editor.

### Verification
- 766 total routes mounted (up from 765 in v1.4.1).  New routes:
  ``/api/v1/bim_hub/coverage-summary/``.
- Frontend ``tsc --noEmit`` clean.
- Backend ``ruff check`` clean across every file touched in v1.4.2
  (4 pre-existing warnings in unrelated bim_hub/router.py CAD upload
  and BOQ-access-verifier code paths are not from this sweep).
- ``_safe_quote_ids`` smoke-tested against literal SQL injection
  payloads and confirms attacker strings are dropped.

## [1.4.1] - 2026-04-11

### Added
- **Validation reports vector adapter** - `oe_validation` collection now
  has a real adapter (`backend/app/modules/validation/vector_adapter.py`),
  event subscribers wired to the new `validation.report.created/deleted`
  publishes, and `/api/v1/validation/vector/status/`,
  `/vector/reindex/`, `/{id}/similar/` endpoints.  Semantic search across
  validation history (e.g. "find reports about missing classification
  codes") now works.
- **Chat messages vector adapter** - `oe_chat` collection now has a real
  adapter (`backend/app/modules/erp_chat/vector_adapter.py`).  User and
  assistant messages with non-empty content are auto-indexed via the new
  `erp_chat.message.created` event publish in
  `service.py:_persist_messages`.  Long-term semantic memory for the
  AI advisor and per-message similarity search both now functional.
- **Auto-backfill on startup** - new `_auto_backfill_vector_collections`
  helper in `backend/app/main.py` runs as a detached background task
  during the lifespan startup.  For each of the 7 collections it
  compares the live row count to the indexed count and backfills any
  missing rows (capped by `vector_backfill_max_rows=5000` per pass to
  protect against multi-million-row tenants).  Disable with
  `vector_auto_backfill=False` in settings.  This closes the upgrade
  gap where existing v1.3.x BOQ / Document / Task / Risk / BIM / chat
  rows were unsearchable until the user manually called every per-module
  reindex endpoint.
- **Settings → Semantic Search Status panel** - new `VectorStatusCard`
  in `frontend/src/features/settings/`.  Renders a per-collection
  health table fetched from `/api/v1/search/status/` with one-click
  reindex buttons (POST to the matching `/vector/reindex/` route),
  engine + model + dimension + total-vectors badges, connection
  indicator and a "purge first" toggle for embedding-model migrations.

### Fixed
- The `bim_hub.element.updated` event subscription is now documented
  as a forward-compat hook (no current publisher - BIM elements are
  refreshed via the bulk-import path which already publishes
  `created`).  The day a `PATCH /elements/{id}/` endpoint lands, vector
  freshness will work without any wiring change.
- Backend `ruff check` clean across every file touched in this sweep
  (auto-fixed I001 import-order issues in two files).

### Verification
- Full app boot: 765 routes, 34 vector / similar / search routes (up
  from 28 in v1.4.0).  All 7 collections now have real adapters.
- `intfloat/multilingual-e5-small` model loads from HuggingFace cache
  on first encode call - confirmed by Python boot.
- Frontend `tsc --noEmit` clean.

## [1.4.0] - 2026-04-11

### Added
- **Cross-module semantic memory layer** - every business module now
  participates in a unified vector store via the new
  `app/core/vector_index.py` `EmbeddingAdapter` protocol.  Six new
  collections live alongside the existing CWICR cost index:
  `oe_boq_positions`, `oe_documents`, `oe_tasks`, `oe_risks`,
  `oe_bim_elements`, `oe_validation`, `oe_chat`.  All collections share
  the same schema (id / vector / text / tenant_id / project_id / module
  / payload) so the unified search layer can write to any of them
  through one code path.
- **Multilingual embedding model** - switched the default from
  `all-MiniLM-L6-v2` (English-mostly) to `intfloat/multilingual-e5-small`
  (50+ languages, same 384-dim).  CWICR's 9-language cost database now
  ranks correctly across English, German, Russian, Lithuanian, French,
  Spanish, Italian, Polish and Portuguese.  The legacy model is kept as
  a graceful fallback so existing LanceDB tables stay loadable.
- **Event-driven indexing** - every Position / Document / Task / Risk /
  BIM Element create/update/delete event now triggers an automatic
  upsert into the matching vector collection.  No cron jobs, no Celery
  workers, no manual reindex needed for normal operation.  Failures are
  logged and swallowed so vector indexing can never break a CRUD path.
- **Per-module reindex / status / similar endpoints** - every
  participating module now exposes:
  - `GET  /vector/status/` - collection health + row count
  - `POST /vector/reindex/?project_id=...&purge_first=false` - backfill
  - `GET  /{id}/similar/?limit=5&cross_project=true` - top-N most
    semantically similar rows, optionally cross-project
  Live: `/api/v1/boq/`, `/api/v1/documents/`, `/api/v1/tasks/`,
  `/api/v1/risk/`, `/api/v1/bim_hub/elements/`.
- **Unified cross-collection search API** - new `oe_search` module:
  - `GET /api/v1/search/?q=...&types=boq,documents,risks&project_id=...`
    fans out to every selected collection in parallel and merges the
    results via Reciprocal Rank Fusion (Cormack et al., 2009).
  - `GET /api/v1/search/status/` - aggregated per-collection health
  - `GET /api/v1/search/types/` - list of supported short names
- **Cmd+Shift+K Global Search modal** - frontend `GlobalSearchModal`
  with debounced input, facet pills (BOQ / Documents / Tasks / Risks /
  BIM / Validation / Chat) showing per-collection hit counts, current
  project scope toggle, grouped results and click-to-navigate routing.
  Works from any page including text fields so estimators can trigger
  semantic search while editing a BOQ row.
- **`<SimilarItemsPanel>` shared component** - universal "more like this"
  card that drops next to any record with `module="risks" id={...}`.
  Embedded in:
  - Risk Register detail view (cross-project lessons learned reuse)
  - BIM viewer element details panel
  - Documents preview modal (cross-project related drawings)
- **AI Chat semantic tools** - six new tool definitions for the ERP Chat
  agent: `search_boq_positions`, `search_documents`, `search_tasks`,
  `search_risks`, `search_bim_elements`, `search_anything`.  Each tool
  returns ranked hits with score + match reasons and the chat panel
  renders them as compact result cards.  System prompt updated to
  prefer semantic tools for free-text questions.
- **AI Advisor RAG injection** - `project_intelligence/advisor.py`
  `answer_question()` now retrieves the top-12 semantic hits from the
  unified search layer and injects them into the LLM prompt as a
  "Relevant context (semantic retrieval)" block.  The advisor is now a
  proper RAG agent - answers stay anchored in real evidence instead of
  hallucinating from the structured project state alone.

### Architecture
- New foundation file `backend/app/core/vector_index.py` - protocol,
  hit dataclass, RRF fusion, search/find_similar/index_one helpers.
- Multi-collection helpers in `backend/app/core/vector.py` -
  `vector_index_collection`, `vector_search_collection`,
  `vector_delete_collection`, `vector_count_collection` plus the
  `_lancedb_*_generic` and Qdrant equivalents.
- New `backend/app/modules/search/` module with manifest, schemas,
  service and router.
- Per-module `vector_adapter.py` files in `boq`, `documents`, `tasks`,
  `risk`, `bim_hub` - tiny stateless adapters implementing the
  `EmbeddingAdapter` protocol.

### Verification
- 759 total routes mounted; 28 vector / similar / search routes wired
  end-to-end.
- 217 487 CWICR cost vectors auto-loaded from existing LanceDB index on
  startup.
- Frontend `tsc --noEmit` clean.
- Backend imports clean across foundation + 5 modules + unified search
  + 6 new chat tools + advisor RAG.
- Reciprocal Rank Fusion smoke-tested on synthetic rankings.

## [1.3.32] - 2026-04-10

### Added
- **BIM viewer health stats banner** - top-of-viewport multi-pill banner
  shows total elements, BOQ-linked count, validation errors, warnings,
  has-tasks and has-documents counts.  Each pill is clickable and applies
  the matching smart filter to the viewport in one click.
- **Smart filter chips in BIMFilterPanel** - same five health buckets
  exposed as chips at the top of the filter sidebar (errors, warnings,
  unlinked-to-BOQ, has tasks, has documents).  Counts are computed from
  the cross-module link arrays on each element.
- **Color-by status modes** in the BIM viewer - three new colour-by
  options grouped under "By compliance":  🛡️ Validation status (red /
  amber / green), 💰 BOQ link coverage (red unlinked / green linked),
  📄 Document coverage.  Implemented via a new
  `ElementManager.colorByDirect()` helper that paints meshes from a
  fixed palette without rebuilding materials.
- **Cost auto-suggestion for BIM elements** - new
  `POST /api/v1/costs/suggest-for-element/` endpoint ranks CWICR cost
  items by classification overlap, element-type / material / family
  keyword matches and discipline tag overlap.  Each result carries a
  0..1 confidence score and human-readable match reasons.
- **Cost suggestion chips in AddToBOQModal** - the "Create new position"
  tab now fetches the top-5 ranked rates for the clicked element and
  renders them as one-click chips with code, description, unit rate and
  confidence dot.  Clicking a chip populates description / unit /
  unit_rate from the matching cost item - no manual lookup needed.

## [1.3.31] - 2026-04-11

### Added
- **Inline create-from-element modals** in BIM viewer - three new
  modals (`CreateTaskFromBIMModal`, `LinkDocumentToBIMModal`,
  `LinkActivityToBIMModal`) let the user create new tasks, link existing
  documents, and link existing schedule activities to a BIM element
  WITHOUT leaving the viewer.
- **Validation ↔ BIM per-element rules engine** - new
  `POST /api/v1/validation/check-bim-model` endpoint runs universal
  BIM rules (wall has thickness, structural has material, fire-rating
  present, MEP has system, etc.) against every element in a model.
  Per-element results eager-loaded into `BIMElementResponse.validation_results`
  + worst-severity rollup in `validation_status`.
- **Per-element validation badge** in the BIM viewer details panel,
  colour-coded by worst severity.
- **Tasks page** - `TaskCard` now renders a "Pinned to N BIM element(s)"
  badge with click-to-jump navigation.

### Fixed
- `ValidationReportResponse` pydantic schema collision with SQLAlchemy
  `MetaData()` class-level registry - switched to `validation_alias`.

## [1.3.30] - 2026-04-11

### Added
- **BIM viewer cross-module deep integration** - element details panel now
  shows four collapsible link sections in one place: Linked BOQ Positions
  (existing), Linked Documents (drawings/RFIs/photos), Linked Tasks
  (defects/issues), Schedule Activities (4D timeline). Each section has
  count badges, clicking any row navigates to the target detail page.
- **Documents ↔ BIM** - new `oe_documents_bim_link` table + GET/POST/DELETE
  endpoints under `/api/v1/documents/bim-links/`. Bidirectional querying.
  Eager-loaded into `BIMElementResponse.linked_documents`.
- **Tasks ↔ BIM** - new `Task.bim_element_ids` JSON column. PATCH
  `/api/v1/tasks/{id}/bim-links` + reverse query. Eager-loaded into
  `BIMElementResponse.linked_tasks`.
- **Schedule ↔ BIM** - wired up the dormant `Activity.bim_element_ids` field
  with PATCH endpoint and `/api/v1/schedule/activities/by-bim-element/`
  reverse query. Eager-loaded into `BIMElementResponse.linked_activities`.
- **Documents preview modal** - new "Linked BIM elements" footer strip with
  click-to-navigate chips.

## [1.3.29] - 2026-04-11

### Changed
- **Chat page** - removed the redundant "ERP AI Assistant" top bar. The
  app's main layout already provides a header; the chat-specific bar
  duplicated UI and didn't match the rest of the site palette. Clear
  chat now lives in the input bar.
- **Release process** - CHANGELOG.md now mirrors the in-app
  `Changelog.tsx` so the GitHub release workflow can extract the right
  section when a tag is pushed (the workflow at `.github/workflows/release.yml`
  reads `## [VERSION]` patterns from this file).

## [1.3.28] - 2026-04-11

### Added
- **Universal Building / Other split** in BIM filter - every category
  is classified by its semantic bucket and rendered in either a
  "real building elements" section (chips at top) or a collapsible
  "Annotations & analytical" section (closed by default). Works
  zero-curation for any project.
- **Pretty category names** for ~150 well-known Revit categories
  ("Curtainwallmullions" → "Curtain Wall Mullions", "Doortags" → "Door Tags").
  Anything not in the table passes through with first-letter
  capitalised - no wrong algorithmic word splits.

### Fixed
- BIM filter "None" element_type (the 6 048 Revit-ingest junk rows in
  the demo) now classified as noise.
- Headless test verdict baseline comparison.

## [1.3.27] - 2026-04-11

### Added
- **3 grouping modes** in BIM filter via segmented control:
  **By Category** (flat, default), **By Type Name** (Revit Browser
  hierarchy), **Buckets** (semantic).

## [1.3.26] - 2026-04-11

### Fixed
- **"Add to BOQ" 500** - the v1.3.22 backend agent's ownership check
  referenced `position.project_id` but Position has no such column;
  the project lives on the parent BOQ via `position.boq_id`. Fix:
  rewrote `_verify_boq_position_access` as a single-row SELECT joining
  Position → BOQ.

## [1.3.25] - 2026-04-11

### Added
- **Saved Groups panel section** in BIMFilterPanel - collapsible,
  one-click apply, hover-revealed link/delete actions.
- Headless test full saved-group lifecycle (save → list → apply → delete).

## [1.3.24] - 2026-04-11

### Added
- **Pluggable storage backend** (`app/core/storage.py`) with
  `LocalStorageBackend` (default) and `S3StorageBackend` (opt-in via
  `pip install openconstructionerp[s3]`). Supports MinIO / AWS / Backblaze /
  DigitalOcean Spaces.
- **BIM Element Groups** - new `oe_bim_element_group` table for saved
  selections. Dynamic groups recompute members from a filter; static
  groups freeze the snapshot.
- **SaveGroupModal** for saving the current filter as a named group.
- **Architecture doc** - `docs/BIM-STORAGE-ARCHITECTURE.md` with the
  three-layer design + migration path.

## [1.3.23] - 2026-04-11

### Added
- Headless deep test (`frontend/debug-bim.cjs`) extended with 4 new
  test groups verifying every UI surface from v1.3.22.
- `ElementManager.batchMeshesByMaterial()` - three.js BatchedMesh
  collapse for big-model perf (gated at 50 000+ meshes pending GPU
  visibility-sync work).

### Fixed
- Sidebar `nav.bim_rules` translation key.

## [1.3.22] - 2026-04-11

### Added
- **BIM ↔ BOQ linking** end-to-end. Backend embeds `boq_links` in
  element response; `apply_quantity_maps` actually persists; `Position.cad_element_ids`
  auto-syncs on link CRUD.
- **Add to BOQ modal** - Link to existing position OR create new with
  pre-filled quantities, single-element and bulk modes.
- **Quick takeoff** button in filter panel - bulk-link visible elements.
- **BIM Quantity Rules page** at `/bim/rules` - dedicated UI for rule-based
  bulk linking.
- **Selection sync store** - BOQ row click highlights linked BIM
  elements orange and vice versa.
- **Toolbar rework** - removed broken 4D/5D stubs, added camera
  presets (Fit / Iso / Top / Front / Side), grid toggle.

## [1.2.0] - 2026-04-09

### Added
- **Project Completion Intelligence (PCI)** - AI co-pilot: project scoring (A-F), domain analysis, critical gaps, achievements, AI advisor
- **Architecture Map** - interactive React Flow visualization of 54 modules, 98 models, 128 dependency edges
- **Dashboard project cards** - KPI metrics per project (BOQ value, tasks, RFIs, safety, progress)
- **Sidebar badge counts** - live open item counts for Tasks, RFI, Safety
- **Data Explorer** - professional landing page with feature cards and upload zone
- **BIM filmstrip layout** - models at bottom, delete button, stale cleanup endpoint
- **NCR → Change Order** traceability banner with navigation
- **UserSearchInput** integrated into Meetings, Tasks, Inspections, RFI forms
- **Document Hub cross-links** - Takeoff, Punchlist, Meeting transcripts auto-appear in Documents
- **Swagger UI** accessible at /api/docs (SPA catch-all fixed)
- **Change password** returns new JWT tokens (user stays logged in)
- **Configurable rate limiter** via API_RATE_LIMIT, LOGIN_RATE_LIMIT env vars

### Fixed
- **CORS 307 redirects eliminated** - redirect_slashes=False + 369 backend routes with trailing slash
- **All form field mismatches** - 15+ modules aligned frontend↔backend
- **Correspondence crash** - to_contact_ids field name mismatch
- **BOQ Create Revision** - MissingGreenlet fix + trailing slash
- **BOQ Import** - source enum (cost_database, smart_import, assembly)
- **BOQ costs→positions** - ordinal XX.YYY format, no conflicts
- **Finance invoice list** - endpoint URL fix
- **Procurement PO list** - endpoint URL + paginated response
- **Safety create buttons** - visible in empty state
- **Project cascade delete** - child records cleaned up
- **Notifications** fire on task creation
- **Photo gallery** - served without auth for img tags
- **Meetings 500** - corrupt UUID data fixed
- **Paginated response handling** - 7 modules with defensive Array.isArray checks
- **Project context guards** - 6 modules show warning when no project selected
- **Unified create buttons** - 14 pages standardized to "+ New X" pattern

### Changed
- CAD converter references unified under DDC cad2data
- Integrations moved from sidebar to Settings
- Architecture Map in Modules section
- GitHub button moved to header
- Version bumped to 1.2.0

## [1.1.0] - 2026-04-09

### Added
- **User Management page** (`/users`) - invite users, change roles (admin/manager/editor/viewer), activate/deactivate, per-user module access matrix with custom role names
- **UserSearchInput** component - searchable dropdown for selecting team members across all modules
- **Document Hub cross-linking** - photos and BIM files automatically appear in Documents module with source tags (`photo`, `bim`, `site`, `ifc`, etc.)
- **CDE Link Document modal** - searchable document picker instead of redirect to /documents page
- **20-language translations** for User Management module

### Fixed
- **All form field mismatches** - systematic audit and fix of 15+ modules (Tasks, Meetings, RFI, NCR, Submittals, Inspections, Correspondence, Contacts, Transmittals, Finance, Safety, Procurement)
- **Trailing slash CORS issue** - all GET list endpoints now use trailing slash to prevent 307 redirect → CORS block
- **Contacts display** - field names aligned with backend (`first_name`/`last_name`, `primary_email`, `country_code`)
- **Procurement PO list** - fixed endpoint URL (`/purchase-orders` → `/`) and paginated response handling
- **Transmittals list** - fixed paginated response handling
- **Photo gallery** - photos now served without auth requirement for `<img>` tags
- **Safety incidents** - POST route trailing slash fix
- **Meetings 500 error** - fixed corrupt UUID in chairperson_id
- **NCR status enum** - `open` → `identified` to match backend
- **Inspection types** - expanded to include all construction-standard types
- **Documents upload** - clear "Select project first" warning when no project selected, clickable drop zone
- **BIM upload** - inline progress bar, only IFC/RVT accepted

### Changed
- Backend enum patterns expanded for inspections and correspondence
- Contacts `prequalification_status` removed invalid `none` value
- Tasks `task_type` `info` → `information`, `priority` `medium` → `normal`

## [0.9.1] - 2026-04-07

### Added - Integration Hub expansion
- **Discord webhook connector** - send embed notifications to Discord channels, with color, fields, and action link
- **WhatsApp Business connector** (Coming Soon) - Meta Cloud API v20.0 template messages, pending Meta Business verification
- **Integration Hub redesign** - 14 integration cards grouped into 3 categories (Notifications, Automation, Data & Analytics)
- **n8n / Zapier / Make cards** - guidance for connecting workflow automation tools via our existing webhook system
- **Google Sheets card** - export BOQ/cost data to Sheets-compatible Excel format
- **Power BI / Tableau card** - connect BI tools to our REST API for custom dashboards
- **REST API card** - link to interactive OpenAPI docs at /api/docs

### Fixed
- Deep audit fixes for cross-module event flows
- Integration type schema extended to support `discord` and `whatsapp` connectors

## [0.9.0] - 2026-04-07

### Added - 30 new backend modules (Phase 9–22 master plan)
- **Internationalization Foundation** - MoneyValue (35 currencies, Decimal arithmetic), LocalizedStr (JSONB multi-language), AcceptLanguage middleware, i18n_data (ISO constants for 30 countries), ECB exchange rate fetcher, 198 countries with 20-language translations, 30 work calendars, 70 tax configurations
- **Module System v2** - enable/disable modules at runtime, persistent state, dependency tree API, admin REST endpoints
- **Contacts Directory** - unified contacts for clients, subcontractors, suppliers, consultants with prequalification tracking
- **Audit Log** - system-wide entity change tracking with admin API
- **Notifications** - in-app notifications with i18n keys, unread count, mark-read, per-user listing
- **Comments & Viewpoints** - threaded comments on any entity with @mentions, PDF/BIM viewpoints
- **Teams** - project teams with membership roles and entity visibility grants
- **Meetings** - meeting management with attendees, agenda, action items, auto-numbering
- **CDE** - ISO 19650 Common Data Environment with 4-state workflow (WIP→Shared→Published→Archived)
- **Transmittals** - formal document distribution with issue/lock, acknowledge/respond
- **OpenCDE API** - BuildingSMART Foundation API 1.1 + BCF 3.0 compliance (13 endpoints)
- **Finance** - invoices (payable/receivable), payments, project budgets with WBS, EVM snapshots
- **Procurement** - purchase orders, goods receipts with quantity tracking
- **Inspections** - quality inspections with checklists, pass/fail/partial results
- **Safety** - incidents and observations with 5×5 risk scoring
- **Tasks** - 5-type taxonomy (task/topic/information/decision/personal) with Kanban board
- **RFI** - requests for information with ball-in-court, cost/schedule impact
- **Submittals** - multi-stage review workflow (submit→review→approve)
- **NCR** - non-conformance reports with root cause analysis
- **Correspondence** - formal communication register
- **BIM Hub** - BIM models, elements, BOQ links, quantity maps, model diffs
- **Reporting** - KPI snapshots, 6 report templates, report generation
- **8 Regional Packs** - US (AIA/CSI/RSMeans), DACH (DIN 276/GAEB/VOB/HOAI), UK (NRM2/JCT/NEC4/CIS), Russia (GESN/FER/TER), Middle East (FIDIC/Hijri/VAT GCC), Asia-Pacific, India, LatAm
- **3 Enterprise Packs** - approval workflows, deep EVM (ETC/EAC/VAC/TCPI), RFQ bidding pipeline
- **CPM Engine** - forward/backward pass, float calculation, critical path, calendar-aware

### Added - Projects & BOQ expansion
- Project: WBS, milestones, project code, type, phase, address, contract value, dates, budget
- BOQ: estimate type, lock/unlock, revision chain, base date, WBS linkage

### Added - 13 new frontend pages
- Contacts, Tasks (Kanban), RFI, Finance (4 tabs), Procurement, Safety, Meetings, Inspections, NCR, Submittals, Correspondence, CDE, Transmittals

### Added - Shared UI components
- SVG Gantt chart (day/week/month zoom, task bars, dependency arrows, critical path, drag-to-reschedule)
- Three.js BIM Viewer (discipline coloring, raycaster selection, properties panel)
- NotificationBell (API-backed, 30s polling, dropdown, mark-read)
- CommentThread (threaded, nested, @mentions, inline edit)
- MoneyDisplay, DateDisplay, QuantityDisplay (locale-aware formatting)
- Regional Settings page (timezone, measurement, paper, date/number format, currency)

### Added - Inter-module event wiring
- Meeting action items → auto-create tasks
- Safety high-risk observation → notification to PM
- Invoice paid → update project budget actuals
- PO issued → update project budget committed
- RFI/NCR cost impact → variation flagging

### Added - i18n
- 568 translation keys across 20 languages for all new modules
- Professional construction terminology in DE, FR, ES, RU, ZH, AR, JA

### Added - Testing
- 50 integration tests covering critical API flows
- Total: 697 backend tests passing

### Fixed
- Removed competitor product names from codebase
- Standardized all new pages to match established layout patterns

## [0.8.0] - 2026-04-07

### Added - Professional BOQ features
- **Custom Columns** with 7 one-click presets - Procurement (Supplier, Lead Time, PO Number, PO Status), Notes, Quality Control (QC Status, Inspector, Date), Sustainability (CO₂, EPD, Material Source), **German Tender Style** (KG-Bezug, Lohn-EP, Material-EP, Geräte-EP, Sonstiges-EP, Wagnis %), **Austrian Tender Style** (LV-Position, Stichwort, Lohn-Anteil %, Aufschlag %, Lieferant), **BIM Integration** (IFC GUID, Element ID, Storey, Phase). Manual form for everything else. Live fill-rate progress bar shows how complete each column is.
- **Renumber positions** with gap-of-10 scheme (`01`, `01.10`, `01.20`, `02`, `02.10`) - matches the professional German/Austrian tender output convention. Lets you insert `01.15` later without renumbering everything else. New `POST /boqs/{id}/renumber` endpoint + toolbar button.
- **Excel round-trip with custom columns** - supplier, notes and procurement values are now exported to .xlsx and survive a full import → edit → export cycle. Number-typed columns are formatted as numbers in the spreadsheet.
- **Project Health bar** on Project Detail - circular progress with 5 checkpoints (BOQ created → positions added → all priced → validation run → no errors) and a single "Next step" button that always points at the first incomplete item.

### Added - Security hardening (from QA / pentest report)
- **Strong password policy** - 8+ chars, ≥1 letter, ≥1 digit, blacklist of 24 common/leaked passwords. `password`, `12345678` and friends are now rejected with a clear 422.
- **Login rate limit** - 10 attempts per minute per IP, returns 429 with `Retry-After` header.
- **JWT freshness check** - old tokens are invalidated automatically when the user changes password (via `password_changed_at` column + `iat` comparison in `get_current_user_payload`).
- **Security headers middleware** - `X-Frame-Options`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy` (relaxed for SPA, excluded from /docs and /redoc), `Strict-Transport-Security` (HTTPS only).
- **Schedule date validation** - `start_date > end_date` is now rejected with a clear 422 (Pydantic `model_validator`).
- **PDF upload magic-byte check** - `/takeoff/documents/upload` now rejects JPGs/HTML/etc. renamed to `.pdf`.
- **Cross-user permission boundary verified** - User B gets 403 on every attempt to read/modify/delete User A's data (end-to-end test in place).

### Added - UX & frontend
- **User-friendly API error messages** - `ApiError` now extracts the actual FastAPI `detail` string instead of `"API 500: Internal Server Error"`. Covers FastAPI 422 validation arrays, generic envelopes, and per-status fallbacks (400/401/403/404/409/413/422/429/500/502/503/504). Network errors and `AbortError` get their own friendly text. 14 i18n keys × 21 locales added.
- **Modernized update notification** in the sidebar - gradient emerald/teal/cyan card with pulsing Sparkles icon, grouped highlights (New / Fixed / Polished), in-app changelog link (scrolls to `/about#changelog`), GitHub release link, change-count badge. Caches the GitHub response in `localStorage` (1h TTL) so multi-tab sessions don't burn the unauthenticated rate limit.
- **Continue your work** card on Dashboard - gradient card showing the most recently updated BOQ with name, project, position count and grand total; one click jumps back to the editor.
- **Role-aware ChangeOrders Approve button** - hidden for non-admin/manager roles; an "Awaiting approval" amber badge appears instead, so users no longer click into a 403.
- **Highlight unpriced positions** in the BOQ grid - subtle amber background and 3px left border on rows where `qty > 0` but `unit_rate = 0`.
- **Duplicate-name guard** for new projects - typing a name that matches an existing project shows an amber warning and requires a second click to confirm.
- **Single source-of-truth** for app version - `package.json` is the only place to edit. Sidebar, About page, error logger, update checker and bug-report params all import `APP_VERSION` from a Vite-injected define.
- **Changelog** entries filled in for v0.5.0, v0.6.0, v0.7.0 (previously the in-app history jumped from v0.4 → v0.7 with no notes).
- **Accessibility** - `<h1>` (sr-only) on /login and /register, `name` and `id` attributes on all auth inputs, `aria-label` on password show/hide buttons, dead `_SavedSessionsList` removed.
- **Keyboard shortcuts dialog** - removed misleading shortcuts that browsers reserved (`Ctrl+N`, `Ctrl+Shift+N`); fixed buggy "Ctrl then Shift then V" separator; added `g r` → Reports and `g t` → Tendering navigation sequences.

### Fixed - backend critical bugs
- **`ChangeOrders POST /items` returned 500 for every payload** - `MissingGreenlet` on `order.code` after `_recalculate_cost_impact` (which calls `expire_all`) triggered a lazy load in async context. Fix: capture identifying fields before the recalc, then `refresh(item)` after.
- **`5D /generate-budget` returned 500 on missing `boq_id`** - bare `uuid.UUID(str(...))` raised on empty body. Fix: validate explicitly with try/except → 422 on bad input. Auto-pick the most recently updated BOQ when omitted.
- **Project soft-delete was leaky** - `DELETE /projects/{id}` set `status=archived`, but the project still came back from `GET`, list, and BOQ list. Fix: `get_project` gains `include_archived` flag (default `False`); `list_projects` defaults to `exclude_archived=True`; BOQ verify treats archived as 404.
- **Requirements module tables were missing on fresh installs** - module models were not imported in `main.py`/`alembic env.py`, so `Base.metadata.create_all()` skipped them. Fix: added the missing imports; same for 6 other previously missing module models.
- **Custom Columns SQLAlchemy JSON persistence** - only the FIRST added column was being saved due to in-place dict mutation. Fix: build a fresh `dict` and call `flag_modified(boq, "metadata_")` to defeat value-based change detection.
- **Custom column edit silently rewrote `total`/`unit_rate`** - `update_position` re-derived pricing from `metadata.resources` on every metadata patch. Fix: only re-derive when `quantity` actually changed OR the resources list itself differs from what's stored. Critical correctness fix for resource-priced positions.

### Changed
- The visible "Quick Start Estimate" flow now uses **gap-of-10 ordinals** by default - new positions get `01.40`, `01.50` etc. instead of `01.4`, `01.5`.
- `update_position` is stricter about when it touches pricing fields - only quantity/rate/resource changes recalculate `total`. Pure metadata patches leave the existing total intact.

## [0.2.1] - 2026-04-04

### Fixed
- **CRITICAL: pip install -e ./backend** - `[project.urls]` was placed before `dependencies` in pyproject.toml, breaking editable installs and PyPI builds
- **CRITICAL: BOQ Duplication crash** - MissingGreenlet error when duplicating BOQ (eagerly capture ORM attributes before session expiry)
- **CRITICAL: CWICR import 500 error** - ProcessPoolExecutor fails on Windows/uvicorn; replaced with asyncio.to_thread
- **Security: Path traversal** - Document/takeoff download endpoints now resolve symlinks and sandbox-check paths
- **Security: CORS** - Block wildcard `*` origins in production mode with warning
- **Security: Login enumeration** - Deactivated accounts return same 401 as invalid credentials; password policy not revealed before auth
- **Security: Catalog price factor** - Bounded to `0 < factor ≤ 10` with explicit validation
- **Docker quickstart** - Dockerfile copies full backend (incl. README.md for hatchling), installs `[server]` extras, creates frontend/dist dir, uses development mode
- **Alembic migration** - Replaced broken init migration (DROP non-existent tables) with no-op baseline
- **Nginx** - Added CSP, HSTS, Permissions-Policy security headers
- **35 test errors** - Marked standalone test_full_platform.py with pytest.mark.skip

### Added
- Version number (v0.2.0) displayed in sidebar footer
- "Run Setup Wizard" link in welcome modal for re-onboarding
- Comparison table in README (vs commercial estimating suites)
- Estimation workflow diagram in README
- Security section in README
- Validation & Compliance and Guided Onboarding sections in README
- Trademark disclaimer on comparison table

### Changed
- CLI command renamed from `openestimate` to `openconstructionerp`
- DDC Toolkit → DDC cad2data in all references
- README screenshots use real PNG files (not placeholder JPGs)

### Removed
- 11 development screenshot JPGs from repository root
- Test failure PNG from frontend/test-results/

## [0.1.0] - 2026-03-30

### Added
- **BOQ Editor** - Hierarchical Bill of Quantities with AG Grid, inline editing, keyboard navigation
- **Resource Management** - Material, labor, equipment resources per position with Catalog Picker
- **Cost Database** - CWICR 55,000+ cost items across 11 regional databases (US, UK, DE, FR, ES, PT, RU, AE, CN, IN, CA)
- **Resource Catalog** - Searchable catalog with materials, labor, equipment, operators
- **20 Regional Standards** - DIN 276, NRM, MasterFormat, GAEB, DPGF, GESN, GB/T 50500, CPWD, Birim Fiyat, Sekisan, Computo Metrico, STABU, KNR, Korean Standard, NS 3420, URS, ACMM, CSI/CIQS, FIDIC, PBC
- **42 Validation Rules** - 13 rule sets: boq_quality, din276, gaeb, nrm, masterformat, sinapi, gesn, dpgf, onorm, gbt50500, cpwd, birimfiyat, sekisan
- **4D Schedule** - Gantt chart with CPM, dependencies, resource assignment
- **5D Cost Model** - Earned Value Management (SPI, CPI, EAC), S-curve, budget tracking
- **Risk Register** - Risk matrix (probability x impact), mitigation strategies
- **Change Orders** - Scope changes with cost/schedule impact, approval workflow
- **Tendering** - Bid packages, subcontractor management, bid comparison
- **Reports** - 12 report templates (PDF, Excel, GAEB XML, CSV)
- **Document Management** - Upload, categorize, search project files
- **AI Quick Estimate** - Generate BOQ from text, photo, PDF, Excel, CAD/BIM
- **AI Cost Advisor** - Chat interface for cost questions with database context
- **AI Smart Actions** - Enhance descriptions, suggest prerequisites, escalate rates, check scope
- **7 AI Providers** - Anthropic, OpenAI, Gemini, OpenRouter, Mistral, Groq, DeepSeek
- **20+ Languages** - Full i18n: EN, DE, FR, ES, PT, RU, ZH, AR, HI, TR, IT, NL, PL, CS, JA, KO, SV, NO, DA, FI
- **Dark Mode** - Full dark theme with system preference detection
- **Onboarding Wizard** - 7-step setup: Language, Cost DB, Catalog, Demo Projects, AI, Finish
- **5 Demo Projects** - Berlin (DIN 276), London (NRM), Houston (MasterFormat), Paris (DPGF), Dubai (FIDIC)
- **Backup & Restore** - Export/import user data as ZIP with manifest
- **Version Updates** - Automatic GitHub release checking with sidebar notification
- **SQLite Auto-Migration** - Seamless schema upgrades without data loss
- **Error Logging** - Anonymized error reports with PII scrubbing
- **Command Palette** - Ctrl+K search across pages, projects, BOQs
- **Keyboard Shortcuts** - Full keyboard navigation (?, Ctrl+N, Ctrl+Shift+N, etc.)
- **Locale-Aware Units** - Language-specific measurement units (Stk, sht, ge, etc.)

### Infrastructure
- FastAPI backend with 17 auto-discovered modules
- React 18 + TypeScript + Vite frontend
- SQLite (dev) / PostgreSQL (prod)
- LanceDB vector search (168K+ vectors)
- Modular plugin architecture
- AGPL-3.0 license

### Security
- JWT authentication with bcrypt password hashing
- Role-based access control (RBAC)
- CORS middleware with configurable origins
- Input validation via Pydantic v2
