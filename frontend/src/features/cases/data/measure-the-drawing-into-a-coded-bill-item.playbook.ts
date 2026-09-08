// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure the drawing into a coded bill item" (CN).
//
// Measurement under the bill of quantities valuation code produces something
// more particular than a number. It produces a bill item that carries its code
// from the national schedule and, beside the code, the statement of what the
// item covers - the grade, the thickness, the mix, the finish, the method. That
// statement is the ground for what the rate includes, and most final-account
// arguments in China start with one that did not say enough.
//
// So the case is measurement plus the two things that have to travel with the
// quantity, and it ends on validation, which reads the code and reports on its
// form. The distinction between a well-formed code and a code that exists in
// the national schedule is kept explicit, because a case about landing a
// CORRECT item cannot let the reader hear one as the other. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-the-drawing-into-a-coded-bill-item",
  order: 1126,
  region: "CN",
  category: "estimating",
  companyTypes: ["general-contractor", "cost-consultant", "subcontractor"],
  roles: ["estimator", "quantity-surveyor"],
  icon: "Ruler",
  titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.title",
  titleDefault: "Measure the drawing into a coded bill item",
  descKey: "cases.measure_the_drawing_into_a_coded_bill_item.desc",
  descDefault:
    "Measure on the drawing, land the quantity on a bill item, give the item its GB 50500 code and the description of what it covers, and validate the codes before the bill goes out.",
  longDescKey: "cases.measure_the_drawing_into_a_coded_bill_item.longdesc",
  longDescDefault:
    "A quantity on its own is not a bill item. Under the bill of quantities valuation code an item is a quantity plus a code from the national schedule plus a statement of the characteristics the rate has to cover, and the third of those is the one that decides disputes. Two bidders pricing the same code can be pricing very different work if one of them read C30 and the other read C40 into an item that said neither, and the argument surfaces at settlement rather than at tender. This case takes the measurement from the drawing to a coded item with its characteristics written down, and finishes on validation so a malformed code is found by you rather than by the owner's reviewer.",
  estMinutes: 18,
  steps: [
    {
      id: "measure",
      icon: "PencilRuler",
      inputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.in.drawing", label: "Drawing set" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.in.scale", label: "Scale and reference dimension" },
      ],
      outputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.out.measured", label: "Measurements on the sheet" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.out.shown", label: "What was measured, visible" },
      ],
      titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.title",
      titleDefault: "Measure on the drawing, not off it",
      whatKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.what",
      whatDefault:
        "Open the sheet, set the scale against a dimension printed on the drawing, and measure the areas, lengths and counts you need. The measurements stay on the sheet where they were taken.",
      whyKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.measure.why",
      whyDefault:
        "A measurement you can point at on the drawing is checkable by somebody else in a minute. The same number in a spreadsheet cell is only as good as the memory of whoever put it there, and on a revision it has to be redone from scratch because nobody can see what it covered.",
      moduleLabel: "PDF Measurements",
      moduleLabelKey: "nav.pdf_measurements",
      to: "/takeoff",
    },
    {
      id: "gather",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.in.measured", label: "Measurements from the sheets" },
      ],
      outputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.out.grouped", label: "Quantities grouped by work" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.out.units", label: "Units the bill will use" },
      ],
      titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.title",
      titleDefault: "Gather the measurements into quantities",
      whatKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.what",
      whatDefault:
        "Group the measurements into the quantities the bill will actually carry, in the units the measurement rules give for each kind of work, and check the totals against anything you already know about the building.",
      whyKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.gather.why",
      whyDefault:
        "The unit is part of the measurement rule, not a formatting choice, and a quantity carried in the wrong one produces a rate that is wrong by a factor rather than by a margin. It is also the last cheap moment to notice that a floor is missing from the take-off.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "code",
      icon: "Tags",
      inputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.in.qty", label: "The measured quantity" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.in.schedule", label: "GB 50500 item schedule" },
      ],
      outputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.out.item", label: "Bill item with its code" },
      ],
      titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.title",
      titleDefault: "Land the quantity on a coded bill item",
      whatKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.what",
      whatDefault:
        "Put the quantity on a bill item under the right section and give the item its code. The measurement standard for your discipline gives the first nine digits (GB/T 50854-2024 for buildings and decoration, with eight siblings for the other disciplines, all in force since September 2025); a project bill extends that with a three-digit sequence of its own, so a code of either length is what the bill ends up carrying.",
      whyKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.code.why",
      whyDefault:
        "The code is the item's identity for the rest of the job. It is what lets a settlement bill be compared against a tender bill after both have been renumbered, and it is what lets two bidders' prices for the same work be set against each other at all.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "characteristics",
      icon: "FileText",
      inputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.in.spec", label: "Specification and drawing notes" },
      ],
      outputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.out.desc", label: "Item characteristics written down" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.out.scope", label: "What the rate has to cover" },
      ],
      titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.title",
      titleDefault: "Write the characteristics the rate has to cover",
      whatKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.what",
      whatDefault:
        "Beside the code, write out what the item actually covers: grade, mix, thickness, finish, method, and anything about access or sequence that changes the price. It is free text, so it can say whatever the item needs it to say.",
      whyKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.characteristics.why",
      whyDefault:
        "The characteristics are what the code cannot carry, and they differ for every kind of work: what you must state for concrete is nothing like what you must state for windows. An item described in three words gets priced three different ways by three bidders, and the difference becomes yours to absorb at settlement. The 2024 standard treats a characteristic that does not match the drawings as a defect in the bill: on a unit-rate contract the item is repriced and the owner pays the difference, on a lump-sum contract the bidder is taken to have priced what the drawings show.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.in.bill", label: "The coded bill" },
      ],
      outputs: [
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.out.missing", label: "Items with no code" },
        { labelKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.out.malformed", label: "Codes of the wrong shape" },
      ],
      titleKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.title",
      titleDefault: "Validate the codes, and know what the check does not do",
      whatKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.what",
      whatDefault:
        "Run validation on the bill. For a project in China the GB 50500 rules are selected for you: they find items carrying no code at all, and codes that are not a well-formed nine or twelve digits. If your bill form also has a code column of its own, make sure the code being checked is the one on the item rather than a second copy typed elsewhere.",
      whyKey: "cases.measure_the_drawing_into_a_coded_bill_item.step.validate.why",
      whyDefault:
        "This checks the shape of the code, not whether that code exists in the national schedule, so a well-formed number nobody ever published passes. Read a clean run as having cleared the typing errors, and read the codes yourself for the ones that matter.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
  ],
};

export default playbook;
