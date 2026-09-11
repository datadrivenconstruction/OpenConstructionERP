# South Korea Construction Pack

A country pack for South Korean construction work. It configures the
workspace around the way a Korean estimate is built: quantities classified
under KBIM, materials and execution specified to KS standards, and the
whole subject to the Building Act and the MOLIT Standard Specifications.

## What makes a Korean estimate Korean

South Korean construction estimation follows a structured system overseen
by the Ministry of Land, Infrastructure and Transport (MOLIT). Public works
estimation uses the Standard Estimation System (Pyojun Jeoksan), which
defines how unit rates are composed from material, labour and equipment
components using officially published unit prices.

The Korea Building Information Modeling standard (KBIM) provides the
classification framework for construction elements. It defines how work items
are categorized and coded, and an estimate built outside this classification
cannot be cross-checked against the standard cost databases that Korean
public works require.

KS standards, published by the Korean Agency for Technology and Standards
(KATS), cover material specifications and testing methods. They are the
Korean equivalent of ISO or JIS standards and define what quality a specified
material must meet.

The Building Act is the primary building regulation, setting structural,
fire safety and environmental requirements. The MOLIT Standard
Specifications provide the detailed execution standards for public
infrastructure and building works, defining how each trade is to be carried
out and measured.

VAT applies at 10 percent on construction services, administered by the
National Tax Service (NTS).

## What this pack enables

- **Currency KRW**, the `kr_vat_10` tax template and kbim as the
  classification standard, with a Korean-language interface.
- **No engine rule sets** are registered yet. The validation engine does not
  carry a Korean rule set at this time; this pack sets the locale, currency
  and cost region without asserting measurement rules.
- **One demo project**, `residential-seoul`, showing a residential building
  project in Seoul.
- **A three-step onboarding wizard** that collects the company profile,
  confirms the standards in use, and reviews the setup.

## Standards referenced

- Building Act (Geonchukbeop)
- KS standards (Korean Industrial Standards, KATS)
- MOLIT Standard Specifications (Ministry of Land, Infrastructure and Transport)
- Pyojun Jeoksan (Standard Estimation System)
- KBIM (Korea Building Information Modeling standard)

These are referenced for interoperability and compliance checking. Section
numbers are interoperability facts and are used as such; the publishers' own
text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "South Korea Construction Pack", then
Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=korea-kr openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
