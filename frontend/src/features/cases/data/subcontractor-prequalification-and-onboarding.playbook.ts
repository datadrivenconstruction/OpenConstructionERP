// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Get prequalified and onboarded as a subcontractor".
//
// A subcontractor case: put your insurance, qualifications and safety record
// in front of a contractor once, get approved, and stay on the list they
// invite for future packages. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "subcontractor-prequalification-and-onboarding",
  order: 245,
  category: "quality",
  companyTypes: ["subcontractor", "general-contractor", "project-manager"],
  roles: ["procurement-buyer", "hse-officer", "contract-administrator"],
  icon: "BadgeCheck",
  titleKey: "cases.subcontractor_prequalification_and_onboarding.title",
  titleDefault: "Get prequalified and onboarded as a subcontractor",
  descKey: "cases.subcontractor_prequalification_and_onboarding.desc",
  descDefault:
    "Put your insurance, qualifications and safety record in front of a contractor once, get approved, and stay on the list they invite for future packages.",
  estMinutes: 8,
  steps: [
    {
      id: "submit",
      icon: "FileCheck",
      inputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.submit.in.insurance",
          label: "Insurance certificates",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.submit.in.quals",
          label: "Trade qualifications",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.submit.in.package",
          label: "Target package",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.submit.out.pack",
          label: "Submitted qualification pack",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.submit.out.record",
          label: "Prequalification record",
        },
      ],
      titleKey:
        "cases.subcontractor_prequalification_and_onboarding.step.submit.title",
      titleDefault: "Submit your qualification documents",
      whatKey:
        "cases.subcontractor_prequalification_and_onboarding.step.submit.what",
      whatDefault:
        "Upload your current insurance certificates, trade qualifications and method statements against the package you are being considered for.",
      whyKey:
        "cases.subcontractor_prequalification_and_onboarding.step.submit.why",
      whyDefault:
        "A contractor cannot place a package with a firm whose paperwork they cannot check, and a complete set submitted up front is what gets a decision made quickly.",
      moduleLabel: "Subcontractors",
      moduleLabelKey: "onboarding.mod_subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "safety",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.safety.in.record",
          label: "Prequalification record",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.safety.in.history",
          label: "Safety history",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.safety.in.methods",
          label: "Method statements",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.safety.out.safety",
          label: "Attached safety record",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.safety.out.profile",
          label: "Complete prequal profile",
        },
      ],
      titleKey:
        "cases.subcontractor_prequalification_and_onboarding.step.safety.title",
      titleDefault: "Attach your safety record",
      whatKey:
        "cases.subcontractor_prequalification_and_onboarding.step.safety.what",
      whatDefault:
        "Add your safety history and any relevant method statements to the record so the contractor can weigh your prequalification against your actual site performance.",
      whyKey:
        "cases.subcontractor_prequalification_and_onboarding.step.safety.why",
      whyDefault:
        "Price and qualifications only tell half the story. A clean safety record is often what tips a close prequalification decision in your favour.",
      moduleLabel: "Safety",
      moduleLabelKey: "nav.safety",
      to: "/projects/:projectId/safety",
    },
    {
      id: "approved",
      icon: "PackageCheck",
      inputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.approved.in.profile",
          label: "Complete prequal profile",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.approved.in.decision",
          label: "Approval decision",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.approved.out.approved",
          label: "Approved supplier status",
        },
        {
          labelKey:
            "cases.subcontractor_prequalification_and_onboarding.step.approved.out.list",
          label: "Place on invite list",
        },
      ],
      titleKey:
        "cases.subcontractor_prequalification_and_onboarding.step.approved.title",
      titleDefault: "Get approved and stay on the list",
      whatKey:
        "cases.subcontractor_prequalification_and_onboarding.step.approved.what",
      whatDefault:
        "Once approved, confirm you are on the invitation list so future packages come to you automatically instead of you having to ask each time.",
      whyKey:
        "cases.subcontractor_prequalification_and_onboarding.step.approved.why",
      whyDefault:
        "Prequalifying once and staying visible on the list is what turns a one-off approval into a standing pipeline of invitations.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
  ],
};

export default playbook;
