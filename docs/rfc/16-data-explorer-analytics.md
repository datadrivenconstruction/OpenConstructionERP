# RFC 16 — Data Explorer: Power BI-style analytics

**Status:** draft
**Related items:** ROADMAP_v1.9.md #16 (R2 → v1.9.1)
**Date:** 2026-04-17

## 1. Context

The Data Explorer at `/data-explorer` is a working MVP with 4 tabs — Data / Pivot / Charts / Describe. The user asks: "what features are missing to make it feel like Power BI or Tableau?"

### Current inventory (`frontend/src/features/cad-explorer/CadDataExplorerPage.tsx`)

| Tab | Features | Lines |
|-----|----------|-------|
| Data | pagination, sort, global search, single-column filter, column-visibility, heatmap, CSV export, page totals | 64–382 |
| Pivot | multi-level group-by, multiple agg columns, tree expansion, CSV export, Create-BOQ from pivot | 386–713 |
| Charts | bar, pie (custom SVG — no chart lib), category + value selectors | 718–881 |
| Describe | data completeness %, dtype inference, stats table, value-counts | 885–1004 |

**Backend:** `backend/app/modules/takeoff/router.py` — `cad_data_describe`, `aggregate`, `elements`, `value_counts`.

**Libraries available in `package.json`:** `ag-grid-community` (used by BOQ, not here), `recharts` (installed, unused). Custom `<table>` renders the grid.

### Gap against Power BI / Tableau

- Pivot drag-drop UI — absent (button-click only)
- Cross-filter (chart → table, table → chart) — absent
- Chart types beyond bar / pie — absent (no line, scatter, heatmap, area)
- Measure creation / calculated columns — absent
- Drill-down from chart to detail rows — absent
- Saved views / bookmarks — absent (sessions are saved, analysis state isn't)
- Multi-column slicers — absent
- Number formatting (currency, %, thousands) — partial
- Top-N / bottom-N filters — absent (charts auto-sort desc, table doesn't)
- Export Excel with formatting — partial (CSV only)

## 2. Options considered

### Option A — Lightweight layer (Recharts + React state)

Keep custom `<table>`, add Recharts for richer charts, introduce a `useAnalysisStateStore` Zustand store for cross-filter + saved views. Ships in ~3 weeks.

### Option B — AG Grid Enterprise upgrade

Replace custom `<table>` with AG Grid Enterprise (drag-drop pivot, charts, row grouping built-in). Commercial licence cost, major refactor.

### Option C — Dedicated "Analytics Mode" full-screen workspace

Separate full-screen workspace with drop zones (Tableau-like). Large UX design investment.

## 3. Decision

**Option A — lightweight Recharts layer.**

B is rejected for v1.9.1 because of the licence cost and refactor size. C is rejected because the current 4-tab layout is well-understood by users; a new workspace is scope creep. A delivers 7 of the 12 Power-BI gaps in 3 weeks with no licence change.

### v1.9.1 shortlist (7 items, ordered by ROI)

| Rank | Feature | Size | Notes |
|------|---------|------|-------|
| 1 | Cross-filter chart ↔ table | S | Click a bar / slice → filter table; highlight chart row on table row hover |
| 2 | Multi-column slicer panel | S | Chip-based filters; supports AND across columns |
| 3 | Top-N / bottom-N toggle | S | "Show top 10" radio in Charts and Pivot |
| 4 | Line chart + Scatter chart (Recharts) | M | Replaces custom SVG charts; adds time-series + correlation |
| 5 | Saved analysis snapshots | M | Serialise filters + pivot config + chart config → persist on `CadExtractionSession.columns_metadata` |
| 6 | Chart drill-down to detail rows | M | Click a bar → modal with rows for that category |
| 7 | Currency / % / thousand-separator formatting | S | Dropdown in Charts tab; applied via `Intl.NumberFormat` |

### Deferred to v1.9.2+

- Drag-drop pivot UI (Option B territory)
- Calculated measures / DAX-lite
- Multi-file sessions (union/append)

## 4. Implementation sketch

### 4.1 State store

New file `frontend/src/stores/useAnalysisStateStore.ts`:
```ts
type SlicerFilter = { column: string; values: string[] };
type ChartConfig = {
  kind: 'bar' | 'line' | 'pie' | 'scatter';
  category: string;
  value: string;
  topN: number | null; // null = all
  format: 'number' | 'currency' | 'percent';
};
type SavedView = { id: string; name: string; filters: SlicerFilter[]; chart: ChartConfig; pivot: PivotConfig };
```

### 4.2 Cross-filter

`ChartsTab` — on `onClick` of a bar/slice/point, call `store.addSlicer(category, [clickedValue])`. `DataTableTab` and `PivotTab` read the same store and apply filters.

### 4.3 Recharts migration

Replace `ChartsTab` custom SVG (L804-870) with Recharts `<BarChart>`, `<LineChart>`, `<PieChart>`, `<ScatterChart>`. Shared `<ResponsiveContainer>` wrapper. Keep the existing colour palette.

### 4.4 Saved views

PATCH `/v1/takeoff/cad-sessions/{id}` with `{ analysis_state: {...} }` → stored in `CadExtractionSession.columns_metadata.analysis_state`. Frontend list lives on a right-side "Views" drawer.

### 4.5 Drill-down modal

Reuse the existing position-creation modal pattern (`CreateBOQFromPivotModal` at L1010-1209) as the UX blueprint — modal with filtered rows from the click context.

## 5. Testing plan

**Unit** (`cad-explorer/__tests__/`):
- Slicer store: add / remove / cross-column filter composition
- Format helpers: currency, percent, thousand-separator edge cases
- Top-N: stable when the nth-and-(n+1)th values tie

**E2E** (`frontend/e2e/v1.9/16-data-explorer.spec.ts`):
- Click chart bar → table row count reduces and shows only the category
- Add slicer chip for "Material = Concrete" → charts update
- Save view, reload page, verify state restored
- Switch to line chart, verify axes and units format
- Top-5 toggle → chart shows exactly 5 entries

**Visual regression:** snapshot of each chart type with a fixed dataset.

## 6. Risks / follow-ups

- **Bundle size.** Recharts is ~38 kB gzipped — modest. Keep charts lazy-loaded.
- **Cross-filter loops.** Guard against chart-click → slicer → chart-refetch feedback loops by debouncing (100 ms) and diffing the slicer values.
- **Custom `<table>` performance.** With 100 k+ rows plus slicers the O(n) filter in memory is fine; defer AG Grid upgrade unless profiler flags it.
- **Persistence schema.** Saved views live in `columns_metadata` today; if the list grows, migrate to a dedicated `cad_analysis_views` table in v1.9.2.
