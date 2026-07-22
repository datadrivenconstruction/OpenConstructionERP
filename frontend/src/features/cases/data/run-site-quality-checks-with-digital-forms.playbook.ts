// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run site quality checks with digital forms".
//
// Build the quality checklist from the specification, complete it on site with
// photos, flag the fails to the quality system and keep the completed checks as
// the record. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-site-quality-checks-with-digital-forms",
  order: 1023,
  category: "quality",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  icon: "ClipboardCheck",
  titleKey: "cases.run_site_quality_checks_with_digital_forms.title",
  titleDefault: "Run site quality checks with digital forms",
  descKey: "cases.run_site_quality_checks_with_digital_forms.desc",
  descDefault:
    "Build the quality checklist from the specification, complete it on site with photos and sign-off, flag the fails to the quality system and keep every completed check as part of the record.",
  longDescKey: "cases.run_site_quality_checks_with_digital_forms.longdesc",
  longDescDefault:
    "A quality check done on paper and stuffed in a drawer proves nothing and helps no one. The same check done on a digital form is instantly a searchable, photographed, timestamped record that builds the handover pack as the work goes in rather than in a panic at the end.",
  estMinutes: 9,
  steps: [
    {
      id: "build",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.build.in.spec", label: "Specification and ITP" },
      ],
      outputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.build.out.form", label: "Digital checklist" },
      ],
      titleKey: "cases.run_site_quality_checks_with_digital_forms.step.build.title",
      titleDefault: "Build the checklist",
      whatKey: "cases.run_site_quality_checks_with_digital_forms.step.build.what",
      whatDefault:
        "Build the check as a digital form straight from the specification and the inspection and test plan, so it asks exactly the acceptance criteria the work has to meet.",
      whyKey: "cases.run_site_quality_checks_with_digital_forms.step.build.why",
      whyDefault:
        "A checklist that mirrors the specification is a checklist that catches real defects. One made up from memory misses the clause that matters and passes work that should have failed.",
      moduleLabel: "Forms",
      moduleLabelKey: "nav.forms",
      to: "/forms",
    },
    {
      id: "complete",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.in.form", label: "Digital checklist" },
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.in.work", label: "Completed work" },
      ],
      outputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.out.record", label: "Completed check" },
      ],
      titleKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.title",
      titleDefault: "Complete it on site",
      whatKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.what",
      whatDefault:
        "Complete the check at the workface with photos and the inspector sign-off, capturing the result where the work is rather than back in the office from memory.",
      whyKey: "cases.run_site_quality_checks_with_digital_forms.step.complete.why",
      whyDefault:
        "A check completed at the point of work, with a photo and a time on it, is evidence. One filled in later is a guess dressed up as a record, and it falls apart under scrutiny.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "flag",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.flag.in.record", label: "Completed check" },
      ],
      outputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.flag.out.actions", label: "Fails routed for fix" },
      ],
      titleKey: "cases.run_site_quality_checks_with_digital_forms.step.flag.title",
      titleDefault: "Flag the fails",
      whatKey: "cases.run_site_quality_checks_with_digital_forms.step.flag.what",
      whatDefault:
        "Route the failed items into the quality system as actions to put right, with the photo and the failed criterion attached, so nothing that failed a check is quietly built over.",
      whyKey: "cases.run_site_quality_checks_with_digital_forms.step.flag.why",
      whyDefault:
        "A failed check with no follow-up is worse than no check, because it records that you knew. Turning fails into tracked actions is what closes the loop between finding a defect and fixing it.",
      moduleLabel: "Quality",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "record",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.record.in.checks", label: "Completed checks" },
      ],
      outputs: [
        { labelKey: "cases.run_site_quality_checks_with_digital_forms.step.record.out.pack", label: "Quality record" },
      ],
      titleKey: "cases.run_site_quality_checks_with_digital_forms.step.record.title",
      titleDefault: "Keep the record",
      whatKey: "cases.run_site_quality_checks_with_digital_forms.step.record.what",
      whatDefault:
        "Keep the completed checks together as the running quality record, so the evidence for each element is filed and ready long before the handover pack is due.",
      whyKey: "cases.run_site_quality_checks_with_digital_forms.step.record.why",
      whyDefault:
        "Quality records assembled as you go are complete and cheap. The same records reconstructed at handover are full of holes and cost weeks of chasing signatures for work long since covered.",
      moduleLabel: "Quality",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
  ],
};

export default playbook;
