// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Assemble the svodnyy smetnyy raschet for state expertise" (RU).
//
// Roll the local estimates into object estimates and into the twelve chapters of
// the summary calculation, add the temporary works and winter allowances and the
// contingency reserve, then submit the package and work the remarks until the
// conclusion is positive. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "assemble-the-svodnyy-smetnyy-raschet-for-state-expertise",
  order: 1303,
  category: "estimating",
  companyTypes: ["developer-client", "cost-consultant", "designer", "general-contractor"],
  roles: ["estimator", "quantity-surveyor", "document-controller"],
  region: "RU",
  icon: "Landmark",
  titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.title",
  titleDefault: "Assemble the svodnyy smetnyy raschet for state expertise",
  descKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.desc",
  descDefault:
    "Gather the local estimates into object estimates and into the chapters of the summary calculation, add the temporary works and winter allowances and the contingency reserve, submit the package and answer the remarks until the conclusion is positive.",
  longDescKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.longdesc",
  longDescDefault:
    "Smetnaya dokumentatsiya is not one large smeta, it is a hierarchy. Local estimates cover sections of work, object estimates gather them per building or structure, and one summary calculation places the objects into twelve chapters running from site preparation through external utilities and temporary buildings to design and survey work. Budget-funded construction cannot begin without a positive conclusion from state expertise, and the reviewer reads down that structure rather than across the prices. Most remarks are not about what a position costs at all, they are about something missing from a chapter, or sitting in two chapters at once.",
  estMinutes: 18,
  steps: [
    {
      id: "locals",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.in.design", label: "Design documentation" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.in.norms", label: "Norm base and price level" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.out.locals", label: "Lokalnye smety" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.out.boundaries", label: "Section boundaries agreed" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.title",
      titleDefault: "Finish the lokalnye smety section by section",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.what",
      whatDefault:
        "Complete a local estimate for each section of works and each engineering system, with the norm base and the price level stated on every one of them, and check that the section boundaries follow the way the design documentation is divided.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.locals.why",
      whyDefault:
        "Everything above this is a sum of these. If two locals cover the same work, or a system falls between them, the error is repeated in the object estimate and again in the summary, and the reviewer returns the whole package rather than the one sheet that caused it.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "cascade",
      icon: "Workflow",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.in.type", label: "Type of construction" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.in.funding", label: "Source of funding" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.out.stack", label: "Cost cascade in order" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.out.bases", label: "Base declared per layer" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.title",
      titleDefault: "Set the cost cascade the summary runs on",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.what",
      whatDefault:
        "Set the stack the summary is built from and the order it applies in: overheads and estimated profit inside the works, then temporary buildings and structures, then the winter allowance, then the other costs, then the contingency reserve, then NDS on the result. State for each layer what it is calculated on.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.cascade.why",
      whyDefault:
        "The order matters as much as the rates, because every layer is calculated on the one beneath it. A winter allowance applied after the contingency reserve, or NDS applied before it, produces a different total from identical inputs, and that is a difference a reviewer reproduces in a minute.",
      moduleLabel: "Methodologies",
      moduleLabelKey: "nav.methodologies",
      to: "/methodologies",
    },
    {
      id: "winter",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.in.zone", label: "Temperature zone of the site" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.in.type", label: "Type of construction" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.out.winter", label: "Winter allowance" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.out.vzis", label: "Temporary works allowance" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.title",
      titleDefault: "Add the winter allowance for the zone you build in",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.what",
      whatDefault:
        "In the bill's Markups & Overheads panel, add the winter cost allowance (zimnee udorozhanie) for the temperature zone the site sits in and for this type of construction, and add the allowance for temporary buildings and structures (VZiS) alongside it. Add each as a line of its own so the summary can show it separately, keep the zone and the type recorded next to each rate, and note that the summary carries them in different chapters: temporary buildings in chapter 8, winter costs among the other works and costs in chapter 9.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.winter.why",
      whyDefault:
        "Winter working is a normed cost rather than a contingency: heating and thermal protection, lower output in frost, snow clearance and the extra handling that comes with all of it. The rate is set by temperature zone, so the same building carries a different allowance in different parts of the country, and an estimator who reuses the rate from a job in another region produces a figure the reviewer will not accept.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "chapters",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.in.locals", label: "Completed locals" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.in.structure", label: "Objects and structures" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.out.objects", label: "Object estimates" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.out.summary", label: "Summary by chapter" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.title",
      titleDefault: "Roll the locals into objects and into the chapters",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.what",
      whatDefault:
        "Gather the local estimates into an object estimate for each building or structure and place the objects into the twelve chapters of the summary calculation, from site preparation and the main objects through the external utilities and site improvement to the chapters for the client's own service, construction control and design and survey work. Carry that hierarchy as the nested section structure of the estimate, so a chapter total is read off the structure rather than added up by hand.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.chapters.why",
      whyDefault:
        "The chapter structure is what the customer's funding is built against and what the reviewer navigates by. A cost sitting in the wrong chapter is not a filing mistake, because chapters are financed and controlled separately, and moving a figure between them after approval means going back through expertise to do it.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "reserve",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.in.total", label: "Total by chapter" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.in.class", label: "Class of the object" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.out.reserve", label: "Contingency reserve" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.out.rationale", label: "Rationale on record" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.title",
      titleDefault: "Set the reserve for unforeseen works and costs",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.what",
      whatDefault:
        "Set the reserve line at the rate the class of object and the source of funding allow: the Russian template carries it after overheads and estimated profit on the total of the chapters, which is where the summary takes it. Hold the same sum as a contingency allowance with a note of what it covers, work the design genuinely cannot foresee and not a cushion for estimating left unfinished, so every drawdown against it is recorded.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.reserve.why",
      whyDefault:
        "The reserve is capped, and the cap is not the same for an ordinary object and for a technically complex or unique one. It also behaves differently once the job runs: on a state contract the customer controls its release, so a contractor who quietly plans to live off it is planning on money that is not his to spend.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.in.package", label: "Assembled package" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.in.rules", label: "Validation rule set" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.out.findings", label: "Findings to clear" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.out.ready", label: "Package cleared for submission" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.title",
      titleDefault: "Run the package through validation before it leaves",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.what",
      whatDefault:
        "Run validation on the assembled package and read what the rules report: a bill with no price level declared, a line without a norm code or with one that is not in the base, a markup line without a settled base or two lines claiming the same place in the order, and the flag on a reserve computed after profit, which the rule raises by name and which is the expected reading of a Russian summary. Then read the section tree for what no rule can see: every local referenced by an object, every object placed in a chapter, nothing counted twice.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.check.why",
      whyDefault:
        "Expertise counts working days from the moment the package is accepted, and an incomplete package is returned without being read at all. The rules catch what is checkable from the document alone, and the reviewer checks exactly that first; the cheapest remark is the one you find here, because it costs an hour rather than a review cycle.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "submit",
      icon: "Send",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.in.cleared", label: "Cleared package" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.in.note", label: "Explanatory note" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.out.pinned", label: "Submission kept as sent" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.out.clock", label: "Review clock started" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.title",
      titleDefault: "Submit the package and keep the version that went",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.what",
      whatDefault:
        "Put the submission together on the profile for the expertise body, defining the profile once if none is built in: the summary calculation, the object and local estimates, the calculations behind the other costs, the price justification for anything quoted from the market and the explanatory note. Generate it, read the validation report on its fields, and submit; the record keeps the payload and the generated file as they went, with the date.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.submit.why",
      whyDefault:
        "The package is judged as one cross-referenced document set, and it keeps being edited while the review runs. A submission kept as it was sent is what lets you answer a remark six weeks later about a sheet that has changed three times since it went out.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "remarks",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.in.remarks", label: "Remarks from the reviewer" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.in.pinned", label: "Pinned submission" },
      ],
      outputs: [
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.out.answers", label: "Answer per remark" },
        { labelKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.out.conclusion", label: "Conclusion of the expertise" },
      ],
      titleKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.title",
      titleDefault: "Answer the remarks and watch what comes back twice",
      whatKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.what",
      whatDefault:
        "Open a review cycle for the expertise and log each remark as it arrives, classified as one that cites a norm, one without a norm reference that you are entitled to contest, a clarification, or a defect. Answer the first kind with a correction to the sheet, contest the second with a reasoned reply, resubmit, and then look at which remarks came back a second time.",
      whyKey: "cases.assemble_the_svodnyy_smetnyy_raschet_for_state_expertise.step.remarks.why",
      whyDefault:
        "A remark citing a clause is a correction to make, a remark without one is a position you are entitled to argue, and treating both the same way either gives away money or burns the review clock. A remark that repeats after resubmission is the expensive one, because it usually means the answer addressed the wording rather than the finding underneath it.",
      moduleLabel: "Review Authority",
      moduleLabelKey: "review_authority.title",
      to: "/projects/:projectId/review-authority",
    },
  ],
};

export default playbook;
