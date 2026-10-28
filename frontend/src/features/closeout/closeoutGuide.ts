// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// closeoutGuide - "How it works" content for the Handover & Closeout module.
// Consumed by <ModuleGuideButton content={closeoutGuide} /> on CloseoutPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const closeoutGuide: ModuleGuideContent = {
  titleKey: 'guide.closeout.title',
  titleDefault: 'Handover & Closeout',
  introKey: 'guide.closeout.intro',
  introDefault:
    'Handover & Closeout assembles every document the client needs at the end of a project into one verified package. Use it as a live checklist to track what is collected, close the gaps, then build a single structured deliverable to hand over.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.closeout.checklist.title',
      titleDefault: 'Start from a checklist',
      bodyKey: 'guide.closeout.checklist.body',
      bodyDefault:
        'Pick the project type, commercial, residential, infrastructure, fitout or custom, to seed the right handover checklist. Items are grouped by category and split into required and optional, so you always know what the client expects. You can add or remove items afterwards.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.closeout.evidence.title',
      titleDefault: 'Bind and verify evidence',
      bodyKey: 'guide.closeout.evidence.body',
      bodyDefault:
        'Each item is a slot you fill by binding evidence: an as-built drawing, an O&M manual, a warranty or an external link. Bound items can then be marked Verified once a reviewer confirms them, moving each slot from Empty to Bound to Verified.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.closeout.suggest.title',
      titleDefault: 'Auto-suggest matching documents',
      bodyKey: 'guide.closeout.suggest.body',
      bodyDefault:
        'Click Auto-suggest evidence to let the system scan your project documents and propose a match for each open slot, with a confidence score and a reason. Suggestions are never applied automatically, you confirm each one before it binds.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.closeout.readiness.title',
      titleDefault: 'Cross-module readiness gates',
      bodyKey: 'guide.closeout.readiness.body',
      bodyDefault:
        'Two items are generated from other modules: punch closure from the Punch List and the final inspection certificate from Inspections. Their readiness chips deep-link to the source module, and an outstanding required gate is flagged before you build.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.closeout.build.title',
      titleDefault: 'Build the package',
      bodyKey: 'guide.closeout.build.body',
      bodyDefault:
        'The completeness ring shows how many required items are delivered and turns green when the package is ready. Build package collects everything into one structured ZIP with a PDF cover sheet and a machine-readable manifest, ready to download and hand to the client.',
    },
  ],
  ctaKey: 'guide.closeout.cta',
  ctaDefault: 'Start a closeout package',
};
