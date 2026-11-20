// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Compare bids and award".
//
// Open a tender, level the returned bids on a like-for-like basis, spot the
// gaps and outliers, then produce the award recommendation. Content strings
// are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "compare-bids-and-award",
  order: 85,
  category: "tendering",
  companyTypes: [
    "general-contractor",
    "cost-consultant",
    "project-manager",
    "developer-client",
  ],
  roles: ["estimator", "procurement-buyer", "commercial-manager"],
  icon: "Gavel",
  titleKey: "cases.compare_bids_and_award.title",
  titleDefault: "Compare bids and award",
  descKey: "cases.compare_bids_and_award.desc",
  descDefault:
    "Take a folder of returned tenders that never quite match, strip them back to the same scope, and hand the client an award call that survives scrutiny.",
  estMinutes: 12,
  steps: [
    {
      id: "open",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.compare_bids_and_award.step.open.in.bids",
          label: "Returned bids",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.open.in.invited",
          label: "Invited bidder list",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.open.in.schedule",
          label: "Issued pricing schedule",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compare_bids_and_award.step.open.out.baseline",
          label: "Confirmed common baseline",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.open.out.verified",
          label: "Verified bidder list",
        },
      ],
      titleKey: "cases.compare_bids_and_award.step.open.title",
      titleDefault: "Open the tender package",
      whatKey: "cases.compare_bids_and_award.step.open.what",
      whatDefault:
        "Pull up the tender record, verify the bidder list against who was actually invited, and check that every return prices the same issued schedule and the same drawing revision.",
      whyKey: "cases.compare_bids_and_award.step.open.why",
      whyDefault:
        "Bidders working from an earlier drawing set or a trimmed schedule are not competing on the same job. Nailing the common baseline now is what keeps the whole comparison downstream honest.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "level",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.compare_bids_and_award.step.level.in.bids",
          label: "Verified bids",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.level.in.quals",
          label: "Bidder qualifications",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.level.in.psums",
          label: "Provisional sums",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compare_bids_and_award.step.level.out.levelled",
          label: "Levelled bid comparison",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.level.out.gaps",
          label: "Flagged scope gaps",
        },
      ],
      titleKey: "cases.compare_bids_and_award.step.level.title",
      titleDefault: "Level the bids",
      whatKey: "cases.compare_bids_and_award.step.level.what",
      whatDefault:
        "Set the returns out column by column, then push every qualification, exclusion and provisional sum back into the price so line rates read against each other. Mark the gaps where a bidder simply left scope out.",
      whyKey: "cases.compare_bids_and_award.step.level.why",
      whyDefault:
        "The lowest headline number often belongs to whoever forgot the most. Once the missing builders work and the daywork assumptions go back in, the genuinely keen bid is usually a different one.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "award",
      icon: "Trophy",
      inputs: [
        {
          labelKey: "cases.compare_bids_and_award.step.award.in.levelled",
          label: "Levelled comparison",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.award.in.coverage",
          label: "Scope coverage",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.award.in.risk",
          label: "Commercial risk notes",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.compare_bids_and_award.step.award.out.recommendation",
          label: "Award recommendation",
        },
        {
          labelKey: "cases.compare_bids_and_award.step.award.out.bidder",
          label: "Preferred bidder",
        },
      ],
      titleKey: "cases.compare_bids_and_award.step.award.title",
      titleDefault: "Recommend the award",
      whatKey: "cases.compare_bids_and_award.step.award.what",
      whatDefault:
        "Write up the recommendation: the levelled spread, coverage against the full scope, any commercial or programme risk, and the bidder you would appoint with the reasoning set beside the figures.",
      whyKey: "cases.compare_bids_and_award.step.award.why",
      whyDefault:
        "An award gets second-guessed by a director, an auditor, or the losing bidder. A short paper showing both the math and the judgement behind the pick closes that conversation before it starts.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
