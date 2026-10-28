// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog entry for the Value Realized dashboard.
//
// Authored as a standalone per-module file under ./catalog/modules/*.ts; the
// index globs this folder eagerly, so no edit to moduleExplanations.ts is
// needed. Every string is an i18n key with its inline English default, read via
// t(key, { defaultValue }); the defaults are the source copy and translators
// fill the other locales later.

import type { ModuleExplanation } from '../../types';

export const valueModules: ModuleExplanation[] = [
  {
    id: 'value',
    route: '/value',
    icon: 'TrendingUp',
    category: 'controls',
    keywords:
      'value realized roi return on investment payback exposure managed cost recovered recovery rate admin hours saved dispute risk adoption benchmark overrun regional confidence value case portfolio',
    titleKey: 'howto.value.title',
    titleDefault: 'Value Realized',
    summaryKey: 'howto.value.summary',
    summaryDefault:
      'The measurable value the platform has delivered on the project, each headline carrying its own confidence.',
    whatKey: 'howto.value.what',
    whatDefault:
      'Value Realized composes figures the platform already computes into one defensible "what has this bought us" view. The summary shows the budget exposure approved changes now control rather than discovering late, the cost you recovered and your recovery rate, the admin hours assisted actions gave back, and a documented dispute-risk-reduction proxy. Every number carries a confidence label, currencies are never blended, and you can scope the whole view to one project or the whole portfolio.',
    how: [
      {
        key: 'howto.value.how.1',
        default:
          'Pick the scope at the top: This project, or the whole Portfolio across every project you can see.',
      },
      {
        key: 'howto.value.how.2',
        default:
          'On Value summary, read the four headline tiles (exposure managed, cost recovered with its recovery rate, admin hours saved, and dispute-risk reduction), each with a confidence badge, plus the per-currency breakdown that never blends currencies.',
      },
      {
        key: 'howto.value.how.3',
        default:
          'Open Getting started, choose a role, and work the checklist: each step flips to done from what the project actually holds (a bill of quantities, a takeoff, a routed approval, a logged change, an AI run and its verdict, an evidence pack), and "Do next" points at the highest-value gap.',
      },
      {
        key: 'howto.value.how.4',
        default:
          'Use Adoption benchmark to contrast your high- and low-adoption projects on outcomes like recovery rate, overrun and change cycle time, and see which group each metric favours.',
      },
      {
        key: 'howto.value.how.5',
        default:
          'Use Regional benchmarks to see the spread of cost overrun or recovery rate from min to max across your own projects, optionally narrowed to one region.',
      },
      {
        key: 'howto.value.how.6',
        default:
          'Click Value case to print a shareable report; in project scope this also records the report so the Getting started checklist credits it.',
      },
    ],
    tips: [
      {
        key: 'howto.value.tip.1',
        default:
          'Every headline carries a confidence label, so a thin-evidence number is never dressed up as a firm one; a small cohort weakens a benchmark the same way.',
      },
      {
        key: 'howto.value.tip.2',
        default:
          'Currencies are kept apart and never blended; the headline figures use the project primary currency.',
      },
      {
        key: 'howto.value.tip.3',
        default:
          'Admins can tune the admin-hours-saved minute factors from the Hours-saved factors button so the hours reflect your firm real effort.',
      },
    ],
    whenKey: 'howto.value.when',
    whenDefault:
      'Use it to show stakeholders the measurable value disciplined, assisted delivery has bought on your own data, and to see which projects get the most out of the platform.',
  },
];
