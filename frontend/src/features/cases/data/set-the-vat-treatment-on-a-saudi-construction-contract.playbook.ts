// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set the VAT treatment on a Saudi construction contract" (SA).
//
// Fifteen percent is the easy half. The half that costs money is knowing
// which supplies on a construction job are not standard rated: the sale of
// the finished property, which left VAT for the real estate transaction tax
// in October 2020, the residential lease that is exempt, the design service
// for a foreign client that people assume is an export and is not, because a
// service relating to land in the Kingdom follows the land rather than the
// customer. This case fixes the treatment once, at contract level and per
// bill section, so the progress invoices that follow inherit it instead of
// each being decided by whoever raised them. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-the-vat-treatment-on-a-saudi-construction-contract",
  order: 1191,
  region: "SA",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "cost-consultant", "subcontractor"],
  roles: ["finance-manager", "accountant", "quantity-surveyor"],
  stage: "procure",
  icon: "Percent",
  titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.title",
  titleDefault: "Set the VAT treatment on a Saudi construction contract",
  descKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.desc",
  descDefault:
    "Record both parties' tax status, set the treatment per bill section rather than per invoice, keep the property sale and the contracting service apart, account for the non-resident supplier under reverse charge, and close the period with input tax you can actually evidence.",
  longDescKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.longdesc",
  longDescDefault:
    "Value added tax has stood at 15 percent in the Kingdom since July 2020, and on a construction job almost everything is standard rated. The exceptions are few and each of them is somebody's expensive surprise. The sale of real estate itself moved out of VAT in October 2020 and is charged the real estate transaction tax at 5 percent instead, while the contracting service that built the property stays standard rated, so a developer who reads the two as one supply prices the job wrong. A residential lease is exempt, which is not the same as zero rated and changes what input tax can be recovered. And a service relating to real estate in the Kingdom is supplied where the real estate is, so design or supervision billed to a client abroad is taxed here rather than zero rated as an export. Deciding all of this once, on the contract, is what stops it being decided twelve times by twelve different people.",
  estMinutes: 16,
  steps: [
    {
      id: "parties",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.in.contract", label: "Signed contract" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.in.registrations", label: "Tax registrations of both parties" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.out.status", label: "Tax status on record" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.out.place", label: "Place of supply settled" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.title",
      titleDefault: "Record who the parties are for tax, not just for signature",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.what",
      whatDefault:
        "Record the VAT registration of the employer and of your own entity, whether either is a government body, and where the works are. Where the client is not resident, note that the works are on land in the Kingdom, which is what decides the place of supply for a construction or a real estate related service.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.parties.why",
      whyDefault:
        "The commonest Saudi VAT error on a construction contract is treating a foreign client as an export customer. Services connected with real estate follow the real estate, so a design or supervision fee billed to a company abroad for a building in Riyadh is taxed here at the standard rate. Writing that down at contract stage costs nothing. Discovering it at assessment costs the tax plus the penalty, and the client has usually gone home.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "sections",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.in.boq", label: "Contract bill of quantities" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.in.status", label: "Tax status on record" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.out.rates", label: "Treatment set per section" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.out.totals", label: "Tax inclusive totals" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.title",
      titleDefault: "Set the treatment per bill section, once",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.what",
      whatDefault:
        "Go through the bill and mark which sections are standard rated at 15 percent, which are zero rated, which are exempt and which fall outside the scope of the tax. On most building contracts every section is standard rated and the work is proving it rather than finding exceptions, which is a five minute job that removes a monthly argument.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.sections.why",
      whyDefault:
        "Zero rated and exempt look the same on an invoice and behave in opposite ways behind it. A zero rated supply is taxable at nought and carries a full right to recover the input tax on what went into it. An exempt supply carries none, so the tax on your materials becomes a cost rather than a receivable. A bill that marks both as 0 percent hides the difference and only pays for it at the return.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "taxpoint",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.in.certificates", label: "Payment certificates" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.in.terms", label: "Contract payment terms" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.out.point", label: "Tax point per certificate" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.out.period", label: "Period the tax falls into" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.title",
      titleDefault: "Fix the tax point on a job billed in stages",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.what",
      whatDefault:
        "For each certified stage, record the date of supply the tax is due on, the date the invoice was issued and the date payment was received, and let the earliest of the events the regulation recognises decide which return period the output tax belongs to. Advances and payments on account are supplies in their own right and belong in the period they were received, not the period the work was done.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.taxpoint.why",
      whyDefault:
        "A construction contract runs for years and is billed in slices, so the question is never whether tax is due but which month it is due in. An advance taken in one quarter and set against work done in the next is the classic case, and a contractor who accounts for the tax when the work happens rather than when the money arrived is late on a supply he has already been paid for.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "property",
      icon: "Building2",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.in.scheme", label: "Development scheme" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.in.units", label: "Units and their tenure" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.out.split", label: "Sale and service separated" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.out.rett", label: "Transaction tax accounted for" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.title",
      titleDefault: "Keep the property sale and the building service apart",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.what",
      whatDefault:
        "Where the job ends in a sale, model the two supplies separately: the disposal of the real estate, which carries the real estate transaction tax at 5 percent and not VAT, and the contracting, design and management services, which stay standard rated. Residential letting is exempt, and an exempt income stream restricts what input tax the scheme can recover, so it belongs in the appraisal rather than in a footnote.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.property.why",
      whyDefault:
        "The October 2020 change took real estate disposals out of VAT and put the 5 percent transaction tax in their place, and it is still the point where developer appraisals go wrong, in both directions. A scheme that adds 15 percent to a sale price prices itself out. A scheme that assumes full input tax recovery on units it will let residentially is short by the tax on everything it built them with.",
      moduleLabel: "Property Development",
      moduleLabelKey: "nav.property_dev",
      to: "/property-dev",
    },
    {
      id: "nonresident",
      icon: "Globe",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.in.suppliers", label: "Non-resident suppliers" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.in.invoices", label: "Their invoices" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.out.reverse", label: "Reverse charge accounted" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.out.withholding", label: "Withholding computed" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.title",
      titleDefault: "Account for the non-resident supplier twice over",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.what",
      whatDefault:
        "For every specialist engaged from outside the Kingdom, record two separate obligations against the same invoice. VAT is accounted for by you under the reverse charge, as output tax with the matching input deduction. Withholding tax is deducted from the payment at the rate the type of payment attracts and paid over separately, and a treaty position, where there is one, is evidenced rather than assumed.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.nonresident.why",
      whyDefault:
        "These are two different taxes on one payment and they are usually handled by two different people who each think the other has it. Reverse charge VAT is broadly cash neutral and still has to appear on both sides of the return. Withholding is real money leaving, and it is the payer who is liable for it, so an amount paid gross abroad is an amount the payer will be asked for again later.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "recover",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.in.purchases", label: "Purchase invoices" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.in.customs", label: "Import documents" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.out.input", label: "Recoverable input tax" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.out.blocked", label: "Blocked items identified" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.title",
      titleDefault: "Recover input tax you can evidence, and only that",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.what",
      whatDefault:
        "Match the input tax you intend to recover to the document that supports it: a valid tax invoice from a registered supplier, or the import declaration for goods brought in. Separate out what is blocked or restricted, entertainment and private use being the usual ones, and anything attributable to an exempt supply.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.recover.why",
      whyDefault:
        "Input tax is a deduction the taxpayer has to prove, not a figure the accounting system computes. On a site with hundreds of small purchases, the tax deducted against a receipt that is not a valid tax invoice is the amount that comes back with interest, and it is invisible in the ledger because the number itself was right.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "file",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.in.output", label: "Output tax for the period" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.in.input", label: "Recoverable input tax" },
      ],
      outputs: [
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.out.return", label: "Return figures" },
        { labelKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.out.audit", label: "Audit trail per box" },
      ],
      titleKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.title",
      titleDefault: "Close the period with a trail behind every figure",
      whatKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.what",
      whatDefault:
        "Produce the period figures with the documents behind each of them: output tax by treatment, input tax by evidence type, reverse charge on both sides, and the adjustments made for credit notes cleared in the period.",
      whyKey: "cases.set_the_vat_treatment_on_a_saudi_construction_contract.step.file.why",
      whyDefault:
        "ZATCA already holds the cleared invoices, so the return is a claim that can be checked against records the authority produced. The value of the trail is not the filing, it is the question two years later, when the person who prepared it has moved on and the only defence is the working that came with the figure.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
