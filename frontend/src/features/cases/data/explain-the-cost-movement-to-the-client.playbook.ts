// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Explain the cost movement to the client".
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "explain-the-cost-movement-to-the-client",
  order: 1703,
  category: "commercial",
  stage: "build",
  companyTypes: ["developer-client", "cost-consultant", "project-manager"],
  roles: ["commercial-manager", "project-manager", "finance-manager"],
  icon: "TrendingUp",
  titleKey: "cases.explain_the_cost_movement_to_the_client.title",
  titleDefault: "Explain the cost movement to the client",
  descKey: "cases.explain_the_cost_movement_to_the_client.desc",
  descDefault:
    "Save forecasts at each stage from budget to final account, read the chart of forecast against plan over time, and take the movement to the client or the bank with the reasons behind it.",
  longDescKey: "cases.explain_the_cost_movement_to_the_client.longdesc",
  longDescDefault:
    "A client or a lender rarely asks only what the project will cost. They ask why the number moved since the last report. Saved forecasts answer that: each one freezes the figures of a date and is marked with its stage, from budget and estimate through award and the monthly forecasts to the final account. The chart puts them on one line against the plan, and the line drawers carry the reasons for every own forecast.",
  estMinutes: 10,
  steps: [
    {
      id: "stages",
      icon: "Milestone",
      inputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.stages.in.figures", label: "Current figures" },
      ],
      outputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.stages.out.snapshot", label: "Snapshot marked with its stage" },
      ],
      titleKey: "cases.explain_the_cost_movement_to_the_client.step.stages.title",
      titleDefault: "Save a forecast at each stage",
      whatKey: "cases.explain_the_cost_movement_to_the_client.step.stages.what",
      whatDefault:
        "In Cost control, press Save forecast and choose the stage the figures mark: budget, estimate, detailed estimate, pre-tender estimate, award, forecast or final account.",
      whyKey: "cases.explain_the_cost_movement_to_the_client.step.stages.why",
      whyDefault:
        "Stages are how clients and standards talk about cost. Marking each snapshot with its stage lets you compare like with like years later.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "chart",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.chart.in.snapshots", label: "Saved forecasts" },
      ],
      outputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.chart.out.movement", label: "Movement over time" },
      ],
      titleKey: "cases.explain_the_cost_movement_to_the_client.step.chart.title",
      titleDefault: "Read the chart over time",
      whatKey: "cases.explain_the_cost_movement_to_the_client.step.chart.what",
      whatDefault:
        "Once two or more forecasts are saved, read the forecast line against the dashed planned line under Saved forecasts, and the change from the previous one in the list below it.",
      whyKey: "cases.explain_the_cost_movement_to_the_client.step.chart.why",
      whyDefault:
        "The chart shows in one glance whether the project is drifting or jumped once. The two need very different explanations.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "reasons",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.reasons.in.movement", label: "Movement over time" },
      ],
      outputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.reasons.out.reasons", label: "Reasons per line" },
      ],
      titleKey: "cases.explain_the_cost_movement_to_the_client.step.reasons.title",
      titleDefault: "Collect the reasons",
      whatKey: "cases.explain_the_cost_movement_to_the_client.step.reasons.what",
      whatDefault:
        "For the lines that moved, open the drawer and read the history: approved changes, own forecasts and the reasons given for them.",
      whyKey: "cases.explain_the_cost_movement_to_the_client.step.reasons.why",
      whyDefault:
        "A movement with a reason attached is a management decision. A movement without one is a surprise, and clients remember surprises.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.report.in.reasons", label: "Reasons per line" },
      ],
      outputs: [
        { labelKey: "cases.explain_the_cost_movement_to_the_client.step.report.out.report", label: "Cost report for the client" },
      ],
      titleKey: "cases.explain_the_cost_movement_to_the_client.step.report.title",
      titleDefault: "Report to the client",
      whatKey: "cases.explain_the_cost_movement_to_the_client.step.report.what",
      whatDefault:
        "Take the figures from Cost control to the client or the bank: the expected final cost, the difference to plan, the saved-forecast chart and the reasons from the line drawers. The Cost Report under Reports is a 5D budget export and does not carry the reasons.",
      whyKey: "cases.explain_the_cost_movement_to_the_client.step.report.why",
      whyDefault:
        "A short report that names the movement and its causes builds the trust that keeps a client calm when the next change comes.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
  ],
};

export default playbook;
