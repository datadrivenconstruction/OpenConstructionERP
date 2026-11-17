// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The volumes lessons as spotlight cards, in the order the course runs them. */
export const volumesGuide: ModuleGuideContent = {
  titleKey: 'volumes.page.title',
  titleDefault: 'Volumes',
  introKey: 'volumes.guide.intro',
  introDefault: 'Cut and fill between two ground surfaces, checked and confirmed before they become BOQ quantities.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'volumes.action.new_surface',
      titleDefault: 'New surface',
      bodyKey: 'volumes.guide.surface_body',
      bodyDefault: 'Build the existing ground from a point set, then import the design as LandXML. Check the point count and the area.',
      spotlightSelector: '[data-testid="volumes-new-surface"]',
    },
    {
      icon: 'Plus',
      titleKey: 'volumes.action.new_volume',
      titleDefault: 'New volume',
      bodyKey: 'volumes.guide.volume_body',
      bodyDefault: 'Pick the base (earlier) and the compare (later) surface and a name. The grid method with an automatic cell size is used.',
      spotlightSelector: '[data-testid="volumes-new"]',
    },
    {
      icon: 'CheckCircle2',
      titleKey: 'volumes.action.confirm',
      titleDefault: 'Confirm result',
      bodyKey: 'volumes.guide.confirm_body',
      bodyDefault: 'Read the coverage, the confidence and the findings, then confirm. Send to BOQ and Record progress open only after that.',
      spotlightSelector: '[data-testid="volumes-table"]',
    },
  ],
};
