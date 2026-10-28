// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko
/**
 * How many points a chart needs before drawing it says anything.
 *
 * The frontend chart primitives had an empty-state guard and nothing between
 * "no data" and "a real chart", so one row rendered as a donut with a single
 * segment and one month rendered as a line with one point. A chart of one is
 * not a small chart, it is a picture that asserts a shape the data does not
 * have.
 *
 * THE NUMBERS ARE NOT INVENTED HERE. They mirror
 * `backend/app/modules/dashboards/insights.py`, which already decides whether
 * a column is worth charting and has carried thought-through minimums since
 * it was written. Two analytics systems disagreeing about what counts as
 * enough data is the drift this table exists to end. Each entry cites the
 * backend constant it mirrors, so a change there has an obvious counterpart.
 *
 * WHAT THIS CANNOT DO, and it matters for reading the guard's limits. The
 * backend reasons over a dataframe: it knows the row count and each column's
 * cardinality. These renderers receive points that are already aggregated, so
 * they can count points and nothing else. Three categories holding one record
 * each and three categories whose totals happen to be 1 arrive here as the
 * same three points, and the second is legitimate - three costs of 1 EUR is
 * not thin data. A floor on the sum of the values would suppress it, so there
 * isn't one. The all-bars-equal-1 case therefore survives this guard, and the
 * place to reject it is where the points are built, with the record count
 * still in hand.
 */

/**
 * Chart shapes with a minimum. The union spans both renderers: `SeriesChart`
 * in features/insights draws bar/line/area/donut, `ChartBody` in
 * features/dashboards draws histogram/bar/line/scatter/donut.
 */
export type FlooredChartKind = 'bar' | 'donut' | 'line' | 'area' | 'histogram' | 'scatter';

/**
 * Minimum number of rendered points per chart shape.
 *
 * - `donut`, `bar` - 2, mirroring `_MIN_CATEGORICAL_FOR_DONUT` and
 *   `_MIN_CATEGORICAL_FOR_BAR` (insights.py:96-97). One slice is a full
 *   circle labelled with a number; one bar is a rectangle.
 * - `line`, `area` - 3, mirroring `sub[dt_col].nunique() < 3`
 *   (insights.py:319), the backend's own refusal to draw a trend. Two points
 *   are a straight segment that always trends, whichever way they fall.
 *   `area` has no backend analogue - it is a filled line and is treated as
 *   one.
 * - `scatter` - 5, mirroring `len(sub) < 5` (insights.py:361).
 * - `histogram` - 2, and this one is a deliberate deviation worth reading.
 *   The backend requires 10 distinct numeric values
 *   (`_MIN_NUMERIC_DISTINCT_FOR_HISTOGRAM`, insights.py:93) *before* it bins
 *   them. Bars are bins, so 10 distinct values may legitimately arrive here
 *   as far fewer bars, and copying 10 across would suppress histograms the
 *   backend deliberately allowed. The real rule stays upstream where the
 *   distinct count is still known; 2 is the backstop that only rejects a
 *   histogram which is a single rectangle.
 */
export const MIN_POINTS: Record<FlooredChartKind, number> = {
  donut: 2,
  bar: 2,
  histogram: 2,
  line: 3,
  area: 3,
  scatter: 5,
};

/**
 * Whether `pointCount` points are enough to draw `kind` honestly.
 *
 * An unknown kind returns `true`: this guard exists to stop a chart
 * overclaiming, not to become a new way for a panel to render nothing. A
 * shape nobody gave a floor to is not thereby suspect.
 */
export function hasEnoughPoints(kind: string, pointCount: number): boolean {
  const floor = MIN_POINTS[kind as FlooredChartKind];
  if (floor === undefined) return true;
  return pointCount >= floor;
}
