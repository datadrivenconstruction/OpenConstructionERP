// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Inside track - "Coming next" roadmap list.
//
// Deliberately just plain one-line titles, not prose blurbs: this list has to
// stay cheap to maintain, since it is a donor perk and not a product a team
// is staffed to keep narrating. Reorder or edit titles here as direction
// shifts; nothing else in the feature needs to change when this list does.
// Keep entries honest and non-committal - a direction, not a promise.

export interface InsideRoadmapItem {
  /** Stable id, unique within the list. */
  id: string;
  /** i18n key for the title. */
  titleKey: string;
  /** Inline English default for the title. */
  titleDefault: string;
}

export const INSIDE_ROADMAP: InsideRoadmapItem[] = [
  {
    id: 'regional-cost-data',
    titleKey: 'inside.roadmap.regional_cost_data',
    titleDefault: 'More regional cost databases (CWICR)',
  },
  {
    id: 'ai-estimation',
    titleKey: 'inside.roadmap.ai_estimation',
    titleDefault: 'Sharper AI estimation and cost matching',
  },
  {
    id: 'cad-formats',
    titleKey: 'inside.roadmap.cad_formats',
    titleDefault: 'Support for more CAD and BIM file formats',
  },
  {
    id: 'bim-viewer',
    titleKey: 'inside.roadmap.bim_viewer',
    titleDefault: 'A faster, more capable BIM viewer',
  },
  {
    id: 'takeoff',
    titleKey: 'inside.roadmap.takeoff',
    titleDefault: 'Better PDF and drawing takeoff tools',
  },
  {
    id: 'portal',
    titleKey: 'inside.roadmap.portal',
    titleDefault: 'A richer client and partner portal',
  },
  {
    id: 'scheduling',
    titleKey: 'inside.roadmap.scheduling',
    titleDefault: 'Deeper scheduling and progress tracking',
  },
  {
    id: 'mobile',
    titleKey: 'inside.roadmap.mobile',
    titleDefault: 'A mobile app for field use',
  },
];
