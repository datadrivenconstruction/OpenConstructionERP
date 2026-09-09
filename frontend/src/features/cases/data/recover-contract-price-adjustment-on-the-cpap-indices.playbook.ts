// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Recover contract price adjustment on the CPAP indices" (ZA).
//
// Contract price adjustment is a provision of the contract rather than a claim
// under it, so it is recovered by working the formula the contract data already
// carries, month by month, on the published work group indices. Content strings
// are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "recover-contract-price-adjustment-on-the-cpap-indices",
  order: 1349,
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "subcontractor"],
  roles: ["quantity-surveyor", "commercial-manager", "estimator", "contract-administrator"],
  region: "ZA",
  icon: "TrendingUp",
  titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.title",
  titleDefault: "Recover contract price adjustment on the CPAP indices",
  descKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.desc",
  descDefault:
    "Read the contract data to settle whether the job carries contract price adjustment, pin the base month and the work groups it names, separate the work the provisions reach from the work they do not, work the factor on the published indices and certify it as its own item.",
  longDescKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.longdesc",
  longDescDefault:
    "The contract price adjustment provisions are not a claim. They are a clause, worked by formula on index series published for the sector, and a contractor who never works them simply carries the inflation on a two year contract without ever presenting a figure to anybody. The Haylett formula behind them is arithmetic: each work group's current index over its base index, weighted the way the contract data weights it, applied to the adjustable portion of the value certified in the period. Everything hard about it is upstream of the arithmetic, in deciding which month is the base, which value the provisions actually reach, and what happens to the indices once the works are in delay.",
  estMinutes: 15,
  steps: [
    {
      id: "provisions",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.in.contract", label: "Signed contract" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.in.data", label: "Contract data" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.out.terms", label: "Adjustment terms recorded" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.out.base", label: "Base month fixed" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.title",
      titleDefault: "Settle whether the contract carries adjustment at all",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.what",
      whatDefault:
        "Read the contract data of the building agreement or of the civil engineering conditions and record four things before anything is measured: whether contract price adjustment applies, the base month it runs from, the work groups the contract names together with the weighting given to each, and the portion of the value the contract data holds non adjustable. Record as well what the contract says about the indices once the works are in delay.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.provisions.why",
      whyDefault:
        "A fixed price job and an adjustable one look identical on the drawings and differ by one page of the contract data. The difference is a year or two of inflation on the whole contract sum, and it is settled at tender stage by a person who is usually not the person certifying payment eighteen months later. Writing the terms down where the certificate is prepared is what stops the provisions being remembered at the final account.",
      moduleLabel: "Contracts",
      moduleLabelKey: "contracts.title",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "indices",
      icon: "LineChart",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.in.series", label: "Published index series" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.in.groups", label: "Work groups the contract names" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.out.base", label: "Base index pinned" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.out.monthly", label: "Monthly index record" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.title",
      titleDefault: "Load the work group indices and pin the base month",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.what",
      whatDefault:
        "Load the index series the contract data names, the work group indices published for building or for civil engineering work, and pin the base index to the month the contract fixes rather than to the month work started on site. Keep every month's figure with the date it was published and flag the ones that are still provisional.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.indices.why",
      whyDefault:
        "The indices are published behind the month they describe and the early figures are revised, so an adjustment worked on a provisional number will have to be worked again. Pinning the base once, at the start, is what stops every later certificate reopening the argument about which month the escalation runs from, which is the argument that costs the most and settles the least.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "split",
      icon: "Split",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.in.certified", label: "Certified value" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.in.exclusions", label: "Exclusions the contract names" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.out.adjustable", label: "Adjustable value" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.out.excluded", label: "Excluded amounts" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.title",
      titleDefault: "Separate the work the provisions reach from the work they do not",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.what",
      whatDefault:
        "Take the value certified for the period and set aside what the provisions do not adjust: materials on site that are not yet built in, the amounts the contract excludes by name, anything already adjusted under another clause, and the non adjustable portion the contract data fixes. What is left is the adjustable value for the month.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.split.why",
      whyDefault:
        "Applying escalation to the whole certificate is the commonest way an adjustment is refused in full rather than corrected in part. The exclusions are written in the contract and the person certifying knows them, so a submission that shows the split is checked once, while one that shows a single figure is queried every month until somebody stops asking for it.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "factor",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.in.adjustable", label: "Adjustable value" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.in.current", label: "Current indices" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.out.factor", label: "Adjustment factor" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.out.amount", label: "Amount for the month" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.title",
      titleDefault: "Work the factor the way the formula works it",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.what",
      whatDefault:
        "Take each work group's current index over its base index, weight it as the contract data weights it, sum the weighted ratios, subtract one, and apply the result to the adjustable value with the non adjustable portion held out. Record the index figures actually used against the month, not just the answer they produced.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.factor.why",
      whyDefault:
        "The formula is arithmetic and its result is only as defensible as the inputs printed beside it. An adjustment presented as one number is a request to be trusted, and the quantity surveyor certifying it is not permitted to trust it. The same working also says what the next few months cost if the trend holds, which is a figure the cash flow should have and usually does not.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "certify",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.in.amount", label: "Amount for the month" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.in.certificate", label: "Payment certificate" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.out.certified", label: "Adjustment certified" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.out.cumulative", label: "Cumulative position" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.title",
      titleDefault: "Certify the adjustment as its own item",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.what",
      whatDefault:
        "Put the adjustment on the payment certificate as a separate item with its working attached, never folded into the rates or into a lump sum under preliminaries. Carry the cumulative adjustment forward so the figure claimed this month is the movement since last month and not the total again.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.certify.why",
      whyDefault:
        "An adjustment buried in the rates cannot be checked, and what cannot be checked is deferred to the final account, where it is settled at whatever both sides can still evidence years later. Standing on its own line it is either paid this month or refused this month with a reason, and a refusal with a reason is something you can answer.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "delay",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.in.completion", label: "Contract completion date" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.in.extensions", label: "Extensions granted" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.out.cutoff", label: "Index cut-off date" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.out.risk", label: "Adjustment at risk" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.title",
      titleDefault: "Fix the date the indices stop moving",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.what",
      whatDefault:
        "Record the date the works were to reach practical completion together with every extension of time actually granted, and put both under a reminder. Where the contract stops the adjustment moving once the delay is the contractor's own, work the later months on the indices current at that date rather than at the date the work was done.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.delay.why",
      whyDefault:
        "This is the half of the provisions that runs against the contractor, and it is applied by the person certifying whether or not you applied it first. Knowing the date the indices freeze turns an extension of time from a programme argument into a money one, with a figure attached to every week of it, which is the only form in which such an argument gets settled quickly.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
    {
      id: "final",
      icon: "FileCheck2",
      inputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.in.final_indices", label: "Final indices" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.in.certified", label: "Certified adjustments" },
      ],
      outputs: [
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.out.reconciled", label: "Reconciled total" },
        { labelKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.out.line", label: "Final account line" },
      ],
      titleKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.title",
      titleDefault: "Rework the provisional months for the final account",
      whatKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.what",
      whatDefault:
        "When the final index figures are published, rework every month that was certified on a provisional one, set the reworked cumulative adjustment against what was actually paid, and settle the difference in the final account instead of leaving it in a spreadsheet nobody opens again.",
      whyKey: "cases.recover_contract_price_adjustment_on_the_cpap_indices.step.final.why",
      whyDefault:
        "Revisions run both ways, so a job that never reworks them leaves money on both sides of the table and has no way of saying which. The reconciliation is ten minutes of arithmetic while the file is open and an unprovable claim two years after the last certificate.",
      moduleLabel: "Post-calculation",
      moduleLabelKey: "postcalc.title",
      to: "/projects/:projectId/postcalc",
    },
  ],
};

export default playbook;
