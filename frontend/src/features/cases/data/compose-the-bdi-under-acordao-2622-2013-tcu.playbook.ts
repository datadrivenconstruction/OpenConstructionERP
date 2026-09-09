// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Compose the BDI under Acordao 2622/2013-TCU" (BR).
//
// The BDI is not a single percentage anybody negotiates, it is a formula with
// named terms, and Acordao 2622/2013 of the Tribunal de Contas da Uniao is
// what settles which cost belongs in which term. Two of its rulings decide
// most disputes: administracao local belongs in the orcamento as measured
// items rather than inside the BDI, and IRPJ and CSLL are not part of the tax
// term. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "compose-the-bdi-under-acordao-2622-2013-tcu",
  order: 1504,
  region: "BR",
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "subcontractor"],
  roles: ["estimator", "commercial-manager", "quantity-surveyor"],
  icon: "Percent",
  titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.title",
  titleDefault: "Compose the BDI under Acordao 2622/2013-TCU",
  descKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.desc",
  descDefault:
    "Move administracao local out of the BDI and into the orcamento, price risk and guarantees where they belong, set the tax term without the taxes that may not be in it, and publish a demonstrativo that shows every figure against the reference range.",
  longDescKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.longdesc",
  longDescDefault:
    "Almost every argument about a Brazilian BDI is really an argument about which bucket a cost sits in, not about whether it is a real cost. Acordao 2622/2013 of the Tribunal de Contas da Uniao settled the two that come up most. Administracao local, the engineer, the storeman and the site office that exist because this job exists, belong in the orcamento as items that can be measured and paid as the job runs, not inside a percentage applied to work done. And the tax term covers the taxes that fall on the invoice, which does not include corporate income tax, because those follow profit rather than turnover and the contractor would otherwise be paid for them twice. The same decision published reference ranges by type of work, which are not a cap but are the number an analyst compares yours against, so a term outside the range needs a sentence rather than a redraft.",
  estMinutes: 16,
  steps: [
    {
      id: "local",
      icon: "HardHat",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.in.team",
          label: "Site team and site facilities",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.in.duration",
          label: "Contract duration",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.out.items",
          label: "Administracao local as bill items",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.out.removed",
          label: "Same cost out of the BDI",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.title",
      titleDefault: "Take administracao local out of the BDI",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.what",
      whatDefault:
        "Price the site management, the canteiro de obras, the mobilizacao and the desmobilizacao as their own items with a quantity and a duration, and take the same cost out of the percentage. Keep the monthly items monthly, so a job that runs long is paid for the months it actually ran.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.local.why",
      whyDefault:
        "Acordao 2622/2013-TCU holds that administracao local is a direct cost of this job and belongs in the orcamento where it can be measured, not inside a BDI applied to work executed. The practical difference shows up on a job that is delayed for reasons that are not yours: as a measured monthly item the extra months are payable, as a percentage of the same work they are not, because the work did not grow.",
      moduleLabel: "Preliminaries",
      moduleLabelKey: "nav.preliminaries",
      to: "/preliminaries",
    },
    {
      id: "risk",
      icon: "ShieldAlert",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.in.register",
          label: "Risk register for the job",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.in.bonds",
          label: "Insurance and guarantee quotes",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.out.terms",
          label: "Risk, insurance and guarantee rates",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.out.reason",
          label: "Reason recorded per rate",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.title",
      titleDefault: "Price the risco, the seguro and the garantia",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.what",
      whatDefault:
        "Set the three terms separately and take each from something real: the risk term from the register of what could go wrong on this job, the insurance term from a broker's quote for this scope, the guarantee term from what the bank charges you for a performance bond of this size and length.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.risk.why",
      whyDefault:
        "These three are the terms most often copied from the last job, and they are the ones that vary most between jobs. A guarantee priced on a two year contract and reused on a five year one is wrong by a factor the profit term cannot absorb, and it is invisible because the BDI still totals to a number that looks normal.",
      moduleLabel: "Allowances & Contingency",
      moduleLabelKey: "nav.allowances",
      to: "/allowances",
    },
    {
      id: "tributos",
      icon: "Landmark",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.in.regime",
          label: "Tax regime of the company",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.in.city",
          label: "Rate of the city where the work is",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.out.rate",
          label: "Tax term of the BDI rate",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.out.excluded",
          label: "Taxes deliberately left out",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.title",
      titleDefault: "Set the tax term, and only the taxes that belong in it",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.what",
      whatDefault:
        "Build the tax term from the levies that fall on the invoice: the municipal service tax at the rate of the city where the work is done, the federal turnover contributions at the rate your regime charges, and the payroll contribution on turnover where the company has taken that option. Record which taxes you deliberately kept out and why.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.tributos.why",
      whyDefault:
        "Acordao 2622/2013-TCU holds that corporate income tax and the social contribution on net profit do not belong in the BDI, because they are levied on the result rather than on the invoice, and a contractor who includes them is paid for them by the client and again out of margin. Municipal rates also differ from city to city, so a term carried over from the last job is a real error even when the arithmetic is perfect.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "compose",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.in.terms",
          label: "Risk, insurance and guarantee rates",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.in.tax",
          label: "Tax term of the BDI rate",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.out.bdi",
          label: "BDI rate applied to the bill",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.out.price",
          label: "Price with the markup visible",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.title",
      titleDefault: "Assemble the BDI in the markups panel",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.what",
      whatDefault:
        "In the bill's Markups & Overheads panel enter the central office overhead, the risk, the insurance, the guarantee, the finance charge, the profit and the tax term as separate figures, so the BDI is composed rather than typed. Check that the tax term divides rather than multiplies, because it is charged on the price you invoice and not on the cost you carry.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.compose.why",
      whyDefault:
        "A BDI entered as one number cannot be checked, cannot be adjusted term by term when the client questions one of them, and hides the single most common arithmetic error in Brazilian estimating, which is applying the tax term as a simple addition. Composed, the same figure is a short table anybody can follow.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "justify",
      icon: "BookOpen",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.in.bdi",
          label: "BDI rate applied to the bill",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.in.ranges",
          label: "Reference range for this work type",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.out.memo",
          label: "Justification report per term",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.out.flags",
          label: "Terms outside the range named",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.title",
      titleDefault: "Place every term against the reference range",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.what",
      whatDefault:
        "Record on the basis of estimate where each term sits relative to the reference range published for this type of work, and write a sentence for any term that sits outside it. Say what about this job puts it there, in terms of the job rather than of the company.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.justify.why",
      whyDefault:
        "The ranges in Acordao 2622/2013-TCU are the first thing an analyst reaches for, and a term above the range with a written reason is a discussion while the same term without one is a finding. Writing it during the estimate costs a paragraph, writing it afterwards means reconstructing a decision nobody remembers making.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "publish",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.in.memo",
          label: "Justification report per term",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.in.price",
          label: "Price with the markup visible",
        },
      ],
      outputs: [
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.out.sheet",
          label: "BDI demonstrativo for the proposal",
        },
        {
          labelKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.out.one",
          label: "One version everyone quotes",
        },
      ],
      titleKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.title",
      titleDefault: "Publish the demonstrativo with the proposal",
      whatKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.what",
      whatDefault:
        "Export the BDI as its own sheet showing every term and the formula that combines them, and send it with the proposal rather than on request. Where the edital asks for a differentiated BDI for supplied equipment, publish that one beside it instead of averaging the two.",
      whyKey: "cases.compose_the_bdi_under_acordao_2622_2013_tcu.step.publish.why",
      whyDefault:
        "A proposal carrying a bare percentage invites the analyst to reconstruct it, and their reconstruction will not be yours. Published as a sheet, the same figure arrives already explained, and a differentiated BDI for equipment supply is either declared or it is treated as an attempt to earn a construction markup on a purchase.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
