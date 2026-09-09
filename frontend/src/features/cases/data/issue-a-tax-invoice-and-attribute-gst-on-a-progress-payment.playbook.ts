// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Issue a tax invoice and attribute GST on a progress payment" (AU).
//
// GST at ten per cent under A New Tax System (Goods and Services Tax) Act 1999,
// the particulars a tax invoice has to carry, and Division 156, which treats
// each progressive or periodic component of a construction supply as a separate
// supply for attribution. The two questions a builder gets wrong are which
// period the GST falls in and what happens to the retention that has not been
// released yet. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "issue-a-tax-invoice-and-attribute-gst-on-a-progress-payment",
  order: 1648,
  region: "AU",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "commercial-manager", "contract-administrator"],
  stage: "build",
  icon: "ReceiptText",
  titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.title",
  titleDefault: "Issue a tax invoice and attribute GST on a progress payment",
  descKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.desc",
  descDefault:
    "Set GST at ten per cent and mark what falls outside it, issue a tax invoice carrying the particulars the law requires, attribute each progress component to the right period under Division 156, deal with retention when it is withheld and when it is released, check every subcontractor's ABN before you pay, and reconcile the period for the activity statement.",
  longDescKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.longdesc",
  longDescDefault:
    "Construction is the classic case Division 156 was written for: one supply, built over years, paid for in monthly slices. The rule is that each progressive or periodic component is attributed as though it were a separate supply, so the GST on a progress claim falls into the period the invoice was issued in or the payment was received in rather than being deferred until the building is finished. That sounds obvious until retention enters, because retention is money earned and not yet paid, and a builder who treats the released retention as a fresh supply two years later has reported the same GST twice or not at all. None of this is discretionary and all of it is arithmetic, which makes it exactly the kind of thing worth setting up once at the start of a job.",
  estMinutes: 14,
  steps: [
    {
      id: "rate",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.in.registration", label: "GST registration and ABN" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.in.scope", label: "What the contract supplies" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.out.rate", label: "GST rate set on the project" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.out.outside", label: "Amounts outside the tax" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.title",
      titleDefault: "Set the rate and mark what sits outside it",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.what",
      whatDefault:
        "Set GST at ten per cent on the project and mark the amounts that are not consideration for a taxable supply, so they never pick the rate up by default. Liquidated damages deducted, a payment of damages and a security deposit that has not been forfeited are the ones that come up on a building job.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.rate.why",
      whyDefault:
        "The rate is the easy half. The expensive half is a deduction that was never a supply being run through the same tax treatment as the work, because the error is invisible on the face of the invoice and repeats every month until somebody reconciles a year of it at once.",
      moduleLabel: "Tax Rates",
      moduleLabelKey: "nav.tax_rates",
      to: "/tax-rates",
    },
    {
      id: "invoice",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.in.claim", label: "Certified progress claim" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.in.parties", label: "Supplier and recipient details" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.out.invoice", label: "Tax invoice issued" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.out.particulars", label: "Required particulars present" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.title",
      titleDefault: "Issue a document that is actually a tax invoice",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.what",
      whatDefault:
        "Raise the invoice with everything the law asks a tax invoice to show: that it is intended as a tax invoice, your identity and your ABN, the date, what was supplied, the GST amount or a statement that the total includes GST, and the recipient's identity or ABN once the sale reaches the threshold at which that is required. Where the principal issues a recipient created tax invoice instead, record the written agreement that allows it.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.invoice.why",
      whyDefault:
        "A recipient cannot claim the input tax credit without a valid tax invoice, so a document short of one particular is not a small formatting problem, it is a payment your client's accounts team will hold until it is reissued. On a monthly claim cycle that is a month of cash for a missing line of text.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "attribute",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.in.invoice", label: "Tax invoice issued" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.in.basis", label: "Cash or accruals basis" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.out.period", label: "Component in the right period" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.out.trail", label: "Invoice and payment dates recorded" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.title",
      titleDefault: "Attribute each component to the period it belongs in",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.what",
      whatDefault:
        "Record the date the invoice was issued and the date payment came in against each progress component, and let the period follow the basis you account on. Division 156 treats each progressive or periodic component of a supply as a separate supply for this purpose, so the building being unfinished does not defer anything.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.attribute.why",
      whyDefault:
        "A builder who waits for practical completion to account for the GST on two years of progress claims has been reporting a series of periods wrong, and the correction arrives with interest attached. The dates that settle it are the invoice date and the payment date, both of which are on the record already if anybody thought to keep them.",
      moduleLabel: "Payments",
      moduleLabelKey: "finance.payments",
      to: "/projects/:projectId/finance?tab=payments",
    },
    {
      id: "retention",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.in.held", label: "Retention withheld this period" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.in.release", label: "Retention due for release" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.out.treated", label: "Retention treated once" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.out.balance", label: "Balance held by release date" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.title",
      titleDefault: "Handle retention once, not twice",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.what",
      whatDefault:
        "Track retention as an amount withheld from a claim that has already been made rather than as a separate later sale, with the balance held, the reduction at practical completion and the release at the end of the defects liability period each carrying its own date.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.retention.why",
      whyDefault:
        "Retention is the place the two common errors meet. Treated as a new supply on release, the GST is reported twice; forgotten entirely, the last five per cent of a job is never chased at all. Held as a running balance with dates on it, both problems disappear and the release becomes something somebody is watching for.",
      moduleLabel: "Retention",
      moduleLabelKey: "finance.retention_tab",
      to: "/projects/:projectId/finance?tab=retention",
    },
    {
      id: "abn",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.in.invoices", label: "Subcontractor invoices" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.in.abn", label: "ABN quoted or missing" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.out.checked", label: "ABN and GST status checked" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.out.withheld", label: "Withholding applied where required" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.title",
      titleDefault: "Check the ABN before you pay the subcontractor",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.what",
      whatDefault:
        "Check that each supplier has quoted an ABN and whether it is registered for GST, and set the withholding on the ones that have not. An invoice from a supplier who is not registered for GST should not be carrying a GST line at all, and paying one that does is money you cannot claim back.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.abn.why",
      whyDefault:
        "Where no ABN is quoted for a taxable supply the payer is required to withhold at the top rate and remit it, and the liability for not doing so sits with the payer rather than with the supplier who left it off. Checking at the first invoice costs a minute and settles the whole job.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "reconcile",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.in.period", label: "Components in the period" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.in.credits", label: "Input tax credits claimed" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.out.summary", label: "Period totals reconciled" },
        { labelKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.out.variances", label: "Differences explained" },
      ],
      titleKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.title",
      titleDefault: "Reconcile the period before the activity statement",
      whatKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.what",
      whatDefault:
        "Report the period: what was invoiced, what was received, the GST collected and the credits claimed, with the differences named rather than left as a rounding. Keep the report so the same question about the same month can be answered a year later without rebuilding it.",
      whyKey: "cases.issue_a_tax_invoice_and_attribute_gst_on_a_progress_payment.step.reconcile.why",
      whyDefault:
        "The activity statement is a return, so an error in it is a correction rather than an adjustment, and corrections come with interest. A reconciliation that names its differences each month is also the only version of this work that takes an hour instead of a fortnight when a review asks for it.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
