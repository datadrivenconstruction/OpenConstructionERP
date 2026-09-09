// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set the encargos sociais and decide on desoneracao" (BR).
//
// Lei 12.546/2011 lets a construction company pay the social security
// contribution on turnover instead of on payroll, and the reference bases
// publish a table for each choice. The choice is therefore not an accounting
// detail: it changes the encargos percentage inside every composicao, and an
// orcamento holding both tables at once is wrong in a way that totals cleanly
// and cannot be spotted from the bottom line. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-the-encargos-sociais-and-decide-on-desoneracao",
  order: 1505,
  region: "BR",
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "commercial-manager", "accountant"],
  icon: "Users",
  titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.title",
  titleDefault: "Set the encargos sociais and decide on desoneracao",
  descKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.desc",
  descDefault:
    "Build the hourly cost of each function, choose the payroll regime for the whole orcamento, rebuild every composicao on the table that matches it, prove no composicao was left on the other one, and check the priced encargos against the folha you actually paid.",
  longDescKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.longdesc",
  longDescDefault:
    "Encargos sociais are the largest multiplier in a Brazilian estimate and the least often re-examined. They arrive as a percentage on the hourly wage, that percentage comes from a published table, and the table has two versions because Lei 12.546 of 2011 allows a construction company to pay the social security contribution on gross revenue rather than on its payroll. The two versions differ by roughly twenty points on the labour, which is enough to decide a tender. The failure mode is not choosing wrongly, it is choosing twice: an orcamento assembled over several weeks from composicoes taken from different exports ends up with some items priced on one table and some on the other, the total looks entirely plausible, and nothing in the arithmetic disagrees with itself.",
  estMinutes: 16,
  steps: [
    {
      id: "rates",
      icon: "Coins",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.in.agreement",
          label: "Collective agreement wage rates",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.in.functions",
          label: "Functions the work needs",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.out.hourly",
          label: "Hourly labour rates",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.out.base",
          label: "Base wage separated from the burden",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.title",
      titleDefault: "Build the hourly cost of each function",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.what",
      whatDefault:
        "Enter the wage each function is paid under the collective agreement of the region and the year, and keep the base wage and the encargos as two visible numbers rather than one loaded rate. Do it for the servente and the encarregado as well as for the pedreiro.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.rates.why",
      whyDefault:
        "A loaded rate cannot be re-based when the agreement is renewed or when the payroll regime changes, and both happen inside the life of one estimate. Split, the same change is one figure edited in one place, and the composicoes underneath follow it.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "option",
      icon: "Split",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.in.turnover",
          label: "Company turnover and payroll",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.in.tables",
          label: "Encargos tables for both regimes",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.out.choice",
          label: "Regime recorded for this orcamento",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.out.rate",
          label: "Encargos rate that follows from it",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.title",
      titleDefault: "Choose the payroll regime for the whole orcamento",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.what",
      whatDefault:
        "Decide whether this estimate is priced with the contribution on payroll or on turnover, check the edital in case it fixes the answer for you, and record the decision on the basis of estimate together with the encargos percentage it implies. One regime, one percentage, one orcamento.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.option.why",
      whyDefault:
        "Lei 12.546 of 2011 makes this a company decision with a real effect on the labour cost, and the reference bases publish a separate table for each answer. Recorded once at the top, it becomes a fact everybody working on the estimate can check against. Left implicit, it is rediscovered by whoever opens the file next, and they will assume whichever table they used last.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "apply",
      icon: "Combine",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.in.rate",
          label: "Encargos rate that follows from it",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.in.assemblies",
          label: "Composicoes holding labour",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.out.rebuilt",
          label: "Composicoes rebuilt on one table",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.out.delta",
          label: "Cost analysis of the change",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.title",
      titleDefault: "Rebuild every composicao on the chosen table",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.what",
      whatDefault:
        "Push the chosen encargos percentage through every composicao that carries labour, including the auxiliares underneath them, and read the change in the total. Do it as one pass rather than as a correction applied to the items somebody happens to open.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.apply.why",
      whyDefault:
        "The auxiliares are what get missed, because they are priced early and then behave like insumos. An argamassa still carrying the other table quietly prices the mason inside it under a regime the rest of the estimate has abandoned, and the item above it looks entirely normal.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.in.rebuilt",
          label: "Composicoes rebuilt on one table",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.in.choice",
          label: "Regime recorded for this orcamento",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.out.report",
          label: "Validation report on the regime",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.out.strays",
          label: "Positions left on the other table",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.title",
      titleDefault: "Prove nothing was left on the other table",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.what",
      whatDefault:
        "Run the orcamento against the recorded regime and list every position whose labour still carries the percentage of the other one. Treat an empty list as the deliverable of this step, not as a formality.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.check.why",
      whyDefault:
        "This is the one error in the whole estimate that produces no symptom. A mixed orcamento totals cleanly, prints cleanly and reads as internally consistent, and it is discovered either by an analyst comparing your labour cost with the published table or by nobody at all. A machine asking the question line by line is the only reliable reader.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "payroll",
      icon: "Users",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.in.priced",
          label: "Encargos rate that follows from it",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.in.paid",
          label: "Payroll actually paid",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.out.gap",
          label: "Gap between priced and paid",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.out.split",
          label: "Difference split by cause",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.title",
      titleDefault: "Compare the priced burden with the folha you paid",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.what",
      whatDefault:
        "Take a period that has closed and put the encargos you priced next to the encargos the payroll actually paid, split between the contributions, the paid absences and the provisions. Ask which part of the difference is a wrong percentage and which is a job that worked more overtime than it planned.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.payroll.why",
      whyDefault:
        "The published table describes an average company, and yours has a real absence rate, a real overtime pattern and a real turnover of labour. The gap is a fact about the company rather than about the job, and it is the same gap on every job until somebody measures it.",
      moduleLabel: "Payroll",
      moduleLabelKey: "nav.payroll",
      to: "/projects/:projectId/payroll",
    },
    {
      id: "postcalc",
      icon: "GitCompare",
      inputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.in.gap",
          label: "Gap between priced and paid",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.in.hours",
          label: "Hours booked on site",
        },
      ],
      outputs: [
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.out.corrected",
          label: "Corrected rate for the next orcamento",
        },
        {
          labelKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.out.trend",
          label: "Trend across jobs",
        },
      ],
      titleKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.title",
      titleDefault: "Feed the difference back into the next estimate",
      whatKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.what",
      whatDefault:
        "Close the loop in post-calculation: put the difference beside the hours the site actually booked, decide which part is a permanent correction to your own encargos figure, and change the figure rather than remembering to add a bit next time.",
      whyKey: "cases.set_the_encargos_sociais_and_decide_on_desoneracao.step.postcalc.why",
      whyDefault:
        "A correction that lives in an estimator's head is applied on the jobs they price and nowhere else, and it leaves with them. A corrected rate in the cost database is applied by everybody, and the next comparison measures the correction instead of rediscovering the original gap.",
      moduleLabel: "Post-calculation",
      moduleLabelKey: "postcalc.title",
      to: "/projects/:projectId/postcalc",
    },
  ],
};

export default playbook;
