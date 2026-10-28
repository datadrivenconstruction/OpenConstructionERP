// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// requirementsGuide - "How it works" content for the EIR Matrix module.
// Consumed by <ModuleGuideButton content={requirementsGuide} /> on
// RequirementsMatrixPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const requirementsGuide: ModuleGuideContent = {
  titleKey: 'guide.requirements.title',
  titleDefault: 'EIR Matrix (ISO 19650)',
  introKey: 'guide.requirements.intro',
  introDefault:
    'The EIR Matrix proves that every information requirement on a project has been met. Rows are the requirements you write, columns are the ISO 19650 deliverables that satisfy them, and each cell turns green once the evidence is accepted.',
  sections: [
    {
      icon: 'Layers',
      titleKey: 'guide.requirements.sets.title',
      titleDefault: 'Start with a requirement set',
      bodyKey: 'guide.requirements.sets.body',
      bodyDefault:
        'A requirement set groups the requirements for one project, such as the structural information requirements for a stage. From an empty project, create a set first, give it a name and an optional description, then add the requirements that belong to it.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.requirements.rows.title',
      titleDefault: 'Write each requirement',
      bodyKey: 'guide.requirements.rows.body',
      bodyDefault:
        'Every row is one requirement expressed as an Entity, an Attribute and a Constraint, for example exterior wall, fire rating, equals F90. Set a priority of must, should or may, and add a unit, category or notes so the requirement is clear and testable.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.requirements.deliverables.title',
      titleDefault: 'Attach deliverables in the columns',
      bodyKey: 'guide.requirements.deliverables.body',
      bodyDefault:
        'The columns are the ISO 19650 deliverable types that prove a requirement: Model, Drawing, Schedule, Report, COBie and PSET. Click any cell to attach a deliverable and record its LOD, LOI and the submitted and accepted timestamps.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.requirements.coverage.title',
      titleDefault: 'Read the coverage heatmap',
      bodyKey: 'guide.requirements.coverage.body',
      bodyDefault:
        'Each cell is colour coded by status: green when accepted, amber when submitted and red when still missing. A coverage percentage is shown per row and rolled up for the whole project, so you can see at a glance how complete the evidence is.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.requirements.filter.title',
      titleDefault: 'Filter and open the source',
      bodyKey: 'guide.requirements.filter.body',
      bodyDefault:
        'Use the filters to narrow by requirement set, deliverable type or status when the matrix grows. Open deliverable jumps straight to the module that holds the evidence, the BIM viewer for a model, markups for a drawing or the schedule for a programme, and linked requirements deep-link to their BOQ position.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.requirements.review.title',
      titleDefault: 'Review and keep it current',
      bodyKey: 'guide.requirements.review.body',
      bodyDefault:
        'Edit or delete any requirement from the row actions, and rename or remove a set from the filter bar. Refresh pulls the latest deliverable status so the coverage score always reflects what has actually been submitted and accepted.',
    },
  ],
  ctaKey: 'guide.requirements.cta',
  ctaDefault: 'Create your first requirement set',
};
