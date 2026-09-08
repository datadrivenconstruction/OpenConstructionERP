// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Keep the golden thread on a higher-risk building" (GB).
//
// The Building Safety Act 2022 asks for building information that is
// accurate, current and findable, handed on at each gateway and again at
// occupation. The platform has no gateway form to fill in, so the case walks
// the discipline that produces the thread: stated requirements, a common data
// environment with states, a versioned register, a review cycle answered
// against pinned versions, and a handover. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "keep-the-golden-thread-on-a-higher-risk-building",
  order: 1166,
  region: "GB",
  category: "bim",
  companyTypes: ["developer-client", "bim-consultant", "general-contractor", "project-manager"],
  roles: ["document-controller", "bim-coordinator", "design-lead", "project-manager"],
  stage: "design",
  icon: "ShieldCheck",
  titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.title",
  titleDefault: "Keep the golden thread on a higher-risk building",
  descKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.desc",
  descDefault:
    "State what information the building safety regime will ask for, keep it in a common data environment with states and suitability codes rather than in folders, answer building control against pinned versions, and hand the thread on complete instead of closing it.",
  longDescKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.longdesc",
  longDescDefault:
    "The Building Safety Act 2022 put a higher-risk building through three gateways and made somebody accountable for the information about it, from design through to occupation. That information is the golden thread, and the regime asks for it to be accurate, current and available to the people who need it, rather than merely archived somewhere nobody can search. In practice that is an information management discipline and not a document dump: what is required is stated up front, drafts are kept apart from what has been shared and what has been published, and every review is answered against the version that was actually submitted. This case builds that discipline out of what the platform holds today. It does not fill in a gateway application; it produces the record a gateway application has to be made from.",
  estMinutes: 16,
  steps: [
    {
      id: "require",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.in.requirements", label: "Client information requirements" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.in.programme", label: "Delivery programme" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.out.matrix", label: "Requirements matrix" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.out.criteria", label: "Acceptance criteria agreed" },
      ],
      titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.title",
      titleDefault: "State what information is required before anybody produces it",
      whatKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.what",
      whatDefault:
        "Set the information requirements out as a matrix: what has to be delivered, by whom, at what point and to what standard, with the quality gates each set has to pass. Everything downstream is then measured against this rather than against habit.",
      whyKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.require.why",
      whyDefault:
        "The golden thread fails at the beginning far more often than at the end. Nobody hands over a building with no information; they hand over a great deal of information nobody asked for, in a form nobody can search, which under a regime that expects the accountable person to answer a question quickly is the same as having none.",
      moduleLabel: "EIR Matrix (ISO 19650)",
      moduleLabelKey: "nav.eir_matrix",
      to: "/requirements/matrix",
    },
    {
      id: "cde",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.in.containers", label: "Drawings and models" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.in.codes", label: "Agreed suitability codes" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.out.approved", label: "Information approved for construction" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.out.wip", label: "Work in progress kept separate" },
      ],
      titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.title",
      titleDefault: "Separate work in progress from what has been shared",
      whatKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.what",
      whatDefault:
        "Run the information through the common data environment states, from work in progress to shared, published and archived, with a suitability code on every container saying what it may be used for. Moving a container between states is a gate somebody passes, not a drag between folders.",
      whyKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.cde.why",
      whyDefault:
        "The difference between a drawing you may build from and a drawing somebody is still working on is the single most expensive distinction on a construction project, and a folder name cannot carry it. A suitability code travels with the container, so whoever opens it six months later knows what it was fit for without ringing the person who made it.",
      moduleLabel: "Common Data Environment",
      moduleLabelKey: "cde.title",
      to: "/projects/:projectId/cde",
    },
    {
      id: "register",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.in.docs", label: "Drawings, specifications and certificates" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.in.product", label: "Product data and test results" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.out.register", label: "Versioned document register" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.out.superseded", label: "Superseded revisions kept" },
      ],
      titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.title",
      titleDefault: "Keep the register the accountable person will read",
      whatKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.what",
      whatDefault:
        "Hold the drawings, specifications, calculations, product data and certificates as one register with versions, so the current revision is obvious and the superseded one is still there. Tag and file them the way the requirements matrix asked for, not the way each discipline would prefer.",
      whyKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.register.why",
      whyDefault:
        "The regime expects information to be current and findable, and those two fail together: a register where the latest revision is ambiguous is a register where somebody eventually builds from the wrong sheet. Keeping superseded versions rather than overwriting them also answers the question that comes up in every investigation, which is what was known at the time.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "review",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.in.pack", label: "Submission pack" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.in.comments", label: "Comments raised on review" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.out.responses", label: "Responses against pinned versions" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.out.decision", label: "Decision recorded" },
      ],
      titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.title",
      titleDefault: "Answer building control against the version you submitted",
      whatKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.what",
      whatDefault:
        "Run the review cycle with the Building Safety Regulator, which is the building control authority for a higher-risk building in England: record the submission with the document version pinned to it, log each remark, respond to it and close out the decision. When the live document moves on, a remark raised against the submitted version is flagged as stale rather than silently remapped onto the new one.",
      whyKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.review.why",
      whyDefault:
        "A remark answered against a drawing that has changed since submission is an answer to a question nobody asked. Pinning the version makes the exchange reconstructable, which is the whole ask of a gateway: show what you submitted, what you were told about it, and what you did in response.",
      moduleLabel: "Review Authority",
      moduleLabelKey: "review_authority.title",
      to: "/projects/:projectId/review-authority",
    },
    {
      id: "handover",
      icon: "PackageCheck",
      inputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.in.register", label: "Versioned document register" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.in.asbuilt", label: "As-built information" },
      ],
      outputs: [
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.out.package", label: "Handover package issued" },
        { labelKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.out.thread", label: "Accountable person has the thread" },
      ],
      titleKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.title",
      titleDefault: "Hand the thread on rather than closing it",
      whatKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.what",
      whatDefault:
        "Bind the information into the handover package: the as-built set, the operation and maintenance information, the test and commissioning certificates, the fire and structural information, and the manifest that says what is in there. Issue it to whoever becomes accountable for the building in occupation.",
      whyKey: "cases.keep_the_golden_thread_on_a_higher_risk_building.step.handover.why",
      whyDefault:
        "The golden thread does not stop at practical completion, it changes hands. A package that arrives as a folder tree with no manifest becomes an archive nobody opens within a month, and the next person who needs to know how the building was actually built starts again from whatever drawings are still on site.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
  ],
};

export default playbook;
