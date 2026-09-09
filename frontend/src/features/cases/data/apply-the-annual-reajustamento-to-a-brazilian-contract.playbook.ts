// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Apply the annual reajustamento to a Brazilian contract" (BR).
//
// Lei 10.192/2001 fixes the periodicity of price adjustment at one year from
// the data-base, and Lei 14.133/2021 requires the contract to name the index
// and that date. Reajustamento is therefore arithmetic on a clock the contract
// already set, not a negotiation: what needs care is which work has reached
// its anniversary and that the result is recorded as an adjustment rather than
// as a new price. Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "apply-the-annual-reajustamento-to-a-brazilian-contract",
  order: 1508,
  region: "BR",
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "developer-client"],
  roles: ["commercial-manager", "contract-administrator", "quantity-surveyor", "accountant"],
  icon: "TrendingUp",
  titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.title",
  titleDefault: "Apply the annual reajustamento to a Brazilian contract",
  descKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.desc",
  descDefault:
    "Read the index, the data-base and the periodicity out of the contract, load the published series, find the work whose anniversary has passed, apply the formula and record the result as an adjustment carried into the accounts.",
  longDescKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.longdesc",
  longDescDefault:
    "Three different things get called a price increase on a Brazilian contract and only one of them is reajustamento. Reajustamento is the index-linked adjustment the contract itself provides for, it runs on the periodicity Lei 10.192 of 2001 sets at one year from the data-base, and because it was agreed in advance it is applied by an administrative note rather than by an amendment. Repactuacao is the renegotiation of a labour-heavy service contract when the collective agreement moves. Reequilibrio economico-financeiro is the extraordinary remedy for an event nobody could have foreseen. Contractors lose money by asking for the third when they were entitled to the first, because the first only needs an index and a date while the third needs proof, and they lose it again by never asking at all, since nothing in the contract makes the anniversary announce itself.",
  estMinutes: 15,
  steps: [
    {
      id: "clause",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.in.contract",
          label: "Signed contract terms",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.in.edital",
          label: "Edital and its annexes",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.out.index",
          label: "Index named by the contract",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.out.date",
          label: "Data-base date on the record",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.title",
      titleDefault: "Read the index and the data-base out of the contract",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.what",
      whatDefault:
        "Record three things from the contract itself: which index applies, and to which parcels of the work if there is more than one, what date the prices are referred to, and how the periodicity is counted. Note whether the data-base is the date of the proposal or the reference month of the orcamento, because they are often different.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.clause.why",
      whyDefault:
        "Lei 14.133 of 2021 requires the contract to state the criterion, the index and the date, and Lei 10.192 of 2001 fixes the periodicity at one year, so all three facts already exist and none of them is negotiable. What is negotiable is which of two plausible dates the parties meant, and settling that at the start of the contract costs a sentence rather than a claim.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "index",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.in.name",
          label: "Index named by the contract",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.in.series",
          label: "Published index series",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.out.loaded",
          label: "Index series loaded by month",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.out.factor",
          label: "Factor between the two months",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.title",
      titleDefault: "Load the index the contract names, not the one you follow",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.what",
      whatDefault:
        "Load the published series for the named index, month by month, from the data-base to the month of application, and compute the factor between the two. Where the contract splits the work between several indices, load each one and keep the parcels apart.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.index.why",
      whyDefault:
        "A construction cost index and a general price index diverge by several points a year, which on a long contract is the whole margin. Using the one you normally follow rather than the one the contract names produces a number that is defensible in every way except the one that matters, and the correction lands after the invoice is out.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "eligible",
      icon: "CalendarCheck",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.in.progress",
          label: "Work measured to date",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.in.date",
          label: "Data-base date on the record",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.out.eligible",
          label: "Work past its anniversary",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.out.excluded",
          label: "Work still inside the year",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.title",
      titleDefault: "Find the work whose anniversary has passed",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.what",
      whatDefault:
        "Split the measured work by the period it was executed in and separate what falls after the first anniversary of the data-base from what falls before it. Keep the two lists rather than applying an average to everything.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.eligible.why",
      whyDefault:
        "The periodicity is annual under Lei 10.192 of 2001, so work executed inside the first year is not adjusted at all and work executed afterwards is adjusted by the factor for its own month. An average applied to the whole contract overpays one half and underpays the other, and it is the overpaid half that gets questioned.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "compute",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.in.eligible",
          label: "Work past its anniversary",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.in.factor",
          label: "Factor between the two months",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.out.amount",
          label: "Adjustment amount per item",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.out.workings",
          label: "Workings anybody can repeat",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.title",
      titleDefault: "Apply the formula to the eligible amounts",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.what",
      whatDefault:
        "Apply the factor to the eligible value, parcel by parcel where the contract uses more than one index, and keep the calculation visible: the base value, the two index readings, the factor and the result. Do not adjust an item that was already priced at a later reference month.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.compute.why",
      whyDefault:
        "Reajustamento is one of the few figures in a contract that both sides can compute independently and get the same answer to, which makes showing the workings a cheap way of removing the argument entirely. An amount presented without them is treated as a request rather than as an entitlement.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "record",
      icon: "FileCheck2",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.in.amount",
          label: "Adjustment amount per item",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.in.clause",
          label: "Clause that provides for it",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.out.entry",
          label: "Adjustment recorded as its own line",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.out.trail",
          label: "Approval trail attached",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.title",
      titleDefault: "Record it as an adjustment, not as a new price",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.what",
      whatDefault:
        "Raise the reajustamento as its own entry against the contract, citing the clause and the index readings, and keep the original unit prices untouched underneath it. Do not fold the adjustment into the rates, and do not open a renegotiation of scope alongside it.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.record.why",
      whyDefault:
        "An adjustment the contract already provides for is recorded by administrative note, while a change to the price itself is an amendment with a different approval path and a different audit reading. Folding it into the rates loses that distinction, and it also destroys the base the next annual adjustment has to be computed from.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "settle",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.in.entry",
          label: "Adjustment recorded as its own line",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.in.medicao",
          label: "Medicao for the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.out.invoice",
          label: "Adjustment carried to invoice",
        },
        {
          labelKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.out.next",
          label: "Next anniversary on the calendar",
        },
      ],
      titleKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.title",
      titleDefault: "Carry it into the accounts and set the next date",
      whatKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.what",
      whatDefault:
        "Put the adjustment through with the medicao it belongs to so the invoice and the contract record hold the same figure, and set the next anniversary as a dated item somebody owns before you close the file.",
      whyKey: "cases.apply_the_annual_reajustamento_to_a_brazilian_contract.step.settle.why",
      whyDefault:
        "The second year is the one that gets missed, because the first was prompted by somebody noticing. On a four year contract that is three quarters of the entitlement, and it is not recoverable later by arithmetic alone, since the periods it belonged to have been invoiced and settled at the old prices.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
