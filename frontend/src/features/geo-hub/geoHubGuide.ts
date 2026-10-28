// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// geoHubGuide - "How it works" content for the Geo Hub module.
// Consumed by <ModuleGuideButton content={geoHubGuide} /> on GeoHubPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const geoHubGuide: ModuleGuideContent = {
  titleKey: 'guide.geo_hub.title',
  titleDefault: 'Geo Hub',
  introKey: 'guide.geo_hub.intro',
  introDefault:
    'Geo Hub is the shared 3D globe that pins every one of your projects to its real location on Earth. Use it to see your whole portfolio in space and to jump from a map point straight into a project.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.geo_hub.globe.title',
      titleDefault: 'The global view',
      bodyKey: 'guide.geo_hub.globe.body',
      bodyDefault:
        'The whole canvas is a navigable 3D globe with each anchored project shown as a pin. Drag to rotate, scroll to zoom, and click a pin to open that project. Nearby projects group into a cluster bubble that breaks apart as you fly closer.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.geo_hub.anchor.title',
      titleDefault: 'Anchor your projects',
      bodyKey: 'guide.geo_hub.anchor.body',
      bodyDefault:
        'A project only appears once it is anchored to a location. Use Auto-anchor all my projects to place every project that has an address, or open a single project and set its position by address or coordinates. Auto-anchor reads addresses through OpenStreetMap and caches the result.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.geo_hub.rail.title',
      titleDefault: 'The anchored projects list',
      bodyKey: 'guide.geo_hub.rail.body',
      bodyDefault:
        'The floating panel on the top left lists every anchored project with its coordinates and region. Click a name to fly the camera to it, or use Open to deep link into that project map. Collapse the panel to a slim pill when you want the full globe.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.geo_hub.search.title',
      titleDefault: 'Search any address',
      bodyKey: 'guide.geo_hub.search.body',
      bodyDefault:
        'The search bar at the top finds any address worldwide and drops a single pin there, flying the camera to the spot. It is handy for scouting a site before a project exists. Clear the pin from the chip below the box or press Escape.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.geo_hub.views.title',
      titleDefault: 'Projections and overlays',
      bodyKey: 'guide.geo_hub.views.body',
      bodyDefault:
        'Switch the projection between 3D globe, 2D map, and Columbus view, and your choice is remembered across visits. When a project is in context you can also pin raster overlays, such as a site plan, onto its location right from this view.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.geo_hub.connect.title',
      titleDefault: 'From map to project data',
      bodyKey: 'guide.geo_hub.connect.body',
      bodyDefault:
        'Geo Hub is the spatial entry point to the rest of the platform. Once you open a project from the map you land on its project map, from where you can reach its BOQ, BIM models, and the rest of the canonical project data.',
    },
  ],
  ctaKey: 'guide.geo_hub.cta',
  ctaDefault: 'Anchor your first project',
};
