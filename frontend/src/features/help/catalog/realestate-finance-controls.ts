// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Real estate + Finance & reports + Controls & BI.
// See ../types.ts for the shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const realestateFinanceControlsModules: ModuleExplanation[] = [
  /* ── Real estate ──────────────────────────────────────────────────────── */
  {
    id: 'property-dev',
    route: '/property-dev',
    icon: 'Building2',
    category: 'real_estate',
    keywords: 'developer units plots house types buyers leads handover warranty sales inventory pricing',
    titleKey: 'howto.property-dev.title',
    titleDefault: 'Property Development',
    summaryKey: 'howto.property-dev.summary',
    summaryDefault: 'Run a residential development end to end: plots, pricing, buyers and handover.',
    whatKey: 'howto.property-dev.what',
    whatDefault:
      'Property Development is the workspace for a developer selling homes. It holds your developments and the plots inside them, the house types you build, the leads and buyers moving through the sales journey, and the handovers and warranty claims that follow completion. It turns a scheme into a tracked inventory of units you can price, reserve and sell.',
    how: [
      { key: 'howto.property-dev.how.1', default: 'Create a development, then add the plots inside it and assign each one a house type so it has a layout and a base price.' },
      { key: 'howto.property-dev.how.2', default: 'Set prices in the pricing engine, then watch availability on the inventory map as plots move from available to reserved to sold.' },
      { key: 'howto.property-dev.how.3', default: 'Capture leads, convert a lead into a reservation, and progress the buyer from reservation through to a signed contract.' },
      { key: 'howto.property-dev.how.4', default: 'After completion, schedule handovers and log any warranty claims against the unit so post-sale issues stay tracked.' },
    ],
    tips: [
      { key: 'howto.property-dev.tip.1', default: 'Use the tabs along the top - developments, plots, house types, leads, buyers and handovers - to move through the lifecycle in order.' },
      { key: 'howto.property-dev.tip.2', default: 'Worker housing for a development block links across to the Accommodation module, so site crews and unit sales stay separate but connected.' },
    ],
    whenKey: 'howto.property-dev.when',
    whenDefault: 'Use it whenever you are developing and selling units rather than building a single contracted job.',
  },
  {
    id: 'accommodation',
    route: '/accommodation',
    icon: 'Home',
    category: 'real_estate',
    keywords: 'worker camp rental hotel rooms bookings capacity housing lodging stays',
    titleKey: 'howto.accommodation.title',
    titleDefault: 'Accommodation',
    summaryKey: 'howto.accommodation.summary',
    summaryDefault: 'House the workforce and guests: worker camps, rentals and hotels with rooms and bookings.',
    whatKey: 'howto.accommodation.what',
    whatDefault:
      'Accommodation manages places people stay across a project: worker camps for site crews, rentals for staff, and hotels for visiting consultants. Each property holds its rooms, bookings and charges, and a shared calendar shows who is where on any date. It bridges to HR contacts so you can put a named person into a bed in a few clicks.',
    how: [
      { key: 'howto.accommodation.how.1', default: 'Create an accommodation, choose its kind - worker camp, rental or hotel - and set its total capacity and location.' },
      { key: 'howto.accommodation.how.2', default: 'Add the rooms inside the property, then book people into them and record the charges that go with each stay.' },
      { key: 'howto.accommodation.how.3', default: 'Open the calendar to see occupancy across every property and date at a glance.' },
      { key: 'howto.accommodation.how.4', default: 'Use Suggest room for employee to bridge from an HR contact straight into a booking.' },
    ],
    tips: [
      { key: 'howto.accommodation.tip.1', default: 'Filter by kind using the tabs to focus on just worker camps, rentals or hotels when a project mixes all three.' },
    ],
    whenKey: 'howto.accommodation.when',
    whenDefault: 'Reach for it when a project has to lodge crews, staff or visitors and you need bookings and capacity in one place.',
  },

  /* ── Finance & reports ────────────────────────────────────────────────── */
  {
    id: 'finance',
    route: '/finance',
    icon: 'PieChart',
    category: 'finance',
    keywords: 'budget invoices payable receivable payments ledger connectors cash flow',
    titleKey: 'howto.finance.title',
    titleDefault: 'Finance',
    summaryKey: 'howto.finance.summary',
    summaryDefault: 'Track the project budget, raise and settle invoices, and watch the cash position.',
    whatKey: 'howto.finance.what',
    whatDefault:
      'Finance is where the money on a project is tracked: the budget by line, the payable and receivable invoices, the payments against them, and the cash flow that results. It ties invoices back to the cost spine so actuals land where they belong, and connectors let you bring figures in from outside systems.',
    how: [
      { key: 'howto.finance.how.1', default: 'Open Finance on a project to see its budget lines with original, revised, committed, actual and forecast figures side by side.' },
      { key: 'howto.finance.how.2', default: 'Create payable and receivable invoices, recording the counterparty, dates, amounts and line items for each.' },
      { key: 'howto.finance.how.3', default: 'Record payments against invoices so the outstanding and overdue balances stay current.' },
      { key: 'howto.finance.how.4', default: 'Use the connectors tab to link an outside finance source, and link invoice lines to cost rows so actuals post to the right budget.' },
    ],
    tips: [
      { key: 'howto.finance.tip.1', default: 'Amounts always carry their currency code - the platform never blends currencies, so check the code before comparing totals.' },
    ],
    whenKey: 'howto.finance.when',
    whenDefault: 'Use it to manage invoicing and budget consumption once a project is live and money is moving.',
  },
  {
    id: 'analytics',
    route: '/analytics',
    icon: 'BarChart3',
    category: 'finance',
    keywords: 'portfolio budget actual variance comparison cross project overview',
    titleKey: 'howto.analytics.title',
    titleDefault: 'Analytics',
    summaryKey: 'howto.analytics.summary',
    summaryDefault: 'Compare budget against actuals across every project in your portfolio.',
    whatKey: 'howto.analytics.what',
    whatDefault:
      'Analytics rolls every project you own into one comparison: planned budget, actual spend and the variance between them, with a flag for anything over budget. It is the portfolio-level view that sits above any single project, so you can see which jobs are healthy and which need attention.',
    how: [
      { key: 'howto.analytics.how.1', default: 'Open Analytics to load every project into one table of budget, actual and variance.' },
      { key: 'howto.analytics.how.2', default: 'Sort by budget, actual or variance, and filter by region or status to focus on the projects that matter.' },
      { key: 'howto.analytics.how.3', default: 'Search for a project by name, then click through to open it directly.' },
    ],
    tips: [
      { key: 'howto.analytics.tip.1', default: 'When the portfolio spans several currencies, totals are grouped per currency rather than summed into one blended number.' },
    ],
    whenKey: 'howto.analytics.when',
    whenDefault: 'Use it for a fast health check across all projects, not for the detail of any single one.',
  },
  {
    id: 'reports',
    route: '/reports',
    icon: 'FileBarChart',
    category: 'finance',
    keywords: 'export pdf excel csv gaeb boq cost validation generate download',
    titleKey: 'howto.reports.title',
    titleDefault: 'Reports',
    summaryKey: 'howto.reports.summary',
    summaryDefault: 'Generate and export the standard project reports in the format you need.',
    whatKey: 'howto.reports.what',
    whatDefault:
      'Reports is a gallery of ready-made outputs for the active project - the bill of quantities, cost summaries, an open exchange export and validation checks - each available in the formats stakeholders expect. Pick a report, choose a format and download it; a history keeps a record of what you generated.',
    how: [
      { key: 'howto.reports.how.1', default: 'Pick the project, then choose the report card that matches what you need to send.' },
      { key: 'howto.reports.how.2', default: 'Select a format - for example PDF, Excel, CSV or an open exchange format - and generate it.' },
      { key: 'howto.reports.how.3', default: 'Download the file, and revisit the generated-reports history to find an earlier one again.' },
    ],
    tips: [
      { key: 'howto.reports.tip.1', default: 'A report reflects the project as it stands now - freeze a BOQ revision first if you need the figures to match a specific point in time.' },
    ],
    whenKey: 'howto.reports.when',
    whenDefault: 'Use it whenever you need a clean, shareable document to send to a client, partner or reviewer.',
  },
  {
    id: 'reporting',
    route: '/reporting',
    icon: 'FileBarChart',
    category: 'finance',
    keywords: 'dashboard kpi executive pm estimator site finance cpi spi templates scheduled',
    titleKey: 'howto.reporting.title',
    titleDefault: 'Reporting Dashboards',
    summaryKey: 'howto.reporting.summary',
    summaryDefault: 'Role-based dashboards of the live KPIs each audience cares about.',
    whatKey: 'howto.reporting.what',
    whatDefault:
      'Reporting Dashboards present the project as a set of live, role-tuned views - executive, project manager, estimator, site and finance - each surfacing the KPIs that audience needs, such as cost and schedule performance, budget consumed and open items. It also manages report templates and the snapshots of KPIs taken over time.',
    how: [
      { key: 'howto.reporting.how.1', default: 'Choose the dashboard tab for your role to see the KPIs framed for that audience.' },
      { key: 'howto.reporting.how.2', default: 'Read the cards for cost and schedule performance, budget consumed, safety and open items to gauge project health.' },
      { key: 'howto.reporting.how.3', default: 'Use report templates to produce a consistent output, and schedule one to run on a recurring basis.' },
    ],
    tips: [
      { key: 'howto.reporting.tip.1', default: 'Recomputing portfolio KPIs is limited to managers, so the trigger only appears if your role allows it.' },
    ],
    whenKey: 'howto.reporting.when',
    whenDefault: 'Use it for a recurring read-out of project health, tailored to whoever is looking.',
  },

  /* ── Controls & BI ────────────────────────────────────────────────────── */
  {
    id: 'project-controls',
    route: '/project-controls',
    icon: 'Gauge',
    category: 'controls',
    keywords: 'cost schedule quality safety risk change kpi drill cross module executive',
    titleKey: 'howto.project-controls.title',
    titleDefault: 'Project Controls',
    summaryKey: 'howto.project-controls.summary',
    summaryDefault: 'Cost, schedule, quality, safety, risk and change KPIs together in one traceable view.',
    whatKey: 'howto.project-controls.what',
    whatDefault:
      'Project Controls is the executive cross-module view: six domains - cost, schedule, quality, safety, risk and change - on one screen, every number status-banded green to red and traceable back to the records it came from. It pulls a single consolidated snapshot so you can spot a project slipping before it shows up anywhere else.',
    how: [
      { key: 'howto.project-controls.how.1', default: 'Open Project Controls to see the six domains as status-banded tiles for the project in context.' },
      { key: 'howto.project-controls.how.2', default: 'Scan for amber and red tiles, and read the alerts to see what is off track.' },
      { key: 'howto.project-controls.how.3', default: 'Click a tile to open the drill drawer and trace the number back to the source records in its owning module.' },
    ],
    tips: [
      { key: 'howto.project-controls.tip.1', default: 'Scope follows the project switcher: pick a project to scope to it, or clear it to see the whole portfolio.' },
    ],
    whenKey: 'howto.project-controls.when',
    whenDefault: 'Use it as the single board you check to know whether a project, or the portfolio, is on track.',
  },
  {
    id: 'bi-dashboards',
    route: '/bi-dashboards',
    icon: 'PieChart',
    category: 'controls',
    keywords: 'business intelligence widgets kpi definitions reports schedules alerts starter pack',
    titleKey: 'howto.bi-dashboards.title',
    titleDefault: 'BI Dashboards',
    summaryKey: 'howto.bi-dashboards.summary',
    summaryDefault: 'Build your own dashboards from KPIs, widgets, reports, schedules and alerts.',
    whatKey: 'howto.bi-dashboards.what',
    whatDefault:
      'BI Dashboards is the build-it-yourself business-intelligence layer. Define the KPIs that matter, arrange them into dashboards as widgets, save reports, schedule them to run, and set alerts that fire when a metric crosses a threshold. A starter pack gets you a useful set without building from scratch.',
    how: [
      { key: 'howto.bi-dashboards.how.1', default: 'Install the starter pack for a ready-made set, or create a dashboard and add widgets to it.' },
      { key: 'howto.bi-dashboards.how.2', default: 'Define KPIs and drop them onto a dashboard, choosing how each one is displayed.' },
      { key: 'howto.bi-dashboards.how.3', default: 'Save reports and schedule them to run, and set alerts so a metric crossing a threshold notifies you.' },
    ],
    tips: [
      { key: 'howto.bi-dashboards.tip.1', default: 'Money widgets always show their currency code; portfolio rollups with no single base currency show the amount with a neutral marker instead.' },
    ],
    whenKey: 'howto.bi-dashboards.when',
    whenDefault: 'Use it when the built-in views do not cover a metric you need to watch and you want to design your own.',
  },
  {
    id: 'dashboards',
    route: '/dashboards',
    icon: 'GitCompare',
    category: 'controls',
    keywords: 'snapshots baseline freeze compare diff timeline parquet cad bim dataset',
    titleKey: 'howto.dashboards.title',
    titleDefault: 'Snapshots',
    summaryKey: 'howto.dashboards.summary',
    summaryDefault: 'Freeze the project dataset into snapshots and compare how it changed over time.',
    whatKey: 'howto.dashboards.what',
    whatDefault:
      'Snapshots freezes the project data from your uploaded CAD and BIM files into a fixed dataset at a point in time. Each snapshot is a baseline you can keep, view on a timeline, and compare against another to see exactly what changed between two states of the project.',
    how: [
      { key: 'howto.dashboards.how.1', default: 'Create a snapshot from the uploaded CAD or BIM files to freeze the current project dataset.' },
      { key: 'howto.dashboards.how.2', default: 'Browse the list or the timeline to see every snapshot taken for the project.' },
      { key: 'howto.dashboards.how.3', default: 'Pick an older snapshot and a newer one, then open the diff view to see what changed between them.' },
    ],
    tips: [
      { key: 'howto.dashboards.tip.1', default: 'Take a snapshot at each milestone so you always have a clean baseline to compare later changes against.' },
    ],
    whenKey: 'howto.dashboards.when',
    whenDefault: 'Use it when you need a frozen reference point or want to prove what changed between two stages of a project.',
  },
];
