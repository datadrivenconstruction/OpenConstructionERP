// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// complianceDocsGuide - "How it works" content for the Compliance Documents
// module. Consumed by <ModuleGuideButton content={complianceDocsGuide} /> on
// CompliancePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const complianceDocsGuide: ModuleGuideContent = {
  titleKey: 'guide.compliance_docs.title',
  titleDefault: 'Compliance documents',
  introKey: 'guide.compliance_docs.intro',
  introDefault:
    'The compliance register keeps every project document that has an expiry date in one place: insurance policies, permits, bonds and certifications. Use it to know what is current, what is lapsing and what has run out, so nothing on site is left uncovered.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.compliance_docs.purpose.title',
      titleDefault: 'What you track here',
      bodyKey: 'guide.compliance_docs.purpose.body',
      bodyDefault:
        'Each record stands for one time-limited obligation tied to this project: general liability, workers comp, auto and umbrella insurance, building, electrical and plumbing permits, payment, performance and bid bonds, and safety or other certifications. Records are scoped to the open project, so open a project first.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.compliance_docs.add.title',
      titleDefault: 'Add a document',
      bodyKey: 'guide.compliance_docs.add.body',
      bodyDefault:
        'Click New document and pick a type, then give it a name and an expiry date. Capture the issuer, policy or permit number, coverage amount and currency, the effective date, and an optional attachment pulled from the project files. These details make the register an audit-ready record, not just a reminder list.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.compliance_docs.table.title',
      titleDefault: 'Read the register',
      bodyKey: 'guide.compliance_docs.table.body',
      bodyDefault:
        'The table lists each document with its type, expiry date, days left and a status pill. Rows are ordered by expiry date, soonest first, so whatever needs attention next sits at the top. The issuer shows next to the name for quick context.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.compliance_docs.status.title',
      titleDefault: 'Status at a glance',
      bodyKey: 'guide.compliance_docs.status.body',
      bodyDefault:
        'The colour-coded pill tells you where each document stands: green for active, amber for expiring soon, red for expired, and grey for cancelled or void. The days left figure is computed from the expiry date so the picture stays current without manual updates.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.compliance_docs.reminders.title',
      titleDefault: 'Expiry reminders',
      bodyKey: 'guide.compliance_docs.reminders.body',
      bodyDefault:
        'Set Notify days before on each document to choose how far ahead it flags as expiring soon. That lead time gives you room to renew a policy or pull a fresh permit before cover lapses and work has to stop.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.compliance_docs.filter.title',
      titleDefault: 'Filter the list',
      bodyKey: 'guide.compliance_docs.filter.body',
      bodyDefault:
        'Use the type and status dropdowns above the table to narrow the view, for example just expiring insurance or every expired permit. Clear a filter to return to the full register, and remove a document with the row action when it no longer applies.',
    },
  ],
  ctaKey: 'guide.compliance_docs.cta',
  ctaDefault: 'Add your first document',
};
