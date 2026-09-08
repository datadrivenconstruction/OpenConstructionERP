// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Issue a compliant XRechnung".
//
// The work is certified; now the invoice has to survive a public buyer's
// portal. Bill the certified claim, complete the buyer and seller data the
// standard demands, clear every BR-DE finding the built-in check quotes,
// export the XRechnung XML and record the transmission. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "issue-a-compliant-xrechnung",
  order: 1049,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "commercial-manager", "finance-manager"],
  region: "DE",
  icon: "ReceiptEuro",
  titleKey: "cases.issue_a_compliant_xrechnung.title",
  titleDefault: "Issue a compliant XRechnung",
  descKey: "cases.issue_a_compliant_xrechnung.desc",
  descDefault:
    "Turn a period of finished work into an electronic invoice a German public client will actually accept: complete the buyer and seller data the standard demands, clear every rule the check quotes, export the XRechnung XML and record where you sent it.",
  longDescKey: "cases.issue_a_compliant_xrechnung.longdesc",
  longDescDefault:
    "XRechnung is the German reading of EN 16931, the European standard for what an electronic invoice has to contain. A public buyer does not read a PDF and does not phone you about a missing field: a portal parses the XML and hands back a rule identifier instead of a payment. So the work is front-loaded. Get the buyer party, the seller contact, the bank details and the Leitweg-ID right once, and the check goes green in seconds every month after.",
  estMinutes: 11,
  steps: [
    {
      id: "basis",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.basis.in.positions", label: "Priced bill positions" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.basis.in.measure", label: "Site measurement" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.basis.out.amount", label: "Amount to bill" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.basis.out.period", label: "Billing period" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.basis.title",
      titleDefault: "Take this period's positions off the bill",
      whatKey: "cases.issue_a_compliant_xrechnung.step.basis.what",
      whatDefault:
        "Open the priced bill and work out what this interim actually bills: the positions finished on site in this period, measured rather than estimated, and the amount that falls on them.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.basis.why",
      whyDefault:
        "An interim invoice is a payment on account for work genuinely done. A position billed ahead of the Leistungsstand is the one the client's surveyor strikes out, and the rest of the invoice waits while that single line is argued.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "invoice",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.invoice.in.amount", label: "Amount to bill" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.invoice.in.contact", label: "Client contact" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.invoice.out.invoice", label: "Receivable invoice" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.invoice.out.lines", label: "Invoice lines" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.invoice.title",
      titleDefault: "Raise the receivable invoice",
      whatKey: "cases.issue_a_compliant_xrechnung.step.invoice.what",
      whatDefault:
        "On the receivable side of the Invoices tab, raise the interim invoice with its number, invoice date, due date and one line per block of work it bills, and pick the client from the contacts rather than typing a name into a free text field.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.invoice.why",
      whyDefault:
        "The electronic invoice is built from this record and nothing else, so a line missing here is a line missing in the XML. Picking the linked contact is what lets the buyer address be read instead of retyped on every invoice you send that client.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "buyer",
      icon: "Building2",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.buyer.in.contact", label: "Client contact" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.buyer.in.address", label: "Buyer postal address" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.buyer.out.party", label: "Complete buyer party" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.buyer.out.master", label: "Reusable master data" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.buyer.title",
      titleDefault: "Complete the buyer on the contact",
      whatKey: "cases.issue_a_compliant_xrechnung.step.buyer.what",
      whatDefault:
        "Open the client contact the invoice bills and fill in the buyer party the standard wants: legal name, street, postcode, town and the two-letter country code. The electronic invoice reads the buyer from here, not from the invoice.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.buyer.why",
      whyDefault:
        "An invoice whose buyer has no postal address is rejected outright, and for XRechnung the town and the postcode are each a fatal finding of their own. Filling them once on the contact fixes every invoice you will ever send that client.",
      moduleLabel: "Contacts",
      moduleLabelKey: "contacts.title",
      to: "/contacts",
    },
    {
      id: "seller",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.seller.in.registration", label: "Company registration data" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.seller.in.bank", label: "Bank account" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.seller.out.identity", label: "Seller identity" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.seller.out.terms", label: "Payment terms" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.seller.title",
      titleDefault: "Fill the seller side once",
      whatKey: "cases.issue_a_compliant_xrechnung.step.seller.what",
      whatDefault:
        "Under Settings, E-invoice, set your own side once: legal name and address, VAT identifier or tax number, a named contact with telephone and email, the IBAN the client pays into, and the payment terms you invoice on.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.seller.why",
      whyDefault:
        "XRechnung asks for more than the European standard does, and the named seller contact with a phone number and an email is exactly where it goes further. Set it here and it is right on every invoice afterwards, instead of being chased once a month.",
      moduleLabel: "Settings",
      moduleLabelKey: "nav.settings",
      to: "/settings",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.check.in.draft", label: "Draft electronic invoice" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.check.in.leitweg", label: "Leitweg-ID from the client" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.check.out.findings", label: "Rule findings" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.check.out.green", label: "Green check" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.check.title",
      titleDefault: "Run the check until it is green",
      whatKey: "cases.issue_a_compliant_xrechnung.step.check.what",
      whatDefault:
        "Open the electronic invoice dialog on that invoice, pick the XRechnung profile, and read what comes back. Blocking findings quote the rule identifier that will reject you, BR-DE-15 for a missing Leitweg-ID among them. Fix each one and run it again.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.check.why",
      whyDefault:
        "This is the same rule set the receiving portal runs, quoted in the same words. Reading BR-DE-15 here costs you a minute. Reading it in a rejection notice three weeks later costs you the whole payment period and a second run at the invoice.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "export",
      icon: "Download",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.export.in.green", label: "Green check" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.export.in.invoice", label: "Approved invoice" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.export.out.xml", label: "XRechnung XML" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.export.out.pdf", label: "Optional hybrid PDF" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.export.title",
      titleDefault: "Export the XRechnung XML",
      whatKey: "cases.issue_a_compliant_xrechnung.step.export.what",
      whatDefault:
        "The download only unlocks once the check is clean. Take the XML: that file is the invoice. A hybrid PDF carrying the same data inside it is there for readers who want a page to look at, and it is not what the receiver parses.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.export.why",
      whyDefault:
        "A public buyer's system reads the XML and ignores whatever you attached for human eyes. Sending a PDF and calling it an electronic invoice is the most common way a small firm finds out what the mandate actually asked for.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "record",
      icon: "Send",
      inputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.record.in.xml", label: "XRechnung XML" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.record.in.receipt", label: "Portal receipt" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_compliant_xrechnung.step.record.out.transmission", label: "Transmission id" },
        { labelKey: "cases.issue_a_compliant_xrechnung.step.record.out.record", label: "Send on record" },
      ],
      titleKey: "cases.issue_a_compliant_xrechnung.step.record.title",
      titleDefault: "Record where it went",
      whatKey: "cases.issue_a_compliant_xrechnung.step.record.what",
      whatDefault:
        "Log the send: the registration you issued under, the document itself, and the transmission id that came back from the ZRE or OZG-RE of the federal administration, the portal of the Land, or the Peppol access point where the client receives that way. The Leitweg-ID it was routed on is what the record keeps.",
      whyKey: "cases.issue_a_compliant_xrechnung.step.record.why",
      whyDefault:
        "Germany routes an invoice rather than clearing it, so no authority stamps yours. The transmission id is the only proof you sent it on the day you say you did, and it is what you quote when the client's accounts department cannot find it.",
      moduleLabel: "E-invoice Clearance",
      moduleLabelKey: "nav.einvoice_clearance",
      to: "/einvoice-clearance",
    },
  ],
};

export default playbook;
