// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The monitoring lessons as spotlight cards, in the order the course runs them. */
export const monitoringGuide: ModuleGuideContent = {
  titleKey: 'survey.page.monitoring',
  titleDefault: 'Monitoring',
  introKey: 'survey.monitoring.guide.intro',
  introDefault: 'Watch how a wall, a pin or a prism moves between surveys, and see at once when a limit is crossed.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'survey.monitoring.action.import_readings',
      titleDefault: 'Import readings',
      bodyKey: 'survey.monitoring.guide.import_body',
      bodyDefault: 'Drop a CSV with point, date and Z (or E, N, Z). Read the preview, then Import. New points are created for you.',
      spotlightSelector: '[data-testid="mon-import"]',
    },
    {
      icon: 'Activity',
      titleKey: 'survey.monitoring.guide.levels_title',
      titleDefault: 'Read the levels',
      bodyKey: 'survey.monitoring.guide.levels_body',
      bodyDefault: 'OK, Alert, Action and Alarm come from the limits of the profile. Open a point to see its readings against the bands.',
      spotlightSelector: '[data-testid="mon-points"]',
    },
    {
      icon: 'CheckCircle2',
      titleKey: 'survey.monitoring.action.acknowledge',
      titleDefault: 'Acknowledge',
      bodyKey: 'survey.monitoring.guide.ack_body',
      bodyDefault: 'When an alert is open, write what you did. Your name and the time go on the alarm report.',
      spotlightSelector: '[data-testid="mon-points"]',
    },
  ],
};
