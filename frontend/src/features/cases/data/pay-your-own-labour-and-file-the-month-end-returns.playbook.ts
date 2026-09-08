// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Pay your own labour and file the month end returns" (ZA).
//
// A South African contractor that employs its own people carries four
// statutory obligations that all fall due in the same fortnight: PAYE, UIF and
// SDL declared together on one monthly EMP201, VAT at 15 per cent under the
// Value-Added Tax Act 89 of 1991 on what it invoices, and the annual Return of
// Earnings under the Compensation for Occupational Injuries and Diseases Act
// 130 of 1993 that keeps the letter of good standing alive. The month end is
// one job, and it starts at the gate with the hours. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "pay-your-own-labour-and-file-the-month-end-returns",
  order: 1346,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor"],
  roles: ["accountant", "finance-manager", "site-manager"],
  region: "ZA",
  stage: "build",
  icon: "Coins",
  titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.title",
  titleDefault: "Pay your own labour and file the month end returns",
  descKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.desc",
  descDefault:
    "Take the hours off the site, pay them at the rates the agreement sets, put PAYE, UIF and SDL on one EMP201, keep the letter of good standing current and get the labour cost back onto the job it was spent on.",
  longDescKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.longdesc",
  longDescDefault:
    "Directly employed labour is the difference between a contractor and a broker, and it comes with a monthly cycle that does not move. PAYE, the unemployment insurance contribution and the skills development levy are declared together on one EMP201 return due by the seventh of the following month. VAT at 15 per cent is charged on what you invoice and reclaimed only against valid tax invoices. The annual Return of Earnings under the Compensation for Occupational Injuries and Diseases Act 130 of 1993 keeps the letter of good standing current, and that letter is asked for by almost every client and every tender. What ties them together is the timesheet: a month where nobody knows which job the hours were spent on produces correct returns and a useless cost report.",
  estMinutes: 12,
  steps: [
    {
      id: "hours",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.in.gate", label: "Gate and shift records" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.in.allocation", label: "Job allocation" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.out.timesheets", label: "Approved timesheets" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.out.overtime", label: "Overtime hours" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.title",
      titleDefault: "Capture the hours against the job, not against the week",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.what",
      whatDefault:
        "Collect the hours daily with the job, the activity and the person on each line, separate normal time from overtime and from work on a Sunday or a public holiday, and have the foreman approve the week before it goes anywhere near payroll.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.hours.why",
      whyDefault:
        "Hours captured only as a weekly total pay people correctly and tell you nothing. The same lines are the basis of the labour cost on the job, the substantiation of an expense and loss claim under clause 26.5 of the JBCC principal building agreement, and the earnings figure in the Return of Earnings. Collecting them once, at the right level of detail, is what stops three departments reconstructing the same month three different ways.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "rates",
      icon: "Tags",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.in.agreement", label: "Bargaining council agreement" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.in.grades", label: "Worker grades" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.out.rates", label: "Wage rates" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.out.oncosts", label: "On-cost percentages" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.title",
      titleDefault: "Set the wage rates and what sits on top of them",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.what",
      whatDefault:
        "Record the rate for each grade, together with the minimum the National Minimum Wage Act sets and any higher rate a bargaining council agreement imposes where one covers this work and this area, then add the on-costs: leave, the benefit fund contributions the agreement requires, the employer share of the unemployment insurance contribution and the skills development levy.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.rates.why",
      whyDefault:
        "The rate a person is paid and the rate a job is charged are different numbers, and estimators who confuse them lose the difference on every hour of the contract. Writing the on-costs down once, as percentages on the bare rate, is what lets an estimate and a payroll come from the same figures instead of from two habits.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "run",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.in.timesheets", label: "Approved timesheets" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.in.rates", label: "Wage rates" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.out.payslips", label: "Payslips" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.out.register", label: "Payroll register" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.title",
      titleDefault: "Run the payroll and produce the payslips",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.what",
      whatDefault:
        "Run the pay period from the approved hours, produce a payslip for every worker showing gross pay, each deduction separately and the net, and keep the payroll register that the returns will be built from.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.run.why",
      whyDefault:
        "A payslip is a legal entitlement, not a courtesy, and a deduction that appears on it without a name is the fastest route to a dispute with a bargaining council or a labour inspector. The register behind it is also what an audit reconciles the EMP201 declarations against at the end of the tax year, so it has to be right monthly rather than corrected annually.",
      moduleLabel: "Payroll",
      moduleLabelKey: "nav.payroll",
      to: "/projects/:projectId/payroll",
    },
    {
      id: "deductions",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.in.register", label: "Payroll register" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.in.thresholds", label: "Statutory thresholds" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.out.paye", label: "PAYE calculated" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.out.levies", label: "UIF and SDL" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.title",
      titleDefault: "Work out PAYE, UIF and the skills development levy",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.what",
      whatDefault:
        "Calculate PAYE on each employee's remuneration for the period, the unemployment insurance contribution at one per cent from the employee and one per cent from the employer up to the monthly earnings ceiling, and the skills development levy at one per cent of total payroll on the employer side, which small employers below the payroll threshold are exempt from.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.deductions.why",
      whyDefault:
        "The unemployment insurance contribution is capped and the skills development levy is not, so a site that grows its labour force finds the two moving apart, and a spreadsheet built once at the ceiling of a previous year quietly under-deducts for every month after the ceiling changes. Holding the rates and the ceiling where they can be updated in one place is the difference between a correction and a reassessment.",
      moduleLabel: "Tax Rates",
      moduleLabelKey: "nav.tax_rates",
      to: "/tax-rates",
    },
    {
      id: "emp201",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.in.totals", label: "Monthly totals" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.in.calendar", label: "Filing calendar" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.out.return", label: "EMP201 filed" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.out.payment", label: "Payment made" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.title",
      titleDefault: "File the EMP201 by the seventh and pay it",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.what",
      whatDefault:
        "Put the PAYE, unemployment insurance and skills development levy totals for the month onto the single EMP201 return, declare and pay it by the seventh of the following month, and keep the payment reference against the period it settles.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.emp201.why",
      whyDefault:
        "The seventh is a hard date and it falls in the same week as the payment certificate you are waiting to be paid on, which is why contractors miss it. A late EMP201 also breaks the tax compliance status that a public sector tender checks, so a missed month at one site can cost a bid at another.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "coida",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.in.earnings", label: "Annual earnings" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.in.subbies", label: "Subcontractor cover" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.out.roe", label: "Return of Earnings" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.out.letter", label: "Letter of good standing" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.title",
      titleDefault: "Keep the letter of good standing alive",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.what",
      whatDefault:
        "Submit the annual Return of Earnings under the Compensation for Occupational Injuries and Diseases Act 130 of 1993, pay the assessment and keep the letter of good standing on file with its expiry date. Collect the same letter from every subcontractor before it starts on site.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.coida.why",
      whyDefault:
        "Regulation 5(1)(j) of the Construction Regulations, 2014 makes it the client's duty to ensure, before any work commences, that every principal contractor is registered and in good standing with the compensation fund or with a licensed compensation insurer, so on a construction site the letter is checked at the gate and not only at tender. It also expires quietly, and an uncovered subcontractor is not somebody else's problem: when one of its people is hurt there is no fund behind the claim and it comes back up the chain to you.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "vat",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.in.certificate", label: "Payment certificate" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.in.invoices", label: "Supplier tax invoices" },
      ],
      outputs: [
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.out.invoice", label: "Tax invoice issued" },
        { labelKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.out.cost", label: "Labour cost on the job" },
      ],
      titleKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.title",
      titleDefault: "Invoice with VAT and put the cost back on the job",
      whatKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.what",
      whatDefault:
        "Raise the tax invoice on the certified amount with VAT at 15 per cent under the Value-Added Tax Act 89 of 1991, hold a valid tax invoice for every input you intend to claim, and post the month's labour cost to the jobs the timesheets allocated it to.",
      whyKey: "cases.pay_your_own_labour_and_file_the_month_end_returns.step.vat.why",
      whyDefault:
        "Input tax is claimable against a tax invoice and against nothing else, so a delivery note, a statement or a quotation in the file is a cost you carry the VAT on yourself. Posting the labour back to the job in the same run is what makes the cost report on that job a fact rather than an allocation somebody does at year end from memory.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
