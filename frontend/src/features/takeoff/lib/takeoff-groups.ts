/**
 * Group aggregation helpers for the color-coded legend overlay.
 *
 * Given a list of measurements on the current page, compute per-group
 * summary rows (count + total value) so the legend renders in one pass.
 */

import type { Measurement } from './takeoff-types';

/** Tool types that shouldn't be counted in legend totals. */
export const ANNOTATION_TYPES = new Set([
  'cloud',
  'arrow',
  'text',
  'rectangle',
  'highlight',
]);

export interface GroupSummary {
  /** Group name (e.g. "Structural"). */
  name: string;
  /** Hex color to render the chip / row. */
  color: string;
  /** Number of measurements in this group on the current page. */
  count: number;
  /** Sum of `value` across measurements (annotations excluded). */
  total: number;
  /** Most common unit string — used for the summary row label. */
  unit: string;
}

/**
 * Summarize measurements for the legend.  Produces one row per group
 * present on the supplied measurement list, with the group color looked
 * up from `groupColorMap`.  Unknown groups fall back to `fallbackColor`.
 */
export function computeGroupSummaries(
  measurements: Measurement[],
  groupColorMap: Readonly<Record<string, string>>,
  fallbackColor: string = '#3B82F6',
): GroupSummary[] {
  const byGroup = new Map<
    string,
    { count: number; total: number; unitCounts: Record<string, number> }
  >();

  for (const m of measurements) {
    const name = m.group || 'General';
    const existing = byGroup.get(name) ?? {
      count: 0,
      total: 0,
      unitCounts: {} as Record<string, number>,
    };
    existing.count += 1;
    // Annotation tools don't contribute a numeric quantity.
    if (!ANNOTATION_TYPES.has(m.type)) {
      existing.total += m.value;
      if (m.unit) {
        existing.unitCounts[m.unit] = (existing.unitCounts[m.unit] ?? 0) + 1;
      }
    }
    byGroup.set(name, existing);
  }

  const summaries: GroupSummary[] = [];
  for (const [name, { count, total, unitCounts }] of byGroup.entries()) {
    // Pick the most-used unit for this group (stable tiebreak: lexicographic).
    const unitEntries = Object.entries(unitCounts);
    unitEntries.sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));
    const unit = unitEntries[0]?.[0] ?? '';
    summaries.push({
      name,
      color: groupColorMap[name] ?? fallbackColor,
      count,
      total,
      unit,
    });
  }

  // Stable, predictable ordering for the legend: by name.
  summaries.sort((a, b) => a.name.localeCompare(b.name));
  return summaries;
}

/** Format a group total for the legend row. */
export function formatGroupTotal(total: number, unit: string): string {
  const precision = total >= 100 ? 1 : total >= 1 ? 2 : 3;
  const rounded = Number(total.toFixed(precision));
  return unit ? `${rounded} ${unit}` : `${rounded}`;
}
