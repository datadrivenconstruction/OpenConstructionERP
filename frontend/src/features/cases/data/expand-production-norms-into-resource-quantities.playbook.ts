// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Expand production norms into resource quantities".
//
// Take a production norm per unit, expand it across the takeoff quantity into
// labour, plant and material, roll it up by trade and price it. The normative
// estimating method. Content strings are key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "expand-production-norms-into-resource-quantities",
  order: 1006,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  icon: "Combine",
  titleKey: "cases.expand_production_norms_into_resource_quantities.title",
  titleDefault: "Expand production norms into resource quantities",
  descKey: "cases.expand_production_norms_into_resource_quantities.desc",
  descDefault:
    "Take a production norm per unit, expand it across the takeoff quantity into labour, plant and material, roll the resources up by trade and carry the resourced rate into the bill.",
  longDescKey: "cases.expand_production_norms_into_resource_quantities.longdesc",
  longDescDefault:
    "Normative estimating prices from the ground up: a norm says how much labour, plant and material one unit of work consumes, and the takeoff says how many units there are. It is how much of the world outside price-book markets estimates, and it stays honest because every rate is a resource build-up you can inspect.",
  estMinutes: 11,
  steps: [
    {
      id: "pick",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.pick.in.item", label: "Work item" },
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.pick.in.norms", label: "Norm library" },
      ],
      outputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.pick.out.norm", label: "Chosen norm" },
      ],
      titleKey: "cases.expand_production_norms_into_resource_quantities.step.pick.title",
      titleDefault: "Pick the norm",
      whatKey: "cases.expand_production_norms_into_resource_quantities.step.pick.what",
      whatDefault:
        "Find the production norm that matches the work item and the conditions - the trade, the material, the difficulty - so the consumption per unit reflects how the job will really be built.",
      whyKey: "cases.expand_production_norms_into_resource_quantities.step.pick.why",
      whyDefault:
        "A norm chosen for the wrong conditions carries the error into every unit. Matching the norm to the actual work is where the accuracy of the whole build-up is won or lost.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "expand",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.expand.in.norm", label: "Chosen norm" },
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.expand.in.quantity", label: "Takeoff quantity" },
      ],
      outputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.expand.out.resources", label: "Labour, plant, material" },
      ],
      titleKey: "cases.expand_production_norms_into_resource_quantities.step.expand.title",
      titleDefault: "Expand across the quantity",
      whatKey: "cases.expand_production_norms_into_resource_quantities.step.expand.what",
      whatDefault:
        "Multiply the norm by the takeoff quantity to explode the item into the hours of labour, hours of plant and units of material it will actually consume.",
      whyKey: "cases.expand_production_norms_into_resource_quantities.step.expand.why",
      whyDefault:
        "Seeing the raw resource demand, not just a rate, is what lets you sanity check it against your crews and plant. A rate hides an impossible labour figure; the expansion shows it.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "summarise",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.summarise.in.resources", label: "Expanded resources" },
      ],
      outputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.summarise.out.bytrade", label: "Resources by trade" },
      ],
      titleKey: "cases.expand_production_norms_into_resource_quantities.step.summarise.title",
      titleDefault: "Roll it up by trade",
      whatKey: "cases.expand_production_norms_into_resource_quantities.step.summarise.what",
      whatDefault:
        "Gather the expanded resources across the whole bill into a summary by trade, so you can see total labour hours, plant hours and key material tonnages in one place.",
      whyKey: "cases.expand_production_norms_into_resource_quantities.step.summarise.why",
      whyDefault:
        "The resource summary is the reality check on the price. It tells you whether the labour you have priced can be manned and whether the material order matches the estimate.",
      moduleLabel: "Resource Summary",
      moduleLabelKey: "nav.resource_summary",
      to: "/resource-summary",
    },
    {
      id: "price",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.price.in.bytrade", label: "Resourced quantities" },
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.price.in.rates", label: "Resource rates" },
      ],
      outputs: [
        { labelKey: "cases.expand_production_norms_into_resource_quantities.step.price.out.rate", label: "Resourced unit rate" },
      ],
      titleKey: "cases.expand_production_norms_into_resource_quantities.step.price.title",
      titleDefault: "Carry the rate into the bill",
      whatKey: "cases.expand_production_norms_into_resource_quantities.step.price.what",
      whatDefault:
        "Price the resources at your labour, plant and material rates and carry the resulting unit rate into the bill, where it stands on a build-up you can defend line by line.",
      whyKey: "cases.expand_production_norms_into_resource_quantities.step.price.why",
      whyDefault:
        "A rate backed by a resource build-up survives scrutiny that a lump-sum guess does not. When a client challenges a price, you can open the norm and show exactly what it is made of.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
  ],
};

export default playbook;
