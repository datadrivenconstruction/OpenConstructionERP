// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ncrGuide - "How it works" content for the Non-Conformance Reports module.
// Consumed by <ModuleGuideButton content={ncrGuide} /> on NCRPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const ncrGuide: ModuleGuideContent = {
  titleKey: 'guide.ncr.title',
  titleDefault: 'Non-Conformance Reports',
  introKey: 'guide.ncr.intro',
  introDefault:
    'A Non-Conformance Report turns defective work into a formal, numbered record with a severity and an owner, so the defect cannot quietly disappear and its cause gets fixed, not just the symptom. Use it whenever site work fails to meet the specification.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.ncr.what.title',
      titleDefault: 'What an NCR records',
      bodyKey: 'guide.ncr.what.body',
      bodyDefault:
        'Each NCR captures one non-conformance against the spec it breaches: concrete below strength, a clashing duct run, a missing test certificate or a safety breach. It carries a type (material, workmanship, design, documentation or safety) and a severity from observation up to critical.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.ncr.raise.title',
      titleDefault: 'Raising a report',
      bodyKey: 'guide.ncr.raise.body',
      bodyDefault:
        'Click New NCR, then classify the defect by type and severity and give it a clear title and description of what was observed, where, and which specification was not met. Add the location on site and, if known, a preliminary root cause so the investigation can begin.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.ncr.lifecycle.title',
      titleDefault: 'The status lifecycle',
      bodyKey: 'guide.ncr.lifecycle.body',
      bodyDefault:
        'Every NCR moves through identified, under review, corrective action and verification before it is closed, or voided if raised in error. Record the corrective action that fixes this instance and a preventive action so the same failure does not recur on the next pour or run.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.ncr.register.title',
      titleDefault: 'Tracking the register',
      bodyKey: 'guide.ncr.register.body',
      bodyDefault:
        'The register lists every NCR with its number, type, severity and status, above at-a-glance counts of total, open, under-review and closed. Use the search box and status filter to focus the list, and expand any row to read the full detail and act on it.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.ncr.trace.title',
      titleDefault: 'Traceability across modules',
      bodyKey: 'guide.ncr.trace.body',
      bodyDefault:
        'NCRs are often raised straight from a failed Inspection, and a badge shows when one was auto-raised from a clash or a blocking validation error. The expanded row links back to the originating inspection so you land on the exact failed check.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.ncr.variation.title',
      titleDefault: 'When the defect costs money',
      bodyKey: 'guide.ncr.variation.body',
      bodyDefault:
        'If a non-conformance carries a cost impact, create a Variation straight from the NCR to raise a linked Change Order, so the quality record and the commercial one never separate. Minor snags that just need a re-check belong on the Punch List instead.',
    },
  ],
  ctaKey: 'guide.ncr.cta',
  ctaDefault: 'Raise your first NCR',
};
