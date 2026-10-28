// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// constructionControlGuide - "How it works" content for the Construction
// Control (QA/QC) module. Consumed by
// <ModuleGuideButton content={constructionControlGuide} /> on
// ConstructionControlPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.
//
// Spotlight selectors point at the page's five pillar tabs. The TabBar is
// rendered with testIdPrefix="cc", so each tab exposes a stable
// data-testid="cc-tab-<id>" that survives styling churn. When no project is
// selected the tabs are not on screen and the card simply centres itself.

import type { ModuleGuideContent } from '@/shared/ui';

export const constructionControlGuide: ModuleGuideContent = {
  titleKey: 'guide.construction-control.title',
  titleDefault: 'Construction Control',
  introKey: 'guide.construction-control.intro',
  introDefault:
    'Construction Control is your quality assurance and control workspace for the active project. It runs five pillars in one place: inspections, materials and tests, as-built records, hold points, and the handover package. Pick a project from the header, then work the pillars left to right to build a traceable acceptance trail.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.construction-control.inspections.title',
      titleDefault: 'Acceptance criteria and inspections',
      bodyKey: 'guide.construction-control.inspections.body',
      bodyDefault:
        'Start by defining acceptance criteria: reusable checks with a standard reference, a method, a unit and a tolerance. Raise an inspection against a criterion, set its type and the party doing the check, link it to the activity or BIM element, and record the result as pass, fail or conditional. A fail raises a non-conformance automatically, so the defect keeps its link to the check that found it.',
      spotlightSelector: '[data-testid="cc-tab-inspections"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.construction-control.materials.title',
      titleDefault: 'Materials and lab tests',
      bodyKey: 'guide.construction-control.materials.body',
      bodyDefault:
        'Log a material certificate as a digital passport: manufacturer, supplier, certificate type, CE or UKCA marking, and the batch, heat or lot number plus a validity window so expiry is flagged. Review each material for conformity, and record lab test results from an accredited lab with the test method and measured value. A rejected material or a failed test raises a linked non-conformance.',
      spotlightSelector: '[data-testid="cc-tab-materials"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.construction-control.asbuilt.title',
      titleDefault: 'As-built records and tolerance',
      bodyKey: 'guide.construction-control.asbuilt.body',
      bodyDefault:
        'Capture how a finished element was actually built. Record the survey, with the capture method, instrument and accuracy, or import it straight from a point-cloud scan. The measured value is checked against the criterion tolerance, an out-of-tolerance result raises a workmanship non-conformance, and once a record is verified you can e-sign it so it stands as a legal as-built.',
      spotlightSelector: '[data-testid="cc-tab-asbuilt"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.construction-control.gates.title',
      titleDefault: 'Hold and witness gates',
      bodyKey: 'guide.construction-control.gates.body',
      bodyDefault:
        'Set hold, witness, surveillance or review points that gate the work. A gate names the party role that must release it and can block progress on an activity until it is cleared. Hold gates must be released by that party; witness, surveillance and review gates can be waived with a reason. Use the proceed check to see whether an activity is clear to continue or is still blocked.',
      spotlightSelector: '[data-testid="cc-tab-gates"]',
    },
    {
      icon: 'Send',
      titleKey: 'guide.construction-control.handover.title',
      titleDefault: 'Handover and acceptance',
      bodyKey: 'guide.construction-control.handover.body',
      bodyDefault:
        'Build a handover package for the right completion regime - taking-over, substantial or practical completion. Assemble pulls every piece of acceptance evidence into one manifest and recomputes the gate. The gate stays blocked while non-conformances or hold points are open; once it is clear, or a manager overrides it on record, you e-sign and issue the acceptance certificate.',
      spotlightSelector: '[data-testid="cc-tab-handover"]',
    },
  ],
  ctaKey: 'guide.construction-control.cta',
  ctaDefault: 'Pick a project to start a check',
};
