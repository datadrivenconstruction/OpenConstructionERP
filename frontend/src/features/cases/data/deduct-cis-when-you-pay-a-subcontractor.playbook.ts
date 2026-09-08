// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Deduct CIS when you pay a subcontractor" (GB).
//
// The Construction Industry Scheme makes the payer responsible for a rate
// that depends on somebody else's verification status, and the domestic
// reverse charge sits on top of the same supply. The case works both out
// before the payment leaves rather than after. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "deduct-cis-when-you-pay-a-subcontractor",
  order: 1164,
  region: "GB",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor"],
  roles: ["accountant", "finance-manager", "commercial-manager"],
  stage: "build",
  icon: "Receipt",
  titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.title",
  titleDefault: "Deduct CIS when you pay a subcontractor",
  descKey: "cases.deduct_cis_when_you_pay_a_subcontractor.desc",
  descDefault:
    "Check who you are paying, record their scheme standing and the verification behind it, work the deduction out before the payment leaves, settle whether the reverse charge applies, and keep the record the monthly return is built from.",
  longDescKey: "cases.deduct_cis_when_you_pay_a_subcontractor.longdesc",
  longDescDefault:
    "Under the Construction Industry Scheme the contractor deducts tax from a subcontractor's payment and pays it over to HMRC, at nothing, twenty percent or thirty percent depending on how that subcontractor is verified. Deducting at the wrong rate is the payer's problem rather than the payee's, and it compounds every month until somebody notices. The domestic reverse charge sits on the same supply and moves the VAT to the customer for construction services reported under the scheme, stopping at the end user. Neither is difficult; both are unforgiving. This case gets them right on one payment and leaves behind the record the monthly return and the subcontractor's own statement are made of.",
  estMinutes: 12,
  steps: [
    {
      id: "standing",
      icon: "Users",
      inputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.in.details", label: "Subcontractor details" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.in.signed", label: "Signed subcontract" },
      ],
      outputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.out.party", label: "The paying party confirmed" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.out.record", label: "Record to deduct against" },
      ],
      titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.title",
      titleDefault: "Know who you are paying before you pay them",
      whatKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.what",
      whatDefault:
        "Open the subcontractor's record and check it is the party you actually contracted with: the trading name, the company registration and the subcontract they are working under. This is the record the deduction is taken against.",
      whyKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.standing.why",
      whyDefault:
        "A deduction is taken from a party, not from an invoice, and on a job with three companies inside one group the invoice does not always tell you which one is which. Getting the party right first is what makes everything after it checkable.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "scheme",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.in.verified", label: "Verified standing with HMRC" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.in.bands", label: "Scheme rate bands" },
      ],
      outputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.out.recorded", label: "Party standing recorded" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.out.expiry", label: "Band and its expiry date" },
      ],
      titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.title",
      titleDefault: "Record the scheme standing and the verification behind it",
      whatKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.what",
      whatDefault:
        "Install the Construction Industry Scheme for the United Kingdom and record this subcontractor's standing under it: the band they are entitled to, whether gross payment, standard or higher, the verification reference the authority gave, and the dates that verification covers.",
      whyKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.scheme.why",
      whyDefault:
        "The band is only as good as the verification behind it, and verifications expire. Holding the reference and the dates on the record means the rate applied to a payment can be justified months afterwards, which is precisely when somebody asks about it.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "preview",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.in.gross", label: "Gross payment amount" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.in.split", label: "Materials and labour split" },
      ],
      outputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.out.net", label: "Net payment to the subcontractor" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.out.drop", label: "Rate drop reported before it bites" },
      ],
      titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.title",
      titleDefault: "Work the deduction out before the payment leaves",
      whatKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.what",
      whatDefault:
        "Preview the deduction against the gross payment. The scheme decides what comes out of the taxable base, so the materials element and the VAT are handled by the scheme rather than by whoever happens to be doing the sum, and a band that depends on a verification is only kept while that verification still holds.",
      whyKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.preview.why",
      whyDefault:
        "A party who has lost their verification drops to the scheme's highest band, and the preview reports the drop rather than quietly applying it. A rate that went up because a certificate lapsed is a conversation to have before the remittance, not after the subcontractor has read it and rung the commercial manager.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "vat",
      icon: "GitCompareArrows",
      inputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.in.supply", label: "The supply being invoiced" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.in.enduser", label: "End user status" },
      ],
      outputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.out.decision", label: "Reverse charge decision on record" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.out.invoice", label: "Invoice raised the right way" },
      ],
      titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.title",
      titleDefault: "Settle whether the reverse charge applies",
      whatKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.what",
      whatDefault:
        "Determine whether the domestic reverse charge applies to this supply. It covers construction services reported under the scheme between VAT registered businesses, and it stops at the end user or intermediary supplier, who accounts for VAT the ordinary way, but only once they have told you so in writing; without that written confirmation you apply the reverse charge.",
      whyKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.vat.why",
      whyDefault:
        "The reverse charge moves the VAT from the supplier to the customer, so an invoice raised the old way is wrong on its face and the customer cannot simply pay it and move on. Determining it per supply, and keeping the determination, is what keeps a subcontractor's invoice payable on the day it arrives.",
      moduleLabel: "Withholding Tax",
      moduleLabelKey: "nav.tax_withholding",
      to: "/tax-withholding",
    },
    {
      id: "return",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.in.deductions", label: "Recorded deductions" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.in.payments", label: "Payments in the period" },
      ],
      outputs: [
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.out.report", label: "Monthly deduction report" },
        { labelKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.out.statements", label: "Subcontractor statements" },
      ],
      titleKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.title",
      titleDefault: "Keep the record the monthly return is built from",
      whatKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.what",
      whatDefault:
        "Report the deductions taken in the period: who they were taken from, the gross, the materials, the amount deducted and the verification each band rested on. That is the substance of the monthly return and of the statement every subcontractor is entitled to receive.",
      whyKey: "cases.deduct_cis_when_you_pay_a_subcontractor.step.return.why",
      whyDefault:
        "The CIS300 is due by the 19th for the tax month that ended on the 5th, whether or not the paperwork was kept, and each subcontractor's payment and deduction statement within fourteen days of the same month end. Reconstructing a month of deductions from bank payments is how a small error turns into a penalty. A report built from the recorded deductions carries the same facts as the subcontractor's own statement, which is why the two agree without anybody negotiating.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
