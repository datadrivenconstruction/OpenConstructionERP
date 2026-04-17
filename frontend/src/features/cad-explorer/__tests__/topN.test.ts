import { describe, it, expect } from 'vitest';
import { applyTopN, applySlicers, groupMatchesSlicers } from '../aggregation';
import type { AggregateGroup } from '../api';

function mkGroup(cat: string, value: number): AggregateGroup {
  return {
    key: { Category: cat },
    results: { Volume: value },
    count: 1,
  };
}

describe('applyTopN', () => {
  it('returns all groups when topN is null', () => {
    const groups = [mkGroup('A', 10), mkGroup('B', 20), mkGroup('C', 5)];
    const out = applyTopN(groups, 'Volume', null, 'top', 'Category');
    expect(out).toHaveLength(3);
    // Sort still runs (descending by default).
    expect(out.map((g) => g.key.Category)).toEqual(['B', 'A', 'C']);
  });

  it('keeps only top-N groups by value desc', () => {
    const groups = [mkGroup('A', 10), mkGroup('B', 20), mkGroup('C', 5), mkGroup('D', 30)];
    const out = applyTopN(groups, 'Volume', 2, 'top', 'Category');
    expect(out).toHaveLength(2);
    expect(out.map((g) => g.key.Category)).toEqual(['D', 'B']);
  });

  it('keeps only bottom-N groups by value asc', () => {
    const groups = [mkGroup('A', 10), mkGroup('B', 20), mkGroup('C', 5), mkGroup('D', 30)];
    const out = applyTopN(groups, 'Volume', 2, 'bottom', 'Category');
    expect(out).toHaveLength(2);
    expect(out.map((g) => g.key.Category)).toEqual(['C', 'A']);
  });

  it('is stable when nth and (n+1)th values tie — alphabetical by category', () => {
    // Three groups with identical value 100 and one outlier.
    const groups = [
      mkGroup('Zebra', 100),
      mkGroup('Alpha', 100),
      mkGroup('Mango', 100),
      mkGroup('Outlier', 200),
    ];
    // Top-2 should yield Outlier, then the alphabetically first among ties.
    const out = applyTopN(groups, 'Volume', 2, 'top', 'Category');
    expect(out.map((g) => g.key.Category)).toEqual(['Outlier', 'Alpha']);

    // Top-3 must consistently return Alpha, Mango in that alphabetical order.
    const out3 = applyTopN(groups, 'Volume', 3, 'top', 'Category');
    expect(out3.map((g) => g.key.Category)).toEqual(['Outlier', 'Alpha', 'Mango']);
  });

  it('treats missing values as zero', () => {
    const groups: AggregateGroup[] = [
      { key: { Category: 'A' }, results: {}, count: 1 },
      { key: { Category: 'B' }, results: { Volume: 5 }, count: 1 },
    ];
    const out = applyTopN(groups, 'Volume', 2, 'top', 'Category');
    expect(out.map((g) => g.key.Category)).toEqual(['B', 'A']);
  });

  it('falls back to key concatenation when no categoryKey is given', () => {
    const groups = [
      { key: { A: 'x', B: 'y' }, results: { V: 5 }, count: 1 },
      { key: { A: 'a', B: 'b' }, results: { V: 5 }, count: 1 },
    ];
    const out = applyTopN(groups, 'V', 2, 'top');
    // 'a|b' < 'x|y', so that group is first among equal values.
    expect(out[0]?.key.A).toBe('a');
    expect(out[1]?.key.A).toBe('x');
  });
});

describe('applySlicers / groupMatchesSlicers', () => {
  it('returns everything when there are no slicers', () => {
    const rows = [{ Material: 'Concrete' }, { Material: 'Steel' }];
    expect(applySlicers(rows, [])).toEqual(rows);
  });

  it('keeps only rows matching a single slicer', () => {
    const rows = [{ Material: 'Concrete' }, { Material: 'Steel' }, { Material: 'Wood' }];
    const out = applySlicers(rows, [{ column: 'Material', values: ['Steel'] }]);
    expect(out).toEqual([{ Material: 'Steel' }]);
  });

  it('ANDs across columns', () => {
    const rows = [
      { Material: 'Concrete', Level: 'L1' },
      { Material: 'Concrete', Level: 'L2' },
      { Material: 'Steel', Level: 'L1' },
    ];
    const out = applySlicers(rows, [
      { column: 'Material', values: ['Concrete'] },
      { column: 'Level', values: ['L1'] },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]?.Level).toBe('L1');
  });

  it('ORs within one column values', () => {
    const rows = [
      { Material: 'Concrete' },
      { Material: 'Steel' },
      { Material: 'Wood' },
    ];
    const out = applySlicers(rows, [
      { column: 'Material', values: ['Concrete', 'Steel'] },
    ]);
    expect(out).toHaveLength(2);
  });

  it('groupMatchesSlicers mirrors applySlicers semantics', () => {
    const group: AggregateGroup = {
      key: { Material: 'Concrete', Level: 'L1' },
      results: { Volume: 10 },
      count: 1,
    };
    expect(
      groupMatchesSlicers(group, [{ column: 'Material', values: ['Concrete'] }]),
    ).toBe(true);
    expect(
      groupMatchesSlicers(group, [{ column: 'Material', values: ['Steel'] }]),
    ).toBe(false);
    expect(
      groupMatchesSlicers(group, [
        { column: 'Material', values: ['Concrete'] },
        { column: 'Level', values: ['L2'] },
      ]),
    ).toBe(false);
  });
});
