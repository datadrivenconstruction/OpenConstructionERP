// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Lodge regulated designs under the Design and Building Practitioners
// Act" (AU, New South Wales).
//
// The declaration regime New South Wales built after the national Building
// Confidence review: regulated designs prepared by registered design
// practitioners, a design compliance declaration for each of them, an optional
// principal design practitioner who collects and lodges, and a building
// compliance declaration from the registered builder before an occupation
// certificate can be applied for. The lodgements run through the state planning
// portal, and the ones that follow a change on site are the half that gets
// missed. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "lodge-regulated-designs-under-the-design-and-building-practitioners-act",
  order: 1664,
  region: "AU",
  category: "quality",
  companyTypes: ["general-contractor", "designer", "developer-client", "project-manager"],
  roles: ["design-lead", "document-controller", "contract-administrator", "project-manager"],
  stage: "design",
  icon: "BadgeCheck",
  titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.title",
  titleDefault: "Lodge regulated designs under the Design and Building Practitioners Act",
  descKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.desc",
  descDefault:
    "Decide which drawings are regulated designs, check every practitioner is registered for the class of work they are declaring, collect the construction issued designs and their compliance declarations, lodge them before building work starts, catch the site change that creates a new regulated design and close out with the declaration the occupation certificate depends on.",
  longDescKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.longdesc",
  longDescDefault:
    "The Design and Building Practitioners Act 2020 changed what a design deliverable is in New South Wales. A regulated design is not simply a drawing any more, it is a document that a registered practitioner has personally declared complies with the Building Code of Australia, lodged with the state before the work it covers is built, and declared again if it changes. The practical consequence is a documentation discipline rather than a design one, and the projects that come unstuck are rarely the ones with bad designs. They are the ones where a variation was built on a marked up sketch, no new regulated design was ever declared, and the gap surfaces at the occupation certificate with the building finished and the practitioner who could have declared it no longer engaged.",
  estMinutes: 18,
  steps: [
    {
      id: "scope",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.in.documents", label: "Design documents for the job" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.in.classes", label: "Building class and work type" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.out.list", label: "List of regulated designs" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.out.owner", label: "Practitioner responsible for each" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.title",
      titleDefault: "Decide which designs are regulated designs",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.what",
      whatDefault:
        "Work through the design register and mark which documents are regulated designs, the ones covering building elements the regulation names, such as fire safety systems, waterproofing, and the internal and external load bearing components, together with the performance solutions that support them. Name the practitioner who will declare each one.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.scope.why",
      whyDefault:
        "The list decides the whole workflow, and it is drawn once at the start when it is cheap. A document identified as regulated three months into construction needs a declaration from a practitioner who may not have been engaged on that basis, at a price nobody budgeted, for work that is already built.",
      moduleLabel: "Review Authority",
      moduleLabelKey: "review_authority.title",
      to: "/projects/:projectId/review-authority",
    },
    {
      id: "practitioners",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.in.team", label: "Design team engaged" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.in.classes", label: "Classes of design work" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.out.registered", label: "Registration checked per class" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.out.expiry", label: "Expiry and insurance dates watched" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.title",
      titleDefault: "Check the registration covers the class being declared",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.what",
      whatDefault:
        "Record each practitioner's registration, the classes of design work it authorises and its expiry, along with the professional indemnity cover the scheme requires. Check the registration against the class of the design they are being asked to declare, not simply that they hold one.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.practitioners.why",
      whyDefault:
        "A declaration made by someone whose registration does not authorise that class of work is not a declaration, and the failure is invisible until it is checked. Registration also expires mid project, which turns a valid declaration into a problem on a date nobody was watching.",
      moduleLabel: "Credentials",
      moduleLabelKey: "nav.credentials",
      to: "/credentials",
    },
    {
      id: "designs",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.in.issued", label: "Construction issued drawings" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.in.list", label: "List of regulated designs" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.out.collected", label: "Designs collected with revisions" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.out.gaps", label: "Missing designs visible" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.title",
      titleDefault: "Collect the construction issued designs and their revisions",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.what",
      whatDefault:
        "Run the regulated designs through the submittal register so each one arrives with its revision, its date and the practitioner who prepared it, and so a design still outstanding is visible as an outstanding item rather than as an absence nobody noticed.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.designs.why",
      whyDefault:
        "What is lodged has to be the version that will actually be built from, and a register that tracks revisions is the only thing that keeps those two the same document. A declaration attached to a superseded revision is worse than none, because it reads as compliance while describing a building nobody is constructing.",
      moduleLabel: "Submittals",
      moduleLabelKey: "submittals.title",
      to: "/projects/:projectId/submittals",
    },
    {
      id: "declarations",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.in.collected", label: "Designs collected with revisions" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.in.registered", label: "Registration checked per class" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.out.design", label: "Design compliance declarations" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.out.principal", label: "Principal declaration where appointed" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.title",
      titleDefault: "Get a declaration for every regulated design",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.what",
      whatDefault:
        "Collect a design compliance declaration signed by the registered design practitioner for each regulated design. Where a principal design practitioner has been appointed, they make the principal compliance declaration that the designs are covered and the declarations were made by practitioners authorised to make them.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.declarations.why",
      whyDefault:
        "The declaration is a personal statement by a named practitioner and it carries personal consequences, which is why it is chased rather than given. Collecting them as they are signed, against a list drawn at the start, is the difference between a routine administrative task and a search for six people at the end of a job.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "lodge",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.in.designs", label: "Designs and declarations" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.in.start", label: "Planned start on site" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.out.lodged", label: "Lodged before work starts" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.out.receipt", label: "Lodgement receipts on file" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.title",
      titleDefault: "Lodge them before the work they cover starts",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.what",
      whatDefault:
        "Lodge the construction issued regulated designs and their declarations through the state planning portal before building work commences, and keep the lodgement receipts against the submission record so the date can be shown rather than remembered.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.lodge.why",
      whyDefault:
        "The obligation is tied to the start of the work rather than to a milestone anybody celebrates, so the deadline arrives while the site is mobilising and everyone is busy with something else. Lodging late is not curable by lodging afterwards, because the record shows when the work started.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "changes",
      icon: "GitCompareArrows",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.in.variation", label: "Design change on site" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.in.lodged", label: "What was lodged before" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.out.varied", label: "Varied design declared again" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.out.asbuilt", label: "What was built matches what was declared" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.title",
      titleDefault: "Treat a change on site as a new regulated design",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.what",
      whatDefault:
        "Route every change that touches a regulated design back through the same loop, a varied regulated design, a fresh declaration from a registered practitioner and a lodgement, before the varied work is built. Keep the link between the change and the design it varied.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.changes.why",
      whyDefault:
        "This is the step the regime is most often failed on, and it fails quietly. Work built to a marked up sketch is work with no declared design behind it, and nothing on site looks wrong; the gap appears at the end, when the building is finished and the only remedies are expensive.",
      moduleLabel: "Quality Management",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "occupation",
      icon: "Trophy",
      inputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.in.declared", label: "All declarations lodged" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.in.works", label: "Building work complete" },
      ],
      outputs: [
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.out.building", label: "Building compliance declaration" },
        { labelKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.out.ready", label: "Ready to apply for occupation" },
      ],
      titleKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.title",
      titleDefault: "Close it out before the occupation certificate is applied for",
      whatKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.what",
      whatDefault:
        "Check the close-out register holds every regulated design, every declaration and every lodgement receipt, then have the registered building practitioner make the building compliance declaration that the work complies with the designs as declared.",
      whyKey: "cases.lodge_regulated_designs_under_the_design_and_building_practitioners_act.step.occupation.why",
      whyDefault:
        "The compliance declarations have to be in place before an application for an occupation certificate can be made, which means a single missing declaration holds up handover for a finished building. Every day of that is carrying cost on a project that has stopped earning.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
