// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price the preliminaries and general conditions".
//
// Price the cost of running the job itself - site management, welfare, plant,
// scaffolding, insurances - split into time-related and fixed, driven by the
// programme. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-the-preliminaries-and-general-conditions",
  order: 1001,
  category: "estimating",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  icon: "Container",
  titleKey: "cases.price_the_preliminaries_and_general_conditions.title",
  titleDefault: "Price the preliminaries and general conditions",
  descKey: "cases.price_the_preliminaries_and_general_conditions.desc",
  descDefault:
    "Price the cost of running the job itself - site staff, welfare, plant, scaffolding and insurances - split into time-related and fixed and driven by the programme, then carry it into the bill.",
  longDescKey: "cases.price_the_preliminaries_and_general_conditions.longdesc",
  longDescDefault:
    "Preliminaries are often ten to fifteen percent of a bid and the part estimators rush. Getting them wrong either prices you out of the job or leaves you carrying the site establishment out of margin. The trick is to drive them off the programme, because most of them are time-related.",
  estMinutes: 11,
  steps: [
    {
      id: "scope",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.in.contract", label: "Contract & prelims" },
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.in.programme", label: "Outline programme" },
      ],
      outputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.out.schedule", label: "Prelims schedule" },
      ],
      titleKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.title",
      titleDefault: "List the prelims scope",
      whatKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.what",
      whatDefault:
        "Build the list of everything it takes to run the site: management and supervision, welfare and cabins, temporary services, common plant, scaffolding, security, insurances and bonds.",
      whyKey: "cases.price_the_preliminaries_and_general_conditions.step.scope.why",
      whyDefault:
        "The items you forget in prelims are the ones you fund out of profit. A complete checklist read against the contract is the difference between a covered site and a leaking one.",
      moduleLabel: "Preliminaries",
      moduleLabelKey: "nav.preliminaries",
      to: "/preliminaries",
    },
    {
      id: "timeprice",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.in.schedule", label: "Prelims schedule" },
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.in.duration", label: "Programme duration" },
      ],
      outputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.out.priced", label: "Priced prelims" },
      ],
      titleKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.title",
      titleDefault: "Split time-related from fixed",
      whatKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.what",
      whatDefault:
        "Mark each item as time-related or fixed, then price the time-related ones per week against the programme duration and the fixed ones as one-off set-up and removal.",
      whyKey: "cases.price_the_preliminaries_and_general_conditions.step.timeprice.why",
      whyDefault:
        "Splitting them this way is what lets prelims flex if the programme moves. If the job runs four weeks late, you can show exactly what the extra time costs instead of guessing.",
      moduleLabel: "Preliminaries",
      moduleLabelKey: "nav.preliminaries",
      to: "/preliminaries",
    },
    {
      id: "resource",
      icon: "Users",
      inputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.resource.in.priced", label: "Priced prelims" },
      ],
      outputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.resource.out.rollup", label: "Resource roll-up" },
      ],
      titleKey: "cases.price_the_preliminaries_and_general_conditions.step.resource.title",
      titleDefault: "Check the resources roll up",
      whatKey: "cases.price_the_preliminaries_and_general_conditions.step.resource.what",
      whatDefault:
        "Look at the staff, plant and cabins the prelims imply in the resource summary and sanity check the headcount curve against the programme peaks.",
      whyKey: "cases.price_the_preliminaries_and_general_conditions.step.resource.why",
      whyDefault:
        "A prelims price that needs three site managers in a quiet month is a warning. Seeing the resource curve catches a double count or a gap before it reaches the tender total.",
      moduleLabel: "Resource Summary",
      moduleLabelKey: "nav.resource_summary",
      to: "/resource-summary",
    },
    {
      id: "carry",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.in.priced", label: "Priced prelims" },
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.in.works", label: "Measured works" },
      ],
      outputs: [
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.out.section", label: "Prelims bill section" },
        { labelKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.out.percent", label: "Prelims as percent of works" },
      ],
      titleKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.title",
      titleDefault: "Carry it into the bill",
      whatKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.what",
      whatDefault:
        "Bring the prelims total into the bill as its own section, kept separate from measured work, and read it back as a percentage of the works value.",
      whyKey: "cases.price_the_preliminaries_and_general_conditions.step.carry.why",
      whyDefault:
        "Keeping prelims visible as their own line lets a reviewer benchmark them at a glance. Burying them in the rates hides the one number a client always wants to test.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
  ],
};

export default playbook;
