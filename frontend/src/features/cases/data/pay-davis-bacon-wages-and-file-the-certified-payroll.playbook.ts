// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Pay Davis-Bacon wages and file the certified payroll" (US).
//
// A federally funded job carries a wage determination, and the determination is
// a pricing input before it is a payroll obligation. Price it, capture hours by
// classification, pay the base rate and the fringe, and file the weekly
// certified payroll with its statement of compliance. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "pay-davis-bacon-wages-and-file-the-certified-payroll",
  order: 1068,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["commercial-manager", "estimator", "accountant", "contract-administrator", "site-manager"],
  region: "US",
  icon: "Banknote",
  titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.title",
  titleDefault: "Pay Davis-Bacon wages and file the certified payroll",
  descKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.desc",
  descDefault:
    "Pull the wage determination into the job before it is priced, map every classification to work somebody will really do, capture hours by classification on site, pay the base rate and the fringe the determination sets, and file the weekly certified payroll with its signed statement of compliance.",
  longDescKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.longdesc",
  longDescDefault:
    "The Davis-Bacon Act and the related acts that extend it to federally assisted work put a floor under the wages on a construction contract, and the floor arrives as a wage determination attached to the solicitation: a list of classifications, each with a basic hourly rate and a fringe benefit rate. The obligation that follows is not only to pay it but to prove weekly that you paid it, on a certified payroll signed under penalty. Estimators meet the determination first and payroll clerks meet it last, and the jobs that go wrong are the ones where those two never compared notes: a bid priced on shop rates, and a payroll department discovering the difference in week three with the whole labour budget already spent.",
  estMinutes: 15,
  steps: [
    {
      id: "determination",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.in.solicitation", label: "Solicitation documents" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.in.determination", label: "Wage determination" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.out.rates", label: "Rate table loaded" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.out.gaps", label: "Classifications not listed" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.title",
      titleDefault: "Pull the wage determination in before you price anything",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.what",
      whatDefault:
        "Load the wage determination that came with the solicitation as a rate table: every classification, its basic hourly rate and its fringe rate, with the determination number and its date recorded beside them. Mark the classifications your crews will work that the determination does not list, because those need a conformance request to the contracting officer rather than a rate you picked yourself.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.determination.why",
      whyDefault:
        "The determination is the floor, it is county specific and trade specific, and it is not negotiable at any point after award. Reading it after the bid is submitted is how a job is won at a labour rate that does not exist, and a classification handled by inventing a rate is the one the audit finds, because a rate nobody conformed has no paper behind it.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.in.rates", label: "Rate table loaded" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.in.scope", label: "Scope and quantities" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.out.priced", label: "Priced bill" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.out.delta", label: "Cost above shop rates" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.title",
      titleDefault: "Price the work at the determination, not at your shop rate",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.what",
      whatDefault:
        "Build the crew rate behind each item from the determination's basic rate plus its fringe, then add the burdens the fringe does not cover, and price overtime at time and a half beyond forty hours in the week. Keep the difference between this and your ordinary shop rate visible as its own figure.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.price.why",
      whyDefault:
        "The fringe is part of the obligation and not an allowance, so a bill priced on base rates alone is short by the fringe on every hour. Keeping the difference from your ordinary rates visible is what lets the company decide whether it wants this kind of work at all, rather than finding out at the post mortem that federally funded jobs quietly lose money.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "hours",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.in.crew", label: "Crew on site" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.in.classifications", label: "Classification list" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.out.hours", label: "Hours by classification" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.out.split", label: "Split-classification days" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.title",
      titleDefault: "Capture hours by classification, not by name alone",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.what",
      whatDefault:
        "Book every hour worked on site against the classification the work belongs to and the day it happened. Where somebody worked two classifications in one day, record both with the hours split between them rather than putting the whole day under the higher one or the lower one.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.hours.why",
      whyDefault:
        "The certified payroll is a statement about hours by classification, so a timesheet that records only hours by person cannot produce it and has to be reconstructed from memory every Friday. Split days are where reconstruction goes wrong, and an underpayment found months later is repaid with interest plus whatever the agency withholds while it looks at the rest of the file.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "payroll",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.in.hours", label: "Hours by classification" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.in.fringe", label: "Fringe benefit plans" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.out.paid", label: "Weekly payroll run" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.out.deductions", label: "Deductions recorded" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.title",
      titleDefault: "Pay weekly, with the fringe in cash or into a real plan",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.what",
      whatDefault:
        "Run the payroll once a week, pay each worker the basic rate for the classification they worked, and settle the fringe either as cash on the paycheck or as a contribution to a bona fide plan, recorded either way. Pay apprentices at their program rate only where they are registered in an approved program and only within the ratio it allows, and list every deduction taken.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.payroll.why",
      whyDefault:
        "Weekly payment is part of the obligation, not a company habit, and an unregistered apprentice is simply a journeyman being underpaid. Deductions are the other common finding: anything beyond the ones permitted turns a correct gross wage into an incorrect net one, and it is the net figure the investigator reads first.",
      moduleLabel: "Payroll",
      moduleLabelKey: "nav.payroll",
      to: "/projects/:projectId/payroll",
    },
    {
      id: "certify",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.in.paid", label: "Weekly payroll run" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.in.determination", label: "Wage determination" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.out.payroll", label: "Certified payroll filed" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.out.statement", label: "Statement of compliance" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.title",
      titleDefault: "File the weekly certified payroll and sign the statement",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.what",
      whatDefault:
        "Produce the payroll for each week the crew worked on the site, showing every worker with their classification, hours by day, rate, gross, deductions and net, and file it with the contracting agency within the days the contract allows after the pay date. Attach the signed statement of compliance and keep the filed copy with the week it covers. The published form is optional; the information on it is not.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.certify.why",
      whyDefault:
        "This is the document that turns paying correctly into having proved it, and it is signed personally under penalty, which is why it should never be assembled by somebody who did not see the hours. A week filed late is a compliance finding on its own, before anybody has looked at whether the wages themselves were right, and the usual remedy is the agency holding the next payment.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "subs",
      icon: "Users",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.in.subcontracts", label: "Subcontract list" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.in.their_payrolls", label: "Subcontractor payrolls" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.out.gate", label: "Payment gated on the payroll" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.out.record", label: "Compliance record per sub" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.title",
      titleDefault: "Hold every subcontractor to the same obligation",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.what",
      whatDefault:
        "Write the wage clauses and the determination into every subcontract at every tier, then make the week's certified payroll a condition of that subcontractor being paid rather than something chased afterwards. Read what they send: a payroll with a classification that is not on the determination, or a rate below it, is a finding you can still fix.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.subs.why",
      whyDefault:
        "The prime contractor answers for the compliance of the whole chain, so a second tier subcontractor underpaying its crew is the prime's restitution to pay and the prime's payments the agency withholds. Gating the money on the paperwork is the only mechanism that reliably produces the paperwork, and it costs nothing while the money is still yours.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "clock",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.in.schedule", label: "Weekly filing schedule" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.in.retention", label: "Record retention rule" },
      ],
      outputs: [
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.out.watch", label: "Filing dates under watch" },
        { labelKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.out.file", label: "Records kept to the end date" },
      ],
      titleKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.title",
      titleDefault: "Put the weekly clock and the retention date under watch",
      whatKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.what",
      whatDefault:
        "Set the weekly filing date as a recurring deadline for as long as anyone works on the site, add the posting of the determination and the worker notice at the site entrance, and record the date the payroll records may finally be destroyed, counted from completion rather than from the last pay date.",
      whyKey: "cases.pay_davis_bacon_wages_and_file_the_certified_payroll.step.clock.why",
      whyDefault:
        "An investigation usually arrives long after the crews have gone, and it asks for the weeks nobody remembers. Records destroyed before the retention period ends leave the contractor unable to prove a payment it actually made, which in practice is the same position as not having made it.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
