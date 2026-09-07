# CWICR Resource Catalog

Extracted from the CWICR Construction Cost Database (55,719 work items, 900K+ resource rows).

## Files

| File | Resources | Size | Description |
|------|-----------|------|-------------|
| `cwicr_resources_full.csv` | 7,024 | 1.1 MB | All resources combined |
| `cwicr_materials.csv` | 4,808 | 762 KB | Construction materials (concrete, steel, wood, etc.) |
| `cwicr_equipments.csv` | 1,594 | 263 KB | Equipment & machinery (cranes, excavators, trucks) |
| `cwicr_labors.csv` | 68 | 6 KB | Labor grades (workers grade 1-7, engineers) |
| `cwicr_operators.csv` | 42 | 5 KB | Machine operators (personnel per machine-hour) |
| `cwicr_electricitys.csv` | 512 | 73 KB | Electricity consumption rates |

## CSV Columns

| Column | Type | Description |
|--------|------|-------------|
| `code` | string | Unique CWICR resource code |
| `name` | string | Resource name (English) |
| `type` | string | `material`, `equipment`, `labor`, `operator`, `electricity` |
| `category` | string | Auto-classified category (see below) |
| `unit` | string | Unit of measurement (kg, m3, hrs, Machine hours, etc.) |
| `base_price` | float | Average unit price (EUR) |
| `min_price` | float | Lowest observed price |
| `max_price` | float | Highest observed price |
| `currency` | string | Always EUR |
| `usage_count` | int | How many work items reference this resource |
| `regions` | string | Comma-separated source regions |

## Material Categories (4,808 items)

| Category | Count | Examples |
|----------|-------|---------|
| Steel & Metal | 1,367 | Structural steel, reinforcement, profiles |
| General | 1,344 | Uncategorized specialty items |
| Concrete & Cement | 393 | Heavy concrete mixes, cement, mortar |
| Electrical | 263 | Cables, wires, insulating tape |
| Paint & Coatings | 223 | Oil paint, primers, enamels |
| Welding Consumables | 193 | Electrodes, welding wire |
| Wood & Timber | 173 | Softwood boards, plywood, props |
| Chemicals & Gases | 169 | Oxygen, acetylene, solvents |
| Fasteners | 133 | Bolts, nails, screws |
| Pipes & Fittings | 120 | Steel pipes, valves |
| Aggregates & Earth | 99 | Crushed rock, sand, gravel |
| Rubber & Gaskets | 88 | Technical rubber, gaskets |
| Waterproofing | 62 | Bitumen, membranes |
| Insulation | 58 | Mineral wool, thermal insulation |
| Water | 35 | Tap water, industrial water |
| Glass & Glazing | 18 | Construction glass |

## Equipment Categories (1,594 items)

| Category | Count |
|----------|-------|
| General | 846 |
| Cranes | 190 |
| Trucks & Vehicles | 132 |
| Pumps | 100 |
| Excavators | 92 |
| Hoists & Winches | 62 |
| Welding Equipment | 57 |
| Bulldozers | 36 |
| Pipe Equipment | 29 |
| Testing Equipment | 27 |
| Compressors | 23 |

## Import into OpenConstructionERP

```bash
# From the OpenConstructionERP backend directory:
python -m app.scripts.seed_catalog
```

Or via the API:
```
POST /api/v1/catalog/extract
```

## Source

Data Driven Construction (DDC) CWICR Database
- 48 regional databases
- 55,719 work items per region
- 900,225 resource component rows
- https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR

The `cwicr_*.csv` files above are an extract of the global CWICR base. The
per-region catalogues in `regions/` come from several different bases, and
they do not all share one origin. Eleven of them (`AR_DUBAI`, `DE_BERLIN`,
`ENG_TORONTO`, `FR_PARIS`, `HI_MUMBAI`, `PT_SAOPAULO`, `RU_STPETERSBURG`,
`SP_BARCELONA`, `UK_GBP`, `USA_USD`, `ZH_SHANGHAI`) are the same global base
translated and repriced per market, sharing 6,671 of 6,674 resource codes.
A file named for a city is that market's prices over the global base, not a
price book published in that country. The remaining five are separate
national bases.

## Licence and attribution

Each base derives from a cost standard published by a public sector body.
The derived data carries item descriptions, the classification tree and, in
several bases, the published code numbers. Prices are aggregates computed
across price variants and converted per market, not transcribed figures.

| Base / region | Source publication | Basis |
|---|---|---|
| Global CWICR (the 11 market catalogues and `cwicr_*.csv`) | GESN / FER / TER norm structure (CIS) | **PENDING, see note below** |
| `ZH_CHINA` | China, Beijing 2012 + Bole 2022 construction quota (Dinge) | Official government tariff |
| `TR_NATIONAL` | Turkiye, CSB national unit prices (Birim Fiyat) | Official publication, FSEK Art. 31 |
| `BR_NATIONAL` | Brazil, SINAPI analytical compositions (CAIXA/IBGE) | Open data, Decreto 7.983/2013 |
| `ES_ANDALUCIA` | Spain, Base de Costes de la Construccion de Andalucia (BCCA 2023) | Open institutional publication |
| `IT_TOSCANA` | Italy, Prezzario dei Lavori Pubblici della Toscana (edizione 2026) | CC BY 4.0, attribution below |
| `GR_NATIONAL` | Greece, analytical price lists for works (GGDE) | Public document, Law 2121/1993 |

The basis for the global CWICR base is **PENDING** and is left open rather
than assumed. It is the largest dataset here and the one base with no
written basis recorded. Settling it needs the edition of the norms used and
the terms that edition was published under. Do not read the other rows as
covering it.

### Attribution required by CC BY 4.0

"Prezzario dei Lavori Pubblici della Toscana, edizione 2026", published by
Regione Toscana, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**This work has been modified by DataDrivenConstruction.** Source items were
parsed into the CWICR canonical schema, resource components restructured,
unit labels normalised, descriptions translated into further languages, and
aggregate price columns computed. Regione Toscana does not endorse this
project or its use of the material.

### Licence of these files

The extraction and transformation code, the canonical schema and the
compilation as published here are AGPL-3.0, the same as OpenConstructionERP.
That covers this project's own contribution only. It does not override the
terms of the source publications listed above, and it does not apply to any
base whose basis is still marked pending.
