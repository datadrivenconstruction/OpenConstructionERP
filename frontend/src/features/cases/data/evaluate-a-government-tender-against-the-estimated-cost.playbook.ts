// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Evaluate a government tender against the estimated cost" (IN).
//
// Indian public works are tendered against a number the department has already
// computed: the estimated cost, built on the governing schedule of rates and
// sanctioned before the notice goes out. Bids are then read as a percentage
// above or below that figure, which is why the estimate is not merely internal
// paperwork. It is the yardstick the award is measured with and the document a
// scrutiny of the award will start from.
//
// Two tender forms sit on the same estimate and behave differently. A
// percentage rate tender asks for one figure above or below the whole schedule
// and is quick to compare and blunt to analyse. An item rate tender asks for a
// rate against every item, which is where front loading and unbalanced pricing
// live: a bidder can be lowest overall while being far above the estimate on
// the items that get executed first.
//
// So the useful comparison is never the total alone. It is the total, and then
// the items, against the department's own estimated rates.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "evaluate-a-government-tender-against-the-estimated-cost",
  order: 1184,
  region: "IN",
  category: "tendering",
  companyTypes: ["developer-client", "project-manager", "cost-consultant", "general-contractor"],
  roles: ["procurement-buyer", "quantity-surveyor", "estimator", "commercial-manager"],
  icon: "Gavel",
  titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.title",
  titleDefault: "Evaluate a government tender against the estimated cost",
  descKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.desc",
  descDefault:
    "Fix the estimated cost the tender is called on, issue the same bill to every bidder, receive and open the offers, read them item by item against the estimate rather than only on the percentage, and put the reasoning for the award on the record.",
  longDescKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.longdesc",
  longDescDefault:
    "A public tender in India produces two numbers that are easy to confuse: the estimated cost the department computed, and the percentage above or below it that the successful bidder quoted. Only the first is evidence about what the work costs. The second is evidence about the market on the day, and on an item rate tender it hides a good deal of structure. A bid twelve percent below overall may be forty percent below on earthwork, which the department will execute in the first three months, and level on finishes, which it will execute in the last six. That bidder has been paid ahead of progress before the job is half done, and the department discovers it during the third running bill rather than during evaluation. This case sets the estimate up as the reference it is supposed to be, then compares against it at the level where the information lives.",
  estMinutes: 24,
  steps: [
    {
      id: "estimate",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.in.priced",
          label: "The priced estimate",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.in.sanction",
          label: "The sanctioned amount",
        },
      ],
      outputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.out.reference",
          label: "The estimated cost, fixed and dated",
        },
      ],
      titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.title",
      titleDefault: "Fix the estimated cost the tender is called on",
      whatKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.what",
      whatDefault:
        "Record the estimated cost as issued, the schedule and edition behind it, the price level, and what it excludes. Freeze it before the notice goes out, so later comparison is against the figure bidders actually saw.",
      whyKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.estimate.why",
      whyDefault:
        "An estimate that keeps moving after issue cannot be compared with anything. Fixing it is what makes the percentage above or below meaningful, and it is the first thing an audit of the award asks to see.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "invite",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.in.bill",
          label: "The tender bill",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.in.conditions",
          label: "Conditions and eligibility",
        },
      ],
      outputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.out.issued",
          label: "One bill issued to everyone",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.out.dates",
          label: "Dates and the earnest money required",
        },
      ],
      titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.title",
      titleDefault: "Issue one bill, one set of conditions, one clock",
      whatKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.what",
      whatDefault:
        "Publish the tender on the frozen bill, stating the tender form, whether rates are quoted item by item or as a single percentage, the earnest money required, the eligibility conditions and the closing date. Issue every clarification to every bidder.",
      whyKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.invite.why",
      whyDefault:
        "The comparison at the end is only valid if the offers answer the same question. A clarification sent to one bidder, or a bill quietly corrected after issue, breaks that and is the most common ground on which an award is challenged.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "receive",
      icon: "FolderInput",
      inputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.in.offers",
          label: "Sealed offers",
        },
      ],
      outputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.out.register",
          label: "A register of who bid and when",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.out.qualified",
          label: "Who cleared the technical stage",
        },
      ],
      titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.title",
      titleDefault: "Receive the offers and settle eligibility before price",
      whatKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.what",
      whatDefault:
        "Log every offer with its time of receipt, check the earnest money and the eligibility documents, and settle who is technically qualified before any financial offer is read.",
      whyKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.receive.why",
      whyDefault:
        "Two-stage opening exists so that eligibility cannot be decided by knowing the price. Recording the technical decision with its date, before the financial opening, is what makes that separation demonstrable rather than merely intended.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "compare",
      icon: "GitCompareArrows",
      inputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.in.bids",
          label: "Qualified offers on the same bill",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.in.estimate",
          label: "The estimated rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.out.spread",
          label: "Item by item spread against the estimate",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.out.queries",
          label: "The items worth querying",
        },
      ],
      titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.title",
      titleDefault: "Compare at the item, not only at the percentage",
      whatKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.what",
      whatDefault:
        "Put the offers beside the estimated rates and look for items that are far below the estimate on early work and far above on late work, and for rates that no analysis supports. Query those with the bidder and record the answer.",
      whyKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.compare.why",
      whyDefault:
        "Front loading is legal, invisible in a total, and expensive. So is a rate so far below the estimate that the item cannot be built for it, because that work is either not done or comes back as a claim. Both are visible only when the bill is compared line by line against a fixed reference.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "award",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.in.recommendation",
          label: "The recommendation and its reasons",
        },
      ],
      outputs: [
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.out.contract",
          label: "A contract on the accepted rates",
        },
        {
          labelKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.out.security",
          label: "Performance security recorded",
        },
      ],
      titleKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.title",
      titleDefault: "Award on the record, with the security in place",
      whatKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.what",
      whatDefault:
        "Set the contract up on the accepted rates, carry the percentage above or below onto it, and record the performance security, the defect liability period and the price variation position agreed at award.",
      whyKey: "cases.evaluate_a_government_tender_against_the_estimated_cost.step.award.why",
      whyDefault:
        "Everything the job argues about later, valuation, extras, escalation, release of security, is decided against what the contract says at this moment. Writing it down here is cheap; reconstructing it from the tender file two years later is not.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
