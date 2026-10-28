// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// subcontractorsGuide - "How it works" content for the Subcontractors module.
// Consumed by <ModuleGuideButton content={subcontractorsGuide} /> on
// SubcontractorsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const subcontractorsGuide: ModuleGuideContent = {
  titleKey: 'guide.subcontractors.title',
  titleDefault: 'Subcontractors',
  introKey: 'guide.subcontractors.intro',
  introDefault:
    'This is the register for your supply chain. Keep each firm here with its prequalification, insurance and certificate status, subcontract scopes, payment applications, retention and performance ratings, so you only ever award and pay companies that are actually qualified.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.subcontractors.register.title',
      titleDefault: 'The subcontractor register',
      bodyKey: 'guide.subcontractors.register.body',
      bodyDefault:
        'Click New Subcontractor to add a firm with its legal name, trades, tax ID and country. Each row shows the prequalification status, an insurance traffic light, the performance rating and a blocked badge at a glance. Use the search box and status filter to find a company fast, then click a row to open its full detail drawer.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.subcontractors.prequal.title',
      titleDefault: 'Prequalify before you award',
      bodyKey: 'guide.subcontractors.prequal.body',
      bodyDefault:
        'Open a firm and run Prequalify to score it against the questionnaire. The status of pending, approved, suspended or rejected drives an award eligibility gate, so only an approved subcontractor can be invited to a bid package or put on a subcontract. You can re-run the assessment at any time to refresh the score.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.subcontractors.scope.title',
      titleDefault: 'Scope and agreements',
      bodyKey: 'guide.subcontractors.scope.body',
      bodyDefault:
        'The Scope tab lists the subcontract agreements that link a firm to specific projects, each with its value, dates, retention percent and work packages with completion progress. From the drawer you can jump straight to the matching contract or invite the firm to the partner portal.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.subcontractors.payments.title',
      titleDefault: 'Payments, waivers and retention',
      bodyKey: 'guide.subcontractors.payments.body',
      bodyDefault:
        'The Payments tab tracks each payment application from submitted through foreman and finance approval to paid, with gross and net amounts. Turn on Require signed lien waiver to hold finance approval and mark-paid until a valid waiver covering the net amount is on file. The Retention tab keeps the running accrued, released and balance figures.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.subcontractors.ratings.title',
      titleDefault: 'Performance ratings',
      bodyKey: 'guide.subcontractors.ratings.body',
      bodyDefault:
        'The Ratings tab rolls up a monthly scorecard from quality NCRs, safety incidents and schedule slips, broken out by quality, HSE, schedule and cost. Use Recompute this month to refresh the current period, and follow the trace links to see the source registers behind each score.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.subcontractors.compliance.title',
      titleDefault: 'Compliance and blocking',
      bodyKey: 'guide.subcontractors.compliance.body',
      bodyDefault:
        'Certificates and insurance are flagged red, amber or green by their expiry, and a compliance banner warns when something has lapsed. Block a firm with a reason to stop awards and payments outright, and Unblock once the issue is resolved.',
    },
  ],
  ctaKey: 'guide.subcontractors.cta',
  ctaDefault: 'Add your first subcontractor',
};
