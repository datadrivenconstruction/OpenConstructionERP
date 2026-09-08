// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a comprehensive unit rate under GB 50500" (CN).
//
// The bill of quantities valuation code prices an item as a comprehensive unit
// rate: labour, material and plant for the work itself, plus the firm's
// management fee and profit, all inside one number the bill carries on one
// line. Everything the code puts OUTSIDE that number - the measure items, the
// statutory charges, the tax - is a head on the bill total and does not belong
// inside a rate.
//
// So the case is about composition, not about entry. The estimator's own
// labour, material and plant rates are the ones that matter, and the payoff is
// a rate analysis whose parts add up to the rate the bill shows. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-comprehensive-unit-rate-under-gb-50500",
  order: 1120,
  region: "CN",
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor"],
  icon: "Calculator",
  titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.title",
  titleDefault: "Build a comprehensive unit rate under GB 50500",
  descKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.desc",
  descDefault:
    "Take a coded item on a bill of quantities, put your own labour, material and plant behind it, add the management fee and the profit, and read back a comprehensive unit rate whose parts add up to the number on the line.",
  longDescKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.longdesc",
  longDescDefault:
    "A comprehensive unit rate is the whole subject of pricing under the bill of quantities valuation code, and it is a composition rather than a figure: labour, material and plant for the work described, then the firm's management fee and its profit, and nothing else. The charges that sit outside it - the measure items, the statutory charges, the tax - are heads on the bill total, and an estimator who lets one of them drift inside a rate reports a management fee that is not the one the firm runs on. This case builds one rate from the bottom, on your own resource prices rather than on a borrowed average, and ends on the analysis that shows the arithmetic. Reading your own numbers back is the point; a rate you cannot take apart in front of a client is a rate you cannot defend.",
  estMinutes: 14,
  steps: [
    {
      id: "open",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.in.bill", label: "Bill of quantities" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.in.codes", label: "GB 50500 item codes" },
      ],
      outputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.out.item", label: "The item you are pricing" },
      ],
      titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.title",
      titleDefault: "Open the coded bill and pick the item",
      whatKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.what",
      whatDefault:
        "Open the bill, find the section and the item you are pricing, and read the item description and its code before you price anything. The code tells you which schedule item this is; the description tells you what the rate has to cover.",
      whyKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.open.why",
      whyDefault:
        "Under GB 50500 the item description is the ground for what the rate includes, and most final-account arguments start with an item whose description did not say enough. Reading it before you price is the cheapest minute in the whole exercise.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "resources",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.in.prices", label: "Your own supplier prices" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.in.crews", label: "Crew and plant costs" },
      ],
      outputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.out.catalog", label: "Maintained resource rates" },
      ],
      titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.title",
      titleDefault: "Hold your labour, material and plant rates in one place",
      whatKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.what",
      whatDefault:
        "Put the prices you actually buy at into the resource catalog: wage costs by trade, with the social insurance and housing fund contributions the 2024 standard now carries inside the labour price; material prices by supplier, net of deductible input VAT if you price under the general tax method; plant by the hour. Keep them current rather than accurate once a year.",
      whyKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.resources.why",
      whyDefault:
        "The rates a contractor is judged on are the firm's own, and a published average is a starting point rather than an answer. Holding them centrally means the next hundred rates you build are consistent with this one, and a price change is one edit instead of a hunt through old bids.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "compose",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.in.item", label: "The coded item" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.in.rates", label: "Labour, material and plant rates" },
      ],
      outputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.out.direct", label: "Direct cost per unit" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.out.rate", label: "Comprehensive unit rate" },
      ],
      titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.title",
      titleDefault: "Compose the rate and read the analysis back",
      whatKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.what",
      whatDefault:
        "Enter the labour, material and plant the item consumes per unit, then open the rate analysis on the line. It shows the direct cost per unit, the management fee, the profit, the comprehensive unit rate and the item total, in that order.",
      whyKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.compose.why",
      whyDefault:
        "That sequence is the composition GB/T 50500-2024 defines: labour, material and plant, the management fee, the profit and the priced risk, with VAT outside the rate. Seeing it as a chain rather than as a total is what lets you answer a client who asks why the rate is what it is. The fee and the profit are taken on the direct cost here, so the measures items, the other items and the VAT stay where they belong, on the bill total, instead of inflating a rate from the inside. The statutory charges the 2013 code kept as a separate head are gone from the 2024 standard: the social insurance and housing fund contributions now sit inside the labour price and the management fee, so where your province has moved to the 2024 shape take the statutory-charges head out of the bill's markup stack, and where it still runs the 2013 shape leave that head on the bill total.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.in.priced", label: "Priced bill" },
      ],
      outputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.out.report", label: "Validation report" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.out.unpriced", label: "Items left at zero" },
      ],
      titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.title",
      titleDefault: "Validate before the bill leaves your desk",
      whatKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.what",
      whatDefault:
        "Run the bill through validation. For a project in China the GB 50500 rules are selected for you: every item has to carry a code, and the code has to be well formed at nine or twelve digits.",
      whyKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.validate.why",
      whyDefault:
        "One item left at zero can carry a loss all the way to site, and a malformed code is the sort of thing an owner's reviewer finds before you do. The check is on the shape of the code rather than on its membership in the national schedule, so treat a clean run as a floor and still read the codes yourself.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "issue",
      icon: "FileOutput",
      inputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.in.validated", label: "Validated priced bill" },
      ],
      outputs: [
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.out.priced", label: "Priced bill for issue" },
        { labelKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.out.analysis", label: "Rate analysis behind each item" },
      ],
      titleKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.title",
      titleDefault: "Issue the priced bill with its working behind it",
      whatKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.what",
      whatDefault:
        "Report the priced bill, and keep the rate analysis for the items that carry real money. The analysis is the document you bring to a rate query, not something you rebuild when one arrives.",
      whyKey: "cases.build_a_comprehensive_unit_rate_under_gb_50500.step.issue.why",
      whyDefault:
        "A rate you can take apart in a meeting settles a query in ten minutes. A rate that exists only as a total turns the same query into a week of reconstruction, and every reconstruction after the event looks like an argument rather than a record.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
