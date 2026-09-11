# UAE Construction Pack

A country pack for construction work in the United Arab Emirates. It configures
the workspace for the way estimates are built in the Gulf: MasterFormat
classification, AED currency, 5% VAT under the Federal Tax Authority, and the
regulatory landscape split between Abu Dhabi and Dubai.

## What this pack configures

- **Currency AED**, the `ae_vat_5` tax template and the `uae` estimating
  methodology, with an English interface.
- **MasterFormat classification** as the default work breakdown, which is the
  predominant system used across the UAE construction industry.
- **One CWICR cost region**, `cwicr-ar-dubai`, resolving to AE_DUBAI.
- **Two demo projects**: a warehouse in Dubai and a tower in Abu Dhabi.

## Regulatory landscape

The UAE has no single national building code. Abu Dhabi adopted an IBC-based
International Building Code. Dubai follows the Dubai Municipality Building Code.
The other five emirates have their own municipal regulations, though they
generally align with one of the two main codes.

Civil Defense regulations govern fire and life safety across all emirates and
are administered by each emirate's civil defense authority.

Estidama is Abu Dhabi's sustainability rating system, mandatory for all new
buildings on Abu Dhabi land since 2010. The Pearl Rating applies to villas,
buildings, and communities, and scores from 1 Pearl (mandatory minimum) to
5 Pearls.

## VAT

The UAE introduced VAT at 5% on 1 January 2018 under Federal Decree-Law No. 8
of 2017. Construction services and materials are standard-rated at 5%. The pack
sets the `ae_vat_5` tax template as the default.

## Onboarding

A three-step wizard collects the company profile and trade license details,
building code preference, and a review step that applies the configuration.
The greeting is in Arabic, content is in English.

## Standards referenced

- Abu Dhabi International Building Code
- Dubai Municipality Building Code
- Civil Defense regulations (fire and life safety)
- Estidama Pearl Rating System

These are referenced for interoperability and compliance checking. Nothing in
this pack is legal or tax advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "UAE Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=uae-ae openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
