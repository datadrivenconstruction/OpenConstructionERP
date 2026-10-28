// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// reportingGuide - "How it works" content for the Reporting Dashboards module.
// Consumed by <ModuleGuideButton content={reportingGuide} /> on ReportingPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const reportingGuide: ModuleGuideContent = {
  titleKey: 'guide.reporting.title',
  titleDefault: 'Reporting Dashboards',
  introKey: 'guide.reporting.intro',
  introDefault:
    'Reporting Dashboards turn live project data into role-based KPI views, one project at a time. Use it to check the health of a project at a glance: cost and schedule performance, budget, open items, safety and finance.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.reporting.roles.title',
      titleDefault: 'One dashboard per role',
      bodyKey: 'guide.reporting.roles.body',
      bodyDefault:
        'The tabs across the top each frame the same project for a different audience: Executive for the portfolio, Project Manager for delivery, Estimator for cost, Site Engineer for safety and schedule, and Finance for the money. Switch tabs to see the metrics that matter to that role.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.reporting.executive.title',
      titleDefault: 'The Executive view',
      bodyKey: 'guide.reporting.executive.body',
      bodyDefault:
        'Executive needs no project selected. It lists every project with its status and KPI traffic lights, plus portfolio totals such as active projects and value grouped by currency. Click any row to make that project active and jump straight to its Project Manager dashboard.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.reporting.kpis.title',
      titleDefault: 'Live KPIs and traffic lights',
      bodyKey: 'guide.reporting.kpis.body',
      bodyDefault:
        'Each project is scored on cost (CPI), schedule (SPI), budget consumed and schedule progress, shown as green, amber or red. A dash is not an error: it simply means the project has no cost snapshot yet, so those figures are not measured.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.reporting.project_tabs.title',
      titleDefault: 'Project-scoped tabs',
      bodyKey: 'guide.reporting.project_tabs.body',
      bodyDefault:
        'The Project Manager, Estimator, Site Engineer and Finance tabs each need an active project. They pull live stats for that project, open RFIs and overdue tasks, BOQ totals, safety incidents, finance budget and overdue amounts. If none is selected, pick one from the inline project picker.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.reporting.reports.title',
      titleDefault: 'Report templates and documents',
      bodyKey: 'guide.reporting.reports.body',
      bodyDefault:
        'The Reports tab lists the report templates and the documents already generated for the active project. Use it to see what is available and what has been produced. For downloadable PDF and Excel files across the workspace, head to the Reports area.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.reporting.refresh.title',
      titleDefault: 'Recalculate and where to go next',
      bodyKey: 'guide.reporting.refresh.body',
      bodyDefault:
        'Managers can use Recalculate KPIs to queue a fresh snapshot for every project; the dashboard updates as the figures land. This module covers one project at a time, so for numbers that span every project use Analytics instead.',
    },
  ],
  ctaKey: 'guide.reporting.cta',
  ctaDefault: 'Explore your dashboards',
};
