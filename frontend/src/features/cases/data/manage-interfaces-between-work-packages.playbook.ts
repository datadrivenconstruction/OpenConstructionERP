// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage interfaces between work packages".
//
// Build the interface register, give each interface an owner on both sides and
// the information to exchange, drive the open ones through interface meetings and
// close them when both sides agree. Content strings key plus inline default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-interfaces-between-work-packages",
  order: 1022,
  category: "planning",
  companyTypes: ["general-contractor", "project-manager", "bim-consultant"],
  stage: "build",
  icon: "Waypoints",
  titleKey: "cases.manage_interfaces_between_work_packages.title",
  titleDefault: "Manage interfaces between work packages",
  descKey: "cases.manage_interfaces_between_work_packages.desc",
  descDefault:
    "Build the interface register, give each interface an owner on both sides and the information to exchange, drive the open ones through interface meetings and close them only when both sides agree.",
  longDescKey: "cases.manage_interfaces_between_work_packages.longdesc",
  longDescDefault:
    "The work inside a package usually goes fine. It is the boundary between packages - who casts the upstand, who leaves the hole, whose tolerance governs - where things fall down the gap. An interface register makes those boundaries somebody's job instead of nobody's.",
  estMinutes: 10,
  steps: [
    {
      id: "register",
      icon: "Waypoints",
      inputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.register.in.packages", label: "Work packages" },
        { labelKey: "cases.manage_interfaces_between_work_packages.step.register.in.scope", label: "Scope boundaries" },
      ],
      outputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.register.out.register", label: "Interface register" },
      ],
      titleKey: "cases.manage_interfaces_between_work_packages.step.register.title",
      titleDefault: "Build the interface register",
      whatKey: "cases.manage_interfaces_between_work_packages.step.register.what",
      whatDefault:
        "List the physical and organisational interfaces between packages: where one trade hands over to the next, where scopes touch and where a tolerance or a builder's-work detail crosses a boundary.",
      whyKey: "cases.manage_interfaces_between_work_packages.step.register.why",
      whyDefault:
        "Naming the interfaces is what turns a fuzzy boundary into a managed one. The interface nobody wrote down is the gap that becomes a variation and a delay when both sides deny it.",
      moduleLabel: "Interface Register",
      moduleLabelKey: "nav.interface_management",
      to: "/projects/:projectId/interface-management",
    },
    {
      id: "owners",
      icon: "Users",
      inputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.owners.in.register", label: "Interface register" },
      ],
      outputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.owners.out.assigned", label: "Owners and needs set" },
      ],
      titleKey: "cases.manage_interfaces_between_work_packages.step.owners.title",
      titleDefault: "Assign owners on both sides",
      whatKey: "cases.manage_interfaces_between_work_packages.step.owners.what",
      whatDefault:
        "Give each interface an owner on both sides, the information each needs from the other and the date it is needed by, so the exchange is a commitment rather than a hope.",
      whyKey: "cases.manage_interfaces_between_work_packages.step.owners.why",
      whyDefault:
        "An interface with one owner is an argument waiting to happen. Naming both sides and what each owes the other is what makes the handover actually work at the boundary.",
      moduleLabel: "Interface Register",
      moduleLabelKey: "nav.interface_management",
      to: "/projects/:projectId/interface-management",
    },
    {
      id: "drive",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.drive.in.assigned", label: "Open interfaces" },
      ],
      outputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.drive.out.actions", label: "Agreed actions" },
      ],
      titleKey: "cases.manage_interfaces_between_work_packages.step.drive.title",
      titleDefault: "Drive them in interface meetings",
      whatKey: "cases.manage_interfaces_between_work_packages.step.drive.what",
      whatDefault:
        "Work the open interfaces in regular interface meetings, agree who does what by when at each boundary and minute the actions against the register.",
      whyKey: "cases.manage_interfaces_between_work_packages.step.drive.why",
      whyDefault:
        "Interfaces close when the two sides sit down and agree, not when a register sits idle. The meeting is where the ambiguity at the boundary gets resolved before the trades reach it.",
      moduleLabel: "Meetings",
      moduleLabelKey: "nav.meetings",
      to: "/projects/:projectId/meetings",
    },
    {
      id: "close",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.close.in.actions", label: "Agreed actions" },
      ],
      outputs: [
        { labelKey: "cases.manage_interfaces_between_work_packages.step.close.out.closed", label: "Closed interfaces" },
      ],
      titleKey: "cases.manage_interfaces_between_work_packages.step.close.title",
      titleDefault: "Close when both sides agree",
      whatKey: "cases.manage_interfaces_between_work_packages.step.close.what",
      whatDefault:
        "Close an interface only when both owners confirm the exchange is done and the physical detail is resolved, so a closed item really is closed.",
      whyKey: "cases.manage_interfaces_between_work_packages.step.close.why",
      whyDefault:
        "Closing on one side's say-so is how a gap reopens on site. Requiring both sides to agree is what makes the register a true picture of what is settled and what still bites.",
      moduleLabel: "Interface Register",
      moduleLabelKey: "nav.interface_management",
      to: "/projects/:projectId/interface-management",
    },
  ],
};

export default playbook;
