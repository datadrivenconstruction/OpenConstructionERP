// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Claim ajuste de costos on a public works contract" (MX).
//
// Hand written, not composed. Ajuste de costos on a LOPSRM contract is a
// statutory mechanism, not a goodwill gesture: article 56 opens it when
// circumstances of an economic order arising after the presentation and
// opening of proposals move the direct costs of work still to be executed,
// article 57 lists the procedures and the contract picks one of them, and
// article 58 fixes how the adjustment is computed and what it may touch.
//
// What the platform holds and what it does not, stated the same way the
// Spanish revision de precios case states it. The cost index module carries
// a series of period factors plus location factors and applies them to an
// amount. It does NOT compute the grupo de precios arithmetic, and it does
// not hold the published INPP tables. Those are worked out against the
// INEGI publication outside, and what is recorded here is the factor that
// work produced for the month, so the claim can be reproduced years later
// by somebody who was not in the room.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "claim-ajuste-de-costos-on-a-public-works-contract",
  order: 1264,
  region: "MX",
  category: "commercial",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client"],
  roles: ["commercial-manager", "quantity-surveyor", "contract-administrator"],
  icon: "TrendingUp",
  titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.title",
  titleDefault: "Claim ajuste de costos on a public works contract",
  descKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.desc",
  descDefault:
    "Establish which procedure the contract chose, record the factor each period produced from the published indices, work out which work the adjustment actually reaches, apply it to the costos directos as its own line, and file the solicitud before the sixty natural days run out.",
  longDescKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.longdesc",
  longDescDefault:
    "Ajuste de costos is what keeps a multi year public contract from being destroyed by the price of steel or diesel, and it is lost far more often to a calendar than to an argument. Article 56 LOPSRM opens the right when economic circumstances arising after the presentation and opening of proposals move the direct costs of work not yet executed. Article 57 sets out the procedures and the contract names one of them, so the method is chosen at signature and not at the moment of claiming. Article 58 then fixes the two things people get wrong: the adjustment runs from the month the movement in the cost of the insumos happened, over the work pending execution according to the agreed programme, and it moves the costos directos while the percentages of indirectos and utilidad stay as they were tendered. And it has a deadline. The contractor has sixty natural days from the publication of the applicable indices for the month to present the solicitud, and once that passes the right lapses, whatever the merits. The dependencia has its own sixty days to resolve, and silence is treated as agreement.",
  estMinutes: 20,
  steps: [
    {
      id: "entitlement",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.in.contract",
          label: "Contract and bases de licitacion",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.in.programme",
          label: "Programme as agreed",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.out.procedure",
          label: "Article 57 procedure the contract chose",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.out.base",
          label: "Base month recorded",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.title",
      titleDefault: "Find out which procedure the contract actually chose",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.what",
      whatDefault:
        "Read the contract for three things and record them against it: that ajuste de costos was provided for at all, which of the procedures of article 57 LOPSRM it names, and the base month the adjustment runs from, which is fixed by the presentation and opening of proposals rather than by the day work started. Note that the unamortised anticipo is outside the adjustment, because the money for it was already in your hands.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.entitlement.why",
      whyDefault:
        "The procedure is chosen at signature and cannot be swapped later for the one that gives a better answer, which is exactly what a firm tries to do the first month it wants to claim. Establishing it at the start costs an hour and settles every claim for the life of the contract, and the base month settles more than the procedure does: the same published indices give a different result from a different base.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "series",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.in.indices",
          label: "Published INPP values for the month",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.in.groups",
          label: "Grupos de precios and their weights",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.out.series",
          label: "Index series, one point per period",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.out.factor",
          label: "Factor for each month",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.title",
      titleDefault: "Record the factor each month produced",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.what",
      whatDefault:
        "Create a series for this contract and add one point per month: the period and the factor the chosen procedure produced for it, against the producer price indices for public works inputs that INEGI publishes. The arithmetic across the grupos de precios, with the relative weight of each insumo, is done outside the platform. What lives here is the factor it produced and the month it belongs to.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.series.why",
      whyDefault:
        "Published indices are revised after publication, so an audit two years later can look the same month up and get a different number. A dated series of the factors you actually applied, kept beside the contract, is the difference between a calculation that can be defended twice and one that can only be defended by the person who did it, who by then works somewhere else.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "scope",
      icon: "CalendarDays",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.in.programme",
          label: "Agreed programme against actual progress",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.in.month",
          label: "Month the cost movement happened",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.out.eligible",
          label: "Work the adjustment reaches",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.out.excluded",
          label: "Work excluded, with the reason",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.title",
      titleDefault: "Work out which work the adjustment reaches",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.what",
      whatDefault:
        "Take the programme and mark, month by month, the work that was still pending execution when the cost movement happened. Article 58 LOPSRM computes the adjustment from that month over work pending according to the agreed programme, so where the works are behind for a reason that is your own, the eligible quantity is the one the original programme said would still be outstanding, not the one that actually was.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.scope.why",
      whyDefault:
        "This is the sentence that decides most ajuste disputes, and it cuts both ways. A contractor running late cannot enlarge a claim by being later; a contractor running early is not punished for it. Working the eligible quantity out from the programme, in writing, at the time, is what turns the claim into a check rather than a negotiation.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "apply",
      icon: "Coins",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.in.eligible",
          label: "Eligible amount for the period",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.in.factor",
          label: "Factor for that period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.out.line",
          label: "Ajuste as its own line",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.out.rates",
          label: "Contract precios unitarios untouched",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.title",
      titleDefault: "Put the ajuste on its own line, on the costos directos",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.what",
      whatDefault:
        "Apply the factor to the eligible amount and carry the result as a separate line beside the estimacion, never inside it. The precios unitarios of the contract stay exactly as awarded, the adjustment moves the costos directos, and the percentages of indirectos and utilidad stay as they were tendered.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.apply.why",
      whyDefault:
        "An adjustment folded into the unit rates destroys the one comparison anybody has, which is what was certified against what was contracted, and it compounds without anybody deciding to: next month is adjusted against rates that were already adjusted. It surfaces at the finiquito, when the paid total will not reconcile to the catalogo and nobody can say which month the drift started in.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "solicitud",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.in.working",
          label: "Factor, eligible work and the arithmetic",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.in.publication",
          label: "Date the indices were published",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.out.filed",
          label: "Solicitud filed and dated",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.out.clock",
          label: "The dependencia's own period running",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.title",
      titleDefault: "File the solicitud before the sixty days run out",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.what",
      whatDefault:
        "Present the solicitud de ajuste de costos in writing with the studies and documentation behind it, and record the date the indices for that month were published as well as the date you filed. The count is sixty natural days from the publication, and natural means it does not stretch for weekends or holidays.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.solicitud.why",
      whyDefault:
        "When that period passes the contractor loses the possibility of asking, and a right that has lapsed is not recovered by being obviously correct. This is the single most expensive deadline on a Mexican public contract precisely because nothing happens on the day it passes: no letter arrives, no meeting is called, and the loss is only discovered when somebody finally gets round to preparing the claim.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "track",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.in.claims",
          label: "Ajuste recognised to date",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.in.remaining",
          label: "Work still to come",
        },
      ],
      outputs: [
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.out.report",
          label: "Report of ajuste against certified value",
        },
        {
          labelKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.out.forecast",
          label: "Forecast carrying the trend forward",
        },
      ],
      titleKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.title",
      titleDefault: "Track what the adjustment is worth across the job",
      whatKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.what",
      whatDefault:
        "Report the ajuste recognised so far against the value certified, and carry the trend of the factors over the work still to come so the forecast and the cash plan carry it too. Check every month that a solicitud was filed for the month before, because that is the check nobody runs.",
      whyKey: "cases.claim_ajuste_de_costos_on_a_public_works_contract.step.track.why",
      whyDefault:
        "Ajuste is usually treated as a windfall that turns up in the accounts, which means it is never in the forecast and nobody notices when a month is missed. On a three year contract it is a material share of turnover, and one skipped month is not visible in any total until the job is over.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
