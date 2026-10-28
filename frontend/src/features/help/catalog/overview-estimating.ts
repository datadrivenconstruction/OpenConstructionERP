// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Overview + Estimating domains.
// See ../types.ts for the ModuleExplanation shape and the key convention.

import type { ModuleExplanation } from '../types';

export const overviewEstimatingModules: ModuleExplanation[] = [
  /* ── Overview ─────────────────────────────────────────────────────────── */
  {
    id: 'dashboard',
    route: '/dashboard',
    icon: 'LayoutDashboard',
    category: 'overview',
    titleKey: 'howto.dashboard.title',
    titleDefault: 'Dashboard',
    summaryKey: 'howto.dashboard.summary',
    summaryDefault: 'Your home screen: a live snapshot of the active project and what needs attention.',
    whatKey: 'howto.dashboard.what',
    whatDefault:
      'The Dashboard is where every working day starts. It pulls the headline numbers for the project you are in - cost, progress, open items and recent activity - into one screen so you can see the state of the job without opening each module.',
    how: [
      { key: 'howto.dashboard.how.1', default: 'Pick the project you want to work on from the project switcher at the top; the whole dashboard refocuses on it.' },
      { key: 'howto.dashboard.how.2', default: 'Read the summary cards for cost, schedule and open actions to spot anything off-track at a glance.' },
      { key: 'howto.dashboard.how.3', default: 'Click any card or recent-activity row to jump straight into the module behind it.' },
      { key: 'howto.dashboard.how.4', default: 'Use the project journey guide to see which stage you are at and what comes next.' },
    ],
    tips: [
      { key: 'howto.dashboard.tip.1', default: 'If the numbers look empty, check the project switcher - you may be viewing a project with no data yet.' },
    ],
    whenKey: 'howto.dashboard.when',
    whenDefault: 'Start here every session to orient yourself before diving into a specific task.',
  },
  {
    id: 'projects',
    route: '/projects',
    icon: 'FolderKanban',
    category: 'overview',
    titleKey: 'howto.projects.title',
    titleDefault: 'Projects',
    summaryKey: 'howto.projects.summary',
    summaryDefault: 'Create and manage the projects that everything else hangs off.',
    whatKey: 'howto.projects.what',
    whatDefault:
      'A project is the container for all your work: estimates, files, schedules, costs and documents all belong to one. This is where you create projects, set their basics and switch the active one.',
    how: [
      { key: 'howto.projects.how.1', default: 'Click New project and give it a name, client and location; you can refine the details later.' },
      { key: 'howto.projects.how.2', default: 'Open a project to make it active - every other module then works inside that project.' },
      { key: 'howto.projects.how.3', default: 'Use the list to archive finished work or duplicate a project as a starting point for the next one.' },
    ],
    tips: [
      { key: 'howto.projects.tip.1', default: 'Keep one project per real job. Mixing several jobs into one makes every report harder to read.' },
    ],
    whenKey: 'howto.projects.when',
    whenDefault: 'Set up a project first - most modules need an active project to show meaningful data.',
  },
  {
    id: 'files',
    route: '/files',
    icon: 'FolderOpen',
    category: 'overview',
    titleKey: 'howto.files.title',
    titleDefault: 'Project Files',
    summaryKey: 'howto.files.summary',
    summaryDefault: 'A versioned home for drawings, models and documents on the project.',
    whatKey: 'howto.files.what',
    whatDefault:
      'Project Files is the file manager for the job. Upload drawings, models, spreadsheets and documents; they are versioned, searchable and can be opened directly by the takeoff, BIM and document modules.',
    how: [
      { key: 'howto.files.how.1', default: 'Drag files in or use Upload; large CAD and BIM files upload in the background and resume if interrupted.' },
      { key: 'howto.files.how.2', default: 'Organise into folders, then open a file to view it or send it to the matching tool (PDF takeoff, BIM viewer, converters).' },
      { key: 'howto.files.how.3', default: 'Replace a file to create a new version; older versions stay available so nothing is lost.' },
      { key: 'howto.files.how.4', default: 'Use search across projects to find a file by name even when you are not sure which job it is in.' },
    ],
    tips: [
      { key: 'howto.files.tip.1', default: 'Deleted files go to the recycle bin first, so an accidental delete is recoverable.' },
    ],
  },

  /* ── Estimating ───────────────────────────────────────────────────────── */
  {
    id: 'boq',
    route: '/boq',
    icon: 'Calculator',
    category: 'estimating',
    keywords: 'bill of quantities estimate lv leistungsverzeichnis priced positions',
    titleKey: 'howto.boq.title',
    titleDefault: 'Bill of Quantities',
    summaryKey: 'howto.boq.summary',
    summaryDefault: 'Build a structured, priced list of every item of work - the heart of an estimate.',
    whatKey: 'howto.boq.what',
    whatDefault:
      'A Bill of Quantities (BOQ) is a structured, priced list of every item of work in a project. You build it top-down: sections that group the work, then positions inside them, then the quantities and rates that drive the cost. It is the central document the rest of the platform feeds and reads.',
    how: [
      { key: 'howto.boq.how.1', default: 'Create sections to group the work, then add positions under them - each with a description, unit, quantity and unit rate.' },
      { key: 'howto.boq.how.2', default: 'Fill rates fast by pulling priced items From Database or From Assembly instead of typing them, or import from Excel, GAEB, CAD or PDF.' },
      { key: 'howto.boq.how.3', default: 'Add markups - overhead, profit, contingency and tax - as percentages on top of the net total to reach the gross.' },
      { key: 'howto.boq.how.4', default: 'Watch the live quality ring flag missing quantities, zero prices and duplicates as you work.' },
      { key: 'howto.boq.how.5', default: 'Export to GAEB, Excel, CSV or PDF, or freeze a revision to keep a snapshot you can compare against later.' },
    ],
    tips: [
      { key: 'howto.boq.tip.1', default: 'Rates are net - no tax or markup is baked into a position. Keep all markup in the markup panel so the maths stays auditable.' },
      { key: 'howto.boq.tip.2', default: 'Double-click a description to open the full long-text for detailed specifications.' },
    ],
    whenKey: 'howto.boq.when',
    whenDefault: 'Use it for every priced estimate, tender or budget - it is the spine the whole estimate is built on.',
  },
  {
    id: 'templates',
    route: '/templates',
    icon: 'FileText',
    category: 'estimating',
    titleKey: 'howto.templates.title',
    titleDefault: 'BOQ Templates',
    summaryKey: 'howto.templates.summary',
    summaryDefault: 'Reusable BOQ skeletons so you never start an estimate from a blank page.',
    whatKey: 'howto.templates.what',
    whatDefault:
      'A template is a saved BOQ structure - the sections and typical positions for a kind of job - that you can drop into a new estimate. It captures your standard way of pricing so each new bid starts consistent and complete.',
    how: [
      { key: 'howto.templates.how.1', default: 'Browse the template gallery and pick one that matches the job type.' },
      { key: 'howto.templates.how.2', default: 'Apply it to a project to create a ready-made BOQ structure, then adjust quantities and rates for the specific job.' },
      { key: 'howto.templates.how.3', default: 'Save any BOQ you are proud of back as a template to reuse its structure next time.' },
    ],
    tips: [
      { key: 'howto.templates.tip.1', default: 'Templates carry structure, not final prices - always review rates against current cost data before you submit.' },
    ],
  },
  {
    id: 'ai-estimator',
    route: '/ai-estimator',
    icon: 'Wand2',
    category: 'estimating',
    beta: true,
    titleKey: 'howto.ai-estimator.title',
    titleDefault: 'AI Estimate Builder',
    summaryKey: 'howto.ai-estimator.summary',
    summaryDefault: 'Describe the job and get a first-draft BOQ to refine, not retype.',
    whatKey: 'howto.ai-estimator.what',
    whatDefault:
      'The AI Estimate Builder turns a plain description of a project into a structured first-draft BOQ. It proposes sections, positions and quantities so you start from a sensible draft and spend your time checking and pricing instead of typing from scratch.',
    how: [
      { key: 'howto.ai-estimator.how.1', default: 'Describe the project in plain language - type, size, scope and any specifics you know.' },
      { key: 'howto.ai-estimator.how.2', default: 'Review the proposed sections and positions; the tool shows its reasoning so you can judge each suggestion.' },
      { key: 'howto.ai-estimator.how.3', default: 'Accept what fits into a real BOQ, then price it from your cost data and adjust quantities.' },
    ],
    tips: [
      { key: 'howto.ai-estimator.tip.1', default: 'Treat the output as a knowledgeable first draft, never a final estimate - you stay responsible for every number that ships.' },
    ],
    whenKey: 'howto.ai-estimator.when',
    whenDefault: 'Use it to break the blank-page problem on a new estimate or to sanity-check that you have not missed a trade.',
  },
  {
    id: 'match-elements',
    route: '/match-elements',
    icon: 'Link2',
    category: 'estimating',
    beta: true,
    titleKey: 'howto.match-elements.title',
    titleDefault: 'Match Elements',
    summaryKey: 'howto.match-elements.summary',
    summaryDefault: 'Map model or import elements to priced catalog items automatically.',
    whatKey: 'howto.match-elements.what',
    whatDefault:
      'Match Elements connects raw items - BIM elements, imported rows or takeoff results - to priced items in your cost catalog. It scores likely matches so you can price a model-derived quantity list in minutes instead of hand-mapping every line.',
    how: [
      { key: 'howto.match-elements.how.1', default: 'Bring in elements from a model, takeoff or import; each needs a description the matcher can read.' },
      { key: 'howto.match-elements.how.2', default: 'Review the ranked match suggestions and confirm the right catalog item for each element.' },
      { key: 'howto.match-elements.how.3', default: 'Push the confirmed matches into your BOQ as priced positions.' },
    ],
    tips: [
      { key: 'howto.match-elements.tip.1', default: 'Low scores on sparse or synthetic data are honest, not a bug - richer descriptions and a fuller catalog raise match quality.' },
    ],
  },
  {
    id: 'project-intelligence',
    route: '/project-intelligence',
    icon: 'Brain',
    category: 'estimating',
    titleKey: 'howto.project-intelligence.title',
    titleDefault: 'Project Intelligence',
    summaryKey: 'howto.project-intelligence.summary',
    summaryDefault: 'A read-out of the estimate quality: gaps, outliers and how complete it is.',
    whatKey: 'howto.project-intelligence.what',
    whatDefault:
      'Project Intelligence analyses your estimate and surfaces what a reviewer would look for: missing quantities, suspicious rates, thin sections and overall completeness. It is the pre-submission health check for the numbers.',
    how: [
      { key: 'howto.project-intelligence.how.1', default: 'Open it on a project with a BOQ in progress; it scores the estimate across several quality dimensions.' },
      { key: 'howto.project-intelligence.how.2', default: 'Work through the flagged items - each links back to the position that needs attention.' },
      { key: 'howto.project-intelligence.how.3', default: 'Re-check before you submit to confirm the gaps are closed.' },
    ],
    whenKey: 'howto.project-intelligence.when',
    whenDefault: 'Run it before a tender goes out, as a second pair of eyes on the estimate.',
  },
  {
    id: 'methodologies',
    route: '/methodologies',
    icon: 'Layers3',
    category: 'estimating',
    keywords: 'markup cascade vat equipment split funding analytical',
    titleKey: 'howto.methodologies.title',
    titleDefault: 'Methodologies',
    summaryKey: 'howto.methodologies.summary',
    summaryDefault: 'Define how raw cost becomes a final price - markup cascades per country or client.',
    whatKey: 'howto.methodologies.what',
    whatDefault:
      'A methodology is the recipe that turns base cost into a final price: the ordered markup steps, the works-versus-equipment split, base sets, VAT and funding sources. Install a built-in one for your country or build your own, then make it the active method for a project.',
    how: [
      { key: 'howto.methodologies.how.1', default: 'Browse the built-in templates and install one that matches how you price in your market.' },
      { key: 'howto.methodologies.how.2', default: 'Open the cascade editor to adjust the ordered percentage steps, splits and VAT to your standard.' },
      { key: 'howto.methodologies.how.3', default: 'Set the methodology active on a project so its BOQ totals use your cascade.' },
    ],
    tips: [
      { key: 'howto.methodologies.tip.1', default: 'You can switch a project between your detailed cascade and the simple international flat method at any time.' },
    ],
  },
];
