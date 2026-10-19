# Historical benchmarks: cost index and location normalisation (issue #492, spec v1, 2026-10-19)

Part of the historical benchmark work in the Analytics Performance tab and the estimate check
(`backend/app/modules/bi_dashboards/performance.py`, `router.py`, frontend
`features/analytics/PerformanceTab.tsx`). This section covers the P1 item "price index and location
normalisation of historical cost". The predictive part (P2) is a separate proposal in
`historical_benchmarks_predictive.md`.

## 1. Problem

A rate per m2 from a project priced in 2020 and one priced in 2024 are not the same money. Comparing them
as they are makes the old project look cheap and pulls the benchmark down, and the same happens across
regions with different cost levels. The platform already keeps the data to correct this in the Price
Index module: cost index series (`oe_price_index_series` and `oe_price_index_point`, one value per
`YYYY-MM`) and regional factors (`oe_price_index_location_factor`, keyed by a free-form region code). The
math is `price_index/index_math.py`: `resolve_factor` gives `index(target) / index(base)` and refuses a
period the series does not carry, and the location factor is `region(target) / region(base)`.

## 2. What the user asks for

Opt-in, request time, three fields on the benchmark, compare, drilldown and both estimate check
requests (`CostIndexOptions` in `schemas.py`):

- `index_series_id`: the cost index series to use. Absent means no temporal adjustment.
- `index_target_period`: the month money is brought to, `YYYY-MM`. Absent means the series' latest
  month. Only valid together with a series.
- `location_target_region`: the region money is brought to. Absent means no regional adjustment.

Either part or both. A series that does not exist, a target month the series lacks, or a target region
without a factor is refused with 422, because every reading would be wrong in the same way and a whole
screen of exclusions explains less than one error.

In the Performance tab the three controls sit under "More filters" beside the reporting currency. The
estimate check under each group sends the same request, so an estimate is compared with the history as
it is shown. Saved benchmark sets do not store these fields yet (it needs a migration); see section 7.

## 3. Which month the money is in

Each KPI entity already has a `period_column`, the date the existing period filter reads:
`Position.created_at` for bill positions, `FieldTimesheet.date` for hours, `CostItemUsage.used_at` for
cost database use, `Project.created_at` for project level figures. That column dates the money. When a
cost index is asked for, the per-project query is grouped once more by the year and month of that
column (`kpi_spec.evaluate_spec_by_project(by_period=True)`), so one project yields one partial reading
per month.

This is the decision that makes the result correct for a project that spans years. Each month moves by
its own factor and only then are the months merged back into one reading per project. One factor per
project (first month, last month or an average) gives a different and wrong answer; the test
`test_one_project_across_two_years_moves_each_month_by_its_own_factor` pins all three wrong answers.

Known limitation: for the `project` entity the period column is the creation date of the project,
which is a fair date for a budget and a poor one for the actual cost of a project that finished years
later. The adjustment is then overstated for those KPIs. A per-field price date (for example the
actual end date for `actual_cost`) is the fix; it needs a typed date column, which the project table
does not have (its end dates are strings).

## 4. How a reading moves

Money moves the way an exchange rate moves it (`currency_exponents`): a money field is multiplied by
the factor, a rate per money is divided, and money over money is unchanged. A KPI without money (hours
per m2) is not touched, and the response says so with `cost_index.applicable = false`. For a ratio the
two sums are moved and re-divided, so the benchmark stays a ratio of sums.

The location factor is `factor(target region) / factor(project region)`, with the project's `region`
matched to the register's `region_code`, trimmed and case-insensitive.

Order of operations: the cost index runs first, month by month and in the reading's own currency, then
the FX restatement into a reporting currency, then unit conversion. Currencies are never combined by
the index: it changes no dimension, so a EUR and a USD reading stay in their own groups.

## 5. Nothing is guessed

A reading is excluded, with a reason counted in the group's `excluded` and shown beside the project,
when:

- `index_period_missing`: one of its months has no point in the series. The months are listed in
  `index_missing_periods`. Counting the other months alone, or the uncovered month unadjusted beside
  adjusted ones, would both print a figure that is neither the old nor the restated value.
- `no_record_date`: its rows carry no date.
- `no_project_region`: a region adjustment was asked for and the project has no region.
- `no_location_factor`: the project's region has no factor in the register.

Note the deliberate difference to `index_math.location_multiplier`, which reads a region without a
factor as the national baseline 1. That is a reasonable default for a single typed adjustment, where
the user sees the result line by line. Inside a benchmark of many projects it would silently leave
some projects unadjusted, so the benchmark excludes them instead.

## 6. Provenance

Every row carries what was done to it: `index_series`, `index_base_periods` (the months its money was
in), `index_target_period`, `index_factor` (the one factor that takes the value before to the value
after; the exact factor when there is one month), `location_region`, `location_factor` and
`unadjusted_value`. The tab prints it under the value ("was 200, x1.3125 Building cost index,
2020-06 - 2022-06 to 2024-06"), and a notice above the groups names the series and the target month.

The drilldown restates each record by the factor of its own month and the project's region and shows
that factor per record, so its totals still equal the reading's numerator and denominator.

## 7. Open points

- Benchmark sets do not persist the three fields. It needs a column on `oe_bi_benchmark_set` and a
  revision; until then the set check uses the fields of the request.
- The bill editor's historical panel, post-calculation and the conceptual estimate and copilot cards
  (`HistoricalRange.tsx`, `position-context`) do not offer the adjustment yet. The backend parameter is
  in place for the routes they call except `position-context`.
- Which series a tenant should use by default (national building cost index, a trade-specific one) is
  a data question for the country packs, not for this module.
