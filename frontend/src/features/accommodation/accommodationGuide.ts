// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// accommodationGuide - "How it works" content for the Accommodation module.
// Consumed by <ModuleGuideButton content={accommodationGuide} /> on
// AccommodationListPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const accommodationGuide: ModuleGuideContent = {
  titleKey: 'guide.accommodation.title',
  titleDefault: 'Accommodation',
  introKey: 'guide.accommodation.intro',
  introDefault:
    'Accommodation tracks where your people sleep across three kinds of stays: worker camps for site crews, rentals for staff, and hotels for visiting consultants. Use it to house the workforce, hold rooms and bookings in one place, and see who is where on any date.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.accommodation.kinds.title',
      titleDefault: 'Three kinds of property',
      bodyKey: 'guide.accommodation.kinds.body',
      bodyDefault:
        'Every property is a worker camp, a rental or a hotel, shown as a card with its kind badge, project and total capacity. Use the tabs at the top to filter to one kind, and the summary strip to read total properties and capacity at a glance.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.accommodation.create.title',
      titleDefault: 'Create a property',
      bodyKey: 'guide.accommodation.create.body',
      bodyDefault:
        'Click New accommodation and pick the project, kind, name, address and total capacity. The new property opens straight away so you can start adding rooms. You can also bootstrap a camp from a Property Development block to turn planned units into bookable rooms.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.accommodation.rooms.title',
      titleDefault: 'Rooms and bookings',
      bodyKey: 'guide.accommodation.rooms.body',
      bodyDefault:
        'Open a property to manage its rooms, bookings and charges. Each room carries a label, capacity, base rate and status. Bookings move through a clear lifecycle, from reserved to checked in to checked out, and the system blocks two live bookings from overlapping in the same room.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.accommodation.hr_autobook.title',
      titleDefault: 'Suggest a room for an employee',
      bodyKey: 'guide.accommodation.hr_autobook.body',
      bodyDefault:
        'Suggest room for employee bridges your HR contacts into a booking. Pick a person and a start date, and the module proposes the best available room with its rate, so you assign people to real vacancy instead of hunting for free beds by hand.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.accommodation.calendar.title',
      titleDefault: 'See who is where',
      bodyKey: 'guide.accommodation.calendar.body',
      bodyDefault:
        'Open the Calendar to see every bed across every date, with rooms down the side and dates across the top. A filled cell is a booking and an empty one is a free bed, so conflicts and vacancy read at a glance. Geo links open a property on the map when coordinates are set.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.accommodation.charges.title',
      titleDefault: 'Charges and billing',
      bodyKey: 'guide.accommodation.charges.body',
      bodyDefault:
        'Each booking can carry charges for base rent, extras, deposits and refunds. A charge moves from pending to invoiced to paid, or can be waived, and once it is paid or waived it locks so settled records stay intact.',
    },
  ],
  ctaKey: 'guide.accommodation.cta',
  ctaDefault: 'Create your first property',
};
