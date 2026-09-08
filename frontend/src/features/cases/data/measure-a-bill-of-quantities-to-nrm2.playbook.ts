// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure a bill of quantities to NRM 2" (GB).
//
// Detailed measurement under NRM 2, from the drawing to a bill that is safe to
// send out. The provisional and prime cost sums stay on the allowances
// register rather than being folded into rates, and the preliminaries are
// priced as their own work section. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-a-bill-of-quantities-to-nrm2",
  order: 1161,
  region: "GB",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "project-manager"],
  roles: ["quantity-surveyor", "estimator"],
  stage: "estimate",
  icon: "Ruler",
  titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.title",
  titleDefault: "Measure a bill of quantities to NRM 2",
  descKey: "cases.measure_a_bill_of_quantities_to_nrm2.desc",
  descDefault:
    "Measure off the drawings, roll the quantities up before writing a rate, write each item the way the rules ask and classify it to the NRM elements, keep the provisional and prime cost sums out of the rates, price the preliminaries as their own section and validate the lot before it goes out.",
  longDescKey: "cases.measure_a_bill_of_quantities_to_nrm2.longdesc",
  longDescDefault:
    "NRM 2 is the RICS rule set for detailed measurement, and the bill produced under it is the document every tenderer prices and every later variation is valued against. It is also where a project stops guessing: by RIBA Stage 4 the drawings are firm enough to measure, and the bill inherits whatever discipline that measurement had. This case measures from the drawings rather than from a supplier's take-off, keeps the sums that are not yet designed visible instead of hidden inside rates, prices the preliminaries out of what the job actually needs, and runs the whole bill through validation before several tenderers price the same mistake at once.",
  estMinutes: 20,
  steps: [
    {
      id: "measure",
      icon: "PencilRuler",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.in.drawings", label: "Tender drawings" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.in.register", label: "Drawing register" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.out.quantities", label: "Measured quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.out.tied", label: "Measurements tied to a drawing sheet" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.title",
      titleDefault: "Measure off the drawings at the right scale",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.what",
      whatDefault:
        "Open the tender drawings on the measurement canvas, set the scale from a dimension you trust, and measure the areas, lengths and counts each work section needs. Every measurement stays attached to the sheet and the revision it was taken from.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.measure.why",
      whyDefault:
        "NRM 2 measures net quantities of finished work, so the thing that decides whether a quantity survives a challenge is which drawing it came off and which revision that was. A measurement with no sheet behind it cannot be rechecked when the drawing is reissued, and on a live job the drawing is always reissued.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements",
    },
    {
      id: "rollup",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.in.measured", label: "Measured quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.in.bill", label: "Bill line quantities" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.out.rollup", label: "Quantity rollup by unit" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.out.outliers", label: "Outliers flagged for a recheck" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.title",
      titleDefault: "Roll the quantities up before you write a rate",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.what",
      whatDefault:
        "Open the measured quantities register. It gathers the take-off measurements and the quantities already sitting on the bill into one rollup, grouped by unit, trade or source, with running totals that never mix units.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.rollup.why",
      whyDefault:
        "A rollup by unit is the cheapest error check in measurement. A wall area that came out an order of magnitude wrong is invisible in a list of two hundred measurements and obvious in a total, and looking costs nothing while the rates are still off.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "bill",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.in.rollup", label: "Quantity rollup by unit" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.in.rates", label: "Unit rates" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.out.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.out.sections", label: "Items classified to NRM groups" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.title",
      titleDefault: "Write each item the way the rules ask and classify it",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.what",
      whatDefault:
        "Write each bill item as NRM 2 asks for it, a description that identifies the work, the unit of measurement and the measured quantity, and price it from the cost catalogue or from your own rates. Then classify the items: pick NRM as the standard and the picker offers the cost groups, from facilitating works and substructure through superstructure, internal finishes and services to external works. NRM 2 lets the bill be broken down by elements, by work sections or by work packages, and the elemental breakdown is the one that rolls straight back up into the NRM 1 cost plan.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.bill.why",
      whyDefault:
        "Classification is what makes one bill comparable with another bill and with the cost plan the job started from. A bill organised in whatever order the measurer happened to work in prices perfectly well and benchmarks against nothing, and putting the items into the same groups the estimate used is what lets somebody answer why this job came in above the last one.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
    {
      id: "sums",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.in.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.in.undesigned", label: "Items still to be designed" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.out.provisional", label: "Provisional sums held" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.out.pc", label: "Prime cost sums on the register" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.title",
      titleDefault: "Keep the provisional and prime cost sums out of the rates",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.what",
      whatDefault:
        "Put the defined and undefined provisional sums and the prime cost sums onto the register as their own entries, each with its amount and what it is meant to cover. As the work is instructed and valued, draw against them and watch the remainder.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.sums.why",
      whyDefault:
        "A provisional sum folded into a rate is a sum nobody can release, and an undefined one that a tenderer has quietly priced as though it were defined is an argument booked in for the first valuation. Held on the register both parties can see them, and the contract sum adjustment at the end becomes arithmetic rather than archaeology.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "prelims",
      icon: "HardHat",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.in.site", label: "Site establishment and welfare" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.in.programme", label: "Construction programme" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.out.priced", label: "Priced preliminaries" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.out.weekly", label: "Time-related cost per week" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.title",
      titleDefault: "Price the preliminaries as their own section",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.what",
      whatDefault:
        "Build the preliminaries out of the site establishment, site staff, temporary works, standing plant and welfare the job actually needs, splitting the time-related items from the fixed ones. The time-related lines follow the programme, so a longer job costs more here without anybody rewriting a rate.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.prelims.why",
      whyDefault:
        "Preliminaries are work section 1 of NRM 2 and they are also the section most often carried as a percentage of everything else. A percentage cannot answer the one question that matters when the programme slips, which is what a further six weeks on site costs, and a properly built prelims section answers it in a minute.",
      moduleLabel: "Preliminaries",
      moduleLabelKey: "nav.preliminaries",
      to: "/preliminaries",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.in.priced", label: "Priced bill of quantities" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.in.prelims", label: "Priced preliminaries" },
      ],
      outputs: [
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.out.cleared", label: "Bill cleared for tender" },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.title",
      titleDefault: "Validate the bill before it goes out",
      whatKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.what",
      whatDefault:
        "Run the bill through validation to catch the item left at zero, the quantity that no longer ties to the rollup, the unit that contradicts its own description and the section that got missed. Fix what it finds and run it again until it comes back clean.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nrm2.step.check.why",
      whyDefault:
        "A bill goes to several tenderers at once and every one of them prices the same mistake. An item with no quantity comes back priced six different ways, and the levelling that follows is then an argument about your own bill rather than about their offers.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
  ],
};

export default playbook;
