# South Africa Construction Pack

DataDrivenConstruction's first African market pack. It pre-configures
OpenConstructionERP for South African construction with the local measurement
standards, contractor grading, procurement framework, currency and tax.

## What this pack enables

- Currency ZAR and 15 percent VAT (SARS, Value-Added Tax Act 89 of 1991)
- en-ZA locale with South African construction vocabulary and regulators
- SANS 1200 civil engineering construction and the ASAQS Standard System of
  Measuring Building Work
- CIDB contractor grading, grades 1 to 9, across the classes of work
- PPPFA preferential procurement scoring, both 80/20 and 90/10 systems
- National Treasury infrastructure delivery and procurement gates (FIDPM 2019)
- Nine provinces available as cost regions, wired to the ZA_JOHANNESBURG CWICR
  dataset (on the published-data roadmap)
- South African flag colours for co-branding

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "South Africa Construction Pack", then Apply.

To run a workspace that boots straight into it:

```bash
OE_PACK=south-africa openconstructionerp serve
```

## Standards referenced

- SANS 1200 Standardized Specification for Civil Engineering Construction (SABS)
- ASAQS Standard System of Measuring Building Work
- Construction Industry Development Board Act 38 of 2000 (CIDB grading)
- Preferential Procurement Policy Framework Act 5 of 2000 and the 2022
  Regulations (PPPFA 80/20 and 90/10)
- National Treasury Framework for Infrastructure Delivery and Procurement
  Management (FIDPM 2019)
- Value-Added Tax Act 89 of 1991 (SARS)

The endorsed contract suite (JBCC, GCC 2015, NEC4, FIDIC) is surfaced for
reference. The PPPFA scoring endpoint implements the official price-points
formula, not a flat sum.

## Cost data

Rates are not bundled. The pack points at the ZA_JOHANNESBURG CWICR region so
real South African cost data loads on demand once the snapshot is published.
Province location factors are provided as indicative starting points and are
fully editable; they are not an official index.

## Credit

The idea and a reference implementation were contributed by Aidan Koetaan.
This pack is our own implementation, written from the
public standards listed above. See CONTRIBUTORS.md.

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
