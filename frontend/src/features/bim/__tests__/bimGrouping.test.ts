// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import type { BIMElementGroup } from '../api';
import {
  buildGroupTree,
  decodeUrlFilter,
  discoverPropertyKeys,
  encodeUrlFilter,
  groupValueOf,
  groupsToCsv,
  isConditionComplete,
  matchesCondition,
  resolveGroupMembers,
  totalsOf,
  withResolvedMembers,
} from '../bimGrouping';

// Shaped like the demo "Residential House" IFC rows.
const el = (
  id: string,
  element_type: string,
  storey: string,
  properties: Record<string, unknown> = {},
  quantities: Record<string, unknown> = {},
): BIMElementData =>
  ({ id, element_type, storey, name: `${element_type} ${id}`, properties, quantities }) as unknown as BIMElementData;

const rows = [
  el('w1', 'IfcWall', 'Ground Floor', { '[other] category': 'Walls', family: 'Basic Wall', material: 'Brick' }, { area: 10, volume: 2 }),
  el('w2', 'IfcWallStandardCase', 'Ground Floor', { '[other] category': 'Walls', family: 'Basic Wall' }, { area: 5 }),
  el('d1', 'IfcDoor', 'Ground Floor', { '[other] category': 'Doors', 'Fire Rating': 'EI30' }),
  el('r1', 'IfcRoof', 'Roof', { category: 'IfcRoof', material: 'Tiles' }, { area: '40,5' }),
];

describe('groupValueOf', () => {
  it('prefers the human category over the IFC class', () => {
    expect(groupValueOf(rows[0]!, 'category')).toBe('Walls');
    expect(groupValueOf(rows[3]!, 'category')).toBe('IfcRoof');
    expect(groupValueOf(rows[0]!, 'ifc_class')).toBe('IfcWall');
  });

  it('reads level, family, material and custom parameters', () => {
    expect(groupValueOf(rows[3]!, 'level')).toBe('Roof');
    expect(groupValueOf(rows[0]!, 'family')).toBe('Basic Wall');
    expect(groupValueOf(rows[1]!, 'material')).toBe('');
    expect(groupValueOf(rows[2]!, 'prop:fire rating')).toBe('EI30');
  });
});

describe('buildGroupTree', () => {
  it('groups by one key with counts and quantity totals', () => {
    const tree = buildGroupTree(rows, 'category');
    expect(tree.map((n) => [n.value, n.count])).toEqual([
      ['Walls', 2],
      ['Doors', 1],
      ['IfcRoof', 1],
    ]);
    expect(tree[0]!.area).toBe(15);
    expect(tree[0]!.volume).toBe(2);
    expect(tree[2]!.area).toBe(40.5);
    expect(totalsOf(tree).count).toBe(4);
  });

  it('nests a second level and puts "(not set)" last', () => {
    const tree = buildGroupTree(rows, 'level', 'material');
    const ground = tree.find((n) => n.value === 'Ground Floor')!;
    expect(ground.children.map((c) => [c.value, c.count])).toEqual([
      ['Brick', 1],
      ['', 2],
    ]);
    expect(ground.ids).toEqual(['w1', 'w2', 'd1']);
  });
});

describe('conditions', () => {
  it('matches equals, contains, not and numeric ranges', () => {
    expect(matchesCondition(rows[0]!, { field: 'material', op: 'eq', value: 'brick' })).toBe(true);
    expect(matchesCondition(rows[0]!, { field: 'family', op: 'contains', value: 'wall' })).toBe(true);
    expect(matchesCondition(rows[2]!, { field: 'category', op: 'neq', value: 'Walls' })).toBe(true);
    expect(matchesCondition(rows[0]!, { field: 'qty:area', op: 'between', min: 8, max: 12 })).toBe(true);
    expect(matchesCondition(rows[1]!, { field: 'qty:area', op: 'between', min: 8 })).toBe(false);
  });

  it('rejects incomplete or inverted conditions', () => {
    expect(isConditionComplete({ field: 'material', op: 'eq', value: ' ' })).toBe(false);
    expect(isConditionComplete({ field: 'qty:area', op: 'between', min: 5, max: 1 })).toBe(false);
    expect(isConditionComplete({ field: 'qty:area', op: 'between', max: 1 })).toBe(true);
  });
});

describe('URL codec', () => {
  it('round-trips the filter and drops garbage', () => {
    const state = {
      search: 'wall',
      storeys: ['Roof'],
      types: ['IfcWall'],
      buildingsOnly: false,
      conditions: [{ field: 'qty:volume' as const, op: 'between' as const, value: undefined, min: 1, max: null }],
    };
    expect(decodeUrlFilter(encodeUrlFilter(state))).toEqual(state);
    expect(encodeUrlFilter({ search: '', storeys: [], types: [], buildingsOnly: true, conditions: [] })).toBeNull();
    expect(decodeUrlFilter('{not json')).toBeNull();
    expect(decodeUrlFilter('{"c":[{"field":"x","op":"drop"}],"s":[1]}')).toEqual({
      search: '',
      storeys: [],
      types: [],
      buildingsOnly: true,
      conditions: [],
    });
  });
});

describe('saved groups', () => {
  const group = (patch: Partial<BIMElementGroup>): BIMElementGroup =>
    ({
      id: 'g',
      name: 'All Walls',
      is_dynamic: true,
      filter_criteria: {},
      member_element_ids: [],
      element_count: 0,
      ...patch,
    }) as BIMElementGroup;

  it('resolves a dynamic group whose server snapshot is empty', () => {
    const g = group({ filter_criteria: { element_type: ['IfcWall', 'IfcWallStandardCase', 'Wall'] } });
    expect(resolveGroupMembers(g, rows)).toEqual(['w1', 'w2']);
    expect(withResolvedMembers(g, rows).element_count).toBe(2);
  });

  it('narrows static ids to the loaded model', () => {
    const g = group({ is_dynamic: false, member_element_ids: ['w1', 'gone'] });
    expect(resolveGroupMembers(g, rows)).toEqual(['w1']);
    expect(resolveGroupMembers(g, [])).toEqual(['w1', 'gone']);
  });
});

describe('export and discovery', () => {
  it('writes a CSV with a total row and neutralised formulas', () => {
    const tree = buildGroupTree([...rows, el('x', '=cmd', 'L1')], 'ifc_class');
    const csv = groupsToCsv(
      tree,
      { level1: 'Class', count: 'Count', length: 'L', area: 'A', volume: 'V', notSet: '-', total: 'Total' },
      false,
    );
    const lines = csv.split('\r\n');
    expect(lines[0]).toBe('Class,Count,L,A,V');
    expect(lines).toContain("'=cmd,1,0,0,0");
    expect(lines[lines.length - 1]).toBe('Total,5,0,55.5,2');
  });

  it('offers parameters present on at least two elements', () => {
    expect(discoverPropertyKeys(rows)).toEqual(['[other] category', 'family', 'material']);
  });
});
