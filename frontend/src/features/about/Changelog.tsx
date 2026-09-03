// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
   * One summary in plain language. Proper-noun-heavy strings stay in English.
   * Two short sentences at most, ideally one: say what a reader can now do, or
   * what stopped going wrong, in the words that reader would use. Keep a
   * number, a language, a format or a module name where it helps, and leave
   * out the internal mechanism, the file names and why it was hard.
   */
  summary: string;
  tag?: Tag;
}

// Sorted newest to oldest. Sort is enforced at runtime below (semver-aware) so
// out-of-order entries here still display correctly.
//
// RULE: keep the version, date and meaning intact; trim the prose, not the
// facts. Two short sentences at most, in the words a user would use. This rule
// has been the other way round before: it asked for one to two sentences while
// every entry ran to a paragraph, so it was rewritten to describe the
// paragraphs. Those paragraphs are what the page is being trimmed back from.
// The entries from 15.3.0 up read at the new length; the older ones below still
// carry the long form and are left alone as the record of what shipped.
const CHANGELOG: ChangelogEntry[] = [
  {
    version: '16.7.0',
    date: '2026-09-03',
    tag: 'NEW',
    summary:
      'India reads its own numbers. A bill of quantities is grouped in lakh and crore rather than in thousands and millions, ten Indian cases ship with the case library in the four reference languages, and the demo stops pricing its tax with the labour welfare cess standing where GST belongs. A schedule exported from a machine that does not run in English now imports as what was exported: a P6 XER file declares no encoding anywhere in it and the reader ended its ladder in Latin-1, which accepts every byte and raises nothing, so Arabic, Russian, Greek and Hebrew activity names arrived as mojibake, were stored that way, and showed up on a Gantt chart weeks later. The same reader now declines to guess rather than naming a code page on almost no evidence, which it was doing for four hundred and sixty five of roughly seven and a half thousand name shaped samples, and falls to the Western default those files were already getting. An input with something at both ends keeps both of its paddings in Arabic, where the text used to run underneath the icon. Dragging a GAEB file onto the import area now does something instead of silently accepting it. And two checks that were passing without checking anything have been repaired, one satisfied by a route that served nobody and one rendering a single arrangement of a control that has three.',
  },
  {
    version: '16.6.0',
    date: '2026-09-03',
    tag: 'NEW',
    summary:
      'A bill is priced by the country that owns the project. The rate used to come from whichever table was nearest, so a bill could be charged the VAT of the region it sat in rather than of its country, a Brazilian bill could have the project rate applied twice, and an exported bill charged its tax a second time on a total that already carried it. Israel was priced at seventeen percent a year after the rise to eighteen. Kuwait and Qatar levy nothing on construction and now say so in their own languages rather than in English. Twenty two more markets price with their own national method, the six markets we sell a country pack or a demo for that had no method at all now have one, a price analysis opens in the shape its market reads with all six sheets offered, and a bill takes its markup stack from the country of the project itself. Installing a country pack leaves the workspace knowing which country it is in. Eight countries had national rules and no pack that delivered them, three resolved to a compliance pack belonging to somebody else, sixteen country presets promised an example project during onboarding and installed nothing, and a German take-off could not be measured under German rules. Backend linting and the tests that price a bill now run where a failure stops something, and the PostgreSQL test lane is green again after failing 217 of 880 on every run. The GAEB export stops labelling a tax inclusive figure TotalNet, which in a German exchange format means the total before VAT, and the compliance gate names all sixteen rule packs instead of the four it knew by hand.',
  },
  {
    version: '16.5.0',
    date: '2026-09-01',
    tag: 'NEW',
    summary:
      'An estimate can be compared against its own outturn at the level it was written. Field timesheet lines can name the bill position the hours were spent on, supplier invoice lines can name the position the money paid for, and position actuals reports the hours beside the money, labour and plant apart. Neither link is mandatory: a day that covered six items honestly names none of them. Only approved timesheets count and only those that have not been reversed, which is what makes a corrected day net to nothing rather than reporting its hours once in the wrong direction, and the per unit rate divides by what is installed rather than by what was billed, and is blank where no progress has been reported. The value agreed on a variation is recorded rather than inherited: a change requested at 12000 and agreed at 7200 became a variation order for 12000, and the approved amount, the basis it rests on and any departure from the bill the approver saw are now stored, with the mirrored change order no longer carrying a second editable price. A position can record the dispersion around its price, the basis that price rests on and the schedule activity it belongs to. The item code column knew three classification standards where the product ships eighteen, so positions coded in the other fifteen exported an empty code. The country packs stop promising work they did not do: the United Kingdom pack advertised ninety seven checks the engine did not have and published one version while reporting another, the India pack said it preloaded seven cities of rates and shipped one, the Hungarian and Russian packs had no demo project to install, and a Russian estimate had no norm base. Custom KPIs can break down by a key inside a classification and read one estimate at a time. Four database revisions created tables the startup sequence had already built, which stopped the schema moving on any installation that had run once before upgrading while the health report still called it healthy. A project total joined its estimates together instead of adding them. And twelve languages had shipped strings with their diacritics deleted, in some cases across a whole panel, with the check meant to catch it reading the breadth of the damage as evidence that nothing was wrong. And Uzbek is offered in the language picker: the file had shipped for some time but stayed out of the picker while 942 keys still answered in English, with the insights panels and the case library English from end to end, and those bands are translated now.',
  },
  {
    version: '16.4.0',
    date: '2026-08-31',
    tag: 'NEW',
    summary:
      'How a generated PDF looks is a setting rather than a constant. Property development settings carry a document appearance panel that sets the accent colour across the top of an export, the grey of the footer under it, A4, Letter or Legal, the margin in millimetres, the size of the body type, which corner the brand sits in, a footer line in your own wording and whether pages are numbered, with a live preview of the page beside the controls. Only an administrator can save, one button returns everything to the defaults the platform ships with, and a change applies to the next export rather than to the next restart. Raising the body type size moves the headings with it, so a larger document stays a document. One control defers to a layout and the panel now says so: bills of quantities, daily diaries and methodology statements print a title of their own in the header and hold the brand in the opposite corner deliberately, so that the two never sit on top of each other.',
  },
  {
    version: '16.3.0',
    date: '2026-08-30',
    tag: 'NEW',
    summary:
      'PostgreSQL 16 is checked when the server starts rather than assumed, and a working week stored with a day number that does not exist is repaired on the way in, which moves dates on Saudi Arabian projects. Rates that come out of a cost recipe change, and this is the one to read if you keep a cost database: a component carrying no usable quantity used to contribute nothing, count as priced and leave the item reported as fully priced at a rate of zero, and the stored breakdown now adds up to the rate it explains. Records that could not be removed at all can be removed, across six registers, and where a record is held the product now says what is holding it rather than refusing without a reason. The sign-in screen stops telling people their password is wrong when the service is down, every search result carries a real score instead of zero percent, and an unexpected answer from the projects list no longer leaves the browser holding an empty page. Fifty two controls that were written as though they had a hover state now have one. There is a container image again, a module for reinforcement bending schedules that reads and writes the ABS interchange format, and the running product can open the licence texts it ships without a network. The dashboard no longer sends every site\'s coordinates to a weather service on behalf of someone who never asked for a forecast, and what we tell a commercial licensee has been corrected, which a reader who acted on the old wording should know about. The labour rates screen ships a starter set of build-ups instead of opening on an empty picker, and twenty strings that had been English in every language since the day they were written are translated. Signing in is now something you can take back: a session can be ended on its own rather than only by ending all of them, changing a password ends every session rather than only the browser doing the changing, and the list of your own sessions marks the one you are reading it from. Sign-in on the public demo works again, having been refused by the demo read-only guard once a sign-in started writing a session row. And a case page now names the regional pack whose standards its numbers assume, with the button that switches it on.',
  },
  {
    version: '16.2.0',
    date: '2026-08-28',
    tag: 'NEW',
    summary:
      'Maps work again: the basemap now comes from us, with no key to obtain and no quota to exceed, and any module can be found by name without knowing which tab it sits on. Regional packs are in the build at last, an upgraded install no longer calls itself degraded for good, and the dashboard opens cases as two rows with a link to the rest. A report exported as CSV now carries readable column headings rather than raw internal keys, so a script reading that export needs its column names updating once. A KPI can now be defined as data through the API, checked when it is created rather than when it is computed, and creating a production norm no longer fails on a request that carries no materials. A new DEVELOPING.md at the root explains how to build on the platform in one sitting, and says plainly how contributions are taken.',
  },
  {
    version: '16.1.0',
    date: '2026-08-27',
    tag: 'FIX',
    summary:
      'Installing with Docker now works from the commands we publish, and out of date Romanian and Canadian tax rates are corrected on databases that already exist, so amounts on those screens change and go up. Thai, Devanagari and Korean print correctly in plain table cells, which 16.0.0 named as still to come.',
  },
  {
    version: '16.0.0',
    date: '2026-08-26',
    tag: 'MILESTONE',
    summary:
      'Amounts now round to the decimals their own currency really uses, so nothing loses a digit or gains one it cannot settle. The full licence text ships with every build, and Thai, Devanagari and Korean print correctly in document text, with plain table cells still to come. Bengali and Urdu documents still print boxes, for want of a font rather than a fix.',
  },
  {
    version: '15.9.1',
    date: '2026-08-25',
    tag: 'FIX',
    summary:
      'When a partner rule pack does not switch on, the installer now names the exact identifier it needs. Regional languages such as pt-BR and es-MX work everywhere, and the command line reports the version you are really running.',
  },
  {
    version: '15.9.0',
    date: '2026-08-25',
    tag: 'NEW',
    summary:
      'The Canadian contract standard can now be picked on screen, not just recognised behind it. Uzbek, German and Dutch gained thousands of translated strings, and a desktop upgrade no longer hangs on a step that usually does nothing.',
  },
  {
    version: '15.8.0',
    date: '2026-08-25',
    tag: 'NEW',
    summary:
      'A workspace with no cost database now opens on an invitation with two ways to start, instead of an empty screen. The dashboard shows 23 readable cases in a block you can resize or hide, and the case library leads with the market your language speaks for.',
  },
  {
    version: '15.7.0',
    date: '2026-08-25',
    tag: 'NEW',
    summary:
      'The case library grows from 164 walkthroughs to 202, with ten each for Canada, China, Spain and Britain, which had almost none. A project now finds its country rules from the country code it carries, so calendars and payment deadlines stop coming from the wrong country.',
  },
  {
    version: '15.6.1',
    date: '2026-08-25',
    tag: 'FIX',
    summary:
      'A stocktake, a stock reservation or a goods receipt no longer fails with a server error. Awarding a tender package records which submission won, notifies the right people and settles the currency once.',
  },
  {
    version: '15.6.0',
    date: '2026-08-24',
    tag: 'FIX',
    summary:
      'Every document the product generates can now print Chinese correctly. Working calendars match the countries they name, including Canada, Saudi Arabia, the Gulf states and China.',
  },
  {
    version: '15.5.0',
    date: '2026-08-23',
    tag: 'FIX',
    summary:
      'Anyone running one installation with several projects should take this release: a permission gap let someone open a requirement set in a project that was not theirs. Certified payroll and electronic invoice clearance are reachable again, and Persian text has its letters back.',
  },
  {
    version: '15.4.0',
    date: '2026-08-22',
    tag: 'NEW',
    summary:
      'Closing the desktop application no longer interrupts the local database, so the next start is a normal one instead of a long wait that looks like an application that will not open. Modules can now be installed and removed in Settings and chosen during onboarding.',
  },
  {
    version: '15.3.1',
    date: '2026-08-21',
    tag: 'FIX',
    summary:
      'The screen shown while the application starts now names the version it is running, and the copy button includes it. An application that is still starting normally after an upgrade is no longer given up on too early.',
  },
  {
    version: '15.3.0',
    date: '2026-08-21',
    tag: 'FIX',
    summary:
      'A desktop application that had stopped starting works again on its own, because a database that is there but no longer answering is now cleared instead of trusted. Starting the local database on Windows no longer fails on a folder the application had just made.',
  },
  {
    version: '15.2.0',
    date: '2026-08-20',
    tag: 'NEW',
    summary:
      'The Windows installer carries the web view runtime instead of fetching it during setup, so an install no longer depends on reaching Microsoft from a site network, and Windows now offers one installer rather than two that each recorded the same application separately. The update notice names the file that fits the machine it is running on and asks this installation\'s own server rather than GitHub from every browser tab, a purchase order commits against the cost line the estimate priced so committed against remaining stops reading zero on every project, and a bill position can be asked in one row what the estimate allowed, what is committed, what was installed and what left the store. Post-calculation covers material as well as labour and refuses to read an earned total against an actual that does not cover the same lines. A backend that has started and reports that it cannot do its job is no longer indistinguishable from one still coming up, so the window stops opening on top of a server whose every action will fail.',
  },
  {
    version: '15.1.0',
    date: '2026-08-20',
    tag: 'FIX',
    summary:
      'The Windows desktop application starts. 15.0.0 stopped on a missing locales directory before it drew a window, because the catalogue the server reads while starting sits beside the application package rather than inside it, and a test now refuses any release whose frozen build ships less than the wheel declares. Everything else that could block a first run went with it: the server starts where it is allowed to write, ignores a pidfile whose number now belongs to something else, waits for the database to answer before announcing it, asks the cluster on the address family it listens on, and refuses a data directory a new PostgreSQL major cannot open with the routes that keep your data named first. The BCF issue register also stops showing healthy issues as broken pictures, telling a snapshot that failed to load apart from a viewpoint that never carried one.',
  },
  {
    version: '15.0.0',
    date: '2026-08-18',
    tag: 'MILESTONE',
    summary:
      'The product ships for two markets it could previously only describe: nine American playbooks with Texas and California state rules and a weekly certified payroll, and twelve German ones with the statutory VOB/B and BGB payment clocks and the working time record MiLoG section 17 requires. GAEB became a format the product both reads and writes, where a plain X84 export is a Hauptangebot, imported sections keep their hierarchy, and a bill stops claiming prices it does not carry. Markups are now something an estimator can reason about, with a rate per section, bonds priced off a rate card, escalation off an index, and a stack that reports its own contradictions rather than refusing the work. A register that cannot fit on one screen now says so, with a guard that stops a new one shipping silently truncated, measurement from drawings speaks the reader\'s units and digits throughout, and the semantic encoder downloads in the background while telling you which of five states it is in.',
  },
  {
    version: '14.8.1',
    date: '2026-08-12',
    tag: 'NEW',
    summary:
      'The file module is called Documents in all forty languages, and a module can introduce itself in the reader\'s own language. An electronic invoice reads the buyer address from the contact it already names, raises its buyer findings on the screen that now holds the buyer, follows the German profile rules to the letter, and refuses an address that is only a country. Desktop releases answer for their own signatures: a backfill can sign bytes that already shipped, and an unsigned Windows build says so. Lists stop looking complete when they are merely full, totals survive the page envelope, the product serves its own typefaces, and the Spanish and Portuguese locales got their diacritics and their own documented wording back.',
  },
  {
    version: '14.8.0',
    date: '2026-08-11',
    tag: 'NEW',
    summary:
      'A foreman with no signal records the day on the device and it reaches the office exactly once, because every logical day carries a key minted on the device and a redelivery returns the timesheet the first delivery produced rather than writing a second one. The seller identity, tax registration and bank account an electronic invoice cannot be issued without now have a screen, are held once for the company and merged beneath whatever an individual invoice says, and the account is checked against its own ISO 7064 check digits on the way in. An invoice no longer names Germany for a firm that never chose a country, so an invoice with no buyer country is refused under BR-11 instead of exporting a false statement about where a legal person is established. Overdue deadline notifications reach the managers again after one unresolvable row had been silencing the whole sweep on every tick, and Portuguese now reads as European Portuguese rather than Brazilian.',
  },
  {
    version: '14.7.0',
    date: '2026-08-11',
    tag: 'NEW',
    summary:
      'A register can be described inside the product and installed into the running server a moment later, into a module directory belonging to the instance so an upgrade cannot carry it away, with every generated file on screen before anything is written. The three statutory modules that shipped over the API with no screens now have them, along with cost matching, currencies, earned value and the inbound email reader, so every mounted module has a way in from the product. An electronic invoice is checked against the rules a receiver will actually cite and can finally be issued from a screen, carries a different VAT rate on every line, and relates its embedded XML as an alternative the way Factur-X and ZUGFeRD require. A tender in Chile, Colombia and Brazil is priced the way each country reads it, a currency with no minor unit stops printing cents on a public tender, a DXF opens without the converter binary it never needed, a worker day is costed once from whichever field surface recorded it, an upgrade started from inside the product stops reporting a failure while it is still running, and the platform reads in 40 languages, up from 29.',
  },
  {
    version: '14.6.0',
    date: '2026-08-06',
    tag: 'FIX',
    summary:
      'Tabbing from the unit column to quantity in a bill of quantities no longer opens the editor and closes it in the same keystroke, and Shift with Tab now walks backwards in all three hand-written editors instead of forwards. An inspection shows who carried it out by name rather than as an identifier, on the list, in the drawer and in the spreadsheet export, resolving against parties first and people second and keeping a typed name as typed.',
  },
  {
    version: '14.5.0',
    date: '2026-08-05',
    tag: 'NEW',
    summary:
      'A firm can write its own cases instead of only reading ours, the credentials register can finally be opened from inside the product, and the securities that make a contract enforceable are held against the contract itself. Three modules ship for work that crosses borders: invoices filed where a government has to clear them, statutory withholding taken the way the governing statute defines it, and payment deadlines treated the way security of payment law treats them, all three over the API with their screens still to come. A drawing opened in DWG Take Off matches the file it came from again, approving a timesheet no longer fails because of the daywork sheet written after it, and roughly 320 new strings per language reach all 29 languages. The macOS start failure reported against 14.4.0 is not fixed here: the shipped file was read binary by binary and the explanation we had for it is wrong, which is said plainly rather than shipped as a fix.',
  },
  {
    version: '14.4.0',
    date: '2026-08-04',
    tag: 'FIX',
    summary:
      'An upgrade that crosses several releases applies again, after a foreign key name too long for PostgreSQL rolled back every pending revision and left the contracts feature uninstallable there. The sheet register has a screen worth opening, a re-uploaded drawing set now retires the sheets it replaces instead of leaving two of each number both claiming to be current, and the list is ordered and counted in a way the database has to repeat. The assistant reaches live project data whatever provider is behind it, an assembly applied from a template no longer folds an unconverted amount into a converted total, and DWG Take Off frames a drawing by its geometry rather than by its labels, keeps block definitions out of the sheet picker and stops rendering a right angle as ninety radians. The worked example in the bill of quantities paste box shows its columns again, after every tab and newline in it had lost its backslash in English as well as in twelve translations, and the sheets register no longer labels a superseded sheet as the current one in twelve languages.',
  },
  {
    version: '14.3.0',
    date: '2026-08-04',
    tag: 'NEW',
    summary:
      'The parties to a contract can now be seen, added and removed from the contract itself, and the panel says which of the rows the signature block is built from. A contract with nobody in a signing role no longer has a signatory invented from its own title, the compliance gate no longer closes itself and the drawer behind it on any click inside, and removing a party no longer answers with a not found error.',
  },
  {
    version: '14.2.2',
    date: '2026-08-03',
    tag: 'FIX',
    summary:
      'Counted labels now carry every plural form the language they appear in actually uses, instead of dropping to English when one form is missing, and three of them no longer assemble their own English sentence in code before a translator can see it. Demo records that named companies trading in the real world have been rewritten with invented names, the seeded catalogue no longer ships codes with a DEMO prefix, and the money field tooltips are translated.',
  },
  {
    version: '14.2.1',
    date: '2026-08-03',
    tag: 'FIX',
    summary:
      'The desktop app starts its own database on Linux again. On Linux, PostgreSQL names its loadable modules the same way Python names an extension, so the tool that freezes the backend threw all of them away on the way into the Linux installer and the app stopped at "Starting the local database". The build now reads that directory itself and refuses to produce an installer without them.',
  },
  {
    version: '14.2.0',
    date: '2026-08-03',
    tag: 'FIX',
    summary:
      'Choosing a project now moves the whole dashboard onto it, cost items imported without a currency have been given the one their region implies, and analytics panels say there is not enough data instead of drawing a chart of one row. The demo estate reads like a project rather than a fixture, and several hundred strings that were reaching every language as English are translated.',
  },
  {
    version: '14.1.0',
    date: '2026-08-01',
    tag: 'NEW',
    summary:
      'Six registers became places to decide something rather than only look at data, with rates priced as of a date, bids put on the same basis before one is picked, and a matching engine that stores a run for a person to rule on. Stamp templates no longer cross between projects, budget lines carry their own project currency, self-hosted upgrades work again, and module analytics leaves an empty panel empty instead of filling it with plausible looking figures.',
  },
  {
    version: '14.0.0',
    date: '2026-07-29',
    tag: 'NEW',
    summary:
      'Mesh models open in the browser instead of waiting on the server, and rearranging measurements in PDF takeoff no longer runs out of room after enough drops into the same slot. Browsers stop offering saved card details on the add-section field, long catalogue names keep their tail visible in both pickers, the assemblies drag handle is visible before you hover it, and the quickstart Docker build survives a registry that stops answering.',
  },
  {
    version: '12.9.0',
    date: '2026-07-28',
    tag: 'FIX',
    summary:
      'The vector service now installs under the platform data directory instead of the account home, so a container no longer needs its ownership corrected by hand before CAD to cost matching will work, and a permission problem names the path and the reason. Twenty-one record updates stopped marking every loaded object stale, which had been raising errors far from the code that caused them, and the desktop diagnostic no longer reports a healthy PDF reader as broken.',
  },
  {
    version: '12.8.0',
    date: '2026-07-28',
    tag: 'NEW',
    summary:
      'Measurements in PDF takeoff can be arranged freely: dropped below a row and not only above it, dragged into another group, and whole group blocks moved, with the arrangement surviving a reload. Purchase orders and invoices now leave the audit rows they were missing, agreed variation orders count as committed cost, forms save only the fields you actually edited, and the vector service explains why it will not start instead of returning a bare error.',
  },
  {
    version: '12.7.0',
    date: '2026-07-27',
    tag: 'NEW',
    summary:
      'Progress percentages now roll up from the individual positions and weight by design quantity instead of taking the highest reading anywhere, so figures quoted from older reports need regenerating. Large models start drawing almost immediately, purchase orders and subcontracts are checked before they commit money, and the desktop update button no longer answers with command line usage text.',
  },
  {
    version: '12.6.1',
    date: '2026-07-25',
    tag: 'FIX',
    summary:
      'Live notifications and shared editing presence work again: both real-time channels were refusing every connection, so the notification bell only updated on reload and two people on the same position could not see each other. The handshake is now covered by a test in the database gate so it cannot break unnoticed again.',
  },
  {
    version: '12.6.0',
    date: '2026-07-24',
    tag: 'NEW',
    summary:
      'Case studies now open the running demo on the exact module the story is about, so a 4D sequence case lands on the schedule board and a 5D cost model case lands on the BOQ. Sign-in keeps your intended destination too: arriving at the login screen from a deep link returns you to that page after you sign in instead of dropping you on the dashboard.',
  },
  {
    version: '12.5.0',
    date: '2026-07-24',
    tag: 'NEW',
    summary:
      'Every module register can show a Module Insights panel with key counts, a breakdown chart and a build-your-own chart maker, now across dozens of registers, and the long how-it-works explainers fold into a single expandable line. Deadlines gains a cross-module overdue register with an escalation sweep, file approvals gets its own register page with Excel export and workflow notifications, and documents can reconcile a sheet set against the drawing index. Fixes include the correct router base under the /demo prefix, the BOQ resources toggle firing on the first click, and cost bases no longer doubling work names.',
  },
  {
    version: '12.4.0',
    date: '2026-07-23',
    tag: 'NEW',
    summary:
      'The Common Data Environment can adopt an ISO 19650 approval preset and clone it into an editable project route, wired through the setup wizard with a preset library and a training case. Correspondence, RFI and inbound items get a Create task action that pre-fills from the source and tags the task with where it came from. Reporting adds a COBie facility export over the whole asset register, and e-signatures move onto a pluggable provider interface. The six international modules link out to their files, schedule and change orders, and every public case page now carries the home-page header.',
  },
  {
    version: '12.3.0',
    date: '2026-07-23',
    tag: 'NEW',
    summary:
      'Six delivery and authority modules that had a backend but no screens are now fully usable: authority submissions, authority review cycles with an evidence dossier, an e-signature registry, a source-data register, a work-type route classifier and site supervision, each with its guide and worked cases. The Bill of Quantities grid follows the dark theme, PDF takeoff restores and shares the current sheet through the URL, and the scale auto-detect strip stays quiet when idle or once a page is calibrated.',
  },
  {
    version: '12.2.0',
    date: '2026-07-22',
    tag: 'NEW',
    summary:
      'Model review keeps the 3D model in view while checks run, instead of the viewer ballooning off screen when a long report renders. The pipeline builder gains ten ready-to-run templates, a saved-workflow picker that used to be reachable only by URL, and seven new node types, and it now flags steps wired to nothing. Point cloud adds a Groups tool that captures a region with its point count, volume and plan area and sends the quantity straight into a BOQ. Kyrgyz joins the interface languages as a full translation, bringing the count to twenty-eight.',
  },
  {
    version: '12.1.0',
    date: '2026-07-21',
    tag: 'NEW',
    summary:
      'Approval routes get a tenant-wide preset library and a dry-run simulator, interface management links to RFIs and schedule activities, and the CDE adds ISO 19650 roles with a per-project go-live readiness score. National cost bases translate into the market language with a per-row revision id, cases show a compact process row, BOQ positions renumber freely, and the multi-tenant RLS policy is hardened.',
  },
  {
    version: '12.0.1',
    date: '2026-07-19',
    tag: 'NEW',
    summary:
      'Patch release. Corrects a frontend type-build error introduced in 12.0.0 that stopped the container image from building, with no functional or behavioural change.',
  },
  {
    version: '12.0.0',
    date: '2026-07-19',
    tag: 'NEW',
    summary:
      'Model review now runs twenty more automatic checks over an imported model, from missing element properties and dimensions to duplicate marks and classification coverage, all shown in the review panel and folded into the completeness score. New screens surface analytics that were computed but never shown: a physical progress page with an actual against planned S-curve and quantity variance, contract gain share, security coverage and milestone schedule panels, and a finance retention ledger, each translated into every language.',
  },
  {
    version: '11.18.0',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'Bills of quantities now export back to FIEBDC-3 (BC3), the Spanish and Latin American construction budget format, with the full chapter and item hierarchy, codes, units, quantities and rates, and a clean round-trip through the BC3 reader. The in-app error log also scrubs a wider set of secrets, including bare session tokens, before anything reaches local storage or a downloaded bug report.',
  },
  {
    version: '11.17.0',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'Security hardening across the outbound connectors and several server-side parsers. The Slack, Teams and Discord webhook connectors re-check the target address at send time, so a webhook pointed at an internal address is refused, not only when it is saved. Status probes no longer echo raw exception text and return a short, stable message instead. The schedule, change order, smart view, formula and email parsers cap the length they inspect before the pattern runs. Browser-stored BIM shortcuts and selection sets reject reserved keys, and the desktop download page escapes the release tag it reads from the public API.',
  },
  {
    version: '11.16.2',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'The longer case introduction now shows in every interface language. Fourteen guided cases carried this paragraph in English only; it is now translated into all twenty-seven other locales so each case reads in one language.',
  },
  {
    version: '11.16.1',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'The step blocks on the case detail page are more compact: smaller padding, title and body text, a tighter gap between the text and the data-flow column, and shorter connectors, so each step takes less room and the page reads denser with less empty space.',
  },
  {
    version: '11.16.0',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'The case detail page lays its header out in two columns on wide screens, with the case identity on the left and a compact control panel (progress, start, reset and the sample-project picker) on the right, so it reads shorter and denser. The featured article card in the sidebar now shows only its title and expands to reveal the summary and link when you hover or focus it.',
  },
  {
    version: '11.15.0',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'Match a selected element to a priced cost position from inside every viewer. In the BIM, PDF takeoff and DWG takeoff viewers, pick an element and the panel reads its properties, searches every loaded cost catalogue and ranks the positions that fit; accept one to create a priced BOQ line for that element and link it back in a single step.',
  },
  {
    version: '11.14.0',
    date: '2026-07-18',
    tag: 'NEW',
    summary:
      'The sidebar Edit menu now hides and restores the bottom shortcut buttons (Settings, Users, Modules, Governance, Audit log, About) too, not just the main menu rows. The defects liability and interface management registers, which had shipped in English only, are now fully translated into every interface language.',
  },
  {
    version: '11.13.0',
    date: '2026-07-18',
    tag: 'SECURITY',
    summary:
      'Two security fixes from disclosed reports: the in-app upgrade endpoint now requires an authenticated admin, and self-hosted AI provider URLs (Ollama, vLLM) are validated against internal and cloud-metadata targets before they are fetched. The PDF takeoff viewer also gets a shorter calibrate label, no stray draw previews during a scale calibration and a toolbar that collapses by its own width, and the cases are recolored per category with the case page reworked to lead with its title and steps.',
  },
  {
    version: '11.12.0',
    date: '2026-07-17',
    tag: 'NEW',
    summary:
      'Assemblies become parametric: name the values that drive a recipe (an input, a constant, or one calculated from the others), give any component a quantity formula over them, and a preview shows the exact per-line quantities and rate the bill will get before you apply it. The five delivery registers from 11.11 now have their own pages in the app, and a desktop security advisory is cleared.',
  },
  {
    version: '11.11.1',
    date: '2026-07-16',
    tag: 'FIX',
    summary:
      'A packaging fix for 11.11.0: a test type annotation tripped the strict frontend build in the release pipeline, so the installers and wheel did not publish. Same feature set, build corrected.',
  },
  {
    version: '11.11.0',
    date: '2026-07-16',
    tag: 'NEW',
    summary:
      'Five new registers cover work that usually lives in spreadsheets: temporary works with its permit-to-load and permit-to-strike gates, the interface register between work packages, the defects liability period with its retention-release readiness signal, pre-construction site readiness, and on-site material stock. This release also stops the desktop app implying your data is lost when offline (it keeps saving locally, only live multi-user collaboration pauses), reopens external links in the system browser, adds a wider spread of project analytics, and closes cross-tenant access gaps on several endpoints.',
  },
  {
    version: '11.10.0',
    date: '2026-07-16',
    tag: 'NEW',
    summary:
      'Onboarding no longer waits on a slow cost-base or sample download, moving you straight on with a live background progress bar, and the team-size step now previews the modules each size switches on and grows into. Model Review gains coordination tools: zoom to issue flies the 3D view to where an issue was raised, coordination mode walks the open issues for a meeting, a dashboard sums the backlog up, and the list prints to a clean report.',
  },
  {
    version: '11.9.0',
    date: '2026-07-16',
    tag: 'NEW',
    summary:
      'The files area becomes a real document workspace with a right-click menu, content search, paged folders, drag-and-drop upload, keyboard navigation and bulk status changes. Takeoff measurements can now link to issues and RFIs, the How it works guide highlights the actual control it describes, setup adapts to your company size, and the worked-case library gains twelve new cases with a connected step flow and an at-a-glance panel.',
  },
  {
    version: '11.8.0',
    date: '2026-07-16',
    tag: 'NEW',
    summary:
      'PDF takeoff gets a round of viewer fixes: the cursor readout no longer freezes on a point you are dragging, a measurement value sits just off its line instead of hidden under a wide band, a wide line shows its full width band while you drag or move it, and a tool shortcut pressed mid-drag no longer starts a stray measurement. The legend, hints and readout stay pinned while the drawing pans, the group legend can be dragged aside by its header and remembers its place, each measurement has its own show and hide control that never changes exported quantities, and client-portal notifications now read correctly on Telegram instead of showing an internal label.',
  },
  {
    version: '11.7.1',
    date: '2026-07-14',
    tag: 'FIX',
    summary:
      'The Windows desktop app now stops its background service before installing or uninstalling, so a reinstall no longer fails because the old backend process was still running and locking the file. That service is also renamed to openconstructionerp-server so the app carries one name, and your data and settings are untouched.',
  },
  {
    version: '11.7.0',
    date: '2026-07-14',
    summary:
      'Each national cost base now opens market by market like the global base, and picking a market reprices the base into that market at its own price level and currency. This release also finishes removing third-party cost-index product names and refreshes the interface translations across all 27 languages.',
    tag: 'NEW',
  },
  {
    version: '11.6.2',
    date: '2026-07-14',
    tag: 'FIX',
    summary:
      'Switching the interface language now applies at once, without a page reload. The cost base browser labels the global base as Russia with its own flag, the worked-case pages get a tighter step rail with clear done marks and larger, softer flow arrows, and third-party cost-index product names were removed from the app.',
  },
  {
    version: '11.6.1',
    date: '2026-07-14',
    tag: 'NEW',
    summary:
      'The in-app How it works manual reads top to bottom in the order a project runs, with each section card numbered, and a Sort control lets you switch between the lifecycle order, alphabetical, or a custom order you arrange yourself and that is remembered. Worked cases can carry a longer description shown under the title on the case page, and case cards no longer cut the summary as short.',
  },
  {
    version: '11.6.0',
    date: '2026-07-14',
    tag: 'NEW',
    summary:
      'A personal backup now carries all of your own data across every module, not just the core few tables, so your contacts, site diaries, takeoff, inspections and safety records, labor rates, custom catalogs and templates travel with your projects, estimates, schedules and documents. Records are written in dependency order so a restore rebuilds parents before the rows that depend on them, shared reference and catalog data stays out as before, and every safeguard from the last release still holds: merge by default, replace only into an empty account, ownership pinned to the restoring account, embedded files restored, and provider keys never in a backup.',
  },
  { version: '11.5.0', date: '2026-07-14', tag: 'FIX', summary: 'Backups now move cleanly between machines: restoring a backup on a second computer no longer fails, and the projects, estimates, schedules, cost data, documents and change records it carries land under the account doing the restore, with any drawings and photos restored alongside. Merge is now the default and only adds what is missing, replace is limited to an empty account so it can never wipe data a backup does not carry, a single record that cannot come across is skipped with a note rather than failing the whole restore, and provider keys never travel in a backup. Site records such as diaries, takeoff, inspections and safety are not part of the backup yet, and the backup screen says so.' },
  { version: '11.4.0', date: '2026-07-13', tag: 'NEW', summary: 'Scheduling gains work calendars: define named work weeks for a project (five-day, six-day or a custom set of days), each with its own hours and public holidays, and assign one to any activity from the schedule table. Rescheduling measures each activity on its own calendar, so a six-day trade finishes sooner than a five-day one and a crew with its own holidays finishes later, while activities left on the default reschedule exactly as before.' },
  { version: '11.3.0', date: '2026-07-13', tag: 'FIX', summary: 'PDF takeoff is reliable again and the platform is hardened against out-of-memory crashes: opening a PDF from Project Files no longer floods the console with 404s, every document, revision, PDF-split and photo upload streams to disk under a size cap, PDF parsing runs in an isolated memory-capped subprocess, and the desktop build parses in-process again. The published container is secure by default while still starting with zero configuration, a pip install now ships every interface language, and scheduling gains a dependency editor and an editable grid and reschedules each chain from its own start.' },
  { version: '11.2.0', date: '2026-07-12', tag: 'NEW', summary: 'The point cloud viewer becomes a measurement workspace for a reality-capture scan: trace a polyline for running length and perimeter, draw a polygon for plan area, estimate a volume against a reference plane, jump to preset top, front and side views, thin a dense cloud to stay responsive, and export measurements to CSV, and once a scan is loaded the viewer leads the page like the BIM hub with the uploader collapsed below. The architecture map lights up what connects to what when you click or hover a module, the case count on each project-journey module opens the list of cases attached to it, the cost base import screen uses one country picker with the local China base first and the global CWICR set next, and the guided case pages read more clearly. It also fixes a drawing that anchored away from the project location and a takeoff viewer that did not fill its height.' },
  { version: '11.1.0', date: '2026-07-12', tag: 'NEW', summary: 'The cost bases move to the centre of the workspace: every price base you can load now shows in one place with its own count of rates, so you see all of them at a glance, the global set and each national base, and the same picker appears in import, data setup and onboarding, where you can search across bases, load one, set the active base or simply pick a base to work with. The point cloud viewer gains a fuller set of professional tools for a reality-capture scan, the dashboard lets you set the width of each widget, a drawing that could not be placed on the map is fixed, the Cases line-art illustrations are complete, and a PDF takeoff scale calibration is no longer left armed when you switch tools mid-pick. The interface is also more complete in every language, with thousands more strings translated in each of the twenty seven supported languages.' },
  { version: '11.0.0', date: '2026-07-11', tag: 'NEW', summary: 'The point cloud viewer becomes a site review tool: slice a reality-capture scan to a height band and read it as a top-down plan, measure point to point with the horizontal and vertical parts in millimetres, box off a region, colour points by elevation with a pinnable band, and save the view as a PNG. Onboarding now leads with the national cost base and rebuilds the left menu to your company profile, the Cases hub gains a start-here tile row with clearer step visuals and the full case library translated into every language, the dashboard fits more case tiles with the inbox below the map, and module pages share one full-width layout.' },
  { version: '10.10.0', date: '2026-07-10', tag: 'NEW', summary: 'Work with the world national cost bases at once: eight are wired in, you can search or compare a rate code across several bases together with typo-tolerant and descriptive search, browse resource catalogs, price a coefficient base through a resource price sheet, and read bases in one currency using live European Central Bank reference rates with a purchasing-power fallback. A new Design Options workspace compares competing designs for the same project side by side on total, by-trade delta and cost per square metre, converting every option to one base currency first, with a transparent recommendation and a fairness banner. Builders get a Module SDK and guides plus a full user documentation set, and this release fixes chat-connector notifications, the portal shared-model viewer bouncing to login and the property developer sales-target form, adds an admin switch for the public demo login, and lets you hide whole sections of the left menu.' },
  { version: '10.9.0', date: '2026-07-10', tag: 'NEW', summary: 'Site issue management becomes one connected workflow: punch list items carry phone photos and a pin placed visually on the drawing with a full closure stepper, issues can be raised on the 3D model as open-standard BCF topics with a captured viewpoint and snapshot that import and export as a standard file, a drawing markup converts to a tracked issue in one click, checklists attach to an issue and a failed check raises one, the field shell captures a defect with a photo offline, and a new Issues hub unifies every open item across drawings, punch lists, non-conformances, model coordination and clashes with owner and overdue at a glance. Several delivery modules are deepened, led by a site-logistics gate timeline that lanes overlapping deliveries with per-gate occupancy and an exportable day schedule, and the guided Cases process strip is more compact with a prominent numbered title. It also fixes the PDF takeoff viewer to fill available height with a flexible layout, adds real-world line-width entry for linear measurements, and resolves a Files in-app bug report.' },
  { version: '10.8.0', date: '2026-07-08', tag: 'NEW', summary: 'The estimating tools from the last version now connect into one chain: a production norm expands into a priced assembly and grosses material up for waste, a labor build-up publishes as a reusable rate, the resource summary exports a material buy-list, and the estimate rolls the bill base, preliminaries and allowances into one total that the conceptual estimate reconciles against, with rates escalatable in time and by region. The dashboard delivery and quality cards are tighter with a two-column locations and weather panel, the Cases hub loads on scroll with a soft per-discipline card wash and drawn scenes for cases that ship without a picture, a resourceless bill position keeps its unit rate editable, and multi-currency estimate lines reconcile exactly to the total. The Cases hub shows the project lifecycle as labelled stage cards with a how-to translated across all languages, the pipeline builder labels the typed inputs and outputs of each step with a key for connecting them, newer maturing modules are marked beta, and more recent modules now appear in onboarding and the project journey.' },
  { version: '10.7.0', date: '2026-07-08', tag: 'NEW', summary: 'A wave of estimating tools takes a job from a first rough number to a documented bill: conceptual order-of-magnitude estimates with a guided copilot and a written basis of estimate, priced preliminaries and general conditions split into time-related and fixed, an allowances and contingency register, regional and time-based price indexing, labor-rate build-ups, a labor, material and equipment resource summary, net-to-gross waste factors, and production-norm expansion. Cost rates now flag when a price is going stale and suggest a refreshed value, AI-suggested assemblies are grounded in real per-unit factors instead of a flat quantity, and the desktop app shows the real reason if startup ever fails instead of the database shutdown noise.' },
  { version: '10.6.1', date: '2026-07-08', tag: 'FIX', summary: 'The app loads noticeably faster on first open: the 3D globe and 2D map libraries no longer ride along in the initial download for people who never open a map, and load only when a map or the geo hub is actually opened, which takes about 1.6 MB off first paint with no change in behaviour. Clicks inside the takeoff Link to BOQ picker no longer bubble to the measurement row and toggle the properties panel.' },
  { version: '10.6.0', date: '2026-07-07', tag: 'NEW', summary: 'Five new modules extend the platform past the estimate into delivery on site: site logistics with gates, laydown zones and delivery bookings, systems commissioning, off-site and prefab production with a quality gate before dispatch, ESG site performance against targets, and a monthly cost-value reconciliation with a cashflow S-curve and interim payment applications. Site coordination gets stronger too: meeting minutes now capture decisions and turn them into tracked action items that carry over across a recurring series, a new forms and checklists library lets you build reusable inspection and handover templates and fill them in on site, voice input turns spoken notes into structured diary, defect and task entries, and the finance module gains an invoice inbox that captures a supplier invoice, proposes the booking and keeps a tamper-evident archive through approval and posting. PDF takeoff adds per-measurement line opacity, a roof and ramp slope factor, a wastage allowance, a typical multiplier and copy to other pages, every guided case now shows a clear colour picture of each step, and this release also fixes takeoff calibration on reload, the pipeline builder run action, the cost database open error and the developer guide layout.' },
  { version: '10.5.0', date: '2026-07-06', tag: 'NEW', summary: 'Every step of every case now shows a small line-art drawing of what it does, chosen from the step itself so all 85 cases got them at once, falling back to a clean framed icon where none is drawn yet, and the same pictures now appear in the How it works hub. The Cases lifecycle timeline is bigger and matches the pickers below it, and twenty two new worked cases take the catalogue from 63 to 85, covering permits to work, plant registers, progress meetings, takt planning, AI element matching, 5D models, delay claims, a client portal, the common data environment, supplier catalogs, submittals, engineering changes and reactive facilities service.' },
  { version: '10.4.0', date: '2026-07-06', tag: 'NEW', summary: 'The Cases hub gets a hand-drawn look. Every case, professional role and company type now carries a light line-art illustration, the pickers are picture-left chips, each card has an illustration banner with a single discipline colour and a stack of role avatars, and the runner shows the art beside a bigger title. Missing art falls back to a plain glyph so nothing breaks. The two inbound capture webhooks also accept an X-API-Key header, so an external system can post with a shared key instead of a signed-in session, covered by tests.' },
  { version: '10.3.0', date: '2026-07-06', tag: 'NEW', summary: 'The Cases hub is reworked around who you are and the shape of a real project. On top of company type you can pick your professional role, estimator, quantity surveyor, site manager, project manager, BIM coordinator, procurement, planner, health and safety officer, design lead, document controller, commercial manager or foreman, each drawn as its own illustrated persona avatar. The whole catalogue is laid out along the project lifecycle, from Define through Design, Estimate, Procurement, Plan, Build, Handover and Operate, with a timeline across the top, a stage and a sequential number on every case, and the grid reading in the order a project runs. Eleven more cases were added for the thinnest roles, taking it from 52 to 63, and the dashboard Cases block now quick-launches into resumable and role-matched cases.' },
  { version: '10.2.0', date: '2026-07-06', tag: 'NEW', summary: 'The Cases hub is now organized by company type: pick how you work, general contractor, subcontractor, cost consultant, designer, developer, project manager, BIM consultant or owner and operator, and you see the cases that type of company runs, with a project pin to keep a project shortlist. The catalogue grew from 40 to 52 cases. Custom cost catalogues are easy to fill now, creating one opens the add position form and every custom catalogue has an add position button and empty state. Supporters get an Inside track panel at /inside with early access to what shipped and what is coming, and the client portal gains an Invoices tab and view-only BIM and CAD sharing. It also fixes a start-up failure where four streaming-or-json routes stopped the app from booting, checks catalogue ownership when adding or listing cost items, and converts an imperial takeoff volume depth correctly.' },
  { version: '10.1.0', date: '2026-07-05', tag: 'NEW', summary: 'The main dashboard gains five delivery and quality cards (upcoming milestones, RFI turnaround, submittals, inspections and punch list), each self-hiding when its module has no data and each explaining its own numbers. The estimate grid now explains itself too: the line total on hover, the labour, material and plant build-up behind a unit rate, missing quantity or price flags, each section share of the total, an AI confidence badge, a price provenance chip and a cost per square metre benchmark against your own past projects. It also fixes three takeoff issues: measurement to position unit conversion on linking, US trade units as convertible targets, and a document-space stroke width.' },
  { version: '10.0.1', date: '2026-07-04', tag: 'FIX', summary: 'Fixes a Windows startup crash where the desktop app stalled at Starting the application server after the embedded database was ready, by connecting to the exact IPv4 loopback it listens on. The left menu again lists every module whatever onboarding profile you picked, a shared video now plays in the document viewer, custom takeoff group colours persist for everyone, and the methodologies catalogue grows to 37 with sixteen more countries and ten industry packs.' },
  { version: '10.0.0', date: '2026-07-04', tag: 'NEW', summary: 'A milestone release that finishes the PDF takeoff quality wave, reworks onboarding with 22 company profiles and curated country packs, and grows the Cases hub to 24 worked examples with category filters, soft per-group colours and a compact step-by-step runner. It also recognises a dropped point cloud or drone file as a reality-capture asset, renames the Spanish bill of quantities to presupuesto, and translates the new strings across all 27 other languages.' },
  { version: '9.9.3', date: '2026-07-04', tag: 'NEW', summary: 'Cost Benchmarks now covers eleven markets and five more building types, each region carrying a named public source and a note on what drives its cost. A new How these benchmarks work section explains the percentiles, quartiles, DIN 276 split and confidence.' },
  { version: '9.9.2', date: '2026-07-04', tag: 'FIX', summary: 'A follow-up that keeps your place across the Cost Explorer tabs and warns in Substitute when a replacement is priced in a different unit. It also adds a Mexico contract-compliance pack for APU, IVA, CFDI and LOPSRM checks.' },
  { version: '9.9.1', date: '2026-07-04', tag: 'NEW', summary: 'Cost Explorer search now understands construction vocabulary, so rebar also finds work priced against reinforcement, and a descriptive search returns the closest partial matches instead of zero results. Substitute is steadier on currencies and blank rates, and the workspace flags a price base that is not yet indexed with a one-click rebuild.' },
  { version: '9.9.0', date: '2026-07-03', tag: 'NEW', summary: 'A new Cost Explorer workspace finds priced work from the materials, trades or plant you name, searches catalogs by description, compares a rate code across regional price bases, and substitutes one resource to show the effect on a rate. Starter cost items now ship with resource recipes so it returns real results before any regional catalogue is imported.' },
  { version: '9.8.0', date: '2026-07-03', tag: 'NEW', summary: 'A new Field Time and Daywork module captures labour and plant hours on site with an approval workflow that feeds payroll and earned value, and the 3D importer adds LightWave (.lwo) meshes. The PDF takeoff viewer gets a wave of fixes so measurements no longer vanish on page change or zoom, carry a per-measurement colour, snap to corners and can be duplicated.' },
  { version: '9.7.0', date: '2026-07-02', tag: 'NEW', summary: 'Compare two DWG drawings side by side, import 3D meshes (glTF, OBJ, DAE, 3DS, STL, PLY, USD) with in-browser quantities, and read the dashboard from a redesigned map with a sites and weather panel. It also loads large BIM models without running out of memory, adds a client-portal Documents area, and lets Bill of Quantities cells take feet-and-inches and reuse a quantity across positions.' },
  { version: '9.6.1', date: '2026-07-02', tag: 'FIX', summary: 'A photo uploaded from a project Photos tab now becomes a real site picture across every gallery instead of vanishing, and a shared video streams and seeks in the file viewer. It also stops a field report linking another project document, models ISO 15686-5 residual value in whole-life cost, and completes the Spanish and Mexican Spanish translations on the newest screens.' },
  { version: '9.6.0', date: '2026-07-01', tag: 'NEW', summary: 'Change Intelligence gains a notice and time-bar register that guards claim and extension-of-time deadlines, plus change-driver Pareto and run-rate analytics with a burn-rate forecast. The 6D module adds a whole-life dashboard for embodied and operational carbon by EN 15978 and ISO 15686-5 cost, computed from your BIM model.' },
  { version: '9.5.0', date: '2026-07-01', tag: 'NEW', summary: 'The interface is now in Mexican Spanish, a new Contracts workspace tracks parties, guarantees and claims, and a Mexico pack adds unit-price analysis, IMSS safety and IVA and CFDI billing. Cross-module Cases playbooks and built-in How-It-Works guides arrive across the platform, 6D links embodied carbon to BIM elements, and the main PDF exports now carry your logo.' },
  { version: '9.4.0', date: '2026-06-30', tag: 'NEW', summary: 'Imperial now works end to end, including the editable Bill of Quantities grid, while storage and the Excel, CSV and GAEB exports stay canonical metric. The paired per-unit rate is restated reciprocally so the line reconciles and the total stays invariant, and takeoff, bid management, assemblies, tendering and the AI quick-estimate all honour the preference.' },
  { version: '9.3.0', date: '2026-06-29', tag: 'NEW', summary: 'The Imperial preference is now honoured beyond Takeoff across read-only quantity displays, the BIM inspector and the printed Bill of Quantities, while exports stay canonical metric. Project Files opens a PDF inline by default, Finance gains send-for-approval and reversible invoice edits, GeoHub anchors from an address or a placed pin, and a Cancelled project status is added.' },
  { version: '9.2.0', date: '2026-06-29', tag: 'NEW', summary: 'The model viewer becomes a federated workspace with several models in one scene, a spatial tree and an eye-level Walk mode, and filtered elements turn into a quantity report or Excel export. Schedules import and export Microsoft Project XML and XER, a PDF from a transmittal or NCR previews inline, and the Change Intelligence and approval screens are fully translated.' },
  { version: '9.1.0', date: '2026-06-29', tag: 'NEW', summary: 'Projects gain working statuses with a status history, archived projects get a filterable view with one-click restore, and notification settings become a per-event, per-channel routing matrix that drives Telegram, Slack, Teams, Discord and WhatsApp. It also opens a drafted RFI from the interface and gives the Client and Partner Portal invite a complete sign-in link.' },
  { version: '9.0.1', date: '2026-06-27', tag: 'FIX', summary: 'Opening a BIM file (IFC or RVT) uploaded through Project Files now builds the 3D model on the fly instead of reporting "model not found". The File Manager had been opening it by document id as if it were a model id; it now hands the file to the same on-demand converter used elsewhere, and a stale link is recovered the same way.' },
  { version: '9.0.0', date: '2026-06-26', tag: 'NEW', summary: 'A stability and self-hosting release that hardens the production path: OE_ prefixed environment variables are honoured, uploads follow the configured data directory and survive a restart, the in-app PDF preview is no longer blocked, and an external PostgreSQL self-heals missing columns and indexes on startup. The desktop build now bundles the PDF, computer-vision and point-cloud libraries it was missing.' },
  { version: '8.11.0', date: '2026-06-25', tag: 'NEW', summary: 'The trust envelope and an accuracy scoreboard are now visible wherever the assistant speaks, a Value Realized dashboard proves the payoff of acting early, and change accountability deepens with a hand-off log, provability score, dispute risk and exportable evidence packs. It also adds a Phone Log, Document Connectors that pull a watched folder onto the record, and one faceted Find Records search across documents, correspondence and change orders.' },
  { version: '8.10.0', date: '2026-06-24', tag: 'NEW', summary: 'A new Change Intelligence page brings the change-adjacent modules into one project view with co-pilots for what to act on first, who owes the next action, the committed cost of approved changes, a back-charge ledger and a note-to-request clarifier. It builds on a new layer with a unified timeline, approval breach monitoring, ball-in-court tracking, cycle-time analytics, a claims evidence pack and inbound email delay detection.' },
  { version: '8.9.1', date: '2026-06-23', tag: 'FIX', summary: 'A correctness and hardening release. The 4D earned-value dashboard now serves every money value as an exact decimal string (no binary-float drift; SPI, CPI and percentages stay numbers), and creating a cross-project schedule link now rejects an activity that does not belong to its schedule with a clear error instead of dropping the link silently during portfolio analysis.' },
  { version: '8.9.0', date: '2026-06-23', tag: 'NEW', summary: 'A new Construction Control (QA/QC) module spans acceptance criteria and inspections, material and lab records with EN 10204 and ISO/IEC 17025, as-built records, hold and witness points, and a handover acceptance package. It also completes the advanced scheduling suite with a claims-grade critical-path engine, schedule comparison, Monte-Carlo risk, forensic delay analysis, resource leveling and a multi-project portfolio.' },
  { version: '8.8.4', date: '2026-06-22', tag: 'SECURITY', summary: 'A hardening release from a deep internal audit that closes cross-tenant access gaps across procurement, private catalogues, property development, BIM validation, safety and document revisions, and sanitises template previews against stored cross-site scripting. It also fixes markup totals that added up as text, a lost-update race on posted actual cost, phantom budget commitments and dashboards that showed green zeros when their data failed to load.' },
  { version: '8.8.3', date: '2026-06-21', tag: 'SECURITY', summary: 'Rebuilding the bill-of-quantities search index now enforces per-project ownership, and the resource summary converts foreign-currency resources to the project base currency before totalling. It also stops partial edits to bills, markups and takeoff measurements dropping saved details, fixes the safety incident-rate metric that always read zero, and degrades the 3D viewer gracefully where WebGL2 is unavailable.' },
  { version: '8.8.2', date: '2026-06-21', tag: 'NEW', summary: 'BIM and CAD converters now install themselves the first time you upload a model, trying a system package, a rootless unpack and a built-in pure-Python reader in turn so it works on minimal containers too. Bill-of-quantities exports and the compare view also convert foreign-currency amounts to the project base currency before totalling.' },
  { version: '8.8.1', date: '2026-06-21', tag: 'FIX', summary: 'A PDF uploaded for quantity takeoff now stays attached to the active project, so it remains in the document list after a reload. Previously it was saved without a project and the filtered list dropped it on refresh.' },
  { version: '8.8.0', date: '2026-06-21', tag: 'NEW', summary: 'Monte-Carlo cost-risk analysis turns a bill of quantities into a full cost distribution with P5 to P95 bands, an S-curve, a recommended contingency and a tornado chart, and a new "How it works" hub explains every module in all 27 languages. This release also adds 2D project maps, a DIN 276 breakdown in cost benchmarks, count-by-example symbol counting and quantity-weighted progress rollups.' },
  { version: '8.7.1', date: '2026-06-20', tag: 'FIX', summary: 'The repeated "request timed out" message no longer floods a busy server, a CAD conversion interrupted by a restart now shows a clear recoverable error, and the AI Estimator no longer analyses the source twice. It also confines the AI agent reading tools to projects the user can access and aligns the transmittals statuses with the backend.' },
  { version: '8.7.0', date: '2026-06-20', tag: 'SECURITY', summary: 'A broad security pass closes cross-tenant gaps across requirements, contacts and project controls, rejects not-a-number and absurd monetary inputs, stops currency roll-ups blending currencies, and keeps partial edits from dropping unmentioned fields. It also adds methodology-aware country and industry packs, PDF and Excel export for methodology estimates, and LAS, LAZ and COPC point cloud reading.' },
  { version: '8.6.1', date: '2026-06-19', tag: 'FIX', summary: 'Uploaded 3D models, DWG drawings and takeoff PDFs could fail with a file-not-found error on PostgreSQL, Docker and macOS because files were written to one location and read from another. Storage now resolves a single consistent data directory across every launch mode, with a fallback that still finds files saved by earlier versions.' },
  { version: '8.6.0', date: '2026-06-18', tag: 'NEW', summary: 'A data-driven estimating methodology engine lets a project follow a named methodology you build in the app, with a typed bill-of-quantities hierarchy, analytical dimensions, funding sources and a cascade of markups. Country and industry templates ship ready to install, and construction machinery is now costed separately from installed equipment.' },
  { version: '8.5.0', date: '2026-06-18', tag: 'NEW', summary: 'DWG and DXF takeoff is now a full vector takeoff, with a one-click per-layer quantity table, a count-by-block tool, drawing-text search and Excel export. The PDF takeoff viewer gains a thumbnail sidebar, find-on-sheet, scale detection and zoom controls, and steel can be priced by mass.' },
  { version: '8.4.0', date: '2026-06-17', tag: 'FIX', summary: 'PDF takeoff measurements are now scoped to the project and the specific document they were drawn on rather than keyed by file name, so two files that share a name no longer show the same measurements. The resources under a bill-of-quantities position now expand on the first click, and the public hosted demo keeps its bundled cost databases read-only.' },
  { version: '8.3.3', date: '2026-06-15', tag: 'FIX', summary: 'Totals that summed money values arriving from the server as text were concatenating instead of adding, producing wrong figures. This is fixed across the Excel and PDF exports, assembly rollups, the BOQ tree and resource subtotals, the cost model columns, bid analysis and the chat and AI estimate totals.' },
  { version: '8.3.2', date: '2026-06-15', tag: 'SECURITY', summary: 'Money figures the server sends as text no longer break the screens that show them, so exports, reports, the cost benchmark, the 5D cost model and the cost-match panels all render reliably. Access checks were also tightened so an account only opens and changes records in projects it can reach.' },
  { version: '8.3.1', date: '2026-06-15', tag: 'FIX', summary: 'Sample projects are now clearly labelled and easy to remove so a fresh install can start from an empty workspace, a new project takes its currency from your regional preference, and the AI estimate builder, the match-to-cost wizard and the assembly template dialog now follow the project chosen in the top bar. Regional cost-database downloads explain a blocked connection and offer a retry, and the new wording is translated across all 26 other languages.' },
  { version: '8.3.0', date: '2026-06-15', tag: 'NEW', summary: 'A new South Africa construction pack, the first in our African coverage, pre-configured with SANS 1200 and ASAQS measurement, CIDB contractor grading, the PPPFA 80/20 and 90/10 procurement scoring, the nine provinces and the rand with 15 percent VAT, and Johannesburg cost data on demand. This release also translates the most recent feature screens across all 26 other languages.' },
  { version: '8.2.2', date: '2026-06-15', tag: 'FIX', summary: 'The macOS desktop app no longer opens with a "damaged" warning. The build is now ad-hoc signed across the app and its bundled local server so the code signature is valid, and the install guide explains the one-time command to clear the download quarantine.' },
  { version: '8.2.1', date: '2026-06-15', tag: 'SECURITY', summary: 'Editing one part of a record no longer clears the other saved details, fixed across more than two dozen modules, and paying an invoice, converting mixed currencies and reversing a ledger entry now behave correctly. Access checks were tightened so an account only reads and changes records in projects it can reach.' },
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

export function Changelog({ maxEntries }: { maxEntries?: number } = {}) {
  const { t } = useTranslation();

  const sorted = [...CHANGELOG].sort(compareVersionsDesc);
  const total = sorted.length;
  // When collapsed (maxEntries set) we render only the newest few cards but
  // still report the full release count so the "Show full changelog" toggle
  // reads as an invitation rather than the whole list.
  const entries =
    typeof maxEntries === 'number' ? sorted.slice(0, Math.max(0, maxEntries)) : sorted;
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
            count: total,
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
