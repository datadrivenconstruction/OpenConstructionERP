import { describe, it, expect } from 'vitest';
import {
  parseTab,
  parseSlicers,
  serialiseSlicers,
  parsePivot,
  serialisePivot,
  parseChart,
  serialiseChart,
  computeDataBar,
  maxAbsAcross,
} from '@/features/cad-explorer/urlState';
import type {
  ChartConfig,
  PivotConfigSnapshot,
  SlicerFilter,
} from '@/stores/useAnalysisStateStore';

describe('urlState — tab', () => {
  it('returns the default when the raw value is null / empty / unknown', () => {
    expect(parseTab(null)).toBe('table');
    expect(parseTab('')).toBe('table');
    expect(parseTab('bogus')).toBe('table');
  });

  it('accepts each of the four valid tab ids', () => {
    expect(parseTab('table')).toBe('table');
    expect(parseTab('pivot')).toBe('pivot');
    expect(parseTab('charts')).toBe('charts');
    expect(parseTab('describe')).toBe('describe');
  });

  it('respects a custom fallback', () => {
    expect(parseTab(null, 'pivot')).toBe('pivot');
    expect(parseTab('garbage', 'charts')).toBe('charts');
  });
});

describe('urlState — slicer round-trip', () => {
  it('empty list ↔ empty string', () => {
    expect(serialiseSlicers([])).toBe('');
    expect(parseSlicers('')).toEqual([]);
    expect(parseSlicers(null)).toEqual([]);
    expect(parseSlicers(undefined)).toEqual([]);
  });

  it('single slicer with one value', () => {
    const slicers: SlicerFilter[] = [{ column: 'category', values: ['Wall'] }];
    const s = serialiseSlicers(slicers);
    expect(s).toBe('category:Wall');
    expect(parseSlicers(s)).toEqual(slicers);
  });

  it('single slicer with multiple values', () => {
    const slicers: SlicerFilter[] = [{ column: 'category', values: ['Wall', 'Floor'] }];
    const s = serialiseSlicers(slicers);
    expect(s).toBe('category:Wall|Floor');
    expect(parseSlicers(s)).toEqual(slicers);
  });

  it('multiple slicers across columns', () => {
    const slicers: SlicerFilter[] = [
      { column: 'category', values: ['Wall', 'Floor'] },
      { column: 'level', values: ['L01'] },
    ];
    const s = serialiseSlicers(slicers);
    expect(s).toBe('category:Wall|Floor,level:L01');
    expect(parseSlicers(s)).toEqual(slicers);
  });

  it('URL-encodes values containing pipe, comma, colon and percent', () => {
    const slicers: SlicerFilter[] = [
      { column: 'label', values: ['a|b', 'c,d', 'e:f', 'g%h'] },
    ];
    const s = serialiseSlicers(slicers);
    // None of the special separators should appear raw in the serialised string.
    expect(s.split(',')).toHaveLength(1); // Only one slicer — no un-escaped commas.
    // Parse should restore the original values exactly.
    expect(parseSlicers(s)).toEqual(slicers);
  });

  it('handles unicode values', () => {
    const slicers: SlicerFilter[] = [{ column: 'material', values: ['Béton armé', '木'] }];
    const s = serialiseSlicers(slicers);
    const parsed = parseSlicers(s);
    expect(parsed).toEqual(slicers);
  });

  it('drops slicers with no values on serialise', () => {
    const slicers: SlicerFilter[] = [
      { column: 'category', values: ['Wall'] },
      { column: 'empty', values: [] },
    ];
    expect(serialiseSlicers(slicers)).toBe('category:Wall');
  });

  it('tolerates malformed input gracefully', () => {
    expect(parseSlicers('justtext')).toEqual([]);
    expect(parseSlicers(':valueWithoutColumn')).toEqual([]);
    expect(parseSlicers('col:')).toEqual([]);
    // Trailing comma should not break parsing.
    expect(parseSlicers('category:Wall,')).toEqual([
      { column: 'category', values: ['Wall'] },
    ]);
  });
});

describe('urlState — pivot round-trip', () => {
  const snapshot: PivotConfigSnapshot = {
    groupBy: ['category', 'level'],
    aggCols: ['volume', 'area'],
    aggFn: 'sum',
    topN: 10,
    topNDirection: 'top',
    viz: 'table',
  };

  it('round-trips a full snapshot', () => {
    const s = serialisePivot(snapshot);
    expect(s).toEqual({
      group: 'category,level',
      sum: 'volume,area',
      agg: 'sum',
      top: '10',
      viz: null, // 'table' is the default and is omitted from the URL
    });
    expect(parsePivot(s)).toEqual(snapshot);
  });

  it('encodes bottom-N direction with a negative number', () => {
    const snap: PivotConfigSnapshot = { ...snapshot, topN: 5, topNDirection: 'bottom' };
    const s = serialisePivot(snap);
    expect(s.top).toBe('-5');
    expect(parsePivot(s)).toEqual(snap);
  });

  it('omits empty fields', () => {
    const s = serialisePivot({
      groupBy: [],
      aggCols: [],
      aggFn: '',
      topN: null,
      topNDirection: 'top',
      viz: 'table',
    });
    expect(s).toEqual({ group: null, sum: null, agg: null, top: null, viz: null });
  });

  it('returns null when the URL has no pivot params at all', () => {
    expect(parsePivot({})).toBeNull();
    expect(parsePivot({ group: null, sum: null })).toBeNull();
  });

  it('defaults agg fn to sum when missing', () => {
    const parsed = parsePivot({ group: 'category' });
    expect(parsed).not.toBeNull();
    expect(parsed!.aggFn).toBe('sum');
  });

  it('returns null snapshot when passed null', () => {
    expect(serialisePivot(null)).toEqual({ group: null, sum: null, agg: null, top: null, viz: null });
  });

  it('tolerates bogus top values', () => {
    expect(parsePivot({ group: 'x', top: 'banana' })?.topN).toBeNull();
    expect(parsePivot({ group: 'x', top: '0' })?.topN).toBeNull();
  });

  it('round-trips count_unique through ?piv_agg=', () => {
    const snap: PivotConfigSnapshot = {
      groupBy: ['category'],
      aggCols: ['client_name'],
      aggFn: 'count_unique',
      topN: null,
      topNDirection: 'top',
      viz: 'table',
    };
    const s = serialisePivot(snap);
    expect(s.agg).toBe('count_unique');
    expect(parsePivot(s)).toEqual(snap);
  });

  it('round-trips count through ?piv_agg=', () => {
    const snap: PivotConfigSnapshot = {
      groupBy: ['category'],
      aggCols: ['family'],
      aggFn: 'count',
      topN: null,
      topNDirection: 'top',
      viz: 'table',
    };
    const s = serialisePivot(snap);
    expect(s.agg).toBe('count');
    expect(parsePivot(s)).toEqual(snap);
  });

  it('rejects unknown agg functions in the URL (falls back to sum)', () => {
    // A typo in a shared link should not break the Pivot tab — the
    // `<select>` only has options for known agg fns, so we coerce back
    // to the default.
    const parsed = parsePivot({ group: 'category', agg: 'median' });
    expect(parsed?.aggFn).toBe('sum');
  });

  it('is case-insensitive for agg function names', () => {
    const parsed = parsePivot({ group: 'category', agg: 'COUNT_UNIQUE' });
    expect(parsed?.aggFn).toBe('count_unique');
  });
});

describe('urlState — chart round-trip', () => {
  const full: ChartConfig = {
    kind: 'line',
    category: 'category',
    value: 'volume',
    aggFn: 'sum',
    topN: 20,
    topNDirection: 'top',
    format: 'number',
  };

  it('round-trips kind / category / value / topN', () => {
    const s = serialiseChart(full);
    expect(s).toEqual({ kind: 'line', cat: 'category', val: 'volume', agg: null, top: '20' });
    const parsed = parseChart(s);
    expect(parsed.kind).toBe('line');
    expect(parsed.category).toBe('category');
    expect(parsed.value).toBe('volume');
    expect(parsed.topN).toBe(20);
    expect(parsed.topNDirection).toBe('top');
  });

  it('omits kind when it is the default (bar)', () => {
    const s = serialiseChart({ ...full, kind: 'bar' });
    expect(s.kind).toBeNull();
  });

  it('encodes bottom-N with a negative number', () => {
    const s = serialiseChart({ ...full, topN: 5, topNDirection: 'bottom' });
    expect(s.top).toBe('-5');
    const parsed = parseChart(s);
    expect(parsed.topN).toBe(5);
    expect(parsed.topNDirection).toBe('bottom');
  });

  it('ignores unknown chart kinds', () => {
    expect(parseChart({ kind: 'wasabi' }).kind).toBeUndefined();
  });

  it('round-trips a non-default aggFn', () => {
    const s = serialiseChart({ ...full, aggFn: 'count_unique' });
    expect(s.agg).toBe('count_unique');
    const parsed = parseChart(s);
    expect(parsed.aggFn).toBe('count_unique');
  });

  it('omits aggFn when it is the default (sum)', () => {
    const s = serialiseChart({ ...full, aggFn: 'sum' });
    expect(s.agg).toBeNull();
  });

  it('ignores unknown aggFn values (leaves aggFn undefined)', () => {
    expect(parseChart({ agg: 'median' }).aggFn).toBeUndefined();
  });

  it('is case-insensitive for chart aggFn', () => {
    expect(parseChart({ agg: 'COUNT' }).aggFn).toBe('count');
  });
});

describe('urlState — pivot viz mode', () => {
  it('defaults to table when the viz key is absent', () => {
    const parsed = parsePivot({ group: 'category', sum: 'volume' });
    expect(parsed?.viz).toBe('table');
  });

  it('round-trips a non-default viz mode', () => {
    const snapshot: PivotConfigSnapshot = {
      groupBy: ['category'],
      aggCols: ['volume'],
      aggFn: 'sum',
      topN: null,
      topNDirection: 'top',
      viz: 'heatmap',
    };
    const s = serialisePivot(snapshot);
    expect(s.viz).toBe('heatmap');
    const parsed = parsePivot({ group: s.group, sum: s.sum, agg: s.agg, top: s.top, viz: s.viz });
    expect(parsed?.viz).toBe('heatmap');
  });

  it('omits viz when it is the default (table)', () => {
    const snapshot: PivotConfigSnapshot = {
      groupBy: ['category'],
      aggCols: ['volume'],
      aggFn: 'sum',
      topN: null,
      topNDirection: 'top',
      viz: 'table',
    };
    const s = serialisePivot(snapshot);
    expect(s.viz).toBeNull();
  });

  it('accepts each of the five valid viz modes', () => {
    for (const viz of ['table', 'heatmap', 'bar', 'treemap', 'matrix'] as const) {
      const parsed = parsePivot({ group: 'category', viz });
      expect(parsed?.viz).toBe(viz);
    }
  });

  it('falls back to table on unknown viz values', () => {
    const parsed = parsePivot({ group: 'category', viz: 'radar' });
    expect(parsed?.viz).toBe('table');
  });
});

describe('urlState — computeDataBar', () => {
  it('returns 0 width when max is 0 (single-row case)', () => {
    expect(computeDataBar(42, 0)).toEqual({ widthPct: 0, negative: false });
  });

  it('returns 0 width when value is null / undefined', () => {
    expect(computeDataBar(null, 100)).toEqual({ widthPct: 0, negative: false });
    expect(computeDataBar(undefined, 100)).toEqual({ widthPct: 0, negative: false });
  });

  it('returns 0 width when value is NaN / Infinity', () => {
    expect(computeDataBar(NaN, 100).widthPct).toBe(0);
    expect(computeDataBar(Infinity, 100).widthPct).toBe(0);
  });

  it('computes proportional width', () => {
    expect(computeDataBar(50, 100).widthPct).toBe(50);
    expect(computeDataBar(25, 100).widthPct).toBe(25);
    expect(computeDataBar(100, 100).widthPct).toBe(100);
    expect(computeDataBar(0, 100).widthPct).toBe(0);
  });

  it('clamps to [0, 100] even when value exceeds max', () => {
    expect(computeDataBar(250, 100).widthPct).toBe(100);
    expect(computeDataBar(-250, 100).widthPct).toBe(100);
  });

  it('flags negative values and returns positive width from absolute value', () => {
    const bar = computeDataBar(-30, 100);
    expect(bar.widthPct).toBe(30);
    expect(bar.negative).toBe(true);
  });

  it('non-finite max also degrades to 0 width', () => {
    expect(computeDataBar(50, NaN).widthPct).toBe(0);
    expect(computeDataBar(50, Infinity).widthPct).toBe(0);
  });
});

describe('urlState — maxAbsAcross', () => {
  it('returns 0 for an empty list', () => {
    expect(maxAbsAcross([], (r) => r as number)).toBe(0);
  });

  it('ignores null / undefined / NaN samples', () => {
    const rows = [null, undefined, NaN, 5, 9, -3] as (number | null | undefined)[];
    expect(maxAbsAcross(rows, (r) => r)).toBe(9);
  });

  it('uses absolute values', () => {
    expect(maxAbsAcross([-12, 5, -3], (r) => r)).toBe(12);
  });

  it('handles a single row', () => {
    expect(maxAbsAcross([7], (r) => r)).toBe(7);
  });

  it('handles objects via accessor', () => {
    const rows = [{ v: 1 }, { v: 5 }, { v: 3 }];
    expect(maxAbsAcross(rows, (r) => r.v)).toBe(5);
  });
});
