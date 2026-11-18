// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The stockpile lessons as spotlight cards, in the order the course runs them. */
export const stockpilesGuide: ModuleGuideContent = {
  titleKey: 'stockpiles.page.title',
  titleDefault: 'Stockpiles',
  introKey: 'stockpiles.guide.intro',
  introDefault: 'Survey a pile, turn its volume into tonnes, compare with the book and correct the inventory with a confirmed adjustment.',
  sections: [
    {
      icon: 'Plus',
      titleKey: 'stockpiles.action.new_stockpile',
      titleDefault: 'New stockpile',
      bodyKey: 'stockpiles.guide.create_body',
      bodyDefault: 'Name the pile, load the ground file under it and enter the book stock.',
      spotlightSelector: '[data-testid="stockpiles-new"]',
    },
    {
      icon: 'Package',
      titleKey: 'stockpiles.action.add_survey',
      titleDefault: 'Add survey',
      bodyKey: 'stockpiles.guide.survey_body',
      bodyDefault: 'Add the pile file with the density and its source. Check volume, tonnes and variance.',
      spotlightSelector: '[data-testid="stockpiles-add-survey"]',
    },
    {
      icon: 'CheckCircle2',
      titleKey: 'stockpiles.action.propose',
      titleDefault: 'Propose adjustment',
      bodyKey: 'stockpiles.guide.adjust_body',
      bodyDefault: 'If the variance is real, propose an adjustment and confirm it. The inventory moves only then.',
      spotlightSelector: '[data-testid="stockpile-cards"]',
    },
  ],
};
