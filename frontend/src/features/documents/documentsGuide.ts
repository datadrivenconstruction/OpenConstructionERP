// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// documentsGuide - "How it works" content for the Documents module.
// Consumed by <ModuleGuideButton content={documentsGuide} /> on DocumentsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const documentsGuide: ModuleGuideContent = {
  titleKey: 'guide.documents.title',
  titleDefault: 'Documents',
  introKey: 'guide.documents.intro',
  introDefault:
    'Documents is the single register for every file on a project: drawings, contracts, specifications, photos and correspondence. Upload files here, keep their versions and status in order, then hand them off to the people who need them.',
  sections: [
    {
      icon: 'Rocket',
      titleKey: 'guide.documents.upload.title',
      titleDefault: 'Upload your files',
      bodyKey: 'guide.documents.upload.body',
      bodyDefault:
        'Drag and drop files onto the drop zone, or use Browse Files and Upload Files to pick them. Any file type is accepted, including PDF, images, Excel, DWG and IFC. Each upload is added to a background queue so you can keep working while it finishes.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.documents.categories.title',
      titleDefault: 'Categories and metadata',
      bodyKey: 'guide.documents.categories.body',
      bodyDefault:
        'Every document is filed under a category such as drawing, contract, specification, photo or correspondence. Open Properties on any file to change its category, add a description and apply tags, which makes large registers easy to scan and search.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.documents.find.title',
      titleDefault: 'Find what you need',
      bodyKey: 'guide.documents.find.body',
      bodyDefault:
        'Search by name to jump straight to a file, then narrow the list with the category pills and the file-type and revision filters. Sort by date, name or size, and use the revision filter to show only the latest version or files that have multiple versions.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.documents.versions.title',
      titleDefault: 'Versions and CDE status',
      bodyKey: 'guide.documents.versions.body',
      bodyDefault:
        'Re-uploading a file under the same name keeps a version history, shown as a version badge on the card. ISO 19650 status flows forward from WIP to Shared to Published to Archived, with optional suitability codes, so everyone can see how mature each document is.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.documents.preview.title',
      titleDefault: 'Preview and open in context',
      bodyKey: 'guide.documents.preview.body',
      bodyDefault:
        'Click a PDF or image to preview it in place, with related documents surfaced by semantic similarity. CAD and BIM files open in their viewer, and a PDF can be sent straight to Measure and Takeoff, so a document becomes the start of real work.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.documents.distribute.title',
      titleDefault: 'Organize and distribute',
      bodyKey: 'guide.documents.distribute.body',
      bodyDefault:
        'The document flow runs from Upload to Organize in the CDE to Distribute. Use the actions menu to rename or download a file, or send it on a formal transmittal so the issue is tracked and recipients are recorded.',
    },
  ],
  ctaKey: 'guide.documents.cta',
  ctaDefault: 'Upload your first document',
};
