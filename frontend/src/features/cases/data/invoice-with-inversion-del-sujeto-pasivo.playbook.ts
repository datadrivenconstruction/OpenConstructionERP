// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Invoice construction work under inversion del sujeto pasivo" (ES).
//
// The platform ships the Spanish reverse-charge rule as data: art. 84.Uno.2 f)
// of Ley 37/1992, the sentence that has to appear on the invoice, and the scope
// note that it runs from the contract between promotor and contratista down the
// chain of subcontracts under it. A determination is recorded per invoice and
// carries the rule, the legal reference, the wording and the net amount, and
// the module's own rules refuse to let a record leave draft while the wording
// is missing or a VAT amount is still on it. The last step is the other half of
// the Spanish obligation: the invoice is valid on issue, but the record goes to
// the authority inside four calendar days.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "invoice-with-inversion-del-sujeto-pasivo",
  order: 1147,
  region: "ES",
  category: "commercial",
  companyTypes: ["subcontractor", "general-contractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "commercial-manager"],
  icon: "ReceiptEuro",
  titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.title",
  titleDefault: "Invoice construction work under inversion del sujeto pasivo",
  descKey: "cases.invoice_with_inversion_del_sujeto_pasivo.desc",
  descDefault:
    "Work out where you sit in the chain, record the determination against the invoice with the article it rests on, issue the invoice with the statutory sentence and no VAT, keep the confirmation that made it apply and report it inside the four days the authority allows.",
  longDescKey: "cases.invoice_with_inversion_del_sujeto_pasivo.longdesc",
  longDescDefault:
    "Inversion del sujeto pasivo moves the VAT on a construction invoice from the supplier to the customer, and it is not optional where it applies. It reaches works of construction or refurbishment of a building carried out under a contract between the promotor and the main contractor, and it follows down the subcontracts under that contract, which is why a subcontractor two levels down is inside it as surely as the contratista. Two mistakes cost money in opposite directions. Charging VAT where the reverse charge applies leaves the customer with a deduction the authority will not accept, and it is you they come back to. Applying it where it does not, on a repair or on work for a customer who is not acting as a business, leaves VAT you should have collected and did not. Both are decided per invoice, which is why the determination is recorded per invoice rather than set once on a customer.",
  estMinutes: 15,
  steps: [
    {
      id: "chain",
      icon: "Waypoints",
      inputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.in.contract",
          label: "Contract and subcontract chain",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.in.works",
          label: "Description of the works",
        },
      ],
      outputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.out.position",
          label: "Your position in the chain",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.out.scope",
          label: "Whether the works are in scope",
        },
      ],
      titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.title",
      titleDefault: "Establish where you sit and what you are building",
      whatKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.what",
      whatDefault:
        "Read the contract for two facts: that there is a contract between a promotor and a contratista for the construction or refurbishment of a building, and that your own contract sits under it, directly or through another subcontract. Both have to hold before the reverse charge reaches your invoice.",
      whyKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.chain.why",
      whyDefault:
        "The rule is about the chain, not about the trade. The same crew doing the same work is inside it on a refurbishment under a main contract and outside it on a call-out repair for the same client, and nobody notices the difference until an inspection reads the two invoices side by side.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "determine",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.in.position",
          label: "Your position in the chain",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.in.amount",
          label: "Net amount to be invoiced",
        },
      ],
      outputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.out.record",
          label: "Determination on record",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.out.wording",
          label: "Statutory wording on the invoice",
        },
      ],
      titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.title",
      titleDefault: "Record the determination against the invoice",
      whatKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.what",
      whatDefault:
        "Create the determination for this invoice: the Spanish construction rule, the article it rests on, the sentence that goes on the document, the net amount and the fact that the buyer accounts for the VAT. The record will not leave draft while the wording is missing or a VAT amount is still sitting on it.",
      whyKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.determine.why",
      whyDefault:
        "Per invoice rather than per customer, because the same customer can be inside the rule on one job and outside it on the next. Recorded rather than remembered, because the question that arrives in an inspection is why this invoice carried no VAT, and the answer has to be a decision with a date and an article rather than a habit.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "issue",
      icon: "Receipt",
      inputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.in.determination",
          label: "Determination on record",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.in.certificacion",
          label: "Approved certificacion",
        },
      ],
      outputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.out.invoice",
          label: "Invoice with no VAT amount",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.out.sentence",
          label: "Required sentence on the document",
        },
      ],
      titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.title",
      titleDefault: "Issue it with the sentence on and the VAT off",
      whatKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.what",
      whatDefault:
        "Raise the invoice for the net amount, put the statutory sentence naming the article on the face of it, and leave the VAT line empty rather than at zero percent. Reference the certificacion it answers so the two can be matched later.",
      whyKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.issue.why",
      whyDefault:
        "An invoice with the right total and no sentence is the one that gets returned, and returning it restarts the payment clock that was the whole point of certifying on time. A zero-rate line is not the same thing as no VAT either: it says a rate was applied, which is a different tax position from the one you meant.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "evidence",
      icon: "Paperclip",
      inputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.in.confirmation",
          label: "Customer confirmed in writing",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.in.registration",
          label: "Tax registration record",
        },
      ],
      outputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.out.filed",
          label: "Filed evidence document",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.out.linked",
          label: "Evidence linked to the invoice",
        },
      ],
      titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.title",
      titleDefault: "Keep the confirmation that made it apply",
      whatKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.what",
      whatDefault:
        "File the customer's written statement that they are acting as a business in this transaction, together with their tax registration details, and link it to the invoices it covers. Keep it against the contract it was given for rather than against the customer, because the same customer can be outside the rule on the next job.",
      whyKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.evidence.why",
      whyDefault:
        "The rule turns on the customer's status, and the customer is the only one who can state it. Without that statement on file the VAT you did not charge is VAT you may end up paying yourself, with the interest, years after the client has gone.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "report",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.in.invoice",
          label: "Issued invoice",
        },
      ],
      outputs: [
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.out.reported",
          label: "Invoice reported to the authority",
        },
        {
          labelKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.out.acknowledged",
          label: "Acknowledgement reference on record",
        },
      ],
      titleKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.title",
      titleDefault: "Report it in the return, or inside four days on the SII",
      whatKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.what",
      whatDefault:
        "If you file under the SII, which binds companies with turnover above 6.01 million euros, VAT groups and monthly filers, send the invoice record to the AEAT within four days of issue, weekends and national holidays not counted, and keep the acknowledgement reference against it; the invoice is valid from the moment it is issued, and a correction is an annulment record followed by a corrected one. Everyone else declares the invoice in the periodic modelo 303, in the box for operations under inversion del sujeto pasivo, and again in the annual modelo 390.",
      whyKey: "cases.invoice_with_inversion_del_sujeto_pasivo.step.report.why",
      whyDefault:
        "Late reporting is a penalty rather than an invalid invoice, which is exactly why it slides: nothing breaks and nobody chases it. On the SII the window is short enough that either you have a routine or you have a fine, and in the return an invoice issued without VAT that is missing from the reverse-charge box is the first thing an inspection compares against your customer's modelo 303.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
  ],
};

export default playbook;
