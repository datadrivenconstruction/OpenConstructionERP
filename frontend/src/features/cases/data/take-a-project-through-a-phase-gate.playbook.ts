// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Take a project through a phase gate".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "take-a-project-through-a-phase-gate",
  order: 1681,
  category: "planning",
  stage: "define",
  companyTypes: ["developer-client", "project-manager", "owner-operator"],
  roles: ["project-manager", "commercial-manager"],
  requiresProject: true,
  icon: "Flag",
  titleKey: "cases.take_a_project_through_a_phase_gate.title",
  titleDefault: "Take a project through a phase gate",
  descKey: "cases.take_a_project_through_a_phase_gate.desc",
  descDefault:
    "Pick a phase model, name an owner for every area, collect the evidence, and record a gate decision under the four-eyes rule, with conditions you later clear or waive on the record.",
  longDescKey: "cases.take_a_project_through_a_phase_gate.longdesc",
  longDescDefault:
    "A phase gate is the moment a client decides whether the project is ready for the next phase. The decision is only as good as what was on the table: an owner for every area, the documents that prove readiness, and a decider who is not the person who prepared them. Project governance holds all of this in one matrix, refuses a plain go while blockers are open, and keeps every decision, condition and reopening in the history.",
  estMinutes: 15,
  steps: [
    {
      id: "model",
      icon: "GitBranch",
      inputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.model.in.catalogue", label: "Phase model catalogue" },
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.model.in.route", label: "Approval route" },
      ],
      outputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.model.out.gates", label: "Gates of the project" },
      ],
      titleKey: "cases.take_a_project_through_a_phase_gate.step.model.title",
      titleDefault: "Choose the phase model",
      whatKey: "cases.take_a_project_through_a_phase_gate.step.model.what",
      whatDefault:
        "On the Phase model tab, look at the available models, press Use this phase model and pick the approval route that decides gate decisions.",
      whyKey: "cases.take_a_project_through_a_phase_gate.step.model.why",
      whyDefault:
        "The phase model fixes which gates the project passes and what each one needs. The approval route fixes who decides. Both have to be settled before anyone collects evidence.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance?tab=model",
    },
    {
      id: "owners",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.owners.in.team", label: "Project team" },
      ],
      outputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.owners.out.owners", label: "Owner and deputy per area" },
      ],
      titleKey: "cases.take_a_project_through_a_phase_gate.step.owners.title",
      titleDefault: "Assign the area owners",
      whatKey: "cases.take_a_project_through_a_phase_gate.step.owners.what",
      whatDefault:
        "In the matrix, open each management area and press Assign to name an owner and a deputy.",
      whyKey: "cases.take_a_project_through_a_phase_gate.step.owners.why",
      whyDefault:
        "An area without an owner blocks its gate. Naming a person per area is what turns a list of topics into a list of answers someone is responsible for.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance",
    },
    {
      id: "evidence",
      icon: "Paperclip",
      inputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.evidence.in.docs", label: "Frame documents" },
      ],
      outputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.evidence.out.ready", label: "Areas confirmed ready" },
      ],
      titleKey: "cases.take_a_project_through_a_phase_gate.step.evidence.title",
      titleDefault: "Attach the evidence",
      whatKey: "cases.take_a_project_through_a_phase_gate.step.evidence.what",
      whatDefault:
        "On each area page, attach the frame document from the document environment or upload it, then press Submit for gate review. On the gate page, the area owner or the deputy then presses Confirm readiness.",
      whyKey: "cases.take_a_project_through_a_phase_gate.step.evidence.why",
      whyDefault:
        "A gate decided on slides cannot be checked later. Evidence attached to the area stays with the decision, in the revision that was actually reviewed.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance",
    },
    {
      id: "decide",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.decide.in.ready", label: "Areas confirmed ready" },
      ],
      outputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.decide.out.decision", label: "Gate decision on record" },
      ],
      titleKey: "cases.take_a_project_through_a_phase_gate.step.decide.title",
      titleDefault: "Record the gate decision",
      whatKey: "cases.take_a_project_through_a_phase_gate.step.decide.what",
      whatDefault:
        "Open the gate and press Start preparation, then Submit for review. Once the earlier approvers of the route have signed off, press Record decision, choose go, go with conditions, hold, recycle or stop, and tick every evidence item that needs confirming.",
      whyKey: "cases.take_a_project_through_a_phase_gate.step.decide.why",
      whyDefault:
        "Only the manager named on the last step of the route may decide, and never the owner of an area or the deputy. A plain go is refused while blockers are open, so nothing slips through on goodwill.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance",
    },
    {
      id: "conditions",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.conditions.in.open", label: "Open conditions" },
      ],
      outputs: [
        { labelKey: "cases.take_a_project_through_a_phase_gate.step.conditions.out.closed", label: "Conditions closed on record" },
      ],
      titleKey: "cases.take_a_project_through_a_phase_gate.step.conditions.title",
      titleDefault: "Clear or waive the conditions",
      whatKey: "cases.take_a_project_through_a_phase_gate.step.conditions.what",
      whatDefault:
        "On the Conditions tab, clear each condition with evidence, or waive it with a written reason.",
      whyKey: "cases.take_a_project_through_a_phase_gate.step.conditions.why",
      whyDefault:
        "A go with conditions is only safe when the conditions are actually closed. The tab counts the open ones so they cannot be forgotten in the next phase.",
      moduleLabel: "Project governance",
      moduleLabelKey: "governance.project.title",
      to: "/projects/:projectId/governance?tab=conditions",
    },
  ],
};

export default playbook;
