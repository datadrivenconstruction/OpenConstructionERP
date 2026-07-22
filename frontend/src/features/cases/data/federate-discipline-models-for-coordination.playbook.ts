// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Federate discipline models for coordination".
//
// Gather the latest model from each discipline, combine them into one aligned
// federation, walk it in a coordination review and raise a BCF issue on every
// conflict. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "federate-discipline-models-for-coordination",
  order: 1013,
  category: "bim",
  companyTypes: ["bim-consultant", "general-contractor", "designer"],
  icon: "Network",
  titleKey: "cases.federate_discipline_models_for_coordination.title",
  titleDefault: "Federate discipline models for coordination",
  descKey: "cases.federate_discipline_models_for_coordination.desc",
  descDefault:
    "Gather the latest model from each discipline, combine them into one aligned federation, walk it in a coordination review and raise a BCF issue on every conflict for the discipline that owns it.",
  longDescKey: "cases.federate_discipline_models_for_coordination.longdesc",
  longDescDefault:
    "No single discipline model shows the building. The clashes live in the gaps between architecture, structure and services, and they only appear when the models sit in one coordinate system together. Federation is the step that makes those gaps visible before they are built.",
  estMinutes: 12,
  steps: [
    {
      id: "gather",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.gather.in.models", label: "Discipline models" },
        { labelKey: "cases.federate_discipline_models_for_coordination.step.gather.in.status", label: "Issue status" },
      ],
      outputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.gather.out.set", label: "Current model set" },
      ],
      titleKey: "cases.federate_discipline_models_for_coordination.step.gather.title",
      titleDefault: "Gather the latest models",
      whatKey: "cases.federate_discipline_models_for_coordination.step.gather.what",
      whatDefault:
        "Pull the latest issued model from each discipline and confirm you have the right revision of every one, so the federation reflects where the design actually is.",
      whyKey: "cases.federate_discipline_models_for_coordination.step.gather.why",
      whyDefault:
        "Federating a stale structural model wastes everyone's review. Getting the current revision of each discipline first is what makes the clashes you find real and worth fixing.",
      moduleLabel: "Files",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "federate",
      icon: "Network",
      inputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.federate.in.set", label: "Model set" },
      ],
      outputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.federate.out.federation", label: "Federated model" },
      ],
      titleKey: "cases.federate_discipline_models_for_coordination.step.federate.title",
      titleDefault: "Combine into a federation",
      whatKey: "cases.federate_discipline_models_for_coordination.step.federate.what",
      whatDefault:
        "Combine the discipline models into one federation and confirm their origins and coordinates line up, so an element sits where it really is against every other trade.",
      whyKey: "cases.federate_discipline_models_for_coordination.step.federate.why",
      whyDefault:
        "A misaligned origin makes everything look like it clashes and hides the clashes that matter. Getting the models onto one coordinate system is the whole point of federating.",
      moduleLabel: "BIM Federations",
      moduleLabelKey: "nav.bim_federations",
      to: "/bim/federations",
    },
    {
      id: "review",
      icon: "Box",
      inputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.review.in.federation", label: "Federated model" },
      ],
      outputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.review.out.conflicts", label: "Conflicts found" },
      ],
      titleKey: "cases.federate_discipline_models_for_coordination.step.review.title",
      titleDefault: "Walk the coordination review",
      whatKey: "cases.federate_discipline_models_for_coordination.step.review.what",
      whatDefault:
        "Walk the federated model zone by zone with the design team, looking for the clashes, tight spots and buildability problems the separate models could never show.",
      whyKey: "cases.federate_discipline_models_for_coordination.step.review.why",
      whyDefault:
        "The coordination review is where trades meet before the concrete does. An hour around the federated model saves the rework of a duct that has nowhere to go once the slab is poured.",
      moduleLabel: "Coordination",
      moduleLabelKey: "nav.coordination_hub",
      to: "/coordination",
    },
    {
      id: "issues",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.issues.in.conflicts", label: "Conflicts found" },
      ],
      outputs: [
        { labelKey: "cases.federate_discipline_models_for_coordination.step.issues.out.bcf", label: "BCF issues raised" },
      ],
      titleKey: "cases.federate_discipline_models_for_coordination.step.issues.title",
      titleDefault: "Raise a BCF issue for each",
      whatKey: "cases.federate_discipline_models_for_coordination.step.issues.what",
      whatDefault:
        "Raise a BCF issue on each conflict with the viewpoint and the responsible discipline, so every one becomes a tracked action rather than a note in a meeting.",
      whyKey: "cases.federate_discipline_models_for_coordination.step.issues.why",
      whyDefault:
        "A clash spotted and forgotten is a clash built. A BCF issue with an owner and a viewpoint is what turns a review into resolved coordination instead of a nice look at the model.",
      moduleLabel: "Model Issues",
      moduleLabelKey: "nav.model_issues",
      to: "/bcf",
    },
  ],
};

export default playbook;
