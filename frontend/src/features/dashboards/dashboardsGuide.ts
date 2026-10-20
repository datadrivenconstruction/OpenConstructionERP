// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// dashboardsGuide - "How it works" content for the Data Snapshots module.
// Consumed by <ModuleGuideButton content={dashboardsGuide} /> on SnapshotsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const dashboardsGuide: ModuleGuideContent = {
  titleKey: 'guide.dashboards.title',
  titleDefault: 'Data Snapshots',
  introKey: 'guide.dashboards.intro',
  introDefault:
    'A snapshot freezes the uploaded CAD and BIM files of a project into a dated parquet dataset of every element and category. Use it to prove what changed between model revisions and to feed the charts, CAD-BIM BI Explorer and cost flows that read from it.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.dashboards.concept.title',
      titleDefault: 'What a snapshot is',
      bodyKey: 'guide.dashboards.concept.body',
      bodyDefault:
        'Each snapshot is a frozen parquet dataset captured from a project at one point in time. It records the total entities and categories plus per-source summary stats, so the model state is provable and queryable long after the source files change.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.dashboards.create.title',
      titleDefault: 'Create a snapshot',
      bodyKey: 'guide.dashboards.create.body',
      bodyDefault:
        'Snapshots are scoped to a project, so pick one first. Click New snapshot and select the uploaded IFC, RVT or DWG files to freeze. The capture rolls every element and category into a dated parquet dataset that later dashboards can query.',
      spotlightSelector: '[data-testid="dashboards-new-snapshot-btn"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.dashboards.list.title',
      titleDefault: 'Browse the snapshot list',
      bodyKey: 'guide.dashboards.list.body',
      bodyDefault:
        'The Snapshots view shows every capture as a card with its date, entity and category counts, and summary badges. Delete a snapshot you no longer need, or load more when a large project has paged results.',
      spotlightSelector: '[data-testid="dashboards-view-list"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.dashboards.timeline.title',
      titleDefault: 'Track growth on the timeline',
      bodyKey: 'guide.dashboards.timeline.body',
      bodyDefault:
        'The Timeline view lines up every snapshot in order so you can see how the project model grew over time. It is the quick read on cadence and scope before you dig into a specific revision.',
      spotlightSelector: '[data-testid="dashboards-view-timeline"]',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.dashboards.compare.title',
      titleDefault: 'Compare two revisions',
      bodyKey: 'guide.dashboards.compare.body',
      bodyDefault:
        'The Compare view sets an older snapshot A against a newer snapshot B and lists the schema-level changes between them. This is how you prove exactly what was added, removed or altered from one model revision to the next.',
      spotlightSelector: '[data-testid="dashboards-view-diff"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.dashboards.downstream.title',
      titleDefault: 'Put a snapshot to work',
      bodyKey: 'guide.dashboards.downstream.body',
      bodyDefault:
        'A snapshot is not a dead end. From any card, jump to CAD-BIM Match to price its elements against cost, or to PDF Takeoff to measure quantities. The frozen dataset is also what the CAD-BIM BI Explorer queries.',
    },
  ],
  ctaKey: 'guide.dashboards.cta',
  ctaDefault: 'Create your first snapshot',
};
