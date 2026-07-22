// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Mobilise the site and set up logistics".
//
// Get the site ready before work starts: the mobilisation checklist for
// hoarding, welfare and utilities, then the logistics plan for access, cranes
// and laydown. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "mobilise-the-site-and-set-up-logistics",
  order: 1020,
  category: "site",
  companyTypes: ["general-contractor", "project-manager", "subcontractor"],
  stage: "plan",
  icon: "MapPin",
  titleKey: "cases.mobilise_the_site_and_set_up_logistics.title",
  titleDefault: "Mobilise the site and set up logistics",
  descKey: "cases.mobilise_the_site_and_set_up_logistics.desc",
  descDefault:
    "Get the site ready before work starts: run the mobilisation checklist for hoarding, welfare and utilities, then set the logistics plan for access, deliveries, cranes and laydown.",
  longDescKey: "cases.mobilise_the_site_and_set_up_logistics.longdesc",
  longDescDefault:
    "The first weeks on site set the tone for the whole job. A site that opens with welfare in, utilities connected and a real logistics plan runs; one that opens with a scramble spends the first month firefighting deliveries and access it should have planned.",
  estMinutes: 10,
  steps: [
    {
      id: "checklist",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.in.contract", label: "Contract start" },
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.in.site", label: "Site conditions" },
      ],
      outputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.out.checklist", label: "Mobilisation checklist" },
      ],
      titleKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.title",
      titleDefault: "Run the mobilisation checklist",
      whatKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.what",
      whatDefault:
        "Work the mobilisation checklist: hoarding and security, welfare and offices, temporary power and water, signage, first aid and the statutory notices, each with an owner and a date.",
      whyKey: "cases.mobilise_the_site_and_set_up_logistics.step.checklist.why",
      whyDefault:
        "The item forgotten at mobilisation stops work later - no water for the concrete, no power for the tools. A checklist with owners and dates is what turns a chaotic start into a controlled one.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "nav.site_prep",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "utilities",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.utilities.in.checklist", label: "Mobilisation checklist" },
      ],
      outputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.utilities.out.ready", label: "Site established" },
      ],
      titleKey: "cases.mobilise_the_site_and_set_up_logistics.step.utilities.title",
      titleDefault: "Track set-up to complete",
      whatKey: "cases.mobilise_the_site_and_set_up_logistics.step.utilities.what",
      whatDefault:
        "Track each mobilisation task to done, chasing the long-lead connections and approvals that gate the site opening, until the establishment is genuinely complete.",
      whyKey: "cases.mobilise_the_site_and_set_up_logistics.step.utilities.why",
      whyDefault:
        "A utility connection can take weeks of notice. Tracking the set-up as a live list is what surfaces the item that will hold up the start while there is still time to expedite it.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "nav.site_prep",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "logistics",
      icon: "Route",
      inputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.in.ready", label: "Established site" },
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.in.programme", label: "Programme peaks" },
      ],
      outputs: [
        { labelKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.out.plan", label: "Logistics plan" },
      ],
      titleKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.title",
      titleDefault: "Set the logistics plan",
      whatKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.what",
      whatDefault:
        "Set the logistics plan: gates and access routes, delivery windows, crane and hoist positions and reach, laydown and waste areas, mapped against the busy phases of the programme.",
      whyKey: "cases.mobilise_the_site_and_set_up_logistics.step.logistics.why",
      whyDefault:
        "Space is the scarcest resource on a tight site. A logistics plan that thinks ahead to the busy weeks is what stops trades fighting over the same crane and the same gate.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/site-logistics",
    },
  ],
};

export default playbook;
