// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Write the basis of estimate".
//
// Capture the assumptions, inclusions, exclusions and qualifications behind a
// price and issue them with it, so the number is read in context. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "write-the-basis-of-estimate",
  order: 1005,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "subcontractor"],
  icon: "NotebookPen",
  titleKey: "cases.write_the_basis_of_estimate.title",
  titleDefault: "Write the basis of estimate",
  descKey: "cases.write_the_basis_of_estimate.desc",
  descDefault:
    "Capture the assumptions, inclusions, exclusions and qualifications behind a price and issue them with the number, so it is read in context instead of as a bare figure.",
  longDescKey: "cases.write_the_basis_of_estimate.longdesc",
  longDescDefault:
    "A price without its basis is an accident waiting to happen. Two estimators pricing the same job to different assumptions produce different numbers, and the gap only surfaces on site as a claim. The basis of estimate is the cheapest insurance in the whole process.",
  estMinutes: 9,
  steps: [
    {
      id: "assumptions",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.assumptions.in.docs", label: "Documents priced" },
        { labelKey: "cases.write_the_basis_of_estimate.step.assumptions.in.info", label: "Information gaps" },
      ],
      outputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.assumptions.out.assumptions", label: "Stated assumptions" },
      ],
      titleKey: "cases.write_the_basis_of_estimate.step.assumptions.title",
      titleDefault: "Capture the assumptions",
      whatKey: "cases.write_the_basis_of_estimate.step.assumptions.what",
      whatDefault:
        "Record which drawings and revisions you priced, the method and programme you assumed, the ground and access you took for granted, and every gap you filled with a judgement.",
      whyKey: "cases.write_the_basis_of_estimate.step.assumptions.why",
      whyDefault:
        "The assumptions are where the risk lives. Writing them down turns a silent bet into an agreed position and gives you the ground to stand on when the design that lands is not the one you priced.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "inout",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.inout.in.scope", label: "Priced scope" },
      ],
      outputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.inout.out.inclusions", label: "Inclusions and exclusions" },
        { labelKey: "cases.write_the_basis_of_estimate.step.inout.out.quals", label: "Qualifications" },
      ],
      titleKey: "cases.write_the_basis_of_estimate.step.inout.title",
      titleDefault: "List inclusions and exclusions",
      whatKey: "cases.write_the_basis_of_estimate.step.inout.what",
      whatDefault:
        "Set out plainly what the price includes, what it excludes and the qualifications that condition it, so there is no doubt on either side about what was bought.",
      whyKey: "cases.write_the_basis_of_estimate.step.inout.why",
      whyDefault:
        "Most disputes are not about the rate, they are about whether an item was in or out. A clear inclusions and exclusions list settles that before it becomes a variation argument.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "link",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.link.in.basis", label: "Basis document" },
        { labelKey: "cases.write_the_basis_of_estimate.step.link.in.bill", label: "Priced bill" },
      ],
      outputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.link.out.linked", label: "Basis linked to bill" },
      ],
      titleKey: "cases.write_the_basis_of_estimate.step.link.title",
      titleDefault: "Link it to the bill",
      whatKey: "cases.write_the_basis_of_estimate.step.link.what",
      whatDefault:
        "Tie the basis to the bill it explains, so anyone opening the price can read the assumptions that produced it without hunting through email.",
      whyKey: "cases.write_the_basis_of_estimate.step.link.why",
      whyDefault:
        "A basis that lives apart from the bill gets lost. Kept together, the two travel through review, award and delivery as one story about what was priced and why.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "issue",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.issue.in.linked", label: "Bill and basis" },
      ],
      outputs: [
        { labelKey: "cases.write_the_basis_of_estimate.step.issue.out.issued", label: "Issued together" },
      ],
      titleKey: "cases.write_the_basis_of_estimate.step.issue.title",
      titleDefault: "Issue it with the price",
      whatKey: "cases.write_the_basis_of_estimate.step.issue.what",
      whatDefault:
        "Issue the basis alongside the price in the estimate report, so the client reads the number and the ground it stands on at the same time.",
      whyKey: "cases.write_the_basis_of_estimate.step.issue.why",
      whyDefault:
        "A number sent on its own gets treated as gospel and then disputed. Sent with its basis, it invites the right conversation about scope and risk before anyone commits.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
