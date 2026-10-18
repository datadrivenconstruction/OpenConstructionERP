// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// analyticsGuide - "How it works" content for the Analytics module.
// Consumed by <ModuleGuideButton content={analyticsGuide} /> on AnalyticsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const analyticsGuide: ModuleGuideContent = {
  titleKey: 'guide.analytics.title',
  titleDefault: 'Analytics',
  introKey: 'guide.analytics.intro',
  introDefault:
    'Analytics rolls budget against actual cost across every project into one portfolio view, and its Performance tab benchmarks what your past projects actually achieved. Use it to see which jobs are over budget, and to ground the next estimate in your own measured history.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.analytics.overview.title',
      titleDefault: 'A portfolio-wide rollup',
      bodyKey: 'guide.analytics.overview.body',
      bodyDefault:
        'This page aggregates the budget and actual cost of all your projects into one place. The figures come straight from your projects and their cost data, so there is nothing to enter here. Create a project or import a cost database and it appears automatically.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.analytics.kpis.title',
      titleDefault: 'The headline KPI cards',
      bodyKey: 'guide.analytics.kpis.body',
      bodyDefault:
        'Four cards summarise the whole portfolio: total projects, total budget against actual spend, the overall variance, and how many projects are at risk because they are over budget. A positive variance is shown in green and an overrun in red.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.analytics.currency.title',
      titleDefault: 'Currencies stay separate',
      bodyKey: 'guide.analytics.currency.body',
      bodyDefault:
        'A EUR job is never blended with a USD one. When your projects span several currencies the totals break down per currency, each with its own figure and variance, so the headline numbers always make sense.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.analytics.compare.title',
      titleDefault: 'Compare projects in the table',
      bodyKey: 'guide.analytics.compare.body',
      bodyDefault:
        'The comparison table lists every project with its budget, actual, variance, variance percent and an on-budget or over-budget status. Click any column header to sort, click a row to open that project, or use the wallet button to jump straight to its Finance module.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.analytics.filter.title',
      titleDefault: 'Search, filter and chart',
      bodyKey: 'guide.analytics.filter.body',
      bodyDefault:
        'Narrow the table by searching for a project name or filtering by region and status. The budget breakdown chart below mirrors the rows in view, plotting planned against actual cost as bars so overruns are easy to spot.',
    },
    {
      icon: 'GraduationCap',
      titleKey: 'guide.analytics.perf.title',
      titleDefault: 'Historical performance: what your projects achieved',
      bodyKey: 'guide.analytics.perf.body',
      bodyDefault:
        'The Performance tab compares measured results across projects: labour hours per installed unit, cost per m², rates in past estimates and your own KPIs. Pick projects by name, client, region, type or status, or leave the selection empty to use every project you can open. Each project is one row and opens with a click. Save the selection and settings as a benchmark set to reuse it or share the definition with colleagues; everyone sees only the projects they may open.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.analytics.perf_stats.title',
      titleDefault: 'How the benchmark is computed',
      bodyKey: 'guide.analytics.perf_stats.body',
      bodyDefault:
        'A ratio is a sum over a sum: 420 hours over 290 m² is 1.45 h/m², not the average of the project ratios. The average of projects and the median are shown beside it, with the normal range P25 - P75, P10 - P90 from ten projects, the standard deviation and the spread. A group with fewer projects or records than the minimum you set is marked as not enough evidence. Missing data is shown as unavailable with its reason, never as zero.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.analytics.perf_units.title',
      titleDefault: 'Units, currencies and splits',
      bodyKey: 'guide.analytics.perf_units.body',
      bodyDefault:
        'm² and ft², m³ and yd³, kg, t and lb can be converted into one unit; different kinds of unit are never added. Enter a reporting currency to restate money with the FX rates in Settings: each converted row shows its original value and the rate used, and currencies without a rate stay apart. Split by client, region, project type, status, end year or a classification standard such as DIN 276 to get one block per value.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.analytics.perf_drill.title',
      titleDefault: 'Trace a value, check the data, export',
      bodyKey: 'guide.analytics.perf_drill.body',
      bodyDefault:
        'The list button on a row opens the records behind that value, each linked to its bill position; the totals match the value in the table. The data quality line shows how much of the selected work has hours booked to positions, reported progress and a classification. Compare KPIs puts up to eight KPIs side by side and exports them to CSV or Excel.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.analytics.perf_estimating.title',
      titleDefault: 'History while you estimate',
      bodyKey: 'guide.analytics.perf_estimating.body',
      bodyDefault:
        'The same figures appear where you estimate: the bill editor shows historical labour hours per unit for positions with the same classification code on your other projects, post-calculation shows what other projects achieved next to each feedback factor, and the conceptual estimate compares its cost per m² with the actual cost of completed projects. These are measured history, kept apart from market price ranges and from the accuracy band of an estimate class. Nothing is changed in an estimate automatically.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.analytics.export.title',
      titleDefault: 'Export the comparison',
      bodyKey: 'guide.analytics.export.body',
      bodyDefault:
        'Use Export CSV to download the full filtered comparison for a spreadsheet or a report. For the role-by-role KPI view switch to Reporting, and open Finance on any project to trace a figure back to its source.',
    },
  ],
  ctaKey: 'guide.analytics.cta',
  ctaDefault: 'Review your projects',
};
