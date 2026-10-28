// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Model coordination domain.
// See ../types.ts for the shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const coordinationModules: ModuleExplanation[] = [
  {
    id: 'coordination',
    route: '/coordination',
    icon: 'Network',
    category: 'coordination',
    keywords: 'coordination hub federated bcf clash health discipline trade matrix',
    titleKey: 'howto.coordination.title',
    titleDefault: 'Model Coordination',
    summaryKey: 'howto.coordination.summary',
    summaryDefault: 'One health view that brings every discipline model together to find and resolve issues.',
    whatKey: 'howto.coordination.what',
    whatDefault:
      'Model Coordination is the hub for keeping the design disciplines aligned. It rolls up your federated models, clash results, rule-pack checks and issue activity for the active project into a single status view, so you can see where the models disagree and drive each problem to a resolution instead of chasing them across separate tools.',
    how: [
      { key: 'howto.coordination.how.1', default: 'Pick the project at the top; the dashboard refocuses on its models, clashes and open issues.' },
      { key: 'howto.coordination.how.2', default: 'Read the headline cards for federations, open clashes, rule checks and recent activity to see overall health at a glance.' },
      { key: 'howto.coordination.how.3', default: 'Use the clash-by-discipline-pair matrix to spot which trades collide most, and click a cell to drill into that filtered list.' },
      { key: 'howto.coordination.how.4', default: 'Jump to a task with the quick actions - review clashes, manage federations or run rule checks - then track progress on the activity timeline.' },
      { key: 'howto.coordination.how.5', default: 'Export a CSV snapshot to bring the current coordination status into a meeting or a report.' },
    ],
    tips: [
      { key: 'howto.coordination.tip.1', default: 'Set alert thresholds so the dashboard flags a project as needing attention before the open-clash count gets out of hand.' },
      { key: 'howto.coordination.tip.2', default: 'Widen the activity window to 90 days to see whether issues are genuinely closing or just being reopened.' },
    ],
    whenKey: 'howto.coordination.when',
    whenDefault: 'Use it before and during coordination meetings to set the agenda and confirm that last round of issues actually got resolved.',
  },
  {
    id: 'bim-federations',
    route: '/bim/federations',
    icon: 'Boxes',
    category: 'coordination',
    keywords: 'federation federated combine arch struct mep discipline merge models origin',
    titleKey: 'howto.bim-federations.title',
    titleDefault: 'BIM Federations',
    summaryKey: 'howto.bim-federations.summary',
    summaryDefault: 'Combine separate discipline models into one coordinated, federated model.',
    whatKey: 'howto.bim-federations.what',
    whatDefault:
      'A federation groups related models that share an origin - for example architectural, structural and MEP - into one coordinated set. Stitching the disciplines together this way gives you a single basis for clash checking, takeoff and reporting, and lets you watch how the combined model changes between coordination rounds.',
    how: [
      { key: 'howto.bim-federations.how.1', default: 'Create a federation for the project and give it a name and shared units.' },
      { key: 'howto.bim-federations.how.2', default: 'Add the discipline models as members, tagging each with its discipline so it is colour-coded in the set.' },
      { key: 'howto.bim-federations.how.3', default: 'Open the health tab to check readiness - which members are converted, populated and in sync, and which are lagging behind.' },
      { key: 'howto.bim-federations.how.4', default: 'Run clash detection straight from the federation once it has at least two members, or open any member in the 3D viewer.' },
    ],
    tips: [
      { key: 'howto.bim-federations.tip.1', default: 'Download a snapshot after each round, then compare a later one to see exactly which models were added, removed or grew between revisions.' },
    ],
    whenKey: 'howto.bim-federations.when',
    whenDefault: 'Set up a federation as soon as a second discipline issues a model, so coordination always runs against the full combined set.',
  },
  {
    id: 'clash',
    route: '/clash',
    icon: 'GitCompare',
    category: 'coordination',
    keywords: 'clash detection interference clearance collision bcf isolate discipline penetration',
    titleKey: 'howto.clash.title',
    titleDefault: 'Clash Detection',
    summaryKey: 'howto.clash.summary',
    summaryDefault: 'Find geometric clashes between models, then group and track them to resolution.',
    whatKey: 'howto.clash.what',
    whatDefault:
      'Clash Detection finds where elements from different models physically collide or sit too close for clearance. It checks the models geometrically, lays the results out in a discipline-by-discipline matrix and a full review list, and gives every clash a status so the team can work each one from open to resolved.',
    how: [
      { key: 'howto.clash.how.1', default: 'Choose the models to test - often the members of a federation - and run a clash check.' },
      { key: 'howto.clash.how.2', default: 'Use the matrix and filters to narrow by discipline pair, status, type, minimum penetration or a free-text search.' },
      { key: 'howto.clash.how.3', default: 'Open a clash to isolate the two clashing elements in the 3D viewer and judge whether it is real or can be suppressed.' },
      { key: 'howto.clash.how.4', default: 'Set a status and assign the issue to the responsible discipline, then re-run later to confirm it has gone.' },
      { key: 'howto.clash.how.5', default: 'Export issues to BCF, individually or in bulk, to hand them to a designer or a coordination meeting.' },
    ],
    tips: [
      { key: 'howto.clash.tip.1', default: 'Raise the minimum-penetration threshold to filter out trivial overlaps so the team focuses on the clashes that actually matter.' },
      { key: 'howto.clash.tip.2', default: 'Compare a new run against the previous one to see which clashes are newly introduced and which are finally cleared.' },
    ],
    whenKey: 'howto.clash.when',
    whenDefault: 'Run it every time a discipline issues an updated model, and again before any design freeze or coordination sign-off.',
  },
  {
    id: 'bim-rules',
    route: '/bim/rules',
    icon: 'ShieldCheck',
    category: 'coordination',
    keywords: 'rules compliance ids cobie eir naming properties completeness lod loi rule pack quantity link',
    titleKey: 'howto.bim-rules.title',
    titleDefault: 'BIM Rules',
    summaryKey: 'howto.bim-rules.summary',
    summaryDefault: 'Check incoming models against rules and standards for naming, properties and completeness.',
    whatKey: 'howto.bim-rules.what',
    whatDefault:
      'BIM Rules is where you set the standards a model has to meet and check it against them. Import information requirements - for example as IDS, COBie or a spreadsheet - and the page reports which elements carry the required classification, properties and level of information, and which fall short. The same page also lets you bulk-link matching elements to BOQ positions with pattern-based rules.',
    how: [
      { key: 'howto.bim-rules.how.1', default: 'Import or pick a rule set that captures your naming, property and completeness requirements.' },
      { key: 'howto.bim-rules.how.2', default: 'Select the BIM model to check and run the rules against it.' },
      { key: 'howto.bim-rules.how.3', default: 'Review the results to see which requirements pass and which elements are missing the expected data.' },
      { key: 'howto.bim-rules.how.4', default: 'Send the gaps back to the model author to fix, or use a quantity rule to bulk-link matching elements straight to BOQ positions.' },
    ],
    tips: [
      { key: 'howto.bim-rules.tip.1', default: 'Run the checks on every incoming revision so missing properties are caught early, while there is still time to correct them at source.' },
    ],
    whenKey: 'howto.bim-rules.when',
    whenDefault: 'Use it as the gate for accepting a model into coordination, and to confirm the data is complete enough for takeoff and handover.',
  },
  {
    id: 'requirements-matrix',
    route: '/requirements/matrix',
    icon: 'ClipboardCheck',
    category: 'coordination',
    keywords: 'requirements matrix eir iso 19650 deliverable coverage lod loi information cobie pset',
    titleKey: 'howto.requirements-matrix.title',
    titleDefault: 'Requirements Matrix',
    summaryKey: 'howto.requirements-matrix.summary',
    summaryDefault: 'Track what information must be delivered and whether it is actually present.',
    whatKey: 'howto.requirements-matrix.what',
    whatDefault:
      'The Requirements Matrix is an information-requirements register. Each row is a requirement written as an entity, an attribute and a constraint; each column is a kind of deliverable that can prove it - model, drawing, schedule, report, COBie or property set. The grid gives you a live, colour-coded read-out of how much of the required information has actually been delivered and accepted.',
    how: [
      { key: 'howto.requirements-matrix.how.1', default: 'Create a requirement set for the project to hold its requirements.' },
      { key: 'howto.requirements-matrix.how.2', default: 'Add requirements as rows - for example exterior wall, fire rating, equals F90 - with a priority for each.' },
      { key: 'howto.requirements-matrix.how.3', default: 'Click a cell to attach the deliverable that satisfies a requirement and record its level of information and status.' },
      { key: 'howto.requirements-matrix.how.4', default: 'Watch the colours - green for accepted, amber for submitted, red for missing - and work the red cells until the coverage is complete.' },
    ],
    tips: [
      { key: 'howto.requirements-matrix.tip.1', default: 'Mark the truly essential requirements as must so a reviewer can tell critical gaps apart from nice-to-have ones at a glance.' },
    ],
    whenKey: 'howto.requirements-matrix.when',
    whenDefault: 'Use it to agree deliverables at the start of a project and to prove, at each milestone, that the required information was handed over.',
  },
  {
    id: 'assets',
    route: '/assets',
    icon: 'Box',
    category: 'coordination',
    keywords: 'asset register cobie handover operations equipment fixtures serial manufacturer facilities',
    titleKey: 'howto.assets.title',
    titleDefault: 'Asset Register',
    summaryKey: 'howto.assets.summary',
    summaryDefault: 'The register of building assets and components handed over for operation.',
    whatKey: 'howto.assets.what',
    whatDefault:
      'The Asset Register lists every model element flagged as a tracked asset - the installed equipment, fixtures and systems that the operator will run after handover. It carries operational data such as manufacturer, model and serial number, so the information captured during design and construction follows the building into facilities management.',
    how: [
      { key: 'howto.assets.how.1', default: 'Open it on a project; it lists the model elements marked as tracked assets.' },
      { key: 'howto.assets.how.2', default: 'Search across manufacturer, model and serial, or filter by operational status to find a specific asset.' },
      { key: 'howto.assets.how.3', default: 'Edit a row to record operational details on the element, or open it in the 3D viewer to see it in context.' },
      { key: 'howto.assets.how.4', default: 'Export the register as COBie to hand the asset data over to the operator or a facilities-management system.' },
    ],
    tips: [
      { key: 'howto.assets.tip.1', default: 'This register is for installed building assets and fixtures from the model; for plant, vehicles and movable machinery use Equipment and Fleet instead.' },
    ],
    whenKey: 'howto.assets.when',
    whenDefault: 'Use it as the project nears handover, to assemble and check the asset data the operations team will depend on.',
  },
];
