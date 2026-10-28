// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - per-module gap-fill: Earned Value (EVM).
// A sub-panel of the 4D Schedule (host route /schedule), also surfaced by the
// 5D Cost Model. See ../../types.ts for the ModuleExplanation shape and the key
// convention. English defaults live inline; translators fill other locales.

import type { ModuleExplanation } from '../../types';

export const fullEvmModules: ModuleExplanation[] = [
  {
    id: 'full_evm',
    route: '/schedule',
    icon: 'BarChart3',
    category: 'cost_control',
    keywords:
      'earned value evm pv ev ac bac spi cpi eac etc vac schedule variance cost variance forecast at completion bcws bcwp performance index',
    titleKey: 'howto.full_evm.title',
    titleDefault: 'Earned Value (EVM)',
    summaryKey: 'howto.full_evm.summary',
    summaryDefault:
      'See whether the job is ahead or behind on cost and time, with SPI, CPI and a forecast final cost.',
    whatKey: 'howto.full_evm.what',
    whatDefault:
      'Earned Value (EVM) is a view inside the 4D Schedule that turns progress and spend into one clear performance picture. It compares the value of the work you planned (PV), the value of the work actually done (EV) and what it cost (AC) at a data date, then derives the SPI and CPI indices and forecasts the final cost. The same panel is also surfaced by the 5D Cost Model.',
    how: [
      {
        key: 'howto.full_evm.how.1',
        default: 'Open a schedule on the 4D Schedule page and switch the view to EVM.',
      },
      {
        key: 'howto.full_evm.how.2',
        default:
          'Cost-load the schedule first: generate activities from a BOQ, or set planned and actual cost on activities, so PV, EV and AC have numbers to work with.',
      },
      {
        key: 'howto.full_evm.how.3',
        default:
          'Read PV, EV, AC and BAC to see the budgeted work scheduled, the work performed, the cost incurred so far and the total budget.',
      },
      {
        key: 'howto.full_evm.how.4',
        default:
          'Check SPI and CPI: above 1.0 is ahead or under budget, below 1.0 is behind or over, with the schedule and cost variances shown beside each.',
      },
      {
        key: 'howto.full_evm.how.5',
        default:
          'Read the forecast block for EAC, ETC and VAC to project the final cost if current efficiency holds; a negative VAC flags a likely overrun.',
      },
    ],
    tips: [
      {
        key: 'howto.full_evm.tip.1',
        default:
          'EVM needs a cost-loaded schedule. If the panel shows no numbers, add planned and actual cost on activities, or generate them from a BOQ, first.',
      },
      {
        key: 'howto.full_evm.tip.2',
        default:
          'EAC uses the CPI method (budget divided by CPI), so it assumes today efficiency holds to the end. A poor CPI early on is an early warning, not the final verdict.',
      },
    ],
    whenKey: 'howto.full_evm.when',
    whenDefault:
      'Use it at each progress update to catch cost or schedule slippage early, while there is still time to recover.',
  },
];
