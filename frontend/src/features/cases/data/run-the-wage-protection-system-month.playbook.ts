// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run the Wage Protection System month" (SA).
//
// The Wage Protection System is run by the Ministry of Human Resources and
// Social Development, and wage files are submitted through the Mudad
// platform. It compares what an establishment says it owes its workers with
// what the banks say it actually transferred, and scores the difference. A
// contractor who falls out of compliance does not get a letter, he gets the
// labour services he depends on suspended, which stops work permits and
// transfers and therefore stops the site. This case runs one month end to
// end, from the hours the crews worked to the evidence the file was accepted.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-the-wage-protection-system-month",
  order: 1195,
  region: "SA",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor"],
  roles: ["accountant", "finance-manager", "site-manager"],
  stage: "build",
  icon: "Users",
  titleKey: "cases.run_the_wage_protection_system_month.title",
  titleDefault: "Run the Wage Protection System month",
  descKey: "cases.run_the_wage_protection_system_month.desc",
  descDefault:
    "Capture the hours the crews really worked, reconcile the crew list against the establishment record, pay every worker into an account in their own name, submit the wage file and read the compliance back, and hold your labour subcontractors to the same obligation.",
  longDescKey: "cases.run_the_wage_protection_system_month.longdesc",
  longDescDefault:
    "The Wage Protection System is an obligation with teeth. Every private sector establishment in the Kingdom pays wages through a bank licensed here, into an account in the worker's own name, and submits a monthly wage file through the Mudad platform, where the Ministry of Human Resources and Social Development compares what was declared against what the banks report. Falling out of compliance is not a fine that arrives later, it is the suspension of the labour services an employer runs on, so work permits and transfers stop and the shortage lands on site within weeks. On a construction job the exposure is concentrated in exactly the places that are hardest to keep tidy: crews that change size week to week, a workforce whose identity documents expire on Hijri dates, and labour supply subcontractors whose compliance failure becomes your labour shortage.",
  estMinutes: 15,
  steps: [
    {
      id: "hours",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.hours.in.attendance", label: "Site attendance" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.hours.in.overtime", label: "Overtime worked" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.hours.out.hours", label: "Hours per worker" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.hours.out.allocation", label: "Hours allocated to the works" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.hours.title",
      titleDefault: "Capture the hours the crews actually worked",
      whatKey: "cases.run_the_wage_protection_system_month.step.hours.what",
      whatDefault:
        "Record time by worker for the month, with the overtime separated from the normal day and the reduced Ramadan hours shown as what they are, and allocate the hours to the work they were spent on so the payroll and the cost report are built from the same record.",
      whyKey: "cases.run_the_wage_protection_system_month.step.hours.why",
      whyDefault:
        "The wage file has to agree with the employment contract as well as with the bank, and overtime is where the two drift apart. Time captured on site, by the person who saw the crew, is also the only defence when a worker raises a wage complaint, because the labour office will ask what was worked and paid rather than what was budgeted.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "roster",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.roster.in.crew", label: "Crew list on site" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.roster.in.records", label: "Establishment records" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.roster.out.matched", label: "Crew matched to the register" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.roster.out.exceptions", label: "Exceptions to resolve" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.roster.title",
      titleDefault: "Reconcile who is on site against who you employ",
      whatKey: "cases.run_the_wage_protection_system_month.step.roster.what",
      whatDefault:
        "Match the crew on site to the establishment's own records worker by worker: the identity and residence permit details, the social insurance registration, and the bank account each wage is paid into. List the exceptions rather than paying around them, a worker on site who is registered to another establishment being the one to escalate the same day.",
      whyKey: "cases.run_the_wage_protection_system_month.step.roster.why",
      whyDefault:
        "The wage file is submitted per establishment, so a mismatch between the site and the register is not a clerical difference, it is a file that will not reconcile. It is also where two separate obligations meet: a worker whose permit has lapsed cannot lawfully work, and paying him correctly through the system does not cure that.",
      moduleLabel: "Resources & Crew",
      moduleLabelKey: "nav.resources",
      to: "/projects/:projectId/resources",
    },
    {
      id: "payroll",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.payroll.in.hours", label: "Hours per worker" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.payroll.in.contracts", label: "Employment contracts" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.payroll.out.run", label: "Payroll run" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.payroll.out.file", label: "Wage file prepared" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.payroll.title",
      titleDefault: "Run the payroll and build the wage file from it",
      whatKey: "cases.run_the_wage_protection_system_month.step.payroll.what",
      whatDefault:
        "Run the payroll against the contracts, with basic wage, housing and transport allowances and any deduction shown separately, and produce the wage file from the same run rather than typing it again. Wages are due monthly under the Labour Law, so the run and the file belong to the same cycle.",
      whyKey: "cases.run_the_wage_protection_system_month.step.payroll.why",
      whyDefault:
        "A wage file keyed separately from the payroll is a file that will disagree with the payroll, usually by one leaver and one joiner. The system compares declaration against transfer, so any difference is visible to the ministry before it is visible to you, and the correction costs a month of compliance rather than an afternoon.",
      moduleLabel: "Payroll",
      moduleLabelKey: "nav.payroll",
      to: "/projects/:projectId/payroll",
    },
    {
      id: "pay",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.pay.in.file", label: "Wage file" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.pay.in.accounts", label: "Worker bank accounts" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.pay.out.paid", label: "Wages transferred" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.pay.out.confirmations", label: "Bank confirmations" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.pay.title",
      titleDefault: "Pay through the bank, into the worker's own account",
      whatKey: "cases.run_the_wage_protection_system_month.step.pay.what",
      whatDefault:
        "Transfer the wages through a bank licensed in the Kingdom into an account in each worker's own name, checking the account number is a well formed Saudi IBAN of twenty four characters before the run rather than after a rejected transfer, and keep the bank confirmations against the payroll.",
      whyKey: "cases.run_the_wage_protection_system_month.step.pay.why",
      whyDefault:
        "The whole point of the system is that a wage reaches the worker and can be proven to have reached him. Cash on site, payment into somebody else's account or a transfer to a labour supplier who will pass it on are all outside it, however genuinely the money was intended. A single malformed account number silently drops one worker out of the month, and one unpaid worker is what a compliance percentage is measured in.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "submit",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.submit.in.file", label: "Wage file submitted" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.submit.in.confirmations", label: "Bank confirmations" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.submit.out.status", label: "Compliance status read" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.submit.out.gaps", label: "Unmatched workers listed" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.submit.title",
      titleDefault: "Read the compliance back before the month closes",
      whatKey: "cases.run_the_wage_protection_system_month.step.submit.what",
      whatDefault:
        "After the file is submitted, read the result rather than assuming it: how many workers matched, which did not, and what the establishment's compliance status is now. Work the unmatched list the same week, because the fix is nearly always a wrong account number, a leaver still on the file or a wage paid outside the transfer.",
      whyKey: "cases.run_the_wage_protection_system_month.step.submit.why",
      whyDefault:
        "Compliance is scored monthly and the consequence is the suspension of labour services, so a bad month is felt as a hiring freeze one or two months later, by which time the cause is hard to reconstruct. Reading the result on submission turns a compliance problem into a data problem, which is the only form of it anybody can fix quickly.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
    {
      id: "subs",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.subs.in.subs", label: "Labour subcontractors" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.subs.in.terms", label: "Subcontract terms" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.subs.out.declarations", label: "Compliance declarations held" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.subs.out.flag", label: "At risk suppliers flagged" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.subs.title",
      titleDefault: "Hold the labour subcontractors to the same obligation",
      whatKey: "cases.run_the_wage_protection_system_month.step.subs.what",
      whatDefault:
        "For each subcontractor supplying labour, record their establishment details and require evidence of their own wage compliance as a condition of each payment, and flag the ones whose status has slipped before you plan next month's crews around them.",
      whyKey: "cases.run_the_wage_protection_system_month.step.subs.why",
      whyDefault:
        "Their compliance failure arrives as your labour shortage. A subcontractor whose services are suspended cannot renew permits or move men, so the crew he promised for next month simply is not there, and it is far too late to price an alternative. Asking for the evidence monthly is unpopular and much cheaper than the alternative.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "evidence",
      icon: "Paperclip",
      inputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.evidence.in.month", label: "The month's records" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.evidence.in.status", label: "Compliance status" },
      ],
      outputs: [
        { labelKey: "cases.run_the_wage_protection_system_month.step.evidence.out.pack", label: "Month filed as one pack" },
        { labelKey: "cases.run_the_wage_protection_system_month.step.evidence.out.trail", label: "Trail from hours to transfer" },
      ],
      titleKey: "cases.run_the_wage_protection_system_month.step.evidence.title",
      titleDefault: "File the month so the chain can be walked",
      whatKey: "cases.run_the_wage_protection_system_month.step.evidence.what",
      whatDefault:
        "Keep the month as one pack: the time records, the payroll run, the wage file as submitted, the bank confirmations and the compliance result, so any single worker can be traced from the hours he worked to the money that reached his account.",
      whyKey: "cases.run_the_wage_protection_system_month.step.evidence.why",
      whyDefault:
        "Wage claims are made by individuals about single months, sometimes long after the man has left the country. A pack that lets one name be followed from attendance to transfer answers the claim in an afternoon. Records scattered across a timesheet folder, an accounts system and a bank portal turn the same question into a week of work with an uncertain ending.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
