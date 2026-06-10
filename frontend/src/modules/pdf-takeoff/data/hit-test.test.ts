// OpenConstructionERP — DataDrivenConstruction (DDC)
// CAD2DATA Pipeline · PDF Takeoff in-canvas editing — unit tests (#194)
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
import { describe, expect, it } from 'vitest';
import {
  hitTest,
  insertVertexAt,
  deleteVertexAt,
  translatePoints,
  recomputeMeasurement,
  supportsVariableVertices,
  minVertices,
  GRAB_PX,
  type EditableMeasurement,
  type Point,
} from './hit-test';
import { presetScale } from './scale-helpers';

const square: Point[] = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

const areaM = (points: Point[]): EditableMeasurement => ({ type: 'area', points });
const distanceM = (points: Point[]): EditableMeasurement => ({ type: 'distance', points });

describe('hitTest priority', () => {
  it('returns a vertex hit when the pointer is on a corner', () => {
    const hit = hitTest({ x: 1, y: 1 }, areaM(square), 1, true);
    expect(hit).toEqual({ kind: 'vertex', index: 0 });
  });

  it('prefers a vertex over the edge it sits on', () => {
    // Right on vertex 1 (100,0) which is also on edges 0 and 1.
    const hit = hitTest({ x: 100, y: 0 }, areaM(square), 1, true);
    expect(hit?.kind).toBe('vertex');
    expect(hit?.index).toBe(1);
  });

  it('returns an edge-midpoint hit only when selected', () => {
    const mid = { x: 50, y: 0 }; // midpoint of edge 0 (0,0)->(100,0)
    const selected = hitTest(mid, areaM(square), 1, true);
    expect(selected).toEqual({ kind: 'edge', index: 0 });
    const unselected = hitTest(mid, areaM(square), 1, false);
    // Not an edge-add when unselected, but still a body (on the line).
    expect(unselected?.kind).toBe('body');
  });

  it('returns a body hit on the polygon interior', () => {
    const hit = hitTest({ x: 50, y: 50 }, areaM(square), 1, false);
    expect(hit?.kind).toBe('body');
  });

  it('returns null when the pointer is far outside', () => {
    expect(hitTest({ x: 500, y: 500 }, areaM(square), 1, true)).toBeNull();
  });
});

describe('hitTest tolerance is zoom-invariant (no dpr leakage)', () => {
  // The grab radius must stay constant in SCREEN pixels at any zoom: a
  // pointer GRAB_PX/zoom away in PDF units is exactly on the screen-grab
  // boundary, so a hair inside hits and a hair outside misses, identically
  // at every zoom.
  for (const zoom of [0.5, 1, 4]) {
    it(`grab radius is GRAB_PX screen px at zoom ${zoom}`, () => {
      const tolPdf = GRAB_PX / zoom;
      const onLine = { x: 50, y: tolPdf * 0.9 }; // inside the edge tolerance
      const offLine = { x: 50, y: tolPdf * 1.5 }; // outside it
      // Use an open distance so only the edge body can match (no interior).
      const seg = distanceM([
        { x: 0, y: 0 },
        { x: 100, y: 0 },
      ]);
      expect(hitTest(onLine, seg, zoom, false)?.kind).toBe('body');
      expect(hitTest(offLine, seg, zoom, false)).toBeNull();
    });
  }
});

describe('vertex add / delete', () => {
  it('inserts a vertex at the segment midpoint after the edge index', () => {
    const grown = insertVertexAt(square, 0);
    expect(grown).toHaveLength(5);
    expect(grown[1]).toEqual({ x: 50, y: 0 });
  });

  it('removes the vertex at the given index', () => {
    const shrunk = deleteVertexAt(square, 1);
    expect(shrunk).toHaveLength(3);
    expect(shrunk).not.toContainEqual({ x: 100, y: 0 });
  });

  it('reports the correct minimum vertices per type', () => {
    expect(minVertices('area')).toBe(3);
    expect(minVertices('volume')).toBe(3);
    expect(minVertices('polyline')).toBe(2);
    expect(minVertices('distance')).toBe(2);
    expect(minVertices('count')).toBe(1);
  });

  it('knows which types support variable vertices', () => {
    expect(supportsVariableVertices('area')).toBe(true);
    expect(supportsVariableVertices('polyline')).toBe(true);
    expect(supportsVariableVertices('distance')).toBe(false);
    expect(supportsVariableVertices('count')).toBe(false);
  });
});

describe('translatePoints', () => {
  it('shifts every point by the delta', () => {
    const moved = translatePoints(square, 10, -5);
    expect(moved[0]).toEqual({ x: 10, y: -5 });
    expect(moved[2]).toEqual({ x: 110, y: 95 });
  });
});

describe('recomputeMeasurement parity with create-time math', () => {
  const scale = presetScale(50); // 1:50

  it('distance equals toRealDistance of the pixel length', () => {
    const m = distanceM([
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ]);
    const patch = recomputeMeasurement(m, m.points, scale);
    // pixelsPerUnit at 1:50 => 100px / ppu metres.
    const expected = 100 / scale.pixelsPerUnit;
    expect(patch.value).toBeCloseTo(expected, 6);
    expect(patch.unit).toBe('m');
  });

  it('area emits the pinned "(P: ...)" perimeter label and the m2 unit', () => {
    const patch = recomputeMeasurement(areaM(square), square, scale);
    expect(patch.unit).toBe('m²');
    expect(patch.label).toContain('(P:');
    // 100x100 px square => 10000 px2 / ppu^2 metres2.
    const expected = 10000 / scale.pixelsPerUnit ** 2;
    expect(patch.value).toBeCloseTo(expected, 6);
    expect(patch.selfIntersecting).toBe(false);
  });

  it('volume keeps depth and emits the pinned "V = ..." label', () => {
    const m: EditableMeasurement = { type: 'volume', points: square, depth: 3 };
    const patch = recomputeMeasurement(m, square, scale);
    expect(patch.unit).toBe('m³');
    expect(patch.label.startsWith('V = ')).toBe(true);
    expect(patch.depth).toBe(3);
    const area = 10000 / scale.pixelsPerUnit ** 2;
    expect(patch.area).toBeCloseTo(area, 6);
    expect(patch.value).toBeCloseTo(area * 3, 6);
  });

  it('count equals the dot count', () => {
    const m: EditableMeasurement = {
      type: 'count',
      points: [
        { x: 0, y: 0 },
        { x: 10, y: 10 },
        { x: 20, y: 20 },
      ],
    };
    const patch = recomputeMeasurement(m, m.points, scale);
    expect(patch.value).toBe(3);
    expect(patch.unit).toBe('pcs');
  });

  it('flags a self-intersecting (bowtie) polygon during recompute', () => {
    // A classic bowtie quad.
    const bowtie: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 100 },
      { x: 100, y: 0 },
      { x: 0, y: 100 },
    ];
    const patch = recomputeMeasurement(areaM(bowtie), bowtie, scale);
    expect(patch.selfIntersecting).toBe(true);
  });
});
