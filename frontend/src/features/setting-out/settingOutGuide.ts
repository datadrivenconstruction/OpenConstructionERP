// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The setting-out lessons as spotlight cards, in the order the course runs them. */
export const settingOutGuide: ModuleGuideContent = {
  titleKey: 'survey.page.setting_out',
  titleDefault: 'Setting-out',
  introKey: 'survey.setting_out.guide.intro',
  introDefault: 'Mark design points on site, type what the instrument measured, and see Pass or Fail at once.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'survey.setting_out.guide.request_title',
      titleDefault: 'Open the request',
      bodyKey: 'survey.setting_out.guide.request_body',
      bodyDefault: 'A request lists the points to stake and the tolerance they are checked against, for example Demo 10 mm.',
      spotlightSelector: '[data-testid="so-request-tolerance"]',
    },
    {
      icon: 'Target',
      titleKey: 'survey.setting_out.guide.measure_title',
      titleDefault: 'Enter the measured values',
      bodyKey: 'survey.setting_out.guide.measure_body',
      bodyDefault: 'Type the measured E and N from the instrument. d is the distance to the design point in mm; within tolerance is Pass.',
      spotlightSelector: '[data-testid^="stake-card-"]',
    },
    {
      icon: 'AlertTriangle',
      titleKey: 'survey.setting_out.action.create_ncr',
      titleDefault: 'Create NCR draft',
      bodyKey: 'survey.setting_out.guide.ncr_body',
      bodyDefault: 'A failed stake gets a Create NCR draft button. The draft appears in Quality with the numbers filled in.',
      spotlightSelector: '[data-testid="so-findings"]',
    },
    {
      icon: 'Printer',
      titleKey: 'survey.setting_out.action.print_sheet',
      titleDefault: 'Print sheet',
      bodyKey: 'survey.setting_out.guide.print_body',
      bodyDefault: 'The setting-out sheet lists every point, its verdict and who measured it, for the site file.',
      spotlightSelector: '[data-testid="so-print-sheet"]',
    },
  ],
};
