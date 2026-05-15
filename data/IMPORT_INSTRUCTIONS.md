# Import Instructions: US Tennessee Sitework Cost Database — Batch 2

## Prerequisites

1. OCERP backend running at http://localhost:8082
2. Batch 1 already imported (12 items in database)
3. Logged in as estimator or admin account
4. Data files:
   - Batch 1: `data/us_tn_sitework_costs.json` (existing, already imported)
   - Batch 2: `data/us_tn_concrete_utilities_costs.json` (TO BE BUILT, then imported)

## Quick Import

```bash
cd /home/sergei/dev/bedrock-siteworks/OCERP

# Import Batch 1 (already done)
python scripts/import_cost_database.py --file data/us_tn_sitework_costs.json

# Import Batch 2 (new)
python scripts/import_cost_database.py --file data/us_tn_concrete_utilities_costs.json
```

## Update material_rates.json

Before building Batch 1 items, extend `data/material_rates.json` with these 13 new material codes:

```json
[
  {"material_code": "MAT-CON-3500", "description": "Ready-mix concrete, 3500 PSI, delivered", "unit": "CY", "rate": 225.00},
  {"material_code": "MAT-ASP-HM", "description": "Hot mix asphalt (surface course)", "unit": "TON", "rate": 135.00},
  {"material_code": "MAT-2A-STONE", "description": "#2A stone (crusher run, 3/4\" minus)", "unit": "CY", "rate": 40.00},
  {"material_code": "MAT-CON-FORMS", "description": "Form lumber + stakes for curb", "unit": "LF", "rate": 1.50},
  {"material_code": "MAT-CON-JOINTS", "description": "Expansion joint + curing compound", "unit": "LF", "rate": 0.40},
  {"material_code": "MAT-PVC-3", "description": "3\" PVC schedule 40 pipe", "unit": "LF", "rate": 2.50},
  {"material_code": "MAT-PVC-15", "description": "1.5\" PVC schedule 40 pipe", "unit": "LF", "rate": 1.50},
  {"material_code": "MAT-STONE-DUST", "description": "Stone dust / crusher run screenings", "unit": "CY", "rate": 28.00},
  {"material_code": "MAT-RCP-18", "description": "18\" reinforced concrete pipe (Class III)", "unit": "LF", "rate": 22.00},
  {"material_code": "MAT-HDW-18", "description": "Precast concrete headwall for 18\" RCP", "unit": "EA", "rate": 800.00},
  {"material_code": "MAT-CORR-4", "description": "4\" corrugated perforated HDPE pipe", "unit": "LF", "rate": 2.25},
  {"material_code": "MAT-VB-10MIL", "description": "Vapor barrier, 10 mil polyethylene", "unit": "SF", "rate": 0.25},
  {"material_code": "MAT-RIP-RAP", "description": "Rip rap stone / outlet protection", "unit": "CY", "rate": 45.00}
]
```

## Batch 2 Items: 13 Cost Items

| Code | Description | Unit | Est. Rate | Category |
|------|-------------|------|-----------|----------|
| CON-CUR-01 | Concrete curb and gutter (street frontage, 3500 PSI) | LF | $14.67 | Concrete & Paving |
| CON-RCB-01 | Concrete ribbon curb (perimeter, 3500 PSI) | LF | $9.25 | Concrete & Paving |
| ASP-PAV-01 | Asphalt pavement, 3.5" hot mix, placed and compacted | SF | $5.45 | Concrete & Paving |
| STN-BSE-01 | Stone base, 8" crushed aggregate, placed and compacted | SF | $1.63 | Concrete & Paving |
| UT-ELC-01 | Electrical conduit, 3" PVC sched 40, trench + pipe + stone dust + red tape | LF | $16.01 | Utility Conduits |
| UT-COM-01 | Communications conduit, 1.5" PVC (pipe only, shares trench w/ electrical) | LF | $3.21 | Utility Conduits |
| UT-GAS-01 | Gas line trench, 3' wide x 3' deep, stone dust backfill + yellow tape (no pipe) | LF | $17.07 | Utility Conduits |
| STR-RCP-18 | 18" RCP storm pipe (Class III), trench, bed, backfill | LF | $44.01 | Storm Pipe |
| STR-HDW-01 | Precast concrete headwall with outlet protection, for 18" RCP | EA | $1,323.47 | Storm Pipe |
| EXC-CRW-01 | Crawlspace and footer excavation, precision (±1/4"), stockpile on site | CY | $12.52 | Foundation Prep |
| DRN-PRM-01 | Foundation perimeter drain, 4" corrugated, geotextile wrap, #57 stone | LF | $22.24 | Foundation Prep |
| GRD-CRW-01 | Fine grade crawlspace + 10 mil vapor barrier + 4" #57 stone | SF | $1.32 | Foundation Prep |
| EQP-RNT-HMR | Excavator 30T with hydraulic hammer, monthly rental | MO | $13,500.00 | Equipment Rental |

## Manual Import (via API)

### 1. Login
```bash
TOKEN=$(curl -s -X POST http://localhost:8082/api/v1/users/auth/demo-login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"estimator@openestimator.io"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### 2. Bulk import
```bash
curl -X POST http://localhost:8082/api/v1/costs/bulk/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @data/us_tn_concrete_utilities_costs.json
```

### 3. Verify
```bash
# Should show 26 items total (12 batch 1 + 13 batch 2 + SIT-LAY-01)
curl -s "http://localhost:8082/api/v1/costs/?region=USA_TENNESSEE&limit=30" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Total: {d[\"total\"]} items')"
```

## Validation

After import, check component math for all items:

```bash
python3 -c "
import json
with open('data/us_tn_concrete_utilities_costs.json') as f:
    items = json.load(f)
for item in items:
    expected = round(item['rate'], 2)
    actual = round(sum(c['cost'] for c in item.get('components', [])), 2)
    diff = round(expected - actual, 2)
    status = '✓' if abs(diff) < 0.01 else f'✗ diff={diff}'
    print(f'{status} {item[\"code\"]}: expected={expected}, calculated={actual}')
"
```

## Data Sources

- **Equipment rates**: USACE EP 1110-1-8 (Dec 2022, Region 3 Southeast) — `data/usace_equipment_rates.json`
- **Labor wages**: BLS OEWS May 2024 Nashville MSA — `data/bls_labor_wages.json`
- **Material rates**: Nashville market estimates — `data/material_rates.json` (extended with 13 new codes)
- **TDOT validation**: 2024 Average Unit Bid Prices — `data/tdot_bid_prices.json` (extended with 8 new items)

## Notes

- All items use `region: USA_TENNESSEE`, `currency: USD`, `source: manual`
- Component validation: `rate == sum(components.cost)` within $0.01 tolerance
- `UT-COM-01` is designed to share trench with `UT-ELC-01` (no trench labor/equipment in its components)
- `UT-GAS-01` is trench-only (3' wide); gas pipe installation by others
- `SIT-LAY-01` is a lump-sum item; manual rates acceptable
- Asphalt paver hourly rate ($89/hr) is estimated (not in USACE data)
- Monthly equipment rental rates are rough market estimates
