// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Apply the price variation formula on a public contract" (IN).
//
// Long Indian public contracts carry a price variation clause, and it does not
// reimburse cost. It pays a computed amount: the work done in a period is split
// into components by fixed weightages, usually labour, cement, steel, fuel and
// other materials, and each component moves with a named published index
// between the base date and the period. What the contractor actually paid for
// cement that month does not enter the calculation at all.
//
// Three consequences follow, and all three are worth knowing before the first
// claim rather than after it. The formula can pay more or less than the cost
// actually incurred, and both happen. It is arithmetic on published numbers, so
// a claim on the correct basis is not really arguable, which makes it one of
// the few Indian entitlements that gets paid without a fight. And it is
// bounded: a clause usually names a threshold before it starts, a ceiling on
// what it can pay, and a base date that is fixed at tender rather than at
// award.
//
// The one thing that ruins it is the base. A wrong base index or a wrong base
// date is wrong in every period after it.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "apply-the-price-variation-formula-on-a-public-contract",
  order: 1186,
  region: "IN",
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client", "project-manager"],
  roles: ["commercial-manager", "quantity-surveyor", "contract-administrator", "accountant"],
  icon: "TrendingUp",
  titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.title",
  titleDefault: "Apply the price variation formula on a public contract",
  descKey: "cases.apply_the_price_variation_formula_on_a_public_contract.desc",
  descDefault:
    "Record the escalation clause with its components, weightages and base date, load the index series it names, compute the adjustment on the work done in the period, bill it and keep the arithmetic where a checker can repeat it.",
  longDescKey: "cases.apply_the_price_variation_formula_on_a_public_contract.longdesc",
  longDescDefault:
    "Price variation is the calmest money on an Indian job, and it is regularly left unclaimed because nobody set the base up at the beginning. The clause is a formula over published numbers: take the value of work done in the period, split it by the weightages the contract states, and move each part by the ratio between the current index and the base index for that component. Everything in that sentence has to be fixed once, correctly, and then never argued again. Which index series, published by whom, at what frequency. Which month is the base. Whether the base is the month of tender opening or the month of award, which are not the same and which the contract settles. Whether there is a threshold below which nothing is payable and a ceiling above which nothing more is. Get those right and every period afterwards is arithmetic; get one of them wrong and every period afterwards is wrong in the same direction, which is how a claim gets rejected in the eleventh month for a mistake made in the first.",
  estMinutes: 20,
  steps: [
    {
      id: "clause",
      icon: "FileSearch",
      inputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.in.contract",
          label: "The contract conditions",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.out.components",
          label: "Components and their weightages",
        },
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.out.base",
          label: "Base date, threshold and ceiling",
        },
      ],
      titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.title",
      titleDefault: "Write the clause down as parameters, not as prose",
      whatKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.what",
      whatDefault:
        "Record against the contract each component the clause names and its weightage, which index series applies to each, what the base date is, whether a minimum period must pass before anything is payable, and whether a ceiling applies.",
      whyKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.clause.why",
      whyDefault:
        "The clause is read once, at the start, by whoever is available, and then applied for years by other people. Turning it into stated parameters at that first reading is what stops the third claim being computed on a different understanding from the first.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "indices",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.indices.in.series",
          label: "The index series the clause names",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.indices.out.loaded",
          label: "Base and current index per component",
        },
      ],
      titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.indices.title",
      titleDefault: "Load the index series and pin the base month",
      whatKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.indices.what",
      whatDefault:
        "Bring in the published series for each component, record the base month value the contract fixes, and add each period's value as it is published. Where a series is revised after publication, keep both the provisional and the final figure.",
      whyKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.indices.why",
      whyDefault:
        "Index series get revised, and a claim computed on a provisional figure has to be reworked when the final one lands. Holding both makes that a recomputation rather than a discovery, and it explains the difference to the checker before they ask.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "apply",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.in.value",
          label: "Value of work done in the period",
        },
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.in.indices",
          label: "Base and current indices",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.out.adjustment",
          label: "The adjustment for the period",
        },
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.out.working",
          label: "Working, component by component",
        },
      ],
      titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.title",
      titleDefault: "Compute the adjustment on the period, component by component",
      whatKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.what",
      whatDefault:
        "Take the value of work executed in the period from the bill, split it by the weightages, apply each component's index movement, and keep the working visible per component rather than as a single figure.",
      whyKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.apply.why",
      whyDefault:
        "Escalation is checked by re-doing it, not by reading it. Working that shows the split, the two index values and the resulting amount for each component can be verified in minutes; a single total invites the checker to compute their own and argue about the difference.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "bill",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.bill.in.adjustment",
          label: "The computed adjustment",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.bill.out.line",
          label: "Escalation as its own bill line",
        },
      ],
      titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.bill.title",
      titleDefault: "Bill it as its own line, never inside the rates",
      whatKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.bill.what",
      whatDefault:
        "Put the adjustment on the running account bill as a separate line naming the period and the clause, and let the tax and the deductions treat it the way the contract and the invoice rules require.",
      whyKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.bill.why",
      whyDefault:
        "Escalation folded into rates makes the rates untraceable to the contract and the escalation untraceable to a period, so both become unverifiable at once. Kept as a line, it can be certified, queried or withheld on its own without touching the measured work.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "evidence",
      icon: "FileStack",
      inputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.evidence.in.working",
          label: "The working and the published figures",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.evidence.out.file",
          label: "A file that supports every period",
        },
      ],
      titleKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.evidence.title",
      titleDefault: "Keep the evidence with the period it belongs to",
      whatKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.evidence.what",
      whatDefault:
        "File the published index pages used, the value of work certified for the period, and the working, all keyed to the period, so any single month can be produced on its own.",
      whyKey: "cases.apply_the_price_variation_formula_on_a_public_contract.step.evidence.why",
      whyDefault:
        "Escalation is settled at the end of the job as often as during it, by which time the person who computed period four has left. A file organised by period answers a query about period four; a file organised by year does not.",
      moduleLabel: "Claims Evidence",
      moduleLabelKey: "nav.claims_evidence",
      to: "/projects/:projectId/claims-evidence",
    },
  ],
};

export default playbook;
