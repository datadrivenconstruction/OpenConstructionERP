// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Invoice a subcontract under forditott adozas" (HU).
//
// The single most consequential tax question on a Hungarian subcontract
// invoice: does the domestic reverse charge apply, and can you show why. The
// test is in the VAT Act, the evidence is a written declaration the parties
// exchange before the work, and getting it wrong in either direction is
// expensive in a different way each time. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "invoice-a-subcontract-under-forditott-adozas",
  order: 1243,
  region: "HU",
  category: "commercial",
  companyTypes: ["subcontractor", "general-contractor", "cost-consultant"],
  roles: ["accountant", "finance-manager", "commercial-manager", "contract-administrator"],
  icon: "Percent",
  titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.title",
  titleDefault: "Invoice a subcontract under forditott adozas",
  descKey: "cases.invoice_a_subcontract_under_forditott_adozas.desc",
  descDefault:
    "Test whether the domestic reverse charge applies to the work, get the written nyilatkozat on file before you invoice, issue the szamla with no tax and the words forditott adozas on it, and keep the supplies that fall outside the rule on their own lines.",
  longDescKey: "cases.invoice_a_subcontract_under_forditott_adozas.longdesc",
  longDescDefault:
    "Article 142 of Act CXXVII of 2007 on VAT, the Afa tv., moves the tax on construction and installation work from the supplier to the customer where the work creates, extends, alters, demolishes or changes the use of real property and is subject to an authority permit or an authority notification, both parties are domestic taxable persons and neither has a status that would keep it out. The consequence for a subcontractor is that the invoice carries no tax at all, which is either a cashflow advantage or a disaster depending on whether the condition really held. Charge 27 percent where the reverse charge applied and your customer cannot deduct it; leave the tax off where it did not apply and the missing tax is yours to pay, with the interest. The rule is not the hard part. The evidence that the condition held on the day is.",
  estMinutes: 12,
  steps: [
    {
      id: "test",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.in.contract", label: "Subcontract and scope" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.in.permit", label: "Permit or notification status" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.out.decision", label: "Tax treatment decided" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.out.reason", label: "Reason recorded on the contract" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.title",
      titleDefault: "Test the work against the rule, not the habit",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.what",
      whatDefault:
        "Record on the contract which limb of the test the work meets: that it is construction or installation work directed at real property, that the work is subject to a permit from or a notification to an authority, and that both parties are domestic taxable persons. Record the answer even when it is no, because the no is the thing you will be asked to justify later.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.test.why",
      whyDefault:
        "The condition is about the work, not about the trade, so two packages for the same customer on the same site can fall on opposite sides of it. Since the wording was widened to cover work subject to a notification and not only work subject to a permit, jobs that used to sit outside the rule now sit inside it, and firms that decided this once years ago are the ones getting it wrong now.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "nyilatkozat",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.in.parties", label: "Both parties and their tax status" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.in.decision", label: "Tax treatment decided" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.out.nyilatkozat", label: "Signed nyilatkozat on file" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.out.dated", label: "Dated before the work" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.title",
      titleDefault: "Get the written nyilatkozat before the work",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.what",
      whatDefault:
        "File the written declaration the parties owe each other in advance. The party who knows the permit or notification status of the works is the party who declares it, so on a normal subcontract that is the customer declaring the status of the works, and where the permit or notification concerns the supplier's own activity the supplier declares it instead. Keep it with the contract, dated before the first invoice.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.nyilatkozat.why",
      whyDefault:
        "The Afa tv. makes the declaration a condition and not a courtesy. In an audit the question is never whether the building needed a permit, it is what you knew on the day you invoiced, and a declaration written afterwards answers a different question. A subcontractor who invoices without one is relying on a fact held by somebody else with no record that they were ever told it.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "split",
      icon: "Split",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.in.valuation", label: "Valuation for the period" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.in.scope", label: "Scope of the package" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.out.reverse", label: "Lines under the reverse charge" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.out.normal", label: "Lines taxed normally" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.title",
      titleDefault: "Keep what falls outside the rule on its own lines",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.what",
      whatDefault:
        "Go through the period's tetel list and separate the work that meets the test from anything invoiced alongside it that does not, such as goods sold on without installation, plant hired out on its own or design work billed separately. The two groups end up on different tax treatments, so they have to be different lines.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.split.why",
      whyDefault:
        "A mixed invoice is the shape most reverse-charge errors arrive in, because the decision was made once for the contract and then applied to everything that came out of it. Splitting the lines while the valuation is in front of you is minutes; unpicking it from a year of invoices during an audit is not.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "szamla",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.in.lines", label: "Lines under the reverse charge" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.in.igazolas", label: "Signed teljesitesigazolas" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.out.szamla", label: "Szamla issued without tax" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.out.marking", label: "Forditott adozas marked on it" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.title",
      titleDefault: "Issue the szamla with the tax left off and said so",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.what",
      whatDefault:
        "Raise the szamla against the approved figure with no tax amount on the reverse-charge lines, the words forditott adozas on the invoice, the customer's tax number shown, and the teljesitesigazolas it answers referenced. The 27 percent standard rate is not shown and not collected: the customer accounts for it.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.szamla.why",
      whyDefault:
        "The mandatory invoice content list in the Afa tv. requires the reference to forditott adozas on a reverse-charge invoice, and an invoice missing it is defective even though the amount is right. Your customer's accountant will send it back, which costs a period, and the payment clock does not run on a returned invoice.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "report",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.in.szamla", label: "Issued szamla" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.in.schema", label: "Reporting schema" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.out.reported", label: "Invoice reported" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.out.receipt", label: "Transaction receipt" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.title",
      titleDefault: "Report it like any other invoice",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.what",
      whatDefault:
        "Send the invoice data to NAV through the Online Szamla channel and keep the transaction receipt with the invoice. A reverse-charge invoice is reported on the same terms as a taxed one, and the reverse-charge marking travels in the data.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.report.why",
      whyDefault:
        "Carrying no tax does not make an invoice invisible to the reporting obligation, and this is a genuinely common misreading. The reported data is also what makes the pair check out: your customer declares the tax they self-assessed on the same transaction, and a supply that was never reported leaves them holding a deduction with nothing on the other side of it.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
    {
      id: "reconcile",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.in.issued", label: "Invoices issued in the period" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.in.treatment", label: "Tax treatment per line" },
      ],
      outputs: [
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.out.report", label: "Period tax summary" },
        { labelKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.out.exceptions", label: "Exceptions to look at" },
      ],
      titleKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.title",
      titleDefault: "Reconcile the period before the return goes in",
      whatKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.what",
      whatDefault:
        "Before the VAT return, list the period's invoices by treatment and look at the exceptions: a customer who appears under both treatments, a contract whose declaration is missing, an invoice with tax on it on a site where every other invoice had none.",
      whyKey: "cases.invoice_a_subcontract_under_forditott_adozas.step.reconcile.why",
      whyDefault:
        "Both sides report the same transaction in the same period, so a mismatch is visible to the tax authority whether or not it is visible to you. Finding your own inconsistency before the return goes in turns a correction into a routine amendment, and finding it two years later turns it into an assessment with interest running from the original date.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
