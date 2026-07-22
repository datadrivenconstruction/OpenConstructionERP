// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a milestone payment schedule".
//
// Tie payment milestones to programme events, value each one so the schedule
// sums to the contract, agree it with the client and read it as a cash flow.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-milestone-payment-schedule",
  order: 1012,
  category: "planning",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client"],
  icon: "Milestone",
  titleKey: "cases.build_a_milestone_payment_schedule.title",
  titleDefault: "Build a milestone payment schedule",
  descKey: "cases.build_a_milestone_payment_schedule.desc",
  descDefault:
    "Tie payment milestones to real programme events, value each one so the schedule sums back to the contract, agree it with the client and read the whole thing back as a cash flow.",
  longDescKey: "cases.build_a_milestone_payment_schedule.longdesc",
  longDescDefault:
    "A milestone schedule replaces monthly guesswork with payment on proof of progress. It only works if each milestone is a clear, verifiable event on the programme, because a vague milestone is an argument about whether it was reached.",
  estMinutes: 10,
  steps: [
    {
      id: "milestones",
      icon: "Milestone",
      inputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.milestones.in.programme", label: "Baseline programme" },
        { labelKey: "cases.build_a_milestone_payment_schedule.step.milestones.in.contract", label: "Contract terms" },
      ],
      outputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.milestones.out.events", label: "Payment milestones" },
      ],
      titleKey: "cases.build_a_milestone_payment_schedule.step.milestones.title",
      titleDefault: "Mark the payment milestones",
      whatKey: "cases.build_a_milestone_payment_schedule.step.milestones.what",
      whatDefault:
        "Pick the programme events that clearly prove progress - foundations complete, watertight, services on, handover - and mark each as a payment milestone.",
      whyKey: "cases.build_a_milestone_payment_schedule.step.milestones.why",
      whyDefault:
        "Payment on a verifiable event removes the monthly haggle over percentage complete. Choosing unambiguous milestones is what keeps the cash flowing without a dispute each cycle.",
      moduleLabel: "Schedule",
      moduleLabelKey: "schedule.title",
      to: "/schedule",
    },
    {
      id: "values",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.values.in.events", label: "Payment milestones" },
        { labelKey: "cases.build_a_milestone_payment_schedule.step.values.in.sum", label: "Contract sum" },
      ],
      outputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.values.out.valued", label: "Valued schedule" },
      ],
      titleKey: "cases.build_a_milestone_payment_schedule.step.values.title",
      titleDefault: "Value each milestone",
      whatKey: "cases.build_a_milestone_payment_schedule.step.values.what",
      whatDefault:
        "Attach a value to each milestone from the priced work it represents, and check the milestones sum exactly to the contract with nothing lost or double counted.",
      whyKey: "cases.build_a_milestone_payment_schedule.step.values.why",
      whyDefault:
        "Front-loaded milestones flatter the contractor and worry the client; back-loaded ones do the reverse. Valuing each one off the real work keeps the schedule fair and fundable.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "agree",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.agree.in.valued", label: "Valued schedule" },
      ],
      outputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.agree.out.agreed", label: "Agreed schedule" },
      ],
      titleKey: "cases.build_a_milestone_payment_schedule.step.agree.title",
      titleDefault: "Agree it with the client",
      whatKey: "cases.build_a_milestone_payment_schedule.step.agree.what",
      whatDefault:
        "Agree the milestone schedule with the client as the contractual basis for drawdown, so both sides sign up to what triggers each payment before work starts.",
      whyKey: "cases.build_a_milestone_payment_schedule.step.agree.why",
      whyDefault:
        "A schedule agreed up front is a schedule that pays on time. Settling the triggers before the money is due is what stops each milestone becoming a fresh negotiation.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "forecast",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.forecast.in.agreed", label: "Agreed schedule" },
      ],
      outputs: [
        { labelKey: "cases.build_a_milestone_payment_schedule.step.forecast.out.cashflow", label: "Cash flow forecast" },
      ],
      titleKey: "cases.build_a_milestone_payment_schedule.step.forecast.title",
      titleDefault: "Read it as a cash flow",
      whatKey: "cases.build_a_milestone_payment_schedule.step.forecast.what",
      whatDefault:
        "View the milestone payments across the programme as a cash flow forecast, so the client can plan funding and you can see when the money actually arrives.",
      whyKey: "cases.build_a_milestone_payment_schedule.step.forecast.why",
      whyDefault:
        "Milestones set the timing of cash, and cash timing is what keeps a job solvent. Seeing the curve early lets both sides fix a lumpy month before it becomes a funding crunch.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
