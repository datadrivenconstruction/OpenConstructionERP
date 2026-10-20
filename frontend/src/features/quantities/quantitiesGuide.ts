// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// quantitiesGuide - "How it works" content for the Quantity Takeoff module.
// Consumed by <ModuleGuideButton content={quantitiesGuide} /> on QuantitiesPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const quantitiesGuide: ModuleGuideContent = {
  titleKey: 'guide.quantities.title',
  titleDefault: 'Quantity Takeoff',
  introKey: 'guide.quantities.intro',
  introDefault:
    'Quantity Takeoff is the hub for collecting the measured quantities behind an estimate. Pick the route that fits your source, from a written description, PDF drawings, or CAD and BIM models, and every route feeds the same BOQ.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.quantities.methods.title',
      titleDefault: 'Three ways to measure',
      bodyKey: 'guide.quantities.methods.body',
      bodyDefault:
        'The method cards are your starting points. Quick Estimate (AI) turns a written scope into priced lines, PDF Takeoff measures areas and lengths on drawings, and CAD/BIM extracts quantities straight from a model. Choose the one that matches the source material you have.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.quantities.register.title',
      titleDefault: 'The measured quantities register',
      bodyKey: 'guide.quantities.register.body',
      bodyDefault:
        'Once a project is active, the Measured quantities panel rolls up everything already captured, both takeoff measurements and BOQ line quantities, grouped by unit, trade, type or source with running totals. Filter it, focus a single drawing, or export the rollup to CSV. It is read-only, so the numbers move as you measure more.',
      spotlightSelector: '[data-guide="quantities-summary"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.quantities.ai.title',
      titleDefault: 'Quick Estimate from text',
      bodyKey: 'guide.quantities.ai.body',
      bodyDefault:
        'When you only have a written description, open Quick Estimate (AI). It reads your scope text and proposes measured, priced lines with confidence scores, so you can review and confirm rather than type every position by hand.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.quantities.pdf.title',
      titleDefault: 'Takeoff from PDF drawings',
      bodyKey: 'guide.quantities.pdf.body',
      bodyDefault:
        'PDF Takeoff opens a drawing on a measurement canvas where you click to measure areas, lengths and counts at the right scale. Uploaded drawings appear under Recent Documents so you can pick up where you left off.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.quantities.converters.title',
      titleDefault: 'CAD and BIM converter modules',
      bodyKey: 'guide.quantities.converters.body',
      bodyDefault:
        'To read DWG, RVT or IFC files you install the matching converter module, a one-time download per format. The module cards show what is installed, flag when a newer build is available to update, and let you uninstall any you no longer need.',
      spotlightSelector: '[data-guide="quantities-converters"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.quantities.flow.title',
      titleDefault: 'Upload, measure, into the BOQ',
      bodyKey: 'guide.quantities.flow.body',
      bodyDefault:
        'Every route follows the same three steps: upload or describe the source, measure or extract the quantities, then send them into the estimate. The measured quantities flow into your Bill of Quantities where rates and totals are applied.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.quantities.manual.title',
      titleDefault: 'Or enter quantities by hand',
      bodyKey: 'guide.quantities.manual.body',
      bodyDefault:
        'Sometimes a count is faster typed than measured. Quick Manual Entry opens the BOQ Editor so you can add positions and quantities directly, alongside anything captured from AI, PDF or CAD.',
    },
  ],
  ctaKey: 'guide.quantities.cta',
  ctaDefault: 'Pick a takeoff method',
};
