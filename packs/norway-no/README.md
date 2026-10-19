# Norway Construction Pack

Country pack for Norwegian construction estimating. It configures the workspace
the way a Norwegian kalkyle is actually built: against the NS 3451 building
element table, specified with NS 3420, contracted under NS 8405 or NS 8407,
priced in kroner, and checked against the regulations a Norwegian contractor
needs to satisfy.

## What makes a Norwegian estimate Norwegian

A cost estimate in Norway is organised by the NS 3451 bygningsdelstabell, which
breaks the building into element groups numbered 1 through 8. NS 3451 is
complemented by NS 3453, which specifies how costs are broken down and reported
in a building project. Together they define the structure a Norwegian estimator
reads and a Norwegian client checks.

Specifications follow NS 3420, the standard system of description texts for
building, civil engineering and installation works. NS 3420 defines how work
items are described, how quantities are measured, and which quality and
tolerance requirements apply. A specification written outside NS 3420 is
uncommon in formal Norwegian procurement.

Contracts follow the NS 8400 series. NS 8405 governs general contracting
(utfoerelsesentreprise) and NS 8407 governs design-build (totalentreprise).
These are the standard forms both parties know.

Tax is 25 percent merverdiavgift (MVA) on construction services. The pack sets
the standard 25 percent rate.

## What this pack enables

- **Currency NOK** (the pack does not set VAT) and the `norway` estimating
  methodology, with a Norwegian and English interface.
- **Three validation rule packs** covering the NS 3420 specification standard,
  NS 3451 classification, and NS 8405 contract conditions. These are reference
  material for the estimator.
- **A four-step onboarding wizard** that collects the company profile and
  organisasjonsnummer, the standards and classification preference, the tax
  defaults, and creates the workspace. Bilingual Norwegian and English.
- **Two demo projects**: an office building in Oslo and a residential project
  in Bergen. Both are classified to NS 3451, specified to NS 3420, and priced
  at regional rates with 25% MVA.

## Standards referenced

- NS 3420 (Beskrivelsestekster for bygg, anlegg og installasjoner)
- NS 3451 (Bygningsdelstabell, building element table)
- NS 3453 (Spesifikasjon av kostnader i byggeprosjekt)
- NS 8405 (Norsk bygge- og anleggskontrakt)
- NS 8407 (Alminnelige kontraktsbestemmelser for totalentreprise)
- TEK17 (Byggteknisk forskrift, technical building regulations)
- Plan- og bygningsloven (Planning and Building Act)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal, tax or fee advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Norway Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=norway-no openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
