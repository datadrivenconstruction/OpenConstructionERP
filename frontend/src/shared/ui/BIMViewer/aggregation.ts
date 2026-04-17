/**
 * Quantity aggregation rules for groups of BIM elements.
 *
 * When a user selects N elements in the 3D viewer (or links N elements
 * to a BOQ position), each numeric property needs an aggregation rule
 * that actually means something:
 *
 *   SUM (Σ)       — additive totals: volume, area, length, perimeter,
 *                   weight, count, qty.  Σ across the group is a real
 *                   rollup that the BOQ position quantity should be.
 *
 *   AVG (⌀)       — per-element dimensions: thickness, width, height,
 *                   depth, diameter, radius, span, slope, angle,
 *                   elevation, offset.  Summing is meaningless (five
 *                   240 mm walls aren't "1200 mm thick"), but the mean
 *                   is a useful descriptor for the group.  We also
 *                   surface min/max and the unique-value count so the
 *                   user can spot bimodal distributions.
 *
 *   DISTINCT      — categorical / per-element constants whose numeric
 *                   value isn't a magnitude (mark numbers, material
 *                   ids, fire ratings, type codes).  Listing the
 *                   unique values is the only honest aggregation.
 *
 * The classifier uses a keyword heuristic.  Unknown keys default to
 * DISTINCT — the safest fallback because "N unique values" is always
 * truthful, while a wrongful sum can silently overstate a quantity.
 *
 * The output is rendered in:
 *   • Selection summary panel (BIMViewer)
 *   • Linked Geometry popover "Apply to BOQ" column (BOQ grid)
 *
 * Keeping the classifier in one place means the Apply panel and the
 * Selection summary always agree on what's a sum vs an average vs a
 * distinct list — no surprises when the user moves between the two.
 */

import type { BIMElementData } from './ElementManager';

export type AggMode = 'sum' | 'avg' | 'distinct';

export interface AggResult {
  /** Original parquet/db key — used for stable React keys. */
  key: string;
  /** Human-friendly label (CamelCased, "_" → space, unit suffix stripped). */
  label: string;
  mode: AggMode;
  /** Number of elements that contributed a non-zero numeric value. */
  count: number;
  /** Sum across all contributors — always computed; only meaningful for `mode === 'sum'`. */
  sum: number;
  /** Arithmetic mean — only meaningful for `mode === 'avg'`. */
  avg: number;
  /** Smallest contributing value. */
  min: number;
  /** Largest contributing value. */
  max: number;
  /** Sorted ascending list of unique numeric values seen. */
  uniqueValues: number[];
  /** Inferred unit ("m", "m²", "m³", "mm", "kg", "pcs", "") — best-effort from the key suffix. */
  unit: string;
}

const SUM_KEYWORDS = [
  'area',
  'volume',
  'perimeter',
  'weight',
  'count',
];
const SUM_EXACT = new Set(['length', 'qty', 'quantity']);
const SUM_SUFFIXES = ['_m2', '_m3', '_kg', '_length', '_m'];

const AVG_KEYWORDS = [
  'thickness',
  'width',
  'height',
  'depth',
  'diameter',
  'radius',
  'span',
  'slope',
  'angle',
  'elevation',
  'offset',
];

/** Classify a quantity key into an aggregation mode using its name. */
export function classifyAggKey(key: string): AggMode {
  const k = key.toLowerCase();
  if (SUM_EXACT.has(k)) return 'sum';
  if (SUM_SUFFIXES.some((s) => k.endsWith(s))) return 'sum';
  if (SUM_KEYWORDS.some((s) => k.includes(s))) return 'sum';
  if (AVG_KEYWORDS.some((s) => k.includes(s))) return 'avg';
  return 'distinct';
}

/** Best-effort unit inference from the key suffix / keyword. */
export function inferAggUnit(key: string): string {
  const k = key.toLowerCase();
  if (k.includes('area') || k.endsWith('_m2')) return 'm\u00B2';
  if (k.includes('volume') || k.endsWith('_m3')) return 'm\u00B3';
  if (k.includes('thickness')) return 'mm';
  if (k.includes('weight') || k.endsWith('_kg')) return 'kg';
  if (k.includes('count') || k === 'qty' || k === 'quantity') return 'pcs';
  if (k.includes('angle') || k.includes('slope')) return '\u00B0';
  if (
    k.includes('length') ||
    k.endsWith('_m') ||
    k.includes('height') ||
    k.includes('width') ||
    k.includes('depth') ||
    k.includes('diameter') ||
    k.includes('radius') ||
    k.includes('perimeter') ||
    k.includes('span') ||
    k.includes('elevation') ||
    k.includes('offset')
  ) {
    return 'm';
  }
  return '';
}

function makeLabel(key: string): string {
  return key
    .replace(/_m2$|_m3$|_m$|_kg$/i, '')
    .replace(/_/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Aggregate every numeric value across a group of BIM elements.
 *
 * @param elements Elements to roll up.  Empty input returns `[]`.
 * @param parquetByElementId Optional Parquet rows keyed by element id —
 *   when provided, every numeric column from Parquet is also folded in.
 *   This is how the Apply panel and Selection summary both pick up
 *   "thickness", "rafter cut" etc. that DDC's standard quantities
 *   extract leaves out.
 *
 * @returns sorted aggregations: SUM first (largest first), AVG next,
 *   DISTINCT last (most-varied first).
 */
export function aggregateBIMQuantities(
  elements: readonly BIMElementData[],
  parquetByElementId?: Record<string, Record<string, unknown> | undefined>,
): AggResult[] {
  if (elements.length === 0) return [];

  type Acc = {
    key: string;
    values: number[];
  };
  const accs = new Map<string, Acc>();
  const push = (k: string, num: number) => {
    if (!Number.isFinite(num) || num === 0) return;
    let a = accs.get(k);
    if (!a) {
      a = { key: k, values: [] };
      accs.set(k, a);
    }
    a.values.push(num);
  };

  for (const el of elements) {
    const seen = new Set<string>();
    if (el.quantities) {
      for (const [k, v] of Object.entries(el.quantities)) {
        const num = typeof v === 'number' ? v : parseFloat(String(v));
        push(k, num);
        seen.add(k);
      }
    }
    const parquet = parquetByElementId?.[el.id];
    if (parquet) {
      for (const [k, v] of Object.entries(parquet)) {
        if (k === 'id') continue;
        if (seen.has(k)) continue;
        const num = typeof v === 'number' ? v : parseFloat(String(v));
        push(k, num);
      }
    }
  }

  const out: AggResult[] = [];
  for (const a of accs.values()) {
    if (a.values.length === 0) continue;
    let sum = 0;
    let min = a.values[0]!;
    let max = a.values[0]!;
    const uniq = new Set<number>();
    for (const v of a.values) {
      sum += v;
      if (v < min) min = v;
      if (v > max) max = v;
      uniq.add(v);
    }
    const count = a.values.length;
    out.push({
      key: a.key,
      label: makeLabel(a.key),
      mode: classifyAggKey(a.key),
      count,
      sum,
      avg: sum / count,
      min,
      max,
      uniqueValues: [...uniq].sort((x, y) => x - y),
      unit: inferAggUnit(a.key),
    });
  }

  return out.sort((a, b) => {
    const order = { sum: 0, avg: 1, distinct: 2 } as const;
    if (a.mode !== b.mode) return order[a.mode] - order[b.mode];
    if (a.mode === 'sum') return b.sum - a.sum;
    if (a.mode === 'avg') return b.count - a.count;
    return b.uniqueValues.length - a.uniqueValues.length;
  });
}
