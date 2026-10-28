// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the Project Intelligence / Estimation
// Dashboard module. Co-located with the feature and consumed by
// <ModuleGuideButton content={project_intelligenceGuide} /> on
// ProjectIntelligencePage.
//
// i18n: every key carries its inline English defaultValue. The keys are not
// in en.ts, the inline defaults are the English source; their translations
// live in the other locale files, so a changed default needs its translations
// redone too. Key prefix: guide.project_intelligence.*

import type { ModuleGuideContent } from '@/shared/ui';

export const project_intelligenceGuide: ModuleGuideContent = {
  titleKey: 'guide.project_intelligence.title',
  titleDefault: 'Estimation Dashboard',
  introKey: 'guide.project_intelligence.intro',
  introDefault:
    'This dashboard reads your live project (BOQ, cost model, schedule and risk) and grades how ready the estimate is to go out. It does not store its own numbers. You make it better by keeping the underlying screens up to date and by setting a scope baseline here.',
  sections: [
    {
      icon: 'Lightbulb',
      titleKey: 'guide.project_intelligence.readiness.title',
      titleDefault: 'Readiness score and grade',
      bodyKey: 'guide.project_intelligence.readiness.body',
      bodyDefault:
        'The ring gives one A to F grade for the whole estimate. It is a weighted blend: BOQ 40 percent, Cost Model 30 percent, Validation 20 percent, Risk 10 percent. A low grade means one of those areas needs attention, not that the dashboard is broken.',
      spotlightSelector: '[data-testid="kpi-card-variance"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.project_intelligence.gaps.title',
      titleDefault: 'Critical gaps are your to-do list',
      bodyKey: 'guide.project_intelligence.gaps.body',
      bodyDefault:
        'Critical Gaps lists the fastest ways to raise the grade, sorted by impact. Where prices are missing it shows the rough cost uncertainty in money. Each gap links straight to the screen that fixes it, usually the BOQ editor or Validation.',
      spotlightSelector: '[data-testid="pi-dollar-impact"]',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.project_intelligence.drivers.title',
      titleDefault: 'Top cost drivers and rollups',
      bodyKey: 'guide.project_intelligence.drivers.body',
      bodyDefault:
        'The Cost drivers widget is a Pareto of your five biggest line items by total cost, so you know where the money sits. The other widgets roll the same BOQ and bid data up by phase and by vendor. Focus your review effort on the tallest bars first.',
      spotlightSelector: '[data-testid="pi-widget-cost-drivers"]',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.project_intelligence.anomalies.title',
      titleDefault: 'Anomaly flags',
      bodyKey: 'guide.project_intelligence.anomalies.body',
      bodyDefault:
        'Real-time validation scans the BOQ for outlier rates, sudden price jumps and format problems such as a missing unit rate. Red is an error, amber is a warning. Open the flagged position in the BOQ editor and correct it, then refresh to clear the flag.',
      spotlightSelector: '[data-testid="pi-widget-validation"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.project_intelligence.baseline.title',
      titleDefault: 'Set a scope baseline',
      bodyKey: 'guide.project_intelligence.baseline.body',
      bodyDefault:
        'This is the one thing you enter here. Click Set baseline to freeze the current BOQ line count as your reference scope. After that, Scope coverage shows creep (lines added) or de-scoping (lines removed) against that frozen number.',
      spotlightSelector: '[data-testid="pi-set-baseline"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.project_intelligence.refresh.title',
      titleDefault: 'Refresh, roles and forecasts',
      bodyKey: 'guide.project_intelligence.refresh.body',
      bodyDefault:
        'Figures refresh roughly every 60 seconds, or press Refresh to recompute now after editing the BOQ. Switch the View as role to reframe the advisor for an estimator, manager or explorer. The Predictive Forecast section raises a banner when a cost or schedule threshold is breached.',
      spotlightSelector: '[data-testid="pi-refresh-button"]',
    },
  ],
  ctaKey: 'guide.project_intelligence.cta',
  ctaDefault: 'Got it',
};
