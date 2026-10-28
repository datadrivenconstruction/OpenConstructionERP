// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// resourcesGuide - "How it works" content for the Resources & Crews module.
// Consumed by <ModuleGuideButton content={resourcesGuide} /> on ResourcesPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const resourcesGuide: ModuleGuideContent = {
  titleKey: 'guide.resources.title',
  titleDefault: 'Resources & Crews',
  introKey: 'guide.resources.intro',
  introDefault:
    'This is where you register the people, crews and equipment that do the work, then put them to work on projects. A request creates demand, an assignment reserves a resource for a date range, and double-booking conflicts are flagged for you so two jobs never claim the same crew.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.resources.catalog.title',
      titleDefault: 'Your resource pool',
      bodyKey: 'guide.resources.catalog.body',
      bodyDefault:
        'The Resources tab is your roster of every person, crew, piece of equipment and subcontractor. Each one has a code, a type, a status of active, on leave or inactive, and a default cost rate. Use New Resource to add one, click the rate to edit it inline, and select rows to export them to CSV.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.resources.find.title',
      titleDefault: 'Find and sort the roster',
      bodyKey: 'guide.resources.find.body',
      bodyDefault:
        'Search by code, name or notes, then narrow the list with the type, status and currency filters. Click any column header to sort, and click a row to open its full detail drawer with skills, certifications and availability.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.resources.requests.title',
      titleDefault: 'Requests capture demand',
      bodyKey: 'guide.resources.requests.body',
      bodyDefault:
        'The Requests tab is the demand side. A foreman or project manager raises a request such as two carpenters with formwork experience next week, with a quantity, priority and date window. Requests are scoped per project, so pick the project first, then track them as open, fulfilled or cancelled.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.resources.fulfill.title',
      titleDefault: 'Fulfil into an assignment',
      bodyKey: 'guide.resources.fulfill.body',
      bodyDefault:
        'A dispatcher fulfils an open request by matching an available resource, which creates an assignment that reserves that resource for the requested dates. You can also propose an assignment directly from the Assignments tab when there is no formal request.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.resources.assignments.title',
      titleDefault: 'Assignments and conflicts',
      bodyKey: 'guide.resources.assignments.body',
      bodyDefault:
        'The Assignments tab is the board of who is reserved and when, moving through proposed, confirmed, in progress and completed. The system flags double-booking conflicts automatically, so you can confirm, cancel or reassign before anyone is committed to two places at once.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.resources.portfolio.title',
      titleDefault: 'See the bigger picture',
      bodyKey: 'guide.resources.portfolio.body',
      bodyDefault:
        'Confirmed assignments are the source of truth for who is on site each day. Jump to Portfolio capacity and Resource leveling to balance workload across projects, and follow the links into the schedule and tasks to keep everything aligned.',
    },
  ],
  ctaKey: 'guide.resources.cta',
  ctaDefault: 'Add your first resource',
};
