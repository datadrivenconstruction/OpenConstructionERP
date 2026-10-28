// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// sustainabilityGuide - "How it works" content for the Sustainability module.
// Consumed by <ModuleGuideButton content={sustainabilityGuide} /> on
// SustainabilityPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const sustainabilityGuide: ModuleGuideContent = {
  titleKey: 'guide.sustainability.title',
  titleDefault: 'Sustainability',
  introKey: 'guide.sustainability.intro',
  introDefault:
    'Sustainability reads the embodied carbon of a single Bill of Quantities, position by position. Use it to turn a priced BOQ into a CO2e footprint backed by EPD data (EN 15804, stages A1-A3), with a per-square-metre benchmark and a rating you can act on.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.sustainability.select.title',
      titleDefault: 'Pick a project, BOQ and area',
      bodyKey: 'guide.sustainability.select.body',
      bodyDefault:
        'Start by choosing a project and one of its BOQs, then enter the gross floor area in square metres. The area drives the per-m2 benchmark and the EU CPR figure, so set it before you calculate. Opening the page from the BOQ carbon-footprint action preselects everything and runs the analysis for you.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.sustainability.enrich.title',
      titleDefault: 'Enrich with EPD factors',
      bodyKey: 'guide.sustainability.enrich.body',
      bodyDefault:
        'Click Enrich CO2 to auto-detect the material behind each position and attach a Global Warming Potential factor from the EPD library (OKOBAUDAT, ICE v3.0, EU Level(s)). Enrichment stores the match on the position, so the next calculation reuses it. Positions it cannot match are reported as skipped.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.sustainability.calculate.title',
      titleDefault: 'Calculate the footprint',
      bodyKey: 'guide.sustainability.calculate.body',
      bodyDefault:
        'Calculate rolls every position into the total embodied carbon, shown in tonnes of CO2e with an A to D rating against the per-m2 benchmark. Alongside it you get the EU CPR 2024/3110 figure on a 50-year reference study period and a data-quality readout of how many positions actually carry CO2 data.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.sustainability.breakdown.title',
      titleDefault: 'Breakdown by material category',
      bodyKey: 'guide.sustainability.breakdown.body',
      bodyDefault:
        'The breakdown groups the footprint by material category and charts it as a donut with a matching table. Each row shows the category, how many positions feed it, its share of the total and the carbon in tonnes, so you can see at a glance where the impact concentrates.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.sustainability.positions.title',
      titleDefault: 'Tune position-level data',
      bodyKey: 'guide.sustainability.positions.body',
      bodyDefault:
        'The position table lists every line sorted by impact, with its quantity, unit and assigned EPD material. Where auto-detection got it wrong, pick a better EPD material from the dropdown and the GWP per unit and total update straight away. Negative totals, such as stored carbon, are shown in green.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.sustainability.export.title',
      titleDefault: 'Export the report',
      bodyKey: 'guide.sustainability.export.body',
      bodyDefault:
        'When the numbers look right, Export CO2 Report writes a CSV with the summary, the category breakdown and the full position detail, ready for Excel or a wider report. For inventories, scopes, targets and standards reporting across the whole project, move on to the Carbon module.',
    },
  ],
  ctaKey: 'guide.sustainability.cta',
  ctaDefault: 'Select a BOQ to begin',
};
