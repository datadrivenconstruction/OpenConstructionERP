# Cross-Module Metric Drift Audit — OpenConstructionERP

**Date:** 2026-04-18  
**Phase:** 3 of 9  
**Scope:** BOQ totals, project costs, validation scores, KPI counts, currency aggregation, as-of-date consistency

Summary (by severity):

| Severity | Count |
|----------|------:|
| Critical | 1 |
| High     | 3 |
| Medium   | 2 |
| Info     | 0 |
| **Total**| **6** |

---

## 1. BOQ Grand Total Rollup — CRITICAL DRIFT

### Dashboard uses position sum; detail pages use markup-inclusive grand_total

**Dashboard (Box count includes markups):**
`backend/app/modules/projects/router.py:1041-1057`

Position sum only, no markups applied.

**BOQ Service (used by detail pages):**
`backend/app/modules/boq/repository.py:56-110`

Applies active markups (percentage and fixed) in sort order to compute final grand_total.

**Frontend Dashboard KPI display:**
`frontend/src/features/dashboard/DashboardPage.tsx:1603-1621`

Fetches BOQWithTotal from API and sums grand_total field. Box totals should include markups.

**Frontend BOQ Editor (in-page display):**
`frontend/src/features/boq/BOQEditorPage.tsx:1045-1075`

Computes directCost from positions, then applies markups client-side.

**Impact:**
- Dashboard shows boq_total_value = sum of positions ONLY
- User clicks into project detail card: same BOQ now shows 25% more (with markup)
- Portfolio analytics off by markup percentage

**Root cause:**
dashboard_cards endpoint computes direct cost only. grand_totals_for_boqs applies markups. Separate code paths, no shared utility.

---

## 2. Validation Score Formula Mismatch — HIGH DRIFT

### Engine uses weighted severity; BIM uses simple pass/fail ratio

**Validation Engine (BOQ validation, PRIMARY):**
`backend/app/core/validation/engine.py:122-135`

Score = passed_weight / total_weight, where weights are ERROR:3.0, WARNING:1.5, INFO:0.4

**BIM Validation Service (SECONDARY):**
`backend/app/modules/validation/bim_validation_service.py:174-205`

Score = passed_count / total_checks (no severity weighting)

**Example:**
9 INFO rules pass, 1 ERROR fails:
- Engine: (9×0.4 + 0×3.0) / (10×0.4 + 1×3.0) = 3.6 / 7.0 ≈ 0.514
- BIM: 9/10 = 0.90 — **36 point difference**

**Impact:**
User runs BOQ validation → sees 0.514 score. Switches to BIM validation → sees 0.90 for same rule results.

---

## 3. Dashboard Quality Score ≠ Validation Score — HIGH DRIFT

### Dashboard computes completeness % (positions with prices); validation reports use weighted formula

**Dashboard KPI card:**
`frontend/src/features/dashboard/DashboardPage.tsx:661-673`

Quality = % of positions with non-zero totals. Purely structural completeness, no rule checking.

**Actual validation report score:**
`backend/app/core/validation/engine.py:122-135`

Weighted by ERROR/WARNING/INFO severity. Checks correctness, not just presence.

**Impact:**
Dashboard: "Quality Score: 85%" (positions have prices)
Validation page: 0.62 score (weighted rule failures)
Same BOQ, two completely different "quality" metrics.

---

## 4. Project Cost Aggregation — Lacks Currency Conversion — HIGH DRIFT

### Dashboard sums budget across projects with different currencies

**Analytics overview:**
`backend/app/modules/projects/router.py:1237-1255`

Sums BudgetLine.planned_amount and actual_amount across all projects.
No FX conversion applied.

**Impact:**
Portfolio has projects in EUR (500K), USD (600K), GBP (400K).
Analytics returns total_planned: 1500 (raw sum, meaningless).
No currency specified; no conversion applied.

**Root cause:**
BudgetLine has no currency field. Raw sum across currencies without conversion.

---

## 5. Open Tasks vs. Dashboard Task Count — MEDIUM DRIFT

### Dashboard filters by different status than detail page

**Dashboard cards endpoint:**
`backend/app/modules/projects/router.py:1066-1077`

Filters Task.status IN ["draft", "open", "in_progress"]

**Tasks detail page:**
Allows user-selectable filters, likely includes additional statuses.

**Impact:**
Dashboard shows "Open Tasks: 3". Tasks page shows 5 tasks with custom filters.

---

## 6. EVM Snapshot — No Historical As-Of-Date Filtering — CLEAN

### Snapshot stores date correctly; design is sound

**EVM snapshot creation:**
`backend/app/modules/finance/service.py:452-523`

Snapshot stores pre-calculated PV/EV/AC/BAC values at a point in time. Does not attempt to recompute historical data.

**Conclusion:** No drift. Snapshot is correctly immutable. Design validates correctly.

---

## 7. RFI Open Count — MINOR DRIFT

### Dashboard filters RFIs; detail page may not

**Dashboard cards:**
`backend/app/modules/projects/router.py:1086-1097`

Filters RFI.status IN ["draft", "open", "in_review"]

Same pattern as tasks: hardcoded status filter. RFI detail page allows additional filters.

**Impact:** Low — typical user doesn't notice single-digit mismatches.

---

## Summary Table

| Metric | Dashboard | Detail Page | Match? | Status |
|--------|-----------|-------------|--------|--------|
| BOQ Total | Position sum (no markup) | Markup-inclusive | ❌ | CRITICAL |
| Validation Score | Completeness % | Weighted rules | ❌ | HIGH |
| Project Cost | Sum (no FX) | Per-project | ❌ | HIGH |
| Open Tasks | status IN (draft, open, in_progress) | User-selectable | ⚠ | MEDIUM |
| Open RFIs | status IN (draft, open, in_review) | User-selectable | ⚠ | MEDIUM |
| EVM Snapshots | Pre-computed, immutable | Historical lookup | ✓ | CLEAN |

---

## Top Actions

1. **BOQ Grand Total (CRITICAL):** Extract markup logic to shared utility. Update dashboard_cards endpoint to call boq_repo.grand_totals_for_boqs() instead of raw position sum.
   - File: backend/app/modules/boq/repository.py → create compute_boq_totals() helper
   - File: backend/app/modules/projects/router.py:1041-1057 → use shared helper
   - Impact: fixes portfolio totals across 10+ projects

2. **Validation Score (HIGH):** Unify formula. Update bim_validation_service.py:174 to use weighted engine.score instead of simple ratio.

3. **Dashboard Quality KPI (HIGH):** Rename to "Completeness %" or fetch actual ValidationReport.score.

4. **Project Cost Aggregation (HIGH):** Add currency check. File: backend/app/modules/projects/router.py:1254-1255 → log warning if >1 currency detected.

5. **Task/RFI Counts (MEDIUM):** Document hardcoded status filters or move to config.

