// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a composicao de custo unitario propria" (BR).
//
// The composicao is the unit of argument in a Brazilian orcamento: insumos at
// stated coeficientes, composicoes auxiliares underneath, and a unit cost that
// is a total rather than an opinion. Decreto 7.983/2013 allows a composicao
// propria where the reference systems carry nothing, and it is allowed exactly
// as far as it is justified, which is why the source of every coefficient is
// part of the deliverable. Content strings are key plus inline English default
// and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-composicao-de-custo-unitario-propria",
  order: 1502,
  region: "BR",
  category: "estimating",
  companyTypes: ["cost-consultant", "general-contractor", "subcontractor"],
  roles: ["estimator", "quantity-surveyor"],
  icon: "Layers",
  titleKey: "cases.build_a_composicao_de_custo_unitario_propria.title",
  titleDefault: "Build a composicao de custo unitario propria",
  descKey: "cases.build_a_composicao_de_custo_unitario_propria.desc",
  descDefault:
    "Price the insumos once, set the coeficientes you can defend, build the composicoes auxiliares underneath, compose the servico from them and let the unit cost be calculated rather than typed, with the source of every coefficient on the record.",
  longDescKey: "cases.build_a_composicao_de_custo_unitario_propria.longdesc",
  longDescDefault:
    "A composicao propria is written for the item the reference base does not carry, and the moment it exists it becomes the thing an auditor reads instead of a SINAPI code. That changes what makes it good. A composicao whose arithmetic is right and whose productivity came from nowhere is worth less than one that is slightly conservative and says which job, which crew and which measured period produced the coefficient. So this case builds the composicao in the same object twice, an auxiliar for what is made on site and a servico above it, and treats the justification as part of the deliverable rather than as paperwork somebody assembles later from memory.",
  estMinutes: 20,
  steps: [
    {
      id: "insumos",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.in.quotes",
          label: "Supplier quotes and labour costs",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.in.units",
          label: "Units of measure",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.out.rates",
          label: "Priced insumo rates",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.out.typed",
          label: "Labour, material and plant separated",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.title",
      titleDefault: "Price the insumos once",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.what",
      whatDefault:
        "Put the mao de obra, the materiais and the equipamentos into the catalog as priced insumos, each in the unit it is bought or paid in and each typed as labour, material or plant. An hour of pedreiro, a tonne of cimento, a productive hour of retroescavadeira.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.insumos.why",
      whyDefault:
        "Every composicao you write will lean on the same few dozen insumos. Priced once, a change in the steel price moves every composicao that contains steel in a single edit. Priced inside each composicao, the same change is a search through four hundred lines and some of them will be missed.",
      moduleLabel: "Resource Catalog",
      moduleLabelKey: "catalog.title",
      to: "/catalog",
    },
    {
      id: "produtividade",
      icon: "Gauge",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.in.records",
          label: "Site records of work done",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.in.published",
          label: "Published productivity rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.out.norms",
          label: "Coeficientes per unit of work",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.out.source",
          label: "Source recorded per coefficient",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.title",
      titleDefault: "Set the coeficientes you can defend",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.what",
      whatDefault:
        "Decide how much of each insumo one unit of the servico consumes, and take the figure from a measured period on a real job wherever you have one. Where you do not, take it from a published productivity study and say which. Keep the loss and reuse factors separate from the productivity itself.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.produtividade.why",
      whyDefault:
        "The coefficient is what the disagreement is actually about, and it is the only part of the composicao that a reader can test against their own experience. Written down with its source it becomes a conversation about how the work is done. Left implicit inside a unit cost, the same disagreement arrives as an accusation that the price is inflated, and there is nothing to point at.",
      moduleLabel: "Production Norms",
      moduleLabelKey: "nav.norm_expansion",
      to: "/norm-expansion",
    },
    {
      id: "auxiliar",
      icon: "FlaskConical",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.in.rates",
          label: "Priced insumo rates",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.in.recipe",
          label: "Mix quantities per unit",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.out.aux",
          label: "Composicao auxiliar with a calculated rate",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.out.reuse",
          label: "One rate shared by every user",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.title",
      titleDefault: "Build the composicoes auxiliares first",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.what",
      whatDefault:
        "Anything produced on site before it goes into the work is an auxiliar: the argamassa, the concreto feito em obra, the forma you assemble and use several times. Build each as its own assembly, in its own unit, from the insumos you have just priced.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.auxiliar.why",
      whyDefault:
        "The argamassa turns up in the alvenaria, the reboco and the piso, and it is one mix. Modelled once as an auxiliar it stays one number in three composicoes. Retyped into each of them it becomes three numbers that drift apart the first time the sand price moves, and nobody can tell which of the three is the stale one.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "compose",
      icon: "Combine",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.in.aux",
          label: "Composicoes auxiliares priced",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.in.norms",
          label: "Coeficientes per unit of work",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.out.assembly",
          label: "Composicao with a built-up rate",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.out.breakdown",
          label: "Readable priced breakdown",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.title",
      titleDefault: "Compose the servico at the stated coeficientes",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.what",
      whatDefault:
        "Build the servico as an assembly in the unit the bill measures it in, and give every component the quantity one unit of work consumes. Keep the equipment split between productive and idle hours where the machine waits on the crew, because the two are paid differently and averaging them hides both.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.compose.why",
      whyDefault:
        "A unit cost that is the total of its components can be checked line by line by somebody who disagrees with only one of them. A unit cost typed in as a single figure has to be accepted or rejected whole, and in public work that means rejected, because there is nothing in it an analyst is able to approve.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "apply",
      icon: "Calculator",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.in.assembly",
          label: "Composicao and its calculated rate",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.in.positions",
          label: "Bill positions to price",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.out.priced",
          label: "Priced bill positions",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.out.linked",
          label: "Rate linked to its breakdown",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.title",
      titleDefault: "Put the calculated cost on the bill",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.what",
      whatDefault:
        "Apply the composicao to its position so the unit cost on the bill is the total of the breakdown rather than a number somebody keyed in. Do the same for the positions that share the recipe and differ only in thickness, diameter or class.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.apply.why",
      whyDefault:
        "A typed cost and its composicao stop agreeing the moment either one changes, and the bill is the copy everybody reads. Linked, the orcamento you submit and the calculation you defend are the same arithmetic, which is the entire reason for writing the composicao in the first place.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "justify",
      icon: "BookOpen",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.in.source",
          label: "Source recorded per coefficient",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.in.gap",
          label: "Reason the base carries no item",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.out.memo",
          label: "Justification report per composicao",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.out.audit",
          label: "Trail an auditor can follow",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.title",
      titleDefault: "Write down why this composicao exists at all",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.what",
      whatDefault:
        "For each composicao propria record two things on the basis of estimate: that the reference systems carry no equivalent item, and where each coefficient and each insumo price came from. Name the job or the study, not the person.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.justify.why",
      whyDefault:
        "Decreto 7.983 of 2013 permits a composicao propria where the reference systems fall short, and the permission is only as strong as the evidence that they do. Without that sentence the composicao reads as a way around the median rather than as an answer to a real gap, and it is the reading, not the arithmetic, that decides the finding.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "keep",
      icon: "Warehouse",
      inputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.in.assemblies",
          label: "Finished composicoes",
        },
      ],
      outputs: [
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.out.database",
          label: "Your own cost database",
        },
        {
          labelKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.out.reuse",
          label: "Rates ready for the next orcamento",
        },
      ],
      titleKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.title",
      titleDefault: "Keep it as your own banco de composicoes",
      whatKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.what",
      whatDefault:
        "Move the composicoes you are happy with into the cost database under codes you can search, with the reference month they were priced in. The next orcamento starts from these instead of from a published base you correct in the same three places every time.",
      whyKey: "cases.build_a_composicao_de_custo_unitario_propria.step.keep.why",
      whyDefault:
        "A published base is a good place to start and a poor place to finish: its coeficientes are regional averages and its prices belong to a month that has passed. The version your own jobs have corrected is worth more than either, and it only accumulates if somebody puts it somewhere other than the last project folder.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
  ],
};

export default playbook;
