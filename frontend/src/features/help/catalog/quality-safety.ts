// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Quality + Safety & ESG domains.
// See ../types.ts for the ModuleExplanation shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const qualitySafetyModules: ModuleExplanation[] = [
  /* ── Quality ──────────────────────────────────────────────────────────── */
  {
    id: 'validation',
    route: '/validation',
    icon: 'ShieldCheck',
    category: 'quality',
    keywords: 'rules check estimate quality gate score errors warnings standards',
    titleKey: 'howto.validation.title',
    titleDefault: 'Validation',
    summaryKey: 'howto.validation.summary',
    summaryDefault: 'Run rule checks over an estimate and get a pass, warning and error score before it goes out.',
    whatKey: 'howto.validation.what',
    whatDefault:
      'Validation runs a set of rules against a BOQ and reports what a reviewer would catch: missing quantities, zero prices, duplicates, broken structure and standard-specific issues. Each rule reports as a pass, a warning or an error, and the run gives the estimate an overall quality score so you can fix problems before submitting.',
    how: [
      { key: 'howto.validation.how.1', default: 'Pick the project and the BOQ you want to check, then choose which rule sets to apply.' },
      { key: 'howto.validation.how.2', default: 'Run the validation; it scores the estimate and lists every rule result grouped by severity - errors, warnings and information.' },
      { key: 'howto.validation.how.3', default: 'Work through the failures - each item points at the position or area that needs attention, often with a suggested fix.' },
      { key: 'howto.validation.how.4', default: 'Re-run after editing to confirm the score has improved, then export the report as a record.' },
    ],
    tips: [
      { key: 'howto.validation.tip.1', default: 'A rule set that has no implemented rules is shown as not-supported rather than silently passing, so a green result always means real checks ran.' },
      { key: 'howto.validation.tip.2', default: 'Errors block a clean result; warnings are advisory. Clear the errors first, then judge the warnings case by case.' },
    ],
    whenKey: 'howto.validation.when',
    whenDefault: 'Run it as the final gate before a tender or budget leaves your hands.',
  },
  {
    id: 'inspections',
    route: '/inspections',
    icon: 'ClipboardCheck',
    category: 'quality',
    keywords: 'site quality inspection checklist pass fail hold point concrete pour mep',
    titleKey: 'howto.inspections.title',
    titleDefault: 'Inspections',
    summaryKey: 'howto.inspections.summary',
    summaryDefault: 'Schedule and record quality inspections on site, with checklists and pass or fail results.',
    whatKey: 'howto.inspections.what',
    whatDefault:
      'Inspections is where site quality checks are planned, carried out and recorded. You raise an inspection for a discipline - structural, concrete, electrical, plumbing, fire safety and more - work through its checklist on site, and log the result as pass, fail or partial so there is a dated record of what was verified.',
    how: [
      { key: 'howto.inspections.how.1', default: 'Create an inspection, choosing its type and the location or element being checked, and schedule it.' },
      { key: 'howto.inspections.how.2', default: 'On site, run through the checklist items and mark each one off as you verify it.' },
      { key: 'howto.inspections.how.3', default: 'Complete the inspection with a pass, fail or partial result; a fail can raise a non-conformance report directly.' },
      { key: 'howto.inspections.how.4', default: 'Export the record so the inspection history travels with the project.' },
    ],
    tips: [
      { key: 'howto.inspections.tip.1', default: 'When an inspection fails, raise the NCR straight from it so the defect is linked back to the check that found it.' },
    ],
    whenKey: 'howto.inspections.when',
    whenDefault: 'Use it for every quality hold point and witness check during construction.',
  },
  {
    id: 'ncr',
    route: '/ncr',
    icon: 'ShieldAlert',
    category: 'quality',
    keywords: 'non conformance report defect disposition corrective action quality major minor',
    titleKey: 'howto.ncr.title',
    titleDefault: 'Non-Conformance Reports',
    summaryKey: 'howto.ncr.summary',
    summaryDefault: 'Log defects, rate their severity and drive them through corrective action to closure.',
    whatKey: 'howto.ncr.what',
    whatDefault:
      'A non-conformance report (NCR) records work that does not meet the specification - a material, workmanship, design, documentation or safety issue. Each NCR carries a severity, moves through a clear lifecycle from identified to closed, and captures the corrective action and verification so nothing is signed off until it is genuinely fixed.',
    how: [
      { key: 'howto.ncr.how.1', default: 'Raise an NCR describing the defect, then set its type and severity from observation up to critical.' },
      { key: 'howto.ncr.how.2', default: 'Move it through the workflow - under review, corrective action, then verification - as the problem is worked.' },
      { key: 'howto.ncr.how.3', default: 'Record the corrective action taken and verify the fix on site.' },
      { key: 'howto.ncr.how.4', default: 'Close the NCR once verified, leaving a complete audit trail of how it was resolved.' },
    ],
    tips: [
      { key: 'howto.ncr.tip.1', default: 'NCRs can be raised automatically from a failed inspection, so the defect keeps its link to the check that found it.' },
    ],
    whenKey: 'howto.ncr.when',
    whenDefault: 'Open one whenever work fails an inspection or is found not to meet the specification.',
  },
  {
    id: 'punchlist',
    route: '/punchlist',
    icon: 'ClipboardList',
    category: 'quality',
    keywords: 'snag punch list defects closeout kanban resolved verified photos',
    titleKey: 'howto.punchlist.title',
    titleDefault: 'Punch List',
    summaryKey: 'howto.punchlist.summary',
    summaryDefault: 'Track every snag from open to closed so the project can reach a clean handover.',
    whatKey: 'howto.punchlist.what',
    whatDefault:
      'The Punch List (or snag list) collects the small outstanding items that must be put right before handover. Each item has a priority, a category and an owner, and moves across a board from open through in progress, resolved and verified to closed, so you can see at a glance how close the job is to done.',
    how: [
      { key: 'howto.punchlist.how.1', default: 'Add a punch item with a description, location, category and priority, and assign it to a team member.' },
      { key: 'howto.punchlist.how.2', default: 'Attach a photo so whoever fixes it can see exactly what and where the issue is.' },
      { key: 'howto.punchlist.how.3', default: 'Drag items across the board as they progress - open, in progress, resolved, verified, closed.' },
      { key: 'howto.punchlist.how.4', default: 'Verify completed work and close items, using bulk close to clear a batch once a list is signed off.' },
    ],
    tips: [
      { key: 'howto.punchlist.tip.1', default: 'Keep priorities honest - reserve critical for items that genuinely block handover so the team trusts the board.' },
    ],
    whenKey: 'howto.punchlist.when',
    whenDefault: 'Run it through the finishing stages, then drive it to zero before practical completion.',
  },
  {
    id: 'closeout',
    route: '/closeout',
    icon: 'ClipboardCheck',
    category: 'quality',
    keywords: 'handover closeout package o&m manuals warranties as built documents slots verified',
    titleKey: 'howto.closeout.title',
    titleDefault: 'Handover & Closeout',
    summaryKey: 'howto.closeout.summary',
    summaryDefault: 'Assemble the handover pack - every required document slot bound, verified and delivered.',
    whatKey: 'howto.closeout.what',
    whatDefault:
      'Handover and Closeout assembles the deliverables a client expects at the end of a job - as-built drawings, operation and maintenance manuals, warranties, certificates and more. The package is a checklist of document slots; you bind the right file to each slot, verify it, and build a single downloadable handover pack once everything is complete.',
    how: [
      { key: 'howto.closeout.how.1', default: 'Create a closeout package for the project, choosing the project type so the right slots are listed.' },
      { key: 'howto.closeout.how.2', default: 'Bind a project document to each required slot, using the suggested matches to speed it up.' },
      { key: 'howto.closeout.how.3', default: 'Verify each bound slot so the pack only contains documents someone has actually checked.' },
      { key: 'howto.closeout.how.4', default: 'Build the package once the slots are complete, then download the finished handover pack.' },
    ],
    tips: [
      { key: 'howto.closeout.tip.1', default: 'A slot moves from empty to bound to verified - aim for every slot verified before you build, so the client gets a complete, checked pack.' },
    ],
    whenKey: 'howto.closeout.when',
    whenDefault: 'Use it at project completion to package and deliver the handover documentation.',
  },
  {
    id: 'qms',
    route: '/qms',
    icon: 'ShieldCheck',
    category: 'quality',
    keywords: 'quality management system itp inspection test plan hold point audit copq cost of poor quality',
    titleKey: 'howto.qms.title',
    titleDefault: 'Quality Management',
    summaryKey: 'howto.qms.summary',
    summaryDefault: 'The quality management hub: inspection and test plans, inspections, NCRs, punch items and audits in one place.',
    whatKey: 'howto.qms.what',
    whatDefault:
      'Quality Management ties the whole quality system together. It holds inspection and test plans (ITPs) with hold points, the inspections that satisfy them, non-conformance reports, punch items and quality audits, plus a cost-of-poor-quality view. It is the procedures-and-records backbone that shows quality is being planned, executed and signed off.',
    how: [
      { key: 'howto.qms.how.1', default: 'Build an inspection and test plan listing the checks, hold points and witness points for the work, then activate it.' },
      { key: 'howto.qms.how.2', default: 'Carry out the planned inspections and capture sign-offs and evidence against each item.' },
      { key: 'howto.qms.how.3', default: 'Log and resolve non-conformances and punch items, escalating a serious NCR to a variation when it has a commercial impact.' },
      { key: 'howto.qms.how.4', default: 'Run quality audits and review the cost of poor quality to see where rework is hurting the project.' },
    ],
    tips: [
      { key: 'howto.qms.tip.1', default: 'A hold point cannot be passed until its inspection is released, so the plan enforces the right sequence of checks.' },
      { key: 'howto.qms.tip.2', default: 'Link inspection and test plan items to the specification so each check is traceable back to a requirement.' },
    ],
    whenKey: 'howto.qms.when',
    whenDefault: 'Use it to run a structured quality programme across the project, not just one-off checks.',
  },

  /* ── Safety & ESG ─────────────────────────────────────────────────────── */
  {
    id: 'safety',
    route: '/safety',
    icon: 'HardHat',
    category: 'safety',
    keywords: 'health safety incidents observations near miss days lost trir metrics',
    titleKey: 'howto.safety.title',
    titleDefault: 'Safety',
    summaryKey: 'howto.safety.summary',
    summaryDefault: 'Record incidents and observations and watch the safety metrics that come out of them.',
    whatKey: 'howto.safety.what',
    whatDefault:
      'Safety is where site health and safety is logged and measured. You record incidents with their type, severity and days lost, capture observations and near misses with a risk score and corrective action, and the module turns that data into trends and threshold alerts so safety performance is visible, not anecdotal.',
    how: [
      { key: 'howto.safety.how.1', default: 'Log an incident with its date, type, severity and any days lost, and note who reported it.' },
      { key: 'howto.safety.how.2', default: 'Record observations and near misses, scoring the risk and capturing the corrective action taken.' },
      { key: 'howto.safety.how.3', default: 'Watch the trend charts and threshold widgets to see whether safety performance is improving.' },
      { key: 'howto.safety.how.4', default: 'Export the records when you need to report figures to a client or regulator.' },
    ],
    tips: [
      { key: 'howto.safety.tip.1', default: 'Capturing near misses as well as incidents gives you leading indicators - the warning signs before something serious happens.' },
    ],
    whenKey: 'howto.safety.when',
    whenDefault: 'Use it daily on site to log events and keep safety metrics current.',
  },
  {
    id: 'hse-advanced',
    route: '/hse-advanced',
    icon: 'HardHat',
    category: 'safety',
    keywords: 'hse permit to work jsa job safety analysis toolbox talk ppe capa investigation osha audit',
    titleKey: 'howto.hse-advanced.title',
    titleDefault: 'HSE Management',
    summaryKey: 'howto.hse-advanced.summary',
    summaryDefault: 'The full HSE toolkit: permits to work, job safety analyses, toolbox talks, PPE, audits and corrective actions.',
    whatKey: 'howto.hse-advanced.what',
    whatDefault:
      'HSE Management is the advanced health, safety and environment workspace that sits above day-to-day incident logging. It covers incident investigations, job safety analyses, permits to work with a controlled approval lifecycle, toolbox talks, PPE issue records, safety audits and corrective and preventive actions, plus headline HSE indicators.',
    how: [
      { key: 'howto.hse-advanced.how.1', default: 'Plan the work safely - raise a job safety analysis and issue a permit to work, moving it from requested through approved to active.' },
      { key: 'howto.hse-advanced.how.2', default: 'Run toolbox talks and record PPE issued so briefings and equipment are documented.' },
      { key: 'howto.hse-advanced.how.3', default: 'Investigate incidents and carry out safety audits, logging the findings.' },
      { key: 'howto.hse-advanced.how.4', default: 'Drive corrective and preventive actions to closure, using a five-whys root cause and an effectiveness check before sign-off.' },
    ],
    tips: [
      { key: 'howto.hse-advanced.tip.1', default: 'A permit follows a strict lifecycle - it can be suspended and reactivated, so high-risk work is always under live control.' },
      { key: 'howto.hse-advanced.tip.2', default: 'Incident records can be exported in an OSHA 300 layout when you need to report against that standard.' },
    ],
    whenKey: 'howto.hse-advanced.when',
    whenDefault: 'Use it on larger or higher-risk projects that need permits, JSAs and a formal HSE programme.',
  },
  {
    id: 'carbon',
    route: '/carbon',
    icon: 'Leaf',
    category: 'safety',
    keywords: 'carbon esg ghg scope 1 2 3 embodied epd targets reporting gri issb okobaudat',
    titleKey: 'howto.carbon.title',
    titleDefault: 'Carbon & ESG',
    summaryKey: 'howto.carbon.summary',
    summaryDefault: 'Track embodied and operational carbon, set reduction targets and produce GHG reports.',
    whatKey: 'howto.carbon.what',
    whatDefault:
      'Carbon & ESG is the project carbon ledger. Embodied carbon comes from the BOQ - each position is multiplied by a material carbon factor from EPD sources or a manual override - alongside Scope 1, 2 and 3 operational emissions. You manage inventories and EPDs, set reduction targets against a baseline, and package the results as standards-based reports.',
    how: [
      { key: 'howto.carbon.how.1', default: 'Create a carbon inventory for the project to hold its embodied and operational emissions.' },
      { key: 'howto.carbon.how.2', default: 'Add embodied entries from the BOQ and record Scope 1, 2 and 3 activity to roll up lifecycle stages A1 to D.' },
      { key: 'howto.carbon.how.3', default: 'Set reduction targets, then track current emissions against the baseline year.' },
      { key: 'howto.carbon.how.4', default: 'Review top emitters and their lower-carbon alternatives, and generate a GHG, GRI or ISSB report.' },
    ],
    tips: [
      { key: 'howto.carbon.tip.1', default: 'EPD factors are drawn from recognised sources, with a manual override when you have a product-specific figure.' },
      { key: 'howto.carbon.tip.2', default: 'For a quick per-estimate footprint without a full inventory, use the Sustainability module instead.' },
    ],
    whenKey: 'howto.carbon.when',
    whenDefault: 'Use it when the project needs proper carbon accounting and ESG reporting across its lifecycle.',
  },
  {
    id: 'sustainability',
    route: '/sustainability',
    icon: 'Leaf',
    category: 'safety',
    keywords: 'embodied carbon epd lifecycle co2 gwp boq footprint en 15804 benchmark',
    titleKey: 'howto.sustainability.title',
    titleDefault: 'Sustainability',
    summaryKey: 'howto.sustainability.summary',
    summaryDefault: 'Read a BOQ carbon footprint position by position, with a per-square-metre benchmark.',
    whatKey: 'howto.sustainability.what',
    whatDefault:
      'Sustainability gives a fast embodied-carbon read of a single bill of quantities. It matches each position to EPD material factors, totals the embodied CO2, and shows a per-square-metre benchmark with a breakdown by material category down to each position. It is the quick per-BOQ view, while the Carbon module holds full inventories, scopes and standards reporting.',
    how: [
      { key: 'howto.sustainability.how.1', default: 'Select a project and a BOQ, and enter the gross floor area for the benchmark.' },
      { key: 'howto.sustainability.how.2', default: 'Enrich the BOQ to auto-detect materials and attach EPD carbon factors to its positions.' },
      { key: 'howto.sustainability.how.3', default: 'Calculate to see the total embodied carbon, the rating against the per-square-metre benchmark and the category breakdown.' },
      { key: 'howto.sustainability.how.4', default: 'Refine the match by assigning a specific EPD material to any position, then export the CO2 report.' },
    ],
    tips: [
      { key: 'howto.sustainability.tip.1', default: 'A richer BOQ matches more positions to materials, so completing descriptions and quantities improves the carbon figure.' },
      { key: 'howto.sustainability.tip.2', default: 'This view depends on the BOQ - price and structure it first, then read its footprint here.' },
    ],
    whenKey: 'howto.sustainability.when',
    whenDefault: 'Use it to sense-check the carbon impact of an estimate while you are still pricing it.',
  },
];
