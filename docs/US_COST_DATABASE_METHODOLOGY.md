# US Resource-Based Cost Database — Methodology & Integration Guide

**Audience:** OCERP developers and data integrators  
**Last updated:** 2026-05-15  
**Related:** `docs/US_COST_DATABASE_PILOT.md` (pilot batch)  
**Related:** `docs/validation_report.md` (pilot validation results)  
**Quick reference:** For API-focused import guides (CSV/Excel/JSON bulk upload), see [`docs/cost-database-import.md`](cost-database-import.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [How We Built the Pilot: Process Walkthrough](#2-how-we-built-the-pilot-process-walkthrough)
3. [OCERP Cost Database Architecture](#3-ocerp-cost-database-architecture)
4. [CostItem Schema Reference](#4-costitem-schema-reference)
5. [The Resource-Based Costing Method](#5-the-resource-based-costing-method)
6. [How to Determine What Cost Items Are Needed](#6-how-to-determine-what-cost-items-are-needed)
7. [External Cost Data Sources](#7-external-cost-data-sources)
8. [Source-to-Schema Mapping Reference](#8-source-to-schema-mapping-reference)
9. [Classification Systems](#9-classification-systems)
10. [Step-by-Step: Building a New Regional Database](#10-step-by-step-building-a-new-regional-database)
11. [Validation & Quality Assurance](#11-validation--quality-assurance)
12. [Importing Data into OCERP](#12-importing-data-into-ocerp)

---

## 1. Overview

OCERP's cost database stores **resource-based cost items** — each item represents a unit of construction work (e.g., "Bulk excavation, common earth, machine") with a total rate **decomposed into labor, material, and equipment components**. This decomposition enables:

- **Transparent costing** — estimators see *why* a rate is what it is, not just a number
- **Regional adaptation** — swap labor wages or material prices for a different market without rebuilding from scratch
- **Cross-validation** — compare calculated rates against bid prices to catch errors
- **Sensitivity analysis** — model cost impacts of wage changes, material price swings, or equipment selection

This guide documents:

- How we built the USA_TENNESSEE pilot from real government and market data
- The OCERP cost database architecture and schema
- How to evaluate what cost items are needed for a given project type
- How to find, extract, and map data from every major US cost source
- How to build a new regional database from scratch

---

## 2. How We Built the Pilot: Process Walkthrough

The pilot batch of 12 sitework cost items (Nashville, TN) was built through this process:

### Phase 1: Identify Required Items (Scope Definition)

Starting from the TCG Brentwood Sitework project scope, we identified 12 items across four categories:

| Category | Items | MasterFormat Division |
|----------|-------|----------------------|
| Demolition | 4 (house, garage, concrete, asphalt) | 02 — Existing Conditions |
| Excavation & Grading | 4 (bulk, trench, grading, fill) | 31 — Earthwork |
| Stormwater | 2 (French drain, infiltration pit) | 33 — Utilities |
| Utilities | 2 (water, sewer service lines) | 33 — Utilities |

Each item was assigned a human-readable code (e.g., `DEM-HSE-01`, `EXC-BLK-01`) and a unit of measurement based on industry convention for that work type.

### Phase 2: Source Research

Three government free sources provided the foundational data:

| Source | What It Provided | How We Used It |
|--------|-----------------|----------------|
| **USACE EP 1110-1-8** (Region 3 Southeast, 2022 ed.) | Equipment hourly rates (ownership + operating) | Machine cost components in every cost item |
| **BLS OEWS** (May 2024, Nashville MSA #34980) | Mean hourly wages by occupation (SOC codes) | Labor cost components |
| **TDOT Average Bid Prices** (2024) | Real bid prices for validation | Cross-check: our calculated rates vs. market reality |

Material rates were compiled from local Nashville market estimates (Home Depot, Lowe's, regional suppliers).

### Phase 3: Component Decomposition

For each cost item, we determined:

1. **What crew and equipment are needed** — e.g., house demolition needs 1 excavator operator + 2 laborers + hydraulic excavator with grapple
2. **Productivity rates** — how many hours of each resource per unit of work (e.g., 0.06 equipment-hrs/SF for house demolition)
3. **Material quantities** — e.g., 0.003 dumpster rentals per SF, 0.015 tons of debris per SF

Then computed each component cost as `quantity × unit_rate` and the total rate as `sum(component_costs)`.

**Example — DEM-HSE-01 (House Demolition):**

```
rate = sum(components.cost) = $10.33/SF

Component breakdown:
  Labor:     0.12 hrs/SF × $22.45/hr  = $2.69  (Construction Laborers, BLS 47-2061)
  Equipment: 0.06 hrs/SF × $73.58/hr  = $4.41  (Excavator 30T, USACE EXC-30T)
  Material:  0.003 EA/SF × $650/EA    = $1.95  (Dumpster 30-yd)
  Material:  0.015 ton/SF × $85/ton   = $1.28  (Debris disposal)
```

### Phase 4: Validation

Validated two ways:

1. **Component math**: `abs(rate - sum(components.cost)) < 0.01` for all 12 items
2. **TDOT cross-comparison**: Our rates vs. TDOT bid prices. Where scope is comparable (French drain: +6.4% variance), our rates are within ±10%. Where scope differs (residential service vs. highway sewer: -86%), the variance is expected and documented.

Result files:

```
data/
├── usace_equipment_rates.json   # 14 equipment types from USACE
├── bls_labor_wages.json         # 8 occupations from BLS
├── material_rates.json           # 14 material costs
├── tdot_bid_prices.json          # 14 TDOT bid items for validation
└── us_tn_sitework_costs.json    # 12 CostItems with 78 components
```

---

## 3. OCERP Cost Database Architecture

### 3.1 Module Structure

```
backend/app/modules/costs/
├── models.py           # CostItem ORM model (oe_costs_item table)
├── schemas.py          # Pydantic request/response schemas
├── repository.py      # Database queries (search, bulk ops, category tree)
├── service.py         # Business logic layer
├── router.py           # FastAPI routes (REST API)
├── matcher.py          # CWICR text/semantic matcher
├── vector_adapter.py   # Vector search adapter (LanceDB embedded or Qdrant)
├── permissions.py      # Role-based access control
├── events.py           # Event bus integration
├── translations/       # 16-locale localization JSON files
└── manifest.py         # Module registration
```

### 3.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rate storage | `String(50)` | SQLite float precision safety; parsed to float on read. PostgreSQL is the production DB, SQLite is the zero-config dev fallback |
| Currency fallback | 3-tier chain | Explicit → region map → `"EUR"` default. Handles legacy CWICR rows with empty currency |
| Component type | Free-form JSON list | Supports `labor`, `material`, `equipment`, `subcontractor`, `operator`, `electricity`, `other` |
| Classification | Free-form dict | Supports DIN 276, MasterFormat, UniFormat, NRM, and any other standard simultaneously |
| Uniqueness | `(code, region)` | Same code allowed in different regions. No upsert on bulk import — duplicates silently skipped |
| Region format | `COUNTRYCODE_CITY` | Uppercase, underscore-delimited: `USA_TENNESSEE`, `DE_BERLIN`, `GB_LONDON` |
| Search pagination | Keyset cursor | O(1) page fetches; total count cached for 60 min |
| Lite mode | `?lite=true` | Strips 31KB `components` array for list views; `components_count` preserves "has breakdown" hint |

### 3.3 API Endpoints Summary

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| GET | `/costs/` | Search/filter cost items | Public |
| GET | `/costs/autocomplete/` | Fast text autocomplete | Public |
| GET | `/costs/{id}` | Get single item by UUID | Public |
| POST | `/costs/` | Create single item | Editor+ |
| PATCH | `/costs/{id}` | Update item | Editor+ |
| DELETE | `/costs/{id}` | Delete item | Manager+ |
| POST | `/costs/bulk/` | Bulk import JSON array | Editor+ |
| POST | `/costs/import/file/` | Import from Excel/CSV | Editor+ |
| DELETE | `/costs/actions/clear-region/{region}` | Wipe all items in a region | Admin |
| GET | `/costs/regions/` | List distinct regions | Public |
| GET | `/costs/regions/stats/` | Region row counts | Public |
| POST | `/costs/match/` | CWICR text matcher | Public |
| POST | `/costs/match-from-position/` | Match from BOQ position | Public |

### 3.4 Catalog Module (`backend/app/modules/catalog/`)

After cost items are imported, their component resources can be extracted into the **Resource Catalog** for reuse in assemblies and the BOQ editor.

```
backend/app/modules/catalog/
├── models.py           # CatalogResource ORM model (oe_catalog_resource table)
├── schemas.py          # Pydantic request/response schemas
├── repository.py       # Database queries (search, stats, bulk ops)
├── service.py          # Business logic including extraction from cost items
├── router.py           # FastAPI routes (REST API)
├── permissions.py      # Role-based access control (catalog.extract requires Manager+)
└── manifest.py         # Module registration (depends on oe_costs)
```

**Key concept:** The Resource Catalog stores **leaf resources** — individual materials, equipment items, labor rates, and operators — extracted from the `components` arrays of cost items. These resources can then be referenced by assemblies and applied directly to BOQ positions.

**Extraction workflow:**
1. Import cost items with `components[]` arrays into `oe_costs_item`
2. Run `CatalogResourceService.import_region_from_costs(region)` or `POST /catalog/extract/`
3. Components are aggregated by `(code, type)`, averages computed, and inserted into `oe_catalog_resource`
4. Extracted resources appear in the catalog UI under their region tab (e.g. `USA_TENNESSEE`)

> **Note:** The "My Catalog" tab on `/catalog` only shows `region='CUSTOM'` resources. Extracted regional resources appear as a separate region tab.

---

## 4. CostItem Schema Reference

### 4.1 Database Model (`oe_costs_item`)

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | PK | auto | |
| `code` | `String(100)` | NO | — | Unique per region. E.g. `"DEM-HSE-01"` or `"03.330.10"` |
| `description` | `Text` | NO | — | Primary human-readable description |
| `descriptions` | `JSON` | NO | `{}` | Localized: `{"en": "House demolition", "de": "Haushaltabbruch"}` |
| `unit` | `String(20)` | NO | — | Measurement unit: `SF`, `CY`, `LF`, `EA`, `hr`, `m`, `m2`, `m3`, `kg`, `pcs` |
| `rate` | `String(50)` | NO | — | Unit rate stored as string for SQLite compatibility |
| `currency` | `String(10)` | NO | `""` | ISO 4217 code. Resolved from region if empty |
| `source` | `String(50)` | NO | `"cwicr"` | Data provenance: `cwicr`, `rsmeans`, `manual`, `file_import`, `custom` |
| `classification` | `JSON` | NO | `{}` | Multi-standard: `{"masterformat": "03 30 00", "din276": "330"}` |
| `components` | `JSON` | NO | `[]` | Resource breakdown: `[{type, name, quantity, unit_rate, cost, unit}]` |
| `tags` | `JSON` | NO | `[]` | Searchable: `["demolition", "sitework", "nashville"]` |
| `region` | `String(50)` | YES | `None` | E.g. `USA_TENNESSEE`, `DE_BERLIN` |
| `is_active` | `Boolean` | NO | `True` | Soft-delete |
| `metadata_` | `JSON` | NO | `{}` | Column name `metadata`; arbitrary key-value store |

**Unique constraint:** `uq_costs_code_region` on `(code, region)`

### 4.2 Component Schema

Each entry in the `components` array follows this structure:

```json
{
  "type": "labor",              // "labor" | "material" | "equipment" | "subcontractor" | "other"
  "name": "Construction Laborers (SOC 47-2061)",  // Descriptive name
  "quantity": 0.12,             // Quantity per parent unit
  "unit_rate": 22.45,           // Rate per component unit
  "cost": 2.69,                 // quantity × unit_rate (MUST sum to parent rate)
  "unit": "hr",                 // Component unit (hr, SF, CY, EA, ton, etc.)
  "code": "LAB-2061"            // Required for catalog extraction; optional otherwise. Auto-generated by import script if missing
}
```

**Validation rule:**

```python
assert abs(rate - sum(c["cost"] for c in components)) < 0.01
```

The parent `rate` must equal the sum of all component `cost` values within $0.01. This is enforced by the import script and should be validated before any bulk import.

### 4.3 Classification Dict

The `classification` field stores one or more classification standard codes:

```json
{
  "division": "02",
  "section": "4100",
  "category": "Selective Demolition",
  "masterformat": "02 41 00",
  "uniformat": "G2020"
}
```

OCERP uses `collection → department → section → subsection` for the CWICR 4-level tree, and arbitrary keys like `masterformat`, `din276`, `nrm` for standard classification codes.

### 4.4 Metadata Dict

The `metadata_` field stores arbitrary extension data:

```json
{
  "labor_hours": 0.12,
  "equipment_hours": 0.06,
  "data_sources": ["USACE EP 1110-1-8", "BLS OEWS May 2024"],
  "validation_status": "pilot",
  "tdot_comparison": {
    "tdot_item": "203-01",
    "tdot_rate_2024": 21.42,
    "variance_pct": -41.9
  }
}
```

---

## 5. The Resource-Based Costing Method

### 5.1 What Is Resource-Based Costing?

Resource-based costing decomposes a unit rate into its constituent resources:

```
total_rate = Σ(labor_costs) + Σ(equipment_costs) + Σ(material_costs)
           = Σ(quantity_i × unit_rate_i) for each component i
```

This differs from **unit-price estimating** (a single rate per unit of work with no breakdown) and **parametric estimating** (rate derived from building characteristics like $/SF).

### 5.2 Why Resource-Based?

| Advantage | Explanation |
|-----------|-------------|
| **Transparency** | Estimators see *why* a rate is $10.33/SF, not just the bottom line |
| **Regional adaptation** | Swap Nashville labor wages for Denver wages → rates update automatically |
| **Time adjustment** | Update equipment rates from USACE 2022 to 2026 → costs adjust |
| **Cross-validation** | Compare calculated rates against TDOT/RSMeans bid prices |
| **Sensitivity analysis** | Model impact of wage changes, material price volatility, equipment selection |
| **Audit trail** | Every component references its source (BLS SOC code, USACE equipment code, market rate) |

### 5.3 Productivity Rates

The critical input is the **productivity rate** — how many hours of each resource are needed per unit of work. Sources for productivity rates:

| Source | Type | Best For |
|--------|------|----------|
| RSMeans | Published manhours/unit | General building |
| Craftsman NCE | Published manhours/unit | Residential/light commercial |
| Richardson Engineering | Published manhours/unit | Heavy civil/industrial |
| USACE EP 1110-1-8 | Equipment hours/unit (derived) | Government work |
| DOT standard specifications | Implicit in bid items | Highway/infrastructure |
| Historic project data | Your own records | Project-specific |
| Crew analysis | Engineering judgment | Custom assemblies |

### 5.4 Component Decomposition Template

For each cost item, follow this template:

```
1. Define the scope of work (what's included/excluded)
2. Identify the crew composition:
   - Which trades? → BLS SOC codes → labor hourly rate
   - How many workers per crew? → labor hours per unit
3. Identify the equipment:
   - Which machines? → USACE/FEMA equipment code → equipment hourly rate
   - How many hours per unit? → equipment hours per unit
4. Identify the materials:
   - What materials? → material code → material unit price
   - What quantity per unit? → material quantity per parent unit
5. Add incidentals:
   - Dumpster rentals, water, marking paint, silt fence, etc.
6. Compute:
   component_cost = quantity × unit_rate
   total_rate = round(sum(component_costs), 2)
7. Validate:
   abs(total_rate - sum(component_costs)) < 0.01
8. Cross-check against bid prices
```

### 5.5 Example: French Drain (SW-FRN-01)

**Scope:** Trench excavation, geotextile wrap, #57 stone fill, 4" perforated PVC pipe, backfill, and compaction. Per linear foot.

**Crew & Equipment:**
- Operating Engineer (excavator operator, SOC 47-2073): 0.08 hr/LF × $25.58/hr
- Pipelayer (pipe installation, SOC 47-2151): 0.10 hr/LF × $22.77/hr
- Construction Laborer (backfill/compaction, SOC 47-2061): 0.10 hr/LF × $22.45/hr
- Excavator 20-ton: 0.08 hr/LF × $60.94/hr
- Vibratory Roller 5.2-ton: 0.04 hr/LF × $30.73/hr

**Materials:**
- 4" PVC perforated pipe: 1.05 LF/LF × $3.50/LF (5% waste allowance)
- #57 stone: 0.08 CY/LF × $45.00/CY
- Geotextile fabric: 6.0 SF/LF × $0.85/SF
- Sand bedding: 0.03 CY/LF × $35.00/CY
- PVC fittings: 1.00 LF/LF × $1.88/LF

**Result:**
```
rate = $28.00/LF = 2.05 + 2.28 + 2.25 + 4.88 + 1.23 + 3.68 + 3.60 + 5.10 + 1.05 + 1.88
```

**Validation:** TDOT 2024 average bid price for Filter Cloth Underdrain (Item 710-04) = $26.31/LF. Variance: +6.4%.

---

## 6. How to Determine What Cost Items Are Needed

### 6.1 Scope-Driven Approach

**Start from the project scope of work, not from available data sources.**

1. **Identify the project type:** Sitework? Building? Highway? Utility? Each type maps to specific CSI MasterFormat divisions.

2. **List work items from the scope:**
   - For sitework: demolition, earthwork, stormwater, utilities
   - For building: foundations, structure, envelope, MEP, finishes
   - For highway: earthwork, paving, drainage, traffic, landscaping

3. **Map each work item to a cost item code** using the project's specification or the estimator's work breakdown structure.

4. **Validate coverage:** For each MasterFormat division in the project, ensure the cost database has items covering 80%+ of the estimated value.

### 6.2 MasterFormat Division Coverage for Sitework

| Division | Name | Key Items |
|----------|------|-----------|
| 02 | Existing Conditions | Demolition, site assessment, hazardous material survey |
| 31 | Earthwork | Excavation, fill, grading, compaction, dewatering |
| 32 | Exterior Improvements | Paving, landscaping, fencing, irrigation |
| 33 | Utilities | Water, sewer, storm drain, gas, electric, communications |
| 34 | Transportation | Roadways, bridges, rail, signage |

### 6.3 Project-Type Templates

When starting a new regional database, begin with a project-type template:

**Sitework (Residential Subdivision — 20 items):**
```
02 41 00 — Demolition (4): house, garage, concrete, asphalt removal
31 23 00 — Excavation (4): bulk, trench, grading, fill
33 46 00 — Stormwater (2): French drain, infiltration pit
33 11 00 — Water utility (1): water service line
33 30 00 — Sewer utility (1): sewer service line
31 25 00 — Erosion control (4): silt fence, construction entrance, stabilization, mulch
32 12 00 — Paving (2): asphalt base, asphalt surface
32 31 00 — Fencing (2): chain-link fence, temporary construction fence
```

**Heavy Highway (30+ items):**
- Division 31 items for cut/fill/haul
- TDOT/CALTRANS standard bid items for paving, drainage, striping
- MORE items from utility relocation

### 6.4 Coverage Analysis Method

After building a cost database for a region, verify coverage:

1. **By division**: Does the database have items for every relevant MasterFormat division?
2. **By value**: Do the top 20 items by estimated project value have cost entries?
3. **By bid item**: Can 80%+ of the project's bid items be mapped to cost entries?
4. **By source**: Are all components (labor, material, equipment) sourced from current data?

### 6.5 Prioritization When Starting a New Region

When building a new regional database from scratch:

1. **Start with labor, equipment, and material rate tables** — these are the building blocks
2. **Build the highest-value items first** — excavation, concrete, and pipe work represent 60-70% of sitework value
3. **Validate each batch against local bid prices** — TDOT, CALTRANS, etc.
4. **Add detail progressively** — first batch may have simplified components; later batches add variants, alternates, and more detail

---

## 7. External Cost Data Sources

Sources are organized into three tiers: **Government Free** (authoritative, no cost), **Commercial Subscription** (comprehensive, paid), and **Industry Free/Low-Cost** (partial, accessible).

### 7.1 Government Free Sources

#### 7.1.1 USACE EP 1110-1-8 — Equipment Ownership & Operating Rates

| Attribute | Value |
|-----------|-------|
| **What** | Hourly equipment rates (ownership + operating) by machine type, size, condition |
| **Regions** | 12 US regions (Northeast through Pacific) |
| **Update** | Sporadic (current edition 2022) |
| **Access** | Free PDF download |
| **URL** | https://www.usace.army.mil/Missions/Cost-Engineering/EP1110-1-8/ |

**Our use:** Equipment cost components in every cost item. The 2022 Region 3 (Southeast) data was parsed and stored in `data/usace_equipment_rates.json`.

**Limitations:** Data is from 2011 with 2022 rate adjustments. Does not include operator labor (separate BLS wage). Rates are machine-only.

**Better alternative:** FEMA Schedule of Equipment Rates (annual updates, ~530 items, national scope):
- URL: https://www.fema.gov/sites/default/files/documents/fema_pa_schedule-equipment-rates_2025.pdf
- Also on data.gov as dataset FEMA-0359

#### 7.1.2 BLS OEWS — Occupational Employment & Wage Statistics

| Attribute | Value |
|-----------|-------|
| **What** | Mean/median hourly and annual wages by SOC occupation code, by metro area |
| **Regions** | National, state, 400+ metro areas |
| **Update** | Annual (May data, released ~18 months after) |
| **Access** | Free API (v2.2) and downloadable CSV/XLSX |
| **URL** | https://www.bls.gov/oes/tables.htm |
| **API** | https://www.bls.gov/bls/api_features.htm |

**Our use:** Labor cost components. Nashville MSA (34980) May 2024 data stored in `data/bls_labor_wages.json`.

**Key construction SOC codes:**

| SOC Code | Occupation | Typical Use |
|----------|-----------|-------------|
| 47-2061 | Construction Laborers | Ground crew, cleanup, manual labor |
| 47-2073 | Operating Engineers | Equipment operators |
| 47-2151 | Pipelayers | Pipe installation |
| 47-2051 | Cement Masons | Concrete work |
| 47-2031 | Carpenters | Formwork, woodwork |
| 47-2111 | Electricians | Electrical utility work |
| 47-2152 | Plumbers | Water/sewer connections |
| 37-3013 | Tree Trimmers | Clearing, site prep |
| 47-2211 | Ironworkers | Structural steel, rebar |

**Limitations:** Mean wages, not prevailing (Davis-Bacon) wages. For federally-funded projects, use Davis-Bacon determinations instead.

#### 7.1.3 Davis-Bacon Wage Determinations

| Attribute | Value |
|-----------|-------|
| **What** | Legally binding prevailing wage rates by county, by construction type |
| **Regions** | County-level for all US states/territories |
| **Update** | Annual general determinations + modifications |
| **Access** | Free on SAM.gov |
| **URL** | https://sam.gov (Wage Determinations tab) |

**When to use:** Davis-Bacon rates are **mandatory** for federally-funded construction projects over $2,000. They're typically 25-40% higher than BLS mean wages because they reflect union/collective bargaining rates.

**How to extract:** No bulk API. Determinations are individual HTML pages on SAM.gov. A scraper must enumerate WD numbers by state + construction type (Building, Heavy, Highway, Residential).

#### 7.1.4 State DOT Bid Prices

| Attribute | Value |
|-----------|-------|
| **What** | Average unit bid prices from awarded contracts |
| **Regions** | State-wide (some states provide district-level) |
| **Update** | Annual or quarterly |
| **Access** | Free from state DOT websites |
| **Best states** | TN, CA, FL, WI, TX, NY (via DOTestimate) |

**Our use:** Cross-validation of our calculated rates against real market prices. TDOT 2024 data stored in `data/tdot_bid_prices.json`.

**State DOT URLs:**

| State | URL | Format |
|-------|-----|--------|
| Tennessee | https://www.tn.gov/tdot/.../transportation-construction-price-information.html | Excel/PDF |
| California | https://sv08data.dot.ca.gov/ | Interactive web DB |
| Florida | https://www.fdot.gov/fpo/fpc/reports/historicalitemaveragecost | Power BI |
| Wisconsin | https://wisconsindot.gov/.../average-unit-price.pdf | PDF |
| Texas | https://www.txdot.gov/.../average-low-bid-prices.html | Excel |
| New York | Via DOTestimate.com | Web platform |

**Key insight:** DOT bid prices are the **gold standard for sitework/civil unit costs** because they reflect actual market conditions. However, they are composite rates (labor + material + equipment + overhead + profit bundled together), not resource-decomposed. Use them for **validation**, not as component sources.

### 7.2 Commercial Subscription Sources

#### 7.2.1 RSMeans (Gordian)

| Attribute | Value |
|-----------|-------|
| **What** | 92,000+ unit cost line items with labor/material/equipment breakdowns, crew compositions, daily outputs, and city cost indexes |
| **Regions** | National average + 970+ city adjustment factors |
| **Update** | Quarterly (Jan, Apr, Jul, Oct) |
| **Cost** | $2,195/yr (single dataset) to $35,752/yr (complete) |
| **Format** | Online, CD (CostWorks), print, API (enterprise) |
| **URL** | https://www.rsmeans.com |

**Why RSMeans matters:** It's the industry standard for US construction cost data. Its structure maps almost perfectly to OCERP's `components` field (labor + material + equipment breakdown, crew compositions). The MasterFormat line numbering maps directly to `classification.masterformat`.

**Mapping:**

```
RSMeans line number  → code (e.g., "RSM-033053.40-3950")
RSMeans description   → description
RSMeans unit          → unit
RSMeans bare cost     → rate
RSMeans city index    → metadata.city_cost_index
RSMeans crew details  → components (labor, material, equipment)
RSMeans CSI division  → classification.masterformat
```

**Limitation:** RSMeans data is copyrighted and *cannot be freely redistributed*. For OCERP, RSMeans could be offered as a premium data connector that users subscribe to separately, or used as a reference/benchmarking source during development.

#### 7.2.2 Craftsman National Construction Estimator (NCE)

| Attribute | Value |
|-----------|-------|
| **What** | 6,000+ unit cost items with manhours, crew sizes, labor/material/total costs |
| **Regions** | National with area modification factors |
| **Update** | Annual (74th edition = 2026) |
| **Cost** | $59 (eBook) / $118 (paperback) |
| **Format** | PDF, print, National Estimator Cloud, API (licensing available) |
| **URL** | https://craftsman-book.com/national-construction-estimator |

**Why NCE matters:** Most affordable comprehensive construction cost book. API access available for integration. Good for residential/light commercial. Directly maps to OCERP components.

#### 7.2.3 ENR Construction Cost Index

| Attribute | Value |
|-----------|-------|
| **What** | Cost escalation indexes (CCI, BCI) + 66 material prices in 20 cities |
| **Regions** | 20 US cities + national average |
| **Update** | Monthly |
| **Cost** | $99.99/yr (digital); Cost Data Dashboard: ~$2,000/yr |
| **URL** | https://www.enr.com/economics |

**Why ENR matters:** Not a unit cost database, but essential for **time-adjusting historical costs** to current dollars. The CCI and BCI are the most widely cited construction inflation indexes. The 66-city material price data (concrete, steel, lumber) can populate individual `CostItem` entries with `source: "enr_materials"`.

#### 7.2.4 Richardson Engineering (via Eos Group)

| Attribute | Value |
|-----------|-------|
| **What** | 190,000+ line items across 520 phases. Heavy civil/industrial focus. Manhours, materials, equipment, subcontractor pricing |
| **Regions** | 130+ North American labor markets; 30+ international |
| **Cost** | ~$3,000–$5,000/yr |
| **URL** | https://eosgroup.com/richardson-engineering-database/ |

**Why Richardson matters:** Best source for heavy civil and industrial/process plant estimating. 130+ labor market rates are more granular than BLS OEWS. The 520 phase structure aligns with sitework scope.

### 7.3 Industry Free / Low-Cost Sources

#### 7.3.1 ICC Building Valuation Data (BVD)

| Attribute | Value |
|-----------|-------|
| **What** | $/SF construction costs by occupancy group and construction type |
| **Regions** | National with regional modifiers |
| **Update** | Semi-annual |
| **Cost** | Free with ICC membership (~$200/yr) |
| **URL** | https://www.iccsafe.org/.../building-valuation-data/ |

**Use case:** Conceptual/square-foot estimating only. Not suitable for detailed estimating but useful for order-of-magnitude validation.

#### 7.3.2 Marshall & Swift / Cotality

| Attribute | Value |
|-----------|-------|
| **What** | Square-foot and unit-in-place replacement costs for insurance/tax assessment |
| **Regions** | US and Canada with local multipliers |
| **Cost** | $100–$1,000+/yr depending on product |
| **URL** | https://www.cotality.com/products/marshall-swift |

**Use case:** Building valuation, not sitework. Segregated cost breakdowns could populate OCERP `components` for building-level items.

---

## 8. Source-to-Schema Mapping Reference

### 8.1 Universal Mapping Template

Every external source maps to the same OCERP `CostItemCreate` schema. Here's the universal mapping:

```
source item identifier     → code
source item description    → description
source unit                 → unit
source rate/price           → rate
source geographic region    → region (transformed to COUNTRYCODE_CITY)
source currency             → currency (ISO 4217)
source classification       → classification (transformed to standard keys)
source labor/equip/material → components (resource-based decomposition)
source metadata             → metadata (provenance, effective dates, source URLs)
source tags                 → tags
source identifier           → source field ("usace", "bls_oews", "rsmeans", etc.)
```

### 8.2 Per-Source Mapping Details

#### USACE / FEMA Equipment Rates → CostItem

```json
{
  "code": "USACE-EXC-30T",
  "description": "Hydraulic Excavator, Crawler, 30-ton class (CAT 326F, 0.69 CY)",
  "unit": "hr",
  "rate": 73.58,
  "currency": "USD",
  "source": "usace_ep1110",
  "region": "USA_SOUTHEAST",
  "classification": {"masterformat": "01 54 00", "equipment_type": "excavator"},
  "components": [
    {"type": "equipment", "name": "Ownership cost (depreciation + FCCM)", "quantity": 1, "unit_rate": 20.77, "cost": 20.77, "unit": "hr"},
    {"type": "equipment", "name": "Operating cost (fuel, tires, repairs)", "quantity": 1, "unit_rate": 52.81, "cost": 52.81, "unit": "hr"},
    {"type": "labor", "name": "Operator (Operating Engineer, SOC 47-2073)", "quantity": 1, "unit_rate": 25.58, "cost": 25.58, "unit": "hr"}
  ],
  "tags": ["equipment", "excavator", "heavy-civil", "usace"],
  "metadata": {
    "ownership_rate": 20.77,
    "operating_rate": 52.81,
    "condition": "average",
    "effective_date": "2022-12-01",
    "usace_region": "3"
  }
}
```

**Note:** The USACE rate is machine-only ($73.58/hr). Operator labor ($25.58/hr from BLS) is added as a separate component to get the fully-burdened rate of $99.16/hr.

#### BLS OEWS Labor Rates → CostItem

```json
{
  "code": "BLS-47-2061",
  "description": "Construction Laborers — Nashville-Davidson-Murfreesboro-Franklin, TN MSA",
  "unit": "hr",
  "rate": 22.45,
  "currency": "USD",
  "source": "bls_oews",
  "region": "USA_TENNESSEE",
  "classification": {"soc": "47-2061", "masterformat": "01 54 00"},
  "components": [],
  "tags": ["labor", "general", "construction", "nashville"],
  "metadata": {
    "soc_code": "47-2061",
    "msa_code": "34980",
    "mean_hourly_wage": 22.45,
    "median_hourly_wage": 18.96,
    "effective_date": "2024-05",
    "data_type": "mean"
  }
}
```

#### TDOT Bid Prices → CostItem (Validation Only)

Bid prices are **composite rates** (labor + material + equipment + overhead + profit). They should NOT be decomposed into components unless you have the component breakdown from another source. Instead, store them as **reference items** with `source: "tdot_bid"` and use for cross-validation:

```json
{
  "code": "TDOT-710-04",
  "description": "Filter Cloth Underdrain (With Pipe) [French Drain]",
  "unit": "LF",
  "rate": 26.31,
  "currency": "USD",
  "source": "tdot_bid",
  "region": "USA_TENNESSEE",
  "classification": {"tdot_item": "710-04", "masterformat": "33 46 00"},
  "components": [],
  "tags": ["validation", "french_drain", "stormwater", "tdot"],
  "metadata": {
    "tdot_item_no": "710-04",
    "year": 2024,
    "is_composite": true,
    "includes_overhead_profit": true
  }
}
```

#### RSMeans → CostItem (Conceptual Mapping)

```json
{
  "code": "RSM-312313.10-0400",
  "description": "Excavation, trench, common earth, 0-4 ft deep, machine",
  "unit": "CY",
  "rate": 18.50,
  "currency": "USD",
  "source": "rsmeans",
  "region": "USA_USD",
  "classification": {"masterformat": "31 23 13.10", "uniformat": "G10"},
  "components": [
    {"type": "labor", "name": "Crew C-1 (1 laborer)", "quantity": 0.35, "unit_rate": 22.45, "cost": 7.86, "unit": "hr"},
    {"type": "equipment", "name": "Hydraulic excavator 3/4 CY", "quantity": 0.35, "unit_rate": 25.49, "cost": 8.92, "unit": "hr"},
    {"type": "material", "name": "No material", "quantity": 0, "unit_rate": 0, "cost": 0, "unit": "CY"}
  ],
  "tags": ["excavation", "trench", "earthwork", "rsmeans"],
  "metadata": {"city_cost_index": 1.0, "rsmeans_line": "312313.10-0400"}
}
```

### 8.3 Common Source Tags

Use these `source` field values consistently:

| Source Tag | Description |
|-----------|-------------|
| `usace_ep1110` | USACE EP 1110-1-8 equipment rates |
| `fema_equipment` | FEMA Schedule of Equipment Rates |
| `bls_oews` | BLS Occupational Employment & Wage Statistics |
| `davis_bacon` | Davis-Bacon prevailing wage determinations |
| `tdot_bid` | Tennessee DOT average bid prices |
| `caltrans_bid` | California DOT contract cost data |
| `fdot_bid` | Florida DOT historical item average cost |
| `dot_bid` | Generic state DOT bid prices |
| `rsmeans` | RSMeans / Gordian construction cost data |
| `craftsman_nce` | Craftsman National Construction Estimator |
| `enr_index` | ENR Construction Cost Index / material prices |
| `marshall_swift` | Marshall & Swift / Cotality valuation data |
| `richardson` | Richardson Engineering (Eos Group) |
| `icc_bvd` | ICC Building Valuation Data |
| `cwicr` | DDC CWICR database (legacy) |
| `manual` | Manually compiled from multiple sources |
| `file_import` | Imported from user-uploaded spreadsheet |
| `custom` | User-created custom items |

---

## 9. Classification Systems

### 9.1 MasterFormat (CSI)

The primary classification standard for US construction cost data. 50 divisions (00-49), each with hierarchical section numbers.

**Key sitework divisions for OCERP:**

| Division | Name | Typical Items |
|----------|------|---------------|
| 01 | General Requirements | Project management, temporary facilities |
| 02 | Existing Conditions | Demolition, site assessment, environmental remediation |
| 31 | Earthwork | Excavation, fill, grading, compaction, dewatering |
| 32 | Exterior Improvements | Paving, landscaping, fencing, irrigation |
| 33 | Utilities | Water, sewer, storm drain, gas, electric, communications |
| 34 | Transportation | Roadways, bridges, rail, signage, markings |

**Mapping to `classification`:**

```json
{"masterformat": "31 23 13"}
```

### 9.2 UniFormat (CSI)

Assembly-level classification for early-stage estimating. Letter-based elements with numeric subdivisions.

**Key sitework elements:**

| Element | Name |
|---------|------|
| G10 | Site Preparation |
| G20 | Site Improvements |
| G30 | Site Civil/Mechanical Utilities |
| G40 | Site Electrical Utilities |

**Mapping to `classification`:**

```json
{"uniformat": "G30"}
```

### 9.3 Using Both Together

OCERP's `classification` dict can hold multiple standards simultaneously:

```json
{
  "division": "02",
  "section": "4100",
  "category": "Selective Demolition",
  "masterformat": "02 41 00",
  "uniformat": "G10"
}
```

The CWICR import uses `collection`, `department`, `section`, `subsection` for its 4-level tree. US items can use `masterformat` and `uniformat` alongside CWICR keys.

---

## 10. Step-by-Step: Building a New Regional Database

### 10.1 Define Scope

1. Choose the region (e.g., `USA_COLORADO`, `USA_SEATTLE`, `CA_TORONTO`)
2. Determine the project type (sitework, building, highway, utility)
3. List the MasterFormat divisions to cover
4. Estimate the number of items (start with 12-30 for a pilot)

### 10.2 Gather Source Data

| Data Need | Primary Source | Alternative | Format |
|-----------|---------------|-------------|--------|
| Equipment rates | FEMA Schedule (free, current) | USACE EP 1110-1-8 | PDF → JSON |
| Labor wages | BLS OEWS (free API) | Davis-Bacon (county-level) | CSV/XLSX → JSON |
| Material prices | Local supplier quotes | Home Depot/Lowe's web | Manual → JSON |
| Bid prices (validation) | State DOT website | DOTestimate.com | Excel/PDF → JSON |
| Productivity rates | RSMeans (paid) | Craftsman NCE (paid) | API/book → JSON |

### 10.3 Create Reference Data Files

Following the pilot structure, create in `data/`:

```python
data/
├── {region}_equipment_rates.json    # Hourly equipment rates
├── {region}_labor_wages.json         # Hourly wages by occupation
├── {region}_material_rates.json       # Material prices
├── {region}_bid_prices.json           # Validation bid prices
└── {region}_cost_items.json          # Final CostItem array (import this)
```

### 10.4 Build Cost Items

For each cost item:

1. **Identify the crew composition** (trades, count, hours)
2. **Identify the equipment** (types, hours)
3. **Identify the materials** (quantities, units)
4. **Look up unit rates** from your reference data
5. **Calculate each component cost** = quantity × unit_rate
6. **Sum component costs** = total rate
7. **Validate** rate rounds to 2 decimal places
8. **Cross-check** against bid prices (±30% tolerance for first pass)

### 10.5 Validation Checklist

Before importing:

- [ ] Every item has `rate == sum(components.cost)` within $0.01
- [ ] Every item has `region` set (e.g., `USA_TENNESSEE`)
- [ ] Every item has `currency` set (e.g., `USD`) or will be resolved from region
- [ ] Every item has `source` set (e.g., `manual`)
- [ ] Component `type` is one of: `labor`, `material`, `equipment`, `subcontractor`, `other`
- [ ] Component `quantity` and `unit_rate` are positive numbers
- [ ] Component `cost` = round(`quantity` × `unit_rate`, 2)
- [ ] No duplicate `(code, region)` pairs
- [ ] Classification codes match the intended standard (MasterFormat, etc.)
- [ ] Tags are lowercase and relevant
- [ ] Rates are in the correct unit (SF, CY, LF, EA — not SY, CF, etc.)

### 10.6 Add Region to Currency Map

In `backend/app/modules/costs/schemas.py` and `router.py`, add the new region to `_REGION_CURRENCY_FALLBACK`:

```python
"USA_TENNESSEE": "USD",
"USA_COLORADO": "USD",
```

### 10.7 Import

```bash
# Import using the recommended script
python scripts/import_tennessee_costs.py \
  --email you@example.com \
  --password "your-password" \
  --port 8000 \
  --data-dir /tmp/tn_import/tn_import_package/data
```

Or use the bulk API directly:

```bash
curl -X POST http://localhost:8000/api/v1/costs/bulk/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @data/usa_colorado_cost_items.json
```

---

## 11. Validation & Quality Assurance

### 11.1 Component Math Validation

**Rule:** `abs(rate - sum(component_costs)) < 0.01`

```python
for item in cost_items:
    total = item["rate"]
    calculated = sum(c["cost"] for c in item["components"])
    assert abs(total - calculated) < 0.01, f"{item['code']}: {total} ≠ {calculated}"
```

### 11.2 Bid Price Cross-Validation

Compare calculated rates against local DOT bid prices:

```python
variance_pct = (our_rate - tdot_rate) / tdot_rate * 100
```

**Interpretation:**

| Variance | Assessment |
|----------|------------|
| ±5% | Excellent match |
| ±10% | Good match |
| ±15-20% | Acceptable for first pass |
| ±20-30% | Needs investigation (scope differences likely) |
| > ±30% | Investigate; may be scope, productivity, or source data issues |

**Common reasons for variance:**
- Our rates are **direct cost only**; DOT prices include 15-25% overhead/profit
- DOT items often include more scope (traffic control, erosion control, mobilization)
- Scale differences: residential sitework vs. highway heavy civil
- Davis-Bacon (prevailing) wages vs. BLS (mean) wages

### 11.3 Reasonableness Checks

| Check | Method |
|-------|--------|
| Labor hours per unit | Compare to RSMeans or Craftsman NCE manhour tables |
| Equipment hours per unit | Compare to USACE productivity guides |
| Material quantities per unit | Verify against construction takeoff standards |
| Total rate per SF/CY/LF | Compare to similar items in other regions (CWICR for EUR, RSMeans for USD) |
| Component cost percentages | Labor typically 30-50%, material 30-50%, equipment 10-30% for sitework |

### 11.4 Continuity Checks

When adding items to an existing region:

- [ ] No `(code, region)` duplicates
- [ ] Units are consistent within a category (all demolition items in SF or all in CY — not mixed)
- [ ] Rate ordering is logical (house demolition > garage demolition per SF)
- [ ] New items don't clash with CWICR/imported items (search by code and description)

---

## 12. Importing Data into OCERP

### 12.1 Bulk JSON Import

The primary method for importing curated cost items:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/users/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"your-password"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/api/v1/costs/bulk/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @data/us_tn_sitework_costs.json
```

**Behavior:** Creates all items. Skips any where `(code, region)` already exists (no upsert). Returns the list of created items.

### 12.2 File Import (Excel/CSV)

For quick imports from spreadsheets:

```bash
curl -X POST http://localhost:8000/api/v1/costs/import/file/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/cost_items.xlsx"
```

**Auto-detected columns:** `code`, `description`, `unit`, `rate`/`price`, `currency`, `classification`/`din 276`/`masterformat`

**Limitations:** File import does not support `components` arrays. Use bulk JSON import for resource-based items.

### 12.3 Python Import Script

The recommended script is `scripts/import_tennessee_costs.py` which:

1. Authenticates with regular user login (`POST /users/auth/login/`)
2. Loads all JSON data files from a directory
3. Auto-generates component `code` fields if missing (required for catalog extraction)
4. Validates `rate == sum(components.cost)` for each item
5. Calls `POST /costs/bulk/`
6. Verifies items by searching the API

> **Note:** `scripts/import_cost_database.py` is the legacy script that uses demo auth on port 8082. It is deprecated for production use.

### 12.4 CWICR Catalog Import

For large CWICR regional catalogs (55K+ items per region):

```bash
# List available catalogs
curl -s http://localhost:8000/api/v1/costs/catalogues/ | python3 -m json.tool

# Load a catalog
curl -X POST http://localhost:8000/api/v1/costs/load-cwicr/DE_BERLIN \
  -H "Authorization: Bearer $TOKEN"
```

This downloads parquet data from GitHub, deduplicates, extracts components, and bulk-inserts. Source is set to `"cwicr"`.

### 12.5 Clearing a Region

To remove all items for a region before re-importing:

```bash
curl -X DELETE http://localhost:8000/api/v1/costs/actions/clear-region/USA_TENNESSEE \
  -H "Authorization: Bearer $TOKEN"
```

**This is irreversible.** Use with caution.

### 12.6 Catalog Resource Extraction

After importing cost items with `components[]` arrays, extract their individual resources into the catalog so they can be reused in assemblies and the BOQ editor.

**Why extraction matters:**
- Components without `code` fields are **silently skipped** during extraction
- Extracted resources become searchable in the catalog UI
- They can be selected directly when building assemblies or adding resources to BOQ positions
- Each resource shows avg/min/max rates and usage count across all cost items in the region

**Using the standalone script:**

```bash
cd backend
python -m app.scripts.extract_tennessee_catalog
```

**Using the API** (requires `catalog.extract` permission — Manager or Admin role):

```bash
curl -X POST http://localhost:8000/api/v1/catalog/extract/ \
  -H "Authorization: Bearer $TOKEN"
```

**Verify extraction:**

```bash
# List regions with catalog resources
curl -s http://localhost:8000/api/v1/catalog/regions/ \
  -H "Authorization: Bearer $TOKEN" | jq .

# Search Tennessee catalog resources
curl -s "http://localhost:8000/api/v1/catalog/?region=USA_TENNESSEE&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'
```

**Component `code` requirement:**

The extraction service groups components by their `code` field. If a component lacks a `code`, it is skipped:

```python
code = comp.get("code", "")
if not code:
    continue  # silently skipped
```

The import script (`scripts/import_tennessee_costs.py`) auto-generates codes in the format `TN-{TYPE}-{slug}` if missing.

---

## Appendix A: Source Comparison Matrix

| Source | Type | Data Provided | Geo | Update | Access | Cost | Best For |
|--------|------|--------------|-----|--------|--------|------|-----------|
| FEMA Equipment Rates | Gov Free | Equipment rates/hr | National | Annual | PDF | $0 | **Equipment rates (primary)** |
| BLS OEWS | Gov Free | Labor wages | National/state/metro | Annual | API/CSV | $0 | **Labor wages (primary)** |
| Davis-Bacon | Gov Free | Prevailing wages | County | Annual | HTML/PDF | $0 | **Federal project wages** |
| State DOT Bid Prices | Gov Free | Unit bid prices | State | Annual | Excel/web | $0 | **Validation benchmark** |
| ICC BVD | Member Free | $/SF by occupancy | National | Semi-annual | PDF | $0* | Conceptual estimates |
| RSMeans | Commercial | 92K+ unit costs | 970+ cities | Quarterly | Online/API | $2K-$36K/yr | Comprehensive estimating |
| Craftsman NCE | Commercial | 6K+ unit costs | National | Annual | Book/API | $59-$118/yr | Affordable estimating |
| ENR CCI/BCI | Commercial | Cost indexes, 66 materials | 20 cities | Monthly | Web | $100-$2K/yr | Escalation/trending |
| Dodge/CMD | Commercial | Project leads | US/Canada | Continuous | Web | $5K-$25K/yr | Market intelligence |
| Marshall & Swift | Commercial | $/SF replacement | US/Canada | Quarterly | Online | $100-$1K+/yr | Building valuation |
| Richardson (Eos) | Commercial | 190K+ items | 130+ markets | Quarterly | Online | $3K-$5K/yr | Heavy civil/industrial |

\* ICC BVD requires membership (~$200/yr)

## Appendix B: Region Naming Convention

OCERP supports multiple region key formats. The CWICR legacy catalogues use two conventions:

### Currency-based regions (broad markets)

Used by CWICR for national/regional price databases:

```
USA_USD           # United States (broad market, USD currency)
UK_GBP            # United Kingdom (broad market, GBP currency)
DE___DDC_CWICR    # Germany (CWICR internal identifier)
```

### Location-based regions (specific metros/states)

Used for custom or city-specific data:

```
USA_TENNESSEE     # Tennessee (state-level)
USA_COLORADO      # Colorado (state-level)
USA_SEATTLE       # Seattle metro
USA_CHICAGO       # Chicago metro
CA_TORONTO        # Toronto, Canada
DE_BERLIN         # Berlin, Germany
FR_PARIS          # Paris, France
PT_SAOPAULO       # São Paulo, Brazil
```

### Custom region guidelines

When creating new custom regions:

1. **Prefer `COUNTRYCODE_STATE`** for state-wide data: `USA_TENNESSEE`, `USA_COLORADO`
2. **Prefer `COUNTRYCODE_CITY`** for metro-specific data: `USA_SEATTLE`, `USA_CHICAGO`
3. **Avoid currency codes** in custom regions unless you're creating a broad national market
4. **Keep uppercase** and use underscores: `USA_TENNESSEE`, not `usa_tennessee` or `USA-Tennessee`
5. **Be consistent** within a region set — don't mix `USA_NASHVILLE` and `USA_TENNESSEE` for the same data

## Appendix C: Recommended Data Strategy for US Sitework

### Immediate (Free, Already Implemented)

1. **FEMA Equipment Rates** → equipment cost items (replaces USACE, more current)
2. **BLS OEWS** → labor wage items (API-accessible, annual updates)
3. **State DOT bid prices** → validation items (start with TDOT, add others as needed)
4. **Local material quotes** → manual market estimates

### Near-Term (Free, Moderate Effort)

5. **Davis-Bacon wage determinations** → prevailing wage items (requires SAM.gov scraper)
6. **Additional state DOT data** → CA (Caltrans), FL (FDOT), TX (TxDOT), WI

### Medium-Term (Paid, High Value)

7. **Craftsman NCE API** → general building costs (~$60-300/yr for data access)
8. **ENR subscription** → cost indexes and material prices for escalation

### Long-Term (Paid, Enterprise)

9. **RSMeans online** → comprehensive 92K+ item database ($2K+/yr)
10. **Richardson Engineering** → heavy civil deep data ($3K+/yr)

## Appendix D: File Structure Reference

```
OCERP/
├── data/
│   ├── usace_equipment_rates.json    # Equipment rates (Sec 7.1.1)
│   ├── bls_labor_wages.json          # Labor wages (Sec 7.1.2)
│   ├── material_rates.json            # Material prices (Sec 7.1.4 context)
│   ├── tdot_bid_prices.json           # Validation prices (Sec 7.1.4)
│   ├── us_tn_sitework_costs.json          # Final CostItem array — sitework (Sec 4)
│   └── us_tn_concrete_utilities_costs.json # Final CostItem array — concrete & utilities
├── scripts/
│   ├── import_tennessee_costs.py          # Recommended import script (Sec 12.3)
│   └── import_cost_database.py            # Legacy demo-auth script (deprecated)
├── docs/
│   ├── US_COST_DATABASE_PILOT.md          # Pilot handoff document
│   ├── US_COST_DATABASE_METHODOLOGY.md    # This document
│   ├── validation_report.md               # TDOT cross-validation results
│   └── cost-database-import.md            # CSV/Excel import guide
├── backend/app/modules/costs/
│   ├── models.py                          # CostItem ORM model (Sec 4.1)
│   ├── schemas.py                         # Pydantic schemas (Sec 4.2)
│   ├── router.py                          # REST API endpoints (Sec 3.3)
│   ├── repository.py                      # Database queries (Sec 3.2)
│   └── service.py                         # Business logic layer
└── backend/app/modules/catalog/
    ├── models.py                          # CatalogResource ORM model
    ├── service.py                         # Extraction logic (Sec 3.4, Sec 12.6)
    ├── router.py                          # Catalog REST API
    └── repository.py                      # Catalog data access
```