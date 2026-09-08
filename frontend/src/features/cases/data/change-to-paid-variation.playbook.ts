// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Turn a change into a paid variation".
//
// The commercial loop for scope change: raise the change, price it as a
// contract variation and bill it in a progress claim so the extra work is
// recovered. Content strings are key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "change-to-paid-variation",
  order: 60,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["quantity-surveyor", "commercial-manager", "contract-administrator"],
  icon: "FileSignature",
  titleKey: "cases.change_to_paid_variation.title",
  titleDefault: "Turn a change into a paid variation",
  descKey: "cases.change_to_paid_variation.desc",
  descDefault:
    "Capture a scope change while it is fresh, price it as a contract variation on your agreed rates and bill it in the next progress claim, so the extra work is recovered rather than quietly absorbed.",
  estMinutes: 11,
  steps: [
    {
      id: "change",
      icon: "GitCompareArrows",
      inputs: [
        {
          labelKey: "cases.change_to_paid_variation.step.change.in.instruction",
          label: "Site instruction",
        },
        {
          labelKey: "cases.change_to_paid_variation.step.change.in.revision",
          label: "Drawing revision",
        },
      ],
      outputs: [
        {
          labelKey: "cases.change_to_paid_variation.step.change.out.record",
          label: "Change record",
        },
        {
          labelKey: "cases.change_to_paid_variation.step.change.out.impact",
          label: "Time & cost impact",
        },
      ],
      titleKey: "cases.change_to_paid_variation.step.change.title",
      titleDefault: "Raise the change",
      whatKey: "cases.change_to_paid_variation.step.change.what",
      whatDefault:
        "Write down exactly what changed, who instructed it and the drawing revision or site instruction that drove it. Note the likely time and cost impact now, while the crew and the facts are still in front of you.",
      whyKey: "cases.change_to_paid_variation.step.change.why",
      whyDefault:
        "A change recorded the day it happens is a change you can substantiate and get paid for. The ones the team just gets on with, without a note, are the ones that eat the margin with nothing to show for it.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "variation",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.change_to_paid_variation.step.variation.in.change",
          label: "Change record",
        },
        {
          labelKey: "cases.change_to_paid_variation.step.variation.in.rates",
          label: "Agreed contract rates",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.change_to_paid_variation.step.variation.out.variation",
          label: "Priced variation",
        },
        {
          labelKey:
            "cases.change_to_paid_variation.step.variation.out.instruction",
          label: "Client instruction",
        },
      ],
      titleKey: "cases.change_to_paid_variation.step.variation.title",
      titleDefault: "Price it as a variation",
      whatKey: "cases.change_to_paid_variation.step.variation.what",
      whatDefault:
        "Promote the change into a formal contract variation, price the added and omitted work line by line against your agreed or star rates, then send it out for the client instruction that authorises it.",
      whyKey: "cases.change_to_paid_variation.step.variation.why",
      whyDefault:
        "The variation is where a change becomes a contractual entitlement rather than a favour. Building the price from agreed rates is what lets it stand up when the quantity surveyor questions it.",
      moduleLabel: "Contracts",
      moduleLabelKey: "onboarding.mod_contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "claim",
      icon: "ReceiptText",
      inputs: [
        {
          labelKey: "cases.change_to_paid_variation.step.claim.in.variation",
          label: "Instructed variation",
        },
        {
          labelKey: "cases.change_to_paid_variation.step.claim.in.measured",
          label: "Measured work done",
        },
      ],
      outputs: [
        {
          labelKey: "cases.change_to_paid_variation.step.claim.out.claim",
          label: "Progress claim",
        },
        {
          labelKey: "cases.change_to_paid_variation.step.claim.out.certified",
          label: "Certified payment",
        },
      ],
      titleKey: "cases.change_to_paid_variation.step.claim.title",
      titleDefault: "Bill it in a progress claim",
      whatKey: "cases.change_to_paid_variation.step.claim.what",
      whatDefault:
        "Roll the instructed variation into the next progress claim on the contract so it is certified and invoiced next to the measured work, not left sitting on a list of things owed.",
      whyKey: "cases.change_to_paid_variation.step.claim.why",
      whyDefault:
        "Priced and instructed still earns you nothing until it is claimed and certified. Folding the variation into the claim is the step that finally turns agreed extra work into cash in the bank.",
      moduleLabel: "Contracts",
      moduleLabelKey: "onboarding.mod_contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
