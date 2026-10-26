// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import type { BranchCompareRow, BranchNode, PlanItem } from './branchApi';
import {
  deltaSign,
  flattenTree,
  planValueText,
  resolutionsFor,
  undecidedConflicts,
  visibleCompareRows,
  withRequiredParents,
} from './branchHelpers';

function node(id: string, parent: string | null, created: string, isMain = false): BranchNode {
  return {
    boq_id: id,
    name: id,
    is_main: isMain,
    parent_boq_id: parent,
    status: 'open',
    note: '',
    is_locked: false,
    created_at: created,
    created_by: null,
    author: '',
    position_count: 0,
    direct_cost: '0',
    grand_total: '0',
    delta_vs_parent: null,
    base_snapshot_id: null,
    source_snapshot_id: null,
    merged_at: null,
    merged_by: null,
    merge_snapshot_id: null,
    design_option: null,
  };
}

function item(key: string, action: PlanItem['action'], extra: Partial<PlanItem> = {}): PlanItem {
  return {
    key,
    action,
    conflict: false,
    ordinal: key,
    description: key,
    is_section: false,
    parent_key: null,
    depth: 0,
    fields: {},
    ...extra,
  };
}

describe('flattenTree', () => {
  it('puts main first and every branch under its parent, oldest first', () => {
    const rows = flattenTree([
      node('b2', 'main', '2026-10-03'),
      node('main', null, '2026-10-01', true),
      node('b1', 'main', '2026-10-02'),
      node('b1a', 'b1', '2026-10-04'),
    ]);
    expect(rows.map((r) => [r.node.boq_id, r.depth])).toEqual([
      ['main', 0],
      ['b1', 1],
      ['b1a', 2],
      ['b2', 1],
    ]);
  });

  it('hangs a branch whose parent is gone off main instead of dropping it', () => {
    const rows = flattenTree([node('main', null, '1', true), node('orphan', 'deleted', '2')]);
    expect(rows.map((r) => r.node.boq_id)).toEqual(['main', 'orphan']);
  });

  it('returns nothing without a main estimate', () => {
    expect(flattenTree([node('b', 'x', '1')])).toEqual([]);
  });
});

describe('deltaSign', () => {
  it('reads decimal strings', () => {
    expect(deltaSign('-12.50')).toBe(-1);
    expect(deltaSign('0.00')).toBe(0);
    expect(deltaSign('3')).toBe(1);
    expect(deltaSign(null)).toBe(0);
    expect(deltaSign('n/a')).toBe(0);
  });
});

describe('conflict bookkeeping', () => {
  const items = [item('a', 'update', { conflict: true }), item('b', 'update', { conflict: true }), item('c', 'add')];

  it('lists only selected conflicts without a decision', () => {
    const pending = undecidedConflicts(items, new Set(['a', 'b', 'c']), { a: 'source' });
    expect(pending.map((i) => i.key)).toEqual(['b']);
    expect(undecidedConflicts(items, new Set(['a', 'c']), { a: 'target' })).toEqual([]);
  });

  it('sends decisions only for lines still selected', () => {
    expect(resolutionsFor(new Set(['a']), { a: 'source', b: 'target' })).toEqual({ a: 'source' });
  });
});

describe('withRequiredParents', () => {
  it('carries the new sections a new line sits in', () => {
    const items = [
      item('S', 'add', { is_section: true }),
      item('S1', 'add', { parent_key: 'S', is_section: true, depth: 1 }),
      item('L', 'add', { parent_key: 'S1', depth: 2 }),
      item('U', 'update', { parent_key: 'X' }),
    ];
    expect([...withRequiredParents(items, ['L'])].sort()).toEqual(['L', 'S', 'S1']);
    expect([...withRequiredParents(items, ['U'])]).toEqual(['U']);
  });
});

describe('visibleCompareRows and planValueText', () => {
  it('hides unchanged rows on request', () => {
    const rows = [{ change_type: 'unchanged' }, { change_type: 'changed' }] as BranchCompareRow[];
    expect(visibleCompareRows(rows, true)).toHaveLength(1);
    expect(visibleCompareRows(rows, false)).toHaveLength(2);
  });

  it('renders plan values, classification as code pairs', () => {
    expect(planValueText(null)).toBe('-');
    expect(planValueText('120.00')).toBe('120.00');
    expect(planValueText({ din276: '330', nrm: '' })).toBe('din276: 330');
    expect(planValueText({})).toBe('-');
  });
});
