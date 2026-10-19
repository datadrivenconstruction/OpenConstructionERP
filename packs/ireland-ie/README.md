# Ireland Construction Pack

Configures OpenConstructionERP for the Irish construction market. Measurement
follows ARM (Agreed Rules of Measurement) and NRM, the two standards Irish QS
practice sits between. Currency is EUR with 13.5% VAT on construction services,
and the pack references BCAR (Building Control Amendment Regulations) and the
RIAI/SCSI contract and practice frameworks.

## What makes an Irish estimate Irish

An Irish bill of quantities is measured to ARM4, the rules agreed between the
SCSI (Society of Chartered Surveyors Ireland) and the CIF (Construction Industry
Federation). In practice most Irish QS offices also reference NRM, since Irish
and UK measurement traditions share the same ancestry, and public clients
increasingly ask for NRM-aligned documents. The pack enables the NRM rule set,
which covers both.

Construction VAT in Ireland is 13.5 percent on building services, not the
standard 23 percent that applies to most goods. The distinction matters in
estimating because every line in a bill carries the reduced rate and the
professional fee carries the standard rate. The pack does not set VAT.

Contracts follow either the RIAI forms (Yellow or Blue book) for private work
or the PWC (Public Works Contract) suite administered by the Government
Contracts Committee. BCAR (SI No. 9 of 2014) and the TGD (Technical Guidance
Document) series define the building control framework.

## What this pack enables

- **Currency EUR** (the pack does not set VAT) and the `ireland`
  estimating methodology
- **NRM rule set** for measurement validation
- **Two demo projects**: an office building in Dublin and a residential
  development in Cork, both priced at Irish 2026 market rates in EUR
  excluding VAT
- **ARM, BCAR, RIAI and SCSI regulatory references** in the pack metadata

## Standards referenced

- ARM4 (Agreed Rules of Measurement, 4th edition, SCSI/CIF)
- NRM 1/2 (RICS New Rules of Measurement)
- Building Control (Amendment) Regulations 2014 (SI No. 9 of 2014)
- TGD Parts A through M (Technical Guidance Documents)
- RIAI Standard Form of Building Contract
- PWC (Public Works Contracts, Government Contracts Committee)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Ireland Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=ireland-ie openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
