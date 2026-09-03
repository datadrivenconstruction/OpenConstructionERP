// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Analyse a schedule rate into labour, material and machinery" (IN).
//
// Rate analysis is how an Indian estimate answers the question a schedule
// cannot: what does this item cost when we do it, on this site, this year. A
// published schedule rate is an analysis somebody else performed on a stated
// method and a stated price level, and the moment either of those stops
// matching your job, the rate stops being an answer and becomes a benchmark.
//
// Two occasions make the analysis compulsory rather than optional. A
// non-schedule item has no published rate at all and has to be built from its
// constituents. And an extra item on a running contract is priced by analysis
// on the schedule's own method, because that is the only basis both sides
// already accept.
//
// The analysis itself is the same either way: quantities of material per unit
// of finished work, the labour to place it, the plant time, then the carriage,
// and the contractor's profit and overheads on top of the direct cost, kept as
// a percentage line rather than buried in the constituents.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "analyse-a-schedule-rate-into-labour-material-and-machinery",
  order: 1182,
  region: "IN",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "subcontractor", "developer-client"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Calculator",
  titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.title",
  titleDefault: "Analyse a schedule rate into labour, material and machinery",
  descKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.desc",
  descDefault:
    "Open a schedule item into the material, labour and plant it actually consumes, price those with your own rates, keep profit and overheads as a visible percentage, and save the result as an assembly you can defend and reuse.",
  longDescKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.longdesc",
  longDescDefault:
    "A schedule of rates is a book of conclusions. Rate analysis is the working that produced them, and on an Indian job you need the working twice: once for the items the schedule does not carry, and once for the extra items priced during execution, where the department will only accept a rate derived on the schedule's own method. Doing it properly is not arithmetic, it is a set of decisions that have to be visible: how much cement goes into a cubic metre of that grade, how many mason and helper hours place it, what the mixer and the vibrator cost for the time they are on it, what the carriage adds by lead and lift, and what percentage sits on top for the contractor. Each of those is arguable on its own, which is exactly why keeping them apart matters. An analysis where every constituent can be queried separately survives a rate query; a single derived number cannot be defended at all, only insisted on.",
  estMinutes: 20,
  steps: [
    {
      id: "item",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.in.schedule",
          label: "The loaded schedule of rates",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.in.spec",
          label: "The specification for the work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.out.item",
          label: "The item and what its rate covers",
        },
      ],
      titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.title",
      titleDefault: "Find the item and read what its rate is supposed to include",
      whatKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.what",
      whatDefault:
        "Locate the nearest schedule item to the work in hand and read its description against the specification: the grade, the thickness, whether centering and shuttering are inside the item or billed separately, whether carriage is included.",
      whyKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.item.why",
      whyDefault:
        "Most rate arguments are really description arguments. Two people agree on the cost of concrete and disagree about whether the item was supposed to include the formwork, and no amount of analysis settles that. Reading the description first tells you whether you are analysing a rate or discovering a missing item.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "constituents",
      icon: "Layers",
      inputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.in.method",
          label: "The construction method assumed",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.in.unit",
          label: "One unit of finished work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.out.materials",
          label: "Material per unit, with wastage",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.out.hours",
          label: "Labour and plant hours per unit",
        },
      ],
      titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.title",
      titleDefault: "Open the unit into what it consumes",
      whatKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.what",
      whatDefault:
        "Expand one unit of the item into its constituents: the materials and their wastage allowance, the trade and helper hours to place them, and the plant hours the method needs. Adjust the assumed method where your site does it differently, and leave a note saying so.",
      whyKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.constituents.why",
      whyDefault:
        "This step is where an inherited norm meets a real site, and the mismatch is worth finding now. A norm that assumes machine mixing on a job doing hand mixing will be wrong in the labour line and right in the material line, and only an opened analysis shows you which half to trust.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "labour",
      icon: "Users",
      inputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.in.hours",
          label: "Hours from the analysis",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.in.wages",
          label: "The wages you actually pay",
        },
      ],
      outputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.out.rate",
          label: "An all-in rate per trade",
        },
      ],
      titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.title",
      titleDefault: "Price the hours at what labour costs you",
      whatKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.what",
      whatDefault:
        "Build the labour rate per trade from the wage you pay plus what sits on top of it: the statutory contributions, the site allowances, the non-productive time you carry. Use the minimum wage notified for the state as a floor rather than as the answer.",
      whyKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.labour.why",
      whyDefault:
        "Labour is where a schedule rate ages fastest and where a contractor's own figure is genuinely better information than a published one. It is also the constituent most often priced at the bare wage, which quietly removes the contribution and allowance cost from every item in the estimate at once.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "assembly",
      icon: "Boxes",
      inputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.in.priced",
          label: "The priced constituents",
        },
      ],
      outputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.out.assembly",
          label: "A reusable analysed rate",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.out.markup",
          label: "Profit and overheads as their own line",
        },
      ],
      titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.title",
      titleDefault: "Save it as an assembly, with the percentage kept outside",
      whatKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.what",
      whatDefault:
        "Store the analysis as a named assembly so the next bill can use it, and keep the contractor's profit and overheads as a percentage on the direct cost rather than absorbing it into the constituent prices.",
      whyKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.assembly.why",
      whyDefault:
        "A tender is often accepted at a percentage above or below the estimated rates, and an assembly whose profit line is visible can be re-quoted at a different percentage in one move. One whose profit is spread through the material prices has to be rebuilt from the beginning, and usually is not.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "compare",
      icon: "GitCompareArrows",
      inputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.in.analysed",
          label: "Your analysed rate",
        },
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.in.published",
          label: "The published schedule rate",
        },
      ],
      outputs: [
        {
          labelKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.out.gap",
          label: "Where the two disagree, and why",
        },
      ],
      titleKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.title",
      titleDefault: "Hold your rate against the published one",
      whatKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.what",
      whatDefault:
        "Compare the analysed rate with the schedule rate for the same item and look at the constituents rather than the totals. Note which constituent carries the difference: material price, labour, plant, or the percentage on top.",
      whyKey: "cases.analyse_a_schedule_rate_into_labour_material_and_machinery.step.compare.why",
      whyDefault:
        "A gap in the material line usually means the schedule is out of date and is an argument you can win with quotations. A gap in the labour line usually means the method differs and is an argument you win with the analysis. Knowing which one you have before the meeting decides how it goes.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
  ],
};

export default playbook;
