// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Compile the tender control price and price a bid" (CN).
//
// State-funded work in China is priced twice on the same bill and by two
// different people. The owner's consultant compiles a control price on a
// published quota base, and the bidders price the same bill on what they can
// actually buy at. The interesting number is neither of them on its own, it is
// the distance between them, item by item.
//
// That duality is the case. Quota pricing expands a norm into hours and
// materials per unit and prices them from a book; market pricing puts the
// firm's own rates on the same items. Holding the two against each other is
// what tells an owner whether a bid is genuinely cheap or merely thin, and it
// is what tells a bidder where their price is exposed.
//
// The national cost base is downloaded through the ordinary import surface
// rather than shipped with the product, and provincial quota books are not part
// of it. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "compile-the-tender-control-price-and-price-a-bid",
  order: 1125,
  region: "CN",
  category: "tendering",
  companyTypes: ["cost-consultant", "developer-client", "general-contractor", "project-manager"],
  roles: ["estimator", "quantity-surveyor", "procurement-buyer", "commercial-manager"],
  icon: "Landmark",
  titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.title",
  titleDefault: "Compile the tender control price and price a bid",
  descKey: "cases.compile_the_tender_control_price_and_price_a_bid.desc",
  descDefault:
    "Load a national cost base, build quota-based rates from it to compile the owner's control price, price the same bill on your own market rates, and read the two against each other before anybody awards anything.",
  longDescKey: "cases.compile_the_tender_control_price_and_price_a_bid.longdesc",
  longDescDefault:
    "Two pricing regimes sit on top of one bill of quantities and they answer different questions. A quota rate says what the work costs when it is done the way the norm assumes, with the hours and materials the book allocates to it; a market rate says what this firm can buy it for this year, on this site, with these suppliers. On public work both exist by design, because the owner needs a defensible ceiling compiled from a published base and the bidder needs a price it can actually deliver at. This case builds both on the same coded bill and then compares them item by item, which is where the useful information is. A bid twenty percent under the control price on earthworks and level on finishes is telling you something specific, and it is not the same thing as a bid twenty percent under overall.",
  estMinutes: 24,
  steps: [
    {
      id: "base",
      icon: "Database",
      inputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.in.published", label: "Published national cost base" },
      ],
      outputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.out.loaded", label: "Cost base loaded and searchable" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.out.currency", label: "Priced in CNY" },
      ],
      titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.title",
      titleDefault: "Load the cost base you are going to price from",
      whatKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.what",
      whatDefault:
        "Bring a cost base into the cost database through the ordinary import surface and check it landed with its work items, units and currency intact. A Chinese base with Shanghai rates in CNY and the GB/T classification is one of the families available to load; a provincial quota book is something you bring yourself.",
      whyKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.base.why",
      whyDefault:
        "A control price is only defensible if everybody can see which base it was compiled from. Loading it as data rather than transcribing rates out of a book means the base is named, versioned and re-pricable later, instead of living as a column somebody typed in once.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "norms",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.in.norm", label: "Norm for the work item" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.in.qty", label: "Quantity from the bill" },
      ],
      outputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.out.hours", label: "Labour and machine hours" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.out.rate", label: "Quota-based rate" },
      ],
      titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.title",
      titleDefault: "Expand a norm into hours and materials, then price it",
      whatKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.what",
      whatDefault:
        "Take a norm, enter the bill's quantity and see the unpriced labour hours, machine hours and material takeoff behind it. Price those at current published prices rather than at the book's, and save the result as an assembly you can reuse across the bill. The 2024 standard no longer names the pricing quota as the basis of the ceiling; it names price information and cost data, and the norm is still the honest way to get the consumption behind a rate.",
      whyKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.norms.why",
      whyDefault:
        "This is what quota pricing actually is, and seeing it expanded is what makes a control price arguable rather than merely quoted. It is also where you notice that a norm assumes a method your site cannot use, which is a finding worth having before the ceiling is published rather than after a bidder challenges it.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "control",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.in.bill", label: "The coded tender bill" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.in.assemblies", label: "Quota-based rates" },
      ],
      outputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.out.control", label: "Control price on the bill" },
      ],
      titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.title",
      titleDefault: "Compile the control price on the tender bill",
      whatKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.what",
      whatDefault:
        "Price the tender bill through with the norm-based rates, keeping the item codes and descriptions exactly as they will be issued to bidders, and add the measures items, the other items and the VAT on top of the item totals. The 2024 standard calls the ceiling the maximum bid price rather than the control price and has it published with the tender documents, so the compilation note has to name where every price came from.",
      whyKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.control.why",
      whyDefault:
        "The control price and the bill the bidders receive have to be the same document with one column filled differently, or the comparison at the end is between two different scopes. Compiling it on the issued bill rather than on a working copy is what guarantees that.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "market",
      icon: "GitCompareArrows",
      inputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.in.quota", label: "Quota-based rates" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.in.own", label: "Your own market rates" },
      ],
      outputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.out.spread", label: "Where the two bases disagree" },
      ],
      titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.title",
      titleDefault: "Hold the quota rate against the market rate",
      whatKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.what",
      whatDefault:
        "Compare the base you compiled from against your own rates, trade by trade, and look for the items where the two disagree most. Those are the items that decide the job.",
      whyKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.market.why",
      whyDefault:
        "A quota rate is an average of a method; a market rate is a quotation from this year. Where they are close, the item is uninteresting whoever prices it. Where they are far apart, either the norm assumes something your site does not do, or somebody is about to bid work they cannot deliver, and both are worth knowing before the envelope is opened.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "evaluate",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.in.bids", label: "Bids on the same bill" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.in.control", label: "The compiled control price" },
      ],
      outputs: [
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.out.comparison", label: "Bids read against the control price" },
        { labelKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.out.record", label: "The reasoning on the record" },
      ],
      titleKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.title",
      titleDefault: "Read the bids against the control price and write down why",
      whatKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.what",
      whatDefault:
        "Put the bids side by side in the tender evaluation and read each one against the control price you compiled, section by section rather than only on the total. Record the reasoning that leads to your recommendation, including which items you queried and what the answer was.",
      whyKey: "cases.compile_the_tender_control_price_and_price_a_bid.step.evaluate.why",
      whyDefault:
        "Two checks are not judgment, and the product does not make them for you: under the 2024 standard a bid above the published maximum bid price is rejected, and so is a bid below cost, so read every total against the ceiling before you read anything else. Below the ceiling the comparison is yours to make and yours to justify. On public work the reasoning is read months later by somebody who was not in the room, and a written comparison against a stated base is the difference between an award that survives a challenge and one that is defended from memory.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
  ],
};

export default playbook;
