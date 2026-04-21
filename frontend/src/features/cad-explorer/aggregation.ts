/**
 * Aggregation helpers shared by the Charts tab, Pivot tab and the
 * analysis-state tests. Pure functions — no React / store imports so
 * they can be unit-tested cheaply.
 */
import type { AggregateGroup } from './api';
import type { SlicerFilter } from '@/stores/useAnalysisStateStore';

/* ── Aggregation function vocabulary ──────────────────────────────────── */

/** The canonical list of aggregation functions supported by the Pivot UI.
 *  `count` / `count_unique` operate on ANY column dtype (they just count
 *  rows or distinct values). The rest require numeric data.
 *
 *  Keep in sync with the `<select>` options in the Pivot tab and with the
 *  `_SUPPORTED_AGG_FUNCS` set on the backend (sum/avg/min/max/count are
 *  computed server-side; count_unique is computed client-side because the
 *  current backend endpoint rejects unknown aggregation names). */
export const AGG_FUNCTIONS = [
  'sum',
  'avg',
  'min',
  'max',
  'count',
  'count_unique',
] as const;

export type AggFunction = (typeof AGG_FUNCTIONS)[number];

const NUMERIC_AGG_FUNCTIONS = new Set<AggFunction>(['sum', 'avg', 'min', 'max']);
const CATEGORICAL_AGG_FUNCTIONS = new Set<AggFunction>(['count', 'count_unique']);

/** `true` when the agg function requires the target column to be numeric
 *  (sum/avg/min/max). `false` when it accepts any column dtype. */
export function isNumericAggFn(fn: string): boolean {
  return NUMERIC_AGG_FUNCTIONS.has(fn as AggFunction);
}

/** `true` when the agg function accepts any column dtype — count and
 *  count_unique both work on text, number, boolean, whatever. */
export function isCategoricalAggFn(fn: string): boolean {
  return CATEGORICAL_AGG_FUNCTIONS.has(fn as AggFunction);
}

/** Validator used by the aggCol picker: given an agg fn and whether the
 *  candidate column is numeric, return whether the combination is valid.
 *  The UI greys out / tooltips invalid choices. */
export function canAggregateColumn(fn: string, isNumeric: boolean): boolean {
  if (isCategoricalAggFn(fn)) return true; // any dtype ok
  if (isNumericAggFn(fn)) return isNumeric;
  // Unknown fn — be permissive; server-side validation will catch it.
  return true;
}

/* ── Client-side pivot computation ────────────────────────────────────── */

/** Stringify a group key tuple so we can use it as a Map key. Uses an
 *  ASCII unit separator (U+001F) because group-by columns may contain any
 *  printable character including `|` and `,`. */
function keyTupleString(tuple: readonly string[]): string {
  return tuple.join('\u001F');
}

/** Extract the group-by key for a row. Missing / nullish values become
 *  the empty string — matching backend behaviour in the `/aggregate/`
 *  endpoint (`str(el.get(c, ""))`). */
function rowGroupKey(
  row: Record<string, unknown>,
  groupBy: readonly string[],
): { tuple: string[]; keyStr: string } {
  const tuple = groupBy.map((c) => {
    const v = row[c];
    return v == null ? '' : String(v);
  });
  return { tuple, keyStr: keyTupleString(tuple) };
}

/**
 * Compute a pivot aggregation client-side. Used for the `count` and
 * `count_unique` agg functions — they either are not supported by the
 * backend (`count_unique`) or would return the same value for every
 * column (`count`), so doing them here lets us keep the per-column
 * semantics consistent with the other aggregations.
 *
 * @param rows    Raw element rows (as returned by `/cad-data/elements/`).
 * @param groupBy Ordered list of group-by columns.
 * @param aggCols Columns the user picked for aggregation.
 * @param aggFn   Aggregation function — must be `count` or `count_unique`.
 * @returns       `AggregateResponse`-shaped result so the existing render
 *                code can consume it without branching.
 */
export function computeClientPivot(
  rows: readonly Record<string, unknown>[],
  groupBy: readonly string[],
  aggCols: readonly string[],
  aggFn: 'count' | 'count_unique',
): {
  groups: AggregateGroup[];
  totals: Record<string, number>;
  total_count: number;
} {
  const groupsMap = new Map<
    string,
    { tuple: string[]; rows: Record<string, unknown>[] }
  >();
  for (const row of rows) {
    const { tuple, keyStr } = rowGroupKey(row, groupBy);
    let bucket = groupsMap.get(keyStr);
    if (!bucket) {
      bucket = { tuple, rows: [] };
      groupsMap.set(keyStr, bucket);
    }
    bucket.rows.push(row);
  }

  const groups: AggregateGroup[] = [];
  for (const { tuple, rows: groupRows } of groupsMap.values()) {
    const key: Record<string, string> = {};
    groupBy.forEach((c, i) => {
      key[c] = tuple[i] ?? '';
    });
    const results: Record<string, number> = {};
    for (const col of aggCols) {
      if (aggFn === 'count') {
        // count = rows with a non-null / non-empty value in the column.
        // Matches what users intuitively expect when they pick a column
        // and ask for "count" — e.g. "how many rows have a client_name".
        let n = 0;
        for (const r of groupRows) {
          const v = r[col];
          if (v != null && v !== '') n += 1;
        }
        results[col] = n;
      } else {
        // count_unique = distinct non-null values in the column.
        const seen = new Set<string>();
        for (const r of groupRows) {
          const v = r[col];
          if (v == null || v === '') continue;
          seen.add(String(v));
        }
        results[col] = seen.size;
      }
    }
    groups.push({ key, results, count: groupRows.length });
  }

  // Totals across all rows (not all groups) — matches server-side semantics.
  const totals: Record<string, number> = {};
  for (const col of aggCols) {
    if (aggFn === 'count') {
      let n = 0;
      for (const r of rows) {
        const v = r[col];
        if (v != null && v !== '') n += 1;
      }
      totals[col] = n;
    } else {
      const seen = new Set<string>();
      for (const r of rows) {
        const v = r[col];
        if (v == null || v === '') continue;
        seen.add(String(v));
      }
      totals[col] = seen.size;
    }
  }

  // Stable sort by first group-by column — mirrors the backend's
  // `result_groups.sort(...)` so screenshots and CSV exports are
  // deterministic across runs.
  groups.sort((a, b) => {
    for (const c of groupBy) {
      const va = a.key[c] ?? '';
      const vb = b.key[c] ?? '';
      if (va !== vb) return va.localeCompare(vb);
    }
    return 0;
  });

  return { groups, totals, total_count: rows.length };
}

/** Format an integer count for display in a pivot cell. No decimals,
 *  always locale-aware thousand separators — e.g. `1,234` or `1 234`. */
export function formatCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '-';
  return Math.round(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/** Sort groups by a numeric `column` and optionally keep the top-N or
 *  bottom-N entries. Uses the first group-by column as a secondary key
 *  for stable ordering when the numeric values tie — deterministic
 *  ordering matters for screenshot-style UI tests.
 */
export function applyTopN(
  groups: AggregateGroup[],
  valueKey: string,
  topN: number | null,
  direction: 'top' | 'bottom' = 'top',
  categoryKey?: string,
): AggregateGroup[] {
  const sorted = [...groups].sort((a, b) => {
    const va = a.results[valueKey] ?? 0;
    const vb = b.results[valueKey] ?? 0;
    if (vb !== va) return direction === 'top' ? vb - va : va - vb;
    // Tie-breaker: sort by category label alphabetically so ordering is
    // stable across re-renders and different JS engines.
    if (categoryKey) {
      const la = String(a.key[categoryKey] ?? '');
      const lb = String(b.key[categoryKey] ?? '');
      return la.localeCompare(lb);
    }
    // Fallback: concatenate all key values.
    return Object.values(a.key).join('|').localeCompare(Object.values(b.key).join('|'));
  });
  if (topN == null || topN <= 0) return sorted;
  return sorted.slice(0, topN);
}

/** Filter a raw row array by the active slicer chips. Each chip is a
 *  logical AND across columns, logical OR within values of the same
 *  column. Case-sensitive match on the column's string representation
 *  because the backend stores values exactly as exported by DDC. */
export function applySlicers(
  rows: Record<string, unknown>[],
  slicers: SlicerFilter[],
): Record<string, unknown>[] {
  if (slicers.length === 0) return rows;
  return rows.filter((row) =>
    slicers.every((s) => {
      if (s.values.length === 0) return true;
      const cell = row[s.column];
      const cellStr = cell == null ? '' : String(cell);
      return s.values.includes(cellStr);
    }),
  );
}

/** Predicate for a single aggregated group — used by the Pivot tab to
 *  keep rows matching the slicer chips without refetching from the
 *  backend. */
export function groupMatchesSlicers(
  group: AggregateGroup,
  slicers: SlicerFilter[],
): boolean {
  return slicers.every((s) => {
    if (s.values.length === 0) return true;
    const cell = group.key[s.column];
    if (cell == null) return false;
    return s.values.includes(String(cell));
  });
}
