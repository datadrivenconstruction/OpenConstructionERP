// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Case: "Take off quantities from a PDF plan" (DE).
//
// A Kalkulator or Handwerksmeister is invited to tender and gets PDF sheets and
// nothing else: no DWG, no model. This case walks the plan into calibrated,
// named measurements and out again as BOQ positions ready for pricing, with the
// chain from the quantity back to the line on the drawing left intact - which is
// what a checkable Aufmass means in the German market. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "takeoff-quantities-from-a-pdf-plan",
  order: 1048,
  category: "estimating",
  companyTypes: ["subcontractor", "general-contractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor"],
  region: "DE",
  icon: "Ruler",
  titleKey: "cases.takeoff_quantities_from_a_pdf_plan.title",
  titleDefault: "Take off quantities from a PDF plan",
  descKey: "cases.takeoff_quantities_from_a_pdf_plan.desc",
  descDefault:
    "The tender arrives as PDF sheets with no model behind them. Calibrate the plan, measure lengths, areas and counts on screen, and land them as BOQ positions where every number still points back to the line you drew.",
  longDescKey: "cases.takeoff_quantities_from_a_pdf_plan.longdesc",
  longDescDefault:
    "German quantity practice expects an Aufmass a third party can check: every figure traceable to a measurement, and the measurement taken the way VOB/C settles that trade. Measuring on the drawing itself keeps that chain whole, which a scale rule and a spreadsheet cannot.",
  estMinutes: 14,
  steps: [
    {
      id: "file",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.in.plans", label: "Tender plan set (PDF)" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.in.revision", label: "Sheet and revision list" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.out.filed", label: "Filed drawing revision" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.out.ready", label: "Sheets ready for takeoff" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.title",
      titleDefault: "File the tender plan set",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.what",
      whatDefault:
        "Put the PDF sheets the client issued into the project files, each carrying the sheet number and revision it was issued under. Takeoff picks the file up from here, so you measure the drawing on record rather than a copy out of an inbox.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.file.why",
      whyDefault:
        "An Aufmass can only be checked if the reader can find the sheet it came from. Filing the issued revision first means every quantity you produce later names a drawing that still exists in the same form.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "calibrate",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.in.sheet", label: "Filed PDF sheet" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.in.dimension", label: "Dimension stated on the plan" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.out.scale", label: "Calibrated scale" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.out.sheet", label: "Measurable sheet" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.title",
      titleDefault: "Calibrate the plan scale",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.what",
      whatDefault:
        "Open the sheet on the Measurements tab and calibrate before you draw anything. Click the two ends of a dimension the plan already states, type its real length, and every later measurement converts to metres. On a clean vector sheet you can take the stated scale, 1:50 or 1:100, as a preset instead.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.calibrate.why",
      whyDefault:
        "A plan that has been through a plotter or a scanner is rarely at the scale printed on it. Calibrating against a stated dimension costs a minute, while a scale two percent out multiplies quietly through every area on the sheet and only surfaces at Abrechnung.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements&name=A-2.01%20Grundriss%20Erdgeschoss%20%28Index%20A%29.pdf",
    },
    {
      id: "measure",
      icon: "PencilRuler",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.in.sheet", label: "Calibrated sheet" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.in.rules", label: "Measurement rules of the trade" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.out.measurements", label: "Measured lengths and areas" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.out.counts", label: "Counted items" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.title",
      titleDefault: "Measure lengths, areas and counts",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.what",
      whatDefault:
        "Work the sheet trade by trade. Area for floors, screed and wall faces, distance or polyline for skirting, kerb and pipe runs, count for doors, sockets and fittings. Give an area a depth where you need the volume, and take openings off the way section 5 of that trade's ATV in VOB/C requires, which for most trades means an opening up to 2.5 square metres is measured over and a larger one is deducted.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.measure.why",
      whyDefault:
        "The rate you are pricing is a rate per the quantity the contract measures, and VOB/C sets those rules trade by trade. Measuring the way the trade is settled keeps the figure in your offer and the figure in the final account the same figure.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements&name=A-2.01%20Grundriss%20Erdgeschoss%20%28Index%20A%29.pdf",
    },
    {
      id: "organise",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.in.raw", label: "Raw measurements" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.in.trades", label: "Trade breakdown" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.out.ledger", label: "Named measurement ledger" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.out.groups", label: "Grouped by trade" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.title",
      titleDefault: "Name and group every measurement",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.what",
      whatDefault:
        "In the measurement ledger give each entry a description a stranger would recognise, the storey or room it sits in, and a group per trade. The ledger keeps every entry beside its shape on the sheet, so clicking the line takes you back to the drawing.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.organise.why",
      whyDefault:
        "A checkable Aufmass is one where a number leads back to a named measurement on a named sheet. Naming costs seconds now and saves the afternoon when the client asks where a figure came from.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff?tab=measurements&name=A-2.01%20Grundriss%20Erdgeschoss%20%28Index%20A%29.pdf",
    },
    {
      id: "review",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.in.ledger", label: "Ledger entries" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.in.scope", label: "Scope you expect to price" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.out.rollup", label: "Checked quantity rollup" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.out.export", label: "Rollup export" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.title",
      titleDefault: "Review the quantity rollup",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.what",
      whatDefault:
        "Open the measured quantities register, which rolls up everything captured so far grouped by unit, trade or source with running totals. Filter it down to one drawing or one trade and read the totals against the building you expect. Export the rollup when somebody else has to check it.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.review.why",
      whyDefault:
        "A storey measured twice and a storey missed altogether both look plausible on the sheet and obvious in the total. This is the last cheap place to catch either, before a wrong quantity gets a price and leaves the office in your offer.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "positions",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.in.confirmed", label: "Confirmed measurements" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.in.bill", label: "Target bill" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.out.positions", label: "Positions with quantities" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.out.trace", label: "Link back to the drawing" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.title",
      titleDefault: "Land them as BOQ positions",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.what",
      whatDefault:
        "Confirm the measurements you trust into the bill. Each one becomes a position carrying its quantity and unit, and it stays linked to the measurement on the drawing, so a reissued sheet updates the quantity in place instead of sending you back to the start of the takeoff.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.positions.why",
      whyDefault:
        "This is where a measured building turns into something you can price. Because each position keeps its link, the chain from the money back to the line on the plan stays intact, which is exactly what a client checking your Aufmass asks to see.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "export",
      icon: "FileOutput",
      inputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.in.positions", label: "Positions with quantities" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.in.recipient", label: "Recipient's GAEB software" },
      ],
      outputs: [
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.out.file", label: "GAEB XML file" },
        { labelKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.out.record", label: "Bill issued for pricing" },
      ],
      titleKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.title",
      titleDefault: "Issue the bill as GAEB",
      whatKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.what",
      whatDefault:
        "Export the finished bill as a GAEB XML file straight from the BOQ editor, as an X83 Angebotsaufforderung, the exchange phase for a bill that goes out to be priced. What leaves the office is the same structure you built from the takeoff, positions, quantities and units, in the exchange format every German AVA package opens without retyping.",
      whyKey: "cases.takeoff_quantities_from_a_pdf_plan.step.export.why",
      whyDefault:
        "A bill that travels as GAEB stays a bill instead of becoming a PDF someone retypes with new mistakes. The quantities you measured arrive in the other side's software as data, and the Aufmass chain behind them survives the handover.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
  ],
};

export default playbook;
