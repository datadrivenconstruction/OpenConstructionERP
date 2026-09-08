// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Score a tender on price and preference under the PPPFA" (ZA).
//
// The Preferential Procurement Policy Framework Act 5 of 2000 and the
// preferential procurement regulations made under it mean a South African
// public tender is not awarded to the lowest price. Points are split between
// price and preference on one of two ratios decided by the value of the
// tender, price points come out of a formula rather than out of judgement, and
// the preference points go to the specific goals the organ of state named in
// the tender document itself. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "score-a-tender-on-price-and-preference-under-the-pppfa",
  order: 1343,
  category: "tendering",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  roles: ["procurement-buyer", "quantity-surveyor", "commercial-manager"],
  region: "ZA",
  stage: "procure",
  icon: "Scale",
  titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.title",
  titleDefault: "Score a tender on price and preference under the PPPFA",
  descKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.desc",
  descDefault:
    "Choose the points ratio the value of the tender dictates, state the specific goals in the tender document, level the priced bills so the price you score is comparable, then score price by formula and preference on what you published.",
  longDescKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.longdesc",
  longDescDefault:
    "Two things decide a South African public tender and only one of them is the price. The Preferential Procurement Policy Framework Act 5 of 2000 splits the points 80 for price and 20 for preference on tenders up to R50 million, and 90 for price and 10 for preference above it, so the ratio is not a choice, it follows the value. Price points come out of a formula that measures each bid against the lowest acceptable one, which means the second cheapest bid does not automatically lose. Preference points go to the specific goals the organ of state itself set out in the tender document, and that is where most evaluations come apart, because a goal that was not published cannot be scored and a goal that was published has to be scored exactly as written.",
  estMinutes: 13,
  steps: [
    {
      id: "goals",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.in.estimate", label: "Pre-tender estimate" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.in.policy", label: "Procurement policy" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.out.ratio", label: "Points ratio" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.out.goals", label: "Published specific goals" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.title",
      titleDefault: "Set the ratio and publish the specific goals",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.what",
      whatDefault:
        "Take the ratio from your own estimate of the value: 80 points for price and 20 for preference up to R50 million, 90 and 10 above it. Then write into the tender document the specific goals that will earn the preference points and the number of points each is worth, together with the proof a bidder must submit to claim them.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.goals.why",
      whyDefault:
        "Under the Preferential Procurement Policy Framework Act 5 of 2000 the goals are the organ of state's to choose, but only in the tender document and only in advance. Goals that commonly appear include the bidder's B-BBEE contributor status level, but nothing is scored by default: an evaluation committee that awards points for a goal the advertisement never mentioned has given every unsuccessful bidder a review, and one that ignores a goal it did publish has done the same.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "receive",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.in.bids", label: "Submitted bids" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.in.checklist", label: "Returnable schedules" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.out.register", label: "Bid register" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.out.responsive", label: "Responsiveness check" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.title",
      titleDefault: "Register the bids and test them for responsiveness",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.what",
      whatDefault:
        "Log every bid received with its price and the returnable schedules it came with, then run the responsiveness check before any scoring: CIDB registration current and of the right designation, tax status, the goal claims supported by the proof the tender asked for.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.receive.why",
      whyDefault:
        "Responsiveness is a gate and not a score. A bid that fails it never reaches the points table, and mixing the two up is how a committee ends up defending why it gave a non-responsive bid 78 points instead of why it set the bid aside. Doing the check first, in writing, is what makes the rest of the evaluation short.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "level",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.in.priced", label: "Priced bills" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.in.qualifications", label: "Bidder qualifications" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.out.comparable", label: "Comparable prices" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.out.queries", label: "Tender queries" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.title",
      titleDefault: "Level the priced bills item by item",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.what",
      whatDefault:
        "Put the priced bills side by side at item level, find the arithmetic errors, the items priced at nil and the qualifications written into a covering letter, and raise a query on each before the price goes into the formula.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.level.why",
      whyDefault:
        "The price points formula measures every bid against the lowest one, so an arithmetic slip in the cheapest bid does not just misprice that bid, it moves the score of every other bidder. Levelling is the only step that makes the number going into the formula mean the same thing for everyone.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "score",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.in.prices", label: "Levelled prices" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.in.claims", label: "Goal claims" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.out.points", label: "Points per bidder" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.out.ranking", label: "Ranking" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.title",
      titleDefault: "Score price by the formula and preference by the goals",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.what",
      whatDefault:
        "Score price with the formula the regulations give: the lowest acceptable bid takes the full weighting, and every other bid loses the proportion by which it exceeds that lowest bid. Then add the preference points, goal by goal, against the proof each bidder submitted, and total the two.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.score.why",
      whyDefault:
        "The formula is what makes preference points decisive rather than decorative. A bid five per cent above the lowest gives up only a small part of its price points, so full preference points can and often do outweigh that gap, and a committee that quietly awards on price alone has ignored the Act. Writing the arithmetic down per bidder is what makes the award defensible.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "approve",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.in.points", label: "Points table" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.in.report", label: "Evaluation report" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.out.decision", label: "Award decision" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.out.trail", label: "Approval trail" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.title",
      titleDefault: "Take the recommendation through the approval route",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.what",
      whatDefault:
        "Send the evaluation report and the points table through the delegation of authority the organ of state works to, so the adjudication decision and the person who took it are both on the record with a date.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.approve.why",
      whyDefault:
        "A tender award is reviewable, and the first thing a review asks is who decided and on what. An approval trail that shows the points table the decision was taken on, unchanged, answers that in one page. Note also that the Public Procurement Act 28 of 2024 has been passed and is being brought into operation in stages, so record which regime the tender was advertised under.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
    {
      id: "award",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.in.decision", label: "Award decision" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.in.bill", label: "Accepted bill" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.out.contract", label: "Signed contract" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.out.data", label: "Contract data" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.title",
      titleDefault: "Turn the award into a contract with its data filled in",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.what",
      whatDefault:
        "Draw up the contract on the form the tender was advertised on and complete the contract data: the accepted priced document, the dates, the securities, the penalty, and the goals the bidder committed to that now become contractual obligations.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.award.why",
      whyDefault:
        "A goal that earned preference points and was never written into the contract is a promise nobody can enforce. Carrying the commitments across at signature is what makes the preference part of the score mean something on site rather than only on the scoresheet.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "notify",
      icon: "Send",
      inputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.in.ranking", label: "Final ranking" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.in.bidders", label: "Bidder list" },
      ],
      outputs: [
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.out.letters", label: "Notification letters" },
        { labelKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.out.file", label: "Tender file" },
      ],
      titleKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.title",
      titleDefault: "Notify every bidder and close the tender file",
      whatKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.what",
      whatDefault:
        "Write to the successful and the unsuccessful bidders, publish the award as the organ of state is required to, and close the file with the advertisement, the bids, the responsiveness check, the points table and the approval in it.",
      whyKey: "cases.score_a_tender_on_price_and_preference_under_the_pppfa.step.notify.why",
      whyDefault:
        "An unsuccessful bidder is entitled to know it lost and to ask why, and the answer is the points table. A tender file assembled after a challenge arrives always looks assembled after a challenge arrives; one closed on the day of the award is simply the record.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
  ],
};

export default playbook;
