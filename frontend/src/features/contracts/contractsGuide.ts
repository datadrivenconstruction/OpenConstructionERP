// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// contractsGuide - "How it works" content for the Contracts module.
// Consumed by <ModuleGuideButton content={contractsGuide} /> on ContractsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const contractsGuide: ModuleGuideContent = {
  titleKey: 'guide.contracts.title',
  titleDefault: 'Contracts',
  introKey: 'guide.contracts.intro',
  introDefault:
    'Contracts is where you manage each commercial agreement on the project from signing through to the final account. Set up the contract sum, retention and schedule of values once, then bill the work with progress claims so what you signed and what you owe never drift apart.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.contracts.types.title',
      titleDefault: 'Type-aware contracts',
      bodyKey: 'guide.contracts.types.body',
      bodyDefault:
        'Click New Contract and pick a type: lump sum, GMP, cost plus, T&M, unit price, design build, remeasurement or a combination. The type shapes how the value is built up and how claims are measured, so choose the one that matches the agreement you signed.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.contracts.sov.title',
      titleDefault: 'Schedule of values and retention',
      bodyKey: 'guide.contracts.sov.body',
      bodyDefault:
        'Each contract carries a schedule of values that breaks the contract sum into billable line items, plus a retention percent and a retention release event. These drive every progress claim, so the gross, retention held and net due always reconcile back to the contract.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.contracts.lifecycle.title',
      titleDefault: 'Contract lifecycle',
      bodyKey: 'guide.contracts.lifecycle.body',
      bodyDefault:
        'A contract starts as a draft. Sign it to make it active, then suspend and resume it as needed, and close or terminate it at the end. Clone is always available to spin up a fresh draft, which is handy for a renewal or a similar package.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.contracts.claims.title',
      titleDefault: 'Progress claims',
      bodyKey: 'guide.contracts.claims.body',
      bodyDefault:
        'The Progress Claims tab bills the work period by period. Each claim shows its gross, retention and net due, and moves through a clear workflow: draft, submit, approve or reject, certify, then mark paid. Approved claims push their net due into Finance.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.contracts.final_accounts.title',
      titleDefault: 'Final accounts',
      bodyKey: 'guide.contracts.final_accounts.body',
      bodyDefault:
        'When a contract is closed it lands on the Final Accounts tab so you can settle it. The contract dashboard tracks total value, paid to date, retention held and outstanding, giving you the running picture you need to agree the final figure.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.contracts.connections.title',
      titleDefault: 'Connected across the platform',
      bodyKey: 'guide.contracts.connections.body',
      bodyDefault:
        'Contracts do not sit alone. Variations adjust the contract sum mid-flight, subcontractor contracts link back to the counterparty record, and certified claims flow into Finance, so the commercial position stays consistent everywhere.',
    },
  ],
  ctaKey: 'guide.contracts.cta',
  ctaDefault: 'Create your first contract',
};
