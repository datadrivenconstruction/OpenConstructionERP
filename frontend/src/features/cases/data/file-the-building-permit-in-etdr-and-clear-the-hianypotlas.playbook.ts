// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "File the building permit in ETDR and clear the hianypotlas" (HU).
//
// The Hungarian permit route as the person assembling it runs it: decide first
// whether the work needs a permit, a notification or neither, test the design
// against the requirements that bind it, assemble the documentation the decree
// lists, submit through ETDR, answer the request to complete the file inside
// its deadline, and hand the permit to the site. The procedural code changed in
// 2024 and the requirements base changed in 2025, so the first two steps are
// the ones people get wrong out of habit. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "file-the-building-permit-in-etdr-and-clear-the-hianypotlas",
  order: 1246,
  region: "HU",
  category: "quality",
  companyTypes: ["designer", "developer-client", "project-manager", "general-contractor"],
  roles: ["design-lead", "document-controller", "project-manager", "contract-administrator"],
  stage: "define",
  icon: "Building2",
  titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.title",
  titleDefault: "File the building permit in ETDR and clear the hianypotlas",
  descKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.desc",
  descDefault:
    "Decide whether the work needs an engedely, a bejelentes or neither, test the design against the requirements that bind it, assemble the documentation the decree lists, file it through ETDR and answer the hianypotlas inside its deadline.",
  longDescKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.longdesc",
  longDescDefault:
    "Hungarian building authority procedures run electronically through ETDR, and the rules they run under were rewritten recently enough that experience is now a liability. Government Decree 281/2024 (IX. 30.) replaced the old procedural code from 1 October 2024 and folded the simple notification route for dwellings into itself, and Government Decree 280/2024 (IX. 30.), the TEKA, replaced the OTEK as the national settlement and building requirements base from 1 January 2025 with mandatory application from that July. So the two questions that decide the whole job, what route the work takes and what the design has to satisfy, both have new answers, and a permit application built on the old ones does not fail loudly. It comes back as a request to complete the file, weeks later, with a short deadline attached.",
  estMinutes: 12,
  steps: [
    {
      id: "route",
      icon: "Route",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.in.scope", label: "Scope of the works" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.in.site", label: "Site and its constraints" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.out.route", label: "Authority route decided" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.out.reason", label: "Reason recorded" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.title",
      titleDefault: "Decide the route before anything is drawn",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.what",
      whatDefault:
        "Classify the work against the current procedural decree: an epitesi engedely, an egyszeru bejelentes, or work that needs neither. Record the decision and what it rests on, including anything that overrides the general rule such as protected status, a heritage constraint or a site under a special regime.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.route.why",
      whyDefault:
        "Government Decree 281/2024 (IX. 30.) replaced the decree everybody in the industry learned this from, and it absorbed the separate notification route for dwellings. A firm applying the version it remembers is not making a small error: work built on the wrong route is unlawful construction, and the fix is retrospective and expensive. Recording the reason also means the next person does not re-decide it from memory.",
      moduleLabel: "Route Classifier",
      moduleLabelKey: "project_route.title",
      to: "/projects/:projectId/project-route",
    },
    {
      id: "requirements",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.in.design", label: "Design at permit stage" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.in.plan", label: "Local settlement plan" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.out.report", label: "Compliance report" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.out.issues", label: "Non-compliances to resolve" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.title",
      titleDefault: "Test the design against what actually binds it",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.what",
      whatDefault:
        "Check the design against the national requirements base and the local settlement plan on top of it: use, height, built ratio, setbacks, parking, green surface and whatever the local plan adds. Resolve the failures before submission rather than letting the authority find them.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.requirements.why",
      whyDefault:
        "The national base changed: Government Decree 280/2024 (IX. 30.), the TEKA, took over from the OTEK from 1 January 2025 and became mandatory that July. A parameter checked against the old base and a parameter checked against nothing look identical in a drawing, and both come back as findings. Doing it here costs a design iteration; doing it after submission costs the iteration plus the procedure.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "pack",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.in.drawings", label: "Permit drawings" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.in.statements", label: "Designer statements and studies" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.out.pack", label: "Complete documentation set" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.out.index", label: "Index against the decree list" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.title",
      titleDefault: "Assemble the documentation against the list",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.what",
      whatDefault:
        "Build the application set in one place with a version and an author on every document, and index it against the decree's own annex rather than against the last application your office made. Include the designer statements, the specialist studies and the consents the case needs.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.pack.why",
      whyDefault:
        "The annex to the procedural decree is a list, and an application is judged complete or incomplete against it mechanically. Indexing against the last successful application is how an office carries a missing document forward for a year: it worked before, so nobody looks, and the authority is the one who eventually notices.",
      moduleLabel: "Common Data Environment",
      moduleLabelKey: "cde.title",
      to: "/projects/:projectId/cde",
    },
    {
      id: "submit",
      icon: "Send",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.in.pack", label: "Complete documentation set" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.in.applicant", label: "Applicant details" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.out.case", label: "ETDR case opened" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.out.reference", label: "Case identifier on record" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.title",
      titleDefault: "Submit through ETDR and keep the identifier",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.what",
      whatDefault:
        "File the application electronically through ETDR and record the case identifier on the project, together with the date of submission and the documents that actually went in that version.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.submit.why",
      whyDefault:
        "Everything that follows is addressed by that identifier: the requests, the specialist authority opinions, the decision and any later modification. A project that only records that the application went in cannot answer which version of the drawings the permit was granted on, and that is the exact question a building supervision inspection asks on site.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "hianypotlas",
      icon: "MessageSquarePlus",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.in.request", label: "Request to complete the file" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.in.pack", label: "Submitted documentation" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.out.reply", label: "Answer filed on the case" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.out.thread", label: "Dated correspondence thread" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.title",
      titleDefault: "Answer the hianypotlas as one tracked item",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.what",
      whatDefault:
        "Log the request as correspondence with its deadline and an owner, answer each point separately so the authority can tick them off, and keep the revised documents versioned against the ones they replace.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.hianypotlas.why",
      whyDefault:
        "A request to complete the file arrives at the designer, who is usually on the next project by then, and the deadline runs whether or not anyone has read it. Half of the delay on Hungarian permits is not the authority being slow, it is a two-week gap between a request landing and somebody noticing it, and that gap is entirely inside the applicant's own office.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "decision",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.in.case", label: "Open ETDR case" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.in.answer", label: "Answer filed" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.out.permit", label: "Permit decision" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.out.validity", label: "Validity date tracked" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.title",
      titleDefault: "Track the decision and what it expires against",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.what",
      whatDefault:
        "When the decision comes, record it with the conditions attached to it and set a deadline on the date the permit stops being usable, so an approval that has been sitting in a drawer while funding was arranged does not quietly expire.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.decision.why",
      whyDefault:
        "A permit is not permanent, and the gap between getting one and starting on site is exactly where a development stalls for reasons that have nothing to do with the permit. The date is knowable on the day the decision arrives and unknowable to whoever finds the file two years later, so it is recorded once, here.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "handoff",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.in.permit", label: "Permit decision and conditions" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.in.drawings", label: "Permitted drawings" },
      ],
      outputs: [
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.out.filed", label: "Permit set filed on the project" },
        { labelKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.out.conditions", label: "Conditions passed to the site" },
      ],
      titleKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.title",
      titleDefault: "Hand the permit and its conditions to the site",
      whatKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.what",
      whatDefault:
        "File the decision, the conditions and the permitted drawings on the project as one set, and pass the conditions to whoever will run the site as items with owners rather than as a PDF attached to an email.",
      whyKey: "cases.file_the_building_permit_in_etdr_and_clear_the_hianypotlas.step.handoff.why",
      whyDefault:
        "The permit is what the naplo is opened against and what the work is checked against, so the site needs it as a live document rather than as an archive. A condition that never reached the foreman is the most ordinary way a permitted building ends up not matching its permit, and it is discovered at the occupancy stage, which is the worst possible moment.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
