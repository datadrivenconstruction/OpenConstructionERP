// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Check SRO membership before anyone starts work" (RU).
//
// Record what each work package legally requires, check the membership and level
// of every firm you intend to use, make it a condition of award, keep the
// register extract that proves it and put the dates that can lapse on a clock.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "check-sro-membership-before-anyone-starts-work",
  order: 1305,
  category: "quality",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["contract-administrator", "procurement-buyer", "project-manager", "document-controller"],
  region: "RU",
  icon: "BadgeCheck",
  titleKey: "cases.check_sro_membership_before_anyone_starts_work.title",
  titleDefault: "Check SRO membership before anyone starts work",
  descKey: "cases.check_sro_membership_before_anyone_starts_work.desc",
  descDefault:
    "Write down what each work package legally requires, check the membership and the level of responsibility of every firm you intend to use, make it a condition of award, file the register extract and watch the dates that lapse.",
  longDescKey: "cases.check_sro_membership_before_anyone_starts_work.longdesc",
  longDescDefault:
    "In Russia the right to carry out construction, design or survey work comes from membership of a self-regulatory organisation rather than from a licence. Membership is not a formality. The level of responsibility a member holds limits the value of the work it may take on, and it is backed by that member's contribution to the SRO's compensation fund, which is what the client is actually relying on if something goes wrong. A subcontractor working outside its level is not merely non-compliant: the client's own acceptance of that work is exposed, and it usually surfaces at handover, when the cheapest remedies are already gone.",
  estMinutes: 11,
  steps: [
    {
      id: "requirements",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.in.disciplines", label: "Disciplines on the job" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.in.holders", label: "Firms or people who hold it" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.out.requirement", label: "Blocking requirement per discipline" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.out.exempt", label: "Work that needs none" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.title",
      titleDefault: "Say what each discipline on the job actually requires",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.what",
      whatDefault:
        "For each discipline, record what the firm or the individual doing it must hold: SRO membership in construction, in design or in survey, and any separate authorisation the work itself carries, such as work on a cultural heritage object or on a hazardous production facility. Mark the requirement blocking where a gap has to stop the work, and set the grace period you are willing to allow.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.requirements.why",
      whyDefault:
        "The requirement belongs to the work rather than to the supplier, and writing it down first is what makes every later check mechanical instead of a judgement call. Blocking is the decision that matters, because a requirement that is only a note stops nobody. It also surfaces the work that needs no membership at all, since the Town Planning Code exempts contracts below a stated value and certain categories of work, and demanding it there costs you bidders for nothing.",
      moduleLabel: "Credentials",
      moduleLabelKey: "nav.credentials",
      to: "/credentials",
    },
    {
      id: "check",
      icon: "Users",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.in.firms", label: "Firms under consideration" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.in.extract", label: "Register extract" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.out.status", label: "Prequalification decided" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.out.mismatch", label: "Firms blocked with a reason" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.title",
      titleDefault: "Prequalify every firm against its own register extract",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.what",
      whatDefault:
        "For each firm, work through the prequalification questionnaire with the register extract in front of you: which SRO it belongs to, its membership number, when it joined, and which level of responsibility it holds against the value of the work you mean to give it. Attach the extract, and block the firm with the reason written down where the level does not cover that work. Read it from the extract, not from the scan on the firm's letterhead.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.check.why",
      whyDefault:
        "Membership is a live status rather than a certificate: it can be suspended or terminated while the firm goes on sending the same scanned page. The level is the part most often wrong, because a firm that is genuinely a member is very often a member at a level below the contract it is about to sign.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "gate",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.in.requirement", label: "Requirement per package" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.in.offers", label: "Offers received" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.out.eligible", label: "Eligible bidders" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.out.blocked", label: "Award blocked without cover" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.title",
      titleDefault: "Make it a condition of award, not a question afterwards",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.what",
      whatDefault:
        "Attach the requirement to the package in procurement so that an award cannot be made to a firm that does not meet it, and ask for the register extract as part of the offer rather than as something to be produced once the work is under way.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.gate.why",
      whyDefault:
        "Checked after award this only ever produces bad options: re-tender and lose the programme, or carry on with a contractor whose work you may not be able to hand over. Checked as a condition of award it costs one field on the offer form.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "evidence",
      icon: "Paperclip",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.in.extract", label: "Register extract with its date" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.in.insurance", label: "Insurance and permits" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.out.filed", label: "Evidence on the package" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.out.dated", label: "Proof dated before the work" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.title",
      titleDefault: "Keep the register extract that proves it",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.what",
      whatDefault:
        "File the register extract for each firm together with the date it was taken, alongside the insurance and any separate authorisation, and keep it attached to the work package rather than in a general supplier folder.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.evidence.why",
      whyDefault:
        "When the client's technical supervision or an inspection asks who was entitled to do this work, the answer has to be a document dated before the work started. An extract pulled after the question is asked proves only that the firm is a member today, which is a much weaker statement and usually the wrong one.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "clause",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.in.award", label: "Firm cleared for award" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.in.template", label: "Subcontract clause template" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.out.obligation", label: "Membership as a standing obligation" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.out.notice", label: "Duty to report a lapse" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.title",
      titleDefault: "Write the membership into the subcontract as a standing duty",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.what",
      whatDefault:
        "Put the requirement in the subcontract itself: membership held for the whole term and not only at signature, notice to you within a fixed number of days if it is suspended or terminated, and the right to suspend the work and withhold payment until it is restored.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.clause.why",
      whyDefault:
        "Membership lapses quietly and the SRO writes to its member, not to you. Checked once at award, it is a snapshot; written into the contract, it is a duty that runs for the whole term and gives you something to act on. A firm that was covered at award and is not covered in month eight goes on signing acts the client can later refuse, and that is normally found while the handover package is being checked.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "compliance",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.in.holders", label: "Every firm and person on site" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.in.requirements", label: "Requirements that bind them" },
      ],
      outputs: [
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.out.stopped", label: "Who may not work today" },
        { labelKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.out.unmatched", label: "Requirements binding nobody" },
      ],
      titleKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.title",
      titleDefault: "Read who may not work today, and what lapses next",
      whatKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.what",
      whatDefault:
        "Read the compliance answer across the project: holders a blocking requirement stops outright, holders still inside their grace period, credentials expiring soon, and requirements that bind nobody at all because no holder on the register matches them. Clear that list before those firms reach the site.",
      whyKey: "cases.check_sro_membership_before_anyone_starts_work.step.compliance.why",
      whyDefault:
        "This is the rare compliance question that is arithmetic rather than judgement, so it belongs in a report read on a date and not in somebody's habit. Expiry is worked out from the dates each time it is read rather than from a status somebody typed once, which is the only version of this check that survives a firm renewing late. A requirement binding nobody is the other half of the finding: the work is being done by somebody the requirement never reached.",
      moduleLabel: "Credentials",
      moduleLabelKey: "nav.credentials",
      to: "/credentials",
    },
  ],
};

export default playbook;
