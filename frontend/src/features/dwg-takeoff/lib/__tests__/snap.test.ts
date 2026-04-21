/**
 * Unit tests for snap candidate finder (Q1 UX #4).
 */

import { describe, it, expect } from 'vitest';
import {
  closestSnapCandidate,
  collectSnapCandidates,
  type SnapModes,
} from '../snap';
import type { DxfEntity } from '../../api';

function makeLine(id: string, from: [number, number], to: [number, number]): DxfEntity {
  return {
    id,
    type: 'LINE',
    layer: '0',
    color: '#fff',
    start: { x: from[0], y: from[1] },
    end: { x: to[0], y: to[1] },
  };
}

function makePolyline(
  id: string,
  verts: Array<[number, number]>,
  closed = false,
): DxfEntity {
  return {
    id,
    type: 'LWPOLYLINE',
    layer: '0',
    color: '#fff',
    vertices: verts.map(([x, y]) => ({ x, y })),
    closed,
  };
}

const BOTH: SnapModes = { endpoint: true, midpoint: true };
const ONLY_ENDPOINT: SnapModes = { endpoint: true, midpoint: false };
const ONLY_MIDPOINT: SnapModes = { endpoint: false, midpoint: true };
const NONE: SnapModes = { endpoint: false, midpoint: false };

describe('collectSnapCandidates', () => {
  it('returns empty list when no modes enabled', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    expect(collectSnapCandidates([l], NONE)).toEqual([]);
  });

  it('LINE: 2 endpoints + 1 midpoint when both modes enabled', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], BOTH);
    expect(cs).toHaveLength(3);
    expect(cs.filter((c) => c.kind === 'endpoint')).toHaveLength(2);
    expect(cs.filter((c) => c.kind === 'midpoint')).toHaveLength(1);
    // Midpoint is halfway.
    const mid = cs.find((c) => c.kind === 'midpoint')!;
    expect(mid.point).toEqual({ x: 5, y: 0 });
  });

  it('LINE: endpoint-only skips midpoints', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    expect(collectSnapCandidates([l], ONLY_ENDPOINT)).toHaveLength(2);
  });

  it('LINE: midpoint-only skips endpoints', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], ONLY_MIDPOINT);
    expect(cs).toHaveLength(1);
    expect(cs[0]!.kind).toBe('midpoint');
  });

  it('LWPOLYLINE open: 3 vertices → 3 endpoints + 2 midpoints', () => {
    const p = makePolyline('p1', [[0, 0], [10, 0], [10, 10]], false);
    const cs = collectSnapCandidates([p], BOTH);
    const eps = cs.filter((c) => c.kind === 'endpoint');
    const mids = cs.filter((c) => c.kind === 'midpoint');
    expect(eps).toHaveLength(3);
    expect(mids).toHaveLength(2);
    // Midpoints are of the two segments.
    expect(mids.map((m) => m.point).sort((a, b) => a.x - b.x + (a.y - b.y) * 0.001)).toEqual([
      { x: 5, y: 0 },
      { x: 10, y: 5 },
    ]);
  });

  it('LWPOLYLINE closed: also includes the wrap-around midpoint', () => {
    const p = makePolyline('p1', [[0, 0], [10, 0], [10, 10], [0, 10]], true);
    const cs = collectSnapCandidates([p], ONLY_MIDPOINT);
    // Closed 4-vert polygon has 4 edges → 4 midpoints.
    expect(cs).toHaveLength(4);
  });

  it('mixes entities: line + polyline combined', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const p = makePolyline('p1', [[20, 0], [20, 20]]);
    const cs = collectSnapCandidates([l, p], ONLY_ENDPOINT);
    expect(cs).toHaveLength(4);
    expect(cs.map((c) => c.entityId).sort()).toEqual(['l1', 'l1', 'p1', 'p1']);
  });
});

describe('closestSnapCandidate', () => {
  it('returns null when no candidate falls within tolerance', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], BOTH);
    expect(closestSnapCandidate(cs, { x: 100, y: 100 }, 5)).toBeNull();
  });

  it('returns the nearest candidate within tolerance', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], BOTH);
    // Cursor at (0.2, 0.2) — nearest is the start endpoint.
    const hit = closestSnapCandidate(cs, { x: 0.2, y: 0.2 }, 2);
    expect(hit).not.toBeNull();
    expect(hit!.point).toEqual({ x: 0, y: 0 });
    expect(hit!.kind).toBe('endpoint');
  });

  it('chooses the midpoint when closer than either endpoint', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], BOTH);
    const hit = closestSnapCandidate(cs, { x: 5, y: 0.1 }, 2);
    expect(hit).not.toBeNull();
    expect(hit!.kind).toBe('midpoint');
  });

  it('endpoint wins over midpoint on a tie (priority ranking)', () => {
    // Construct a pathological case where endpoint & midpoint are equidistant.
    // Line from (0,0) to (10,0). Put a second tiny line whose endpoint
    // coincides exactly with the midpoint's distance from the cursor.
    const l1 = makeLine('l1', [0, 0], [10, 0]); // midpoint (5, 0)
    // Endpoint (5, 1) — distance 1 from cursor (5,0).
    const l2 = makeLine('l2', [5, 1], [5, 10]);
    const cs = collectSnapCandidates([l1, l2], BOTH);
    // Cursor at (5, 0) — midpoint of l1 is 0-dist; endpoint of l2 is 1.
    const hit = closestSnapCandidate(cs, { x: 5, y: 0 }, 5);
    expect(hit).not.toBeNull();
    // Midpoint of l1 wins on pure distance (0 < 1).
    expect(hit!.kind).toBe('midpoint');

    // Now move the cursor to make them equidistant.
    const hit2 = closestSnapCandidate(cs, { x: 5, y: 0.5 }, 5);
    // Midpoint distance = 0.5, endpoint distance = 0.5 → endpoint wins on priority.
    expect(hit2).not.toBeNull();
    expect(hit2!.kind).toBe('endpoint');
  });

  it('tolerance gate: excludes candidates past the threshold', () => {
    const l = makeLine('l1', [0, 0], [10, 0]);
    const cs = collectSnapCandidates([l], BOTH);
    // Cursor at (0, 3) with tolerance 2 → endpoint (0,0) is 3 away, out of range.
    expect(closestSnapCandidate(cs, { x: 0, y: 3 }, 2)).toBeNull();
  });
});
