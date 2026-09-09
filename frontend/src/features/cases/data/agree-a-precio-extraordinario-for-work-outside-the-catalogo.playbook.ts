// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Agree a precio extraordinario for work outside the catalogo" (MX).
//
// Work that no concepto in the catalogo covers still has to be priced, and the
// reglamento says how: the same basic costs and the same indirect cascade the
// winning proposal was built on, presented and conciliated inside the days it
// counts. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "agree-a-precio-extraordinario-for-work-outside-the-catalogo",
  order: 1269,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "quantity-surveyor", "commercial-manager", "contract-administrator"],
  region: "MX",
  icon: "Calculator",
  titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.title",
  titleDefault: "Agree a precio extraordinario for work outside the catalogo",
  descKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.desc",
  descDefault:
    "Prove the work is not covered by any concepto in the catalogo before you price it, get it instructed in the bitacora, build the analisis from basic costs with the indirectos, financiamiento, utilidad and cargos adicionales of the winning proposal, conciliate it inside the days the reglamento counts and carry the authorised price into the estimacion.",
  longDescKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.longdesc",
  longDescDefault:
    "A public works contract in Mexico is awarded on a catalogo de conceptos with a unit price analysed behind every line, and the moment the site meets work that no line covers, the contract does not become silent. The reglamento sets a procedure: the contractor presents an analysis for the concepto not foreseen, built with the same basic costs and the same indirect cascade as the proposal that won, the dependencia reviews and conciliates it, and the result is formalised so it can be estimated and paid. What goes wrong is almost always the shortcut. Work is started because the residente asked for it verbally, the price is negotiated after it is built, and a concepto with no authorisation and no analysis behind it becomes a number nobody in the audit chain is willing to sign.",
  estMinutes: 15,
  steps: [
    {
      id: "outside",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.in.catalogo", label: "Catalogo de conceptos" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.in.work", label: "Work the site has met" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.out.finding", label: "Finding: no concepto covers it" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.out.scope", label: "Scope of the new concepto" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.title",
      titleDefault: "Prove the work is outside the catalogo before pricing it",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.what",
      whatDefault:
        "Read the new work against the catalogo concepto by concepto and against what each existing unit price already includes in its specification. Write down, in one paragraph, which conceptos were considered and why none of them reaches this work, and define the scope and the unit of the new concepto precisely enough that two people would measure it the same way.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.outside.why",
      whyDefault:
        "The first question the reviewer asks is whether an existing concepto already pays for this, and a contractor who cannot answer it in writing loses the price whatever the analysis behind it looks like. Work that is genuinely inside an existing unit price and gets paid again as extraordinary is the observation that comes back at audit years later, with the money already spent.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "instruction",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.in.scope", label: "Scope of the new concepto" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.in.bitacora", label: "Bitacora de obra" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.out.note", label: "Bitacora note with its number" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.out.date", label: "Date the clock starts" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.title",
      titleDefault: "Get it instructed in the bitacora, not over the telephone",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.what",
      whatDefault:
        "Have the residente de obra record the instruction in the bitacora as a numbered note that says what is to be executed and why, and answer it in the bitacora too. Keep the note number with the new concepto from this point on, so every later document, analysis, estimacion and generador carries the same reference.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.instruction.why",
      whyDefault:
        "The bitacora is the instrument of communication the contract recognises, so an instruction that lives anywhere else has no date and, in practice, no author. The note number is also what lets the price, the volume and the payment be tied together by a reviewer who was not there, and a chain that cannot be followed is one that gets unwound.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "basics",
      icon: "Database",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.in.proposal", label: "Winning proposal costs" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.in.market", label: "Market investigation" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.out.basics", label: "Costos basicos" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.out.new", label: "New inputs and their evidence" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.title",
      titleDefault: "Take the basic costs from the proposal that won",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.what",
      whatDefault:
        "Build the costos basicos of the new concepto from the materials, labour, machinery and auxiliary costs already analysed in the winning proposal, at the values that proposal carried. Only where an input does not exist there do you go to the market, and then you attach the quotations that justify it and say so on the face of the analysis.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.basics.why",
      whyDefault:
        "The rule is that the extraordinary price is built on the same footing as the contract, because a contractor who may reprice its own inputs mid-contract holds a lever no tender ever put in the price. Marking the genuinely new inputs is what keeps the review on those three or four lines instead of on the whole analysis.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "cascade",
      icon: "Percent",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.in.basics", label: "Costos basicos" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.in.factors", label: "Factors from the proposal" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.out.analisis", label: "Analisis de precio unitario" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.out.price", label: "Proposed unit price" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.title",
      titleDefault: "Cascade the indirect factors in the order the reglamento fixes",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.what",
      whatDefault:
        "Apply the indirectos, then the financiamiento, then the utilidad and finally the cargos adicionales, each at the percentage the winning proposal carried and each computed on the base the previous step produced rather than all of them on the direct cost. Present the analysis in the same layout the proposal used.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.cascade.why",
      whyDefault:
        "The order is fixed, and a cascade computed flat on the direct cost gives a different answer that looks reasonable and is wrong, in the contractor's favour often enough that reviewers check it first. Presenting it in the proposal's own layout means the reviewer compares like with like, which is the difference between a price agreed in one round and one agreed in four.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "conciliate",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.in.analisis", label: "Analisis de precio unitario" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.in.note", label: "Bitacora note with its number" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.out.authorised", label: "Authorised price" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.out.convenio", label: "Convenio where one is needed" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.title",
      titleDefault: "Conciliate the price and formalise what changes",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.what",
      whatDefault:
        "Submit the analysis to the dependencia, work through its observations line by line rather than by resubmitting a different total, and record the price it authorises. Where the new work also moves the contract amount or the period beyond what the contract already allows, formalise it in a convenio modificatorio and check the change against the ceiling the law puts on modifying a contract at all.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.conciliate.why",
      whyDefault:
        "An authorised price is what the estimacion can be built on and an unauthorised one is work already executed at the contractor's risk. The ceiling matters here rather than later: a change that exceeds what the law permits cannot be rescued by a convenio, it has to become its own procurement, and finding that out after the work is built leaves the money with no lawful route to be paid.",
      moduleLabel: "Variations",
      moduleLabelKey: "nav.variations",
      to: "/projects/:projectId/variations",
    },
    {
      id: "estimacion",
      icon: "Receipt",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.in.authorised", label: "Authorised price" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.in.generadores", label: "Numeros generadores" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.out.line", label: "Concepto on the estimacion" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.out.trail", label: "Traceable back to the note" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.title",
      titleDefault: "Carry the authorised price into the estimacion",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.what",
      whatDefault:
        "Add the concepto to the estimacion at the authorised price with its own numero generador showing how the volume was measured, keeping the extraordinary conceptos identifiable rather than mixed into the original catalogo lines. Amortise the anticipo and hold the fondo de garantia on them exactly as on the rest.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.estimacion.why",
      whyDefault:
        "Extraordinary conceptos are the first thing an auditor separates out, so an estimacion that separates them already answers the question. Keeping the amortisation and the retention rules identical avoids the other common finding, which is a concepto paid in full while the rest of the contract was still funding an advance.",
      moduleLabel: "Finance",
      moduleLabelKey: "finance.title",
      to: "/projects/:projectId/finance",
    },
    {
      id: "deadline",
      icon: "CalendarClock",
      inputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.in.date", label: "Date the clock starts" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.in.periods", label: "Periods the reglamento sets" },
      ],
      outputs: [
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.out.watch", label: "Dates under watch" },
        { labelKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.out.warning", label: "Warning before each date" },
      ],
      titleKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.title",
      titleDefault: "Count the natural days, not the working ones",
      whatKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.what",
      whatDefault:
        "Put the period for presenting the analysis and the period for the dependencia to resolve it under a reminder, counted in natural days from the date in the bitacora, and set the warning far enough ahead that the analysis is finished rather than started when it fires.",
      whyKey: "cases.agree_a_precio_extraordinario_for_work_outside_the_catalogo.step.deadline.why",
      whyDefault:
        "Natural days include weekends and holidays, so a period tracked as working days is always longer than the real one and runs out earlier than the calendar suggests. A price presented late is argued about on its lateness rather than on its arithmetic, and the work is usually already built by then.",
      moduleLabel: "Deadlines",
      moduleLabelKey: "deadlines.title",
      to: "/deadlines",
    },
  ],
};

export default playbook;
