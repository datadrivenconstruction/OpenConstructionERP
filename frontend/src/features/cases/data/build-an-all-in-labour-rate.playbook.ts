// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build an all-in labour rate".
//
// Turn a base wage into a true cost per productive hour by adding on-costs and
// dividing by productive time, then use it in the assemblies that build unit
// rates. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-an-all-in-labour-rate",
  order: 1004,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  icon: "Users",
  titleKey: "cases.build_an_all_in_labour_rate.title",
  titleDefault: "Build an all-in labour rate",
  descKey: "cases.build_an_all_in_labour_rate.desc",
  descDefault:
    "Turn a base wage into a true cost per productive hour by adding on-costs and dividing by the hours actually worked, then feed that rate into the assemblies that build your unit rates.",
  longDescKey: "cases.build_an_all_in_labour_rate.longdesc",
  longDescDefault:
    "The wage is never the cost of an hour of labour. Holidays, pension, insurances, travel and the time nobody is on the tools all sit on top. Pricing off the bare wage is the single most common way an estimate quietly loses its labour margin before the job even starts.",
  estMinutes: 10,
  steps: [
    {
      id: "base",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.base.in.trades", label: "Trades and grades" },
        { labelKey: "cases.build_an_all_in_labour_rate.step.base.in.agreement", label: "Wage agreement" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.base.out.wage", label: "Base wage per trade" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate.step.base.title",
      titleDefault: "Enter the base wage",
      whatKey: "cases.build_an_all_in_labour_rate.step.base.what",
      whatDefault:
        "Enter the base hourly wage for each trade and grade you employ, taken from the working rule agreement or your own payroll rather than a round guess.",
      whyKey: "cases.build_an_all_in_labour_rate.step.base.why",
      whyDefault:
        "Starting from the real agreed wage is what makes everything above it defensible. A rate built on an invented base is wrong no matter how careful the on-costs are.",
      moduleLabel: "Labour Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "oncosts",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.oncosts.in.wage", label: "Base wage" },
        { labelKey: "cases.build_an_all_in_labour_rate.step.oncosts.in.statutory", label: "Statutory on-costs" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.oncosts.out.burdened", label: "Burdened cost" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate.step.oncosts.title",
      titleDefault: "Add the on-costs",
      whatKey: "cases.build_an_all_in_labour_rate.step.oncosts.what",
      whatDefault:
        "Layer on the on-costs that turn a wage into an employment cost: holidays and public holidays, pension, employer taxes and insurances, sick pay, training levy, travel and allowances.",
      whyKey: "cases.build_an_all_in_labour_rate.step.oncosts.why",
      whyDefault:
        "These on-costs commonly add a third or more to the wage. Leaving any of them out understates the cost of every hour of labour in every rate you build on top.",
      moduleLabel: "Labour Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "productive",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.productive.in.burdened", label: "Burdened annual cost" },
        { labelKey: "cases.build_an_all_in_labour_rate.step.productive.in.hours", label: "Productive hours" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.productive.out.rate", label: "All-in hourly rate" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate.step.productive.title",
      titleDefault: "Divide by productive hours",
      whatKey: "cases.build_an_all_in_labour_rate.step.productive.what",
      whatDefault:
        "Divide the burdened annual cost by the hours actually spent on the tools, after taking out holidays, training, travel and downtime, to get the all-in rate per productive hour.",
      whyKey: "cases.build_an_all_in_labour_rate.step.productive.why",
      whyDefault:
        "You pay for the whole year but only sell the productive hours. Dividing by paid hours instead of productive hours is the subtle error that leaves margin on the table on every job.",
      moduleLabel: "Labour Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "use",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.use.in.rate", label: "All-in hourly rate" },
      ],
      outputs: [
        { labelKey: "cases.build_an_all_in_labour_rate.step.use.out.rates", label: "Labour in unit rates" },
      ],
      titleKey: "cases.build_an_all_in_labour_rate.step.use.title",
      titleDefault: "Use it in the assemblies",
      whatKey: "cases.build_an_all_in_labour_rate.step.use.what",
      whatDefault:
        "Feed the all-in rate into the assemblies that build your unit rates, so labour flows into every price from one maintained figure rather than a number retyped per line.",
      whyKey: "cases.build_an_all_in_labour_rate.step.use.why",
      whyDefault:
        "One rate in one place means a wage award or an insurance change updates every price at once. It also kills the inconsistency of different labour rates hiding across the same bill.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
  ],
};

export default playbook;
