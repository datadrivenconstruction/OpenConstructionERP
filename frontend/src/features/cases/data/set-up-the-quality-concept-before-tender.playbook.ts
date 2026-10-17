// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set up the quality concept before tender".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-up-the-quality-concept-before-tender",
  order: 1687,
  category: "quality",
  stage: "design",
  companyTypes: ["developer-client", "project-manager", "designer"],
  roles: ["project-manager", "design-lead"],
  requiresProject: true,
  icon: "BadgeCheck",
  titleKey: "cases.set_up_the_quality_concept_before_tender.title",
  titleDefault: "Set up the quality concept before tender",
  descKey: "cases.set_up_the_quality_concept_before_tender.desc",
  descDefault:
    "Record the standards and requirements, the certification targets, the proofs each package must deliver, the commissioning stages and the acceptance plan, and get the concept approved.",
  longDescKey: "cases.set_up_the_quality_concept_before_tender.longdesc",
  longDescDefault:
    "Quality that is defined after the contracts are signed is quality the client cannot demand. The quality concept sets out, before tender, which standards apply, which certification the building aims for, which proofs each package has to hand in, how commissioning is released stage by stage and how acceptance and the survey of existing conditions are done. Coverage is computed from the evidence linked during construction, never typed in.",
  estMinutes: 16,
  steps: [
    {
      id: "concept",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.concept.in.brief", label: "Client requirements" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.concept.out.concept", label: "Draft quality concept" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.concept.title",
      titleDefault: "Write the concept",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.concept.what",
      whatDefault:
        "Press Create quality concept, then add the standards, the requirements and the packages the concept covers.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.concept.why",
      whyDefault:
        "Standards and requirements written down now become contract obligations. Anything left out has to be bought later as a change.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept",
    },
    {
      id: "certification",
      icon: "Trophy",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.certification.in.target", label: "Certification target" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.certification.out.credits", label: "Credit tracker" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.certification.title",
      titleDefault: "Set the certification targets",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.certification.what",
      whatDefault:
        "On the Certification tab, add the certification target and its credits, register the target, then record the design assessment.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.certification.why",
      whyDefault:
        "A sustainability or quality label is won or lost in design. Tracking the credits from the start shows early if the target is slipping.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept?tab=certification",
    },
    {
      id: "proofs",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.proofs.in.packages", label: "Contract packages" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.proofs.out.prooflist", label: "Proof list per package" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.proofs.title",
      titleDefault: "Define the proofs per package",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.proofs.what",
      whatDefault:
        "On the Proofs tab, use Propose proofs for a package, check the preview and confirm, then add any proofs the proposal missed.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.proofs.why",
      whyDefault:
        "Every contractor should know at tender what they will have to prove. The proof list becomes part of the package documents.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept?tab=proofs",
    },
    {
      id: "stages",
      icon: "Workflow",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.stages.in.systems", label: "Building systems" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.stages.out.stageplan", label: "Commissioning stage plan" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.stages.title",
      titleDefault: "Plan commissioning stages",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.stages.what",
      whatDefault:
        "On the Commissioning stages tab, add the stages and how each one is released.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.stages.why",
      whyDefault:
        "Releasing commissioning stage by stage stops a building being handed over with systems that were never tested together.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept?tab=stages",
    },
    {
      id: "acceptance",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.acceptance.in.units", label: "Building units" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.acceptance.out.acceptance", label: "Acceptance plan" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.acceptance.title",
      titleDefault: "Plan acceptance and evidence",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.acceptance.what",
      whatDefault:
        "On the Acceptance tab add the acceptance units, and on the Evidence preservation tab plan the survey of existing conditions and any expert reports the project needs.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.acceptance.why",
      whyDefault:
        "Acceptance starts warranty periods and shifts risk, so it has to be planned unit by unit. A survey before work starts protects against claims from neighbours.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept?tab=acceptance",
    },
    {
      id: "approve",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.approve.in.concept", label: "Draft quality concept" },
      ],
      outputs: [
        { labelKey: "cases.set_up_the_quality_concept_before_tender.step.approve.out.approved", label: "Binding quality concept" },
      ],
      titleKey: "cases.set_up_the_quality_concept_before_tender.step.approve.title",
      titleDefault: "Submit and approve",
      whatKey: "cases.set_up_the_quality_concept_before_tender.step.approve.what",
      whatDefault:
        "Back on the Concept tab, press Submit for approval. On a project with governance gates the gate decision approves it. Without gates a second person presses Approve the concept.",
      whyKey: "cases.set_up_the_quality_concept_before_tender.step.approve.why",
      whyDefault:
        "An approved concept is the yardstick every inspection and every handover is measured against.",
      moduleLabel: "Quality concept",
      moduleLabelKey: "qualityConcept.title",
      to: "/projects/:projectId/quality-concept",
    },
  ],
};

export default playbook;
