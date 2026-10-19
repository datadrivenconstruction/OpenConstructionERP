# US Construction Pack

Pre-configures OpenConstructionERP for United States general contracting: the
CSI classification structures, the AIA owner-contractor agreement family, OSHA
construction safety, the IBC code editions the states actually adopt, and a
city cost index structure for localizing rates per metro.

## What this pack enables

- Currency USD. The pack does not set sales tax; the tax line is set on the estimate's markups
- en-US locale with US construction vocabulary (bid, RFI, punch list,
  submittal, sub, GC, CM at Risk) and US spellings for the imperial units
  (sq ft, lin ft, cu yd, gal, ton). Metric units keep their own names: the
  locale renames a label, it does not convert the quantity next to it, so a
  cubic metre is never printed as a cubic yard
- CSI MasterFormat 2020 specification structure and UniFormat II (ASTM E1557)
  elemental classification for early-design estimates
- AIA A201-2017 General Conditions plus the A101/A102/A103/A104/A141
  owner-contractor agreement family
- OSHA 29 CFR 1926 construction safety defaults, including State OSHA plan
  jurisdictions
- IBC 2021 with per-state amendment overrides (CA, NY, FL, TX, MA)
- A city cost index rule pack for per-metro localization, with ten metros
  pre-offered in the onboarding wizard
- The cwicr-usa-usd cost region
- US flag colours for co-branding

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "US Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=us-costdata openconstructionerp serve
```

## Cost data

**No commercial cost database is bundled, and none can be.** The commercial US
unit-price databases are licensed products; their licences forbid
redistribution, and no open dataset of that class and coverage exists for the
United States. Shipping one inside an AGPL pack is not something a licence
would permit us to do.

So this pack is the structure, not the data. It gives you the classification
to file rates under, the city cost index rules to localize them with, and the
import path to bring in the rates you are licensed to use, whether that is
your own historical cost history, a subscription you hold, or a public
schedule of values. The onboarding wizard asks which metros you work in and
whether you have an index subscription to import from; it never assumes a
particular vendor.

The pack points at the cwicr-usa-usd region for national-average USD rates
with regional adjustment factors, which loads on demand.

## Standards referenced

- CSI MasterFormat 2020 specification structure
- ASTM E1557-09 UniFormat II elemental classification
- AIA A201-2017 General Conditions and the owner-contractor agreement family
- OSHA 29 CFR 1926, Construction Industry safety regulations
- IBC 2021, International Building Code, with state amendments
- ICC A117.1-2017 accessibility and IECC 2021 energy

These are referenced for interoperability. Division and section numbers are
interoperability facts and are used as such; the licensors' own title text and
tables are not reproduced here.

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
