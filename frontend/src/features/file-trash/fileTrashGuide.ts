// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fileTrashGuide - "How it works" content for the Recycle Bin module.
// Consumed by <ModuleGuideButton content={fileTrashGuide} /> on TrashPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fileTrashGuide: ModuleGuideContent = {
  titleKey: 'guide.file_trash.title',
  titleDefault: 'Recycle Bin',
  introKey: 'guide.file_trash.intro',
  introDefault:
    'The Recycle Bin is the safety net for files you delete from a project. Deleted items are not gone right away: they wait here for 30 days so you can recover anything removed by mistake before it is permanently erased.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.file_trash.scope.title',
      titleDefault: 'One project at a time',
      bodyKey: 'guide.file_trash.scope.body',
      bodyDefault:
        'The Recycle Bin is scoped to the active project, so you only see files trashed from the project you are working in. If no project is selected, open one from the file manager first and the bin will fill with that project deleted items.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.file_trash.contents.title',
      titleDefault: 'What lands here',
      bodyKey: 'guide.file_trash.contents.body',
      bodyDefault:
        'Every kind of file you can delete shows up in the same list: documents, photos, sheets, BIM models, DWG drawings, takeoffs, reports and markups. Each row carries an icon for its type, its name, its size and when it was trashed.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.file_trash.retention.title',
      titleDefault: 'The 30-day countdown',
      bodyKey: 'guide.file_trash.retention.body',
      bodyDefault:
        'Each item keeps a days-left badge that counts down its 30-day retention window. When fewer than three days remain the badge turns red so you can act before the file is removed for good. The header strip totals how many items and how much space the bin holds.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.file_trash.restore.title',
      titleDefault: 'Restore a file',
      bodyKey: 'guide.file_trash.restore.body',
      bodyDefault:
        'Changed your mind? Click Restore on any row to send the file straight back to where it came from, fully intact. The original kind, name and contents are returned, so a restored drawing or report behaves exactly as it did before it was deleted.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.file_trash.purge.title',
      titleDefault: 'Delete forever',
      bodyKey: 'guide.file_trash.purge.body',
      bodyDefault:
        'Delete forever frees the space immediately and cannot be undone, so it asks you to confirm before it runs. Use it to clear sensitive files early or to reclaim storage, and let everything else expire on its own at the end of the retention window.',
    },
  ],
  ctaKey: 'guide.file_trash.cta',
  ctaDefault: 'Review your deleted files',
};
