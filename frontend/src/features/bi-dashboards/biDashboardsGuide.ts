// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// biDashboardsGuide - "How it works" content for the BI Dashboards module.
// Consumed by <ModuleGuideButton content={biDashboardsGuide} /> on
// BIDashboardsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const biDashboardsGuide: ModuleGuideContent = {
  titleKey: 'guide.bi_dashboards.title',
  titleDefault: 'BI Dashboards',
  introKey: 'guide.bi_dashboards.intro',
  introDefault:
    'BI Dashboards brings your KPIs, executive dashboards, scheduled reports and alert rules together in one place. Use it to track project health live, deliver reports to stakeholders on a cadence, and get notified the moment a metric crosses a threshold.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.bi_dashboards.tabs.title',
      titleDefault: 'Five tabs, one workspace',
      bodyKey: 'guide.bi_dashboards.tabs.body',
      bodyDefault:
        'The module is organised into five tabs: My Dashboards for boards of widgets, KPIs for the metric library, Reports for exportable documents, Schedules for automatic delivery, and Alerts for threshold rules. Every KPI is computed live from your project data, so the numbers stay current without manual updates.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.bi_dashboards.starter.title',
      titleDefault: 'Start with the starter pack',
      bodyKey: 'guide.bi_dashboards.starter.body',
      bodyDefault:
        'On a fresh tenant the fastest start is the starter pack. One click installs five role-based dashboards (CEO, CFO, PM, Site, Safety), system KPIs with twelve weeks of history, reports, schedules and alert rules. It is idempotent, so re-running only adds what is missing.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.bi_dashboards.dashboards.title',
      titleDefault: 'Dashboards and widgets',
      bodyKey: 'guide.bi_dashboards.dashboards.body',
      bodyDefault:
        'A dashboard is a named board of widgets scoped to you, a role, a project or the whole organisation. Open any card to render its widgets with live values, or use New Dashboard to build your own from the KPI library.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.bi_dashboards.kpis.title',
      titleDefault: 'The KPI library',
      bodyKey: 'guide.bi_dashboards.kpis.body',
      bodyDefault:
        'Each KPI card shows its latest value, a sparkline of recent periods, the period-over-period change and the source modules that feed it. Click Compute to calculate it now from live data and save a snapshot, or Source records to drill into the underlying rows behind the number. New KPI defines one of your own: pick the records, the aggregation, the field and any filters, and the platform computes it. There is no formula code to write, and a definition that is accepted is one that will produce a number, because it is checked against what the data actually holds before it is saved.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.bi_dashboards.reports.title',
      titleDefault: 'Reports you can export',
      bodyKey: 'guide.bi_dashboards.reports.body',
      bodyDefault:
        'Reports turn your data into a PDF, Excel, CSV or JSON document. Define one with New Report, then use Run now to generate it on demand and Download to open the last generated file.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.bi_dashboards.delivery.title',
      titleDefault: 'Schedules and alerts',
      bodyKey: 'guide.bi_dashboards.delivery.body',
      bodyDefault:
        'Attach a schedule to any report to deliver it to recipients on a daily, weekly, monthly or quarterly cadence. Alerts watch a KPI and notify your team when it crosses a threshold; use Run checks now to evaluate every enabled rule immediately.',
    },
  ],
  ctaKey: 'guide.bi_dashboards.cta',
  ctaDefault: 'Install the starter pack',
};
