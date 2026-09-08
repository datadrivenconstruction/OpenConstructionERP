// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Calculate with your own rates for the EFB price sheets" (DE).
//
// Build the Mittellohn from a loaded wage and the crew, keep material and plant
// rates as your own master data, compose the recipes that carry them, then
// calculate positions from resources so every unit price opens down to the hours
// and quantities behind it. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "calculate-with-your-own-efb-rates",
  order: 1055,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  region: "DE",
  icon: "Calculator",
  titleKey: "cases.calculate_with_your_own_efb_rates.title",
  titleDefault: "Calculate with your own rates for the EFB price sheets",
  descKey: "cases.calculate_with_your_own_efb_rates.desc",
  descDefault:
    "Build the Mittellohn, keep your own material and plant rates, compose the recipes that carry them and calculate every position from resources, so each unit price opens down to the hours and quantities behind it.",
  longDescKey: "cases.calculate_with_your_own_efb_rates.longdesc",
  longDescDefault:
    "A price carried in your head loses a tender twice: too high and someone else gets the job, too low and you win a loss you carry for months. A calculation built from your own Mittellohn, your own material and plant rates and written recipes gives a figure you can defend line by line, which is what the EFB price sheets 221 and 223 ask a bidder to show on a public tender.",
  estMinutes: 13,
  steps: [
    {
      id: "oncosts",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.in.agreement", label: "Wage agreement" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.in.wage", label: "Base wage per grade" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.out.loaded", label: "Loaded hourly cost" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.out.burden", label: "Labour burden in percent" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.title",
      titleDefault: "Load the wage with its social costs",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.what",
      whatDefault:
        "Enter the agreed base hourly wage for a grade, then add what the employer carries on top of it: social insurance, holiday and public holiday pay, continued pay when someone is sick, pension, the training levy, and the site allowances and travel money this job pays.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.oncosts.why",
      whyDefault:
        "The bare wage is not what an hour costs you, and the gap is regularly a third or more. Every labour line in the tender is understated by whatever you leave out here, and the error only shows up once the job is running.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "mittellohn",
      icon: "Users",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.in.loaded", label: "Loaded rate per grade" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.in.crew", label: "Crew composition" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.out.mittellohn", label: "Mittellohn per hour" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.out.template", label: "Saved rate template" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.title",
      titleDefault: "Blend the crew into one Mittellohn",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.what",
      whatDefault:
        "List the crew that actually does the work, the foreman, the skilled workers and the labourers, each with a head count and its loaded rate, and let the page blend them into the single average hourly rate the calculation runs on. Save it as a template so the next tender starts from it.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.mittellohn.why",
      whyDefault:
        "Work is priced in crew hours, not in one person's wage. One Mittellohn behind every position keeps the labour figure consistent across the whole bill, and it is the first line a Vergabestelle looks for when it asks for the EFB price sheets.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "resources",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.resources.in.quotes", label: "Supplier quotes" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.resources.in.plant", label: "Owned and hired plant costs" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.resources.out.materials", label: "Priced material resources" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.resources.out.equipment", label: "Priced equipment resources" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.resources.title",
      titleDefault: "Keep material and plant rates as your own master data",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.resources.what",
      whatDefault:
        "Put your own resources into the catalog next to the imported reference ones: material prices from the quotes your suppliers actually gave you, and an hourly cost for each machine you own or hire, each with its unit and its price.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.resources.why",
      whyDefault:
        "Your own prices are what separates a calculation from a guess, because they are the prices you will really pay. When steel or diesel moves you correct one rate, and every recipe and position standing on it moves with it instead of being retyped line by line.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "assembly",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.assembly.in.mittellohn", label: "Mittellohn per hour" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.assembly.in.rates", label: "Material and equipment rates" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.assembly.in.output", label: "Hours per unit" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.assembly.out.assembly", label: "Assembly with component lines" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.assembly.out.rate", label: "Composite unit rate" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.assembly.title",
      titleDefault: "Compose the recipe for one unit of work",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.assembly.what",
      whatDefault:
        "Build an assembly for one unit of finished work, say a square metre of wall formwork: the crew hours per unit at the Mittellohn, the material with its waste allowance, and the machine hours the work needs. The component lines add up to the rate.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.assembly.why",
      whyDefault:
        "The recipe is where your own output figures meet your own prices. Written down once it prices the same work the same way on every tender, and it is what lets you explain a rate a year later instead of defending a number nobody can reconstruct.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "positions",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.positions.in.positions", label: "Bill positions and quantities" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.positions.in.assemblies", label: "Assemblies" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.positions.out.priced", label: "Priced positions" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.positions.out.split", label: "Resource lines per position" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.positions.title",
      titleDefault: "Calculate the positions from the recipes",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.positions.what",
      whatDefault:
        "Open the bill for this project and price its positions from the assemblies rather than typing a rate into the cell. Each position then carries its own labour, material and plant lines, and the grid can show that split beside the unit price.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.positions.why",
      whyDefault:
        "A unit price assembled from resources survives a question. When the client asks how you got to the figure you open the position and show the hours and the quantities, instead of promising to look into it and hoping the answer is close.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "nav.boq",
      to: "/projects/:projectId/boq",
    },
    {
      id: "zuschlaege",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.in.ekt", label: "Einzelkosten der Teilleistungen" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.in.overheads", label: "Site and company overheads" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.out.markups", label: "Zuschlaege on record" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.out.prices", label: "Angebotspreise per position" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.title",
      titleDefault: "Put the Zuschlaege on top of the Einzelkosten",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.what",
      whatDefault:
        "Open the markups panel in the bill and load the DACH template, then set the Baustellengemeinkosten, the Allgemeine Geschaeftskosten and Wagnis und Gewinn as percentages on the Einzelkosten der Teilleistungen, each against the cost element it belongs to. The bill recalculates the Angebotspreis of every position from the same figures, which is what Formblatt 221 asks you to declare.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.zuschlaege.why",
      whyDefault:
        "The Einzelkosten are the cost of doing the work and nothing else. A bidder who forgets the site and company overheads has offered to run the site for free, and one who spreads them by hand across a few hundred positions cannot show the Vergabestelle a Zuschlagssatz that reconciles with the prices. Formblatt 221 exists precisely to make those percentages checkable.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "nav.boq",
      to: "/projects/:projectId/boq",
    },
    {
      id: "breakdown",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.in.priced", label: "Priced positions" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.in.lines", label: "Resource lines" },
      ],
      outputs: [
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.out.statement", label: "Labour, material and plant statement" },
        { labelKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.out.figures", label: "Figures for the EFB price sheets" },
      ],
      titleKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.title",
      titleDefault: "Open the price down to its resources",
      whatKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.what",
      whatDefault:
        "Read the resource statement for the whole estimate: the total labour hours and their cost, and the quantity and cost of every material, machine and subcontract line behind the offer. Export it when you need the figures outside the platform.",
      whyKey: "cases.calculate_with_your_own_efb_rates.step.breakdown.why",
      whyDefault:
        "This is the breakdown the EFB price sheets 221 and 223 expect a bidder to file with a public tender. Because it is read straight off the priced positions, producing it is a look and an export rather than a weekend spent rebuilding the calculation in a spreadsheet.",
      moduleLabel: "Resource Summary",
      moduleLabelKey: "nav.resource_summary",
      to: "/resource-summary",
    },
  ],
};

export default playbook;
