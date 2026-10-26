// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// guaranteesGuide - "How it works" content for the Guarantees module.
// Consumed by <ModuleGuideButton content={guaranteesGuide} /> on GuaranteesPage.

import type { ModuleGuideContent } from '@/shared/ui';

export const guaranteesGuide: ModuleGuideContent = {
  titleKey: 'guide.guarantees.title',
  titleDefault: 'Guarantees',
  introKey: 'guide.guarantees.intro',
  introDefault:
    'Guarantees is the register of every bank guarantee and bond you give or hold: bid, performance, advance payment, retention, warranty and parent company. It keeps expiry dates in front of you, tracks each change as a timeline and shows how much of your credit lines is tied up.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.guarantees.register.title',
      titleDefault: 'Register each guarantee',
      bodyKey: 'guide.guarantees.register.body',
      bodyDefault:
        'Record the type, direction, issuing bank, amount and expiry date. Link it to a contract, a tender or a subcontractor, and attach the scanned original from Documents.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.guarantees.lifecycle.title',
      titleDefault: 'Follow the lifecycle',
      bodyKey: 'guide.guarantees.lifecycle.body',
      bodyDefault:
        'A guarantee moves from draft to requested and issued, can be extended or reduced while live, and ends as released, called or expired. Every step is stored on a timeline with the old and new amount and the reason.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.guarantees.expiry.title',
      titleDefault: 'Never miss an expiry',
      bodyKey: 'guide.guarantees.expiry.body',
      bodyDefault:
        'Live guarantees are flagged 60, 30 and 14 days before they expire, and a notification is sent so you can extend the guarantee or plan its release in time.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.guarantees.exposure.title',
      titleDefault: 'Watch your exposure',
      bodyKey: 'guide.guarantees.exposure.body',
      bodyDefault:
        'The exposure view adds up live guarantees per currency, bank and type and compares them with each bank credit line, so you see how much headroom is left before you ask for the next one.',
    },
  ],
  ctaKey: 'guide.guarantees.cta',
  ctaDefault: 'Register your first guarantee',
};
