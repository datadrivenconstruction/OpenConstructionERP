// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// qmsGuide - "How it works" content for the Quality Management module.
// Consumed by <ModuleGuideButton content={qmsGuide} /> on QMSPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const qmsGuide: ModuleGuideContent = {
  titleKey: 'guide.qms.title',
  titleDefault: 'Quality Management',
  introKey: 'guide.qms.intro',
  introDefault:
    'Quality Management keeps the whole ISO 9001 chain in one register instead of five separate silos. Plan the checks, sign them off, raise non-conformances when work fails, track the cost and close out every defect, all linked back to the plan it came from.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.qms.overview.title',
      titleDefault: 'One chain across five tabs',
      bodyKey: 'guide.qms.overview.body',
      bodyDefault:
        'The page is organised as ITP Plans, Inspections, NCRs, Punch List and Audits, and you work them left to right. Pick a project first, then use the search box and status filter at the top to narrow any tab. The same records appear in the standalone Inspections, NCRs and Punch List modules, so nothing is duplicated.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.qms.itp.title',
      titleDefault: 'ITP plans and hold points',
      bodyKey: 'guide.qms.itp.body',
      bodyDefault:
        'An Inspection and Test Plan defines the quality gates for a work package: its hold, witness and review points. Build the plan, then activate it so those control points become live gates. Open a plan to see the hold-point dependency tree showing what is cleared to proceed, and export an audit-ready compliance dossier to CSV.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.qms.inspections.title',
      titleDefault: 'Inspections and sign-off',
      bodyKey: 'guide.qms.inspections.body',
      bodyDefault:
        'Schedule an inspection against an ITP control point, then record the result when the work is checked: passed, failed or conditional. Signatures capture who signed off each hold or witness point. If an inspection fails, you can raise an NCR straight from it so the quality chain stays connected.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.qms.ncrs.title',
      titleDefault: 'NCRs and corrective actions',
      bodyKey: 'guide.qms.ncrs.body',
      bodyDefault:
        'A non-conformance report captures work that fails, with a severity of minor, major or critical and any cost impact. Assign corrective actions, verify each one as it is done, then close the NCR. Where the defect carries a cost, escalate it to a Variation against a real variation order so the money trail stays attached.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.qms.copq.title',
      titleDefault: 'Cost of Poor Quality',
      bodyKey: 'guide.qms.copq.body',
      bodyDefault:
        'On the NCRs tab a Cost of Poor Quality panel rolls up NCR cost, rework estimate and open punch count into one figure for the project. It gives you a live read on what quality issues are costing and feeds back into project cost reporting.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.qms.punch_audits.title',
      titleDefault: 'Punch list and audits',
      bodyKey: 'guide.qms.punch_audits.body',
      bodyDefault:
        'The Punch List tracks snags found on walkthroughs by category and severity, from open through assignment to close-out. The Audits tab runs internal, external and supplier audits over the management system itself, each with a finding register and an overall rating.',
    },
  ],
  ctaKey: 'guide.qms.cta',
  ctaDefault: 'Build your first ITP plan',
};
