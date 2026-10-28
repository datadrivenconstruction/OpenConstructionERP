// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// sourceDataGuide - "How it works" content for the Source Data Register.
// Consumed by <ModuleGuideButton content={sourceDataGuide} /> on
// SourceDataPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const sourceDataGuide: ModuleGuideContent = {
  titleKey: 'guide.source_data.title',
  titleDefault: 'Source Data Register',
  introKey: 'guide.source_data.intro',
  introDefault:
    'Track the prerequisite documents a delivery depends on before work can start: permits, surveys, geotechnical reports, technical conditions, title deeds, approvals and technical specifications. Know what you have, what is missing, and what is about to expire.',
  sections: [
    {
      icon: 'FileSearch',
      titleKey: 'guide.source_data.register.title',
      titleDefault: 'Register a document',
      bodyKey: 'guide.source_data.register.body',
      bodyDefault:
        'Add each prerequisite as it is requested or received: its type, owner, issuing authority and identifier. Set a validity window if it has one, so the register can compute how many days remain.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.source_data.verify.title',
      titleDefault: 'Verify and track validity',
      bodyKey: 'guide.source_data.verify.body',
      bodyDefault:
        'Mark a document verified once it has been checked against the source. Status moves automatically to expiring soon or expired as the validity window closes, based on the reminder window you set.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.source_data.blocking.title',
      titleDefault: 'Flag what blocks the schedule',
      bodyKey: 'guide.source_data.blocking.body',
      bodyDefault:
        'Mark a document as schedule-blocking when work cannot start without it. The register surfaces every flagged document that is missing or expired in one place, and the defective-inputs notice turns that into data another module can write up as a formal letter.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.source_data.checklist.title',
      titleDefault: 'Track completeness',
      bodyKey: 'guide.source_data.checklist.body',
      bodyDefault:
        'Build a checklist of everything the project requires, mark each item satisfied once the matching document is in, or waived when it does not apply. The summary shows at a glance whether the project is ready to proceed.',
    },
  ],
  ctaKey: 'guide.source_data.cta',
  ctaDefault: 'Register your first document',
};
