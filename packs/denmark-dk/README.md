# Denmark Construction Pack

Country pack for Danish construction estimating. It configures the workspace
the way a Danish kalkulation is actually built: against the SfB/CCS
classification system, specified with V&S (Vejledende Beskrivelser), contracted
under AB 18 or ABT 18, priced in kroner, and checked against the regulations a
Danish contractor needs to satisfy.

## What makes a Danish estimate Danish

A cost estimate in Denmark is typically structured by building elements using
the SfB classification system or, increasingly, the Cuneco Classification
System (CCS). Both organise the building into functional elements and are the
frameworks a Danish estimator reads.

Specifications follow V&S (Vejledende Beskrivelser), the system of standard
descriptions published by Molio (formerly Byggecentrum). V&S defines how work
items are described, how quantities are measured, and which quality requirements
apply. A specification written outside V&S is unusual in Danish formal
procurement.

Contracts follow the AB system. AB 18 (Almindelige Betingelser) governs
general contracting and ABT 18 governs design-build (totalentreprise). These
replaced the previous AB 92 / ABT 93 editions and are the standard conditions
both parties expect.

Tax is 25 percent moms on construction services. Denmark has no reduced rate
for construction. The pack sets the standard 25 percent rate.

## What this pack enables

- **Currency DKK** (the pack does not set VAT) and the `denmark` estimating
  methodology, with a Danish and English interface.
- **Three validation rule packs** covering the V&S specification system,
  SfB/CCS classification, and AB 18 contract conditions. These are reference
  material for the estimator.
- **A four-step onboarding wizard** that collects the company profile and
  CVR-nummer, the standards and classification preference, the tax defaults,
  and creates the workspace. Bilingual Danish and English.
- **Two demo projects**: an office building in Copenhagen and a residential
  project in Aarhus. Both are classified to SfB/CCS, specified to V&S, and
  priced at regional rates with 25% moms.

## Standards referenced

- V&S (Vejledende Beskrivelser, Molio specification system)
- AB 18 (Almindelige Betingelser for arbejder og leverancer i bygge- og anlaegsvirksomhed)
- ABT 18 (Almindelige Betingelser for totalentreprise)
- SfB (Samarbetskommitten for Byggnadsfragor, classification system)
- CCS (Cuneco Classification System)
- BR 18 (Bygningsreglementet, Danish Building Regulations)
- Planloven (Planning Act)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal, tax or fee advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Denmark Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=denmark-dk openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
