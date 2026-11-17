// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The register lessons as spotlight cards, in the order the course runs them. */
export const surveyGuide: ModuleGuideContent = {
  titleKey: 'survey.page.register',
  titleDefault: 'Survey register',
  introKey: 'survey.guide.intro',
  introDefault: 'Every survey number on this project hangs from the points kept here, in one coordinate system.',
  sections: [
    {
      icon: 'Search',
      titleKey: 'survey.action.set_crs',
      titleDefault: 'Set project CRS',
      bodyKey: 'survey.guide.crs_body',
      bodyDefault: 'Search the EPSG code your surveyor used, for example 32633, and pick it. The chip next to the title shows it.',
      spotlightSelector: '[data-testid="survey-crs-chip"]',
    },
    {
      icon: 'Database',
      titleKey: 'survey.action.import_points',
      titleDefault: 'Import points',
      bodyKey: 'survey.guide.import_body',
      bodyDefault: 'Drop a CSV from the instrument, check the column order (PNEZD is the usual one) and read the preview. Only Import saves.',
      spotlightSelector: '[data-testid="survey-import"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'survey.guide.check_title',
      titleDefault: 'Fix what the checks find',
      bodyKey: 'survey.guide.check_body',
      bodyDefault: 'A point ID used twice, a file without a coordinate system or an unconfirmed guess shows as a finding with one fix.',
      spotlightSelector: '[data-testid="survey-findings"]',
    },
  ],
};
