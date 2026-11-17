import { describe, expect, it } from 'vitest';
import {
  authorOf,
  compareOrder,
  snapshotDiffRows,
  snapshotPreview,
} from './revisionHelpers';
import type { SnapshotCompareResponse } from './api';

const lineage = [
  { boq_id: 'r0' },
  { boq_id: 'r1' },
  { boq_id: 'r2' },
];

describe('compareOrder', () => {
  it('puts the older revision first whichever was ticked first', () => {
    expect(compareOrder(lineage, 'r2', 'r0')).toEqual(['r0', 'r2']);
    expect(compareOrder(lineage, 'r0', 'r2')).toEqual(['r0', 'r2']);
  });
});

describe('authorOf', () => {
  it('names the recorded actor', () => {
    expect(authorOf({ user_id: 'u1', user_name: 'Dana Field' })).toEqual({ kind: 'user', name: 'Dana Field' });
  });
  it('never invents an author when none was recorded', () => {
    expect(authorOf({ user_id: null })).toEqual({ kind: 'unavailable' });
    expect(authorOf({})).toEqual({ kind: 'unavailable' });
  });
  it('keeps an actor whose account is gone apart from a missing one', () => {
    expect(authorOf({ user_id: 'u9' })).toEqual({ kind: 'unknown' });
  });
});

describe('snapshotDiffRows', () => {
  const resp = {
    added: [{ ordinal: '3', description: 'Roof', change_type: 'added', fields: { quantity: 4, unit_rate: 50, total: 200 } }],
    removed: [{ ordinal: '2', description: 'Walls', change_type: 'removed', fields: { quantity: 5, unit_rate: 100, total: 500 } }],
    changed: [
      {
        ordinal: '1',
        description: 'Slab',
        change_type: 'changed',
        fields: { quantity: { old: 10, new: 12 }, total: { old: 1000, new: 1200 } },
      },
    ],
  } as unknown as SnapshotCompareResponse;

  it('lists only differences, with before and after for each changed field', () => {
    const rows = snapshotDiffRows(resp);
    expect(rows.map((r) => [r.kind, r.ordinal])).toEqual([
      ['changed', '1'],
      ['added', '3'],
      ['removed', '2'],
    ]);
    expect(rows[0]!.changes).toEqual([
      { field: 'quantity', before: 10, after: 12 },
      { field: 'total', before: 1000, after: 1200 },
    ]);
    expect(rows[1]!.changes).toContainEqual({ field: 'total', before: null, after: 200 });
    expect(rows[2]!.changes).toContainEqual({ field: 'quantity', before: 5, after: null });
  });
});

describe('snapshotPreview', () => {
  it('shows the saved lines in bill order and totals them without touching the bill', () => {
    const data = {
      positions: [
        { ordinal: '2', description: 'Walls', unit: 'm3', quantity: '5', unit_rate: '100', total: '500', sort_order: 2 },
        { ordinal: '1', description: 'Structure', unit: '', quantity: '0', unit_rate: '0', total: '0', sort_order: 0 },
        { ordinal: '1.1', description: 'Slab', unit: 'm3', quantity: '10', unit_rate: '100', total: '1000', sort_order: 1 },
      ],
      markups: [{ name: 'Overhead' }],
    };
    const frozen = JSON.stringify(data);
    const view = snapshotPreview(data);
    expect(view.rows.map((r) => r.ordinal)).toEqual(['1', '1.1', '2']);
    expect(view.rows[0]!.isSection).toBe(true);
    expect(view.directTotal).toBe(1500);
    expect(view.markupCount).toBe(1);
    expect(JSON.stringify(data)).toBe(frozen);
  });

  it('copes with a snapshot that carries no lines', () => {
    expect(snapshotPreview({})).toEqual({ rows: [], directTotal: 0, markupCount: 0 });
  });
});
