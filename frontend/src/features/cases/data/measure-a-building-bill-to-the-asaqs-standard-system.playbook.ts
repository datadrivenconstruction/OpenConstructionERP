// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure a building bill to the ASAQS standard system" (ZA).
//
// South African building work is measured to the ASAQS Standard System of
// Measuring Building Work, and civil engineering work to the SANS 1200 and
// SANS 2001 series. That is a different document from the British method, and
// the visible difference on a JBCC job is Bill No 1: the preliminaries are
// priced in three categories, fixed charges, value related charges and time
// related charges, so an adjustment to the contract value moves only the part
// of them that is tied to value. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-a-building-bill-to-the-asaqs-standard-system",
  order: 1341,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  roles: ["quantity-surveyor", "estimator"],
  region: "ZA",
  stage: "estimate",
  icon: "Ruler",
  titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.title",
  titleDefault: "Measure a building bill to the ASAQS standard system",
  descKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.desc",
  descDefault:
    "Take the quantities off the drawings, build the bill in the trade order the standard system uses, price Bill No 1 preliminaries as fixed, value related and time related charges, and issue a pricing document a contractor can tender on without asking you what a rate covers.",
  longDescKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.longdesc",
  longDescDefault:
    "A bill of quantities is only worth measuring if every tenderer reads each item the same way, and what makes that true here is the ASAQS Standard System of Measuring Building Work for building work and the SANS 1200 and SANS 2001 series for civil engineering work. The document is not the British one, and the place a British-trained measurer notices it first is the preliminaries. On a JBCC job Bill No 1 is priced in three categories rather than two, fixed charges, value related charges and time related charges, and clause 26.9 adjusts them on that basis when the contract value or the construction period changes. Getting the split right at tender is what makes the adjustment arithmetic later rather than an argument.",
  estMinutes: 14,
  steps: [
    {
      id: "takeoff",
      icon: "PencilRuler",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.in.drawings", label: "Tender drawings" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.in.spec", label: "Specification" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.out.quantities", label: "Measured quantities" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.out.trail", label: "Measurement trail" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.title",
      titleDefault: "Take the quantities off the drawings",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.what",
      whatDefault:
        "Scale the tender drawings, measure element by element and keep each measurement attached to the sheet and the area it came from, so a quantity can be traced back to the line on the drawing that produced it.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.takeoff.why",
      whyDefault:
        "A bill without a measurement trail cannot be remeasured, and remeasurement is exactly what clause 26.9 of the JBCC principal building agreement asks for when quantities in the priced document turn out to be wrong. Quantities that can be pointed back at a drawing settle that in an afternoon; quantities that exist only as totals turn it into a dispute.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements",
    },
    {
      id: "trades",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.in.quantities", label: "Measured quantities" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.in.standard", label: "Measurement standard" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.out.bill", label: "Structured bill" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.out.descriptions", label: "Item descriptions" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.title",
      titleDefault: "Build the bill in the standard trade order",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.what",
      whatDefault:
        "Lay the bill out in the trade sections the ASAQS Standard System of Measuring Building Work uses, write each item description to the unit and the coverage rule that section gives it, and keep civil engineering work in its own bill measured to SANS 1200.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.trades.why",
      whyDefault:
        "The standard system exists so that an item description carries a known coverage: what the rate includes and what has to be measured separately. A bill written in a house style makes every tenderer guess at that boundary, and a bill priced on different guesses is not a comparison of prices, it is a comparison of assumptions.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "prelims",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.in.programme", label: "Construction period" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.in.site", label: "Site constraints" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.out.bill1", label: "Bill No 1" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.out.split", label: "Three charge categories" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.title",
      titleDefault: "Price Bill No 1 in the three charge categories",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.what",
      whatDefault:
        "Set out the preliminaries as Bill No 1 and split every item into the category it belongs to: fixed charges that happen once regardless of value or time, value related charges that move with the contract value, and time related charges that move with the construction period.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.prelims.why",
      whyDefault:
        "Clause 26.9 of the JBCC principal building agreement adjusts preliminaries on exactly this split when the contract value or the period changes, and a lump sum preliminaries figure gives it nothing to work with. A contractor who has priced site establishment as a fixed charge and site management as a time related charge gets paid for an extension of time; one who lumped them together argues for it.",
      moduleLabel: "Preliminaries",
      moduleLabelKey: "nav.preliminaries",
      to: "/preliminaries",
    },
    {
      id: "rates",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.in.items", label: "Bill items" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.in.resources", label: "Labour and material prices" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.out.buildups", label: "Rate build-ups" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.out.priced", label: "Priced items" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.title",
      titleDefault: "Build the rates from labour, material and plant",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.what",
      whatDefault:
        "Price each item from a written build-up rather than from memory: the labour constant, the material with its waste allowance, and the plant the item needs, so the rate can be taken apart again by anyone who asks.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.rates.why",
      whyDefault:
        "Clause 26.2 of the JBCC principal building agreement values work of a similar character at the rates in the priced document, and work that is not similar at rates based on them. Both of those need a rate you can open up. A rate held in one estimator's head prices the tender and then cannot value a single instruction for the next two years.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "markups",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.in.direct", label: "Direct cost" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.in.cpap", label: "CPAP indices" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.out.rates", label: "Markup rates" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.out.tender", label: "Tender sum" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.title",
      titleDefault: "Set the markups and decide on price adjustment",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.what",
      whatDefault:
        "In the bill's Markups & Overheads panel, load the South African markup template, set overheads and profit against the cost element each belongs to, and decide whether the contract carries contract price adjustment. Where it does, the adjustment is the Haylett formula worked on the Statistics South Africa work group indices named in the contract data.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.markups.why",
      whyDefault:
        "A fixed price bid on a two year building contract is a bet on the rand price of steel and cement, and contract price adjustment is the mechanism the market uses instead of that bet. Deciding it at tender rather than at the first cement increase is what keeps the decision commercial rather than adversarial, and clause 26.9 of the JBCC principal building agreement expects the basis to be in the priced document already.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.in.bill", label: "Priced bill" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.in.rules", label: "Validation rules" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.out.fixes", label: "Corrected items" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.title",
      titleDefault: "Run the bill through validation before it goes out",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.what",
      whatDefault:
        "Check the bill for the faults that survive a read-through: an item with a unit that does not match its description, a quantity of zero left in from a superseded drawing, a rate that is an order of magnitude away from its neighbours, a section that carries no preliminaries at all.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.check.why",
      whyDefault:
        "An error in a bill of quantities issued for tender is not a private mistake. Under clause 23.2 of the JBCC principal building agreement an inaccurate quantity in the priced document is a ground for revising the date for practical completion with an adjustment of the contract value, so the employer pays for it twice, in money and in time.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "issue",
      icon: "FileOutput",
      inputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.in.bill", label: "Validated bill" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.in.list", label: "Tenderer list" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.out.document", label: "Pricing document" },
        { labelKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.out.summary", label: "Bill summary" },
      ],
      titleKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.title",
      titleDefault: "Issue the pricing document and its summary",
      whatKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.what",
      whatDefault:
        "Export the bill as the pricing document tenderers price into, with the bill summary that carries the section totals, the preliminaries and the provisional sums, budgetary allowances and prime cost amounts stated separately.",
      whyKey: "cases.measure_a_building_bill_to_the_asaqs_standard_system.step.issue.why",
      whyDefault:
        "Clause 17.1.13 of the JBCC principal building agreement lets the principal agent instruct the expenditure of budgetary allowances, prime cost amounts and provisional sums, and clause 26.9 adjusts them against what was actually spent. That only works if they were shown separately at tender. A bill that buries them inside trade totals cannot be adjusted without reopening the whole price.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
