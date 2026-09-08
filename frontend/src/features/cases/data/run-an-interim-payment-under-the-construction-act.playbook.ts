// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run an interim payment under the Construction Act" (GB).
//
// The statutory sequence, run once end to end: due date, payment notice, pay
// less notice, final date, and the section 111 consequence of missing one.
// The point of the case is that the sum payable is derived from the notices
// that were actually served, not from the valuation everybody remembers.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-an-interim-payment-under-the-construction-act",
  order: 1163,
  region: "GB",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "developer-client"],
  roles: ["quantity-surveyor", "commercial-manager", "contract-administrator"],
  stage: "build",
  icon: "Scale",
  titleKey: "cases.run_an_interim_payment_under_the_construction_act.title",
  titleDefault: "Run an interim payment under the Construction Act",
  descKey: "cases.run_an_interim_payment_under_the_construction_act.desc",
  descDefault:
    "Value the work for the period, open the clock the statute imposes, record every notice as it is served, read what the notified sum actually is, and check the retention as it is held rather than as it is remembered.",
  longDescKey: "cases.run_an_interim_payment_under_the_construction_act.longdesc",
  longDescDefault:
    "The Housing Grants, Construction and Regeneration Act 1996, as amended by the 2009 Act, gives every construction contract in Britain a payment timetable, and the sequence is the whole of it. There is a due date, a payment notice five days after it, a pay less notice up to seven days before the final date, and the final date itself. Section 111 is what gives it teeth: the notified sum must be paid in full by the final date unless a valid pay less notice was served in time, and where the payer served no payment notice at all, the sum the payee applied for becomes the notified sum. This case runs one interim application through that sequence so the deadlines are known before they pass rather than reconstructed from emails afterwards.",
  estMinutes: 18,
  steps: [
    {
      id: "value",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.in.measured", label: "Measured work this period" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.in.lines", label: "Contract lines and rates" },
      ],
      outputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.out.valuation", label: "Interim valuation" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.out.application", label: "Payment application issued" },
      ],
      titleKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.title",
      titleDefault: "Value the work for the period",
      whatKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.what",
      whatDefault:
        "Raise the interim valuation as a progress claim against the contract: the gross value of work properly executed, materials on site where the contract allows them, less retention and less what was certified previously.",
      whyKey: "cases.run_an_interim_payment_under_the_construction_act.step.value.why",
      whyDefault:
        "The application is the document the whole clock is measured from, so its date and its content matter more than how it looks. A valuation assembled from the contract lines rather than typed in as a single figure is also the only version that can be checked line by line when somebody disputes it three weeks later.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "open",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.in.application", label: "Payment application issued" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.in.period", label: "Period end date" },
      ],
      outputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.out.dates", label: "Statutory dates computed" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.out.clock", label: "Payment clock open" },
      ],
      titleKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.title",
      titleDefault: "Open the clock the statute imposes",
      whatKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.what",
      whatDefault:
        "Open a payment clock over the application under the United Kingdom regime. The due date, the payment notice deadline, the pay less deadline and the final date for payment are computed from the Act and the Scheme, counting days the way the statute counts them rather than the way a calendar app would. Where the contract fixes nothing the Scheme's defaults apply: the due date seven days after the end of the period or the claim, whichever is later, the payment notice five days after the due date, the pay less notice seven days before the final date, and the final date seventeen days after the due date.",
      whyKey: "cases.run_an_interim_payment_under_the_construction_act.step.open.why",
      whyDefault:
        "Nobody argues about a payment timetable until the week it matters, and by then the dates are being reconstructed from a mailbox. Computing them the day the application goes in means the argument that follows is about the valuation, which is a proper argument, rather than about which Tuesday something fell due.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "notices",
      icon: "Send",
      inputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.in.payment", label: "Payment notice served" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.in.payless", label: "Pay less notice and its basis" },
      ],
      outputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.out.record", label: "Notices on record with dates" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.out.late", label: "Late or invalid notices flagged" },
      ],
      titleKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.title",
      titleDefault: "Record every notice as it is served",
      whatKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.what",
      whatDefault:
        "Record the payment notice when it arrives, with the sum notified and the basis on which it was calculated. Record a pay less notice the same way, with the ground for withholding stated, and record it even when it was served late, because that is the fact which decides the sum.",
      whyKey: "cases.run_an_interim_payment_under_the_construction_act.step.notices.why",
      whyDefault:
        "A pay less notice that states no basis of calculation is not a valid pay less notice, and one served inside the seven days before the final date is out of time. Recording what actually happened, rather than what should have happened, is what turns the sum payable into a matter of record instead of a matter of opinion.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "sum",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.in.record", label: "Notices on record with dates" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.in.applied", label: "Applied sum" },
      ],
      outputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.out.notified", label: "Notified sum" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.out.exposure", label: "Exposure where a notice was missed" },
      ],
      titleKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.title",
      titleDefault: "Read the notified sum before you pay or chase",
      whatKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.what",
      whatDefault:
        "Read what the clock says is payable and read the derivation beside it. Where a valid payment notice was served in time the notified sum is the notified amount. Where the payer served nothing, the sum applied for is the notified sum, and the payee may serve its own default payment notice under section 110B, which pushes the final date out by the days the payer was late.",
      whyKey: "cases.run_an_interim_payment_under_the_construction_act.step.sum.why",
      whyDefault:
        "This is the part that surprises people. A missed payment notice does not shave a little off the payer's position, it hands the payee the full sum applied for, and the only escape left is a valid pay less notice served in time. Reading the derivation rather than assuming it is the difference between a payment and an adjudication you were always going to lose.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "retention",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.in.valuation", label: "Interim valuation" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.in.terms", label: "Contract retention terms" },
      ],
      outputs: [
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.out.ledger", label: "Retention ledger" },
        { labelKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.out.release", label: "Release dates in sight" },
      ],
      titleKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.title",
      titleDefault: "Check the retention as it is held, not as it is remembered",
      whatKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.what",
      whatDefault:
        "Open the retention ledger and read what has been scheduled, held and released against each counterparty, on this application and cumulatively. The figures come off the contracts rather than out of a spreadsheet one person keeps.",
      whyKey: "cases.run_an_interim_payment_under_the_construction_act.step.retention.why",
      whyDefault:
        "Retention accumulates quietly on every valuation and is the money nobody chases until the job is over. A ledger that shows the held total per counterparty makes the half you owe and the half you are owed two separate questions, and both of them have an answer ready before anybody asks.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
