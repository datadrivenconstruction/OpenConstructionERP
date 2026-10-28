// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Field operations + Resources & assets domains.
// See ../types.ts for the shape + key convention, and
// ../catalog/overview-estimating.ts for a fully-worked example.

import type { ModuleExplanation } from '../types';

export const fieldResourcesModules: ModuleExplanation[] = [
  /* ── Field operations ─────────────────────────────────────────────────── */
  {
    id: 'daily-diary',
    route: '/daily-diary',
    icon: 'ClipboardList',
    category: 'field',
    keywords: 'site log weather labour plant events bautagebuch contemporaneous record signed',
    titleKey: 'howto.daily-diary.title',
    titleDefault: 'Daily Site Diary',
    summaryKey: 'howto.daily-diary.summary',
    summaryDefault: 'A signed, tamper-evident record of each day on site - your evidence when claims arrive.',
    whatKey: 'howto.daily-diary.what',
    whatDefault:
      'The Daily Site Diary is the contemporaneous record of what happened on site each day: weather, headcount, plant on the ground, deliveries and events. Once you close and sign a day it is sealed with a sha256 fingerprint, so it stands as tamper-evident proof in a delay claim or dispute.',
    how: [
      { key: 'howto.daily-diary.how.1', default: 'Pick a day on the calendar to open its diary, or start a new one for today; future days are blocked because a diary is a same-day record.' },
      { key: 'howto.daily-diary.how.2', default: 'Log the headcount and plant on site, then pull the weather automatically from the project location or add a reading by hand.' },
      { key: 'howto.daily-diary.how.3', default: 'Add entries for deliveries, visitors and events, and attach site photos, drone surveys or reality-capture scans.' },
      { key: 'howto.daily-diary.how.4', default: 'Watch the readiness chip; close the day, then sign it to seal the record with a sha256 fingerprint.' },
      { key: 'howto.daily-diary.how.5', default: 'Export a day to PDF, or build a hash-sealed evidence bundle across a date range for a claim.' },
    ],
    tips: [
      { key: 'howto.daily-diary.tip.1', default: 'A signed diary is locked. If you must amend it, unlocking is recorded against the original signature so the change stays traceable.' },
      { key: 'howto.daily-diary.tip.2', default: 'The headcount you log here flows into the labour roster Payroll reads, so log it accurately every day.' },
    ],
    whenKey: 'howto.daily-diary.when',
    whenDefault: 'Fill it in every working day - a gap in the record is the gap a claim will exploit.',
  },
  {
    id: 'field-reports',
    route: '/field-reports',
    icon: 'ClipboardList',
    category: 'field',
    keywords: 'daily inspection safety concrete pour workforce hours trade delays templated',
    titleKey: 'howto.field-reports.title',
    titleDefault: 'Field Reports',
    summaryKey: 'howto.field-reports.summary',
    summaryDefault: 'Structured, templated reports from site: daily, inspection, safety and concrete-pour.',
    whatKey: 'howto.field-reports.what',
    whatDefault:
      'Field Reports are the structured forms the site sends in: daily progress, inspections, safety observations and concrete-pour records. Each captures weather, workforce hours by trade, work performed and delays, and moves through an approval flow with a signature. Unlike the legally sealed Daily Diary, these are templated forms you can export and reuse.',
    how: [
      { key: 'howto.field-reports.how.1', default: 'Create a report and choose its type - daily, inspection, safety or concrete pour - to get the matching form.' },
      { key: 'howto.field-reports.how.2', default: 'Fill in weather, workforce hours by trade, work performed and any delays or incidents.' },
      { key: 'howto.field-reports.how.3', default: 'Move the report from draft to submitted, then approve it with a signature.' },
      { key: 'howto.field-reports.how.4', default: 'Export an approved report to PDF or Excel to share it outside the platform.' },
    ],
    tips: [
      { key: 'howto.field-reports.tip.1', default: 'Workforce hours logged here roll up into Payroll and progress, so record them by trade rather than as a single total.' },
    ],
    whenKey: 'howto.field-reports.when',
    whenDefault: 'Use these for the structured paperwork of the job; reach for the Daily Diary when you need a sealed legal record.',
  },
  {
    id: 'service',
    route: '/service',
    icon: 'HardHat',
    category: 'field',
    keywords: 'maintenance tickets work orders contracts assets sla dispatch technician billing',
    titleKey: 'howto.service.title',
    titleDefault: 'Service & Maintenance',
    summaryKey: 'howto.service.summary',
    summaryDefault: 'Run maintenance jobs end to end: from a customer call to a billed visit.',
    whatKey: 'howto.service.what',
    whatDefault:
      'Service & Maintenance manages reactive and planned upkeep of the assets you look after. A service contract covers a customer and the assets it includes; a ticket is raised when something needs attention; dispatching the ticket creates a work order that schedules an engineer; and once the work is completed with a debrief it can be billed.',
    how: [
      { key: 'howto.service.how.1', default: 'Set up a service contract for a customer and register the assets it covers, such as lifts, HVAC or generators.' },
      { key: 'howto.service.how.2', default: 'Log a ticket against the contract when an asset needs attention, with a priority and an SLA target.' },
      { key: 'howto.service.how.3', default: 'Dispatch the ticket to a technician; this creates a work order that schedules the visit.' },
      { key: 'howto.service.how.4', default: 'Complete the work order with a problem-cause-solution debrief, then bill it.' },
      { key: 'howto.service.how.5', default: 'Use recurring schedules to raise planned-maintenance visits automatically instead of by hand.' },
    ],
    tips: [
      { key: 'howto.service.tip.1', default: 'The SLA chip on each ticket counts down to its breach time, so triage the amber and red ones first.' },
      { key: 'howto.service.tip.2', default: 'Customers come from Contacts and on-site engineers from Subcontractors, so set those up first.' },
    ],
    whenKey: 'howto.service.when',
    whenDefault: 'Use it for any post-handover service or maintenance contract where you track tickets, visits and billing.',
  },
  {
    id: 'portal',
    route: '/portal',
    icon: 'Users',
    category: 'field',
    keywords: 'client partner external access invite magic link scoped permission audit document share',
    titleKey: 'howto.portal.title',
    titleDefault: 'Client & Partner Portal',
    summaryKey: 'howto.portal.summary',
    summaryDefault: 'A controlled external view: give clients and partners exactly what they need, nothing more.',
    whatKey: 'howto.portal.what',
    whatDefault:
      'The Client & Partner Portal lets you invite outsiders - a client, investor, consultant, subcontractor or supplier - and give them tightly scoped access to your work. Each access rule covers one resource and one permission, and nothing is visible until you grant it explicitly. Every view, download and signature is recorded in an audit log.',
    how: [
      { key: 'howto.portal.how.1', default: 'Invite an external party by email with a magic link and a role that sets their default scope.' },
      { key: 'howto.portal.how.2', default: 'Grant access one rule at a time - pick a project, document, ticket or invoice and a permission (view, comment, submit or sign).' },
      { key: 'howto.portal.how.3', default: 'Review the audit log to see exactly what each user viewed, downloaded or signed, with IP and timestamp.' },
      { key: 'howto.portal.how.4', default: 'Suspend a user or revoke a rule at any time to cut off access immediately.' },
    ],
    tips: [
      { key: 'howto.portal.tip.1', default: 'Grants are deny-by-default: an invited user sees nothing until you add an access rule for them.' },
      { key: 'howto.portal.tip.2', default: 'To cover several projects or documents, create one rule per resource rather than a single broad grant.' },
    ],
    whenKey: 'howto.portal.when',
    whenDefault: 'Use it whenever someone outside your team needs to see a slice of the project without an internal account.',
  },

  /* ── Resources & assets ───────────────────────────────────────────────── */
  {
    id: 'equipment',
    route: '/equipment',
    icon: 'Truck',
    category: 'resources',
    keywords: 'fleet plant machines utilisation maintenance certifications fuel telemetry owned rented leased',
    titleKey: 'howto.equipment.title',
    titleDefault: 'Equipment & Fleet',
    summaryKey: 'howto.equipment.summary',
    summaryDefault: 'Your plant and fleet register: utilisation, maintenance and certifications in one place.',
    whatKey: 'howto.equipment.what',
    whatDefault:
      'Equipment & Fleet is the register of every machine you own, rent or lease. Open an asset to see its utilisation, month-to-date fuel cost, open maintenance work orders and certification expiry, so you know what is working, what is idle and what is due for service.',
    how: [
      { key: 'howto.equipment.how.1', default: 'Register each machine with its ownership - owned, rented or leased - and its type.' },
      { key: 'howto.equipment.how.2', default: 'Open an asset to track utilisation, running and fuel cost, and its health over time.' },
      { key: 'howto.equipment.how.3', default: 'Raise maintenance work orders and log inspections so each machine stays serviced and certified.' },
      { key: 'howto.equipment.how.4', default: 'Keep certifications current; an asset that is not active or whose inspection has lapsed is blocked from new assignments.' },
    ],
    tips: [
      { key: 'howto.equipment.tip.1', default: 'A machine\'s running cost flows through to Finance, so keep its status and fuel readings up to date for accurate job costs.' },
    ],
    whenKey: 'howto.equipment.when',
    whenDefault: 'Use it to keep plant serviced and certified, and to see whether the fleet is earning its keep.',
  },
  {
    id: 'resources',
    route: '/resources',
    icon: 'Users',
    category: 'resources',
    keywords: 'crew people gangs assignments requests dispatch scheduling double booking conflict availability',
    titleKey: 'howto.resources.title',
    titleDefault: 'Resources & Crew',
    summaryKey: 'howto.resources.summary',
    summaryDefault: 'Plan who and what is on site: people, crews and equipment, with conflicts flagged.',
    whatKey: 'howto.resources.what',
    whatDefault:
      'Resources & Crew is where you put people, crews and equipment to work. A foreman raises a request, a dispatcher fulfils it by matching an available resource, and the resulting assignment reserves that resource for a date range. Double-booking conflicts are flagged automatically, so confirmed assignments are the source of truth for who is on site each day.',
    how: [
      { key: 'howto.resources.how.1', default: 'Register your resources - people, crews and equipment - with their skills and availability.' },
      { key: 'howto.resources.how.2', default: 'Raise a request for the resource a job needs over a given date range.' },
      { key: 'howto.resources.how.3', default: 'Fulfil the request by matching an available resource, which proposes an assignment.' },
      { key: 'howto.resources.how.4', default: 'Confirm the assignment on the board; the planner flags any double-booking conflict so you can resolve it.' },
    ],
    tips: [
      { key: 'howto.resources.tip.1', default: 'Confirmed assignments line up with the schedule and tasks, so keep them current to keep the plan honest.' },
    ],
    whenKey: 'howto.resources.when',
    whenDefault: 'Use it to plan and reserve crews and plant across jobs and to spot a clash before two sites fight over the same gang.',
  },
  {
    id: 'payroll',
    route: '/payroll',
    icon: 'Calculator',
    category: 'resources',
    keywords: 'labour wages pay batch hours field reports deductions finalize post ledger reconcile',
    titleKey: 'howto.payroll.title',
    titleDefault: 'Payroll',
    summaryKey: 'howto.payroll.summary',
    summaryDefault: 'Turn the hours logged on site into pay batches, then post labour cost to the project.',
    whatKey: 'howto.payroll.what',
    whatDefault:
      'Payroll rolls the labour hours captured in field reports into pay batches, one set of entries per worker. You walk a batch through its lifecycle - draft, submitted, finalized and posted - so labour cost lands in the project budget and the general ledger, with a reconciliation step to confirm the hours before money moves.',
    how: [
      { key: 'howto.payroll.how.1', default: 'Generate a draft batch for a period; it rolls the hours from field reports into pay entries per worker.' },
      { key: 'howto.payroll.how.2', default: 'Review each entry, add any deductions such as tax, social or pension, then submit the batch for approval.' },
      { key: 'howto.payroll.how.3', default: 'Finalize the batch to post its labour cost to the project budget.' },
      { key: 'howto.payroll.how.4', default: 'Post to the general ledger, and export the batch when you need the figures outside the platform.' },
    ],
    tips: [
      { key: 'howto.payroll.tip.1', default: 'Reconcile a batch before finalizing to confirm its hours still match the underlying field records.' },
    ],
    whenKey: 'howto.payroll.when',
    whenDefault: 'Use it each pay period to convert logged site hours into costed, posted pay without re-keying the numbers.',
  },
];
