# Brazil Construction Pack

Pre-configures OpenConstructionERP for Brazilian construction firms: the ABNT
structural and accessibility codes, the CUB unit-cost standard, the 2021
public procurement law, municipal ISS taxation and the RPS/NFS-e service
receipt.

## What this pack enables

- Currency BRL. The pack does not set tax; the tax line is set on the estimate's markups (ISS is collected by
  the municipality, at a rate between 2 and 5 percent)
- Portuguese locale overrides (`pt-BR`)
- Eight validation rule packs: `sinapi_cost_db`, `nbr_12721`,
  `abnt_concrete`, `abnt_steel`, `nbr_9050_2020`, `nbr_5419_2015`,
  `lei_14133_2021` and `rps_pdf_generation`
- The `cwicr-pt-saopaulo` cost region, which loads on demand
- A seven-step onboarding wizard: company profile, tax regime, cost standard,
  RPS and ISS, standards, procurement and review
- The `residential-saopaulo` demo project
- Brazilian flag green and yellow for co-branding

No modules are hidden and no new rule classes ship with the pack; it switches
on rules already present in the core.

## Cost data

**No cost database is bundled.** The pack ships the rules that check imported
rates, not the rates themselves.

`sinapi_cost_db` validates that a reference month is present and still fresh,
that a state index and a regional adjustment factor have been applied, that
the composition code has the expected format, that a composition has not been
confused with an input, and that the BDI markup sits inside the band the
federal audit court set for public works. You import the rate table you are
entitled to use; these rules tell you when it is stale, unadjusted or out of
band.

## Regional cost data

Only the São Paulo CWICR region is published today. Rio de Janeiro, Brasília,
Belo Horizonte and Salvador are listed in the onboarding wizard and will
become selectable when their snapshots ship.

## Standards referenced

- NBR 12721:2006, unit construction costs for real estate development
- NBR 6118:2023 concrete structures and NBR 8800:2008 steel structures
- NBR 9050:2020 accessibility, mandatory for public and commercial buildings
- NBR 5419:2015 parts 1 to 4, lightning protection
- Lei 14.133/2021, the public procurement and administrative contracts law
- RPS and NFS-e municipal service receipts

These are referenced for interoperability and compliance checking. Standard
and article numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Brazil Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=brazil-sinapi openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
