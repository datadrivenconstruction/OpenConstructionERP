// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// photosGuide - "How it works" content for the photo archive.
// Consumed by <ModuleGuideButton content={photosGuide} /> on PhotosPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files.

import type { ModuleGuideContent } from '@/shared/ui';

export const photosGuide: ModuleGuideContent = {
  titleKey: 'guide.photoArchive.title',
  titleDefault: 'Photo archive',
  introKey: 'guide.photoArchive.intro',
  introDefault:
    'Every photo of the project lands here, whether it was taken for a punch item, a daily diary, a field report or uploaded directly. One archive, searchable by date, place, tag and the work it shows.',
  sections: [
    {
      icon: 'Rocket',
      titleKey: 'guide.photoArchive.capture.title',
      titleDefault: 'Take or drop photos',
      bodyKey: 'guide.photoArchive.capture.body',
      bodyDefault:
        'On a phone the button opens the camera; on a desktop drag files in. The capture time and position are read from the photo itself or from the device, and the GPS block is removed from the stored copy for privacy.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.photoArchive.link.title',
      titleDefault: 'Link photos to the work',
      bodyKey: 'guide.photoArchive.link.body',
      bodyDefault:
        'Link a photo to a punch item, inspection, field report or diary day, or add it from a BOQ position or schedule activity. The photo strip on that record then shows it, and validation flags links to records that no longer exist.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.photoArchive.find.title',
      titleDefault: 'Find a photo in seconds',
      bodyKey: 'guide.photoArchive.find.body',
      bodyDefault:
        'Switch between grid, timeline and map, and narrow by date range, source register, album or photos with a position. Albums hold handover packs or claim evidence and export as one ZIP with a JSON record per photo.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.photoArchive.compare.title',
      titleDefault: 'Show progress before and after',
      bodyKey: 'guide.photoArchive.compare.body',
      bodyDefault:
        'Select two photos of the same spot and make a comparison. Drag the handle to reveal how the work moved on between the two dates.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.photoArchive.ai.title',
      titleDefault: 'AI suggests, you confirm',
      bodyKey: 'guide.photoArchive.ai.body',
      bodyDefault:
        'Ask AI for a caption, tags, an observed progress reading or visible hazards. Each suggestion shows its confidence and stays pending until you accept, edit or reject it. It never identifies people.',
    },
  ],
  ctaKey: 'guide.photoArchive.cta',
  ctaDefault: 'Upload your first photo',
};
