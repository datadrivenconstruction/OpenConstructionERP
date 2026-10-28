// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// transmittalsGuide - "How it works" content for the Transmittals module.
// Consumed by <ModuleGuideButton content={transmittalsGuide} /> on
// TransmittalsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const transmittalsGuide: ModuleGuideContent = {
  titleKey: 'guide.transmittals.title',
  titleDefault: 'Transmittals',
  introKey: 'guide.transmittals.intro',
  introDefault:
    'A transmittal is the formal record of issuing drawings or specifications to a subcontractor or consultant: what was sent, to whom, for what purpose and whether they acknowledged receipt. Use it whenever you need dated proof of distribution behind your submittals and correspondence.',
  sections: [
    {
      icon: 'Send',
      titleKey: 'guide.transmittals.what.title',
      titleDefault: 'What a transmittal records',
      bodyKey: 'guide.transmittals.what.body',
      bodyDefault:
        'Each transmittal captures a subject, a set of document items, the recipients and a cover note. Once issued it becomes a locked, dated entry in the distribution log, so there is no dispute later about who received which documents and when.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.transmittals.purpose.title',
      titleDefault: 'Purpose codes',
      bodyKey: 'guide.transmittals.purpose.body',
      bodyDefault:
        'The purpose code states why the documents are being sent and what response is expected: For Approval needs a formal response, For Information needs none, and there are codes For Construction, For Tender, For Review and For Record. Pick the code that matches the intent so recipients know how to act.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.transmittals.compose.title',
      titleDefault: 'Recipients and documents',
      bodyKey: 'guide.transmittals.compose.body',
      bodyDefault:
        'Click New Transmittal, then add the people or companies receiving the package and list the documents being sent. You can link specific revisions straight from a Common Data Environment container so the exact file version is on the record, and set a response due date when an answer is required.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.transmittals.lifecycle.title',
      titleDefault: 'Draft, issue and track',
      bodyKey: 'guide.transmittals.lifecycle.body',
      bodyDefault:
        'A transmittal starts as a draft you can edit or delete. Issuing it locks the record and sends it to the recipients, after which it moves through Issued, Acknowledged and Closed. The status badges and overdue flag let you see at a glance what is still waiting on a response.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.transmittals.acknowledge.title',
      titleDefault: 'Acknowledgement trail',
      bodyKey: 'guide.transmittals.acknowledge.body',
      bodyDefault:
        'Expand any row to see the recipient list with who has acknowledged receipt and when. The counters show acknowledged against total, giving you a clear chase list and the evidence trail that confirms the documents actually landed.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.transmittals.find.title',
      titleDefault: 'Find and filter the log',
      bodyKey: 'guide.transmittals.find.body',
      bodyDefault:
        'The summary cards count transmittals by status across the project. Search by subject or transmittal number, and filter by status, to pull up a specific issue or review everything still open at once.',
    },
  ],
  ctaKey: 'guide.transmittals.cta',
  ctaDefault: 'Create your first transmittal',
};
