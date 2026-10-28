// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// inspectionsGuide - "How it works" content for the Inspections module.
// Consumed by <ModuleGuideButton content={inspectionsGuide} /> on InspectionsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const inspectionsGuide: ModuleGuideContent = {
  titleKey: 'guide.inspections.title',
  titleDefault: 'Inspections',
  introKey: 'guide.inspections.intro',
  introDefault:
    'Inspections is where site quality is checked and recorded. Schedule a check against a project, verify a checklist on site, record the result, and turn any failure into a tracked Punch List item or a formal NCR so nothing slips through.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.inspections.schedule.title',
      titleDefault: 'Schedule an inspection',
      bodyKey: 'guide.inspections.schedule.body',
      bodyDefault:
        'Click New Inspection and give it a title, a type such as structural, electrical, plumbing, fire safety, concrete, waterproofing or handover, a planned date, an inspector and a location. Every inspection belongs to the project you currently have open.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.inspections.checklist.title',
      titleDefault: 'Build the checklist',
      bodyKey: 'guide.inspections.checklist.body',
      bodyDefault:
        'Add the items to verify on site and flag the important ones as critical hold points. The checklist describes what to confirm before the work is accepted, and failed items later pre-fill any Punch List item or NCR you raise.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.inspections.lifecycle.title',
      titleDefault: 'Start and record the result',
      bodyKey: 'guide.inspections.lifecycle.body',
      bodyDefault:
        'An inspection moves from scheduled to in-progress to completed. Use Start when the inspector goes to site, then Record Result to log the outcome as pass, partial or fail. Completed and failed inspections are locked from further editing.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.inspections.register.title',
      titleDefault: 'Track the register',
      bodyKey: 'guide.inspections.register.body',
      bodyDefault:
        'The list shows every inspection with its type, inspector, date, result and status. Counts of total, scheduled, passed and failed sit at the top, and you can search by title, number or inspector and filter by status or type. Expand any row to see its checklist, notes and actions.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.inspections.followup.title',
      titleDefault: 'Raise punch items and NCRs',
      bodyKey: 'guide.inspections.followup.body',
      bodyDefault:
        'A fail or partial result unlocks two follow-ups: create a Punch List item for a minor snag to fix and re-check, or raise a formal NCR for a non-conformance needing root-cause analysis and signoff. Both are pre-filled from the inspection and deep-link straight to the new record.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.inspections.export.title',
      titleDefault: 'Export the log',
      bodyKey: 'guide.inspections.export.body',
      bodyDefault:
        'Use Export Excel to download the full inspection log for the project, ready for records and client reporting. The same control points tie back to the QMS overview so the inspect, defect and close-out loop stays traceable across the quality cluster.',
    },
  ],
  ctaKey: 'guide.inspections.cta',
  ctaDefault: 'Schedule your first inspection',
};
