// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// projectsGuide - "How it works" content for the Projects module.
//
// Co-located with the feature so the copy lives next to the screen it
// describes. Every key carries an inline English default and is consumed
// through t(key, { defaultValue }); the keys are not in en.ts, the inline
// defaults are the English source; their translations live in the other
// locale files, so a changed default needs its translations redone too. The sections explain the core concepts first, then walk the
// user through actually creating a project and filling in its key fields.

import type { ModuleGuideContent } from '@/shared/ui';

export const projectsGuide: ModuleGuideContent = {
  titleKey: 'guide.projects.title',
  titleDefault: 'Projects',
  introKey: 'guide.projects.intro',
  introDefault:
    'A project is the home for one piece of work and everything that hangs off it: its estimates, drawings, documents, team and totals. You create a project once, set a few defaults, and the rest of the platform works inside it.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.projects.concept.title',
      titleDefault: 'What a project holds',
      bodyKey: 'guide.projects.concept.body',
      bodyDefault:
        'Each project owns its bills of quantities, uploaded files, validation reports and settings. On this page every project shows as a card with its BOQ count, total value in its own currency, region and file types, so you read the whole portfolio at a glance.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.projects.create.title',
      titleDefault: 'Creating a project',
      bodyKey: 'guide.projects.create.body',
      bodyDefault:
        'Click New project. Pick Quick create to set everything on one screen, or Guided setup for five short steps that also pre-select the right modules. Only the project name is required; everything else is optional and editable later.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.projects.fields.title',
      titleDefault: 'The key fields',
      bodyKey: 'guide.projects.fields.body',
      bodyDefault:
        'Name identifies the project. Region drives the cost database and local rules. Currency is the base currency for every price and total. Classification standard (DIN 276, NRM, MasterFormat and others) sets how work is coded. Language localizes labels for the team.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.projects.details.title',
      titleDefault: 'Optional details',
      bodyKey: 'guide.projects.details.body',
      bodyDefault:
        'Add a description, site address, client, project code, planned start and end dates and a budget when you have them. The address anchors the project on the map and weather widgets. None of these block creation; fill them in as the project takes shape.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.projects.organize.title',
      titleDefault: 'Find and organize',
      bodyKey: 'guide.projects.organize.body',
      bodyDefault:
        'Search by name, filter by status or region, and sort by name, date or value. Pin the projects you touch daily to keep them on top, and archive finished ones to clear the list without deleting their data.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.projects.next.title',
      titleDefault: 'What happens next',
      bodyKey: 'guide.projects.next.body',
      bodyDefault:
        'Open a card to reach the project hub, where you build BOQs, upload drawings and run validation. Project totals roll up into Analytics and the role dashboards in Reporting, so the numbers you enter here surface across the platform.',
    },
  ],
  ctaKey: 'guide.projects.cta',
  ctaDefault: 'Create your first project',
};
