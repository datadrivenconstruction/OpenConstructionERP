// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Assess an extension of time with programme impact".
//
// Log the delay event with its evidence, insert it into the programme to measure
// the impact on completion, set out the entitlement and submit the extension of
// time notice. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "assess-an-extension-of-time-with-programme-impact",
  order: 1024,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  icon: "CalendarClock",
  titleKey: "cases.assess_an_extension_of_time_with_programme_impact.title",
  titleDefault: "Assess an extension of time with programme impact",
  descKey: "cases.assess_an_extension_of_time_with_programme_impact.desc",
  descDefault:
    "Log the delay event with its evidence, insert it into the programme to measure the real impact on completion, set out the entitlement and submit the extension of time notice under the contract.",
  longDescKey: "cases.assess_an_extension_of_time_with_programme_impact.longdesc",
  longDescDefault:
    "An extension of time is about the completion date, not the money - that comes later as loss and expense. The claim stands or falls on the programme analysis: showing, with the baseline and the impacted programme side by side, that the excusable event actually pushed the finish out.",
  estMinutes: 12,
  steps: [
    {
      id: "event",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.in.delay", label: "Delay event" },
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.in.records", label: "Contemporaneous records" },
      ],
      outputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.out.evidence", label: "Evidence pack" },
      ],
      titleKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.title",
      titleDefault: "Log the delay event",
      whatKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.what",
      whatDefault:
        "Log the delay event with its cause and gather the contemporaneous records that prove it: the diary entries, the late instruction, the photos, the correspondence around the date it hit.",
      whyKey: "cases.assess_an_extension_of_time_with_programme_impact.step.event.why",
      whyDefault:
        "An extension of time claim lives or dies on contemporaneous evidence. Assembling it while the event is fresh is what turns a plausible story into a claim that gets awarded.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
    {
      id: "impact",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.in.baseline", label: "Baseline programme" },
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.in.event", label: "Delay event" },
      ],
      outputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.out.impacted", label: "Impacted programme" },
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.out.days", label: "Days of delay" },
      ],
      titleKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.title",
      titleDefault: "Measure the programme impact",
      whatKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.what",
      whatDefault:
        "Insert the delay into the programme and compare the impacted completion against the baseline, so the days claimed come from a network analysis rather than an assertion.",
      whyKey: "cases.assess_an_extension_of_time_with_programme_impact.step.impact.why",
      whyDefault:
        "Only a delay on the critical path moves the completion date. Showing the impact through the programme is what separates a genuine extension from a claim for a delay that had float to absorb it.",
      moduleLabel: "Advanced Schedule",
      moduleLabelKey: "nav.schedule_advanced",
      to: "/schedule-advanced",
    },
    {
      id: "entitlement",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.in.days", label: "Days of delay" },
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.in.contract", label: "Contract clauses" },
      ],
      outputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.out.claim", label: "Assessed entitlement" },
      ],
      titleKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.title",
      titleDefault: "Set out the entitlement",
      whatKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.what",
      whatDefault:
        "Test the delay against the contract: which cause is a relevant, excusable event, how the clauses treat it, and how many days you are entitled to claim.",
      whyKey: "cases.assess_an_extension_of_time_with_programme_impact.step.entitlement.why",
      whyDefault:
        "Impact is not the same as entitlement. Tying the days to the specific clause is what makes the claim contractual instead of a grievance, and what an assessor can actually award against.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "submit",
      icon: "Send",
      inputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.submit.in.claim", label: "Assessed entitlement" },
      ],
      outputs: [
        { labelKey: "cases.assess_an_extension_of_time_with_programme_impact.step.submit.out.notice", label: "Extension of time notice" },
      ],
      titleKey: "cases.assess_an_extension_of_time_with_programme_impact.step.submit.title",
      titleDefault: "Submit the notice",
      whatKey: "cases.assess_an_extension_of_time_with_programme_impact.step.submit.what",
      whatDefault:
        "Submit the extension of time notice and its particulars within the contractual time limit, with the impacted programme and the evidence attached.",
      whyKey: "cases.assess_an_extension_of_time_with_programme_impact.step.submit.why",
      whyDefault:
        "Many good claims are lost simply by being late. Submitting inside the notice period, complete and evidenced, is what keeps the entitlement alive and the completion date defensible.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
