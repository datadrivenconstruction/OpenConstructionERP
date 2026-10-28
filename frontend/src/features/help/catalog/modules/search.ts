// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Global search.
// Hub card only. Global search has two surfaces: a Ctrl+Shift+K modal
// that searches records by meaning across every module, and a routed
// file search page. The modal has no route, so "Open module" opens the
// routed file search page (/files/search); the "Show me where" spotlight
// targets the File Manager sidebar entry (/files) via spotlightRoute,
// because the sub-route has no sidebar link of its own. See ../../types.ts
// for the shape and key convention.

import type { ModuleExplanation } from '../../types';

export const searchModules: ModuleExplanation[] = [
  {
    id: 'search',
    route: '/files/search',
    spotlightRoute: '/files',
    icon: 'Sparkles',
    category: 'documents',
    keywords:
      'global search find lookup launcher command semantic vector meaning cross project cross module records files documents sheets photos boq positions tasks risks bim elements requirements rfi submittals correspondence validation chat recent searches full text index group by project relevance sort Ctrl Shift K',
    titleKey: 'howto.search.title',
    titleDefault: 'Global search',
    summaryKey: 'howto.search.summary',
    summaryDefault:
      'Find anything across the platform from one box: records by meaning and files by name, with every result one click from where it lives.',
    whatKey: 'howto.search.what',
    whatDefault:
      'Global search gives you two fast ways to find things. Press Ctrl+Shift+K (or Cmd+Shift+K) anywhere to open a search box that looks across your records by meaning, including BOQ positions, drawings, tasks, risks, BIM elements, requirements, RFIs, submittals, correspondence, validation and chat, and ranks the best matches together. Or open the file search page to look up a document, sheet or photo by name across every project you can access. Either way, clicking a result jumps you straight to it in its own module.',
    how: [
      {
        key: 'howto.search.how.1',
        default:
          'Press Ctrl+Shift+K (or Cmd+Shift+K) from anywhere in the app to open global search, then type at least two letters. It matches by meaning, so a rough phrase still surfaces the right record.',
      },
      {
        key: 'howto.search.how.2',
        default:
          'Use the type chips along the top to limit results to one area such as BOQ, documents, tasks or risks, and tick Current project only to stay inside the project you have open.',
      },
      {
        key: 'howto.search.how.3',
        default:
          'Click any result row to close the search and land on that item in its own module, with a match score shown so you can judge how close it is.',
      },
      {
        key: 'howto.search.how.4',
        default:
          'Switch to the file search page to track down a file by name. Type a name, press Search, and it looks across every project you can access for a matching document, sheet or photo.',
      },
      {
        key: 'howto.search.how.5',
        default:
          'On the file search page, narrow by file type, change the sort order, or turn on Group by project, and re-run one of your recent searches from the chips under the box.',
      },
    ],
    tips: [
      {
        key: 'howto.search.tip.1',
        default:
          'The records search works even while you are editing a BOQ row or filling a form, so you can look something up without losing your place.',
      },
      {
        key: 'howto.search.tip.2',
        default:
          'On the file search page a green Full-text index badge means it is reading inside file contents, not just file names. Without it, results match names only.',
      },
    ],
    whenKey: 'howto.search.when',
    whenDefault:
      'Reach for it whenever you know what you need but not where it sits, for example a half-remembered drawing number, a risk about a retaining wall, or every photo named facade across all your projects.',
  },
];
