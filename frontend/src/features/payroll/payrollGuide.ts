// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// payrollGuide - "How it works" content for the Payroll module.
// Consumed by <ModuleGuideButton content={payrollGuide} /> on PayrollPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const payrollGuide: ModuleGuideContent = {
  titleKey: 'guide.payroll.title',
  titleDefault: 'Payroll',
  introKey: 'guide.payroll.intro',
  introDefault:
    'Payroll turns the hours logged in field reports into priced pay batches, then walks each batch through approval and into the cost model. Use it at the end of a pay period to roll labour into a single reviewable run before any money moves.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.payroll.generate.title',
      titleDefault: 'Generate a draft batch',
      bodyKey: 'guide.payroll.generate.body',
      bodyDefault:
        'Click Generate draft batch to aggregate the hours recorded in field reports into pay entries, one per worker. Each entry carries the hours, the pay rate from Resources and Crew, and the resulting amount, so a batch is a complete picture of the period before you review it.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.payroll.batches.title',
      titleDefault: 'Pay batches and entries',
      bodyKey: 'guide.payroll.batches.body',
      bodyDefault:
        'The left panel lists every pay batch with its period, status, total hours and total amount. Select a batch to open its entries on the right, where each row shows the worker, work date, hours, rate, gross, deductions and net. Worker names link straight to their resource record.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.payroll.deductions.title',
      titleDefault: 'Deductions and net pay',
      bodyKey: 'guide.payroll.deductions.body',
      bodyDefault:
        'Each payslip starts at gross pay (hours times rate). Expand a row to add deduction lines, a tax, social, pension or other withholding entered either as a fixed amount or a percentage of the gross. Net pay is gross minus the deductions and updates as you edit. The platform ships no tax tables, so the rates are yours to enter and confirm. Deductions are editable while the batch is draft or submitted and lock once it is approved. Gross still drives the labour cost posted to the budget and ledger; net is what each worker takes home.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.payroll.lifecycle.title',
      titleDefault: 'Submit, finalize and post',
      bodyKey: 'guide.payroll.lifecycle.body',
      bodyDefault:
        'A batch moves through a clear lifecycle: draft, submitted, approved, then posted. Submit for approval sends it for review without posting any cost, Finalize approves it and posts the labour cost to the project budget, and Post to ledger writes the payroll journal to the finance ledger. Each step is confirmed and the later ones cannot be undone.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.payroll.reconcile.title',
      titleDefault: 'Reconcile against the field records',
      bodyKey: 'guide.payroll.reconcile.body',
      bodyDefault:
        'Reconcile compares the hours in the batch against the underlying field reports, worker by worker and day by day. It flags any rows where the totals differ so you can resolve discrepancies before approving, and confirms the batch is balanced once everything matches.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.payroll.labour_cost.title',
      titleDefault: 'Labour cost in the model',
      bodyKey: 'guide.payroll.labour_cost.body',
      bodyDefault:
        'The labour cost card at the top shows the total cost posted from approved batches across the recorded hours, surfaced next to the 5D cost model. This keeps the running labour spend visible and ties payroll directly to the project budget.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.payroll.export.title',
      titleDefault: 'Export the run',
      bodyKey: 'guide.payroll.export.body',
      bodyDefault:
        'Export CSV or JSON to hand a finished batch to an external payroll provider or accounting system. The export carries the full set of entries with gross, deductions and net per worker, plus the batch totals, so the run can be paid out and audited outside the platform.',
    },
  ],
  ctaKey: 'guide.payroll.cta',
  ctaDefault: 'Generate your first batch',
};
