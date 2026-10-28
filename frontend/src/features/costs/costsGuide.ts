// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// costsGuide - "How it works" content for the Cost Database module.
// Consumed by <ModuleGuideButton content={costsGuide} /> in CostsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const costsGuide: ModuleGuideContent = {
  titleKey: 'guide.costs.title',
  titleDefault: 'Cost Database',
  introKey: 'guide.costs.intro',
  introDefault:
    'The cost database is your single source of truth for unit rates. It holds the price of every material, labour and equipment item, so the same numbers feed every estimate. Pull rates from regional reference catalogues or keep your own.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.costs.regions.title',
      titleDefault: 'Regional catalogues',
      bodyKey: 'guide.costs.regions.body',
      bodyDefault:
        'Each tab at the top is a regional reference catalogue such as CWICR, with its own currency and item count. Pick a region to scope the list to that catalogue, or choose All to search across every loaded database. Use Import to add a new region.',
      spotlightSelector: '[data-guide="costs-region-tabs"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.costs.search.title',
      titleDefault: 'Finding the right rate',
      bodyKey: 'guide.costs.search.body',
      bodyDefault:
        'Type a description or code to filter the list, then narrow further by unit, source or the category tree on the left. Turn on AI search to describe what you need in plain language and let it find similar items even when the wording differs.',
      spotlightSelector: '[data-guide="costs-search"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.costs.rates.title',
      titleDefault: 'Rates and currencies',
      bodyKey: 'guide.costs.rates.body',
      bodyDefault:
        'Every item has a unit, a unit rate and the currency that rate is priced in. Catalogues mix currencies, so the code is always shown next to the figure. When you add an item to a BOQ it keeps its currency, and the cost rollup converts it instead of treating it as the base.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.costs.add.title',
      titleDefault: 'Adding your own item',
      bodyKey: 'guide.costs.add.body',
      bodyDefault:
        'Click Add Item to create a custom rate. Enter a description, pick a unit, type the rate and choose its currency. Add a Category (such as Structural Steel) to group it for browsing. For steel sections priced by member type, switch the rate to per tonne or per kg and enter the mass per metre (e.g. 44.7 for a 360UB); the per-metre price is worked out for you when you use it on a length. The code is optional and is generated if you leave it blank. Reference catalogue rows stay read-only, but your own items can be edited or deleted any time.',
      spotlightSelector: '[data-guide="costs-add-item"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.costs.catalogs.title',
      titleDefault: 'Your own catalogues',
      bodyKey: 'guide.costs.catalogs.body',
      bodyDefault:
        'Group your custom rates into catalogues, your own price books, under My catalogs. New items can land in a chosen catalogue and inherit its currency. Click a catalogue to filter the list to just its items, and export any catalogue to share it.',
      spotlightSelector: '[data-guide="costs-catalogs"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.costs.import.title',
      titleDefault: 'Importing a database',
      bodyKey: 'guide.costs.import.body',
      bodyDefault:
        'Use Import to load a regional reference catalogue or bring in your own rates from an Excel or CSV file. Imported items pass through validation before they are stored, so bad units, missing prices and duplicates are flagged up front.',
      spotlightSelector: '[data-guide="costs-import"]',
    },
  ],
  ctaKey: 'guide.costs.cta',
  ctaDefault: 'Add your first cost item',
};
