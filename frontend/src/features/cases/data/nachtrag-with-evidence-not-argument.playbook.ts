// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a Nachtrag on evidence, not argument" (DE).
//
// A Nachtrag starts on site, not in the office: the ground is different, the
// drawing changed, the client ordered extra. Record the condition the day it
// appears, announce it before building it, price it against the contract
// basis and follow it from angemeldet to beauftragt. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "nachtrag-with-evidence-not-argument",
  order: 1054,
  category: "commercial",
  region: "DE",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["site-manager", "commercial-manager", "quantity-surveyor"],
  icon: "Scale",
  titleKey: "cases.nachtrag_with_evidence_not_argument.title",
  titleDefault: "Build a Nachtrag on evidence, not argument",
  descKey: "cases.nachtrag_with_evidence_not_argument.desc",
  descDefault:
    "The ground is different, the drawing changed, the client ordered extra. Capture the changed condition on site the day it appears, price it against the contract basis, and follow the Nachtrag from angemeldet through to beauftragt.",
  longDescKey: "cases.nachtrag_with_evidence_not_argument.longdesc",
  longDescDefault:
    "Paragraph 2 VOB/B is where changed and additional work lives, and it rewards the contractor who wrote the condition down on the day it appeared. A Nachtrag reconstructed months later from memory gets argued down to nothing; the same change carrying a dated diary entry, photographs taken while the trench was still open and a countersigned Stundenlohnzettel gets paid.",
  estMinutes: 13,
  steps: [
    {
      id: "record",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.record.in.condition",
          label: "Changed site condition",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.record.in.revision",
          label: "Revised drawing",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.record.in.instruction",
          label: "Client instruction",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.record.out.entry",
          label: "Dated diary entry",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.record.out.witnesses",
          label: "Who was on site",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.record.title",
      titleDefault: "Write the changed condition into the diary",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.record.what",
      whatDefault:
        "On the day the ground turns out different, the revised drawing lands or the client orders something extra, write it into the site diary: what was found and where, which crews and plant were standing there, the weather, and the instruction or drawing revision behind it.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.record.why",
      whyDefault:
        "A diary entry is dated by the day it was written, not by the day the argument starts. That is the whole difference between a Nachtrag the other side reads and one they take apart line by line.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "photograph",
      icon: "Camera",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.in.shots",
          label: "Site photographs",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.in.entry",
          label: "Diary entry it belongs to",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.out.dated",
          label: "Dated geotagged photos",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.out.record",
          label: "Record of the condition",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.title",
      titleDefault: "Photograph it while it is still open",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.what",
      whatDefault:
        "Upload the photographs the same day: the open trench, the layer that was not in the soil report, the obstruction nobody drew. The gallery reads the capture date and GPS position off each file, so every shot carries its own date and place without you typing one.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.photograph.why",
      whyDefault:
        "Once the excavation is backfilled nobody can photograph it again. A dated, located photograph is the cheapest evidence on the project and the one thing that settles whether the ground really was different.",
      moduleLabel: "Project Photos",
      moduleLabelKey: "nav.photos",
      to: "/photos",
    },
    {
      id: "notify",
      icon: "Flag",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.notify.in.evidence",
          label: "Diary entry and photos",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.notify.in.instruction",
          label: "Instruction or revision",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.notify.out.notice",
          label: "Nachtrag angemeldet",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.notify.out.deadline",
          label: "Recipient and response date",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.notify.title",
      titleDefault: "Announce the Nachtrag before you build it",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.notify.what",
      whatDefault:
        "Raise the notice in the variations register as soon as the change is spotted: name the changed or additional work under paragraph 2 VOB/B, name the recipient, and set the date you expect an answer by. The notice goes in before the work is carried out.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.notify.why",
      whyDefault:
        "Announcing first and building second is what keeps the entitlement alive. A Nachtrag announced after the work is finished invites the reply that nobody ordered it, however good the site records are.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "daywork",
      icon: "Signature",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.in.hours",
          label: "Labour and plant hours",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.in.code",
          label: "Cost code for the change",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.in.notice",
          label: "Announced Nachtrag",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.out.sheet",
          label: "Countersigned Stundenlohnzettel",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.out.approved",
          label: "Approved daywork hours",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.title",
      titleDefault: "Book the Stundenlohn hours and get them signed",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.what",
      whatDefault:
        "Where the work runs as Stundenlohnarbeiten, book the labour and plant hours against the change and flag the lines as daywork rather than measured work, then hand the Stundenlohnzettel to the site supervision daily, or at the latest weekly, for countersignature as paragraph 15 (3) VOB/B requires. A sheet the client does not return with objections within six working days counts as recognised.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.daywork.why",
      whyDefault:
        "Daywork is recovered against the Nachtrag and measured work against the bill; mix them and you lose both. An unsigned Stundenlohnzettel handed over weeks late is the easiest item on any Nachtrag to strike out.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.price.in.positions",
          label: "Contract positions and rates",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.price.in.measure",
          label: "Added and omitted work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.price.out.priced",
          label: "Priced Nachtrag position",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.price.out.basis",
          label: "Traceable price basis",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.price.title",
      titleDefault: "Price it against the contract basis",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.price.what",
      whatDefault:
        "Derive the new position from the nearest position in the contract bill rather than inventing a fresh price, carry the same cost elements the Urkalkulation was built on, the one you lodged sealed with a public client at award, and measure the omitted work as carefully as the added. Keep the actual cost evidence beside it, because where the contract fixes no basis the courts now fall back on the tatsaechlich erforderlichen Kosten with reasonable markups.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.price.why",
      whyDefault:
        "A Nachtrag built on the original calculation can be checked in an afternoon. One built on a market rate that has nothing to do with the contract turns the whole negotiation into a fight about the price basis instead of the work.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "order",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.order.in.priced",
          label: "Priced Nachtrag",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.order.in.notice",
          label: "The notice it answers",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.order.out.request",
          label: "Submitted Nachtrag offer",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.order.out.order",
          label: "Nachtrag beauftragt",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.order.title",
      titleDefault: "Submit it and follow it to beauftragt",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.order.what",
      whatDefault:
        "Turn the announced change into a priced request with its cost and time impact set out, submit it against the notice it answers, and follow it through review to an agreed order that carries the figure into the contract final account.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.order.why",
      whyDefault:
        "Priced but never formally submitted is work done for free. Tracking every open Nachtrag from angemeldet to beauftragt in one register is what stops a folder of changes agreed in principle reaching the final account unbooked.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "prove",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.prove.in.submitted",
          label: "Submitted Nachtrag",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.prove.in.evidence",
          label: "Diary, photos, signed sheets",
        },
      ],
      outputs: [
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.prove.out.score",
          label: "Provability score",
        },
        {
          labelKey: "cases.nachtrag_with_evidence_not_argument.step.prove.out.pack",
          label: "Exportable evidence pack",
        },
      ],
      titleKey: "cases.nachtrag_with_evidence_not_argument.step.prove.title",
      titleDefault: "Check it would survive a challenge",
      whatKey: "cases.nachtrag_with_evidence_not_argument.step.prove.what",
      whatDefault:
        "Before the Nachtrag is contested, read its provability score: whether the notice went out in time, whether the other side acknowledged it, whether it ties to a governing instruction and a dated contemporaneous record. Work the weakest gap first, then assemble the evidence thread into one exportable pack.",
      whyKey: "cases.nachtrag_with_evidence_not_argument.step.prove.why",
      whyDefault:
        "This is the step that decides whether a Nachtrag is paid or talked down. Finding the missing acknowledgement while the site is still open costs one email; finding it at the final account costs the whole item.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
  ],
};

export default playbook;
