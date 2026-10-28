// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - per-module gap-fill entry for Cost recovery.
// Cost recovery is a tab inside Change Intelligence (route /change-intelligence),
// so this card points at the host page route for the spotlight to resolve.
// See ../../types.ts for the shape + key convention.

import type { ModuleExplanation } from '../../types';

export const costRecoveryModules: ModuleExplanation[] = [
  {
    id: 'cost-recovery',
    route: '/change-intelligence',
    icon: 'TrendingUp',
    category: 'commercial',
    keywords:
      'cost recovery back-charge backcharge chargeback claim recoverable liability responsible party apportionment chargeable recovered outstanding absorbed recovery rate traceability provability final account',
    titleKey: 'howto.cost-recovery.title',
    titleDefault: 'Cost recovery',
    summaryKey: 'howto.cost-recovery.summary',
    summaryDefault:
      "Turn a change that is someone else's cost into a tracked, recoverable claim and chase the money back.",
    whatKey: 'howto.cost-recovery.what',
    whatDefault:
      "Cost recovery is the Cost recovery tab inside Change Intelligence. It turns a defect, delay or change that is another party's liability into a back-charge: a recoverable claim position naming the responsible party, the gross amount and the percent of it that is chargeable. The engine works out the chargeable amount, what has been recovered and what is still outstanding. A live ledger rolls the open items up by party and currency, and a recovery-rate panel shows how much of what you were entitled to you actually got back, split by how provable the responsible owner is.",
    how: [
      {
        key: 'howto.cost-recovery.how.1',
        default: 'Open Change Intelligence for the project and switch to the Cost recovery tab.',
      },
      {
        key: 'howto.cost-recovery.how.2',
        default:
          'Record a back-charge: name the responsible party, enter the gross amount, the chargeable percent, the currency and the basis. The chargeable amount is calculated for you.',
      },
      {
        key: 'howto.cost-recovery.how.3',
        default:
          'Move each item through its commercial states, proposed, agreed, disputed, recovered or waived, and log the recovered amount as money comes back in.',
      },
      {
        key: 'howto.cost-recovery.how.4',
        default:
          'Where several parties share the blame, apportion one back-charge across them; the shares must total 100% and the per-party amounts reconcile to the chargeable amount.',
      },
      {
        key: 'howto.cost-recovery.how.5',
        default:
          'Read the ledger for outstanding by responsible party, and the recovery-rate panel for what you recovered versus what you were entitled to, split by owner traceability.',
      },
    ],
    tips: [
      {
        key: 'howto.cost-recovery.tip.1',
        default:
          'High traceability means the responsible owner is provable from the record, a timely notice or complete evidence; items with no scored evidence count as low, so the headline recovery rate is never overstated.',
      },
      {
        key: 'howto.cost-recovery.tip.2',
        default:
          'Amounts are kept exact and currencies are never blended; outstanding is simply the chargeable amount less whatever has been recovered.',
      },
    ],
    whenKey: 'howto.cost-recovery.when',
    whenDefault:
      "Use it whenever a defect, delay or change is another party's liability and you need to log, prove and chase the money back before the final account.",
  },
];
