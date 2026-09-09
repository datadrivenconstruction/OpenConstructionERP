// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Price a road orcamento from the SICRO base" (BR).
//
// Decreto 7.983/2013 sends building works to SINAPI and infrastructure works
// to SICRO, and the two are not the same job wearing different codes. SICRO
// prices machines by the hour, split between productive and idle time, and it
// prices earth and aggregate by how far they travel. So the estimate turns on
// equipment costing and haul distance rather than on crew productivity.
// Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "price-a-road-orcamento-from-the-sicro-base",
  order: 1503,
  region: "BR",
  category: "estimating",
  companyTypes: ["general-contractor", "cost-consultant", "subcontractor"],
  roles: ["estimator", "quantity-surveyor", "planner"],
  icon: "Truck",
  titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.title",
  titleDefault: "Price a road orcamento from the SICRO base",
  descKey: "cases.price_a_road_orcamento_from_the_sicro_base.desc",
  descDefault:
    "Load SICRO for the state and the reference month, build the hourly cost of every machine, turn the haul distances into transport items, compose the servicos at SICRO coefficients and price the orcamento with the assumptions written down.",
  longDescKey: "cases.price_a_road_orcamento_from_the_sicro_base.longdesc",
  longDescDefault:
    "SICRO exists because a road is priced by machines and distance rather than by crews and square metres, and Decreto 7.983 of 2013 makes it the reference system for infrastructure works paid with federal money in the same way SINAPI is for buildings. Two numbers dominate the result and both are usually settled before anybody looks at a unit cost. The hourly cost of a machine depends on how much of its time is productive and how much it is standing waiting on the crew ahead of it, and the two hours cost different amounts. The transport of earth, aggregate and asphalt is priced by distance, so a haul distance taken from a drawing rather than from a borrow pit that actually has material in it moves the estimate by more than any argument about productivity ever will.",
  estMinutes: 20,
  steps: [
    {
      id: "base",
      icon: "Database",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.in.tables",
          label: "SICRO reference prices",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.in.date",
          label: "Reference date the edital names",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.out.loaded",
          label: "Priced reference base loaded",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.out.state",
          label: "State and reference month recorded",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.title",
      titleDefault: "Bring in SICRO for the state and the reference month",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.what",
      whatDefault:
        "Load the SICRO tables for the state the road runs through and the reference month the edital names, and keep both on the record with the prices. Load the matching equipment and insumo tables rather than mixing a new servico table with equipment costs you already had.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.base.why",
      whyDefault:
        "SICRO prices differ by state because fuel, aggregate and labour do, and a road that crosses a boundary can legitimately need two tables. Fixing which table applies to which stretch now is a paragraph. Doing it after the proposals are open is a dispute in which both sides are quoting real published prices.",
      moduleLabel: "Cost Database",
      moduleLabelKey: "costs.title",
      to: "/costs",
    },
    {
      id: "equipment",
      icon: "Truck",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.in.fleet",
          label: "Machines the method needs",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.in.rates",
          label: "Ownership and operating rates",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.out.hourly",
          label: "Hourly cost per machine",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.out.split",
          label: "Productive and idle hours separated",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.title",
      titleDefault: "Build the hourly cost of every machine",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.what",
      whatDefault:
        "For each machine the method needs, set the ownership cost, the fuel and lubricant, the maintenance and the operator, and split the result into a productive hour and an idle hour. Do it for the plant that waits as well as the plant that works, the water truck and the roller included.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.equipment.why",
      whyDefault:
        "On a road contract the machines are the estimate. A single hourly cost averaged across productive and idle time prices a fleet that is always either working or parked, and no earthworks operation behaves that way. The two-rate split is what lets the composicao say honestly that the excavator drives the cycle and the trucks wait on it.",
      moduleLabel: "Equipment & Fleet",
      moduleLabelKey: "nav.equipment",
      to: "/equipment",
    },
    {
      id: "transport",
      icon: "Route",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.in.volumes",
          label: "Earthwork quantities by origin",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.in.haul",
          label: "Haul distance to each destination",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.out.dmt",
          label: "Distancia media de transporte",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.out.items",
          label: "Transport items measured",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.title",
      titleDefault: "Turn the haul distances into measured transport",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.what",
      whatDefault:
        "Measure what moves and how far: cut to fill, borrow pit to embankment, quarry to plant, plant to laydown. Work out the distancia media de transporte for each pairing and carry it as a measured item rather than as a note beside a volume.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.transport.why",
      whyDefault:
        "Transport is often the largest single cost on an earthworks job and it is the one most often taken from a drawing rather than from the ground. A DMT measured against real borrow pits and real access roads is a number both sides can check. A DMT assumed to be the straight-line distance is a claim waiting to happen the first week the trucks run.",
      moduleLabel: "Quantity Takeoff",
      moduleLabelKey: "nav.quantities",
      to: "/quantities",
    },
    {
      id: "compose",
      icon: "Combine",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.in.hourly",
          label: "Hourly cost per machine",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.in.coef",
          label: "SICRO coefficients per servico",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.out.assembly",
          label: "Composicao with a built-up rate",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.out.cycle",
          label: "Production per hour on the record",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.title",
      titleDefault: "Compose each servico around the machine that sets the pace",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.what",
      whatDefault:
        "Build each servico as an assembly whose production per hour comes from one machine, and let the rest of the fleet follow it as productive or idle hours. Keep the material, the labour and the transport as their own components so the cost of a cubic metre can be read apart from the cost of moving it.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.compose.why",
      whyDefault:
        "A road composicao where every machine works at full production prices a fleet that never queues, and it is always the cheapest way to be wrong. Naming the machine that sets the pace makes the estimate say what the site will do, and it tells the planner which single piece of plant the programme depends on.",
      moduleLabel: "Assemblies",
      moduleLabelKey: "nav.assemblies",
      to: "/assemblies",
    },
    {
      id: "price",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.in.assembly",
          label: "Composicao with a built-up rate",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.in.items",
          label: "Transport items measured",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.out.priced",
          label: "Priced bill positions",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.out.lote",
          label: "Total per lote",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.title",
      titleDefault: "Price the orcamento and total it per lote",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.what",
      whatDefault:
        "Apply the composicoes to the positions, carry the transport as its own set of items, and total the bill by lote and by segment so each stretch can be read on its own. Check that the earthworks balance in the bill matches the one the transport was measured from.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.price.why",
      whyDefault:
        "A road contract is usually awarded and measured by lote, so a total that only exists for the whole scheme has to be rebuilt by hand for every conversation. And an earthworks balance that disagrees with the transport measured against it means one of the two is describing a road that was not designed.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "basis",
      icon: "BookOpen",
      inputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.in.dmt",
          label: "Distancia media de transporte",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.in.state",
          label: "State and reference month recorded",
        },
      ],
      outputs: [
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.out.memo",
          label: "Assumptions report",
        },
        {
          labelKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.out.risk",
          label: "Risk items named",
        },
      ],
      titleKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.title",
      titleDefault: "Record the SICRO reference and the haul assumptions",
      whatKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.what",
      whatDefault:
        "Write down which SICRO table and month priced the work, which borrow pits and quarries the transport assumed, and which of those are not yet licensed or contracted. Name the assumptions that would move the price if they turn out differently.",
      whyKey: "cases.price_a_road_orcamento_from_the_sicro_base.step.basis.why",
      whyDefault:
        "The borrow pit is the assumption that changes most often and costs most when it does. Named in the basis of estimate before the bid, a pit that turns out to be unavailable is a variation with a documented starting point. Unnamed, it is a cost the contractor carries while explaining that everybody knew.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
  ],
};

export default playbook;
