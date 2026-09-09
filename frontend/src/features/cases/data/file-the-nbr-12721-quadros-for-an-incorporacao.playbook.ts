// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "File the NBR 12721 quadros for an incorporacao" (BR).
//
// Lei 4.591/1964 will not let an incorporador sell an unbuilt unit until the
// memorial de incorporacao is registered, and ABNT NBR 12721 is the standard
// that says how the areas and the cost behind that memorial are calculated and
// which quadros carry them. The cost here is not an estimate for a tender, it
// is a filed statement each buyer is entitled to read. Content strings are key
// plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "file-the-nbr-12721-quadros-for-an-incorporacao",
  order: 1509,
  region: "BR",
  category: "estimating",
  companyTypes: ["developer-client", "cost-consultant", "designer"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager", "design-lead"],
  icon: "Building2",
  titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.title",
  titleDefault: "File the NBR 12721 quadros for an incorporacao",
  descKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.desc",
  descDefault:
    "Measure the areas the standard defines, build the custo global for the building's padrao, place it against the published CUB, produce the quadros, carry the cost onto each unit by its fracao ideal and assemble the memorial for registration.",
  longDescKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.longdesc",
  longDescDefault:
    "This is the one cost calculation a Brazilian developer files with a registry office rather than sends to a client. Lei 4.591 of 1964 bars the sale of units in a building that does not exist yet until the memorial de incorporacao is registered, and ABNT NBR 12721 defines the areas, the standard of finish and the quadros that memorial carries. Two things about it surprise estimators arriving from tender work. The area is not the area a designer quotes, because the standard converts covered, uncovered and common areas into an equivalent area before any cost touches them, so an arithmetic slip lands on every unit at once. And the cost is a public statement rather than a working figure, which means the interesting number is not the total but the gap between it and the published CUB for the same standard, since that gap is what a buyer, a bank or a court will ask you to explain.",
  estMinutes: 20,
  steps: [
    {
      id: "areas",
      icon: "Ruler",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.in.drawings",
          label: "Approved architectural drawings",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.in.units",
          label: "Unit schedule of the building",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.out.real",
          label: "Real areas per unit",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.out.equiv",
          label: "Equivalent area of construction",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.title",
      titleDefault: "Measure the areas the way the standard defines them",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.what",
      whatDefault:
        "Take off the private, the common and the total real area of every unit, then convert them into the equivalent area of construction the way NBR 12721 prescribes, so that covered and uncovered work are weighted rather than added. Keep both sets of figures, because the quadros ask for both.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.areas.why",
      whyDefault:
        "Every figure downstream is a rate multiplied by one of these areas, so an area computed the ordinary way rather than the way NBR 12721 defines it is wrong in the same direction on every unit and in the registered document. Corrections after registration are a rectification at the registry office, not an edit.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "cost",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.in.spec",
          label: "Specification and standard of finish",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.in.equiv",
          label: "Equivalent area of construction",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.out.global",
          label: "Custo global of the building",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.out.rate",
          label: "Cost rate per square metre",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.title",
      titleDefault: "Build the custo global for the padrao you are building",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.what",
      whatDefault:
        "Price the building at the standard of finish it is actually specified to, keeping the structure, the finishes and the services apart, and separate what the standard treats as the building from what it treats as land, licences and marketing. Read out the cost per square metre of equivalent area.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cost.why",
      whyDefault:
        "The rate per square metre is the figure everyone compares, and it only means anything when the numerator and the denominator were built to the same rules. Costs that do not belong to the construction inflate the rate and make the building look expensive against every published reference, which is a conversation with a bank rather than with an estimator.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "cub",
      icon: "LineChart",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.in.rate",
          label: "Cost rate per square metre",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.in.cub",
          label: "Published CUB for the state",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.out.gap",
          label: "Difference against the CUB",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.out.reason",
          label: "Reason recorded for the gap",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.title",
      titleDefault: "Place the rate against the published CUB",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.what",
      whatDefault:
        "Load the CUB published for the state and the building type that matches yours, put your rate beside it, and write down what the difference is made of: the items the CUB expressly leaves out, such as foundations, lifts and external works, and the specification choices that are genuinely yours.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.cub.why",
      whyDefault:
        "The CUB is computed under NBR 12721 for a standard project and deliberately excludes several real costs, so a building priced honestly is expected to sit above it. What has to exist is the sentence saying by how much and why. Without it, the same gap reads to a buyer or an auditor as a padded cost rather than as foundations.",
      moduleLabel: "Price Index",
      moduleLabelKey: "nav.price_index",
      to: "/price-index",
    },
    {
      id: "quadros",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.in.global",
          label: "Custo global of the building",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.in.real",
          label: "Real areas per unit",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.out.quadros",
          label: "Quadros report in the prescribed form",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.out.consistent",
          label: "Totals agreeing across quadros",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.title",
      titleDefault: "Produce the quadros in the form the standard prescribes",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.what",
      whatDefault:
        "Generate the numbered quadros NBR 12721 lays out, from the areas of each unit through to the cost of construction and its distribution, and check that the same total appears identically in every quadro that carries it. Keep the reference month of the cost on every sheet.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.quadros.why",
      whyDefault:
        "The quadros are read by a registrar who checks them against each other rather than against the building, so an internal disagreement between two sheets stops the filing even when both figures are individually defensible. Generated from one source they agree by construction, which is the only reliable way to make a set of twelve tables consistent.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
    {
      id: "units",
      icon: "Building2",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.in.quadros",
          label: "Quadros report in the prescribed form",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.in.fracao",
          label: "Fracao ideal per unit",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.out.perunit",
          label: "Cost carried onto each unit",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.out.pricing",
          label: "Basis for the sale price",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.title",
      titleDefault: "Carry the cost onto each unit by its fracao ideal",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.what",
      whatDefault:
        "Distribute the construction cost across the units in proportion to the fracao ideal recorded for each one, and hold that distribution beside the sale prices so the margin on a small unit can be read separately from the margin on a penthouse.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.units.why",
      whyDefault:
        "A development sold at one price per square metre across every unit is usually selling the ground floor at a loss and does not know it, because the cost per square metre is not flat once parking, terraces and common areas are allocated. The filed distribution is the only version of that arithmetic both the buyer and the developer are looking at.",
      moduleLabel: "Property Development",
      moduleLabelKey: "nav.property_dev",
      to: "/property-dev",
    },
    {
      id: "memorial",
      icon: "FolderInput",
      inputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.in.quadros",
          label: "Quadros report in the prescribed form",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.in.docs",
          label: "Title, licences and drawings",
        },
      ],
      outputs: [
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.out.memorial",
          label: "Memorial assembled for filing",
        },
        {
          labelKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.out.version",
          label: "Filed version kept as issued",
        },
      ],
      titleKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.title",
      titleDefault: "Assemble the memorial de incorporacao for registration",
      whatKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.what",
      whatDefault:
        "Bring the quadros together with the title, the approved drawings, the licences and the technical responsibility notes into the set that goes to the registry office, and keep the filed version untouched afterwards as its own record.",
      whyKey: "cases.file_the_nbr_12721_quadros_for_an_incorporacao.step.memorial.why",
      whyDefault:
        "Lei 4.591 of 1964 makes registration of the memorial the condition of selling units that are not built, so this set is what allows the sales to start, and every buyer contracts against the version that was filed. A working copy that keeps evolving in the same folder is how a later dispute finds two memorials, and only one of them is the one anybody agreed to.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
