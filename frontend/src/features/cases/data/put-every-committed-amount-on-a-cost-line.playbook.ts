// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Put every committed amount on a cost line".
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "put-every-committed-amount-on-a-cost-line",
  order: 1701,
  category: "commercial",
  stage: "build",
  companyTypes: ["developer-client", "cost-consultant", "general-contractor", "project-manager"],
  roles: ["commercial-manager", "quantity-surveyor", "procurement-buyer"],
  icon: "Combine",
  titleKey: "cases.put_every_committed_amount_on_a_cost_line.title",
  titleDefault: "Put every committed amount on a cost line",
  descKey: "cases.put_every_committed_amount_on_a_cost_line.desc",
  descDefault:
    "Award a contract or issue a purchase order, then make sure its money lands on the right cost line, so the awarded column and the forecast show the whole commitment.",
  longDescKey: "cases.put_every_committed_amount_on_a_cost_line.longdesc",
  longDescDefault:
    "The awarded amount of a cost line comes from the contracts and purchase orders placed against it. An order that was issued without a cost line still binds the money, but no line shows it, and the project looks cheaper than it is. Cost control lists every such line in one drawer and lets you put it where it belongs, then shows the result both by cost line and by contract.",
  estMinutes: 10,
  steps: [
    {
      id: "contract",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.contract.in.award", label: "Award decision" },
      ],
      outputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.contract.out.contract", label: "Signed contract with lines" },
      ],
      titleKey: "cases.put_every_committed_amount_on_a_cost_line.step.contract.title",
      titleDefault: "Award the contract",
      whatKey: "cases.put_every_committed_amount_on_a_cost_line.step.contract.what",
      whatDefault:
        "In Contracts, set up the subcontract with its lines and amounts, then press Sign. A contract still in Draft binds no money and does not show in cost control.",
      whyKey: "cases.put_every_committed_amount_on_a_cost_line.step.contract.why",
      whyDefault:
        "A signed contract is the largest commitment the project makes. Its lines are what the awarded column of cost control is built from.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "order",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.order.in.need", label: "Material need" },
      ],
      outputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.order.out.po", label: "Issued purchase order" },
      ],
      titleKey: "cases.put_every_committed_amount_on_a_cost_line.step.order.title",
      titleDefault: "Issue the purchase order",
      whatKey: "cases.put_every_committed_amount_on_a_cost_line.step.order.what",
      whatDefault:
        "In Procurement, issue purchase orders for material and services bought outside the subcontracts, with exact quantities and unit prices.",
      whyKey: "cases.put_every_committed_amount_on_a_cost_line.step.order.why",
      whyDefault:
        "Smaller orders add up. Each issued order counts as committed money, so it belongs in the forecast as much as a contract does.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "assign",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.assign.in.po", label: "Issued purchase order" },
      ],
      outputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.assign.out.assigned", label: "Money on cost lines" },
      ],
      titleKey: "cases.put_every_committed_amount_on_a_cost_line.step.assign.title",
      titleDefault: "Assign the money to cost lines",
      whatKey: "cases.put_every_committed_amount_on_a_cost_line.step.assign.what",
      whatDefault:
        "Open Cost control. The finding Committed money is not on any cost line opens a drawer that lists every unassigned contract and order line. Pick a cost line for each, or one for all.",
      whyKey: "cases.put_every_committed_amount_on_a_cost_line.step.assign.why",
      whyDefault:
        "Once every amount sits on a line, the finding disappears and the drawer says Every line is on a cost line. That sentence is what you are aiming for.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "bycontract",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.bycontract.in.assigned", label: "Money on cost lines" },
      ],
      outputs: [
        { labelKey: "cases.put_every_committed_amount_on_a_cost_line.step.bycontract.out.check", label: "Commitments checked per contract" },
      ],
      titleKey: "cases.put_every_committed_amount_on_a_cost_line.step.bycontract.title",
      titleDefault: "Check the view by contract",
      whatKey: "cases.put_every_committed_amount_on_a_cost_line.step.bycontract.what",
      whatDefault:
        "Switch the table to By contract and check awarded, changes, certified and paid per contract, and the row for purchase orders and other commitments.",
      whyKey: "cases.put_every_committed_amount_on_a_cost_line.step.bycontract.why",
      whyDefault:
        "The view by contract is how a contractor's account reads. It is the quickest way to see that nothing was assigned twice or left out.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
  ],
};

export default playbook;
