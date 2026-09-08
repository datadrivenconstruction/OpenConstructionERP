// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Track a design change through to the site record".
//
// Follow a design change from the drawing that carries it, through the site
// instruction, to the record that proves the right version was actually
// built. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "track-a-design-change-to-site-record",
  order: 255,
  category: "site",
  companyTypes: ["designer", "general-contractor", "bim-consultant"],
  roles: ["design-lead", "site-manager", "document-controller"],
  icon: "GitCompare",
  titleKey: "cases.track_a_design_change_to_site_record.title",
  titleDefault: "Track a design change through to the site record",
  descKey: "cases.track_a_design_change_to_site_record.desc",
  descDefault:
    "Follow a design change from the drawing that carries it, through the site instruction, to the record that proves the right version was actually built.",
  estMinutes: 9,
  steps: [
    {
      id: "revise",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.revise.in.change",
          label: "Design change",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.revise.in.previous",
          label: "Previous drawing version",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.revise.out.revision",
          label: "Registered drawing revision",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.revise.out.superseded",
          label: "Superseded version marked",
        },
      ],
      titleKey: "cases.track_a_design_change_to_site_record.step.revise.title",
      titleDefault: "Issue the revised drawing",
      whatKey: "cases.track_a_design_change_to_site_record.step.revise.what",
      whatDefault:
        "Register the revised drawing carrying the design change, mark the previous version superseded and note plainly what moved and why.",
      whyKey: "cases.track_a_design_change_to_site_record.step.revise.why",
      whyDefault:
        "A change that only exists as a verbal instruction on site has no paper trail behind it if the cost or the time is ever questioned.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "instruct",
      icon: "GitCompareArrows",
      inputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.instruct.in.revision",
          label: "Drawing revision",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.instruct.in.scope",
          label: "Changed work scope",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.instruct.out.instruction",
          label: "Logged site instruction",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.instruct.out.impact",
          label: "Cost & time impact",
        },
      ],
      titleKey:
        "cases.track_a_design_change_to_site_record.step.instruct.title",
      titleDefault: "Log the site instruction",
      whatKey: "cases.track_a_design_change_to_site_record.step.instruct.what",
      whatDefault:
        "Log the instruction that authorises the change on site, tied to the drawing revision that carries it, with the likely cost and time impact noted.",
      whyKey: "cases.track_a_design_change_to_site_record.step.instruct.why",
      whyDefault:
        "Tying the instruction to the exact revision is what stops a dispute later over which version of the change was actually agreed.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "verify",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.verify.in.instruction",
          label: "Site instruction",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.verify.in.drawing",
          label: "Revised drawing",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.verify.in.work",
          label: "Affected work",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.verify.out.record",
          label: "Verified inspection record",
        },
        {
          labelKey:
            "cases.track_a_design_change_to_site_record.step.verify.out.asbuilt",
          label: "As-built confirmation",
        },
      ],
      titleKey: "cases.track_a_design_change_to_site_record.step.verify.title",
      titleDefault: "Verify it was built as changed",
      whatKey: "cases.track_a_design_change_to_site_record.step.verify.what",
      whatDefault:
        "Inspect the affected work against the revised drawing and record that what went in matches the change, not the superseded detail.",
      whyKey: "cases.track_a_design_change_to_site_record.step.verify.why",
      whyDefault:
        "A change is only real once it is confirmed built. Verifying it on site is what closes the loop between the drawing, the instruction and the finished work.",
      moduleLabel: "Inspections",
      moduleLabelKey: "inspections.title",
      to: "/projects/:projectId/inspections",
    },
  ],
};

export default playbook;
