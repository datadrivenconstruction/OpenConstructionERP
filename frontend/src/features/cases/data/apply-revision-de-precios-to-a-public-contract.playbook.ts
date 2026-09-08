// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Apply revision de precios to a public works contract" (ES).
//
// Revision de precios on Spanish public work is not automatic and it is not a
// negotiation: it applies only where the contract provided for it, only after
// the periods the law fixes, and only through the polynomial formula the
// contract names, whose index values are published rather than agreed.
//
// The product carries a cost index as a series of period factors plus regional
// location factors, and applies temporal times location as one multiplier. It
// does NOT compute the polynomial split by material family. The case therefore
// walks the user through recording the resulting coefficient per period and
// applying it, and says plainly that the formula arithmetic happens outside.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "apply-revision-de-precios-to-a-public-contract",
  order: 1146,
  region: "ES",
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client"],
  roles: ["commercial-manager", "quantity-surveyor", "estimator"],
  icon: "TrendingUp",
  titleKey: "cases.apply_revision_de_precios_to_a_public_contract.title",
  titleDefault: "Apply revision de precios to a public works contract",
  descKey: "cases.apply_revision_de_precios_to_a_public_contract.desc",
  descDefault:
    "Establish first whether the contract allows revision at all, record the published coefficient for each period as a series, apply it as its own line on the certificacion, and keep the index values you used where an auditor can find them.",
  longDescKey: "cases.apply_revision_de_precios_to_a_public_contract.longdesc",
  longDescDefault:
    "Revision de precios is the mechanism that lets a long public contract survive a change in the price of steel or fuel, and it is narrower than most people assume. It applies only where the contract expressly provided for it, only to work executed after the qualifying period, and only through the formula the contract names, using index values that are published rather than negotiated. What the platform holds is the result: a cost index series of one factor per period, optional regional location factors, and the arithmetic that applies them to an amount. The polynomial split by material family, with the fixed coefficients of the formula, is computed outside and what you enter here is the coefficient it produced for that month. Written down that way, the revision on a certificacion is a number anybody can reproduce from the same published sources, which is the only kind of revision that survives an audit.",
  estMinutes: 16,
  steps: [
    {
      id: "entitlement",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.in.contract",
          label: "Contract and tender terms",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.in.dates",
          label: "Key contract dates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.out.confirmed",
          label: "Entitlement confirmed or ruled out",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.out.formula",
          label: "Formula and base period recorded",
        },
      ],
      titleKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.title",
      titleDefault: "Find out whether revision applies at all",
      whatKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.what",
      whatDefault:
        "Read the contract for three things: whether revision was provided for in the pliego, which of the formulas of Real Decreto 1359/2011 it names, and from which date it bites. Under article 103 LCSP the revision cannot start before two years have passed since formalisation and twenty percent of the price has been executed, and it reaches only the work after that point. Record all three against the contract rather than in a spreadsheet on somebody's machine.",
      whyKey: "cases.apply_revision_de_precios_to_a_public_contract.step.entitlement.why",
      whyDefault:
        "Most of the effort spent on revision de precios is spent on contracts that never carried the entitlement, and the answer takes ten minutes to establish at the start of the job instead of at the first month you want to claim. The base period matters as much as the formula: the same published indices give a different answer from a different base.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "series",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.in.published",
          label: "Published index values",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.in.formula",
          label: "Contract formula and base period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.out.series",
          label: "Cost index series by period",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.out.factor",
          label: "Coefficient for each period",
        },
      ],
      titleKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.title",
      titleDefault: "Record the coefficient for each period",
      whatKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.what",
      whatDefault:
        "Create a series for this contract's formula and add one point per month: the period and the coefficient that formula produced for it. The polynomial split across steel, energy, cement and the rest is worked out from the published indices outside the platform, and the coefficient is what you record here.",
      whyKey: "cases.apply_revision_de_precios_to_a_public_contract.step.series.why",
      whyDefault:
        "Keeping the coefficients as a dated series means the revision on month nine can still be reproduced in year three, when the person who calculated it has left and the published tables have been reissued. A number that exists only inside one certificacion is a number nobody can defend twice.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "apply",
      icon: "Coins",
      inputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.in.certified",
          label: "Certified amount for the period",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.in.factor",
          label: "Coefficient for that period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.out.line",
          label: "Revision as its own invoice line",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.out.rates",
          label: "Contract rates left untouched",
        },
      ],
      titleKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.title",
      titleDefault: "Put the revision on its own line",
      whatKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.what",
      whatDefault:
        "Apply the coefficient to the amount certified in that period and carry the result as a separate line, alongside the certificacion rather than inside it. The contract rates in the bill stay exactly as awarded.",
      whyKey: "cases.apply_revision_de_precios_to_a_public_contract.step.apply.why",
      whyDefault:
        "Revision folded into the unit rates destroys the only comparison anybody has: certified against contract. It also compounds silently, because the following month is revised against rates that were already revised, and nobody discovers it until the final account will not reconcile.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "evidence",
      icon: "Paperclip",
      inputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.in.published",
          label: "Published index tables",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.in.working",
          label: "Formula working for the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.out.filed",
          label: "Filed evidence document",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.out.reproducible",
          label: "A reproducible calculation on record",
        },
      ],
      titleKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.title",
      titleDefault: "File the indices you actually used",
      whatKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.what",
      whatDefault:
        "Attach the published tables for the periods you used and the working that turned them into the coefficient, filed against the project and dated. One page per period is enough as long as the numbers on it are the ones you applied.",
      whyKey: "cases.apply_revision_de_precios_to_a_public_contract.step.evidence.why",
      whyDefault:
        "Published indices get revised after publication, so an audit two years later can look up the same month and get a different figure. The version you used, filed on the day you used it, is the difference between a defensible calculation and a disputed one.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "track",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.in.lines",
          label: "Revision lines to date",
        },
      ],
      outputs: [
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.out.report",
          label: "Report of revision to date",
        },
        {
          labelKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.out.forecast",
          label: "Forecast of the rest",
        },
      ],
      titleKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.title",
      titleDefault: "Track what revision is worth across the job",
      whatKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.what",
      whatDefault:
        "Report the revision recognised to date against the certified value, and carry the coefficient trend forward over the work still to come so the forecast reflects it.",
      whyKey: "cases.apply_revision_de_precios_to_a_public_contract.step.track.why",
      whyDefault:
        "Revision is usually treated as a windfall that turns up in the accounts, which means it is never in the forecast and never in the cash plan. On a three-year contract it is a material share of the turnover, and a job that is not counting on it is also not noticing when a month has been missed.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
