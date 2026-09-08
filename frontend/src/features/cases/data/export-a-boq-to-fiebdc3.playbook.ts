// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Send a bill to Spain in FIEBDC-3".
//
// Export a priced bill to FIEBDC-3 (BC3), the budget exchange format used
// across Spain and Latin America, check the charset the header declares, then
// prove the round trip through our own reader. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "export-a-boq-to-fiebdc3",
  order: 1039,
  region: "ES",
  category: "commercial",
  companyTypes: ["cost-consultant", "general-contractor", "subcontractor"],
  roles: ["quantity-surveyor", "estimator"],
  icon: "Globe",
  titleKey: "cases.export_a_boq_to_fiebdc3.title",
  titleDefault: "Send a bill to Spain in FIEBDC-3",
  descKey: "cases.export_a_boq_to_fiebdc3.desc",
  descDefault:
    "Export a priced bill to FIEBDC-3, the budget format the Spanish and Latin American market exchanges in, so it opens as a real budget in a desktop estimating tool and comes back through your own reader unchanged.",
  longDescKey: "cases.export_a_boq_to_fiebdc3.longdesc",
  longDescDefault:
    "FIEBDC-3, usually just called BC3, is the de-facto exchange format for budgets across Spain, Mexico, Argentina, Chile, Peru and Colombia, and it is mandated for Spanish public tenders. The export carries the full chapter and item hierarchy with codes, units, quantities, unit rates and long texts, which is the whole budget rather than a flat price list. Overhead, profit and VAT stay for the receiving tool to apply from its own coefficients, which is also how the importer treats them.",
  estMinutes: 11,
  steps: [
    {
      id: "prepare",
      icon: "Layers",
      inputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.prepare.in.bill",
          label: "Priced bill",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.prepare.in.structure",
          label: "Chapter structure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.prepare.out.tree",
          label: "Clean chapter and item tree",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.prepare.out.coded",
          label: "Every position coded",
        },
      ],
      titleKey: "cases.export_a_boq_to_fiebdc3.step.prepare.title",
      titleDefault: "Get the bill ready to travel",
      whatKey: "cases.export_a_boq_to_fiebdc3.step.prepare.what",
      whatDefault:
        "Check the bill has the shape BC3 expects before you export anything: a chapter for each section, an item for each position, and a code, a unit, a quantity and a unit rate on every line. Long descriptions travel too, so read the ones you would rather a client did not see.",
      whyKey: "cases.export_a_boq_to_fiebdc3.step.prepare.why",
      whyDefault:
        "BC3 carries a hierarchy, so a bill with orphaned positions or two items sharing a code arrives at the other end as a budget nobody can navigate. Sorting the tree out here takes minutes. Sorting it out after someone has started pricing in their own software is no longer your decision to make.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
    {
      id: "export",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.export.in.bill",
          label: "Structured priced bill",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.export.in.format",
          label: "FIEBDC-3 export",
        },
      ],
      outputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.export.out.file",
          label: "BC3 budget file",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.export.out.hierarchy",
          label: "Hierarchy, rates and texts",
        },
      ],
      titleKey: "cases.export_a_boq_to_fiebdc3.step.export.title",
      titleDefault: "Export to FIEBDC-3",
      whatKey: "cases.export_a_boq_to_fiebdc3.step.export.what",
      whatDefault:
        "Export the bill to FIEBDC-3. The file carries the chapters and items with their codes, units, quantities, unit rates and long texts, which is what a Spanish desktop estimating tool needs to open it as a working budget instead of a list of numbers.",
      whyKey: "cases.export_a_boq_to_fiebdc3.step.export.why",
      whyDefault:
        "BC3 is what that market actually exchanges budgets in, and the pliego of a Spanish public tender almost always asks for the presupuesto in it. Sending a spreadsheet instead means somebody at the other end retypes your bill, and a retyped bill of four hundred positions always loses a few.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
    {
      id: "charset",
      icon: "FileCheck",
      inputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.charset.in.file",
          label: "BC3 file",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.charset.in.texts",
          label: "Position texts",
        },
      ],
      outputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.charset.out.declared",
          label: "Charset named in the header",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.charset.out.intact",
          label: "Text that survives the trip",
        },
      ],
      titleKey: "cases.export_a_boq_to_fiebdc3.step.charset.title",
      titleDefault: "Check the charset in the header",
      whatKey: "cases.export_a_boq_to_fiebdc3.step.charset.what",
      whatDefault:
        "Open the file and read the charset the header declares. It is written Windows-1252 by default, which is what the desktop tools in that market expect, and it switches to UTF-8 only when a character in your texts cannot be represented. Either way the header states which one was used.",
      whyKey: "cases.export_a_boq_to_fiebdc3.step.charset.why",
      whyDefault:
        "A mis-declared charset is the classic BC3 failure. The file opens, the numbers are all correct, and every accented character in the descriptions comes out as rubbish. It gets spotted late, usually by the client reading your descriptions, and it makes an otherwise careful submission look sloppy.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
    {
      id: "roundtrip",
      icon: "GitCompare",
      inputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.in.file",
          label: "Exported BC3 file",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.in.reader",
          label: "BC3 importer",
        },
      ],
      outputs: [
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.out.reimported",
          label: "Re-imported bill",
        },
        {
          labelKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.out.match",
          label: "Confirmed match",
        },
      ],
      titleKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.title",
      titleDefault: "Prove the round trip",
      whatKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.what",
      whatDefault:
        "Read the file you have just written straight back in through the BC3 importer and compare it against what you exported. Codes, chapters, quantities, units, rates and long texts should all come back the same.",
      whyKey: "cases.export_a_boq_to_fiebdc3.step.roundtrip.why",
      whyDefault:
        "An export nobody has ever read back is a guess. Putting it through your own reader takes a minute and is the difference between believing the file is sound and knowing it, which matters most on the submission where you do not get a second go.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/boq",
    },
  ],
};

export default playbook;
