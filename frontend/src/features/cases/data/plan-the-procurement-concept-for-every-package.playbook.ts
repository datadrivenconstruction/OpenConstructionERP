// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Plan the procurement concept for every package".
//
// Content strings are key plus inline English default and live only here.
// Every screen it walks lives inside one project, so the case declares
// requiresProject and the runner opens the project list when none is picked.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "plan-the-procurement-concept-for-every-package",
  order: 1684,
  category: "tendering",
  stage: "procure",
  companyTypes: ["developer-client", "project-manager", "cost-consultant"],
  roles: ["procurement-buyer", "project-manager", "contract-administrator"],
  requiresProject: true,
  icon: "PackageCheck",
  titleKey: "cases.plan_the_procurement_concept_for_every_package.title",
  titleDefault: "Plan the procurement concept for every package",
  descKey: "cases.plan_the_procurement_concept_for_every_package.desc",
  descDefault:
    "Plan the award route of each package, check thresholds, prequalify bidders, sound the market, let the award dates run back from the programme and get the concept approved.",
  longDescKey: "cases.plan_the_procurement_concept_for_every_package.longdesc",
  longDescDefault:
    "Before the first tender goes out, a client needs one plan for how every package will be bought: which procedure, whether a public threshold applies, which firms are on the short list, when each award must be made so the site is not held up. Procurement concept builds that plan from the delivery model's packages, writes confirmed award milestones into the schedule, and locks the concept once a second person approves it.",
  estMinutes: 15,
  steps: [
    {
      id: "start",
      icon: "Package",
      inputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.start.in.packages", label: "Package plan" },
      ],
      outputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.start.out.routes", label: "Award route per package" },
      ],
      titleKey: "cases.plan_the_procurement_concept_for_every_package.step.start.title",
      titleDefault: "Plan the award for each package",
      whatKey: "cases.plan_the_procurement_concept_for_every_package.step.start.what",
      whatDefault:
        "Press Start concept, then Plan award for each package: estimated value, threshold check, procedure and contract need. The packages come from the delivery model's package plan.",
      whyKey: "cases.plan_the_procurement_concept_for_every_package.step.start.why",
      whyDefault:
        "The procedure follows from the value and the client type. Getting it wrong is the easiest way to have a tender challenged.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept",
    },
    {
      id: "prequal",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.prequal.in.market", label: "Candidate firms" },
      ],
      outputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.prequal.out.shortlist", label: "Short list" },
      ],
      titleKey: "cases.plan_the_procurement_concept_for_every_package.step.prequal.title",
      titleDefault: "Prequalify the bidders",
      whatKey: "cases.plan_the_procurement_concept_for_every_package.step.prequal.what",
      whatDefault:
        "On the Prequalification tab, set up the profile, add candidates and their references, and check whether the short list is ready.",
      whyKey: "cases.plan_the_procurement_concept_for_every_package.step.prequal.why",
      whyDefault:
        "Inviting firms that cannot deliver wastes everyone's time. A documented short list also protects the choice if it is questioned.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept?tab=prequalification",
    },
    {
      id: "sounding",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.sounding.in.signals", label: "Market signals" },
      ],
      outputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.sounding.out.sounding", label: "Market sounding record" },
      ],
      titleKey: "cases.plan_the_procurement_concept_for_every_package.step.sounding.title",
      titleDefault: "Sound the market",
      whatKey: "cases.plan_the_procurement_concept_for_every_package.step.sounding.what",
      whatDefault:
        "On the Market sounding tab, record what firms say about capacity, price and lead times.",
      whyKey: "cases.plan_the_procurement_concept_for_every_package.step.sounding.why",
      whyDefault:
        "A busy market changes the right procedure and the right timing. Writing the signals down makes them part of the decision.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept?tab=market",
    },
    {
      id: "schedule",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.schedule.in.programme", label: "Project programme" },
      ],
      outputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.schedule.out.milestones", label: "Award milestones" },
      ],
      titleKey: "cases.plan_the_procurement_concept_for_every_package.step.schedule.title",
      titleDefault: "Set the award schedule",
      whatKey: "cases.plan_the_procurement_concept_for_every_package.step.schedule.what",
      whatDefault:
        "On the Award schedule tab, review the proposed dates that run back from the programme and confirm them. Confirmed milestones are written to the project schedule.",
      whyKey: "cases.plan_the_procurement_concept_for_every_package.step.schedule.why",
      whyDefault:
        "Each award date is set by when the work is needed on site, minus the time the procedure takes. Confirming them puts procurement on the critical path where it belongs.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept?tab=schedule",
    },
    {
      id: "record",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.record.in.routes", label: "Award route per package" },
      ],
      outputs: [
        { labelKey: "cases.plan_the_procurement_concept_for_every_package.step.record.out.concept", label: "Approved procurement concept" },
      ],
      titleKey: "cases.plan_the_procurement_concept_for_every_package.step.record.title",
      titleDefault: "Get the concept approved",
      whatKey: "cases.plan_the_procurement_concept_for_every_package.step.record.what",
      whatDefault:
        "On the Concept record tab, read what the rule check found and press Submit for the gate, the governance gate then approves it. On a project without gates a second person approves it here. Export the Concept record (PDF) and the Package list (XLSX).",
      whyKey: "cases.plan_the_procurement_concept_for_every_package.step.record.why",
      whyDefault:
        "Once approved the plan is locked and can only be reopened with a reason, which keeps the procurement strategy stable while the tenders run.",
      moduleLabel: "Procurement concept",
      moduleLabelKey: "procurement_concept.nav.title",
      to: "/projects/:projectId/procurement-concept?tab=record",
    },
  ],
};

export default playbook;
