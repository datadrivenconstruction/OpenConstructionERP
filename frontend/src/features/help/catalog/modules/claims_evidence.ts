// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Claims Evidence (per-module gap-fill card).
//
// Hub card for the claims-evidence sub-panel. It is hosted in the Dispute risk
// tab of Change Intelligence: expanding an open change reveals a provability
// gauge (0 to 100 score, evidence signals and a cure list) and a reconstructed,
// exportable evidence thread. Both panels are read-only.
// See ../../types.ts for the shape and key convention.

import type { ModuleExplanation } from '../../types';

export const claimsEvidenceModules: ModuleExplanation[] = [
  {
    id: 'claims_evidence',
    route: '/change-intelligence',
    icon: 'FileSignature',
    category: 'commercial',
    keywords:
      'claim provability evidence thread dispute variation change order notice acknowledgement contemporaneous record audit pack export score band cure traceability',
    titleKey: 'howto.claims_evidence.title',
    titleDefault: 'Claims Evidence',
    summaryKey: 'howto.claims_evidence.summary',
    summaryDefault:
      'Grade how provable a change or claim is, then assemble its supporting evidence into an exportable pack.',
    whatKey: 'howto.claims_evidence.what',
    whatDefault:
      'Claims Evidence strengthens a progress or variation claim before it is contested. It lives in the Dispute risk tab of Change Intelligence: expand an open change and you get a provability gauge that scores, from 0 to 100, how well the change could be proven from the record, alongside an evidence thread that pulls every linked notice, instruction and piece of correspondence into one reproducible pack you can export. It is read-only, so reviewing a claim never alters it.',
    how: [
      {
        key: 'howto.claims_evidence.how.1',
        default:
          'Open Change Intelligence, pick the project and go to the Dispute risk tab to see every open change scored for exposure.',
      },
      {
        key: 'howto.claims_evidence.how.2',
        default:
          'Expand a change row to reveal its provability gauge: a 0 to 100 score with a strong, moderate or weak band.',
      },
      {
        key: 'howto.claims_evidence.how.3',
        default:
          'Read the evidence signals - notice served on time, acknowledged by the other party, linked to a governing instruction, clear ownership chain and dated contemporaneous record - to see what is present and what is missing.',
      },
      {
        key: 'howto.claims_evidence.how.4',
        default:
          'Work the cure list under What would strengthen it, worst gap first, to raise the score before the change is contested.',
      },
      {
        key: 'howto.claims_evidence.how.5',
        default:
          'Select Reconstruct evidence thread to gather every linked notice, instruction and correspondence record around the change, grouped by section with its date span and content digest.',
      },
      {
        key: 'howto.claims_evidence.how.6',
        default:
          'Export the assembled pack as JSON; the export is logged in the audit trail and the same project state always reproduces the same digest.',
      },
    ],
    tips: [
      {
        key: 'howto.claims_evidence.tip.1',
        default:
          'The gauge and the thread are read-only, so reviewing a claim never changes it and you can open any change safely.',
      },
      {
        key: 'howto.claims_evidence.tip.2',
        default:
          'A reproducible digest means two people who assemble the same pack get the same fingerprint, which is what helps it stand up when a claim is challenged.',
      },
    ],
    whenKey: 'howto.claims_evidence.when',
    whenDefault:
      'Use it whenever a change or claim could be questioned, to confirm it is provable and to hand over a clean evidence pack.',
  },
];
