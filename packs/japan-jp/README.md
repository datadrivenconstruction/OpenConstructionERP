# Japan Construction Pack

A country pack for Japanese construction work. It configures the workspace
around the way a Japanese estimate is built: quantities measured and priced
according to the Sekisan Kijun standards, materials and workmanship specified
to JASS, and the whole subject to the Building Standards Act and the Public
Works Standard Specifications.

## What makes a Japanese estimate Japanese

Japanese construction estimation follows the Sekisan Kijun, the official
estimation standards published by the Ministry of Land, Infrastructure,
Transport and Tourism (MLIT). These standards define how quantities are
measured, how unit rates are composed, and how indirect costs are structured.
Public works estimation in particular follows detailed composite rate tables
that break each work item into material, labour, equipment and overhead
components.

The technical specification side is governed by JASS, the Japanese
Architectural Standard Specification published by the Architectural Institute
of Japan (AIJ). Each trade has its own JASS volume, and it defines both the
quality requirements and the measurement conventions for that trade. JASS and
the Sekisan Kijun together form the specification-and-measurement pair that a
Japanese estimate sits on.

The Building Standards Act is the primary building regulation. It sets
structural, fire safety and environmental requirements that directly affect
scope and cost. The Public Works Standard Specifications, published by MLIT,
provide the detailed execution standards for government infrastructure work.

Consumption tax applies at 10 percent on construction services. Unlike VAT
systems in many countries, the Japanese consumption tax is a single national
rate with no regional variation.

## What this pack enables

- **Currency JPY**, the `jp_consumption_10` tax template and sekisan as the
  classification standard, with a Japanese-language interface.
- **No engine rule sets** are registered yet. The validation engine does not
  carry a sekisan rule set at this time; this pack sets the locale, currency
  and cost region without asserting measurement rules.
- **One demo project**, `office-tokyo`, showing a commercial office building
  priced in the Sekisan format.
- **A three-step onboarding wizard** that collects the company profile,
  confirms the standards in use, and reviews the setup.

## Standards referenced

- Building Standards Act (Kenchiku Kijun Ho)
- JASS (Japanese Architectural Standard Specification, AIJ)
- Public Works Standard Specifications (MLIT)
- Sekisan Kijun (Public Works Estimation Standards, MLIT)

These are referenced for interoperability and compliance checking. Section
numbers are interoperability facts and are used as such; the publishers' own
text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Japan Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=japan-jp openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
