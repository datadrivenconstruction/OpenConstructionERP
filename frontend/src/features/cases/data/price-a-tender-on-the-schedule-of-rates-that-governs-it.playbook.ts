// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a tender on the schedule of rates that governs it" (IN).
//
// An Indian estimate is written against a published schedule of rates, and
// which schedule depends on who is paying. CPWD publishes the Delhi Schedule
// of Rates for central government work; every state PWD publishes its own for
// state work. They are not interchangeable. The item numbering differs, the
// specifications differ, and a rate lifted from the wrong schedule is not an
// approximation, it is the wrong number.
//
// So the first act of pricing here is not pricing. It is establishing which
// document the contract is written against, loading that one as data, and then
// holding every priced line to an item reference out of it. The India pack
// ships exactly that rule, cpwd.code_required: a priced line with no schedule
// item behind it is a number the client cannot check.
//
// No commercial rate schedule is bundled with the product, and this case does
// not pretend otherwise. The schedule comes in through the ordinary import
// surface, from the department's own copy or from the firm's cost history.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-tender-on-the-schedule-of-rates-that-governs-it",
  order: 1180,
  region: "IN",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "developer-client", "project-manager"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "BookOpen",
  titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.title",
  titleDefault: "Price a tender on the schedule of rates that governs it",
  descKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.desc",
  descDefault:
    "Establish which schedule of rates the contract is written against, load that one as a cost base, price the bill from it, and prove every line carries the schedule item it came from before the estimate leaves your desk.",
  longDescKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.longdesc",
  longDescDefault:
    "Central government work is priced on the CPWD Delhi Schedule of Rates. State work is priced on the state PWD schedule, and there are as many of those as there are states. The two look similar enough to be confused and are different enough that confusing them is expensive: the item numbering does not line up, the specification behind an item is not the same specification, and the price level is set for a different market. A department checking your bill checks it item by item against its own schedule, so a rate that came from somewhere else has nothing to be checked against and is queried on principle. This case puts the schedule question first, before any number is entered, then makes the answer visible in the estimate itself rather than remembered by the person who built it.",
  estMinutes: 22,
  steps: [
    {
      id: "schedule",
      icon: "FileSearch",
      inputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.in.docs",
          label: "Tender documents",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.in.client",
          label: "Who is paying for the work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.out.named",
          label: "The governing schedule, named",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.out.year",
          label: "Its edition and price level",
        },
      ],
      titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.title",
      titleDefault: "Settle which schedule the contract is written against",
      whatKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.what",
      whatDefault:
        "Read the tender conditions and record, against the contract, which schedule of rates governs it, which edition, and what price level it is stated at. Central government work names CPWD DSR; state work names the state PWD schedule; a private client may name neither and leave you on market rates.",
      whyKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.schedule.why",
      whyDefault:
        "This is the one decision every later number depends on, and it is the one most often taken by assumption. Writing it down where the contract lives means the next person to open the estimate can see which document it was built from, instead of inferring it from the shape of the rates.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "base",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.in.copy",
          label: "Your copy of the schedule",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.out.loaded",
          label: "Cost base loaded and searchable",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.out.currency",
          label: "Priced in INR",
        },
      ],
      titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.title",
      titleDefault: "Load that schedule as a cost base, not as a column you typed",
      whatKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.what",
      whatDefault:
        "Bring the schedule into the cost database through the ordinary import surface and check it landed with its item numbers, descriptions, units and rates intact. No commercial schedule ships with the product, so this is your own copy or your own cost history, loaded once and reused.",
      whyKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.base.why",
      whyDefault:
        "A schedule loaded as data can be searched, versioned and re-priced next year. A schedule transcribed into a spreadsheet column becomes a set of numbers with no provenance the moment the person who typed them moves on, and every query about a rate turns into an archaeology exercise.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "price",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.in.bill",
          label: "The tender bill of quantities",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.in.base",
          label: "The loaded schedule",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.out.priced",
          label: "A priced bill",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.out.refs",
          label: "Schedule item on every line",
        },
      ],
      titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.title",
      titleDefault: "Price the bill and carry the item reference with the rate",
      whatKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.what",
      whatDefault:
        "Work down the bill sub-head by sub-head, from earthwork to external services, pulling each rate off the loaded schedule and keeping its item number on the line. Where no schedule item fits, price it as a non-schedule item and say so on the line rather than bending a neighbouring item to cover it.",
      whyKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.price.why",
      whyDefault:
        "Non-schedule items are normal and are checked differently, by rate analysis rather than by lookup. Marking them at the point of pricing is what lets the department check the rest quickly and concentrate on the few that need argument, instead of treating the whole bill as unverified.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.in.priced",
          label: "The priced bill",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.out.missing",
          label: "Lines with no item reference",
        },
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.out.clean",
          label: "A bill that passes before it is sent",
        },
      ],
      titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.title",
      titleDefault: "Run the check that finds a rate with nothing behind it",
      whatKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.what",
      whatDefault:
        "Validate the priced bill and read the findings. The India pack ships a rule that asks every priced line for its schedule item reference, so the lines you meant to mark as non-schedule and the lines you simply forgot both come back in one list.",
      whyKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.check.why",
      whyDefault:
        "The difference between a deliberate non-schedule item and a forgotten reference is invisible in a printed bill and obvious in a validation run. Finding it here costs a few minutes; finding it after the tender is opened costs a technical query you answer under a clock.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "basis",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.basis.in.decisions",
          label: "What you assumed and why",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.basis.out.basis",
          label: "A written basis of estimate",
        },
      ],
      titleKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.basis.title",
      titleDefault: "Write down the basis while you still remember it",
      whatKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.basis.what",
      whatDefault:
        "Record the schedule and edition used, the price level and base date, the lead and lift assumptions, which items are non-schedule and how they were analysed, and what the estimate excludes.",
      whyKey: "cases.price_a_tender_on_the_schedule_of_rates_that_governs_it.step.basis.why",
      whyDefault:
        "An estimate on a public job is read months later by somebody who was not in the room, often during a query about a single item. The basis is what turns that from a defence of your memory into a reading of the file.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
  ],
};

export default playbook;
