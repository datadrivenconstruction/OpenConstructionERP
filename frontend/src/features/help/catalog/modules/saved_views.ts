// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - Saved views (file manager sub-panel).
// Hub card only: the Saved views rail is a side-mounted panel on the
// Files page, so this entry routes to the host /files page. See
// ../../types.ts for the shape and key convention.

import type { ModuleExplanation } from '../../types';

export const savedViewsModules: ModuleExplanation[] = [
  {
    id: 'saved_views',
    route: '/files',
    icon: 'Library',
    category: 'documents',
    keywords:
      'saved views file filter preset bookmark sort search rail recall pinned shared file manager documents layout',
    titleKey: 'howto.saved_views.title',
    titleDefault: 'Saved views',
    summaryKey: 'howto.saved_views.summary',
    summaryDefault:
      'Save a file filter, search and sort as a named view and recall it from a rail in one click.',
    whatKey: 'howto.saved_views.what',
    whatDefault:
      'Saved views capture how you have narrowed the file list, the category, search text, sort order, file extension, tags and date range, under a name you choose. They sit in a Saved views rail under the folder tree on the Files page, so a filter you set up once comes back with a single click instead of being rebuilt every time. A view can stay private to you or be shared with everyone on the project.',
    how: [
      {
        key: 'howto.saved_views.how.1',
        default:
          'Narrow the file list first: set a category, type a search, choose a sort, or filter by extension. The Save view button then appears in the file actions bar.',
      },
      {
        key: 'howto.saved_views.how.2',
        default:
          'Click Save view, give it a clear name and pick an icon. Tick Pin to top to keep it at the head of the rail, or Share with everyone on this project so the team sees it too.',
      },
      {
        key: 'howto.saved_views.how.3',
        default:
          'Open any view from the Saved views rail under the folder tree on the left. One click re-applies its filter, search and sort to the file list.',
      },
      {
        key: 'howto.saved_views.how.4',
        default:
          'Right-click a view to rename it, pin or unpin it, share it or stop sharing, duplicate it as a starting point, or delete it.',
      },
      {
        key: 'howto.saved_views.how.5',
        default:
          'Watch the use-count badge climb each time you open a view, so the layouts you rely on most stay easy to spot.',
      },
    ],
    tips: [
      {
        key: 'howto.saved_views.tip.1',
        default:
          'The Save view button only shows once you have actually narrowed the list, so the rail never fills up with empty filters.',
      },
      {
        key: 'howto.saved_views.tip.2',
        default:
          'Pin the views you use daily to keep them on top, and share a view so the whole project team works from the same filter.',
      },
    ],
    whenKey: 'howto.saved_views.when',
    whenDefault:
      'Reach for it whenever you keep rebuilding the same file filter, for example structural drawings awaiting review or this week uploaded photos, so the layout is always one click away.',
  },
];
