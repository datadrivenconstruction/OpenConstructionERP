// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// levelingGuide - "How it works" content for the Resource Leveling module.
// Consumed by <ModuleGuideButton content={levelingGuide} /> on
// ResourceLevelingPage, mirroring portfolioGuide on CapacityPlanningPage.
//
// The text describes what this page ACTUALLY does: it compares booked
// allocation against each resource's declared capacity and proposes one
// action per over-booked period. It deliberately does NOT promise levelling
// within float or a recomputed finish date - that engine exists elsewhere and
// is not what this surface runs, and a guide that oversells the page is worse
// than no guide at all.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const levelingGuide: ModuleGuideContent = {
  titleKey: 'guide.leveling.title',
  titleDefault: 'Resource Leveling',
  introKey: 'guide.leveling.intro',
  introDefault:
    'Chasing a peak with hired plant and agency labour is the most expensive way to build. This page finds the periods where a crew or machine is booked past what it can actually deliver, across every project at once, so you spend your own resources before you pay a premium for someone else.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.leveling.grid.title',
      titleDefault: 'What the grid shows',
      bodyKey: 'guide.leveling.grid.body',
      bodyDefault:
        'Each row is one resource and each column is a period. The number in a cell is everything booked on that resource in that period, added up across every project, not just the one you are looking at. Rows are ordered worst first, so the resources that need a decision are already at the top.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.leveling.over.title',
      titleDefault: 'What counts as over capacity',
      bodyKey: 'guide.leveling.over.body',
      bodyDefault:
        'A period turns red only when the booked total passes the capacity declared on that resource: 100 percent for one person or one machine, more for a crew that can split across sites. A resource with no capacity set is drawn in grey and is never called overloaded, because there is no honest ceiling to compare it against. Set a capacity on those resources and they join the check.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.leveling.drawer.title',
      titleDefault: 'Open a red period to see the options',
      bodyKey: 'guide.leveling.drawer.body',
      bodyDefault:
        'Click a red cell, or any resource name, to open its panel. It lists every booking behind each period, project by project, so you can see exactly which two jobs are competing, and it proposes one action for each over-booked period.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.leveling.actions.title',
      titleDefault: 'Shift and Spread, and which one you can apply',
      bodyKey: 'guide.leveling.actions.body',
      bodyDefault:
        'Spread reduces the largest booking in that period to the share that fits, and you can apply it here: it changes that one booking after you confirm it. Shift means the smallest booking is on its own enough to clear the overload if it moves to another period. Choosing that period is a scheduling decision with knock-on effects, so this page will not invent a date for you; it links you to the booking in the 4D Schedule instead.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.leveling.limits.title',
      titleDefault: 'What this page will not do',
      bodyKey: 'guide.leveling.limits.body',
      bodyDefault:
        'Nothing moves on its own. No booking is rescheduled, no start date is changed and no finish date is recalculated. Every suggestion is a proposal you read and confirm, and anything you apply here can be changed back in Resources & Crew.',
    },
  ],
  ctaKey: 'guide.leveling.cta',
  ctaDefault: 'Open Resources & Crew',
};
