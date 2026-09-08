// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Settle the avans and release the guarantee retention" (RU).
//
// Record what the contract says about the advance and the retention, book the
// advance and the tax on it, set it off against every act at the agreed rate,
// keep the net payable on the statutory clock, release the retention against its
// real trigger and agree the closing balance. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "settle-the-avans-and-release-the-guarantee-retention",
  order: 1308,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "developer-client"],
  roles: ["commercial-manager", "accountant", "contract-administrator", "finance-manager"],
  region: "RU",
  icon: "Coins",
  titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.title",
  titleDefault: "Settle the avans and release the guarantee retention",
  descKey: "cases.settle_the_avans_and_release_the_guarantee_retention.desc",
  descDefault:
    "Record the advance and the retention the contract sets, book the advance and its tax, set it off against every act at the agreed rate, keep the net payable on the statutory clock, release the retention at its trigger and agree the closing balance.",
  longDescKey: "cases.settle_the_avans_and_release_the_guarantee_retention.longdesc",
  longDescDefault:
    "Two sums move in opposite directions across the life of a Russian contract. The advance arrives at the start and is recovered by deducting a share of every act until it is gone. The guarantee retention is withheld from every act and comes back only after the defects period has run. Between them sits NDS, charged on the advance when it is received and deducted again when the work it paid for is accepted, and whose standard rate became 22 percent on 1 January 2026 having been 20 percent before. A contract that ran across that date carries both rates, and which one a given document takes is settled by dates rather than by preference.",
  estMinutes: 13,
  steps: [
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.in.contract", label: "Signed contract" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.in.guarantees", label: "Bank guarantees held" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.out.advance", label: "Advance and recovery rate" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.out.retention", label: "Retention rate and release event" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.title",
      titleDefault: "Record the advance and the retention the contract sets",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.what",
      whatDefault:
        "Take from the contract the size of the advance and what it may be spent on, the rate at which it is recovered from each act, the retention percentage, the event that releases it and how long it is held, together with any bank guarantee standing in place of either of them.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.terms.why",
      whyDefault:
        "These two terms are negotiated once and then govern every payment for years. A retention rate remembered wrongly is an error repeated monthly, and an advance recovery schedule that was never written down is how a contractor reaches the end of a job still owing an advance against acts that have all been paid in full.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "advance",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.in.received", label: "Advance received" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.in.restriction", label: "Restriction on its use" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.out.booked", label: "Advance on the ledger" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.out.outstanding", label: "Balance still to recover" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.title",
      titleDefault: "Book the advance and the document that goes with it",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.what",
      whatDefault:
        "Raise the advance invoice with the schet-faktura on it and book the receipt as a payment against it, and where the contract restricts what the money may be spent on, keep that restriction with the contract record. The balance still to recover is not a figure the ledger carries: keep it as the running total you deduct from on each act, starting from the advance received.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.advance.why",
      whyDefault:
        "An advance is not revenue, it is money held against work not yet done, and the only figure that matters day to day is how much of it is still outstanding. On state contracts an advance is often ring-fenced to particular expenditure and monitored through the treasury, so spending it elsewhere is a breach quite apart from whether the work eventually gets done.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "vat",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.in.dates", label: "Date of receipt and of acceptance" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.in.rates", label: "Rates by effective period" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.out.rate", label: "Rate on each document" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.out.deduction", label: "Deduction on the advance" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.title",
      titleDefault: "Decide which NDS rate each document carries",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.what",
      whatDefault:
        "Set the rate that applies to the advance and to each act, and check which date decides it in each case: the day the advance was received for the advance, the day the work was accepted for the act. Keep the earlier rate available for documents that belong to an earlier period.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.vat.why",
      whyDefault:
        "The standard rate became 22 percent on 1 January 2026, having been 20 percent before that. A contract running across the change carries both, and the tax charged on an advance received at the old rate does not become the new rate because the act is signed later. A system that only knows today's rate will quietly restate history and put the return out.",
      moduleLabel: "Tax Rates",
      moduleLabelKey: "nav.tax_rates",
      to: "/tax-rates",
    },
    {
      id: "zachet",
      icon: "Split",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.in.act", label: "Certified act for the month" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.in.rates", label: "Recovery and retention rates" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.out.net", label: "Net payable" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.out.carried", label: "Advance carried forward" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.title",
      titleDefault: "Set the advance off against each act",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.what",
      whatDefault:
        "For every certified act, enter the retention on the invoice so the claim carries gross, retention and net, deduct the agreed share of the advance from what you claim and say so on the invoice, so the gross value, each deduction and the net payable read from one document. Carry the remaining advance forward so the next act starts from it.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.zachet.why",
      whyDefault:
        "The set-off is the reason both sides can reconcile at all, because the client's ledger has to show the advance shrinking at exactly the rate yours does. Where the two disagree it is almost always because one side applied the percentage to a different base, the gross act or the act after retention, and that gap grows quietly every single month.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "clock",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.in.net", label: "Net payable" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.in.event", label: "Event the term runs from" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.out.due", label: "Due date" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.out.interest", label: "Interest if it is late" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.title",
      titleDefault: "Put the net payable on the clock",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.what",
      whatDefault:
        "Send the net figure with the documents that support it and let the payment term run from the event the contract or the law names, which is the signing of the acceptance document rather than the day you got round to issuing the invoice.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.clock.why",
      whyDefault:
        "The deductions do not move the due date. On work under 44-FZ payment falls due within seven working days of the acceptance document being signed and interest on delay runs at a statutory rate, so the day the clock starts is the difference between a claim you can put a number on and a complaint you cannot.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "retention",
      icon: "KeyRound",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.in.withheld", label: "Retention accumulated" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.in.conditions", label: "Release conditions" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.out.released", label: "Retention released" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.out.remaining", label: "Amount still held" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.title",
      titleDefault: "Release the retention when its trigger actually arrives",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.what",
      whatDefault:
        "Track the accumulated retention against its release conditions, completion of the works, the end of the guarantee period, defects actually closed out, and release it against the condition that has been met rather than against a date somebody remembered.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.retention.why",
      whyDefault:
        "Retention is money already earned and held back, and it is the balance most often forgotten on a finished job, because by the time it falls due the project team has moved to the next one. The condition that releases it is usually not a date at all, it is the closing of the last defect, which means somebody has to still be watching.",
      moduleLabel: "Retention",
      moduleLabelKey: "finance.retention_tab",
      to: "/projects/:projectId/finance?tab=retention",
    },
    {
      id: "reconcile",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.in.ledger", label: "Your ledger for the contract" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.in.client", label: "Client's figures" },
      ],
      outputs: [
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.out.statement", label: "Signed reconciliation" },
        { labelKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.out.balance", label: "Agreed closing balance" },
      ],
      titleKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.title",
      titleDefault: "Agree the closing balance with the other side",
      whatKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.what",
      whatDefault:
        "Assemble the statement from the invoices and payments on this contract, acts certified, advance received and recovered, retention withheld and released, tax at each rate and every payment made, then set it against the figures the client is carrying and have the two sides agreed and signed.",
      whyKey: "cases.settle_the_avans_and_release_the_guarantee_retention.step.reconcile.why",
      whyDefault:
        "A signed akt sverki is what closes the contract as a financial matter, and it is the document any later dispute starts from. Left unagreed, the two ledgers stay a few percent apart for years, and the difference is usually one deduction taken on the wrong base far enough back that nobody can reconstruct which month it was.",
      moduleLabel: "Payments",
      moduleLabelKey: "finance.payments",
      to: "/projects/:projectId/finance?tab=payments",
    },
  ],
};

export default playbook;
