// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// punchlistGuide - "How it works" content for the Punch List module.
// Consumed by <ModuleGuideButton content={punchlistGuide} /> on PunchListPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const punchlistGuide: ModuleGuideContent = {
  titleKey: 'guide.punchlist.title',
  titleDefault: 'Punch List',
  introKey: 'guide.punchlist.intro',
  introDefault:
    'The Punch List is the running register of snags and minor defects that have to be fixed before handover. Use it near the end of a job to capture outstanding work, assign an owner and a deadline, and drive every item through to a verified close-out.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.punchlist.capture.title',
      titleDefault: 'Capture a snag',
      bodyKey: 'guide.punchlist.capture.body',
      bodyDefault:
        'Click New Item to log a snag with a title, description, priority from low to critical, a category such as structural or finishing, and a location. Assign it to a team member and set a due date so every item has an owner and a deadline. You can also pin it to a drawing sheet so the issue can be reopened on the plan.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.punchlist.lifecycle.title',
      titleDefault: 'The status lifecycle',
      bodyKey: 'guide.punchlist.lifecycle.body',
      bodyDefault:
        'Each item moves Open to In Progress to Resolved to Verified to Closed. The owner works it up to Resolved, then a checker verifies the fix and closes it. If a fix does not hold up on a re-check, reopen the item straight back to Open from Resolved, Verified or Closed. The backend enforces the flow, so only legal moves are offered.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.punchlist.views.title',
      titleDefault: 'List and Kanban views',
      bodyKey: 'guide.punchlist.views.body',
      bodyDefault:
        'Switch between a Kanban board to manage flow across the status columns and a list view for bulk triage and close-out. Search by title, description or location, and use the filters to narrow by priority, status, category or assignee. Overdue items are flagged in red so nothing slips.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.punchlist.kpis.title',
      titleDefault: 'Read the KPI strip',
      bodyKey: 'guide.punchlist.kpis.body',
      bodyDefault:
        'The KPI band at the top tracks the live workload: open items, overdue, critical and high priority, resolved and awaiting verify, closed this week, and the average days to close. Click a tile to filter the list below to that slice, so you can jump straight to the work that needs attention.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.punchlist.sources.title',
      titleDefault: 'Items from other modules',
      bodyKey: 'guide.punchlist.sources.body',
      bodyDefault:
        'Punch items can be raised automatically from a failed inspection, an NCR or a model clash. These carry a source badge you can click to open the record they came from, which keeps the inspect, defect and close-out loop traceable right through to handover.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.punchlist.close_out.title',
      titleDefault: 'Bulk close and map',
      bodyKey: 'guide.punchlist.close_out.body',
      bodyDefault:
        'When a zone is signed off, multi-select items in the list view and bulk close the batch in one step. Each item holds its own photos for evidence, and View on map plots snags by location so you can see what is outstanding across the site.',
    },
  ],
  ctaKey: 'guide.punchlist.cta',
  ctaDefault: 'Add your first punch item',
};
