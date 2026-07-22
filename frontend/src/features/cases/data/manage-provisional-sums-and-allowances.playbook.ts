// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Manage provisional sums and allowances".
//
// Handle the parts of a bill the design cannot yet fix: provisional sums, prime
// cost sums and allowances. Keep them separate from measured work so they can be
// tracked and drawn down. Content strings are key plus inline English default.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "manage-provisional-sums-and-allowances",
  order: 1002,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  icon: "Coins",
  titleKey: "cases.manage_provisional_sums_and_allowances.title",
  titleDefault: "Manage provisional sums and allowances",
  descKey: "cases.manage_provisional_sums_and_allowances.desc",
  descDefault:
    "Handle the parts of a bill the design cannot yet fix - provisional sums, prime cost sums and allowances - kept separate from measured work so each one has an owner and can be drawn down cleanly.",
  longDescKey: "cases.manage_provisional_sums_and_allowances.longdesc",
  longDescDefault:
    "Every estimate carries work that is real but not yet designed. Dropping a round number into a rate hides it; carrying it as a named provisional sum keeps it honest, lets the client see the risk they are holding and gives you something clean to expend against later.",
  estMinutes: 10,
  steps: [
    {
      id: "identify",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.identify.in.design", label: "Incomplete design" },
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.identify.in.scope", label: "Scope gaps" },
      ],
      outputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.identify.out.list", label: "List of sums" },
      ],
      titleKey: "cases.manage_provisional_sums_and_allowances.step.identify.title",
      titleDefault: "Find what cannot be fixed yet",
      whatKey: "cases.manage_provisional_sums_and_allowances.step.identify.what",
      whatDefault:
        "Go through the scope and list every element the design cannot yet price firmly: undesigned finishes, a specialist package still out to market, statutory connections, a prime cost item.",
      whyKey: "cases.manage_provisional_sums_and_allowances.step.identify.why",
      whyDefault:
        "Naming the soft spots up front is what stops them being priced twice or missed entirely. It also tells the client exactly which parts of the number are still to be firmed up.",
      moduleLabel: "Allowances",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "classify",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.classify.in.list", label: "List of sums" },
      ],
      outputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.classify.out.basis", label: "Basis and owner set" },
      ],
      titleKey: "cases.manage_provisional_sums_and_allowances.step.classify.title",
      titleDefault: "Set the type and the basis",
      whatKey: "cases.manage_provisional_sums_and_allowances.step.classify.what",
      whatDefault:
        "Mark each one as a defined or undefined provisional sum, a prime cost sum or an allowance, then record the basis behind the figure and who owns firming it up.",
      whyKey: "cases.manage_provisional_sums_and_allowances.step.classify.why",
      whyDefault:
        "A defined sum carries programme and preliminaries; an undefined one does not. Getting the type right now decides whether you can claim time and cost when it is finally instructed.",
      moduleLabel: "Allowances",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "carry",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.carry.in.basis", label: "Classified sums" },
      ],
      outputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.carry.out.section", label: "Separate bill section" },
      ],
      titleKey: "cases.manage_provisional_sums_and_allowances.step.carry.title",
      titleDefault: "Carry them into the bill",
      whatKey: "cases.manage_provisional_sums_and_allowances.step.carry.what",
      whatDefault:
        "Bring the sums into the bill in their own section, clearly separate from measured work, so the tender total shows firm price and provisional money apart.",
      whyKey: "cases.manage_provisional_sums_and_allowances.step.carry.why",
      whyDefault:
        "Kept separate, the sums can be expended and adjusted through the job without disturbing the measured rates. Buried in the rates they become impossible to track or hand back.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.validate.in.section", label: "Bill with sums" },
      ],
      outputs: [
        { labelKey: "cases.manage_provisional_sums_and_allowances.step.validate.out.clean", label: "No double counts" },
      ],
      titleKey: "cases.manage_provisional_sums_and_allowances.step.validate.title",
      titleDefault: "Check for double counting",
      whatKey: "cases.manage_provisional_sums_and_allowances.step.validate.what",
      whatDefault:
        "Validate that nothing sits in both a rate and a provisional sum, that every sum has an owner, and that the totals reconcile before the bill goes out.",
      whyKey: "cases.manage_provisional_sums_and_allowances.step.validate.why",
      whyDefault:
        "Double counting a package is an easy way to price yourself out of a job; missing it is an easy way to lose money. A quick validation pass closes both traps at once.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
  ],
};

export default playbook;
