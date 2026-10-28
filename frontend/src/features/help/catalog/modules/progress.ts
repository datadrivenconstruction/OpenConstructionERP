// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog (gap-fill) - Schedule Progress.
// Sub-panel of the 4D Schedule page, reached via the Progress tab, so the
// hub card points at the host route /schedule. See ../../types.ts for the
// ModuleExplanation shape and the key convention.

import type { ModuleExplanation } from '../../types';

export const scheduleProgressModules: ModuleExplanation[] = [
  {
    id: 'schedule-progress',
    route: '/schedule',
    icon: 'Gauge',
    category: 'scheduling',
    keywords:
      'progress percent complete earned value planned value pv bac data date duration units physical steps weighted milestone suspend resume remaining duration progress update evm rigor',
    titleKey: 'howto.schedule-progress.title',
    titleDefault: 'Schedule Progress',
    summaryKey: 'howto.schedule-progress.summary',
    summaryDefault:
      'Measure activity progress precisely and watch planned value move with the data date.',
    whatKey: 'howto.schedule-progress.what',
    whatDefault:
      'Schedule Progress is the Progress tab on the 4D Schedule. It makes percent complete mean something exact: choose how each activity is measured (by duration, by installed units, or by physical work with weighted steps), suspend and resume work with a reason, and read a live planned value that is time-phased to your data date instead of sitting frozen at the full budget. It warns you before a measurement choice would distort earned value.',
    how: [
      {
        key: 'howto.schedule-progress.how.1',
        default: 'Open the 4D Schedule and switch to the Progress tab.',
      },
      {
        key: 'howto.schedule-progress.how.2',
        default:
          'Set a data date in the live planned value header to preview planned value against budget at completion, then press Advance to refresh the earned-value snapshot.',
      },
      {
        key: 'howto.schedule-progress.how.3',
        default:
          'Pick an activity and choose its percent-complete method: Duration, Units or Physical.',
      },
      {
        key: 'howto.schedule-progress.how.4',
        default:
          'Enter progress the way that fits: drag the duration slider, type installed and budgeted units for a derived percent, or set a physical percent with remaining days.',
      },
      {
        key: 'howto.schedule-progress.how.5',
        default:
          'For physical work, add weighted steps with a name, weight, percent and milestone flag so the activity percent rolls up from its parts.',
      },
      {
        key: 'howto.schedule-progress.how.6',
        default:
          'Suspend an activity with a reason to freeze its remaining duration, and resume it when work restarts.',
      },
    ],
    tips: [
      {
        key: 'howto.schedule-progress.tip.1',
        default:
          'Hover a method before you pick it: an amber note flags when that choice would distort earned value, for example Units with no budgeted quantity.',
      },
      {
        key: 'howto.schedule-progress.tip.2',
        default:
          'Time-phased planned value moves as you advance the data date, so progress is judged against what was planned by today, not the whole budget.',
      },
    ],
    whenKey: 'howto.schedule-progress.when',
    whenDefault:
      'Use it at each progress update or data date to record where every activity really stands and keep earned value honest.',
  },
];
