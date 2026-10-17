// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Staff the project and clear people to start".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "staff-the-project-and-clear-people-to-start",
  order: 1690,
  category: "planning",
  stage: "plan",
  companyTypes: ["developer-client", "project-manager", "general-contractor"],
  roles: ["project-manager", "site-manager", "hse-officer"],
  requiresProject: true,
  icon: "UserCheck",
  titleKey: "cases.staff_the_project_and_clear_people_to_start.title",
  titleDefault: "Staff the project and clear people to start",
  descKey: "cases.staff_the_project_and_clear_people_to_start.desc",
  descDefault:
    "Build the staffing plan from the role catalogue, fill each position, keep a personnel file with the documents each role requires, watch what is expiring, and get the plan approved.",
  longDescKey: "cases.staff_the_project_and_clear_people_to_start.longdesc",
  longDescDefault:
    "A project needs the right roles in each phase and people in them who are cleared to work. Staffing turns the role catalogue into positions with headcount and dates, links them to the people on the project team, and keeps a personnel file per person with the documents the role requires. It derives whether each document is valid, expiring or missing, and the plan becomes binding once it is approved at the gate or by a second person.",
  estMinutes: 14,
  steps: [
    {
      id: "plan",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.plan.in.catalogue", label: "Role catalogue" },
      ],
      outputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.plan.out.positions", label: "Positions per phase" },
      ],
      titleKey: "cases.staff_the_project_and_clear_people_to_start.step.plan.title",
      titleDefault: "Create the staffing plan",
      whatKey: "cases.staff_the_project_and_clear_people_to_start.step.plan.what",
      whatDefault:
        "Pick a catalogue and press Create staffing plan, then use Add roles from catalogue to create one position per role for a phase and start date. Edit a position to set its headcount and mark key roles.",
      whyKey: "cases.staff_the_project_and_clear_people_to_start.step.plan.why",
      whyDefault:
        "A plan per phase shows early where key roles are still open, while there is time to recruit.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing",
    },
    {
      id: "assign",
      icon: "UserPlus",
      inputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.assign.in.team", label: "Project team" },
      ],
      outputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.assign.out.fills", label: "Filled positions" },
      ],
      titleKey: "cases.staff_the_project_and_clear_people_to_start.step.assign.title",
      titleDefault: "Fill the positions",
      whatKey: "cases.staff_the_project_and_clear_people_to_start.step.assign.what",
      whatDefault:
        "Press Assign person for each position and pick someone from the project team. Confirm the fill once it is agreed.",
      whyKey: "cases.staff_the_project_and_clear_people_to_start.step.assign.why",
      whyDefault:
        "An open key role is a risk to the gate. Filling the plan shows exactly who carries each responsibility.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing",
    },
    {
      id: "files",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.files.in.documents", label: "Personal documents" },
      ],
      outputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.files.out.files", label: "Personnel files" },
      ],
      titleKey: "cases.staff_the_project_and_clear_people_to_start.step.files.title",
      titleDefault: "Keep the personnel files",
      whatKey: "cases.staff_the_project_and_clear_people_to_start.step.files.what",
      whatDefault:
        "On the People tab, open each personnel file and record the documents the role requires: contract, work permit, induction, training and qualifications.",
      whyKey: "cases.staff_the_project_and_clear_people_to_start.step.files.why",
      whyDefault:
        "A person without a valid permit or induction cannot work, whatever the plan says. The file is where that is proven.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing?tab=people",
    },
    {
      id: "compliance",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.compliance.in.files", label: "Personnel files" },
      ],
      outputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.compliance.out.matrix", label: "Compliance matrix" },
      ],
      titleKey: "cases.staff_the_project_and_clear_people_to_start.step.compliance.title",
      titleDefault: "Check compliance",
      whatKey: "cases.staff_the_project_and_clear_people_to_start.step.compliance.what",
      whatDefault:
        "On the Compliance tab, read the matrix of people against required documents, and on the Upcoming tab see which documents expire in the next 90 days, with those due within 30 days highlighted.",
      whyKey: "cases.staff_the_project_and_clear_people_to_start.step.compliance.why",
      whyDefault:
        "Documents expire while people are on site. Seeing them coming avoids someone being sent home on the day of a pour.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing?tab=compliance",
    },
    {
      id: "approve",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.approve.in.positions", label: "Positions per phase" },
      ],
      outputs: [
        { labelKey: "cases.staff_the_project_and_clear_people_to_start.step.approve.out.approved", label: "Approved staffing plan" },
      ],
      titleKey: "cases.staff_the_project_and_clear_people_to_start.step.approve.title",
      titleDefault: "Submit the plan for approval",
      whatKey: "cases.staff_the_project_and_clear_people_to_start.step.approve.what",
      whatDefault:
        "Clear the findings listed under Before you can submit, then press Submit for review. The plan is approved at the gate or by a second person, and exported as PDF or Excel.",
      whyKey: "cases.staff_the_project_and_clear_people_to_start.step.approve.why",
      whyDefault:
        "An approved plan is the binding record of who the project relies on. Later changes open a revision while the approved plan stays in force.",
      moduleLabel: "Staffing",
      moduleLabelKey: "staffing.title",
      to: "/projects/:projectId/staffing",
    },
  ],
};

export default playbook;
