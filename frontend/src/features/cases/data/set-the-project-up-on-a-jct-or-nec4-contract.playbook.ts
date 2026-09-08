// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Set the project up on a JCT or NEC4 contract" (GB).
//
// The two British contract families behave differently enough that a team
// running one on the other's habits loses money quietly. This case records
// which form the job is actually under, what releases the retention, which
// statutory payment regime sits behind it, and which dates carry a
// consequence. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "set-the-project-up-on-a-jct-or-nec4-contract",
  order: 1162,
  region: "GB",
  category: "commercial",
  companyTypes: ["general-contractor", "developer-client", "project-manager", "cost-consultant"],
  roles: ["contract-administrator", "commercial-manager", "quantity-surveyor"],
  stage: "procure",
  icon: "FileSignature",
  titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.title",
  titleDefault: "Set the project up on a JCT or NEC4 contract",
  descKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.desc",
  descDefault:
    "Draw the contract from the standard form the job is really being run under, say what the retention is and what releases it, execute it, put the statutory payment regime behind it and get the dates that carry a consequence onto a clock somebody watches.",
  longDescKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.longdesc",
  longDescDefault:
    "Two contract families cover most British construction and they are not interchangeable. JCT is instruction and certificate led: the contract administrator issues an instruction, the work is valued under the valuation rules, delay runs through relevant events and an extension of time, and it ends on a final certificate. NEC4 is process led: early warnings, compensation events notified inside a time bar, quotations, and assessment against an accepted programme on a clock both parties are held to. What they share is the Construction Act sitting underneath both of them. This case records which form is in play so that everything downstream, valuations, variations, notices and the final account, is measured against the right paper rather than against the habits of the last job.",
  estMinutes: 16,
  steps: [
    {
      id: "form",
      icon: "BookOpen",
      inputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.in.award", label: "Award recommendation" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.in.scope", label: "Scope and contract sum" },
      ],
      outputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.out.contract", label: "Contract on the named form" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.out.clauses", label: "Clause set on record" },
      ],
      titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.title",
      titleDefault: "Draw the contract from the form you are actually using",
      whatKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.what",
      whatDefault:
        "Create the contract and pick the clause template it is drawn from: a JCT standard building contract, design and build or minor works in the 2024 or the 2016 edition, or an NEC4 engineering and construction contract under the main option A to F you are working to. The contract records the template and its version, so it keeps naming the right paper after a later version is published.",
      whyKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.form.why",
      whyDefault:
        "Half the arguments on a job start with two people applying different contracts to the same fact. Naming the form on the record means the clause somebody cites can be looked up rather than remembered, and a quantity surveyor who joined in month nine can see what the job is working to without ringing round.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "retention",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.in.contract", label: "Contract on the named form" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.in.pct", label: "Retention percentage agreed" },
      ],
      outputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.out.terms", label: "Retention terms recorded" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.out.event", label: "Release tied to practical completion" },
      ],
      titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.title",
      titleDefault: "Say what retention is and what releases it",
      whatKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.what",
      whatDefault:
        "Set the retention percentage on the contract and choose the event that releases it, whether that is practical completion, the final account or handover. Add the contract lines so the sum is built out of something rather than typed in as one total.",
      whyKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.retention.why",
      whyDefault:
        "Retention is the money most often lost by the party that earned it, and it goes missing because nobody ever wrote down when it became payable. A release event on the contract turns it into something the platform can chase; a percentage with no release event is just a deduction with no end date.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "sign",
      icon: "Signature",
      inputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.in.contract", label: "Contract on the named form" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.in.parties", label: "Client and contractor contacts" },
      ],
      outputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.out.executed", label: "Executed contract" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.out.record", label: "Signature record on file" },
      ],
      titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.title",
      titleDefault: "Execute it and keep the executed copy",
      whatKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.what",
      whatDefault:
        "Send the contract out for signature, collect it back from both parties and keep the executed version as the one on file. Every valuation, variation and final account after this point hangs off this document.",
      whyKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.sign.why",
      whyDefault:
        "An unexecuted contract that everybody is nevertheless working to is the normal state of a British project for its first few months, and it is exactly where the terms drift. Getting it signed and filed is what makes the retention percentage and the payment terms enforceable rather than assumed.",
      moduleLabel: "E-Signatures",
      moduleLabelKey: "signing.title",
      to: "/signing",
    },
    {
      id: "regime",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.in.executed", label: "Executed contract" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.in.terms", label: "Payment terms in the contract" },
      ],
      outputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.out.regime", label: "Payment regime selected" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.out.dates", label: "Statutory deadlines computed" },
      ],
      titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.title",
      titleDefault: "Put the statutory payment regime behind it",
      whatKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.what",
      whatDefault:
        "Open the payment clock for the project and select the United Kingdom regime. It carries the Housing Grants, Construction and Regeneration Act 1996 as amended, with the default periods from the Scheme for Construction Contracts, so the due date, the payment notice deadline, the pay less deadline and the final date for payment are computed rather than remembered.",
      whyKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.regime.why",
      whyDefault:
        "The Act applies to a construction contract whether or not the parties thought about it, and a contract that provides no compliant payment mechanism gets the Scheme's one instead. Setting the regime once means every application on this job is timed against the right statute rather than against whatever the last job happened to use.",
      moduleLabel: "Payment Clock",
      moduleLabelKey: "nav.payment_clock",
      to: "/payment-clock",
    },
    {
      id: "dates",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.in.executed", label: "Executed contract" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.in.computed", label: "Statutory deadlines computed" },
      ],
      outputs: [
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.out.owned", label: "Contract dates with owners" },
        { labelKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.out.reminders", label: "Reminders before each date" },
      ],
      titleKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.title",
      titleDefault: "Get the dates with a consequence onto a clock",
      whatKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.what",
      whatDefault:
        "Record the dates the contract makes consequential: the date for completion, the notice periods, the retention release dates and the end of the rectification period. Give each one an owner so it lands on a person's list rather than on the project's.",
      whyKey: "cases.set_the_project_up_on_a_jct_or_nec4_contract.step.dates.why",
      whyDefault:
        "Contract dates are not diary entries, they are the moments a right appears or disappears. A missed pay less deadline changes what is payable and a missed notice under NEC4 can lose an entitlement outright, so these are the dates worth automating and the exact ones nobody remembers when the job is busy.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
