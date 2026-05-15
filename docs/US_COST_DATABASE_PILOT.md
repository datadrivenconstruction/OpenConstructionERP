# US Resource-Based Cost Database — Pilot Batch
## Handoff Document for OpenConstructionERP

**Project:** TCG Brentwood Sitework — Cost Database Build  
**Region:** Nashville, Tennessee (USA_TENNESSEE)  
**Scope:** 12 pilot items covering demolition, excavation, stormwater, utilities  
**Created:** 2026-05-13  
**Status:** Ready for Execution  
**Estimated Time:** 45-60 minutes  

---

## Objective

Build a US-specific, resource-based cost database for OpenConstructionERP with **full component breakdowns** (labor + equipment + material) for sitework estimating. Start with a pilot batch of 12 items focused on the Nashville, Tennessee market.

This database will enable:
- Resource-based costing in BOQs (labor hours, equipment costs, material costs visible per position)
- Cross-validation against real TDOT bid prices
- Foundation for a complete US sitework cost database (future batches)

---

## Scope: 12 Pilot Items

### Demolition (4 items)
| Code | Description | Unit |
|------|-------------|------|
| DEM-HSE-01 | House demolition (wood-frame residential) | SF |
| DEM-GRG-01 | Garage demolition (detached structure) | SF |
| DEM-CON-01 | Concrete removal (sidewalk/driveway/patio) | SF |
| DEM-ASP-01 | Asphalt removal (pavement) | SF |

### Excavation & Grading (4 items)
| Code | Description | Unit |
|------|-------------|------|
| EXC-BLK-01 | Bulk excavation, common earth, machine | CY |
| EXC-TRN-01 | Trench excavation (utility trench, up to 3ft) | LF |
| GRD-SIT-01 | Site grading and leveling | SF |
| FILL-CMP-01 | Fill import, placement, and compaction | CY |

### Stormwater (2 items)
| Code | Description | Unit |
|------|-------------|------|
| SW-FRN-01 | French drain installation | LF |
| SW-INF-01 | Stormwater infiltration pit | EA |

### Utilities (2 items)
| Code | Description | Unit |
|------|-------------|------|
| UT-WTR-01 | Water service line installation | LF |
| UT-SWR-01 | Sewer service line installation | LF |

---

## Data Sources

### 1. USACE EP 1110-1-8 — Equipment Rates
**URL:** https://www.usace.army.mil/Missions/Cost-Engineering/EP1110-1-8/

- Download the **Southeastern US** volume (Region 5 covers TN/KY/GA/AL/MS/NC/SC)
- Parse PDF to extract hourly equipment rates:
  - Hydraulic excavators (various sizes)
  - Bulldozers
  - Wheel loaders
  - Dump trucks
  - Concrete breakers/jackhammers
  - Graders
  - Compactors/vibratory rollers
  - Stump grinders
  - Chippers
  - Cold planers/milling machines

**Output:** `data/usace_equipment_rates.json`
```json
[
  {"equipment_code": "EXC-30T", "name": "Hydraulic excavator 30-ton",
   "ownership_rate": 45.50, "operating_rate": 28.75,
   "total_hourly_rate": 74.25, "unit": "hr", "region": "USA_SOUTHEAST"}
]
```

### 2. BLS OEWS — Labor Wages (Nashville MSA)
**URL:** https://www.bls.gov/oes/tables.htm

- Download May 2024 OEWS data for **Nashville-Davidson-Murfreesboro-Franklin, TN** MSA (METRO 34980)
- Extract hourly wages for:
  - Construction Laborers (SOC 47-2061)
  - Operating Engineers (SOC 47-2073)
  - Pipelayers (SOC 47-2151)
  - Cement Masons (SOC 47-2051)
  - Tree Trimmers/Pruners (SOC 37-3013)

**Output:** `data/bls_labor_wages.json`
```json
[
  {"soc_code": "47-2061", "occupation": "Construction Laborers",
   "mean_hourly_wage": 22.45, "unit": "hr", "region": "Nashville TN MSA"}
]
```

### 3. Tennessee Material Rates (Market Estimates)
**Sources:** Home Depot / Lowe's / local supplier pricing (no purchase, just reference)

- Concrete disposal: $65/ton
- Asphalt disposal: $55/ton
- Structural fill dirt: $12/CY
- #57 stone: $45/CY
- #8 stone: $55/CY
- Sand bedding: $35/CY
- Geotextile fabric: $0.85/SF
- 4" PVC pipe: $3.50/LF
- 6" PVC pipe: $5.25/LF
- Dumpster rental (30yd): $650/EA
- Silt fence fabric: $0.85/LF
- Steel posts (6ft): $4.50/EA
- Wire backing: $0.45/LF

**Output:** `data/material_rates.json`
```json
[
  {"material_code": "MAT-CON-DIS", "description": "Concrete disposal/recycling",
   "unit": "ton", "rate": 65.00, "region": "USA_TENNESSEE"}
]
```

### 4. TDOT Bid Prices — Validation
**URL:** https://www.tn.gov/tdot/tdot-construction-division/transportation-construction-division-resources/transportation-construction-price-information.html

- Download 2024-2025 Average Bid Prices PDF
- Extract real bid prices for items matching our 12 pilot items
- Use for cross-validation after calculating our rates

**Output:** `data/tdot_bid_prices.json`
```json
[
  {"tdot_item_no": "2030100", "description": "Unclassified excavation",
   "unit": "CY", "avg_bid_price": 9.50, "year": 2024}
]
```

### 5. DDC CWICR Reference (Existing OCERP Database)
**URL:** https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR

- Reference existing CWICR items for structure/schema
- Compare our calculated rates against CWICR rates (e.g., `EXC-BLK-1M` = $9.50/m3)
- Note: CWICR is Eurasian/EUR — expect 20-40% variance vs US rates

---

## Resource-Based Calculation Method

For each CostItem, the **total rate** = sum of all component costs:

```python
total_rate = sum(component["quantity"] * component["unit_rate"] for component in components)
```

### Example: DEM-HSE-01 (House Demolition)

| Component | Type | Qty | Unit Rate | Cost |
|-----------|------|-----|-----------|------|
| Demolition crew (3 workers) | labor | 0.12 hrs/SF | $22.45/hr | $2.69 |
| Excavator with grapple attachment | equipment | 0.06 hrs/SF | $74.25/hr | $4.46 |
| Dumpster rental (30yd) | material | 0.003 EA/SF | $650.00/EA | $1.95 |
| Debris disposal and hauling | material | 0.015 ton/SF | $85.00/ton | $1.28 |
| **TOTAL** | | | | **$10.38/SF** |

### Validation Rule
```python
assert abs(total_rate - sum(c["cost"] for c in components)) < 0.01, "Component math error"
```

---

## JSON Schema for CostItems

Each item in `data/us_tn_sitework_costs.json` must follow this schema:

```json
{
  "code": "DEM-HSE-01",
  "description": "Demolition of wood-frame residential structure",
  "unit": "SF",
  "rate": 10.38,
  "currency": "USD",
  "source": "manual",
  "region": "USA_TENNESSEE",
  "classification": {
    "division": "02",
    "section": "4100",
    "category": "Selective Demolition"
  },
  "components": [
    {
      "type": "labor",
      "name": "Demolition crew (3 workers)",
      "quantity": 0.12,
      "unit_rate": 22.45,
      "cost": 2.69,
      "unit": "hrs"
    },
    {
      "type": "equipment",
      "name": "Excavator with grapple attachment",
      "quantity": 0.06,
      "unit_rate": 74.25,
      "cost": 4.46,
      "unit": "hrs"
    },
    {
      "type": "material",
      "name": "Dumpster rental (30yd)",
      "quantity": 0.003,
      "unit_rate": 650.00,
      "cost": 1.95,
      "unit": "EA"
    },
    {
      "type": "material",
      "name": "Debris disposal and hauling",
      "quantity": 0.015,
      "unit_rate": 85.00,
      "cost": 1.28,
      "unit": "ton"
    }
  ],
  "tags": ["demolition", "residential", "sitework", "nashville", "tn"]
}
```

---

## File Structure

```
OCERP/
├── data/
│   ├── usace_equipment_rates.json   # Parsed from USACE PDF
│   ├── bls_labor_wages.json         # Nashville MSA wages
│   ├── material_rates.json           # TN market estimates
│   ├── tdot_bid_prices.json          # TDOT validation prices
│   └── us_tn_sitework_costs.json     # Final 12 CostItems (import this)
├── scripts/
│   └── import_cost_database.py       # Reusable import script
├── docs/
│   └── US_COST_DATABASE_PILOT.md     # This document
└── IMPORT_INSTRUCTIONS.md             # Quick reference
```

---

## Execution Checklist

- [ ] 1. Download USACE EP 1110-1-8 Southeastern PDF
- [ ] 2. Parse USACE PDF → `data/usace_equipment_rates.json`
- [ ] 3. Download BLS OEWS Nashville Excel
- [ ] 4. Parse BLS data → `data/bls_labor_wages.json`
- [ ] 5. Research TN material rates → `data/material_rates.json`
- [ ] 6. Download TDOT bid prices PDF
- [ ] 7. Extract TDOT prices → `data/tdot_bid_prices.json`
- [ ] 8. Build 12 CostItems with component arrays
- [ ] 9. Validate: `rate == sum(components.cost)` for each item
- [ ] 10. Import to OCERP: `POST /api/v1/costs/bulk/`
- [ ] 11. Verify in OCERP: search for `USA_TENNESSEE` region items
- [ ] 12. Create test BOQ positions using cost items
- [ ] 13. Compare OCERP totals vs TDOT bid prices vs BedRock CSV
- [ ] 14. Document validation report in `docs/validation_report.md`

---

## Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| USACE PDF parsing complex | Use `pdfplumber` or `tabula-py`; spot-check extracted values manually |
| BLS data annual (May 2024) | Use this data; note date in metadata |
| Material rates are estimates | Mark source as `manual`; refine with actual supplier quotes |
| TDOT PDF format unpredictable | May need manual extraction if parsing fails |
| Region mismatch | Use `USA_TENNESSEE` for all items; can sub-divide later |

---

## Reference: TCG BedRock Job Totals (For Comparison)

After importing, compare against these BedRock values:

| Job | BedRock Total |
|-----|---------------|
| Economy Level Site (01.01) | $79,784.44 |
| Demolition (01.02) | $359,469.05 (bundle) |
| French Drain (02.01) | $76,421.25 |

Our calculated rates should be within ±30% for a first-pass validation.

---

## Contact / Questions

For issues or clarifications, refer to:
- OCERP cost module: `backend/app/modules/costs/`
- CostItem schema: `backend/app/modules/costs/schemas.py`
- Bulk import endpoint: `POST /api/v1/costs/bulk/`
- File import endpoint: `POST /api/v1/costs/import/file/`

---

## Next Steps (After Pilot Validation)

Once the 12-item pilot is validated:

**Batch 2** (~15 items): Stormwater items
- Drainage pipe (various sizes)
- Catch basins/manholes
- Headwalls
- Rip rap

**Batch 3** (~15 items): Utilities
- Gas line trench
- Electrical conduit
- Communications conduit

**Batch 4** (~15 items): Concrete & Paving
- Concrete curb and gutter
- Sidewalk
- Asphalt paving

**Batch 5** (~10 items): Site Finishing
- Erosion control blankets
- Seeding
- Straw mulch
- Construction fencing

---

*End of Handoff Document*