// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fileTransmittalsGuide - "How it works" content for the Transmittals module.
// Consumed by <ModuleGuideButton content={fileTransmittalsGuide} /> on
// TransmittalLogPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fileTransmittalsGuide: ModuleGuideContent = {
  titleKey: 'guide.file_transmittals.title',
  titleDefault: 'Transmittals',
  introKey: 'guide.file_transmittals.intro',
  introDefault:
    'A transmittal is the formal record of files handed over to an external party, with an auto-generated cover sheet and acknowledgement tracking. Use it whenever you need proof of what was issued, to whom, when and why.',
  sections: [
    {
      icon: 'Send',
      titleKey: 'guide.file_transmittals.concept.title',
      titleDefault: 'What a transmittal is',
      bodyKey: 'guide.file_transmittals.concept.body',
      bodyDefault:
        'Each transmittal bundles a set of project files into a single numbered send-record addressed to one or more recipients. It captures the subject, the reason for issue and a timestamped cover sheet, so the hand-over is auditable rather than a loose email.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.file_transmittals.create.title',
      titleDefault: 'Create a new transmittal',
      bodyKey: 'guide.file_transmittals.create.body',
      bodyDefault:
        'Click New Transmittal to open the wizard. You set a subject and reason, pick the files to include and add the recipients. On send, the transmittal gets its own number and a cover sheet is generated automatically.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.file_transmittals.log.title',
      titleDefault: 'Read the log',
      bodyKey: 'guide.file_transmittals.log.body',
      bodyDefault:
        'The table lists every transmittal for the active project, newest first. Columns show the number, subject, reason, item count, recipient progress and the date it was sent so you can scan the full issue history at a glance.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.file_transmittals.reason.title',
      titleDefault: 'Reason for issue',
      bodyKey: 'guide.file_transmittals.reason.body',
      bodyDefault:
        'Every transmittal carries a reason that states why the files were sent: for review, for construction, for approval, for information or for record. This sets expectations for the recipient and keeps the log searchable by intent.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.file_transmittals.status.title',
      titleDefault: 'Status and acknowledgement',
      bodyKey: 'guide.file_transmittals.status.body',
      bodyDefault:
        'A transmittal moves from Draft to Sent, then to Acknowledged once recipients confirm receipt, or Rejected if they push back. The recipients column shows acknowledged over total, so you can see at a glance who still owes a confirmation.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.file_transmittals.detail.title',
      titleDefault: 'Filter and drill in',
      bodyKey: 'guide.file_transmittals.detail.body',
      bodyDefault:
        'Narrow the log with the Status and Reason filters above the table. Click any row to open the detail drawer, where you can review the cover sheet, the included files and the acknowledgement state for each recipient.',
    },
  ],
  ctaKey: 'guide.file_transmittals.cta',
  ctaDefault: 'Create your first transmittal',
};
