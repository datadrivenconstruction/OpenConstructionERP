// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Close out permits and statutory approvals".
//
// List every permit and condition, book the final statutory inspections,
// collect the completion certificates and confirm every condition is discharged
// so the building can be legally occupied. Content strings key plus inline default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "close-out-permits-and-statutory-approvals",
  order: 1028,
  category: "handover",
  companyTypes: ["general-contractor", "project-manager", "developer-client"],
  icon: "Landmark",
  titleKey: "cases.close_out_permits_and_statutory_approvals.title",
  titleDefault: "Close out permits and statutory approvals",
  descKey: "cases.close_out_permits_and_statutory_approvals.desc",
  descDefault:
    "List every permit and planning condition, book the final statutory inspections, collect the completion certificates and confirm every condition is discharged so the building can be legally occupied.",
  longDescKey: "cases.close_out_permits_and_statutory_approvals.longdesc",
  longDescDefault:
    "A building is not finished when the last trade leaves, it is finished when it is legal to use. The statutory sign-offs, discharged conditions and completion certificates are what let the client take occupation, and chasing them late can hold up a handover that is otherwise done.",
  estMinutes: 10,
  steps: [
    {
      id: "list",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.list.in.consents", label: "Consents and conditions" },
      ],
      outputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.list.out.schedule", label: "Approvals schedule" },
      ],
      titleKey: "cases.close_out_permits_and_statutory_approvals.step.list.title",
      titleDefault: "List every approval",
      whatKey: "cases.close_out_permits_and_statutory_approvals.step.list.what",
      whatDefault:
        "List every permit, statutory approval and planning condition the project carries, with what each one needs to be discharged and who is responsible for it.",
      whyKey: "cases.close_out_permits_and_statutory_approvals.step.list.why",
      whyDefault:
        "A condition forgotten until handover week can stall occupation. Listing them all early is what turns a scramble for certificates into a schedule that closes out in good time.",
      moduleLabel: "Handover",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "inspect",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.inspect.in.schedule", label: "Approvals schedule" },
      ],
      outputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.inspect.out.signoffs", label: "Statutory sign-offs" },
      ],
      titleKey: "cases.close_out_permits_and_statutory_approvals.step.inspect.title",
      titleDefault: "Book the final inspections",
      whatKey: "cases.close_out_permits_and_statutory_approvals.step.inspect.what",
      whatDefault:
        "Book the final statutory inspections - building control, fire, utilities and any specialist body - and record each sign-off against the approval it satisfies.",
      whyKey: "cases.close_out_permits_and_statutory_approvals.step.inspect.why",
      whyDefault:
        "Statutory inspectors work to their own diaries, not yours. Booking them early and tracking each sign-off is what keeps a missing inspection from becoming the thing that delays completion.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "certificates",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.certificates.in.signoffs", label: "Statutory sign-offs" },
      ],
      outputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.certificates.out.certificates", label: "Completion certificates" },
      ],
      titleKey: "cases.close_out_permits_and_statutory_approvals.step.certificates.title",
      titleDefault: "Collect the certificates",
      whatKey: "cases.close_out_permits_and_statutory_approvals.step.certificates.what",
      whatDefault:
        "Collect the completion certificates and approval letters into the handover file, so the proof that the building is signed off lives in one place the client can rely on.",
      whyKey: "cases.close_out_permits_and_statutory_approvals.step.certificates.why",
      whyDefault:
        "A certificate that cannot be found is a certificate that does not exist as far as a lawyer or a future buyer is concerned. Filing them properly protects the client for the life of the building.",
      moduleLabel: "Files",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "discharge",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.discharge.in.certificates", label: "Certificates collected" },
      ],
      outputs: [
        { labelKey: "cases.close_out_permits_and_statutory_approvals.step.discharge.out.occupiable", label: "Cleared for occupation" },
      ],
      titleKey: "cases.close_out_permits_and_statutory_approvals.step.discharge.title",
      titleDefault: "Confirm every condition discharged",
      whatKey: "cases.close_out_permits_and_statutory_approvals.step.discharge.what",
      whatDefault:
        "Confirm every condition is formally discharged and nothing is left outstanding, so the building is legally clear for the client to occupy and operate.",
      whyKey: "cases.close_out_permits_and_statutory_approvals.step.discharge.why",
      whyDefault:
        "One undischarged condition can make an occupied building non-compliant. Confirming the full set is closed is the final gate that lets everyone hand over and move on with confidence.",
      moduleLabel: "Handover",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
