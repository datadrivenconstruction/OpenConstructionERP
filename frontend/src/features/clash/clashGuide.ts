// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// clashGuide - "How it works" content for the Clash Detection module.
// Consumed by <ModuleGuideButton content={clashGuide} /> on ClashDetectionPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const clashGuide: ModuleGuideContent = {
  titleKey: 'guide.clash.title',
  titleDefault: 'Clash Detection',
  introKey: 'guide.clash.intro',
  introDefault:
    'Clash Detection finds geometric interferences and clearance violations across your federated BIM models. Run a check, work through the results in a coordination matrix and review table, then export the issues as BCF for the design team.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.clash.scope.title',
      titleDefault: 'Pick the models to check',
      bodyKey: 'guide.clash.scope.body',
      bodyDefault:
        'Coordination runs against the BIM models on the active project. Select two or more parsed models from the card picker; those cards are the scope of the check. Narrow each side further with selection sets that filter by discipline, element type, category or IFC entity.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.clash.run.title',
      titleDefault: 'Configure and run',
      bodyKey: 'guide.clash.run.body',
      bodyDefault:
        'Choose a clash type: Hard for true interpenetration, Clearance for proximity with no overlap, or Both. Set the tolerance and clearance distances, give the run a name, then click Run clash detection. Save a configuration as a reusable profile to repeat the same check later.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.clash.matrix.title',
      titleDefault: 'Read the clash matrix',
      bodyKey: 'guide.clash.matrix.body',
      bodyDefault:
        'Results roll up into a discipline by discipline matrix, with level and model views as well. Each cell is colour-heated by how many clashes it holds, so the hotspots stand out. Click any cell to filter the review table down to that pair.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.clash.review.title',
      titleDefault: 'Work through the results',
      bodyKey: 'guide.clash.review.body',
      bodyDefault:
        'The review workspace pairs KPI tiles with a sortable, paginated table. Use the filter bar to narrow by status, clash type, minimum penetration or free-text search, then move each clash through its status from new to resolved as you triage it.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.clash.collaborate.title',
      titleDefault: 'Assign, comment and isolate',
      bodyKey: 'guide.clash.collaborate.body',
      bodyDefault:
        'Open a clash to assign an owner, set a due date and add threaded comments with @mentions. Isolate in 3D deep-links straight into the BIM viewer with both elements isolated, so the right person can see exactly where the conflict sits.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.clash.export.title',
      titleDefault: 'Export to BCF',
      bodyKey: 'guide.clash.export.body',
      bodyDefault:
        'When the issues are triaged, export them as BCF, one row at a time or in bulk. BCF is the open format coordination tools read, so the clashes land in the design team workflow with their viewpoints and notes intact.',
    },
  ],
  ctaKey: 'guide.clash.cta',
  ctaDefault: 'Run a clash detection',
};
