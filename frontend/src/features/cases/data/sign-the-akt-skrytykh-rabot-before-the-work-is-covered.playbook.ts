// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Sign the akt skrytykh rabot before the work is covered" (RU).
//
// List what the next operation will hide, give the parties notice, have the
// materials documented and the work inspected, get the act signed by everyone the
// law names, and let a missing act hold back the payment for the position it
// covers. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "sign-the-akt-skrytykh-rabot-before-the-work-is-covered",
  order: 1307,
  category: "quality",
  companyTypes: ["general-contractor", "subcontractor", "developer-client"],
  roles: ["site-manager", "foreman", "document-controller", "quantity-surveyor"],
  region: "RU",
  icon: "FileCheck",
  titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.title",
  titleDefault: "Sign the akt skrytykh rabot before the work is covered",
  descKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.desc",
  descDefault:
    "List what the next operation will hide, give the parties notice, document the materials, have it inspected, get the act signed by everyone who must sign it, and keep a position without its act out of the month's acceptance.",
  longDescKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.longdesc",
  longDescDefault:
    "Ispolnitelnaya dokumentatsiya is the running record that the structure was built the way the design says, and the akt osvidetelstvovaniya skrytykh rabot is the part of it that cannot be recreated afterwards. Once the concrete is poured or the trench is backfilled, the only remaining proof that the reinforcement, the waterproofing or the bedding was right is the act signed while it could still be seen. Missing acts stop being a paperwork problem at two specific moments: when the client refuses to certify a KS-2 line for work it cannot verify, and when the object is handed over and the set has to be complete.",
  estMinutes: 13,
  steps: [
    {
      id: "holdpoints",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.in.programme", label: "Programme for the section" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.in.design", label: "Design and specification" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.out.list", label: "Hold points listed" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.out.notice", label: "Notice given to each party" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.title",
      titleDefault: "List what will be hidden and who has to attend",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.what",
      whatDefault:
        "Go through the coming section and put every operation whose result the next one will cover on the inspection and test plan as a hold point: reinforcement before the pour, waterproofing before the screed, bedding and buried services before backfill. Against each, set the signatories the act needs, the client's technical supervision and the designer where author supervision is required, the notice period you owe them, and the predecessor item that has to pass before it.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.holdpoints.why",
      whyDefault:
        "The form of the act and who signs it are set by the Ministry of Construction's rules on ispolnitelnaya dokumentatsiya, order 344/pr, and the parties have to be given time to get there. A hold point discovered on the morning of the pour becomes either a delayed pour or an act signed by whoever happened to be on site, and it is the second version that fails at handover.",
      moduleLabel: "Quality Management",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "materials",
      icon: "FlaskConical",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.in.delivery", label: "Delivered batch" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.in.papers", label: "Passports and certificates" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.out.matched", label: "Documents matched to the batch" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.out.tests", label: "Test results on file" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.title",
      titleDefault: "Have the documents for what is going in",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.what",
      whatDefault:
        "Log the passports, certificates of conformity and test reports for every material and product going into the hidden work as submittals of their own kind, certificate or test report, and check the batch named on the document against the batch that actually arrived before the submittal is approved.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.materials.why",
      whyDefault:
        "The act certifies the materials as well as the work, and it names them. A certificate covering a different batch, or one issued after the act was signed, is the first thing an inspection finds, because it is checkable from the paperwork alone without anybody going near the structure.",
      moduleLabel: "Submittals",
      moduleLabelKey: "submittals.title",
      to: "/projects/:projectId/submittals",
    },
    {
      id: "journal",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.in.day", label: "Work done that day" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.in.conditions", label: "Conditions and batch used" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.out.entry", label: "Journal entry" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.out.reference", label: "Entry the act refers to" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.title",
      titleDefault: "Write the day into the works journal",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.what",
      whatDefault:
        "Record the day in the general works journal: what was done and where, by whom, the weather where the process depends on it, the batch of concrete or mix used, and the entry number the act will refer back to.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.journal.why",
      whyDefault:
        "The journal and the act have to agree, because the journal is the continuous record and the act is a statement about one moment inside it. A dispute about when something was built is settled from the journal, and an act whose date has no matching entry is worth a great deal less than one that has.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "control",
      icon: "Eye",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.in.holdpoint", label: "Hold point reached" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.in.drawing", label: "Drawing and tolerances" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.out.result", label: "Inspection result" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.out.reinspect", label: "Re-inspection after fixes" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.title",
      titleDefault: "Have construction control look at it while it is visible",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.what",
      whatDefault:
        "Raise the inspection as hidden works at the hold point: your own construction control first, then the client's technical supervision, both against the drawing and the acceptance criteria rather than against the last act that was signed. Record a fail as a nonconformance and re-inspect once it is fixed; the gate stays closed until the result is a pass.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.control.why",
      whyDefault:
        "Construction control is a duty on the contractor and on the client, not a courtesy either of them extends, and this is the last moment at which a mistake in a hidden element can still be put right cheaply. After it is covered, the correction is demolition.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "construction_control.title",
      to: "/projects/:projectId/construction-control",
    },
    {
      id: "act",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.in.result", label: "Inspection result" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.in.parties", label: "Parties who must sign" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.out.act", label: "Signed act" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.out.permission", label: "Permission to proceed" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.title",
      titleDefault: "Get the act signed by everyone who has to sign it",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.what",
      whatDefault:
        "Draw up the act of examination of hidden works with the design references, the materials and their documents, the result of the inspection and the permission to begin the following works, then run a signing session that collects the signature of every required party before anything is covered.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.act.why",
      whyDefault:
        "The act is what permits the next operation to start and the only evidence that the hidden work was ever examined. An act drawn up later, with dates written to fit, is the document that gets challenged, because a signature added afterwards is not evidence that anybody looked.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "pack",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.in.acts", label: "Signed acts" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.in.expected", label: "Acts the programme expects" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.out.indexed", label: "Set indexed by structure" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.out.gaps", label: "Outstanding acts listed" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.title",
      titleDefault: "Keep the set complete as it accumulates",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.what",
      whatDefault:
        "File each signed act together with the journal entries, the material documents and the survey results it refers to, indexed by structure and by date, and keep a running list of the acts the programme still expects against the ones that exist.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.pack.why",
      whyDefault:
        "The set is assembled at handover and checked as a whole, and that is the point at which a missing act stops being retrievable at all. A running list of expected against actual turns a scramble at the end of the job into a line on the weekly meeting.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "payment",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.in.completed", label: "Hidden work completed" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.in.acts", label: "Acts covering it" },
      ],
      outputs: [
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.out.eligible", label: "Positions eligible for the month" },
        { labelKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.out.held", label: "Positions held back" },
      ],
      titleKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.title",
      titleDefault: "Let the act gate the payment for the work it covers",
      whatKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.what",
      whatDefault:
        "Tie each completed hidden operation to the position it belongs to in the month's acceptance, and record the period's quantity for a position only once its act is signed, so a position whose act is missing stays out of the submission until the act is there.",
      whyKey: "cases.sign_the_akt_skrytykh_rabot_before_the_work_is_covered.step.payment.why",
      whyDefault:
        "The client's technical supervision certifies what it can verify, and hidden work is verifiable only through its act. A position submitted without one is not just paid later, it invites the client to question the whole submission, and a disputed line is struck out while everything behind it waits.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
  ],
};

export default playbook;
