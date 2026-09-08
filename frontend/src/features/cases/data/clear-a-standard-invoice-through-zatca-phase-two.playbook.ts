// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Clear a standard invoice through ZATCA phase two" (SA).
//
// Saudi e-invoicing is not a filing obligation, it is a gate the invoice
// passes through before the buyer ever sees it. Under the phase two
// integration rules a standard tax invoice is submitted to ZATCA's Fatoora
// platform and cleared there, and only the cleared document, carrying the
// cryptographic stamp ZATCA applied, is a valid tax invoice. A simplified
// invoice is not cleared, it is reported within twenty four hours of issue.
// This case runs one progress invoice through that path and treats a cleared
// invoice and an uncleared one as two different objects, because the tax
// authority does. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "clear-a-standard-invoice-through-zatca-phase-two",
  order: 1190,
  region: "SA",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["finance-manager", "accountant", "commercial-manager"],
  stage: "build",
  icon: "ReceiptText",
  titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.title",
  titleDefault: "Clear a standard invoice through ZATCA phase two",
  descKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.desc",
  descDefault:
    "Put the tax profile and the integration credentials on record, raise the progress invoice, validate it before it leaves, clear it with ZATCA, hand the buyer the cleared document with its QR, and correct it with a credit note rather than by deleting it.",
  longDescKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.longdesc",
  longDescDefault:
    "Phase two of the Saudi e-invoicing regulation, the integration phase, connects your system to ZATCA's Fatoora platform. A standard tax invoice, the business to business document a contractor raises against a payment certificate, is submitted for clearance and comes back stamped, and it is that stamped document, not the one your system produced, that the buyer is entitled to and that supports his input tax. A simplified invoice, the business to consumer document, is not cleared at all, it is reported within twenty four hours. The failure this case is built to prevent is a contractor who emails the invoice his system generated, files it as sent, and finds out at the buyer's audit that the document in his own folder is not the document ZATCA holds. Clearance first, delivery second, and every correction as a credit note through the same integration.",
  estMinutes: 15,
  steps: [
    {
      id: "profile",
      icon: "KeyRound",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.in.certificate", label: "VAT registration certificate" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.in.onboarding", label: "Onboarding credentials" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.out.profile", label: "Tax profile on record" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.out.stamp", label: "Stamp identifier referenced" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.title",
      titleDefault: "Record the tax profile the invoice is stamped with",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.what",
      whatDefault:
        "Put the seller's VAT registration number, the commercial registration and the address as ZATCA holds them into the profile the invoice is built from, and reference the cryptographic stamp identifier the integration was onboarded with. The buyer's VAT number belongs on the same record, because a standard invoice needs it and an invoice missing it is refused rather than queued.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.profile.why",
      whyDefault:
        "The e-invoicing regulation and its controls fix the fields a tax invoice must carry, and the integration checks them at submission rather than at audit. A number typed differently on each invoice is not a formatting question here, it is the difference between a document that clears and one that comes back, and the person who finds out is whoever is holding the payment.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings",
    },
    {
      id: "raise",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.in.certificate", label: "Approved payment certificate" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.in.profile", label: "Tax profile on record" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.out.invoice", label: "Draft standard invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.out.vat", label: "VAT at 15 percent applied" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.title",
      titleDefault: "Raise the invoice against the approved certificate",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.what",
      whatDefault:
        "Build the invoice from the certified figure for the period, with the advance recovery and the retention shown as the contract provides for them, and VAT applied at the standard Saudi rate of 15 percent on the taxable lines. Reference the payment certificate on the invoice so the two documents can be read against each other later.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.raise.why",
      whyDefault:
        "An invoice built by hand beside the certificate rather than from it is one that will disagree with it by a few riyals, and a cleared invoice cannot be quietly edited to make the disagreement go away. The correction is a credit note that ZATCA also holds, so the cheap moment to get the figure right is before submission.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.in.invoice", label: "Draft standard invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.in.rules", label: "Country rule set" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.out.report", label: "Validation report" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.out.fixed", label: "Blocking findings cleared" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.title",
      titleDefault: "Validate it before it leaves the building",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.what",
      whatDefault:
        "Run the invoice through validation with the Saudi rule set selected and clear the blocking findings: missing buyer VAT number on a standard invoice, a tax total that does not follow from the lines, an address that does not match the registration, a bank account in the wrong format for a Saudi IBAN.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.validate.why",
      whyDefault:
        "ZATCA validates at submission and rejects, and a rejection is not a soft failure, it means no valid tax invoice exists for that supply yet. Catching the same defects locally costs a minute and does not consume a document number, which is the whole reason validation sits before the integration and not after it.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "clear",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.in.invoice", label: "Validated invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.in.credentials", label: "Integration credentials" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.out.cleared", label: "Cleared invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.out.qr", label: "Stamp and QR on the document" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.title",
      titleDefault: "Clear it with ZATCA before the buyer sees it",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.what",
      whatDefault:
        "Submit the invoice for clearance under the Saudi regime and keep what comes back: the cryptographic stamp, the QR the document must carry, and the identifier the submission is known by. A standard invoice is cleared before issue. A simplified invoice takes the other path and is reported within twenty four hours of being issued, so decide which document you are raising before you submit it, not after.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.clear.why",
      whyDefault:
        "This is the step that makes Saudi e-invoicing different from a filing regime. Until clearance comes back, the document your system produced is a draft with a total on it, and issuing it to the buyer does not make it a tax invoice. The cleared document is the one that supports the buyer's input tax, so a contractor who skips this has not just missed a formality, he has handed his client something the client cannot use.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
    {
      id: "deliver",
      icon: "Send",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.in.cleared", label: "Cleared invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.in.backup", label: "Certificate and backup" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.out.sent", label: "Document sent to the buyer" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.out.archive", label: "Archived with its stamp" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.title",
      titleDefault: "Send the cleared document, not the one you printed",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.what",
      whatDefault:
        "File the cleared invoice with the payment certificate and the measure behind it, and send the buyer that version, the one carrying the stamp and the QR. Keep the XML alongside the readable copy, because the structured document is the record and the printed page is a rendering of it.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.deliver.why",
      whyDefault:
        "Two documents with the same number and different provenance is the shape this failure takes, and it stays invisible until somebody reconciles. Archiving the cleared version, with everything that justified it in the same place, is what lets a query six months later be answered in one folder rather than in three inboxes.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "correct",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.in.cleared", label: "Cleared invoice" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.in.dispute", label: "Agreed correction" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.out.note", label: "Credit note cleared" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.out.trail", label: "Trail from one to the other" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.title",
      titleDefault: "Correct it with a credit note, never by deleting it",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.what",
      whatDefault:
        "When the client disputes a quantity or a rate after the invoice has cleared, raise a credit note that references the original invoice and put it through the same integration. Where the correction restores the amount at a different figure, a second invoice follows the credit note. The original stays where it is.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.correct.why",
      whyDefault:
        "There is no unclearing. A cleared invoice exists in ZATCA's records whatever your system later shows, so the only correction the regime recognises is a credit note reported through the same channel. Teams used to editing a draft learn this the expensive way, at a reconciliation where their ledger and the tax authority's differ by exactly the amount somebody tidied up.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "reconcile",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.in.cleared", label: "Cleared documents for the period" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.in.ledger", label: "Project ledger" },
      ],
      outputs: [
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.out.match", label: "Cleared set reconciled" },
        { labelKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.out.return", label: "Figures ready for the return" },
      ],
      titleKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.title",
      titleDefault: "Reconcile what cleared against what the accounts hold",
      whatKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.what",
      whatDefault:
        "At the end of the period, list every document that cleared, every credit note against them and the output tax each carried, and read that list against the project ledger. Anything in one and not the other is the thing to explain before the return is filed.",
      whyKey: "cases.clear_a_standard_invoice_through_zatca_phase_two.step.reconcile.why",
      whyDefault:
        "Under a clearance regime the tax authority already has your sales ledger, so the return is a statement about records ZATCA can compare with its own. A monthly reconciliation turns a mismatch into a two line explanation while somebody still remembers the job, instead of a query about a number nobody in the room recognises.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
