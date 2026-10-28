// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// valueGuide - "How it works" content for the Value Realized dashboard.
// Consumed by <ModuleGuideButton content={valueGuide} /> on ValueDashboardPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too. No spotlight
// selectors are set because the page exposes no stable data-testid hooks, so
// each card renders centred.

import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

export const valueGuide: ModuleGuideContent = {
  titleKey: 'guide.value.title',
  titleDefault: 'Value Realized',
  introKey: 'guide.value.intro',
  introDefault:
    'Value Realized turns figures the platform already computes into one defensible view of what disciplined, assisted delivery has bought on your own data. Read it top to bottom: the headline numbers, the evidence behind them, and how your projects compare.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.value.scope.title',
      titleDefault: 'Project or portfolio',
      bodyKey: 'guide.value.scope.body',
      bodyDefault:
        'Start by choosing the scope at the top. This project shows the value case for the project in context; Portfolio rolls the same figures up across every project you can see. The tabs below follow your choice, so you can present one job or the whole book of work from the same screen.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.value.headline.title',
      titleDefault: 'The four headline numbers',
      bodyKey: 'guide.value.headline.body',
      bodyDefault:
        'The Value summary leads with four tiles: the budget exposure approved changes now control rather than discovering late, the cost you recovered with your recovery rate, the admin hours assisted actions gave back, and a documented dispute-risk-reduction proxy. Each tile carries a confidence badge, so a thin-evidence number is never dressed up as a firm one.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.value.currency.title',
      titleDefault: 'Money, kept honest',
      bodyKey: 'guide.value.currency.body',
      bodyDefault:
        'Below the tiles, a per-currency table breaks the value down without ever blending currencies. Each row keeps its own exposure, chargeable, recovered, rate and managed schedule days, and the headline figures use the project primary currency. Money arrives as exact values and is shown as is, never rounded into something it is not.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.value.checklist.title',
      titleDefault: 'Getting started checklist',
      bodyKey: 'guide.value.checklist.body',
      bodyDefault:
        'Getting started is a role-scoped path to first value. Pick a role and the steps are marked done from what the project actually holds: a bill of quantities, a takeoff, a routed approval, a logged change, an AI run and its recorded verdict, an assembled evidence pack. The adoption score weights each step by how much value it carries, and Do next points at the highest-value gap.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.value.benchmark.title',
      titleDefault: 'Benchmarks on your own data',
      bodyKey: 'guide.value.benchmark.body',
      bodyDefault:
        'Adoption benchmark contrasts your high- and low-adoption projects on outcomes like recovery rate, overrun and change cycle time, and flags which group each metric favours. Regional benchmarks show the spread of cost overrun or recovery rate from min to max across your projects, optionally narrowed to one region. A comparison is only as strong as its smaller cohort.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.value.case.title',
      titleDefault: 'Share the value case',
      bodyKey: 'guide.value.case.body',
      bodyDefault:
        'Value case prints the page into a clean report you can hand to a client or sponsor. In project scope it also records that you generated the report, which credits the matching step on the Getting started checklist. Admins get a Hours-saved factors editor to tune the minute factors so the admin-hours figure reflects your firm real effort.',
    },
  ],
  ctaKey: 'guide.value.cta',
  ctaDefault: 'Open your value summary',
};
