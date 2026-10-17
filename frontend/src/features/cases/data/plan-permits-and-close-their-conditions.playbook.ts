// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Plan permits and close their conditions".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "plan-permits-and-close-their-conditions",
  order: 1688,
  category: "planning",
  stage: "design",
  companyTypes: ["developer-client", "project-manager", "designer"],
  roles: ["project-manager", "design-lead", "document-controller"],
  requiresProject: true,
  icon: "Stamp",
  titleKey: "cases.plan_permits_and_close_their_conditions.title",
  titleDefault: "Plan permits and close their conditions",
  descKey: "cases.plan_permits_and_close_their_conditions.desc",
  descDefault:
    "Build the permit roadmap with need-by dates, follow each application to a decision, read the conditions out of the notice, and close every condition with evidence checked by a second person.",
  longDescKey: "cases.plan_permits_and_close_their_conditions.longdesc",
  longDescDefault:
    "A permit is not done when it is granted. Most notices carry conditions, and the ones that must be met before work starts or before handover can stop a site as surely as a refusal. Permits keeps the roadmap, the application history and the conditions in one place. Conditions can be read out of the notice for you, but each one waits for a person to accept or dismiss it, and closing a condition needs evidence that someone other than its owner has checked.",
  estMinutes: 14,
  steps: [
    {
      id: "roadmap",
      icon: "Route",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.roadmap.in.programme", label: "Project programme" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.roadmap.out.roadmap", label: "Permit roadmap" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.roadmap.title",
      titleDefault: "Start the roadmap",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.roadmap.what",
      whatDefault:
        "Press Start roadmap, choose the jurisdiction and permit catalogue, then use Take from the permit route or Add permit to list every permit with its need-by date.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.roadmap.why",
      whyDefault:
        "The need-by date comes from the programme, so a late application shows up as a programme risk months before it becomes a delay.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits",
    },
    {
      id: "apply",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.apply.in.roadmap", label: "Permit roadmap" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.apply.out.history", label: "Application history" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.apply.title",
      titleDefault: "Follow the application",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.apply.what",
      whatDefault:
        "On the Roadmap, open the permit and press Open application. Record each step as it happens: Start preparing, Record submission, Authority asked for information, and record a stop or extension when the decision period stops or is extended.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.apply.why",
      whyDefault:
        "Review periods stop and restart. Recording the steps keeps the real deadline visible instead of the one in the original plan.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits",
    },
    {
      id: "decision",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.decision.in.notice", label: "Permit notice" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.decision.out.permit", label: "Permit on record" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.decision.title",
      titleDefault: "Record the decision",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.decision.what",
      whatDefault:
        "In the open application, press Record decision and choose Granted, Granted with conditions, Partially granted or Refused, with the decision date and the notice reference.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.decision.why",
      whyDefault:
        "The decision starts the clock for appeals and for the conditions. Recording it with the reference makes it citable later.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits",
    },
    {
      id: "conditions",
      icon: "ListTodo",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.conditions.in.notice", label: "Permit notice" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.conditions.out.conditions", label: "Conditions with owners" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.conditions.title",
      titleDefault: "Read in the conditions",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.conditions.what",
      whatDefault:
        "On the Permits granted tab, press Read conditions from the notice on a permit in force, or Add condition, then accept or dismiss each proposal. On the Conditions tab, press Assign owner to conditions without one.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.conditions.why",
      whyDefault:
        "Reading the notice for you saves an afternoon, but only you can judge whether a condition was read correctly. Nothing is added until you accept it.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits?tab=permits",
    },
    {
      id: "close",
      icon: "CircleCheckBig",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.close.in.conditions", label: "Conditions with owners" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.close.out.closed", label: "Closed conditions with evidence" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.close.title",
      titleDefault: "Close conditions with evidence",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.close.what",
      whatDefault:
        "For each condition, add the evidence, submit it for checking and let a second person close it.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.close.why",
      whyDefault:
        "A condition closed by its own owner is a claim, not a proof. The second check is what an authority or a buyer will rely on later.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits?tab=conditions",
    },
    {
      id: "readiness",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.readiness.in.closed", label: "Closed conditions with evidence" },
      ],
      outputs: [
        { labelKey: "cases.plan_permits_and_close_their_conditions.step.readiness.out.readiness", label: "Readiness report" },
      ],
      titleKey: "cases.plan_permits_and_close_their_conditions.step.readiness.title",
      titleDefault: "Check readiness to start",
      whatKey: "cases.plan_permits_and_close_their_conditions.step.readiness.what",
      whatDefault:
        "On the Readiness tab, check whether the project is ready to start work and later to hand over. To export the register, switch to the Roadmap, Permits granted or Conditions tab.",
      whyKey: "cases.plan_permits_and_close_their_conditions.step.readiness.why",
      whyDefault:
        "Conditions that must be met before start or before handover block those milestones. The readiness check names exactly which ones.",
      moduleLabel: "Permits",
      moduleLabelKey: "permits.ui.title",
      to: "/projects/:projectId/permits?tab=checks",
    },
  ],
};

export default playbook;
