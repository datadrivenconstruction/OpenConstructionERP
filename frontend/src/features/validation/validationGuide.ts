// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// validationGuide - "How it works" content for the Validation module.
// Consumed by <ModuleGuideButton content={validationGuide} /> on ValidationPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const validationGuide: ModuleGuideContent = {
  titleKey: 'guide.validation.title',
  titleDefault: 'Validation',
  introKey: 'guide.validation.intro',
  introDefault:
    'Validation checks a Bill of Quantities against the rule sets configured for its project and grades the result. Run it as a first-class step in the Import, Validate, Enrich, Estimate pipeline to catch data-quality and compliance issues before you price or tender.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.validation.pick_run.title',
      titleDefault: 'Pick a BOQ and run',
      bodyKey: 'guide.validation.pick_run.body',
      bodyDefault:
        'The project comes from the switcher in the top bar. Choose one of its Bills of Quantities, then click Run Validation. Each run is saved as a report, so when you come back the page restores your last result instead of starting empty.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.validation.rule_sets.title',
      titleDefault: 'Rule sets are chosen for you',
      bodyKey: 'guide.validation.rule_sets.body',
      bodyDefault:
        'You do not pick rules by hand. The engine derives them from the project region and classification standard: boq_quality applies everywhere, and DIN 276, GAEB, NRM or MasterFormat layer on top. The chips above the Run button show exactly which checks will be applied.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.validation.score.title',
      titleDefault: 'Read the score and summary',
      bodyKey: 'guide.validation.score.body',
      bodyDefault:
        'The ring scores the run from 0 to 100 percent, from Poor to Excellent. The summary next to it counts the rules checked and how many passed, raised warnings or failed as errors, so you see the health of the estimate at a glance.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.validation.findings.title',
      titleDefault: 'Work through the findings',
      bodyKey: 'guide.validation.findings.body',
      bodyDefault:
        'Every finding lists below the score. Filter by errors, warnings, info or passed, then expand a row for its message and suggested fix. Where a finding points at a BOQ element you can jump straight to that position in the editor and fix it at the source.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.validation.raise_ncr.title',
      titleDefault: 'Escalate a blocking error',
      bodyKey: 'guide.validation.raise_ncr.body',
      bodyDefault:
        'A failing error can be turned into a formal record. Use Raise NCR on the finding to open the non-conformance register with the rule, message and element reference pre-filled, so a genuine defect is tracked rather than lost.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.validation.export.title',
      titleDefault: 'Export the results',
      bodyKey: 'guide.validation.export.body',
      bodyDefault:
        'When the review is done, export the findings to CSV for sharing or a paper trail, or export the priced BOQ to PDF. The CSV mirrors exactly what is on screen so the file always matches the report you reviewed.',
    },
  ],
  ctaKey: 'guide.validation.cta',
  ctaDefault: 'Run validation on a BOQ',
};
