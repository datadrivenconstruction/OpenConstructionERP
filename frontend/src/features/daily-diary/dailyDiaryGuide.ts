// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// dailyDiaryGuide - "How it works" content for the Daily Site Diary module.
// Consumed by <ModuleGuideButton content={dailyDiaryGuide} /> on DailyDiaryPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const dailyDiaryGuide: ModuleGuideContent = {
  titleKey: 'guide.daily_diary.title',
  titleDefault: 'Daily Site Diary',
  introKey: 'guide.daily_diary.intro',
  introDefault:
    'The daily site diary is your contemporaneous record of what happened on site each day: weather, headcount, deliveries, events, photos and surveys. Open one per site day, fill it in as the day runs, then close and sign it so it stands as tamper-evident proof for delay claims and disputes.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.daily_diary.concept.title',
      titleDefault: 'One diary per site day',
      bodyKey: 'guide.daily_diary.concept.body',
      bodyDefault:
        'A diary is a single dated record for one project day, and the date is its identity. A diary moves through a lifecycle from open to closed to signed to archived, and you cannot open one further ahead than tomorrow because a diary is a record of a day that has happened, not a plan.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.daily_diary.tabs.title',
      titleDefault: 'Calendar, Today and Archive',
      bodyKey: 'guide.daily_diary.tabs.body',
      bodyDefault:
        'The Diaries tab is a month calendar: click a day with a diary to open it, or an empty day to start one. The Today tab is the working record for the selected day, and the Archive tab holds the signed, sealed diaries for the project.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.daily_diary.log.title',
      titleDefault: 'Log weather, workforce and entries',
      bodyKey: 'guide.daily_diary.log.body',
      bodyDefault:
        'On the day record, set the labour and equipment headcount and add diary entries such as deliveries, visitors and events. Weather can be fetched automatically from the project location or added by hand, and the headcount you log here flows into the labour roster used by Payroll.',
      spotlightSelector: '[data-testid="daily-diary-edit"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.daily_diary.evidence.title',
      titleDefault: 'Attach photos and surveys',
      bodyKey: 'guide.daily_diary.evidence.body',
      bodyDefault:
        'Upload site photos for the day and attach drone surveys or reality-capture scans to build a visual record. These assets are tied to the diary date and feed the site photo library, so the evidence stays linked to the day it belongs to.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.daily_diary.sign.title',
      titleDefault: 'Close, sign and seal',
      bodyKey: 'guide.daily_diary.sign.body',
      bodyDefault:
        'A readiness chip shows how complete the diary is and what is still missing before you sign. When the day is done, close it and sign it: a signed diary is sealed with a sha256 fingerprint so any later change is traceable. Unlocking a signed diary preserves the original signature so the integrity break is on record.',
      spotlightSelector: '[data-testid="daily-diary-export-pdf"]',
    },
    {
      icon: 'Send',
      titleKey: 'guide.daily_diary.export.title',
      titleDefault: 'Export and claim evidence',
      bodyKey: 'guide.daily_diary.export.body',
      bodyDefault:
        'Export any diary to PDF for the record, or build a hash-sealed SCL Protocol evidence bundle across a date range to support a delay claim. Signed diaries also feed schedule progress, so the daily record does more than sit in a file.',
      spotlightSelector: '[data-testid="daily-diary-scl-bundle"]',
    },
  ],
  ctaKey: 'guide.daily_diary.cta',
  ctaDefault: 'Open today’s diary',
};
