// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// mocGuide - "How it works" content for the Management of Change module.
// Consumed by <ModuleGuideButton content={mocGuide} /> on MoCPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const mocGuide: ModuleGuideContent = {
  titleKey: 'guide.moc.title',
  titleDefault: 'Management of Change',
  introKey: 'guide.moc.intro',
  introDefault:
    'Management of Change is the gate that stops a deviation from the agreed design, scope or process from happening informally. Use it to capture a proposed change, assess its cost, schedule and risk impact, then route it through review and approval before any work changes.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.moc.raise.title',
      titleDefault: 'Raise a change request',
      bodyKey: 'guide.moc.raise.body',
      bodyDefault:
        'Click New change request and give it a title, a category (engineering, scope, design, process, material, safety, regulatory and more) and a risk level from low to critical. Add a headline cost impact, currency and schedule delta in days so the commercial effect is on record from the start. Each request gets its own unique code.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.moc.impacts.title',
      titleDefault: 'Assess the full impact',
      bodyKey: 'guide.moc.impacts.body',
      bodyDefault:
        'The headline figure is rarely the whole story. Expand a request and add one or more impact assessment lines, each scoped to an area such as cost, schedule, safety, quality or environment, with its own severity, cost, schedule delta and mitigation. Together they record the complete effect, not just the headline.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.moc.flow.title',
      titleDefault: 'Review and decide',
      bodyKey: 'guide.moc.flow.body',
      bodyDefault:
        'Every change moves through a controlled flow: proposed, reviewed, then accepted or declined, and finally implemented. Mark it reviewed once it has been technically checked, then accept or decline it. A declined request is final and cannot be reopened. Once an approved change is carried out on site or in the model, mark it implemented.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.moc.audit.title',
      titleDefault: 'A locked audit trail',
      bodyKey: 'guide.moc.audit.body',
      bodyDefault:
        'Only the transitions that are legal right now are offered, because the status flow is enforced by the backend. Review and decision notes are captured at each step, and the proposed, reviewed, decided and implemented timestamps are kept, so there is always a clear record of who decided what and when.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.moc.track.title',
      titleDefault: 'Track the register',
      bodyKey: 'guide.moc.track.body',
      bodyDefault:
        'The summary cards show totals at a glance: total, in progress, accepted and implemented. Search by title or code and filter by status to focus on what needs attention. Risk, cost impact and status are shown on every row so the whole register stays readable.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.moc.commercial.title',
      titleDefault: 'Keep change and cost connected',
      bodyKey: 'guide.moc.commercial.body',
      bodyDefault:
        'A change request controls the decision; it is not the priced instruction itself. Approved changes flow on to Variations and Change Orders, where the priced commercial record lives. Linked records appear on the request so the change-to-cost trail never drifts apart.',
    },
  ],
  ctaKey: 'guide.moc.cta',
  ctaDefault: 'Raise your first change request',
};
