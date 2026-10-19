# Singapore Construction Pack

Configures OpenConstructionERP for the Singapore construction market. Measurement
follows SMM7, the standard method that Singapore QS practice is built on. Currency
is SGD with 9% GST on construction services. The BCA regulatory framework, CONQUAS
quality benchmarks and SIA/PSSCOC contract forms are referenced for compliance
context.

## What makes a Singaporean estimate Singaporean

A bill of quantities in Singapore is measured to SMM7, the same standard method the
UK uses, adapted to local practice by the Singapore Institute of Surveyors and
Valuers. The BCA (Building and Construction Authority) regulates the industry and
its buildability and CONQUAS frameworks shape project delivery.

Construction contracts typically follow SIA (Singapore Institute of Architects)
conditions for private work or PSSCOC (Public Sector Standard Conditions of
Contract) for government projects. Both are well defined and widely understood.

GST at 9 percent applies to construction services. The pack does not set the rate.

## What this pack enables

- **Currency SGD** (the pack does not set GST) and the `singapore` estimating
  methodology
- **NRM rule set** for measurement validation, aligned with Singapore QS practice
- **Two demo projects**: an office building and a residential development, both
  priced at Singapore 2026 market rates in SGD excluding GST
- **BCA, CONQUAS and SIA regulatory references** in the pack metadata

## Standards referenced

- SMM7 (Standard Method of Measurement, 7th edition)
- BCA Building Control Act and Regulations
- CONQUAS (Construction Quality Assessment System)
- SIA Conditions of Building Contract
- PSSCOC (Public Sector Standard Conditions of Contract)
- SS EN standards (Singapore Standards, Eurocode-aligned)
- Code of Practice on Buildability (BCA)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Singapore Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=singapore-sg openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
