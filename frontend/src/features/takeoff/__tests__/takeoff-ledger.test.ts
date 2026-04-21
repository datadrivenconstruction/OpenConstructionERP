/**
 * Unit tests for the pure ledger helpers — sort, filter, subtotals,
 * grand totals, CSV serialization.
 */

import { describe, it, expect } from 'vitest';
import type { Measurement } from '../lib/takeoff-types';
import {
  emptyFilter,
  filterMeasurements,
  groupSubtotals,
  ledgerToCsv,
  sortMeasurements,
  typeGrandTotals,
  uniqueFilterOptions,
  withOrdinals,
} from '../lib/takeoff-ledger';

function m(partial: Partial<Measurement> & { id: string }): Measurement {
  return {
    type: partial.type ?? 'distance',
    points: partial.points ?? [],
    value: partial.value ?? 0,
    unit: partial.unit ?? 'm',
    label: partial.label ?? '',
    annotation: partial.annotation ?? '',
    page: partial.page ?? 1,
    group: partial.group ?? 'General',
    ...partial,
  };
}

/** Canonical 5-measurement fixture across 2 groups + 2 pages. */
function fiveFixture(): Measurement[] {
  return [
    m({ id: 'a', type: 'distance', value: 10, unit: 'm', group: 'Walls', page: 1, annotation: 'Wall 1' }),
    m({ id: 'b', type: 'distance', value: 5, unit: 'm', group: 'Walls', page: 1, annotation: 'Wall 2' }),
    m({ id: 'c', type: 'area', value: 20, unit: 'm²', group: 'Floors', page: 2, annotation: 'Floor 1' }),
    m({ id: 'd', type: 'area', value: 15, unit: 'm²', group: 'Floors', page: 2, annotation: 'Floor 2' }),
    m({ id: 'e', type: 'count', value: 3, unit: 'pcs', group: 'Walls', page: 1, annotation: 'Doors' }),
  ];
}

describe('filterMeasurements', () => {
  it('returns every measurement when filter is empty', () => {
    const fixture = fiveFixture();
    expect(filterMeasurements(fixture, emptyFilter())).toHaveLength(5);
  });

  it('restricts by group', () => {
    const fixture = fiveFixture();
    const res = filterMeasurements(fixture, {
      groups: new Set(['Walls']),
      types: new Set(),
      pages: new Set(),
    });
    expect(res.map((r) => r.id).sort()).toEqual(['a', 'b', 'e']);
  });

  it('restricts by type', () => {
    const fixture = fiveFixture();
    const res = filterMeasurements(fixture, {
      groups: new Set(),
      types: new Set(['area']),
      pages: new Set(),
    });
    expect(res.map((r) => r.id).sort()).toEqual(['c', 'd']);
  });

  it('restricts by page', () => {
    const fixture = fiveFixture();
    const res = filterMeasurements(fixture, {
      groups: new Set(),
      types: new Set(),
      pages: new Set([2]),
    });
    expect(res.map((r) => r.id).sort()).toEqual(['c', 'd']);
  });

  it('combines restrictions (AND semantics)', () => {
    const fixture = fiveFixture();
    const res = filterMeasurements(fixture, {
      groups: new Set(['Walls']),
      types: new Set(['distance']),
      pages: new Set([1]),
    });
    expect(res.map((r) => r.id).sort()).toEqual(['a', 'b']);
  });
});

describe('sortMeasurements', () => {
  it('sorts by value ascending', () => {
    const fixture = fiveFixture();
    const sorted = sortMeasurements(fixture, 'value', 'asc');
    expect(sorted.map((m) => m.value)).toEqual([3, 5, 10, 15, 20]);
  });

  it('sorts by value descending', () => {
    const fixture = fiveFixture();
    const sorted = sortMeasurements(fixture, 'value', 'desc');
    expect(sorted.map((m) => m.value)).toEqual([20, 15, 10, 5, 3]);
  });

  it('toggle asc ↔ desc with the same column flips order', () => {
    const fixture = fiveFixture();
    const asc = sortMeasurements(fixture, 'value', 'asc').map((m) => m.id);
    const desc = sortMeasurements(fixture, 'value', 'desc').map((m) => m.id);
    expect(asc).toEqual([...desc].reverse());
  });

  it('sorts by type', () => {
    const fixture = fiveFixture();
    const sorted = sortMeasurements(fixture, 'type', 'asc');
    expect(sorted.map((m) => m.type)).toEqual([
      'area',
      'area',
      'count',
      'distance',
      'distance',
    ]);
  });

  it('sorts by group, then tie-breaks deterministically', () => {
    const fixture = fiveFixture();
    const sorted = sortMeasurements(fixture, 'group', 'asc');
    expect(sorted[0]!.group).toBe('Floors');
    expect(sorted[4]!.group).toBe('Walls');
  });

  it('sorts by page', () => {
    const fixture = fiveFixture();
    const asc = sortMeasurements(fixture, 'page', 'asc').map((m) => m.page);
    expect(asc[0]).toBe(1);
    expect(asc[asc.length - 1]).toBe(2);
  });

  it('does not mutate input', () => {
    const fixture = fiveFixture();
    const ids = fixture.map((m) => m.id);
    sortMeasurements(fixture, 'value', 'desc');
    expect(fixture.map((m) => m.id)).toEqual(ids);
  });
});

describe('groupSubtotals', () => {
  it('computes one entry per group', () => {
    const fixture = fiveFixture();
    const subs = groupSubtotals(fixture);
    expect(subs.map((s) => s.group).sort()).toEqual(['Floors', 'Walls']);
  });

  it('sums per-unit totals within a group', () => {
    const fixture = fiveFixture();
    const subs = groupSubtotals(fixture);
    const walls = subs.find((s) => s.group === 'Walls')!;
    expect(walls.totals.m).toBe(15); // 10 + 5
    expect(walls.totals.pcs).toBe(3);
  });

  it('computes floors area total', () => {
    const fixture = fiveFixture();
    const subs = groupSubtotals(fixture);
    const floors = subs.find((s) => s.group === 'Floors')!;
    expect(floors.totals['m²']).toBe(35); // 20 + 15
  });

  it('counts annotations in the group count but excludes them from totals', () => {
    const measurements: Measurement[] = [
      m({ id: 'a', type: 'distance', value: 10, unit: 'm', group: 'G' }),
      m({ id: 'b', type: 'cloud', value: 99, unit: '', group: 'G' }),
    ];
    const subs = groupSubtotals(measurements);
    expect(subs[0]!.count).toBe(2);
    expect(subs[0]!.totals.m).toBe(10);
  });
});

describe('typeGrandTotals', () => {
  it('groups by type', () => {
    const fixture = fiveFixture();
    const totals = typeGrandTotals(fixture);
    const dist = totals.find((t) => t.type === 'distance');
    expect(dist?.total).toBe(15);
    expect(dist?.count).toBe(2);
  });

  it('reports grand totals per unit type', () => {
    const fixture = fiveFixture();
    const totals = typeGrandTotals(fixture);
    const area = totals.find((t) => t.type === 'area');
    expect(area?.total).toBe(35);
    expect(area?.unit).toBe('m²');
  });

  it('excludes annotation types entirely', () => {
    const measurements: Measurement[] = [
      m({ id: 'a', type: 'distance', value: 10, unit: 'm', group: 'G' }),
      m({ id: 'b', type: 'cloud', value: 99, unit: '', group: 'G' }),
      m({ id: 'c', type: 'arrow', value: 99, unit: '', group: 'G' }),
    ];
    const totals = typeGrandTotals(measurements);
    expect(totals).toHaveLength(1);
    expect(totals[0]!.type).toBe('distance');
  });
});

describe('withOrdinals', () => {
  it('assigns 1-based ordinals in array order', () => {
    const fixture = fiveFixture();
    const rows = withOrdinals(fixture);
    expect(rows.map((r) => r.ordinal)).toEqual([1, 2, 3, 4, 5]);
    expect(rows[0]!.measurement.id).toBe('a');
  });
});

describe('uniqueFilterOptions', () => {
  it('returns sorted unique dimensions', () => {
    const fixture = fiveFixture();
    const options = uniqueFilterOptions(fixture);
    expect(options.groups).toEqual(['Floors', 'Walls']);
    expect(options.types.sort()).toEqual(['area', 'count', 'distance']);
    expect(options.pages).toEqual([1, 2]);
  });
});

describe('ledgerToCsv', () => {
  it('begins with the canonical header row', () => {
    const csv = ledgerToCsv(fiveFixture());
    expect(csv.split('\n')[0]).toBe('#,Type,Annotation,Group,Value,Unit,Page');
  });

  it('includes one row per measurement', () => {
    const fixture = fiveFixture();
    const csv = ledgerToCsv(fixture);
    // Every measurement id's annotation should appear.
    for (const me of fixture) {
      expect(csv).toContain(me.annotation);
    }
  });

  it('includes subtotal rows for each group', () => {
    const csv = ledgerToCsv(fiveFixture());
    expect(csv).toContain('Walls subtotal');
    expect(csv).toContain('Floors subtotal');
  });

  it('includes grand-total rows per type', () => {
    const csv = ledgerToCsv(fiveFixture());
    expect(csv).toContain('Total distance');
    expect(csv).toContain('Total area');
    expect(csv).toContain('Total count');
  });

  it('quotes values containing commas or quotes', () => {
    const measurements: Measurement[] = [
      m({ id: 'a', type: 'distance', value: 10, unit: 'm', annotation: 'hello, "world"' }),
    ];
    const csv = ledgerToCsv(measurements);
    expect(csv).toContain('"hello, ""world"""');
  });
});
