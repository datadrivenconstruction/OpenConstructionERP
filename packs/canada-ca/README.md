# Canada Construction Pack

The community country pack for Canadian construction estimating. It configures
the workspace the way a Canadian cost estimate is actually built: classified to
CSI MasterFormat, contracted under CCDC standard forms, built to the National
Building Code, priced in Canadian dollars, and checked against provincial
construction acts and tax regimes.

## What makes a Canadian estimate Canadian

A cost estimate in Canada is defined first by its classification. CSI
MasterFormat 2020 organises construction work into numbered divisions (01
through 49), and most Canadian general contractors, cost consultants and
quantity surveyors structure their estimates and tenders this way. UniFormat II
(ASTM E1557) provides the elemental alternative used in early-stage cost
planning. The pack loads MasterFormat as the default classification and
validates every priced line against its division hierarchy.

The contractual framework is the CCDC suite, published jointly by the Canadian
Construction Association (CCA) and the Royal Architectural Institute of Canada
(RAIC). CCDC 2 (Stipulated Price Contract) is the most common form for lump-
sum tenders; CCDC 5A (Construction Management - for services) governs CM
mandates; CCDC 14 (Design-Build Stipulated Price) covers design-build delivery.
The pack references these forms in its validation rule packs so the workspace
is configured for the correct contract administration workflow.

The National Building Code of Canada (NBC) 2020 sets the baseline, but each
province adopts and amends it on its own schedule. Ontario has the OBC,
Quebec has the CCQ, British Columbia has the BCBC and Alberta has the ABC.
A pack that says "built to code" without naming the province has not said
anything useful. The metadata carries province-specific building code
references, construction lien acts, and tax rates.

Tax is where Canadian construction gets complicated. The federal Goods and
Services Tax (GST) at 5% applies everywhere. Ontario, New Brunswick, Nova
Scotia, Newfoundland and PEI harmonize it into HST at 13% or 15%. Quebec
adds its own QST at 9.975%. British Columbia charges a separate PST at 7%.
Alberta, Yukon, Northwest Territories and Nunavut charge only the federal GST.
The pack does not set sales tax (the tax line is set on the estimate's markups) and lets the onboarding wizard
adjust the provincial rate.

Units are metric by code and by regulation (the Weights and Measures Act
requires SI), though imperial units persist in some trades and in everyday
speech. The pack uses metric throughout.

## What this pack enables

- **Currency CAD** (the pack does not set sales tax; the tax line is set on the estimate's markups) and the `canada` estimating
  methodology, with an English and French interface.
- **One engine rule set**, `masterformat`. The MasterFormat rules check that
  every priced line carries a valid division reference and that the hierarchy
  is consistent.
- **Twelve validation rule packs** covering MasterFormat 2020, NBC 2020,
  CCDC 2/5A/14, CSA A23.1/A23.3/S16, and provincial codes for Ontario,
  Quebec, BC and Alberta.
- **An onboarding wizard** that collects the company profile, province,
  standards preference, tax defaults and creates the workspace.
- **Two demo projects**: a commercial office tower in Toronto and a
  residential project in Vancouver, both structured to MasterFormat,
  priced at regional rates in CAD with the applicable tax.

## Cost data

One CWICR cost region is available: Toronto. Vancouver, Calgary, Montreal and
other Canadian cities are not yet published. The city cost index can be applied
per project to adjust base rates to the local price level.

## Standards referenced

- CSI MasterFormat 2020 (work-results classification, Divisions 01 through 49)
- ASTM E1557 UniFormat II (elemental classification)
- National Building Code of Canada (NBC) 2020
- CCDC 2-2020, Stipulated Price Contract
- CCDC 5A-2025, Construction Management - for services
- CCDC 14-2013, Design-Build Stipulated Price Contract
- NMS National Master Specification
- CSA A23.1/A23.3 (concrete materials and structural design)
- CSA S16 (design of steel structures)
- Ontario Building Code (OBC), O. Reg. 332/12
- Code de construction du Quebec (CCQ), chapter I
- BC Building Code (BCBC) 2024
- Alberta Building Code (ABC) 2019

These are referenced for interoperability and compliance checking. Clause,
section and division numbers are interoperability facts and are used as such;
the publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal, tax or fee advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Canada Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=canada-ca openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
