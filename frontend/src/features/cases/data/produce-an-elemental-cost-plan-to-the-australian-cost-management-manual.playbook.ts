// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Produce an elemental cost plan to the Australian Cost Management
// Manual" (AU).
//
// Elemental cost planning on the element list the Australian Institute of
// Quantity Surveyors publishes in the Australian Cost Management Manual, the
// same list a completed job is analysed back into. Gross floor area and the
// functional unit are settled first, the element unit rates come from analysed
// projects, escalation runs to the middle of construction and the two
// contingencies stay separate. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "produce-an-elemental-cost-plan-to-the-australian-cost-management-manual",
  order: 1608,
  region: "AU",
  category: "estimating",
  companyTypes: ["cost-consultant", "developer-client", "project-manager"],
  roles: ["quantity-surveyor", "estimator", "finance-manager"],
  stage: "estimate",
  icon: "Layers",
  titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.title",
  titleDefault: "Produce an elemental cost plan to the Australian Cost Management Manual",
  descKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.desc",
  descDefault:
    "Fix the gross floor area and the functional unit, build the plan element by element on the AIQS element list, rate each element from analysed projects, escalate to the middle of construction, keep the design and construction contingencies apart and issue a plan the next one can be compared against.",
  longDescKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.longdesc",
  longDescDefault:
    "The Australian Cost Management Manual is the Australian Institute of Quantity Surveyors' rule set for cost planning and cost analysis, and its element list, substructure, columns, upper floors, staircases, roof, external walls, windows, external doors, internal walls, finishes and the rest, is the spine of both. That symmetry is the point: a plan built on those elements can be checked against analysed projects that were taken apart into the same elements, and when this job finishes it goes back into the same library for the next one. A cost plan that invents its own breakdown prices just as well and benchmarks against nothing, which is why the first question at every design review, why is this more than the last one, has no answer.",
  estMinutes: 18,
  steps: [
    {
      id: "basis",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.in.brief", label: "Project brief and area schedule" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.in.stage", label: "Design stage reached" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.out.gfa", label: "Gross floor area agreed" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.out.exclusions", label: "Inclusions and exclusions stated" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.title",
      titleDefault: "Fix the area, the functional unit and the exclusions",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.what",
      whatDefault:
        "Record the gross floor area the plan is built on, measured the way the manual measures it, the functional unit the client thinks in, beds, car spaces, classrooms or seats, and the list of what the plan excludes: land, authority charges, loose furniture, client contingency and the escalation beyond the horizon you have priced to.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.basis.why",
      whyDefault:
        "Two cost plans for the same building differ by a fifth when they measure area differently, and neither is wrong. Everything downstream is a rate per square metre, so an area defined loosely puts the same looseness on every element at once, and no later check finds it because every element is internally consistent.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "elements",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.in.gfa", label: "Gross floor area agreed" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.in.drawings", label: "Concept drawings" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.out.plan", label: "Cost plan by element" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.out.quantities", label: "Element quantities" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.title",
      titleDefault: "Build the plan element by element",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.what",
      whatDefault:
        "Work down the element list rather than around the drawing: substructure, columns, upper floors, staircases, roof, external walls, windows and external doors, internal walls and doors, the three finishes, fittings, services and external works. Each element carries its own quantity, its element unit quantity and its cost, so the number can be argued about one element at a time.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.elements.why",
      whyDefault:
        "An element list worked through in order is also a completeness check, because an element with nothing against it is visible and a missing trade in a lump sum is not. It is how a plan produced in a day still has a roof in it.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "rates",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.in.plan", label: "Cost plan by element" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.in.library", label: "Analysed projects" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.out.benchmark", label: "Elements benchmarked" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.out.outliers", label: "Outlying elements explained" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.title",
      titleDefault: "Rate each element against projects already analysed",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.what",
      whatDefault:
        "Compare each element unit rate with the same element on completed projects of the same type, and write down the reason for every element that sits outside the range. A facade rate double the library is either a design decision worth naming or an error, and the difference between those two is a sentence.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.rates.why",
      whyDefault:
        "Elemental analysis exists so that a plan can be challenged before it is approved rather than after it is exceeded. An element that nobody could explain at the design review is the same element that becomes the overrun, and it was visible months earlier.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "escalation",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.in.benchmark", label: "Elements benchmarked" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.in.programme", label: "Indicative programme" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.out.escalated", label: "Escalated to a stated date" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.out.base", label: "Base date on the record" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.title",
      titleDefault: "Escalate to the middle of construction, not to today",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.what",
      whatDefault:
        "Record the base date the rates are current at, then escalate them to the midpoint of the construction period the programme implies. State both dates on the plan, and state the index you escalated with.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.escalation.why",
      whyDefault:
        "A cost plan priced at today's rates for a building that starts in eighteen months is wrong on the day it is issued, and it is wrong in the direction nobody wants to discover later. Naming the base date is what lets a board read the number as an estimate of a future cost rather than as a price.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "contingency",
      icon: "Dice5",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.in.escalated", label: "Escalated to a stated date" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.in.risks", label: "Known design gaps" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.out.design", label: "Design contingency" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.out.construction", label: "Construction contingency" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.title",
      titleDefault: "Keep the two contingencies apart",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.what",
      whatDefault:
        "Carry a design contingency for the drawings that are not finished yet and a separate construction contingency for what the site will find, each as its own entry with what it is for. Reduce the design one as the design is resolved rather than letting it drift into the construction one.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.contingency.why",
      whyDefault:
        "One combined contingency answers no question. It cannot be released as the design firms up, because nobody can say which part was for the design, and it cannot be defended when the site finds rock, because it has already been spent on documentation gaps.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "issue",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.in.plan", label: "Complete cost plan" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.in.previous", label: "Previous cost plan" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.out.report", label: "Cost plan issued" },
        { labelKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.out.movement", label: "Movement since the last plan" },
      ],
      titleKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.title",
      titleDefault: "Issue it against the plan it replaces",
      whatKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.what",
      whatDefault:
        "Issue the plan with the element table, the rate per square metre, the rate per functional unit and a reconciliation against the previous plan that says which elements moved and why. Keep it as the version the next design review is measured from.",
      whyKey: "cases.produce_an_elemental_cost_plan_to_the_australian_cost_management_manual.step.issue.why",
      whyDefault:
        "A cost plan issued without a reconciliation is a new number rather than a report on the old one, and the conversation it produces is about whether to believe it. With the movement written out element by element, the same meeting is about four decisions that were already made.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
