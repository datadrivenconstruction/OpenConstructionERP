// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Budget development contributions for a territorial authority" (NZ).
//
// Part 8 of the Local Government Act 2002 lets a territorial authority require
// a development to contribute to the reserves, network infrastructure and
// community infrastructure whose demand it creates, but only under a
// development contributions policy the council has adopted with its long-term
// plan. The figure is therefore a policy output rather than a construction
// cost, it usually has to be paid before a consent or a connection is released,
// and it is one of the few numbers in a feasibility that can be objected to.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "budget-development-contributions-for-a-territorial-authority",
  order: 1480,
  region: "NZ",
  category: "estimating",
  companyTypes: ["developer-client", "cost-consultant", "project-manager"],
  roles: ["quantity-surveyor", "finance-manager", "project-manager", "estimator"],
  icon: "Landmark",
  titleKey: "cases.budget_development_contributions_for_a_territorial_authority.title",
  titleDefault: "Budget development contributions for a territorial authority",
  descKey: "cases.budget_development_contributions_for_a_territorial_authority.desc",
  descDefault:
    "Describe the development the way the council's policy measures it, put the assessed contribution into the feasibility before the land price is fixed, hold the risk that the policy moves, work the notice of assessment and any objection, place the figure in the cost plan where it will not be read as construction cost, and know when each payment falls due.",
  longDescKey: "cases.budget_development_contributions_for_a_territorial_authority.longdesc",
  longDescDefault:
    "A development contribution is not a tax and it is not a construction cost. Under Part 8 of the Local Government Act 2002 a territorial authority may require it to fund the reserves, network infrastructure and community infrastructure that new development creates demand for, and it may only do so under a development contributions policy adopted as part of its long-term plan. That has three consequences a developer feels directly. The figure comes from a policy document rather than from a rate card, so it is knowable in advance and it also changes when the policy is reviewed. It is usually payable before the council releases the consent, the certificate or the service connection, which puts it early in the cash flow rather than with the construction spend. And an assessment can be objected to, with objections heard by independent commissioners, so an assessment that misreads the development is a thing you can do something about, but only inside the window and only with the demand argued in the policy's own units.",
  estMinutes: 14,
  steps: [
    {
      id: "scope",
      icon: "Building2",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.in.scheme",
          label: "Development scheme",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.in.policy",
          label: "Council contributions policy",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.out.units",
          label: "Demand in the policy's own units",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.out.existing",
          label: "Credit for existing demand",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.title",
      titleDefault: "Describe the development the way the policy measures it",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.what",
      whatDefault:
        "Restate the scheme in the units the council's policy counts in, usually household equivalent units or an equivalent measure per activity, split by the activities the policy charges for: water, wastewater, stormwater, transport, reserves and community infrastructure. Record the demand the site already carries, because a redevelopment is charged on the increase rather than on the whole.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.scope.why",
      whyDefault:
        "The assessment is arithmetic once the units are agreed, so the units are the whole argument. A scheme described in the developer's language and assessed in the council's is a scheme whose figure nobody can reproduce, and the credit for existing demand is the single most commonly missed line, worth more than most of the details anybody spends time on.",
      moduleLabel: "Property Development",
      moduleLabelKey: "nav.property_dev",
      to: "/property-dev",
    },
    {
      id: "feasibility",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.in.units",
          label: "Demand in the policy's own units",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.in.rates",
          label: "Policy rates per unit",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.out.figure",
          label: "Contribution in the feasibility",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.out.land",
          label: "Effect on what the land is worth",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.title",
      titleDefault: "Put it in the feasibility before the land price is fixed",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.what",
      whatDefault:
        "Price the contribution into the early estimate as its own line, activity by activity, and read what it does to the residual land value. Do it at the point the scheme is still being sized, because the number moves with unit count and with the mix of activities rather than with the build cost.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.feasibility.why",
      whyDefault:
        "On a medium density scheme the contribution can be a substantial share of the total development cost and it lands before any revenue does. Discovered after the land is bought it comes straight off the margin, because the only remaining lever is the number of units, and that is the lever that changes the contribution too.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "risk",
      icon: "Dice5",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.in.figure",
          label: "Contribution in the feasibility",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.in.review",
          label: "When the policy is next reviewed",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.out.allowance",
          label: "Allowance held against a policy change",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.out.trigger",
          label: "What would release it",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.title",
      titleDefault: "Hold an allowance against the policy moving",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.what",
      whatDefault:
        "Hold the contribution risk as a named allowance rather than inside a general contingency: the policy is reviewed on a cycle with the long-term plan, the rates move with it, and a project consented after a review is assessed on the rates in force at the time. Record what would release the allowance, which is usually the consent being lodged and assessed.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.risk.why",
      whyDefault:
        "A long-dated scheme can cross a policy review between feasibility and consent, and the movement is a policy decision rather than market drift, so no cost index will predict it. Held as a named allowance it can be released deliberately when the assessment arrives; buried in contingency it is spent on something else long before the invoice comes.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "assessment",
      icon: "Gavel",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.in.notice",
          label: "Notice of assessment",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.in.own",
          label: "Your own calculation",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.out.position",
          label: "Accept, object or agree",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.out.filed",
          label: "Correspondence on the record",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.title",
      titleDefault: "Read the assessment against your own calculation",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.what",
      whatDefault:
        "When the notice of assessment arrives, read it line by line against the calculation you made in the feasibility and settle a position: accept it, object to it inside the window the Act gives, or open a development agreement in which the works or the payment are agreed with the council instead. Keep the notice, the working and the reply together on the record.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.assessment.why",
      whyDefault:
        "An objection is heard by independent development contribution commissioners rather than by the council that made the assessment, which makes it a genuine route and not a complaint. It is also a route with a deadline, and it is argued on the grounds the Act allows, such as the assessment misdescribing the development or the policy having been applied incorrectly, so the work done at the scoping step is the evidence for it.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "place",
      icon: "ListTree",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.in.position",
          label: "Accept, object or agree",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.in.plan",
          label: "Cost plan structure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.out.line",
          label: "Contribution on its own line",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.out.compare",
          label: "Comparable across schemes",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.title",
      titleDefault: "Put it where nobody will read it as a build cost",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.what",
      whatDefault:
        "Place the contribution in the cost plan as its own line under development costs rather than inside the infrastructure or external works packages, split by the activities the policy charges for. Keep it comparable across schemes so the cost per unit can be read from one project to the next.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.place.why",
      whyDefault:
        "A contribution folded into external works distorts every rate benchmark the business keeps, and it does so silently, because the total still looks right. It also hides the one comparison that is genuinely useful to a developer, which is what different councils charge for the same building, and that comparison is a location decision rather than a design one.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "cash",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.in.line",
          label: "Contribution on its own line",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.in.trigger",
          label: "Event that makes it payable",
        },
      ],
      outputs: [
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.out.due",
          label: "When each payment falls due",
        },
        {
          labelKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.out.hold",
          label: "What the council can withhold",
        },
      ],
      titleKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.title",
      titleDefault: "Know what the council can withhold until it is paid",
      whatKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.what",
      whatDefault:
        "Report the contributions across the portfolio with the event that makes each one payable, which under the policy may be the resource consent, the building consent, the service connection or the certificate that lets a subdivision proceed, and with what the council may withhold until it is paid.",
      whyKey: "cases.budget_development_contributions_for_a_territorial_authority.step.cash.why",
      whyDefault:
        "This is the step that turns a known cost into a programme risk. A council entitled to withhold a code compliance certificate or a water connection until the contribution is paid can stop a settlement date, and the money is usually wanted at exactly the point in a development when there is least of it. Read a quarter ahead it is a drawdown. Read on the day it is a delay.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
