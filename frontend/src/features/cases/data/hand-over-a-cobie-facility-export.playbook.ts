// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Hand over a COBie facility export".
//
// Get the asset register complete enough that a COBie UK 2.4 workbook comes
// out full rather than padded, produce it, and issue it inside the close-out
// package. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "hand-over-a-cobie-facility-export",
  order: 1042,
  region: "GB",
  category: "handover",
  companyTypes: ["general-contractor", "owner-operator", "bim-consultant"],
  roles: ["bim-coordinator", "document-controller"],
  stage: "handover",
  icon: "FileSpreadsheet",
  titleKey: "cases.hand_over_a_cobie_facility_export.title",
  titleDefault: "Hand over a COBie facility export",
  descKey: "cases.hand_over_a_cobie_facility_export.desc",
  descDefault:
    "Turn the asset register into the COBie UK 2.4 workbook an FM system can actually import: fill the fields the sheets are built from, fix what the export would expose, produce the workbook and issue it with the close-out package.",
  longDescKey: "cases.hand_over_a_cobie_facility_export.longdesc",
  longDescDefault:
    "Most projects still hand asset data over as a spreadsheet somebody typed by hand, which starts drifting from the building the day it is written. COBie is the structured alternative, and it is only as good as the register underneath it. This case gets the register complete enough that the Contact, Facility, Floor, Space, Type, Component and System sheets come out full instead of padded with n/a, then hands the workbook over as part of the close-out set rather than as a loose file.",
  estMinutes: 9,
  steps: [
    {
      id: "complete",
      icon: "Boxes",
      inputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.complete.in.assets",
          label: "Tracked assets",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.complete.in.model",
          label: "Canonical model data",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.complete.out.register",
          label: "Complete asset register",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.complete.out.systems",
          label: "Assets under a parent system",
        },
      ],
      titleKey: "cases.hand_over_a_cobie_facility_export.step.complete.title",
      titleDefault: "Complete the register the workbook is built from",
      whatKey: "cases.hand_over_a_cobie_facility_export.step.complete.what",
      whatDefault:
        "Work through the tracked assets and fill the fields COBie reads: make, model and serial, the operational status and warranty date, the storey the item sits on and the parent system it belongs to.",
      whyKey: "cases.hand_over_a_cobie_facility_export.step.complete.why",
      whyDefault:
        "The workbook is a projection of the register, not a document you write separately, so the sheets are only as complete as the rows behind them. A blank storey does not leave one empty cell, it removes a whole Floor row the receiving system was expecting to hang the asset on.",
      moduleLabel: "Building Assets (FM)",
      moduleLabelKey: "nav.assets",
      to: "/assets",
    },
    {
      id: "gaps",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.gaps.in.register",
          label: "Complete asset register",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.gaps.in.requirements",
          label: "Operator data requirements",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hand_over_a_cobie_facility_export.step.gaps.out.list",
          label: "List of thin records",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.gaps.out.actions",
          label: "Fixes back to the delivery team",
        },
      ],
      titleKey: "cases.hand_over_a_cobie_facility_export.step.gaps.title",
      titleDefault: "Check the gaps the export will expose",
      whatKey: "cases.hand_over_a_cobie_facility_export.step.gaps.what",
      whatDefault:
        "Before you export, read the register the way the workbook will: search and filter down to the assets with no serial, no warranty date and no parent system, and either fix them or put them back to whoever installed the plant.",
      whyKey: "cases.hand_over_a_cobie_facility_export.step.gaps.why",
      whyDefault:
        "The export falls back to n/a rather than failing, so a workbook full of holes still downloads cleanly and still looks finished. Nobody finds out until the operator tries to raise a work order against a pump with no serial and no system, by which time the fitters have long gone.",
      moduleLabel: "Building Assets (FM)",
      moduleLabelKey: "nav.assets",
      to: "/assets",
    },
    {
      id: "build",
      icon: "Table2",
      inputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.build.in.register",
          label: "Checked asset register",
        },
        {
          labelKey: "cases.hand_over_a_cobie_facility_export.step.build.in.model",
          label: "Model to export",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.build.out.workbook",
          label: "COBie 2.4 workbook",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.build.out.sheets",
          label: "Seven populated sheets",
        },
      ],
      titleKey: "cases.hand_over_a_cobie_facility_export.step.build.title",
      titleDefault: "Build the COBie 2.4 workbook",
      whatKey: "cases.hand_over_a_cobie_facility_export.step.build.what",
      whatDefault:
        "Export the register as a COBie 2.4 workbook in the shape BS 1192-4 asks for in the United Kingdom. It arrives as one spreadsheet with seven sheets, Contact, Facility, Floor, Space, Type, Component and System, each projected straight from the canonical model and the asset data sitting on it.",
      whyKey: "cases.hand_over_a_cobie_facility_export.step.build.why",
      whyDefault:
        "A workbook generated from the model matches the building; a workbook typed into a template matches whatever the typist had in front of them that week. Exporting per model as each one is signed off also keeps the register current, instead of leaving the whole job to the fortnight before handover.",
      moduleLabel: "Building Assets (FM)",
      moduleLabelKey: "nav.assets",
      to: "/assets",
    },
    {
      id: "issue",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.issue.in.workbook",
          label: "COBie 2.4 workbook",
        },
        {
          labelKey: "cases.hand_over_a_cobie_facility_export.step.issue.in.pack",
          label: "Close-out checklist",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.issue.out.package",
          label: "Issued handover package",
        },
        {
          labelKey:
            "cases.hand_over_a_cobie_facility_export.step.issue.out.accepted",
          label: "Operator acceptance",
        },
      ],
      titleKey: "cases.hand_over_a_cobie_facility_export.step.issue.title",
      titleDefault: "Issue it to the operator",
      whatKey: "cases.hand_over_a_cobie_facility_export.step.issue.what",
      whatDefault:
        "Bind the workbook into the close-out package alongside the as-built drawings, the O and M manuals and the warranties, and issue the lot as one structured set with its manifest.",
      whyKey: "cases.hand_over_a_cobie_facility_export.step.issue.why",
      whyDefault:
        "A COBie file arriving on its own gets loaded by nobody, because the FM team cannot tell which state of the building it describes. Wrapped in the close-out package, dated and listed on the manifest, it is a deliverable the operator can accept, import and be held to.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
