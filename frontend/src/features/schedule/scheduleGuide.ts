// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// scheduleGuide - "How it works" content for the 4D Schedule module.
// Consumed by <ModuleGuideButton content={scheduleGuide} /> on SchedulePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const scheduleGuide: ModuleGuideContent = {
  titleKey: 'guide.schedule.title',
  titleDefault: '4D Schedule',
  introKey: 'guide.schedule.intro',
  introDefault:
    'The schedule turns your estimate into a time plan: a Gantt of activities with dependencies, the critical path, and a link to the BIM model for a 4D sequence. Use it to lay out the build timeline and see what drives the finish date.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.schedule.create.title',
      titleDefault: 'Pick a project and a schedule',
      bodyKey: 'guide.schedule.create.body',
      bodyDefault:
        'Start by choosing a project from the list, then create a schedule inside it with a name and a start date. A project can hold several schedules, so you can keep separate plans for tender, baseline and as-built side by side.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.schedule.activities.title',
      titleDefault: 'Add activities by hand or from a BOQ',
      bodyKey: 'guide.schedule.activities.body',
      bodyDefault:
        'Each activity has a name, a WBS code, start and end dates, and a type of task, milestone or summary. Add them one at a time, or use Generate from BOQ to build the whole activity list straight from your priced positions, with durations estimated from quantities.',
      spotlightSelector: '[data-guide="schedule-generate"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.schedule.gantt.title',
      titleDefault: 'Read the Gantt timeline',
      bodyKey: 'guide.schedule.gantt.body',
      bodyDefault:
        'The Gantt draws every activity as a bar across the timeline, with milestones as diamonds and a marker for today. Zoom from day to year, drag a bar to reschedule it, and follow the arrows between bars to see finish-to-start and other dependency links.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.schedule.cpm.title',
      titleDefault: 'Run the critical path',
      bodyKey: 'guide.schedule.cpm.body',
      bodyDefault:
        'Calculate CPM to find the longest chain of dependent activities that sets the project finish date. Critical activities are flagged with a CP badge and highlighted in red, so you know which slips push the whole plan and which have float to spare.',
      spotlightSelector: '[data-guide="schedule-cpm"]',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.schedule.risk.title',
      titleDefault: 'Test the plan against risk',
      bodyKey: 'guide.schedule.risk.body',
      bodyDefault:
        'Risk analysis runs a PERT pass over the critical path and reports P50, P80 and P95 durations alongside a suggested buffer. Carry that buffer forward into the Risk Register or turn it into cost contingency in the 5D view.',
      spotlightSelector: '[data-guide="schedule-risk"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.schedule.progress.title',
      titleDefault: 'Track progress and the 4D link',
      bodyKey: 'guide.schedule.progress.body',
      bodyDefault:
        'Drag the slider on any activity to set its percent complete, and the bar fills to match. Link activities to BIM elements so the timeline drives a 4D sequence on the model, and jump back to the source positions in the BOQ at any time.',
    },
  ],
  ctaKey: 'guide.schedule.cta',
  ctaDefault: 'Open a project to begin',
};
