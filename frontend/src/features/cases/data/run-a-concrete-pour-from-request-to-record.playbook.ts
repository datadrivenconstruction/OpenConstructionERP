// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a concrete pour from request to record".
//
// The pour card loop: raise the request, clear the pre-pour hold point, release
// and pour with the delivery tickets and cube samples, then record the test
// results and the as-built. Content strings key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-a-concrete-pour-from-request-to-record",
  order: 1019,
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  icon: "ClipboardCheck",
  titleKey: "cases.run_a_concrete_pour_from_request_to_record.title",
  titleDefault: "Run a concrete pour from request to record",
  descKey: "cases.run_a_concrete_pour_from_request_to_record.desc",
  descDefault:
    "Run the pour card loop end to end: raise the request, clear the pre-pour hold point, release and pour with the delivery tickets and cube samples, then record the test results and the as-built against the element.",
  longDescKey: "cases.run_a_concrete_pour_from_request_to_record.longdesc",
  longDescDefault:
    "Concrete is unforgiving: once it is in, a missed reinforcement bar or a wrong cover is buried for the life of the building. The pour card exists so nobody pours until the steel, the formwork and the paperwork are all checked and released together.",
  estMinutes: 11,
  steps: [
    {
      id: "request",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.in.element", label: "Element to pour" },
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.in.mix", label: "Specified mix" },
      ],
      outputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.out.card", label: "Pour request" },
      ],
      titleKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.title",
      titleDefault: "Raise the pour request",
      whatKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.what",
      whatDefault:
        "Raise the pour request with the element, the location, the specified mix and the volume, giving enough notice for the inspection and the concrete order to line up.",
      whyKey: "cases.run_a_concrete_pour_from_request_to_record.step.request.why",
      whyDefault:
        "A pour called at short notice is a pour that skips checks. Requesting it properly gives the inspection its window and the batching plant its lead time, so nothing is rushed on the day.",
      moduleLabel: "Forms",
      moduleLabelKey: "nav.forms",
      to: "/forms",
    },
    {
      id: "inspect",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.in.card", label: "Pour request" },
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.in.itp", label: "Inspection checklist" },
      ],
      outputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.out.cleared", label: "Hold point cleared" },
      ],
      titleKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.title",
      titleDefault: "Clear the pre-pour hold point",
      whatKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.what",
      whatDefault:
        "Inspect against the checklist before the pour: reinforcement size and spacing, cover, ties, formwork line and cleanliness, and any cast-in items in the right place.",
      whyKey: "cases.run_a_concrete_pour_from_request_to_record.step.inspect.why",
      whyDefault:
        "This is the last moment the steel and the formwork are visible. A hold point cleared here catches the error that would otherwise be entombed and only found when the cover meter comes out.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "release",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.in.cleared", label: "Cleared hold point" },
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.in.tickets", label: "Delivery tickets" },
      ],
      outputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.out.poured", label: "Pour completed" },
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.out.samples", label: "Cube samples taken" },
      ],
      titleKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.title",
      titleDefault: "Release and pour",
      whatKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.what",
      whatDefault:
        "Release the hold point and pour, logging each delivery ticket, the mix and slump on arrival, and taking the cube samples for testing as the concrete goes in.",
      whyKey: "cases.run_a_concrete_pour_from_request_to_record.step.release.why",
      whyDefault:
        "The tickets and samples captured during the pour are the proof the right concrete went in. Reconstructed afterwards they are worthless, so they have to be taken as it happens.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "nav.construction_control",
      to: "/projects/:projectId/construction-control",
    },
    {
      id: "record",
      icon: "FlaskConical",
      inputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.in.samples", label: "Cube samples" },
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.in.results", label: "Test results" },
      ],
      outputs: [
        { labelKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.out.asbuilt", label: "As-built pour record" },
      ],
      titleKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.title",
      titleDefault: "Record tests and as-built",
      whatKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.what",
      whatDefault:
        "Record the cube test results at seven and twenty-eight days against the pour, and close the as-built record for the element, so the concrete has a verified strength on file.",
      whyKey: "cases.run_a_concrete_pour_from_request_to_record.step.record.why",
      whyDefault:
        "A pour is not finished when the concrete sets, it is finished when it is proven to strength on record. That record is what the structural sign-off and the eventual handover depend on.",
      moduleLabel: "Construction Control",
      moduleLabelKey: "nav.construction_control",
      to: "/projects/:projectId/construction-control",
    },
  ],
};

export default playbook;
