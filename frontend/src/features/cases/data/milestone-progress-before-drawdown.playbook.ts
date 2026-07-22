// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Check milestone progress before a valuation is approved".
//
// A developer / client case: confirm the programme has genuinely hit its
// milestone before signing off the valuation that releases funds against it.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "milestone-progress-before-drawdown",
  order: 235,
  category: "commercial",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  icon: "Flag",
  titleKey: "cases.milestone_progress_before_drawdown.title",
  titleDefault: "Check milestone progress before a valuation is approved",
  descKey: "cases.milestone_progress_before_drawdown.desc",
  descDefault:
    "Confirm the programme has genuinely hit its milestone, cross-check it against the earned value, and only then approve the valuation that releases funds against it.",
  estMinutes: 9,
  steps: [
    {
      id: "milestones",
      icon: "Flag",
      inputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.milestones.in.schedule",
          label: "Project schedule",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.milestones.in.claim",
          label: "Claimed milestone",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.milestones.out.status",
          label: "Confirmed milestone status",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.milestones.out.progress",
          label: "Verified progress",
        },
      ],
      inputsHintKey:
        "cases.milestone_progress_before_drawdown.step.milestones.in.hint",
      inputsHintDefault:
        "Bring the live programme and the exact milestone the valuation is claimed against. With both open you can point at one dated milestone and read straight off the schedule whether it is finished or only close.",
      outputsHintKey:
        "cases.milestone_progress_before_drawdown.step.milestones.out.hint",
      outputsHintDefault:
        "You walk away with a firm reached or not-reached decision for that milestone and the verified percent complete behind it, ready to defend if the figure is questioned later.",
      titleKey:
        "cases.milestone_progress_before_drawdown.step.milestones.title",
      titleDefault: "Check the milestone against the programme",
      whatKey: "cases.milestone_progress_before_drawdown.step.milestones.what",
      whatDefault:
        "Open the schedule and confirm the milestone the valuation is claimed against has actually been reached, not just is close.",
      whyKey: "cases.milestone_progress_before_drawdown.step.milestones.why",
      whyDefault:
        "A milestone claimed a week early and paid against is money released for work not yet done, and it is awkward to claw back.",
      moduleLabel: "Schedule",
      moduleLabelKey: "schedule.title",
      to: "/schedule",
    },
    {
      id: "earned",
      icon: "LineChart",
      inputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.earned.in.milestone",
          label: "Confirmed milestone",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.earned.in.spend",
          label: "Cost to date",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.earned.in.planned",
          label: "Planned value",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.earned.out.ev",
          label: "Earned value reading",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.earned.out.consistency",
          label: "Claim consistency check",
        },
      ],
      inputsHintKey:
        "cases.milestone_progress_before_drawdown.step.earned.in.hint",
      inputsHintDefault:
        "Bring the milestone you just confirmed together with the cost booked to date and the value that was planned for this point. Having the three side by side is what lets you weigh the claim against the real spend.",
      outputsHintKey:
        "cases.milestone_progress_before_drawdown.step.earned.out.hint",
      outputsHintDefault:
        "You get a clear earned-value reading and a simple consistency check: does what has been earned line up with the milestone being claimed, or is one running ahead of the other.",
      titleKey: "cases.milestone_progress_before_drawdown.step.earned.title",
      titleDefault: "Read the earned value to date",
      whatKey: "cases.milestone_progress_before_drawdown.step.earned.what",
      whatDefault:
        "Check the value earned to date against what has been spent and what was planned, so the milestone claim is consistent with the wider cost picture.",
      whyKey: "cases.milestone_progress_before_drawdown.step.earned.why",
      whyDefault:
        "A milestone can look reached on the programme while the cost and earned-value picture tells a different story. Reading both together is what catches an inconsistency before it is paid.",
      moduleLabel: "Value",
      moduleLabelKey: "nav.value",
      to: "/projects/:projectId/value",
    },
    {
      id: "approve",
      icon: "Banknote",
      inputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.approve.in.ev",
          label: "Earned value reading",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.approve.in.status",
          label: "Milestone status",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.approve.in.amount",
          label: "Valuation amount",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.approve.out.approved",
          label: "Approved valuation",
        },
        {
          labelKey:
            "cases.milestone_progress_before_drawdown.step.approve.out.drawdown",
          label: "Released drawdown",
        },
      ],
      inputsHintKey:
        "cases.milestone_progress_before_drawdown.step.approve.in.hint",
      inputsHintDefault:
        "Bring the earned-value reading, the confirmed milestone status and the amount on the valuation. These three together tell you exactly how much of the claim the evidence actually supports.",
      outputsHintKey:
        "cases.milestone_progress_before_drawdown.step.approve.out.hint",
      outputsHintDefault:
        "You issue an approved valuation for the amount the evidence supports and release the matching drawdown, with any partial amount clearly noted against a milestone still in progress.",
      titleKey: "cases.milestone_progress_before_drawdown.step.approve.title",
      titleDefault: "Approve the valuation",
      whatKey: "cases.milestone_progress_before_drawdown.step.approve.what",
      whatDefault:
        "Approve the valuation for the amount the milestone and the earned value actually support, noting any partial release against a milestone still in progress.",
      whyKey: "cases.milestone_progress_before_drawdown.step.approve.why",
      whyDefault:
        "An approval grounded in the programme and the earned value is one that stands up when funders or auditors ask what it was based on.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
