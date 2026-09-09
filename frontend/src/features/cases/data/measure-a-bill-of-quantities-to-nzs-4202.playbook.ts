// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure a bill of quantities to NZS 4202" (NZ).
//
// The New Zealand standard method of measurement of building works. A bill
// measured to a stated method is what lets several tenderers price the same
// quantities, so the differences between their tenders are commercial rather
// than arithmetic. The rules that matter here are the boring ones: what is
// measured, in what unit, and what the rate is deemed to already include.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-a-bill-of-quantities-to-nzs-4202",
  order: 1430,
  region: "NZ",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  roles: ["quantity-surveyor", "estimator", "commercial-manager"],
  icon: "Ruler",
  titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.title",
  titleDefault: "Measure a bill of quantities to NZS 4202",
  descKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.desc",
  descDefault:
    "Measure net as fixed in place under the New Zealand standard method, build the composite items so each rate carries what the standard deems included, arrange the bill in its trade sections with preliminary and general, keep waste in the rate, check the bill against the rules and write the preambles that record the method and every departure from it.",
  longDescKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.longdesc",
  longDescDefault:
    "NZS 4202:1995 is the standard method of measurement of building works in New Zealand, and its job is to remove one whole class of argument from tendering. If every tenderer is measuring the same way, the quantities are common ground and the tender is a contest about rates, method and risk. If they are not, the cheapest tender is often just the one that measured least, and that difference surfaces on site as a variation nobody budgeted. The standard settles what is measured and in what unit, and just as importantly what a rate is deemed to already include, which is where most of the money hides. None of it works without the preambles: the standard expects departures to be stated, and an unstated departure is worse than no standard at all, because everybody is entitled to assume the rules were followed.",
  estMinutes: 16,
  steps: [
    {
      id: "measure",
      icon: "PencilRuler",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.in.drawings",
          label: "Drawings and specification",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.in.rules",
          label: "Measurement rules for the trade",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.out.net",
          label: "Net quantities as fixed in place",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.out.dims",
          label: "Dimensions traceable to a drawing",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.title",
      titleDefault: "Measure net as fixed in place",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.what",
      whatDefault:
        "Take off quantities the way the standard measures them: net as the work is fixed in place, in the unit the rule for that trade names, with the deductions the rule requires and no others. Keep each dimension attached to the drawing and revision it came from so the take-off can be re-read rather than re-done.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.measure.why",
      whyDefault:
        "Net measurement is what makes two bills comparable, and it is also what makes a bill re-measurable when the design moves. A quantity that already has an allowance baked into it cannot be checked against a drawing by anybody except the person who made it, and that person is usually the one not available when the tender query arrives.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "compose",
      icon: "Layers",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.in.net",
          label: "Net quantities as fixed in place",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.in.deemed",
          label: "What the rate is deemed to include",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.out.items",
          label: "Composite items built",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.out.coverage",
          label: "Coverage rules written into the item",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.title",
      titleDefault: "Build items that carry what the rate includes",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.what",
      whatDefault:
        "Assemble each measured item as the composite the standard describes: the labour, the material, the plant and the incidental work the rule says the rate covers. Where a rule deems something included, put it inside the assembly rather than leaving it as a separate line somebody will price twice.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.compose.why",
      whyDefault:
        "Nearly every dispute about a bill is a coverage dispute, not a quantity one: two people agreeing on the square metres and disagreeing about whether the rate included the edge trim. Building the coverage into the item makes it visible to the estimator pricing it and to the contractor reading it, which is the only place it can be settled cheaply.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "bill",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.in.items",
          label: "Composite items built",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.in.sections",
          label: "Trade section structure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.out.bill",
          label: "Bill in its trade sections",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.out.pg",
          label: "Preliminary and general separated",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.title",
      titleDefault: "Arrange the bill the way tenderers will read it",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.what",
      whatDefault:
        "Put the measured work into the trade sections the standard uses, and keep preliminary and general as its own section rather than spreading site costs through the trades. Carry provisional and prime cost sums as their own items with what they cover written against them.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.bill.why",
      whyDefault:
        "A bill is priced by subcontractors who each read one section and ignore the rest, so the structure decides who sees what. Time-related site cost buried in the trades is cost nobody prices as time-related, and it is the first thing to be argued about when the job runs long.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "waste",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.in.net",
          label: "Net measured quantity",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.in.material",
          label: "Material and cutting pattern",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.out.factor",
          label: "Waste held in the rate",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.out.purchase",
          label: "Purchase quantity kept separate",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.title",
      titleDefault: "Keep waste in the rate and out of the quantity",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.what",
      whatDefault:
        "Set the waste allowance per material as a factor the rate carries, and let the purchase quantity be derived from it rather than typed into the bill. The measured quantity stays the net one the drawing supports; the quantity ordered from the merchant is a different number for a different purpose.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.waste.why",
      whyDefault:
        "Waste added to the measured quantity breaks the one property that makes a bill useful, which is that anybody can check it against the drawing. It also double counts the moment a rate that already allows for waste is applied to a quantity that also does, and nobody notices because both numbers look reasonable on their own.",
      moduleLabel: "Waste Factors",
      moduleLabelKey: "nav.waste_factors",
      to: "/waste-factors",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.in.bill",
          label: "Bill in its trade sections",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.in.rules",
          label: "Rules the bill claims to follow",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.out.findings",
          label: "Items that break a rule",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.out.clean",
          label: "Bill fit to go out",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.title",
      titleDefault: "Check the bill against the rules it claims to follow",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.what",
      whatDefault:
        "Run the bill through the checks before it goes out: items with a unit that does not match the rule for their trade, items with no quantity, sections the drawings imply and the bill does not carry, and rates that fall outside a sane band for their unit. Fix what is wrong and record what is deliberate.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.check.why",
      whyDefault:
        "A bill goes to several tenderers on the same day, so an error in it is not one error, it is one error multiplied by the number of people pricing it, and every one of them prices around it differently. Half an hour of checking before issue is the cheapest half hour in the whole tender period.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "preambles",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.in.bill",
          label: "Bill fit to go out",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.in.departures",
          label: "Departures from the standard",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.out.basis",
          label: "Method of measurement stated",
        },
        {
          labelKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.out.exclusions",
          label: "Exclusions and assumptions listed",
        },
      ],
      titleKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.title",
      titleDefault: "State the method, the drawings and every departure",
      whatKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.what",
      whatDefault:
        "Record the basis of the bill in one place: that it is measured to NZS 4202, the drawings and revisions it was measured from, the specification it reads with, every departure from the standard and every exclusion and assumption the quantities rest on. Issue it with the bill rather than keeping it in the file.",
      whyKey: "cases.measure_a_bill_of_quantities_to_nzs_4202.step.preambles.why",
      whyDefault:
        "The standard only does its job when the departures are stated, because a tenderer is entitled to assume the rules were followed everywhere it is silent. A bill issued without its basis puts the risk of every unstated assumption onto whoever priced it, which is the party least able to see it, and that is exactly the claim that comes back nine months later.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
  ],
};

export default playbook;
