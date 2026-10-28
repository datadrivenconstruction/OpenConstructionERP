// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the Cost Benchmarks module (route
// /benchmarks, rendered by modules/cost-benchmark/BenchmarkModule.tsx).
//
// Concept-first, then a step-by-step of the four inputs the user fills.
// Every key carries its inline English defaultValue; the keys are not in
// en.ts, the inline defaults are the English source; their translations live
// in the other locale files, so a changed default needs its translations
// redone too. Key prefix: guide.benchmarks.*

import type { ModuleGuideContent } from '@/shared/ui';

export const benchmarksGuide: ModuleGuideContent = {
  titleKey: 'guide.benchmarks.title',
  titleDefault: 'Cost Benchmarks',
  introKey: 'guide.benchmarks.intro',
  introDefault:
    'Benchmarks tell you whether your estimate is normal for the kind of building you are pricing. You enter a total cost and a floor area, and the page shows where your cost per square metre sits against typical industry figures.',
  sections: [
    {
      icon: 'Lightbulb',
      titleKey: 'guide.benchmarks.concept.title',
      titleDefault: 'What a cost benchmark is',
      bodyKey: 'guide.benchmarks.concept.body',
      bodyDefault:
        'A benchmark is the typical cost to build one square metre of a given building type, drawn from public construction cost datasets. It covers DIN 276 KG300 construction works plus KG400 technical systems. It is a planning reference, not a live price feed.',
      spotlightSelector: '[data-guide="benchmarks-source"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.benchmarks.inputs.title',
      titleDefault: 'Enter your four values',
      bodyKey: 'guide.benchmarks.inputs.body',
      bodyDefault:
        'Pick the building type and region, then type your gross floor area in square metres and your total cost in the region currency. The page divides cost by area to get your cost per square metre. If your tenant has projects, the picker can pre-fill these from a real project, and you can still edit any value.',
      spotlightSelector: '[data-guide="benchmarks-inputs"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.benchmarks.persquaremetre.title',
      titleDefault: 'Cost per square metre',
      bodyKey: 'guide.benchmarks.persquaremetre.body',
      bodyDefault:
        'Cost per square metre is the one number that lets you compare projects of different sizes. The headline cards show your figure next to the industry median, and the difference from the median in both money and percent.',
      spotlightSelector: '[data-guide="benchmarks-results"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.benchmarks.reading.title',
      titleDefault: 'Reading the percentile and the bar',
      bodyKey: 'guide.benchmarks.reading.body',
      bodyDefault:
        'The coloured bar runs from the cheapest to the most expensive observed projects, split into quartiles around the median. Your marker shows where you land. A low percentile such as P25 means cost-effective, P50 is on the median, and a high percentile means a premium build worth a second look.',
      spotlightSelector: '[data-guide="benchmarks-bar"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.benchmarks.split.title',
      titleDefault: 'Cost group split and confidence',
      bodyKey: 'guide.benchmarks.split.body',
      bodyDefault:
        'The KG300 versus KG400 strip shows how your cost per square metre typically divides between construction works and technical systems for this building type. Always check the data confidence and sample size before you trust a tight comparison, since thin or dated samples are only indicative.',
      spotlightSelector: '[data-guide="benchmarks-split"]',
    },
  ],
  ctaKey: 'guide.benchmarks.cta',
  ctaDefault: 'Got it',
};
