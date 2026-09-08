// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep the e-epitesi naplo as the legal record it is" (HU).
//
// The Hungarian site log is not a diary a firm keeps for itself. Government
// Decree 191/2009 (IX. 15.), the Epkiv., makes it a register the works are
// carried out under: it is opened before the site is handed over, the chain of
// contractors hangs off it, measurement and concealed work are entered in it,
// and the certificates that release money are signed in it. This case writes
// the day into the systems that feed it. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-the-e-epitesi-naplo-as-the-legal-record",
  order: 1245,
  region: "HU",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["site-manager", "foreman", "document-controller", "project-manager"],
  icon: "NotebookPen",
  titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.title",
  titleDefault: "Keep the e-epitesi naplo as the legal record it is",
  descKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.desc",
  descDefault:
    "Have the naplo opened before anyone goes on site, write the day while it is happening, hang each contractor's alnaplo off the fonaplo, record measurement and concealed work as they occur, and close the record so it can be read years later.",
  longDescKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.longdesc",
  longDescDefault:
    "Government Decree 191/2009 (IX. 15.) treats the e-epitesi naplo as a condition of lawful construction rather than as good practice. The epitteto opens it and the first e-fonaplo before the site is handed over, the contractor accepts the handover through the system, the handover itself is entered, and work may begin only after that. Everything that decides money later is written into the same record: the measurement the valuation is built on, the inspection of a structure about to be covered, and the teljesitesigazolas without which no invoice can lawfully be issued. Kept as the work runs it is a register. Written up afterwards it is a story, and an inspector can tell the difference.",
  estMinutes: 13,
  steps: [
    {
      id: "keszenlet",
      icon: "Flag",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.in.permit", label: "Permit or notification record" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.in.parties", label: "Epitteto and contractor" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.out.open", label: "Naplo open and accepted" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.out.handover", label: "Site handover entered" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.title",
      titleDefault: "Have the naplo open before the site is handed over",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.what",
      whatDefault:
        "Before mobilisation, confirm that the epitteto has put the naplo and the first fonaplo into readiness, that the contractor has accepted the site handover through it, and that the handover is entered as an event. Record the same milestone on the project so the site does not start on somebody's assurance that it is done.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.keszenlet.why",
      whyDefault:
        "The Epkiv. lets the work begin only once that entry exists, so a crew that starts a week early is not ahead of programme, it is carrying out construction work outside the record. Building supervision treats that as a defect of the works and not as a filing lapse, and the contractor is the party standing in front of it.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "site_prep.title",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "day",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.in.crews", label: "Crews and plant on site" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.in.weather", label: "Weather and conditions" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.out.entry", label: "Diary entry for the day" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.out.events", label: "Events logged with their hour" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.title",
      titleDefault: "Write the day while the day is happening",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.what",
      whatDefault:
        "Record what the site actually did: which crews and which subcontractors were there, what each area got done, the weather and ground conditions, deliveries, visitors, and anything that stopped the work, with the hour it started and who was told.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.day.why",
      whyDefault:
        "The naplo is where a Hungarian dispute is decided, because it is the one record both sides signed up to in advance. An entry made on the day is evidence; the same words typed in November are a claim about what somebody remembers, and the other side gets to say so. The cost of the discipline is ten minutes a day and the cost of skipping it lands all at once.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "alnaplo",
      icon: "Users",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.in.subs", label: "Subcontractors on the package" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.in.fonaplo", label: "Open fonaplo" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.out.chain", label: "Contractor chain on record" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.out.alnaplo", label: "Alnaplo open per contractor" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.title",
      titleDefault: "Hang every contractor off the fonaplo",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.what",
      whatDefault:
        "Keep the register of who is working under whom in step with the naplo: each contractor in the chain keeps its own alnaplo under the fonaplo above it, and a firm that turns up on site without one is a firm working outside the record.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.alnaplo.why",
      whyDefault:
        "The chain of alnaplok is how an inspection reads a site, and it is also how a payment chain is reconstructed when somebody in the middle stops paying. A subcontractor with no alnaplo has no record of its own work on the job it is owed for, which is a much larger problem for them than the administrative one it looks like on the day.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "felmeres",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.in.executed", label: "Work executed this period" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.in.tetel", label: "Tetel and contract quantity" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.out.quantities", label: "Measured quantities per tetel" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.out.basis", label: "Basis for the valuation" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.title",
      titleDefault: "Record the measurement where the money will look for it",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.what",
      whatDefault:
        "Where the contract settles on measured quantities, record the measurement tetel by tetel as the work is done, and keep it agreed with the muszaki ellenor rather than presented to them at the end of the month. The felmeresi naplo is the sub-log this belongs in, and the valuation should be readable straight out of it.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.felmeres.why",
      whyDefault:
        "Measurement agreed while the work is visible takes minutes and measurement argued after it is buried takes a meeting, sometimes a survey, and occasionally a court. It is also the difference between a valuation the certifier can approve line by line and one they can only accept or refuse whole.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "eltakart",
      icon: "Eye",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.in.structure", label: "Structure about to be covered" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.in.notice", label: "Notice to the muszaki ellenor" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.out.inspection", label: "Inspection record with photos" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.out.release", label: "Release to cover" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.title",
      titleDefault: "Inspect the concealed work before it is concealed",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.what",
      whatDefault:
        "Before reinforcement is poured over, insulation is boarded, or a service run is buried, call the inspection, photograph the work as built, record the result and only then release the cover. Keep the notice, the inspection and the photographs on the same record.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.eltakart.why",
      whyDefault:
        "The Epkiv. puts the checking of eltakart szerkezetek on the felelos muszaki vezeto, and once the work is covered the record is the only thing anybody can look at. A dispute about concealed work is decided on the entry and the photograph, and opening it up again to find out is a cost somebody pays whether or not they were wrong.",
      moduleLabel: "Inspections",
      moduleLabelKey: "inspections.title",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "ellenor",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.in.entries", label: "Entries awaiting the ellenor" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.in.appointment", label: "Muszaki ellenor appointment" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.out.countersigned", label: "Countersigned entries" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.out.notice", label: "Notice of completion sent" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.title",
      titleDefault: "Keep the muszaki ellenor inside the record",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.what",
      whatDefault:
        "Route what the supervising engineer has to see through the naplo rather than by message: the inspections, the measurements, the instructions they give and the written notice that a performance is complete. Record the date the notice went in.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.ellenor.why",
      whyDefault:
        "The Epkiv. makes a muszaki ellenor mandatory on several kinds of work, public procurement among them, and gives them at most fifteen working days from the contractor's written notice of completion to issue the teljesitesigazolas or refuse it with reasons. That clock only exists if the notice has a date, and the naplo is where the date is beyond argument.",
      moduleLabel: "Site Supervision",
      moduleLabelKey: "site_supervision.title",
      to: "/projects/:projectId/site-supervision",
    },
    {
      id: "close",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.in.entries", label: "Closed diary days" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.in.records", label: "Inspections and measurements" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.out.pack", label: "Site record pack" },
        { labelKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.out.handover", label: "Record handed to close-out" },
      ],
      titleKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.title",
      titleDefault: "Close the record so it can be read later",
      whatKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.what",
      whatDefault:
        "At the end of the works, pull the diary days, the inspections, the measurements and the photographs into one pack on the project, indexed by date, and hand it to close-out with the rest of the completion documentation.",
      whyKey: "cases.keep_the_e_epitesi_naplo_as_the_legal_record.step.close.why",
      whyDefault:
        "The people who will need this record are not the people who wrote it. A defect claim arrives years after the site manager has moved on, and the question is always the same: what was done here, when, and who checked it. A pack assembled at the end while everyone is still on the job answers that; a pack assembled from a defect notice does not.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
