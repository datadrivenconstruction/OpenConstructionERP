// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Map and engage the stakeholders".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "map-and-engage-the-stakeholders",
  order: 1686,
  category: "planning",
  stage: "define",
  companyTypes: ["developer-client", "project-manager", "owner-operator"],
  roles: ["project-manager", "document-controller"],
  requiresProject: true,
  icon: "Users",
  titleKey: "cases.map_and_engage_the_stakeholders.title",
  titleDefault: "Map and engage the stakeholders",
  descKey: "cases.map_and_engage_the_stakeholders.desc",
  descDefault:
    "Register who can affect the project, assess them, plan and record the communication, track every promise made to them, and set out the project organisation with its mandates.",
  longDescKey: "cases.map_and_engage_the_stakeholders.longdesc",
  longDescDefault:
    "Projects are stopped by people as often as by ground conditions: a neighbour who was never told, an authority that learned about a change from the press, a promise to a tenant nobody kept. Stakeholders keeps the register, the assessment, the communication plan and the commitments in one place, and sets out who inside the project may decide what. A breached commitment can raise a risk, and the plan is filed for the gate.",
  estMinutes: 14,
  steps: [
    {
      id: "register",
      icon: "UserPlus",
      inputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.register.in.contacts", label: "Contacts" },
      ],
      outputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.register.out.register", label: "Stakeholder register" },
      ],
      titleKey: "cases.map_and_engage_the_stakeholders.step.register.title",
      titleDefault: "Register the stakeholders",
      whatKey: "cases.map_and_engage_the_stakeholders.step.register.what",
      whatDefault:
        "On the Settings tab pick the framework, then on the Register tab press Add stakeholder for each person or organisation that can affect the project.",
      whyKey: "cases.map_and_engage_the_stakeholders.step.register.why",
      whyDefault:
        "You cannot engage someone you have not listed. The register is the starting point for everything else on this screen.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=register",
    },
    {
      id: "assess",
      icon: "Crosshair",
      inputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.assess.in.register", label: "Stakeholder register" },
      ],
      outputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.assess.out.grid", label: "Interest and influence grid" },
      ],
      titleKey: "cases.map_and_engage_the_stakeholders.step.assess.title",
      titleDefault: "Assess interest and influence",
      whatKey: "cases.map_and_engage_the_stakeholders.step.assess.what",
      whatDefault:
        "Open a stakeholder and press Assess stakeholder, then look at the Analysis tab to see the grid.",
      whyKey: "cases.map_and_engage_the_stakeholders.step.assess.why",
      whyDefault:
        "The grid tells you who to manage closely and who only needs to be kept informed, so the effort goes where it matters.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=analysis",
    },
    {
      id: "communicate",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.communicate.in.grid", label: "Interest and influence grid" },
      ],
      outputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.communicate.out.plan", label: "Communication plan and log" },
      ],
      titleKey: "cases.map_and_engage_the_stakeholders.step.communicate.title",
      titleDefault: "Plan and record the communication",
      whatKey: "cases.map_and_engage_the_stakeholders.step.communicate.what",
      whatDefault:
        "On the Communication plan tab, plan each communication and record the event once it has taken place.",
      whyKey: "cases.map_and_engage_the_stakeholders.step.communicate.why",
      whyDefault:
        "A plan that is never checked against what happened is just a wish. Recording the events shows who was actually told what.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=plan",
    },
    {
      id: "commitments",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.commitments.in.meetings", label: "Meetings and letters" },
      ],
      outputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.commitments.out.commitments", label: "Commitment register" },
      ],
      titleKey: "cases.map_and_engage_the_stakeholders.step.commitments.title",
      titleDefault: "Track the promises",
      whatKey: "cases.map_and_engage_the_stakeholders.step.commitments.what",
      whatDefault:
        "On the Commitments tab, record each promise made to a stakeholder with an owner and a due date, and move it through agreed, in progress, fulfilled and verified.",
      whyKey: "cases.map_and_engage_the_stakeholders.step.commitments.why",
      whyDefault:
        "Promises made in meetings are forgotten by the project and remembered by the stakeholder. A tracked commitment is kept or openly renegotiated.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=commitments",
    },
    {
      id: "organisation",
      icon: "Network",
      inputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.organisation.in.team", label: "Project team" },
      ],
      outputs: [
        { labelKey: "cases.map_and_engage_the_stakeholders.step.organisation.out.mandates", label: "Organisation and mandates" },
      ],
      titleKey: "cases.map_and_engage_the_stakeholders.step.organisation.title",
      titleDefault: "Set the organisation and mandates",
      whatKey: "cases.map_and_engage_the_stakeholders.step.organisation.what",
      whatDefault:
        "On the Organisation and mandates tab, press Set holder for each role, add the governance bodies and their members, and save the mandates. Then export the project organisation and press File for the gate. The stakeholder and communication plan is filed the same way from the Register tab.",
      whyKey: "cases.map_and_engage_the_stakeholders.step.organisation.why",
      whyDefault:
        "Knowing who may decide what inside the project avoids decisions taken by the wrong person and decisions nobody takes.",
      moduleLabel: "Stakeholders",
      moduleLabelKey: "stakeholders.ui.title",
      to: "/projects/:projectId/stakeholders?tab=organisation",
    },
  ],
};

export default playbook;
