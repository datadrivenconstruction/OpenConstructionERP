// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Register warranties and guarantees at handover".
//
// Collect every product and workmanship warranty from the supply chain, register
// each against the asset it covers with its term and beneficiary, file the
// documents and hand the register to the operator. Content strings key plus default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "register-warranties-and-guarantees-at-handover",
  order: 1029,
  category: "handover",
  companyTypes: ["general-contractor", "owner-operator", "developer-client"],
  icon: "ShieldCheck",
  titleKey: "cases.register_warranties_and_guarantees_at_handover.title",
  titleDefault: "Register warranties and guarantees at handover",
  descKey: "cases.register_warranties_and_guarantees_at_handover.desc",
  descDefault:
    "Collect every product and workmanship warranty from the supply chain, register each against the asset it covers with its term and beneficiary, file the documents and hand the register to the operator.",
  longDescKey: "cases.register_warranties_and_guarantees_at_handover.longdesc",
  longDescDefault:
    "Warranties are worth real money only if someone can find them and knows when they expire. Scattered through email and box files they are useless the day a roof leaks. A warranty register turns a pile of certificates into a live asset the operator can actually claim against.",
  estMinutes: 10,
  steps: [
    {
      id: "collect",
      icon: "FolderOpen",
      inputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.in.supply", label: "Supply chain" },
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.in.certificates", label: "Warranty certificates" },
      ],
      outputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.out.collected", label: "Warranties collected" },
      ],
      titleKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.title",
      titleDefault: "Collect every warranty",
      whatKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.what",
      whatDefault:
        "Chase every product and workmanship warranty and guarantee out of the supply chain - roofing, cladding, plant, finishes - before the subcontractors demobilise and disappear.",
      whyKey: "cases.register_warranties_and_guarantees_at_handover.step.collect.why",
      whyDefault:
        "A warranty is far easier to extract while you still hold retention than a year after a subcontractor has left. Collecting them at handover is the moment of maximum leverage.",
      moduleLabel: "Handover",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "register",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.register.in.collected", label: "Collected warranties" },
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.register.in.assets", label: "Asset register" },
      ],
      outputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.register.out.register", label: "Warranty register" },
      ],
      titleKey: "cases.register_warranties_and_guarantees_at_handover.step.register.title",
      titleDefault: "Register each against its asset",
      whatKey: "cases.register_warranties_and_guarantees_at_handover.step.register.what",
      whatDefault:
        "Register each warranty against the asset it covers, with its start date, its term, the beneficiary and the conditions that keep it valid, so it is tied to the thing it protects.",
      whyKey: "cases.register_warranties_and_guarantees_at_handover.step.register.why",
      whyDefault:
        "A warranty linked to its asset surfaces the moment that asset fails. Recording the term and the maintenance conditions is also what stops a warranty being voided by a missed service.",
      moduleLabel: "Asset Register",
      moduleLabelKey: "assets.title",
      to: "/assets",
    },
    {
      id: "file",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.file.in.register", label: "Warranty register" },
      ],
      outputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.file.out.filed", label: "Documents filed" },
      ],
      titleKey: "cases.register_warranties_and_guarantees_at_handover.step.file.title",
      titleDefault: "File the documents",
      whatKey: "cases.register_warranties_and_guarantees_at_handover.step.file.what",
      whatDefault:
        "File the warranty documents in the handover file, linked from the register, so the certificate behind every entry is one click away when a claim needs to be made.",
      whyKey: "cases.register_warranties_and_guarantees_at_handover.step.file.why",
      whyDefault:
        "A register that points at missing documents is only half a register. Filing the certificates with it is what makes a claim a simple lookup instead of an archaeological dig.",
      moduleLabel: "Files",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "handover",
      icon: "KeyRound",
      inputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.handover.in.filed", label: "Complete register" },
      ],
      outputs: [
        { labelKey: "cases.register_warranties_and_guarantees_at_handover.step.handover.out.operator", label: "Handed to operator" },
      ],
      titleKey: "cases.register_warranties_and_guarantees_at_handover.step.handover.title",
      titleDefault: "Hand it to the operator",
      whatKey: "cases.register_warranties_and_guarantees_at_handover.step.handover.what",
      whatDefault:
        "Hand the warranty register to the operator or facilities team, with the expiry dates loaded so they are prompted before cover runs out and know exactly how to claim.",
      whyKey: "cases.register_warranties_and_guarantees_at_handover.step.handover.why",
      whyDefault:
        "A warranty the operator does not know about is money left unclaimed. Handing over a live register with its dates is what lets them make good on cover instead of paying for a repair twice.",
      moduleLabel: "Service",
      moduleLabelKey: "nav.service",
      to: "/projects/:projectId/service",
    },
  ],
};

export default playbook;
