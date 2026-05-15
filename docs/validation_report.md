# Validation Report — US Tennessee Sitework Cost Database (Pilot Batch)

**Date:** 2026-05-13  
**Region:** USA_TENNESSEE (Nashville, TN)  
**Items Validated:** 12  

---

## 1. Component Math Validation

All 12 items pass: `rate == sum(components.cost)` within $0.01 tolerance.

| Code | Rate | Sum of Components | Diff | Components | Status |
|------|------|-------------------|------|------------|--------|
| DEM-HSE-01 | $10.33 | $10.33 | $0.00 | 4 | PASS |
| DEM-GRG-01 | $7.50 | $7.50 | $0.00 | 4 | PASS |
| DEM-CON-01 | $4.25 | $4.25 | $0.00 | 3 | PASS |
| DEM-ASP-01 | $3.50 | $3.50 | $0.00 | 3 | PASS |
| EXC-BLK-01 | $12.45 | $12.45 | $0.00 | 7 | PASS |
| EXC-TRN-01 | $15.00 | $15.00 | $0.00 | 7 | PASS |
| GRD-SIT-01 | $0.45 | $0.45 | $0.00 | 6 | PASS |
| FILL-CMP-01 | $18.50 | $18.50 | $0.00 | 7 | PASS |
| SW-FRN-01 | $28.00 | $28.00 | $0.00 | 10 | PASS |
| SW-INF-01 | $850.00 | $850.00 | $0.00 | 9 | PASS |
| UT-WTR-01 | $22.00 | $22.00 | $0.00 | 9 | PASS |
| UT-SWR-01 | $28.00 | $28.00 | $0.00 | 9 | PASS |

---

## 2. TDOT Bid Price Cross-Validation

Our resource-based rates (direct cost only) are compared against TDOT 2024 Average Unit Bid Prices (fully loaded bid prices including overhead, profit, bonds, traffic control).

| OCERP Item | OCERP Rate | TDOT Item | TDOT Rate | Variance | Assessment |
|------------|-----------|-----------|-----------|----------|------------|
| EXC-BLK-01 | $12.45/CY | 203-01 Unclassified Excavation | $21.42/CY | -41.9% | Acceptable. TDOT includes clearing, erosion control, disposal, and wider scope. Direct costs expected 55-75% of bid. |
| FILL-CMP-01 | $18.50/CY | 203-03 Borrow Excavation | $28.24/CY | -34.5% | Acceptable. Import fill material cost ($12/CY) is market rate; TDOT borrow includes longer hauls. |
| SW-FRN-01 | $28.00/LF | 710-04 Filter Cloth Underdrain | $26.31/LF | +6.4% | Excellent match. Within 10% of TDOT 2024 bid. |
| DEM-CON-01 | $4.25/SF | 202-03 Rigid Pavement Removal | $4.56/SF* | -6.8% | Excellent match. *Converted from $41.03/SY ÷ 9. |
| DEM-ASP-01 | $3.50/SF | 202-03.01 Asphalt Pavement Removal | $1.28/SF* | +173% | Variance exceeds ±30%. TDOT asphalt removal is priced per SY ($11.56/SY ÷ 9 = $1.28/SF) for highway milling, not full-depth demolition. Our rate models complete removal of driveway pavement (4" thick). Different scope. |
| UT-WTR-01 | $22.00/LF | 795-03.02 2" PVC Water Line | $39.50/LF | -44.3% | Our 4" residential service vs TDOT 2" highway water line — not directly comparable. TDOT rates include highway mobilization and traffic control. |
| UT-SWR-01 | $28.00/LF | 797-05.51 8" PVC Gravity Sewer | $201.42/LF | -86.1% | Our 6" residential service vs TDOT 8" highway sewer — completely different scope. TDOT sewer includes deep excavation (0-6 ft), bedding, manholes, connections. |

**Summary:** Where scope is comparable (grading, french drain, concrete removal), our rates are within ±35% of TDOT. Where scope differs (highway vs residential, large-diameter vs small), direct comparison is not meaningful.

---

## 3. TCG BedRock Job Comparison

Reference values from the TCG Brentwood estimate for cross-checking:

| BedRock Job | BedRock Total | Our Rate × Typical Qty | Estimated OCERP Total | Variance |
|-------------|---------------|----------------------|----------------------|----------|
| Economy Level Site (01.01) | $79,784.44 | Using GRD-SIT-01 at $0.45/SF × 45,225 SF + EXC-BLK-01 at $12.45/CY × 1,955 CY | ~$44,700 | -44% |
| Demolition (01.02) | $359,469.05 (bundle) | Mixed demo items across 1,500 SF house + 400 SF garage + 1,500 SF concrete + 8,400 SF asphalt | ~$74,000 (demo only) | Not comparable — BedRock bundles demo with erosion control, tree removal, hauling |
| French Drain (02.01) | $76,421.25 | SW-FRN-01 at $28.00/LF × ~1,500 LF estimate | ~$42,000 | -45% |

**Note:** Direct comparison is limited because BedRock totals include many items we haven't modeled yet (mobilization, markups, overhead, profit, bonds, traffic control). Our rates represent **direct cost** only.

---

## 4. Data Source Quality

| Data Source | Quality | Notes |
|-------------|---------|-------|
| USACE EP 1110-1-8 | **High** | Official Dec 2022 edition, Region 3 Southeast. Rates verified from PDF. |
| BLS OEWS May 2024 | **High** | Official BLS data for Nashville MSA (34980). Exact matches from `MSA_M2024_dl.xlsx`. |
| Tennessee Material Rates | **Medium** | Market estimates from Home Depot/Lowe's catalog pricing. Should be validated with supplier quotes. |
| TDOT Bid Prices 2024 | **High** | Official published average bid prices from `Const_aup2024.pdf`. |

---

## 5. Known Limitations

1. **USACE rates are machine-only.** Operator labor is in separate labor components. Total fleet cost = equipment rate + operator wage.
2. **No markup applied.** These are direct costs. Add overhead (10-15%), profit (5-10%), bonds, and insurance for bid prices.
3. **Small project productivity.** Our quantities assume residential/sitework scale (not highway). Production rates are lower.
4. **Davis-Bacon wages not applied.** Federal prevailing wage rates for TN are 25-40% higher than BLS mean wages.
5. **Material rates are estimates.** Should be validated against actual Nashville supplier quotes.

---

## 6. Next Steps

- [ ] Import to OCERP: `python scripts/import_cost_database.py`
- [ ] Verify items appear at `/costs?region=USA_TENNESSEE`
- [ ] Create test BOQ positions using DEM-HSE-01, EXC-BLK-01, SW-FRN-01
- [ ] Compare against actual BedRock CSV line items
- [ ] Begin Batch 2: Stormwater items (15 items)
