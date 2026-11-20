import { describe, expect, it } from 'vitest';
import {
  EARTH_RADIUS_M,
  MAX_PLOT_AREA_M2,
  areaM2,
  bounds,
  closeRing,
  distanceM,
  fromPolygon,
  isCounterClockwise,
  openRing,
  perimeterM,
  plotProblem,
  selfIntersects,
  toCounterClockwise,
  toPolygon,
  wrapLon,
  type LngLat,
} from './polygon';

// The example plot of the contract: 0.000575° × 0.000162° at 51.34° N.
const PLOT: LngLat[] = [[12.37, 51.34], [12.370575, 51.34], [12.370575, 51.340162], [12.37, 51.340162]];
const M_PER_DEG = (Math.PI / 180) * EARTH_RADIUS_M;

describe('rings', () => {
  it('opens and closes, dropping repeated vertices', () => {
    expect(openRing([[0, 0], [0, 0], [1, 0], [1, 1], [0, 0]])).toEqual([[0, 0], [1, 0], [1, 1]]);
    expect(closeRing([[0, 0], [1, 0], [1, 1]])).toEqual([[0, 0], [1, 0], [1, 1], [0, 0]]);
    expect(closeRing([])).toEqual([]);
  });

  it('knows and fixes the winding', () => {
    expect(isCounterClockwise(PLOT)).toBe(true);
    const cw = [...PLOT].reverse();
    expect(isCounterClockwise(cw)).toBe(false);
    const fixed = toCounterClockwise(cw);
    expect(isCounterClockwise(fixed)).toBe(true);
    expect(fixed[0]).toEqual(cw[0]); // starts where the person started
  });
});

describe('measures', () => {
  it('area of the example plot matches width × depth on the sphere', () => {
    const width = 0.000575 * M_PER_DEG * Math.cos((51.34 * Math.PI) / 180);
    const depth = 0.000162 * M_PER_DEG;
    expect(areaM2(PLOT)).toBeCloseTo(width * depth, 0);
    expect(areaM2(PLOT)).toBeGreaterThan(715);
    expect(areaM2(PLOT)).toBeLessThan(725);
    expect(areaM2([...PLOT].reverse())).toBeCloseTo(areaM2(PLOT), 6);
  });

  it('area of a 1° cell at the equator', () => {
    const cell: LngLat[] = [[0, 0], [1, 0], [1, 1], [0, 1]];
    // Exact spherical cell: R² · Δλ · (sin φ2 − sin φ1).
    const exact = EARTH_RADIUS_M ** 2 * (Math.PI / 180) * Math.sin(Math.PI / 180);
    expect(areaM2(cell) / exact).toBeCloseTo(1, 9);
  });

  it('perimeter and distance', () => {
    expect(distanceM([0, 0], [0, 1])).toBeCloseTo(M_PER_DEG, 3);
    const width = distanceM(PLOT[0]!, PLOT[1]!);
    const depth = distanceM(PLOT[1]!, PLOT[2]!);
    expect(perimeterM(PLOT)).toBeCloseTo(width * 2 + depth * 2, 1);
    expect(perimeterM(closeRing(PLOT))).toBeCloseTo(perimeterM(PLOT), 9);
  });

  it('bounds', () => {
    expect(bounds(PLOT)).toEqual([12.37, 51.34, 12.370575, 51.340162]);
    expect(bounds([])).toBeNull();
  });
});

describe('validity', () => {
  it('finds crossing edges', () => {
    expect(selfIntersects([[0, 0], [1, 1], [1, 0], [0, 1]])).toBe(true); // bow tie
    expect(selfIntersects(PLOT)).toBe(false);
    expect(selfIntersects([[0, 0], [2, 0], [2, 2], [1, 0], [0, 2]])).toBe(true); // vertex touches an edge
  });

  it('names the problem', () => {
    expect(plotProblem(PLOT)).toBeNull();
    expect(plotProblem([[0, 0], [1, 0]])).toBe('too_few_points');
    expect(plotProblem([[0, 0], [1, 0], [2, 0]])).toBe('degenerate'); // collinear: enough corners, no area
    expect(plotProblem([[0, 0], [1, 1], [1, 0], [0, 1]])).toBe('self_intersecting');
    expect(plotProblem([[0, 0], [181, 0], [0, 1]])).toBe('out_of_range');
  });
});

describe('GeoJSON', () => {
  it('stores a closed counter-clockwise ring rounded to about a centimetre', () => {
    const drawn: LngLat[] = [[12.37000001234, 51.34], [12.37, 51.340162], [12.370575, 51.340162], [12.370575, 51.34]];
    const poly = toPolygon(drawn);
    expect(poly.type).toBe('Polygon');
    const ring = poly.coordinates[0]! as LngLat[];
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    expect(ring).toHaveLength(5);
    expect(isCounterClockwise(ring)).toBe(true);
    expect(ring[0]).toEqual([12.37, 51.34]);
  });

  it('round-trips the outline and keeps holes', () => {
    const hole = [[12.3701, 51.34005], [12.3701, 51.3401], [12.3702, 51.3401], [12.3701, 51.34005]];
    const stored = { type: 'Polygon' as const, coordinates: [closeRing(PLOT), hole] };
    const outline = fromPolygon(stored);
    expect(outline).toEqual(PLOT);
    expect(toPolygon(outline, stored)).toEqual(stored);
    expect(fromPolygon(null)).toEqual([]);
  });
});

describe('wrapLon and plot size', () => {
  it('wraps longitudes of repeated world copies into [-180, 180]', () => {
    expect(wrapLon(190)).toBeCloseTo(-170);
    expect(wrapLon(-190)).toBeCloseTo(170);
    expect(wrapLon(540.5)).toBeCloseTo(-179.5);
    expect(wrapLon(13.4)).toBe(13.4);
  });
  it('refuses a plot above the bound and accepts one just below', () => {
    expect(MAX_PLOT_AREA_M2).toBe(100e6);
    expect(plotProblem([[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]])).toBe('too_large'); // ~3000 km2
    expect(plotProblem([[0, 0], [0.05, 0], [0.05, 0.05], [0, 0.05]])).toBeNull(); // ~30 km2
  });
});
