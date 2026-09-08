// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build an all-in labour rate with the Canadian burden" (CA).
//
// The country child of the universal all-in-rate case. The objection is "I know
// my rate, I have used it for fifteen years", and the case does not say the rate
// is wrong. It says the rate is a stack of separately sourced contributions,
// that the stack is provincial rather than national, and that when it moves the
// estimator should be able to name which line moved and when.
//
// No contribution percentage appears anywhere in this file on purpose: the
// components are named, and the rates belong to the bodies that administer them
// and to the user's own basis of estimate. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-an-all-in-labour-rate-with-the-canadian-burden",
  order: 1104,
  region: "CA",
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor", "accountant"],
  icon: "Coins",
  titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.title",
  titleDefault: "Build an all-in labour rate with the Canadian burden",
  descKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.desc",
  descDefault:
    "Take the hourly rate you have used for years apart into the base wage and the named contributions sitting on top of it, keep one template per province because the burden is provincial, and record where every rate came from and the date it took effect.",
  longDescKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.longdesc",
  longDescDefault:
    "An all-in rate is not one number. It is a base wage carrying a stack of separately sourced contributions, most of which moved at some point without telling anybody, and the reason to build it as a stack is not that your number is wrong. It is that when the number changes you should be able to say which line moved and when, and that is a property of how the rate was assembled rather than of how carefully it was checked. The stack is also provincial rather than national: the pension contribution, the employment insurance multiple paid by the employer, vacation and statutory holiday pay, the workers compensation rate for the classification unit the trade falls in and the benefit contributions are administered by different bodies at different rates in different provinces. Quebec is not a fourth province in this, it is a different stack, with its own pension plan and a separate parental insurance premium standing beside a reduced employment insurance rate.",
  estMinutes: 20,
  steps: [
    {
      id: "base",
      icon: "Users",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.in.trade", label: "Trade and province" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.in.wage", label: "Base hourly wage" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.out.template", label: "One rate template per province" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.out.wage", label: "Base wage on record" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.title",
      titleDefault: "Start from the base wage, one province at a time",
      whatKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.what",
      whatDefault:
        "Create a rate template for the trade, enter the base hourly wage, and name the template for the province it belongs to, because the same trade carries a different burden in every province it works in.",
      whyKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.base.why",
      whyDefault:
        "One template covering two provinces has to average something, and an averaged burden is precisely the thing you cannot explain when a bid gets queried. A template per province costs a few minutes to set up and is the only version that survives being asked where the number came from.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "stack",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.in.rates", label: "Contribution rates for the province" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.in.unit", label: "Classification unit for the trade" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.out.stack", label: "Named burden stack" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.out.allin", label: "All-in rate derived from its parts" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.title",
      titleDefault: "Add each contribution as its own named line",
      whatKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.what",
      whatDefault:
        "Build the stack on the wage as separate lines: pension contribution, employment insurance at the employer multiple, vacation pay, statutory holiday pay, workers compensation at the classification unit rate for this trade, the employer health or payroll tax where the province levies one, and the benefit, pension and training contributions the collective agreement sets. Keep percentages as percentages and fixed amounts as amounts rather than blending them into one uplift.",
      whyKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.stack.why",
      whyDefault:
        "A single burden percentage hides the fact that its parts move independently and on different dates. Workers compensation in particular is rated by classification unit, so it changes when the work the crew does changes, not when the calendar turns, and that is the movement a blended uplift will never show you.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "basis",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.in.stack", label: "The burden stack as built" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.in.sources", label: "Source and effective date per line" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.out.basis", label: "Sourced and dated rate basis" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.out.handover", label: "A rate somebody else can maintain" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.title",
      titleDefault: "Write down where each rate came from and when it applied",
      whatKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.what",
      whatDefault:
        "Record in the basis of estimate the source of every contribution in the stack, the body that administers it, and the date that rate took effect, so the whole stack can be re-checked against its authorities in an afternoon.",
      whyKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.basis.why",
      whyDefault:
        "When the rate moves you will be asked which line moved, and the answer has to be a citation rather than a memory. It is also what turns a rate into something a colleague can maintain after you, which is the whole difference between a company rate and a personal one.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "crews",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.in.template", label: "The rate template" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.in.crews", label: "Crew compositions and assemblies" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.out.priced", label: "Assemblies priced off one rate" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.out.propagate", label: "Updates that propagate" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.title",
      titleDefault: "Point the assemblies at the rate, not at a typed number",
      whatKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.what",
      whatDefault:
        "Build the crew compositions and assemblies against the rate template rather than against a figure typed into each one, so that a change to any contribution reprices everything that depends on it.",
      whyKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.crews.why",
      whyDefault:
        "A rate typed into forty assemblies is forty rates, and they will not all be updated on the day a premium changes. Pointing at the template is what makes the next update a single edit instead of a search that finds most of them.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "check",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.in.built", label: "The built all-in rate" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.in.actual", label: "Recorded hours and paid cost" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.out.variance", label: "Variance by component" },
        { labelKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.out.fix", label: "A corrected line, not a corrected total" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.title",
      titleDefault: "Test the built rate against what the job actually cost",
      whatKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.what",
      whatDefault:
        "Report the built rate against recorded hours and paid cost on a job that has finished, component by component, and correct the line that is wrong rather than adjusting the total until it matches.",
      whyKey: "cases.build_an_all_in_labour_rate_with_the_canadian_burden.step.check.why",
      whyDefault:
        "A stack is only worth building if it gets corrected, and correcting a total teaches nobody anything. Fifteen years of experience tells you what the number should be; the stack tells you which part of it drifted, and only one of those two can be handed to the next estimator.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
