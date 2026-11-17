// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The Land & parcels lessons as spotlight cards, in the order the course runs them. */
export const parcelsGuide: ModuleGuideContent = {
  titleKey: 'survey.parcels.title',
  titleDefault: 'Land & parcels',
  introKey: 'survey.parcels.guide.intro',
  introDefault: 'Which land the works need, who holds it, and whether the project has it yet.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'survey.parcels.btn.import',
      titleDefault: 'Import parcels',
      bodyKey: 'survey.parcels.guide.import_body',
      bodyDefault: 'Drop a GeoJSON or a zipped Shapefile. The preview shows each parcel with its area before anything is saved.',
      spotlightSelector: '[data-testid="parcels-import"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'survey.parcels.guide.check_title',
      titleDefault: 'Compare the areas',
      bodyKey: 'survey.parcels.guide.check_body',
      bodyDefault: 'Computed comes from the boundary points, Legal from the register. A difference beyond tolerance shows as PAR-001.',
      spotlightSelector: '[data-testid="parcels-table"]',
    },
    {
      icon: 'Map',
      titleKey: 'survey.parcels.guide.zone_title',
      titleDefault: 'Check the work zone',
      bodyKey: 'survey.parcels.guide.zone_body',
      bodyDefault: 'Import the work zone. A parcel it crosses that is not Acquired yet blocks the works (PAR-003).',
      spotlightSelector: '[data-testid="parcels-kpi"]',
    },
    {
      icon: 'FileText',
      titleKey: 'survey.parcels.btn.print',
      titleDefault: 'Print schedule',
      bodyKey: 'survey.parcels.guide.print_body',
      bodyDefault: 'Export the parcels as Shapefile, GeoJSON or DXF, or print the parcel schedule with its findings.',
      spotlightSelector: '[data-testid="parcels-print"]',
    },
  ],
};
