// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Soll-Ist control on a running site" (DE).
//
// Read the Deckungsbeitrag while the site is still running instead of at the
// Schlussrechnung: set the Soll from the calculation, freeze it, book progress
// and actual cost every period, reconcile cost against value and let earned
// value forecast the outturn. Content strings are key plus inline English
// default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "soll-ist-control-on-a-running-site",
  order: 1051,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["commercial-manager", "quantity-surveyor", "project-manager"],
  region: "DE",
  icon: "Gauge",
  titleKey: "cases.soll_ist_control_on_a_running_site.title",
  titleDefault: "Soll-Ist control on a running site",
  descKey: "cases.soll_ist_control_on_a_running_site.desc",
  descDefault:
    "Read the Deckungsbeitrag while the site is still running: set the Soll from the calculation, book progress and actual cost every period, reconcile cost against value and let earned value say where the job lands.",
  longDescKey: "cases.soll_ist_control_on_a_running_site.longdesc",
  longDescDefault:
    "Most jobs show their margin once, at the Schlussrechnung, by which time every decision that could have changed it has already been taken. A monthly Soll-Ist-Vergleich turns the same figures into a steering instrument: the Soll comes from the calculation the job was priced on, the Ist comes from what site actually consumed, and the gap between them is on the table in month three rather than month twelve.",
  estMinutes: 14,
  steps: [
    {
      id: "soll",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.soll.in.boq",
          label: "Priced bill of quantities",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.soll.in.categories",
          label: "Cost categories",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.soll.out.lines",
          label: "Soll budget lines",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.soll.out.bac",
          label: "Budget at completion",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.soll.title",
      titleDefault: "Set the Soll from the calculation",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.soll.what",
      whatDefault:
        "Generate the cost budget from the Auftragskalkulation, the priced bill as awarded, then work down the budget lines category by category so the Soll carries the money your calculation carried, split the way site will actually spend it. Where the Arbeitskalkulation moved money between positions before the start, the Soll follows the Arbeitskalkulation, not the offer.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.soll.why",
      whyDefault:
        "A Soll is only worth comparing against when it comes from the calculation the job was priced on. A budget keyed in from memory turns every later variance into an argument about the budget instead of a decision about the work.",
      moduleLabel: "5D Cost Model",
      moduleLabelKey: "nav.5d_cost_model",
      to: "/5d",
    },
    {
      id: "basis",
      icon: "Flag",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.basis.in.lines",
          label: "Soll budget lines",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.basis.in.bac",
          label: "Budget at completion",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.basis.out.baseline",
          label: "Approved baseline",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.basis.out.frozen",
          label: "Dated Soll",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.basis.title",
      titleDefault: "Freeze the baseline",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.basis.what",
      whatDefault:
        "Create the baseline from that budget with its budget at completion, run the check, and approve it. From here the Soll is fixed and dated, and every later measurement is read against it.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.basis.why",
      whyDefault:
        "A budget nobody froze quietly swallows a Nachtrag, and the margin never moves - which is exactly how a job reads as healthy until the end. A dated, approved Soll makes added scope show up as a change you can see, price and defend.",
      moduleLabel: "Earned Value",
      moduleLabelKey: "nav.full_evm",
      to: "/full-evm",
    },
    {
      id: "leistung",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.in.aufmass",
          label: "Site measurement",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.in.positions",
          label: "Bill positions",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.in.cutoff",
          label: "Period cut-off",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.out.percent",
          label: "Percent complete per position",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.out.quantity",
          label: "Earned quantity",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.leistung.out.variance",
          label: "Quantity variance",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.leistung.title",
      titleDefault: "Record what is built at the cut-off",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.leistung.what",
      whatDefault:
        "On the cut-off date record the percent complete against the bill positions from the site measurement, then read the earned quantity and the quantity variance the entries produce.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.leistung.why",
      whyDefault:
        "Built work is the one figure nobody can invoice their way around. Recording it position by position, on a date everyone holds to, is what keeps the value side of the reconciliation from turning into a feeling.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "meldung",
      icon: "FileSignature",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.meldung.in.progress",
          label: "Recorded progress",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.meldung.in.terms",
          label: "Contract and retention terms",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.meldung.out.claim",
          label: "Leistungsmeldung for the period",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.meldung.out.value",
          label: "Certified value to date",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.meldung.title",
      titleDefault: "Turn the progress into a Leistungsmeldung",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.meldung.what",
      whatDefault:
        "Raise the progress claim for the period and populate it from the progress you just recorded, then walk it from submitted through approved to certified so the period ends with a value both sides stand behind.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.meldung.why",
      whyDefault:
        "The Leistungsmeldung is what turns built work into money you are allowed to count. Filling it from recorded progress rather than from a spreadsheet keeps the value in the reconciliation tied to something that was measured on site.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "ist",
      icon: "Banknote",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.ist.in.invoices",
          label: "Subcontractor and supplier invoices",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.ist.in.site",
          label: "Labour and plant records",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.ist.in.orders",
          label: "Orders placed",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.ist.out.actual",
          label: "Ist cost to date",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.ist.out.obligo",
          label: "Obligo",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.ist.title",
      titleDefault: "Book the Ist and the Obligo",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.ist.what",
      whatDefault:
        "Book the cost that landed in the same period - subcontractor and supplier invoices, labour, plant - and bring in the orders placed but not yet invoiced so the Obligo sits alongside the Ist.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.ist.why",
      whyDefault:
        "Cost you have ordered but not yet been billed for is the part of the overrun that has already happened and cannot be seen yet. Leave it out and the margin looks fine for exactly as long as the post takes to arrive.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "deckungsbeitrag",
      icon: "Scale",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.in.value",
          label: "Certified value to date",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.in.cost",
          label: "Ist cost and Obligo",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.in.soll",
          label: "Soll budget lines",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.out.margin",
          label: "Deckungsbeitrag to date",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.out.forecast",
          label: "Forecast margin",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.out.month",
          label: "Finalised month",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.title",
      titleDefault: "Read the Deckungsbeitrag",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.what",
      whatDefault:
        "Open the month, set the value to date against the cost to date per cost head with the accruals in, and read the margin to date and the forecast margin. Finalise the month once the figures are agreed.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.deckungsbeitrag.why",
      whyDefault:
        "One margin figure tells you there is a problem; a margin per cost head tells you which trade caused it. Finalising the month puts an agreed number on the record, so next month's movement is a comparison rather than a fresh opinion.",
      moduleLabel: "Cost-Value Reconciliation",
      moduleLabelKey: "nav.cvr",
      to: "/projects/:projectId/cvr",
    },
    {
      id: "prognose",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.in.baseline",
          label: "Approved baseline",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.in.measurement",
          label: "Earned value and actual cost",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.in.date",
          label: "Cut-off date",
        },
      ],
      outputs: [
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.out.indices",
          label: "Cost and schedule indices",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.out.outturn",
          label: "Outturn against budget",
        },
        {
          labelKey: "cases.soll_ist_control_on_a_running_site.step.prognose.out.alert",
          label: "Threshold alert",
        },
      ],
      titleKey: "cases.soll_ist_control_on_a_running_site.step.prognose.title",
      titleDefault: "Forecast where the job lands",
      whatKey: "cases.soll_ist_control_on_a_running_site.step.prognose.what",
      whatDefault:
        "Record the measurement for the cut-off - earned value, actual cost, planned value - and work out the forecast. Read the cost and schedule indices, the outturn against budget, and pick up any alert that has tripped its threshold.",
      whyKey: "cases.soll_ist_control_on_a_running_site.step.prognose.why",
      whyDefault:
        "An index under one is a forecast, not a report card: it says where the job ends up if nothing changes. Read in month three that is a plan to fix the trade that is losing. Read at the Schlussrechnung it is only the loss you already took.",
      moduleLabel: "Earned Value",
      moduleLabelKey: "nav.full_evm",
      to: "/full-evm",
    },
  ],
};

export default playbook;
