// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep jotallas apart from szavatossag and release the retention" (HU).
//
// Two different guarantees that Hungarian contracts routinely collapse into one
// word. Under kellekszavatossag the party claiming has to show the defect was
// there at performance; under jotallas the obligor is liable unless it shows the
// cause arose afterwards. They run side by side, they end on different days, and
// the retention is usually released against the shorter one. This case keeps
// them apart from the contract through to the last release. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-jotallas-apart-from-szavatossag-and-release-the-retention",
  order: 1247,
  region: "HU",
  category: "handover",
  companyTypes: ["general-contractor", "subcontractor", "developer-client", "cost-consultant"],
  roles: ["contract-administrator", "commercial-manager", "quantity-surveyor", "project-manager"],
  icon: "ShieldCheck",
  titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.title",
  titleDefault: "Keep jotallas apart from szavatossag and release the retention",
  descKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.desc",
  descDefault:
    "Write the two guarantees into the contract as two things, take the works over with the outstanding items listed, run both clocks separately, and release the retention against the right one instead of against whichever ends first.",
  longDescKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.longdesc",
  longDescDefault:
    "Hungarian contracts say garancia and mean one of two different things. Kellekszavatossag under the Ptk. is the liability that comes with defective performance, and the party claiming has to show the defect was already there when the work was handed over. Jotallas is an undertaking, contractual or imposed by a decree, under which the obligor is liable unless it proves the cause of the defect arose after performance. That difference in who has to prove what is the whole practical value of the distinction, and it is the part that gets lost when both are called the warranty. They also end on different days. The jotallas period is typically the shorter one, while a kellekszavatossagi igeny on real property lapses five years from performance, so the end of the guarantee is not the end of the liability, and a retention released on the wrong date is released against a risk that has not gone.",
  estMinutes: 12,
  steps: [
    {
      id: "terms",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.in.draft", label: "Contract draft" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.in.scope", label: "Scope and building type" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.out.terms", label: "Two guarantees written separately" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.out.security", label: "Retention and security terms" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.title",
      titleDefault: "Write the two guarantees as two clauses",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.what",
      whatDefault:
        "Record in the contract, separately, the jotallas the contractor undertakes and its period, and the szavatossag that follows from the Ptk. whether anybody writes it down or not. Alongside them record how the obligation is secured: retention held from each payment, a bank guarantee, or both, and on what event each is released.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.terms.why",
      whyDefault:
        "Under jotallas the obligor escapes only by proving that the cause of the defect arose after performance; under szavatossag the party claiming carries the proof. A clause that says only garancia leaves that question to be argued at the worst possible moment, which is when a defect has appeared and neither side has a technical answer yet. Two clauses cost one paragraph and settle it in advance.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "mandatory",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.in.type", label: "Building type and client" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.in.terms", label: "Drafted guarantee terms" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.out.floor", label: "Mandatory floor identified" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.out.report", label: "Compliance report" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.title",
      titleDefault: "Check whether a mandatory jotallas applies",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.what",
      whatDefault:
        "Before the terms are agreed, check whether the work falls under a jotallas imposed by law rather than chosen by the parties. Government Decree 181/2003 (XI. 5.) is the one that matters in housing, and where it applies the parties cannot contract below it.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.mandatory.why",
      whyDefault:
        "A negotiated guarantee shorter than the mandatory floor is not a negotiated guarantee, it is an unenforceable clause that both sides believed until the day it was tested. The contractor priced a risk it did not shed and the client relied on a period that was never in danger, and both find out at the same moment.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "atadas",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.in.works", label: "Completed works" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.in.inspection", label: "Takeover inspection" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.out.list", label: "List of outstanding items" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.out.date", label: "Takeover date fixed" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.title",
      titleDefault: "Take the works over with the list attached",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.what",
      whatDefault:
        "Walk the works at the atadas-atvetel and record what is outstanding as a list of items with owners and dates, separating what is genuinely incomplete from what is defective. Fix the takeover date on the record, because both guarantee periods are measured from performance.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.atadas.why",
      whyDefault:
        "Everything after this is dated from here, so a takeover that happened in stages and was never written down leaves two parties with two different opinions about when the clocks started. The distinction between incomplete and defective matters as much: incomplete work is finishing under the contract, and defective work is the guarantee, and only one of them should be holding up the payment.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "retention",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.in.held", label: "Retention held to date" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.in.terms", label: "Release terms" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.out.schedule", label: "Release schedule" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.out.balance", label: "Balance still held" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.title",
      titleDefault: "Put the retention on a schedule, not in a memory",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.what",
      whatDefault:
        "Total what has been retained across the payments, split it into the portion released at takeover and the portion released at the end of the guarantee, and record each release as a dated event with the condition that triggers it.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.retention.why",
      whyDefault:
        "Retention is the most commonly forgotten money in construction, in both directions. A contractor who does not track it asks for it late, sometimes years late and sometimes never. A client who does not track it releases it early against a defect it had every right to hold, and cannot get it back.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "clocks",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.in.date", label: "Takeover date" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.in.terms", label: "Both guarantee periods" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.out.jotallas", label: "Jotallas end date" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.out.szavatossag", label: "Szavatossag end date" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.title",
      titleDefault: "Run the two clocks as two clocks",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.what",
      whatDefault:
        "Open a deadline for each period from the takeover date: the jotallas as the contract or the decree sets it, and the kellekszavatossagi igeny separately. Where the thing supplied is real property, that second one lapses five years from performance under the Ptk. rather than in the one year that applies generally.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.clocks.why",
      whyDefault:
        "Both parties tend to file the job when the shorter clock stops, and that is the error the five-year rule punishes. A client who lets the szavatossagi period run out on a real defect loses a claim it had; a contractor who thinks the file closed with the jotallas has stopped keeping the record that would answer the claim. Two dated deadlines cost nothing and prevent both.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "defects",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.in.notice", label: "Defect notified after handover" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.in.record", label: "Site record for that work" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.out.classified", label: "Defect classified under one guarantee" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.out.remedy", label: "Remedy tracked to closure" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.title",
      titleDefault: "Classify each defect before you argue about it",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.what",
      whatDefault:
        "When a defect is notified, record which period it falls in, what the site record says about that work, and which guarantee is being relied on. Then track the remedy to closure with the date it was fixed, because a repaired part restarts the limitation on that part.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.defects.why",
      whyDefault:
        "Which guarantee applies decides who has to prove what, and that decides the outcome far more often than the technical merits do. Making the classification an explicit step, with the site record next to it, is what turns a defect notice into a question with an answer rather than into an exchange of letters that runs until somebody gives up.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "close",
      icon: "CheckCheck",
      inputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.in.expired", label: "Expired jotallas period" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.in.open", label: "Open defect items" },
      ],
      outputs: [
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.out.released", label: "Final retention released" },
        { labelKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.out.record", label: "Record kept for the longer period" },
      ],
      titleKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.title",
      titleDefault: "Close the guarantee without closing the file",
      whatKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.what",
      whatDefault:
        "At the end of the jotallas period, walk the outstanding items, release the final retention against a clean list, and keep the project record open until the longer szavatossagi period has run rather than archiving it with the money.",
      whyKey: "cases.keep_jotallas_apart_from_szavatossag_and_release_the_retention.step.close.why",
      whyDefault:
        "The record is the asset that outlives the retention. A claim arriving in year four is answered from the naplo, the inspections and the takeover list, and a firm that filed all of it when the money was released is answering from memory instead. Releasing the retention and keeping the file are two decisions, and only one of them should be made at this point.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
