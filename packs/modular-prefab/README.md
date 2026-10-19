# Modular & Prefab Pack

Pre-configures OpenConstructionERP for modular construction, off-site
fabrication and project management contractors. Where a country pack carries a
jurisdiction, this one carries a delivery method: factory-line scheduling,
dimensional tolerance control, transport logistics, inter-module assembly and
phased handover.

## What this pack enables

- Currency EUR and the English locale; the pack sets no tax, because it
  crosses jurisdictions and the tax regime comes from wherever the project
  sits
- Seven validation rule packs: `en_1090_steel`, `as_5104_modular`,
  `modular_standards`, `factory_qc_schedule`, `factory_qc_tolerances`,
  `transport_logistics` and `module_handover_protocol`
- The `cwicr-eng-london` cost region, which loads on demand
- A six-step onboarding wizard: company profile, module typology, standards,
  DfMA maturity, logistics and review
- Two repeatable-housing demo projects, `modular-housing` and
  `residential-berlin`
- Industrial blue and modular yellow for co-branding

No modules are hidden and no new rule classes ship with the pack; it switches
on rules already present in the core.

## Cost data

**No cost database is bundled.** This pack is a method, not a price book: it
brings the factory and logistics rules that a site-built estimate has no
place for, and leaves the rates to you. Import your own fabrication and
transport costs, or load a cost region from the marketplace, and the rules
check the schedule and the tolerances around them.

Because the pack is cross-regional, it makes no assumption about which market
your rates come from. It preloads the London cost region only as a starting
point.

## Standards referenced

- EN 1090-1, -2 and -3:2011, execution of steel and aluminium structures
- ICC/MBI 1200-2021 and 1205-2021, off-site construction
- CSA A277:2016 and NEN 9090
- AS 5104 and ISO 2394:2015 reliability targets
- ISO 3834 welding quality, EN 1993-1-1, EN 13670 concrete execution
- ISO 19650 information management and DfMA design principles

These are referenced for interoperability and compliance checking. Standard
and clause numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Modular & Prefab Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=modular-prefab openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
