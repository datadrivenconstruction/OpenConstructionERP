// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Choose and record the delivery model".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "choose-and-record-the-delivery-model",
  order: 1683,
  category: "tendering",
  stage: "define",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  roles: ["project-manager", "procurement-buyer", "contract-administrator"],
  requiresProject: true,
  icon: "Network",
  titleKey: "cases.choose_and_record_the_delivery_model.title",
  titleDefault: "Choose and record the delivery model",
  descKey: "cases.choose_and_record_the_delivery_model.desc",
  descDefault:
    "Compare delivery forms on weighted criteria, confirm who carries which risk, split the work into packages, list what the client supplies, and propose a decision the gate can approve.",
  longDescKey: "cases.choose_and_record_the_delivery_model.longdesc",
  longDescDefault:
    "Whether a building is delivered by separate trade contracts, a general contractor, design and build or a partnering model is decided early and felt for years. Delivery model keeps that decision honest: at least two forms are compared, the risk allocation is confirmed line by line, the package plan follows from the choice, and the decision itself is approved at the governance gate by someone other than the person who proposed it.",
  estMinutes: 15,
  steps: [
    {
      id: "compare",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.compare.in.catalogue", label: "Delivery form catalogue" },
      ],
      outputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.compare.out.scores", label: "Weighted comparison" },
      ],
      titleKey: "cases.choose_and_record_the_delivery_model.step.compare.title",
      titleDefault: "Compare the delivery forms",
      whatKey: "cases.choose_and_record_the_delivery_model.step.compare.what",
      whatDefault:
        "If the project has no delivery model yet, choose the catalogue and press Start delivery model. Then, on the Compare forms tab, press Add a form for at least two options, score them against the criteria and press Save weights.",
      whyKey: "cases.choose_and_record_the_delivery_model.step.compare.why",
      whyDefault:
        "A decision with only one option on the table is not a decision. Weighted criteria make it visible why one form won.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=comparison",
    },
    {
      id: "risks",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.risks.in.register", label: "Risk register" },
      ],
      outputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.risks.out.allocation", label: "Confirmed risk allocation" },
      ],
      titleKey: "cases.choose_and_record_the_delivery_model.step.risks.title",
      titleDefault: "Confirm the risk allocation",
      whatKey: "cases.choose_and_record_the_delivery_model.step.risks.what",
      whatDefault:
        "On the Risk allocation tab, read who carries each risk under the chosen form and confirm the rows, one by one or with Confirm all.",
      whyKey: "cases.choose_and_record_the_delivery_model.step.risks.why",
      whyDefault:
        "Risks that nobody confirmed end up with whoever is weakest in the dispute. A confirmed allocation is what the contracts will be drafted from.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=risks",
    },
    {
      id: "packages",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.packages.in.scope", label: "Project scope" },
      ],
      outputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.packages.out.packages", label: "Package plan" },
      ],
      titleKey: "cases.choose_and_record_the_delivery_model.step.packages.title",
      titleDefault: "Plan the packages",
      whatKey: "cases.choose_and_record_the_delivery_model.step.packages.what",
      whatDefault:
        "On the Package plan tab, press Add a package for each contract package and link it to a procurement record where one exists.",
      whyKey: "cases.choose_and_record_the_delivery_model.step.packages.why",
      whyDefault:
        "The package plan is what procurement buys. Getting the cut lines right avoids gaps and overlaps between contractors.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=packages",
    },
    {
      id: "ofi",
      icon: "Container",
      inputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.ofi.in.plant", label: "Plant and equipment" },
      ],
      outputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.ofi.out.ofi", label: "Owner-furnished items" },
      ],
      titleKey: "cases.choose_and_record_the_delivery_model.step.ofi.title",
      titleDefault: "List what the client supplies",
      whatKey: "cases.choose_and_record_the_delivery_model.step.ofi.what",
      whatDefault:
        "On the Owner-furnished items tab, press Add an item for every piece of equipment or material the client buys and hands to the contractor.",
      whyKey: "cases.choose_and_record_the_delivery_model.step.ofi.why",
      whyDefault:
        "Owner-furnished items are a frequent source of delay claims. Listing them makes the client's own delivery duties explicit.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=ofi",
    },
    {
      id: "decision",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.decision.in.scores", label: "Weighted comparison" },
      ],
      outputs: [
        { labelKey: "cases.choose_and_record_the_delivery_model.step.decision.out.record", label: "Delivery decision record" },
      ],
      titleKey: "cases.choose_and_record_the_delivery_model.step.decision.title",
      titleDefault: "Propose the decision",
      whatKey: "cases.choose_and_record_the_delivery_model.step.decision.what",
      whatDefault:
        "On the Compare forms tab, press Propose decision, pick the form and write why it was chosen. The Decision record tab then shows the proposal. It is approved at the governance gate, by a different person when four-eyes is on.",
      whyKey: "cases.choose_and_record_the_delivery_model.step.decision.why",
      whyDefault:
        "A written rationale is what keeps the decision standing when the project team changes. Approval at the gate makes it binding.",
      moduleLabel: "Delivery model",
      moduleLabelKey: "delivery_model.ui.title",
      to: "/projects/:projectId/delivery?tab=decision",
    },
  ],
};

export default playbook;
