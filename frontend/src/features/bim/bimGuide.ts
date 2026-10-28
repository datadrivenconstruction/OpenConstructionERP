// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui';

/**
 * "How it works" guide for the BIM Hub.
 *
 * Walks a construction professional through the module's core concepts and
 * the real data-entry flow: load a model, navigate the 3D viewport, filter
 * elements, read quantities, and turn the model into a cost / schedule
 * dashboard. Every key carries its inline English default and is consumed
 * via `t(key, { defaultValue })`, so none of these keys live in any locale
 * file. Spotlight selectors point at live elements on BIMPage.
 */
export const bimGuide: ModuleGuideContent = {
  titleKey: 'guide.bim.title',
  titleDefault: 'BIM Hub',
  introKey: 'guide.bim.intro',
  introDefault:
    'The BIM Hub turns a 3D building model into measurable, priceable data. Upload a model, explore it in 3D, then read quantities straight off the geometry and connect them to your BOQ, cost and schedule.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.bim.concept.title',
      titleDefault: 'What a BIM model gives you',
      bodyKey: 'guide.bim.concept.body',
      bodyDefault:
        'A model is a 3D set of building elements (walls, slabs, doors, pipes), each carrying properties and quantities. Instead of measuring from drawings by hand, you take quantities off the model itself, so areas, volumes and counts stay consistent with the design.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.bim.load.title',
      titleDefault: 'Load a model',
      bodyKey: 'guide.bim.load.body',
      bodyDefault:
        'Click Add Model and drop an IFC or RVT file (DWG and DXF are 2D drawings and open in the DWG Takeoff module instead). Give it a name and discipline, then upload. Conversion runs in the background, and you can keep working while it processes.',
      spotlightSelector: '[data-testid="bim-add-model-top"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.bim.navigate.title',
      titleDefault: 'Navigate the 3D viewport',
      bodyKey: 'guide.bim.navigate.body',
      bodyDefault:
        'Drag to orbit, scroll to zoom, and right-drag to pan. Click any element to select it and see its properties and bounding-box dimensions (length, width, height and volume in metres). The models filmstrip at the bottom switches between loaded models.',
      spotlightSelector: '[data-testid="bim-active-model-name"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.bim.filter.title',
      titleDefault: 'Filter and isolate elements',
      bodyKey: 'guide.bim.filter.body',
      bodyDefault:
        'Open Filter to narrow the model by level, category or discipline, or use Property search to query any property and isolate just the matching elements. Isolating hides everything else so you can focus on, and measure, one trade or zone at a time.',
      spotlightSelector: '[data-testid="bim-tour-filter-button"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.bim.quantities.title',
      titleDefault: 'Read quantities from the model',
      bodyKey: 'guide.bim.quantities.body',
      bodyDefault:
        'Open Summary to roll up counts, areas and volumes by category and level for the elements currently visible. The numbers come straight from the model geometry, so filter first to scope the takeoff, then feed those quantities into a BOQ position.',
      spotlightSelector: '[data-guide="bim-summary-button"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.bim.dashboard.title',
      titleDefault: 'Turn the model into a dashboard',
      bodyKey: 'guide.bim.dashboard.body',
      bodyDefault:
        'Use Color by to paint the model live: validation status, BOQ and document coverage, 5D unit rate or 4D timeline and progress. It is a fast visual check of what is priced, linked, scheduled or still missing across the whole model.',
      spotlightSelector: '[data-testid="bim-color-mode-select"]',
    },
  ],
  ctaKey: 'guide.bim.cta',
  ctaDefault: 'Add your first model',
};
