// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works hub card for the Change Intelligence module. Authored as a
// standalone file under catalog/modules/*.ts; the glob aggregator in
// moduleExplanations.ts picks it up, so no edit there is needed. Every string
// carries its inline English default and is harvested into the locales later.

import type { ModuleExplanation } from '../../types';

export const changeIntelligenceModules: ModuleExplanation[] = [
  {
    id: 'change-intelligence',
    route: '/change-intelligence',
    icon: 'GitCompare',
    category: 'controls',
    keywords:
      'change order variation moc management of change claim back-charge cost recovery dispute risk delay risk scope ambiguity correspondence ball in court committed cost coordination cycle time clarifier intake apportionment',
    titleKey: 'howto.change-intelligence.title',
    titleDefault: 'Change Intelligence',
    summaryKey: 'howto.change-intelligence.summary',
    summaryDefault:
      'One read of every change on the project: what to act on first, who owes the next action, what it has committed, and what to recover.',
    whatKey: 'howto.change-intelligence.what',
    whatDefault:
      'Change Intelligence pulls the change-adjacent modules - change orders, variations, management of change, approvals and the correspondence around them - into one set of co-pilots. It ranks what needs action, ages each open item by the party holding it, totals the committed cost and schedule of approved changes, tracks what you mean to recover from the party at fault, and flags dispute, delay and scope risk early. Its scores are read against your real BOQ, schedule and earned-value ledger, not guesses.',
    how: [
      {
        key: 'howto.change-intelligence.how.1',
        default:
          'Pick a project and the co-pilots read its change orders, variations, management-of-change entries and correspondence together in one place.',
      },
      {
        key: 'howto.change-intelligence.how.2',
        default:
          'Start on Act first to see open change items ranked by urgency, each with the party the ball sits with and the recommended next action.',
      },
      {
        key: 'howto.change-intelligence.how.3',
        default:
          'Use Waiting on whom to age each open item by responsible party, and Correspondence to see which letters and emails still await your reply.',
      },
      {
        key: 'howto.change-intelligence.how.4',
        default:
          'Open Impact to total the committed cost and schedule of approved changes, and Decision impact to preview what approving one more candidate would add.',
      },
      {
        key: 'howto.change-intelligence.how.5',
        default:
          'Record what you mean to recover under Cost recovery: set the gross amount and the chargeable share, and split it across parties when responsibility is shared.',
      },
      {
        key: 'howto.change-intelligence.how.6',
        default:
          'Lean on the risk tabs - Dispute risk, Delay risk, Scope risk and Watch - and the Clarifier and Intake helpers to get ahead of trouble and clean up rough notes.',
      },
    ],
    tips: [
      {
        key: 'howto.change-intelligence.tip.1',
        default:
          'The recovery rate is split by how provable each responsible owner is, so back-charges backed by a timely notice and complete evidence recover at a higher rate than those with none.',
      },
      {
        key: 'howto.change-intelligence.tip.2',
        default:
          'The Clarifier and Intake previews never save anything, so you can paste a rough note or a foreign tracker row and see the structured draft before you commit to it.',
      },
      {
        key: 'howto.change-intelligence.tip.3',
        default:
          'Scope risk grades your BOQ lines for vague wording before work starts, so the soft spots that breed a change order later surface while they are still cheap to firm up.',
      },
    ],
    whenKey: 'howto.change-intelligence.when',
    whenDefault:
      'Reach for it in your weekly change and commercial review to decide what to chase, what it has cost and what to recover, and during pre-construction to firm up vague scope before it turns into a variation.',
  },
];
