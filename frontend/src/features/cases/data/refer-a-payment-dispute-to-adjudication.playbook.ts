// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Refer a payment dispute to adjudication" (GB).
//
// The statutory right to adjudicate runs on a timetable with no room in it
// for going and looking for records, so the case is about assembly rather
// than advocacy: what the clock says was notified, one reproducible evidence
// pack, service that cannot be challenged on jurisdiction, and the decision
// put back into the job. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "refer-a-payment-dispute-to-adjudication",
  order: 1168,
  region: "GB",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["commercial-manager", "quantity-surveyor", "contract-administrator"],
  stage: "build",
  icon: "Gavel",
  titleKey: "cases.refer_a_payment_dispute_to_adjudication.title",
  titleDefault: "Refer a payment dispute to adjudication",
  descKey: "cases.refer_a_payment_dispute_to_adjudication.desc",
  descDefault:
    "Establish what was notified and what was not, assemble the contemporaneous records into one pack both sides can reproduce, serve the notice where the contract says to serve it, file the referral with everything that goes with it, and put the decision back into the job.",
  longDescKey: "cases.refer_a_payment_dispute_to_adjudication.longdesc",
  longDescDefault:
    "The Housing Grants, Construction and Regeneration Act 1996 gives a party to a construction contract the right to refer a dispute to adjudication at any time, and the process is deliberately fast: the referral follows the notice within seven days and the adjudicator reaches a decision within twenty eight days of the referral unless the parties agree to extend it. Nothing in that timetable leaves room to go looking for records. The work that decides an adjudication was done months earlier, by whoever kept the notices, the diaries and the correspondence somewhere they could be found. This case is about that assembly rather than about the advocacy, and it assumes the argument itself is being run by people who do this for a living.",
  estMinutes: 15,
  steps: [
    {
      id: "position",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.in.application", label: "Payment application and notices" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.in.dates", label: "Statutory dates" },
      ],
      outputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.out.sum", label: "Notified sum, with its derivation" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.out.missed", label: "Notices missed or out of time" },
      ],
      titleKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.title",
      titleDefault: "Establish what was notified and what was not",
      whatKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.what",
      whatDefault:
        "Read the clock for the application in dispute: the dates, the notices actually served, the ones that were missed or served out of time, and the sum the module derives as notified. Take the derivation as it is printed rather than paraphrasing it into a sentence.",
      whyKey: "cases.refer_a_payment_dispute_to_adjudication.step.position.why",
      whyDefault:
        "Most British payment disputes are decided on the sequence rather than on the valuation. Whether a payment notice was served, whether a pay less notice stated its basis and whether either was in time will usually settle the sum before anybody looks at the work, so this is the cheapest thing to get right and the most expensive to get wrong.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "evidence",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.in.letters", label: "Notices, letters and RFIs" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.in.diary", label: "Diary and progress records" },
      ],
      outputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.out.pack", label: "Evidence pack" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.out.order", label: "Sources in a fixed order" },
      ],
      titleKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.title",
      titleDefault: "Assemble one pack both sides can reproduce",
      whatKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.what",
      whatDefault:
        "Build the evidence pack from the source records: the notices, the correspondence, the RFIs, the approvals, the variation records and any delay analysis. The ordering is deterministic and the pack carries a content digest, so feeding the same records in a different order produces the same bundle.",
      whyKey: "cases.refer_a_payment_dispute_to_adjudication.step.evidence.why",
      whyDefault:
        "An adjudicator reads a great deal of paper in a short time, and an ordered pack is read differently from a folder of attachments. A digest also means the other side cannot end up holding a slightly different bundle from the one the adjudicator has, which is a dispute nobody needs inside a dispute.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "serve",
      icon: "Send",
      inputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.in.pack", label: "Evidence pack" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.in.provisions", label: "Contract service provisions" },
      ],
      outputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.out.notice", label: "Notice of adjudication served" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.out.proof", label: "Date and method of service on record" },
      ],
      titleKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.title",
      titleDefault: "Serve the notice where the contract says to serve it",
      whatKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.what",
      whatDefault:
        "Issue the notice of adjudication through the correspondence register: to the right party, at the address the contract gives for service, stating the nature of the dispute, what is claimed and the redress sought. The register keeps the date and the method of service with it. Apply to the adjudicator nominating body the contract names in the same window, because the referral has to reach the adjudicator within seven days of the notice.",
      whyKey: "cases.refer_a_payment_dispute_to_adjudication.step.serve.why",
      whyDefault:
        "Service is where an otherwise good referral dies. A notice sent to the wrong entity inside a group, or to an email address the contract does not recognise, can be challenged on jurisdiction before anybody looks at the merits, and the seven days to the referral do not pause while that gets sorted out.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "file",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.in.referral", label: "Referral document and annexes" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.in.notice", label: "Notice of adjudication served" },
      ],
      outputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.out.set", label: "One filed set of the dispute" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.out.responses", label: "Responses filed as they arrive" },
      ],
      titleKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.title",
      titleDefault: "File the referral and everything that follows it",
      whatKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.what",
      whatDefault:
        "Put the referral and its annexes into the project files as one versioned, dated set alongside the notice. The response, the reply and the decision go into the same place as they arrive rather than into whoever happened to receive them.",
      whyKey: "cases.refer_a_payment_dispute_to_adjudication.step.file.why",
      whyDefault:
        "An adjudication produces a lot of documents in twenty eight days, across several people, usually while the job is still running. Keeping them in the project rather than in one mailbox is what lets the next stage, whether that is enforcement, a second adjudication or a settlement, start from the record instead of from a reconstruction.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "outcome",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.in.decision", label: "Decision and its date" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.in.sum", label: "Sum payable" },
      ],
      outputs: [
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.out.reported", label: "Outcome reported to the project" },
        { labelKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.out.valuations", label: "Valuations follow the decision" },
      ],
      titleKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.title",
      titleDefault: "Put the decision back into the job",
      whatKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.what",
      whatDefault:
        "Record the decision and what it changed: the sum payable, the date it is payable by, and any effect on the programme. An adjudicator's decision binds the parties until the dispute is finally determined, so it is the number the job works to from that day.",
      whyKey: "cases.refer_a_payment_dispute_to_adjudication.step.outcome.why",
      whyDefault:
        "The commonest failure after an adjudication is that the decision stays with the commercial team while the valuations carry on exactly as before. Reporting the outcome into the project is what makes the decision operate, and it also leaves the next job an honest record of what a dispute of this kind cost in time and attention.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
