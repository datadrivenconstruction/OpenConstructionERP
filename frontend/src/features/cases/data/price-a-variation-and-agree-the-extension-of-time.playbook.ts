// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a variation and agree the extension of time" (GB).
//
// One change, from the notice that preserves the entitlement to the order
// that closes it. JCT calls it a variation and a relevant event, NEC4 calls
// it a compensation event with a time bar, and both are decided on records
// taken while the work was happening. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-variation-and-agree-the-extension-of-time",
  order: 1165,
  region: "GB",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "project-manager"],
  roles: ["quantity-surveyor", "commercial-manager", "project-manager", "planner"],
  stage: "build",
  icon: "GitCompare",
  titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.title",
  titleDefault: "Price a variation and agree the extension of time",
  descKey: "cases.price_a_variation_and_agree_the_extension_of_time.desc",
  descDefault:
    "Notice the change while it is still a fact, price it the way the contract says to price it, prove the delay from records taken at the time, show it against the programme, and close it as an order and an agreed date rather than as a claim at the end.",
  longDescKey: "cases.price_a_variation_and_agree_the_extension_of_time.longdesc",
  longDescDefault:
    "JCT and NEC4 handle a change identically in substance and very differently in procedure. Under JCT the contract administrator issues an instruction, the work is valued under the valuation rules, and delay runs through a relevant event and an extension of time. Under NEC4 the same fact is a compensation event: notified inside a time bar, quoted, and assessed against the accepted programme with cost and time settled together. What both forms share is that the entitlement is won or lost by the records taken while the work was happening, not by the argument made afterwards. This case runs one change from notice to agreed order and posts it against the contract sum, so the final account is a running total rather than a reconciliation.",
  estMinutes: 20,
  steps: [
    {
      id: "notice",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.in.instruction", label: "Instruction or site event" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.in.aware", label: "Date you became aware" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.out.issued", label: "Notice issued and dated" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.out.register", label: "Change on the register" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.title",
      titleDefault: "Notice it while it is still a fact and not a claim",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.what",
      whatDefault:
        "Raise the notice as soon as the change appears, addressed to the party the contract names, carrying the date it was raised and the date a response is due. Under NEC4 this is the compensation event notification, and the quotation follows within three weeks of the project manager's instruction to quote; under JCT it is the notice of delay given forthwith, with particulars of the cause and its expected effect, which starts the extension of time running.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.notice.why",
      whyDefault:
        "Both forms make the notice the thing that preserves the entitlement, and NEC4 says so out loud: a compensation event not notified within eight weeks of the contractor becoming aware of it is generally not assessed at all. A notice raised on the day costs a minute; the same notice raised in the final account costs the entitlement.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.in.notice", label: "Notice issued and dated" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.in.rates", label: "Bill rates and dayworks" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.out.request", label: "Priced variation request" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.out.effect", label: "Cost and schedule effect" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.title",
      titleDefault: "Price it the way the contract says to price it",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.what",
      whatDefault:
        "Turn the notice into a variation request and price it: measured work at bill rates where the rates apply, pro rata where the character of the work is similar, and dayworks where neither fits. Record the effect on time alongside the effect on cost, because under NEC4 the two are assessed together.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.price.why",
      whyDefault:
        "The valuation rules exist so that a change is priced the same way whoever prices it, and the disputes happen exactly where somebody skipped them. Dayworks in particular are worth what the signed sheets say and nothing more, so a daywork record agreed on the day beats a well argued rate three months later.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "evidence",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.in.diary", label: "Diary entries for the period" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.in.corr", label: "Correspondence and RFIs" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.out.pack", label: "Evidence pack" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.out.order", label: "Sources listed in order" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.title",
      titleDefault: "Assemble the records that prove it",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.what",
      whatDefault:
        "Build the evidence pack out of what was already recorded: the diary entries for the days in question, the correspondence, the RFIs, the approvals and the earlier notices. The pack is ordered deterministically and carries a digest, so both sides can reproduce the same bundle.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.evidence.why",
      whyDefault:
        "An entitlement is decided on contemporaneous records, and contemporaneous means written while it was happening by somebody who did not yet know it would matter. A pack drawn from the diary and the correspondence is that. A narrative written afterwards from memory reads as advocacy even when every word of it is true.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "programme",
      icon: "GanttChartSquare",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.in.accepted", label: "Accepted programme" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.in.pack", label: "Evidence pack" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.out.delay", label: "Delay shown on the programme" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.out.eot", label: "Extension of time claimed" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.title",
      titleDefault: "Show the delay against the programme, not against the feeling",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.what",
      whatDefault:
        "Take the accepted programme and show what the event did to it: which activities moved, how much float was available to absorb it, and whether the completion date actually moved. That is the extension of time argument under JCT and the assessment of the compensation event under NEC4.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.programme.why",
      whyDefault:
        "Delay is a property of the critical path, and a job can lose three weeks on an activity that was never critical and still finish on time. Showing the effect on the programme separates an extension of time you are given from one you argue about, and it also tells you honestly when there is nothing here worth chasing.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "order",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.in.request", label: "Priced variation request" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.in.delay", label: "Delay shown on the programme" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.out.issued", label: "Variation order issued" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.out.granted", label: "Extension of time granted" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.title",
      titleDefault: "Close it as an order, not as an open item",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.what",
      whatDefault:
        "Convert the agreed request into a variation order carrying the final cost effect and the final effect on time, and record the extension of time decision with its cause: employer caused, neutral, contractor caused or concurrent.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.order.why",
      whyDefault:
        "An open variation is a number two parties each remember differently. Closing it fixes both halves at once, and recording the cause of the delay is what stops the same fact being re-argued at the final account under a different name and a fresh set of adjectives.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "sum",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.in.order", label: "Variation order issued" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.in.sum", label: "Contract sum before the change" },
      ],
      outputs: [
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.out.adjusted", label: "Adjusted contract sum" },
        { labelKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.out.closed", label: "Nothing left open on this change" },
      ],
      titleKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.title",
      titleDefault: "Carry it into the contract sum",
      whatKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.what",
      whatDefault:
        "Post the variation order against the contract so the adjusted contract sum moves with it, and let the next interim valuation pick it up. The final account is then the running total rather than an exercise in reconciliation.",
      whyKey: "cases.price_a_variation_and_agree_the_extension_of_time.step.sum.why",
      whyDefault:
        "A variation agreed but never posted is the commonest reason a final account comes as a surprise. Carrying each one into the contract sum as it is agreed keeps both parties working to the same number the whole way through, and turns the final account into a signature rather than a negotiation.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
