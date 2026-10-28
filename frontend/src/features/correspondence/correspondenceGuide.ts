// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// correspondenceGuide - "How it works" content for the Correspondence module.
// Consumed by <ModuleGuideButton content={correspondenceGuide} /> on
// CorrespondencePage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const correspondenceGuide: ModuleGuideContent = {
  titleKey: 'guide.correspondence.title',
  titleDefault: 'Correspondence',
  introKey: 'guide.correspondence.intro',
  introDefault:
    'Correspondence is your contemporaneous register of every formal letter, notice, email, memo and report exchanged with project parties. Log each one as it happens so you have a clean, traceable evidence trail if a claim or dispute arises.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.correspondence.what.title',
      titleDefault: 'What this register is for',
      bodyKey: 'guide.correspondence.what.body',
      bodyDefault:
        'This is a dated log, not a mailbox. Every entry is a record of one communication that already happened, captured while the facts are fresh. Keeping it current is what gives you a reliable timeline of who said what, and when.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.correspondence.log.title',
      titleDefault: 'Log an entry',
      bodyKey: 'guide.correspondence.log.body',
      bodyDefault:
        'Click New Letter to record a communication. Set the direction (incoming or outgoing) and the type (letter, email, notice, memo or report), then add the subject. Inbound email auto-import is not wired yet, so entries are logged by hand today.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.correspondence.parties.title',
      titleDefault: 'Parties and dates',
      bodyKey: 'guide.correspondence.parties.body',
      bodyDefault:
        'Record who it was From and who it went To, picking real people from your Contacts directory so each party links back to its record. Date Sent and Date Received pin the entry on the project timeline, and the form pre-fills the key date for the direction you chose.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.correspondence.links.title',
      titleDefault: 'Link into the thread',
      bodyKey: 'guide.correspondence.links.body',
      bodyDefault:
        'Connect an entry to the related Transmittal, RFI and project Documents so one thread of communication stays traceable end to end. Linked references show as badges on the row, and you can attach the source file itself to each entry as proof.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.correspondence.find.title',
      titleDefault: 'Find and review',
      bodyKey: 'guide.correspondence.find.body',
      bodyDefault:
        'Search by subject, reference number or party to pull up a record fast, and narrow the list with the direction and type filters. Click any row to expand it and read the full notes, linked records and attached files.',
    },
  ],
  ctaKey: 'guide.correspondence.cta',
  ctaDefault: 'Log your first entry',
};
