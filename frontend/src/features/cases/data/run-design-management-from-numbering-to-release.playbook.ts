// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run design management from numbering to release".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-design-management-from-numbering-to-release",
  order: 1685,
  category: "planning",
  stage: "design",
  companyTypes: ["developer-client", "project-manager", "designer"],
  roles: ["design-lead", "document-controller", "project-manager"],
  requiresProject: true,
  icon: "PenTool",
  titleKey: "cases.run_design_management_from_numbering_to_release.title",
  titleDefault: "Run design management from numbering to release",
  descKey: "cases.run_design_management_from_numbering_to_release.desc",
  descDefault:
    "Set the numbering scheme, the design team and the design schedule, register drawings, issue releases to the right recipients, run the reviews and assemble the permit package.",
  longDescKey: "cases.run_design_management_from_numbering_to_release.longdesc",
  longDescDefault:
    "Design management is where the client keeps control of a design produced by many firms. Design management fixes how drawings are numbered, who designs what and when, who releases a drawing for issue and how comments are closed. It owns no files of its own: drawings live in the document environment, releases become transmittals, and the registers are filed back as a revision of the frame document.",
  estMinutes: 18,
  steps: [
    {
      id: "setup",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.setup.in.country", label: "Project country" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.setup.out.scheme", label: "Numbering scheme" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.setup.title",
      titleDefault: "Set up design management",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.setup.what",
      whatDefault:
        "Press Set up design management, pick the numbering scheme recommended for the project's country and decide whether a release must be issued by a second person.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.setup.why",
      whyDefault:
        "A numbering scheme agreed on day one keeps every drawing findable for the life of the building. The four-eyes release rule stops unchecked drawings reaching site.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=setup",
    },
    {
      id: "team",
      icon: "Users",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.team.in.scope", label: "Project scope" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.team.out.team", label: "Design team and breakdown" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.team.title",
      titleDefault: "Build the breakdown and the team",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.team.what",
      whatDefault:
        "On the Design team tab press Add role for each role and who fills it, then on the Work breakdown tab press Add node for the parts of the design.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.team.why",
      whyDefault:
        "Every drawing and every decision belongs to a part of the building and to a responsible designer. Without that, comments have nowhere to go.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=team",
    },
    {
      id: "schedule",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.schedule.in.programme", label: "Project programme" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.schedule.out.dschedule", label: "Design schedule" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.schedule.title",
      titleDefault: "Plan the design schedule",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.schedule.what",
      whatDefault:
        "On the Design schedule tab, press Add schedule line for what each designer delivers, then Add approval point where the client has to sign off, and press Send for approval on each point.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.schedule.why",
      whyDefault:
        "Design that has no dates arrives when it arrives. Approval points make the client's own decisions part of the plan.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=schedule",
    },
    {
      id: "drawings",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.drawings.in.scheme", label: "Numbering scheme" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.drawings.out.register", label: "Drawing register" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.drawings.title",
      titleDefault: "Register the drawings",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.drawings.what",
      whatDefault:
        "On the Drawings tab, add drawings with their generated numbers, then run Check all numbers and Check title block.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.drawings.why",
      whyDefault:
        "A wrong number or title block is cheap to fix in the register and expensive to fix on a revision that is already on site.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=drawings",
    },
    {
      id: "issue",
      icon: "Send",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.issue.in.register", label: "Drawing register" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.issue.out.transmittals", label: "Transmittals per recipient" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.issue.title",
      titleDefault: "Issue a release",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.issue.what",
      whatDefault:
        "On the Issue tab, press New release, add the drawings and press Mark ready. If a second person must issue releases, wait for Approved for issue, then press Issue. One transmittal is created per recipient and this cannot be undone.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.issue.why",
      whyDefault:
        "Releasing through the register means every recipient gets the same revision and the record shows who got what, when.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=issue",
    },
    {
      id: "reviews",
      icon: "MessageSquarePlus",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.reviews.in.drawings", label: "Issued drawings" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.reviews.out.review", label: "Concluded design review" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.reviews.title",
      titleDefault: "Run the design reviews",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.reviews.what",
      whatDefault:
        "On the Reviews tab, press New review and Open for comments, add comments and have the designer answer them. Accept or reject each answer, then press Close comments and Record outcome.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.reviews.why",
      whyDefault:
        "A concluded review cannot be reopened, so the record of what was checked stays reliable.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=reviews",
    },
    {
      id: "permit",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.permit.in.register", label: "Drawing register" },
      ],
      outputs: [
        { labelKey: "cases.run_design_management_from_numbering_to_release.step.permit.out.package", label: "Permit package" },
      ],
      titleKey: "cases.run_design_management_from_numbering_to_release.step.permit.title",
      titleDefault: "Assemble the permit package",
      whatKey: "cases.run_design_management_from_numbering_to_release.step.permit.what",
      whatDefault:
        "On the Permit tab, press New permit package and Add item for each drawing, report and form. When no required item shows Missing or Not shared yet, press Mark ready, and the package shows Ready to submit.",
      whyKey: "cases.run_design_management_from_numbering_to_release.step.permit.why",
      whyDefault:
        "The permit package is the design's first hard deadline. Building it from the register shows exactly what is still missing.",
      moduleLabel: "Design management",
      moduleLabelKey: "design.ui.title",
      to: "/projects/:projectId/design?tab=permit",
    },
  ],
};

export default playbook;
