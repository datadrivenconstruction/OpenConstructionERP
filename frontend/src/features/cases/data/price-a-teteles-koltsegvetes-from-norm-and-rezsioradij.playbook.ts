// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a teteles koltsegvetes from norm and rezsioradij" (HU).
//
// The Hungarian itemised bill built the way a Hungarian client reads it. A
// tetel is not one number: it carries a norm behind it, an anyag side and a
// dij side, and the dij is norm hours times a rezsioradij that has to be
// stated rather than assumed. Priced this way the bill answers the question a
// muszaki ellenor and a public client both ask, which is not "how much" but
// "out of what". Content strings are key plus inline English default and live
// only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-teteles-koltsegvetes-from-norm-and-rezsioradij",
  order: 1242,
  region: "HU",
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Calculator",
  titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.title",
  titleDefault: "Price a teteles koltsegvetes from norm and rezsioradij",
  descKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.desc",
  descDefault:
    "Build the Hungarian itemised bill the way it is read: a norm behind every tetel, the anyag and the dij shown apart, the dij built from norm hours and a stated rezsioradij, and a foosszesito by munkanem the client can check line by line.",
  longDescKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.longdesc",
  longDescDefault:
    "A Hungarian koltsegvetes is a document with a shape, not a spreadsheet with a total. Each tetel names the work, the unit and the quantity, and carries a unit price split into anyag and dij. Behind the dij sits a norm, the labour time the work is allowed per unit, and a rezsioradij, the all-in hourly rate that has to cover wage, contributions, small plant, site running costs and company overhead. Priced this way the bill answers the only question anybody asks about a price they did not expect, which is what it is made of. Priced as one number per line it answers nothing, and every conversation about a variation, an extra or a disproportionately low price starts from zero.",
  estMinutes: 13,
  steps: [
    {
      id: "kiiras",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.in.kiiras", label: "Arazatlan koltsegvetesi kiiras" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.in.drawings", label: "Drawings and specification" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.out.bill", label: "Tetel list by munkanem" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.out.gaps", label: "Missing tetel flagged" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.title",
      titleDefault: "Take in the tetel list and group it by munkanem",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.what",
      whatDefault:
        "Bring the tetel list in as the bill you will price, keeping the numbering, the unit and the quantity as issued, and group it by munkanem so each trade section can be totalled and read on its own. Flag the work the drawings show and the list does not, rather than silently pricing it inside a neighbouring tetel.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.kiiras.why",
      whyDefault:
        "Government Decree 191/2009 (IX. 15.), the Epkiv., requires the kivitelezesi szerzodes to be in writing and lists what it carries, the unpriced itemised bill among them. So this list is not working material, it is the annex the contract will be measured against for the whole job. Work you absorb into another line now is work you cannot bill separately later, and a tetel you add without saying so reads as a different offer from everyone else's.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "norms",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.in.tetel", label: "Tetel and its unit" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.in.method", label: "Method and site conditions" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.out.hours", label: "Norm hours per unit" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.out.materials", label: "Material consumption per unit" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.title",
      titleDefault: "Put a norm behind every tetel",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.what",
      whatDefault:
        "For each tetel record the labour time and the material consumption per unit that the price assumes, and name where that norm came from: a published norm collection with its edition year, or your own measured output from a comparable job. Adjust it for the conditions this site imposes rather than editing the rate at the end to make the total look right.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.norms.why",
      whyDefault:
        "A norm with a name and a year can be argued with. A rate that arrived from nowhere can only be believed or disbelieved. That difference decides how a variation is settled, how a claim for extra work is read, and whether a justification for a low price is accepted, and it costs nothing to record while you are already looking at the tetel.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "rezsi",
      icon: "Coins",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.in.wages", label: "Wages and contributions" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.in.overhead", label: "Site and company overhead" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.out.rate", label: "Rezsioradij for the job" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.out.buildup", label: "Rate build-up on record" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.title",
      titleDefault: "Build the rezsioradij you will actually use",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.what",
      whatDefault:
        "Build the hourly rate from its parts: gross wage, the employer contributions on it, paid non-working time, small plant and hand tools, site running costs and the share of company overhead the job carries. Keep the build-up attached to the rate so anyone can see which of those parts is doing the work.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.rezsi.why",
      whyDefault:
        "The rezsioradij is the single number that decides whether a Hungarian bid is profitable, and it is the number most often taken from last year without being rebuilt. A recommended industry figure is published annually and a public client will hold yours against it, so a rate far below it needs an explanation you have written down and a rate far above it needs one too.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "tetel",
      icon: "Layers",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.in.norm", label: "Norm hours and materials" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.in.rate", label: "Rezsioradij and material prices" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.out.anyag", label: "Anyag side of the unit price" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.out.dij", label: "Dij side of the unit price" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.title",
      titleDefault: "Assemble each tetel as anyag plus dij",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.what",
      whatDefault:
        "Build the unit price as an assembly rather than typing it. The dij is the norm hours multiplied by the rezsioradij, the anyag is the consumption multiplied by the material price including waste and delivery, and hired plant sits on its own line rather than being smeared through the hourly rate.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.tetel.why",
      whyDefault:
        "Hungarian bills are read with the anyag and the dij apart, and the two move for different reasons: material prices move with the market and the dij moves with wages and productivity. A single blended number hides which one moved, which is exactly what you need to show when a client asks why a rate has changed since last year.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "markups",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.in.direct", label: "Direct cost per tetel" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.in.policy", label: "Markup policy" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.out.applied", label: "Markups applied" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.out.offer", label: "Offer price per tetel" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.title",
      titleDefault: "Add the markups where they can be seen",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.what",
      whatDefault:
        "Apply the markups as their own layer over the direct cost, so the direct cost stays readable underneath. Decide once whether overhead already sits inside the rezsioradij or on top of the tetel, and apply that decision everywhere rather than per section.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.markups.why",
      whyDefault:
        "Overhead counted twice, once inside the hourly rate and once as a percentage on the total, is the commonest quiet error in an itemised bill and it is invisible in the total. Keeping the layer separate makes it a thing you can look at, and it also makes a discount a decision about margin rather than an unexplained edit to a unit rate.",
      moduleLabel: "Markups",
      moduleLabelKey: "nav.markups",
      to: "/markups",
    },
    {
      id: "check",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.in.priced", label: "Priced koltsegvetes" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.in.kiiras", label: "Original kiiras" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.out.fixed", label: "Findings cleared" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.title",
      titleDefault: "Check the bill against the list you were given",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.what",
      whatDefault:
        "Run validation over the priced bill: nothing left at zero, no unit or quantity drifted from the kiiras, no tetel priced far outside the band its neighbours sit in, and every rate carrying the norm and the rate basis it claims.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.check.why",
      whyDefault:
        "An outlier is not automatically wrong, and that is the point of looking: half of them are a decimal place and half of them are the one tetel on the job where your method genuinely differs. You want to know which is which before the client tells you, because only one of the two is worth defending.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "report",
      icon: "FileSpreadsheet",
      inputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.in.bill", label: "Validated priced bill" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.in.structure", label: "Munkanem structure" },
      ],
      outputs: [
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.out.foosszesito", label: "Foosszesito by munkanem" },
        { labelKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.out.export", label: "Koltsegvetes for the client" },
      ],
      titleKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.title",
      titleDefault: "Issue the koltsegvetes with its foosszesito",
      whatKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.what",
      whatDefault:
        "Produce the document rather than the spreadsheet: the tetel detail under each munkanem, the anyag and dij columns kept apart, a summary per munkanem and a foosszesito that carries the sections up to the offer total.",
      whyKey: "cases.price_a_teteles_koltsegvetes_from_norm_and_rezsioradij.step.report.why",
      whyDefault:
        "The foosszesito is how a Hungarian client reads a price, and a bill delivered without one gets retyped into that shape by somebody who was not there when it was priced. Issuing it in the expected form is the difference between a price that gets discussed and a price that gets rebuilt.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
