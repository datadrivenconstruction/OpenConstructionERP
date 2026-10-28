// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// serviceGuide - "How it works" content for the Service & Maintenance module.
// Consumed by <ModuleGuideButton content={serviceGuide} /> on ServicePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const serviceGuide: ModuleGuideContent = {
  titleKey: 'guide.service.title',
  titleDefault: 'Service & Maintenance',
  introKey: 'guide.service.intro',
  introDefault:
    'Run the full after-sales lifecycle in one place: service contracts, the assets they cover, the tickets raised against them, and the work orders that get an engineer on site and the visit billed. Use it whenever a customer reports a fault or a maintenance visit is due.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.service.flow.title',
      titleDefault: 'From customer call to billed visit',
      bodyKey: 'guide.service.flow.body',
      bodyDefault:
        'The flow runs left to right across the tabs. Set up a contract for a customer, register the assets it covers, then log a ticket whenever something needs attention. Dispatching a ticket creates a work order, and once the work is completed with a debrief it can be billed into Finance.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.service.contracts.title',
      titleDefault: 'Contracts are the foundation',
      bodyKey: 'guide.service.contracts.body',
      bodyDefault:
        'A service contract ties a customer to a coverage period, an SLA tier and a value. Customers come from Contacts, and the contract is what everything else hangs off, so create one before adding assets or tickets. Deleting a contract cascades to its assets, tickets and work orders.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.service.assets.title',
      titleDefault: 'Register the assets you maintain',
      bodyKey: 'guide.service.assets.body',
      bodyDefault:
        'Each asset is a piece of equipment under a contract, such as HVAC units, lifts or generators, with a tag, type, location and warranty date. Pick the contract from the selector, then add the assets it covers so tickets can be raised against the right equipment.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.service.tickets.title',
      titleDefault: 'Tickets and the SLA clock',
      bodyKey: 'guide.service.tickets.body',
      bodyDefault:
        'A ticket records a fault or request with a priority and status, from new through assigned, in progress, resolved and closed. The SLA chip counts down to the due time and turns red on breach, and the Overdue only filter isolates the tickets at risk. Dispatch a ticket to a technician to spin up a work order.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.service.work_orders.title',
      titleDefault: 'Work orders and billing',
      bodyKey: 'guide.service.work_orders.body',
      bodyDefault:
        'A work order schedules an engineer and tracks the on-site job from dispatched through in progress to completed. Closing it out needs a debrief covering the problem, cause and solution, and once completed you bill the work order so its value rolls into Finance.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.service.recurring.title',
      titleDefault: 'Recurring maintenance',
      bodyKey: 'guide.service.recurring.body',
      bodyDefault:
        'The Recurring tab sets up planned preventive maintenance on a schedule against a contract, so routine visits are generated automatically instead of waiting for a fault to be reported. Use it for the periodic inspections and servicing your contracts commit to.',
    },
  ],
  ctaKey: 'guide.service.cta',
  ctaDefault: 'Create your first contract',
};
