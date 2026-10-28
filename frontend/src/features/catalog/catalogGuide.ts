// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// catalogGuide - "How it works" content for the Resource Catalog module.
// Consumed by <ModuleGuideButton content={catalogGuide} /> on CatalogPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const catalogGuide: ModuleGuideContent = {
  titleKey: 'guide.catalog.title',
  titleDefault: 'Resource Catalog',
  introKey: 'guide.catalog.intro',
  introDefault:
    'The catalog is your priced library of the building blocks behind every estimate: individual materials, labour rates, equipment and operators. Price them right here once, then feed assemblies, BOQ unit rates and cost matching across all your projects.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.catalog.concept.title',
      titleDefault: 'What lives in the catalog',
      bodyKey: 'guide.catalog.concept.body',
      bodyDefault:
        'Each entry is one resource with a code, a unit and a price (a low, average and high range so you can see the spread). Resources are grouped into four types: materials, equipment, labour and operators. The usage badge shows how many estimates already reference it.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.catalog.import.title',
      titleDefault: 'Start by importing a region',
      bodyKey: 'guide.catalog.import.body',
      bodyDefault:
        'An empty catalog has nothing to price with. Click Import Region and pick a country to download a pre-built CWICR catalog with thousands of priced resources in the local currency. Import as many regions as you work in; each appears as its own tab.',
      spotlightSelector: '[data-guide="catalog-import"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.catalog.browse.title',
      titleDefault: 'Browse by type and region',
      bodyKey: 'guide.catalog.browse.body',
      bodyDefault:
        'Use the type pills to narrow to materials, equipment, labour or operators, and the region tabs to switch between an imported country and your own My Catalog items. Each pill and tab shows a live count so you always know how much is in view.',
      spotlightSelector: '[data-guide="catalog-type-filters"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.catalog.search.title',
      titleDefault: 'Search and filter',
      bodyKey: 'guide.catalog.search.body',
      bodyDefault:
        'Type a name or code to find a resource fast, then refine further with the category and unit filters next to the search box. Click any row to expand its price cards, source and full properties.',
      spotlightSelector: '[data-guide="catalog-search"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.catalog.add.title',
      titleDefault: 'Add your own resource',
      bodyKey: 'guide.catalog.add.body',
      bodyDefault:
        'Have a rate the regional catalog does not cover? Click Add Resource and fill in the name, code, type, unit and price. Custom items land in My Catalog and behave exactly like imported ones. Use Adjust Prices to inflate or shift a whole group at once.',
      spotlightSelector: '[data-guide="catalog-add-resource"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.catalog.apply.title',
      titleDefault: 'Apply items to your estimate',
      bodyKey: 'guide.catalog.apply.body',
      bodyDefault:
        'Tick the checkbox on any rows you need. Copy puts the rate on your clipboard to paste straight into a BOQ unit rate, while Build Assembly combines the selected resources into a reusable composite rate that flows into the BOQ and cost matching.',
      spotlightSelector: '[data-guide="catalog-table"]',
    },
  ],
  ctaKey: 'guide.catalog.cta',
  ctaDefault: 'Import a region to begin',
};
