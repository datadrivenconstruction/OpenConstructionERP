// UI QA: plot geometry against an independent computation (unit vectors on the sphere, no shared code).
import { describe, expect, it } from 'vitest';
import { areaM2, perimeterM, plotProblem, selfIntersects, type LngLat } from '../data/polygon';

const R = 6371008.8;
const rad = (d: number) => (d * Math.PI) / 180;
const vec = ([lon, lat]: LngLat) => [Math.cos(rad(lat)) * Math.cos(rad(lon)), Math.cos(rad(lat)) * Math.sin(rad(lon)), Math.sin(rad(lat))];
const dot = (a: number[], b: number[]) => a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;
const cross = (a: number[], b: number[]) => [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];

/** Great-circle edges; area by summing signed solid angles of triangles (pole, a, b). */
function refArea(ring: LngLat[]): number {
  const p = [0, 0, 1];
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = vec(ring[i]!);
    const b = vec(ring[(i + 1) % ring.length]!);
    const num = dot(p, cross(a, b));
    const den = 1 + dot(p, a) + dot(a, b) + dot(b, p);
    sum += 2 * Math.atan2(num, den);
  }
  return Math.abs(sum) * R * R;
}
function refPerimeter(ring: LngLat[]): number {
  let s = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = vec(ring[i]!);
    const b = vec(ring[(i + 1) % ring.length]!);
    const c = cross(a, b);
    s += Math.atan2(Math.hypot(c[0]!, c[1]!, c[2]!), dot(a, b)) * R;
  }
  return s;
}
const box = (lon: number, lat: number, dLon: number, dLat: number): LngLat[] => [
  [lon, lat], [lon + dLon, lat], [lon + dLon, lat + dLat], [lon, lat + dLat],
];

describe('plot measures vs independent computation', () => {
  for (const [name, ring, tol] of [
    ['100 m plot at 52N', box(13.4, 52.5, 0.0015, 0.0009), 1e-4],
    ['plot at 80N', box(10, 80, 0.01, 0.0009), 1e-4],
    ['1 degree block at 60N', box(30, 60, 1, 1), 5e-3],
  ] as const) {
    it(`area ${name}`, () => {
      expect(Math.abs(areaM2(ring) / refArea(ring) - 1)).toBeLessThan(tol);
    });
    it(`perimeter ${name}`, () => {
      expect(Math.abs(perimeterM(ring) / refPerimeter(ring) - 1)).toBeLessThan(tol);
    });
  }
});

describe('plot across the antimeridian (Fiji, Chukotka)', () => {
  // ~222 m square straddling 180: stored as lon 179.999 .. -179.999 (RFC 7946 section 3.1.9 cuts or wraps).
  const ring: LngLat[] = [[179.999, -17], [-179.999, -17], [-179.999, -16.998], [179.999, -16.998]];
  it('area is that of the small square, not of a band around the globe', () => {
    expect(Math.abs(areaM2(ring) / refArea(ring) - 1)).toBeLessThan(1e-3);
  });
  it('is not reported as self-intersecting', () => {
    expect(selfIntersects(ring)).toBe(false);
    expect(plotProblem(ring)).toBeNull();
  });
  it('perimeter is that of the small square', () => {
    expect(Math.abs(perimeterM(ring) / refPerimeter(ring) - 1)).toBeLessThan(1e-3);
  });
});

describe('degenerate outlines', () => {
  it('three collinear points are not called "too few points"', () => {
    expect(plotProblem([[10, 50], [10.001, 50], [10.002, 50]])).not.toBe('too_few_points');
  });
  it('a plot larger than the Earth surface fraction a person could mean is refused', () => {
    // 90 x 90 degree "plot" (about 8e13 m2): a typo for 0.0009, not a building site.
    expect(plotProblem(box(0, 0, 90, 90))).not.toBeNull();
  });
});
