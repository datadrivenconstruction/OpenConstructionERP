# Cost Database Import — Resource-Based Costing

**Audience:** OCERP operators and end users  
**Full methodology:** For the complete guide on building regional cost databases from external sources (architecture, validation, source mapping), see [`docs/US_COST_DATABASE_METHODOLOGY.md`](US_COST_DATABASE_METHODOLOGY.md)

This guide explains how to extend OpenConstructionERP's cost database with your own data using **resource-based costing methodology**. It covers two paths:

- **Flat-row import** (`.xlsx` / `.csv` via `POST /api/v1/costs/import/file/`) — fast onboarding of an existing rate sheet
- **Recipe (assembly) import** (`POST /api/v1/costs/items` with `components[]`) — full resource-based methodology where each work item breaks down into labor + material + equipment lines

Both paths write into the same `oe_costs_item` table. Match-Elements, BOQ, and the Costs UI then see the items immediately.

---

## Method 1 — Flat-row import (Excel / CSV)

Use this when you already have a price book where each row is one priced item (no breakdown). Minimum required columns: **code**, **description**, **unit**, **rate**. Everything else is optional.

### Minimal template

```csv
code,description,unit,rate,currency,classification
LAB-CARP-01,Carpenter — journeyman labor,hr,68.50,USD,03 10 00
LAB-LAB-01,General laborer,hr,35.00,USD,01 50 00
MAT-CONC-3K,Ready-mix concrete C3000 psi,yd3,165.00,USD,03 30 00
MAT-REBAR-60,Rebar — Grade 60 #4 (1/2"),lb,0.85,USD,03 20 00
EQP-PUMP-CONC,Concrete pump truck (operated),hr,285.00,USD,01 54 00
WI-WALL-CIP-8,"Cast-in-place concrete wall, 8"" thick",sf,18.75,USD,03 30 53
```

### Recognised column aliases

The parser does case-insensitive header matching. Any of these aliases work:

| Canonical | Aliases (case-insensitive) |
|---|---|
| **code** | code, item code, cost code, item, nr, nr., no, no., #, id, position, artikelnummer, art.nr. |
| **description** | description, beschreibung, desc, text, bezeichnung, item description, name, title |
| **unit** | unit, einheit, me, uom, unit of measure, measure |
| **rate** | rate, price, cost, unit rate, unit price, unit cost, ep, einheitspreis, preis, amount, value |
| **currency** | currency, währung, curr, cur |
| **classification** | classification, din 276, din276, kg, cost group, nrm, masterformat, class, category, group |

CSV delimiter is auto-detected (`,` `;` `\t` `|`). Encoding is auto-detected (UTF-8 / UTF-8 BOM / Latin-1).

### Upload

```bash
curl -X POST "http://localhost:8000/api/v1/costs/import/file/" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@example_us_construction.csv"
```

Response:
```json
{
  "imported": 30,
  "skipped": 0,
  "errors": []
}
```

---

## Method 2 — Resource-based recipes (assemblies)

Resource-based costing decomposes each work item into the resources that build it. In our schema, a **CostItem** can either be:

- a **leaf resource** — `components = []`, has its own `rate` (per hour, per unit, etc.); examples: a carpenter hour, a yd³ of concrete, an excavator hour
- a **recipe / assembly** — `components = [...]`, references leaf resources with quantities; the recipe's `rate` is the rolled-up total

The recipe model lives inside `CostItem.components` as a JSON list. Each component points at another CostItem's `code` and declares how much of it is consumed per unit of the recipe.

### Component schema

```json
{
  "code": "<leaf-code>",        // required — references CostItem.code
  "factor": 1.5,                // required — consumed quantity per 1 unit of the recipe
  "unit": "hr",                 // optional — unit of the leaf (informational; rate is taken from leaf's CostItem)
  "type": "labor"               // optional — labor | material | equipment | subcontractor | other
}
```

### Recipe upload

For recipes the file-import path doesn't yet parse component columns — use the **JSON API** directly:

```bash
curl -X POST "http://localhost:8000/api/v1/costs/items" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "code": "WI-WALL-CIP-8",
  "description": "Cast-in-place concrete wall, 8\" thick (forming + rebar + pour)",
  "unit": "sf",
  "rate": 18.75,
  "currency": "USD",
  "source": "custom",
  "classification": {"masterformat": "03 30 53"},
  "components": [
    {"code": "LAB-CARP-01",  "factor": 0.15, "unit": "hr",  "type": "labor"},
    {"code": "LAB-LAB-01",   "factor": 0.12, "unit": "hr",  "type": "labor"},
    {"code": "MAT-CONC-3K",  "factor": 0.025,"unit": "yd3", "type": "material"},
    {"code": "MAT-REBAR-60", "factor": 1.20, "unit": "lb",  "type": "material"},
    {"code": "EQP-PUMP-CONC","factor": 0.008,"unit": "hr",  "type": "equipment"}
  ],
  "region": "US_BOSTON"
}
EOF
```

The leaves (LAB-CARP-01, MAT-CONC-3K, …) must exist first — either import them via Method 1 first, or push them via the same JSON API before the recipes.

### Bulk recipe import via a wrapper script

For larger sets, `data/templates/cost_database_with_assemblies.json` ships a complete example. Iterate the list and POST each item:

```python
import json, requests
items = json.load(open("data/templates/cost_database_with_assemblies.json"))
for item in items:
    r = requests.post(
        "http://localhost:8000/api/v1/costs/items",
        headers={"Authorization": f"Bearer {token}"},
        json=item,
        timeout=30,
    )
    r.raise_for_status()
```

A working end-to-end smoke test lives at `scripts/test_cost_import.py` — it uploads the leaf CSV, then POSTs the recipe JSON, then verifies all items round-trip correctly via the search endpoint.

---

## Classification codes

The `classification` field is a free-form `{standard: code}` dict. Recognised standards:

| Standard | Region | Example |
|---|---|---|
| `masterformat` | US / Canada | `"03 30 53"` (Cast-in-Place Concrete Forming) |
| `nrm` | UK / NZ / Ireland | `"2.6.1"` (Substructure / Foundations) |
| `din276` | DACH (DE / AT / CH) | `"330"` (External walls) |
| `uniformat` | US | `"B2010"` (Exterior Walls) |
| `gaeb` | DACH tender format | `"014.1.20"` (LV position number) |

In the flat-CSV import, the **classification** column accepts a single bare code; the parser stores it under the catalogue's `default_classification_standard` (which defaults to MasterFormat for US, NRM for UK/NZ, DIN 276 for DACH).

For multi-standard mapping (e.g., a single concrete item known by both MasterFormat and DIN 276), use the JSON API and pass the full dict.

---

## Currency handling

Set `currency` once per row (ISO 4217: `USD`, `EUR`, `GBP`, `JPY`, `MNT`, …). Leave it blank when unknown — the system surfaces "Rate unavailable" in the UI rather than silently substituting EUR (an earlier bug, fixed in 3.0.5).

When a project's currency differs from the cost item's, the FX layer converts at match time using the live rate from the projects' base currency.

---

## Match-Elements with custom data

Once your items are imported they're available to the vector matcher. To wire them in:

1. Create a project bound to your region (or a custom region — see `backend/app/modules/costs/cwicr_v3_catalogue.py`).
2. In `/match-elements` pick **method = lexical** if you want rule-based matching against descriptions, or **method = resources** if you want the resource matcher to find recipes by their components, or **method = vector** if you also re-embedded the descriptions into a Qdrant collection.
3. The match runs against `oe_costs_item` for that region; your items show up alongside the CWICR baseline.

If you want your items to participate in **vector** search (semantic similarity), you'll need to embed them. The simplest path: drop a small `MATCH_EMBED_NEW_ITEMS=1` env var (planned for v3.1) — for now the lexical and resources matchers work natively on freshly imported rows without any extra step.

---

## Verifying an import

After upload:

```bash
# Count items in your region
curl -s "http://localhost:8000/api/v1/costs/items/?region=CUSTOM&limit=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'

# Find a specific item
curl -s "http://localhost:8000/api/v1/costs/items/?q=Carpenter&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.items[0]'

# Pull a recipe with its components
curl -s "http://localhost:8000/api/v1/costs/items/?q=WI-WALL-CIP-8&limit=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.items[0].components'
```

The smoke-test script `scripts/test_cost_import.py` performs all three checks plus a round-trip assertion (every code that was uploaded comes back via the search endpoint with matching unit + rate).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 No data rows found` | Header on a row other than line 1, or empty file | Move headers to row 1; remove blank header row |
| `400 Failed to parse file` | Mixed-encoding CSV; binary bytes in a `.csv` rename | Save as UTF-8 in your editor; ensure file is actually CSV |
| Items uploaded but absent in UI | Wrong / no `region` set on items, UI scoped to a different region | Pass `region` in your payload OR update items via `PATCH /api/v1/costs/items/{id}` |
| Recipe rolled-up rate is wrong | Component `factor` typo or leaf `rate` is 0 | Verify each leaf has a rate > 0; multiply factor × leaf rate manually to confirm |
| Duplicate code error | `code` already exists in same region | Codes are unique per region (DB constraint); change the code or change the region |

---

## Method 3 — Bulk JSON import with catalog extraction (ZIP packages)

Use this when you receive a packaged cost database (e.g. `tn_import_package.zip`) containing JSON files with full resource-based `components[]` arrays. This is the workflow used for importing regional data such as the Tennessee sitework and utilities cost sets.

### What this workflow does

1. **Bulk-import cost items** into `oe_costs_item` via `POST /api/v1/costs/bulk/`
2. **Auto-generate component `code` fields** if missing (required for catalog extraction)
3. **Extract catalog resources** from the imported cost item components so they become reusable in assemblies and the Resource Catalog

### Step-by-step

#### 1. Prepare the data

Unzip the package and inspect the JSON files:

```bash
unzip -o tn_import_package.zip -d /tmp/tn_import
ls /tmp/tn_import/tn_import_package/data/
# us_tn_sitework_costs.json
# us_tn_concrete_utilities_costs.json
# material_rates.json
```

Each JSON file is a list of cost items. Example item shape:

```json
{
  "code": "DEM-HSE-01",
  "description": "Demolition of wood-frame residential structure...",
  "unit": "SF",
  "rate": 10.33,
  "currency": "USD",
  "region": "USA_TENNESSEE",
  "source": "manual",
  "classification": {"division": "02", "section": "4100", "category": "Selective Demolition"},
  "components": [
    {"type": "labor", "name": "Demolition crew labor...", "quantity": 0.12, "unit_rate": 22.45, "cost": 2.69, "unit": "hr"},
    {"type": "equipment", "name": "Hydraulic Excavator 30-ton...", "quantity": 0.06, "unit_rate": 73.58, "cost": 4.41, "unit": "hr"},
    {"type": "material", "name": "Dumpster rental...", "quantity": 0.003, "unit_rate": 650.00, "cost": 1.95, "unit": "EA"}
  ],
  "tags": ["demolition", "residential", "sitework", "nashville", "tn"],
  "metadata": {"labor_hours": 0.12, "equipment_hours": 0.06, "validation_status": "pilot"}
}
```

> **Important**: Each component **must have a `code`** for catalog extraction to work. If the source data omits `code` fields, the import script auto-generates them as `TN-{TYPE}-{slug}`.

#### 2. Run the import script

Use `scripts/import_tennessee_costs.py` (or adapt it for your region):

```bash
python scripts/import_tennessee_costs.py \
  --email sergeilapp@gmail.com \
  --password "your-password" \
  --port 8000 \
  --data-dir /tmp/tn_import/tn_import_package/data
```

This will:
- Authenticate via `POST /api/v1/users/auth/login/`
- Validate `rate == sum(components.cost)` for each item
- Generate component codes if missing
- Bulk-import via `POST /api/v1/costs/bulk/`
- Verify items exist in the database

#### 3. Extract catalog resources

After cost items are imported, extract their components into the Resource Catalog so they can be reused in assemblies:

```bash
cd backend
python -m app.scripts.extract_tennessee_catalog
```

Or call the API directly (requires `catalog.extract` permission, i.e. Manager/Admin role):

```bash
curl -X POST "http://localhost:8000/api/v1/catalog/extract/" \
  -H "Authorization: Bearer $TOKEN"
```

The extraction aggregates components by `(code, type)` across all active cost items, computes average/min/max rates, categorises resources, and inserts them into `oe_catalog_resource`.

#### 4. Verify

```bash
# Cost items
curl -s "http://localhost:8000/api/v1/costs/?region=USA_TENNESSEE&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'

# Catalog resources for the region
curl -s "http://localhost:8000/api/v1/catalog/?region=USA_TENNESSEE&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'

# Loaded regions
curl -s "http://localhost:8000/api/v1/catalog/regions/" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### Architecture: Cost Database vs. Resource Catalog vs. "My Catalog"

| Layer | Table | What it stores | Source |
|-------|-------|---------------|--------|
| **Cost Database** | `oe_costs_item` | Work positions / compositions with rates and component breakdowns | Bulk import, CSV, CWICR, manual |
| **Resource Catalog** | `oe_catalog_resource` | Extracted leaf resources (materials, equipment, labour, operators) with prices | Extracted from cost item `components[]`, or GitHub CSV import |
| **"My Catalog"** | `oe_catalog_resource` (region=`CUSTOM`) | User-created custom resources added one-by-one via the UI | Manual creation via `POST /api/v1/catalog/` |

**Key point**: The "My Catalog" tab on `/catalog` only shows resources with `region='CUSTOM'`. Your imported regional data (e.g. `USA_TENNESSEE`) appears as a **separate region tab**, not under "My Catalog".

### Why component codes matter

The catalog extraction service (`CatalogResourceService.import_region_from_costs`) groups components by their `code` field:

```python
code = comp.get("code", "")
if not code:
    continue  # SKIP — component without code is invisible to the catalog
```

Without codes, components are silently skipped during extraction. The import script auto-generates codes using a slugified name hash:

```python
base = f"TN-{comp['type'][:3].upper()}-{slugify(comp['name'])}"
```

### Check existing data before importing

Always verify whether the target region already has data:

```bash
# Check cost items
curl -s "http://localhost:8000/api/v1/costs/?region=USA_TENNESSEE&limit=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'

# Check catalog resources
sqlite3 openestimate.db "SELECT COUNT(*) FROM oe_catalog_resource WHERE region='USA_TENNESSEE';"
```

The bulk import API skips duplicates by `code` within the same region, so re-running is safe. To force a clean re-import, delete the region first:

```bash
# Delete catalog resources for region
curl -X DELETE "http://localhost:8000/api/v1/catalog/region/USA_TENNESSEE" \
  -H "Authorization: Bearer $TOKEN"

# Delete cost items for region (no bulk-delete endpoint — use direct SQL or delete individually)
```

### Scripts shipped with this repository

| File | Purpose |
|---|---|
| `scripts/import_tennessee_costs.py` | Authenticated bulk import + validation + catalog extraction trigger for ZIP packages |
| `backend/app/scripts/extract_tennessee_catalog.py` | Standalone backend script for region-specific catalog extraction with explicit `session.commit()` |

---

## Reference templates shipped with this repository

| File | Purpose |
|---|---|
| `data/templates/cost_database_template.csv` | Empty CSV with headers + 3 example rows |
| `data/templates/example_us_construction.csv` | 30-row working US construction database (leaves only) |
| `data/templates/cost_database_with_assemblies.json` | 6 recipe items + their leaves, ready for JSON-API push |
| `scripts/test_cost_import.py` | End-to-end smoke test that imports the templates and verifies correctness |
