// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a LOPSRM tender and integrate the precios unitarios" (MX).
//
// Hand written, not composed. Federal public works in Mexico are let under
// the Ley de Obras Publicas y Servicios Relacionados con las Mismas, and the
// thing that distinguishes a Mexican bid from a priced bill anywhere else is
// that the unit price is not a number, it is an integration whose order the
// reglamento fixes: costo directo, then indirectos, then financiamiento,
// then utilidad, then cargos adicionales, with IVA applied to the total and
// never folded into the price.
//
// The product carries that order as the built-in "mexico" methodology
// template (slug mexico, currency MXN) with the cascade steps in it, and the
// engine ships four Mexican validation rules: mexico.apu_completeness,
// mexico.iva_rate_valid, mexico.subcontract_retencion and
// mexico.cfdi_issuer_data. What it does not do is submit the bid: the
// federal contracting platform the LOPSRM names is outside, and the case
// says so rather than implying an upload button.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-lopsrm-tender-and-integrate-the-precios-unitarios",
  order: 1263,
  region: "MX",
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager"],
  icon: "Gavel",
  titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.title",
  titleDefault: "Price a LOPSRM tender and integrate the precios unitarios",
  descKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.desc",
  descDefault:
    "Read the convocatoria, load the catalogo de conceptos as issued, build the basic costs behind the analisis de precios unitarios, cascade indirectos, financiamiento, utilidad and cargos adicionales in the order the reglamento fixes, and check the proposal against the Mexican rule set before it leaves the office.",
  longDescKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.longdesc",
  longDescDefault:
    "A LOPSRM bid is refused for arithmetic far more often than it is lost on price. The propuesta economica is not a priced list, it is a set of analisis de precios unitarios that the convocante takes apart: the costo directo split into materiales, mano de obra and maquinaria, then indirectos on the costo directo, then financiamiento on what those two make, then utilidad on the accumulated cost, then cargos adicionales on the lot, of which the cinco al millar inspection fee is the usual content. IVA sits on the total and never inside the unit price. Every percentage in that cascade has to be supported by the analysis behind it, so a utilidad typed in as a round number with nothing under it is an incomplete proposal even when the total is competitive. Integrated once in the right order, the same structure feeds the estimaciones, the conceptos extraordinarios and the ajuste de costos for the rest of the contract.",
  estMinutes: 25,
  steps: [
    {
      id: "convocatoria",
      icon: "FileSearch",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.in.notice",
          label: "Convocatoria and bases de licitacion",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.in.dates",
          label: "Junta de aclaraciones and closing dates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.out.decision",
          label: "Bid or no bid, with a reason",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.out.requirements",
          label: "Document list the propuesta must carry",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.title",
      titleDefault: "Read the convocatoria before you price anything",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.what",
      whatDefault:
        "Register the opportunity with the four things that decide whether it is worth pricing: the contract type the LOPSRM allows and the convocatoria chose, precios unitarios, precio alzado or mixto; the anticipo offered; whether the contract provides for ajuste de costos; and the full list of documents the propuesta tecnica and the propuesta economica have to carry. Put the junta de aclaraciones and the closing in the calendar the day you register it.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.convocatoria.why",
      whyDefault:
        "The contract type changes the whole shape of the work: on precios unitarios the quantities move and the rates do not, on precio alzado nothing moves and the risk of the quantity is yours. Firms that price first and read the bases afterwards discover this on a job they have already won, which is the most expensive order to discover it in.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "catalogo",
      icon: "ListTree",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.in.issued",
          label: "Catalogo de conceptos as issued",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.in.specs",
          label: "Especificaciones and drawings",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.out.loaded",
          label: "Catalogo loaded line for line",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.out.queries",
          label: "Queries for the junta de aclaraciones",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.title",
      titleDefault: "Load the catalogo exactly as it was issued",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.what",
      whatDefault:
        "Bring the catalogo de conceptos in with its claves, units and quantities untouched, and read each concepto against the especificacion that describes it. Where the description and the specification disagree, or a unit cannot carry the work described, that is a question for the junta de aclaraciones and not a decision for the estimator.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.catalogo.why",
      whyDefault:
        "The catalogo is the contract's spine for years: estimaciones, extraordinarios and the finiquito all read against it. A clave changed at tender to make the spreadsheet tidier is a mismatch that shows up in every future estimacion, and a question not asked at the junta becomes a risk you priced without knowing you had.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "labour",
      icon: "Users",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.in.wages",
          label: "Salarios base by category",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.in.charges",
          label: "Statutory charges on employment",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.out.real",
          label: "Salario real per category",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.out.basis",
          label: "The factor written down and dated",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.title",
      titleDefault: "Build the mano de obra on a salario real, not a wage",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.what",
      whatDefault:
        "Set one rate per labour category and build it from the salario base plus the factor de salario real: the days actually worked in a year against the days paid, and the statutory employer charges on top, IMSS contributions and the housing fund contributions among them. Keep the factor and the year it was computed for beside the rate.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.labour.why",
      whyDefault:
        "The gap between a daily wage and a salario real is not a rounding difference, it is the whole margin on a labour heavy concepto. It also has to be defensible: the convocante can ask how the factor was arrived at, and a rate carried forward from a job three years ago answers that question with a number nobody can reconstruct.",
      moduleLabel: "Labor Rates",
      moduleLabelKey: "nav.labor_rates",
      to: "/labor-rates",
    },
    {
      id: "insumos",
      icon: "Boxes",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.in.quotes",
          label: "Supplier quotations",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.in.plant",
          label: "Machinery, its hours and its costs",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.out.materials",
          label: "Materiales priced at the site",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.out.hourly",
          label: "Costo horario per machine",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.title",
      titleDefault: "Price the materiales at site and the maquinaria by the hour",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.what",
      whatDefault:
        "Hold the materiales at the cost of getting them onto the site, not at the yard price, and build each machine as a costo horario: ownership, depreciation, the money tied up in it, maintenance, fuel and the operator. Herramienta menor rides as its own charge on the labour rather than as a guess inside every concepto.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.insumos.why",
      whyDefault:
        "The costo horario is the piece the convocante takes apart hardest, because it is where a proposal can be made to look cheap without changing anything visible. Built once from real ownership and running costs, it also survives the machine moving to the next job, which a rate invented for one tender never does.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "apu",
      icon: "Layers",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.in.basics",
          label: "Labour, materials and machinery costs",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.in.norms",
          label: "Output per crew and per machine",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.out.direct",
          label: "Costo directo per concepto",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.out.apu",
          label: "Analisis a reviewer can take apart",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.title",
      titleDefault: "Compose the costo directo of each concepto",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.what",
      whatDefault:
        "Build each concepto as an analisis: the quantity of each material per unit of work, the crew and the hours it takes, the machines and their hours. That sum is the costo directo, and it is the only part of the price that is composed rather than applied as a percentage.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.apu.why",
      whyDefault:
        "The mexico.apu_completeness rule in the validation engine exists because an incomplete analisis is the most common defect in a Mexican proposal and the easiest one to miss in your own work: a concepto with materials and no labour reads perfectly well until somebody asks who places it. Composed properly, the same analisis prices the extraordinarios later without being rebuilt.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "cascade",
      icon: "Percent",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.in.direct",
          label: "Costo directo across the catalogo",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.in.overhead",
          label: "Office and site overhead, and the cash curve",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.out.unit",
          label: "Precio unitario integrated in order",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.out.support",
          label: "Analysis behind each percentage",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.title",
      titleDefault: "Cascade indirectos, financiamiento, utilidad and cargos adicionales",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.what",
      whatDefault:
        "Apply the four charges in the order the reglamento of the LOPSRM fixes and on the base each one is applied to: indirectos on the costo directo, covering oficinas centrales and oficinas de campo; financiamiento on the costo directo plus indirectos, from the gap between spending the money and being paid it; utilidad on the accumulated cost; cargos adicionales on the lot, which on a federal contract is where the cinco al millar inspection fee sits. Keep IVA off the unit price entirely.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.cascade.why",
      whyDefault:
        "The order is not a convention, it is what the integration means, and applying utilidad to the costo directo alone or folding the cinco al millar into indirectos produces a different total from the one the convocante will compute. Each percentage also has to be supported: the financiamiento comes from a cash flow against the programme, so it moves when the anticipo or the payment period moves, and a figure typed straight in cannot answer why.",
      moduleLabel: "Markups",
      moduleLabelKey: "nav.markups",
      to: "/markups",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.in.priced",
          label: "Fully priced catalogo",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.in.fiscal",
          label: "Issuer fiscal data",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.out.findings",
          label: "Findings against the Mexican rule set",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.out.fixed",
          label: "Gaps closed before submission",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.title",
      titleDefault: "Run the Mexican rule set before the proposal leaves",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.what",
      whatDefault:
        "Validate the priced catalogo against the mexico rule set: the APU completeness check on every concepto, the IVA rate check that will only accept sixteen, eight or zero, the retencion flag on subcontracted lines, and the CFDI issuer data the invoicing will need the moment the job is won. Fix the findings rather than filing them.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.validate.why",
      whyDefault:
        "A public proposal is discarded for a missing piece far more readily than it is discounted for a high price, and the pieces that go missing are the boring ones, an analisis with no labour line or an issuer field nobody filled in. Ten minutes against a rule set beats finding out at the apertura de proposiciones, where there is nothing to be done.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "assemble",
      icon: "PackageCheck",
      inputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.in.checked",
          label: "Checked catalogo and analisis",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.in.docs",
          label: "Company, tax and programme documents",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.out.package",
          label: "Propuesta tecnica and economica assembled",
        },
        {
          labelKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.out.record",
          label: "What was submitted, kept as issued",
        },
      ],
      titleKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.title",
      titleDefault: "Assemble the propuesta and keep what you sent",
      whatKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.what",
      whatDefault:
        "Put the two proposals together against the document list from the first step: the propuesta tecnica with the programmes of work, personnel and machinery, and the propuesta economica with the catalogo, the analisis, the basic costs and the explosion of insumos. Submission itself happens on the federal contracting platform the LOPSRM names, outside this product, so keep the exact package you uploaded here beside the tender record.",
      whyKey: "cases.price_a_lopsrm_tender_and_integrate_the_precios_unitarios.step.assemble.why",
      whyDefault:
        "What you submitted becomes the contract, and the version on somebody's laptop is not evidence of it. A year later, when an estimacion is queried or an extraordinario is priced, the argument is settled by the analisis that went in with the bid, and the firm that can produce it in a minute is negotiating from a different position from the one still looking for it.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
  ],
};

export default playbook;
