// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Hold the design estimate to the approved budget" (CN).
//
// State-funded work in China runs an approval chain of estimates, each one
// bound by the last: an investment estimate at feasibility, a design estimate
// that may not exceed it, and a construction-drawing budget that may not exceed
// that. Cost-capped design is the practice of handing the design team a rate
// per square metre at the start and holding them to it, rather than pricing
// whatever comes back and negotiating afterwards.
//
// The product's part in that is the measurement, not the enforcement. It gives
// you a conceptual number with a rate per square metre behind it, a written
// basis so the next stage is priced on the same assumptions, and a line-by-line
// comparison between the bill as it stands and the version that was approved.
// It does not declare a ceiling and it does not return a verdict; holding the
// cap is a decision somebody makes, and the case says so rather than implying
// a control that is not there. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "hold-the-design-estimate-to-the-approved-budget",
  order: 1129,
  region: "CN",
  category: "estimating",
  stage: "design",
  companyTypes: ["developer-client", "cost-consultant", "designer", "project-manager"],
  roles: ["estimator", "quantity-surveyor", "design-lead", "project-manager"],
  icon: "Gauge",
  titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.title",
  titleDefault: "Hold the design estimate to the approved budget",
  descKey: "cases.hold_the_design_estimate_to_the_approved_budget.desc",
  descDefault:
    "Set an investment estimate with a rate per square metre behind it, write down what it assumes, price the design estimate against the same scope, and compare it with the approved version at every gate.",
  longDescKey: "cases.hold_the_design_estimate_to_the_approved_budget.longdesc",
  longDescDefault:
    "The approval chain on public work is a sequence of estimates in which each stage is bound by the one before it, and the failure mode is always the same: the design develops for eight months without anybody pricing it, and the design estimate arrives twenty percent over a figure that was approved on assumptions nobody wrote down. By then the argument is about whether the scope changed, and there is no document that could settle it. This case puts two things in place early. The first is a stated basis, so the next stage is priced against the same assumptions rather than against a remembered version of them. The second is a comparison run at every gate rather than at the end, while a section that has moved is still small enough to be a design decision instead of a re-approval. The comparison tells you where the money went; deciding whether that is acceptable is yours, and it is not a decision worth automating.",
  estMinutes: 20,
  steps: [
    {
      id: "investment",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.in.brief", label: "Building type and quality level" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.in.area", label: "Gross floor area" },
      ],
      outputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.out.total", label: "Investment estimate" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.out.rate", label: "Rate per square metre" },
      ],
      titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.title",
      titleDefault: "Set the investment estimate as a rate, not just a total",
      whatKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.what",
      whatDefault:
        "Build the feasibility number from the building type, the gross floor area and the quality level, and read off the rate per square metre it implies as well as the total.",
      whyKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.investment.why",
      whyDefault:
        "A total is a fact about a building nobody has designed yet, and a design team cannot work to it. A rate per square metre is a constraint they can test every decision against, which is the whole mechanism of cost-capped design, and it stays comparable when the area moves.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "basis",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.in.number", label: "The approved number" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.in.assumptions", label: "What it assumed" },
      ],
      outputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.out.basis", label: "Written basis of estimate" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.out.exclusions", label: "Exclusions on the record" },
      ],
      titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.title",
      titleDefault: "Write down what the approved number assumes",
      whatKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.what",
      whatDefault:
        "Record the basis: the scope covered, the standard of finish, the price level and date, what is excluded, and where the rates came from. Keep it with the estimate rather than in the covering email.",
      whyKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.basis.why",
      whyDefault:
        "Every argument at the next gate is about whether the design changed or the estimate was wrong, and only the basis can answer it. Without one, a stage that comes in over is always explained as a scope change, and there is nothing on either side that can contradict that.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "design",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.in.drawings", label: "Design as it stands" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.in.basis", label: "The stated basis" },
      ],
      outputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.out.priced", label: "Design estimate priced by item" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.out.version", label: "Named version at the gate" },
      ],
      titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.title",
      titleDefault: "Price the design estimate and name the version",
      whatKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.what",
      whatDefault:
        "Price the design item by item against the same scope the basis describes, and save a named version of the bill at the moment it goes for approval so the approved state can be retrieved exactly.",
      whyKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.design.why",
      whyDefault:
        "The version that was approved is the only meaningful thing to measure later movements against, and it is unrecoverable a month afterwards unless somebody named it at the time. Naming it costs a moment and turns the next comparison from an argument into a report.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "compare",
      icon: "GitCompareArrows",
      inputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.in.current", label: "The bill as it stands now" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.in.approved", label: "The approved version" },
      ],
      outputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.out.moved", label: "Which sections moved" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.out.rate", label: "The rate per square metre now" },
      ],
      titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.title",
      titleDefault: "Compare against the approved version at every gate",
      whatKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.what",
      whatDefault:
        "Set the current bill against the version approved at the previous stage and read the difference by section: which items were added, which quantities grew, which rates moved. Work the rate per square metre out again on the current area and put it beside the one you started with.",
      whyKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.compare.why",
      whyDefault:
        "Nothing here declares a limit or returns a verdict, and that is the honest shape of it: the product shows you where the money went and the cap is held by people. What makes that workable is running the comparison at each gate rather than once at the end, because a section that has grown by six percent is a design conversation, while a design estimate more than ten percent over the approved investment estimate is, under the government investment regulation, a report to the investment authority that can send the feasibility study back.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.in.comparison", label: "The gate comparison" },
      ],
      outputs: [
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.out.stage", label: "Stage report for approval" },
        { labelKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.out.actions", label: "Where savings have to come from" },
      ],
      titleKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.title",
      titleDefault: "Report the position with the movement explained",
      whatKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.what",
      whatDefault:
        "Report the stage total, the rate per square metre, the difference against the approved figure and the sections it came from, with a line on each saying whether it was a scope change, a design decision or a price movement.",
      whyKey: "cases.hold_the_design_estimate_to_the_approved_budget.step.report.why",
      whyDefault:
        "An approving body asked to consider a number will ask where it came from, and a report that answers that in advance gets a decision instead of a deferral. The approved design estimate is the figure the project is controlled to from then on, and raising it means going back to the body that approved it with a funding source, so naming the cause per section is also what tells the design team where the savings have to come from, which is the only useful output of the exercise.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
