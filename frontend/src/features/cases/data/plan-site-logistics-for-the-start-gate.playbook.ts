// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Plan site logistics for the start gate".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "plan-site-logistics-for-the-start-gate",
  order: 1691,
  category: "site",
  stage: "plan",
  companyTypes: ["developer-client", "project-manager", "general-contractor"],
  roles: ["site-manager", "planner", "project-manager"],
  requiresProject: true,
  icon: "Truck",
  titleKey: "cases.plan_site_logistics_for_the_start_gate.title",
  titleDefault: "Plan site logistics for the start gate",
  descKey: "cases.plan_site_logistics_for_the_start_gate.desc",
  descDefault:
    "Set the construction stages and site areas, check utilities against demand, plan heavy transports and their permits, set up gates and deliveries, and confirm the plan is ready for the start gate.",
  longDescKey: "cases.plan_site_logistics_for_the_start_gate.longdesc",
  longDescDefault:
    "Before the first excavator arrives, someone has to know where the cranes stand, where material is stored, whether the power connection carries the demand and which heavy loads need a permit. The logistics plan answers these per construction stage and checks itself: the area balance must close, gate load limits must hold, every heavy transport needs a granted permit. Gate readiness shows in one view whether the plan can go to the start gate.",
  estMinutes: 16,
  steps: [
    {
      id: "stages",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.stages.in.siteplan", label: "Site plan" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.stages.out.areas", label: "Areas per stage" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.stages.title",
      titleDefault: "Set stages and areas",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.stages.what",
      whatDefault:
        "Open the Logistics plan tab. On Expansion stages add the stages with their periods, then on Areas add the site areas and allocate them to the stages until the area balance closes.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.stages.why",
      whyDefault:
        "Site space changes as the building grows. Planning it stage by stage avoids the moment when the laydown area becomes the next building section.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=plan",
    },
    {
      id: "utilities",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.utilities.in.demand", label: "Site power demand" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.utilities.out.balance", label: "Utility balance" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.utilities.title",
      titleDefault: "Check utilities against demand",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.utilities.what",
      whatDefault:
        "On the Utilities tab, add the connections and the demand per stage.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.utilities.why",
      whyDefault:
        "A connection that cannot carry the demand stops the site on the day the second crane switches on. The check shows the gap with the reserve included.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=plan",
    },
    {
      id: "transports",
      icon: "Truck",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.transports.in.plant", label: "Long-lead plant" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.transports.out.transports", label: "Transport plan" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.transports.title",
      titleDefault: "Plan transports and permits",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.transports.what",
      whatDefault:
        "On the Transports tab, add the heavy and oversize transports, and on the Permits tab record the permit each one needs.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.transports.why",
      whyDefault:
        "A heavy load without a granted permit does not leave the depot. Linking them makes the missing permit a visible blocker.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=plan",
    },
    {
      id: "gates",
      icon: "MapPin",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.gates.in.siteplan", label: "Site plan" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.gates.out.gates", label: "Gates and zones" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.gates.title",
      titleDefault: "Set up gates and laydown",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.gates.what",
      whatDefault:
        "On the Gates and Laydown zones tabs, set up the site gates with their load limits and the storage zones.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.gates.why",
      whyDefault:
        "Gate limits and zones are what every delivery booking is checked against later.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=gates",
    },
    {
      id: "deliveries",
      icon: "CalendarCheck",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.deliveries.in.gates", label: "Gates and zones" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.deliveries.out.board", label: "Delivery board" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.deliveries.title",
      titleDefault: "Book the deliveries",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.deliveries.what",
      whatDefault:
        "On the Deliveries tab, book deliveries against the gates, approve or reject them, and mark them arrived and completed.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.deliveries.why",
      whyDefault:
        "A delivery board stops two trucks arriving at the same gate at the same hour and leaves a record of what actually came.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=deliveries",
    },
    {
      id: "readiness",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.readiness.in.logplan", label: "Logistics plan" },
      ],
      outputs: [
        { labelKey: "cases.plan_site_logistics_for_the_start_gate.step.readiness.out.readiness", label: "Logistics readiness" },
      ],
      titleKey: "cases.plan_site_logistics_for_the_start_gate.step.readiness.title",
      titleDefault: "Check gate readiness",
      whatKey: "cases.plan_site_logistics_for_the_start_gate.step.readiness.what",
      whatDefault:
        "Back on the Logistics plan tab, open Gate readiness and see whether the plan is ready for the start gate. Export the registers you need.",
      whyKey: "cases.plan_site_logistics_for_the_start_gate.step.readiness.why",
      whyDefault:
        "The readiness view collects every open check in one place, so the gate is decided on facts rather than on assurances.",
      moduleLabel: "Site Logistics",
      moduleLabelKey: "nav.site_logistics",
      to: "/projects/:projectId/site-logistics?tab=plan",
    },
  ],
};

export default playbook;
