// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Back an estimacion with its numeros generadores" (MX).
//
// Hand written, not composed. The progress-payment spine covers the money
// half of a Mexican period; this case covers the half that has to exist
// before the money half is worth presenting, which is the measurement
// evidence the residencia de obra actually checks.
//
// The distinction the case is built on: an estimacion is not a progress
// claim with a percentage on it. It is a set of conceptos, each carrying a
// numero generador that shows where the volume came from, and the residencia
// reviews the generadores rather than the totals. The platform holds the
// catalogo as a BOQ, the measurement as take-off, the period as progress and
// the record as the diary. The croquis and the physical signature sheets
// that travel with a generador live outside the platform, and the case says
// so rather than implying the product prints them.
//
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "back-the-estimacion-with-its-numeros-generadores",
  order: 1261,
  region: "MX",
  category: "site",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["site-manager", "quantity-surveyor", "contract-administrator"],
  icon: "Ruler",
  titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.title",
  titleDefault: "Back an estimacion with its numeros generadores",
  descKey: "cases.back_the_estimacion_with_its_numeros_generadores.desc",
  descDefault:
    "Measure the period against the catalogo de conceptos, write a numero generador that shows how each volume was arrived at, tie the ones that were instructed to the bitacora note that instructed them, and present the estimacion with its arithmetic attached instead of after it is asked for.",
  longDescKey: "cases.back_the_estimacion_with_its_numeros_generadores.longdesc",
  longDescDefault:
    "A progress claim says how far along the work is. An estimacion says what was built, where, and how the number was reached, and the difference is the generador. Article 54 LOPSRM gives the contractor six days after the cut-off date to present the estimacion and the residencia de obra fifteen days to review and authorise it, and the twenty natural days the same article allows for payment start only from that authorisation. An estimacion presented without its generadores is not reviewed and then rejected, it is returned, and the days spent assembling the backup afterwards are days nobody is paying interest on. Measured line by line with a generador behind each line, a disagreement is about one concepto rather than about the month, and the rest of the money keeps moving while that one is settled.",
  estMinutes: 16,
  steps: [
    {
      id: "catalogo",
      icon: "ListTree",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.in.contract",
          label: "Signed contract and its catalogo",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.in.rates",
          label: "Precios unitarios as awarded",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.out.lines",
          label: "Conceptos with unit and contract quantity",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.out.units",
          label: "Unit of measurement per concepto",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.title",
      titleDefault: "Open the catalogo de conceptos the contract pays on",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.what",
      whatDefault:
        "Load the catalogo de conceptos exactly as it was awarded: every concepto with its clave, its unit, its contract quantity and its precio unitario. Do not tidy it, do not merge lines and do not renumber. The estimacion pays these lines and nothing else, so the catalogo is the only list a generador is allowed to point at.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.catalogo.why",
      whyDefault:
        "A generador written against an activity, a floor or a crew has nowhere to land, because the estimacion is settled concepto by concepto and the reviewer works down the catalogo. Renumbering is worse than measuring wrongly: a wrong volume is corrected in the next period, a renumbered catalogo makes every past estimacion unreadable against the current one.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "measure",
      icon: "Ruler",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.in.plans",
          label: "Drawings with their revision",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.in.executed",
          label: "Work executed in the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.out.volumes",
          label: "Volumes by eje, nivel and tramo",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.out.source",
          label: "Sheet and revision behind each figure",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.title",
      titleDefault: "Measure the period against the drawing that governs",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.what",
      whatDefault:
        "Take the period off the drawings, subdivided the way the generador will show it: by eje, by nivel, by tramo or by whatever grid the works are actually built on. Record the sheet number and the revision each figure came from as you measure, not afterwards.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.measure.why",
      whyDefault:
        "Drawings are reissued mid job and the reviewer will be holding a different revision from the one you measured. A generador that names its sheet and revision can be rechecked in a minute; one that does not has to be measured again from scratch by somebody who was not there, and the volume that comes back is never the one you claimed.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "generador",
      icon: "FileSpreadsheet",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.in.volumes",
          label: "Measured volumes for the period",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.in.previous",
          label: "Generadores of earlier periods",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.out.generador",
          label: "Numero generador per concepto",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.out.period",
          label: "Volume claimed this period",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.title",
      titleDefault: "Write one numero generador per concepto",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.what",
      whatDefault:
        "For each concepto write the generador the reviewer will read: the location, the dimensions as measured, the arithmetic that turns them into a volume, and the total. Where the shape is not obvious, the croquis goes with it. Show the cumulative volume and the volume claimed this period side by side, because the estimacion pays the difference between two cumulative figures and not a figure of its own.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.generador.why",
      whyDefault:
        "The residencia de obra checks generadores, not totals, and it has fifteen days under article 54 LOPSRM to review and authorise before the twenty natural day payment period can start. A total with nothing behind it cannot be authorised inside those fifteen days even by somebody who believes you, so it comes back, and the period starts again with the next estimacion rather than with this one.",
      moduleLabel: "Progress",
      moduleLabelKey: "nav.progress",
      to: "/progress",
    },
    {
      id: "bitacora",
      icon: "NotebookPen",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.in.generadores",
          label: "Generadores that lean on an instruction",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.in.notes",
          label: "Notas de bitacora for the period",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.out.cited",
          label: "Nota number cited on the generador",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.out.trail",
          label: "Instruction traceable to its author",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.title",
      titleDefault: "Cite the bitacora note behind instructed work",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.what",
      whatDefault:
        "Where a generador covers work that was instructed, varied, accelerated or executed under a condition the contract did not foresee, cite the nota de bitacora that recorded it. The bitacora de obra is the instrument of communication between the parties under the reglamento of the LOPSRM, so the note is not a memory aid, it is the paper the instruction lives on.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.bitacora.why",
      whyDefault:
        "At the finiquito the question is almost never whether the work was built. It is whether it was ordered, by whom and on what date, and a generador that cannot name its nota is a volume the reviewer has no way to accept without taking your word for it. Nobody signs a finiquito on somebody's word.",
      moduleLabel: "Daily Diary",
      moduleLabelKey: "nav.daily_diary",
      to: "/projects/:projectId/daily-diary",
    },
    {
      id: "extraordinarios",
      icon: "Split",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.in.over",
          label: "Volumes past the contract quantity",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.in.missing",
          label: "Work the catalogo does not carry",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.out.raised",
          label: "Concepto fuera de catalogo raised",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.out.clean",
          label: "Estimacion left with contract lines only",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.title",
      titleDefault: "Take out what the catalogo does not carry",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.what",
      whatDefault:
        "Where a generador runs past the contract quantity, or measures something the catalogo does not carry at all, lift it out of the estimacion and raise it as a concepto extraordinario or fuera de catalogo, with its own precio unitario integrated the way the reglamento requires and its own authorisation. Put it back into an estimacion only once it has been authorised.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.extraordinarios.why",
      whyDefault:
        "An extraordinario carried quietly inside an ordinary line is the most common reason a Mexican finiquito does not close. It passes while nobody is looking at that concepto, it fails at the audit that reads the catalogo against the paid volumes, and by then the work is a year old and the people who agreed it verbally have moved on.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "present",
      icon: "FileStack",
      inputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.in.generadores",
          label: "Generadores, croquis and evidence",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.in.rates",
          label: "Precios unitarios as awarded",
        },
      ],
      outputs: [
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.out.estimacion",
          label: "Estimacion presented with its backup",
        },
        {
          labelKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.out.date",
          label: "Date of presentation on record",
        },
      ],
      titleKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.title",
      titleDefault: "Present the estimacion as one package, on the day",
      whatKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.what",
      whatDefault:
        "Carry each generador total onto its concepto line, price it at the awarded precio unitario, and hand the estimacion over as one package: the lines, the generadores, the croquis, the photographs and the test results the specification calls for. Record the date you presented it, separately from the date it is authorised.",
      whyKey: "cases.back_the_estimacion_with_its_numeros_generadores.step.present.why",
      whyDefault:
        "Two different dates drive two different obligations under article 54 LOPSRM, and keeping only one of them is how a contractor loses an argument it was winning. The presentation date is what shows you met the cut-off; the authorisation date is what starts the twenty natural days for payment. Written down as they happen, both are facts. Reconstructed later, both are claims.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
  ],
};

export default playbook;
