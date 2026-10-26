// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  circlePolygon,
  fenceRing,
  haversineM,
  pointInPolygon,
  previewPoint,
  radiusFromEdge,
  type FenceShape,
  type LatLng,
} from './geometry';

const SQUARE: LatLng[] = [
  [52.0, 13.0],
  [52.0, 13.01],
  [52.01, 13.01],
  [52.01, 13.0],
];

describe('geometry', () => {
  it('haversine of one degree of latitude is about 111 km', () => {
    expect(haversineM([0, 0], [1, 0])).toBeGreaterThan(110_000);
    expect(haversineM([0, 0], [1, 0])).toBeLessThan(112_000);
  });

  it('circle ring is closed and every vertex sits at the radius', () => {
    const ring = circlePolygon([52, 13], 100);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    for (const [lng, lat] of ring) expect(haversineM([52, 13], [lat, lng])).toBeCloseTo(100, -1);
  });

  it('point in polygon', () => {
    expect(pointInPolygon([52.005, 13.005], SQUARE)).toBe(true);
    expect(pointInPolygon([52.02, 13.005], SQUARE)).toBe(false);
    expect(pointInPolygon([52.005, 13.005], SQUARE.slice(0, 2))).toBe(false);
  });

  it('circle preview honours tolerance', () => {
    const fence: FenceShape = {
      shape: 'circle', center_lat: 52, center_lng: 13, radius_m: 100, polygon: [], tolerance_m: 20,
    };
    expect(previewPoint([52, 13], fence)).toEqual({ inside: true, distance_m: 0 });
    const at110 = previewPoint([52 + 110 / 111195, 13], fence)!;
    expect(at110.inside).toBe(true);
    const at300 = previewPoint([52 + 300 / 111195, 13], fence)!;
    expect(at300.inside).toBe(false);
    expect(at300.distance_m).toBeGreaterThan(190);
  });

  it('polygon preview reports distance to the edge', () => {
    const fence: FenceShape = {
      shape: 'polygon', center_lat: null, center_lng: null, radius_m: null, polygon: SQUARE, tolerance_m: 0,
    };
    expect(previewPoint([52.005, 13.005], fence)!.inside).toBe(true);
    const out = previewPoint([52.011, 13.005], fence)!;
    expect(out.inside).toBe(false);
    expect(out.distance_m).toBeGreaterThan(100);
    expect(out.distance_m).toBeLessThan(120);
  });

  it('incomplete fences give no ring and no preview', () => {
    const fence: FenceShape = {
      shape: 'polygon', center_lat: null, center_lng: null, radius_m: null, polygon: [[1, 1]], tolerance_m: 0,
    };
    expect(fenceRing(fence)).toBeNull();
    expect(previewPoint([0, 0], fence)).toBeNull();
  });

  it('radiusFromEdge is at least 1 m', () => {
    expect(radiusFromEdge([52, 13], [52, 13])).toBe(1);
  });
});
