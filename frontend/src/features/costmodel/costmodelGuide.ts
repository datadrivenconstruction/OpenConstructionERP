// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// costmodelGuide - "How it works" content for the 5D Cost Model module.
// Consumed by <ModuleGuideButton content={costmodelGuide} /> on CostModelPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const costmodelGuide: ModuleGuideContent = {
  titleKey: 'guide.costmodel.title',
  titleDefault: '5D Cost Model',
  introKey: 'guide.costmodel.intro',
  introDefault:
    'The 5D Cost Model turns a project BOQ estimate into a living cost control dashboard. Use it to track a project against its budget over time and to see where the money is really going, drawing on cost, schedule progress and finance data.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.costmodel.pick_project.title',
      titleDefault: 'Pick a project to control',
      bodyKey: 'guide.costmodel.pick_project.body',
      bodyDefault:
        'The cost model works one project at a time. Select a project from the list to open its 5D dashboard, or use View all projects to come back to the portfolio. It needs a project with a BOQ and a generated budget, so build the estimate first if the dashboard looks empty.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.costmodel.budget.title',
      titleDefault: 'Budget by category and line',
      bodyKey: 'guide.costmodel.budget.body',
      bodyDefault:
        'Budget lines are generated from your BOQ positions and grouped into categories such as material, labor, equipment and subcontractor. Each row tracks planned, committed, actual and forecast amounts with a spent percentage and variance, so an overrun shows up the moment it appears. Double-click a line to edit its amounts or set an overrun alert threshold.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.costmodel.evm.title',
      titleDefault: 'Earned Value Analysis',
      bodyKey: 'guide.costmodel.evm.body',
      bodyDefault:
        'Earned Value Management compares planned, earned and actual cost to score schedule and cost performance. SPI and CPI tell you if you are ahead or behind and over or under budget, while EAC, VAC and TCPI forecast the final cost and the efficiency needed to finish on budget. These figures refresh as cost, schedule progress and finance data change.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.costmodel.scurve.title',
      titleDefault: 'S-curve and cash flow',
      bodyKey: 'guide.costmodel.scurve.body',
      bodyDefault:
        'The cumulative S-curve plots planned value, earned value and actual cost over time so a widening gap between the lines is easy to spot. The cash flow view forecasts inflows and outflows period by period to help you manage project liquidity.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.costmodel.scenarios.title',
      titleDefault: 'What-if and Monte Carlo',
      bodyKey: 'guide.costmodel.scenarios.body',
      bodyDefault:
        'Run what-if scenarios by adjusting material, labor and duration assumptions to instantly see the impact on budget and forecast. Monte Carlo simulation runs many probabilistic iterations to give you P50, P80 and P95 cost confidence levels for risk-aware planning.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.costmodel.spine.title',
      titleDefault: 'Generate the cost spine',
      bodyKey: 'guide.costmodel.spine.body',
      bodyDefault:
        'The cost spine is the control-account structure that ties the BOQ, schedule and finance data together. Generate it to roll costs up through control accounts and cost lines, giving the EVM and budget figures a consistent backbone to report against.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.costmodel.payments.title',
      titleDefault: 'Invoices, retention and payment',
      bodyKey: 'guide.costmodel.payments.body',
      bodyDefault:
        'On the cost control page every supplier contract has payment terms: cumulative or incremental invoices, retention, and optional warranty retention, early payment discount and rounding. Each invoice shows the steps from its amount to the amount released for payment, measured work is kept apart from certified value, and the invoiced and paid figures land on the cost lines. A manager confirms each release and pays held retention back after its event.',
    },
  ],
  ctaKey: 'guide.costmodel.cta',
  ctaDefault: 'Select a project to begin',
};
