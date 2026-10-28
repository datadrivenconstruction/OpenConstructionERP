// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// approvalRoutesGuide - "How it works" content for the Approval Routes module.
// Consumed by <ModuleGuideButton content={approvalRoutesGuide} /> on
// ApprovalRoutesPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const approvalRoutesGuide: ModuleGuideContent = {
  titleKey: 'guide.approval_routes.title',
  titleDefault: 'Approval routes',
  introKey: 'guide.approval_routes.intro',
  introDefault:
    'Approval routes are reusable sign-off workflows applied to records like markups, submittals, RFIs and change orders. Define a route once, then any matching record can run it to collect the right approvals in the right order.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.approval_routes.concept.title',
      titleDefault: 'What an approval route is',
      bodyKey: 'guide.approval_routes.concept.body',
      bodyDefault:
        'A route is a named template tied to one target kind, such as submittals or change orders. It can be Global across every project or scoped to a single project. Build as many as you need to mirror how your organisation signs work off.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.approval_routes.steps.title',
      titleDefault: 'Steps and approvers',
      bodyKey: 'guide.approval_routes.steps.body',
      bodyDefault:
        'A route is an ordered list of steps that are decided one after another. Each step pins an approver as either a role or a specific user, never both. Use the arrows to reorder steps so the sequence matches your chain of command.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.approval_routes.modes.title',
      titleDefault: 'Decision modes and SLA',
      bodyKey: 'guide.approval_routes.modes.body',
      bodyDefault:
        'The mode sets how many assigned approvers must sign off: All, Any or Majority. Role steps clear on the first approval, so to require all or a majority you pin specific users instead. Add an optional SLA in hours to flag steps that overrun.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.approval_routes.create.title',
      titleDefault: 'Creating and editing routes',
      bodyKey: 'guide.approval_routes.create.body',
      bodyDefault:
        'Click New route to open the editor, give the route a name, pick its target kind and scope, then add steps. Once a route is saved its target kind and scope are locked, but you can still rename it, edit its steps, or archive it so new approvals can no longer use it.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.approval_routes.instances.title',
      titleDefault: 'Running and history',
      bodyKey: 'guide.approval_routes.instances.body',
      bodyDefault:
        'The Running and history tab lists every approval workflow started across the app, filterable by kind, status and search. Click a row to open the full step ladder and approve, reject or cancel a pending workflow without leaving the page.',
    },
  ],
  ctaKey: 'guide.approval_routes.cta',
  ctaDefault: 'Create your first route',
};
