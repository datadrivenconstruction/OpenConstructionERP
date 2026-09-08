// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Value the month and certify the progress payment" (CN).
//
// The monthly cycle on a Chinese project: the work is inspected and accepted,
// the period is valued against the contract's schedule of values, retention is
// held, the supervising side certifies, and the certified amount becomes a
// payable. The engine underneath is country-neutral - nothing on this screen is
// an American or a British form - so the case is about running the Chinese
// ritual through it rather than about a national layout.
//
// The last step is the one with real statutory content. The payment clock
// carries two Chinese regimes from the SME payment regulation: thirty calendar
// days where the buyer is a government organ or a public institution, sixty
// where it is a large enterprise, both owed to a small or medium-sized supplier.
// For a progress claim the clock runs from the date the parties confirmed the
// settlement amount, so that is the date to put on the application. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "value-the-month-and-certify-the-progress-payment",
  order: 1122,
  region: "CN",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "project-manager"],
  roles: ["quantity-surveyor", "commercial-manager", "contract-administrator", "finance-manager"],
  icon: "Banknote",
  titleKey: "cases.value_the_month_and_certify_the_progress_payment.title",
  titleDefault: "Value the month and certify the progress payment",
  descKey: "cases.value_the_month_and_certify_the_progress_payment.desc",
  descDefault:
    "Value one period against the contract's schedule of values from what the site actually completed, hold retention, have a second person certify it, land the certified amount in finance and put the statutory payment clock on it.",
  longDescKey: "cases.value_the_month_and_certify_the_progress_payment.longdesc",
  longDescDefault:
    "The monthly application is where a construction business either has cash or does not, and it fails in two ordinary ways: the percentages are typed from memory rather than taken from the site, and certification is a formality performed by the same person who prepared the claim. This case closes both. The valuation is pulled from progress that was recorded against accepted work, so the number answers to something; certification is a separate act under a separate permission, which is the structural half of the supervising engineer's signature; and the certified amount reaches finance as a payable without being re-entered. It ends on the payment clock because a due date nobody computed is a due date nobody can enforce, and because the Chinese regime that applies depends on who the buyer is rather than on what the contract says.",
  estMinutes: 22,
  steps: [
    {
      id: "sov",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.in.contract", label: "Signed contract" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.in.bill", label: "Coded bill of quantities" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.out.sov", label: "Schedule of values" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.title",
      titleDefault: "Set the schedule of values off the bill",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.what",
      whatDefault:
        "Open the contract and build its schedule of values from the bill's own items, carrying the code, the description, the unit, the quantity and the rate rather than a summarised version of them.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.sov.why",
      whyDefault:
        "Every month for the next two years is valued against this list. A schedule that summarises twelve bill items into one line saves an hour now and costs an argument every month afterwards, because nobody can show which part of the line was completed.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "accept",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.in.work", label: "Work completed in the period" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.out.accepted", label: "Work signed off as accepted" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.out.open", label: "Work held back" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.title",
      titleDefault: "Get the work accepted before you value it",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.what",
      whatDefault:
        "Record the period's inspections and note what was accepted and what was held back. Work that failed its inspection does not go into this month's valuation, and the inspection record is why.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.accept.why",
      whyDefault:
        "Acceptance is what a Chinese payment cycle is built on, and it decides what is allowed into this month's valuation at all. Claiming for work that has not passed is the fastest way to have the whole application sent back rather than the one line queried, and it is the inspection record that settles the argument about which it was.",
      moduleLabel: "Inspections",
      moduleLabelKey: "inspections.title",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "progress",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.in.site", label: "What the site reported" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.in.accepted", label: "Accepted work" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.out.pct", label: "Percent complete per item" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.title",
      titleDefault: "Record the period's progress against the work",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.what",
      whatDefault:
        "Record what was completed in the period as progress against the work items, so the percentages exist before anyone opens the application rather than being decided while filling it in.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.progress.why",
      whyDefault:
        "A percentage typed straight into a payment application is an opinion; the same percentage recorded against observed work is a measurement. The difference is invisible in the month you do it and decisive in the month somebody disputes it.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "value",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.in.sov", label: "Schedule of values" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.in.pct", label: "Recorded progress" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.out.claim", label: "Valued application" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.out.totals", label: "Gross, retention, prior, net due" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.title",
      titleDefault: "Value the period rather than type it",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.what",
      whatDefault:
        "Open the period's application and populate the percent complete from the progress you just recorded. Each line gets this period's quantity, this period's value and the running total; the header keeps gross, retention held, previously settled and net due recomputing as you go.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.value.why",
      whyDefault:
        "Retention is the deduction the application holds for you, and the national rules cap the quality retention at three percent of the settlement total, so holding it in the same document as the valuation is what stops the two drifting apart. Anything else your contract deducts - advance payment recovery, owner-supplied material, site utilities, the wage account carve-out - is yours to apply, and you should agree those figures with the other side in the same conversation as the valuation, not after it.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "certify",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.in.submitted", label: "Submitted application" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.out.certified", label: "Certified amount" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.out.trail", label: "Who certified, and when" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.title",
      titleDefault: "Let a second person certify it",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.what",
      whatDefault:
        "Submit the application, then have it certified by somebody other than the person who prepared it. Certification is a separate action under a separate permission, and rejection back to the preparer is available while it is still submitted.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.certify.why",
      whyDefault:
        "The supervising engineer's signature on a Chinese payment is the moment the amount stops being a request and becomes a certified figure, and the structural part of that ritual is that a different person performs it, on the record, at a known time. One person preparing and approving their own application is the control failure auditors look for first.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "invoice",
      icon: "ReceiptText",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.in.certified", label: "Certified amount" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.out.payable", label: "Payable in finance" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.out.vat", label: "VAT carried per line" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.title",
      titleDefault: "Carry the certified amount into finance",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.what",
      whatDefault:
        "The certified amount lands in finance as a payable without being re-entered. Raise the invoice against it with the tax rate on each line, nine percent for construction services under the general method or three percent where the project runs on the simplified method, and keep the fapiao you issue to the buyer tied to the same record.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.invoice.why",
      whyDefault:
        "In China the buyer generally cannot process the money until the fapiao is in hand, so the tax invoicing chain is part of the payment cycle rather than an accounting afterthought. Re-keying the certified figure into a separate ledger is where a transposed digit becomes a payment nobody can reconcile at year end.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "clock",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.in.application", label: "The payment application" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.in.confirmed", label: "Date the amount was confirmed" },
      ],
      outputs: [
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.out.final", label: "Final date for payment" },
        { labelKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.out.breach", label: "A late payment that is visible" },
      ],
      titleKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.title",
      titleDefault: "Put the statutory clock on the payment",
      whatKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.what",
      whatDefault:
        "Open a clock over the application, but check first that a statutory one reaches you at all. The two Chinese regimes turn on who is owed: both cover a sum owed to a small or medium-sized supplier, giving thirty calendar days when the buyer is a government organ or a public institution and sixty when it is a large enterprise. Where both sides are large enterprises no statutory period applies and the contract's own dates govern, so read the clock off the contract rather than expecting one to be computed. For a progress claim the period runs from the date both parties confirmed the settlement amount, so enter that date as the application date rather than the date you posted the paperwork.",
      whyKey: "cases.value_the_month_and_certify_the_progress_payment.step.clock.why",
      whyDefault:
        "Chasing late money starts with knowing exactly when it became late, and the regulation counts calendar days from a date that is easy to lose. Where your contract agrees a different period, put the agreed final date on the application instead: a public-sector clock cannot be extended past sixty days, and a private-sector one has to be reasonable rather than merely written down.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
  ],
};

export default playbook;
