# Sweden Construction Pack

Country pack for Swedish construction estimating. It configures the workspace
the way a Swedish kalkyl is actually built: against the BSAB classification
system, specified with AMA (Allman Material- och Arbetsbeskrivning), contracted
under AB 04 or ABT 06, priced in kronor, and checked against the regulations a
Swedish contractor needs to satisfy.

## What makes a Swedish estimate Swedish

A cost estimate in Sweden is built around AMA, the specification system that
defines how materials and work are described, measured and quality-assured. AMA
is published by Svensk Byggtjanst and comes in discipline-specific volumes: AMA
Hus for building works, AMA Anlaggning for civil engineering, AMA VVS and El
for services. A specification written outside AMA is not wrong, but it will not
match what a Swedish contractor expects to price against, and a public-sector
tender will usually require it.

Classification follows BSAB, which organises the building into functional
elements and production results. BSAB codes appear on every priced line and
structure the kalkyl the way a Swedish estimator reads it.

Contracts follow the AB family of standard conditions. AB 04 governs general
contracting (utforandeentreprenad) and ABT 06 governs design-build
(totalentreprenad). These are the forms a Swedish client and contractor both
know and the ones the tender documents reference.

Tax is 25 percent moms on construction services, with a reduced rate of 12
percent for certain renovation work on residential buildings. The pack sets
the standard 25 percent rate.

## What this pack enables

- **Currency SEK** (the pack does not set VAT) and the `sweden` estimating
  methodology, with a Swedish and English interface.
- **Three validation rule packs** covering the AMA specification system, BSAB
  classification, and AB 04 contract conditions. These are reference material
  for the estimator.
- **A four-step onboarding wizard** that collects the company profile and
  organisationsnummer, the standards and classification preference, the tax
  defaults, and creates the workspace. Bilingual Swedish and English.
- **Two demo projects**: an office building in Stockholm and a residential
  project in Gothenburg. Both are classified to BSAB, specified to AMA, and
  priced at regional rates with 25% moms.

## Standards referenced

- AMA (Allman Material- och Arbetsbeskrivning, Svensk Byggtjanst)
- AB 04 (Allmanna Bestammelser for byggnads-, anlaggnings- och installationsentreprenader)
- ABT 06 (Allmanna Bestammelser for totalentreprenader)
- BSAB (Byggandets Samordning AB, classification system)
- BBR (Boverkets byggregler, national building regulations)
- PBL (Plan- och bygglagen, Planning and Building Act)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal, tax or fee advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Sweden Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=sweden-se openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
