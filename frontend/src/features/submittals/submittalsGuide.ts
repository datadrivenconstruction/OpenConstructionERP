// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// submittalsGuide - "How it works" content for the Submittals module.
// Consumed by <ModuleGuideButton content={submittalsGuide} /> on SubmittalsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const submittalsGuide: ModuleGuideContent = {
  titleKey: 'guide.submittals.title',
  titleDefault: 'Submittals',
  introKey: 'guide.submittals.intro',
  introDefault:
    'Submittals are the formal log of shop drawings, product data, samples and certificates that need sign-off before the work is built. Use this module to move each one through review and approval so nothing goes to site without approved documentation.',
  sections: [
    {
      icon: 'FileSearch',
      titleKey: 'guide.submittals.what.title',
      titleDefault: 'What a submittal is',
      bodyKey: 'guide.submittals.what.body',
      bodyDefault:
        'Each submittal is one item that needs review, tagged with a type such as shop drawing, product data, sample, mock-up, test report, calculation, method statement, certificate or warranty. It carries a submittal number, a spec section, a title and a revision so you always know which version is in play.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.submittals.create.title',
      titleDefault: 'Create and edit',
      bodyKey: 'guide.submittals.create.body',
      bodyDefault:
        'Click New Submittal and fill in the title, spec section, type, date required and an optional description. The number is assigned for you. Use Edit to correct details on a draft, and add the description that reviewers see when they open the row.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.submittals.lifecycle.title',
      titleDefault: 'The review lifecycle',
      bodyKey: 'guide.submittals.lifecycle.body',
      bodyDefault:
        'A submittal moves through Draft, Submitted and Under Review, then ends as Approved, Approved as Noted, Revise and Resubmit, or Rejected. Submit sends a draft for review, and a reviewer records a Decision with comments. When changes are requested, edit the item and resubmit to start a new revision.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.submittals.tracking.title',
      titleDefault: 'Ball in court and due dates',
      bodyKey: 'guide.submittals.tracking.body',
      bodyDefault:
        'Each row shows who holds the ball in court plus a status pipeline so you can see progress at a glance. A days-in-court chip flags items sitting too long with the reviewer, and a due-date badge warns when a required date is close or overdue.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.submittals.boq_link.title',
      titleDefault: 'Link to BOQ positions',
      bodyKey: 'guide.submittals.boq_link.body',
      bodyDefault:
        'Link a submittal to the Bill of Quantities positions it covers so you can tell which work items already have approved documentation. Each linked position appears as a pill you can click to jump straight to it in the BOQ.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.submittals.find.title',
      titleDefault: 'Find and track at scale',
      bodyKey: 'guide.submittals.find.body',
      bodyDefault:
        'The stat cards summarise totals, pending review, approved and rejected counts for the project. Search by title, number, spec section or reviewer, and filter by status to focus on the items that need action now.',
    },
  ],
  ctaKey: 'guide.submittals.cta',
  ctaDefault: 'Create your first submittal',
};
