// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run the monthly cost report".
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-the-monthly-cost-report",
  order: 1700,
  category: "commercial",
  stage: "build",
  companyTypes: ["developer-client", "cost-consultant", "project-manager", "general-contractor"],
  roles: ["commercial-manager", "quantity-surveyor", "project-manager"],
  icon: "LineChart",
  titleKey: "cases.run_the_monthly_cost_report.title",
  titleDefault: "Run the monthly cost report",
  descKey: "cases.run_the_monthly_cost_report.desc",
  descDefault:
    "Once a month: put every committed amount on a cost line, read what is worth a look, correct the forecast where you know better, decide pending changes and save the month's forecast for the history.",
  longDescKey: "cases.run_the_monthly_cost_report.longdesc",
  longDescDefault:
    "Cost control answers one question every month: what will this project cost in the end, and what moved since last time? It reads the plan from the cost lines, the awarded amount from contracts and purchase orders, approved changes and certified work, and works out a forecast per line from the most reliable source available. The monthly routine is short: nothing unassigned, findings read, your own knowledge entered with a reason, changes decided, snapshot saved. On a test install, the command python -m app.cli demo-cost-control sets up the Lindenhof office building demo with the findings this case talks about. The old-snapshot finding appears once its last saved forecast is more than 35 days old.",
  estMinutes: 18,
  steps: [
    {
      id: "lines",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.lines.in.boq", label: "Priced bill of quantities" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.lines.out.lines", label: "Cost lines with plan" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.lines.title",
      titleDefault: "Make sure the cost lines exist",
      whatKey: "cases.run_the_monthly_cost_report.step.lines.what",
      whatDefault:
        "Open the 5D Cost Model for the project and generate the cost lines from the bill of quantities if the project has none yet. Each line carries its budget or estimate.",
      whyKey: "cases.run_the_monthly_cost_report.step.lines.why",
      whyDefault:
        "Cost control compares everything against the plan on the cost lines. Without them there is nothing to compare against.",
      moduleLabel: "5D Cost Model",
      moduleLabelKey: "nav.5d_cost_model",
      to: "/5d",
    },
    {
      id: "assign",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.assign.in.orders", label: "Contracts and purchase orders" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.assign.out.assigned", label: "Every amount on a cost line" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.assign.title",
      titleDefault: "Put unassigned money on cost lines",
      whatKey: "cases.run_the_monthly_cost_report.step.assign.what",
      whatDefault:
        "Open Cost control. If the finding Committed money is not on any cost line appears, open it and choose a cost line for each contract or order line, or send all lines of one contract or order to a single cost line.",
      whyKey: "cases.run_the_monthly_cost_report.step.assign.why",
      whyDefault:
        "Money that sits on no cost line is invisible in every line's forecast. A single unassigned order can hide an overrun the size of the order.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "findings",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.findings.in.assigned", label: "Every amount on a cost line" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.findings.out.watch", label: "Lines to act on" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.findings.title",
      titleDefault: "Read what is worth a look",
      whatKey: "cases.run_the_monthly_cost_report.step.findings.what",
      whatDefault:
        "Read the Worth a look list: lines forecast above plan, lines only partly awarded, more certified than awarded, pending changes and an old snapshot. Click a finding to open the line.",
      whyKey: "cases.run_the_monthly_cost_report.step.findings.why",
      whyDefault:
        "The findings are sorted with warnings first and by amount, so the five minutes you have go to the lines that matter.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "override",
      icon: "Pencil",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.override.in.knowledge", label: "New offers and site knowledge" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.override.out.forecast", label: "Forecast with a reason" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.override.title",
      titleDefault: "Enter your own forecast where you know better",
      whatKey: "cases.run_the_monthly_cost_report.step.override.what",
      whatDefault:
        "In the line drawer, press Enter your own forecast, type the expected final cost and why, and note the document it rests on, for example the date of a new offer.",
      whyKey: "cases.run_the_monthly_cost_report.step.override.why",
      whyDefault:
        "The automatic forecast only knows what is booked. When you know a package will cost more, your figure with its reason is the honest forecast, and the drawer keeps what the automatic one would say.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
    {
      id: "changes",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.changes.in.pending", label: "Submitted changes" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.changes.out.decided", label: "Decided changes" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.changes.title",
      titleDefault: "Decide the pending changes",
      whatKey: "cases.run_the_monthly_cost_report.step.changes.what",
      whatDefault:
        "Open Change Orders and approve or reject the changes that wait for a decision. Approved changes on a contract flow into the forecast of that contract's cost line.",
      whyKey: "cases.run_the_monthly_cost_report.step.changes.why",
      whyDefault:
        "Undecided changes are not in the forecast, so a long list of them means the forecast is too low. Deciding them is what makes the figure complete.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "snapshot",
      icon: "Download",
      inputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.snapshot.in.forecast", label: "Forecast with a reason" },
      ],
      outputs: [
        { labelKey: "cases.run_the_monthly_cost_report.step.snapshot.out.snapshot", label: "Saved monthly forecast" },
      ],
      titleKey: "cases.run_the_monthly_cost_report.step.snapshot.title",
      titleDefault: "Save the month's forecast",
      whatKey: "cases.run_the_monthly_cost_report.step.snapshot.what",
      whatDefault:
        "Back in Cost control, press Save forecast, choose the stage Forecast and add a short title and note for this month.",
      whyKey: "cases.run_the_monthly_cost_report.step.snapshot.why",
      whyDefault:
        "A saved forecast freezes the figures of the month. Without it, next month you can only say where you are, not how you got there.",
      moduleLabel: "Cost control",
      moduleLabelKey: "nav.cost_control",
      to: "/cost-control",
    },
  ],
};

export default playbook;
