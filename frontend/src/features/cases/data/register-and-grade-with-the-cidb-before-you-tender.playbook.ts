// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Register and grade with the CIDB before you tender" (ZA).
//
// The Construction Industry Development Board Act 38 of 2000 and the
// construction industry development regulations made under it put two
// registers between a contractor and public sector work: the register of
// contractors, which grades a firm by class of work and by a grade that caps
// the value it may tender for, and the register of projects, which the client
// keeps. A bid from a firm without the right designation is not a losing bid,
// it is a bid that cannot be considered. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "register-and-grade-with-the-cidb-before-you-tender",
  order: 1342,
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["procurement-buyer", "commercial-manager", "contract-administrator"],
  region: "ZA",
  stage: "procure",
  icon: "BadgeCheck",
  titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.title",
  titleDefault: "Register and grade with the CIDB before you tender",
  descKey: "cases.register_and_grade_with_the_cidb_before_you_tender.desc",
  descDefault:
    "Read the grading designation a tender calls for, check your own registration and grade against it, keep the renewal off the critical path, and check the same thing on every subcontractor you carry with you.",
  longDescKey: "cases.register_and_grade_with_the_cidb_before_you_tender.longdesc",
  longDescDefault:
    "The register of contractors kept under the Construction Industry Development Board Act 38 of 2000 gives a firm a designation made of two parts: a class of work, such as general building or civil engineering or one of the electrical, mechanical and specialist classes, and a grade from 1 to 9 that caps the value of the contract it may tender for. A public sector client may not award construction works to a contractor that is not registered, and it may not award above the grade. That makes registration a tender gate rather than a formality, and the two ways firms lose work to it are letting the registration lapse in the week a bid is due, and putting a subcontractor on the team whose own designation does not cover the work it has been given.",
  estMinutes: 11,
  steps: [
    {
      id: "designation",
      icon: "FileSearch",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.in.tender", label: "Tender document" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.in.scope", label: "Scope of work" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.out.class", label: "Required class of work" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.out.grade", label: "Required grade" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.title",
      titleDefault: "Read the grading designation the tender calls for",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.what",
      whatDefault:
        "Open the tender and write down the designation it asks for, both halves of it: the class of work, and the grade. Then read the scope against the class, because a building contract with a substantial electrical or mechanical element can call for more than one class.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.designation.why",
      whyDefault:
        "The designation is the first thing an evaluation committee checks and the cheapest thing to fail on. A bid from a firm whose class of work does not cover the contract is not scored and then rejected, it is set aside before scoring, and the tender fee and three weeks of estimating go with it.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "ceiling",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.in.own", label: "Own registration" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.in.estimate", label: "Tender value" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.out.decision", label: "Bid or no bid" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.out.reason", label: "Recorded reason" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.title",
      titleDefault: "Check your own grade against the tender value",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.what",
      whatDefault:
        "Put your own designation next to your estimate of the tender value and make the bid or no bid decision on it. Each grade carries a tender value ceiling, rising through the nine grades, and only grade 9 has no upper limit.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.ceiling.why",
      whyDefault:
        "A grade is a ceiling, not a guideline: a public sector client cannot award above it whatever the merits of the price. Making the call before the estimating starts is the difference between a considered no bid and an expensive one, and recording why you passed is what lets you argue for an upgrade with evidence next year.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "renewal",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.in.certificate", label: "Registration certificate" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.in.pipeline", label: "Bid pipeline" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.out.expiry", label: "Expiry date tracked" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.out.reminder", label: "Renewal reminder" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.title",
      titleDefault: "Put the registration expiry on the deadline register",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.what",
      whatDefault:
        "Record the expiry date of the registration as a deadline with a reminder far enough ahead to renew, and put the same date against every bid in the pipeline that closes after it.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.renewal.why",
      whyDefault:
        "Registration is checked as at the closing date of the tender, not as at the day the work starts. A firm that has been on the register for eleven years and let it lapse for eleven days is, on that day, a firm a public sector client may not award to, and no amount of history changes that.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "subbies",
      icon: "Users",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.in.team", label: "Proposed subcontractors" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.in.packages", label: "Work packages" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.out.checked", label: "Checked designations" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.out.gaps", label: "Gaps to fill" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.title",
      titleDefault: "Check the designation of every subcontractor on the team",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.what",
      whatDefault:
        "For each package you intend to sublet, record the subcontractor, the class of work its designation carries and the value of the package, and flag any package whose value or class the subcontractor cannot cover.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.subbies.why",
      whyDefault:
        "The electrical and mechanical classes exist precisely because that work is graded separately from general building. A team assembled on price alone can be perfectly capable and still put a package with a firm whose designation does not reach it, and the tender document usually asks you to name them.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "evidence",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.in.certificates", label: "Registration certificates" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.in.returns", label: "Statutory returns" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.out.pack", label: "Compliance pack" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.out.current", label: "Current versions" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.title",
      titleDefault: "Keep one compliance pack the bid team can reach",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.what",
      whatDefault:
        "Hold the registration certificate, the tax clearance, the letter of good standing under the Compensation for Occupational Injuries and Diseases Act 130 of 1993 and the B-BBEE certificate or sworn affidavit in one place, each with the date it stops being current.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.evidence.why",
      whyDefault:
        "Every one of these documents is asked for by almost every tender and every one of them expires. Hunting for the current version on the afternoon a bid closes is how a compliant firm submits an expired certificate, and an expired certificate is treated as no certificate.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "projects",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.in.award", label: "Award details" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.in.value", label: "Contract value" },
      ],
      outputs: [
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.out.registration", label: "Project registered" },
        { labelKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.out.record", label: "Submission record" },
      ],
      titleKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.title",
      titleDefault: "Get the award onto the register of projects",
      whatKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.what",
      whatDefault:
        "Supply the client with what the register of projects needs and keep the record of the submission. A public sector client registers construction works above R200 000; for state owned entities and for private sector work the threshold is R10 million.",
      whyKey: "cases.register_and_grade_with_the_cidb_before_you_tender.step.projects.why",
      whyDefault:
        "The register of projects is the client's duty under the construction industry development regulations, but the data comes from the contractor and the delay lands on the contractor. It also matters to you later: the performance record built on registered projects is what a grading upgrade application is assessed on, so a project nobody registered is a project that never counted towards your next grade.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
  ],
};

export default playbook;
