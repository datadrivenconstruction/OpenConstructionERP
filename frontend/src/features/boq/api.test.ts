// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  normalizePosition,
  normalizePositions,
  groupPositionsIntoSections,
  type Position,
} from './api';

/* ── Position factory ────────────────────────────────────────────────── */

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: 'pos-1',
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '01.001',
    description: 'Test position',
    unit: 'm2',
    quantity: 10,
    unit_rate: 50,
    total: 500,
    classification: {},
    source: 'manual',
    confidence: null,
    validation_status: 'pending',
    sort_order: 0,
    metadata: {},
    ...overrides,
  };
}

/* ── normalizePosition ───────────────────────────────────────────────── */

describe('normalizePosition', () => {
  it('should return position unchanged if metadata exists', () => {
    const pos = makePosition({ metadata: { key: 'value' } });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({ key: 'value' });
  });

  it('should copy metadata_ to metadata when metadata is missing', () => {
    const pos = makePosition({ metadata: undefined as unknown as Record<string, unknown>, metadata_: { legacy: true } });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({ legacy: true });
  });

  it('should set empty metadata when both are missing', () => {
    const pos = makePosition({ metadata: undefined as unknown as Record<string, unknown> });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({});
  });
});

/* ── normalizePositions ──────────────────────────────────────────────── */

describe('normalizePositions', () => {
  it('should normalize an array of positions', () => {
    const positions = [
      makePosition({ id: 'p1', metadata: { a: 1 } }),
      makePosition({ id: 'p2', metadata: undefined as unknown as Record<string, unknown>, metadata_: { b: 2 } }),
    ];
    const result = normalizePositions(positions);
    expect(result).toHaveLength(2);
    expect(result[0].metadata).toEqual({ a: 1 });
    expect(result[1].metadata).toEqual({ b: 2 });
  });

  it('should handle empty array', () => {
    expect(normalizePositions([])).toEqual([]);
  });
});

/* ── groupPositionsIntoSections ──────────────────────────────────────── */

describe('groupPositionsIntoSections', () => {
  it('should group positions under their parent section', () => {
    const section = makePosition({
      id: 'sec-1',
      ordinal: '01',
      description: 'Foundations',
      unit: '',
      quantity: 0,
      unit_rate: 0,
      total: 0,
      sort_order: 0,
    });
    const child1 = makePosition({
      id: 'pos-1',
      parent_id: 'sec-1',
      ordinal: '01.001',
      total: 100,
      sort_order: 10,
    });
    const child2 = makePosition({
      id: 'pos-2',
      parent_id: 'sec-1',
      ordinal: '01.002',
      total: 200,
      sort_order: 20,
    });

    const result = groupPositionsIntoSections([section, child1, child2]);
    expect(result.sections).toHaveLength(1);
    expect(result.sections[0].section.id).toBe('sec-1');
    expect(result.sections[0].children).toHaveLength(2);
    expect(result.sections[0].subtotal).toBe(300);
    expect(result.ungrouped).toHaveLength(0);
  });

  it('should put orphan positions in ungrouped', () => {
    const orphan = makePosition({ id: 'pos-1', parent_id: null, total: 500 });
    const result = groupPositionsIntoSections([orphan]);
    expect(result.ungrouped).toHaveLength(1);
    expect(result.ungrouped[0].id).toBe('pos-1');
    expect(result.sections).toHaveLength(0);
  });

  it('should handle mixed sections and ungrouped', () => {
    const section = makePosition({
      id: 'sec-1',
      ordinal: '01',
      description: 'Section 1',
      unit: '',
      quantity: 0,
      unit_rate: 0,
      total: 0,
    });
    const child = makePosition({
      id: 'pos-1',
      parent_id: 'sec-1',
      ordinal: '01.001',
      total: 100,
    });
    const orphan = makePosition({
      id: 'pos-2',
      parent_id: null,
      ordinal: '02.001',
      total: 200,
    });

    const result = groupPositionsIntoSections([section, child, orphan]);
    expect(result.sections).toHaveLength(1);
    expect(result.ungrouped).toHaveLength(1);
  });

  it('should sort sections by sort_order then ordinal', () => {
    const sec1 = makePosition({
      id: 'sec-1', ordinal: '02', description: 'B', unit: '', quantity: 0, unit_rate: 0, total: 0,
      sort_order: 20,
    });
    const sec2 = makePosition({
      id: 'sec-2', ordinal: '01', description: 'A', unit: '', quantity: 0, unit_rate: 0, total: 0,
      sort_order: 10,
    });

    const result = groupPositionsIntoSections([sec1, sec2]);
    expect(result.sections[0].section.id).toBe('sec-2');
    expect(result.sections[1].section.id).toBe('sec-1');
  });

  it('should handle empty array', () => {
    const result = groupPositionsIntoSections([]);
    expect(result.sections).toHaveLength(0);
    expect(result.ungrouped).toHaveLength(0);
  });
});
