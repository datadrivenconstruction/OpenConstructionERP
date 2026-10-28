// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// reportsGuide - "How it works" content for the Reports module.
// Consumed by <ModuleGuideButton content={reportsGuide} /> on ReportsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const reportsGuide: ModuleGuideContent = {
  titleKey: 'guide.reports.title',
  titleDefault: 'Reports',
  introKey: 'guide.reports.intro',
  introDefault:
    'Reports turns the live data in a project into a finished document you can hand over: a detailed BOQ, a cost breakdown, a GAEB tender file, validation results, a schedule summary and more. Use it when a client, authority or subcontractor needs a deliverable instead of a screenshot.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.reports.concept.title',
      titleDefault: 'What this module produces',
      bodyKey: 'guide.reports.concept.body',
      bodyDefault:
        'Each card on this page generates one report and downloads it as a file in the format your recipient expects: PDF, Excel, CSV, GAEB XML, HTML or plain text. The numbers are pulled straight from the BOQ, cost model, schedule and risk data, so what you send always matches what is on screen.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.reports.select.title',
      titleDefault: 'Pick a project and BOQ first',
      bodyKey: 'guide.reports.select.body',
      bodyDefault:
        'Choose the project from the selector in the top bar, then pick a BOQ from the dropdown on this page. BOQ-based reports such as the detailed BOQ and the GAEB export need a BOQ selected, while project-wide reports like cost, schedule and risk only need the project.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.reports.generate.title',
      titleDefault: 'Generate a report',
      bodyKey: 'guide.reports.generate.body',
      bodyDefault:
        'Click the format button on any card to build and download that report on the spot. The detailed BOQ exports to PDF or Excel, GAEB X83 is for tender exchange, and the cost, validation, schedule, 5D, tender comparison, change order, risk, cash flow and progress reports each download with one click.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.reports.builder.title',
      titleDefault: 'Custom report builder',
      bodyKey: 'guide.reports.builder.body',
      bodyDefault:
        'Open Configure Sections to assemble one combined HTML report from the parts you want: executive summary, budget vs actual, cost breakdown, BOQ detail, earned value, schedule and risk. Tick the sections you need and generate a single document tailored to the audience.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.reports.history.title',
      titleDefault: 'Recently generated reports',
      bodyKey: 'guide.reports.history.body',
      bodyDefault:
        'The history list at the bottom shows reports that were generated and stored for the selected project, so you can find and re-download an earlier deliverable without rebuilding it from scratch.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.reports.share.title',
      titleDefault: 'Hand it over',
      bodyKey: 'guide.reports.share.body',
      bodyDefault:
        'Every report downloads as a self-contained file you can attach to an email, upload to a portal or print. GAEB XML goes back into another estimating tool, Excel and CSV open in any spreadsheet, and the HTML and PDF reports are ready to read as they are.',
    },
  ],
  ctaKey: 'guide.reports.cta',
  ctaDefault: 'Generate a report',
};
