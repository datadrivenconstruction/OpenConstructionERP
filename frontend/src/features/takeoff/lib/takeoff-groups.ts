// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Group aggregation helpers for the color-coded legend overlay.
 *
 * Given a list of measurements on the current page, compute per-group
 * summary rows (count + total value) so the legend renders in one pass.
 */

import type { Measurement } from './takeoff-types';
import { effectiveQuantity } from './takeoff-quantity';
import { formatCountQuantity, formatQuantity } from './measurement-format';
import { compareNames } from '@/shared/lib/collator';

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
  /** True when every quantity contribution came from count-type
   *  measurements — the total is whole pieces, not a measured figure. */
  isCount: boolean;
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
    {
      count: number;
      total: number;
      unitCounts: Record<string, number>;
      quantified: number;
      countTyped: number;
    }
  >();

  for (const m of measurements) {
    const name = m.group || 'General';
    const existing = byGroup.get(name) ?? {
      count: 0,
      total: 0,
      unitCounts: {} as Record<string, number>,
      quantified: 0,
      countTyped: 0,
    };
    existing.count += 1;
    // Annotation tools don't contribute a numeric quantity.
    if (!ANNOTATION_TYPES.has(m.type)) {
      // Effective quantity folds slope / wastage / typical-multiplier and the
      // opening-deduction sign (net area = gross - openings), so the legend
      // rolls up the same reported figure the ledger and exports do.
      existing.total += effectiveQuantity(m);
      existing.quantified += 1;
      if (m.type === 'count') existing.countTyped += 1;
      if (m.unit) {
        existing.unitCounts[m.unit] = (existing.unitCounts[m.unit] ?? 0) + 1;
      }
    }
    byGroup.set(name, existing);
  }

  const summaries: GroupSummary[] = [];
  for (const [name, { count, total, unitCounts, quantified, countTyped }] of byGroup.entries()) {
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
      isCount: quantified > 0 && countTyped === quantified,
    });
  }

  // Stable, predictable ordering for the legend: by name.
  summaries.sort((a, b) => compareNames(a.name, b.name));
  return summaries;
}

/** Format a group total for the legend row. Renders through the shared
 *  quantity formatter so the total and the measurement rows it sums use
 *  one decimal separator (K-12: the legend read "485.3" directly above
 *  the "248,5" rows it summed). Count-only groups are whole pieces and
 *  must not inherit the decimal ladder (K-14: "17,00 pcs" for windows);
 *  pass `isCount` from the group summary. */
export function formatGroupTotal(
  total: number,
  unit: string,
  locale?: string,
  isCount = false,
): string {
  const rendered = isCount ? formatCountQuantity(total, locale) : formatQuantity(total, locale);
  return unit ? `${rendered} ${unit}` : rendered;
}
