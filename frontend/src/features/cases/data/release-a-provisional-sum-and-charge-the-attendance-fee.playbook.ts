// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Release a provisional sum and charge the attendance fee" (CN).
//
// A Chinese bill carries a section of items that are not measured work: sums
// the owner holds for scope that is not yet defined, packages that will be
// tendered separately, and the main contractor's fee for coordinating the
// specialists the owner appoints directly. They appear together and they behave
// as a set - the fee has a base only because the packages sit in the bill, and
// the sums only mean anything if the drawdowns against them are recorded.
//
// So the case is about the section as a structure rather than about a register
// in isolation. A provisional sum is held, drawn against as instructions issue,
// and its remaining balance is derived rather than stored, which is the only
// arrangement where the balance cannot go stale. Over-drawing is deliberately
// allowed and flagged rather than blocked, because a system that refuses to
// record what happened is a system people work around. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "release-a-provisional-sum-and-charge-the-attendance-fee",
  order: 1128,
  region: "CN",
  category: "commercial",
  stage: "procure",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client", "project-manager"],
  roles: ["quantity-surveyor", "commercial-manager", "procurement-buyer"],
  icon: "Coins",
  titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.title",
  titleDefault: "Release a provisional sum and charge the attendance fee",
  descKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.desc",
  descDefault:
    "Hold the owner's provisional sums in a register, carry the specialist packages in the bill so the coordination fee has something to be charged on, tender the package, draw down as it is let, and report what is left.",
  longDescKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.longdesc",
  longDescDefault:
    "The items that are not measured work are where a bill quietly stops adding up. A provisional sum is a real commitment of the owner's money against scope nobody has defined yet; a package to be tendered separately is a hole in the bill with a number in it; and the main contractor's coordination fee is a percentage that has to be charged on something specific rather than on the job. Each of the three is easy on its own and they go wrong together, because the fee's base and the sums' balances both depend on how the bill is structured. This case sets the structure first and then runs one sum through its life: held, tendered, let, drawn down, reported. The balance is always derived from the drawdowns rather than stored, so it cannot drift out of step with them, and drawing more than was held is recorded and flagged rather than refused - the register's job is to show you the position, not to prevent the project from having one.",
  estMinutes: 20,
  steps: [
    {
      id: "hold",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.in.bill", label: "Sums named in the bill" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.in.scope", label: "What each sum is for" },
      ],
      outputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.out.register", label: "Sums on the register" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.out.held", label: "Total held, visible" },
      ],
      titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.title",
      titleDefault: "Put every sum on the register with what it is for",
      whatKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.what",
      whatDefault:
        "Enter each sum the bill carries among its other items: the provisional sums the owner holds for scope and changes not yet defined, which are also the bill's contingency, and the provisional prices standing in for the materials, equipment and specialist packages to be priced later. Give each one the scope it covers, not just a figure.",
      whyKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.hold.why",
      whyDefault:
        "A sum with no stated scope gets drawn against for whatever is convenient, and by the time somebody asks what it was for the answer is a list of unrelated instructions. Writing the scope down at the start is what makes the drawdowns arguable later.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "structure",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.in.packages", label: "Directly appointed packages" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.in.rate", label: "The fee percentage" },
      ],
      outputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.out.section", label: "Its own section in the bill" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.out.scoped", label: "Fee scoped to that section" },
      ],
      titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.title",
      titleDefault: "Give the fee something to be charged on",
      whatKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.what",
      whatDefault:
        "Carry the packages and the sums in the bill as positions under a section of their own, then add the coordination fee as a markup scoped to that section rather than to the bill. A scoped markup applies to the position it names and everything under it, and can stand in for a bill-wide one where the two would otherwise both apply.",
      whyKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.structure.why",
      whyDefault:
        "The main contractor's fee for coordinating specialists the owner appoints directly, and for handling what the owner supplies, is a percentage on a defined part of the works and not on the job. If those packages live only in a register, the fee has no base and ends up as a number somebody agreed verbally. Build the section first and the fee is configuration; charge the fee first and it has nothing to compute on.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "tender",
      icon: "Truck",
      inputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.in.sum", label: "The sum being released" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.in.spec", label: "Scope now defined" },
      ],
      outputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.out.quotes", label: "Quotations on one scope" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.out.order", label: "Package let, at a real price" },
      ],
      titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.title",
      titleDefault: "Tender the package the sum was holding money for",
      whatKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.what",
      whatDefault:
        "Once the scope firms up, tender the package properly and let it; a package carried at a provisional price is tendered with the owner in the room, and jointly where the law requires a tender. The price it is let at is what actually gets drawn against the sum, not the sum itself.",
      whyKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.tender.why",
      whyDefault:
        "A provisional sum is an estimate of something nobody had designed, and the gap between the sum and the let price is money that belongs to somebody. Tendering it rather than converting it at book value is how that gap becomes visible while there is still a decision to make about it.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "draw",
      icon: "ArrowRightCircle",
      inputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.in.let", label: "Let price and instruction" },
      ],
      outputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.out.drawdown", label: "Drawdown recorded" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.out.remaining", label: "Remaining balance, derived" },
      ],
      titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.title",
      titleDefault: "Draw down against the sum as the work is released",
      whatKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.what",
      whatDefault:
        "Record a drawdown for the amount released and note which package it went to. The remaining balance is worked out from the drawdowns rather than stored, and drawing more than was held is recorded and flagged rather than refused.",
      whyKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.draw.why",
      whyDefault:
        "A stored balance goes stale the first time somebody edits a drawdown; a derived one cannot. And the moment a sum goes over is exactly the moment the project needs to see it rather than be stopped by it, because the work is usually already instructed by then and the conversation that matters is with the owner, not with the software.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.in.register", label: "Register with its drawdowns" },
      ],
      outputs: [
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.out.position", label: "Held, drawn and remaining" },
        { labelKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.out.fee", label: "Fee earned on the packages" },
      ],
      titleKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.title",
      titleDefault: "Report the position while it can still be acted on",
      whatKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.what",
      whatDefault:
        "Report what is held, what has been drawn, what remains against each sum, and the coordination fee the packages have earned. Take the unspent balances to the owner as part of the settlement conversation.",
      whyKey: "cases.release_a_provisional_sum_and_charge_the_attendance_fee.step.report.why",
      whyDefault:
        "An unspent provisional sum belongs back to the owner at final account, and it goes back because somebody put it on a schedule and asked. Reporting the balances monthly means that schedule already exists when the settlement starts, instead of being assembled from instructions at the point where every figure is contested.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
