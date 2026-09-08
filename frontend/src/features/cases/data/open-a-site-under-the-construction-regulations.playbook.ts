// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Open a site under the Construction Regulations" (ZA).
//
// The Construction Regulations, 2014, made under the Occupational Health and
// Safety Act 85 of 1993, put a documented sequence in front of the first spade
// on a South African site: the client's baseline risk assessment and health
// and safety specification, then the construction work permit or the seven day
// notification, then the principal contractor's health and safety plan, then
// appointments in writing, and a health and safety file kept from the first day
// and handed to the client at the end. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "open-a-site-under-the-construction-regulations",
  order: 1345,
  category: "site",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["hse-officer", "site-manager", "project-manager"],
  region: "ZA",
  stage: "build",
  icon: "HardHat",
  titleKey: "cases.open_a_site_under_the_construction_regulations.title",
  titleDefault: "Open a site under the Construction Regulations",
  descKey: "cases.open_a_site_under_the_construction_regulations.desc",
  descDefault:
    "Work out whether the job needs a construction work permit or only a notification, get the specification and the plan the right way round, make every appointment in writing, and start the health and safety file on day one instead of rebuilding it at handover.",
  longDescKey: "cases.open_a_site_under_the_construction_regulations.longdesc",
  longDescDefault:
    "Regulation 3 of the Construction Regulations, 2014 stops work rather than fining it: where the intended construction work will exceed 180 days, or involve more than 1800 person days, or the works contract is of a value equal to or exceeding thirteen million rand or CIDB grading level 6, the client applies to the provincial director at least 30 days before, and no construction work may start until the permit and its site specific number have been issued. Under that sit the documents in a fixed order. The client writes the baseline risk assessment and the health and safety specification; the principal contractor writes the health and safety plan against that specification and the client approves it; the construction manager, the health and safety officer and the construction supervisors are appointed in writing; and the file that proves all of it is handed to the client on completion.",
  estMinutes: 14,
  steps: [
    {
      id: "permit",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.permit.in.scope", label: "Scope and duration" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.permit.in.value", label: "Works contract value" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.permit.out.route", label: "Permit or notification" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.permit.out.number", label: "Permit number" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.permit.title",
      titleDefault: "Decide between a permit and a notification, then apply",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.permit.what",
      whatDefault:
        "Measure the job against regulation 3(1): more than 180 days, more than 1800 person days, or a works contract value equal to or exceeding thirteen million rand or CIDB grading level 6. Any one of those means the client applies for a construction work permit at least 30 days before work starts. Below that, regulation 4(1) still requires notification at least 7 days before where the work includes excavation, work at height with a risk of falling, demolition or the use of explosives.",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.permit.why",
      whyDefault:
        "Regulation 3(7) forbids construction work before the permit and its number have been issued, and regulation 3(4) requires the number to be displayed conspicuously at the main entrance to the site. A programme that puts the first activity 30 days after award on a permit job is a programme that starts with an unlawful month, and an inspector reads the entrance board before anything else.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "spec",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.spec.in.design", label: "Design information" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.spec.in.hazards", label: "Site hazards" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.spec.out.bra", label: "Baseline risk assessment" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.spec.out.spec", label: "Health and safety specification" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.spec.title",
      titleDefault: "Get the client's specification written before tender",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.spec.what",
      whatDefault:
        "The client prepares a baseline risk assessment for the intended work under regulation 5(1)(a) and, on it, a site specific health and safety specification under regulation 5(1)(b), and gives that specification to the designer and to every tenderer. Where a permit is required, regulation 5(5) also has the client appoint a competent person in writing as agent, and regulation 5(7)(b) requires that agent to be registered with a statutory body approved by the Chief Inspector.",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.spec.why",
      whyDefault:
        "The specification is the client's document and it comes first, because the contractor's plan is written against it. A tender issued without one produces bids that have priced nothing for health and safety, and a contractor asked afterwards to write both documents has been asked to set its own standard and then to be measured against it.",
      moduleLabel: "HSE Management",
      moduleLabelKey: "nav.hse_advanced",
      to: "/projects/:projectId/hse-advanced",
    },
    {
      id: "plan",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.plan.in.spec", label: "Client specification" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.plan.in.method", label: "Method statements" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.plan.out.plan", label: "Health and safety plan" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.plan.out.ras", label: "Risk assessments" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.plan.title",
      titleDefault: "Write the plan against the specification and get it approved",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.plan.what",
      whatDefault:
        "The principal contractor prepares the health and safety plan required by regulation 7(1)(a) against the client's specification, with the risk assessments required by regulation 9 done by a competent person appointed in writing and forming part of the plan. The client then discusses and negotiates the contents of that plan with the principal contractor and finally approves it for implementation under regulation 5(1)(l).",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.plan.why",
      whyDefault:
        "An approved plan is what turns a generic safety policy into something enforceable on this site, activity by activity. It is also the document a client is entitled to stop work over: where the plan is not being followed the client may stop the work, and an approval that was never obtained leaves both sides arguing about what the standard was after somebody has been hurt.",
      moduleLabel: "Safety",
      moduleLabelKey: "nav.safety",
      to: "/projects/:projectId/safety",
    },
    {
      id: "appoint",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.in.people", label: "Nominated people" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.in.competence", label: "Competence evidence" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.out.letters", label: "Written appointments" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.out.chart", label: "Site responsibility chart" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.title",
      titleDefault: "Make every appointment in writing, and only for this site",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.what",
      whatDefault:
        "Appoint in writing, with the competence evidence attached: a full time construction manager for this single site under regulation 8(1), a construction health and safety officer under regulation 8(5) after consultation with the client and registered with an approved statutory body under regulation 8(6), and the construction supervisors that the construction manager itself must appoint in writing under regulation 8(7).",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.appoint.why",
      whyDefault:
        "Regulation 8(4) says a construction manager may not manage more than one site, and regulation 8(10) limits a construction supervisor in the same way unless enough competent employees are designated on every site involved. The habit of one manager covering three sites in a province is exactly what those subregulations forbid, and an appointment letter naming two sites is evidence of the breach rather than cover for it.",
      moduleLabel: "Site Supervision",
      moduleLabelKey: "site_supervision.title",
      to: "/projects/:projectId/site-supervision",
    },
    {
      id: "induct",
      icon: "Users",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.induct.in.workers", label: "Workers and visitors" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.induct.in.plan", label: "Approved plan" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.induct.out.records", label: "Induction records" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.induct.out.medicals", label: "Certificates of fitness" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.induct.title",
      titleDefault: "Induct everyone who comes through the gate",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.induct.what",
      whatDefault:
        "Run health and safety induction training for employees and for visitors, keep the record of it on site as regulation 7(7) requires, and hold a valid medical certificate of fitness in the form of Annexure 3 for every worker before they start.",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.induct.why",
      whyDefault:
        "Induction records and certificates of fitness are the two things checked first in an inspection and the two things hardest to reconstruct afterwards, because they are about individual people on individual days. A gate register that matches the induction list is the cheapest proof a site can hold, and it only exists if it is kept as people arrive.",
      moduleLabel: "Site Mobilisation",
      moduleLabelKey: "site_prep.title",
      to: "/projects/:projectId/site-prep",
    },
    {
      id: "audit",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.audit.in.plan", label: "Approved plan" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.audit.in.walks", label: "Site walks" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.audit.out.reports", label: "Audit reports" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.audit.out.actions", label: "Corrective actions" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.audit.title",
      titleDefault: "Keep the audit cycle running every thirty days",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.audit.what",
      whatDefault:
        "Regulation 5(1)(o) has the client ensure that health and safety audits and document verification are carried out at intervals agreed with the contractors but at least once every 30 days, and regulation 5(1)(p) puts the report in the principal contractor's hands within seven days. Log each finding as a corrective action with an owner and a date, and close it against evidence rather than against a promise.",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.audit.why",
      whyDefault:
        "A thirty day audit that nobody diarised becomes a ninety day audit, and a finding that was closed by conversation is a finding that comes back. The audit trail is also the client's own protection: the duty in regulation 5 is the client's, and a client that never audited cannot show it discharged it.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "file",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.file.in.records", label: "Site records" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.file.in.drawings", label: "Drawings and materials" },
      ],
      outputs: [
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.file.out.file", label: "Health and safety file" },
        { labelKey: "cases.open_a_site_under_the_construction_regulations.step.file.out.handover", label: "Handover to client" },
      ],
      titleKey: "cases.open_a_site_under_the_construction_regulations.step.file.title",
      titleDefault: "Keep the health and safety file, then hand it over",
      whatKey: "cases.open_a_site_under_the_construction_regulations.step.file.what",
      whatDefault:
        "Keep and maintain the health and safety file required by regulation 7(1)(b) from the first day of the job, and on completion hand a consolidated file to the client under regulation 7(1)(e), including a record of all drawings, designs and materials used and any other information about the structure.",
      whyKey: "cases.open_a_site_under_the_construction_regulations.step.file.why",
      whyDefault:
        "The file is not a closing document, it is the running record that happens to be handed over at the end. A file assembled in the last fortnight of a two year contract is missing the appointment letters of people who left, the certificates of materials nobody kept the delivery notes for, and the audit reports from the first winter. The client also needs it to run the building: the next contractor to open a ceiling is relying on what is in it.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
