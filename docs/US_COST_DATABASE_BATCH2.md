# US Resource-Based Cost Database — Batch 2: Concrete, Trenching, Excavation, Additional Work
## Handoff Document for OpenConstructionERP

**Project:** TCG Brentwood Sitework — Cost Database Build (Batch 2 of 3)
**Region:** Nashville, Tennessee (USA_TENNESSEE)
**Scope:** 13 new cost items covering concrete curbing, asphalt, utility conduits, storm pipe, crawlspace prep, foundation drains
**Prerequisite:** Pilot Batch 1 (12 items) completed — `data/us_tn_sitework_costs.json`
**Created:** 2026-05-13
**Status:** Ready for Execution
**Estimated Time:** 45-60 minutes

---

## Objective

Extend the USA_TENNESSEE cost database with 13 new composite cost items to cover the 4 remaining TCG BedRock jobs:

| Job ID | Job Name | BedRock Price | Status |
|--------|----------|--------------|--------|
| 38447 | Concrete Curb | $61,154.41 | **NOT YET DONE** |
| 38522 | Trenching | $51,842.25 | **NOT YET DONE** |
| 38577 | Excavation | $36,298.60 | **NOT YET DONE** |
| 38578 | Additional Work | $85,978.75 | **NOT YET DONE** |

These jobs cover ~$235K in TCG bids that the pilot batch did not address.

---

## Scope: 13 New Cost Items

### Concrete & Paving (4 items)
| Code | Description | Unit | Est. Rate |
|------|-------------|------|-----------|
| CON-CUR-01 | Concrete curb and gutter (street frontage), formed and poured, 3500 PSI | LF | $14.50 |
| CON-RCB-01 | Concrete ribbon curb (perimeter), formed and poured, 3500 PSI | LF | $9.25 |
| ASP-PAV-01 | Asphalt pavement, 3.5" hot mix, placed and compacted | SF | $5.00 |
| STN-BSE-01 | Stone base, 8" crushed aggregate, placed and compacted | SF | $1.65 |

### Utility Conduits & Trenches (3 items)
| Code | Description | Unit | Est. Rate |
|------|-------------|------|-----------|
| UT-ELC-01 | Electrical conduit installation, 3" PVC schedule 40, trench + pipe + stone dust + red tape | LF | $16.00 |
| UT-COM-01 | Communications conduit, 1.5" PVC (shares trench with electrical; pipe + fittings only) | LF | $3.25 |
| UT-GAS-01 | Gas line trench, 3' wide × 3' deep, stone dust backfill + yellow tracer tape (no pipe) | LF | $16.00 |

### Storm Pipe (2 items)
| Code | Description | Unit | Est. Rate |
|------|-------------|------|-----------|
| STR-RCP-18 | 18" RCP storm pipe (Class III), trench, bed, backfill | LF | $44.00 |
| STR-HDW-01 | Precast concrete headwall with outlet protection, for 18" RCP | EA | $1,200.00 |

### Foundation Preparation (3 items)
| Code | Description | Unit | Est. Rate |
|------|-------------|------|-----------|
| EXC-CRW-01 | Crawlspace and footer excavation, precision (±1/4"), stockpile on site, 5 foundations | CY | $14.00 |
| DRN-PRM-01 | Foundation perimeter drain, 4" corrugated perforated pipe, geotextile wrap, #57 stone surround, connect to storm | LF | $22.00 |
| GRD-CRW-01 | Fine grade crawlspace with 10mil vapor barrier and 4" #57 stone placement | SF | $1.35 |

### Equipment Rental (1 item)
| Code | Description | Unit | Est. Rate |
|------|-------------|------|-----------|
| EQP-RNT-HMR | Excavator 30-ton with hydraulic hammer attachment, monthly rental | MO | $13,500.00 |

---

## TCG Job Mapping

### Job 38447 — Concrete Curb ($61,154.41)

From the TCG estimate notes:
- 75 LF concrete curb and gutter along street frontage
- 844 LF concrete ribbon curb around driveway/parking perimeter
- Subgrade excavation, stone base, 3500 PSI concrete, joints
- Excavation/grading for driveway ramp, sidewalk, walkways
- Road widening: 4' × 125' area (500 SF), 8" stone, 3.5" asphalt
- Repair utility trenches on street with asphalt
- Mill and overlay existing curb
- Credit: remove ribbon curb and walkway excavation ($37,000)

**BOQ Positions:**

| Ordinal | Description | Qty | Unit | Cost Item | Rate |
|---------|-------------|-----|------|-----------|------|
| 04.10.0010 | Concrete curb and gutter (street frontage, 3500 PSI) | 75 | LF | CON-CUR-01 | $14.50 |
| 04.10.0020 | Concrete ribbon curb (perimeter, 3500 PSI) | 844 | LF | CON-RCB-01 | $9.25 |
| 04.20.0010 | Subgrade preparation for curb/driveway | 1,500 | SF | GRD-SIT-01 | $0.45 |
| 04.20.0020 | Stone base, 8" crushed (road widening) | 500 | SF | STN-BSE-01 | $1.65 |
| 04.20.0030 | Asphalt pavement, 3.5" (road widening) | 500 | SF | ASP-PAV-01 | $5.00 |
| 04.30.0010 | Subgrade preparation for walkways | 2,000 | SF | GRD-SIT-01 | $0.45 |
| 04.50.0010 | Mill and overlay existing curb | 75 | LF | *custom/manual* | *TBD* |
| 04.50.0020 | Utility trench asphalt repair | 50 | LF | *custom/manual* | *TBD* |
| — | Credit: remove ribbon curb (per plan) | -844 | LF | — | *credit* |
| — | Credit: remove walkway excavation (per plan) | *LS* | — | — | *credit* |

### Job 38522 — Trenching ($51,842.25)

From the TCG estimate notes:
- 1300 LF total trenching (3' deep) for all utilities
- Sanitary sewer: 4" schedule 40 pipe from street to each house
- Water service: 4" schedule 40 pipe from street to each house
- Electrical conduit: 4" conduit in trench, 12" stone dust, red tracer tape
- Communications conduit: in same trench as electrical
- Gas line trench: 3' wide × 3' deep, stone dust backfill, yellow tracer tape (pipe by others)
- 125 LF 18" RCP with 2 precast concrete headwalls and outlet protection

**BOQ Positions:**

| Ordinal | Description | Qty | Unit | Cost Item | Rate |
|---------|-------------|-----|------|-----------|------|
| 05.10.0010 | Sewer service line (4" PVC, 3' deep) | 200 | LF | UT-SWR-01 | $28.00 |
| 05.10.0020 | Water service line (4" PVC, 3' deep) | 200 | LF | UT-WTR-01 | $22.00 |
| 05.20.0010 | Electrical conduit (3" PVC, 3' deep, stone dust + red tape) | 900 | LF | UT-ELC-01 | $16.00 |
| 05.20.0020 | Communications conduit (1.5" PVC, shares trench w/ electrical) | 900 | LF | UT-COM-01 | $3.25 |
| 05.30.0010 | Gas line trench (3'×3', stone dust backfill + yellow tape, pipe by others) | 400 | LF | UT-GAS-01 | $16.00 |
| 05.40.0010 | 18" RCP storm pipe (Class III) | 125 | LF | STR-RCP-18 | $44.00 |
| 05.40.0020 | Precast concrete headwall, 18" with outlet protection | 2 | EA | STR-HDW-01 | $1,200.00 |

### Job 38577 — Excavation ($36,298.60)

From the TCG estimate notes:
- Excavate crawlspace and footers for 5 foundation areas
- Install 4" corrugated perforated pipe around perimeter of 5 foundations
- Surrounded by 12" #57 stone, wrapped in geotextile
- Pipe led to storm drain
- Fine grade crawlspace areas + vapor barrier + 4" #57 stone (5 foundations)
- Fine grade garage areas (stone + concrete by others) (5 areas)
- Fine grade porch areas (stone + concrete by others) (5 areas)
- Credit: fine grading of garage/porch (-$3,200)

**BOQ Positions:**

| Ordinal | Description | Qty | Unit | Cost Item | Rate |
|---------|-------------|-----|------|-----------|------|
| 06.10.0010 | Crawlspace and footer excavation (5 foundations, stockpile on site) | 720 | CY | EXC-CRW-01 | $14.00 |
| 06.20.0010 | Foundation perimeter drain (4" corrugated, geotextile, #57 stone) | 1,000 | LF | DRN-PRM-01 | $22.00 |
| 06.30.0010 | Fine grade crawlspace + vapor barrier + 4" #57 stone | 6,400 | SF | GRD-CRW-01 | $1.35 |
| 06.40.0010 | Fine grade garage areas (5 garages) | 2,500 | SF | GRD-SIT-01 | $0.45 |
| 06.40.0020 | Fine grade porch areas (5 porches) | 1,200 | SF | GRD-SIT-01 | $0.45 |
| — | Credit: fine grading garage/porch | *LS* | — | — | *credit* |

### Job 38578 — Additional Work ($85,978.75)

From the TCG estimate notes:
- Site consultation
- Layout and stake 4 building corners
- Establish finished foundation elevation
- Cut topsoil and stockpile
- Excavate and level site for building pads
- Import, place, and compact fill to 95%
- Excavator and hammer for 1 month
- EXCLUDED: building backfill, topsoil respreading, seeding, compaction test

**BOQ Positions:**

| Ordinal | Description | Qty | Unit | Cost Item | Rate |
|---------|-------------|-----|------|-----------|------|
| 07.10.0010 | Site consultation and layout/staking | 1 | LS | SIT-LAY-01 | $1,300.00 |
| 07.20.0010 | Cut topsoil and stockpile | 1,955 | CY | EXC-BLK-01 | $12.45 |
| 07.20.0020 | Bulk excavation and level for building pads | 1,955 | CY | EXC-BLK-01 | $12.45 |
| 07.20.0030 | Import, place, and compact fill to 95% | 1,955 | CY | FILL-CMP-01 | $18.50 |
| 07.30.0010 | Site grading and fine grade | 45,225 | SF | GRD-SIT-01 | $0.45 |
| 07.40.0010 | Excavator 30T + hydraulic hammer rental (monthly) | 1 | MO | EQP-RNT-HMR | $13,500.00 |

---

## Component Breakdowns

All items follow the same resource-based methodology as Pilot Batch 1:
- **Labor rates:** BLS OEWS May 2024 Nashville MSA (from `data/bls_labor_wages.json`)
- **Equipment rates:** USACE EP 1110-1-8 Region 3 Southeast (from `data/usace_equipment_rates.json`)
- **Material rates:** Nashville market estimates (extend `data/material_rates.json` with new codes below)

### New Material Codes Required

| Code | Description | Unit | Rate | Source |
|------|-------------|------|------|--------|
| MAT-CON-3500 | Ready-mix concrete, 3500 PSI, delivered | CY | $225.00 | Nashville batch plant estimate |
| MAT-ASP-HM | Hot mix asphalt (surface course) | TON | $135.00 | Nashville asphalt plant estimate |
| MAT-2A-STONE | #2A stone (crusher run, 3/4" minus) | CY | $40.00 | Quarry pricing estimate |
| MAT-CON-FORMS | Form lumber + stakes for curb (per LF) | LF | $1.50 | Home Depot/Lowe's estimate |
| MAT-CON-JOINTS | Expansion joint + curing compound (per LF) | LF | $0.40 | Supplier estimate |
| MAT-PVC-3 | 3" PVC schedule 40 pipe | LF | $2.50 | Home Depot/Lowe's estimate |
| MAT-PVC-15 | 1.5" PVC schedule 40 pipe | LF | $1.50 | Home Depot/Lowe's estimate |
| MAT-STONE-DUST | Stone dust / crusher run screenings | CY | $28.00 | Quarry pricing estimate |
| MAT-RCP-18 | 18" reinforced concrete pipe (Class III) | LF | $22.00 | Precast supplier estimate |
| MAT-HDW-18 | Precast concrete headwall for 18" RCP | EA | $800.00 | Precast supplier estimate |
| MAT-CORR-4 | 4" corrugated perforated HDPE pipe | LF | $2.25 | Home Depot/Lowe's estimate |
| MAT-VB-10MIL | Vapor barrier, 10 mil polyethylene | SF | $0.25 | Home Depot/Lowe's estimate |
| MAT-RIP-RAP | Rip rap stone / outlet protection | CY | $45.00 | Quarry pricing estimate |

### Item Component Detail

Each item below includes its full component array. Validate with:
```python
assert abs(item["rate"] - sum(c["cost"] for c in item["components"])) < 0.01
```

#### CON-CUR-01 — Concrete curb and gutter

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Cement Mason (SOC 47-2051) | labor | 0.12 hr | $24.15/hr | $2.90 |
| Construction Laborer (SOC 47-2061) | labor | 0.12 hr | $22.45/hr | $2.69 |
| Excavator 20T (CAT 320, subgrade) | equipment | 0.02 hr | $60.94/hr | $1.22 |
| Vibratory Roller 5.2T | equipment | 0.015 hr | $30.73/hr | $0.46 |
| 3500 PSI concrete (0.02 CY, 10% waste) | material | 0.02 CY | $225.00/CY | $4.50 |
| #2A stone base, 4" depth | material | 0.025 CY | $40.00/CY | $1.00 |
| Form lumber, stakes, hardware | material | 1.00 LF | $1.50/LF | $1.50 |
| Expansion joint + curing compound | material | 1.00 LF | $0.40/LF | $0.40 |
| **TOTAL** | | | | **$14.67** |

#### CON-RCB-01 — Concrete ribbon curb

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Cement Mason (SOC 47-2051) | labor | 0.08 hr | $24.15/hr | $1.93 |
| Construction Laborer (SOC 47-2061) | labor | 0.08 hr | $22.45/hr | $1.80 |
| Excavator 20T (subgrade) | equipment | 0.015 hr | $60.94/hr | $0.91 |
| Vibratory Roller 5.2T | equipment | 0.01 hr | $30.73/hr | $0.31 |
| 3500 PSI concrete (0.012 CY) | material | 0.012 CY | $225.00/CY | $2.70 |
| #2A stone base (minimal) | material | 0.015 CY | $40.00/CY | $0.60 |
| Form lumber, stakes | material | 1.00 LF | $1.00/LF | $1.00 |
| **TOTAL** | | | | **$9.25** |

#### ASP-PAV-01 — Asphalt pavement, 3.5"

| Component | Type | Qty/SF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer, raker (2 workers) | labor | 0.015 hr | $22.45/hr | $0.34 |
| Operating Engineer (paver, SOC 47-2073) | labor | 0.01 hr | $25.58/hr | $0.26 |
| Asphalt Paver (estimated) | equipment | 0.01 hr | $89.00/hr | $0.89 |
| Vibratory Roller 10.2T (breakdown + finish) | equipment | 0.015 hr | $64.84/hr | $0.97 |
| Hot mix asphalt (3.5" @ 145 lb/CF = 0.021 ton/SF) | material | 0.021 ton | $135.00/ton | $2.84 |
| Tack coat emulsion | material | $0.15/SF | — | $0.15 |
| **TOTAL** | | | | **$5.45** |

#### STN-BSE-01 — Stone base, 8" crushed

| Component | Type | Qty/SF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer (SOC 47-2061) | labor | 0.005 hr | $22.45/hr | $0.11 |
| Motor Grader 12-ft (spreading) | equipment | 0.005 hr | $65.63/hr | $0.33 |
| Vibratory Roller 10.2T (compaction) | equipment | 0.003 hr | $64.84/hr | $0.19 |
| #2A stone (crusher run, 8" depth = 0.025 CY/SF) | material | 0.025 CY | $40.00/CY | $1.00 |
| **TOTAL** | | | | **$1.63** |

#### UT-ELC-01 — Electrical conduit, 3" PVC

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Pipelayer (SOC 47-2151) | labor | 0.08 hr | $22.77/hr | $1.82 |
| Operating Engineer (SOC 47-2073) | labor | 0.06 hr | $25.58/hr | $1.53 |
| Construction Laborer (SOC 47-2061) | labor | 0.06 hr | $22.45/hr | $1.35 |
| Excavator 20T (trench 18" wide × 3' deep) | equipment | 0.06 hr | $60.94/hr | $3.66 |
| Vibratory Roller 5.2T (backfill compaction) | equipment | 0.03 hr | $30.73/hr | $0.92 |
| 3" PVC schedule 40 conduit (5% waste) | material | 1.05 LF | $2.50/LF | $2.63 |
| PVC couplings, elbows, sweeps (per LF allowance) | material | 1.00 LF | $1.50/LF | $1.50 |
| Stone dust backfill (12" above conduit, 0.05 CY/LF) | material | 0.05 CY | $28.00/CY | $1.40 |
| Sand bedding (6" pipe zone) | material | 0.03 CY | $35.00/CY | $1.05 |
| Red detectable tracer tape | material | 1.00 LF | $0.15/LF | $0.15 |
| **TOTAL** | | | | **$16.01** |

#### UT-COM-01 — Communications conduit, 1.5"

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Pipelayer (SOC 47-2151) | labor | 0.03 hr | $22.77/hr | $0.68 |
| Construction Laborer (SOC 47-2061) | labor | 0.02 hr | $22.45/hr | $0.45 |
| 1.5" PVC schedule 40 conduit (5% waste) | material | 1.05 LF | $1.50/LF | $1.58 |
| PVC fittings (per LF allowance) | material | 1.00 LF | $0.50/LF | $0.50 |
| **TOTAL** | | | | **$3.21** |

#### UT-GAS-01 — Gas line trench, stone dust backfill

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Operating Engineer (SOC 47-2073) | labor | 0.10 hr | $25.58/hr | $2.56 |
| Construction Laborer (SOC 47-2061) | labor | 0.10 hr | $22.45/hr | $2.25 |
| Excavator 20T (3' wide × 3' deep trench) | equipment | 0.10 hr | $60.94/hr | $6.09 |
| Vibratory Roller 5.2T (backfill compaction) | equipment | 0.05 hr | $30.73/hr | $1.54 |
| Stone dust backfill (pipe zone + 12" cover, 0.16 CY/LF) | material | 0.16 CY | $28.00/CY | $4.48 |
| Yellow detectable tracer tape | material | 1.00 LF | $0.15/LF | $0.15 |
| **TOTAL** | | | | **$17.07** |

#### STR-RCP-18 — 18" RCP storm pipe

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer, 2 workers (SOC 47-2061) | labor | 0.15 hr | $22.45/hr | $3.37 |
| Pipelayer (SOC 47-2151) | labor | 0.10 hr | $22.77/hr | $2.28 |
| Operating Engineer (SOC 47-2073) | labor | 0.08 hr | $25.58/hr | $2.05 |
| Excavator 20T (trench, lower pipe) | equipment | 0.08 hr | $60.94/hr | $4.88 |
| Vibratory Roller 5.2T (backfill compaction) | equipment | 0.04 hr | $30.73/hr | $1.23 |
| 18" RCP Class III (5% waste) | material | 1.05 LF | $22.00/LF | $23.10 |
| Sand bedding (8" pipe zone + haunch, 0.06 CY/LF) | material | 0.06 CY | $35.00/CY | $2.10 |
| Gaskets, joint lubricant, fittings | material | 1.00 LF | $5.00/LF | $5.00 |
| **TOTAL** | | | | **$44.01** |

#### STR-HDW-01 — Precast concrete headwall with outlet protection

| Component | Type | Qty/EA | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer, 2 workers (SOC 47-2061) | labor | 6 hr | $22.45/hr | $134.70 |
| Operating Engineer (SOC 47-2073) | labor | 2 hr | $25.58/hr | $51.16 |
| Excavator 20T (set headwall, grade outlet) | equipment | 2 hr | $60.94/hr | $121.88 |
| Vibratory Roller 5.2T (outlet compaction) | equipment | 1 hr | $30.73/hr | $30.73 |
| Precast concrete headwall, 18" RCP | material | 1 EA | $800.00/EA | $800.00 |
| Rip rap stone, outlet protection | material | 3 CY | $45.00/CY | $135.00 |
| Grout, mortar, sealant | material | 1 EA | $50.00/EA | $50.00 |
| **TOTAL** | | | | **$1,323.47** |

#### EXC-CRW-01 — Crawlspace and footer excavation

| Component | Type | Qty/CY | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Operating Engineer (SOC 47-2073) | labor | 0.09 hr | $25.58/hr | $2.30 |
| Construction Laborer, grade check (SOC 47-2061) | labor | 0.12 hr | $22.45/hr | $2.69 |
| Excavator 30T (CAT 326F, precision digging) | equipment | 0.06 hr | $73.58/hr | $4.41 |
| Bulldozer D6 (CAT D6N, stockpile shaping) | equipment | 0.02 hr | $98.25/hr | $1.97 |
| Vibratory Roller 10.2T (bottom compaction) | equipment | 0.01 hr | $64.84/hr | $0.65 |
| Grade stakes, marking paint, string line | material | $0.50/CY | — | $0.50 |
| **TOTAL** | | | | **$12.52** |

#### DRN-PRM-01 — Foundation perimeter drain

| Component | Type | Qty/LF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Operating Engineer (SOC 47-2073) | labor | 0.06 hr | $25.58/hr | $1.53 |
| Pipelayer (SOC 47-2151) | labor | 0.06 hr | $22.77/hr | $1.37 |
| Construction Laborer (SOC 47-2061) | labor | 0.08 hr | $22.45/hr | $1.80 |
| Excavator 20T (shallow trench for foundation drain) | equipment | 0.06 hr | $60.94/hr | $3.66 |
| Vibratory Roller 5.2T (backfill compaction) | equipment | 0.03 hr | $30.73/hr | $0.92 |
| 4" corrugated perforated HDPE pipe (5% waste) | material | 1.05 LF | $2.25/LF | $2.36 |
| #57 stone (12" surround, 0.10 CY/LF) | material | 0.10 CY | $45.00/CY | $4.50 |
| Geotextile fabric (6 SF per LF for wrap) | material | 6.0 SF | $0.85/SF | $5.10 |
| HDPE fittings, connectors, outlet fittings | material | 1.00 LF | $1.00/LF | $1.00 |
| **TOTAL** | | | | **$22.24** |

#### GRD-CRW-01 — Fine grade crawlspace with vapor barrier + stone

| Component | Type | Qty/SF | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer (SOC 47-2061) | labor | 0.015 hr | $22.45/hr | $0.34 |
| Vibratory Roller 5.2T (surface compaction) | equipment | 0.005 hr | $30.73/hr | $0.15 |
| Vapor barrier, 10 mil polyethylene (15% lap) | material | 1.15 SF | $0.25/SF | $0.29 |
| #57 stone, 4" depth (0.012 CY/SF) | material | 0.012 CY | $45.00/CY | $0.54 |
| **TOTAL** | | | | **$1.32** |

#### EQP-RNT-HMR — Excavator + hydraulic hammer, monthly

| Component | Type | Qty/MO | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Excavator 30T (CAT 326F), monthly rental | material | 1 MO | $10,000.00/MO | $10,000.00 |
| Hydraulic hammer attachment, monthly rental | material | 1 MO | $3,500.00/MO | $3,500.00 |
| **TOTAL** | | | | **$13,500.00** |

#### SIT-LAY-01 — Site layout and staking

| Component | Type | Qty/LS | Unit Rate | Cost |
|-----------|------|--------|-----------|------|
| Construction Laborer, 2 workers × 8 hr (SOC 47-2061) | labor | 16 hr | $22.45/hr | $359.20 |
| Survey equipment rental (transit/level/laser) | material | 1 LS | $500.00/LS | $500.00 |
| Batter boards, wood stakes, ribbon, paint, string | material | 1 LS | $350.00/LS | $350.00 |
| **TOTAL** | | | | **$1,209.20** |

---

## Data Sources (Shared with Pilot)

See Pilot Batch 1 document for full details on:

| Source | File | Status |
|--------|------|--------|
| USACE EP 1110-1-8 Region 3 Southeast | `data/usace_equipment_rates.json` | Already parsed (14 equipment codes) |
| BLS OEWS Nashville MSA May 2024 | `data/bls_labor_wages.json` | Already parsed (7 SOC codes) |
| Nashville material estimates | `data/material_rates.json` | Needs extension (13 new codes above) |
| TDOT bid prices | `data/tdot_bid_prices.json` | Needs extension (new items below) |

### New TDOT Comparison Items

| Our Code | TDOT Item | Description | Unit |
|----------|-----------|-------------|------|
| CON-CUR-01 | 608-01 | Curb and Gutter, Concrete | LF |
| CON-RCB-01 | 608-03 | Ribbon Curb, Concrete | LF |
| ASP-PAV-01 | 411-01.02 | Asphalt Concrete Surface (PG64-22) | TON |
| STN-BSE-01 | 303-01 | Aggregate Base Course, 8" | SY |
| UT-ELC-01 | 795-04 | 3" PVC Conduit in Trench | LF |
| STR-RCP-18 | 710-03 | 18" RCP, Class III | LF |
| STR-HDW-01 | 710-14 | Precast Headwall, 18" | EA |
| DRN-PRM-01 | 710-04 | Underdrain, 4" (with geotextile) | LF |

---

## JSON Output File

All 13 + 1 (SIT-LAY-01) items go into:

**`data/us_tn_concrete_utilities_costs.json`**

Same schema as Pilot Batch 1 — each item has:
```json
{
  "code": "CON-CUR-01",
  "description": "...",
  "unit": "LF",
  "rate": 14.67,
  "currency": "USD",
  "source": "manual",
  "region": "USA_TENNESSEE",
  "classification": { "division": "03", "section": "3000", "category": "Cast-in-Place Concrete" },
  "components": [...],
  "tags": ["concrete", "curb", "sitework", "nashville", "tn"],
  "metadata": {
    "labor_hours": 0.24,
    "equipment_hours": 0.035,
    "data_sources": ["USACE EP 1110-1-8", "BLS OEWS May 2024 Nashville MSA"],
    "validation_status": "pilot",
    "tdot_comparison": { "tdot_item": "608-01", "tdot_rate_2024": null, "note": "pending TDOT lookup" }
  }
}
```

---

## File Structure

```
OCERP/
├── data/
│   ├── usace_equipment_rates.json          # Existing (14 equipment codes)
│   ├── bls_labor_wages.json                # Existing (7 SOC codes)
│   ├── material_rates.json                  # EXTEND with 13 new material codes
│   ├── tdot_bid_prices.json                # EXTEND with new comparison items
│   ├── us_tn_sitework_costs.json            # Batch 1 (12 items, existing)
│   └── us_tn_concrete_utilities_costs.json  # Batch 2 (14 items, TO BE BUILT)
├── scripts/
│   └── import_cost_database.py             # Reusable import script (updates below)
├── docs/
│   ├── US_COST_DATABASE_PILOT.md           # Batch 1 handoff
│   ├── US_COST_DATABASE_BATCH2.md          # This document
│   └── validation_report.md                # EXTEND
```

---

## Execution Checklist

- [ ] 1. Extend `data/material_rates.json` with 13 new material codes
- [ ] 2. Look up TDOT 2024 bid prices for 8 new comparison items → `data/tdot_bid_prices.json`
- [ ] 3. Build 14 CostItems with full component arrays → `data/us_tn_concrete_utilities_costs.json`
- [ ] 4. Validate: `rate == sum(components.cost)` for each item (tolerance ±$0.01)
- [ ] 5. Validate: no negative rates, no zero components
- [ ] 6. Import Batch 2: `POST /api/v1/costs/bulk/` with the new JSON
- [ ] 7. Verify in OCERP: search for `USA_TENNESSEE` region (should now show 26 items)
- [ ] 8. Create BOQ positions for all 4 remaining jobs (see BOQ tables above)
- [ ] 9. Compare OCERP totals vs BedRock CSV (see comparison tables below)
- [ ] 10. Compare OCERP component-level totals vs TDOT bid prices
- [ ] 11. Document validation report (extend `docs/validation_report.md`)
- [ ] 12. Update `data/IMPORT_INSTRUCTIONS.md` with Batch 2 items

---

## Expected Totals (vs BedRock CSV)

| Job | BedRock Total | OCERP Expected Range | Notes |
|-----|--------------|---------------------|-------|
| Concrete Curb (38447) | $61,154 | $45K - $55K | After $37K credit, effective net ~$18K |
| Trenching (38522) | $51,842 | $45K - $55K | Most items have strong cost item match |
| Excavation (38577) | $36,299 | $30K - $40K | Crawlspace + perimeter drain = bulk of cost |
| Additional Work (38578) | $85,979 | $70K - $90K | Excavator rental is $13.5K; rest is bulk earthwork |

Aim for ±25% variance in first pass; refine rates if >30% off.

---

## Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Asphalt paver hourly rate is estimated (not in USACE data) | Mark source as `estimated`; refine with rental house pricing |
| Monthly equipment rental rates are rough estimates | Call local equipment rental companies for current Nashville rates |
| Some items (SIT-LAY-01) are lump sum — hard to validate per-unit | Accept reasonable range; note methodology |
| Credit items in TCG estimate reduce totals | Apply credits as separate negative positions with notes |
| UT-COM-01 shares trench with UT-ELC-01 — risk of double-counting | UT-COM-01 excludes trench labor + equipment by design |
| Items may need manual entry (lump sum credits, mill/overlay) | Create these as `source: "manual"` positions in BOQ, not via cost DB |

---

## Import Script Update

Update `scripts/import_cost_database.py` to accept a `--file` argument so it can import any cost JSON:

```python
# Add at top after imports:
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--file", default=DATA_FILE, help="Path to cost items JSON file")
args = parser.parse_args()
DATA_FILE = args.file
```

Usage:
```bash
python scripts/import_cost_database.py --file data/us_tn_concrete_utilities_costs.json
```

---

## Next Batch (Batch 3)

After Batch 2 is validated, the database will cover **all 7 TCG jobs**. Future development could add:

- **Batch 3** (~10 items): Erosion controls (silt fence, straw mulch, construction fence, erosion blankets)
- **Batch 4** (~8 items): Additional utility items (fire hydrants, water meters, backflow preventers, valve boxes)
- **Batch 5** (~6 items): Site finishing (seeding, sod, landscaping prep, topsoil placement)

---

## Contact / Questions

For issues or clarifications, refer to:
- OCERP cost module: `backend/app/modules/costs/`
- CostItem schema: `backend/app/modules/costs/schemas.py`
- Bulk import endpoint: `POST /api/v1/costs/bulk/` (estimator role with `costs.bulk_import` permission)
- Batch 1 data: `data/us_tn_sitework_costs.json` (reference for schema/examples)
- Batch 1 doc: `docs/US_COST_DATABASE_PILOT.md`

---

*End of Handoff Document*