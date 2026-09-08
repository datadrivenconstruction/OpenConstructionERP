// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Report a DIN 276 cost plan to the client" (DE).
//
// A German cost-consultant case: set the early cost frame, code every bill
// position to its DIN 276 Kostengruppe, let the cost spine build the plan as a
// tree of cost groups, check that nothing is left unclassified, read the
// variance group by group and issue the plan to the Bauherr in the structure
// their auditor reads. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "din-276-cost-plan-for-the-client",
  order: 1057,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  roles: ["quantity-surveyor", "estimator", "design-lead"],
  region: "DE",
  icon: "Layers",
  titleKey: "cases.din_276_cost_plan_for_the_client.title",
  titleDefault: "Report a DIN 276 cost plan to the client",
  descKey: "cases.din_276_cost_plan_for_the_client.desc",
  descDefault:
    "Build the cost plan on the DIN 276 cost groups, code every position to its Kostengruppe, read the variance group by group and issue it to the client in the structure their auditor expects.",
  longDescKey: "cases.din_276_cost_plan_for_the_client.longdesc",
  longDescDefault:
    "DIN 276 groups the cost of a building project from 100 to 800, with 300 carrying the Baukonstruktionen and 400 the Technische Anlagen. A plan built on those groups answers the question a flat spreadsheet total cannot: what is actually inside KG 400. The plan is refined as the design firms up, and every stage stays readable as a movement per group rather than as a new number nobody recognises.",
  estMinutes: 13,
  steps: [
    {
      id: "frame",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.frame.in.area", label: "Gross floor area" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.frame.in.quality", label: "Quality level and region" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.frame.out.frame", label: "Early cost frame" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.frame.out.split", label: "Elemental split" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.frame.title",
      titleDefault: "Set the early cost frame",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.frame.what",
      whatDefault:
        "Open the conceptual estimate and put down the Kostenrahmen, the first of the DIN 276 stages: gross floor area, quality level and region give a cost per square metre, and the total comes back split across the elemental categories rather than as one number.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.frame.why",
      whyDefault:
        "The client approves a figure long before there is a bill to price. Holding that early frame in the project is what lets the later, finer plan be read against something instead of arriving as a fresh number nobody recognises.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "classify",
      icon: "Tags",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.classify.in.positions", label: "Priced positions" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.classify.in.groups", label: "DIN 276 cost groups" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.classify.out.coded", label: "Coded positions" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.classify.out.kg", label: "Cost group on every line" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.classify.title",
      titleDefault: "Code every position to a Kostengruppe",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.classify.what",
      whatDefault:
        "Work down the bill and give each position its DIN 276 code in the classification column: 300 for the Baukonstruktionen, 400 for the Technische Anlagen, 500 for the Aussenanlagen, down to the third level where the work really sits, 351 Deckenkonstruktionen rather than 350 Decken or a bare 300.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.classify.why",
      whyDefault:
        "The cost group is what turns a flat list of positions into a plan that can be read by group. A position left uncoded is money that shows up under no heading at all when the client asks what a group contains.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "spine",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.spine.in.coded", label: "Coded bill" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.spine.in.standard", label: "Classification standard" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.spine.out.accounts", label: "Control account per group" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.spine.out.totals", label: "Rolled-up group totals" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.spine.title",
      titleDefault: "Build the plan by cost group",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.spine.what",
      whatDefault:
        "Generate the cost spine from the bill. Each coded position lands on a control account for its cost group, so the plan appears as a tree of Kostengruppen with the totals rolled up from the positions underneath and every line still reachable.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.spine.why",
      whyDefault:
        "This is the elemental plan itself, and it is generated from the coded positions rather than typed next to them. That is what stops a group total and the detail behind it from drifting apart as the design moves on.",
      moduleLabel: "5D Cost Model",
      moduleLabelKey: "nav.5d_cost_model",
      to: "/5d",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.validate.in.plan", label: "Cost plan" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.validate.in.rules", label: "Classification rules" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.validate.out.report", label: "Validation report" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.validate.out.gaps", label: "Uncoded lines flagged" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.validate.title",
      titleDefault: "Check that nothing is unclassified",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.validate.what",
      whatDefault:
        "Run validation across the bill and look for positions carrying no cost group at all and for codes that sit outside the group the work belongs to, then go back to the line and correct them.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.validate.why",
      whyDefault:
        "A single uncoded position makes a group total wrong while the grand total still adds up, so the error survives every check that looks only at the bottom line. Finding it now is cheaper than explaining it in a review.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "compare",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.compare.in.totals", label: "Group totals" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.compare.in.budget", label: "Recorded budget" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.compare.out.variance", label: "Variance per group" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.compare.out.drivers", label: "The groups that moved" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.compare.title",
      titleDefault: "Read the variance group by group",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.compare.what",
      whatDefault:
        "Go through the spine one cost group at a time and read the estimate against the budget recorded for it, so you can name which Kostengruppe carries the movement and how much of it, before you open the drill-down on the group that moved most.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.compare.why",
      whyDefault:
        "The budget question is almost never about the total, it is about which group moved and why. Having the answer per group turns a defensive meeting into a short one.",
      moduleLabel: "5D Cost Model",
      moduleLabelKey: "nav.5d_cost_model",
      to: "/5d",
    },
    {
      id: "basis",
      icon: "FileText",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.basis.in.plan", label: "Cost plan" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.basis.in.design", label: "Design state" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.basis.out.basis", label: "Basis of estimate" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.basis.out.scope", label: "Inclusions and exclusions" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.basis.title",
      titleDefault: "Write down what the plan assumes",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.basis.what",
      whatDefault:
        "Record the basis behind the numbers: which design state the plan was built on, what each cost group includes and excludes, and which figures are still an allowance rather than a priced quantity.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.basis.why",
      whyDefault:
        "A cost plan is only defensible with its assumptions attached. Written down while you build it, they answer a challenge months later; reconstructed after the challenge, the same sentences read as an excuse.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "report",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.report.in.plan", label: "Validated cost plan" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.report.in.basis", label: "Basis of estimate" },
      ],
      outputs: [
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.report.out.report", label: "Cost plan by group" },
        { labelKey: "cases.din_276_cost_plan_for_the_client.step.report.out.budget", label: "Client-ready budget" },
      ],
      titleKey: "cases.din_276_cost_plan_for_the_client.step.report.title",
      titleDefault: "Issue the plan to the client",
      whatKey: "cases.din_276_cost_plan_for_the_client.step.report.what",
      whatDefault:
        "Export the plan grouped by Kostengruppe, with the group totals, the variance against the budget and the basis alongside them, in the structure the client and their auditor already read. Name the stage it stands at, Kostenschaetzung at the Vorplanung, Kostenberechnung at the Entwurfsplanung, Kostenanschlag once the bids are in, because the client reads the tolerance off the stage.",
      whyKey: "cases.din_276_cost_plan_for_the_client.step.report.why",
      whyDefault:
        "A client who receives the plan in the structure they work in every day can approve it. One who has to re-sort a flat total into cost groups first will send it back, and the next meeting is about the format instead of the money.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
