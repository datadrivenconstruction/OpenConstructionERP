// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Correct the forecast and say why".
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "correct-the-forecast-and-say-why",
  order: 1702,
  category: "commercial",
  stage: "build",
  companyTypes: ["developer-client", "cost-consultant", "project-manager", "general-contractor"],
  roles: ["commercial-manager", "quantity-surveyor"],
  icon: "Pencil",
  titleKey: "cases.correct_the_forecast_and_say_why.title",
  titleDefault: "Correct the forecast and say why",
  descKey: "cases.correct_the_forecast_and_say_why.desc",
  descDefault:
    "See where each line's forecast comes from, recognise a line that is only partly awarded or certified beyond its award, enter your own figure with a reason, and switch back to the automatic forecast when the bookings catch up.",
  longDescKey: "cases.correct_the_forecast_and_say_why.longdesc",
  longDescDefault:
    "Every forecast on the cost control page names its source, most reliable first: your own forecast, the final account, measured work, award plus changes, the plan of a partly awarded line, the estimate, the budget. The automatic choice is right most of the time. When it is not, you overrule it, and the page keeps your reason, the document you name for it, and what the automatic forecast would have said, so the next person can follow the decision.",
  estMinutes: 8,
  steps: [
    {
      id: "source",
      icon: "HelpCircle",
      inputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.source.in.line", label: "Cost line" },
      ],
      outputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.source.out.source", label: "Forecast source understood" },
      ],
      titleKey: "cases.correct_the_forecast_and_say_why.step.source.title",
      titleDefault: "Read where the forecast comes from",
      whatKey: "cases.correct_the_forecast_and_say_why.step.source.what",
      whatDefault:
        "Open Cost control and click a cost line. The drawer shows planned, awarded, changes, certified and paid, and a badge that says which source the forecast is taken from and why.",
      whyKey: "cases.correct_the_forecast_and_say_why.step.source.why",
      whyDefault:
        "A figure you cannot trace is a figure nobody defends in front of the client. The source badge is the explanation.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "partly",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.partly.in.awarded", label: "Awarded amounts" },
      ],
      outputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.partly.out.gap", label: "Remaining work to price" },
      ],
      titleKey: "cases.correct_the_forecast_and_say_why.step.partly.title",
      titleDefault: "Spot a partly awarded line",
      whatKey: "cases.correct_the_forecast_and_say_why.step.partly.what",
      whatDefault:
        "Look for the finding that only part of a line's plan is awarded, less than half. The forecast then stays at the plan, and the hint asks for your own figure if more work is still to be let.",
      whyKey: "cases.correct_the_forecast_and_say_why.step.partly.why",
      whyDefault:
        "A line where only part of the work is let looks safe because the plan still covers it. Only you know whether the rest will fit.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "override",
      icon: "Pencil",
      inputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.override.in.offer", label: "New offer or estimate" },
      ],
      outputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.override.out.own", label: "Own forecast with reason" },
      ],
      titleKey: "cases.correct_the_forecast_and_say_why.step.override.title",
      titleDefault: "Enter your own forecast",
      whatKey: "cases.correct_the_forecast_and_say_why.step.override.what",
      whatDefault:
        "Press Enter your own forecast, type the expected final cost, write why (it is required) and note the document it rests on, then Save forecast.",
      whyKey: "cases.correct_the_forecast_and_say_why.step.override.why",
      whyDefault:
        "Your figure replaces the automatic one, and the drawer keeps showing what the automatic forecast would be, so the difference stays visible.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "revert",
      icon: "GitBranch",
      inputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.revert.in.own", label: "Own forecast with reason" },
      ],
      outputs: [
        { labelKey: "cases.correct_the_forecast_and_say_why.step.revert.out.history", label: "Forecast history per line" },
      ],
      titleKey: "cases.correct_the_forecast_and_say_why.step.revert.title",
      titleDefault: "Go back to the automatic forecast",
      whatKey: "cases.correct_the_forecast_and_say_why.step.revert.what",
      whatDefault:
        "When the contract is let and the bookings catch up, press Use the automatic forecast again. The History list shows every own forecast entered and replaced.",
      whyKey: "cases.correct_the_forecast_and_say_why.step.revert.why",
      whyDefault:
        "An own forecast left standing after the facts changed is worse than none. Switching back keeps the forecast tied to what is booked.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
  ],
};

export default playbook;
