// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep a court-proof Bautagebuch" (DE).
//
// The German site day written as evidence: weather pulled from an independent
// service, the Behinderung logged at the hour it starts, the notice served
// under VOB/B, the crew hours booked before anyone leaves site, the day closed
// and signed so its contents are frozen. Two years later the pack assembles
// itself. Content strings are key plus inline English default and live here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-a-court-proof-bautagebuch",
  order: 1052,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["site-manager", "foreman", "commercial-manager"],
  region: "DE",
  icon: "NotebookPen",
  titleKey: "cases.keep_a_court_proof_bautagebuch.title",
  titleDefault: "Keep a court-proof Bautagebuch",
  descKey: "cases.keep_a_court_proof_bautagebuch.desc",
  descDefault:
    "Write the site day while it happens - weather from an independent source, crews, progress, obstructions and visitors - book the hours the same day, then close and sign the diary so it is sealed evidence instead of something written up weeks later.",
  longDescKey: "cases.keep_a_court_proof_bautagebuch.longdesc",
  longDescDefault:
    "A Bautagebuch is worth exactly what its contemporaneity is worth. Written on the day, it is the record a Bauleiter can put in front of anyone two years later; reconstructed in the office in December it proves nothing, and the other side will say so. Nobody wants to write up the week on a Friday evening, so this case puts every entry where the work is: the diary as the day runs, the Behinderung at the hour it starts, the notice served under VOB/B, the hours booked before the gate closes, and the day signed and sealed.",
  estMinutes: 11,
  steps: [
    {
      id: "tagesbericht",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.in.weather", label: "Weather for the site location" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.in.crews", label: "Crews and subcontractors" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.in.visitors", label: "Visitors and deliveries" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.out.diary", label: "Bautagebuch for the day" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.out.record", label: "Crews, visitors and progress logged" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.title",
      titleDefault: "Open the day and pull the weather",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.what",
      whatDefault:
        "Open today's Bautagebuch and fetch the weather for the project location from the Open-Meteo service rather than typing it from memory. Record the crews and subcontractors on site, the headcount, the visitors and deliveries, and what each area actually got done.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.tagesbericht.why",
      whyDefault:
        "Weather fetched from an independent service on the day it happened is a fact. Weather remembered in December is an assertion, and the other side gets to test it. Frost days, rain days and the crews who stood in them are what an extension of time is later built from, and they only count if they were written while they were still true.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "behinderung",
      icon: "AlertTriangle",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.in.event", label: "Obstruction on site" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.in.time", label: "Clock time it began" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.in.idle", label: "Crews standing idle" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.out.entry", label: "Timed Behinderung entry" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.out.basis", label: "Basis for the notice" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.title",
      titleDefault: "Log the Behinderung at the hour it starts",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.what",
      whatDefault:
        "The moment the work is obstructed - the shaft is not handed over, the design answer is missing, the ready-mix does not arrive - log it on the diary as its own entry: the clock time it began, what exactly is blocked, which crews are standing in it and who on the client side was told.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.behinderung.why",
      whyDefault:
        "A Behinderung recorded as hold-ups in week 34 is worth nothing. The hour it started, the gang that stood in it and the name of the person you told are what turn a complaint into a claim somebody can price. Write it while the crane is still standing, not when the month is being closed.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "anzeige",
      icon: "Send",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.in.entry", label: "Behinderung diary entry" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.in.parties", label: "Contract and parties" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.out.notice", label: "Served Behinderungsanzeige" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.out.thread", label: "Dated notice thread" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.title",
      titleDefault: "Serve the Behinderungsanzeige",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.what",
      whatDefault:
        "Raise the Behinderungsanzeige to the Auftraggeber as an outgoing notice in the correspondence register, quoting the diary entry and its date, and set a response deadline so the answer - or the silence - lands on the same thread.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.anzeige.why",
      whyDefault:
        "The diary entry is your evidence, but it is not the notice. Paragraph 6 (1) VOB/B expects the Auftraggeber to be told in writing without delay, and unless the hindrance was obvious to them the extension of time under paragraph 6 (2) stands or falls on that notice. The claim for time or money most often refused is the one that was never announced. Served from the register it carries its own timestamp and its own thread, so nobody has to search a mailbox two years later.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "correspondence.title",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "stunden",
      icon: "Clock",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.in.crews", label: "Crews and plant on site" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.in.codes", label: "Cost codes" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.in.standing", label: "Standing time from the Behinderung" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.out.hours", label: "Hours booked on the day" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.out.daywork", label: "Standing time as daywork" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.title",
      titleDefault: "Book the hours before anyone leaves site",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.what",
      whatDefault:
        "Book the hours every person and every machine put in today against the right cost code, and flag the standing time caused by the Behinderung as daywork. The day recorder works offline, so the Vorarbeiter books from the site instead of from the office.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.stunden.why",
      whyDefault:
        "MiLoG paragraph 17 gives seven days for the working-hours record to exist and requires it to be kept for at least two years. Booked on the day you are inside that window without anyone writing up the week from memory on a Friday evening, and the standing hours get priced while it is still obvious who stood where and for how long.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "abschluss",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.in.photos", label: "Photos taken today" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.in.entries", label: "The day entries" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.out.signed", label: "Signed and sealed diary day" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.out.pdf", label: "PDF for the project file" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.title",
      titleDefault: "Attach the photos, close and sign the day",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.what",
      whatDefault:
        "Attach the day's photos to the entries they belong to, close the diary and sign it. Signing freezes the contents behind a SHA-256 hash, and the PDF export is the copy you hand to the client or the lawyer.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.abschluss.why",
      whyDefault:
        "A diary that can still be edited invites the one question that decides everything: when was this really written? A signed day answers it before it is asked, because the hash proves the text has not moved since the evening it was written. It is also the moment the Bauleiter stops carrying the week home.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "beweis",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.in.days", label: "Signed diary days" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.in.notices", label: "Served notices" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.in.hours", label: "Booked hours and photos" },
      ],
      outputs: [
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.out.pack", label: "Evidence pack" },
        { labelKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.out.score", label: "Provability score" },
      ],
      titleKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.title",
      titleDefault: "Two years on, assemble the evidence",
      whatKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.what",
      whatDefault:
        "When the dispute finally arrives, open the claims evidence view for the delay or the change in question. It gathers the diary days, the notices, the booked hours and the photos from those dates into one pack and scores how well the record actually carries the point.",
      whyKey: "cases.keep_a_court_proof_bautagebuch.step.beweis.why",
      whyDefault:
        "This is where the daily discipline gets paid. Every entry was made on the day it describes, so the pack is a contemporaneous record and not a reconstruction, and the score shows you which days are thin while there is still time to say so yourself.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
  ],
};

export default playbook;
