// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure a bill of quantities to ASMM 6" (AU).
//
// Detailed measurement under the Australian Standard Method of Measurement of
// Building Works, sixth edition, published by the Australian Institute of
// Quantity Surveyors and Master Builders Australia. The preambles are settled
// before a single dimension is taken, the quantities are net of the finished
// work, the waste sits in the rate rather than in the quantity, and the
// provisional and prime cost sums stay on the allowances register. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-a-bill-of-quantities-to-asmm-6",
  order: 1600,
  region: "AU",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "project-manager"],
  roles: ["quantity-surveyor", "estimator"],
  stage: "estimate",
  icon: "Ruler",
  titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.title",
  titleDefault: "Measure a bill of quantities to ASMM 6",
  descKey: "cases.measure_a_bill_of_quantities_to_asmm_6.desc",
  descDefault:
    "Settle the preambles before you measure, take the dimensions off the drawings, keep the quantities net and the waste in the rate, write the items in the trade sections the standard sets, hold the provisional and prime cost sums out of the rates and validate the bill before it goes to tender.",
  longDescKey: "cases.measure_a_bill_of_quantities_to_asmm_6.longdesc",
  longDescDefault:
    "The Australian Standard Method of Measurement of Building Works is the rule set an Australian bill of quantities is measured under, and its sixth edition is the one in current use. It does two things at once that are easy to confuse. It says how each item is measured, in what unit and to what level of detail, and it says what every rate is deemed to include, which is the half that decides arguments later. A bill measured to the standard can be priced by six tenderers who all read the same words the same way, and a variation valued against it two years on starts from a quantity nobody has to re-take. This case measures one bill from the drawings to the tender issue, and keeps the two things the standard insists are kept apart genuinely apart: quantities that are net of the finished work, and the waste, laps and returns that belong in the rate.",
  estMinutes: 20,
  steps: [
    {
      id: "preambles",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.in.standard", label: "Method of measurement adopted" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.in.scope", label: "Scope and exclusions" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.out.preambles", label: "Preambles recorded" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.out.deemed", label: "What each rate is deemed to include" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.title",
      titleDefault: "Settle the preambles before you take a dimension",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.what",
      whatDefault:
        "Write the basis down first: that the bill is measured to the Australian Standard Method of Measurement of Building Works, sixth edition, which departures from it the job needs and why, what the rates are deemed to include, and what the bill does not cover. Record the drawing revisions the measurement is being taken from in the same place.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.preambles.why",
      whyDefault:
        "The preambles are the part of the bill that is read only when there is a dispute, which is exactly why they have to be written when there is not. A tenderer who priced a rate on the assumption it excluded something the measurer assumed it included has not made an arithmetic mistake, and no amount of levelling afterwards recovers the difference.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "measure",
      icon: "PencilRuler",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.in.drawings", label: "Tender drawings" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.in.preambles", label: "Preambles recorded" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.out.dimensions", label: "Dimensions taken off" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.out.sheet", label: "Every measurement tied to a sheet" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.title",
      titleDefault: "Take the dimensions off the drawings",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.what",
      whatDefault:
        "Open the drawings on the measurement canvas, calibrate the scale against a figured dimension rather than a printed scale bar, and take the areas in square metres, the lengths in metres and the counts each trade section needs. Every measurement keeps the sheet number and the revision it came off.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.measure.why",
      whyDefault:
        "A drawing is reissued on every live job, and the only measurements that survive a reissue are the ones you can find again. A quantity with no sheet behind it cannot be rechecked, so it has to be re-taken from scratch, and the second take-off never agrees with the first.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements",
    },
    {
      id: "net",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.in.dimensions", label: "Dimensions taken off" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.in.methods", label: "How the trade is actually built" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.out.net", label: "Net quantities of finished work" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.out.waste", label: "Waste carried in the rate" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.title",
      titleDefault: "Keep the quantity net and the waste in the rate",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.what",
      whatDefault:
        "Set the waste allowance for each material on its own register, so the bill quantity stays the net quantity of finished work the standard asks for and the cutting, laps, returns and breakage are priced where they belong. Reinforcement laps, tile cutting and plasterboard offcuts all live here rather than in the measured area.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.net.why",
      whyDefault:
        "A quantity quietly grossed up for waste reads as a measurement and behaves as a rate, and nobody downstream can tell which it is. It also breaks the one thing a bill is for, because the next valuation measures the finished work on site and finds less of it than the bill said there would be.",
      moduleLabel: "Waste Factors",
      moduleLabelKey: "nav.waste_factors",
      to: "/waste-factors",
    },
    {
      id: "bill",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.in.net", label: "Net quantities of finished work" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.in.rates", label: "Unit rates" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.out.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.out.sections", label: "Items in their trade sections" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.title",
      titleDefault: "Write each item the way the standard describes it",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.what",
      whatDefault:
        "Write each item with the description, the unit and the quantity the standard calls for, and group the items into the trade sections it organises the work by. Price them from the cost database or from your own rates. An Australian bill is measured by trade, and the elemental view of the same money is produced alongside it rather than instead of it.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.bill.why",
      whyDefault:
        "The description is the contract between the measurer and the estimator. An item written loosely gets priced six different ways by six tenderers, and the levelling that follows is an argument about your own words rather than about their offers.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
    {
      id: "sums",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.in.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.in.undesigned", label: "Work not yet designed" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.out.provisional", label: "Provisional sums held" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.out.pc", label: "Prime cost sums on the register" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.title",
      titleDefault: "Hold the provisional and prime cost sums out of the rates",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.what",
      whatDefault:
        "Put each provisional sum and each prime cost sum on the register as its own entry, with the amount, what it is meant to cover and the allowance for the builder's profit and attendance on it. Draw against them as the work is instructed and watch what is left.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.sums.why",
      whyDefault:
        "A sum folded into a rate is a sum nobody can release and nobody can adjust, so the contract sum adjustment at the end becomes archaeology. Held openly, both sides read the same figure and the final account is arithmetic.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.in.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.in.sums", label: "Sums on the register" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.out.cleared", label: "Bill cleared for tender" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.title",
      titleDefault: "Validate the bill before it goes to tender",
      whatKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.what",
      whatDefault:
        "Run the bill through validation for the item left at zero, the unit that contradicts its own description, the quantity that no longer agrees with the take-off it came from and the trade section that was never measured at all. Fix what it reports and run it again until it comes back clean.",
      whyKey: "cases.measure_a_bill_of_quantities_to_asmm_6.step.check.why",
      whyDefault:
        "One bill goes to every tenderer at once, so one mistake is priced by all of them. Catching it while the document is still yours costs an hour; catching it after the tenders are in costs a re-tender or a variation on day one.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
  ],
};

export default playbook;
