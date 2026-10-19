# Renewables EPC Pack

Pre-configures OpenConstructionERP for solar, wind and battery storage EPC
contractors: PV array takeoff, turbine bill of materials, medium-voltage cable
schedules, levelised cost templates and the grid compliance regimes on both
sides of the Atlantic.

## What this pack enables

- Currency EUR and the English locale; the pack sets no tax, because it
  crosses jurisdictions and the tax regime comes from wherever the plant is
  built
- Eight validation rule packs: `iec_61400_wind`, `iec_61400_wind_full`,
  `iec_61730_pv`, `pv_design_full`, `bess_design`, `lcoe_templates`,
  `mv_cable_specs` and `renewables_grid_compliance`
- The `cwicr-eng-london` cost region, which loads on demand
- A six-step onboarding wizard: company profile, project typology, standards,
  contract form, grid and regions, and review
- Two energy and heavy-civil demo projects, `solar-bess-epc` and
  `rc-structure-formwork`
- Renewable green and energy blue for co-branding

No modules are hidden and no new rule classes ship with the pack; it switches
on rules already present in the core.

## Cost data

**No cost database is bundled.** Module, turbine and cell prices move faster
than any pack could ship them, and the published market indices are licensed
products in their own right. The `lcoe_templates` rule pack is the structure
of a levelised cost calculation and the checks around it, not a set of
prices: you supply the capital cost, the yield and the discount rate, and the
rules check that the inputs are complete and internally consistent.

Because the pack is cross-regional, it makes no assumption about which market
your rates come from. It preloads the London cost region only as a starting
point.

## Standards referenced

- IEC 61400 series for wind turbines, including design, power performance,
  mechanical loads and reliability
- IEC 61215-1:2021, IEC 61730-1/-2:2023 and IEC 62548:2023 for PV
- IEC 60364-7-712:2017 and IEC 60502-1/-2:2014 for installation and cable
- NFPA 855:2023, IEC 62619:2022, IEC 62620:2014, UL 9540 and UL 9540A for
  battery storage
- IEEE 1547-2018, EN 50549-1/-2:2019, the ENTSO-E network code for grid
  connection (EU 2016/631), the UK Grid Code, FERC Order 2222 and
  NERC PRC-024-3
- ISO 50001 energy management, and the public levelised-cost methodologies

These are referenced for interoperability and compliance checking. Standard
and clause numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Renewables EPC Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=renewables-epc openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
