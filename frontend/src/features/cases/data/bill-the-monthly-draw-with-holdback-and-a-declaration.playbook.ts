// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Bill the monthly draw with holdback and a declaration" (CA).
//
// The objection here is the strongest one a Canadian office manager has, and it
// is largely correct: their spreadsheet does compute the draw. What it does not
// do is survive a release, because a percentage recomputed each month and a
// balance with a history stop agreeing the moment money comes back. So the case
// spends its effort on the three facts a net figure has already lost, and on
// the sworn declaration being drawn from the payment record it declares.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "bill-the-monthly-draw-with-holdback-and-a-declaration",
  order: 1101,
  region: "CA",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["accountant", "quantity-surveyor", "commercial-manager", "contract-administrator"],
  icon: "Banknote",
  titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.title",
  titleDefault: "Bill the monthly draw with holdback and a declaration",
  descKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.desc",
  descDefault:
    "Value the work for the month, show the certified amount and the 10 percent holdback as separate figures rather than as one net cheque, keep the held money as a running balance with a history, and swear the declaration against the subcontractor payment record it actually declares.",
  longDescKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.longdesc",
  longDescDefault:
    "The 10 percent statutory holdback in the common-law provinces is not a discount on the cheque and is not negotiable downward. It is money you have earned that somebody else is holding and that has to come back, which makes it an account rather than a percentage. A draw package built as one net figure has already thrown away the three facts you need to chase it: what was certified, what was held this period, and what is held in total. Ontario went further from 1 January 2026 and made annual release mandatory whatever the contract says and whatever the length of the completion schedule, with notice published on prescribed Form 6 within 14 days of each contract anniversary and payment falling between 60 and 74 days after the date of publication. A balance nobody can reconcile before the anniversary is a release nobody can claim after it.",
  estMinutes: 18,
  steps: [
    {
      id: "value",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.in.bill", label: "Contract bill and rates" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.in.done", label: "Work completed since the last draw" },
      ],
      outputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.out.valued", label: "Quantities valued for the period" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.out.lines", label: "A claim built line by line" },
      ],
      titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.title",
      titleDefault: "Value the work, do not estimate the percentage",
      whatKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.what",
      whatDefault:
        "Measure or agree the quantities completed since the last draw and price them against the contract rates, so the claim is built from work done rather than from a percentage that felt about right.",
      whyKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.value.why",
      whyDefault:
        "A claim the consultant can check line by line gets certified, because certifying it is defensible. A claim that arrives as one percentage of the contract opens a negotiation you are structurally going to lose, since the person on the other side has to justify every dollar they certify and you have given them nothing to justify it with.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "claim",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.in.valued", label: "Valued work for the period" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.in.rate", label: "Contract holdback rate" },
      ],
      outputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.out.certified", label: "Certified amount" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.out.held", label: "Holdback taken this period" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.out.payable", label: "Amount actually payable" },
      ],
      titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.title",
      titleDefault: "Show four numbers, not one",
      whatKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.what",
      whatDefault:
        "Raise the progress claim so it carries the value of work completed to date, the amount certified this period, the holdback taken at 10 percent and the amount payable, each as its own line derived from the one above it.",
      whyKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.claim.why",
      whyDefault:
        "The net cheque is the last number, not the first. A claim that shows only the net has discarded the two figures you will need the day the holdback falls due, and the party holding your money has no reason to reconstruct them for you.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "ledger",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.in.taken", label: "Holdback taken each period" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.in.released", label: "Releases already made" },
      ],
      outputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.out.balance", label: "Running holdback balance" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.out.history", label: "A release history you can audit" },
      ],
      titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.title",
      titleDefault: "Keep the holdback as a balance with a history",
      whatKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.what",
      whatDefault:
        "Record every holdback taken and every release against the contract, with its date and what it was against, so the held money reads as an account with a statement rather than as a percentage recomputed from the total each month.",
      whyKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.ledger.why",
      whyDefault:
        "Held money is a ledger, not a percentage. The month a release happens is the month a recomputed percentage and a real balance stop agreeing, and the gap between them leaves quietly. With annual release now mandatory in Ontario on a 14-day publication clock, the balance has to be right before the anniversary rather than reconstructed after it.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "subs",
      icon: "Users",
      inputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.in.certs", label: "Subcontract certificates and payments" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.in.held", label: "Amounts still held below" },
      ],
      outputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.out.record", label: "Reconciled subcontractor payment record" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.out.facts", label: "The facts the declaration will state" },
      ],
      titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.title",
      titleDefault: "Line up the payments the declaration will swear to",
      whatKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.what",
      whatDefault:
        "Pull the payment record for every subcontractor and supplier behind this claim: what was certified to them, what has been paid, and what is still held. Reconcile it before the declaration is drawn rather than after it is sworn.",
      whyKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.subs.why",
      whyDefault:
        "The declaration is a sworn statement about payments to the people below you, and whoever signs it is personally exposed if it is wrong. Checking a record you already keep takes minutes; assembling one from cheque stubs on the afternoon the draw is due is how a wrong number gets sworn to.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "package",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.in.parts", label: "Claim, holdback statement, payment record" },
      ],
      outputs: [
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.out.package", label: "Draw package issued" },
        { labelKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.out.declaration", label: "Declaration sworn against the record" },
      ],
      titleKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.title",
      titleDefault: "Issue the draw and the declaration as one package",
      whatKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.what",
      whatDefault:
        "Print the claim, the holdback statement and the subcontractor payment record as one package, draw the statutory declaration from that record instead of retyping it, on CCDC 9A where the contract is a CCDC form, and have it sworn and issued alongside the claim.",
      whyKey: "cases.bill_the_monthly_draw_with_holdback_and_a_declaration.step.package.why",
      whyDefault:
        "The declaration is a contract requirement rather than a requirement of the Act, which is why the payer is entitled to sit on the draw until it arrives and why arguing about it wastes a month. A package whose sworn statement and payment record are visibly the same numbers is a package nobody sends back for checking.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
