// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Sell off plan under Wafi and draw from the escrow account" (SA).
//
// Selling a unit before it is built is licensed work in Saudi Arabia. The
// buyers' money goes into a project escrow account and comes out against
// certified progress, which makes the drawdown a measurement problem before it
// is a banking one. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "sell-off-plan-under-wafi-and-draw-from-the-escrow-account",
  order: 1198,
  category: "commercial",
  companyTypes: ["developer-client", "cost-consultant", "project-manager", "general-contractor"],
  roles: ["quantity-surveyor", "finance-manager", "commercial-manager", "project-manager"],
  region: "SA",
  icon: "Landmark",
  titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.title",
  titleDefault: "Sell off plan under Wafi and draw from the escrow account",
  descKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.desc",
  descDefault:
    "Licence the project before a single unit is marketed, put the cost plan the drawdown will be measured against on record, route every buyer payment into the escrow account, draw against certified progress rather than against need, report to the regulator on its schedule and close the account only when the units are handed over.",
  longDescKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.longdesc",
  longDescDefault:
    "The off-plan sales and rental regime, run under the Wafi programme by the real estate regulator, exists because a buyer paying for a unit that does not yet exist is lending the developer money with no security. So the money is not the developer's until the work is done: it goes into a dedicated escrow account held by an accredited bank, it cannot be used for another project or reached by another creditor, and it is released in steps against progress that an appointed engineering consultant has certified and the escrow agent has checked. For the cost consultant that turns the monthly valuation from an internal document into the instrument the project's cash flow runs on, because an uncertified month is a month with no money in it.",
  estMinutes: 15,
  steps: [
    {
      id: "licence",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.in.deed", label: "Land title" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.in.permits", label: "Approved design and permit" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.out.licence", label: "Off-plan licence" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.out.parties", label: "Licensed parties on record" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.title",
      titleDefault: "Licence the project before you market a single unit",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.what",
      whatDefault:
        "Register the development and apply for the off-plan licence with everything the programme asks for: clear title to the land, the approved design and the building permit, an appointed contractor and engineering consultant who both hold current classification, the technical and financial study, and the escrow arrangement with an accredited bank. Record the licence number and its validity against the project.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.licence.why",
      whyDefault:
        "Marketing or taking a deposit before the licence is issued is unlicensed selling, not an early start, and it is the one irregularity a buyer can point at years later to unwind their contract. The licence conditions also fix who certifies progress for the rest of the project, so the appointments made here decide who signs the drawdown every month.",
      moduleLabel: "Property Development",
      moduleLabelKey: "nav.property_dev",
      to: "/property-dev",
    },
    {
      id: "budget",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.in.design", label: "Approved design" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.in.contract", label: "Construction contract" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.out.plan", label: "Cost plan by element" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.out.curve", label: "Expenditure curve" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.title",
      titleDefault: "Put the cost plan the drawdown is measured against on record",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.what",
      whatDefault:
        "Build the project cost plan the escrow will be drawn against: construction by element, consultancy, authority and utility charges, marketing and the finance cost, each with the month it is expected to fall in. Keep the construction section reconciled to the contract sum so a certified percentage of work maps onto a figure without a second calculation.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.budget.why",
      whyDefault:
        "The escrow releases against progress on a budget it already holds, so a cost plan that does not match the contract turns every drawdown into a reconciliation exercise with the bank. The expenditure curve is also the thing that tells you, months in advance, whether sales are running ahead of construction or behind it, which is the question the whole regime exists to answer.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "escrow",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.in.sales", label: "Signed unit contracts" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.in.account", label: "Escrow account" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.out.ledger", label: "Escrow ledger" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.out.received", label: "Buyer payments received" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.title",
      titleDefault: "Route every buyer payment into the escrow account",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.what",
      whatDefault:
        "Sell only against the licensed unit schedule, and take every instalment into the project escrow account rather than into a company account, including the reservation amount. Keep the ledger by unit and by buyer so the balance held can be read against the units sold at any moment, and keep the developer's own contribution as its own line.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.escrow.why",
      whyDefault:
        "The account is dedicated to this project by law, which is what protects a buyer from the developer's other troubles, and money that passed through a company account first has left that protection whatever happens next. A ledger kept by unit is also the only way to answer a cancellation quickly, because a refund is calculated on what that buyer actually paid in.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "progress",
      icon: "Gauge",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.in.works", label: "Work done on site" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.in.plan", label: "Cost plan by element" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.out.percent", label: "Certified completion percentage" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.out.report", label: "Consultant progress report" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.title",
      titleDefault: "Measure the period and have the consultant certify it",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.what",
      whatDefault:
        "Measure what was actually built in the period against the cost plan, element by element, and have the appointed engineering consultant certify the completion percentage in a progress report with photographs and the measured backup behind it. Show the period movement and the cumulative figure separately.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.progress.why",
      whyDefault:
        "The percentage in that report is the only number that moves money out of the account, so a report written from a site walk rather than from measurement is a cash flow forecast built on an opinion. Showing the movement apart from the cumulative figure is what lets the bank check the month in minutes instead of recalculating the whole project.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "drawdown",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.in.report", label: "Consultant progress report" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.in.invoices", label: "Contractor invoices" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.out.release", label: "Released amount" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.out.balance", label: "Balance still held" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.title",
      titleDefault: "Draw against certified progress, never against need",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.what",
      whatDefault:
        "Lodge the release request with the certified percentage, the contractor's invoice for the same period and the supporting measurement, and take out only what that certification supports. Record what was released, what remains held and the portion the regime keeps back until the units are handed over.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.drawdown.why",
      whyDefault:
        "The escrow agent is checking the request against the certificate, not against the developer's payment run, so a request that runs ahead of the certified work is refused and delays the money that was actually earned along with it. Reading the held balance every month is also the earliest warning that sales money is being consumed faster than the building is rising.",
      moduleLabel: "Payments",
      moduleLabelKey: "finance.payments",
      to: "/projects/:projectId/finance?tab=payments",
    },
    {
      id: "report",
      icon: "Send",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.in.percent", label: "Certified completion percentage" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.in.ledger", label: "Escrow ledger" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.out.filed", label: "Report filed" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.out.standing", label: "Licence kept in good standing" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.title",
      titleDefault: "Report to the regulator on the schedule the licence sets",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.what",
      whatDefault:
        "File the periodic report the licence requires: physical progress against the programme, units sold, amounts received and released, and any change to the appointed contractor or consultant. Keep each filing with the period it covers and put the next date under a reminder.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.report.why",
      whyDefault:
        "The licence is a continuing permission rather than a one-off approval, and the reporting is how it stays alive. A development that stops reporting is a development the regulator will look at, and the sanction that hurts is a suspension of further sales, which stops the inflow while the construction obligations carry on unchanged.",
      moduleLabel: "Authority Submissions",
      moduleLabelKey: "authority_submission.title",
      to: "/projects/:projectId/authority-submissions",
    },
    {
      id: "handover",
      icon: "KeyRound",
      inputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.in.completion", label: "Completion certificate" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.in.balance", label: "Balance still held" },
      ],
      outputs: [
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.out.units", label: "Units handed over" },
        { labelKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.out.closed", label: "Escrow account closed" },
      ],
      titleKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.title",
      titleDefault: "Hand the units over, then close the account",
      whatKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.what",
      whatDefault:
        "Take the completion and occupancy documents, clear the snag list per unit, hand over against a signed record for each buyer and register the title in their name. Only then release the retained balance and ask the escrow agent to close the account, with the final statement kept in the project file.",
      whyKey: "cases.sell_off_plan_under_wafi_and_draw_from_the_escrow_account.step.handover.why",
      whyDefault:
        "The held-back portion is the buyers' last piece of leverage and the developer's last incentive to finish properly, so releasing it before the handovers are documented removes both at once. A closing statement that reconciles every riyal received against every riyal released is also what answers a complaint about this project three years from now, when nobody involved is still at the company.",
      moduleLabel: "Handover & Closeout",
      moduleLabelKey: "closeout.title",
      to: "/closeout",
    },
  ],
};

export default playbook;
