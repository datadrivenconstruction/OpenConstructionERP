// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price the orcamento de referencia from the SINAPI base" (BR).
//
// Decreto 7.983/2013 does not merely suggest a reference base for federal
// works, it caps each unit cost at the SINAPI median for the same item and
// sets the order in which a cost may be established when SINAPI carries
// nothing. So the work is mapping, checking against a ceiling and recording
// provenance, not typing prices. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-the-orcamento-de-referencia-from-the-sinapi-base",
  order: 1501,
  region: "BR",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Database",
  titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.title",
  titleDefault: "Price the orcamento de referencia from the SINAPI base",
  descKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.desc",
  descDefault:
    "Load SINAPI for the reference month, map every item of the orcamento to its code, hold each unit cost to the median the decree allows, and record where the cost came from for the items SINAPI does not carry.",
  longDescKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.longdesc",
  longDescDefault:
    "SINAPI is a survey, not a price list, and Decreto 7.983 of 2013 turns that survey into a rule: for building works paid with federal money the unit cost in the orcamento de referencia may not exceed the SINAPI median for the corresponding item, and where SINAPI carries no such item the decree names the order in which another source may be used. Two consequences follow that an estimator new to public work usually learns the expensive way. The reference month and the state are part of the price, so an orcamento priced on one month and defended against another is arguing about the wrong number. And an item priced from a supplier quote because it was quicker than finding the code is not a cheaper item, it is an unjustified one, which is the finding an auditor writes rather than a difference anybody negotiates.",
  estMinutes: 18,
  steps: [
    {
      id: "base",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.in.tables",
          label: "SINAPI reference prices",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.in.date",
          label: "Reference date the edital names",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.out.loaded",
          label: "Priced reference base loaded",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.out.state",
          label: "State and reference month recorded",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.title",
      titleDefault: "Bring in SINAPI for the state and the reference month",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.what",
      whatDefault:
        "Load the SINAPI tables into the cost database for the state the work is in and the reference month the edital names, and keep the two on the record beside the prices. Load the encargos sociais table that goes with the same month rather than one you already had.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.base.why",
      whyDefault:
        "A SINAPI price without its state and its reference month is not a reference, it is a number. Every argument about the orcamento de referencia begins by agreeing which table both sides are reading, and that agreement is free now and costs a week once the proposals are in.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "map",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.in.items",
          label: "Item list of the orcamento",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.in.catalog",
          label: "SINAPI code catalogue",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.out.coded",
          label: "Coded bill positions",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.out.gaps",
          label: "Items with no SINAPI code",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.title",
      titleDefault: "Map every item of the orcamento to its SINAPI code",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.what",
      whatDefault:
        "Put the SINAPI code on each position of the bill and check that the code's description, its unit and its scope really are what your item measures. Where a position is served by two codes that differ only in a detail of the method, pick the one the design specifies and say so. Collect the items no code fits rather than forcing them onto the nearest one.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.map.why",
      whyDefault:
        "The code carries the composicao behind the price, so a code chosen for its description alone imports a productivity and a set of insumos nobody read. Forcing an item onto a near code is the quiet version of the same mistake: the total looks defensible and the composicao behind it describes different work.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "median",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.in.coded",
          label: "Coded bill positions",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.in.median",
          label: "SINAPI median unit prices",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.out.report",
          label: "Validation report on the ceiling",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.out.over",
          label: "Positions above the reference price",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.title",
      titleDefault: "Hold every unit cost to the median the decree allows",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.what",
      whatDefault:
        "Run the priced bill against the reference base and list every position whose unit cost sits above the SINAPI median for its code. Treat each one as a question with two possible answers: the code is wrong, or the price needs a written justification. Do not close the list by editing the number down until it fits.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.median.why",
      whyDefault:
        "Decreto 7.983 of 2013 makes the median a ceiling rather than a benchmark for works carried out with federal funds, so a position above it is not expensive, it is outside the rule until somebody explains why. Found here it is a paragraph. Found by the control body it is a finding against the whole orcamento, and the recalculation lands on the contract that was already signed.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "sources",
      icon: "BookOpen",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.in.gaps",
          label: "Items with no SINAPI code",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.in.quotes",
          label: "Supplier quotes and published rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.out.basis",
          label: "Source recorded per item",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.out.order",
          label: "Fallback order followed",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.title",
      titleDefault: "Follow the decree's order for what SINAPI does not carry",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.what",
      whatDefault:
        "For each item left over, work down the order the decree sets before reaching for a quote: another reference table formally approved by a federal body, then specialist technical publications or a sector system, and a market survey only after those. Record on the basis of estimate which one you used, for which item, and on what date.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.sources.why",
      whyDefault:
        "The order is the justification. An item priced from three quotes is defensible when the tables above it genuinely carried nothing, and indefensible when nobody looked. Written down at the moment of the decision, the reasoning survives the estimator leaving the company, which is roughly the timescale on which the question gets asked.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "global",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.in.priced",
          label: "Priced bill positions",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.in.bdi",
          label: "BDI rate",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.out.total",
          label: "Custo global de referencia",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.out.split",
          label: "Cost analysis by group",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.title",
      titleDefault: "Total the custo global with the BDI shown separately",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.what",
      whatDefault:
        "Total the direct costs by group and read them against each other before adding anything on top. Keep the BDI as its own visible line rather than folded into the unit costs, and see which groups carry the money so you know which numbers the whole orcamento actually rests on.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.global.why",
      whyDefault:
        "A custo global that arrives as one figure cannot be argued with, only accepted or rejected. Split by group it shows immediately whether the earthworks or the finishes are carrying the estimate, and a BDI folded into the unit costs makes both the median check and the later composition of the BDI impossible to run at all.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "publish",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.in.total",
          label: "Custo global de referencia",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.in.basis",
          label: "Source recorded per item",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.out.export",
          label: "Orcamento export for the edital",
        },
        {
          labelKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.out.trail",
          label: "Reference month on every page",
        },
      ],
      titleKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.title",
      titleDefault: "Publish it with the base and the month on its face",
      whatKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.what",
      whatDefault:
        "Export the orcamento with the SINAPI reference month, the state and the encargos option printed on it, together with the list of items priced from another source. Send that set as one document rather than the bill alone.",
      whyKey: "cases.price_the_orcamento_de_referencia_from_the_sinapi_base.step.publish.why",
      whyDefault:
        "The bill on its own is the only part anybody copies, and six months later the month it was priced in is the fact everyone needs and nobody has. Printed on the face of the export it travels with the numbers, and the reajustamento clause later has a data-base it can actually point at.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
