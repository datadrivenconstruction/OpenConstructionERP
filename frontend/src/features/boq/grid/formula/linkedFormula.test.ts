// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import {
  aggregateValues,
  buildFormulaLinkPayload,
  collectFormulaVars,
  previewFormula,
  type FormulaElementInput,
} from './linkedFormula';

const els: FormulaElementInput[] = [
  { id: 'a', label: 'Wall A', quantities: { Volume: 2, Length: 5 }, properties: { '[Type] BP_Volume': 0.5 } },
  { id: 'b', label: 'Wall B', quantities: { Volume: 3, Length: 4 }, properties: { '[Type] BP_Volume': '1.5' } },
  { id: 'c', label: 'Wall C', quantities: { Volume: 1 }, properties: {} },
];

describe('previewFormula', () => {
  it('evaluates per element and sums, resolving [Type] params', () => {
    const p = previewFormula('volume + type_bp_volume', 'sum', els.slice(0, 2));
    expect(p.rows.map((r) => r.value)).toEqual([2.5, 4.5]);
    expect(p.total).toBe(7);
    expect(p.skipped).toEqual([]);
  });

  it('lists elements missing a variable instead of counting them as 0', () => {
    const p = previewFormula('volume + type_bp_volume', 'sum', els);
    expect(p.total).toBe(7);
    expect(p.skipped).toHaveLength(1);
    expect(p.skipped[0]).toMatchObject({ id: 'c', missing: ['type_bp_volume'] });
  });

  it('supports functions and reports a syntax error with no rows', () => {
    expect(previewFormula('round(length * volume, 1)', 'max', els).total).toBe(12);
    const bad = previewFormula('volume +', 'sum', els);
    expect(bad.error).toBeTruthy();
    expect(bad.total).toBeNull();
  });

  it('returns an empty preview for a blank formula', () => {
    expect(previewFormula('  ', 'sum', els)).toEqual({ total: null, rows: [], skipped: [], error: null });
  });
});

describe('aggregateValues', () => {
  it('handles sum, max, min, count and empty input', () => {
    expect(aggregateValues([1, 2, 3], 'sum')).toBe(6);
    expect(aggregateValues([1, 2, 3], 'max')).toBe(3);
    expect(aggregateValues([1, 2, 3], 'min')).toBe(1);
    expect(aggregateValues([1, 2, 3], 'count')).toBe(3);
    expect(aggregateValues([], 'sum')).toBeNull();
  });
});

describe('collectFormulaVars', () => {
  it('lists normalised names with availability counts, widest first', () => {
    const chips = collectFormulaVars(els);
    expect(chips[0]).toMatchObject({ name: 'volume', count: 3 });
    expect(chips.find((c) => c.name === 'type_bp_volume')).toMatchObject({ label: '[Type] BP_Volume', count: 2 });
  });
});

describe('buildFormulaLinkPayload', () => {
  it('builds a formula-mode create body without quantity_field', () => {
    const body = buildFormulaLinkPayload('m1', ['s1', 's2'], ' volume * 2 ', 'max');
    expect(body).toEqual({
      model_id: 'm1',
      element_stable_ids: ['s1', 's2'],
      projection_mode: 'formula',
      formula: 'volume * 2',
      aggregation: 'max',
      target_field: 'quantity',
    });
    expect('quantity_field' in body).toBe(false);
  });
});
