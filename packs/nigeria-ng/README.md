# Nigeria Construction Pack

Configures OpenConstructionERP for the Nigerian construction market. Measurement
follows BESMM3 (Building and Engineering Standard Method of Measurement, 3rd
edition), the standard used by Nigerian quantity surveyors. Currency is NGN with
7.5% VAT on construction services. The NBS (Nigerian Building Standards) and NIQS
(Nigerian Institute of Quantity Surveyors) practice frameworks are referenced.

## What makes a Nigerian estimate Nigerian

A bill of quantities in Nigeria is measured to BESMM3, the method developed by the
Nigerian Institute of Quantity Surveyors. The format follows the UK tradition - the
QS profession in Nigeria is RICS-aligned - but BESMM adapts the measurement rules
to local construction methods and materials, particularly for reinforced concrete
frame construction which dominates Nigerian building.

Public procurement follows the Public Procurement Act 2007 administered by the
Bureau of Public Procurement. The National Building Code 2006 sets the regulatory
framework. Professional practice is governed by NIQS for quantity surveyors, COREN
for engineers and ARCON for architects.

VAT on construction services is 7.5 percent. The pack does not set the rate.

## What this pack enables

- **Currency NGN** (the pack does not set VAT) and the `nigeria`
  estimating methodology
- **NRM rule set** for measurement validation, aligned with Nigerian BESMM/QS
  practice
- **Two demo projects**: a commercial building in Lagos and a residential
  development in Abuja, both priced at Nigerian 2026 market rates in NGN
  excluding VAT
- **BESMM, NBS, NIQS and public procurement regulatory references** in the
  pack metadata

## Standards referenced

- BESMM3 (Building and Engineering Standard Method of Measurement, 3rd edition)
- NBS (Nigerian Building Standards)
- National Building Code of Nigeria 2006
- Public Procurement Act 2007 (Bureau of Public Procurement)
- NIQS (Nigerian Institute of Quantity Surveyors) practice standards
- COREN (Council for the Regulation of Engineering in Nigeria)
- ARCON (Architects Registration Council of Nigeria)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Nigeria Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=nigeria-ng openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
