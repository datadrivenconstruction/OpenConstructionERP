// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// frameworkGuide - "How it works" content for framework agreements.
// Consumed by <ModuleGuideButton content={frameworkGuide} />. Keys carry their inline
// English default; translations live in the locale files.

import type { ModuleGuideContent } from '@/shared/ui';

export const frameworkGuide: ModuleGuideContent = {
  titleKey: 'guide.framework.title',
  titleDefault: 'Framework agreements',
  introKey: 'guide.framework.intro',
  introDefault:
    'A framework agreement fixes unit rates for a term; the client then orders work job by job. Each call-off order is priced from the agreement rates, counts against the cap, and is measured and claimed on its own.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.framework.rates.title',
      titleDefault: 'Price list and rate periods',
      bodyKey: 'guide.framework.rates.body',
      bodyDefault:
        'Import or type the agreed items once. A rate period says which factor applies on an order date: fixed prices, an index ratio or a formula. When an index has no value for the order month, the order is held instead of priced at a factor of one.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.framework.orders.title',
      titleDefault: 'Ordering a job',
      bodyKey: 'guide.framework.orders.body',
      bodyDefault:
        'New order takes items from the price list only, applies the conditions you tick (weekend, out of hours) and freezes the rates on issue. Work outside the price list is raised as an extra on the order.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.framework.cap.title',
      titleDefault: 'The cap',
      bodyKey: 'guide.framework.cap.body',
      bodyDefault:
        'Every issued order adds to the committed total. Past the warning threshold the meter turns amber; an order that would pass the cap cannot be issued unless someone allowed to override gives a reason, which is kept with the order.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.framework.claims.title',
      titleDefault: 'Measurement and claims',
      bodyKey: 'guide.framework.claims.body',
      bodyDefault:
        'Measured quantities are recorded per order line; claims are made on orders, never on the agreement itself, so certified and invoiced amounts roll up to the agreement on their own.',
    },
  ],
};
