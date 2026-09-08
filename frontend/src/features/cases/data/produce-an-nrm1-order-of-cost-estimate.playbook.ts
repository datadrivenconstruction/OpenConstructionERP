// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Produce an NRM 1 order of cost estimate" (GB).
//
// The first estimate on a British project is produced under NRM 1 long before
// there is anything to measure, so the case runs the floor area method, holds
// the risk allowances as their own money, rebases for the date the work is
// actually built, and finishes on the basis of estimate. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "produce-an-nrm1-order-of-cost-estimate",
  order: 1160,
  region: "GB",
  category: "estimating",
  companyTypes: ["cost-consultant", "developer-client", "general-contractor"],
  roles: ["estimator", "quantity-surveyor"],
  stage: "estimate",
  icon: "Calculator",
  titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.title",
  titleDefault: "Produce an NRM 1 order of cost estimate",
  descKey: "cases.produce_an_nrm1_order_of_cost_estimate.desc",
  descDefault:
    "Turn a floor area and a building type into an order of cost estimate with an elemental split under it, hold the risk allowances as their own money, rebase to the date the work is built, and write the basis down while you still remember it.",
  longDescKey: "cases.produce_an_nrm1_order_of_cost_estimate.longdesc",
  longDescDefault:
    "NRM 1 is the RICS rule set for order of cost estimating and elemental cost planning, and the first number a client hears is almost always produced under it. At RIBA Stage 2 the only two things anybody knows well are the gross internal floor area and the kind of building, so the estimate is a rate per square metre with an elemental breakdown under it, plus the allowances that make it a project cost rather than a construction cost wearing a project's name. This case runs that sequence and ends on the basis of estimate, because an order of cost estimate with no assumptions written beside it is a number somebody will quote back at you in a year.",
  estMinutes: 14,
  steps: [
    {
      id: "shape",
      icon: "Building2",
      inputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.in.brief", label: "Client brief" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.in.gifa", label: "Gross internal floor area" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.out.estimate", label: "Order of cost estimate" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.out.band", label: "Accuracy band on the total" },
      ],
      titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.title",
      titleDefault: "Size the building before you price it",
      whatKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.what",
      whatDefault:
        "Enter the gross internal floor area, the building type, the quality level and the region. What comes back is a total with an elemental breakdown across substructure, superstructure, finishes, services and external works, and an accuracy band around it rather than one confident figure.",
      whyKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.shape.why",
      whyDefault:
        "NRM 1 calls the earliest estimate a floor area method estimate for a reason: the area and the building type are the only two things anybody knows properly at this point. Publishing the accuracy band beside the total is what stops a Stage 2 figure being read as a tender sum, which is how a project acquires a budget nobody ever agreed to.",
      moduleLabel: "Conceptual Estimate",
      moduleLabelKey: "nav.rom_estimate",
      to: "/rom-estimate",
    },
    {
      id: "risk",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.in.estimate", label: "Order of cost estimate" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.in.risks", label: "Risk register entries" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.out.held", label: "Risk allowances held" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.out.drawn", label: "Contingency drawdown record" },
      ],
      titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.title",
      titleDefault: "Carry the risk allowances as their own money",
      whatKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.what",
      whatDefault:
        "Open the register and put the four NRM 1 risk allowances in separately, design development risk, construction risk, employer change risk and employer other risk, rather than folding one percentage into the rate. As the design firms up, draw against them and read what is left.",
      whyKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.risk.why",
      whyDefault:
        "NRM 1 treats risk as a cost plan item with a name and an owner, not as a cushion buried in a rate. Held separately it can be reported, spent and released deliberately. Buried in the rate it is invisible, and the first time anybody goes looking for it is the day it has already gone.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "rebase",
      icon: "TrendingUp",
      inputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.in.rates", label: "Historic tender rates" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.in.series", label: "Tender price index series" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.out.total", label: "Rebased estimate total" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.out.adjust", label: "Time and location adjustment" },
      ],
      titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.title",
      titleDefault: "Rebase it to the date the money is spent",
      whatKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.what",
      whatDefault:
        "Load a tender price index series of the kind the cost information services publish, set the base period the rates came from and the target period the works will be tendered and built in, and let the adjustment run as the two lines NRM 1 keeps apart, tender inflation from the estimate base date to the date of tender and construction inflation from tender to the mid-point of construction. A location factor moves a national rate to the region the site is actually in.",
      whyKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.rebase.why",
      whyDefault:
        "A rate taken from a price book or from a finished job is priced at the date that job was tendered, and repeating it unchanged for work three years out is a forecast nobody made on purpose. Rebasing turns the gap into a line the client can see, argue with and sign off, which is the whole point of showing inflation rather than absorbing it.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "basis",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.in.total", label: "Rebased estimate total" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.in.quals", label: "Assumptions and exclusions" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.out.doc", label: "Basis of estimate document" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.out.record", label: "Exclusions on record" },
      ],
      titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.title",
      titleDefault: "Write the basis down while you still remember it",
      whatKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.what",
      whatDefault:
        "Generate the basis of estimate and work through the inclusions, exclusions and assumptions it proposes. Say which drawings and which revision the estimate was built from, what sits outside it, and what the client has to decide before the next stage can firm it up.",
      whyKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.basis.why",
      whyDefault:
        "This estimate will be set against a tender in eighteen months by somebody who was not in the room. Without the basis that comparison is between two numbers and somebody is at fault; with it the comparison is between two scopes, and the difference stops being an accusation and becomes a list.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "report",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.in.doc", label: "Basis of estimate document" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.in.elements", label: "Elemental cost breakdown" },
      ],
      outputs: [
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.out.report", label: "Stage cost report" },
        { labelKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.out.baseline", label: "Baseline for the next stage" },
      ],
      titleKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.title",
      titleDefault: "Issue it as a cost report the client can read",
      whatKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.what",
      whatDefault:
        "Produce the cost report for the stage: the elemental summary, the risk allowances, the inflation line and the accuracy band, in one document that is dated and versioned so the next stage has something firm to be measured against.",
      whyKey: "cases.produce_an_nrm1_order_of_cost_estimate.step.report.why",
      whyDefault:
        "Reporting cost against the RIBA stage it belongs to is what lets a client watch cost move as design moves, instead of watching one number get replaced by another with no account of why. A stage report that carries its own basis is also the only version of the estimate anybody can safely quote six months later.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
