# Cost Benchmarks Uplift Spec

Status: draft for founder review
Owner: Cost Benchmarks module
Scope: make the Cost Benchmarks module realistic, comparable against the user's own project data, and properly wired into the rest of the platform.

## 0. Guardrails for this work

i18n: this plan must NOT touch `frontend/src/app/locales/en.ts` or any other locale file. The module already uses the inline default pattern, for example `t('benchmarks.x', { defaultValue: 'Plain English' })`. Every new string introduced here keeps that exact pattern so the work cannot collide with separate in-flight i18n edits. The i18n sweep will pick the new keys up later from the rendered defaults. This is a hard rule for all phases.

Founder text rules: no em dashes or en dashes anywhere in user-facing text. Use a plain hyphen, a comma, or a full stop. No AI attribution anywhere. DataDrivenConstruction voice. Note that `costmodel/CostBenchmark.tsx` currently renders a literal `&ndash;` between the min and max range. That is an HTML en dash entity in a user-facing string and should be replaced with the word "to" or a plain hyphen as part of Phase 3 when we touch that file.

Infrastructure: PostgreSQL only, embedded PG on desktop. Prefer extending the existing costs module services over new infrastructure. Any new endpoint must degrade gracefully to industry-only output when the tenant has zero of their own projects.

Progressive enhancement: the module ships default-enabled, so it must keep working fully client-side when the backend endpoint is absent or returns an error. The static dataset in `data/benchmarks.ts` stays the client-side fallback and the source of truth for industry reference ranges. The backend endpoint only enriches the view, it is never required for the page to render.

## 1. Current state summary

The module is a standalone page at `/benchmarks` backed by a static table.

Files in `frontend/src/modules/cost-benchmark/`:
- `BenchmarkModule.tsx` renders the page. It holds four pieces of local state: `buildingType`, `region`, `gfa`, `totalCost`, all hardcoded defaults. There is no project context, no URL params, no API calls.
- `data/benchmarks.ts` holds `BenchmarkRange` (min, q1, median, q3, max, source, year), `BuildingType` (9 values), `BenchmarkRegion` (DE, AT, CH, UK, US), the `BENCHMARKS` table, and `calculatePercentile`.
- `manifest.ts` registers the route and a search entry. `navItems` is empty so the page is reachable only via search.

A second, duplicated and inconsistent surface lives at `frontend/src/features/costmodel/CostBenchmark.tsx`. It hardcodes its own min and max ranges for 6 project types and is embedded as a card in the cost model dashboard. Its data does not agree with `benchmarks.ts` and it carries the `&ndash;` entity noted above.

## 2. Richer, more realistic benchmark dataset

### 2.1 New TypeScript types

Replace the current `BenchmarkRange` and `BuildingTypeInfo` in `data/benchmarks.ts` with the shapes below. The percentile fields stay so the existing visual bar and `calculatePercentile` keep working unchanged.

```ts
export type CurrencyCode = 'EUR' | 'CHF' | 'GBP' | 'USD';

export interface CostGroupSplit {
  /** DIN 276 KG300 share of KG300+400, 0..1. */
  kg300Pct: number;
  /** DIN 276 KG400 share of KG300+400, 0..1. kg300Pct + kg400Pct === 1. */
  kg400Pct: number;
}

export interface SecondaryMetric {
  /** machine id, e.g. 'bed' | 'room' | 'pupil' | 'space' | 'seat' */
  unitId: string;
  /** plain English label used as a t() defaultValue at render time */
  label: string;
  /** typical cost per secondary unit in the cell currency */
  median: number;
  /** typical count assumed for a reference project of this type */
  typicalCount?: number;
}

export interface BenchmarkRange {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;

  /** KG300 vs KG400 split for this cell. */
  split: CostGroupSplit;
  /** per-unit secondary metric for this cell, when meaningful. */
  secondary?: SecondaryMetric;

  /** number of reference projects behind the cell. */
  sampleSize: number;
  /** 'high' | 'medium' | 'low' confidence label derived from sampleSize + recency. */
  confidence: 'high' | 'medium' | 'low';

  /** provenance */
  source: string;        // e.g. 'BKI Baukosten Gebaeude 2024'
  sourceYear: number;    // survey or publication year
  currency: CurrencyCode;
}

export interface BuildingTypeInfo {
  id: BuildingType;
  label: string;
  description: string;
  /** plain English scope note rendered with a t() defaultValue. */
  scopeNote: string;
  secondaryUnitId?: string;
}
```

`BuildingType`, `BenchmarkRegion`, `BENCHMARK_REGIONS` and `calculatePercentile` stay as they are. `BENCHMARK_REGIONS` gains nothing new in Phase 1. City-level sub-regions are deferred (see decisions).

### 2.2 New derived helpers in `data/benchmarks.ts`

```ts
/** Confidence label from sample size and source year. */
export function deriveConfidence(sampleSize: number, sourceYear: number): 'high' | 'medium' | 'low';

/** Split a cost/m2 figure into KG300 and KG400 components for a cell. */
export function splitByCostGroup(
  costPerM2: number,
  split: CostGroupSplit,
): { kg300: number; kg400: number };

/** Confidence label for a user value vs a cell: how trustworthy the comparison is. */
export function comparisonConfidence(range: BenchmarkRange): { label: string; key: string };
```

### 2.3 How to populate credibly

Keep medians close to the current values, they are reasonable. Add the new fields per cell as follows.

KG split: populate `split` per building type using realistic DIN 276 shares, the same split applied across regions for a given type. Offices and residential around kg300 0.80, kg400 0.20. Hospitals kg300 0.68, kg400 0.32. Schools and hotels kg300 0.76, kg400 0.24. Industrial, retail, warehouse kg300 0.85 to 0.90, kg400 0.10 to 0.15. These are documented as typical planning shares, not survey output, and the UI labels them as "typical split".

Secondary metrics: populate only where the unit is standard. Hospital per bed, hotel per room, school per pupil place. Derive a credible per-unit median from the cell median and a typical area per unit, for example hospital 75 to 110 m2 per bed, hotel 40 to 55 m2 per room, school 9 to 12 m2 per pupil place. Document the area assumption in the `scopeNote`.

Sample size and confidence: assign sampleSize per cell as an honest order of magnitude for the cited source (national published datasets are large, so 80 to 200 for common types, 30 to 80 for rarer types like specialty hospitals). `confidence` is derived, not hand-set, via `deriveConfidence`. The UI never claims more precision than the source supports.

Source and year: replace the vague strings with the specific publication, for example `BKI Baukosten Gebaeude 2024`, `BCIS Building Cost Information Service 2024`, `ENR Construction Cost Index 2024`, `Statistik Austria Baukostenindex 2024`, `SIA / BFS Schweiz 2024`. `sourceYear` is a number. No em dashes in any of these strings.

Honesty note rendered in the UI: a short line via `t('benchmarks.data_basis', { defaultValue: '...' })` stating that splits and per-unit figures are typical planning values, not a live feed, and that actual costs vary by location, specification and market.

## 3. User-data integration

### 3.1 Project picker

Add a project picker to `BenchmarkModule.tsx` that auto-fills `region`, `buildingType`, `gfa` and `totalCost` from the user's real project.

Fields and endpoints, all confirmed in the repo:
- `region`: from `Project.region` (`frontend/src/features/projects/api.ts`, `Project.region`). Map the free-form region string to a `BenchmarkRegion` with a small `mapProjectRegion(region, country_code)` helper, falling back to `country_code` when region is unrecognised, defaulting to DE.
- `buildingType`: from `Project.project_type`. This field already exists on the backend Project model (`backend/app/modules/projects/models.py:119`, `project_type: Mapped[str | None] String(50)`) and on `CreateProjectData`. Confirm it is exposed on the read `Project` interface (see gap G1 below) and map it to `BuildingType` with `mapProjectType(project_type)`.
- `totalCost`: from the project's BOQ grand total. Fetch BOQ list items for the project and sum `grand_total` (`frontend/src/features/boq/api.ts`, `BOQListItem.grand_total`, Decimal string). Prefer a cost rollup call if a single active BOQ is the convention, otherwise sum the list.
- `gfa`: there is no GFA field on Project today. This is gap G2 below. Until it lands, the picker leaves the existing `gfa` input editable and pre-fills nothing for area, with a one-line hint that area is not stored on the project yet.

Picker behaviour: a compact select at the top of the page listing the tenant's projects via `projectsApi.list()`. Selecting a project calls a new client hook `useProjectBenchmarkData(projectId)` that fetches the project and its BOQ totals and returns `{ region, buildingType, gfa, totalCost, currency, projectName }`. The four inputs then auto-fill but stay editable. A "clear" option returns to manual mode. When the tenant has zero projects, the picker is hidden and the page behaves exactly as today.

New file: `frontend/src/modules/cost-benchmark/hooks/useProjectBenchmarkData.ts`.

### 3.2 Your own portfolio distribution

Add a backend endpoint that returns both an industry reference and the tenant's own portfolio distribution for a given cost-per-m2 question, reusing the costs module services as the integration report recommends.

Endpoint: `POST /api/v1/costs/benchmark/` (costs router mounts at `/api/v1/costs`, confirmed via module loader kebab mounting). Permission `costs.read`.

Request schema `BenchmarkRequest`:
```
{
  "building_type": "office",          // optional, maps to project_type
  "region": "DE",                      // optional
  "currency": "EUR",                   // optional, never blends currencies
  "cost_per_m2": 2650.0                // optional, the user value to position
}
```

Response schema `BenchmarkResponse`:
```
{
  "currency": "EUR",
  "own_portfolio": {                   // null when tenant has no usable projects
    "project_count": 7,
    "min": "1850.00",
    "p25": "2100.00",
    "median": "2480.00",
    "p75": "2900.00",
    "max": "3600.00",
    "confidence": "medium",            // from CostCertaintyService style thresholds
    "note": "Based on 7 of your projects with cost and area."
  },
  "percentile_vs_own": 41.0,           // null when own_portfolio is null
  "explanation": "Your value sits below your own portfolio median."
}
```

Industry numbers are not returned by the endpoint. The client already owns the richer industry table and computes the industry percentile locally. The endpoint adds only the tenant-specific portfolio that the client cannot compute. This keeps the endpoint thin and the client authoritative for industry data.

Backend wiring, extending existing files only:
- `backend/app/modules/costs/schemas.py`: add `BenchmarkRequest`, `OwnPortfolio`, `BenchmarkResponse`.
- `backend/app/modules/costs/service.py`: add `CostBenchmarkService.portfolio_distribution(tenant, building_type, region, currency, cost_per_m2)`. It computes a cost-per-m2 per project from each project's BOQ grand total and its area, filters to the same currency, computes p25, median, p75, min, max, and a confidence label. Money serialised as Decimal strings per the money rule.
- `backend/app/modules/costs/router.py`: add `POST /benchmark/`.

Degrade gracefully: when the tenant has zero projects, or no project has both a cost and an area, `own_portfolio` is null and `percentile_vs_own` is null. The endpoint still returns 200. The client then shows industry-only, exactly as the offline path does.

Area source for the portfolio: this depends on gap G2. Two supported inputs in order of preference, decided by the founder: a real GFA field on Project, or area inferred from BOQ quantities. The service reads whichever is available and skips projects with no area. See decisions.

### 3.3 Percentile vs both

The results area shows two percentile readouts side by side: percentile vs industry, computed client-side from `benchmarks.ts`, always present, and percentile vs your own portfolio, from `percentile_vs_own`, shown only when `own_portfolio` is present. Both use the existing colour helper. When the portfolio is absent the second readout is replaced by a quiet line saying your portfolio comparison appears once you have projects with cost and area, via a `t(..., { defaultValue })` string.

## 4. Cross-module wiring

Each item is the smallest concrete change, taken from the integration report and trimmed to what is safe and useful.

Deep link from BOQ: add `useSearchParams` to `BenchmarkModule.tsx` reading `gfa`, `totalCost`, `region`, `buildingType`, `projectId` and pre-filling state on mount. In `frontend/src/features/boq/BOQSummaryPanel.tsx` add a "Benchmark this project" action that builds the query string from the current project and BOQ totals and navigates to `/benchmarks`. The action label uses the inline default pattern.

Validation report verdict: in `frontend/src/features/validation/ValidationPage.tsx`, when the report carries project cost, area and region, append one informational result computed client-side via a small `computeBenchmarkVerdict({ totalCost, gfa, region, buildingType })` helper exported from the module, rendering a row with a "View full comparison" link to `/benchmarks` carrying the same query string. No new backend rule, no new locale keys, all strings inline. The validation manifest does not need a hard `depends` because the helper import is a plain module import, keep manifests untouched in Phase 3 to avoid load-order surprises.

BI KPI tile: register a frontend-only widget renderer in `frontend/src/features/bi-dashboards/BIDashboardsPage.tsx` for `kpi_code === 'cost_percentile'` that shows the percentile and a link to `/benchmarks`. The percentile value can be computed client-side from project cost, area and the industry table, so no backend KPI is strictly required for v1. A backend `cost_percentile` KPI is deferred to a later phase and listed as a decision.

geo_hub regional factors: in `BenchmarkModule.tsx` add an optional fetch of a regional factor for the selected region and show the benchmark median both raw and "adjusted for your region". The fetch is best-effort, any error leaves the factor at 1.0 and the adjusted line hidden, preserving the offline guarantee.

AI estimator rates: when a project is selected and an estimator run exists, show a small "your rates vs industry" table below the main comparison, reading the latest run's resources. This is read-only and optional, hidden when no run exists.

AI advisor note: in `frontend/src/features/ai/AdvisorPage.tsx`, when project context is present, append a one-line cost positioning note built from the same client-side verdict helper, with a link to `/benchmarks`. No backend change required for v1.

Discoverability: add a `navItems` entry to `manifest.ts` pointing at `/benchmarks`, group `tools`, using the existing `nav.cost_benchmarks` label key with the inline default handled by the sidebar. No locale file edits, the sidebar already resolves missing keys to a sensible default through the same `t()` mechanism, and the search entry already exists.

## 5. UI section list, and relation to costmodel/CostBenchmark.tsx

Redesigned `BenchmarkModule.tsx` sections, top to bottom, Apple-tier clean, responsive, no overflow:

1. Header. Title and subtitle, unchanged.
2. Source line. One quiet line naming the active cell source and year, plus the data-basis honesty note.
3. Project picker plus inputs. The project select sits inline with the four inputs in a single responsive grid that wraps to one column on small screens. Picker hidden when there are zero projects.
4. Result KPIs. Three cards: your cost per m2, percentile vs industry, percentile vs your portfolio. The third card degrades to a quiet placeholder when no portfolio.
5. KG split strip. A thin two-segment bar showing the KG300 and KG400 split of the user value, with figures, from `splitByCostGroup`.
6. Industry distribution bar. The existing quartile bar with the marker, kept.
7. Your portfolio distribution bar. The same bar style fed by `own_portfolio`, shown only when present.
8. Secondary metric card. Per bed, per room or per pupil place when the building type defines one, otherwise hidden.
9. All building types comparison. The existing list, kept.
10. Data and confidence footer. Source, year, sample size and confidence for the active cell, plus the standing disclaimer.

Relation to `costmodel/CostBenchmark.tsx`: that card stays as the lightweight inline widget on the cost model dashboard and is refactored to import `BENCHMARKS` and types from the module data file instead of its own hardcoded ranges, removing the data divergence. It keeps its compact two-card look and simply reads `{ min, max, median }` from the shared cell for the mapped project type, using a small `mapProjectTypeToBuildingType` helper. The full multi-section experience lives only in the module page. The card links to `/benchmarks` for the deep view. This removes duplication and makes the two complement rather than compete. The `&ndash;` entity in that file is replaced with the word "to" when we touch it.

## 6. Phased build order

Phase 1, data realism, client-side only, no backend, no cross-links.
File set:
- `frontend/src/modules/cost-benchmark/data/benchmarks.ts` (new types, new fields per cell, new helpers)
- `frontend/src/modules/cost-benchmark/BenchmarkModule.tsx` (render source line, KG split strip, secondary metric card, confidence footer, all strings inline)
- `frontend/src/modules/cost-benchmark/manifest.ts` (add navItems entry)

Phase 2, user-data integration.
File set:
- backend `backend/app/modules/costs/schemas.py`, `service.py`, `router.py` (new endpoint and service)
- frontend `frontend/src/modules/cost-benchmark/hooks/useProjectBenchmarkData.ts` (new)
- frontend `frontend/src/modules/cost-benchmark/api.ts` (new, thin client for the benchmark endpoint with graceful fallback)
- frontend `frontend/src/modules/cost-benchmark/BenchmarkModule.tsx` (project picker, portfolio bar, percentile vs both)
- backend `backend/app/modules/projects/models.py` and schemas, plus a migration, only if the GFA field decision is taken (gap G2)

Phase 3, cross-links and dedup.
File set:
- `frontend/src/features/boq/BOQSummaryPanel.tsx` (benchmark action)
- `frontend/src/features/validation/ValidationPage.tsx` (verdict row)
- `frontend/src/features/bi-dashboards/BIDashboardsPage.tsx` (widget renderer)
- `frontend/src/features/ai/AdvisorPage.tsx` (positioning note)
- `frontend/src/modules/cost-benchmark/BenchmarkModule.tsx` (useSearchParams, geo factor, estimator table, verdict helper export)
- `frontend/src/features/costmodel/CostBenchmark.tsx` (import shared data, remove hardcoded ranges, replace `&ndash;`)

## 7. Assumptions and decisions needing founder confirmation

D1 GFA source. There is no GFA field on Project today and `project_type` already exists. Decide between: A add a real `gross_floor_area` numeric-as-string field to Project plus schema and migration, or B infer area from BOQ quantities, or C ask the user to type area in the picker for now and store nothing. Recommendation A for accuracy, with C as the interim so Phase 1 ships without backend.

D2 Confirm `project_type` is exposed on the read `Project` interface and that its values map cleanly to `BuildingType`. If the value vocabulary differs, confirm the mapping table.

D3 City-level sub-regions. The data-realism report wants city indices. Decision: keep five national regions for v1 and defer city sub-regions, or invest now.

D4 Backend `cost_percentile` KPI. v1 computes percentile client-side. Decide whether a real backend KPI is wanted for portfolio dashboards now or later.

D5 Sample sizes and KG splits are documented as typical planning values, not a live survey feed. Confirm this honesty framing is acceptable for the public default-enabled module.

D6 Portfolio currency policy. The endpoint never blends currencies. Confirm that projects in a currency other than the selected one are simply excluded from the portfolio distribution rather than converted.
