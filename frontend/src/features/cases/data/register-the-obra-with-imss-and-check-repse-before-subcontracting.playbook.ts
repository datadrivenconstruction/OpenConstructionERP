// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Register the obra with IMSS and check REPSE before subcontracting"
// (MX).
//
// Hand written, not composed. Two obligations that arrive in the first week
// of a Mexican job and are usually met late, because neither of them looks
// like construction work.
//
// SIROC is the IMSS system for registering construction works, in place of
// the older SATIC. Article 12 of the Reglamento del Seguro Social
// Obligatorio para los Trabajadores de la Construccion por Obra o Tiempo
// Determinado requires the type of work, where it is and what will be done,
// registered within five working days of the works starting, and a
// subcontract notified within five working days of its signature.
//
// REPSE is the STPS register of providers of specialised services or works,
// created by the 2021 subcontracting reform. Subcontracting personnel is
// prohibited outright; a specialised service or work that is outside the
// beneficiary's own corporate purpose and predominant activity may be
// contracted, and only from a provider holding a current registration.
//
// The product has no IMSS or STPS connector. It has a site mobilisation
// checklist, an attendance record, a payroll record, a subcontractor
// directory with compliance documents and an authority submission log, which
// is where these obligations are tracked. The filings themselves are made on
// the IMSS and STPS portals, outside.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "register-the-obra-with-imss-and-check-repse-before-subcontracting",
  order: 1267,
  region: "MX",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["site-manager", "contract-administrator", "hse-officer"],
  icon: "HardHat",
  titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.title",
  titleDefault: "Register the obra with IMSS and check REPSE before subcontracting",
  descKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.desc",
  descDefault:
    "Register the works in SIROC within the days the reglamento allows, keep attendance and payroll agreeing with each other, verify a specialist's REPSE registration before you engage them, notify IMSS of the subcontract, and hold the monthly evidence before every payment.",
  longDescKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.longdesc",
  longDescDefault:
    "The 2021 subcontracting reform changed who may lawfully be engaged at all, and the answer is narrower than the habit of the industry. Subcontracting personnel is prohibited. What is permitted is contracting a specialised service or work that falls outside your own corporate purpose and predominant economic activity, from a provider registered with the STPS in the REPSE, and the sanction is not only a fine: a payment to an unregistered provider is not deductible for ISR and the IVA on it is not creditable, which turns a subcontract into a cost with tax on top. Running underneath that is the IMSS obligation, which is older and just as unforgiving. Construction works are registered in SIROC within five working days of starting, and a subcontract within five working days of its signature, so both of these land in the same week as mobilisation. Neither obligation is visible on site: nothing stops, nobody is turned away at the gate, and the discovery happens at an inspection or at the moment somebody tries to deduct the year's subcontract payments.",
  estMinutes: 20,
  steps: [
    {
      id: "siroc",
      icon: "Landmark",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.in.contract",
          label: "Contract, site address and start date",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.in.scope",
          label: "Type of work and what will be done",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.out.registered",
          label: "Obra registered in SIROC",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.out.reference",
          label: "Registration reference on the project",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.title",
      titleDefault: "Register the obra in SIROC in the first week",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.what",
      whatDefault:
        "Put the SIROC registration on the mobilisation checklist alongside the hoarding and the site office, with an owner and a date. It carries the type of work, where it is and the tasks that will be carried out, and it is due within five working days of the works starting, under article 12 of the Reglamento del Seguro Social Obligatorio para los Trabajadores de la Construccion por Obra o Tiempo Determinado. Keep the reference against the project once it is filed.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.siroc.why",
      whyDefault:
        "Five working days is roughly the time it takes to get the site fenced, so this obligation competes with everything else in the noisiest week of the job and loses. It is also the record every later IMSS question is answered from: without an obra registered, the contributions your workers generate have no work to attach to, and reconciling them afterwards is a task nobody has budgeted.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "site_prep.title",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "attendance",
      icon: "Users",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.in.crews",
          label: "Crews on site, own and subcontracted",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.in.hours",
          label: "Hours worked in the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.out.record",
          label: "Who was on site, by day",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.out.split",
          label: "Own workers separated from subcontracted",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.title",
      titleDefault: "Keep a record of who was actually on site",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.what",
      whatDefault:
        "Record attendance by day and by worker, and keep your own employees separate from the people a subcontractor brought. Do it as part of the daily routine rather than as a monthly reconstruction, because the value of the record is that it was written on the day.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.attendance.why",
      whyDefault:
        "The line between your workforce and somebody else's is the line the whole subcontracting reform turns on, and it is drawn on site rather than in the contract. A specialist whose people take their instructions from your foreman, use your tools and appear on your attendance list is not providing a specialised service whatever the contract says, and that is precisely how an inspection reads it.",
      moduleLabel: "Field Time",
      moduleLabelKey: "nav.field_time",
      to: "/projects/:projectId/field-time",
    },
    {
      id: "payroll",
      icon: "Coins",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.in.attendance",
          label: "Attendance for the period",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.in.categories",
          label: "Categories and salario base",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.out.payroll",
          label: "Payroll agreeing with the site record",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.out.contributions",
          label: "Contributions attributable to the obra",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.title",
      titleDefault: "Make the payroll agree with the site record",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.what",
      whatDefault:
        "Run the payroll from the attendance rather than beside it, so the workers paid, the workers registered with IMSS and the workers on site are the same list. Keep the contributions attributable to this obra visible against the project, because that is the form the IMSS question takes.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.payroll.why",
      whyDefault:
        "Three lists that should be identical are maintained by three different people, and nothing compares them until somebody outside the firm does. The gap is rarely fraud; it is a worker who started on Monday and was registered on Thursday, repeated across a year. Reconciled monthly it is a small correction, reconciled at an inspection it is an assessment.",
      moduleLabel: "Payroll",
      moduleLabelKey: "nav.payroll",
      to: "/projects/:projectId/payroll",
    },
    {
      id: "repse",
      icon: "SearchCheck",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.in.candidate",
          label: "Specialist you intend to engage",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.in.scope",
          label: "What the subcontract really covers",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.out.verified",
          label: "REPSE registration verified and dated",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.out.activity",
          label: "Registered activity matched to the scope",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.title",
      titleDefault: "Verify the REPSE before you engage, not before you pay",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.what",
      whatDefault:
        "Check two things in the STPS register and file the evidence with the date you checked it: that the provider holds a current REPSE, and that the activity it is registered for actually covers the work you are asking for. Then check the other half, which is your own: that the work is a specialised service or work outside your corporate purpose and predominant economic activity, rather than the placing of people at your disposal, which is prohibited.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.repse.why",
      whyDefault:
        "A payment to a provider that should have been registered and was not is not deductible for ISR, and the IVA on it is not creditable, so the cost of the mistake is the subcontract value plus the tax that was supposed to come back. The registration also has a term and can be lost, so a REPSE verified once at engagement is not evidence of anything two years later, and the verification has to carry a date to be worth filing.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "notify",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.in.signed",
          label: "Subcontract signed, with its date",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.in.registration",
          label: "Obra registration in SIROC",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.out.filed",
          label: "Subcontract notified to IMSS",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.out.log",
          label: "Filing logged with its acknowledgement",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.title",
      titleDefault: "Notify the subcontract inside its five days",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.what",
      whatDefault:
        "Give notice of the subcontract to IMSS within five working days of the day it was signed, using the format the system requires, and log the submission and its acknowledgement against the project alongside every other filing to an authority. The count runs from signature, not from the day the subcontractor first turns up.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.notify.why",
      whyDefault:
        "Signature and mobilisation can be weeks apart, and the deadline attaches to the earlier of them, so a subcontract signed in good time and started later is already late before anybody has done anything wrong. Logging the acknowledgement matters as much as filing: an obligation you believe you met is worth nothing at an inspection without the receipt.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "evidence",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.in.invoice",
          label: "Subcontractor invoice for the month",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.in.docs",
          label: "Compliance documents for the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.out.gate",
          label: "Payment released against evidence",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.out.file",
          label: "Monthly pack on file",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.title",
      titleDefault: "Hold the monthly evidence before you pay",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.what",
      whatDefault:
        "Make the monthly pack a condition of payment rather than a request: the REPSE still current, the opinion del cumplimiento de obligaciones fiscales, evidence that the IMSS and housing fund contributions for the period were paid, and the CFDI de nomina of the people who did the work. Release the payment against the pack, not against the promise of it.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.evidence.why",
      whyDefault:
        "This is the only leverage that exists. Once the money has gone the documents arrive slowly or not at all, and the exposure is yours rather than theirs, because it is your deduction that fails and, where a subcontractor does not pay its workers' contributions, your works those workers were on. A pack that is a condition of payment arrives every month without anybody chasing it.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "closeobra",
      icon: "Flag",
      inputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.in.completion",
          label: "Date the works finished",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.in.filings",
          label: "Filings made across the job",
        },
      ],
      outputs: [
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.out.closed",
          label: "Obra closed in SIROC",
        },
        {
          labelKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.out.pack",
          label: "Labour compliance pack archived",
        },
      ],
      titleKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.title",
      titleDefault: "Close the obra and archive what proves it",
      whatKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.what",
      whatDefault:
        "File the closure of the works in SIROC when they finish, and archive the labour compliance pack with the rest of the close-out documents: the registration and its amendments, the subcontract notices, the monthly evidence and the payroll reconciliations, kept together and kept for as long as the tax and social security records have to be kept.",
      whyKey: "cases.register_the_obra_with_imss_and_check_repse_before_subcontracting.step.closeobra.why",
      whyDefault:
        "An obra left open goes on looking like a live site to IMSS long after the hoarding came down, and it is the finished jobs that get audited, because the people who ran them have moved on and the folders have been split between offices. Archived as one pack at the close, the answer to an inspection two years later is one folder rather than a fortnight.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
