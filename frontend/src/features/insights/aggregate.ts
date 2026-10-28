// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure aggregation for Module Insights. Turns a dataset + a chart definition
 * into chart-ready points (or a single KPI value). Deliberately defensive: the
 * builder can point a chart at a non-numeric measure, an empty dataset or a
 * single category, so every path returns quietly instead of throwing while the
 * user is mid-edit.
 */
import type { Aggregation, ChartKind, InsightDataset, InsightDef } from './types';

export interface SeriesPoint {
  name: string;
  value: number;
}

/** Coerce a cell to a finite number, tolerating '1,234.5' and ' 12 '. */
export function toNumber(v: unknown): number | null {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const n = Number(String(v).replace(/[\s,]+/g, ''));
  return Number.isFinite(n) ? n : null;
}

function dimLabel(v: unknown): string {
  if (v == null || v === '') return '—'; // em-dash placeholder for a blank group
  return String(v);
}

interface Bucket {
  nums: number[];
  n: number;
}

function bucketize(dataset: InsightDataset, def: InsightDef): Map<string, Bucket> {
  const groups = new Map<string, Bucket>();
  const rows = dataset?.rows ?? [];
  for (const row of rows) {
    const name = def.dimension ? dimLabel(row[def.dimension]) : 'All';
    let b = groups.get(name);
    if (!b) {
      b = { nums: [], n: 0 };
      groups.set(name, b);
    }
    b.n += 1;
    if (def.measure) {
      const num = toNumber(row[def.measure]);
      if (num != null) b.nums.push(num);
    }
  }
  return groups;
}

function reduceBucket(b: Bucket, agg: Aggregation): number {
  if (agg === 'count') return b.n;
  if (b.nums.length === 0) return 0;
  const sum = b.nums.reduce((s, x) => s + x, 0);
  switch (agg) {
    case 'sum':
      return sum;
    case 'avg':
      return sum / b.nums.length;
    case 'min':
      return Math.min(...b.nums);
    case 'max':
      return Math.max(...b.nums);
    default:
      return sum;
  }
}

const SORTED_KINDS: ChartKind[] = ['bar', 'donut'];
const MAX_POINTS = 12;

/**
 * Group rows by the definition's dimension and reduce each group by its
 * aggregation. Bar and donut charts sort by value (biggest first) and fold a
 * long tail into a single "Other" point; line and area keep dataset order so a
 * time series stays chronological.
 */
export function computeSeries(
  dataset: InsightDataset,
  def: InsightDef,
  otherLabel = 'Other',
): SeriesPoint[] {
  if (!dataset) return [];
  const groups = bucketize(dataset, def);
  let points: SeriesPoint[] = [];
  for (const [name, b] of groups) points.push({ name, value: reduceBucket(b, def.agg) });
  if (SORTED_KINDS.includes(def.chart)) points.sort((a, b) => b.value - a.value);
  if (points.length > MAX_POINTS) {
    const head = points.slice(0, MAX_POINTS - 1);
    const tail = points.slice(MAX_POINTS - 1);
    head.push({ name: otherLabel, value: tail.reduce((s, p) => s + p.value, 0) });
    points = head;
  }
  return points;
}

/** Aggregate every row as one group - the dimension is ignored for a KPI. */
export function computeKpi(dataset: InsightDataset, def: InsightDef): number {
  if (!dataset) return 0;
  const all: Bucket = { nums: [], n: 0 };
  for (const row of dataset.rows ?? []) {
    all.n += 1;
    if (def.measure) {
      const num = toNumber(row[def.measure]);
      if (num != null) all.nums.push(num);
    }
  }
  return reduceBucket(all, def.agg);
}

/** Look up a field's declared format, defaulting to plain number. */
export function measureFormat(dataset: InsightDataset, def: InsightDef) {
  const f = dataset?.fields.find((x) => x.key === def.measure);
  return f?.format ?? 'number';
}
