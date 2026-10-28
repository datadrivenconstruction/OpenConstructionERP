// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the CAD-BIM Match to Cost module
// (/match-elements). Concept-first cards for a construction professional:
// what matching a model against a cost catalogue means, what the match
// score is, how to fill in each step, and how confirmed matches become a
// real priced bill of quantities.
//
// i18n: every string carries its inline English default and is consumed
// via t(key, { defaultValue }). The keys are not in en.ts, the inline
// defaults are the English source; their translations live in the other
// locale files, so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const matchGuide: ModuleGuideContent = {
  titleKey: 'guide.match.title',
  titleDefault: 'CAD-BIM Match to Cost',
  introKey: 'guide.match.intro',
  introDefault:
    'This module turns a BIM or CAD model into a priced bill of quantities. It groups the model elements, matches each group to a cost catalogue, and lets you confirm the rates before they become real BOQ positions. Walk the steps in order using Next.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.match.model.title',
      titleDefault: 'Pick the model to price',
      bodyKey: 'guide.match.model.body',
      bodyDefault:
        'Start by choosing the BIM or CAD model whose elements you want to estimate. Every wall, slab, door and beam in it becomes part of the cost. If the project has no model yet, upload and convert one in BIM models first.',
      spotlightSelector: '[data-guide="match-rail"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.match.catalogue.title',
      titleDefault: 'Choose the cost catalogue',
      bodyKey: 'guide.match.catalogue.body',
      bodyDefault:
        'A cost catalogue is the regional rate book the model is priced against. Pick the catalogue for your country and the currency for the totals. The project region pre-selects a sensible default, and a multilingual catalogue still works if your region has none.',
      spotlightSelector: '[data-guide="match-rail"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.match.scope.title',
      titleDefault: 'Set the scope and confidence',
      bodyKey: 'guide.match.scope.body',
      bodyDefault:
        'Optionally pin the search to one construction stage, and choose net quantities (openings deducted) or gross. The auto-confirm slider sets how sure a match must be to be accepted for you. A higher score means fewer auto-confirms and more left for your review.',
      spotlightSelector: '[data-guide="match-rail"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.match.grouping.title',
      titleDefault: 'How elements roll up into groups',
      bodyKey: 'guide.match.grouping.body',
      bodyDefault:
        'Pricing one element at a time is too granular, so similar elements are gathered into estimable groups, for example all 24 cm concrete walls on one level. You estimate per group, and the quantities of its members are summed for you.',
      spotlightSelector: '[data-guide="match-rail"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.match.run.title',
      titleDefault: 'Run the match and read the score',
      bodyKey: 'guide.match.run.body',
      bodyDefault:
        'Each group is searched against the catalogue using semantic (meaning-based) search plus keyword and rule checks, and ranked by a match score from 0 to 1. A higher score means the catalogue item is a closer description of the group. With no vector database it still matches on keywords, just less precisely.',
      spotlightSelector: '[data-guide="match-rail"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.match.review.title',
      titleDefault: 'Confirm matches and write the BOQ',
      bodyKey: 'guide.match.review.body',
      bodyDefault:
        'Open any group to see its ranked cost candidates with scores, then confirm the right one or accept all high-confidence matches at once. Nothing is priced until you confirm it. When you are done, preview the rollup and write it to the project as a real bill of quantities.',
      spotlightSelector: '[data-guide="match-next"]',
    },
  ],
  ctaKey: 'guide.match.cta',
  ctaDefault: 'Pick a model and start',
};
