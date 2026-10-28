// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// architectureGuide - "How it works" content for the Architecture Map module.
// Consumed by <ModuleGuideButton content={architectureGuide} /> on
// ArchitectureMapPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const architectureGuide: ModuleGuideContent = {
  titleKey: 'guide.architecture.title',
  titleDefault: 'Architecture Map',
  introKey: 'guide.architecture.intro',
  introDefault:
    'The Architecture Map is an interactive diagram of how the platform fits together: every backend module, its data models, its API routes and the links between them. Use it to explore the system, trace a feature end to end, and understand what depends on what.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.architecture.canvas.title',
      titleDefault: 'An interactive node graph',
      bodyKey: 'guide.architecture.canvas.body',
      bodyDefault:
        'The platform is drawn as a graph of nodes connected by edges. Pan by dragging the canvas, zoom with the controls in the corner, and use the mini-map to jump around a large layout. Nodes are colour-coded by category so related parts of the system read at a glance.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.architecture.views.title',
      titleDefault: 'Four levels of detail',
      bodyKey: 'guide.architecture.views.body',
      bodyDefault:
        'The buttons in the top bar switch the view. Module Overview shows modules and their dependencies, Data Models shows tables and their foreign keys, API Flow links frontend features to their backend routes, and Full Detail combines modules, models and routes in one picture.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.architecture.search.title',
      titleDefault: 'Find a node fast',
      bodyKey: 'guide.architecture.search.body',
      bodyDefault:
        'Type into the search box to highlight matching nodes by name or module and dim everything else, so a single module or table stands out in a crowded diagram. Clear the box to bring the whole graph back into focus.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.architecture.details.title',
      titleDefault: 'Inspect any node',
      bodyKey: 'guide.architecture.details.body',
      bodyDefault:
        'Click a node to open the detail panel on the right. For a module it lists dependencies, models and routes; for a model it lists every column, its type and its relationships; for a route it shows the method, path and any response or request schema.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.architecture.legend.title',
      titleDefault: 'Read the legend',
      bodyKey: 'guide.architecture.legend.body',
      bodyDefault:
        'The legend in the corner decodes the diagram. Node colours map to module categories, edge styles tell dependency, foreign key and API links apart, and the column markers flag which fields are primary keys and which are foreign keys.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.architecture.stats.title',
      titleDefault: 'Live system totals',
      bodyKey: 'guide.architecture.stats.body',
      bodyDefault:
        'The badge in the top bar sums up the whole platform at a glance: how many backend modules, data models and API routes are present. The map is generated from the live system, so it stays in step as the platform grows.',
    },
  ],
  ctaKey: 'guide.architecture.cta',
  ctaDefault: 'Explore the map',
};
