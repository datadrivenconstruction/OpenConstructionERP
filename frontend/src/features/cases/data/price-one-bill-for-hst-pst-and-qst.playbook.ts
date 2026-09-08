// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price one bill for HST, PST and QST" (CA).
//
// Sales tax in Canada is a question about WHERE a cost sits rather than a
// percentage on the end. The same bill priced in three provinces does not just
// total differently: the tax lands inside the unit rate in one, on the invoice
// tail in another, and as two parallel lines on one base in the third. That is
// the only case in the Canadian set about a number being somewhere else rather
// than about a number being wrong. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-one-bill-for-hst-pst-and-qst",
  order: 1106,
  region: "CA",
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "developer-client"],
  roles: ["estimator", "quantity-surveyor", "accountant", "commercial-manager"],
  icon: "Percent",
  titleKey: "cases.price_one_bill_for_hst_pst_and_qst.title",
  titleDefault: "Price one bill for HST, PST and QST",
  descKey: "cases.price_one_bill_for_hst_pst_and_qst.desc",
  descDefault:
    "Settle province by province whether the sales tax on a cost is money you get back or money you carry, put the tax you carry inside the unit rate and the tax you recover on the tail, and record the rate you used with its date and the base it was taken on.",
  longDescKey: "cases.price_one_bill_for_hst_pst_and_qst.longdesc",
  longDescDefault:
    "Canadian sales tax is a question about where a cost sits, not a percentage on the end, and that is why the same bill priced in three provinces is three differently built estimates rather than three totals. In the harmonised provinces the tax goes on the tail and comes back, so it is not a cost at all and a cost plan carrying it is overstated. In British Columbia, Saskatchewan and Manitoba the provincial part on materials is frequently a cost the contractor carries and never recovers, which puts it inside the unit rate rather than on the tail. In Quebec two taxes run in parallel on the same pre-tax base. The rates as they stand: 5 percent federal everywhere, 13 percent harmonised in Ontario, 15 percent in New Brunswick, Newfoundland and Labrador and Prince Edward Island, 14 percent in Nova Scotia since 1 April 2025, 12 percent in British Columbia and in Manitoba, 11 percent in Saskatchewan, 14.975 percent in Quebec, and 5 percent only in Alberta and the three territories. Note the mechanical point that most bids get wrong: the Quebec tax and the British Columbia, Saskatchewan and Manitoba provincial taxes are charged on the price before the federal tax, not on a federal-tax-inclusive figure.",
  estMinutes: 18,
  steps: [
    {
      id: "position",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.in.provinces", label: "Provinces the work touches" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.in.position", label: "Your recovery position" },
      ],
      outputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.out.decision", label: "A written decision per province" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.out.split", label: "What is a cost and what is not" },
      ],
      titleKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.title",
      titleDefault: "Decide per province what you recover and what you carry",
      whatKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.what",
      whatDefault:
        "For every province the work touches, settle whether the provincial tax on materials is recoverable in your position or a cost you carry, and write the decision down before a single rate is entered. Saskatchewan reverses the picture: since 2017 a contractor charges PST on the whole contract price for work on real property and buys the materials exempt for resale, so there the tax belongs on the tail and not in the rate, and Manitoba does the same for mechanical and electrical work.",
      whyKey: "cases.price_one_bill_for_hst_pst_and_qst.step.position.why",
      whyDefault:
        "This one decision moves the tax between two completely different places in the estimate. Getting it wrong does not produce a wrong total, it produces a right total built the wrong way, which passes review cleanly and then fails at the first cost report when the recovery nobody was entitled to does not arrive.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "inside",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.in.rates", label: "Material rates" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.in.position", label: "The provincial position for this job" },
      ],
      outputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.out.rates", label: "Rates carrying the tax they cost" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.out.noted", label: "Position noted on the rate" },
      ],
      titleKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.title",
      titleDefault: "Put the tax you carry inside the material rate",
      whatKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.what",
      whatDefault:
        "Where the provincial tax on materials is a cost you never recover, build it into the material rate in the catalog rather than adding it at the end, and note on the rate that it is tax inclusive so the next reader knows.",
      whyKey: "cases.price_one_bill_for_hst_pst_and_qst.step.inside.why",
      whyDefault:
        "A tax you do not get back is simply part of what the material costs you, and every rate built without it understates the job by the tax on your largest cost line. Putting it on the tail instead makes it look recoverable to everybody who reads the estimate after you, including the person who prepares the cost plan.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "tail",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.in.subtotal", label: "Pre-tax subtotal" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.in.rates", label: "Federal and provincial rates" },
      ],
      outputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.out.lines", label: "Tax lines on the correct base" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.out.buildup", label: "A build-up the client can check" },
      ],
      titleKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.title",
      titleDefault: "Put the tax you recover on the tail, on the right base",
      whatKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.what",
      whatDefault:
        "Add the recoverable tax as a line on the tail at the rate for the province, and where two taxes run in parallel add both of them on the same pre-tax subtotal rather than one on top of the other's result.",
      whyKey: "cases.price_one_bill_for_hst_pst_and_qst.step.tail.why",
      whyDefault:
        "Stacking one tax on a figure that already includes the other is a small percentage of the whole contract, which is more than the margin on most of it. The province decides the base as much as it decides the rate, and a build-up showing which base was used is the difference between a client checking your tax in a glance and a client checking it with their accountant.",
      moduleLabel: "Markups",
      moduleLabelKey: "nav.markups",
      to: "/markups",
    },
    {
      id: "dates",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.in.applied", label: "Rates applied per province" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.in.sources", label: "Effective dates and sources" },
      ],
      outputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.out.basis", label: "A dated tax basis" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.out.repriceable", label: "An estimate that can be re-priced" },
      ],
      titleKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.title",
      titleDefault: "Record the rate you used and the date it applied from",
      whatKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.what",
      whatDefault:
        "Write into the basis of estimate the rate used for each province, the date that rate took effect, the authority that publishes it, and which side of the pre-tax line each one was computed on.",
      whyKey: "cases.price_one_bill_for_hst_pst_and_qst.step.dates.why",
      whyDefault:
        "Rates move, and a bid priced last quarter was priced under the rate in force then. Nova Scotia went from 15 to 14 percent on 1 April 2025, and an estimate that cannot say which of the two it used cannot be defended in either direction when the question comes up nine months later.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "compare",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.in.priced", label: "The same bill priced per province" },
      ],
      outputs: [
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.out.located", label: "Totals with the tax located" },
        { labelKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.out.explained", label: "A difference you can explain" },
      ],
      titleKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.title",
      titleDefault: "Show the same bill per province and say what moved",
      whatKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.what",
      whatDefault:
        "Report the same scope priced for each province, keeping the tax that sits inside the rates separate from the tax on the tail, so the difference reads as a location rather than as a total.",
      whyKey: "cases.price_one_bill_for_hst_pst_and_qst.step.compare.why",
      whyDefault:
        "Three totals tell a client nothing they could not get from a rate table. Showing that the money is inside the rate in one province and on the tail in another is what explains why the same building costs what it costs across a border, and that is the conversation that wins the work rather than the number.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
