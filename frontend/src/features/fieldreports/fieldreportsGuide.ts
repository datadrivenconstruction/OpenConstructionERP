// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fieldreportsGuide - "How it works" content for the Field Reports module.
// Consumed by <ModuleGuideButton content={fieldreportsGuide} /> on
// FieldReportsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fieldreportsGuide: ModuleGuideContent = {
  titleKey: 'guide.fieldreports.title',
  titleDefault: 'Field Reports',
  introKey: 'guide.fieldreports.intro',
  introDefault:
    'Field reports are the structured daily record of life on site: weather, workforce, work performed, delays and safety. Capture one per day or per event, then take it from draft to approved so it becomes a defensible record you can export and roll up.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.fieldreports.types.title',
      titleDefault: 'Pick a report type',
      bodyKey: 'guide.fieldreports.types.body',
      bodyDefault:
        'Every report has a date and a type: daily, inspection, safety or concrete pour. The type frames what you log, and you can attach a saved template to add the extra fields a given report needs.',
    },
    {
      icon: 'Lightbulb',
      titleKey: 'guide.fieldreports.weather.title',
      titleDefault: 'Log weather and conditions',
      bodyKey: 'guide.fieldreports.weather.body',
      bodyDefault:
        'Record the weather condition, temperature, wind, precipitation and humidity for the day. Fill it by hand, or use the location button to pull live weather from your current position when the server has it configured.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.fieldreports.workforce.title',
      titleDefault: 'Record workforce and work done',
      bodyKey: 'guide.fieldreports.workforce.body',
      bodyDefault:
        'Add a line per trade with the number of workers and hours, then note the work performed, delays and delay hours, safety incidents, visitors, deliveries, equipment on site and materials used. The workforce lines total automatically and feed payroll and progress.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.fieldreports.workflow.title',
      titleDefault: 'Draft, submit, approve',
      bodyKey: 'guide.fieldreports.workflow.body',
      bodyDefault:
        'A new report starts as a draft you can keep editing. Submit it for review when it is ready, then approve it with a signature. Approval locks the report permanently, so it can no longer be edited.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.fieldreports.views.title',
      titleDefault: 'Calendar and list views',
      bodyKey: 'guide.fieldreports.views.body',
      bodyDefault:
        'Switch between a month calendar, where each day shows colour-coded status dots, and a filterable list by status and type. Click any day to open its report or start a new one for that date, and watch the summary cards tally totals and workforce hours.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.fieldreports.exchange.title',
      titleDefault: 'Templates, import and export',
      bodyKey: 'guide.fieldreports.exchange.body',
      bodyDefault:
        'Manage reusable templates to standardise what each report captures. Import reports in bulk from Excel or CSV using the download template, export the whole set to Excel, or download any single report as a PDF.',
    },
  ],
  ctaKey: 'guide.fieldreports.cta',
  ctaDefault: 'Create your first report',
};
