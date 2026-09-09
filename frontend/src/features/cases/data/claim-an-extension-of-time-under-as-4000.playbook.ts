// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Claim an extension of time under AS 4000" (AU).
//
// Clause 34 of AS 4000-1997 is the time machinery: a notice of delay as soon
// as the contractor becomes aware of anything likely to delay the work, then a
// claim for an extension of time inside the period the clause allows, assessed
// against the programme. Delay damages are a separate question from the
// extension itself, and the Annexure may change every period in the clause.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "claim-an-extension-of-time-under-as-4000",
  order: 1640,
  region: "AU",
  category: "planning",
  companyTypes: ["general-contractor", "subcontractor", "project-manager", "cost-consultant"],
  roles: ["planner", "contract-administrator", "commercial-manager", "quantity-surveyor"],
  stage: "build",
  icon: "CalendarClock",
  titleKey: "cases.claim_an_extension_of_time_under_as_4000.title",
  titleDefault: "Claim an extension of time under AS 4000",
  descKey: "cases.claim_an_extension_of_time_under_as_4000.desc",
  descDefault:
    "Give the notice of delay as soon as the cause appears, record the delay day by day while it is happening, show it on the programme rather than asserting it, lodge the claim inside the period the clause allows, price the delay costs separately and record the new date for practical completion.",
  longDescKey: "cases.claim_an_extension_of_time_under_as_4000.longdesc",
  longDescDefault:
    "An extension of time claim under AS 4000 is decided on two things, and neither of them is how unfair the delay felt. The first is whether the notices were given when the clause required them: a notice of delay promptly on becoming aware of the cause, then a claim within the period clause 34 allows, which the Annexure can shorten. The second is whether the delay can be shown on the programme as a delay to the work as a whole rather than to one activity that had float. A claim that fails either test fails completely, and liquidated damages then run from the original date. Getting an extension also does not by itself pay for the time; delay damages depend on which cause the delay came from, and that distinction is worth keeping visible from the first day.",
  estMinutes: 18,
  steps: [
    {
      id: "notice",
      icon: "Send",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.in.cause", label: "Event likely to cause delay" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.in.aware", label: "Date you became aware" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.out.served", label: "Notice of delay served" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.out.dated", label: "Date and manner of service" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.title",
      titleDefault: "Give the notice of delay as soon as the cause appears",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.what",
      whatDefault:
        "Send the notice as soon as you become aware of anything likely to delay the work, naming the cause and its likely effect, addressed to the Superintendent and recorded in the correspondence register with the date and the way it was sent. Do not wait until the delay can be quantified.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.notice.why",
      whyDefault:
        "The early notice exists so the Superintendent can do something about the cause while it is still cheap, which is why the clause asks for it before anyone knows how long the delay will be. A notice sent when the contractor finally has the numbers is a notice sent after the only moment it could have been acted on, and it invites the answer that the delay could have been mitigated.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "diary",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.in.site", label: "What happened on site each day" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.in.weather", label: "Weather and lost days" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.out.diary", label: "Day by day record" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.out.standing", label: "Resources standing by" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.title",
      titleDefault: "Record the delay while it is happening",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.what",
      whatDefault:
        "Keep the daily record through the delay: which activities could not proceed, which crews and plant were standing, what work was moved forward instead, and the weather where the claim is a wet weather claim. Record the days the site could not work, not just the days it rained.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.diary.why",
      whyDefault:
        "A wet weather claim is refused more often for measuring the wrong thing than for being untrue. Rainfall from the nearest station proves it rained; the diary proves the excavation could not be worked, which is the fact the claim is actually about, and it can only be written on the day.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "programme",
      icon: "GanttChartSquare",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.in.baseline", label: "Programme before the delay" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.in.diary", label: "Day by day record" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.out.impacted", label: "Delay shown on the programme" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.out.critical", label: "Effect on the critical path" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.title",
      titleDefault: "Show the delay on the programme, not in a sentence",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.what",
      whatDefault:
        "Take the programme as it stood before the event, insert the delay where it actually landed, and read off what it does to the critical path and to the date for practical completion. Keep both versions so the difference between them is the claim.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.programme.why",
      whyDefault:
        "An extension is owed for delay to the work as a whole, so a fortnight lost on an activity carrying three weeks of float earns nothing however real the disruption was. The programme is the only place that distinction can be shown, and showing it is also the fastest way to find out that a claim you were about to spend a month on is not there.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "claim",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.in.impacted", label: "Delay shown on the programme" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.in.evidence", label: "Records supporting the cause" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.out.claim", label: "Extension of time claim" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.out.pack", label: "Cause, effect and evidence together" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.title",
      titleDefault: "Lodge the claim with the cause tied to the effect",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.what",
      whatDefault:
        "Assemble the claim as one pack: the qualifying cause, the facts that establish it, the programme showing what it delayed and the number of days sought. Under AS 4000 the claim must be made within twenty eight days of when the contractor should reasonably have become aware of the causation of the delay, and the Annexure can make that period shorter.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.claim.why",
      whyDefault:
        "Assessors reject extension claims on the join rather than on the parts. A cause everyone accepts and a programme everyone accepts still fail when nothing in between says which activity this event stopped on which day. Assembling the pack in one place is what forces that link to be made while the evidence to make it still exists.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "window",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.in.claim", label: "Extension of time claim" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.in.annexure", label: "Periods from the Annexure" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.out.watched", label: "Claim and response dates watched" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.out.warned", label: "Warning before each date" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.title",
      titleDefault: "Watch the windows the clause and the Annexure set",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.what",
      whatDefault:
        "Put the claim window and the period the Superintendent has to assess it under watch, taking the lengths from the Annexure rather than from the printed default, and let each one warn before it lands.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.window.why",
      whyDefault:
        "Both sides of this clause run on dates that nobody rereads once the job is busy. A claim lodged a day late is barred, and a Superintendent who lets the assessment period pass without a decision leaves the contractor an argument it would not otherwise have had. Either way the date decides, and the date is in the Annexure.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "costs",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.in.days", label: "Days of extension granted" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.in.prelims", label: "Time related site costs" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.out.delay", label: "Delay costs priced" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.out.split", label: "Compensable time separated" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.title",
      titleDefault: "Price the time separately from the entitlement to it",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.what",
      whatDefault:
        "Work out what the extended period costs from the time related preliminaries the job actually carries, site staff, accommodation, standing plant, scaffold hire and site running costs, and separate the days that carry delay damages from the days that only move the date.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.costs.why",
      whyDefault:
        "An extension of time protects the contractor from liquidated damages and does not, by itself, pay for anything. Whether the days are also compensable depends on which cause they came from, so a claim that runs the two together invites a refusal of both, and a contractor who assumed the time came with money has already spent it.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "date",
      icon: "Milestone",
      inputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.in.determination", label: "Superintendent's determination" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.in.previous", label: "Date for practical completion" },
      ],
      outputs: [
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.out.new", label: "New date on the contract" },
        { labelKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.out.damages", label: "Liquidated damages reset" },
      ],
      titleKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.title",
      titleDefault: "Record the new date everything else counts from",
      whatKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.what",
      whatDefault:
        "Post the determination against the contract so the date for practical completion moves, and keep the trail of the days claimed, the days granted and the days still in dispute beside it.",
      whyKey: "cases.claim_an_extension_of_time_under_as_4000.step.date.why",
      whyDefault:
        "The date for practical completion is the date liquidated damages run from, the date the defects liability period is measured from and the date the security reduction hangs on, so an extension that is granted and never recorded leaves three other things wrong. It is also the number a principal will assume was never granted once the people who remember have left the job.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
