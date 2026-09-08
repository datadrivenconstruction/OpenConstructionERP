// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Assess and price a variation".
//
// When a change is instructed, capture it, price the added or omitted work
// from rates, check the programme and cost impact, and issue the variation
// for agreement so it is recovered rather than absorbed. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "assess-and-price-a-variation",
  order: 266,
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant"],
  roles: ["commercial-manager", "quantity-surveyor"],
  icon: "FilePlus2",
  titleKey: "cases.assess_and_price_a_variation.title",
  titleDefault: "Assess and price a variation",
  descKey: "cases.assess_and_price_a_variation.desc",
  descDefault:
    "When a change is instructed, capture it, price the added or omitted work from your rates, check the programme and cost impact, and issue the variation for agreement so it is recovered rather than absorbed.",
  estMinutes: 11,
  steps: [
    {
      id: "capture",
      icon: "FilePlus2",
      inputs: [
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.capture.in.instruction",
          label: "Client instruction",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.capture.in.reference",
          label: "Drawing reference",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.capture.in.date",
          label: "Instruction date",
        },
      ],
      outputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.capture.out.log",
          label: "Logged change order",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.capture.out.origin",
          label: "Traceable origin",
        },
      ],
      titleKey: "cases.assess_and_price_a_variation.step.capture.title",
      titleDefault: "Capture the instructed change",
      whatKey: "cases.assess_and_price_a_variation.step.capture.what",
      whatDefault:
        "Log the change the moment it is instructed: what was asked, who asked, the date, and the drawing or instruction reference, so the variation has a clear origin before any work is done to it.",
      whyKey: "cases.assess_and_price_a_variation.step.capture.why",
      whyDefault:
        "A change that is worked on site but never written down is the one that gets argued about later. Logging it at the instruction is what makes the claim provable instead of a memory.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.price.in.change",
          label: "Logged change order",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.price.in.rates",
          label: "Contract BOQ rates",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.price.in.measure",
          label: "Added and omitted work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.price.out.net",
          label: "Net variation price",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.price.out.breakdown",
          label: "Priced breakdown",
        },
      ],
      titleKey: "cases.assess_and_price_a_variation.step.price.title",
      titleDefault: "Price the added and omitted work",
      whatKey: "cases.assess_and_price_a_variation.step.price.what",
      whatDefault:
        "Measure the work added and the work omitted, and price both from your BOQ rates so the variation shows a net figure built on the same rates the contract was won on.",
      whyKey: "cases.assess_and_price_a_variation.step.price.why",
      whyDefault:
        "Pricing a change from the agreed rates, and pricing the omissions as honestly as the additions, is what keeps the variation defensible and gets it agreed without a fight over made-up numbers.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "impact",
      icon: "TrendingUp",
      inputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.impact.in.priced",
          label: "Priced variation",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.impact.in.forecast",
          label: "Cost forecast",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.impact.in.programme",
          label: "Project programme",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.impact.out.forecast",
          label: "Revised forecast",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.impact.out.time",
          label: "Time impact flagged",
        },
      ],
      titleKey: "cases.assess_and_price_a_variation.step.impact.title",
      titleDefault: "Check the cost and programme impact",
      whatKey: "cases.assess_and_price_a_variation.step.impact.what",
      whatDefault:
        "Add the priced change into the value picture to see its effect on the forecast, and note any time it adds to the programme so any extension of time is claimed alongside the money.",
      whyKey: "cases.assess_and_price_a_variation.step.impact.why",
      whyDefault:
        "A change costs more than its own line when it delays other trades. Pricing the money and flagging the time together is what stops a paid variation quietly causing an unpaid delay.",
      moduleLabel: "Value Realized",
      moduleLabelKey: "nav.value",
      to: "/projects/:projectId/value",
    },
    {
      id: "issue",
      icon: "FileSignature",
      inputs: [
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.issue.in.variation",
          label: "Priced variation",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.issue.in.backup",
          label: "Measure and rates",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.issue.in.terms",
          label: "Contract terms",
        },
      ],
      outputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.issue.out.issued",
          label: "Issued variation",
        },
        {
          labelKey:
            "cases.assess_and_price_a_variation.step.issue.out.agreement",
          label: "Signed agreement",
        },
      ],
      titleKey: "cases.assess_and_price_a_variation.step.issue.title",
      titleDefault: "Issue the variation for agreement",
      whatKey: "cases.assess_and_price_a_variation.step.issue.what",
      whatDefault:
        "Send the priced variation to the client or contract administrator under the contract terms, with the measure and rates as backup, and track it through to a signed agreement.",
      whyKey: "cases.assess_and_price_a_variation.step.issue.why",
      whyDefault:
        "A variation that is priced but never formally issued is work you have done for free. Getting it agreed in writing is what turns a change into recovered cost instead of absorbed loss.",
      moduleLabel: "Contracts",
      moduleLabelKey: "onboarding.mod_contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.report.in.agreed",
          label: "Agreed variation",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.report.in.changes",
          label: "Change order log",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.report.in.sum",
          label: "Contract sum",
        },
      ],
      outputs: [
        {
          labelKey: "cases.assess_and_price_a_variation.step.report.out.report",
          label: "Change position report",
        },
        {
          labelKey: "cases.assess_and_price_a_variation.step.report.out.total",
          label: "Running change total",
        },
      ],
      titleKey: "cases.assess_and_price_a_variation.step.report.title",
      titleDefault: "Report the variation position",
      whatKey: "cases.assess_and_price_a_variation.step.report.what",
      whatDefault:
        "Roll the variation into the change position report so the running total of instructed, priced and agreed changes is visible against the contract sum at any time.",
      whyKey: "cases.assess_and_price_a_variation.step.report.why",
      whyDefault:
        "One variation is easy to follow, thirty are not. A live report of where every change stands is what stops agreed value slipping out of sight and never getting into an application.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
