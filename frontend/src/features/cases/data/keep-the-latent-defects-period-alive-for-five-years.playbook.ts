// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep the latent defects period alive for five years" (ZA).
//
// Clause 22.0 of the JBCC principal building agreement runs a latent defects
// liability period that commences at the start of the construction period and
// ends five years from the certified date of final completion. Five years is
// long enough that the people who built the building have gone, which is why
// this case is about the record rather than about the law: the date, the
// handover pack, the ceded warranties and somebody whose job it is to notice.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-the-latent-defects-period-alive-for-five-years",
  order: 1348,
  category: "handover",
  companyTypes: ["developer-client", "owner-operator", "project-manager"],
  roles: ["contract-administrator", "project-manager", "document-controller"],
  region: "ZA",
  stage: "operate",
  icon: "Gavel",
  titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.title",
  titleDefault: "Keep the latent defects period alive for five years",
  descKey: "cases.keep_the_latent_defects_period_alive_for_five_years.desc",
  descDefault:
    "Fix the certified date of final completion, keep the handover record that makes a hidden defect provable, hold the ceded warranties where somebody can find them, and put the five year end date in front of the person who will still be there.",
  longDescKey: "cases.keep_the_latent_defects_period_alive_for_five_years.longdesc",
  longDescDefault:
    "A latent defect is one that was not reasonably discoverable when the works were accepted, and clause 22.1 of the JBCC principal building agreement gives the employer five years from the certified date of final completion to pursue it. That is a long window and almost every part of it is lost to record keeping rather than to law. The certified date sits on a certificate nobody filed. The as-built drawings and the health and safety file that would show how the detail was actually built are in a box. The subcontractor warranties that were ceded to the employer under clauses 21.10 and 21.11 were never registered against anything. Five years later a facilities manager finds water where it should not be and has a claim on paper and nothing to prove it with.",
  estMinutes: 11,
  steps: [
    {
      id: "date",
      icon: "CalendarCheck",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.in.certificate", label: "Certificate of final completion" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.in.contract", label: "Signed contract" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.out.start", label: "Certified date recorded" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.out.end", label: "Five year end date" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.title",
      titleDefault: "Record the certified date and count five years from it",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.what",
      whatDefault:
        "Take the certified date of final completion off the certificate itself, store the certificate with the project rather than in a personal folder, and calculate the date five years on that clause 22.1 gives as the end of the latent defects liability period.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.date.why",
      whyDefault:
        "Everything else in this case counts from that one date, and it is not the date of practical completion, the date of the handover meeting or the date the client moved in. Clause 22.3 also runs five years from termination where the agreement was terminated early, so a job that ended badly has a different start date and usually nobody who wrote it down.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "record",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.in.asbuilt", label: "As-built drawings" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.in.file", label: "Health and safety file" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.out.pack", label: "Handover pack" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.out.index", label: "Searchable index" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.title",
      titleDefault: "Keep the record that makes a hidden defect provable",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.what",
      whatDefault:
        "Hold the as-built drawings, the specifications, the test and commissioning results, the material approvals and the consolidated health and safety file handed over under regulation 7(1)(e) of the Construction Regulations, 2014, indexed so somebody who was not on the project can find a detail by where it is in the building.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.record.why",
      whyDefault:
        "A latent defect claim turns on showing what was specified, what was actually built and why the difference was not visible at final completion. That is a documents case, and the documents are the ones handed over at the end of the job. A pack that exists but cannot be searched is, four years later, the same as no pack.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "warranties",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.in.ceded", label: "Ceded warranties" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.in.products", label: "Product guarantees" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.out.register", label: "Warranty register" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.out.owner", label: "Party liable" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.title",
      titleDefault: "Register every warranty against what it covers",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.what",
      whatDefault:
        "Register the subcontractor guarantees and product warranties ceded to the employer at final completion under clauses 21.10 and 21.11, each against the element it covers, the party liable under it and the date it runs out.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.warranties.why",
      whyDefault:
        "A waterproofing guarantee and the latent defects liability period are two separate routes to the same repair, and they expire on different days against different parties. An owner that registered neither ends up paying for a roof it had two claims for, and the subcontractor whose warranty it was has usually moved on by then.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "assets",
      icon: "Building2",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.in.handover", label: "Handover pack" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.in.plant", label: "Installed plant" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.out.register", label: "Asset register" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.out.inspections", label: "Inspection schedule" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.title",
      titleDefault: "Put the building somewhere it will be looked at",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.what",
      whatDefault:
        "Load the building and its plant onto the asset register with the warranty and the latent defects end date attached, and set an inspection before that date rather than only routine maintenance after it.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.assets.why",
      whyDefault:
        "Latent defects are latent, which means nobody is going to trip over them. The failures that are still recoverable in year four, movement in a slab, a failing membrane, a settled apron, are the ones somebody went looking for. An inspection booked deliberately against the end date is the only mechanism that turns a five year right into five years of use.",
      moduleLabel: "Building Assets (FM)",
      moduleLabelKey: "nav.assets",
      to: "/assets",
    },
    {
      id: "report",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.in.complaint", label: "Reported fault" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.in.evidence", label: "Photos and readings" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.out.job", label: "Logged job" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.out.cause", label: "Cause and classification" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.title",
      titleDefault: "Log the fault as evidence, not only as a repair",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.what",
      whatDefault:
        "When a fault is reported, log it with the date, the location, photographs and any readings before anyone opens anything up, and classify it: wear, an operating fault, a defect covered by a live warranty, or a construction defect that was not discoverable at final completion.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.report.why",
      whyDefault:
        "The most common way a good latent defect claim dies is that maintenance repaired the evidence in the first week. Once the failed detail has been cut out and replaced, what remains is an invoice and an opinion. Recording the condition before the repair costs an hour and is the whole difference between a claim and a complaint.",
      moduleLabel: "Service & Maintenance",
      moduleLabelKey: "nav.service",
      to: "/projects/:projectId/service",
    },
    {
      id: "pursue",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.in.classified", label: "Classified defect" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.in.end", label: "Five year end date" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.out.notice", label: "Notice to the contractor" },
        { labelKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.out.tracked", label: "Tracked claim" },
      ],
      titleKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.title",
      titleDefault: "Raise it in writing while the period is still open",
      whatKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.what",
      whatDefault:
        "Put the defect to the contractor in writing with the evidence attached and the contractual basis named, track the claim against the end of the latent defects liability period, and keep the deadline visible to whoever holds the building rather than only to the project team that has moved on.",
      whyKey: "cases.keep_the_latent_defects_period_alive_for_five_years.step.pursue.why",
      whyDefault:
        "Clause 21.12 makes the certificate of final completion conclusive as to the sufficiency of the works other than for latent defects, so the latent defects liability period in clause 22.0 is the only door left open. A claim raised a week after the five years is worth exactly nothing however good the evidence behind it, and the person who would have known the date usually left the company in year two.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
