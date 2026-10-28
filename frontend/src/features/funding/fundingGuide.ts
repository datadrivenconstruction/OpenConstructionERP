// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fundingGuide - "How it works" content for the Public Funding module.
// Consumed by <ModuleGuideButton content={fundingGuide} /> on FundingPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fundingGuide: ModuleGuideContent = {
  titleKey: 'guide.funding.title',
  titleDefault: 'Public funding',
  introKey: 'guide.funding.intro',
  introDefault:
    'A project paid for partly with public money runs a second project beside the building one, with its own deadlines and its own definition of what a cost is. This module is that second project: which programme, what it awarded, what has been drawn, and what has to be shown afterwards.',
  sections: [
    {
      icon: 'Landmark',
      titleKey: 'guide.funding.programme.title',
      titleDefault: 'Start from the programme, not the application',
      bodyKey: 'guide.funding.programme.body',
      bodyDefault:
        'A programme carries the terms every later date and figure is measured against: the funding rate, the share you must carry yourself, how long you have to report, how long records must be kept. Most entries arrive with a country pack and need no typing. Check the last verified date before you rely on one, because funding terms change every budget year.',
    },
    {
      icon: 'CalendarClock',
      titleKey: 'guide.funding.before_start.title',
      titleDefault: 'File before anything starts on site',
      bodyKey: 'guide.funding.before_start.body',
      bodyDefault:
        'This is the mistake that cannot be repaired. In most programmes work begun before the application was filed makes the whole measure unfundable, not just the early part, and no later approval fixes it. Record the date work starts and the date you filed, and the module will tell you if they are the wrong way round. If the authority permitted an early start in writing, record that permission too.',
    },
    {
      icon: 'SplitSquareHorizontal',
      titleKey: 'guide.funding.eligible.title',
      titleDefault: 'Separate what the programme will count',
      bodyKey: 'guide.funding.eligible.body',
      bodyDefault:
        'The gap between what a project costs and what a programme funds is not a percentage, it is a list of categories. Split the cost plan into allocations, mark each eligible, partly eligible or not, and say why. That reason is what you will be asked for, sometimes years later, and it is far cheaper to write down now.',
    },
    {
      icon: 'Banknote',
      titleKey: 'guide.funding.draw.title',
      titleDefault: 'Draw against real spending, inside the period',
      bodyKey: 'guide.funding.draw.body',
      bodyDefault:
        'Each draw claims a period, and every cost in it has to fall inside the window the award named. A draw that reaches past either end is usually paid first and reclaimed later, which is worse than being refused. Once money arrives, record the date: several programmes give you only weeks to spend it, and the module turns that into a dated reminder.',
    },
    {
      icon: 'FileCheck2',
      titleKey: 'guide.funding.proof.title',
      titleDefault: 'Show where it went',
      bodyKey: 'guide.funding.proof.body',
      bodyDefault:
        'Every award ends with an account of what was achieved and what it cost. The deadline is worked out from the programme terms the moment the award is recorded, so it is in the list from day one rather than arriving as a surprise. Submit what you have rather than waiting for it to be complete: an extension is usually granted on request and never granted after the date has passed.',
    },
    {
      icon: 'AlertTriangle',
      titleKey: 'guide.funding.cumulation.title',
      titleDefault: 'Watch what the grants add up to',
      bodyKey: 'guide.funding.cumulation.body',
      bodyDefault:
        'Public funding cumulates across programmes and across levels of government. Two applications that are each faultless can break a ceiling simply by existing together, and the ceiling that binds is the lowest one any of the programmes names. The project view adds them up for you and compares the total against that ceiling.',
    },
  ],
};
