/**
 * Unit tests for the group aggregation helper (RFC 11 §4.5).
 *
 * Verifies Σ area / Σ perimeter / Σ length across a heterogeneous set
 * of entities — the primary contract consumed by the right-panel
 * group aggregation UI and by ``handleLinkGroupToPosition``.
 */

import { describe, it, expect } from 'vitest';
import { aggregateEntities } from '../lib/group-aggregation';
import type { DxfEntity } from '../api';

/* ── Entity factories ────────────────────────────────────────────────── */

function rect(id: string, width: number, height: number, closed = true): DxfEntity {
  return {
    id,
    type: 'LWPOLYLINE',
    layer: '0',
    color: '#ffffff',
    vertices: [
      { x: 0, y: 0 },
      { x: width, y: 0 },
      { x: width, y: height },
      { x: 0, y: height },
    ],
    closed,
  };
}

function line(id: string, length: number): DxfEntity {
  return {
    id,
    type: 'LINE',
    layer: '0',
    color: '#ffffff',
    start: { x: 0, y: 0 },
    end: { x: length, y: 0 },
  };
}

function circle(id: string, radius: number): DxfEntity {
  return {
    id,
    type: 'CIRCLE',
    layer: '0',
    color: '#ffffff',
    start: { x: 0, y: 0 },
    radius,
  };
}

function text(id: string): DxfEntity {
  return {
    id,
    type: 'TEXT',
    layer: '0',
    color: '#ffffff',
    start: { x: 0, y: 0 },
    text: 'hello',
  };
}

/* ── Tests ───────────────────────────────────────────────────────────── */

describe('aggregateEntities — RFC 11 §4.5', () => {
  it('returns the empty aggregate for an empty selection', () => {
    const agg = aggregateEntities([]);
    expect(agg.area).toBe(0);
    expect(agg.perimeter).toBe(0);
    expect(agg.length).toBe(0);
    expect(agg.count).toBe(0);
    expect(agg.byType).toEqual({});
  });

  it('sums area + perimeter for closed polylines', () => {
    const agg = aggregateEntities([rect('r1', 10, 5), rect('r2', 4, 4)]);
    // Areas: 10·5 + 4·4 = 50 + 16 = 66
    expect(agg.area).toBeCloseTo(66, 3);
    // Perimeters: 2·(10+5) + 2·(4+4) = 30 + 16 = 46
    expect(agg.perimeter).toBeCloseTo(46, 3);
    expect(agg.length).toBe(0);
    expect(agg.count).toBe(2);
    expect(agg.byType).toEqual({ LWPOLYLINE: 2 });
  });

  it('counts open polylines into length, not area/perimeter', () => {
    const agg = aggregateEntities([rect('r1', 10, 5, /*closed=*/ false)]);
    // Open polyline perimeter (segment sum of 3 edges, no closing): 10+5+10 = 25
    expect(agg.length).toBeCloseTo(25, 3);
    expect(agg.area).toBe(0);
    expect(agg.perimeter).toBe(0);
    expect(agg.count).toBe(1);
  });

  it('sums LINE lengths', () => {
    const agg = aggregateEntities([line('l1', 3), line('l2', 7)]);
    expect(agg.length).toBeCloseTo(10, 3);
    expect(agg.area).toBe(0);
    expect(agg.count).toBe(2);
    expect(agg.byType).toEqual({ LINE: 2 });
  });

  it('sums CIRCLE areas as π·r²', () => {
    const agg = aggregateEntities([circle('c1', 2)]);
    expect(agg.area).toBeCloseTo(Math.PI * 4, 3);
    expect(agg.perimeter).toBe(0);
    expect(agg.length).toBe(0);
    expect(agg.count).toBe(1);
  });

  it('handles a heterogeneous selection correctly', () => {
    const agg = aggregateEntities([
      rect('r1', 10, 5),          // area 50, perimeter 30
      line('l1', 4),              // length 4
      circle('c1', 1),            // area π
      text('t1'),                 // counted in byType only
    ]);
    expect(agg.area).toBeCloseTo(50 + Math.PI, 3);
    expect(agg.perimeter).toBeCloseTo(30, 3);
    expect(agg.length).toBeCloseTo(4, 3);
    expect(agg.count).toBe(3); // text is not counted in ``count``
    expect(agg.byType).toEqual({
      LWPOLYLINE: 1,
      LINE: 1,
      CIRCLE: 1,
      TEXT: 1,
    });
  });

  it('rounds to millimetre precision so UI does not flicker', () => {
    const agg = aggregateEntities([rect('r1', 10 / 3, 10 / 3)]);
    // 10/3 × 10/3 ≈ 11.111111…  should round to 11.111
    expect(agg.area).toBeCloseTo(11.111, 3);
    // No more than three decimal places survive.
    expect(Math.round(agg.area * 1000)).toBe(agg.area * 1000);
  });
});
