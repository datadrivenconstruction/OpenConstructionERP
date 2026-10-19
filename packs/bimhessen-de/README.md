# BIM-Cluster Hessen Pack (Germany)

Partner pack pre-configuring OpenConstructionERP for German BIM consultancies
and engineering offices, with a regional focus on Hessen. Loads the German
standards stack: DIN 276 cost groups, GAEB exchange, VOB contract conditions,
ISO 19650 information management and the HOAI fee phases.

## What this pack enables

- Currency EUR (the pack does not set VAT) and the Germany estimating
  methodology
- German locale overrides on top of the core `de` strings
- Seven validation rule packs: `din_276`, `gaeb_x83_x86`, `vob_2019`,
  `iso_19650_cde`, `bki_benchmarks`, `hoai_2021_fees` and
  `lv_leistungsverzeichnis_quality`
- A six-step onboarding wizard: company profile, HOAI scope, BIM capability,
  standards compliance, cost data and review
- The `residential-berlin` demo project
- BIM-Cluster Hessen teal and grey for co-branding

No modules are hidden and no new rule classes ship with the pack; it switches
on rules already present in the core.

## Cost data

**No commercial cost database is bundled.** German building-cost benchmark
publications are licensed products, and redistributing one inside an AGPL pack
is not something their terms allow.

The `bki_benchmarks` rule pack is the checks, not the figures: whether a cost
per square metre of gross floor area sits in the expected range for the
building type, whether the cost-group shares look plausible, whether a
regional factor and a price index reference date have been recorded. You bring
the benchmark figures you are licensed to use, and the rules tell you when a
plan drifts away from them.

## Regional cost data

No Hessen-specific CWICR region is published yet, so the pack preloads
`cwicr-de-berlin` and relies on the regional factor rule for Hessen. When a
Frankfurt snapshot ships, it becomes available in the marketplace without a
pack change.

## Standards referenced

- DIN 276:2018-12 cost groups
- GAEB DA XML 3.3, exchange phases X83, X84 and X86
- VOB/A, VOB/B and VOB/C 2019
- ISO 19650-1:2018 and ISO 19650-2:2018
- HOAI 2021 service phases

These are referenced for interoperability and compliance checking. Cost-group
and phase numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "BIM-Cluster Hessen", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=bimhessen-de openconstructionerp serve
```

## License

AGPL-3.0-or-later, same as the OpenConstructionERP core. The BIM-Cluster
Hessen name and brand colours are used under partnership agreement.
