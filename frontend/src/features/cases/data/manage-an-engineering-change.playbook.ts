// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage an engineering change".
//
// Run a design or engineering change through control: raise it with its reason
// and risk, clear the technical questions by RFI, then carry any cost or time
// impact into a change order.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-an-engineering-change",
  order: 338,
  category: "quality",
  companyTypes: ["general-contractor", "designer", "owner-operator"],
  roles: ["design-lead", "project-manager", "contract-administrator"],
  icon: "GitCompareArrows",
  titleKey: "cases.manage_an_engineering_change.title",
  titleDefault: "Manage an engineering change",
  descKey: "cases.manage_an_engineering_change.desc",
  descDefault:
    "Run a design or engineering change through proper control: raise it with its reason and risk, clear the technical questions it opens by RFI, and carry any cost or time impact into a change order.",
  estMinutes: 9,
  steps: [
    {
      id: "raise",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey: "cases.manage_an_engineering_change.step.raise.in.proposal",
          label: "Proposed change",
        },
        {
          labelKey: "cases.manage_an_engineering_change.step.raise.in.risk",
          label: "Safety & design risk",
        },
      ],
      outputs: [
        {
          labelKey: "cases.manage_an_engineering_change.step.raise.out.record",
          label: "Change-control record",
        },
        {
          labelKey: "cases.manage_an_engineering_change.step.raise.out.review",
          label: "Routed for review",
        },
      ],
      titleKey: "cases.manage_an_engineering_change.step.raise.title",
      titleDefault: "Raise the change under control",
      whatKey: "cases.manage_an_engineering_change.step.raise.what",
      whatDefault:
        "Open a management-of-change record for the proposed change and state plainly what is changing, why, and the safety, operational and design risk it carries. Route it for review before anyone touches the work.",
      whyKey: "cases.manage_an_engineering_change.step.raise.why",
      whyDefault:
        "Engineering changes that skip a control step are how a well-meant fix ends up unsafe or non-compliant. The record is the proof the risk was looked at and the change was authorised, not just done.",
      moduleLabel: "Management of Change",
      moduleLabelKey: "moc.title",
      to: "/projects/:projectId/moc",
    },
    {
      id: "questions",
      icon: "HelpCircle",
      inputs: [
        {
          labelKey:
            "cases.manage_an_engineering_change.step.questions.in.record",
          label: "Change-control record",
        },
        {
          labelKey:
            "cases.manage_an_engineering_change.step.questions.in.questions",
          label: "Open technical questions",
        },
      ],
      outputs: [
        {
          labelKey: "cases.manage_an_engineering_change.step.questions.out.rfi",
          label: "Raised RFIs",
        },
        {
          labelKey:
            "cases.manage_an_engineering_change.step.questions.out.answers",
          label: "Designer's answers",
        },
      ],
      titleKey: "cases.manage_an_engineering_change.step.questions.title",
      titleDefault: "Clear the technical questions",
      whatKey: "cases.manage_an_engineering_change.step.questions.what",
      whatDefault:
        "Raise an RFI for each open technical question the change throws up, dimensions, interfaces, specification, and get the designer to answer in writing before the detail is fixed. Keep every RFI tied back to the change.",
      whyKey: "cases.manage_an_engineering_change.step.questions.why",
      whyDefault:
        "A change built on an assumption is rework waiting to happen. Getting the answer on the record, from the person responsible for the design, is what stops the same question being argued again on site.",
      moduleLabel: "RFIs",
      moduleLabelKey: "rfi.title",
      to: "/projects/:projectId/rfi",
    },
    {
      id: "impact",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.manage_an_engineering_change.step.impact.in.detail",
          label: "Confirmed change detail",
        },
        {
          labelKey: "cases.manage_an_engineering_change.step.impact.in.pricing",
          label: "Cost & time impact",
        },
      ],
      outputs: [
        {
          labelKey: "cases.manage_an_engineering_change.step.impact.out.order",
          label: "Change order",
        },
        {
          labelKey: "cases.manage_an_engineering_change.step.impact.out.agreed",
          label: "Agreed cost & date",
        },
      ],
      titleKey: "cases.manage_an_engineering_change.step.impact.title",
      titleDefault: "Carry the impact into a change order",
      whatKey: "cases.manage_an_engineering_change.step.impact.what",
      whatDefault:
        "If the change moves cost or time, raise a change order that captures the priced impact and the programme effect, linked back to the change record. If the impact is genuinely nil, record that too.",
      whyKey: "cases.manage_an_engineering_change.step.impact.why",
      whyDefault:
        "The engineering side can be closed and still leave the money open. A change order is what turns an authorised change into an agreed cost and a moved date, before it quietly becomes your problem.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
  ],
};

export default playbook;
