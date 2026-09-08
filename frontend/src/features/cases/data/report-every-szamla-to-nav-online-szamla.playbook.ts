// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Report every szamla to NAV Online Szamla" (HU).
//
// In Hungary an invoice is not finished when it is issued, it is finished when
// its data has reached the tax authority. Software that issues an invoice must
// report it at issue, without a human in the loop; an invoice written out of a
// book has days rather than seconds, and fewer of them when the tax on it is
// large. This case treats the report as part of invoicing rather than as a
// monthly chore. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "report-every-szamla-to-nav-online-szamla",
  order: 1244,
  region: "HU",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "developer-client"],
  roles: ["accountant", "finance-manager", "document-controller", "commercial-manager"],
  icon: "Upload",
  titleKey: "cases.report_every_szamla_to_nav_online_szamla.title",
  titleDefault: "Report every szamla to NAV Online Szamla",
  descKey: "cases.report_every_szamla_to_nav_online_szamla.desc",
  descDefault:
    "Get the invoice content right first, report the data to NAV at the moment of issue, clear what comes back rejected or flagged, and reconcile the reported set against the invoices the project thinks it raised.",
  longDescKey: "cases.report_every_szamla_to_nav_online_szamla.longdesc",
  longDescDefault:
    "Since 4 January 2021 the Hungarian real-time invoice reporting obligation covers every invoice issued under Hungarian rules, not just the business-to-business ones it started with. An invoice produced by software has to be transmitted to the Online Szamla system immediately on issue and without human intervention, in the XML structure the tax authority publishes. An invoice written by hand from a numbered book is reported within four calendar days, and within one calendar day where the tax on it reaches 500 000 forint. Construction firms trip over this in a particular way: the site raises a handwritten invoice at a client's request, nobody in the office hears about it for a week, and the deadline that mattered was the short one.",
  estMinutes: 11,
  steps: [
    {
      id: "content",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.in.igazolas", label: "Approved teljesitesigazolas" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.in.customer", label: "Customer and tax number" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.out.szamla", label: "Szamla ready to issue" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.out.fields", label: "Mandatory fields complete" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.title",
      titleDefault: "Get the invoice right before it is issued",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.what",
      whatDefault:
        "Build the szamla with the content the VAT Act requires: both parties and their tax numbers, the invoice number and dates, the description and quantity of the work, the taxable amount, the rate and the tax, or the marking that says why there is none. Reference the teljesitesigazolas the invoice answers.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.content.why",
      whyDefault:
        "The report carries the invoice, so a defect in the invoice becomes a defect in the report and then a defect in the customer's deduction. Correcting it means a modifying invoice and a second report, and on a construction account it means the payment clock restarts on a document the client has every reason to send back.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "transmit",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.in.szamla", label: "Issued szamla" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.in.credentials", label: "Reporting credentials" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.out.sent", label: "Invoice data transmitted" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.out.token", label: "Transaction identifier" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.title",
      titleDefault: "Transmit the data at the moment of issue",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.what",
      whatDefault:
        "Send the invoice data through the Online Szamla channel as the invoice is issued, in the XML structure the tax authority publishes, and keep the transaction identifier the system returns against the invoice record.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.transmit.why",
      whyDefault:
        "For an invoice produced by software the obligation is immediate and automatic: no batching to the end of the day, no operator pressing a button. Keeping the transaction identifier against the invoice is what turns the claim that it was reported into a fact somebody can check, which is exactly what nobody can produce when the question arrives eighteen months later.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
    {
      id: "manual",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.in.handwritten", label: "Handwritten invoice from site" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.in.amount", label: "Tax amount on it" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.out.deadline", label: "Reporting deadline set" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.out.owner", label: "Owner for the deadline" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.title",
      titleDefault: "Put a clock on every invoice written by hand",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.what",
      whatDefault:
        "For an invoice written out of a numbered book, open a deadline the day it is issued and give it an owner. Four calendar days is the normal window, and one calendar day where the tax on the invoice reaches 500 000 forint, so the amount decides which clock you are on.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.manual.why",
      whyDefault:
        "The short window is the one that catches people out, because the invoice large enough to trigger it is exactly the one raised in a hurry to unblock a payment. Nothing on the paper says which deadline applies and nobody in the office knows the invoice exists yet, so the clock has to be started by whoever wrote it rather than by whoever files it.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "errors",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.in.response", label: "Reporting response" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.in.szamla", label: "Invoice as reported" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.out.cleared", label: "Errors cleared and resent" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.out.log", label: "Warnings recorded" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.title",
      titleDefault: "Read what came back, not just that it went",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.what",
      whatDefault:
        "Check the processing result for every submission. Clear the technical errors and resend, and record the warnings rather than closing them, because a warning is a report that landed with something wrong inside it.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.errors.why",
      whyDefault:
        "A submission that was accepted for transmission and then rejected in processing is an invoice that has not been reported at all, and nothing about it looks different from the sending side. This is the failure that accumulates silently for a quarter and is then discovered as a set rather than as an incident.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "match",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.in.issued", label: "Invoices the project raised" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.in.reported", label: "Invoices reported" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.out.matched", label: "Matched set" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.out.gaps", label: "Unreported invoices found" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.title",
      titleDefault: "Reconcile issued against reported",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.what",
      whatDefault:
        "Match the invoices the project believes it raised against the invoices that carry a transaction identifier, and look at both sides of the difference: an invoice with no report, and a report with no invoice on the project.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.match.why",
      whyDefault:
        "On a construction account the gap is almost never a system fault, it is an invoice raised outside the normal route: from site, from a different company in the group, or against a project code nobody uses any more. Reconciling by count rather than by document is how a firm satisfies itself that everything is reported while one invoice a month is not.",
      moduleLabel: "Event Reconciliation",
      moduleLabelKey: "nav.reconciliation",
      to: "/projects/:projectId/reconciliation",
    },
    {
      id: "archive",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.in.reported", label: "Reported invoice set" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.in.receipts", label: "Transaction receipts" },
      ],
      outputs: [
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.out.pack", label: "Invoice pack with proof of report" },
        { labelKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.out.audit", label: "Audit trail on the project" },
      ],
      titleKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.title",
      titleDefault: "Keep the proof with the project, not with the ledger",
      whatKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.what",
      whatDefault:
        "File the invoice, its transaction receipt and the teljesitesigazolas it answers together on the project, so the three travel as one record rather than living in three systems that agree only when somebody checks.",
      whyKey: "cases.report_every_szamla_to_nav_online_szamla.step.archive.why",
      whyDefault:
        "Questions about an invoice arrive on the project long before they arrive in the accounts: a client disputes a period, a subcontractor claims a payment, a final account is being settled. Whoever answers is on the site side of the business, and giving them the proof of report in the same place as the invoice is the difference between an answer and a request forwarded to somebody on holiday.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
