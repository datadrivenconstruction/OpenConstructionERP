// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage temporary works and inspections".
//
// Register every temporary works item, record the design check and coordinator
// sign-off, inspect before loading and keep the periodic inspection record until
// it is struck. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-temporary-works-and-inspections",
  order: 1018,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  icon: "Wrench",
  titleKey: "cases.manage_temporary_works_and_inspections.title",
  titleDefault: "Manage temporary works and inspections",
  descKey: "cases.manage_temporary_works_and_inspections.desc",
  descDefault:
    "Register every temporary works item, record the design check and coordinator sign-off, inspect before it is loaded and keep the periodic inspection record right up until it is struck.",
  longDescKey: "cases.manage_temporary_works_and_inspections.longdesc",
  longDescDefault:
    "Temporary works fail quietly and then all at once. Scaffolds, props, formwork, excavation support and falsework carry real loads, and the discipline of a register, a design check and a permit to load is what stands between a routine day and a collapse.",
  estMinutes: 11,
  steps: [
    {
      id: "register",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.register.in.works", label: "Temporary works" },
        { labelKey: "cases.manage_temporary_works_and_inspections.step.register.in.method", label: "Method statements" },
      ],
      outputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.register.out.register", label: "Temporary works register" },
      ],
      titleKey: "cases.manage_temporary_works_and_inspections.step.register.title",
      titleDefault: "Register every item",
      whatKey: "cases.manage_temporary_works_and_inspections.step.register.what",
      whatDefault:
        "List every temporary works item on the job - scaffold, props, formwork, falsework, excavation support - with its location, design status and who is responsible for it.",
      whyKey: "cases.manage_temporary_works_and_inspections.step.register.why",
      whyDefault:
        "The item nobody registered is the one that gets loaded without a check. A complete register is what makes sure every load-bearing temporary structure has an owner and a design behind it.",
      moduleLabel: "Temporary Works",
      moduleLabelKey: "nav.temporary_works",
      to: "/projects/:projectId/temporary-works",
    },
    {
      id: "check",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.check.in.register", label: "Registered item" },
        { labelKey: "cases.manage_temporary_works_and_inspections.step.check.in.design", label: "Design and calculations" },
      ],
      outputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.check.out.approved", label: "Design check signed" },
      ],
      titleKey: "cases.manage_temporary_works_and_inspections.step.check.title",
      titleDefault: "Record the design check",
      whatKey: "cases.manage_temporary_works_and_inspections.step.check.what",
      whatDefault:
        "Record the independent design check and the temporary works coordinator sign-off against each item, so the design is verified before anything is built to it.",
      whyKey: "cases.manage_temporary_works_and_inspections.step.check.why",
      whyDefault:
        "A design check is only worth something if it is recorded and holds the work back until it is done. Tying the sign-off to the item is what makes the check a real gate, not a formality.",
      moduleLabel: "Temporary Works",
      moduleLabelKey: "nav.temporary_works",
      to: "/projects/:projectId/temporary-works",
    },
    {
      id: "permit",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.permit.in.approved", label: "Approved item" },
      ],
      outputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.permit.out.permit", label: "Permit to load" },
      ],
      titleKey: "cases.manage_temporary_works_and_inspections.step.permit.title",
      titleDefault: "Inspect and permit to load",
      whatKey: "cases.manage_temporary_works_and_inspections.step.permit.what",
      whatDefault:
        "Inspect the erected item against its design, confirm it was built as drawn, and issue the permit to load only once it passes.",
      whyKey: "cases.manage_temporary_works_and_inspections.step.permit.why",
      whyDefault:
        "The gap between design and what got built is where temporary works fail. A pre-load inspection and permit is the last check before people and loads depend on it.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "reinspect",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.reinspect.in.permit", label: "Loaded item" },
      ],
      outputs: [
        { labelKey: "cases.manage_temporary_works_and_inspections.step.reinspect.out.record", label: "Inspection record" },
      ],
      titleKey: "cases.manage_temporary_works_and_inspections.step.reinspect.title",
      titleDefault: "Keep the inspection record",
      whatKey: "cases.manage_temporary_works_and_inspections.step.reinspect.what",
      whatDefault:
        "Keep the periodic inspections going - after high winds, adaptations or a set period - and record each one until the item is safely struck and signed off.",
      whyKey: "cases.manage_temporary_works_and_inspections.step.reinspect.why",
      whyDefault:
        "A scaffold safe on the day it was signed can be altered or damaged by the next week. The running inspection record is what keeps it safe for its whole life on the job.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
  ],
};

export default playbook;
