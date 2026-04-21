/**
 * URL state serialisation for the CAD-BIM Data Explorer (Q1 UX).
 *
 * All four tabs share a single URL contract so that reloading, sharing a
 * link, or navigating back/forward restores the previous view verbatim.
 *
 * Format
 * ──────
 *   ?tab=pivot                     — one of table | pivot | charts | describe
 *   ?slicers=col:v1|v2,col2:v      — column/value pairs, URL-encoded values
 *   ?piv_group=cat,lvl             — pivot group-by columns (comma list)
 *   ?piv_sum=volume,area           — pivot aggregate columns (comma list)
 *   ?piv_agg=sum                   — pivot aggregation function
 *   ?piv_top=10                    — optional top-N (prefix with `-` for bottom)
 *   ?chart_kind=bar                — one of bar | line | pie | scatter
 *   ?chart_cat=category            — chart category column
 *   ?chart_val=volume              — chart value column
 *   ?chart_top=20                  — optional top-N (prefix with `-` for bottom)
 *
 * The helpers below are intentionally pure — no React, no router, no
 * store imports — so they can be round-tripped in unit tests.
 */

import type {
  ChartConfig,
  ChartKind,
  PivotConfigSnapshot,
  SlicerFilter,
} from '@/stores/useAnalysisStateStore';

export type TabId = 'table' | 'pivot' | 'charts' | 'describe';

const VALID_TABS: readonly TabId[] = ['table', 'pivot', 'charts', 'describe'];
const VALID_CHART_KINDS: readonly ChartKind[] = ['bar', 'line', 'pie', 'scatter'];

/* ── Slicers ──────────────────────────────────────────────────────────── */

/** Encode a single slicer value so `|`, `,`, `:` and `%` survive a round
 *  trip through a URL query string without colliding with our separators. */
function encodeSlicerValue(v: string): string {
  // encodeURIComponent already covers `%`, `:` and most symbols. `|` and
  // `,` are technically safe in query strings but we use them as
  // separators, so encode them explicitly.
  return encodeURIComponent(v).replace(/\|/g, '%7C').replace(/,/g, '%2C');
}

function decodeSlicerValue(v: string): string {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

/** `[{column:'category', values:['Wall','Floor']}, ...] → "category:Wall|Floor,..."` */
export function serialiseSlicers(slicers: SlicerFilter[]): string {
  if (!slicers.length) return '';
  return slicers
    .filter((s) => s.column && s.values.length > 0)
    .map(
      (s) =>
        `${encodeSlicerValue(s.column)}:${s.values.map(encodeSlicerValue).join('|')}`,
    )
    .join(',');
}

/** Inverse of serialiseSlicers. Tolerant of malformed input — returns
 *  `[]` on any parse error so the UI degrades gracefully. */
export function parseSlicers(raw: string | null | undefined): SlicerFilter[] {
  if (!raw) return [];
  const out: SlicerFilter[] = [];
  for (const chunk of raw.split(',')) {
    if (!chunk) continue;
    const idx = chunk.indexOf(':');
    if (idx <= 0) continue;
    const column = decodeSlicerValue(chunk.slice(0, idx));
    const valuesRaw = chunk.slice(idx + 1);
    const values = valuesRaw
      .split('|')
      .map(decodeSlicerValue)
      .filter((v) => v.length > 0);
    if (column && values.length > 0) {
      out.push({ column, values });
    }
  }
  return out;
}

/* ── Pivot config ─────────────────────────────────────────────────────── */

export interface PivotUrlSerialised {
  group: string | null;
  sum: string | null;
  agg: string | null;
  top: string | null;
}

/** Serialise topN + direction into a single signed-number string. */
function encodeTopN(topN: number | null, direction: 'top' | 'bottom'): string | null {
  if (topN == null || topN <= 0) return null;
  return direction === 'bottom' ? `-${topN}` : String(topN);
}

function decodeTopN(raw: string | null): { topN: number | null; direction: 'top' | 'bottom' } {
  if (!raw) return { topN: null, direction: 'top' };
  const n = parseInt(raw, 10);
  if (!Number.isFinite(n) || n === 0) return { topN: null, direction: 'top' };
  if (n < 0) return { topN: Math.abs(n), direction: 'bottom' };
  return { topN: n, direction: 'top' };
}

export function serialisePivot(snapshot: PivotConfigSnapshot | null): PivotUrlSerialised {
  if (!snapshot) return { group: null, sum: null, agg: null, top: null };
  return {
    group: snapshot.groupBy.length > 0 ? snapshot.groupBy.join(',') : null,
    sum: snapshot.aggCols.length > 0 ? snapshot.aggCols.join(',') : null,
    agg: snapshot.aggFn || null,
    top: encodeTopN(snapshot.topN, snapshot.topNDirection),
  };
}

export function parsePivot(src: {
  group?: string | null;
  sum?: string | null;
  agg?: string | null;
  top?: string | null;
}): PivotConfigSnapshot | null {
  const groupBy = (src.group || '').split(',').map((s) => s.trim()).filter(Boolean);
  const aggCols = (src.sum || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (groupBy.length === 0 && aggCols.length === 0) return null;
  const { topN, direction } = decodeTopN(src.top ?? null);
  return {
    groupBy,
    aggCols,
    aggFn: src.agg || 'sum',
    topN,
    topNDirection: direction,
  };
}

/* ── Chart config ─────────────────────────────────────────────────────── */

export interface ChartUrlSerialised {
  kind: string | null;
  cat: string | null;
  val: string | null;
  top: string | null;
}

export function serialiseChart(chart: ChartConfig): ChartUrlSerialised {
  return {
    kind: chart.kind !== 'bar' ? chart.kind : null,
    cat: chart.category || null,
    val: chart.value || null,
    top: encodeTopN(chart.topN, chart.topNDirection),
  };
}

export function parseChart(src: {
  kind?: string | null;
  cat?: string | null;
  val?: string | null;
  top?: string | null;
}): Partial<ChartConfig> {
  const out: Partial<ChartConfig> = {};
  if (src.kind && (VALID_CHART_KINDS as readonly string[]).includes(src.kind)) {
    out.kind = src.kind as ChartKind;
  }
  if (src.cat) out.category = src.cat;
  if (src.val) out.value = src.val;
  const { topN, direction } = decodeTopN(src.top ?? null);
  out.topN = topN;
  out.topNDirection = direction;
  return out;
}

/* ── Tab ──────────────────────────────────────────────────────────────── */

export function parseTab(raw: string | null | undefined, fallback: TabId = 'table'): TabId {
  if (raw && (VALID_TABS as readonly string[]).includes(raw)) return raw as TabId;
  return fallback;
}

/* ── Data-bar width calculator ────────────────────────────────────────── */

export interface DataBarStyle {
  /** 0-100 — width of the bar as a percentage of the cell. */
  widthPct: number;
  /** true if the value is negative — caller renders right-aligned red bar. */
  negative: boolean;
}

/**
 * Compute Power-BI-style data-bar width for a pivot cell.
 *
 * - Returns widthPct 0 when `max` is non-finite, NaN, zero, or when the
 *   value is null/undefined (no bar to render).
 * - Uses absolute values so negative numbers still produce a visible bar.
 * - Clamps to [0, 100] so rounding overflow can't blow past the cell.
 */
export function computeDataBar(
  value: number | null | undefined,
  max: number,
): DataBarStyle {
  if (value == null || !Number.isFinite(value)) {
    return { widthPct: 0, negative: false };
  }
  if (!Number.isFinite(max) || max <= 0) {
    return { widthPct: 0, negative: value < 0 };
  }
  const pct = (Math.abs(value) / max) * 100;
  return {
    widthPct: Math.max(0, Math.min(100, pct)),
    negative: value < 0,
  };
}

/** Compute the max |value| across a set of rows for a given aggregation
 *  column. Returns 0 when there are no positive samples. */
export function maxAbsAcross<R>(
  rows: readonly R[],
  getValue: (row: R) => number | null | undefined,
): number {
  let max = 0;
  for (const row of rows) {
    const v = getValue(row);
    if (v == null || !Number.isFinite(v)) continue;
    const abs = Math.abs(v);
    if (abs > max) max = abs;
  }
  return max;
}
