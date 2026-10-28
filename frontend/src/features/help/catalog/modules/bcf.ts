// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - BCF (BIM Collaboration Format) issue exchange card.
// See ../../types.ts for the ModuleExplanation shape + key convention, and
// ../coordination.ts for the sibling clash / federation / rules cards.
//
// BCF is an I/O capability rather than a standalone page. The interactive
// export / import controls live on the Clash Detection page (/clash); the
// Model Coordination dashboard (/coordination) only rolls up BCF activity
// counts. The card therefore hosts on /clash so the hub "Show me where"
// spotlight lands on the real Export BCF / Import BCF buttons.

import type { ModuleExplanation } from '../../types';

export const bcfModules: ModuleExplanation[] = [
  {
    id: 'bcf',
    route: '/clash',
    icon: 'MessageSquare',
    category: 'coordination',
    keywords:
      'bcf bim collaboration format bcfzip open exchange issue topic viewpoint comment ' +
      'coordination clash round-trip openbim vendor neutral markup snapshot 2.1 3.0 handoff designer',
    titleKey: 'howto.bcf.title',
    titleDefault: 'BCF Issue Exchange',
    summaryKey: 'howto.bcf.summary',
    summaryDefault:
      'Send coordination issues out and take the answers back in as open BCF files, so any BIM tool can join the conversation.',
    whatKey: 'howto.bcf.what',
    whatDefault:
      'BCF (BIM Collaboration Format) is the open, vendor-neutral file for moving coordination issues between BIM tools. Each issue travels as a topic that carries its status, a saved 3D viewpoint and a thread of comments, so whoever opens it sees the same problem from the same camera angle. From the Clash Detection page you export clashes to a .bcfzip to hand to a designer, then import their returned .bcfzip to fold the fixes back into the run, with topics matched to your existing clashes automatically. The Model Coordination dashboard rolls that BCF activity up next to your federations and clash results.',
    how: [
      {
        key: 'howto.bcf.how.1',
        default:
          'Open Clash Detection for the project, pick a clash run and triage the issues by status, severity and assignee.',
      },
      {
        key: 'howto.bcf.how.2',
        default:
          'Export to BCF: use Export open to send every unresolved clash, tick rows to send a subset, or the row action to send a single clash; you get a .bcfzip download with a viewpoint at each clash location.',
      },
      {
        key: 'howto.bcf.how.3',
        default:
          'Hand the .bcfzip to the responsible designer; they open it in their own BIM tool, see each issue in its viewpoint and reply with a comment or a status change.',
      },
      {
        key: 'howto.bcf.how.4',
        default:
          'When the file comes back, use Import BCF and choose their .bcfzip; topics match to your existing clashes by signature or BCF id, and the result reports how many matched, were unmatched or errored.',
      },
      {
        key: 'howto.bcf.how.5',
        default:
          'Spot the clashes that have been through a round-trip by the BCF badge on the row, then re-run the check to confirm the resolved ones are gone.',
      },
    ],
    tips: [
      {
        key: 'howto.bcf.tip.1',
        default:
          'BCF carries only the issues and viewpoints, never the model itself, so the file stays small and any coordination tool can read it without your source models.',
      },
      {
        key: 'howto.bcf.tip.2',
        default:
          'An unmatched count on import means an incoming topic could not be tied to a current clash; read the matched, unmatched and error figures so nothing is silently dropped.',
      },
    ],
    whenKey: 'howto.bcf.when',
    whenDefault:
      'Use it to hand coordination issues to a design partner who works in a different BIM tool, and to pull their resolutions back in before the next coordination meeting.',
  },
];
