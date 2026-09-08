// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a smeta on the GESN norms with the resource method" (RU).
//
// Pick the norm collection the contract names, expand each norm into the labour,
// machine and material consumption it fixes, price those resources at today's
// money, and post the result as a lokalnaya smeta whose every rate opens down to
// the norm behind it. Content strings are key plus inline English default and
// live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-smeta-on-the-gesn-norms-with-the-resource-method",
  order: 1301,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant", "developer-client"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  region: "RU",
  icon: "Calculator",
  titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.title",
  titleDefault: "Build a smeta on the GESN norms with the resource method",
  descKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.desc",
  descDefault:
    "Take the norm collection the contract names, expand every norm into its labour, machine and material consumption, price those resources at current money and post them as a lokalnaya smeta, so each rate opens down to the norm it came from.",
  longDescKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.longdesc",
  longDescDefault:
    "Russian estimating has three methods and they are not interchangeable. The base index method takes a price fixed in a base year and multiplies it by a published index. The resource method prices the physical consumption the state norm fixes at what the resources cost today. The resource index method, the federal method since the 2022 edition of the norm base, takes current prices from the state price system where it publishes them and indexes the rest. Whichever of the three the contract names, the line that survives a challenge is the one built from resources, because the norm number, the resource quantity and the price source all stay visible on it, and that is the line the reviewer traces.",
  estMinutes: 14,
  steps: [
    {
      id: "base",
      icon: "Database",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.in.contract", label: "Contract or technical assignment" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.in.region", label: "Region of the works" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.out.collection", label: "Selected norm collection" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.out.edition", label: "Edition on record" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.title",
      titleDefault: "Pick the norm collection the job is priced on",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.what",
      whatDefault:
        "Open the cost database and choose the collection the job is actually priced on: GESN when you will price the resources yourself, FER when a federal unit rate governs, TER when the region has approved its own territorial rates. Record the edition alongside it, because a norm number is only unique inside its edition.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.base.why",
      whyDefault:
        "GESN and FER are two readings of the same federal norm base, published together as FSNB, while TER are the territorial equivalents a region approves for its own territory. GESN carries physical consumption and no prices, FER and TER carry rates already priced in base year money. Starting on the wrong one is not a rounding error: it decides whether the resource method is open to you at all, and whether state expertise will accept the result.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "expand",
      icon: "ListTree",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.in.norm", label: "Norm number" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.in.technical", label: "Technical part of the collection" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.out.resources", label: "Resource list per unit" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.out.clause", label: "Clause behind any adjustment" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.title",
      titleDefault: "Expand each norm into the resources it fixes",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.what",
      whatDefault:
        "Open the norm and read what it contains: man hours by trade grade, machine hours by machine type, and the material quantity per unit of measure. Adjust a quantity only where the technical part of the collection allows it, and write down the clause you relied on next to the change.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.expand.why",
      whyDefault:
        "The consumption inside a GESN norm is the state's statement of what the work takes, and it is the half of the price nobody is free to invent. A resource quantity moved without the technical part behind it is the first thing an expertise reviewer writes up, because it can be spotted without recalculating anything.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "price",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.in.quotes", label: "Supplier quotes" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.in.wage", label: "Regional wage per grade" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.out.priced", label: "Priced resource catalogue" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.out.source", label: "Source and date per price" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.title",
      titleDefault: "Price the resources at current money",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.what",
      whatDefault:
        "Give every resource a price: the hourly wage for the grade in this region, the machine hour rate with the operator in it, and the material price from your own quotes delivered to site rather than ex works. Keep the source and the date on each price.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.price.why",
      whyDefault:
        "This is the step that makes the method resource based rather than index based. A price without a named source cannot be defended when the customer asks where the figure came from, and a price without a date cannot be re-based when the job runs into the following year.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "recipes",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.in.norms", label: "Norms that recur" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.in.priced", label: "Priced resources" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.out.assembly", label: "Saved assembly" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.out.unit", label: "Assembly unit rate" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.title",
      titleDefault: "Compose the work you repeat into assemblies",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.what",
      whatDefault:
        "Where the same combination of norms and resources comes back section after section, save it once as an assembly with its own unit of measure, so the next section and the next project start from it instead of from the norm list again.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.recipes.why",
      whyDefault:
        "A smeta of several thousand positions cannot be kept consistent line by line, and inconsistency between two identical items in different sections is exactly what a reviewer picks up. An assembly also carries the reasoning with it, which is what lets a second estimator take over your file without rebuilding it.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "positions",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.in.takeoff", label: "Quantities from the takeoff" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.in.rates", label: "Resource-built rates" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.out.smeta", label: "Lokalnaya smeta" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.out.sections", label: "Sections matching the drawings" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.title",
      titleDefault: "Post the positions into the lokalnaya smeta",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.what",
      whatDefault:
        "Enter each priced position with its quantity from the takeoff, grouped into sections the way the working drawings divide the work, and keep the norm number, the unit of measure and the resource-built rate on every line.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.positions.why",
      whyDefault:
        "The lokalnaya smeta is the document every summary above it is built from: object smetas sum the locals and the svodnyy smetnyy raschet sums the objects. A wrong quantity or a wrong norm number here is wrong in every summary above it, and the summaries are what the customer actually reads.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "markups",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.in.trade", label: "Type of work per section" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.in.payroll", label: "Labour cost per position" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.out.nr", label: "NR applied by trade" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.out.sp", label: "SP applied by trade" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.title",
      titleDefault: "Apply NR and SP on the base each is calculated from",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.what",
      whatDefault:
        "In the bill's Markups & Overheads panel, apply the Russian template to bring in the national stack in its order, overheads (NR), estimated profit (SP), the reserve line and NDS, then set the NR and SP rate for each type of work from the norms rather than leaving one rate on the whole bill. Read what each line is applied to: the shipped template carries NR and SP as an effective percentage of direct cost, because a bill markup can take direct cost or the running total as its base and payroll is neither.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.markups.why",
      whyDefault:
        "The norm sets NR and SP against payroll, worker wages plus machine operator wages, and by type of work, not against the position total. An effective percentage of direct cost keeps the bill total right for a typical work mix and wrong in its sensitivity, so on a bill whose labour share is far from typical rebuild the markup on the resource decomposition rather than trusting the line. Applying either to material or equipment cost inflates the smeta in a way a reviewer finds by arithmetic alone.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "resources",
      icon: "Boxes",
      inputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.in.smeta", label: "Completed smeta" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.in.nomenclature", label: "Material nomenclature" },
      ],
      outputs: [
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.out.hours", label: "Man hours and machine hours" },
        { labelKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.out.materials", label: "Material quantities by nomenclature" },
      ],
      titleKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.title",
      titleDefault: "Read the resource summary the method produces",
      whatKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.what",
      whatDefault:
        "Open the summary the smeta rolls up to: total man hours, machine hours by machine type and material quantities by nomenclature across the whole estimate, and read it against what the job plausibly needs in crews, plant and deliveries.",
      whyKey: "cases.build_a_smeta_on_the_gesn_norms_with_the_resource_method.step.resources.why",
      whyDefault:
        "The output of the resource method is not only a total in roubles. The same summary is what the works schedule, the crew plan and the material procurement are built from, and it is the norm baseline that the M-29 material reconciliation will later compare actual consumption against.",
      moduleLabel: "Resource Summary",
      moduleLabelKey: "nav.resource_summary",
      to: "/resource-summary",
    },
  ],
};

export default playbook;
