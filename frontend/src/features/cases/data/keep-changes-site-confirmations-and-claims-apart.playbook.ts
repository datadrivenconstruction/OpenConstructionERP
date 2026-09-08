// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep changes, site confirmations and claims apart" (CN).
//
// Chinese site practice separates three instruments that a lot of contract
// administration elsewhere blurs into one word. An instructed change to the
// works is issued and priced. A site confirmation is a record of work or an
// event, signed on site on the day precisely so it can be priced later. A claim
// is a demand for time or money under the contract, and it lives or dies on
// notice and evidence rather than on agreement.
//
// They travel differently, they are signed by different people at different
// moments, and money is lost when one is filed as another - a site confirmation
// nobody signed on the day is worth nothing later, and a claim raised as a
// change order skips the notice the contract required. This case gives each one
// its own register and keeps the paper trail behind them separate. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-changes-site-confirmations-and-claims-apart",
  order: 1123,
  region: "CN",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "project-manager", "cost-consultant"],
  roles: ["contract-administrator", "commercial-manager", "site-manager", "quantity-surveyor"],
  icon: "Split",
  titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.title",
  titleDefault: "Keep changes, site confirmations and claims apart",
  descKey: "cases.keep_changes_site_confirmations_and_claims_apart.desc",
  descDefault:
    "Record the event on the day it happens, then route it to the right instrument: an instructed change that gets priced, a site confirmation signed on site and priced later, or a claim that needs notice and evidence.",
  longDescKey: "cases.keep_changes_site_confirmations_and_claims_apart.longdesc",
  longDescDefault:
    "Three different pieces of paper cover the ground between what was contracted and what was built, and the commonest commercial loss on a site is filing one of them as another. An instructed change is authorised before the work and priced against the contract's rates. A site confirmation records that something happened - extra excavation in unexpected ground, a stoppage, plant standing - and is signed on the day by whoever was there, because its whole value is that a signature exists from before anyone knew what it would be worth. A claim asks for time or money the contract puts at the other party's risk, and the contract almost always attaches a time bar to it. This case walks the same event through the register it actually belongs in, and keeps the day's record underneath all three.",
  estMinutes: 18,
  steps: [
    {
      id: "record",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.in.event", label: "What happened on site" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.in.photos", label: "Photographs from the day" },
      ],
      outputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.out.entry", label: "Dated diary entry" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.out.present", label: "Who was present" },
      ],
      titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.title",
      titleDefault: "Write it down on the day, before it is worth anything",
      whatKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.what",
      whatDefault:
        "Record the event in the daily diary the day it happens: what was found or instructed, where, who was on site, what plant and labour were affected, with photographs attached.",
      whyKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.record.why",
      whyDefault:
        "The record made before anybody knows what it is worth is the one nobody can argue with, and it is the same record whichever of the three instruments the event turns into. A diary written up at the end of the month is a reconstruction, and everybody reading it can tell.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "instructed",
      icon: "FilePlus2",
      inputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.in.instruction", label: "The instruction" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.in.rates", label: "Contract rates" },
      ],
      outputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.out.co", label: "Priced change order" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.out.reason", label: "Reason on the record" },
      ],
      titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.title",
      titleDefault: "Raise the instructed change and price it",
      whatKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.what",
      whatDefault:
        "Where the work was instructed, raise a change order, state the reason it arose, and price its lines in the order the valuation code sets: the contract's rate where one applies, an adjusted similar rate where one is close, and market evidence where there is neither. Name the instruction and the day it was diarised in the reason, so the record points back at itself.",
      whyKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.instructed.why",
      whyDefault:
        "An instructed change is the cheapest of the three to settle because the authority for it is not in dispute. What is in dispute a year later is the reason it arose and the rate it was priced at, so both belong on the record now, while the person who knows them is still on the job.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "confirmation",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.in.entry", label: "The day's record" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.in.measure", label: "Quantities as done" },
      ],
      outputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.out.entry", label: "Site confirmation on the register" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.out.open", label: "Priced later, tracked meanwhile" },
      ],
      titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.title",
      titleDefault: "Register the site confirmation while it is still unpriced",
      whatKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.what",
      whatDefault:
        "Where the work was done on site without a priced instruction, register it as a daywork sheet with the quantities as executed and the date the work was done. Record who signed it on site and the reference the signed paper carries, and hold the sheet at draft or disputed until the value is agreed.",
      whyKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.confirmation.why",
      whyDefault:
        "Under the 2024 standard a site confirmation is the signed acknowledgement by both site representatives of an event one party is responsible for, and the work itself is new work the owner has to instruct in writing; the 2013 code's seven-day report and forty-eight-hour confirmation are gone, so the deadlines are the contract's own. A site confirmation is signed on the day exactly so that the pricing conversation can happen afterwards without reopening the facts. If it sits in a folder unregistered until settlement, the facts get reopened anyway and the signature stops helping. A register makes the open ones countable, which is the only way anybody chases them.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "claim",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.in.records", label: "Diary, photographs, records" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.in.clause", label: "The clause relied on" },
      ],
      outputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.out.pack", label: "Evidence pack per claim" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.out.gaps", label: "Missing evidence, visible early" },
      ],
      titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.title",
      titleDefault: "Build the claim on evidence, not on recollection",
      whatKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.what",
      whatDefault:
        "Where the event is at the other party's risk, open a claim and gather the evidence against it: the diary entries, the photographs, the labour and plant that stood, and the clause you are relying on.",
      whyKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.claim.why",
      whyDefault:
        "A claim is judged on its evidence and on whether the notice was given in time, and both are decided months before anybody starts writing the submission. Assembling the pack as it happens shows you what is missing while it is still gettable, which is a different exercise from assembling it at the end and discovering what is not.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "notice",
      icon: "Send",
      inputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.in.event", label: "The event and its date" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.in.timebar", label: "The contract's notice period" },
      ],
      outputs: [
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.out.notice", label: "Notice issued and dated" },
        { labelKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.out.thread", label: "One thread per matter" },
      ],
      titleKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.title",
      titleDefault: "Give notice in writing, inside the contract's period",
      whatKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.what",
      whatDefault:
        "Issue the notice as correspondence, dated, naming the event and the clause, and keep every later letter on the same matter in the same thread.",
      whyKey: "cases.keep_changes_site_confirmations_and_claims_apart.step.notice.why",
      whyDefault:
        "Most claims that fail do not fail on the merits, they fail on a notice period that ran out while the matter was being discussed verbally. The valuation code's default is 28 days from the event for the notice of intention and a further 28 for the full claim with its evidence, and the right is lost when the first one is missed. A dated letter costs nothing and is the only thing that answers the question of when the other party first knew.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
  ],
};

export default playbook;
