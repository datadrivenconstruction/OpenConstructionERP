# Agent I - Lossless Roundtrip (Export/Import) Report

**Date:** 2026-04-18
**Environment:** http://127.0.0.1:8080
**Tester:** Agent I (automated)
**Test file:** `C:/Users/Artem/OpenConstructionERP/qa_output/generated_tests/test_p5_agent_i_roundtrip.py`
**Artifacts:** `C:/Users/Artem/OpenConstructionERP/qa_output/agent_reports/part5/agent_i_artifacts/`

---

## 1. Summary

| Metric | Value |
|---|---|
| Roundtrip scenarios attempted | 3 (Excel, CSV, GAEB XML) |
| Scenarios where export + import both succeeded | 2 (Excel, CSV) |
| Scenarios lossless (byte/precision-exact) | **0** |
| Major feature gaps | **1** (GAEB XML import not implemented) |
| Data-loss findings | **7** distinct issues |
| Additional tests | Row-deletion, tamper, UTF-8 BOM |

**Verdict:** No format achieves lossless roundtrip. Excel is closest (preserves descriptions, quantities, unit_rates with full precision, and grand total), but section structure, unit types for sections and subtotal rows are corrupted on re-import. CSV loses decimal precision (2 dp). GAEB XML export works but there is no matching import endpoint — **major feature gap**.

---

## 2. Source BOQ

Built programmatically with 13 rows (3 sections + 10 positions). Data designed to stress-test Unicode, emoji, units, precision, zeros:

| Ordinal | Description (truncated) | Unit | Qty | Rate |
|---|---|---|---|---|
| 01 | Erdarbeiten / Earthworks (ç é) | (section) | - | - |
| 02 | Stahlbetonwände 🏗️ / Concrete | (section) | - | - |
| 03 | Geschäftskosten / Overhead (Ж) | (section) | - | - |
| 01.001 | Aushub Mutterboden (ç é) | m³ | 150.50 | 12.75 |
| 01.002 | Verfüllen mit Kies | m³ | 0 | 0 |
| 01.003 | Transport Ж Deponie | lsum | 1 | **12345.6789** |
| 02.001 | Stahlbetonwände C30/37, 24cm 🏗️ | m² | 420.25 | 185.50 |
| 02.002 | Schalung beidseitig ç | m² | 840.50 | 45.00 |
| 02.003 | Bewehrung Baustahl é | kg | 8500 | 1.25 |
| 02.004 | Ankerbolzen Ж | pcs | 120 | 8.40 |
| 03.001 | Baustelleneinrichtung | lsum | 1 | 5500.00 |
| 03.002 | Bauleitung Stunden | h | 320 | 85.00 |
| 03.003 | Geschäftskosten (Pauschale) | lsum | 1 | **12345.6789** |

Source grand total: **186,722.1078 EUR**

---

## 3. Per-Format Results

| Format | Export | Import | Lossless | Import endpoint | Grand total preserved |
|---|---|---|---|---|---|
| Excel (.xlsx) | ✅ 200 (6411 B) | ✅ 200 (imported=26, skipped=1) | ❌ | `POST /api/v1/boq/boqs/{id}/import/excel/` | ✅ 186722.1078 == 186722.1078 |
| CSV (.csv)    | ✅ 200 (1019 B) | ✅ 200 (imported=18, skipped=1) | ❌ | `POST /api/v1/boq/boqs/{id}/import/excel/` (same endpoint) | ~ 186722.11 vs 186722.1078 (-0.0022) |
| GAEB XML (.xml) | ✅ 200 (3133 B) | ❌ 400 | ❌ | **none** — /import/excel/ rejects XML; /import/smart/ also rejects .xml | n/a (no import) |

### 3.1 Excel roundtrip

- Source non-section rows: 13 (10 positions)
- Re-imported target: 26 positions (13 "real" + 13 ghost rows from Subtotal/Grand Total)
- **Descriptions:** byte-exact, including emoji 🏗️ and all UTF-8 chars ✅
- **Quantities:** exact ✅
- **Unit rates:** exact (12345.6789 preserved as-is in xlsx — no rounding) ✅
- **Units:** correct for positions; **sections re-imported with unit="pcs"** ❌
- **Section structure:** lost — sections become flat positions with numeric ordinals 2,4,6,... (row numbers), not grouped ❌
- **Grand total:** matches exactly ✅

### 3.2 CSV roundtrip

- Source non-section rows: 13 (10 positions)
- Re-imported target: 18 positions
- **Descriptions:** byte-exact (UTF-8, emoji preserved) ✅
- **Quantities:** exact ✅
- **Unit rates:** **2-dp truncation** — `12345.6789 → 12345.68` on both 01.003 and 03.003 ❌
- **Units:** same section issue — sections re-imported as unit="pcs" ❌
- **Section structure:** lost ❌
- **Extra ghost rows:** CSV export includes trailer rows ("Direct Cost", "Site Overhead", "Head Office Overhead", "Profit", "Contingency", "Grand Total") which are re-imported as positions with numeric ordinals 14-18 ❌
- **Grand total:** 186722.11 vs 186722.1078 (diff 0.0022 due to rounding)

### 3.3 GAEB XML roundtrip

- Export works, produces valid GAEB DA XML 3.3 namespace with UTF-8 preserved (emoji kept as Unicode in `<Text>` element).
- Known export quality issues:
  - Unit rates rounded to 2 dp (`12345.68`).
  - Unit conversion: `lsum → psch`, `pcs → Stk` (DE conventions — lossy if user wants source units back).
  - **All positions placed under ghost category `ID="00"` "Ungrouped Positions"** instead of their actual sections (`01`, `02`, `03` — which appear but with empty `<Itemlist />`). GAEB hierarchy is broken.
- **Import: not supported.** Neither `/import/excel/` nor `/import/smart/` accepts `.xml`.
  - `/import/excel/` → 400 `"Unsupported file type. Please upload an Excel (.xlsx) or CSV (.csv) file."`
  - `/import/smart/` → 400 `"Unsupported file type: .xml. Supported: xlsx, csv, pdf, jpg, png, tiff, rvt, ifc, dwg, dgn."`

---

## 4. Data-Loss Findings (Consolidated)

| # | Severity | Format(s) | Finding |
|---|---|---|---|
| F-01 | **Major** | GAEB | No import endpoint for GAEB XML. Export is a one-way door. Feature gap vs CLAUDE.md Phase-1 goal "GAEB XML import/export (X83)". |
| F-02 | **Major** | Excel, CSV | Section rows are exported but re-import treats them as **positions** (quantity=0, unit="pcs"). Hierarchical structure is lost on roundtrip. |
| F-03 | **Major** | CSV | Unit rates truncated to 2 decimal places on export (`12345.6789 → 12345.68`). Financial precision lost. |
| F-04 | **Major** | GAEB | Unit rates truncated to 2 decimal places on export. |
| F-05 | **Major** | GAEB | Sections exported as empty `<BoQCtgy>` containers; all Items dumped into fabricated `ID="00" Ungrouped Positions`. Section-membership relation broken. |
| F-06 | Minor | GAEB | Unit lexicon changes on export: `lsum→psch`, `pcs→Stk`. Roundtrip would be asymmetric even if import existed. |
| F-07 | **Major** | Excel, CSV | Export writes summary/footer rows (Subtotal: ..., Direct Cost, Grand Total, Site Overhead, Head Office Overhead, Profit, Contingency). Import does **not** recognize them as computed totals and creates ghost positions with made-up numeric ordinals (`2, 4, 6, 8, ... 26` for Excel; `14-18` for CSV). |
| F-08 | Minor | Excel | Every section's subtotal row is labelled `Subtotal: 03 Geschäftskosten / Overhead (Ж)` regardless of which section it follows — the export reuses the last section label for all subtotals (bug in the export serializer). See artifact `source_export.xlsx` rows 8,10,12,14,... |
| F-09 | Observation | Excel, CSV | Classification column exported as empty string. Source did not set classification in this test, but if set, whether it survives roundtrip is untested here (no positions with classification). Recommend follow-up test with classification.din276=330. |
| F-10 | Observation | Excel, CSV | `metadata`, `source`, `confidence`, `cad_element_ids`, `wbs_id`, `cost_code_id`, `validation_status`, `parent_id` fields from PositionResponse are not in the export schema (columns: Pos., Description, Unit, Quantity, Unit Rate, Total, Classification). These are silently dropped on any roundtrip. |

---

## 5. Additional Tests

### 5.1 Berlin project — delete rows, re-import

**Not executed** — no Berlin project exists in this instance (projects list: `QA_ValTest`, `QA_InvalidCurrency` x6, `QA_TestProject_Minimal`, `QA_alert(1)`). The test harness probes `name`, `location`, `city`, `metadata` for "berlin" and found none. Recommend seeding a demo Berlin project, or relaxing the test to simply export any BOQ, delete rows in xlsx, re-import, and compare counts.

### 5.2 Tamper unit_rate in Excel

- Took the Excel export, located cell `E12` (Unit Rate for position 01.003), original value `12345.6789`.
- Overwrote with `999999.99` in the xlsx using openpyxl.
- Uploaded via `/import/excel/`.
- Result: `import_status=200`, target BOQ contains a position with `unit_rate=999999.99`. **Tampered value was accepted without any validation flag or warning.**
- **Behavior:** server trusts the client file. No anomaly detection on import. This is a security/quality consideration — an editor could silently 10x a line item and the system accepts it. Consider adding the `boq_quality` validation pass (unrealistic unit-rate range) mentioned in `CLAUDE.md` Validation Pipeline on import.

### 5.3 UTF-8 BOM detection

- Source CSV export is **without** BOM.
- Wrapped the same content with and without BOM and re-imported both:
  - With BOM: `status=200`, 18 positions imported.
  - Without BOM: `status=200`, 18 positions imported.
- **Behavior:** import accepts both forms. No parsing error with BOM. ✅

---

## 6. Raw evidence

- `agent_i_artifacts/source_export.xlsx` — original export of source BOQ
- `agent_i_artifacts/source_export.csv` — original CSV export (no BOM)
- `agent_i_artifacts/source_export.xml` — GAEB XML export
- `agent_i_artifacts/tampered_unit_rate.xlsx` — xlsx with E12 overwritten to 999999.99
- `agent_i_artifacts/results.json` — full machine-readable scenario results

Relevant source paths in app:
- Export code paths live under `/api/v1/boq/boqs/{id}/export/{excel,csv,gaeb}/` (see `backend/app/modules/boq/router.py`).
- Import endpoints: `/api/v1/boq/boqs/{id}/import/excel/` and `/import/smart/` (the former accepts xlsx and csv; the latter adds pdf, images, rvt, ifc, dwg, dgn but **explicitly rejects xml**).

---

## 7. Recommendations

1. **Implement GAEB XML import** (highest priority — closes roundtrip gap mandated by CLAUDE.md Phase 1).
2. **Preserve section rows on import.** The Excel/CSV parser should recognize section rows (no unit/qty/rate, ordinal matches `^\d{2}$` pattern, or a dedicated marker column) and create `Section` records instead of `Position` records.
3. **Skip summary/subtotal/grand-total rows on import.** Detect "Subtotal:", "Direct Cost", "Grand Total", "Site Overhead", "Head Office Overhead", "Profit", "Contingency" labels and ignore them.
4. **Stop 2-dp truncation on export.** Serialize unit_rate with full precision (Decimal). Use locale-neutral format (`12345.6789`, not `12345.68`).
5. **Fix subtotal label bug** in Excel exporter — it currently reuses the last section's label for every subtotal row (evidence: rows 8,10,12,14... all show "Subtotal: 03 Geschäftskosten / Overhead (Ж)").
6. **Fix GAEB hierarchy**: place each `<Item>` inside its parent `<BoQCtgy>.<BoQBody>.<Itemlist>`, not under a fabricated `ID="00" Ungrouped Positions`.
7. **Add validation on import** (boq_quality rules): flag unrealistic unit-rate jumps vs previous import of same ordinal.
8. **Document the Classification column format** in Excel/CSV export; today it is exported as empty even when classification is set via API.
9. **Add a `metadata` / `source` / `confidence` round-trip column** (possibly optional / hidden) to prevent silent loss of provenance when users edit in Excel and re-import.

---

## 8. Test status

- Source BOQ created: ✅
- Excel export → Excel import: completed, lossless=❌
- CSV export → Excel import: completed, lossless=❌
- GAEB export → any import: **blocked — no endpoint**
- Tamper test: completed (accepted)
- BOM / no-BOM CSV: completed (both accepted)
- Berlin delete-rows test: skipped (no Berlin demo project in this instance)
