// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// capitalPlanGuide - "How it works" content for the Capital plan page.
// Consumed by <ModuleGuideButton content={capitalPlanGuide} />.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }); the English source is also in en.ts.

import type { ModuleGuideContent } from '@/shared/ui';

export const capitalPlanGuide: ModuleGuideContent = {
  titleKey: 'guide.capital_plan.title',
  titleDefault: 'Capital plan',
  introKey: 'guide.capital_plan.intro',
  introDefault:
    'The capital plan answers one question: which projects fit the money, and what happens if we delay one. Set the yearly budget, list the projects with their cost and start year, and read the gap row to see where demand runs over the budget.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.capital_plan.grid.title',
      titleDefault: 'Read the grid',
      bodyKey: 'guide.capital_plan.grid.body',
      bodyDefault:
        'Each row is a project and each column a year. A cell is the part of the cost spent that year. The three rows at the bottom compare the budget with the demand, and a red gap means that year is over budget.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.capital_plan.scenarios.title',
      titleDefault: 'Try a what-if',
      bodyKey: 'guide.capital_plan.scenarios.body',
      bodyDefault:
        'Add a scenario to copy the current one, then move a start year with the arrows. The original is never changed, so you can compare the two side by side and keep the one that works.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.capital_plan.suggest.title',
      titleDefault: 'Suggest funding',
      bodyKey: 'guide.capital_plan.suggest.body',
      bodyDefault:
        'The suggestion funds projects by priority, then score, then cost, until a year runs out of money. It only proposes: you see what would change and why, and nothing is applied until you confirm.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.capital_plan.checks.title',
      titleDefault: 'Checks',
      bodyKey: 'guide.capital_plan.checks.body',
      bodyDefault:
        'Phasing that does not add up, a project with no cost, a year with no budget or a year over budget is listed under the grid, so a figure that cannot be trusted is flagged before it reaches a decision.',
    },
  ],
};
