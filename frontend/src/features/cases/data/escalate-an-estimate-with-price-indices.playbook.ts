// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Escalate an estimate with price indices".
//
// Bring base-date rates forward to the midpoint of construction using published
// cost indices, so the price reflects when the money is actually spent. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "escalate-an-estimate-with-price-indices",
  order: 1003,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  icon: "TrendingUp",
  titleKey: "cases.escalate_an_estimate_with_price_indices.title",
  titleDefault: "Escalate an estimate with price indices",
  descKey: "cases.escalate_an_estimate_with_price_indices.desc",
  descDefault:
    "Bring base-date rates forward to the midpoint of construction using published cost indices, so the number reflects when the money is really spent rather than the day the rate was set.",
  longDescKey: "cases.escalate_an_estimate_with_price_indices.longdesc",
  longDescDefault:
    "A rate is only true on its base date. On a job that starts in a year and runs for two, pricing at today's rates quietly under-budgets the client. Escalation with a published index is the transparent, defensible way to close that gap and to show your working when asked.",
  estMinutes: 9,
  steps: [
    {
      id: "basedate",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.in.estimate", label: "Base-date estimate" },
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.in.programme", label: "Construction dates" },
      ],
      outputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.out.dates", label: "Base and target dates" },
      ],
      titleKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.title",
      titleDefault: "Set base and target dates",
      whatKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.what",
      whatDefault:
        "Fix the base date of your rates and the target date to escalate to, usually the midpoint of the construction period where spend is heaviest.",
      whyKey: "cases.escalate_an_estimate_with_price_indices.step.basedate.why",
      whyDefault:
        "Escalating to the midpoint rather than the start or the end is the fair average across the spend curve. Getting these two dates right is most of the accuracy of the whole exercise.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "index",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.index.in.dates", label: "Base and target dates" },
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.index.in.series", label: "Published index series" },
      ],
      outputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.index.out.factor", label: "Escalation factor" },
      ],
      titleKey: "cases.escalate_an_estimate_with_price_indices.step.index.title",
      titleDefault: "Read the escalation factor",
      whatKey: "cases.escalate_an_estimate_with_price_indices.step.index.what",
      whatDefault:
        "Pick the index series that best matches the work - building, civils, or a trade-specific one - and read the factor between the base and target dates.",
      whyKey: "cases.escalate_an_estimate_with_price_indices.step.index.why",
      whyDefault:
        "The right series matters: labour, steel and energy do not move together. Choosing an index that fits the work is what makes the escalation credible rather than a blanket guess.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "apply",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.apply.in.factor", label: "Escalation factor" },
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.apply.in.estimate", label: "Base-date bill" },
      ],
      outputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.apply.out.escalated", label: "Escalated total" },
      ],
      titleKey: "cases.escalate_an_estimate_with_price_indices.step.apply.title",
      titleDefault: "Apply it to the bill",
      whatKey: "cases.escalate_an_estimate_with_price_indices.step.apply.what",
      whatDefault:
        "Apply the factor to the bill and read the escalated total next to the base figure, so the uplift is a line you can point at rather than a number folded into the rates.",
      whyKey: "cases.escalate_an_estimate_with_price_indices.step.apply.why",
      whyDefault:
        "Showing the base and the escalated total side by side keeps the client's trust. It also lets you re-run the uplift cleanly if the start date slips again.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "record",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.record.in.escalated", label: "Escalated total" },
      ],
      outputs: [
        { labelKey: "cases.escalate_an_estimate_with_price_indices.step.record.out.basis", label: "Recorded basis" },
      ],
      titleKey: "cases.escalate_an_estimate_with_price_indices.step.record.title",
      titleDefault: "Record it in the basis",
      whatKey: "cases.escalate_an_estimate_with_price_indices.step.record.what",
      whatDefault:
        "Write the base date, the index series and the factor into the basis of estimate so anyone reading the price later knows exactly how it was escalated.",
      whyKey: "cases.escalate_an_estimate_with_price_indices.step.record.why",
      whyDefault:
        "An escalation nobody can reconstruct is an escalation nobody trusts. Recording the working is what turns a defensible method into an auditable one.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
  ],
};

export default playbook;
