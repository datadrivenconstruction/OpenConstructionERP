// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set the securities and work through to final completion" (ZA).
//
// Two things run together at the end of a South African contract and are
// usually handled by different people: the security, which decides how much of
// the contractor's money the employer is holding at any moment, and the
// completion sequence, which decides when each of those holds is released.
// Under the JBCC principal building agreement that sequence is practical
// completion, a ninety day defects liability period and final completion. On
// civil engineering work under the general conditions of contract for
// construction works it is three certificates, and the middle one is where the
// retention halves. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-the-securities-and-work-through-to-final-completion",
  order: 1347,
  category: "handover",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["contract-administrator", "commercial-manager", "project-manager"],
  region: "ZA",
  stage: "handover",
  icon: "ShieldCheck",
  titleKey: "cases.set_the_securities_and_work_through_to_final_completion.title",
  titleDefault: "Set the securities and work through to final completion",
  descKey: "cases.set_the_securities_and_work_through_to_final_completion.desc",
  descDefault:
    "Choose the security the contract offers, get the employer's guarantee for payment in return, hold the right percentage in each certificate, and walk the works through practical completion, the defects liability period and final completion so every hold is released on the day it should be.",
  longDescKey: "cases.set_the_securities_and_work_through_to_final_completion.longdesc",
  longDescDefault:
    "Clause 11.0 of the JBCC principal building agreement gives the contractor a real choice and most contractors make it by accident. A variable construction guarantee starts at ten per cent of the contract sum and reduces as the works reach practical and then final completion. A fixed construction guarantee is five per cent of the contract sum plus a payment reduction of five per cent of each certificate, capped at five per cent of the contract sum. Where no guarantee is given at all, clause 11.4.1 lets the employer withhold up to ten per cent, dropping to two and a half per cent at practical completion. The cash consequences of those three are very different, and so is the paperwork that releases them, which is the completion sequence in clauses 19.0 and 21.0.",
  estMinutes: 14,
  steps: [
    {
      id: "regime",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.in.contract", label: "Signed contract" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.in.cashflow", label: "Cash flow forecast" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.out.choice", label: "Security chosen" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.out.sequence", label: "Completion sequence" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.title",
      titleDefault: "Choose the security and write down the sequence",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.what",
      whatDefault:
        "Read clause 11.0 and pick: a variable construction guarantee at ten per cent of the contract sum, a fixed construction guarantee at five per cent plus a five per cent payment reduction, or no guarantee with the employer withholding up to ten per cent under clause 11.4.1. Then write down the completion sequence the form uses, because on civil engineering work under the general conditions of contract for construction works there are three certificates rather than two.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.regime.why",
      whyDefault:
        "The three choices cost different amounts of working capital at different moments, and a contractor that lets the employer decide has usually ended up with the most expensive one. The sequence matters for the same reason: under the general conditions of contract for construction works the defects liability period begins on the Certificate of Completion rather than at practical completion, so a contractor running that form on JBCC habits waits a year longer than it needs to for the second half of its retention.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "securities",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.in.forms", label: "Guarantee forms" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.in.bank", label: "Guarantor details" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.out.lodged", label: "Guarantee lodged" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.out.payment", label: "Guarantee for payment" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.title",
      titleDefault: "Lodge your guarantee and ask for theirs",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.what",
      whatDefault:
        "Issue the construction guarantee on the form the contract carries, record its expiry, and note the clause 11.2.1 duty to maintain or replace it at least twenty working days before it lapses. Then pursue the employer's guarantee for payment, which clause 11.5.1 requires within fifteen working days of acceptance of the tender, the same period clause 11.1 gives you for yours.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.securities.why",
      whyDefault:
        "The two securities are a pair and only one of them is usually chased. Clause 11.6 gives the contractor a ten working day notice and then the right to suspend where the employer's guarantee for payment is not given, and clause 11.10 has the contractor waive its lien over the works on receiving it, so a contractor that never received one has given up nothing and should not behave as though it had.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "reduction",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.in.certificates", label: "Payment certificates" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.in.choice", label: "Security chosen" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.out.held", label: "Amount held" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.out.release", label: "Release dates" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.title",
      titleDefault: "Hold the right percentage in every certificate",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.what",
      whatDefault:
        "Apply the reduction the chosen security calls for, certificate by certificate. Where the fixed construction guarantee was chosen, clause 25.12 pays ninety five per cent up to practical completion, ninety seven and a half per cent up to but excluding the final payment certificate, and one hundred per cent in it. Where no guarantee was given, clause 11.4.1 does the same job at ten per cent falling to two and a half.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.reduction.why",
      whyDefault:
        "This is the largest single amount of the contractor's money the employer holds and the easiest to lose track of, because it is spread across twenty certificates. Recording the percentage against every certificate with the event that releases it means the release happens on the certificate after that event rather than on the day somebody notices, and that difference is usually months of cash.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "inspection",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.in.notice", label: "Notice of inspection" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.in.works", label: "Completed works" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.out.list", label: "List for practical completion" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.out.dates", label: "Inspection dates" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.title",
      titleDefault: "Give the notice and take the list that comes back",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.what",
      whatDefault:
        "Give the principal agent at least five working days notice of the anticipated inspection date under clause 19.2.2, walk the works, and take the list of outstanding items for practical completion issued under clause 19.3.1. Work it to zero and call the re-inspection.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.inspection.why",
      whyDefault:
        "Clause 19.4 of the JBCC principal building agreement gives the contractor a remedy for a principal agent who goes quiet. Where the list for practical completion or the certificate is not issued within five working days after the inspection period, the contractor gives notice, and if a further five working days pass, practical completion is deemed to have been achieved on the date of that notice. Every step of that is a written notice, so a contractor that phones instead has no date to count from and nothing to deem.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "practical",
      icon: "Milestone",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.in.cleared", label: "Cleared list" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.in.reinspection", label: "Re-inspection" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.out.certificate", label: "Certificate of practical completion" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.out.completion", label: "List for completion" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.title",
      titleDefault: "Take practical completion and read what it changes",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.what",
      whatDefault:
        "Get the certificate of practical completion issued under clause 19.3.3, together with the list for completion under clause 19.3.4, and record the date on it. That date is the one the defects liability period, the penalty for late completion and the reduction in the security all count from.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.practical.why",
      whyDefault:
        "Practical completion moves several things at once: the employer becomes entitled to possession under clause 19.5, the penalty under clause 24.0 stops running, and the security steps down. Under the general conditions of contract for construction works the equivalent moment is split, and it is the Certificate of Completion, not practical completion, that returns the performance guarantee within fourteen days, starts the defects liability period and halves the retention.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "defects",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.in.list", label: "List for completion" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.in.reports", label: "Defects reported" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.out.closed", label: "Items closed" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.out.expiry", label: "Period end date" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.title",
      titleDefault: "Work the defects liability period to its end date",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.what",
      whatDefault:
        "The defects liability period begins the calendar day after practical completion and ends ninety calendar days from that date, or when the list for completion has been dealt with, whichever is later. Under clause 21.3.1 the contractor rectifies no later than ten working days before it expires, so plan the last inspection well inside the ninety days.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.defects.why",
      whyDefault:
        "Ninety calendar days is short, and the ten working day margin at the end of it is shorter still. A contractor that treats the period as three months of grace discovers in week eleven that the remaining items had to be finished in week ten, and the items it did not reach are the ones that keep the final completion certificate and the last of the security out of reach.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "final",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.in.rectified", label: "Rectified defects" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.in.warranties", label: "Subcontractor warranties" },
      ],
      outputs: [
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.out.certificate", label: "Certificate of final completion" },
        { labelKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.out.ceded", label: "Warranties ceded" },
      ],
      titleKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.title",
      titleDefault: "Get final completion certified and the security released",
      whatKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.what",
      whatDefault:
        "After the last inspection the principal agent has ten working days under clause 21.6 to issue either a list for final completion or the certificate of final completion. Collect the subcontractor guarantees and warranties, which are ceded to the employer at final completion under clauses 21.10 and 21.11, and release what remains of the security.",
      whyKey: "cases.set_the_securities_and_work_through_to_final_completion.step.final.why",
      whyDefault:
        "Clause 21.12 makes the certificate of final completion conclusive evidence that the works are satisfactory, other than for latent defects, so it is worth having and worth having on a date you can prove. It is also the date the latent defects liability period in clause 22.0 is measured from, which makes it the single most important date to record at the end of a South African building contract.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
  ],
};

export default playbook;
