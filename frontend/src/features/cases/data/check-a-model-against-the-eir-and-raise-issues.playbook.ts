// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Check a model against the EIR and raise issues".
//
// Open the information requirements, check a delivered model against them for
// naming, classification, LOD and properties, raise a BCF issue on every gap and
// sign off only what passes. Content strings key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "check-a-model-against-the-eir-and-raise-issues",
  order: 1014,
  category: "bim",
  companyTypes: ["bim-consultant", "developer-client", "project-manager"],
  icon: "BadgeCheck",
  titleKey: "cases.check_a_model_against_the_eir_and_raise_issues.title",
  titleDefault: "Check a model against the EIR and raise issues",
  descKey: "cases.check_a_model_against_the_eir_and_raise_issues.desc",
  descDefault:
    "Open the information requirements, check a delivered model against them for naming, classification, level of detail and required properties, raise a BCF issue on every gap and sign off only what passes.",
  longDescKey: "cases.check_a_model_against_the_eir_and_raise_issues.longdesc",
  longDescDefault:
    "A model can look right and still be useless if it does not carry the data the client asked for. Checking against the information requirements - the ISO 19650 EIR - is how you tell a model that only looks finished from one you can actually build and operate from.",
  estMinutes: 11,
  steps: [
    {
      id: "eir",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.in.eir", label: "Information requirements" },
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.in.model", label: "Delivered model" },
      ],
      outputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.out.checklist", label: "Requirement checklist" },
      ],
      titleKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.title",
      titleDefault: "Open the requirements",
      whatKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.what",
      whatDefault:
        "Open the information requirements the model is meant to satisfy - the naming convention, classification, level of information need and the properties each element must carry.",
      whyKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.eir.why",
      whyDefault:
        "You cannot check a model against a standard you have not opened. Starting from the actual requirements turns a vague review into a definite pass or fail on each point.",
      moduleLabel: "EIR Matrix",
      moduleLabelKey: "nav.eir_matrix",
      to: "/requirements/matrix",
    },
    {
      id: "check",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.check.in.checklist", label: "Requirement checklist" },
      ],
      outputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.check.out.findings", label: "Findings against each" },
      ],
      titleKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.check.title",
      titleDefault: "Check the model against them",
      whatKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.check.what",
      whatDefault:
        "Work through the model checking naming, classification codes, level of detail and the required properties on each element type against the requirement.",
      whyKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.check.why",
      whyDefault:
        "A missing classification or an empty property field breaks the takeoff and the asset handover downstream. Catching it at delivery is far cheaper than finding it when it is needed.",
      moduleLabel: "Model Review",
      moduleLabelKey: "nav.model_review",
      to: "/model-review",
    },
    {
      id: "issues",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.issues.in.findings", label: "Findings" },
      ],
      outputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.issues.out.bcf", label: "BCF issues raised" },
      ],
      titleKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.issues.title",
      titleDefault: "Raise an issue per gap",
      whatKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.issues.what",
      whatDefault:
        "Raise a BCF issue for every gap against a requirement, pointing at the element and naming what is missing, so the author has a precise list to fix.",
      whyKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.issues.why",
      whyDefault:
        "A precise issue gets fixed; a vague complaint that the model is not compliant gets argued. Tying each issue to a requirement and an element removes the room for debate.",
      moduleLabel: "Model Issues",
      moduleLabelKey: "nav.model_issues",
      to: "/bcf",
    },
    {
      id: "sign",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.sign.in.fixed", label: "Resolved issues" },
      ],
      outputs: [
        { labelKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.sign.out.accepted", label: "Requirement signed off" },
      ],
      titleKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.sign.title",
      titleDefault: "Sign off what passes",
      whatKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.sign.what",
      whatDefault:
        "Sign off a requirement only once the model actually meets it, so the matrix records true acceptance rather than a hopeful tick.",
      whyKey: "cases.check_a_model_against_the_eir_and_raise_issues.step.sign.why",
      whyDefault:
        "Sign-off is the gate that protects everyone downstream. Holding it until the model really complies is what stops a data gap being inherited by the estimator and the operator.",
      moduleLabel: "EIR Matrix",
      moduleLabelKey: "nav.eir_matrix",
      to: "/requirements/matrix",
    },
  ],
};

export default playbook;
