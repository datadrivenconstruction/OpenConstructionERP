// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a soft landings performance handover".
//
// Do not walk away at handover: confirm the in-use performance targets, set up
// aftercare, tune the systems in occupation and review performance against
// target in the first year. Content strings key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-a-soft-landings-performance-handover",
  order: 1027,
  category: "handover",
  companyTypes: ["general-contractor", "owner-operator", "project-manager"],
  stage: "operate",
  icon: "HeartHandshake",
  titleKey: "cases.run_a_soft_landings_performance_handover.title",
  titleDefault: "Run a soft landings performance handover",
  descKey: "cases.run_a_soft_landings_performance_handover.desc",
  descDefault:
    "Do not walk away at practical completion: confirm the in-use performance targets, set up an aftercare period, tune the systems in occupation and review real performance against target through the first year.",
  longDescKey: "cases.run_a_soft_landings_performance_handover.longdesc",
  longDescDefault:
    "A building handed over cold rarely performs as designed. Soft landings keeps the delivery team involved through the first year in use, tuning the systems against how the building is actually occupied, so the performance gap between design and reality is closed rather than inherited by the operator.",
  estMinutes: 11,
  steps: [
    {
      id: "targets",
      icon: "Crosshair",
      inputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.targets.in.design", label: "Design intent" },
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.targets.in.commissioning", label: "Commissioning results" },
      ],
      outputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.targets.out.targets", label: "In-use targets" },
      ],
      titleKey: "cases.run_a_soft_landings_performance_handover.step.targets.title",
      titleDefault: "Confirm the performance targets",
      whatKey: "cases.run_a_soft_landings_performance_handover.step.targets.what",
      whatDefault:
        "Confirm the targets the building is meant to hit in use - energy, comfort, air quality - from the design intent and the commissioning results, so aftercare has something concrete to measure against.",
      whyKey: "cases.run_a_soft_landings_performance_handover.step.targets.why",
      whyDefault:
        "You cannot tune towards a target nobody wrote down. Fixing the in-use performance measures at handover is what turns aftercare from a vague promise into a job with a finish line.",
      moduleLabel: "Commissioning",
      moduleLabelKey: "nav.commissioning",
      to: "/commissioning",
    },
    {
      id: "aftercare",
      icon: "HeartHandshake",
      inputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.aftercare.in.targets", label: "In-use targets" },
      ],
      outputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.aftercare.out.plan", label: "Aftercare plan" },
      ],
      titleKey: "cases.run_a_soft_landings_performance_handover.step.aftercare.title",
      titleDefault: "Set up the aftercare",
      whatKey: "cases.run_a_soft_landings_performance_handover.step.aftercare.what",
      whatDefault:
        "Set up the aftercare period with the team who stays involved after handover, the point of contact for the occupier and the schedule of reviews through the first year.",
      whyKey: "cases.run_a_soft_landings_performance_handover.step.aftercare.why",
      whyDefault:
        "The occupier learns a new building slowly and hits problems the delivery team can fix in minutes. A named aftercare contact is what stops small niggles turning into a soured relationship.",
      moduleLabel: "Handover",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "tune",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.tune.in.plan", label: "Aftercare plan" },
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.tune.in.feedback", label: "Occupier feedback" },
      ],
      outputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.tune.out.tuned", label: "Tuned systems" },
      ],
      titleKey: "cases.run_a_soft_landings_performance_handover.step.tune.title",
      titleDefault: "Tune the systems in use",
      whatKey: "cases.run_a_soft_landings_performance_handover.step.tune.what",
      whatDefault:
        "Respond to how the building is actually used: adjust the controls and setpoints, resolve the early service issues and act on occupier feedback as it comes in.",
      whyKey: "cases.run_a_soft_landings_performance_handover.step.tune.why",
      whyDefault:
        "Systems commissioned to an empty building are wrong the day it fills up. Tuning them against real occupancy is where most of the promised energy and comfort performance is actually won.",
      moduleLabel: "Service",
      moduleLabelKey: "nav.service",
      to: "/projects/:projectId/service",
    },
    {
      id: "review",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.review.in.tuned", label: "Tuned systems" },
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.review.in.targets", label: "In-use targets" },
      ],
      outputs: [
        { labelKey: "cases.run_a_soft_landings_performance_handover.step.review.out.lessons", label: "Performance review and lessons" },
      ],
      titleKey: "cases.run_a_soft_landings_performance_handover.step.review.title",
      titleDefault: "Review against target",
      whatKey: "cases.run_a_soft_landings_performance_handover.step.review.what",
      whatDefault:
        "Review the building's real energy and comfort performance against the targets across the first year and capture the lessons for the next project.",
      whyKey: "cases.run_a_soft_landings_performance_handover.step.review.why",
      whyDefault:
        "Measuring performance in use closes the loop that most projects leave open. It proves the building does what was promised and turns one job's hard lessons into the next one's better design.",
      moduleLabel: "Handover",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
