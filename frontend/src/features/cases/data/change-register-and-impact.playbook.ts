// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Change register and impact".
//
// Log every change in one register, read the time and cost impact the platform
// scores against the real ledger, then report the trend to the client.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "change-register-and-impact",
  order: 120,
  category: "commercial",
  companyTypes: [
    "general-contractor",
    "project-manager",
    "cost-consultant",
    "developer-client",
  ],
  roles: ["commercial-manager", "project-manager", "quantity-surveyor"],
  icon: "GitCompare",
  titleKey: "cases.change_register_and_impact.title",
  titleDefault: "Change register and impact",
  descKey: "cases.change_register_and_impact.desc",
  descDefault:
    "Capture every change in one register, read the time and cost impact scored against the real project ledger, and put the trend in front of the client before it becomes a surprise.",
  estMinutes: 11,
  steps: [
    {
      id: "register",
      icon: "ClipboardList",
      inputs: [
        {
          labelKey:
            "cases.change_register_and_impact.step.register.in.instruction",
          label: "Site instruction",
        },
        {
          labelKey: "cases.change_register_and_impact.step.register.in.memo",
          label: "Email or site memo",
        },
      ],
      outputs: [
        {
          labelKey: "cases.change_register_and_impact.step.register.out.entry",
          label: "Change register entry",
        },
        {
          labelKey: "cases.change_register_and_impact.step.register.out.value",
          label: "Logged status and value",
        },
      ],
      titleKey: "cases.change_register_and_impact.step.register.title",
      titleDefault: "Log the change",
      whatKey: "cases.change_register_and_impact.step.register.what",
      whatDefault:
        "Record each change as it lands with its origin, current status and value in a single register, so no instruction survives only as a line buried in an email thread.",
      whyKey: "cases.change_register_and_impact.step.register.why",
      whyDefault:
        "A change that never made the register is a change you will not get paid for. One shared list is what turns a scatter of verbal instructions and site memos into a claimable, auditable position.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "impact",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.change_register_and_impact.step.impact.in.register",
          label: "Change register",
        },
        {
          labelKey: "cases.change_register_and_impact.step.impact.in.ledger",
          label: "Project cost ledger",
        },
      ],
      outputs: [
        {
          labelKey: "cases.change_register_and_impact.step.impact.out.impact",
          label: "Time and cost impact",
        },
        {
          labelKey: "cases.change_register_and_impact.step.impact.out.pareto",
          label: "Top-change Pareto",
        },
      ],
      titleKey: "cases.change_register_and_impact.step.impact.title",
      titleDefault: "Read the impact",
      whatKey: "cases.change_register_and_impact.step.impact.what",
      whatDefault:
        "Read the time and cost impact scored against the actual project ledger, the Pareto of the few changes driving most of the money, and the rate at which new ones keep arriving.",
      whyKey: "cases.change_register_and_impact.step.impact.why",
      whyDefault:
        "Twenty small variations feel harmless right up until they add up to the one that blows the budget. Scoring impact against real spend is what surfaces the drift while there is still room to act.",
      moduleLabel: "Change Intelligence",
      moduleLabelKey: "nav.change_intelligence",
      to: "/change-intelligence",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.change_register_and_impact.step.report.in.impact",
          label: "Scored change impact",
        },
        {
          labelKey: "cases.change_register_and_impact.step.report.in.forecast",
          label: "Forecast final account",
        },
      ],
      outputs: [
        {
          labelKey: "cases.change_register_and_impact.step.report.out.report",
          label: "Client change report",
        },
        {
          labelKey: "cases.change_register_and_impact.step.report.out.trend",
          label: "Cumulative trend",
        },
      ],
      titleKey: "cases.change_register_and_impact.step.report.title",
      titleDefault: "Report the trend",
      whatKey: "cases.change_register_and_impact.step.report.what",
      whatDefault:
        "Produce the change report showing the cumulative value to date, the split of open against agreed, and how much each item moves the forecast final account.",
      whyKey: "cases.change_register_and_impact.step.report.why",
      whyDefault:
        "A client will accept a change trend they watched build; they fight the one dropped on them at the final account. Reporting early and plainly is what keeps that last conversation calm.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
