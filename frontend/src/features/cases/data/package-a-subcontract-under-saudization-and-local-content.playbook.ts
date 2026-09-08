// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Package a subcontract under Saudization and local content" (SA).
//
// Two obligations shape a Saudi subcontract package before price does.
// Saudization is measured under Nitaqat, which puts an establishment in a
// band and makes labour services depend on it, so a subcontractor in the
// bottom band cannot reliably staff the package he just won. Local content is
// measured separately: the Local Content and Government Procurement Authority
// sets the methodology and issues the certificates for government work, and
// the in-Kingdom total value add programme run by the national oil company
// measures its own suppliers on its own basis. Both are commitments that get
// made at award and evidenced monthly. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "package-a-subcontract-under-saudization-and-local-content",
  order: 1196,
  region: "SA",
  category: "tendering",
  companyTypes: ["general-contractor", "project-manager", "subcontractor"],
  roles: ["procurement-buyer", "commercial-manager", "project-manager"],
  stage: "procure",
  icon: "Network",
  titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.title",
  titleDefault: "Package a subcontract under Saudization and local content",
  descKey: "cases.package_a_subcontract_under_saudization_and_local_content.desc",
  descDefault:
    "Break the works into packages, prequalify on classification, Saudization band and local content rather than on price alone, compare like with like, write both obligations into the subcontract, and evidence what was actually delivered month by month.",
  longDescKey: "cases.package_a_subcontract_under_saudization_and_local_content.longdesc",
  longDescDefault:
    "A main contractor in the Kingdom carries two commitments into every package he lets. Nitaqat bands an establishment by the proportion of Saudi nationals it employs, from platinum down through the green bands to red, and the band decides whether the firm can issue and renew work permits or move workers at all, which makes it a delivery risk long before it is a compliance question. Since April 2026 a Saudi employee only counts toward that percentage where the employment contract is documented electronically on the labour platform, so a subcontractor's band can fall without a single person leaving. Local content runs on its own track, with a certificate issued against an audited methodology, and the percentage promised at tender becomes a figure somebody has to prove from real spend. This case gets both into the package before the award rather than into a dispute after it.",
  estMinutes: 18,
  steps: [
    {
      id: "packages",
      icon: "Split",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.in.scope", label: "Works scope" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.in.obligations", label: "Main contract obligations" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.out.packages", label: "Package breakdown" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.out.targets", label: "Target per package" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.title",
      titleDefault: "Break the works into packages that carry their own share",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.what",
      whatDefault:
        "Split the works into procurement packages and give each one its share of what the main contract committed you to: the labour content, the local content percentage and the value it represents. Say which packages are labour heavy and which are supply heavy, because they carry the two obligations in opposite proportions.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.packages.why",
      whyDefault:
        "A commitment held only at project level is one nobody can be held to. Split across packages, each buyer knows the number their package has to deliver and can see at award whether they have bought it. A local content target that arrives at the end as a single project percentage is a target that gets discovered as a shortfall when there is nothing left to buy.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "prequalify",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.in.candidates", label: "Candidate subcontractors" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.in.criteria", label: "Prequalification criteria" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.out.list", label: "Approved bidder list" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.out.evidence", label: "Certificates on file" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.title",
      titleDefault: "Prequalify on the things that can stop the work",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.what",
      whatDefault:
        "Check each candidate on the record rather than on the reference: contractor classification in the field and activity the package needs, current commercial registration, zakat, tax and social insurance certificates, the Nitaqat band, and the local content certificate with the percentage it actually states.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.prequalify.why",
      whyDefault:
        "The band is the one people skip because it looks like the subcontractor's own business. It is not. A firm in the red band cannot renew work permits or transfer workers in, so the crew it promised for month four is a crew it has no lawful way to assemble. Reading the band at prequalification is how you find that out while there is still another bidder.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "enquire",
      icon: "Send",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.in.list", label: "Approved bidder list" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.in.package", label: "Package documents" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.out.quotes", label: "Comparable quotations" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.out.comparison", label: "Comparison on one basis" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.title",
      titleDefault: "Enquire so the answers can be compared",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.what",
      whatDefault:
        "Send one enquiry with one bill, and require each bidder to state the same things beside the price: the local content he will deliver and how it is made up, the crew he will staff the package with, and where that labour comes from. Compare the returns on those columns as well as on the total.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.enquire.why",
      whyDefault:
        "Priced against a common bill, the cheapest number is a fact. Priced against three different assumptions about who supplies the labour, it is a guess. Asking for the local content composition at enquiry also does something the award cannot: it lets you see which bidder has thought about it, because the one who has will answer with named suppliers and the one who has not will answer with a percentage.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "flowdown",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.in.award", label: "Award decision" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.in.commitments", label: "Commitments made at tender" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.out.subcontract", label: "Subcontract executed" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.out.obligations", label: "Obligations written in" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.title",
      titleDefault: "Write both obligations into the subcontract",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.what",
      whatDefault:
        "Draw the subcontract with the commitments as terms rather than as expectations: the local content percentage and how it will be evidenced, wage protection compliance as a condition of payment, the obligation to keep the classification and the certificates current, and notice to you if the band changes.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.flowdown.why",
      whyDefault:
        "You are answerable to the employer for numbers you do not control. Where the obligation is written down, a shortfall is a breach with a remedy attached and the conversation happens in month three. Where it is not, the first anybody hears of it is your own report to the client, and by then the only remedy left is to explain.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "expiry",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.in.certificates", label: "Subcontractor certificates" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.in.bands", label: "Bands at award" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.out.register", label: "Renewal register" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.out.alerts", label: "Slippage caught early" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.title",
      titleDefault: "Watch the certificates and the band, because both move",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.what",
      whatDefault:
        "Register the expiry of every certificate you prequalified on and re-check the band at agreed points through the package rather than only at award. Ask for the evidence again before each milestone payment, not because the subcontractor is suspected but because a band is a moving measurement.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.expiry.why",
      whyDefault:
        "A band is recalculated as the workforce changes, so a subcontractor who was green at award can be red by the time he mobilises without having done anything visible. Since April 2026 an employment contract that is not documented electronically on the labour platform stops counting toward the percentage, which means a firm can slip a band through paperwork alone.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "evidence",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.in.spend", label: "Spend by supplier" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.in.declarations", label: "Supplier declarations" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.out.actual", label: "Local content delivered" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.out.variance", label: "Variance against commitment" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.title",
      titleDefault: "Evidence what was delivered, not what was promised",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.what",
      whatDefault:
        "Build the local content position from the spend that actually went out, supplier by supplier, with the certificate or declaration behind each line, and report it against what was committed. Where the job also reports under the in-Kingdom total value add programme of an operator, keep that measurement separate rather than reusing the government figure, because the two methodologies are not the same.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.evidence.why",
      whyDefault:
        "Local content is audited against invoices, so a figure assembled from intentions does not survive the first sample. Keeping the two schemes apart matters just as much: they are administered by different bodies, measured on different rules and reported on different platforms, and a contractor who submits one authority's number to the other has filed something he cannot support.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
    {
      id: "payment",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.in.application", label: "Subcontractor application" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.in.compliance", label: "Compliance evidence" },
      ],
      outputs: [
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.out.certified", label: "Payment certified" },
        { labelKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.out.withheld", label: "Amounts withheld with a reason" },
      ],
      titleKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.title",
      titleDefault: "Certify against the evidence the subcontract asked for",
      whatKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.what",
      whatDefault:
        "Value the subcontractor's work as measured and check the conditions the subcontract attached to payment before certifying: wage compliance evidence for the period, the certificates still current, the local content return submitted. Where something is withheld, state which term it is withheld under and what would release it.",
      whyKey: "cases.package_a_subcontract_under_saudization_and_local_content.step.payment.why",
      whyDefault:
        "A condition nobody checks is a condition that was never agreed. Checking it at each valuation is also fairer than the alternative, which is a large deduction at the end for months of small omissions nobody mentioned. A withholding that names its clause and its cure gets fixed. One that just appears becomes a dispute about the deduction rather than about the obligation.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
