// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// changeordersGuide - "How it works" content for the Change Orders module.
// Consumed by <ModuleGuideButton content={changeordersGuide} /> on
// ChangeOrdersPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const changeordersGuide: ModuleGuideContent = {
  titleKey: 'guide.changeorders.title',
  titleDefault: 'Change Orders',
  introKey: 'guide.changeorders.intro',
  introDefault:
    'A change order records a change to the agreed scope along with its cost and schedule impact. Use it whenever work is added, removed or modified after the estimate is set, so every variation is priced and approved before it is committed.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.changeorders.concept.title',
      titleDefault: 'What a change order is',
      bodyKey: 'guide.changeorders.concept.body',
      bodyDefault:
        'Each order groups one scope change under a code, a title and a reason such as client request, design change or unforeseen conditions. It carries line items, a computed cost impact and a schedule impact in days, giving you a single auditable record of what changed and why.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.changeorders.create.title',
      titleDefault: 'Create an order',
      bodyKey: 'guide.changeorders.create.body',
      bodyDefault:
        'Click New Change Order to capture the title, description, reason and schedule impact by hand, and optionally apply it to a live contract. Or use AI Draft to generate a starting order from a short prompt, then review and adjust it before submitting.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.changeorders.items.title',
      titleDefault: 'Add line items',
      bodyKey: 'guide.changeorders.items.body',
      bodyDefault:
        'Each item records the original versus new quantity and rate, and the cost delta is calculated for you. Use Pick from BOQ to seed an item straight from an estimate position so its original values come from the work being amended rather than being re-keyed.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.changeorders.workflow.title',
      titleDefault: 'Move through the workflow',
      bodyKey: 'guide.changeorders.workflow.body',
      bodyDefault:
        'An order runs Draft, Submitted, Approved and Executed, with rejection available along the way. Open an order to submit it, and route approval either directly or through a named approval chain where each approver signs off in turn before the next step becomes active.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.changeorders.impact.title',
      titleDefault: 'See the impact',
      bodyKey: 'guide.changeorders.impact.body',
      bodyDefault:
        'The summary cards roll up total orders, approved cost impact, schedule days and pending count for the active project. An approved order is applied to the project budget as a revised commitment, and when it is linked to a contract the contract value is revised on approval too.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.changeorders.track.title',
      titleDefault: 'Track and export',
      bodyKey: 'guide.changeorders.track.body',
      bodyDefault:
        'The table lists every order with its code, status, reason, cost impact and dates. Filter by status to focus on what is in flight, and use Export CSV to hand the full list to finance or reporting.',
    },
  ],
  ctaKey: 'guide.changeorders.cta',
  ctaDefault: 'Create your first change order',
};
