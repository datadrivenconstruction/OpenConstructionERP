// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" guide content for the Project Files module. Co-located
// with the FileManagerPage. Every key carries an inline English default
// and is consumed via t(key, { defaultValue }). The keys are not in en.ts,
// the inline defaults are the English source; their translations live in the
// other locale files, so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const filesGuide: ModuleGuideContent = {
  titleKey: 'guide.files.title',
  titleDefault: 'Project Files',
  introKey: 'guide.files.intro',
  introDefault:
    'Project Files is one hub for every drawing, document and model on the job. Files are sorted into folders by type, and opening one takes you straight to the tool that works with it.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.files.folders.title',
      titleDefault: 'Folders by file type',
      bodyKey: 'guide.files.folders.body',
      bodyDefault:
        'The home view shows a card for each category: documents, photos, sheets, BIM models, DWG drawings, takeoffs, reports and markups. Click a folder to drill into its grid or list view.',
      spotlightSelector: '[data-testid="folder-card-document"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.files.upload.title',
      titleDefault: 'Uploading drawings and documents',
      bodyKey: 'guide.files.upload.body',
      bodyDefault:
        'Press Upload files, or use the button on any folder card to file straight into that category. PDF and Office documents, JPG, PNG and HEIC photos, IFC and RVT BIM models, and DWG drawings are all supported. Drag a file onto the dialog or pick it from disk.',
      spotlightSelector: '[data-guide="files-upload-button"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.files.open.title',
      titleDefault: 'Opening feeds takeoff and the BOQ',
      bodyKey: 'guide.files.open.body',
      bodyDefault:
        'Open a file to send it to the right tool. A PDF goes to PDF Takeoff, an IFC or RVT to the BIM 3D viewer, a DWG to DWG Takeoff. The quantities you measure there flow into your Bill of Quantities.',
      spotlightSelector: '[data-testid="folder-card-sheet"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.files.organise.title',
      titleDefault: 'Find and organise files',
      bodyKey: 'guide.files.organise.body',
      bodyDefault:
        'Inside a folder, search by name, sort, filter by extension or tag, and star the files you reach for most. Switch between grid and list with the view toggle.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.files.share.title',
      titleDefault: 'Share, transmit and control access',
      bodyKey: 'guide.files.share.body',
      bodyDefault:
        'Email a file, create a share link, or send a formal transmittal from the log. Project owners can lock a folder and grant access per person, so the right people see the right drawings.',
      spotlightSelector: '[data-guide="files-transmittal-link"]',
    },
  ],
  ctaKey: 'guide.files.cta',
  ctaDefault: 'Upload your first file',
};
