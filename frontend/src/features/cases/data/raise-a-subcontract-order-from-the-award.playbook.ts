// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Raise a subcontract order from the award".
//
// Turn a winning bid into a subcontract order: confirm scope and rates, raise
// the order, attach programme and terms to the subcontractor, and issue the
// contract for signature. Content strings are key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "raise-a-subcontract-order-from-the-award",
  order: 1009,
  category: "tendering",
  companyTypes: ["general-contractor", "project-manager", "cost-consultant"],
  icon: "Handshake",
  titleKey: "cases.raise_a_subcontract_order_from_the_award.title",
  titleDefault: "Raise a subcontract order from the award",
  descKey: "cases.raise_a_subcontract_order_from_the_award.desc",
  descDefault:
    "Turn a winning bid into a live subcontract order: confirm the agreed scope and rates, raise the order, attach the programme and payment terms, and issue the contract for signature.",
  longDescKey: "cases.raise_a_subcontract_order_from_the_award.longdesc",
  longDescDefault:
    "Award is a decision; the order is the commitment. The gap between the two is where scope drifts and terms get vague. Building the subcontract straight off the awarded bid keeps the deal you agreed and the deal you sign as the same deal.",
  estMinutes: 11,
  steps: [
    {
      id: "award",
      icon: "Trophy",
      inputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.award.in.bid", label: "Awarded bid" },
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.award.in.scope", label: "Agreed scope" },
      ],
      outputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.award.out.confirmed", label: "Confirmed deal" },
      ],
      titleKey: "cases.raise_a_subcontract_order_from_the_award.step.award.title",
      titleDefault: "Confirm the award",
      whatKey: "cases.raise_a_subcontract_order_from_the_award.step.award.what",
      whatDefault:
        "Open the awarded bid and confirm the final scope, rates and any post-tender agreements, so the order is raised against the deal that was actually struck.",
      whyKey: "cases.raise_a_subcontract_order_from_the_award.step.award.why",
      whyDefault:
        "Post-tender negotiations change numbers that the original bid still shows. Confirming the settled position first is what stops the wrong figure being written into the contract.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "order",
      icon: "PackageCheck",
      inputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.order.in.confirmed", label: "Confirmed deal" },
      ],
      outputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.order.out.order", label: "Subcontract order" },
      ],
      titleKey: "cases.raise_a_subcontract_order_from_the_award.step.order.title",
      titleDefault: "Raise the order",
      whatKey: "cases.raise_a_subcontract_order_from_the_award.step.order.what",
      whatDefault:
        "Raise the purchase or subcontract order straight from the award, carrying the priced scope so the committed value ties back to the bill and the budget.",
      whyKey: "cases.raise_a_subcontract_order_from_the_award.step.order.why",
      whyDefault:
        "An order built from the award keeps the commitment stitched to the estimate. Rekeying it by hand is where a rate gets transposed and a package quietly overspends.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.in.order", label: "Subcontract order" },
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.in.programme", label: "Package programme" },
      ],
      outputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.out.record", label: "Subcontractor record" },
      ],
      titleKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.title",
      titleDefault: "Attach programme and terms",
      whatKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.what",
      whatDefault:
        "Attach the package programme dates, the payment terms, retention and the key obligations to the subcontractor record, so the deal is complete rather than just a price.",
      whyKey: "cases.raise_a_subcontract_order_from_the_award.step.terms.why",
      whyDefault:
        "A price with no dates and no terms is where disputes start. Pinning the programme and the payment mechanism to the order now saves the argument later.",
      moduleLabel: "Subcontractors",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "issue",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.issue.in.record", label: "Complete order" },
      ],
      outputs: [
        { labelKey: "cases.raise_a_subcontract_order_from_the_award.step.issue.out.executed", label: "Executed contract" },
      ],
      titleKey: "cases.raise_a_subcontract_order_from_the_award.step.issue.title",
      titleDefault: "Issue for signature",
      whatKey: "cases.raise_a_subcontract_order_from_the_award.step.issue.what",
      whatDefault:
        "Issue the subcontract for signature and file the executed copy against the project, so the commitment is contractually live before the trade starts on site.",
      whyKey: "cases.raise_a_subcontract_order_from_the_award.step.issue.why",
      whyDefault:
        "A subcontractor working without a signed order is a risk to both sides. Getting the contract executed before mobilisation is the discipline that keeps the package governable.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
