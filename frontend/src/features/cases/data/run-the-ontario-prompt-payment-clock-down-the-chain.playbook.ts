// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run the Ontario prompt-payment clock down the chain" (CA, Ontario).
//
// This case is Ontario and says so, because the statutory clock it runs is
// Ontario's. The split down the middle of it is deliberate: the owner-to-
// contractor clock is computed from the regime, and the seven-day pass-through
// to each tier below is not, which the regime's own notes state in as many
// words. So the computed dates and the entered dates sit on different screens
// and the copy never implies the clock cascades by itself. Wording follows the
// field names the screen shows rather than the sentence the statute uses: the
// due date is the day of receipt, and 28 days is the final date for payment.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-the-ontario-prompt-payment-clock-down-the-chain",
  order: 1100,
  region: "CA",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["accountant", "commercial-manager", "contract-administrator", "finance-manager"],
  icon: "CalendarClock",
  titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.title",
  titleDefault: "Run the Ontario prompt-payment clock down the chain",
  descKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.desc",
  descDefault:
    "Issue an invoice that meets the proper-invoice requirements, open a statutory clock on the day it is received so the notice and payment dates are computed rather than counted by hand, put the seven-day pass-through you owe each tier below on the same register, and keep every notice on record with the date it was served.",
  longDescKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.longdesc",
  longDescDefault:
    "Ontario's Construction Act has run a prompt-payment regime since 1 October 2019, with major amendments in force from 1 January 2026, and its timelines are mandatory: section 6.9 applies the whole Part notwithstanding any other agreement, so a contract cannot lengthen them. The shape is one date and a tree of consequences. A proper invoice is defined by statute and is deemed proper unless the owner objects in writing within seven days saying what has to be corrected. Payment falls due on receipt of that invoice, the final date for payment is 28 calendar days later, and the owner has 14 calendar days to serve a notice of non-payment stating the amount withheld and the reasons. Miss that 14-day window and the invoice must be paid in full, which is the whole leverage of the scheme. Every reference to days in this Part is to calendar days rather than business days. Once paid, a contractor has seven days to pay each subcontractor, and that seven-day step repeats at every lower tier with its own notice sequence. Work in Alberta, Saskatchewan, Manitoba or British Columbia falls under that province's own Act or, where none is yet in force, under the terms of its own contract, and those count differently, so pick the regime your contract actually falls under before relying on any date.",
  estMinutes: 18,
  steps: [
    {
      id: "invoice",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.in.work", label: "Work measured for the period" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.in.terms", label: "Contract number and payment terms" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.out.issued", label: "Invoice issued and dated" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.out.receipt", label: "Date of receipt on record" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.title",
      titleDefault: "Issue an invoice that cannot be sent back",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.what",
      whatDefault:
        "Raise the payment application for the period and check it carries everything a proper invoice has to carry before it leaves: your name and address, the date and the period it covers, the contract it is drawn under and its number, a description and quantity of the work done, the amount and the payment terms, the name and contact details of the person payment is to be sent to, and anything else the contract adds to the list. Record the date it was received, not the date it was written.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.invoice.why",
      whyDefault:
        "The clock starts on receipt of a proper invoice, so a missing element does not delay payment by a few days, it stops the clock from ever starting. The owner has seven days to object in writing and say what has to be corrected, and an invoice nobody objects to inside that window is deemed proper. Getting the elements right is the cheapest work in this whole case.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "clock",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.in.received", label: "Date the invoice was received" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.in.regime", label: "The Ontario Construction Act regime" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.out.computed", label: "Notice and payment dates computed" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.out.basis", label: "The statute each date rests on" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.title",
      titleDefault: "Open a clock on the day the invoice lands",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.what",
      whatDefault:
        "Open a payment clock over the application, pick the Ontario Construction Act regime, and enter the day of receipt as the application date. The due date is that same day, the final date for payment comes back 28 calendar days out, and the payment notice deadline comes back 14 calendar days out, each carrying the section it rests on.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.clock.why",
      whyDefault:
        "The date the invoice arrived is the only fact here and everything after it is arithmetic somebody has to do, usually three weeks later and under pressure. A window that crosses a long weekend is exactly where an honest hand count goes wrong, and these are calendar days rather than business days, which is the assumption most often carried in from another market.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "passdown",
      icon: "Workflow",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.in.paid", label: "The day the payment reached you" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.in.subs", label: "Subcontractors under this claim" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.out.tier", label: "Seven-day dates owed to each tier" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.out.register", label: "Owed and owing on one register" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.title",
      titleDefault: "Put the seven days you owe below on the register",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.what",
      whatDefault:
        "Once the owner's payment reaches you, enter the date you owe each subcontractor, seven days on from the day you were paid, as a deadline against this claim. Enter it yourself: the statutory clock computes what the owner owes you, and the tier below it is a separate obligation with its own dates.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.passdown.why",
      whyDefault:
        "The chain does not restart at each tier, it cascades, and the seven days start from the day the money reached you rather than from the day you get round to the run. Putting what you owe on the same register as what you are owed is what makes the gap between the two visible, and that gap is your working capital.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "flowdown",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.in.subs", label: "Subcontracts under this claim" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.in.terms", label: "Payment terms of the contract above" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.out.aligned", label: "Terms written from one event" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.out.default", label: "No default on a date you never chose" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.title",
      titleDefault: "Write the subcontracts to run from the same event",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.what",
      whatDefault:
        "Open the subcontracts sitting under this claim and check that their payment terms run from the same event as the contract above rather than from a monthly cycle of their own, so the day you are paid is the day the seven days below start.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.flowdown.why",
      whyDefault:
        "A subcontract that pays on its own cycle puts you in default on a date you never chose, and the statute does not care what the subcontract says, because these timelines apply notwithstanding any other agreement. The trade below you is not waiting on your goodwill, it is waiting on a date the Act already fixed.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "notices",
      icon: "Send",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.in.due", label: "The obligation that fell due" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.in.reason", label: "The amount withheld and why" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.out.served", label: "Notice served with a date" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.out.thread", label: "Thread carrying the reply" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.title",
      titleDefault: "Serve every notice in writing, from one place",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.what",
      whatDefault:
        "Send the objection, the notice of non-payment or the undertaking to adjudicate from the correspondence register so it carries a date, a named recipient and a copy, and file the reply against the same thread.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.notices.why",
      whyDefault:
        "The scheme turns on whether a notice was given, to whom and when. A notice of non-payment served late is no notice at all and the proper invoice must then be paid in full, so the date of service is worth more than the wording. A notice sent from somebody's own mailbox is one you cannot prove, and when two firms disagree about a date the one that cannot prove service is the one that pays.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "register",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.in.obligations", label: "Dated obligations across projects" },
      ],
      outputs: [
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.out.owed", label: "What is owed and when" },
        { labelKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.out.page", label: "A page the money meeting can act on" },
      ],
      titleKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.title",
      titleDefault: "Read the whole chain on one page",
      whatKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.what",
      whatDefault:
        "Report what is owed to you and what you owe in date order, across every project and every tier, and take that page into the weekly money meeting rather than a set of aged balances.",
      whyKey: "cases.run_the_ontario_prompt_payment_clock_down_the_chain.step.register.why",
      whyDefault:
        "Cash on a construction job is a chain of dates rather than a balance, and an aged debtor report tells you what has already gone wrong. The firm that can see the whole chain at once is the one that stops financing the tier above it out of its own working capital, which is where most of the interest in this industry is quietly paid.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
