// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Hold the concrete to IS 456, from pour card to cube result" (IN).
//
// IS 456 is the Indian code for plain and reinforced concrete, and the reason
// it belongs in a cost product rather than only in an engineer's drawer is that
// its acceptance decision arrives four weeks after the money was spent. Cubes
// are cast when the concrete is placed and tested at seven and twenty-eight
// days, so a pour that was measured, billed and built on top of is judged long
// after all three. A failed result is therefore never only a quality event. It
// reaches back into a running account bill that has already been certified.
//
// Everything that can be checked before that delay is worth checking before it,
// which is what a pre-pour inspection is for: reinforcement as detailed, cover
// maintained, formwork and its supports, the mix and its workability. On a
// seismic structure the detailing check carries more than usual, because
// ductile detailing is what the structure relies on in the event the code is
// designed around, and it is invisible the moment the pour starts.
//
// The pack ships IS 456 as a reference document rather than as executable
// rules; what the engine runs is the schedule and measurement rule set. So this
// case is built on the product's own quality workflow, held to the code.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "hold-the-concrete-to-is-456-from-pour-card-to-cube-result",
  order: 1188,
  region: "IN",
  category: "quality",
  companyTypes: ["general-contractor", "project-manager", "subcontractor", "developer-client"],
  roles: ["site-manager", "foreman", "project-manager", "document-controller"],
  icon: "FlaskConical",
  titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.title",
  titleDefault: "Hold the concrete to IS 456, from pour card to cube result",
  descKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.desc",
  descDefault:
    "Write the concrete inspection and test plan, clear each pour before it starts, cast and track the cubes against the pour they came from, act on a failed result properly, and keep the certificates where handover will need them.",
  longDescKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.longdesc",
  longDescDefault:
    "Concrete is the one trade where the verdict arrives a month late, and every problem with managing it follows from that. By the time a twenty-eight day result is in, the pour has been measured, billed, cured, struck and loaded, and often has two floors on top of it. That gap is survivable only if two records were kept properly at the time: what was checked before the pour, and which cubes belong to which pour. With both, a failed result is a bounded problem, traceable to a specific element, and the code's own route through further testing and assessment is open. Without them, a failed result is a question about an unknown extent of the structure, and the cost of answering it has nothing to do with the cost of the concrete. This case is about keeping those two records well enough that the delay stops being dangerous.",
  estMinutes: 20,
  steps: [
    {
      id: "plan",
      icon: "ListChecks",
      inputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.in.spec",
          label: "Specification and grades",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.in.code",
          label: "The code requirements that apply",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.out.itp",
          label: "An inspection and test plan for concrete",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.out.holds",
          label: "Hold points nobody may pass",
        },
      ],
      titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.title",
      titleDefault: "Write the test plan before the first pour, not after",
      whatKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.what",
      whatDefault:
        "Set out, per grade and per element type, what is checked and when: mix approval, workability at the point of placing, the sampling frequency the code sets by volume placed, the ages at which cubes are tested, curing, and formwork striking. Mark the pre-pour check as a hold point rather than as a notification.",
      whyKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.plan.why",
      whyDefault:
        "A hold point is the only instrument that survives a busy site. A check written as a notification is done when there is time, which on a pour day there is not, and the pour goes ahead because stopping it costs a truck of concrete.",
      moduleLabel: "Quality Management",
      moduleLabelKey: "nav.qms",
      to: "/projects/:projectId/qms",
    },
    {
      id: "prepour",
      icon: "ClipboardCheck",
      inputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.in.element",
          label: "The element about to be poured",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.in.drawings",
          label: "Reinforcement drawings and schedules",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.out.cleared",
          label: "A cleared pour, with evidence",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.out.photos",
          label: "What the reinforcement looked like",
        },
      ],
      titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.title",
      titleDefault: "Clear the pour on the things that disappear",
      whatKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.what",
      whatDefault:
        "Inspect against the plan before concrete is called: bar size, spacing and laps against the schedule, cover blocks in place and of the right thickness, the detailing at joints and confinement zones, formwork line and support, and the element clean. Photograph the reinforcement, and record who cleared it.",
      whyKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.prepour.why",
      whyDefault:
        "Everything in that list is invisible an hour later and expensive to verify afterwards. Cover in particular decides how long the structure lasts and cannot be inspected once poured, so the record made at this moment is the only evidence that will ever exist.",
      moduleLabel: "Inspections",
      moduleLabelKey: "nav.inspections",
      to: "/projects/:projectId/inspections",
    },
    {
      id: "samples",
      icon: "FlaskConical",
      inputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.in.pour",
          label: "The pour, its grade and its volume",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.out.cubes",
          label: "Cubes tied to the element they came from",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.out.due",
          label: "Test dates falling due",
        },
      ],
      titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.title",
      titleDefault: "Cast the cubes and tie them to the element, not to the day",
      whatKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.what",
      whatDefault:
        "Fill the pour card as the concrete is placed: grade, volume, time, workability reading, weather, and the identification of every cube cast from it, against the element being poured. Record the test ages that fall due from those dates.",
      whyKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.samples.why",
      whyDefault:
        "Cubes identified only by date are useless on a site pouring three elements a day. When a result comes back low, the question is which element it belongs to, and a card that answers that turns a structural investigation into a check of one beam.",
      moduleLabel: "Forms & checklists",
      moduleLabelKey: "nav.forms",
      to: "/forms",
    },
    {
      id: "result",
      icon: "AlertTriangle",
      inputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.in.results",
          label: "Cube results at each age",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.out.ncr",
          label: "A non-conformance with a known extent",
        },
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.out.route",
          label: "The route to acceptance or rejection",
        },
      ],
      titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.title",
      titleDefault: "Treat a low result as a bounded non-conformance",
      whatKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.what",
      whatDefault:
        "Read the results against the acceptance criteria the code sets, and where they fall short, raise a non-conformance naming the element, the pour and the volume affected. Record the further testing or structural assessment agreed, and who signs off the outcome.",
      whyKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.result.why",
      whyDefault:
        "A low seven day result is information, not a verdict, and a low twenty-eight day result has a defined route through it. What decides the cost is whether the extent is known. A non-conformance that names one element is a repair; one that cannot say which pour it belongs to becomes a survey of a floor.",
      moduleLabel: "NCRs",
      moduleLabelKey: "ncr.title",
      to: "/projects/:projectId/ncr",
    },
    {
      id: "record",
      icon: "FolderOpen",
      inputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.record.in.certificates",
          label: "Test certificates and pour cards",
        },
      ],
      outputs: [
        {
          labelKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.record.out.file",
          label: "A concrete file arranged by element",
        },
      ],
      titleKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.record.title",
      titleDefault: "File the certificates against the structure they prove",
      whatKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.record.what",
      whatDefault:
        "Keep the pour cards, the laboratory certificates, the pre-pour clearances and any non-conformance and its closure together, organised by element rather than by month.",
      whyKey: "cases.hold_the_concrete_to_is_456_from_pour_card_to_cube_result.step.record.why",
      whyDefault:
        "At handover, and at any later query about the structure, the question is always about a part of the building rather than about a period of time. A file arranged by element answers it in minutes; one arranged by month is searched by somebody who was not there.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
  ],
};

export default playbook;
