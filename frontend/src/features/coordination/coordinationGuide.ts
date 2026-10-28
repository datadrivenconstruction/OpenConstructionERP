// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// coordinationGuide - "How it works" content for the Model Coordination hub.
// Consumed by <ModuleGuideButton content={coordinationGuide} /> on
// CoordinationHubPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const coordinationGuide: ModuleGuideContent = {
  titleKey: 'guide.coordination.title',
  titleDefault: 'Model Coordination',
  introKey: 'guide.coordination.intro',
  introDefault:
    'The Coordination Hub rolls up your federated BIM models, clash results, rule-pack checks and BCF activity for the active project into one health view. Use it to see where coordination stands and to jump straight to the next task.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.coordination.health.title',
      titleDefault: 'The four health signals',
      bodyKey: 'guide.coordination.health.body',
      bodyDefault:
        'The KPI cards at the top track open clashes, the open cost impact, rule-pack pass and fail counts, and federation coverage. Each card shows the run-to-run delta and is clickable, taking you into the list that explains the number.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.coordination.thresholds.title',
      titleDefault: 'Alert thresholds',
      bodyKey: 'guide.coordination.thresholds.body',
      bodyDefault:
        'Thresholds turn the health signals into warnings. When open clashes, high-severity clashes, cost impact or model age cross a limit you set, a banner flags it above the cards. Editors can open Thresholds in the header to tune the warn and error values per project.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.coordination.quick_actions.title',
      titleDefault: 'Quick actions',
      bodyKey: 'guide.coordination.quick_actions.body',
      bodyDefault:
        'The quick action tiles are shortcuts into the coordination workflows: review and triage clashes, manage federations, run rule-pack compliance checks, and open smart views to filter and isolate elements in 3D.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.coordination.trade_matrix.title',
      titleDefault: 'Clashes by discipline pair',
      bodyKey: 'guide.coordination.trade_matrix.body',
      bodyDefault:
        'The trade matrix maps where clashes concentrate across discipline pairs such as architecture against structure or MEP. Each cell shows the clash count and open cost impact. Click a cell to drill into the filtered clash list for that pair.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.coordination.timeline.title',
      titleDefault: 'Recent activity',
      bodyKey: 'guide.coordination.timeline.body',
      bodyDefault:
        'The timeline streams the latest clash runs, federation builds, rule-pack checks and BCF topics for the project. Switch the lookback between 7, 30 and 90 days, and follow any entry through its deep link to the source.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.coordination.export.title',
      titleDefault: 'Export a snapshot',
      bodyKey: 'guide.coordination.export.body',
      bodyDefault:
        'Use Export CSV to pull a single snapshot of the current coordination status, ready to attach to a coordination meeting. Refresh re-runs every panel so the rollup reflects the most recent runs.',
    },
  ],
  ctaKey: 'guide.coordination.cta',
  ctaDefault: 'Review open clashes',
};
