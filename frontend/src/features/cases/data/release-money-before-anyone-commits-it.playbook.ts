// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Release money before anyone commits it".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "release-money-before-anyone-commits-it",
  order: 1682,
  category: "commercial",
  stage: "define",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  roles: ["commercial-manager", "project-manager", "finance-manager"],
  requiresProject: true,
  icon: "Coins",
  titleKey: "cases.release_money_before_anyone_commits_it.title",
  titleDefault: "Release money before anyone commits it",
  descKey: "cases.release_money_before_anyone_commits_it.desc",
  descDefault:
    "Set the authority tiers, add the items the project will commit money to, get each release approved by the right person, link the contract or order, and see what you would lose if you stopped today.",
  longDescKey: "cases.release_money_before_anyone_commits_it.longdesc",
  longDescDefault:
    "Most budgets do not overrun in one big decision. They leak through contracts and orders that were signed before anyone with authority agreed to them. Commitments and releases puts a gate in front of every commitment: the amount and type decide which approver tier applies, the approver cannot be the person who asked, and an award above the released amount warns or blocks depending on how strictly the project is set up.",
  estMinutes: 12,
  steps: [
    {
      id: "setup",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.setup.in.doa", label: "Delegation of authority" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.setup.out.tiers", label: "Approver per tier" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.setup.title",
      titleDefault: "Set the approval rules",
      whatKey: "cases.release_money_before_anyone_commits_it.step.setup.what",
      whatDefault:
        "Choose the authority schedule and how strictly releases are enforced (register only, warn or block), and press Start the commitment matrix. Then, on the Approval setup tab, name an approver for each tier and press Save approvers.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.setup.why",
      whyDefault:
        "The tiers come from the delegation of authority, so a small order and a main contract do not go to the same person. Choosing the enforcement level decides whether the system only records or actually stops a commitment.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments?tab=setup",
    },
    {
      id: "items",
      icon: "ListPlus",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.items.in.budget", label: "Cost plan" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.items.out.items", label: "Commitment items" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.items.title",
      titleDefault: "Add the commitment items",
      whatKey: "cases.release_money_before_anyone_commits_it.step.items.what",
      whatDefault:
        "On the Commitments tab, press Add item for each contract or order the project will place, with its amount and type.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.items.why",
      whyDefault:
        "An item is the promise to spend before the money is spent. Listing them early shows the whole commitment plan against the budget.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments",
    },
    {
      id: "request",
      icon: "Send",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.request.in.items", label: "Commitment items" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.request.out.request", label: "Release request" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.request.title",
      titleDefault: "Request the release",
      whatKey: "cases.release_money_before_anyone_commits_it.step.request.what",
      whatDefault:
        "Open an item and press Request release. The dialog shows who will decide before you send it.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.request.why",
      whyDefault:
        "Seeing the decider up front avoids a request that waits for weeks with the wrong person.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments",
    },
    {
      id: "approve",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.approve.in.request", label: "Release request" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.approve.out.released", label: "Released amount" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.approve.title",
      titleDefault: "Approve or reject",
      whatKey: "cases.release_money_before_anyone_commits_it.step.approve.what",
      whatDefault:
        "The approver of the required tier opens the item and approves or rejects the request. The person who asked can withdraw it while it is open.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.approve.why",
      whyDefault:
        "Four eyes: the requester and the approver are never the same person, so no one releases their own spending.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments",
    },
    {
      id: "link",
      icon: "Paperclip",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.link.in.contract", label: "Contract or order" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.link.out.linked", label: "Commitment linked to its release" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.link.title",
      titleDefault: "Link the contract or order",
      whatKey: "cases.release_money_before_anyone_commits_it.step.link.what",
      whatDefault:
        "Press Link a document and attach the contract or purchase order that uses the release.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.link.why",
      whyDefault:
        "A release that is not linked to the document it pays for cannot be checked. Once linked, an award above the release warns or blocks.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments",
    },
    {
      id: "exposure",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.exposure.in.terms", label: "Abort terms" },
      ],
      outputs: [
        { labelKey: "cases.release_money_before_anyone_commits_it.step.exposure.out.exposure", label: "Abort exposure report" },
      ],
      titleKey: "cases.release_money_before_anyone_commits_it.step.exposure.title",
      titleDefault: "Read the abort exposure",
      whatKey: "cases.release_money_before_anyone_commits_it.step.exposure.what",
      whatDefault:
        "Press Enter abort terms on each item, then open the Abort exposure tab to see what stopping the project today would cost. Export the register as PDF or Excel from the Commitments tab for the board.",
      whyKey: "cases.release_money_before_anyone_commits_it.step.exposure.why",
      whyDefault:
        "Every commitment narrows the way back. Knowing the cost of stopping is what lets a client take a hold or stop decision with open eyes.",
      moduleLabel: "Commitments and releases",
      moduleLabelKey: "commitment.page.title",
      to: "/projects/:projectId/commitments?tab=exposure",
    },
  ],
};

export default playbook;
