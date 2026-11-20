// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { extentOf, misclosureScale, traverseSketch } from './traverseSketch';

const SQ = [
  { station_id: 'A', e: 0, n: 0 },
  { station_id: 'B', e: 100, n: 0 },
  { station_id: 'C', e: 100, n: 100 },
  { station_id: 'D', e: 0, n: 100 },
];

describe('traverse sketch', () => {
  it('scales a 5.8 mm misclosure on a 170 m loop by a round power of ten', () => {
    // Riverside loop: f = 0.0058 m, extent about 170 m: 0.06 x 170 / 0.0058 = 1759 -> x1000.
    expect(misclosureScale(0.0058, 170)).toBe(1000);
    expect(misclosureScale(0.05, 170)).toBe(100);
    expect(misclosureScale(20, 170)).toBe(1);
    expect(misclosureScale(0, 170)).toBe(1);
  });

  it('draws raw legs to the computed end, adjusted legs closed, and the vector', () => {
    const computedEnd = { station_id: 'A', e: 0.003, n: -0.004 };
    const s = traverseSketch({ shape: 'loop', unadjusted: SQ, adjusted: SQ, computedEnd, fixedEnd: SQ[0]! });
    expect(extentOf(SQ)).toBe(100);
    expect(s.misclosure).toBeCloseTo(0.005, 12);
    expect(s.scale).toBe(1000);
    const roles = s.features.map((f) => f.properties.role);
    expect(roles.filter((r) => r === 'raw')).toHaveLength(4);
    expect(roles.filter((r) => r === 'adjusted')).toHaveLength(4);
    expect(roles.filter((r) => r === 'station')).toHaveLength(4);
    const v = s.features.find((f) => f.properties.role === 'misclosure')!;
    expect(v.geometry).toEqual({ type: 'LineString', coordinates: [[0.003, -0.004], [-2.997, 3.996]] });
    expect(v.properties.label).toBe('x1000');
  });

  it('closes a link on the fixed end and skips the vector when it closes exactly', () => {
    const end = { station_id: 'E', e: 200, n: 0 };
    const s = traverseSketch({ shape: 'link', unadjusted: SQ.slice(0, 2), adjusted: SQ.slice(0, 2), computedEnd: end, fixedEnd: end });
    const adj = s.features.filter((f) => f.properties.role === 'adjusted');
    expect(adj[adj.length - 1]!.geometry).toEqual({ type: 'LineString', coordinates: [[100, 0], [200, 0]] });
    expect(s.features.some((f) => f.properties.role === 'misclosure')).toBe(false);
  });
});
