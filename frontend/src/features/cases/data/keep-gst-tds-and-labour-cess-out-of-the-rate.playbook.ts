// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep GST, TDS and the labour cess out of the rate" (IN).
//
// This is the case the India pack was written around. Three deductions sit
// between the value certified on a running bill and the money that reaches the
// contractor's account, and none of them is a cost in the estimate: goods and
// services tax on the works contract, tax deducted at source on the payment,
// and the welfare cess under the Building and Other Construction Workers
// legislation. They change the invoice and the working capital, not the price
// of the work, and folding any of them into a rate is the most common way an
// Indian estimate ends up wrong.
//
// The demo projects that ship with the product are built this way and can be
// opened to see it: bill rates stated tax exclusive, then four markup lines
// above them, contractor's profit and overheads, contingencies, the labour
// cess, and the tax, in that order and on the right base.
//
// Rates and thresholds move by finance act and by notification, and the pack
// says so in its own review note. This case teaches the structure and treats
// every percentage as a figure to confirm against the current notification
// rather than as a fact to memorise.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-gst-tds-and-labour-cess-out-of-the-rate",
  order: 1183,
  region: "IN",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "developer-client"],
  roles: ["accountant", "commercial-manager", "finance-manager", "quantity-surveyor"],
  icon: "ReceiptText",
  titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.title",
  titleDefault: "Keep GST, TDS and the labour cess out of the rate",
  descKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.desc",
  descDefault:
    "Price the bill tax exclusive, carry profit, contingency, the labour cess and the tax as separate lines on the right base, work out what is deducted at source, and show what is certified next to what actually arrives.",
  longDescKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.longdesc",
  longDescDefault:
    "An Indian contractor is paid less than the value certified, on every bill, by design. Tax is added, then deducted at source; the welfare cess comes off; retention comes off on top of that. None of it is a surprise, and none of it belongs inside a unit rate, but the temptation to bury it there is strong because it makes one number look complete. It is a bad trade for three reasons. A rate with tax inside it cannot be compared with a schedule rate or with a competitor's rate, so the estimate stops being checkable. When the rate applicable to the contract type changes, or the contract turns out to be a different type than assumed, every line has to be rebuilt instead of one percentage edited. And the cash question, how much arrives and when, becomes unanswerable, because the deductions are no longer separable from the price. This case sets the structure up once so all three stay answerable.",
  estMinutes: 20,
  steps: [
    {
      id: "rates",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.in.bill",
          label: "The measured bill",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.in.rates",
          label: "Schedule or analysed rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.out.exclusive",
          label: "Rates stated tax exclusive",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.out.direct",
          label: "A direct cost you can compare",
        },
      ],
      titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.title",
      titleDefault: "Price the bill tax exclusive and say so on the bill",
      whatKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.what",
      whatDefault:
        "Enter every rate as the cost of the work with no tax and no cess inside it, and state on the bill header that the rates are exclusive. Where a supplier quotation arrives tax inclusive, strip the tax before the figure becomes a rate.",
      whyKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.rates.why",
      whyDefault:
        "Exclusive rates are the only ones that can be checked against a published schedule, which is stated the same way. They are also the only ones that survive a change of rate or of contract type without a rebuild, because the change then lands on one line instead of on every line.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "markups",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.in.direct",
          label: "Direct cost from the bill",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.in.type",
          label: "What kind of contract this is",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.out.lines",
          label: "Profit, contingency, cess and tax as lines",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.out.base",
          label: "Each one on the base it applies to",
        },
      ],
      titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.title",
      titleDefault: "Stack the markups in the order they actually apply",
      whatKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.what",
      whatDefault:
        "Add the contractor's profit and overheads, the contingency, the welfare cess and the tax as separate markup lines, each pointed at the base it is charged on. The cess is charged on the cost of construction; the tax is charged on the value including what sits below it. Set the tax rate from the contract type rather than from habit, and confirm it against the current notification: works contracts are not all rated alike, and government works, affordable housing and ordinary commercial work are treated differently.",
      whyKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.markups.why",
      whyDefault:
        "Order matters here in money terms, not only in presentation. A cess charged on a base that already includes tax, or a tax charged on a base that leaves out the profit, produces a total that is wrong in a way nobody notices until a department checks the arithmetic. Declaring the base per line makes the stack readable and re-runnable.",
      moduleLabel: "Markups",
      moduleLabelKey: "nav.markups",
      to: "/markups",
    },
    {
      id: "deduction",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.in.payee",
          label: "Who is being paid, and their status",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.in.gross",
          label: "The gross payment",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.out.withheld",
          label: "What is deducted at source",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.out.net",
          label: "What the payee receives",
        },
      ],
      titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.title",
      titleDefault: "Work out the deduction at source before you pay, not after",
      whatKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.what",
      whatDefault:
        "Set up the withholding scheme for the payments you make to contractors and subcontractors, with its rate bands and its threshold, and record the payee's status and registration details against them. The rate turns on what kind of entity the payee is, so it is a fact about them rather than a setting on the project.",
      whyKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.deduction.why",
      whyDefault:
        "Deducting at the wrong rate is the payer's problem, not the payee's. Getting it wrong upward means holding money that was not yours to hold and a subcontractor who stops turning up; getting it wrong downward means the shortfall is recovered from you later, with interest, long after the job is closed.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "bill",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.in.certified",
          label: "The certified value",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.in.deductions",
          label: "Cess, tax at source and retention",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.out.invoice",
          label: "An invoice that shows each line",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.out.expected",
          label: "The amount you expect to receive",
        },
      ],
      titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.title",
      titleDefault: "Raise the bill showing gross, deductions and net",
      whatKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.what",
      whatDefault:
        "Build the payment from the certified value: add the tax, show the cess and the deduction at source and the retention as their own lines, and state the net. Carry the service accounting code and the registration numbers the invoice has to bear.",
      whyKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.bill.why",
      whyDefault:
        "A bill that shows every line is a bill both sides can pass in one go. A bill that shows only a net figure is queried by the department's accounts branch, and each query costs a fortnight, which on a running account is the difference between paying your suppliers this month and next.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "cash",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.in.bills",
          label: "Bills raised and money received",
        },
      ],
      outputs: [
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.out.gap",
          label: "Certified value against cash in",
        },
        {
          labelKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.out.credits",
          label: "What is held and recoverable",
        },
      ],
      titleKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.title",
      titleDefault: "Report what was certified next to what arrived",
      whatKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.what",
      whatDefault:
        "Produce a statement per bill showing value certified, tax added, amounts deducted at source, cess, retention, and cash received, with the running total of what is held against you and recoverable later.",
      whyKey: "cases.keep_gst_tds_and_labour_cess_out_of_the_rate.step.cash.why",
      whyDefault:
        "The deductions are recoverable, which makes them easy to forget and expensive to forget. On a long job the money held at source and in retention is a large working capital number that belongs on the balance sheet rather than in somebody's head, and it is only visible if the lines were kept apart from the start.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
