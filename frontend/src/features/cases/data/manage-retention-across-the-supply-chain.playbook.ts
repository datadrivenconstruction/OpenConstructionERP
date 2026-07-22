// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage retention across the supply chain".
//
// Capture the retention terms both ways, track what you hold on subcontractors,
// release at the right milestones and reconcile the whole ledger so nothing is
// forgotten. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-retention-across-the-supply-chain",
  order: 1025,
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "subcontractor"],
  icon: "Percent",
  titleKey: "cases.manage_retention_across_the_supply_chain.title",
  titleDefault: "Manage retention across the supply chain",
  descKey: "cases.manage_retention_across_the_supply_chain.desc",
  descDefault:
    "Capture the retention terms both ways, track what you hold on each subcontractor, release it at the right milestones and reconcile the whole ledger so no retention is quietly forgotten.",
  longDescKey: "cases.manage_retention_across_the_supply_chain.longdesc",
  longDescDefault:
    "Retention is money that sits still for years and then goes missing. The client holds it on you, you hold it on your subs, and the release dates are all different. Managed loosely it becomes a write-off; managed tightly it is cash that comes home on time in both directions.",
  estMinutes: 11,
  steps: [
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.terms.in.main", label: "Main contract" },
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.terms.in.subs", label: "Subcontracts" },
      ],
      outputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.terms.out.terms", label: "Retention terms captured" },
      ],
      titleKey: "cases.manage_retention_across_the_supply_chain.step.terms.title",
      titleDefault: "Capture the terms both ways",
      whatKey: "cases.manage_retention_across_the_supply_chain.step.terms.what",
      whatDefault:
        "Record the retention percentage, the cap and the release triggers in the main contract and in each subcontract, so you know exactly what is held on you and what you hold on others.",
      whyKey: "cases.manage_retention_across_the_supply_chain.step.terms.why",
      whyDefault:
        "Retention terms differ contract by contract. Capturing them up front is what lets you chase your own release and time your subs' releases instead of discovering the dates by accident.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "track",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.track.in.terms", label: "Retention terms" },
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.track.in.valuations", label: "Subcontractor valuations" },
      ],
      outputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.track.out.held", label: "Retention held per sub" },
      ],
      titleKey: "cases.manage_retention_across_the_supply_chain.step.track.title",
      titleDefault: "Track what you hold",
      whatKey: "cases.manage_retention_across_the_supply_chain.step.track.what",
      whatDefault:
        "Track the retention held on each subcontractor as it builds up through their valuations, so the total held is a live figure, not a number reconstructed at year end.",
      whyKey: "cases.manage_retention_across_the_supply_chain.step.track.why",
      whyDefault:
        "Retention held is your cash and your liability at once. Knowing the live figure per sub is what lets you release fairly and avoid paying out more than you ever withheld.",
      moduleLabel: "Subcontractors",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "release",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.release.in.held", label: "Retention held" },
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.release.in.milestones", label: "Release milestones" },
      ],
      outputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.release.out.released", label: "Timely releases" },
      ],
      titleKey: "cases.manage_retention_across_the_supply_chain.step.release.title",
      titleDefault: "Release at the milestones",
      whatKey: "cases.manage_retention_across_the_supply_chain.step.release.what",
      whatDefault:
        "Trigger the releases at practical completion and the end of the defects period, chasing what the client owes you and paying out what you owe your subs on the due dates.",
      whyKey: "cases.manage_retention_across_the_supply_chain.step.release.why",
      whyDefault:
        "A subcontractor whose retention is released on time is one who comes back for the next job and back to fix a defect. Holding it past the trigger sours the relationship and invites a claim.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "reconcile",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.reconcile.in.released", label: "Releases and holdings" },
      ],
      outputs: [
        { labelKey: "cases.manage_retention_across_the_supply_chain.step.reconcile.out.balanced", label: "Reconciled retention" },
      ],
      titleKey: "cases.manage_retention_across_the_supply_chain.step.reconcile.title",
      titleDefault: "Reconcile the ledger",
      whatKey: "cases.manage_retention_across_the_supply_chain.step.reconcile.what",
      whatDefault:
        "Reconcile retention held against retention released across the whole account, so any balance still outstanding on either side is visible and chased rather than written off.",
      whyKey: "cases.manage_retention_across_the_supply_chain.step.reconcile.why",
      whyDefault:
        "The retention nobody reconciles is the retention nobody recovers. A clean ledger is what turns a forgotten liability into cash that actually finds its way back to the business.",
      moduleLabel: "Reconciliation",
      moduleLabelKey: "nav.reconciliation",
      to: "/projects/:projectId/reconciliation",
    },
  ],
};

export default playbook;
