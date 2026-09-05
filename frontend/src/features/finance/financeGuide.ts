// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// financeGuide - "How it works" content for the Finance module.
// Consumed by <ModuleGuideButton content={financeGuide} /> on FinancePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). These keys are NOT added to en.ts or any
// locale file; the inline defaults are the single source of truth.

import type { ModuleGuideContent } from '@/shared/ui';

export const financeGuide: ModuleGuideContent = {
  titleKey: 'guide.finance.title',
  titleDefault: 'Finance',
  introKey: 'guide.finance.intro',
  introDefault:
    'Finance is where you see what a project actually costs against what you budgeted. Track budget lines, invoices and payments in one place, then watch the variance and earned value so committed, actual and forecast sit side by side with the original budget.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.finance.budgets.title',
      titleDefault: 'Budgets by WBS category',
      bodyKey: 'guide.finance.budgets.body',
      bodyDefault:
        'The Budgets tab tracks each budget line against a WBS code and category, showing original, revised, committed, actual and forecast next to the variance. Variance is highlighted green when under budget and red when over. Add lines by hand, import them, or generate them from a locked BOQ on the 5D Cost Model page.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.finance.invoices.title',
      titleDefault: 'Payable and receivable invoices',
      bodyKey: 'guide.finance.invoices.body',
      bodyDefault:
        'The Invoices tab splits into payable (money you owe) and receivable (money owed to you). Create an invoice with its counterparty, dates, amount and line items, then move it through draft, pending, sent and paid. You can scan a paper invoice with the camera to prefill the form from the captured text.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.finance.payments.title',
      titleDefault: 'Payments against invoices',
      bodyKey: 'guide.finance.payments.body',
      bodyDefault:
        'The Payments tab is the ledger of money that has actually moved. Record a payment against an invoice with its date, amount and reference, and it rolls up into the Actual figure on the matching budget line. Payments are immutable entries, so a correction is posted as a refund rather than edited in place.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.finance.evm.title',
      titleDefault: 'Earned value dashboard',
      bodyKey: 'guide.finance.evm.body',
      bodyDefault:
        'The EVM Dashboard turns budget and actuals into cost and schedule performance. SPI above 1.0 means ahead of schedule and CPI above 1.0 means under budget, alongside the estimate at completion and variance at completion. Take a snapshot periodically to track how those trends move over time.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.finance.connectors.title',
      titleDefault: 'Connectors to external systems',
      bodyKey: 'guide.finance.connectors.body',
      bodyDefault:
        'The Connectors tab links Finance to your accounting or ERP system so records flow out without re-keying. Configure a connector with its credentials and direction, run it on demand, or set it to auto-push when invoices and payments change.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.finance.flow.title',
      titleDefault: 'Where the numbers come from',
      bodyKey: 'guide.finance.flow.body',
      bodyDefault:
        'Finance is the downstream of your estimate. Budgets pull straight from the BOQ estimate and the 5D cost model, commitments arrive from procurement, and the summary cards at the top show total budget, invoiced, receivable and remaining. When records span several currencies the totals are converted using the project exchange rates.',
    },
  ],
  ctaKey: 'guide.finance.cta',
  ctaDefault: 'Open the Budgets tab',
};
