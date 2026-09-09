// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build the cronograma fisico-financeiro from the orcamento" (BR).
//
// Lei 14.133/2021 requires the works package to carry a detailed budget built
// on measured quantities, and the cronograma fisico-financeiro is the document
// that turns that budget into the disbursement the contract is measured and
// paid against. So the curve has to be derived from the priced bill rather
// than drawn beside it. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-the-cronograma-fisico-financeiro-from-the-orcamento",
  order: 1507,
  region: "BR",
  category: "planning",
  companyTypes: ["general-contractor", "developer-client", "project-manager"],
  roles: ["planner", "estimator", "project-manager", "commercial-manager"],
  icon: "GanttChartSquare",
  titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.title",
  titleDefault: "Build the cronograma fisico-financeiro from the orcamento",
  descKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.desc",
  descDefault:
    "Take the priced orcamento as the source, sequence the work, link every item to the activity that earns it, spread the money over the periods, prove the periods sum to the contract total and publish the curve with the proposal.",
  longDescKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.longdesc",
  longDescDefault:
    "The cronograma fisico-financeiro is two documents pretending to be one: a programme that says when the work happens and a disbursement curve that says when the money moves, and they are only useful when the second is derived from the first rather than negotiated separately. Lei 14.133 of 2021 requires the works package to rest on a detailed budget built from measured quantities, and it is that budget the cronograma has to spend, item by item, so that the sum of the monthly figures is the contract sum and not an approximation of it. Built by linking each item to the activity that earns it, the curve moves on its own when the programme moves and the argument about a late medicao becomes an argument about the programme, which is where it belongs. Drawn separately in a spreadsheet, it agrees with the bill on the day it is written and never again.",
  estMinutes: 16,
  steps: [
    {
      id: "source",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.in.priced",
          label: "Priced bill positions",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.in.groups",
          label: "Item groups of the orcamento",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.out.total",
          label: "Contract total to be spread",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.out.units",
          label: "Quantities behind every figure",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.title",
      titleDefault: "Start from the priced orcamento, not from a summary",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.what",
      whatDefault:
        "Open the priced bill and confirm that every item carries a quantity, a unit and a value, and that the group structure is the one the cronograma will report against. Fix the structure here rather than inventing a second grouping for the schedule.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.source.why",
      whyDefault:
        "Lei 14.133 of 2021 requires the works package to carry a detailed budget grounded in measured quantities, so the bill is the legal source of the figures and the cronograma is a view of it. A curve built from a summary sheet quietly becomes a third document with a total of its own, and the first medicao is where the three are discovered to disagree.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "sequence",
      icon: "GanttChartSquare",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.in.method",
          label: "Method and crew sizes",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.in.units",
          label: "Quantities behind every figure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.out.programme",
          label: "Baseline programme",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.out.milestones",
          label: "Milestone dates named",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.title",
      titleDefault: "Sequence the work into a programme",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.what",
      whatDefault:
        "Build the activities the work is actually done in, give each one a duration that comes from the quantity and the crew rather than from the calendar you would like, and set the dependencies between them. Name the milestones the contract will be measured against.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.sequence.why",
      whyDefault:
        "The physical half of the cronograma is the half that gets skipped, because the financial half can be produced by dividing the total into equal months and nobody notices for a quarter. A programme built from quantities and crews is the only version that answers the question the client will ask in month three, which is whether the plan was ever achievable.",
      moduleLabel: "4D Schedule",
      moduleLabelKey: "nav.schedule",
      to: "/schedule",
    },
    {
      id: "link",
      icon: "GitBranch",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.in.programme",
          label: "Baseline programme",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.in.priced",
          label: "Priced bill positions",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.out.linked",
          label: "Every item linked to an activity",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.out.orphans",
          label: "Items no activity earns",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.title",
      titleDefault: "Link every item to the activity that earns it",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.what",
      whatDefault:
        "Attach each bill item to the activity that will earn it, splitting an item across two activities where the work really is done in two places. Then look at what is left over on both sides: items no activity earns, and activities that earn nothing.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.link.why",
      whyDefault:
        "The leftovers are the finding. An item nothing earns is usually work that was priced and then left out of the plan, and an activity earning nothing is usually work that will be done and was never priced. Both are cheap to fix now and expensive to discover during a medicao, when one of them is already built.",
      moduleLabel: "5D Cost Model",
      moduleLabelKey: "nav.5d_cost_model",
      to: "/5d",
    },
    {
      id: "curve",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.in.linked",
          label: "Every item linked to an activity",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.in.periods",
          label: "Measurement periods of the contract",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.out.curve",
          label: "Cash forecast per period",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.out.peak",
          label: "Peak funding named",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.title",
      titleDefault: "Spread the money over the measurement periods",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.what",
      whatDefault:
        "Let the linked values fall into the periods the contract measures in, and read the cumulative curve as well as the monthly bars. Note the month of peak funding and what the advance, if there is one, does to it.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.curve.why",
      whyDefault:
        "The client reads the cronograma as a budget commitment and the contractor reads it as working capital, and the two readings meet at the peak. Named in advance it is a financing decision. Discovered in month five it is a conversation about slowing the work down, which costs both parties more than the finance would have.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.in.curve",
          label: "Cash forecast per period",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.in.total",
          label: "Contract total to be spread",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.out.report",
          label: "Validation report on the totals",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.out.diff",
          label: "Difference to explain",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.title",
      titleDefault: "Prove the periods add up to the contract sum",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.what",
      whatDefault:
        "Run the check that the sum of the periods equals the total of the priced bill, and that no period is negative or empty in the middle of continuous work. Chase any difference back to the item that caused it rather than adjusting the last month to close it.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.check.why",
      whyDefault:
        "A cronograma that does not total to the contract sum will be rejected on sight, and closing the gap by editing the final month hides whatever caused it, usually an item linked twice or linked to nothing. The check takes seconds and the diagnosis it gives is the part worth having.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "publish",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.in.curve",
          label: "Cash forecast per period",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.in.programme",
          label: "Baseline programme",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.out.export",
          label: "Cronograma export for the proposal",
        },
        {
          labelKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.out.baseline",
          label: "Baseline the medicoes report against",
        },
      ],
      titleKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.title",
      titleDefault: "Publish it as the baseline the medicoes report against",
      whatKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.what",
      whatDefault:
        "Export the physical and the financial halves as one document with the same period headings, and keep the version that went with the proposal as the baseline. Later revisions are compared against it rather than replacing it silently.",
      whyKey: "cases.build_the_cronograma_fisico_financeiro_from_the_orcamento.step.publish.why",
      whyDefault:
        "Every medicao is read against the cronograma, and the whole conversation about delay depends on which version of it both sides are holding. A baseline kept as issued makes the comparison a fact. A cronograma quietly updated each month makes the job look on programme until the last month, when the remaining work no longer fits in it.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
