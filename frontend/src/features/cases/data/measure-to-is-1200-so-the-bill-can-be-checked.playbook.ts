// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure to IS 1200 so the bill can be checked" (IN).
//
// IS 1200 is the method of measurement for building and civil engineering
// works in India, written part by part: earthwork in one part, concrete in
// another, brickwork, plastering, steel, each with its own rules about what is
// measured, what is deducted and to what unit. A schedule of rates assumes
// those rules. A quantity arrived at some other way is not slightly different
// from the checker's quantity, it is a number their method cannot reproduce.
//
// This is a subcontractor's case first. Work measured on the main contract to
// IS 1200 and claimed by a subcontractor on a different basis produces a gap
// that nobody can reconcile line by line, and the party with the unusable
// measurement is the one who waits for money.
//
// The India pack ships cpwd.measurement_units, which asks that the unit on a
// line is one IS 1200 recognises and that it is metric. That rule is the last
// step here, and it is deliberately last: it catches what a careful takeoff
// still gets wrong, which is almost always the unit rather than the arithmetic.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-to-is-1200-so-the-bill-can-be-checked",
  order: 1181,
  region: "IN",
  category: "estimating",
  companyTypes: ["subcontractor", "general-contractor", "cost-consultant"],
  roles: ["quantity-surveyor", "estimator", "site-manager"],
  icon: "Ruler",
  titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.title",
  titleDefault: "Measure to IS 1200 so the bill can be checked",
  descKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.desc",
  descDefault:
    "Take the quantities off the drawing the way the Indian method of measurement says to take them, keep the units metric and recognised, and issue a measurement the other side can reproduce line by line instead of dispute in total.",
  longDescKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.longdesc",
  longDescDefault:
    "Two quantity surveyors measuring the same wall can differ by ten percent and both be working carefully, because measurement is a convention rather than a fact: whether the opening is deducted, whether the plaster is measured on the developed surface, whether the excavation is measured to the neat line or to the working space. IS 1200 settles those conventions trade by trade, and it settles them the same way for both sides of the contract. That is the whole value of measuring to it. A claim built on the standard method can be checked against the checker's own takeoff and agreed at the item that differs; a claim built on a private method can only be argued at the total, which is the slowest and least winnable argument there is. This case takes the work from drawing to agreed measurement without leaving the convention behind at any step.",
  estMinutes: 18,
  steps: [
    {
      id: "drawing",
      icon: "Ruler",
      inputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.in.plans",
          label: "Drawings for the work",
        },
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.in.scale",
          label: "A known scale or a dimension to set it",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.out.measured",
          label: "Measurements on the drawing",
        },
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.out.trace",
          label: "Each figure traceable to where it was taken",
        },
      ],
      titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.title",
      titleDefault: "Take the dimensions off the drawing, on the drawing",
      whatKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.what",
      whatDefault:
        "Calibrate the sheet against a stated dimension, then measure lengths, areas and counts directly on it, keeping each measurement attached to the place it was taken from. Work in metres and millimetres throughout.",
      whyKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.drawing.why",
      whyDefault:
        "A measurement that lives on the drawing can be re-opened and re-checked at the exact spot it came from. A measurement that lives only in a spreadsheet cell has to be re-taken from scratch by anyone who doubts it, which is how a query about one wall becomes a re-measure of a floor.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff",
    },
    {
      id: "rules",
      icon: "ListTree",
      inputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.in.raw",
          label: "Raw dimensions from the drawing",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.out.quantities",
          label: "Quantities on the standard method",
        },
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.out.deductions",
          label: "Deductions applied and visible",
        },
      ],
      titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.title",
      titleDefault: "Turn dimensions into quantities the standard way",
      whatKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.what",
      whatDefault:
        "Build the quantity register trade by trade, applying the deduction and inclusion rules the method of measurement sets for each: openings in masonry and plaster, the treatment of the working space in excavation, how reinforcement is measured against how it is placed. Keep the deduction on the register rather than folded into a net figure.",
      whyKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.rules.why",
      whyDefault:
        "The deductions are where two honest takeoffs separate, so they are exactly what a checker wants to see. A register that shows gross, deduction and net can be agreed in one pass; one that shows only net invites a full re-measure to find out why it is short.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "bill",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.bill.in.quantities",
          label: "The quantity register",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.bill.out.items",
          label: "Bill items with their quantities",
        },
      ],
      titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.bill.title",
      titleDefault: "Post the quantities onto the bill items they belong to",
      whatKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.bill.what",
      whatDefault:
        "Move the measured quantities onto the bill, matching each to the item whose description covers the work actually measured, and splitting a measurement across two items rather than stretching one description to cover both.",
      whyKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.bill.why",
      whyDefault:
        "An item description and a method of measurement are a pair: the description says what the rate includes and the method says how the quantity was arrived at. Posting a quantity under a description that does not cover it breaks the pair quietly, and the error surfaces at valuation as a rate that seems wrong.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "units",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.units.in.bill",
          label: "The measured bill",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.units.out.flagged",
          label: "Units the method does not recognise",
        },
      ],
      titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.units.title",
      titleDefault: "Check the units before anybody prices them",
      whatKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.units.what",
      whatDefault:
        "Validate the bill and read what comes back about units. The India pack ships a rule that asks for a unit the method of measurement recognises, and metric only, so an imperial leftover or an invented unit is reported rather than priced.",
      whyKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.units.why",
      whyDefault:
        "A wrong unit does not look wrong. It looks like a rate that is out by a factor, and it is usually blamed on the rate. Catching it as a unit finding names the actual defect and fixes one line instead of re-arguing a trade.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "issue",
      icon: "FileOutput",
      inputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.issue.in.agreed",
          label: "The checked measurement",
        },
      ],
      outputs: [
        {
          labelKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.issue.out.sheet",
          label: "A measurement sheet the other side can reproduce",
        },
      ],
      titleKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.issue.title",
      titleDefault: "Issue the measurement in a form the other side can re-do",
      whatKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.issue.what",
      whatDefault:
        "Produce the measurement sheet showing item, dimensions, deductions, unit and quantity, and send that rather than a single total per trade.",
      whyKey: "cases.measure_to_is_1200_so_the_bill_can_be_checked.step.issue.why",
      whyDefault:
        "Agreement is reached at the line that differs, and only a sheet that shows lines has one. Sending a total asks the other party to trust you, which on a running account nobody does twice.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
