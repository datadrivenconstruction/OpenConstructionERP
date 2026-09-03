// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Hold the estimate to the sanctioned amount" (IN).
//
// Indian public works are authorised twice and the two authorisations answer
// different questions. Administrative approval is the department accepting the
// work and a sum of money for it, given on a preliminary estimate. Technical
// sanction is the engineering authority certifying that a detailed estimate is
// properly prepared, on the governing schedule of rates, and that the figure
// stands up. Money may not be spent beyond what has been sanctioned, and when
// the work is going to exceed it, the sanction is revised before the spending
// rather than after it.
//
// That sequence puts an unusual demand on cost control. On a private job an
// overrun is a commercial problem discovered at the end; here it is a
// procedural one that has to be seen early enough to be regularised, because a
// revision takes time to obtain and expenditure beyond sanction is irregular
// even when the work was necessary and the price was fair.
//
// So the case is about visibility against a fixed ceiling rather than about
// forecasting: what was sanctioned, what the detailed estimate came to, what
// the contingency covers, what the deviations have consumed, and how much
// headroom is left before somebody has to go back and ask.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "hold-the-estimate-to-the-sanctioned-amount",
  order: 1189,
  region: "IN",
  category: "estimating",
  companyTypes: ["developer-client", "project-manager", "cost-consultant", "general-contractor"],
  roles: ["project-manager", "estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Landmark",
  titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.title",
  titleDefault: "Hold the estimate to the sanctioned amount",
  descKey: "cases.hold_the_estimate_to_the_sanctioned_amount.desc",
  descDefault:
    "Take the work from a preliminary estimate and its approval to a detailed estimate and its technical sanction, keep the contingency where it can be seen, track every deviation against the ceiling, and ask for a revision before the money runs out rather than after.",
  longDescKey: "cases.hold_the_estimate_to_the_sanctioned_amount.longdesc",
  longDescDefault:
    "The sanctioned amount is a ceiling with procedure attached, and that is what makes it different from a budget. A budget overrun is reported; a sanction overrun has to be regularised, by a competent authority, on a revised estimate that explains what changed and why, and obtaining one takes long enough that it has to be started while there is still headroom. The failure mode is always the same and always late: deviations are approved individually because each is small and obviously necessary, nobody is adding them up against the ceiling, and the arithmetic is done when a bill cannot be passed. This case keeps the running total visible from the first approval onward, so that the decision to seek a revision is taken as a decision rather than forced by a bill that has nowhere to go.",
  estMinutes: 20,
  steps: [
    {
      id: "preliminary",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.in.scope",
          label: "The scope as proposed",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.in.rates",
          label: "Plinth area or comparable rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.out.estimate",
          label: "A preliminary estimate with its basis",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.out.amount",
          label: "The amount put up for approval",
        },
      ],
      titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.title",
      titleDefault: "Put up a preliminary estimate that says what it assumed",
      whatKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.what",
      whatDefault:
        "Build the early estimate from area rates or from comparable completed work, and record with it the scope assumed, the price level used and what is excluded. Carry that figure as the amount put up for approval.",
      whyKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.preliminary.why",
      whyDefault:
        "The approved amount is fixed from this estimate and governs the job for years, so its assumptions matter more than its precision. An estimate that states what it left out can be revised for a stated reason; one that states only a number is revised for what looks like a mistake.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "detailed",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.in.drawings",
          label: "Working drawings and specification",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.in.schedule",
          label: "The governing schedule of rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.out.detailed",
          label: "A detailed estimate for technical sanction",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.out.gap",
          label: "Where it sits against the approval",
        },
      ],
      titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.title",
      titleDefault: "Build the detailed estimate and compare it with the approval",
      whatKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.what",
      whatDefault:
        "Measure and price the work in full on the governing schedule, then set the total beside the approved amount and account for the difference sub-head by sub-head rather than as one variance.",
      whyKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.detailed.why",
      whyDefault:
        "The gap between a preliminary and a detailed estimate is normal and is expected to be explained. Explaining it by sub-head shows whether the scope grew, the rates moved or the early estimate was thin, and only the first of those is a reason to revise the approval.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "contingency",
      icon: "Dice5",
      inputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.in.risks",
          label: "What the job might still meet",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.out.provision",
          label: "Contingency as a stated provision",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.out.rules",
          label: "Who may draw on it and for what",
        },
      ],
      titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.title",
      titleDefault: "Keep the contingency visible and spend it deliberately",
      whatKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.what",
      whatDefault:
        "Hold the contingency as its own provision inside the sanctioned amount, with a note of what it is for, and record each drawing on it against the event that caused it.",
      whyKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.contingency.why",
      whyDefault:
        "Contingency spread into rates is spent invisibly and is gone before anyone knows it was being used. Held apart, it answers the only question that matters halfway through a job, which is how much room is left before the ceiling and what has already consumed the rest.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "deviations",
      icon: "GitBranch",
      inputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.in.changes",
          label: "Deviations as they arise",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.out.running",
          label: "A running total against the ceiling",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.out.headroom",
          label: "Headroom left, at any moment",
        },
      ],
      titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.title",
      titleDefault: "Add the deviations up as they happen",
      whatKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.what",
      whatDefault:
        "Record every deviation with its value, whether it is an excess over a sanctioned quantity, a new item or a saving, and keep the cumulative effect against the sanctioned amount rather than against the last approved change.",
      whyKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.deviations.why",
      whyDefault:
        "Deviations are approved one at a time and consume the ceiling collectively, which is precisely the arithmetic nobody does in the moment. A running total is the only instrument that turns twelve reasonable individual decisions into a visible position.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/change-orders",
    },
    {
      id: "revise",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.in.position",
          label: "The position against the ceiling",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.out.case",
          label: "A revised estimate with its reasons",
        },
        {
          labelKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.out.time",
          label: "Asked for while there is still headroom",
        },
      ],
      titleKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.title",
      titleDefault: "Ask for the revision before the headroom is gone",
      whatKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.what",
      whatDefault:
        "Report the position against the sanctioned amount at each period, and when the trend shows the ceiling being reached, produce the revised estimate with the reasons separated into scope, quantity and rate, and put it up while there is still room to work under the existing sanction.",
      whyKey: "cases.hold_the_estimate_to_the_sanctioned_amount.step.revise.why",
      whyDefault:
        "A revision sought early is a technical submission with an answer to every question. One sought after the ceiling is passed is the same submission with an explanation attached for why work continued, and that explanation is what turns an ordinary cost increase into a finding against the department.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
