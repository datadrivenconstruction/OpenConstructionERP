// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// aiGuide - "How it works" content for the AI Quick Estimate module.
// Consumed by <ModuleGuideButton content={aiGuide} /> on QuickEstimatePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const aiGuide: ModuleGuideContent = {
  titleKey: 'guide.ai.title',
  titleDefault: 'AI Quick Estimate',
  introKey: 'guide.ai.intro',
  introDefault:
    'Quick Estimate turns a rough brief into a structured, priced estimate in seconds. Describe the work or drop in a file, and the AI returns line items with quantities, units and rates that you can match against the cost database and save as a BOQ.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.ai.input.title',
      titleDefault: 'Choose your input',
      bodyKey: 'guide.ai.input.body',
      bodyDefault:
        'Pick a tab for the source you have: Text to describe the project in plain words, Photo or Scan for a building image or scanned sheet, PDF for BOQ and tender documents, Excel or CSV for spreadsheets, or Paste to drop in rows copied from any app. Each tab accepts one input at a time.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.ai.context.title',
      titleDefault: 'Set the context',
      bodyKey: 'guide.ai.context.body',
      bodyDefault:
        'Add a Location, Currency and classification Standard such as DIN 276, NRM or MasterFormat so the estimate uses the right rates and codes. For text input you can also set the building type and floor area. Leave any field on Auto and the AI infers it from your brief.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.ai.generate.title',
      titleDefault: 'Generate the estimate',
      bodyKey: 'guide.ai.generate.body',
      bodyDefault:
        'Run the estimate and the AI returns a table of positions, each with a description, unit, quantity, unit rate and computed total, grouped by trade or category. Classification codes are attached where detected and a grand total sums the lines. AI output is a starting point, so review every figure before you rely on it.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.ai.match.title',
      titleDefault: 'Match against the cost database',
      bodyKey: 'guide.ai.match.body',
      bodyDefault:
        'Pick a cost-database region and match the lines to find real CWICR rates near the AI guesses. The matched rate and its catalogue code appear next to each line, and rates in the estimate currency are folded into the total while foreign-currency matches are flagged and kept separate so currencies are never blended.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.ai.save.title',
      titleDefault: 'Save as a BOQ or export',
      bodyKey: 'guide.ai.save.body',
      bodyDefault:
        'When the numbers look right, save the estimate as a BOQ on any project to keep working on it in the full editor, optionally applying the matched cost-database rates instead of the AI estimate. You can also export the result or start over with a fresh brief.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.ai.history.title',
      titleDefault: 'Reopen recent estimates',
      bodyKey: 'guide.ai.history.body',
      bodyDefault:
        'Every run is saved to your history on the server, so it survives a reload or a device switch. The Recent estimates panel lists past runs with their item count and total; click one to reopen it and re-render the full results table.',
    },
  ],
  ctaKey: 'guide.ai.cta',
  ctaDefault: 'Describe your project',
};
