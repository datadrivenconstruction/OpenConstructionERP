// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// variationsGuide - "How it works" content for the Variations module.
// Consumed by <ModuleGuideButton content={variationsGuide} /> on
// VariationsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const variationsGuide: ModuleGuideContent = {
  titleKey: 'guide.variations.title',
  titleDefault: 'Variations',
  introKey: 'guide.variations.intro',
  introDefault:
    'Variations is where you settle changes to the contract before they turn into disputes. Track a change event from a notice, through a priced request, to an agreed order, with daywork sheets and extension-of-time claims running alongside, all the way to the final account.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.variations.lifecycle.title',
      titleDefault: 'The change lifecycle',
      bodyKey: 'guide.variations.lifecycle.body',
      bodyDefault:
        'A change moves through five record types, shown as tabs: a Notice flags the event, a Request prices its cost and schedule impact, an Order is the agreed instruction, Daywork captures work done on a rates basis, and EoT claims handle time extensions. The detail panel draws a stepper across Notice, Request and Order so you always see where a change sits.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.variations.notices.title',
      titleDefault: 'Raise a notice',
      bodyKey: 'guide.variations.notices.body',
      bodyDefault:
        'Issue a notice the moment a contractual event occurs to protect your position and the clock. Each notice records a recipient and a response-by date, then runs through issued, acknowledged, responded and closed as the other party reacts.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.variations.requests.title',
      titleDefault: 'Price and approve requests',
      bodyKey: 'guide.variations.requests.body',
      bodyDefault:
        'A variation request carries the estimated cost and schedule-day impact for review. Submit it, then approve or reject with decision notes. Once approved, convert it straight into a variation order so the agreed figures flow on without re-keying.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.variations.orders.title',
      titleDefault: 'Agree orders into the final account',
      bodyKey: 'guide.variations.orders.body',
      bodyDefault:
        'A variation order is the agreed instruction carrying its final cost and time impact. Start it, complete it or void it as work proceeds. On agreement the order feeds the contract final account and rolls up into Finance, so nothing settled on site is lost. Completed and voided orders are locked from editing.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.variations.daywork_eot.title',
      titleDefault: 'Daywork and extension-of-time',
      bodyKey: 'guide.variations.daywork_eot.body',
      bodyDefault:
        'Daywork sheets log daily labour, material and equipment for owner sign-off, moving from draft to signed to billed. Extension-of-Time claims record a delay cause, requested versus granted days and whether the critical path is affected, then run through submission to a grant or rejection.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.variations.dashboard.title',
      titleDefault: 'Watch the running impact',
      bodyKey: 'guide.variations.dashboard.body',
      bodyDefault:
        'The KPI strip keeps the live picture in view: open notices, pending requests, active orders, total cost impact, schedule impact in days and open EoT claims. Use search and the status filter inside each tab to pull up exactly the records you need.',
    },
  ],
  ctaKey: 'guide.variations.cta',
  ctaDefault: 'Raise your first notice',
};
