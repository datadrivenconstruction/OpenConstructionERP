// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// markupsGuide - "How it works" content for the Markups module.
// Consumed by <ModuleGuideButton content={markupsGuide} /> on MarkupsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const markupsGuide: ModuleGuideContent = {
  titleKey: 'guide.markups.title',
  titleDefault: 'Markups',
  introKey: 'guide.markups.intro',
  introDefault:
    'Markups are the drawing comments your team leaves on project documents: clouds, arrows, stamps and measurements placed right on a PDF. Use this module to capture review feedback in one place, assign it to a person and track each note from open to resolved.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.markups.tools.title',
      titleDefault: 'The markup tools',
      bodyKey: 'guide.markups.tools.body',
      bodyDefault:
        'Ten markup types cover most review needs: cloud, arrow, text, rectangle, highlight, distance, area, count, stamp and polygon. Each markup carries a label, optional text and a colour, and lives on a specific document and page so it always points at the right detail.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.markups.annotate.title',
      titleDefault: 'Annotate on the PDF',
      bodyKey: 'guide.markups.annotate.body',
      bodyDefault:
        'Click Annotate to open a document in the inline viewer and draw markups straight onto the page. From any markup you can also Open in document to jump back to its exact spot on the source drawing, so a comment is never disconnected from what it refers to.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.markups.review.title',
      titleDefault: 'Assign, track and approve',
      bodyKey: 'guide.markups.review.body',
      bodyDefault:
        'Give a markup an assignee and move it through active, resolved and archived as the work gets done. Filter by type, status or person to focus a review, and route a markup through an approval workflow when it needs a formal sign-off.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.markups.connect.title',
      titleDefault: 'Measurements and BOQ links',
      bodyKey: 'guide.markups.connect.body',
      bodyDefault:
        'Distance, area and count markups hold a real value and unit. Use as takeoff quantity sends that measurement into PDF Takeoff instead of re-keying it, and a markup linked to a BOQ position opens straight to that line so the comment, the quantity and the cost stay connected.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.markups.stamps.title',
      titleDefault: 'Stamps and revision compare',
      bodyKey: 'guide.markups.stamps.body',
      bodyDefault:
        'Place ready-made stamps such as Approved, Rejected or For Review on a page, or build your own custom stamp with its own text and colour. Open Compare to overlay two revisions of a drawing side by side and see exactly what changed.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.markups.export.title',
      titleDefault: 'See everything and export',
      bodyKey: 'guide.markups.export.body',
      bodyDefault:
        'The All annotations tab pulls markups from every source into one feed, while Hub only shows the ones created here. Switch between list and grid views, and Export sends the full set to CSV for sharing or record keeping.',
    },
  ],
  ctaKey: 'guide.markups.cta',
  ctaDefault: 'Add your first markup',
};
