// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a base year smeta with the Minstroy recalculation index" (RU).
//
// Declare which price base the positions sit in and which quarter it refers to,
// enter the index the Ministry published as an index series per element with
// the region on the location factor, read the escalation preview and carry the
// rates only onto what is still in base money, and print the coefficient and
// its source on the face of the smeta. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-base-year-smeta-with-the-minstroy-index",
  order: 1302,
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client"],
  roles: ["estimator", "quantity-surveyor"],
  region: "RU",
  icon: "TrendingUp",
  titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.title",
  titleDefault: "Price a base year smeta with the Minstroy recalculation index",
  descKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.desc",
  descDefault:
    "Record the price base and the quarter it belongs to, enter the index published for your region and type of construction, apply it only to positions still in base money, and put the coefficient and its source on the document.",
  longDescKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.longdesc",
  longDescDefault:
    "The base index method priced budget-funded work in Russia for two decades and is still how a great deal of documentation reaches an estimator: the positions stay in a base price level and a published recalculation index converts them into today's money. The federal method has moved to resource index pricing since the 2022 norm base, but a smeta on the old method keeps arriving and has to be brought to a current quarter correctly. The whole answer hangs on two facts that nobody can reconstruct later, which base date the positions carry and which quarter's index was applied to them. Get either wrong and the total is out by tens of percent while every line still looks correct, because the arithmetic is right and only the period is not.",
  estMinutes: 12,
  steps: [
    {
      id: "basedate",
      icon: "CalendarDays",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.in.smeta", label: "Smeta in base prices" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.in.target", label: "Target quarter" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.out.base", label: "Base date on the bill" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.out.scope", label: "Region and type of construction" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.title",
      titleDefault: "Declare the price base and the date it belongs to",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.what",
      whatDefault:
        "Set the base date on the bill header, the 2001 base or the quarter of a current price base, so the estimate states which roubles it is in, and record the period you need the money brought to, the region and the type of construction in the basis of estimate beside it.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.basedate.why",
      whyDefault:
        "An index is a ratio between two periods and it means nothing without both of them. The base date on the bill is the price level validation reads, and a smeta that does not state it cannot be re-checked by anyone, including the person who wrote it six months later.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "index",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.in.publication", label: "Index published for the quarter" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.in.scope", label: "Region and type of construction" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.out.elements", label: "Coefficients by element" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.out.provenance", label: "Publication reference" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.title",
      titleDefault: "Enter the index the Ministry published for the quarter",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.what",
      whatDefault:
        "Create an index series for the recalculation index the Ministry of Construction published for your type of construction, with the quarter as the period and the published value as the factor, and where the publication splits the index by element make a series for each: one for construction and assembly work as a whole, and separate ones for labour, machine operation and materials. Put the region on the location factor and the publication reference in the series description.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.index.why",
      whyDefault:
        "One index for the whole smeta is the shortcut that costs most. Labour, machines and materials move at different speeds, and where the publication gives separate coefficients an expertise reviewer expects them applied separately. An index taken from a neighbouring region or from a different type of construction produces a defensible looking total that is simply the wrong one.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "apply",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.in.positions", label: "Positions in base money" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.in.factors", label: "Coefficients by element" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.out.current", label: "Escalated rate per position" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.out.excluded", label: "Rates the preview could not escalate" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.title",
      titleDefault: "Apply the factor only to what is still in base money",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.what",
      whatDefault:
        "Run the escalation preview scoped to this project, from each rate's own price date to the target quarter, and read it line by line: the factor, the escalated rate and, for a rate the preview could not escalate, the note saying why. Then carry the escalated rates onto the positions still in base money yourself, leave anything already priced from a quotation or an invoice untouched, and keep the preview's list of what was left out.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.apply.why",
      whyDefault:
        "Double indexing is the quiet error of this method: equipment bought on a current quotation, or a material priced from a real invoice, gets multiplied a second time by a coefficient built for base year money. The preview writes nothing to the bill, which is the point: the rate that reaches a position is one an estimator read and accepted, and the note on a rate with no price date is the exception list rather than a silent skip.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.in.indexed", label: "Indexed smeta" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.in.rules", label: "Validation rule set" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.out.exceptions", label: "Exception list" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.out.fixed", label: "Corrections applied" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.title",
      titleDefault: "Check what the coefficient should never have touched",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.what",
      whatDefault:
        "Run validation on the indexed bill and read what the Russian rules report: a bill with no base date declared, a line without a norm code or with one that is not in the base, a rate with no resources behind it, and any markup line whose base is not settled. Then go back to the preview's list for the positions the coefficient should not have touched, and clear both lists before the smeta leaves.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.check.why",
      whyDefault:
        "The arithmetic of indexing is trivial and always passes, so validation reads the document rather than the sum: whether it says which roubles it is in and whether every line can be traced to a published norm, which is what an expertise reviewer checks first. The positions indexed twice or priced from a quotation are not a rule's business, they are the preview's, and the two lists together are the whole check.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "compare",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.in.heavy", label: "Positions carrying the cost" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.in.resource", label: "Resource priced check" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.out.gap", label: "Gap per position" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.out.reason", label: "Reason on record" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.title",
      titleDefault: "Test the heaviest positions against a resource price",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.what",
      whatDefault:
        "Take the positions that carry most of the total, price a handful of them from resources at today's money, and compare the two answers. Record the gap and the reason for it, not only the number.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.compare.why",
      whyDefault:
        "This is the resource index method used as a check rather than as a method. An index describes an average, and the positions that dominate your total are the ones least likely to be average. Where the two answers diverge sharply you have found either a stale coefficient or a position built on the wrong norm, and both are far cheaper to find before the contract is signed.",
      moduleLabel: "Cost Explorer",
      moduleLabelKey: "nav.cost_explorer",
      to: "/cost-explorer",
    },
    {
      id: "report",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.in.checked", label: "Checked smeta" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.in.provenance", label: "Index provenance" },
      ],
      outputs: [
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.out.issued", label: "Issued smeta" },
        { labelKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.out.trail", label: "Reproducible calculation trail" },
      ],
      titleKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.title",
      titleDefault: "Show the coefficient and its source on the document",
      whatKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.what",
      whatDefault:
        "Issue the smeta with the base, the base date, the target quarter, the coefficient applied to each element and where it was published, printed on the face of the document rather than kept in a working file on somebody's machine.",
      whyKey: "cases.price_a_base_year_smeta_with_the_minstroy_index.step.report.why",
      whyDefault:
        "The customer, the expertise reviewer and the auditor all check the same thing first: which coefficient was used and for which period. A smeta that carries that on its face is checked in minutes, one that does not comes back as a request for clarification and costs a full review cycle.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
