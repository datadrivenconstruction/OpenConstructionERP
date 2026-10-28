// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the AI Estimate Builder (/ai-estimator).
// Consumed by <ModuleGuideButton content={ai_estimatorGuide} /> in the page
// header. Every key carries its inline English default and is read via
// t(key, { defaultValue }); the keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const ai_estimatorGuide: ModuleGuideContent = {
  titleKey: 'guide.ai_estimator.title',
  titleDefault: 'AI Estimate Builder',
  introKey: 'guide.ai_estimator.intro',
  introDefault:
    'Turn any source into a priced estimate. The agent reads your input, groups the quantities and finds catalogue rates, and you confirm every step. Rates always come from your cost database and are never invented.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.ai_estimator.flow.title',
      titleDefault: 'Four stages, you confirm each one',
      bodyKey: 'guide.ai_estimator.flow.body',
      bodyDefault:
        'The estimate moves through four stages: understand the source, group quantities, match rates, then review and apply. The AI suggests at every stage and nothing is written until you confirm. Use the left rail to move between stages and the right monitor to watch the agent work.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.ai_estimator.source.title',
      titleDefault: 'Stage 1: pick a source and confirm it',
      bodyKey: 'guide.ai_estimator.source.body',
      bodyDefault:
        'Choose a tab and provide one source: a written scope, uploaded files (DWG, PDF, Excel, GAEB, IFC, photos), a converted BIM model, or existing project documents. Press Start, the agent detects the format and reads it into elements. Then check the detected source and set the cost catalogue, currency, region, construction stage and grouping keys before you continue.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.ai_estimator.groups.title',
      titleDefault: 'Stage 2: review the grouped quantities',
      bodyKey: 'guide.ai_estimator.groups.body',
      bodyDefault:
        'The agent buckets elements into estimable groups, each with a description, unit and quantity. Edit any group inline, merge groups that belong together, or skip ones you do not need. These groups become the lines of your estimate, so get them right before matching.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.ai_estimator.match.title',
      titleDefault: 'Stage 3: match catalogue rates',
      bodyKey: 'guide.ai_estimator.match.body',
      bodyDefault:
        'For each group the agent searches your cost database and proposes rates with a confidence score and resource breakdown. Accept the best candidate, skip a group, or re-query when nothing fits. Use bulk-accept to confirm every high-confidence match at once, then handle the rest by hand. Groups with no grounded rate stay flagged and are never given an invented price.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.ai_estimator.review.title',
      titleDefault: 'Stage 4: review totals and apply',
      bodyKey: 'guide.ai_estimator.review.body',
      bodyDefault:
        'Check the rolled-up totals and validation results for the whole estimate. When it looks right, tick the review and apply. The confirmed lines are written straight into a Bill of Quantities you can open and refine.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.ai_estimator.tips.title',
      titleDefault: 'Good to know',
      bodyKey: 'guide.ai_estimator.tips.body',
      bodyDefault:
        'Treat every grouped quantity and matched rate as a draft and review it. The module works without an AI key or vector database, it just leans more on your manual edits. Each run is saved, so you can leave and reopen it from the estimates list at any time.',
    },
  ],
  ctaKey: 'guide.ai_estimator.cta',
  ctaDefault: 'Start an estimate',
};
