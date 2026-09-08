// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Check the RBQ subclass and price GST and QST in parallel" (CA, Quebec).
//
// Two things make a Quebec bid different from the same bid anywhere else in the
// country, and neither of them is a translation: a contractor licence is issued
// by class AND subclass, so holding one is not holding the other, and the two
// sales taxes are parallel rather than stacked. The case is built around those
// two and nothing else, because they are what a product built for another
// market gets wrong. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "check-the-rbq-subclass-and-price-gst-and-qst",
  order: 1102,
  region: "CA",
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "procurement-buyer", "quantity-surveyor", "contract-administrator"],
  icon: "BadgeCheck",
  titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.title",
  titleDefault: "Check the RBQ subclass and price GST and QST in parallel",
  descKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.desc",
  descDefault:
    "Record a Quebec subcontractor's RBQ licence with the subclass it actually carries, check that subclass covers the scope before you award, and price the job with GST and QST as two parallel lines taken on the same pre-tax base.",
  longDescKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.longdesc",
  longDescDefault:
    "A licence in Quebec is issued by class and subclass, and the subclass is what says which work is permitted: 1.3 covers buildings, 1.4 covers roads and mains, and a firm holding one is not licensed for the other however current its licence looks. The taxes work the same way, differently from the rest of the country: GST at 5 percent and QST at 9.975 percent are both computed on the pre-tax price, giving 14.975 percent in total, and QST is administered by Revenu Quebec rather than by the federal agency. Software written elsewhere gets both of these wrong in the same way, by checking that a thing exists rather than checking what it is. A licence that exists and does not cover the scope is a problem you inherit, and a QST computed on a GST-inclusive figure is half a percent of the contract you either give away or never collect.",
  estMinutes: 16,
  steps: [
    {
      id: "licence",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.in.cert", label: "Licence certificate from the subcontractor" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.in.scope", label: "Scope of the package" },
      ],
      outputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.out.record", label: "Licence on record with its subclass" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.out.expiry", label: "Expiry date on file" },
      ],
      titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.title",
      titleDefault: "Record the licence with its subclass, not just its number",
      whatKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.what",
      whatDefault:
        "Add the RBQ licence to the subcontractor's record with the class and subclass it carries, whether it is restricted, and the date it expires, and file the certificate itself beside it rather than a note saying it was seen. File next to it the other papers a Quebec award turns on: the CNESST clearance, the CCQ letter of good standing and, on public work, the Revenu Quebec attestation.",
      whyKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.licence.why",
      whyDefault:
        "A register that says only that a firm is licensed has answered the easy half of the question. The subclass is what states the work the licence actually permits, and without it on the record nobody can tell later whether the right question was ever asked.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "scope",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.in.subclass", label: "Licence subclass on record" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.in.package", label: "Work the package contains" },
      ],
      outputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.out.covered", label: "Scope covered by the licence held" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.out.split", label: "Package split where it is not" },
      ],
      titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.title",
      titleDefault: "Read the subclass against the scope before you award",
      whatKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.what",
      whatDefault:
        "Before the award, read the subclass on the licence against the work the package actually contains. Where the scope crosses into work the subclass does not cover, either split the package or ask the firm for the licence that covers it, and record which you did.",
      whyKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.scope.why",
      whyDefault:
        "This is the check that a process built for another market does not make: it confirms a licence exists and stops there. In Quebec the licence usually exists and is the wrong one more often than it is missing, and the party who finds out is the owner of the project, at the worst possible moment.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "bill",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.in.quantities", label: "Measured quantities" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.in.rates", label: "Montreal cost rates" },
      ],
      outputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.out.bill", label: "Bill written in French" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.out.metric", label: "Metric quantities priced in CAD" },
      ],
      titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.title",
      titleDefault: "Build the bill as a Quebec estimator would write it",
      whatKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.what",
      whatDefault:
        "Write the item descriptions in French, keep the quantities metric and the prices in Canadian dollars at a Montreal level, and structure the bill by the divisions your client and their consultants already read.",
      whyKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.bill.why",
      whyDefault:
        "The client, the architect and the engineer read the bill in French and check it against documents written in French. A bill that arrives translated back out of another language reads as a bid prepared somewhere else, and the first thing that gets questioned after that is the price.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "tax",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.in.subtotal", label: "Pre-tax subtotal" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.in.rates", label: "Current GST and QST rates" },
      ],
      outputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.out.parallel", label: "Two tax lines on one base" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.out.base", label: "The base each was taken on" },
      ],
      titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.title",
      titleDefault: "Put the two taxes side by side, not one on top of the other",
      whatKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.what",
      whatDefault:
        "Add GST at 5 percent and QST at 9.975 percent as two separate lines, both taken on the same pre-tax subtotal, and show the base each one was computed on rather than only the combined figure.",
      whyKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.tax.why",
      whyDefault:
        "The two taxes are parallel, not stacked, and 14.975 percent is the sum of two rates on one base rather than one rate applied to the other's result. Compounding them adds half a percent of the contract to your price, which loses a competitive bid, or leaves it out of a cost plan, which loses money on the job. Showing the base is what lets the client verify it in a glance instead of a phone call.",
      moduleLabel: "Markups",
      moduleLabelKey: "nav.markups",
      to: "/markups",
    },
    {
      id: "review",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.in.priced", label: "Priced bill and tax lines" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.in.licences", label: "Subcontractor licence details" },
      ],
      outputs: [
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.out.buildup", label: "A tax build-up that reconciles" },
        { labelKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.out.covered", label: "Licensed scopes confirmed covered" },
      ],
      titleKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.title",
      titleDefault: "Read the tax and the licences back before the bid goes out",
      whatKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.what",
      whatDefault:
        "Before the bid leaves, read back the two things this case turns on: the pre-tax total with the two tax lines and the base each was taken on, and which firms hold a licence whose subclass covers the scope they were priced for.",
      whyKey: "cases.check_the_rbq_subclass_and_price_gst_and_qst.step.review.why",
      whyDefault:
        "A Quebec client checks both of those first, and both are far cheaper to correct while the bid is still yours. A tax computed the way Revenu Quebec computes it, and a licence that covers the work it was priced for, are what turn a week of evaluation correspondence into no correspondence at all.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
