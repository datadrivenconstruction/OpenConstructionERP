// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// portfolioGuide - "How it works" content for the portfolio Capacity
// Planning module. Consumed by <ModuleGuideButton content={portfolioGuide} />
// on CapacityPlanningPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const portfolioGuide: ModuleGuideContent = {
  titleKey: 'guide.portfolio.title',
  titleDefault: 'Capacity Planning',
  introKey: 'guide.portfolio.intro',
  introDefault:
    'Capacity Planning is a portfolio-wide heatmap of how your people, crews, equipment and subcontractors are booked across every project. Use it to see who is busy when, and to catch two projects competing for the same resource before it turns into a delay.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.portfolio.heatmap.title',
      titleDefault: 'The capacity heatmap',
      bodyKey: 'guide.portfolio.heatmap.body',
      bodyDefault:
        'Each row is one resource and each column is a time bucket, with the cell showing that resource total allocation for the period across all projects. The colour reads at a glance: green is comfortable, amber is near full, and red means over 100 percent.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.portfolio.buckets.title',
      titleDefault: 'Switch the time window',
      bodyKey: 'guide.portfolio.buckets.body',
      bodyDefault:
        'Use the Weeks and Months toggle in the header to change the bucket size. Weeks gives you a near-term, twelve-bucket view for day-to-day crew planning, while Months zooms out to a six-bucket horizon for longer-range portfolio loading.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.portfolio.conflicts.title',
      titleDefault: 'Spot conflicts and shared resources',
      bodyKey: 'guide.portfolio.conflicts.body',
      bodyDefault:
        'The summary chips count resources booked, shared (floating) resources used by more than one project, and over-allocated resources. A Shared badge marks a resource working across projects, a Conflict badge flags an overload, and a ringed cell means two or more projects are competing for the same period.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.portfolio.drill.title',
      titleDefault: 'Trace a booking to its source',
      bodyKey: 'guide.portfolio.drill.body',
      bodyDefault:
        'Hover any cell to see the per-project breakdown behind the number. Click a resource name to open it in Resources and Crew where its bookings are managed, so a red row never dead-ends and you can always reach the assignment that caused it.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.portfolio.leveling.title',
      titleDefault: 'Resolve overloads with leveling',
      bodyKey: 'guide.portfolio.leveling.body',
      bodyDefault:
        'When a cell turns red, click it or use Open Resource Leveling to move into the tool that fixes the clash. Leveling proposes deterministic actions, spreading a booking down to fit declared capacity or flagging one to shift, and you confirm each change before it is applied.',
    },
  ],
  ctaKey: 'guide.portfolio.cta',
  ctaDefault: 'Open Resource Leveling',
};
