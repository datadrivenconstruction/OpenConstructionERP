// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Close out from substantial performance to the final account" (CA).
//
// The objection is "closeout is a legal matter, not a software matter", and it
// is half right. Closeout IS a legal matter, and a legal matter with four dated
// consequences hanging off one certified date is exactly the shape software is
// for. Quebec is named as a contrast rather than folded in: there is no
// statutory holdback of this kind there and the security is a legal hypothec,
// which must never be called a lien. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "close-out-from-substantial-performance-to-the-final-account",
  order: 1107,
  region: "CA",
  category: "handover",
  companyTypes: ["general-contractor", "project-manager", "cost-consultant"],
  roles: ["contract-administrator", "quantity-surveyor", "project-manager", "commercial-manager"],
  icon: "Milestone",
  titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.title",
  titleDefault: "Close out from substantial performance to the final account",
  descKey: "cases.close_out_from_substantial_performance_to_the_final_account.desc",
  descDefault:
    "Certify and date substantial performance once, put every consequence that runs from it onto one register, price the deficiency list so the reserve is money rather than a checklist, and reconcile a final account whose every line can be walked backwards.",
  longDescKey: "cases.close_out_from_substantial_performance_to_the_final_account.longdesc",
  longDescDefault:
    "Substantial performance is one date with a tree of consequences under it. It starts a publication deadline, it starts the period during which security can still be claimed against the project, it makes the holdback releasable, and it fixes the point deficiencies are reckoned from. Most firms track those four in four places and reconcile them from memory, which works until the month somebody is away. Quebec is genuinely different rather than differently worded: there is no statutory holdback of this kind, and the security is a legal hypothec whose notice must be registered in the land register within 30 days following the end of the work and served on the owner, with no extension and no exception, where the end of the work means the work called for in the plans and specifications is complete and not that the minor deficiencies have been corrected. Calling that mechanism a lien is the fastest way to tell a Quebec client you have not worked there.",
  estMinutes: 22,
  steps: [
    {
      id: "certify",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.in.state", label: "State of the work" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.in.cert", label: "Consultant certification" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.out.dated", label: "Certified date on record" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.out.evidence", label: "The evidence it rests on" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.title",
      titleDefault: "Certify the date once, and only once",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.what",
      whatDefault:
        "Record substantial performance as a dated, certified event with the signature behind it, and attach the certificate together with the record of the state of the work it was certified against. On a CCDC 2 (2020) contract record Ready-for-Takeover as a second dated milestone: it is a contractual test rather than the statutory one, and the one-year warranty runs from it.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.certify.why",
      whyDefault:
        "Everything downstream counts from this date, so it has to be one date with a document behind it rather than a date three people remember slightly differently. The version that ends up challenged is always the one nobody can produce on the day it is questioned.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "construction_control.title",
      to: "/projects/:projectId/construction-control",
    },
    {
      id: "consequences",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.in.date", label: "The certified date" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.in.rules", label: "The provincial rules that apply" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.out.dated", label: "Every consequence dated" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.out.one", label: "One register instead of four" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.title",
      titleDefault: "Put every consequence on one register",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.what",
      whatDefault:
        "Enter the obligations that run from the certified date against it: publication of the notice, the period in which security can still be claimed, the holdback release, and the date deficiencies are reckoned from. Count each one on the rules of the province the work is in.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.consequences.why",
      whyDefault:
        "Four consequences tracked in four places are four chances to miss one, and the one that gets missed is always the one with no invoice attached to remind you. A single register in date order is also what lets somebody cover for you without being briefed.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "deficiencies",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.in.items", label: "Outstanding and defective work" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.in.rates", label: "Rates to complete or correct" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.out.priced", label: "Priced deficiency list" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.out.reserve", label: "A reserve with a number on it" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.title",
      titleDefault: "Price the deficiency list so the reserve is money",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.what",
      whatDefault:
        "Value each outstanding item at what it will cost to complete or correct, and total the list as the reserve to be held against release rather than reporting it as a count of open items.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.deficiencies.why",
      whyDefault:
        "A deficiency list is a claim about money and a checklist is a claim about tidiness. Releasing against a count treats ninety small items and one expensive one as ninety-one, and the expensive one is the entire reason the release is being argued about.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "release",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.in.balance", label: "Holdback balance" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.in.reserve", label: "Priced deficiency reserve" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.out.recorded", label: "Release recorded with its date" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.out.reconciled", label: "A balance that still reconciles" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.title",
      titleDefault: "Release the holdback less the reserve, and record it",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.what",
      whatDefault:
        "Record the release against the contract for the holdback balance less the valued deficiency reserve, so the ledger shows what was held, what was released, on what date, and against what.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.release.why",
      whyDefault:
        "The release is the moment a balance and a recomputed percentage stop being the same number, and only writing the release down as a transaction keeps them together. A release nobody recorded is one both sides will later compute differently and each be certain about.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "account",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.in.parts", label: "Contract price, changes, releases, deductions" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.out.final", label: "Final account, every line traceable" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.out.walkback", label: "A figure that can be walked back" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.title",
      titleDefault: "Reconcile the final account line by line",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.what",
      whatDefault:
        "Build the final account from the original contract price, every approved change with its code, holdback released, deficiency deductions and any credits, so that each line points at the transaction that produced it.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.account.why",
      whyDefault:
        "A final account is agreed when the other side can check it, not when it is delivered. One that can be walked backwards to its transactions settles in a meeting; one that arrives as a total settles in a negotiation, and the negotiation is where the last few percent of the job goes.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "close",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.in.records", label: "Final account and supporting records" },
      ],
      outputs: [
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.out.package", label: "Closeout package issued" },
        { labelKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.out.file", label: "A file that survives the team" },
      ],
      titleKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.title",
      titleDefault: "Issue the closeout package and keep the file copy",
      whatKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.what",
      whatDefault:
        "Issue the final account together with the certified date, the deficiency list and its status, the holdback release and the warranties, as one package to the client and one record to your own file.",
      whyKey: "cases.close_out_from_substantial_performance_to_the_final_account.step.close.why",
      whyDefault:
        "The package is what the client's finance department needs before it can pay, and the file copy is what you need when a security claim or a deficiency argument arrives eighteen months later, by which time everyone who did the work has moved to another job.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
