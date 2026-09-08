// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Maengel, Abnahme and the Verjaehrung clock" (DE).
//
// The end of a German project is a legal sequence, not a mood. Walk the site
// and log every Mangel with photo and location, drive the list to zero or to
// agreed exceptions, hold the formal Abnahme whose protocol decides when risk
// passes and the Verjaehrung starts, then track the defects through the
// liability period on the limitation the contract actually gives you: four
// years for building works under VOB/B, five under a BGB Werkvertrag. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "maengel-abnahme-and-verjaehrung",
  order: 1056,
  category: "handover",
  companyTypes: ["general-contractor", "project-manager", "developer-client"],
  roles: ["contract-administrator", "site-manager", "project-manager"],
  region: "DE",
  icon: "Gavel",
  titleKey: "cases.maengel_abnahme_and_verjaehrung.title",
  titleDefault: "Maengel, Abnahme and the Verjaehrung clock",
  descKey: "cases.maengel_abnahme_and_verjaehrung.desc",
  descDefault:
    "Log every Mangel with photo and location, clear the list before the Abnahme, sign a protocol that says exactly what was reserved, and track the defects on the limitation period the contract really gives you.",
  longDescKey: "cases.maengel_abnahme_and_verjaehrung.longdesc",
  longDescDefault:
    "The Abnahme is the hinge of a German construction contract: risk passes, the money falls due, the burden of proof turns around and the Verjaehrung starts running. Everything before it is about walking into that appointment with a list that is already clear, and everything after it is about knowing which clock you are on - four years for building works under VOB/B, five under a BGB Werkvertrag - so no Maengelruege and no counter-deadline is missed while the period is still open.",
  estMinutes: 11,
  steps: [
    {
      id: "walk",
      icon: "Camera",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.in.walk", label: "Pre-acceptance walk" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.in.trades", label: "Trades on site" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.out.items", label: "Logged Maengel" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.out.evidence", label: "Photo and location" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.title",
      titleDefault: "Walk the building and log every Mangel",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.what",
      whatDefault:
        "Walk the building trade by trade well before the acceptance date and put every defect straight into the list: what is wrong, the room or axis it sits in, a photo, and the trade that owns the fix.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.walk.why",
      whyDefault:
        "A defect written on a slip of paper and typed up three weeks later is a defect the trade disputes. Location plus photo, captured while you are standing in front of it, is what turns a complaint into something enforceable.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "clear",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.in.open", label: "Open Maengel" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.in.fixes", label: "Reported fixes" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.out.closed", label: "Verified closures" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.out.exceptions", label: "Agreed exceptions" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.title",
      titleDefault: "Drive the list to zero or to agreed exceptions",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.what",
      whatDefault:
        "Re-inspect every item the trade reports as done, close the ones that genuinely pass and reopen the ones that do not, and mark the few that will stay open as exceptions both sides have agreed to carry into the protocol.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.clear.why",
      whyDefault:
        "The acceptance appointment is the worst possible place to discover an open list. Every item closed and proven beforehand is one that cannot be reserved against you, held against your payment, or used to refuse acceptance outright.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "abnahme",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.in.cleared", label: "Cleared Maengel list" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.in.date", label: "Acceptance appointment" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.out.protocol", label: "Signed Abnahmeprotokoll" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.out.reserved", label: "Reserved defects" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.title",
      titleDefault: "Hold the formal Abnahme and write the protocol",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.what",
      whatDefault:
        "Run the acceptance walk with the client and record the Abnahmeprotokoll: the date, who was present, what was accepted, which defects are reserved, and any contract penalty the client wants to keep. Both sides sign it. If the client does not turn up, the works count as accepted under paragraph 12 (5) VOB/B twelve working days after your written notice of completion, or six working days after the client starts using them, and the protocol then records that date instead.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.abnahme.why",
      whyDefault:
        "This one document decides more than any other on the project: risk passes, the final payment falls due, the burden of proof turns to the client, and the Verjaehrung starts on its date. A defect not reserved in it, and a contract penalty not reserved with it, is one nobody can raise afterwards.",
      moduleLabel: "Handover & Closeout",
      moduleLabelKey: "closeout.title",
      to: "/closeout",
    },
    {
      id: "frist",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.in.contract", label: "Signed contract" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.in.protocol", label: "Abnahme date" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.out.regime", label: "Contract regime" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.out.period", label: "Verjaehrungsfrist set" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.title",
      titleDefault: "Read the limitation period off the contract",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.what",
      whatDefault:
        "Open the contract, establish whether VOB/B was validly agreed or the job runs as a plain BGB Werkvertrag, and record the limitation period that follows: four years for building works under VOB/B, five under the BGB, counted from the Abnahme date in the protocol.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.frist.why",
      whyDefault:
        "The two regimes are a full year apart, and assuming the wrong one either hands the client a year you never owed or writes off a claim that was still alive. Reading it off the contract once, at the Abnahme, is what makes every deadline after it trustworthy.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "track",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.track.in.reserved", label: "Reserved defects" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.track.in.reports", label: "Defects reported later" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.track.out.register", label: "Tracked claims" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.track.out.end", label: "Period end date" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.track.title",
      titleDefault: "Track the defects through the liability period",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.track.what",
      whatDefault:
        "Register the reserved defects and everything reported after handover against the party obliged to fix it, each with the warranty that covers it and the date its period runs out.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.track.why",
      whyDefault:
        "A defect phoned in to a caretaker and written into nobody's list is a defect the owner quietly ends up paying to fix. One register is what keeps every claim attached to the party that owes it for as long as the period runs.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "ruege",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.in.ends", label: "Limitation end dates" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.in.claims", label: "Open defect claims" },
      ],
      outputs: [
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.out.notice", label: "Maengelruege sent" },
        { labelKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.out.deadline", label: "Remedy deadline set" },
      ],
      titleKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.title",
      titleDefault: "Send the Maengelruege while the period is open",
      whatKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.what",
      whatDefault:
        "Work the deadline register: the day each limitation period ends, the date a notified defect must be remedied by, and the counter-deadlines you set the contractor. Issue the Maengelruege in writing, with a deadline to put it right.",
      whyKey: "cases.maengel_abnahme_and_verjaehrung.step.ruege.why",
      whyDefault:
        "A claim raised one day after the period has run out is worth nothing, however well it was documented. Under a VOB/B contract a written Maengelruege starts a fresh two-year period for that defect, paragraph 13 (5) VOB/B, which is the reason to send it in writing rather than say it on site. Under the BGB alone a letter stops nothing, only negotiations, an independent evidence procedure or a claim do, so read the contract before you rely on the notice. The remedy deadline you set with it is what turns it into work on site rather than correspondence.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
