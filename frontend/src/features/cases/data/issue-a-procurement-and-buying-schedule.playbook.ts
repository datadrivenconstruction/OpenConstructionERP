// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Issue a procurement and buying schedule".
//
// Turn the BOQ and the programme into a live buying list: name the packages
// to buy, set the lead times and need-by dates by working back from the
// programme, price or tender each one, and track order status so nothing is
// bought too late. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "issue-a-procurement-and-buying-schedule",
  order: 265,
  category: "tendering",
  companyTypes: ["general-contractor", "project-manager"],
  roles: ["procurement-buyer", "commercial-manager"],
  icon: "CalendarClock",
  titleKey: "cases.issue_a_procurement_and_buying_schedule.title",
  titleDefault: "Issue a procurement and buying schedule",
  descKey: "cases.issue_a_procurement_and_buying_schedule.desc",
  descDefault:
    "Turn the BOQ and the programme into a buying schedule: list the packages to buy, set lead times and need-by dates back from the programme, tender or price each package, and track every order so nothing is bought too late.",
  estMinutes: 11,
  steps: [
    {
      id: "packages",
      icon: "Boxes",
      inputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.packages.in.boq",
          label: "Priced BOQ",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.packages.in.trades",
          label: "Trade breakdown",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.packages.out.packages",
          label: "Buying packages",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.packages.out.quantities",
          label: "Package quantities",
        },
      ],
      titleKey:
        "cases.issue_a_procurement_and_buying_schedule.step.packages.title",
      titleDefault: "Break the BOQ into buying packages",
      whatKey:
        "cases.issue_a_procurement_and_buying_schedule.step.packages.what",
      whatDefault:
        "Group the priced BOQ into the packages you will actually buy, one per trade or supply item, so each line of the buying schedule maps to a real order rather than a loose collection of positions.",
      whyKey: "cases.issue_a_procurement_and_buying_schedule.step.packages.why",
      whyDefault:
        "A buying schedule built straight off the BOQ carries the right quantities and value from the start, so nothing quietly falls between two packages and gets bought by nobody.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "leadtimes",
      icon: "CalendarClock",
      inputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.in.packages",
          label: "Buying packages",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.in.programme",
          label: "Programme dates",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.out.leadtimes",
          label: "Lead times",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.out.orderby",
          label: "Latest order dates",
        },
      ],
      titleKey:
        "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.title",
      titleDefault: "Set lead times and need-by dates",
      whatKey:
        "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.what",
      whatDefault:
        "For each package set the manufacture and delivery lead time, then work back from the programme date the material is needed on site to fix the latest date the order must be placed.",
      whyKey:
        "cases.issue_a_procurement_and_buying_schedule.step.leadtimes.why",
      whyDefault:
        "Most late materials are not bought late by accident, they are bought on time against the wrong date. Working back from the programme is what turns a wish list into a schedule with real deadlines.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "tender",
      icon: "Send",
      inputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.tender.in.packages",
          label: "Buying packages",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.tender.in.dates",
          label: "Latest order dates",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.tender.out.quotes",
          label: "Supplier quotes",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.tender.out.price",
          label: "Firm price & supplier",
        },
      ],
      titleKey:
        "cases.issue_a_procurement_and_buying_schedule.step.tender.title",
      titleDefault: "Tender or price each package",
      whatKey: "cases.issue_a_procurement_and_buying_schedule.step.tender.what",
      whatDefault:
        "Send the packages with the earliest order dates out to enquiry first, gather quotes, and settle a firm price and supplier for each one so the buying schedule carries a committed number, not a guess.",
      whyKey: "cases.issue_a_procurement_and_buying_schedule.step.tender.why",
      whyDefault:
        "Pricing in order of urgency means the long-lead packages are settled while there is still time to negotiate, instead of being rushed at any price the week they are needed.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "order",
      icon: "ClipboardList",
      inputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.order.in.price",
          label: "Agreed price & supplier",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.order.in.dates",
          label: "Need-by dates",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.order.out.order",
          label: "Purchase order raised",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.order.out.committed",
          label: "Committed cost",
        },
      ],
      titleKey:
        "cases.issue_a_procurement_and_buying_schedule.step.order.title",
      titleDefault: "Place orders and appoint suppliers",
      whatKey: "cases.issue_a_procurement_and_buying_schedule.step.order.what",
      whatDefault:
        "Award each package to its chosen supplier or subcontractor and raise the order, so the committed cost is booked and the delivery is locked against the need-by date on the schedule.",
      whyKey: "cases.issue_a_procurement_and_buying_schedule.step.order.why",
      whyDefault:
        "A price agreed but not ordered is not a delivery. Placing the order is the point the supplier is bound to the date, and the point your committed cost becomes real and trackable.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "track",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.track.in.orders",
          label: "Placed orders",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.track.in.schedule",
          label: "Buying schedule",
        },
      ],
      outputs: [
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.track.out.status",
          label: "Live order status",
        },
        {
          labelKey:
            "cases.issue_a_procurement_and_buying_schedule.step.track.out.flags",
          label: "Slipping-date flags",
        },
      ],
      titleKey:
        "cases.issue_a_procurement_and_buying_schedule.step.track.title",
      titleDefault: "Track order status against the dates",
      whatKey: "cases.issue_a_procurement_and_buying_schedule.step.track.what",
      whatDefault:
        "Read the buying schedule as a live report: which packages are still to enquire, out to price, ordered or delivered, and flag any order whose latest date is closing in before it is placed.",
      whyKey: "cases.issue_a_procurement_and_buying_schedule.step.track.why",
      whyDefault:
        "A buying schedule only protects the programme if someone watches it every week. Catching a slipping order date early is what keeps a late package from stopping a trade on site.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
