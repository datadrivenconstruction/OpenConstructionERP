// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Construction Control (QA/QC) module card.
// See ../../types.ts for the ModuleExplanation shape + key convention, and
// ../quality-safety.ts for fully-worked quality-domain examples.
//
// This is the integrated acceptance-control module at /construction-control:
// one place that runs the five pillars of construction quality control over
// the active project (inspections against acceptance criteria, material and
// lab certificates, as-built tolerance with e-sign, hold and witness gates,
// and a regime-aware handover package). It is distinct from the standalone
// Inspections, QMS and Handover cards.

import type { ModuleExplanation } from '../../types';

export const constructionControlModules: ModuleExplanation[] = [
  {
    id: 'construction-control',
    route: '/construction-control',
    icon: 'ClipboardCheck',
    category: 'quality',
    keywords:
      'qa qc quality control acceptance criteria inspection mir wir hold point witness point ' +
      'material certificate en 10204 mill cert lab test iso 17025 as-built tolerance e-sign ' +
      'handover taking over substantial practical completion certificate ncr ce ukca',
    titleKey: 'howto.construction-control.title',
    titleDefault: 'Construction Control',
    summaryKey: 'howto.construction-control.summary',
    summaryDefault:
      'Prove the work was inspected, tested and accepted, from the first hold point to a signed handover certificate.',
    whatKey: 'howto.construction-control.what',
    whatDefault:
      'Construction Control is the quality assurance and control workspace for the active project. It joins five pillars in one place: acceptance criteria and the inspections that check them, material certificates and lab test results, as-built records checked against tolerance and e-signed, hold and witness gates that block progress until released, and the handover package that bundles all the evidence and issues an acceptance certificate. Any failed check raises a non-conformance automatically, so every defect traces back to the record that found it.',
    how: [
      {
        key: 'howto.construction-control.how.1',
        default:
          'Pick the project from the header, then open Inspections to define reusable acceptance criteria - the measurable checks with their standard, method and tolerance.',
      },
      {
        key: 'howto.construction-control.how.2',
        default:
          'Raise an inspection against a criterion, link it to the activity or BIM element being checked, and record the outcome as pass, fail or conditional; a fail raises a non-conformance for you.',
      },
      {
        key: 'howto.construction-control.how.3',
        default:
          'In Materials and Tests, log material certificates with batch and validity details and review them for conformity, and record lab test results from an accredited lab.',
      },
      {
        key: 'howto.construction-control.how.4',
        default:
          'In As-Built, capture the surveyed value, let it check against the tolerance, then verify and e-sign the record so it stands as a legal as-built.',
      },
      {
        key: 'howto.construction-control.how.5',
        default:
          'In Hold Points, set hold, witness, surveillance or review gates that block progress until the right party releases them, and check whether an activity may proceed.',
      },
      {
        key: 'howto.construction-control.how.6',
        default:
          'In Handover, assemble the evidence package; the completion gate stays blocked while non-conformances or hold points are open, then e-sign and issue the acceptance certificate.',
      },
    ],
    tips: [
      {
        key: 'howto.construction-control.tip.1',
        default:
          'A failed inspection, a rejected material, a failed lab test and an out-of-tolerance as-built each raise a linked non-conformance, so defects always point back to the check that caught them.',
      },
      {
        key: 'howto.construction-control.tip.2',
        default:
          'A hold gate can only be released by the required party (site QC, QA, a third-party inspector or the authority); witness, surveillance and review gates can be waived with a reason, a hold gate cannot.',
      },
      {
        key: 'howto.construction-control.tip.3',
        default:
          'The handover package follows your contract regime - taking-over, substantial or practical completion - and will not issue while the gate is blocked unless a manager overrides it on record.',
      },
    ],
    whenKey: 'howto.construction-control.when',
    whenDefault:
      'Use it through construction to run a traceable acceptance trail for every element, right up to a signed, evidence-backed handover.',
  },
];
