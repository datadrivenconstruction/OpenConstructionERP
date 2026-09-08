// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Amortise the anticipo before the last estimacion" (MX).
//
// Hand written, not composed. The MX progress-payment case treats the
// amortizacion as one line inside a monthly valuation, which is what it is
// once somebody has set it up correctly. This case is about setting it up
// correctly, because the anticipo is the single place a Mexican contractor
// most often loses track of what it has actually been paid: the money
// arrives at the start, it is spent on mobilisation, and the repayment is
// invisible for two years until the last estimacion cannot carry it.
//
// The anticipo is granted under the LOPSRM in parts with different purposes,
// site set up and the purchase of materials and permanently installed
// equipment, it is secured by a fianza for its whole amount, and it is
// repaid proportionally out of each estimacion rather than on a schedule
// somebody invents. The unamortised balance also sits outside ajuste de
// costos, which is where this case meets that one.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "amortise-the-anticipo-before-the-last-estimacion",
  order: 1265,
  region: "MX",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "developer-client"],
  roles: ["contract-administrator", "finance-manager", "commercial-manager"],
  icon: "Banknote",
  titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.title",
  titleDefault: "Amortise the anticipo before the last estimacion",
  descKey: "cases.amortise_the_anticipo_before_the_last_estimacion.desc",
  descDefault:
    "Record what the anticipo is for and what secures it, invoice it with its own CFDI, spend it on what it was granted for, take the amortizacion off every estimacion in proportion, and read the outstanding balance every period so the last one is not the one that discovers it.",
  longDescKey: "cases.amortise_the_anticipo_before_the_last_estimacion.longdesc",
  longDescDefault:
    "The anticipo is the friendliest money on a Mexican job and the easiest to mistake for income. It is granted under the LOPSRM in parts with named purposes, one for setting up on site and moving plant, another for buying materials and the equipment that will be installed permanently, and it is secured by a fianza de anticipo covering the whole of it until it has been repaid. It is repaid out of the estimaciones, proportionally, so a month that earns more repays more and a quiet month repays less. That proportionality is the part that gets replaced by a round monthly figure somebody agreed once, and a round figure is always either too small, which finishes the works still owing, or too large, which starves the job of the cash the anticipo existed to provide. Two more things follow the balance rather than the payment: the fianza cannot be cancelled while any of it is outstanding, and the unamortised part is outside ajuste de costos, because that money was already in your hands at the old prices.",
  estMinutes: 16,
  steps: [
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.in.contract",
          label: "Contract and its anticipo clause",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.in.fianza",
          label: "Fianza de anticipo as issued",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.out.parts",
          label: "Anticipo recorded with its purposes",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.out.rate",
          label: "Amortisation proportion on record",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.title",
      titleDefault: "Record what the anticipo is for and what secures it",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.what",
      whatDefault:
        "Put four things on the contract record: the amount of the anticipo, the parts it is granted in and the purpose of each, the fianza de anticipo that secures it, and the proportion at which it will be amortised, which follows from the anticipo against the contract amount rather than from a negotiation.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.terms.why",
      whyDefault:
        "Everything downstream reads these four numbers, and each of them lives in a different document today: the amount in the contract, the security with the insurer, the proportion in somebody's spreadsheet. Recorded once against the contract, the monthly amortizacion is computed rather than remembered, and the person who computes it in month nineteen does not have to have been there in month one.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "cfdi",
      icon: "ReceiptText",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.in.fianza",
          label: "Fianza delivered and accepted",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.in.amount",
          label: "Anticipo amount and IVA",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.out.cfdi",
          label: "CFDI for the anticipo, stamped",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.out.link",
          label: "Reference the estimaciones will relate to",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.title",
      titleDefault: "Invoice the anticipo with its own CFDI",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.what",
      whatDefault:
        "The anticipo is invoiced on its own CFDI when it is received, not netted quietly against the first estimacion. Record the UUID it was stamped with, because the CFDIs raised against later estimaciones have to relate back to it as the anticipo is consumed.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.cfdi.why",
      whyDefault:
        "Without that relationship the same peso is invoiced twice: once when the advance arrived and again inside the estimacion that repaid it. Both documents are stamped, both are real, and the excess is only found when somebody totals the year's CFDIs against the contract amount and gets a number larger than the contract.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "spend",
      icon: "Truck",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.in.anticipo",
          label: "Anticipo received, by part",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.in.plan",
          label: "Mobilisation and buying plan",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.out.orders",
          label: "Orders placed against the anticipo",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.out.trace",
          label: "Spend traceable to its purpose",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.title",
      titleDefault: "Spend it on what it was granted for",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.what",
      whatDefault:
        "Place the orders the anticipo was granted for and mark them as such: the site installations, offices and stores and the movement of plant against the first part; the materials and the permanently installed equipment against the second. Keep the spend traceable back to the part that funded it.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.spend.why",
      whyDefault:
        "The anticipo is granted for named purposes under the LOPSRM, and the convocante can ask what it went on. That question is easy in month two and impossible in month twenty. There is a commercial reason as well as an audit one: an anticipo spent on general cash flow leaves the works with the materials still unbought and the repayment already running.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "amortise",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.in.estimacion",
          label: "Estimacion for the period",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.in.rate",
          label: "Amortisation proportion",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.out.deduction",
          label: "Amortizacion for the period",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.out.net",
          label: "Net amount payable",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.title",
      titleDefault: "Take the amortizacion off in proportion, every period",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.what",
      whatDefault:
        "Apply the recorded proportion to what the estimacion earned and deduct that, so a period that measures more repays more. Show the amortizacion as its own line on the estimacion and on the CFDI raised against it, next to the fondo de garantia rather than merged with it.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.amortise.why",
      whyDefault:
        "A flat monthly deduction is the standard error and it fails in both directions. Too small and the works finish with the anticipo still outstanding, which turns the final estimacion into a debt; too large and it takes back the working capital the anticipo was granted to provide, in the months the job most needs it. Proportional repayment is self correcting and needs nobody to watch it.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "balance",
      icon: "Gauge",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.in.paid",
          label: "Amortizacion to date",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.in.granted",
          label: "Anticipo granted",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.out.outstanding",
          label: "Anticipo outstanding this period",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.out.projection",
          label: "Period it reaches zero",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.title",
      titleDefault: "Read the outstanding balance every period",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.what",
      whatDefault:
        "Put the anticipo granted next to the amortizacion taken to date and carry the difference forward as a running balance, with the period it is projected to reach zero. Compare that period against the programmed completion every month, not once a year.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.balance.why",
      whyDefault:
        "The balance is the only figure that answers what you have really been paid, and it is the one nobody prints, because the estimacion shows the month and the ledger shows the cash. It also governs two other things: the fianza de anticipo stays alive while any of it is outstanding, and the unamortised part sits outside ajuste de costos, so a claim computed over the whole certified value quietly overstates itself.",
      moduleLabel: "Event Reconciliation",
      moduleLabelKey: "nav.reconciliation",
      to: "/projects/:projectId/reconciliation",
    },
    {
      id: "close",
      icon: "Flag",
      inputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.in.balance",
          label: "Balance at the last estimacion",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.in.remaining",
          label: "Work left to certify",
        },
      ],
      outputs: [
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.out.zero",
          label: "Anticipo fully amortised",
        },
        {
          labelKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.out.release",
          label: "Fianza de anticipo clear to cancel",
        },
      ],
      titleKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.title",
      titleDefault: "Reach zero before the finiquito, not during it",
      whatKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.what",
      whatDefault:
        "Two or three periods out from completion, check that the remaining work is enough to absorb the remaining balance at the contract proportion. Where it is not, deal with it while there are still estimaciones to deal with it in, and take the settled balance into the finiquito rather than discovering it there.",
      whyKey: "cases.amortise_the_anticipo_before_the_last_estimacion.step.close.why",
      whyDefault:
        "An anticipo still outstanding when the works finish stops being an advance and becomes a debt, payable in cash rather than out of work, and it holds the fianza de anticipo open and its premium running. Found three periods early it is an adjustment to the amortisation; found at the finiquito it is a cheque.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
