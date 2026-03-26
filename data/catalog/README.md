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

## Import into OpenEstimator

```bash
# From the OpenEstimator backend directory:
python -m app.scripts.seed_catalog
```

Or via the API:
```
POST /api/v1/catalog/extract
```

## Source

Data Driven Construction (DDC) CWICR Database
- 11 regional databases
- 55,719 work items per region
- 900,225 resource component rows
- https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR

## License

AGPL-3.0 (same as OpenEstimator.io)
