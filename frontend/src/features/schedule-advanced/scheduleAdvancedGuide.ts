// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// scheduleAdvancedGuide - "How it works" content for the Last Planner / CPM
// module. Consumed by <ModuleGuideButton content={scheduleAdvancedGuide} />
// in the ScheduleAdvancedPage header.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const scheduleAdvancedGuide: ModuleGuideContent = {
  titleKey: 'guide.schedule_advanced.title',
  titleDefault: 'Last Planner / CPM',
  introKey: 'guide.schedule_advanced.intro',
  introDefault:
    'This is the Last Planner stack that turns a master schedule into reliable weekly work. Use it to pull-plan phases, roll a look-ahead that clears constraints, capture the weekly commitments trade foremen actually make, and track variance against a baseline.',
  sections: [
    {
      icon: 'Calendar',
      titleKey: 'guide.schedule_advanced.master.title',
      titleDefault: 'Start with a master schedule',
      bodyKey: 'guide.schedule_advanced.master.body',
      bodyDefault:
        'The master schedule is the top-level plan that every phase plan, look-ahead and weekly work plan rolls up to. Create one per project with its planned start and finish, then select it to make it the working plan for all the other tabs.',
    },
    {
      icon: 'LayoutGrid',
      titleKey: 'guide.schedule_advanced.phases.title',
      titleDefault: 'Break the work into phases',
      bodyKey: 'guide.schedule_advanced.phases.body',
      bodyDefault:
        'Phase plans split the project into high-level construction phases such as foundation, structure, MEP and finishes. Build them by hand or apply a ready-made template, then pull, start and complete each phase as planning matures. Cards, table and timeline views show progress, delays and variance against the baseline.',
    },
    {
      icon: 'Clock',
      titleKey: 'guide.schedule_advanced.look_ahead.title',
      titleDefault: 'Roll a look-ahead',
      bodyKey: 'guide.schedule_advanced.look_ahead.body',
      bodyDefault:
        'A look-ahead plan is the rolling window, typically six weeks, where the team makes near-term work ready. Create a look-ahead and publish it once the upcoming activities have been screened for what could stop them.',
    },
    {
      icon: 'AlertCircle',
      titleKey: 'guide.schedule_advanced.constraints.title',
      titleDefault: 'Clear constraints before work starts',
      bodyKey: 'guide.schedule_advanced.constraints.body',
      bodyDefault:
        'Constraints are anything that blocks a task from being ready: missing design, materials, equipment, labour or prerequisite work. Log them against a look-ahead, assign and track them to cleared, and escalate the ones that cannot be resolved in time so only sound work is promised.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.schedule_advanced.weekly.title',
      titleDefault: 'Capture weekly commitments',
      bodyKey: 'guide.schedule_advanced.weekly.body',
      bodyDefault:
        'The weekly work plan holds the promises trade foremen commit to for the coming week, each linked to a real project task. Commit, complete or mark commitments at risk, and when one is missed record the reason for non-completion so the percent plan complete and root-cause analysis stay honest.',
    },
    {
      icon: 'GitBranch',
      titleKey: 'guide.schedule_advanced.baselines.title',
      titleDefault: 'Baseline and track variance',
      bodyKey: 'guide.schedule_advanced.baselines.body',
      bodyDefault:
        'Capture a baseline to freeze the current plan, then compare live phases against it to see what slipped or moved ahead. The schedule variance in days surfaces as inline badges on the phase views so drift is visible at a glance.',
    },
  ],
  ctaKey: 'guide.schedule_advanced.cta',
  ctaDefault: 'Create your master schedule',
};
