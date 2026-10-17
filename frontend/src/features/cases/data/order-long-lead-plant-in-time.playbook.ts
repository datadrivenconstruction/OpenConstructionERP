// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Order long-lead plant in time".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "order-long-lead-plant-in-time",
  order: 1689,
  category: "tendering",
  stage: "procure",
  companyTypes: ["developer-client", "project-manager", "owner-operator"],
  roles: ["procurement-buyer", "project-manager", "planner"],
  requiresProject: true,
  icon: "Container",
  titleKey: "cases.order_long_lead_plant_in_time.title",
  titleDefault: "Order long-lead plant in time",
  descKey: "cases.order_long_lead_plant_in_time.desc",
  descDefault:
    "Register the equipment with long lead times, record lead times with their source, see the last safe order date, decide who buys and installs each item, and settle the site services.",
  longDescKey: "cases.order_long_lead_plant_in_time.longdesc",
  longDescDefault:
    "A transformer, a switchboard or a lift can take longer to arrive than the whole shell takes to build. If nobody orders it in time, the finish date moves and nothing on site can bring it back. Plant register lists these items, works out the last order date from when the programme needs them, records who buys and who installs each one, and for critical items asks for a decision paper approved by someone other than its author.",
  estMinutes: 14,
  steps: [
    {
      id: "register",
      icon: "ListPlus",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.register.in.needs", label: "Equipment needs" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.register.out.register", label: "Plant register" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.register.title",
      titleDefault: "Register the item",
      whatKey: "cases.order_long_lead_plant_in_time.step.register.what",
      whatDefault:
        "On the Register tab, press Add item for each piece of plant with a long lead time, for example the main transformer or the switchgear.",
      whyKey: "cases.order_long_lead_plant_in_time.step.register.why",
      whyDefault:
        "The register is the list of things the programme cannot wait for. Anything not on it is ordered when someone remembers.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register",
    },
    {
      id: "leadtime",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.leadtime.in.quotes", label: "Supplier quotes" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.leadtime.out.orderdate", label: "Last safe order date" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.leadtime.title",
      titleDefault: "Record lead time and need date",
      whatKey: "cases.order_long_lead_plant_in_time.step.leadtime.what",
      whatDefault:
        "Enter the performance requirements when you add the item. Then open it, press Add lead time with the source, who answered and the response date, and under Production slot press Reserve slot.",
      whyKey: "cases.order_long_lead_plant_in_time.step.leadtime.why",
      whyDefault:
        "A lead time without a source and a date is a guess. With both, the register can tell you when the quote has gone stale.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register",
    },
    {
      id: "route",
      icon: "SignpostBig",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.route.in.options", label: "Options and criteria" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.route.out.route", label: "Approved procurement route" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.route.title",
      titleDefault: "Decide who buys and installs",
      whatKey: "cases.order_long_lead_plant_in_time.step.route.what",
      whatDefault:
        "For a critical item, first press Write decision paper and Submit for approval. Once a second person approves it, press Set route and choose who furnishes and who installs the item.",
      whyKey: "cases.order_long_lead_plant_in_time.step.route.why",
      whyDefault:
        "Whether the client or the contractor buys a piece of plant changes the contracts, the risk and the warranty. Deciding it per item avoids gaps.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register",
    },
    {
      id: "timeline",
      icon: "GanttChartSquare",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.timeline.in.register", label: "Plant register" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.timeline.out.timeline", label: "Long-lead timeline" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.timeline.title",
      titleDefault: "Watch the long-lead timeline",
      whatKey: "cases.order_long_lead_plant_in_time.step.timeline.what",
      whatDefault:
        "On the Long-lead timeline tab, see for every item the last date to order against the programme need.",
      whyKey: "cases.order_long_lead_plant_in_time.step.timeline.why",
      whyDefault:
        "The timeline turns a list into a warning: the items closest to their order date are the ones to act on this week.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register?tab=long_lead",
    },
    {
      id: "limits",
      icon: "Split",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.limits.in.packages", label: "Contract packages" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.limits.out.matrix", label: "Delivery limit matrix" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.limits.title",
      titleDefault: "Agree the delivery limits",
      whatKey: "cases.order_long_lead_plant_in_time.step.limits.what",
      whatDefault:
        "On the Delivery limits tab, check the matrix of who supplies what at each interface.",
      whyKey: "cases.order_long_lead_plant_in_time.step.limits.why",
      whyDefault:
        "Most plant disputes happen at the boundary: who supplies the cable, the base, the commissioning. A matrix settles it before the order.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register?tab=limits",
    },
    {
      id: "power",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.power.in.positions", label: "Site plant and IT needs" },
      ],
      outputs: [
        { labelKey: "cases.order_long_lead_plant_in_time.step.power.out.demand", label: "Site services" },
      ],
      titleKey: "cases.order_long_lead_plant_in_time.step.power.title",
      titleDefault: "Settle the site services",
      whatKey: "cases.order_long_lead_plant_in_time.step.power.what",
      whatDefault:
        "On the Site and IT tab, add the IT services the site needs and check the site plant that is placed on the logistics plan.",
      whyKey: "cases.order_long_lead_plant_in_time.step.power.why",
      whyDefault:
        "Cranes, temporary plant and the site network are needed from the first day. Settling them early avoids a site that cannot switch on.",
      moduleLabel: "Plant register",
      moduleLabelKey: "plant.nav.title",
      to: "/projects/:projectId/plant-register?tab=site_it",
    },
  ],
};

export default playbook;
