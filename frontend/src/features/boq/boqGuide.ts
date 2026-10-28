// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui';

/**
 * "How it works" guide content for the Bill of Quantities module.
 *
 * Consumed by <ModuleGuideButton content={boqGuide} /> in BOQEditorPage.
 * Every string is inline-defaulted and read via t(key, { defaultValue }),
 * so the keys are not in en.ts, the inline defaults are the English source;
 * their translations live in the other locale files, so a changed default
 * needs its translations redone too.
 *
 * Spotlight selectors reuse the same stable data-testid hooks the
 * ProductTour relies on, so the highlight survives Tailwind churn and
 * button reorders.
 */
export const boqGuide: ModuleGuideContent = {
  titleKey: 'guide.boq.title',
  titleDefault: 'Bill of Quantities',
  introKey: 'guide.boq.intro',
  introDefault:
    'A Bill of Quantities is a structured, priced list of every item of work in a project. You build it top-down: first the sections that group the work, then the positions inside them, then the quantities and rates that drive the cost.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.boq.structure.title',
      titleDefault: 'Sections and positions',
      bodyKey: 'guide.boq.structure.body',
      bodyDefault:
        'The BOQ is a hierarchy. Sections are the headings that group related work, such as a trade or building element. Positions are the priced line items that sit under a section. Add as many sections as you need and nest positions beneath them to mirror how the job is organised.',
      spotlightSelector: '[data-testid="boq-add-position-button"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.boq.columns.title',
      titleDefault: 'The core columns',
      bodyKey: 'guide.boq.columns.body',
      bodyDefault:
        'Each position carries a Description, a Unit, a Quantity and a Unit Rate. The Total is computed for you as Quantity times Unit Rate, with no tax and no markups baked in. Click any cell to edit it, and double-click a description to open the full Langtext for longer specifications.',
      spotlightSelector: '[data-testid="boq-grid"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.boq.entry.title',
      titleDefault: 'Entering and editing rows',
      bodyKey: 'guide.boq.entry.body',
      bodyDefault:
        'Use Add position for a blank line, or pull priced items straight in with From Database or From Assembly so the description, unit and rate are filled for you. You can also Import from Excel, GAEB, CAD or PDF, or paste rows directly from a spreadsheet.',
      spotlightSelector: '[data-testid="boq-toolbar"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.boq.markups.title',
      titleDefault: 'Markups and the gross total',
      bodyKey: 'guide.boq.markups.body',
      bodyDefault:
        'The net total is the sum of every line. Markups add the rest on top as percentages: overhead, profit, contingency, insurance, bond and tax. The tax row drives the VAT rate, and together they roll the net up into the gross total shown in the summary.',
      spotlightSelector: '[data-testid="boq-markup-panel"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.boq.quality.title',
      titleDefault: 'Quality and validation',
      bodyKey: 'guide.boq.quality.body',
      bodyDefault:
        'The quality ring scores your estimate live and flags missing quantities, zero prices and duplicates. Run Validate for a full compliance check, and use the AI tools to find costs, fill gaps and catch anomalies before you finish.',
      spotlightSelector: '[data-testid="boq-quality-ring"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.boq.export.title',
      titleDefault: 'Exporting and sharing',
      bodyKey: 'guide.boq.export.body',
      bodyDefault:
        'When the estimate is ready, Export it to GAEB, Excel, CSV or PDF, or create a revision to keep a frozen snapshot. Compare lets you check one BOQ against another to see what changed.',
      spotlightSelector: '[data-testid="boq-export-button"]',
    },
  ],
  ctaKey: 'guide.boq.cta',
  ctaDefault: 'Add your first position',
};
