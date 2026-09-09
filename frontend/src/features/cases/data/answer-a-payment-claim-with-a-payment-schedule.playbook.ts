// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Answer a payment claim with a payment schedule" (NZ).
//
// The other half of the Construction Contracts Act 2002 regime, written for the
// party that RECEIVES claims rather than the one that serves them. A head
// contractor answering ten subcontractor claims a month lives on this side of
// it, and the failure mode is not a bad valuation, it is a good valuation that
// went out as an email instead of as a payment schedule, or went out one working
// day late. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "answer-a-payment-claim-with-a-payment-schedule",
  order: 1410,
  region: "NZ",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["contract-administrator", "commercial-manager", "quantity-surveyor", "accountant"],
  icon: "ReceiptText",
  titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.title",
  titleDefault: "Answer a payment claim with a payment schedule",
  descKey: "cases.answer_a_payment_claim_with_a_payment_schedule.desc",
  descDefault:
    "Log an incoming payment claim on the day it arrives, open the window the Act gives you to answer it, settle the scheduled amount, serve a payment schedule that says how you calculated it and why it differs, and watch the window on every other claim you are holding.",
  longDescKey: "cases.answer_a_payment_claim_with_a_payment_schedule.longdesc",
  longDescDefault:
    "The Construction Contracts Act 2002 does not punish a payer for disagreeing with a claim. It punishes a payer for saying nothing. If no payment schedule is provided within the time the contract requires, or within 20 working days of service where the contract is silent, the payer becomes liable to pay the amount that was claimed, and the claimant can recover it as a debt in court where a counterclaim or a set-off is no answer. That is the whole trap: the money is lost on the calendar rather than on the merits, and it is lost by a business that had a perfectly good reason it never wrote down in the form the Act asks for. A payment schedule is a short document with four things in it, and getting it out on time is a process question rather than a commercial one.",
  estMinutes: 12,
  steps: [
    {
      id: "receive",
      icon: "FolderInput",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.in.claim",
          label: "Incoming payment claim",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.in.contract",
          label: "Subcontract payment terms",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.out.dated",
          label: "Claim logged with its service date",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.out.status",
          label: "Whether it is a payment claim at all",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.title",
      titleDefault: "Log the claim on the day it is served",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.what",
      whatDefault:
        "File every incoming claim against its contract with the date and the manner it was served, and settle straight away whether the document is a payment claim under the Act: is it in writing, does it identify the work and the period, does it state a claimed amount and how it was calculated, and does it say it is made under the Act. Where the payer is a residential occupier, check as well that the prescribed notices the regulations require came with it.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.receive.why",
      whyDefault:
        "Every consequence in this case counts from the date of service, so the date is the single fact that must not be reconstructed later. Whether the document is a payment claim decides whether the count runs at all, and that question is far cheaper to answer on the day it lands than in the week the answer is already overdue.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "window",
      icon: "Clock",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.in.dated",
          label: "Claim logged with its service date",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.in.terms",
          label: "Response period the contract sets",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.out.answer",
          label: "Last day to answer",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.out.pay",
          label: "Date payment falls due",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.title",
      titleDefault: "Open the window you have to answer in",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.what",
      whatDefault:
        "Put the claim on the clock from the day it was served and read back two dates: the last day a payment schedule can be provided, and the day payment falls due. The contract's own period governs where it sets one; where it is silent the Act gives 20 working days for the schedule. Working days exclude weekends, public holidays and the year-end closedown, so a December claim does not answer on the same arithmetic as a June one.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.window.why",
      whyDefault:
        "The two dates are different questions and they are routinely confused. Missing the second is late payment, which costs interest and goodwill. Missing the first is losing the argument entirely, because the claimed amount then becomes payable whatever the work was actually worth. Naming both on the day the claim arrives is what keeps a busy month from turning the cheaper mistake into the expensive one.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "value",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.in.claim",
          label: "Claimed amount and its build-up",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.in.records",
          label: "Your own measure and records",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.out.scheduled",
          label: "Scheduled amount settled",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.out.calculation",
          label: "Manner of calculation written down",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.title",
      titleDefault: "Settle the scheduled amount and how you got there",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.what",
      whatDefault:
        "Work out what you say the period is worth, line by line against the claim, and write down the calculation as you go: the quantity you accept, the rate you applied, the retention withheld and any amount deducted. Keep the difference attached to the line it came from rather than as one adjustment at the bottom.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.value.why",
      whyDefault:
        "A payment schedule that certifies less than was claimed has to show the manner in which the payer calculated the scheduled amount, so the calculation is not working paper, it is part of the document. Built line by line it also survives adjudication, where a lump-sum reduction with no derivation reads as a payer who reduced the claim first and looked for reasons afterwards.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "serve",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.in.scheduled",
          label: "Scheduled amount settled",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.in.calculation",
          label: "Manner of calculation written down",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.out.served",
          label: "Payment schedule served",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.out.reasons",
          label: "Reasons for the difference recorded",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.title",
      titleDefault: "Serve a schedule that carries its reasons",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.what",
      whatDefault:
        "Issue the payment schedule in writing to the claimant. It has to identify the payment claim it answers and state the scheduled amount, and where that is less than the amount claimed it has to give the manner of calculation, the reason for the difference and, for anything being withheld, the reason for withholding it. Send it against the contract record so the sent copy and its date are kept, not just the draft.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.serve.why",
      whyDefault:
        "A schedule missing its reasons is treated as no schedule at all, which puts the payer in the same position as one who never answered. Note also that being unpaid yourself is not a reason the Act will hear: conditional payment provisions of the pay-when-paid kind are ineffective, so a subcontractor's money does not wait on the principal's.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "watch",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.in.open",
          label: "Claims still open",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.in.answer",
          label: "Last day to answer",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.out.due",
          label: "Answers falling due this week",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.out.owner",
          label: "Named owner for each one",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.title",
      titleDefault: "Watch every claim you are still holding",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.what",
      whatDefault:
        "Keep the answer dates for every open claim across every project on one list, each with the person who owes the schedule, and let it warn you a few days out rather than on the morning it expires. Include the claims you intend to certify in full, because those are the ones that get left in a tray.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.watch.why",
      whyDefault:
        "Nobody misses this deadline on a claim they are arguing about. It is missed on the routine ones, on the week somebody is on leave, and on the claim that arrived by an inbox nobody was reading. A list with an owner against each row is the only version of this that survives a busy month.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "exposure",
      icon: "AlertTriangle",
      inputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.in.unanswered",
          label: "Claims answered by nothing",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.in.scheduled",
          label: "Scheduled against claimed",
        },
      ],
      outputs: [
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.out.amount",
          label: "Amount at risk of becoming payable",
        },
        {
          labelKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.out.pattern",
          label: "Where answers keep running late",
        },
      ],
      titleKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.title",
      titleDefault: "Read what an unanswered claim would cost you",
      whatKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.what",
      whatDefault:
        "Read the gap between what was claimed and what was scheduled across the portfolio, next to the claims that have no schedule against them yet. The second number is the exposure: it is what becomes payable if the window closes, regardless of what the work was worth.",
      whyKey: "cases.answer_a_payment_claim_with_a_payment_schedule.step.exposure.why",
      whyDefault:
        "Boards understand this regime when it is a figure and not a rule. One project answering late is an administrative problem; the same figure repeated across six projects is a working capital risk, and it is the kind that arrives as a court filing rather than as a warning.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
