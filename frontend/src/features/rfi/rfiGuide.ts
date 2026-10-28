// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// rfiGuide - "How it works" content for the RFIs module.
// Consumed by <ModuleGuideButton content={rfiGuide} /> on RFIPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The inline defaults are the English source and
// the keys are not in en.ts; the translations live in the other locale
// files, so a changed default here needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const rfiGuide: ModuleGuideContent = {
  titleKey: 'guide.rfi.title',
  titleDefault: 'RFIs',
  introKey: 'guide.rfi.intro',
  introDefault:
    'An RFI is a formal Request for Information you raise to get a design or construction question answered on the record. Use it whenever a drawing, specification or site condition is unclear, so the question, the official answer and any cost or schedule impact are all tracked in one place.',
  sections: [
    {
      icon: 'PencilLine',
      titleKey: 'guide.rfi.raise.title',
      titleDefault: 'Raise a question',
      bodyKey: 'guide.rfi.raise.body',
      bodyDefault:
        'Click New RFI and write a clear subject and the question you need answered. Set a priority and discipline, name who owns the next move with Ball in Court, and give it a response due date so the clock is visible to everyone.',
      spotlightSelector: '[data-guide="rfi-new"]',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.rfi.attach.title',
      titleDefault: 'Attach the drawings in question',
      bodyKey: 'guide.rfi.attach.body',
      bodyDefault:
        'Pull the relevant drawings and documents straight from the project with Attach drawings, or drop a file to upload it on the spot. Linking the exact sheet removes ambiguity and gives the responder everything they need to answer.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.rfi.track.title',
      titleDefault: 'Track to an answer',
      bodyKey: 'guide.rfi.track.body',
      bodyDefault:
        'Each RFI moves from Open to Answered to Closed. The ball-in-court badge shows whether it is with you or with them, and the days-open counter turns red once an RFI passes its due date so nothing stalls unnoticed.',
      spotlightSelector: '[data-guide="rfi-stats"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.rfi.respond.title',
      titleDefault: 'Respond and close out',
      bodyKey: 'guide.rfi.respond.body',
      bodyDefault:
        'When the answer is ready, open the RFI and record the official response, then close it so no further changes can be made. The response is kept with the question as the permanent record for the contract file.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.rfi.filter.title',
      titleDefault: 'Find what is on your plate',
      bodyKey: 'guide.rfi.filter.body',
      bodyDefault:
        'The stat cards summarise total, open, overdue and average response days. Use the quick views for Awaiting me, Raised by me and Overdue, and narrow further by status, priority or discipline, or search across every RFI.',
      spotlightSelector: '[data-guide="rfi-quickviews"]',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.rfi.impact.title',
      titleDefault: 'Carry impact into change orders',
      bodyKey: 'guide.rfi.impact.body',
      bodyDefault:
        'Flag cost or schedule impact on the RFI so it is never lost. When an answer carries cost, Create Change Order turns it straight into a change order, and Export RFI Log produces the full register for records and reporting.',
      spotlightSelector: '[data-guide="rfi-export"]',
    },
  ],
  ctaKey: 'guide.rfi.cta',
  ctaDefault: 'Raise your first RFI',
};
