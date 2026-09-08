// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Start the works with the acta de comprobacion del replanteo" (ES).
//
// On a Spanish public works contract the plazo de ejecucion does not run from
// the award, from the signature or from the day the first lorry arrives. It
// runs from the acta de comprobacion del replanteo, the joint act in which the
// direccion facultativa and the contractor go to the site and confirm that the
// ground, the boundaries and the availability match the project. Everything
// downstream is dated from it, which is why the case spends its first step on
// the readiness that decides whether the act can be signed without reservas
// at all.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "start-the-works-with-an-acta-de-replanteo",
  order: 1142,
  region: "ES",
  category: "site",
  stage: "plan",
  companyTypes: ["general-contractor", "project-manager", "developer-client"],
  roles: ["site-manager", "project-manager", "contract-administrator"],
  icon: "Crosshair",
  titleKey: "cases.start_the_works_with_an_acta_de_replanteo.title",
  titleDefault: "Start the works with the acta de comprobacion del replanteo",
  descKey: "cases.start_the_works_with_an_acta_de_replanteo.desc",
  descDefault:
    "Prove the site is really available before you sign anything, get the acta signed by both sides, file it as the dated start of the plazo, and hang every deadline and the programa de trabajo off that one date.",
  longDescKey: "cases.start_the_works_with_an_acta_de_replanteo.longdesc",
  longDescDefault:
    "The comprobacion del replanteo is the moment a Spanish works contract becomes real. Until it is signed the contractor has an award and no obligation to be anywhere; from the day after, the plazo runs and every penalty for delay counts from it. That makes the act worth preparing rather than attending. Reservas raised in it about land not yet available, a service not diverted or a boundary that does not match the project are the cheapest reservas anyone will ever raise, because they are raised before the clock starts rather than claimed afterwards. The steps below get the evidence together first, put the signed act where it can be found in a year, and turn its date into the deadlines and the programme the contract asks for.",
  estMinutes: 15,
  steps: [
    {
      id: "readiness",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.in.project",
          label: "Project and site boundary",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.in.permits",
          label: "Permit and consent records",
        },
      ],
      outputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.out.status",
          label: "Site readiness status",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.out.gaps",
          label: "Gaps to raise as reservas",
        },
      ],
      titleKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.title",
      titleDefault: "Prove the site is available before you go",
      whatKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.what",
      whatDefault:
        "Work the mobilisation checklist before the date is set: land handed over, permits issued, services diverted or at least located, access agreed, welfare in place. Anything still open is a reserva you take to the act with you rather than a surprise you find on the ground. Under article 237 LCSP the comprobacion del replanteo has to take place within a month of formalisation of the contract, so the checklist runs from the day the contract is signed, not from the day somebody proposes a date.",
      whyKey: "cases.start_the_works_with_an_acta_de_replanteo.step.readiness.why",
      whyDefault:
        "A reserva raised in the acta suspends the start for exactly that part and costs nothing. The same fact discovered three weeks later is an extension of time you have to prove, against a clock that has already been running. The list is short and the asymmetry between the two outcomes is not.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "site_prep.title",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "sign",
      icon: "Signature",
      inputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.in.draft",
          label: "Draft acta document",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.in.parties",
          label: "Contract parties and their roles",
        },
      ],
      outputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.out.signed",
          label: "Signed acta with an audit trail",
        },
      ],
      titleKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.title",
      titleDefault: "Get the acta signed by both sides",
      whatKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.what",
      whatDefault:
        "Send the acta for signature by the direccion facultativa and by the contractor, with the reservas written into it rather than agreed verbally on the day. The signature record keeps who signed, when, and what document they signed.",
      whyKey: "cases.start_the_works_with_an_acta_de_replanteo.step.sign.why",
      whyDefault:
        "This is the single most consequential date on the contract and it is routinely captured as a scanned page in somebody's mail. A signed record with a trail is what answers, without ceremony, the question of whether a delay claim two years from now is counting from the right day.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "file",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.in.signed",
          label: "Signed acta",
        },
      ],
      outputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.out.filed",
          label: "Filed contract document",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.out.date",
          label: "Start date on record",
        },
      ],
      titleKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.title",
      titleDefault: "File it where the whole team can find it",
      whatKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.what",
      whatDefault:
        "Put the signed acta into the project files under the contract documents, not in the site folder, and make sure its date is the date on the document rather than the day somebody uploaded it.",
      whyKey: "cases.start_the_works_with_an_acta_de_replanteo.step.file.why",
      whyDefault:
        "Every subsequent argument about time, from a penalty to a revision de precios eligibility date, is measured from this one page. It is worth ten seconds of filing so that the person who needs it in eighteen months is not the only one who knows where it went.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "clock",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.in.date",
          label: "Acta date",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.in.plazo",
          label: "Contract plazo and milestones",
        },
      ],
      outputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.out.deadlines",
          label: "Tracked deadlines",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.out.owners",
          label: "An owner on every date",
        },
      ],
      titleKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.title",
      titleDefault: "Start the plazo and the dates that hang off it",
      whatKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.what",
      whatDefault:
        "Enter the completion date and the intermediate plazos parciales, counted from the acta, and put a name against each. Include the date by which the programa de trabajo itself is due, which on a public contract article 144 RGLCAP sets at thirty days from formalisation, so that one can already be running before the acta is signed.",
      whyKey: "cases.start_the_works_with_an_acta_de_replanteo.step.clock.why",
      whyDefault:
        "Dates that exist only in the contract are dates nobody is watching. The plazos parciales are the ones that carry penalties of their own and the ones a monthly meeting forgets first, precisely because the final date still looks reachable.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "programme",
      icon: "GanttChartSquare",
      inputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.in.date",
          label: "Acta date",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.in.scope",
          label: "Contract scope and quantities",
        },
      ],
      outputs: [
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.out.baseline",
          label: "Baseline programme",
        },
        {
          labelKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.out.submitted",
          label: "Programa de trabajo submitted",
        },
      ],
      titleKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.title",
      titleDefault: "Build the programa de trabajo from that date",
      whatKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.what",
      whatDefault:
        "Build the programme starting on the day after the acta, with the activities and the monthly quantities the contract asks you to show, and baseline it once it has been approved, which on a public contract is the Administration resolving on it within fifteen days of submission under article 144 RGLCAP, on the direccion facultativa's report.",
      whyKey: "cases.start_the_works_with_an_acta_de_replanteo.step.programme.why",
      whyDefault:
        "An approved programa is what an extension of time is later measured against, so it is worth being honest in rather than optimistic. A programme that started on the wrong day is worse than none at all: every comparison drawn from it is shifted, and the shift is invisible in the numbers.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
  ],
};

export default playbook;
