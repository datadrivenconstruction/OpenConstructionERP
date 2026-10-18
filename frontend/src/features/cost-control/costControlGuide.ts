// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// costControlGuide - "How it works" content for the cost control page.
// Consumed by <ModuleGuideButton content={costControlGuide} /> on
// CostControlPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }); the keys are in every locale file.

import type { ModuleGuideContent } from '@/shared/ui';

export const costControlGuide: ModuleGuideContent = {
  titleKey: 'guide.cost_control.title',
  titleDefault: 'Cost control',
  introKey: 'guide.cost_control.intro',
  introDefault:
    'Cost control answers one question: what will the project cost in the end, and why. It reads the budget, the estimate, contracts, changes, measured work and invoices that already live in their own modules, so nothing is typed in twice.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.cost_control.methods.title',
      titleDefault: 'Four ways to read the forecast',
      bodyKey: 'guide.cost_control.methods.body',
      bodyDefault:
        'Best available source takes the most reliable figure of each line and is the usual choice. Maximum value takes the highest figure, for a cautious report. Projected from progress takes what was spent and how much is done, and extends it to the end. Manual is your own figure with a reason. The project has one method; any line can be read another way from its drawer, with a comment.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.cost_control.snapshots.title',
      titleDefault: 'A snapshot every month',
      bodyKey: 'guide.cost_control.snapshots.body',
      bodyDefault:
        'Start a snapshot and it opens as a draft. Every line that moved by more than the project threshold since the last frozen snapshot asks for a comment and a piece of evidence, a document or meeting minutes. When nothing is missing, freeze it. A frozen snapshot is a record: nobody can change or delete it.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.cost_control.compare.title',
      titleDefault: 'How the cost moved',
      bodyKey: 'guide.cost_control.compare.body',
      bodyDefault:
        'Step by step walks from one total to the next, the largest move first, with its cause and the reason written for it. Side by side shows several snapshots in columns. The phase comparison shows budget, estimate, best tender, award, changes, measured, invoiced and forecast next to each other on the account tree.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.cost_control.checks.title',
      titleDefault: 'Checks that keep the forecast honest',
      bodyKey: 'guide.cost_control.checks.body',
      bodyDefault:
        'A forecast below what is already owed needs a document or a comment. A large move on the draft needs its reason. A line on a different method than the project needs a comment. The checks are listed under the forecast method and each one opens its line.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.cost_control.export.title',
      titleDefault: 'Documents for the meeting',
      bodyKey: 'guide.cost_control.export.body',
      bodyDefault:
        'Export the cost report, the phase comparison, the invoice ledger and the forecast documentation as PDF or Excel, in your language.',
    },
  ],
};
