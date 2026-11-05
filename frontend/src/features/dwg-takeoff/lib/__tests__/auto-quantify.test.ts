// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Unit tests for per-layer auto-quantification.
 *
 * Verifies that each layer rolls its exact vector geometry up into
 * area / length / count, picks the right headline measure, and converts
 * raw DXF units to metres - the contract the Summary panel's
 * "Auto-quantify by layer" table relies on.
 */

import { describe, it, expect } from 'vitest';
import { quantifyByLayer, quantityFor, unitForMeasure } from '../auto-quantify';
import type { DxfEntity } from '../../api';

/* ── Entity factories (layer-aware) ──────────────────────────────────── */

function rect(id: string, layer: string, w: number, h: number, closed = true): DxfEntity {
  return {
    id,
    type: 'LWPOLYLINE',
    layer,
    color: '#fff',
    vertices: [
      { x: 0, y: 0 },
      { x: w, y: 0 },
      { x: w, y: h },
      { x: 0, y: h },
    ],
    closed,
  };
}

function line(id: string, layer: string, length: number): DxfEntity {
  return { id, type: 'LINE', layer, color: '#fff', start: { x: 0, y: 0 }, end: { x: length, y: 0 } };
}

function circle(id: string, layer: string, radius: number): DxfEntity {
  return { id, type: 'CIRCLE', layer, color: '#fff', start: { x: 0, y: 0 }, radius };
}

function arc(id: string, layer: string, radius: number, start: number, end: number): DxfEntity {
  return { id, type: 'ARC', layer, color: '#fff', start: { x: 0, y: 0 }, radius, start_angle: start, end_angle: end };
}

function insert(id: string, layer: string, block: string): DxfEntity {
  return { id, type: 'INSERT', layer, color: '#fff', start: { x: 0, y: 0 }, block_name: block };
}

/* ── Tests ───────────────────────────────────────────────────────────── */

describe('quantifyByLayer', () => {
  it('returns nothing for an empty drawing', () => {
    expect(quantifyByLayer([])).toEqual([]);
  });

  it('picks AREA as the headline for layers with closed polylines', () => {
    const [row] = quantifyByLayer([rect('r1', 'SLAB', 10, 5)]);
    expect(row!.layer).toBe('SLAB');
    expect(row!.primary).toBe('area');
    expect(row!.area).toBeCloseTo(50, 3);
    expect(row!.quantity).toBeCloseTo(50, 3);
    expect(row!.unit).toBe('m²');
    expect(row!.count).toBe(1);
    expect(row!.available).toContain('area');
    expect(row!.available).toContain('count');
  });

  it('subtracts hatch holes (shafts, openings) from the hatched area', () => {
    const sq = (x: number, y: number, s: number) => [
      { x, y },
      { x: x + s, y },
      { x: x + s, y: y + s },
      { x, y: y + s },
    ];
    const hatch: DxfEntity = {
      id: 'h1',
      type: 'HATCH',
      layer: 'SLAB',
      color: '#fff',
      vertices: sq(0, 0, 10),
      holes: [sq(2, 2, 2), sq(6, 6, 1)],
    };
    const [row] = quantifyByLayer([hatch]);
    expect(row!.area).toBeCloseTo(100 - 4 - 1, 6);
  });

  it('adds every filled loop of a hatch drawn over separate slabs', () => {
    const sq = (x: number, y: number, s: number) => [
      { x, y },
      { x: x + s, y },
      { x: x + s, y: y + s },
      { x, y: y + s },
    ];
    const hatch: DxfEntity = {
      id: 'h2',
      type: 'HATCH',
      layer: 'SLAB',
      color: '#fff',
      vertices: sq(0, 0, 6),
      extra_loops: [sq(10, 0, 4)],
      holes: [sq(1, 1, 2)],
    };
    const [row] = quantifyByLayer([hatch]);
    expect(row!.area).toBeCloseTo(36 + 16 - 4, 6);
  });

  it('picks LENGTH for line-only layers', () => {
    const [row] = quantifyByLayer([line('l1', 'PIPE', 3), line('l2', 'PIPE', 7)]);
    expect(row!.primary).toBe('length');
    expect(row!.length).toBeCloseTo(10, 3);
    expect(row!.unit).toBe('m');
    expect(row!.count).toBe(2);
    expect(row!.available).not.toContain('area');
  });

  it('falls back to COUNT for block/symbol layers with no measurable geometry', () => {
    const [row] = quantifyByLayer([insert('i1', 'DOORS', 'DOOR'), insert('i2', 'DOORS', 'DOOR')]);
    expect(row!.primary).toBe('count');
    expect(row!.quantity).toBe(2);
    expect(row!.unit).toBe('nr');
    expect(row!.available).toEqual(['count']);
  });

  it('measures ARC entities by arc length (r × sweep)', () => {
    // Quarter circle, r = 4 -> length = 4 × (π/2) = 2π.
    const [row] = quantifyByLayer([arc('a1', 'EDGE', 4, 0, Math.PI / 2)]);
    expect(row!.primary).toBe('length');
    expect(row!.length).toBeCloseTo(2 * Math.PI, 3);
  });

  it('sums CIRCLE area as π·r²', () => {
    const [row] = quantifyByLayer([circle('c1', 'COL', 2)]);
    expect(row!.primary).toBe('area');
    expect(row!.area).toBeCloseTo(Math.PI * 4, 3);
  });

  it('groups entities by layer into separate rows', () => {
    const rows = quantifyByLayer([
      rect('r1', 'SLAB', 10, 10), // area 100
      line('l1', 'PIPE', 5), // length 5
      insert('i1', 'DOORS', 'DOOR'), // count
    ]);
    expect(rows).toHaveLength(3);
    const byLayer = Object.fromEntries(rows.map((r) => [r.layer, r]));
    expect(byLayer.SLAB!.primary).toBe('area');
    expect(byLayer.PIPE!.primary).toBe('length');
    expect(byLayer.DOORS!.primary).toBe('count');
  });

  it('sorts area layers before length before count', () => {
    const rows = quantifyByLayer([
      insert('i1', 'DOORS', 'DOOR'),
      line('l1', 'PIPE', 5),
      rect('r1', 'SLAB', 10, 10),
    ]);
    expect(rows.map((r) => r.primary)).toEqual(['area', 'length', 'count']);
  });

  it('offers both measures for a layer that mixes closed and open geometry', () => {
    const rows = quantifyByLayer([rect('r1', 'MIX', 10, 5), line('l1', 'MIX', 4)]);
    expect(rows).toHaveLength(1);
    const row = rows[0]!;
    expect(row.available).toContain('area');
    expect(row.available).toContain('length');
    expect(row.primary).toBe('area'); // area wins the headline
    expect(quantityFor(row, 'length')).toBeCloseTo(4, 3);
    expect(quantityFor(row, 'area')).toBeCloseTo(50, 3);
  });

  it('converts millimetre drawings to metres (linear × scale, area × scale²)', () => {
    const [row] = quantifyByLayer([rect('r1', 'SLAB', 10_000, 5_000)], 0.001);
    expect(row!.area).toBeCloseTo(50, 3); // 50e6 mm² × 1e-6
  });
});

describe('unitForMeasure', () => {
  it('maps measures to construction units', () => {
    expect(unitForMeasure('area')).toBe('m²');
    expect(unitForMeasure('length')).toBe('m');
    expect(unitForMeasure('count')).toBe('nr');
  });
});
