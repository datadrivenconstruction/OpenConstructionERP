// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// propertyDevGuide - "How it works" content for the Property Development module.
// Consumed by <ModuleGuideButton content={propertyDevGuide} /> on PropertyDevPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const propertyDevGuide: ModuleGuideContent = {
  titleKey: 'guide.property_dev.title',
  titleDefault: 'Property Development',
  introKey: 'guide.property_dev.intro',
  introDefault:
    'Property Development runs the residential sales side of a project, from laying out your inventory to handing keys to buyers. Use it to take a buyer the whole way from first enquiry to handover and after-sales warranty, while signed contract values feed straight into Finance.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.property_dev.inventory.title',
      titleDefault: 'Lay out your inventory',
      bodyKey: 'guide.property_dev.inventory.body',
      bodyDefault:
        'Start with master data. A Development is the top-level project, broken into Phases and Blocks, with Plots as the individual sellable units. House Types are reusable unit templates and variants you assign to plots so pricing and specification stay consistent.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.property_dev.pipeline.title',
      titleDefault: 'The sales pipeline',
      bodyKey: 'guide.property_dev.pipeline.body',
      bodyDefault:
        'The Sales tabs follow one lifecycle. A Lead is an inbound prospect that you qualify into a Buyer, who then holds a unit with a Reservation. The reservation converts into a Sale and Purchase Agreement, and a Payment Schedule splits the price into milestone installments.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.property_dev.tabs.title',
      titleDefault: 'Master data, Sales and Operations',
      bodyKey: 'guide.property_dev.tabs.body',
      bodyDefault:
        'The tabs are grouped into three blocks so the flow reads as one taxonomy. Master data covers developments through house types, Sales covers leads through payment schedules, and Operations holds brokers, the price matrix, escrow, handovers and warranty claims.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.property_dev.create.title',
      titleDefault: 'Create records as you go',
      bodyKey: 'guide.property_dev.create.body',
      bodyDefault:
        'The primary New button always creates the record for the tab you are on, so New Plot on Plots and New Lead on Leads. Contracts and payment schedules are always created downstream, so the button there sends you back to Reservations where that flow begins.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.property_dev.operations.title',
      titleDefault: 'Handover and after-sales',
      bodyKey: 'guide.property_dev.operations.body',
      bodyDefault:
        'Once a unit is paid, record the Handover event and log any snags found at inspection. After the keys change hands, buyers raise Warranty Claims for post-handover defects, which you triage, accept or reject, and close out. Escrow tracks the trust funds released along the way.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.property_dev.analytics.title',
      titleDefault: 'Track performance',
      bodyKey: 'guide.property_dev.analytics.body',
      bodyDefault:
        'The Overview tab shows portfolio KPIs and a pipeline snapshot, and Dashboards opens deeper analytics such as sales velocity, the conversion funnel, inventory ageing and cash flow. Signed contract values flow into Finance so the pipeline and the project books stay in step.',
    },
  ],
  ctaKey: 'guide.property_dev.cta',
  ctaDefault: 'Set up your first development',
};
