// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Charge GST on a progress payment at the right time" (NZ).
//
// The Goods and Services Tax Act 1985 as it lands on construction work paid in
// instalments. The rate is the easy half. The hard half is the time of supply,
// because for work paid periodically the liability can arise on the date a
// payment becomes DUE, which is not the date it arrives, and a contractor who
// accounts on the invoice basis can therefore owe the tax on money it has not
// been paid. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "charge-gst-on-a-progress-payment-at-the-right-time",
  order: 1450,
  region: "NZ",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "commercial-manager", "contract-administrator"],
  icon: "Receipt",
  titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.title",
  titleDefault: "Charge GST on a progress payment at the right time",
  descKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.desc",
  descDefault:
    "Set the rate once, settle whether the contract price is inclusive or exclusive, work out the time of supply for work paid in instalments, put the taxable supply information on every claim, file for the right taxable period and keep the records the Act asks you to keep.",
  longDescKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.longdesc",
  longDescDefault:
    "GST under the Goods and Services Tax Act 1985 is a single rate on almost everything, which makes it feel simple and makes the one hard question invisible. That question is when the supply happens. The general rule in the Act is the earlier of an invoice being issued or a payment being received, but construction work paid in instalments or periodically has its own rule, and under it the time of supply is the earliest of the date a payment becomes due, the date it is received and the date an invoice is issued for it. On the invoice basis that means the tax can be payable in a period when the money has not arrived, which is a cash flow event rather than an accounting one and it is worst on the jobs that are going worst. Retentions were pulled out of that pattern by a later amendment, so retention money is accounted for when it becomes payable rather than when it was deducted, and since 1 April 2023 what a supplier has to provide is taxable supply information rather than a document called a tax invoice.",
  estMinutes: 13,
  steps: [
    {
      id: "rate",
      icon: "Coins",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.in.registration",
          label: "GST registration",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.in.jurisdiction",
          label: "Where the work is supplied",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.out.rate",
          label: "Rate set once, used everywhere",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.out.effective",
          label: "Effective date on record",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.title",
      titleDefault: "Set the rate once with the date it took effect",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.what",
      whatDefault:
        "Record GST at 15 percent with the date it took effect, 1 October 2010, so that anything valued before that date is computed at the rate that applied then rather than at today's. Keep it as one setting the whole system reads instead of a number typed into each template.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.rate.why",
      whyDefault:
        "A rate that lives in six templates is a rate that will be six different numbers the first time it changes, and the errors will be in the templates nobody uses often. Holding the effective date beside it is what lets an old valuation, a retrospective claim or a long-running contract be recomputed correctly instead of being quietly restated at the current rate.",
      moduleLabel: "Tax Rates",
      moduleLabelKey: "nav.tax_rates",
      to: "/tax-rates",
    },
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.in.contract",
          label: "Contract price and payment terms",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.in.due",
          label: "When a payment becomes due",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.out.basis",
          label: "Inclusive or exclusive settled",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.out.trigger",
          label: "Due date rule on record",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.title",
      titleDefault: "Settle whether the price includes it, and when payment falls due",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.what",
      whatDefault:
        "Record two things off the contract: whether the contract price is stated inclusive or exclusive of GST, and the rule that decides when a progress payment becomes due, which on a construction contract is usually a number of working days after a claim is served or certified. Both belong on the contract record where the person raising claims can see them.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.terms.why",
      whyDefault:
        "An inclusive price misread as exclusive is a thirteen percent error on the whole contract, and it survives review because both readings produce a plausible number. The due date rule matters for a different reason: it is one of the three dates the time of supply test looks at, so a contract term is doing tax work whether or not anybody in the finance team has read it.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "supply",
      icon: "Clock",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.in.claim",
          label: "Progress claim for the period",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.in.trigger",
          label: "Due date rule on record",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.out.date",
          label: "Time of supply for the instalment",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.out.retention",
          label: "Retention slice timed separately",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.title",
      titleDefault: "Fix the time of supply for the instalment",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.what",
      whatDefault:
        "For each progress payment take the earliest of three dates: the date the payment becomes due under the contract, the date it is actually received, and the date an invoice is issued for it. That date decides the period the GST belongs to. Deal with the retention slice separately, because retention money is accounted for when it becomes payable rather than when it was deducted from the claim.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.supply.why",
      whyDefault:
        "This is where construction differs from ordinary trading and where the money is lost. On the invoice basis the tax can fall due in a period when the payer has not paid, so a slow client funds its own delay out of your account. Knowing the date in advance turns that into a planned outflow rather than a surprise in the week the return is filed.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "information",
      icon: "SearchCheck",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.in.documents",
          label: "Claims and invoices issued",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.in.required",
          label: "Information the Act requires",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.out.complete",
          label: "Documents carrying what they must",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.out.flagged",
          label: "Documents missing a field",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.title",
      titleDefault: "Check every document carries the taxable supply information",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.what",
      whatDefault:
        "Run the check over the documents you issue: the supplier's name and GST number, the date, a description of the work, the amount and the GST, and the recipient's details where the value requires them. Since 1 April 2023 this is taxable supply information rather than a document that has to be headed tax invoice, and it may be spread across more than one document as long as the set is complete.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.information.why",
      whyDefault:
        "The obligation is now about information rather than about a form, which is easier to satisfy and easier to fail quietly, because a document that looks like every other invoice can be missing the one field that lets your customer claim the input tax. They discover it at their return, months later, and the correction lands on the relationship as well as on the paperwork.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "return",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.in.supply",
          label: "Time of supply per instalment",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.in.period",
          label: "Taxable period and accounting basis",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.out.figures",
          label: "Output and input tax for the period",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.out.cash",
          label: "Cash the return will take",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.title",
      titleDefault: "Line the periods up with the cash",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.what",
      whatDefault:
        "Read the output tax the period carries against the input tax on what you bought, and read both against when the money actually moves. Record which accounting basis the business is on, because the invoice basis and the payments basis put the same job's tax in different periods, and the payments basis is only open to smaller registered persons.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.return.why",
      whyDefault:
        "A construction business fails on cash rather than on margin, and GST is one of the largest predictable outflows it has. Read a month ahead it is a payment to plan for. Read on the due date it is the reason a subcontractor waits, and that has consequences under a different Act entirely.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
    {
      id: "records",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.in.documents",
          label: "Claims, invoices and returns",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.in.workings",
          label: "Workings behind each figure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.out.archive",
          label: "Records kept for seven years",
        },
        {
          labelKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.out.retrieval",
          label: "One place to answer a query from",
        },
      ],
      titleKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.title",
      titleDefault: "Keep the records for as long as the Act asks",
      whatKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.what",
      whatDefault:
        "File the claims, the taxable supply information, the credit notes and the workings behind each return together, project by project, and keep them for seven years. Keep the workings, not only the outputs, because a query is always about how a figure was arrived at rather than about what it was.",
      whyKey: "cases.charge_gst_on_a_progress_payment_at_the_right_time.step.records.why",
      whyDefault:
        "Seven years is longer than most construction businesses keep their project folders and longer than most of the people who built the job stay in it. A query about a return from four years ago is answered in an hour by a business that filed the workings and in a fortnight by one that has to rebuild them from bank statements.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
