// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Record a change under a CCDC-family contract" (CA).
//
// The objection is "our changes get sorted out on site and written up later",
// and later is when the memory of who agreed what has gone. The case follows
// the order the standard forms impose: notice first, valuation second by a
// route the contract names, and the contract price as a derived figure with a
// reason for every movement. The notice periods are stated in WORKING days, so
// the step tells the user to count them against their own site calendar and
// record the date rather than to assume a count. Content strings are key plus
// inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "record-a-change-under-a-ccdc-family-contract",
  order: 1103,
  region: "CA",
  category: "commercial",
  companyTypes: ["general-contractor", "project-manager", "cost-consultant"],
  roles: ["project-manager", "contract-administrator", "quantity-surveyor", "commercial-manager"],
  icon: "FileSignature",
  titleKey: "cases.record_a_change_under_a_ccdc_family_contract.title",
  titleDefault: "Record a change under a CCDC-family contract",
  descKey: "cases.record_a_change_under_a_ccdc_family_contract.desc",
  descDefault:
    "Give notice of the event inside the period the contract allows, raise the change against the clause it is raised under, value it by one of the routes the contract names and say which, and keep the contract price as a derived figure with a reason for every movement.",
  longDescKey: "cases.record_a_change_under_a_ccdc_family_contract.longdesc",
  longDescDefault:
    "The standard forms in the CCDC family put a bar in front of every change. A concealed or unknown condition, a delay and a claim each carry their own notice period, and a claim that misses one can be lost on the notice rather than on the merits, however good the merits are. What follows the notice is a valuation, and the general conditions for a change directive name the routes that will be accepted: the contract's own unit prices, cost plus a fixed or percentage fee, or an estimated and accepted lump sum with its supporting documentation. The change order clause names no method at all and expects the parties to have agreed one in the supplementary conditions, which is worth reading before you need it rather than after. One detail decides more disputes than any other: these periods are stated in working days, not calendar days, so count them against the site calendar with the statutory holidays your province actually keeps, and write the resulting date on the notice. A contract under the Civil Code of Quebec argues a change under different articles and is not covered here.",
  estMinutes: 18,
  steps: [
    {
      id: "notice",
      icon: "Send",
      inputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.in.event", label: "The site event and the day it was found" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.in.period", label: "The notice period the contract allows" },
      ],
      outputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.out.given", label: "Notice given and dated" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.out.expiry", label: "The day the period runs out" },
      ],
      titleKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.title",
      titleDefault: "Give the notice before you price anything",
      whatKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.what",
      whatDefault:
        "Send written notice of the event from the correspondence register on the day it is found, describing what was found and where, and record the date it was given and who received it. Count the period the contract allows in working days against your own site calendar and put that date on the record beside the notice.",
      whyKey: "cases.record_a_change_under_a_ccdc_family_contract.step.notice.why",
      whyDefault:
        "The general conditions give a concealed condition, a delay and a claim each their own period counted from the event or from its discovery, and a notice given late can lose an entitlement that would otherwise have been paid in full. Notice first and price second is the order that survives, because the price can be argued and the missed notice cannot.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "raise",
      icon: "FilePlus2",
      inputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.in.notice", label: "The notice as given" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.in.evidence", label: "Photographs and site records" },
      ],
      outputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.out.raised", label: "Change raised with its clause reference" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.out.attached", label: "Evidence attached to the change" },
      ],
      titleKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.title",
      titleDefault: "Raise it against the clause it is raised under",
      whatKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.what",
      whatDefault:
        "Open the change, name the contract and the general condition it is raised under in its reference, and attach the notice, the photographs and the survey that establish the condition you found.",
      whyKey: "cases.record_a_change_under_a_ccdc_family_contract.step.raise.why",
      whyDefault:
        "A change carrying its clause reference is a change the consultant can assess without asking what it is for, which is most of the delay in getting one approved. Six months later that reference is also the difference between an approved change and an argument about whether it was ever properly raised.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "value",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.in.measured", label: "Measured work or daywork records" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.in.rates", label: "Contract unit rates and agreed fee" },
      ],
      outputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.out.valued", label: "Valuation with its method named" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.out.support", label: "Supporting build-up attached" },
      ],
      titleKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.title",
      titleDefault: "Value it by a route the contract names, and say which",
      whatKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.what",
      whatDefault:
        "Price the change at the contract's own unit rates where the work is measurable, as cost plus the agreed fee off the daywork records where it is not, or as a lump sum with its build-up attached. State in the change which of the three you used and why that route fits this work.",
      whyKey: "cases.record_a_change_under_a_ccdc_family_contract.step.value.why",
      whyDefault:
        "A number without its method invites the other side to re-price it by a different method, and the method they choose will not be the one that favours you. Naming the route also settles the argument in the right order: first whether the route is right, which is a contract question, and only then whether the number is right, which is an arithmetic one.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "price",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.in.approved", label: "Approved change value" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.in.original", label: "Original stipulated price" },
      ],
      outputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.out.running", label: "Running contract price" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.out.reasons", label: "Every movement with a named reason" },
      ],
      titleKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.title",
      titleDefault: "Move the contract price with a reason attached",
      whatKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.what",
      whatDefault:
        "Approve the change against the contract so the running price shows the original stipulated price, every approved change with its own code and value, and the current price, instead of a total somebody keeps in a spreadsheet cell.",
      whyKey: "cases.record_a_change_under_a_ccdc_family_contract.step.price.why",
      whyDefault:
        "The contract price is a derived figure, and the only way to defend it at the final account is to walk it backwards to the changes that produced it. A running total nobody can explain is one the payer is entitled to question line by line, at exactly the point in the job where you most need the money.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.in.changes", label: "Notices, valuations and approvals" },
      ],
      outputs: [
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.out.register", label: "Change register issued" },
        { labelKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.out.unapproved", label: "Unapproved changes made visible" },
      ],
      titleKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.title",
      titleDefault: "Report the register every month, not at the end",
      whatKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.what",
      whatDefault:
        "Issue the change register with the monthly report: what has been notified, what is priced and waiting, what is approved, and what the contract price stands at today.",
      whyKey: "cases.record_a_change_under_a_ccdc_family_contract.step.report.why",
      whyDefault:
        "Changes get sorted out on site and written up later, and later is when the people who agreed them have moved on. A monthly register turns the writing-up into a five-minute review instead of a reconstruction, and it puts the unapproved column in front of the one person who can actually move it.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
