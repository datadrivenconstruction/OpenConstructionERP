/**
 * Aggregation helpers shared by the Charts tab, Pivot tab and the
 * analysis-state tests. Pure functions — no React / store imports so
 * they can be unit-tested cheaply.
 */
import type { AggregateGroup } from './api';
import type { SlicerFilter } from '@/stores/useAnalysisStateStore';

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
